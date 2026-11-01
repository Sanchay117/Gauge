"""Print the timed narration of a clip with Muse Voice Transcribe.

Usage: uv run spikes/transcribe.py VIDEO
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gauge.budget import default_ledger
from gauge.meta_api import MetaClient
from gauge.video import extract_wav, frame_times


def main(video: str) -> None:
    client = MetaClient(default_ledger())
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        extract_wav(Path(video), wav)
        result = client.transcribe(wav, frame_times(Path(video))[-1])
    for turn in result.get("turns", []):
        print(f"{turn['startMs'] / 1000:7.2f} to {turn['endMs'] / 1000:7.2f}  {turn.get('speaker', '')}  {turn['transcript']}")


if __name__ == "__main__":
    main(sys.argv[1])
