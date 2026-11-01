"""Build the landing page frame and its measured arc from the real Apollo 16 track.

Usage: uv run spikes/hero_art.py
"""
import json
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FIRST, LAST = 228, 288
FIT_FIRST, FIT_LAST = 236, 279
WIDTH, HEIGHT = 300, 150
PAD = 14


def main() -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(ROOT / "samples" / "jump_1.mp4"),
                    "-vf", r"select=eq(n\,49),crop=962:712:50:0", "-frames:v", "1", "-q:v", "3",
                    str(ROOT / "gauge" / "static" / "moon.jpg")], check=True)
    with open(ROOT / "data" / "apollo" / "pack.json") as handle:
        tracks = json.load(handle)["tracks"]
    pack = {p["frame"]: p for p in max(tracks.values(), key=len)}
    frames = list(range(FIRST, LAST + 1))
    t = np.array([pack[f]["t"] for f in frames])
    y = -np.array([(pack[f]["y1"] + pack[f]["y2"]) / 2 for f in frames])
    inside = np.array([FIT_FIRST <= f <= FIT_LAST for f in frames])
    curve = np.polyfit(t[inside], y[inside], 2)

    def sx(value):
        return PAD + (value - t[0]) / (t[-1] - t[0]) * (WIDTH - 2 * PAD)

    def sy(value):
        return HEIGHT - PAD - (value - y.min()) / np.ptp(y) * (HEIGHT - 2 * PAD)

    grid = np.linspace(t[inside][0], t[inside][-1], 60)
    line = " ".join(f"{sx(a):.1f},{sy(b):.1f}" for a, b in zip(grid, np.polyval(curve, grid)))
    dots = "".join(f'<circle cx="{sx(a):.1f}" cy="{sy(b):.1f}" r="2.6" fill="#4a9be0"/>' for a, b in zip(t, y))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}">{dots}'
           f'<polyline points="{line}" fill="none" stroke="#cc7730" stroke-width="2"/></svg>')
    (ROOT / "gauge" / "static" / "moon-arc.svg").write_text(svg)


if __name__ == "__main__":
    main()
