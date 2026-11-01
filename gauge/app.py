"""Gauge web server. Runs live in memory, which is fine for a single demo instance."""
import threading
import uuid
from dataclasses import dataclass, field
from math import hypot
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent
from .budget import BudgetExceeded, RateLimited, VisitorLimiter, default_ledger
from .laws import Fit, speed_factor, verify
from .measure import (Series, build_series, motion_window, clean_track, quality_warnings,
                      scale_from_reference, scale_uncertainty)
from .meta_api import MetaClient, point_prompt
from .timeslice import build as build_slice
from .video import Clip, extract_wav, nearest_frame, normalise

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "data" / "runs"
SAMPLES_DIR = ROOT / "samples"
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
LENGTH_PARAMETERS = {"a", "v", "v0", "amp"}

app = FastAPI(title="Gauge")
ledger = default_ledger()
limiter = VisitorLimiter(max_actions=12, window_seconds=3600)
client = MetaClient(ledger)


@dataclass
class Run:
    id: str
    clip: Clip
    file_id: str | None = None
    status: str = "reading"
    setup: dict = field(default_factory=dict)
    transcript: dict = field(default_factory=dict)
    track: list[dict] = field(default_factory=list)
    metres_per_px: float | None = None
    scale_error: float = 0.0
    series: Series | None = None
    events: list[dict] = field(default_factory=list)
    finding: dict | None = None
    fit: Fit | None = None
    verdict: dict | None = None
    error: str | None = None

    def emit(self, event: dict) -> None:
        self.events.append(event)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "status": self.status, "error": self.error, "setup": self.setup,
            "transcript": self.transcript.get("transcript", ""), "turns": self.transcript.get("turns", []),
            "width": self.clip.width, "height": self.clip.height, "frames": self.clip.frames,
            "duration": self.clip.duration, "times": self.clip.times, "video": f"/media/{self.id}",
            "track": self.track, "metres_per_px": self.metres_per_px,
            "series": self.series.to_dict() if self.series else None,
            "events": self.events, "finding": self.finding, "verdict": self.verdict,
        }


RUNS: dict[str, Run] = {}


class TrackRequest(BaseModel):
    t: float
    x: int
    y: int


class ReferenceRequest(BaseModel):
    p1: tuple[float, float]
    p2: tuple[float, float]
    metres: float


class VerifyRequest(BaseModel):
    against: str


def get_run(run_id: str) -> Run:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


def visitor_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else request.client.host


def spawn(run: Run, status: str, work) -> None:
    def target():
        try:
            work()
        except Exception as exc:
            run.error = str(exc)
            run.emit({"kind": "error", "text": str(exc)})
        finally:
            run.status = "idle"

    run.status = status
    run.error = None
    threading.Thread(target=target, daemon=True).start()


def read_run(run: Run) -> None:
    run.file_id = client.upload(run.clip.path)
    transcript = ""
    if run.clip.has_audio:
        wav = run.clip.path.with_suffix(".wav")
        extract_wav(run.clip.path, wav)
        run.transcript = client.transcribe(wav, run.clip.duration)
        transcript = run.transcript.get("transcript", "")
    run.setup = agent.read_setup(client, run.file_id, transcript)


@app.exception_handler(BudgetExceeded)
async def on_budget(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=402)


@app.exception_handler(RateLimited)
async def on_rate(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=429)


@app.post("/api/runs")
def create_run(request: Request, file: UploadFile = File(...)) -> dict:
    limiter.hit(visitor_id(request))
    if int(request.headers.get("content-length", 0)) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "video is larger than 300 MB")
    run_id = uuid.uuid4().hex
    folder = RUNS_DIR / run_id
    folder.mkdir(parents=True)
    source = folder / "source"
    with open(source, "wb") as handle:
        while chunk := file.file.read(1024 * 1024):
            handle.write(chunk)
    try:
        return start_run(run_id, source).to_dict()
    finally:
        source.unlink(missing_ok=True)


def start_run(run_id: str, source: Path) -> Run:
    folder = RUNS_DIR / run_id
    folder.mkdir(parents=True, exist_ok=True)
    try:
        clip = normalise(source, folder / "clip.mp4")
    except Exception as exc:
        raise HTTPException(400, f"could not read this video: {exc}")
    run = Run(run_id, clip)
    RUNS[run_id] = run
    spawn(run, "reading", lambda: read_run(run))
    return run


@app.get("/api/samples")
def samples() -> list[str]:
    return sorted(p.stem for p in SAMPLES_DIR.glob("*.mp4"))


@app.post("/api/samples/{name}")
def create_sample_run(request: Request, name: str) -> dict:
    limiter.hit(visitor_id(request))
    if name not in samples():
        raise HTTPException(404, "sample not found")
    return start_run(uuid.uuid4().hex, SAMPLES_DIR / f"{name}.mp4").to_dict()


@app.get("/api/runs/{run_id}")
def read(run_id: str) -> dict:
    return get_run(run_id).to_dict()


@app.get("/media/{run_id}")
def media(run_id: str) -> FileResponse:
    return FileResponse(get_run(run_id).clip.path, media_type="video/mp4")


@app.post("/api/runs/{run_id}/track")
def track(run_id: str, body: TrackRequest) -> dict:
    run = get_run(run_id)
    if run.file_id is None:
        raise HTTPException(409, "the video is still being read")
    frame = nearest_frame(run.clip.times, body.t)
    x = min(max(body.x, 0), run.clip.width - 1)
    y = min(max(body.y, 0), run.clip.height - 1)
    tracks = client.track(run.file_id, point_prompt(frame, x, y, run.clip.width, run.clip.height), run.clip.frames)
    if not tracks:
        raise HTTPException(422, "SAM could not lock on, try tapping a clearer frame")
    run.track = max(tracks.values(), key=len)
    slice_path(run).unlink(missing_ok=True)
    refresh_series(run)
    return run.to_dict()


def slice_path(run: Run) -> Path:
    return run.clip.path.with_name("slice.jpg")


@app.get("/api/runs/{run_id}/slice.jpg")
def run_slice(run_id: str) -> FileResponse:
    run = get_run(run_id)
    if not run.track:
        raise HTTPException(409, "tap the object first")
    path = slice_path(run)
    if not path.exists():
        build_slice(run.clip.path, run.clip.width, run.clip.height, run.track, path)
    return FileResponse(path, media_type="image/jpeg")


@app.post("/api/runs/{run_id}/reference")
def reference(run_id: str, body: ReferenceRequest) -> dict:
    run = get_run(run_id)
    try:
        run.metres_per_px = scale_from_reference(body.p1, body.p2, body.metres)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    run.scale_error = scale_uncertainty(body.p1, body.p2)
    refresh_series(run)
    return run.to_dict()


def refresh_series(run: Run) -> None:
    if run.track and run.metres_per_px:
        clean = clean_track(run.track, run.clip.width, run.clip.height)
        run.series = build_series(clean, run.clip.times, run.metres_per_px)


def agent_context(run: Run) -> str:
    return (
        f"Experiment: {run.setup.get('experiment', 'unknown')}. Object measured: {run.setup.get('track', 'object')}. "
        f"Narration: {run.transcript.get('transcript', 'none')}. "
        f"Narration timing in ms: {run.transcript.get('turns', [])}. "
        f"Positions are in metres with y up. Video is {run.clip.frames} frames over {run.clip.duration:.2f} s."
    )


@app.post("/api/runs/{run_id}/analyse")
def analyse(run_id: str) -> dict:
    run = get_run(run_id)
    if run.series is None:
        raise HTTPException(409, "tap the object and set the reference first")

    def work():
        run.events.clear()
        analysis = agent.Analysis(run.series, run.clip.frames)
        run.finding = agent.analyse(client, analysis, agent_context(run), run.emit)
        finding = run.finding
        if finding["error"] is not None and finding["parameter"] in LENGTH_PARAMETERS:
            finding["fit_error"] = finding["error"]
            finding["error"] = float(hypot(finding["error"], abs(finding["value"]) * run.scale_error))
        run.fit = Fit(run.finding["fit"]["law"], run.finding["fit"]["values"], run.finding["fit"]["errors"],
                      run.finding["fit"]["rms_m"], run.finding["fit"]["aicc"], run.finding["fit"]["r2"],
                      run.finding["fit"]["n"], run.finding["fit"]["derived"])

    spawn(run, "analysing", work)
    return run.to_dict()


@app.post("/api/runs/{run_id}/verify")
def verify_run(run_id: str, body: VerifyRequest) -> dict:
    run = get_run(run_id)
    first = get_run(body.against)
    if run.series is None or first.fit is None or first.finding is None:
        raise HTTPException(409, "both runs need measurements, and run 1 needs a finding")

    def work():
        axis = first.finding["axis"]
        # The window is set from run 2 alone, before the law from run 1 is applied.
        start, end = motion_window(run.series, axis)
        part = run.series.window(start, end)
        verdict = verify(first.fit, part.t - part.t[0], part.axis(axis))
        run.verdict = {**verdict.to_dict(), "warnings": quality_warnings(part, axis, len(part.t)),
                       "window": [start, end], "axis": axis, "law": first.fit.law,
                       "speed": None if verdict.passed else speed_factor(verdict.constants)}
        run.verdict["explanation"] = agent.explain_verdict(client, first.finding, verdict,
                                                           first.setup.get("experiment", "unknown"),
                                                           run.setup.get("experiment", "unknown"),
                                                           run.verdict["speed"])

    spawn(run, "verifying", work)
    return run.to_dict()


@app.get("/api/budget")
def budget() -> dict:
    return {"spent": round(ledger.spent, 4), "limit": ledger.limit_usd}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
