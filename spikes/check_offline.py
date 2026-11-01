"""Check the parser and fit without the API, using the synthetic drop's exact geometry."""
import json
import sys
import tempfile

import make_drop_video as drop
from fit_drop import main as fit
from sam_parse import parse_tracks

DOCS_SAMPLE = (
    "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,~!!!|>,"
    "2<|box;x1=1;y1=2;x2=3;y2=4;w=320;h=334|><|mask;x=0;y=0;data=3,3,~!|>"
)


def fake_sam_output() -> tuple[str, str]:
    r, ball, ruler = drop.RADIUS, [], []
    ruler_px = int(drop.RULER_METRES * drop.PX_PER_METRE)
    for frame in range(drop.HOLD_FRAMES + 60):
        y = round(drop.ball_y(frame))
        ball.append(f"<{frame}f>0<|box;x1={300 - r};y1={y - r};x2={300 + r};y2={y + r};w=720;h=1280|>")
        ruler.append(f"<{frame}f>0<|box;x1=580;y1=300;x2=619;y2={299 + ruler_px};w=720;h=1280|>")
    return "\n".join(ball), "\n".join(ruler)


def save(raw: str, path: str) -> None:
    tracks = parse_tracks(raw)
    for points in tracks.values():
        for point in points:
            point["t"] = point["frame"] / drop.FPS
    with open(path, "w") as handle:
        json.dump({"tracks": tracks}, handle)


def main() -> None:
    parsed = parse_tracks(DOCS_SAMPLE)
    assert sorted(parsed) == [0, 2] and parsed[0][0]["x2"] == 270, parsed
    print("parser ok on the docs sample")
    ball_raw, ruler_raw = fake_sam_output()
    with tempfile.TemporaryDirectory() as tmp:
        save(ball_raw, f"{tmp}/ball.json")
        save(ruler_raw, f"{tmp}/ruler.json")
        fit(f"{tmp}/ball.json", f"{tmp}/ruler.json", str(drop.RULER_METRES))


if __name__ == "__main__":
    sys.exit(main())
