"""Mechanical gate for a rendered promo. One PASS/FAIL/SKIP line per rule; exit 0 only when no rule fails.

Rules: (a) clocked capture frames: clock rate == footage speed, HUMAN <= 1, WAIT 8-60, HOLD frozen, CUT/RESET 0.3 s;
(b) no shot longer than the preset's max_shot_s without a change point; (c) every capture crop inside its source frame
and 16:9; (d) narration ids are the script lines once each, in order, no overlap, stretch within 8 %; (e) no forbidden
source window; (f) edit-list total == video duration within 0.1 s; (h) one clock box for every clocked frame, top right;
(g) optional: Whisper transcript of each narration window matches its line (word ratio >= 0.85), SKIP without whisper_url.
--self-test breaks a built-in sample once per rule (a)-(f), (h); each broken copy must FAIL. Standard library only."""
import copy
import csv
import json
import os
import subprocess
import tempfile
from pathlib import Path

from . import script as S

from .checksample import save_sample, sample_edl  # noqa: F401 (re-exported for callers and tests)
from .common import FPS, probe_duration


TOL = 0.01
MIX_MATCH = 0.85
CROP_ASPECT, ASPECT_TOL = 16 / 9, 0.02
NAMES = {"a": "clocked frames: clock rate == footage speed; HUMAN <= 1, WAIT 8-60, HOLD frozen, CUT/RESET 0.3 s",
         "b": "no shot longer than max_shot_s without a cut, crop change or new graphic",
         "c": "every capture crop inside its source frame and 16:9",
         "d": "narration: every script line once, in order, no overlap, stretch within 8 %",
         "e": "no forbidden source window",
         "f": "edit-list total == video duration within 0.1 s",
         "h": "one clock box for every clocked frame, top right (x >= 1500, y + d <= 300)"}


def badge_for(speed):
    if speed < 0.999:
        return "SLOW-MO"
    return "LIVE" if speed <= 1.001 else f"x{int(round(speed))}"


def rule_a(edl, rows):
    errs, by_seg = [], {}
    for r in rows:
        by_seg.setdefault(r["seg"], []).append(r)
    for seg in edl["segments"]:
        rs = by_seg.get(seg["id"], [])
        if len(rs) != seg["frames"]:
            errs.append(f"{seg['id']}: {len(rs)} logged frames != {seg['frames']}")
            continue
        clocked = seg["kind"] == "capture" and seg.get("clock", False)
        if not clocked:
            if any(r["clock_visible"] == "1" for r in rs):
                errs.append(f"{seg['id']}: clock shown on a segment without clock")
            if seg["kind"] == "capture" and seg.get("mode") not in ("HUMAN", "WAIT", "HOLD", "CUT", "RESET"):
                errs.append(f"{seg['id']}: unknown mode {seg.get('mode')}")
            continue
        mode, sp = seg["mode"], float(seg.get("speed", 0))
        if any(r["clock_visible"] != "1" for r in rs):
            errs.append(f"{seg['id']}: clocked capture frame without the clock")
        f = [{k: (float(r[k]) if k in ("raw_t", "speed", "clock_t", "clock_rate") else r[k]) for k in r} for r in rs]
        if mode == "HOLD":
            if any(x["speed"] != 0 or x["clock_rate"] != 0 or x["badge"] != "PAUSED" for x in f) or \
                    len({x["clock_t"] for x in f}) != 1:
                errs.append(f"{seg['id']}: HOLD must freeze the clock with badge PAUSED")
            continue
        if mode == "CUT":
            jump = seg["raw_in"] - seg["cut_from"]
            if abs(seg["frames"] / FPS - 0.3) > 1.01 / FPS or jump <= 0 or \
                    any(x["badge"] != f"+{int(round(jump))} s" for x in f):
                errs.append(f"{seg['id']}: CUT must last 0.3 s with badge +N s for a forward jump")
            continue
        if mode == "RESET":
            if abs(seg["frames"] / FPS - 0.3) > 1.01 / FPS:
                errs.append(f"{seg['id']}: RESET spin must last 0.3 s")
            continue
        if mode == "HUMAN" and sp > 1.0:
            errs.append(f"{seg['id']}: HUMAN speed {sp} > 1.0")
        if mode == "WAIT" and not 8 <= sp <= 60:
            errs.append(f"{seg['id']}: WAIT speed {sp} outside 8-60")
        if mode not in ("HUMAN", "WAIT"):
            errs.append(f"{seg['id']}: unknown mode {mode}")
        for key, src in (("ramp_in", "ramp_from"), ("ramp_out", "ramp_to")):
            if seg.get(src) is not None and not 0.3 <= seg.get(key, 0.45) <= 0.6:
                errs.append(f"{seg['id']}: {key} {seg.get(key)} outside 0.3-0.6 s")
        zero = float(seg.get("clock_zero", 0))
        for i, x in enumerate(f):
            if abs(x["clock_rate"] - x["speed"]) > TOL:
                errs.append(f"{seg['id']} frame {x['frame']}: clock_rate {x['clock_rate']} != speed {x['speed']}")
                break
            if x["badge"] != badge_for(x["speed"]):
                errs.append(f"{seg['id']} frame {x['frame']}: badge {x['badge']} for speed {x['speed']}")
                break
            if i + 1 < len(f):
                d_raw = f[i + 1]["raw_t"] - x["raw_t"]
                if abs(d_raw * FPS - x["speed"]) > 3 * TOL * max(1, x["speed"]):
                    errs.append(f"{seg['id']} frame {x['frame']}: footage advanced {d_raw * FPS:.3f}/frame, "
                                f"speed {x['speed']}")
                    break
                if x["raw_t"] >= zero and abs((f[i + 1]["clock_t"] - x["clock_t"]) - d_raw) > 2e-3:
                    errs.append(f"{seg['id']} frame {x['frame']}: clock advanced differently from the footage")
                    break
    return errs


def rule_b(edl, rows, max_shot_s):
    errs = []
    for seg in edl["segments"]:
        cps = sorted(c for c in seg.get("change_points", [0.0]) if 0 <= c < seg["dur"]) + [seg["frames"] / FPS]
        gap = max(b - a for a, b in zip([0.0] + cps[:-1], cps, strict=True))
        if gap > max_shot_s + 1e-6:
            errs.append(f"{seg['id']}: {gap:.2f} s without a cut, crop change or new graphic (max {max_shot_s:g} s)")
    return errs


def rule_c(edl, rows):
    errs = []
    for seg in edl["segments"]:
        if seg["kind"] != "capture":
            continue
        size = seg.get("src_size")
        if not size:
            errs.append(f"{seg['id']}: source size unknown ({seg.get('source')} missing?)")
            continue
        for b in [k[1] for k in (seg.get("crop_keys") or [])] or [seg.get("crop")]:
            if not b or b[2] <= 0 or b[3] <= 0 or b[0] < 0 or b[1] < 0 or b[0] + b[2] > size[0] + 0.5 or \
                    b[1] + b[3] > size[1] + 0.5:
                errs.append(f"{seg['id']}: crop {b} missing or outside the {size[0]}x{size[1]} source frame")
            elif abs(b[2] / b[3] / CROP_ASPECT - 1) > ASPECT_TOL:
                errs.append(f"{seg['id']}: crop {b} is not 16:9 (would distort)")
    return errs


def rule_d(edl, rows, ids):
    vo = edl.get("audio", {}).get("vo", [])
    got = [v["id"] for v in vo]
    errs = []
    if got != ids:
        errs.append(f"narration ids {got} != script ids {ids} (once each, in order)")
    order = sorted(vo, key=lambda v: v["start"])
    if [v["id"] for v in order] != got:
        errs.append("narration start times are not in script order")
    for a, b in zip(order, order[1:], strict=False):
        if a["start"] + a["dur"] > b["start"] + 1e-6:
            errs.append(f"{a['id']} overlaps {b['id']}")
    for v in vo:
        if abs(v.get("stretch", 1.0) - 1.0) > 0.08:
            errs.append(f"{v['id']}: stretch {v['stretch']} beyond 8 %")
        if v["start"] < 0 or v["start"] + v["dur"] > edl["total"] + 1e-6:
            errs.append(f"{v['id']}: outside the timeline")
    return errs


def rule_e(edl, rows):
    errs = []
    for seg in edl["segments"]:
        spans = []
        if seg["kind"] == "capture":
            spans.append((seg["source"], min(seg["raw_in"], seg["raw_out"]), max(seg["raw_in"], seg["raw_out"])))
        for src, t in seg.get("stills", []):
            spans.append((src, t, t))
        for src, a, b in spans:
            for fsrc, fa, fb in edl.get("forbidden", []):
                if src == fsrc and a <= fb and b >= fa:
                    errs.append(f"{seg['id']}: uses {src} {a:.1f}-{b:.1f}, forbidden {fa:g}-{fb:g}")
    return errs


def rule_f(edl, rows, duration):
    errs = []
    frames = sum(s["frames"] for s in edl["segments"])
    if abs(frames / FPS - edl["total"]) > 1e-3 or len(rows) != frames:
        errs.append(f"segment frames {frames} / log rows {len(rows)} disagree with total {edl['total']}")
    if abs(edl["total"] - duration) > 0.1:
        errs.append(f"edit-list total {edl['total']:.3f} != video duration {duration:.3f}")
    return errs


def rule_h(edl, rows):
    errs = []
    boxes = {r.get("clock_box", "") for r in rows if r["clock_visible"] == "1"}
    if len(boxes) > 1:
        errs.append(f"clocked frames use {len(boxes)} different clock boxes: {sorted(boxes)[:3]}")
    for b in boxes:
        try:
            x, y, d = (float(v) for v in b.split(","))
        except ValueError:
            errs.append(f"clock box {b!r} unreadable")
            continue
        if x < 1500 or y + d > 300 or x + d > 1920 or y < 0 or d > 190:
            errs.append(f"clock box {b} not inside x >= 1500, y + d <= 300 (diameter <= 190)")
    return errs


def run_rules(edl, rows, duration, max_shot_s=None):
    max_shot_s = max_shot_s or edl.get("max_shot_s") or 4.0
    ids = list(edl.get("script", {}))
    return {"a": rule_a(edl, rows), "b": rule_b(edl, rows, max_shot_s), "c": rule_c(edl, rows),
            "d": rule_d(edl, rows, ids), "e": rule_e(edl, rows), "f": rule_f(edl, rows, duration),
            "h": rule_h(edl, rows)}


def self_test():
    """Feed one broken copy of the sample per rule; each must FAIL. Returns (ok, lines); every line PASS when ok."""
    edl, rows = sample_edl()
    total, lines = edl["total"], []
    base = run_rules(edl, rows, total)
    ok = all(not v for v in base.values())
    lines.append(("PASS" if ok else "FAIL") + " self-test baseline: the unmodified sample passes rules a-f and h"
                 + ("" if ok else f" ({ {k: v[:1] for k, v in base.items() if v} })"))

    def seg(e, sid):
        return next(s for s in e["segments"] if s["id"] == sid)

    def broken_a():
        r = copy.deepcopy(rows)
        row = next(x for x in r if x["seg"] == "c2")
        row["clock_rate"] = str(float(row["speed"]) * 2 + 1)
        return edl, r, total

    def broken_b():
        e = copy.deepcopy(edl)
        s = seg(e, "g1")
        s["dur"], s["frames"], s["change_points"] = 5.0, 150, [0.0]
        return e, rows, total

    def broken_c_outside():
        e = copy.deepcopy(edl)
        seg(e, "c2")["crop"] = [1000, 600, 1280, 720]
        return e, rows, total

    def broken_c_aspect():
        e = copy.deepcopy(edl)
        seg(e, "c2")["crop"] = [0, 0, 1000, 1000]
        return e, rows, total

    def broken_d():
        e = copy.deepcopy(edl)
        e["audio"]["vo"].append(dict(e["audio"]["vo"][0]))
        return e, rows, total

    def broken_e():
        e = copy.deepcopy(edl)
        e["forbidden"] = [["footage/demo.mp4", 20.0, 25.0]]
        return e, rows, total

    def broken_f():
        return edl, rows, total + 1.0

    def broken_h():
        r = copy.deepcopy(rows)
        next(x for x in r if x["clock_visible"] == "1")["clock_box"] = "26,854,180"
        return edl, r, total

    for key, fn in (("a", broken_a), ("b", broken_b), ("c", broken_c_outside), ("c", broken_c_aspect),
                    ("d", broken_d), ("e", broken_e), ("f", broken_f), ("h", broken_h)):
        e, r, dur = fn()
        res = run_rules(e, r, dur)[key]
        ok &= bool(res)
        lines.append(("PASS" if res else "FAIL") + f" self-test ({key}, {fn.__name__}): broken copy "
                     + ("FAILED as expected: " + res[0] if res else "was NOT caught"))
    return ok, lines




def load(edl_path):
    edl = json.loads(Path(edl_path).read_text())
    with open(Path(edl_path).parent / edl["frames_log"]) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return edl, rows


def _extract(video, start, dur, out):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, start - 0.15):.3f}", "-t", f"{dur + 0.4:.3f}",
                    "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(out)], check=True)


def transcription(edl, video, whisper_url, transport, extract=None):
    """Rule (g): (errors, line). Without a whisper_url: no errors and one SKIP line."""
    if not whisper_url:
        return [], "SKIP (g) narration transcription: no whisper_url configured"
    extract = extract or _extract
    errs, notes = [], []
    with tempfile.TemporaryDirectory() as d:
        for v in edl["audio"]["vo"]:
            wav = os.path.join(d, v["id"] + ".wav")
            extract(video, v["start"], v["dur"], wav)
            try:
                heard = str(transport.post_file(whisper_url, wav, {"model": "whisper-1", "response_format": "json"},
                                                60).get("text", ""))
            except Exception as e:  # noqa: BLE001 - any transport failure is a FAIL line, not a crash
                errs.append(f"{v['id']}: no transcript ({e.__class__.__name__})")
                continue
            ratio = S.match_ratio(edl["script"][v["id"]], heard)
            notes.append(f"{v['id']}={ratio:.2f}")
            if ratio < MIX_MATCH:
                errs.append(f"{v['id']}: word ratio {ratio:.2f} heard {heard.strip()[:60]!r}")
    head = f"(g) Whisper matches each narration line >= {MIX_MATCH}: "
    return errs, ("FAIL " + head + "; ".join(errs[:5])) if errs else ("PASS " + head + " ".join(notes))


def rule_h_pixels(rows, video, samples=8):
    """Decode a few clocked frames: the inner disc of the clock box must be the light, low-saturation clock face."""
    clocked = [r for r in rows if r["clock_visible"] == "1"]
    if not clocked:
        return []
    errs = []
    x, y, d = (float(v) for v in clocked[0]["clock_box"].split(","))
    r, cx, cy = d * 0.18, x + d / 2, y + d / 2
    for k in range(samples):
        row = clocked[(len(clocked) - 1) * k // max(1, samples - 1)]
        t = max(0.0, (int(row["frame"]) - 0.1) / FPS)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.4f}", "-i", str(video), "-frames:v", "1", "-vf",
                              f"crop={int(2 * r)}:{int(2 * r)}:{int(cx - r)}:{int(cy - r)}", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        px = [raw[i:i + 3] for i in range(0, len(raw), 3)]
        light = sum(1 for p in px if min(p) > 150 and max(p) - min(p) < 40) / max(1, len(px))
        if light < 0.5:
            errs.append(f"frame {row['frame']}: clock face not found in the clock box ({light:.0%} light pixels)")
    return errs


def check_video(edl_path, video, whisper_url=None, transport=None, duration=None):
    """All rules against a rendered video and its resolved edit list. Returns (ok, lines)."""
    edl, rows = load(edl_path)
    duration = probe_duration(video) if duration is None else duration
    res = run_rules(edl, rows, duration)
    if not res["h"] and os.path.exists(str(video)):
        res["h"] = rule_h_pixels(rows, video)
    ok, lines = True, []
    for k, errs in res.items():
        ok &= not errs
        lines.append(("PASS" if not errs else "FAIL") + f" ({k}) {NAMES[k]}"
                     + ("" if not errs else ": " + "; ".join(errs[:5])))
    if whisper_url and transport is None:
        from .transport import UrllibTransport
        transport = UrllibTransport()
    errs, line = transcription(edl, video, whisper_url, transport)
    ok &= not errs
    lines.append(line)
    return ok, lines
