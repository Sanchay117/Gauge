"""Client for the Meta Model API. Every paid call goes through the ledger."""
import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .budget import SPARK_RESERVE_USD, Ledger, asr_cost, sam_cost, spark_cost

BASE_URL = "https://api.meta.ai/v1"
SAM_MODEL = "sam-3.1"
SPARK_MODEL = "muse-spark-1.3"
ASR_MODEL = "muse-voice-transcribe-1.0"

FRAME = re.compile(r"<(\d+)f>")
RECORD = re.compile(r"(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)")


def parse_tracks(text: str) -> dict[int, list[dict]]:
    tracks: dict[int, list[dict]] = {}
    for line in text.splitlines():
        head = FRAME.match(line)
        if not head:
            continue
        frame = int(head.group(1))
        for match in RECORD.finditer(line, head.end()):
            obj, x1, y1, x2, y2, _, _ = map(int, match.groups())
            tracks.setdefault(obj, []).append(
                {"frame": frame, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
            )
    for points in tracks.values():
        points.sort(key=lambda p: p["frame"])
    return tracks


def point_prompt(frame: int, x: int, y: int, width: int, height: int) -> str:
    return f"<{frame}f>1<|point;x={x};y={y};w={width};h={height}|>"


def box_prompt(frame: int, box: tuple[int, int, int, int], width: int, height: int) -> str:
    x1, y1, x2, y2 = box
    return f"<{frame}f>1<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={width};h={height}|>"


class MetaClient:
    def __init__(self, ledger: Ledger):
        load_dotenv()
        self.ledger = ledger
        self.headers = {"Authorization": f"Bearer {os.environ['MODEL_API_KEY']}"}

    def _post(self, path: str, **kwargs) -> requests.Response:
        for attempt in range(4):
            res = requests.post(f"{BASE_URL}{path}", headers=self.headers, **kwargs)
            if res.status_code != 429:
                break
            time.sleep(float(res.headers.get("Retry-After", 0.5 * 2**attempt)))
        if not res.ok:
            raise RuntimeError(f"{path} failed with {res.status_code}: {res.text[:500]}")
        return res

    def upload(self, path: Path) -> str:
        with open(path, "rb") as handle:
            res = self._post("/files", data={"purpose": "user_data"}, files={"file": handle}, timeout=300)
        return res.json()["id"]

    def track(self, file_id: str, prompt: str, frames: int) -> dict[int, list[dict]]:
        cost = sam_cost(frames)
        self.ledger.check(cost)
        body = {
            "model": SAM_MODEL,
            "stream": True,
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_video", "file_id": file_id},
            ]}],
        }
        res = self._post("/responses", json=body, stream=True, timeout=600)
        text = ""
        for raw in res.iter_lines():
            if not raw.startswith(b"data:"):
                continue
            payload = raw[5:].strip()
            if payload == b"[DONE]":
                break
            event = json.loads(payload)
            if event.get("type") == "response.output_text.delta":
                text += event["delta"] + "\n"
        self.ledger.record(cost)
        return parse_tracks(text)

    def spark(self, input_items: list, tools: list | None = None, previous_id: str | None = None,
              effort: str = "low", instructions: str | None = None) -> dict:
        self.ledger.check(SPARK_RESERVE_USD)
        body: dict = {"model": SPARK_MODEL, "input": input_items, "reasoning": {"effort": effort}}
        if tools:
            body["tools"] = tools
        if previous_id:
            body["previous_response_id"] = previous_id
        if instructions:
            body["instructions"] = instructions
        res = self._post("/responses", json=body, timeout=300).json()
        usage = res.get("usage", {})
        self.ledger.record(spark_cost(usage.get("input_tokens", 0), usage.get("output_tokens", 0)))
        return res

    def transcribe(self, wav: Path, seconds: float) -> dict:
        cost = asr_cost(seconds)
        self.ledger.check(cost)
        request = {"mode": "DIARIZATION", "model": ASR_MODEL, "audioEncoding": "WAV"}
        with open(wav, "rb") as handle:
            files = {
                "request": (None, json.dumps(request), "application/json"),
                "audio": ("audio.wav", handle, "audio/wav"),
            }
            res = self._post("/asr/transcribe", files=files, timeout=300)
        self.ledger.record(cost)
        return res.json()


def output_text(response: dict) -> str:
    parts = []
    for item in response.get("output", []):
        if item.get("type") == "message":
            parts += [c.get("text", "") for c in item.get("content", []) if c.get("type") == "output_text"]
    return "".join(parts)


def function_calls(response: dict) -> list[dict]:
    return [item for item in response.get("output", []) if item.get("type") == "function_call"]
