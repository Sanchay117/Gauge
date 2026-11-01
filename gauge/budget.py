"""Local spend guard. Meta's API has no hard cap, so Gauge enforces its own."""
import json
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

SAM_PER_FRAME = 0.20 / 1000
SAM_MIN_FRAMES = 50
SPARK_INPUT_PER_TOKEN = 1.25 / 1_000_000
SPARK_OUTPUT_PER_TOKEN = 4.25 / 1_000_000
ASR_PER_SECOND = 0.18 / 3600
SPARK_RESERVE_USD = 0.05


class BudgetExceeded(Exception):
    pass


class RateLimited(Exception):
    pass


def sam_cost(frames: int) -> float:
    return max(frames, SAM_MIN_FRAMES) * SAM_PER_FRAME


def spark_cost(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * SPARK_INPUT_PER_TOKEN + output_tokens * SPARK_OUTPUT_PER_TOKEN


def asr_cost(seconds: float) -> float:
    return seconds * ASR_PER_SECOND


class Ledger:
    """Persistent running total, checked before every paid call."""

    def __init__(self, path: Path, limit_usd: float):
        self.path = path
        self.limit_usd = limit_usd
        self._lock = threading.Lock()
        self.spent = json.loads(path.read_text())["spent"] if path.exists() else 0.0

    def check(self, cost: float) -> None:
        with self._lock:
            if self.spent + cost > self.limit_usd:
                raise BudgetExceeded(
                    f"budget of ${self.limit_usd:.2f} reached, ${self.spent:.2f} spent"
                )

    def record(self, cost: float) -> None:
        with self._lock:
            self.spent += cost
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"spent": self.spent}))


class VisitorLimiter:
    """Sliding-window limit on paid actions per visitor."""

    def __init__(self, max_actions: int, window_seconds: float):
        self.max_actions = max_actions
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, visitor: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            hits = self._hits[visitor]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_actions:
                raise RateLimited("too many runs from this visitor, try again later")
            hits.append(now)


def default_ledger() -> Ledger:
    root = Path(__file__).resolve().parent.parent
    return Ledger(root / "data" / "spend.json", float(os.environ.get("GAUGE_BUDGET_USD", "100")))
