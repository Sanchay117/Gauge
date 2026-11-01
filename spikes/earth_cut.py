"""Cut samples/throw.mp4 from the Commons clip, back at real speed.

The source shows each 25 fps frame ten times over, so keeping every tenth frame restores real time
exactly. The crop keeps the board and stopwatch and drops the slow motion captions and the person.

Usage: uv run spikes/earth_cut.py
"""
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "earth" / "throw.webm"
DEST = ROOT / "samples" / "throw.mp4"
FRAMES = list(range(256, 457, 10))
CROP = (610, 1080, 970, 0)
FPS = 25


def main() -> None:
    picks = "+".join(rf"eq(n\,{n})" for n in FRAMES)
    width, height, left, top = CROP
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(SOURCE), "-an", "-vf",
                    f"select='{picks}',crop={width}:{height}:{left}:{top},setpts=N/{FPS}/TB,format=yuv420p",
                    "-r", str(FPS), "-c:v", "libx264", "-crf", "16", "-movflags", "+faststart", str(DEST)], check=True)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(DEST), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3).astype(np.int16)
    t, y = [], []
    for i, frame in enumerate(frames):
        mask = frame[:860, :, 0] - frame[:860, :, 1:].max(axis=2) > 60
        if mask.sum() >= 200:
            t.append(i / FPS)
            y.append(np.nonzero(mask)[0].mean())
    print(len(frames), "frames,", len(t), "with ball")
    print(np.round(y, 1).tolist())
    # Pixel acceleration only: multiply by the board's metres per pixel to get m/s².
    print("a in px/s²", round(float(np.polyfit(t, y, 2)[0]) * 2, 1))


if __name__ == "__main__":
    main()
