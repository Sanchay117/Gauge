"""Parse SAM 3.1 special-token output into per-object box tracks."""
import re

FRAME = re.compile(r"<(\d+)f>")
RECORD = re.compile(r"(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)")


def parse_tracks(text: str) -> dict[int, list[dict]]:
    tracks: dict[int, list[dict]] = {}
    for line in text.splitlines():
        head = FRAME.match(line)
        if not head:
            continue
        frame = int(head.group(1))
        for match in RECORD.finditer(line, head.end()):
            obj, x1, y1, x2, y2, _, _ = map(int, match.groups())
            tracks.setdefault(obj, []).append(
                {"frame": frame, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
            )
    return tracks
