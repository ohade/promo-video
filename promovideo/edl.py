"""Edit list (EDL): load a project, resolve the timeline, per-frame clock rows and narration timing, and save the
resolved list with its per-frame log. Rendering lives in render.py.

Segment kinds: graphic (a registered scene), black, capture (footage under <project>/, cropped, optional clock).
Capture modes: HUMAN (speed <= 1), WAIT (8-60), HOLD (freeze, clock stopped), CUT (0.3 s clock spin over a declared
jump, badge "+N s"), RESET (0.3 s spin back to zero). For HUMAN/WAIT the source time advances by the instantaneous
speed every frame and the clock advances by the same amount, ramps included (ramp_from/ramp_in, ramp_to/ramp_out)."""
import csv
import json
import os
import tomllib
from pathlib import Path

import numpy as np

from . import clock as clockmod
from . import music
from . import script as S
from .common import FPS, W, ease_in_out, probe_duration, probe_size
from .presets import load_preset

EVENT_TYPES = ("label", "slam", "arrow", "flare", "event")
PLACEHOLDER_WPS = 2.6           # words per second used to time placeholder narration
CLOCK_D = 180
CLOCK_BOX = (W - 32 - CLOCK_D, 32, CLOCK_D)   # clock face bounding box: x, y, diameter (output px), top right


# ---------- timeline ----------
def _speeds(seg, n):
    base = float(seg.get("speed", 1.0))
    v = np.full(n, base)
    if seg.get("ramp_from") is not None:
        k = max(1, round(seg.get("ramp_in", 0.45) * FPS))
        for i in range(min(k, n)):
            v[i] = seg["ramp_from"] + (base - seg["ramp_from"]) * ease_in_out((i + 0.5) / k)
    if seg.get("ramp_to") is not None:
        k = max(1, round(seg.get("ramp_out", 0.45) * FPS))
        for j in range(min(k, n)):
            i = n - k + j
            v[i] = base + (seg["ramp_to"] - base) * ease_in_out((j + 0.5) / k)
    return v


def capture_timeline(seg):
    """Per-frame dicts (raw_t, speed, clock_t, clock_rate, badge, kind) for one capture segment."""
    n, mode, zero = seg["frames"], seg["mode"], float(seg.get("clock_zero", 0.0))
    if mode == "HOLD":
        return [dict(raw_t=seg["raw_in"], speed=0.0, clock_t=max(0.0, seg["raw_in"] - zero), clock_rate=0.0,
                     badge="PAUSED", kind="PAUSED") for _ in range(n)]
    v = _speeds(seg, n)
    raw = seg["raw_in"] + np.concatenate([[0.0], np.cumsum(v)[:-1]]) / FPS
    if mode in ("HUMAN", "WAIT"):
        return [dict(raw_t=float(raw[i]), speed=float(v[i]), clock_t=max(0.0, float(raw[i]) - zero),
                     clock_rate=float(v[i]), badge=clockmod.badge_text(mode, v[i]),
                     kind=clockmod.badge_kind(mode, v[i])) for i in range(n)]
    c0 = (seg["cut_from"] - zero) if mode == "CUT" else float(seg.get("reset_from_clock") or 0.0)
    c1 = max(0.0, float(raw[-1] + v[-1] / FPS) - zero)
    rows, prev = [], c0
    for i in range(n):
        c = c0 + (c1 - c0) * ease_in_out((i + 1) / n)
        rate, prev = (c - prev) * FPS, c
        badge = clockmod.badge_text("CUT", 1, seg["raw_in"] - seg["cut_from"]) if mode == "CUT" else "0:00"
        rows.append(dict(raw_t=float(raw[i]), speed=float(v[i]), clock_t=max(0.0, c), clock_rate=rate, badge=badge,
                         kind=mode))
    return rows


def load_project(project_dir):
    """edl.json + project.toml (preset, title) + script.txt of a project folder, as one dict."""
    project_dir = Path(project_dir)
    edl = json.loads((project_dir / "edl.json").read_text())
    meta_path = project_dir / "project.toml"
    meta = tomllib.loads(meta_path.read_text()) if meta_path.exists() else {}
    edl.setdefault("preset", meta.get("preset", "bay"))
    edl.setdefault("title", meta.get("title", project_dir.name))
    edl["script_lines"] = S.load_script(project_dir)
    edl["script"] = dict(edl["script_lines"])
    return edl


def placeholder_duration(text):
    return len(S.words(text)) / PLACEHOLDER_WPS + 0.3


def _resolve_audio(edl, project_dir, placeholder_audio):
    au = edl.setdefault("audio", {})
    notes = edl.setdefault("notes", [])
    for v in au.get("vo", []):
        if v["id"] not in edl["script"]:
            raise ValueError(f"edit list VO {v['id']} has no line in script.txt")
        path = Path(project_dir) / (v.get("file") or f"audio/vo/{v['id']}.wav")
        if path.exists():
            v["file"] = str(path)
            v["dur"] = round(probe_duration(path) / v.get("stretch", 1.0), 4)
        elif placeholder_audio:
            v["file"] = None
            v["placeholder"] = True
            v["dur"] = round(placeholder_duration(edl["script"][v["id"]]), 4)
        else:
            raise FileNotFoundError(f"narration {path} missing; run `promo-video voice {project_dir}` "
                                    "(paid) or render with --placeholder-audio")
    kept = []
    for m in au.get("music", []):
        path = Path(project_dir) / m["file"] if m.get("file") else music.cue_file(project_dir, m.get("cue", ""))
        if path is not None and Path(path).exists():
            m["file"] = str(path)
            kept.append(m)
        elif placeholder_audio:
            notes.append(f"music cue {m.get('cue') or m.get('file')} not generated: left out (placeholder audio)")
        else:
            raise FileNotFoundError(f"music cue {m.get('cue') or m.get('file')} missing; run "
                                    f"`promo-video music {project_dir}` (paid) or render with --placeholder-audio")
    au["music"] = kept


def resolve(edl, project_dir, placeholder_audio=False):
    """Fill start/frames/raw_out/change_points and narration durations; return the per-frame log rows."""
    project_dir = Path(project_dir)
    log, frame0, last_raw, last_clock = [], 0, None, 0.0
    edl.setdefault("max_shot_s", load_preset(edl.get("preset", "bay")).max_shot_s)
    for seg in edl["segments"]:
        if seg.get("reset_from_clock") == "prev":
            seg["reset_from_clock"] = round(last_clock, 4)
        if seg.get("cut_from") == "prev":
            seg["cut_from"] = last_raw
        if seg.get("raw_in") == "prev":
            seg["raw_in"] = last_raw
        if seg.get("jump") is not None and seg.get("mode") == "CUT":
            seg["raw_in"] = round(seg["cut_from"] + seg["jump"], 4)
        seg["frames"] = n = max(1, round(seg["dur"] * FPS))
        seg["start"] = round(frame0 / FPS, 4)
        ovs = list(seg.get("overlays", []))
        if seg.get("label"):
            ovs.insert(0, dict(type="label", text=seg["label"], t0=seg.get("label_t0", 0.0), t1=seg["dur"]))
        for a in (seg.get("arrows") or ([seg["arrow"]] if seg.get("arrow") else [])):
            extra = {k: a[k] for k in a if k not in ("t0", "t1")}
            ovs.append(dict(type="arrow", t0=a.get("t0", 0.0), t1=a.get("t1", seg["dur"]), **extra))
        seg["_ovs"] = ovs
        cps = {0.0}
        cps.update(k[0] for k in (seg.get("crop_keys") or []))
        cps.update(o.get("t0", 0.0) for o in ovs if o["type"] in EVENT_TYPES and 0 <= o.get("t0", 0.0) < seg["dur"])
        cps.update(seg.get("events", []))
        if seg["kind"] == "graphic":
            beat = seg.get("params", {}).get("beat")
            if beat:
                cps.update(i * beat for i in range(len(seg.get("params", {}).get("lines", []))))
        seg["change_points"] = sorted(round(c, 3) for c in cps if c < seg["dur"])
        vis = False
        if seg["kind"] == "capture":
            src = project_dir / seg["source"]
            if src.exists() and "src_size" not in seg:
                seg["src_size"] = list(probe_size(src))
            rows = capture_timeline(seg)
            seg["raw_out"] = round(rows[-1]["raw_t"] + rows[-1]["speed"] / FPS, 4)
            last_raw = seg["raw_out"]
            last_clock = rows[-1]["clock_t"] + rows[-1]["clock_rate"] / FPS
            seg["clock_rate"] = 0.0 if seg["mode"] == "HOLD" else seg.get("speed", 1.0)
            vis = bool(seg.get("clock", False))
        elif seg["kind"] in ("graphic", "black"):
            rows = [dict(raw_t="", speed="", clock_t="", clock_rate="", badge="", kind="") for _ in range(n)]
        else:
            raise ValueError(f"segment {seg['id']}: unknown kind {seg['kind']!r} (graphic, black, capture)")
        for i, r in enumerate(rows):
            log.append(dict(frame=frame0 + i, seg=seg["id"], mode=seg.get("mode", seg["kind"].upper()),
                            clock_visible=int(vis), clock_box=",".join(map(str, CLOCK_BOX)) if vis else "",
                            **{k: r[k] for k in ("raw_t", "speed", "clock_t", "clock_rate", "badge")}))
        seg["_rows"] = rows
        frame0 += n
    edl["total"] = round(frame0 / FPS, 4)
    _resolve_audio(edl, project_dir, placeholder_audio)
    return log


def save(edl, path, log):
    """Write the resolved edit list (json) and its per-frame log (<name>.frames.tsv) side by side."""
    clean = json.loads(json.dumps({k: v for k, v in edl.items() if k != "script_lines"}, default=str))
    for seg in clean["segments"]:
        seg.pop("_ovs", None)
        seg.pop("_rows", None)
    path = str(path)
    log_path = (path[:-len(".edl.json")] if path.endswith(".edl.json") else os.path.splitext(path)[0]) + ".frames.tsv"
    clean["frames_log"] = os.path.basename(log_path)
    with open(path, "w") as f:
        json.dump(clean, f, indent=1)
    with open(log_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(log[0].keys()), delimiter="\t")
        w.writeheader()
        for r in log:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
