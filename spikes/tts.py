"""Speak text with Deepgram into a WAV file. The key is read from an env file and never printed.

Usage: uv run spikes/tts.py <env file> <out.wav> "text" [voice]
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.deepgram.com/v1/speak?model={voice}&encoding=linear16&container=wav&sample_rate=24000"


def read_key(path: Path) -> str:
    for line in path.read_text().splitlines():
        match = re.match(r"\s*(?:export\s+)?(?:TTS|DEEPGRAM[A-Z0-9_]*)\s*=\s*['\"]?(?:Token\s+)?([^'\"\s#]+)", line)
        if match:
            return match.group(1)
    raise SystemExit("no Deepgram key in that env file")


def main() -> None:
    env_file, out, text = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    voice = sys.argv[4] if len(sys.argv) > 4 else "aura-2-thalia-en"
    request = urllib.request.Request(ENDPOINT.format(voice=voice), data=json.dumps({"text": text}).encode(),
                                     headers={"Authorization": f"Token {read_key(env_file)}",
                                              "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            out.write_bytes(response.read())
    except urllib.error.HTTPError as err:
        raise SystemExit(f"Deepgram returned {err.code}")
    print(out.stat().st_size)


if __name__ == "__main__":
    main()
