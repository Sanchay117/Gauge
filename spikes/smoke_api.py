"""Smoke test the API calls the app depends on.

Usage: uv run spikes/smoke_api.py BALLDROP_2X.mp4 SPEECH.wav SECONDS
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gauge.budget import default_ledger
from gauge.meta_api import MetaClient, function_calls, output_text, point_prompt


def main(video: str, wav: str, seconds: str) -> None:
    client = MetaClient(default_ledger())
    file_id = client.upload(Path(video))
    print("uploaded", file_id)

    tracks = client.track(file_id, point_prompt(24, 393, 396, 1268, 960), 66)
    print("point prompt:", {k: len(v) for k, v in tracks.items()})

    res = client.spark([{"role": "user", "content": [
        {"type": "input_video", "file_id": file_id},
        {"type": "input_text", "text": "In one sentence, what physical experiment is shown?"},
    ]}])
    print("spark video:", output_text(res), res.get("usage"))

    tool = {"type": "function", "name": "get_value", "description": "Return a value.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}
    res = client.spark([{"role": "user", "content": "Call get_value with name=g."}], tools=[tool])
    calls = function_calls(res)
    print("spark tool:", calls)
    follow = client.spark(
        [{"type": "function_call_output", "call_id": calls[0]["call_id"], "output": "9.8"}],
        tools=[tool], previous_id=res["id"],
    )
    print("spark follow up:", output_text(follow))

    print("asr:", client.transcribe(Path(wav), float(seconds)))
    print("ledger spent:", round(client.ledger.spent, 4))


if __name__ == "__main__":
    main(*sys.argv[1:4])
