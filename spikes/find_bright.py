"""Find the bounding box of bright pixels in a region of one frame, standing in for a user tap.

Usage: uv run spikes/find_bright.py VIDEO FRAME X1 Y1 X2 Y2 [THRESHOLD]
"""
import subprocess
import sys

import numpy as np


def read_frame(video: str, frame: int, width: int, height: int) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", video, "-vf", f"select=eq(n\\,{frame})",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width)


def main(video: str, frame: str, x1: str, y1: str, x2: str, y2: str, threshold: str = "140") -> None:
    size = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    width, height = map(int, size.split(","))
    img = read_frame(video, int(frame), width, height)
    left, top, right, bottom = int(x1), int(y1), int(x2), int(y2)
    ys, xs = np.nonzero(img[top:bottom, left:right] > int(threshold))
    if len(xs) == 0:
        print(f"no pixels above threshold, region max {img[top:bottom, left:right].max()}")
        return
    print(f"size {width}x{height}, {len(xs)} bright px, box x {left + xs.min()}..{left + xs.max()} y {top + ys.min()}..{top + ys.max()}")


if __name__ == "__main__":
    main(*sys.argv[1:])
