"""Try several noun phrases on one video and report what SAM finds for each.

Usage: uv run spikes/probe_prompts.py VIDEO "ball" "person" ...
"""
import os
import sys

from dotenv import load_dotenv

from sam_parse import parse_tracks
from track import segment, upload


def main(video: str, prompts: list[str]) -> None:
    load_dotenv()
    headers = {"Authorization": f"Bearer {os.environ['MODEL_API_KEY']}"}
    file_id = upload(video, headers)
    for prompt in prompts:
        raw = segment(file_id, prompt, headers)
        tracks = parse_tracks(raw)
        counts = {obj: len(points) for obj, points in tracks.items()}
        print(f"{prompt!r}: raw {len(raw)} chars, points per object {counts}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
