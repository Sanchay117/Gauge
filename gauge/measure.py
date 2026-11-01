"""Turn tracked boxes into calibrated measurements, and flag data that cannot be trusted."""
from dataclasses import dataclass

import numpy as np

MIN_JUMP_PX = 15
MAX_REJECTED_RUN = 3
MIN_HOLD_SECONDS = 0.15
MAX_TURN_SECONDS = 0.5
ARC_TOLERANCE = 0.03
MIN_ARC_SAMPLES = 12


@dataclass
class Series:
    t: np.ndarray
    x: np.ndarray
    y: np.ndarray

    def axis(self, name: str) -> np.ndarray:
        return {"x": self.x, "y": self.y}[name]

    def window(self, start: float, end: float) -> "Series":
        keep = (self.t >= start) & (self.t <= end)
        return Series(self.t[keep], self.x[keep], self.y[keep])

    def to_dict(self) -> dict:
        return {"t": self.t.tolist(), "x": self.x.tolist(), "y": self.y.tolist()}


def scale_from_reference(p1: tuple[float, float], p2: tuple[float, float], metres: float) -> float:
    pixels = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
    if pixels < 2 or metres <= 0:
        raise ValueError("reference needs two separate points and a positive length")
    return metres / pixels


def scale_uncertainty(p1: tuple[float, float], p2: tuple[float, float], tap_px: float = 3.0) -> float:
    """Relative error in the scale from imprecise taps, usually larger than the fit error."""
    pixels = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
    return float(np.sqrt(2) * tap_px / pixels)


def _centre(point: dict) -> tuple[float, float]:
    return (point["x1"] + point["x2"]) / 2, (point["y1"] + point["y2"]) / 2


def clean_track(track: list[dict], width: int, height: int, margin: int = 3) -> list[dict]:
    """Drop boxes clipped by the frame edge, and single-frame jumps to another object."""
    points = sorted(track, key=lambda p: p["frame"])
    inside = [p for p in points if p["x1"] > margin and p["y1"] > margin
              and p["x2"] < width - 1 - margin and p["y2"] < height - 1 - margin]
    kept: list[dict] = []
    rejected = 0
    for point in inside:
        if len(kept) >= 2 and rejected < MAX_REJECTED_RUN:
            (ax, ay), (bx, by) = _centre(kept[-2]), _centre(kept[-1])
            ratio = (point["frame"] - kept[-1]["frame"]) / max(kept[-1]["frame"] - kept[-2]["frame"], 1)
            x, y = _centre(point)
            miss = np.hypot(x - (bx + (bx - ax) * ratio), y - (by + (by - ay) * ratio))
            box_size = np.hypot(point["x2"] - point["x1"], point["y2"] - point["y1"])
            if miss > max(box_size, MIN_JUMP_PX):
                rejected += 1
                continue
        rejected = 0
        kept.append(point)
    return kept


def build_series(track: list[dict], times: list[float], metres_per_px: float) -> Series:
    points = sorted(track, key=lambda p: p["frame"])
    t = np.array([times[p["frame"]] for p in points])
    x = np.array([(p["x1"] + p["x2"]) / 2 for p in points]) * metres_per_px
    # Image y grows downward, so flip it to make up positive.
    y = -np.array([(p["y1"] + p["y2"]) / 2 for p in points]) * metres_per_px
    return Series(t - t[0], x, y)


def active_window(series: Series, axis: str) -> tuple[float, float]:
    """Find the longest stretch of motion, trimming holds before release and after landing."""
    values = series.axis(axis)
    if len(values) < 4:
        return float(series.t[0]), float(series.t[-1])
    velocity = np.gradient(values, series.t)
    speed = np.abs(velocity)
    moving = speed > max(0.1 * float(np.percentile(speed, 95)), 1e-9)
    # A thrown ball slows at the top of its arc without stopping, so a slow stretch only
    # counts as a hold if it is long and the object leaves in the direction it arrived.
    dt = float(np.median(np.diff(series.t)))
    still = np.flatnonzero(~moving)
    for run in np.split(still, np.flatnonzero(np.diff(still) > 1) + 1):
        if not run.size or run[0] == 0 or run[-1] == len(moving) - 1:
            continue
        seconds = run.size * dt
        turned = velocity[run[0] - 1] * velocity[run[-1] + 1] < 0
        if seconds <= MIN_HOLD_SECONDS or (turned and seconds <= MAX_TURN_SECONDS):
            moving[run] = True
    best_start, best_len, start = 0, 0, None
    for i, flag in enumerate(list(moving) + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start > best_len:
                best_start, best_len = start, i - start
            start = None
    if best_len < 4:
        return float(series.t[0]), float(series.t[-1])
    return float(series.t[best_start]), float(series.t[best_start + best_len - 1])


def _arc_rms(t: np.ndarray, values: np.ndarray) -> float:
    return float(np.sqrt(np.mean((values - np.polyval(np.polyfit(t, values, 2), t)) ** 2)))


def flight_window(series: Series, axis: str) -> tuple[float, float]:
    """Find the longest parabolic arc around the highest point, ignoring walking and landing."""
    t, values = series.t, series.axis(axis)
    limit = ARC_TOLERANCE * float(np.ptp(values))
    apex = int(np.argmax(values))
    best = (0, len(t) - 1)
    best_len = 0
    for left in range(apex, -1, -1):
        for right in range(len(t) - 1, apex, -1):
            if right - left + 1 <= max(best_len, MIN_ARC_SAMPLES - 1):
                break
            if _arc_rms(t[left:right + 1], values[left:right + 1]) <= limit:
                best, best_len = (left, right), right - left + 1
                break
    return float(t[best[0]]), float(t[best[1]])


def motion_window(series: Series, axis: str) -> tuple[float, float]:
    """The active window, narrowed to the flight when it holds more than one arc."""
    start, end = active_window(series, axis)
    part = series.window(start, end)
    if len(part.t) >= MIN_ARC_SAMPLES:
        values = part.axis(axis)
        if _arc_rms(part.t, values) > ARC_TOLERANCE * float(np.ptp(values)):
            return flight_window(part, axis)
    return start, end


def quality_warnings(series: Series, axis: str, total_frames: int) -> list[str]:
    warnings = []
    coverage = len(series.t) / max(total_frames, 1)
    if coverage < 0.3:
        warnings.append(f"object tracked on only {coverage:.0%} of frames")
    values = series.axis(axis)
    if len(values) < 8:
        warnings.append("too few samples for a reliable fit")
        return warnings
    gaps = np.diff(series.t)
    if gaps.max() > 3 * np.median(gaps):
        warnings.append("tracking has gaps in time")
    # Swapped frames reverse direction on every other step, which real motion cannot do.
    steps = np.diff(values)
    reversals = float(np.mean(np.sign(steps[1:]) != np.sign(steps[:-1])))
    if reversals > 0.6 and np.std(steps) > abs(np.mean(steps)):
        warnings.append("position zigzags between samples, frame timing may be wrong")
    return warnings
