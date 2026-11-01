"""Build the landing page's time slice: one column of pixels from every frame, laid side by side.

Time runs left to right, so the film draws the jump's parabola with no plotting involved.
Also writes the scrub clip and the per-frame heights from the SAM track.

Usage: uv run spikes/chrono.py
"""
import json
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "apollo" / "salute_3x.mp4"
OUT = ROOT / "gauge" / "static"
FIRST, LAST = 150, 420
BAND = 12
WIDEN = 7
BLACK, WHITE = 24, 214
CROP_BOTTOM = 80
# Frames between takeoff and landing, with the scale for that jump in metres per pixel.
JUMPS = [(233, 281, 0.00448), (327, 373, 0.00469)]


def probe() -> tuple[int, int, float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-of", "csv=p=0", str(SOURCE)],
                         capture_output=True, text=True, check=True).stdout
    width, height, rate = out.strip().split(",")[:3]
    top, bottom = rate.split("/")
    return int(width), int(height), int(top) / int(bottom)


def read_frames(width: int, height: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(SOURCE), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width)


def load_track() -> dict:
    with open(ROOT / "data" / "apollo" / "pack.json") as handle:
        tracks = json.load(handle)["tracks"]
    return {p["frame"]: p for p in max(tracks.values(), key=len)}


def time_slice(frames: np.ndarray, column: int) -> np.ndarray:
    band = frames[FIRST:LAST + 1, :, column - BAND // 2:column + BAND // 2].astype(np.float32).mean(axis=2)
    image = np.repeat(band.T, WIDEN, axis=1)[:-CROP_BOTTOM]
    return np.clip((image - BLACK) / (WHITE - BLACK), 0, 1) * 255


def save_slice(image: np.ndarray) -> None:
    height, width = image.shape
    # A smooth upscale removes the stair steps left by widening each frame into a band.
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{width}x{height}",
                    "-i", "-", "-vf", "gblur=sigma=2.2:sigmaV=0.6,scale=2400:-2:flags=lanczos", "-frames:v", "1",
                    "-q:v", "3", str(OUT / "slice.jpg")],
                   input=image.astype(np.uint8).tobytes(), check=True)


def save_clip(rate: float) -> None:
    # Every frame is a keyframe, so scrubbing lands instantly.
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(SOURCE), "-an", "-vf",
                    rf"select=between(n\,{FIRST}\,{LAST}),setpts=N/{rate}/TB,scale=528:360,format=yuv420p",
                    "-c:v", "libx264", "-crf", "27", "-g", "1", "-movflags", "+faststart", str(OUT / "film.mp4")],
                   check=True)


def heights(track: dict) -> list[float]:
    values = [0.0] * (LAST - FIRST + 1)
    for first, last, scale in JUMPS:
        centre = lambda f: (track[f]["y1"] + track[f]["y2"]) / 2
        for frame in range(first, last + 1):
            # Interpolate the resting level across the jump, because the camera drifts.
            rest = np.interp(frame, [first, last], [centre(first), centre(last)])
            values[frame - FIRST] = round(max((rest - centre(frame)) * scale, 0), 2)
    return values


def main() -> None:
    width, height, rate = probe()
    track = load_track()
    column = int(np.median([(p["x1"] + p["x2"]) / 2 for p in track.values()]))
    save_slice(time_slice(read_frames(width, height), column))
    save_clip(rate)
    rise = heights(track)
    (OUT / "slice.json").write_text(json.dumps({"fps": rate, "heights": rise}))
    print(rate, max(rise[:150]), max(rise[150:]))


if __name__ == "__main__":
    main()
