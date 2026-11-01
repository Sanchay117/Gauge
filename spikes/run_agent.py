"""Run the agent on saved SAM tracks, no web server needed.

Usage: uv run spikes/run_agent.py TRACK.json METRES_PER_PX "experiment context"
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gauge.agent import Analysis, analyse
from gauge.budget import default_ledger
from gauge.measure import Series
from gauge.meta_api import MetaClient

import numpy as np


def main(path: str, scale: str, context: str) -> None:
    with open(path) as handle:
        data = json.load(handle)
    points = max(data["tracks"].values(), key=len)
    points.sort(key=lambda p: p["frame"])
    series = Series(
        np.array([p["t"] for p in points]),
        np.array([(p["x1"] + p["x2"]) / 2 for p in points]) * float(scale),
        -np.array([(p["y1"] + p["y2"]) / 2 for p in points]) * float(scale),
    )
    client = MetaClient(default_ledger())
    finding = analyse(client, Analysis(series, data["frames"]), context, lambda e: print(e))
    print(json.dumps(finding, indent=2))
    print("spent", round(client.ledger.spent, 4))


if __name__ == "__main__":
    main(*sys.argv[1:4])
