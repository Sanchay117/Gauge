"""Cut the Apollo 16 jump salute into two clips, then measure one jump and test it on the other.

Usage: uv run spikes/e2e_moon.py
"""
import json
import subprocess
from pathlib import Path

import requests

from e2e import BASE, analyse, verify, wait

DATA = Path(__file__).resolve().parent.parent / "data" / "apollo"
PACK_METRES = 0.914  # PLSS 26 in high plus OPS 10 in high, stacked
JUMPS = {"jump_1": (205, 300, 254), "jump_2": (300, 395, 347)}


def load_pack() -> dict[int, dict]:
    with open(DATA / "pack.json") as handle:
        tracks = json.load(handle)["tracks"]
    return {p["frame"]: p for p in max(tracks.values(), key=len)}


def cut(name: str, start: float, end: float) -> Path:
    out = DATA / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(DATA / "salute_3x.mp4"),
                    "-t", f"{end - start:.3f}", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                    "-fps_mode", "passthrough", "-an", str(out)], check=True)
    return out


def prepare(name: str, pack: dict[int, dict]) -> str:
    first, last, peak = JUMPS[name]
    box = pack[peak]
    path = cut(name, pack[first]["t"], pack[last]["t"])
    with open(path, "rb") as handle:
        run = requests.post(f"{BASE}/api/runs", files={"file": (path.name, handle, "video/mp4")}, timeout=120)
    run.raise_for_status()
    run_id = run.json()["id"]
    run = wait(run_id)
    print(f"\n{name}: {run['frames']} frames at {run['width']}x{run['height']}, setup {json.dumps(run['setup'])}")
    t = pack[peak]["t"] - pack[first]["t"]
    x, y = round((box["x1"] + box["x2"]) / 2), round((box["y1"] + box["y2"]) / 2)
    res = requests.post(f"{BASE}/api/runs/{run_id}/track", json={"t": t, "x": x, "y": y}, timeout=300)
    res.raise_for_status()
    track = res.json()["track"]
    heights = [p["y2"] - p["y1"] + 1 for p in track] if "y2" in track[0] else []
    print(f"tracked {len(track)} frames, box height median {sorted(heights)[len(heights) // 2] if heights else 'n/a'}")
    middle = x
    reference = {"p1": [middle, box["y1"]], "p2": [middle, box["y2"] + 1], "metres": PACK_METRES}
    requests.post(f"{BASE}/api/runs/{run_id}/reference", json=reference, timeout=30).raise_for_status()
    return run_id


def main() -> None:
    pack = load_pack()
    first = prepare("jump_1", pack)
    analyse(first)
    second = prepare("jump_2", pack)
    verify(second, first, "jump 1 law on jump 2")
    print("\nspent", requests.get(f"{BASE}/api/budget", timeout=10).json())


if __name__ == "__main__":
    main()
