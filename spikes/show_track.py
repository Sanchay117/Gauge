"""Print every tracked box so a track can be checked by eye.

Usage: uv run spikes/show_track.py TRACK.json
"""
import json
import sys

with open(sys.argv[1]) as handle:
    data = json.load(handle)

print(f"prompt {data['prompt']!r}, {data['frames']} frames in video")
for obj, points in data["tracks"].items():
    print(f"object {obj}: {len(points)} points")
    for p in points:
        w, h = p["x2"] - p["x1"] + 1, p["y2"] - p["y1"] + 1
        print(f"  f{p['frame']:>3} t={p['t']:.3f} centre=({(p['x1'] + p['x2']) / 2:.1f},{(p['y1'] + p['y2']) / 2:.1f}) size={w}x{h}")
