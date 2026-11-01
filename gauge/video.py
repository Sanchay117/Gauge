"""ffmpeg helpers. Timing comes from each frame's own timestamp, because phones record VFR."""
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_SIDE = 1280
MAX_SECONDS = 60


@dataclass
class Clip:
    path: Path
    width: int
    height: int
    times: list[float]
    has_audio: bool

    @property
    def frames(self) -> int:
        return len(self.times)

    @property
    def duration(self) -> float:
        return self.times[-1] if self.times else 0.0


def _run(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def _probe(path: Path) -> dict:
    return json.loads(_run(
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,width,height,field_order:format=duration", "-of", "json", str(path),
    ))


def frame_times(path: Path) -> list[float]:
    out = _run("ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path))
    return [float(line.strip(",")) for line in out.split()]


def _filters(field_order: str) -> str:
    filters = []
    # Field order comes from the file, since guessing it swaps every pair of samples in time.
    if field_order in ("tt", "tb"):
        filters.append("yadif=mode=1:parity=tff")
    elif field_order in ("bb", "bt"):
        filters.append("yadif=mode=1:parity=bff")
    filters.append(f"scale='min({MAX_SIDE},iw)':'min({MAX_SIDE},ih)':force_original_aspect_ratio=decrease")
    filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    return ",".join(filters)


def normalise(source: Path, dest: Path) -> Clip:
    """Re-encode upright H.264 with original frame timing, ready for SAM and the browser."""
    info = _probe(source)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("no video stream found")
    if float(info["format"].get("duration", 0)) > MAX_SECONDS:
        raise ValueError(f"clip is longer than {MAX_SECONDS} seconds")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    _run("ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
         "-vf", _filters(video.get("field_order", "progressive")), "-fps_mode", "passthrough",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-movflags", "+faststart", str(dest))
    stream = next(s for s in _probe(dest)["streams"] if s["codec_type"] == "video")
    return Clip(dest, stream["width"], stream["height"], frame_times(dest), has_audio)


def extract_wav(source: Path, dest: Path) -> None:
    _run("ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-ac", "1", "-ar", "24000",
         "-c:a", "pcm_s16le", "-map_metadata", "-1", str(dest))


def nearest_frame(times: list[float], t: float) -> int:
    return min(range(len(times)), key=lambda i: abs(times[i] - t))
