"""The Spark agent. It picks what to fit, but every number and verdict comes from code."""
import json
import re
from typing import Callable

import numpy as np

from .laws import LAWS, Fit, Verdict, select_law
from .measure import Series, motion_window, quality_warnings
from .meta_api import MetaClient, function_calls, output_text

MAX_STEPS = 12

SYSTEM = """You are Gauge, a careful lab assistant. You work from a tracked object's measured position over time.
Use summarise_data, then fit_laws. Start from the auto-detected motion window and move away from it only if the data shows a reason. Exclude moments when a hand holds the object or it has landed.
Finish by calling report_finding with the fit_id of the fit you trust. Never state a number that did not come from a tool.
If the data is too poor to trust, say so in the explanation rather than forcing a result.
For next_run, give one concrete instruction for a second recording that would test this law under changed conditions, such as a new height or starting position.
Write plain sentences for a student. Round numbers to three significant figures, or leave them out, since the app shows exact values. Do not claim a level of trust beyond the data. Do not use em dashes."""

TOOLS = [
    {"type": "function", "name": "summarise_data",
     "description": "Sample count, duration, ranges, the auto-detected motion window and data quality warnings for one axis.",
     "parameters": {"type": "object", "properties": {"axis": {"type": "string", "enum": ["x", "y"]}},
                    "required": ["axis"]}},
    {"type": "function", "name": "fit_laws",
     "description": "Fit candidate laws to one axis over a time window and rank them by AICc, lowest best. Returns a fit_id for each.",
     "parameters": {"type": "object", "properties": {
         "axis": {"type": "string", "enum": ["x", "y"]},
         "t_start": {"type": "number", "description": "Window start in seconds."},
         "t_end": {"type": "number", "description": "Window end in seconds."},
         "laws": {"type": "array", "items": {"type": "string", "enum": list(LAWS)},
                  "description": "Optional subset of laws."}},
         "required": ["axis", "t_start", "t_end"]}},
    {"type": "function", "name": "report_finding",
     "description": "Finish the analysis.",
     "parameters": {"type": "object", "properties": {
         "fit_id": {"type": "string"},
         "quantity": {"type": "string", "description": "What the main constant means, such as acceleration due to gravity."},
         "parameter": {"type": "string", "description": "Which fitted parameter or derived value is the headline, such as a or period_s."},
         "explanation": {"type": "string", "description": "Two or three sentences on what was found and how far to trust it."},
         "next_run": {"type": "string"}},
         "required": ["fit_id", "quantity", "parameter", "explanation", "next_run"]}},
]


def parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0)) if match else {}


def read_setup(client: MetaClient, file_id: str, transcript: str) -> dict:
    """Ask Spark what the experiment is and pull any spoken reference length."""
    prompt = (
        "This is a recording of a physical experiment. Narration transcript: "
        f"{json.dumps(transcript)}. Reply with only JSON using keys: experiment (one short sentence), "
        "track (short noun phrase for the object to measure), reference (the object of known size, or null), "
        "reference_metres (its length in metres as stated in the narration, or null if not stated). "
        "Never guess a length."
    )
    res = client.spark([{"role": "user", "content": [
        {"type": "input_video", "file_id": file_id},
        {"type": "input_text", "text": prompt},
    ]}])
    return parse_json(output_text(res))


class Analysis:
    def __init__(self, series: Series, total_frames: int):
        self.series = series
        self.total_frames = total_frames
        self.fits: dict[str, tuple[Fit, str, float, float]] = {}

    def summarise_data(self, axis: str) -> dict:
        values = self.series.axis(axis)
        start, end = motion_window(self.series, axis)
        return {"samples": len(values), "duration_s": float(self.series.t[-1]),
                "range_m": float(values.max() - values.min()), "motion_window_s": [start, end],
                "warnings": quality_warnings(self.series, axis, self.total_frames)}

    def fit_laws(self, axis: str, t_start: float, t_end: float, laws: list[str] | None = None) -> dict:
        part = self.series.window(t_start, t_end)
        ranked = select_law(part.t - part.t[0], part.axis(axis), laws)
        if not ranked:
            return {"error": "no law could be fitted, widen the window"}
        results = []
        for fit in ranked:
            fit_id = f"fit{len(self.fits) + 1}"
            self.fits[fit_id] = (fit, axis, t_start, t_end)
            results.append({"fit_id": fit_id, **fit.to_dict()})
        return {"fits": results}


def _headline(fit: Fit, parameter: str) -> tuple[str, float, float | None]:
    if parameter in fit.derived:
        return parameter, fit.derived[parameter], None
    if parameter in fit.values:
        return parameter, fit.values[parameter], fit.errors[parameter]
    key = next(iter(fit.values))
    return key, fit.values[key], fit.errors[key]


def _history_items(response: dict) -> list[dict]:
    """Replay the turn in full, because stored response ids can expire mid-run."""
    items: list[dict] = []
    text = output_text(response)
    if text:
        items.append({"role": "assistant", "content": text})
    for call in function_calls(response):
        items.append({"type": "function_call", "call_id": call["call_id"], "name": call["name"],
                      "arguments": call["arguments"]})
    return items


def analyse(client: MetaClient, analysis: Analysis, context: str, emit: Callable[[dict], None]) -> dict:
    try:
        return _run_agent(client, analysis, context, emit)
    except RuntimeError as exc:
        emit({"kind": "error", "text": f"Agent stopped early: {str(exc)[:120]}"})
        return _fallback(analysis)


def _run_agent(client: MetaClient, analysis: Analysis, context: str, emit: Callable[[dict], None]) -> dict:
    history: list[dict] = [{"role": "user", "content": context}]
    nudged = False
    for _ in range(MAX_STEPS):
        response = client.spark(history, tools=TOOLS, instructions=SYSTEM, effort="medium")
        history += _history_items(response)
        calls = function_calls(response)
        if not calls:
            if nudged:
                break
            nudged = True
            history.append({"role": "user", "content": "Call report_finding now with the fit_id you trust."})
            continue
        outputs = []
        for call in calls:
            args = json.loads(call["arguments"])
            if call["name"] == "report_finding":
                entry = analysis.fits.get(args.get("fit_id"))
                if entry:
                    return _finding(args, entry, analysis)
                result = {"error": "unknown fit_id, use one returned by fit_laws"}
            elif call["name"] == "summarise_data":
                emit({"kind": "tool", "text": f"Checking the {args['axis']} data"})
                result = analysis.summarise_data(**args)
            else:
                emit({"kind": "tool", "text": f"Fitting laws to {args['axis']} from {args['t_start']:.2f} s to {args['t_end']:.2f} s"})
                result = analysis.fit_laws(**args)
                if "fits" in result:
                    top = result["fits"][0]
                    emit({"kind": "result", "text": f"Best fit: {top['law'].replace('_', ' ')}, R² {top['r2']:.4f}"})
            outputs.append({"type": "function_call_output", "call_id": call["call_id"],
                            "output": json.dumps(result)})
        history += outputs
    return _fallback(analysis)


def _finding(args: dict, entry: tuple, analysis: Analysis) -> dict:
    fit, axis, t_start, t_end = entry
    parameter, value, error = _headline(fit, args["parameter"])
    part = analysis.series.window(t_start, t_end)
    return {"fit": fit.to_dict(), "axis": axis, "window": [t_start, t_end], "quantity": args["quantity"],
            "parameter": parameter, "value": value, "error": error,
            "explanation": args["explanation"], "next_run": args["next_run"],
            "warnings": quality_warnings(part, axis, len(part.t))}


def _fallback(analysis: Analysis) -> dict:
    """If the agent never finishes, report the best deterministic fit rather than nothing."""
    axis = "y" if np.ptp(analysis.series.y) >= np.ptp(analysis.series.x) else "x"
    start, end = motion_window(analysis.series, axis)
    result = analysis.fit_laws(axis, start, end)
    if "fits" not in result:
        raise RuntimeError("no law could be fitted to this data")
    entry = analysis.fits[result["fits"][0]["fit_id"]]
    args = {"quantity": "best fitting constant", "parameter": "", "next_run": "Record the same motion again from a new starting position.",
            "explanation": "The agent did not finish, so this is the best automatic fit, which has not been reviewed."}
    return _finding(args, entry, analysis)


def explain_verdict(client: MetaClient, finding: dict, verdict: Verdict) -> str:
    prompt = (
        f"An experiment found {finding['quantity']}. A held-out second run was scored by code: {json.dumps(verdict.to_dict())}. "
        "In two plain sentences say what this means and, if it failed, the most likely experimental cause. "
        "Do not change or restate the pass or fail decision differently. Write numbers as digits with three significant figures. "
        "Only suggest causes that fit a video recording, not sensors. Do not use em dashes."
    )
    return output_text(client.spark([{"role": "user", "content": prompt}]))
