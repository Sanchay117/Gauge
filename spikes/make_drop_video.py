"""Render a ball drop with a known g, so tracking can be scored against the truth."""
import subprocess
import sys

import numpy as np

WIDTH, HEIGHT, FPS = 720, 1280, 60
PX_PER_METRE = 800
G = 9.81
RADIUS = 28
START_Y = 80
FLOOR_Y = HEIGHT - 60
HOLD_FRAMES = 30
RULER_METRES = 0.5


def ball_y(frame: int) -> float:
    t = max(frame - HOLD_FRAMES, 0) / FPS
    return min(START_Y + 0.5 * G * t * t * PX_PER_METRE, FLOOR_Y - RADIUS)


def render(frame: int) -> bytes:
    img = np.full((HEIGHT, WIDTH, 3), 225, dtype=np.uint8)
    ruler_px = int(RULER_METRES * PX_PER_METRE)
    img[300 : 300 + ruler_px, 580:620] = (40, 80, 220)
    yy, xx = np.ogrid[:HEIGHT, :WIDTH]
    inside = (xx - 300) ** 2 + (yy - ball_y(frame)) ** 2 <= RADIUS**2
    img[inside] = (220, 40, 40)
    return img.tobytes()


def main(out: str) -> None:
    total = HOLD_FRAMES + 60
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
        stdin=subprocess.PIPE,
    )
    for frame in range(total):
        ffmpeg.stdin.write(render(frame))
    ffmpeg.stdin.close()
    ffmpeg.wait()


if __name__ == "__main__":
    main(sys.argv[1])
