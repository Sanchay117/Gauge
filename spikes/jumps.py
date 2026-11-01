"""Fit each jump in pixels, then test how results depend on window and camera correction.

Usage: uv run spikes/jumps.py PACK.json FLAG.json PACK_METRES
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauge.laws import fit_law, verify

JUMPS = {"jump 1": (236, 279), "jump 2": (331, 370)}


def load(path: str) -> dict[int, dict]:
    with open(path) as handle:
        tracks = json.load(handle)["tracks"]
    return {p["frame"]: p for p in max(tracks.values(), key=len)}


def series(pack: dict, flag: dict, start: int, end: int, anchored: bool):
    frames = [f for f in range(start, end + 1) if f in pack and f in flag]
    t = np.array([pack[f]["t"] for f in frames])
    y = np.array([(pack[f]["y1"] + pack[f]["y2"]) / 2 for f in frames], dtype=float)
    if anchored:
        y -= np.array([(flag[f]["y1"] + flag[f]["y2"]) / 2 for f in frames])
    height = float(np.median([pack[f]["y2"] - pack[f]["y1"] + 1 for f in frames]))
    return t - t[0], -y, height


def main(pack_path: str, flag_path: str, metres: str) -> None:
    pack, flag = load(pack_path), load(flag_path)
    size = float(metres)
    fits = {}
    for name, (start, end) in JUMPS.items():
        for anchored in (False, True):
            t, y, height = series(pack, flag, start, end, anchored)
            scale = size / height
            fit = fit_law("constant_acceleration", t, y * scale)
            label = "anchored" if anchored else "raw"
            print(f"{name} {label:>8}: g = {-fit.values['a']:.3f} +/- {fit.errors['a']:.3f}, RMS {fit.rms * 1000:.1f} mm, "
                  f"pack {height:.0f} px, airtime in window {t[-1]:.2f} s")
            fits[(name, anchored)] = (fit, t, y * scale)
    print("\nwindow sensitivity, raw:")
    for name, (start, end) in JUMPS.items():
        values = []
        for trim_a in (-3, 0, 3, 6):
            for trim_b in (-3, 0, 3, 6):
                t, y, height = series(pack, flag, start + trim_a, end - trim_b, False)
                values.append(-fit_law("constant_acceleration", t, y * size / height).values["a"])
        print(f"  {name}: {min(values):.3f} to {max(values):.3f}, mean {np.mean(values):.3f}")
    for anchored in (False, True):
        fit = fits[("jump 1", anchored)][0]
        _, t, y = fits[("jump 2", anchored)]
        v = verify(fit, t, y)
        print(f"\nverify jump 1 on jump 2, anchored={anchored}: {'PASS' if v.passed else 'FAIL'} ({v.reason}), {v.constants}, held {v.held_rms * 1000:.1f} mm, free {v.free_rms * 1000:.1f} mm")


if __name__ == "__main__":
    main(*sys.argv[1:])
