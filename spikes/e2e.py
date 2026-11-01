"""Drive the running server through real clips: find a law, then try to break it.

Usage: uv run spikes/e2e.py
"""
import json
import time
from pathlib import Path

import requests

BASE = "http://localhost:8060"
DATA = Path(__file__).resolve().parent.parent / "data" / "tracker"


def wait(run_id: str) -> dict:
    while True:
        run = requests.get(f"{BASE}/api/runs/{run_id}", timeout=30).json()
        if run["status"] == "idle":
            if run["error"]:
                raise SystemExit(f"run failed: {run['error']}")
            return run
        time.sleep(1)


def prepare(video: str, source_width: int, t: float, tap: tuple[int, int], p1: tuple, p2: tuple, metres: float) -> dict:
    with open(DATA / video, "rb") as handle:
        run = requests.post(f"{BASE}/api/runs", files={"file": (video, handle, "video/mp4")}, timeout=120)
    run.raise_for_status()
    run_id = run.json()["id"]
    run = wait(run_id)
    print(f"\n{video}: setup {json.dumps(run['setup'])}, stored at {run['width']}x{run['height']}")
    # Coordinates here are in source pixels, and the server may have downscaled the clip.
    factor = run["width"] / source_width
    x, y = round(tap[0] * factor), round(tap[1] * factor)
    p1 = [p1[0] * factor, p1[1] * factor]
    p2 = [p2[0] * factor, p2[1] * factor]
    res = requests.post(f"{BASE}/api/runs/{run_id}/track", json={"t": t, "x": x, "y": y}, timeout=300)
    res.raise_for_status()
    print(f"tracked {len(res.json()['track'])} of {run['frames']} frames")
    res = requests.post(f"{BASE}/api/runs/{run_id}/reference", json={"p1": p1, "p2": p2, "metres": metres}, timeout=30)
    res.raise_for_status()
    return res.json()


def analyse(run_id: str) -> dict:
    requests.post(f"{BASE}/api/runs/{run_id}/analyse", timeout=30).raise_for_status()
    run = wait(run_id)
    f = run["finding"]
    for event in run["events"]:
        print(f"  {event['text']}")
    print(f"FINDING {f['quantity']}: {f['parameter']} = {f['value']:.4f} +/- {f['error'] or 0:.4f}, law {f['fit']['law']}, "
          f"R2 {f['fit']['r2']:.5f}, derived {f['fit']['derived']}, window {f['window']}, warnings {f['warnings']}")
    print(f"  {f['explanation']}")
    print(f"  next: {f['next_run']}")
    return run


def verify(run_id: str, against: str, label: str) -> None:
    requests.post(f"{BASE}/api/runs/{run_id}/verify", json={"against": against}, timeout=30).raise_for_status()
    v = wait(run_id)["verdict"]
    print(f"VERDICT {label}: {'PASS' if v['passed'] else 'FAIL'} ({v['reason']}), constants {json.dumps(v['constants'])}, "
          f"held {v['held_rms'] * 1000:.2f} mm, free {v['free_rms'] * 1000:.2f} mm, n {v['n']}, warnings {v['warnings']}")
    print(f"  {v['explanation']}")


def main() -> None:
    drop = prepare("BallDrop_2x.mp4", 1268, 0.4, (393, 396), (565, 96), (565, 896), 1.0)
    drop = analyse(drop["id"])

    toss = prepare("BallTossUp_2x.mp4", 1428, 50 / 60, (448, 170), (632, 96), (632, 896), 1.0)
    verify(toss["id"], drop["id"], "drop law on the toss, should pass")

    swing = prepare("Pendulum_3x.mp4", 960, 0.0, (155, 522), (500, 410), (500, 616), 0.4)
    verify(swing["id"], drop["id"], "drop law on the pendulum, should fail")
    analyse(swing["id"])
    print("\nspent", requests.get(f"{BASE}/api/budget", timeout=10).json())


if __name__ == "__main__":
    main()
