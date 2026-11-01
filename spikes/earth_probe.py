"""Find where the ball flies in the slowed clip, and how many frames are really distinct.

Usage: uv run spikes/earth_probe.py
"""
import subprocess
from pathlib import Path

import numpy as np

SOURCE = Path(__file__).resolve().parent.parent / "data" / "earth" / "throw.webm"
W, H = 960, 540


def main() -> None:
    print(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate,avg_frame_rate,nb_frames", "-of", "csv=p=0", str(SOURCE)],
                         capture_output=True, text=True).stdout.strip())
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(SOURCE), "-vf", f"scale={W}:{H}", "-t", "26",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(np.int16)
    fps = 25
    previous = None
    for i, frame in enumerate(frames):
        zone = frame[:430, 540:760]
        red = zone[..., 0] - zone[..., 1:].max(axis=2)
        mask = red > 60
        change = 0.0 if previous is None else float(np.abs(zone - previous).mean())
        previous = zone
        if mask.sum() >= 12:
            ys, xs = np.nonzero(mask)
            print(f"{i:4d} t={i / fps:6.2f} change={change:5.2f} ball=({xs.mean() + 540:6.1f},{ys.mean():6.1f}) n={mask.sum()}")


if __name__ == "__main__":
    main()
