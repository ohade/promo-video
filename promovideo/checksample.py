"""A small resolved edit list with its frame rows, used by `check --self-test` and the tests."""
import csv
import json
from pathlib import Path

from .common import FPS

CLOCK_BOX = "1708,32,180"


def _rows_for(seg, frame0, zero):
    """String rows, as read back from a frames.tsv, for one resolved sample segment."""
    rows = []
    for i in range(seg["frames"]):
        r = dict(frame=str(frame0 + i), seg=seg["id"], mode=seg.get("mode", seg["kind"].upper()), clock_visible="0",
                 clock_box="", raw_t="", speed="", clock_t="", clock_rate="", badge="")
        if seg["kind"] == "capture":
            sp = 0.0 if seg["mode"] == "HOLD" else float(seg["speed"])
            raw = seg["raw_in"] + i * sp / FPS
            badge = "PAUSED" if seg["mode"] == "HOLD" else ("LIVE" if sp == 1.0 else f"x{int(round(sp))}")
            r.update(clock_visible="1", clock_box=CLOCK_BOX, raw_t=f"{raw:.4f}", speed=str(sp),
                     clock_t=f"{max(0.0, raw - zero):.4f}", clock_rate=str(sp), badge=badge)
        rows.append(r)
    return rows


def sample_edl():
    """A small resolved edit list (graphic, three clocked capture modes, black) and its frame rows; every rule passes."""
    zero = 10.0
    src = "footage/demo.mp4"
    segs = [
        dict(id="g1", block="open", kind="graphic", scene="title", dur=2.0, frames=60, change_points=[0.0, 1.0]),
        dict(id="c1", block="demo", kind="capture", source=src, src_size=[1920, 1080], mode="HUMAN", speed=1.0,
             raw_in=10.0, raw_out=12.0, dur=2.0, frames=60, clock=True, clock_zero=zero, crop=[0, 0, 1920, 1080],
             change_points=[0.0]),
        dict(id="c2", block="demo", kind="capture", source=src, src_size=[1920, 1080], mode="WAIT", speed=20.0,
             raw_in=12.0, raw_out=32.0, dur=1.0, frames=30, clock=True, clock_zero=zero, crop=[320, 180, 1280, 720],
             change_points=[0.0]),
        dict(id="c3", block="demo", kind="capture", source=src, src_size=[1920, 1080], mode="HOLD", speed=0.0,
             raw_in=32.0, raw_out=32.0, dur=0.5, frames=15, clock=True, clock_zero=zero, crop=[320, 180, 1280, 720],
             change_points=[0.0]),
        dict(id="b1", block="end", kind="black", dur=0.5, frames=15, change_points=[0.0]),
    ]
    rows, frame0 = [], 0
    for s in segs:
        s["start"] = round(frame0 / FPS, 4)
        rows += _rows_for(s, frame0, zero)
        frame0 += s["frames"]
    edl = {"preset": "bay", "segments": segs, "total": round(frame0 / FPS, 4), "max_shot_s": 4.0,
           "script": {"s01": "A short opening line.", "s02": "And a second line to close."},
           "audio": {"vo": [{"id": "s01", "start": 0.2, "dur": 1.5}, {"id": "s02", "start": 2.5, "dur": 2.0}]}}
    return edl, rows


def save_sample(directory):
    """Write the sample as <dir>/sample.edl.json + sample.frames.tsv (the layout `render` produces)."""
    edl, rows = sample_edl()
    path = Path(directory) / "sample.edl.json"
    edl["frames_log"] = "sample.frames.tsv"
    path.write_text(json.dumps(edl, indent=1))
    with open(Path(directory) / edl["frames_log"], "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    return path
