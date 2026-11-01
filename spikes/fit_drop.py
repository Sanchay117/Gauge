"""Recover g from tracked boxes, using a reference object of known length for scale.

Usage: uv run spikes/fit_drop.py BALL.json RULER.json RULER_METRES
"""
import json
import sys

import numpy as np


def longest_track(path: str) -> list[dict]:
    with open(path) as handle:
        tracks = json.load(handle)["tracks"]
    return max(tracks.values(), key=len)


def metres_per_px(ruler: list[dict], ruler_metres: float) -> float:
    lengths = [max(p["x2"] - p["x1"], p["y2"] - p["y1"]) + 1 for p in ruler]
    return ruler_metres / float(np.median(lengths))


def falling_segment(t: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # Keep the run of frames where the object is moving down, dropping hold and landing.
    moving = np.diff(y) > 1
    first = int(np.argmax(moving))
    last = len(moving) - int(np.argmax(moving[::-1]))
    return t[first:last + 1], y[first:last + 1]


def fit_g(t: np.ndarray, y_metres: np.ndarray) -> tuple[float, float]:
    coeffs = np.polyfit(t, y_metres, 2)
    residual = y_metres - np.polyval(coeffs, t)
    return 2 * coeffs[0], float(np.sqrt(np.mean(residual**2)))


def main(ball_path: str, ruler_path: str, ruler_metres: str) -> None:
    ball = sorted(longest_track(ball_path), key=lambda p: p["frame"])
    scale = metres_per_px(longest_track(ruler_path), float(ruler_metres))
    t = np.array([p["t"] for p in ball])
    y = np.array([(p["y1"] + p["y2"]) / 2 for p in ball])
    t_fall, y_fall = falling_segment(t, y)
    g, rms = fit_g(t_fall, y_fall * scale)
    print(f"scale {scale * 1000:.3f} mm/px, {len(t_fall)} frames in fall")
    print(f"g = {g:.3f} m/s^2, fit RMS {rms * 1000:.2f} mm, error vs 9.81: {abs(g - 9.81) / 9.81:.1%}")
    print(f"reference length that would give exactly 9.81: {float(ruler_metres) * 9.81 / g:.3f} m")


if __name__ == "__main__":
    main(*sys.argv[1:4])
