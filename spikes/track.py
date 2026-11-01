"""Track a noun phrase through a video with SAM 3.1 and save boxes with real timestamps.

Usage: uv run spikes/track.py VIDEO "red ball" OUT.json
"""
import json
import os
import subprocess
import sys

import requests
from dotenv import load_dotenv

from sam_parse import parse_tracks

BASE_URL = "https://api.meta.ai/v1"
SAM_MODEL = "sam-3.1"


def frame_times(video: str) -> list[float]:
    # Phones often record at a variable frame rate, so frame index alone is not time.
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True,
    ).stdout
    return [float(line.strip(",")) for line in out.split()]


def upload(video: str, headers: dict) -> str:
    with open(video, "rb") as handle:
        res = requests.post(
            f"{BASE_URL}/files", headers=headers,
            data={"purpose": "user_data"}, files={"file": handle}, timeout=300,
        )
    res.raise_for_status()
    return res.json()["id"]


def segment(file_id: str, prompt: str, headers: dict) -> str:
    body = {
        "model": SAM_MODEL,
        "stream": True,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_video", "file_id": file_id},
        ]}],
    }
    res = requests.post(f"{BASE_URL}/responses", headers=headers, json=body, stream=True, timeout=600)
    if not res.ok:
        sys.exit(f"SAM error {res.status_code}: {res.text}")
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
    return text


def main(video: str, prompt: str, out: str) -> None:
    load_dotenv()
    headers = {"Authorization": f"Bearer {os.environ['MODEL_API_KEY']}"}
    times = frame_times(video)
    raw = segment(upload(video, headers), prompt, headers)
    tracks = parse_tracks(raw)
    for points in tracks.values():
        for point in points:
            point["t"] = times[point["frame"]]
    with open(out, "w") as handle:
        json.dump({"prompt": prompt, "frames": len(times), "tracks": tracks, "raw": raw}, handle)
    print(f"{len(tracks)} objects, frames with data: {[len(p) for p in tracks.values()]} of {len(times)}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
