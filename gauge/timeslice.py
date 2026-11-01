"""Time slice of a run: one line of pixels through the object from each frame, laid side by side.

Time runs left to right, so the motion draws its own curve. The line follows the object sideways,
and the image is built from the video alone, with nothing plotted on it.
"""
import subprocess
from pathlib import Path

import numpy as np

OUTPUT_WIDTH = 1600
LOW, HIGH = 1, 99


def _centres(track: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frames = np.array([p["frame"] for p in track])
    x = np.array([(p["x1"] + p["x2"]) / 2 for p in track])
    y = np.array([(p["y1"] + p["y2"]) / 2 for p in track])
    return frames, x, y


def choose_axis(track: list[dict]) -> str:
    """The slice runs along the direction of motion, so vertical motion takes a column."""
    _, x, y = _centres(track)
    return "y" if np.ptp(y) >= np.ptp(x) else "x"


def line_path(track: list[dict], axis: str) -> tuple[int, np.ndarray]:
    """Where the slice sits in each frame from the first tracked frame to the last."""
    frames, x, y = _centres(track)
    across = x if axis == "y" else y
    first, last = int(frames.min()), int(frames.max())
    filled = np.interp(np.arange(first, last + 1), frames, across)
    # A short median stops box jitter from shaking the slice.
    padded = np.pad(filled, 2, mode="edge")
    return first, np.median(np.lib.stride_tricks.sliding_window_view(padded, 5), axis=1)


def band_width(track: list[dict], axis: str) -> int:
    sizes = [(p["x2"] - p["x1"]) if axis == "y" else (p["y2"] - p["y1"]) for p in track]
    return max(4, int(np.median(sizes) * 0.12))


def take_line(frame: np.ndarray, centre: float, band: int, axis: str) -> np.ndarray:
    limit = frame.shape[1] if axis == "y" else frame.shape[0]
    start = int(np.clip(centre - band / 2, 0, limit - band))
    if axis == "y":
        return frame[:, start:start + band].mean(axis=1)
    return frame[start:start + band, :].mean(axis=0)


def stretch(image: np.ndarray) -> np.ndarray:
    low, high = np.percentile(image, [LOW, HIGH])
    return np.clip((image - low) / max(high - low, 1), 0, 1) * 255


def build(video: Path, width: int, height: int, track: list[dict], dest: Path) -> None:
    axis = choose_axis(track)
    first, path = line_path(track, axis)
    band = band_width(track, axis)
    size = width * height
    decoder = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                               stdout=subprocess.PIPE)
    lines = []
    for index in range(first + len(path)):
        raw = decoder.stdout.read(size)
        if len(raw) < size:
            break
        if index >= first:
            frame = np.frombuffer(raw, np.uint8).reshape(height, width)
            lines.append(take_line(frame, path[index - first], band, axis))
    decoder.stdout.close()
    decoder.wait()
    image = stretch(np.stack(lines, axis=1))
    rows, columns = image.shape
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{columns}x{rows}",
                    "-i", "-", "-vf", f"scale={OUTPUT_WIDTH}:{rows}:flags=bicubic", "-frames:v", "1", "-q:v", "3",
                    str(dest)], input=image.astype(np.uint8).tobytes(), check=True)
