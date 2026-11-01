"""Measure the bright stripes along the stick from a brightness profile.

Usage: uv run spikes/stick_stripes.py VIDEO FRAME X1 X2
"""
import subprocess
import sys

import numpy as np

from find_bright import read_frame


def main(video: str, frame: str, x1: str, x2: str) -> None:
    size = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    width, height = map(int, size.split(","))
    img = read_frame(video, int(frame), width, height).astype(float)
    profile = img[:, int(x1):int(x2)].mean(axis=1)
    threshold = (profile.max() + profile.min()) / 2
    bright = profile > threshold
    edges = np.flatnonzero(np.diff(bright.astype(int)))
    starts = edges[bright[edges + 1]] + 1
    ends = edges[~bright[edges + 1]] + 1
    print(f"threshold {threshold:.0f}, {len(starts)} bright segments")
    for start, end in zip(starts, ends):
        print(f"  y {start}..{end} length {end - start}")
    if len(starts) > 2:
        print(f"period between stripe starts, median: {np.median(np.diff(starts)):.1f} px")


if __name__ == "__main__":
    main(*sys.argv[1:])
