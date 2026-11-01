"""Fetch the Earth throw clip from Wikimedia Commons into data/earth/.

Usage: uv run spikes/earth_fetch.py
"""
import urllib.request
from pathlib import Path

URL = "https://upload.wikimedia.org/wikipedia/commons/2/25/Senkrechter_Wurf_nach_oben_%28Steigzeit%29.webm"
DEST = Path(__file__).resolve().parent.parent / "data" / "earth" / "throw.webm"

DEST.parent.mkdir(exist_ok=True)
request = urllib.request.Request(URL, headers={"User-Agent": "GaugeHackathonProject/0.1 (github.com/Sanchay117/Gauge)"})
with urllib.request.urlopen(request, timeout=120) as response:
    DEST.write_bytes(response.read())
print(DEST.stat().st_size)
