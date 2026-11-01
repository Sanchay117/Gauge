"""Check that Muse Voice and Spark pull the spoken reference out of the Moon sample.

Usage: uv run --env-file .env spikes/voice_check.py
"""
from pathlib import Path

from gauge import agent
from gauge.budget import default_ledger
from gauge.meta_api import MetaClient
from gauge.video import extract_wav, normalise

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "voice"
WORK.mkdir(exist_ok=True)
clip = normalise(ROOT / "samples" / "jump_1.mp4", WORK / "clip.mp4")
print("audio", clip.has_audio)
client = MetaClient(default_ledger())
extract_wav(clip.path, WORK / "clip.wav")
transcript = client.transcribe(WORK / "clip.wav", clip.duration).get("transcript", "")
print("heard:", transcript)
setup = agent.read_setup(client, client.upload(clip.path), transcript)
print({k: setup.get(k) for k in ("experiment", "track", "reference", "reference_metres")})
