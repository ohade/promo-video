"""Render a resolved edit list: Python compositing per frame piped into ffmpeg, then the audio mix and mux."""
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import audio, gfx, report, scenes
from . import clock as clockmod
from . import frames as fr
from .common import FPS, H, W, ease_in_out
from .edl import CLOCK_BOX, CLOCK_D, load_project, resolve, save
from .presets import load_preset

_FACE_PAD = 18
BLUR_RADIUS = 12


def crop_at(seg, t):
    keys = seg.get("crop_keys")
    if not keys:
        return seg["crop"]
    if t <= keys[0][0]:
        return keys[0][1]
    for (ta, ba), (tb, bb) in zip(keys, keys[1:], strict=False):
        if t <= tb:
            e = ease_in_out((t - ta) / max(1e-6, tb - ta))
            return [ba[i] + (bb[i] - ba[i]) * e for i in range(4)]
    return keys[-1][1]


def seg_bbox(seg):
    boxes = [k[1] for k in (seg.get("crop_keys") or [])] or [seg["crop"]]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
    return [int(x0), int(y0), int(np.ceil(x1 - int(x0))), int(np.ceil(y1 - int(y0)))]


def blur_regions(raw, seg, raw_t, bbox):
    """Privacy blur on source regions BEFORE the crop: seg["blur"] holds [x, y, w, h] or [x, y, w, h, t0, t1]."""
    boxes = [b for b in seg.get("blur", []) if len(b) == 4 or b[4] <= raw_t < b[5]]
    if not boxes:
        return raw
    img = Image.fromarray(raw)
    for b in boxes:
        x0, y0 = max(0, int(b[0] - bbox[0])), max(0, int(b[1] - bbox[1]))
        x1, y1 = min(img.width, int(b[0] + b[2] - bbox[0])), min(img.height, int(b[1] + b[3] - bbox[1]))
        if x1 > x0 and y1 > y0:
            img.paste(img.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(BLUR_RADIUS)), (x0, y0))
    return np.asarray(img)


def _clock_layer(img, row, style):
    c = clockmod.render_clock(row["clock_t"], row["clock_rate"], row["kind"], row["badge"], style=style,
                              diameter=CLOCK_D)
    face_w = CLOCK_D + 2 * _FACE_PAD
    img.alpha_composite(c, (CLOCK_BOX[0] - _FACE_PAD - (c.width - face_w), CLOCK_BOX[1] - _FACE_PAD))


def _raw_to_out(pt, box):
    return ((pt[0] - box[0]) / box[2] * W, (pt[1] - box[1]) / box[3] * H)


def _overlays(img, seg, t, box, bars=0):
    d = ImageDraw.Draw(img)
    for o in seg["_ovs"]:
        if not (o.get("t0", 0.0) <= t < o.get("t1", seg["dur"])):
            continue
        age = t - o.get("t0", 0.0)
        if o["type"] == "label":
            gfx.label(img, o["text"], o.get("pos", (60, 940 - bars)), age, size=o.get("size", 46))
        elif o["type"] == "arrow":
            tip, tail = o["tip"], o["tail"]
            if o.get("space", "raw") == "raw" and box is not None:
                tip, tail = _raw_to_out(tip, box), _raw_to_out(tail, box)
            grow = min(1.0, age / 0.15)
            tail = (tip[0] + (tail[0] - tip[0]) * grow, tip[1] + (tail[1] - tip[1]) * grow)
            gfx.red_arrow(d, tip, tail, o.get("scale", 1.3))
        elif o["type"] == "slam":
            gfx.slam_text(img, o["text"], o.get("center", (960, 540)), o.get("size", 120), age,
                          fnt=o.get("font", "cond"), metallic=o.get("metallic", False),
                          underline=o.get("underline", True))
        elif o["type"] == "flare":
            k = age / o.get("dur", 0.6)
            if k < 1:
                gfx.flare(img, -300 + (W + 600) * k, o.get("y", 540), strength=np.sin(np.pi * k))


def _post_fx(arr, seg, t, frame_no):
    n_t = seg["dur"]
    for o in seg["_ovs"]:
        typ, t0, dur = o["type"], o.get("t0", 0.0), o.get("dur", 0.3)
        if typ == "whip_in" and t < dur:
            arr = gfx.whip_blur(arr, -260 * (1 - t / dur) ** 2 * o.get("dir", 1))
        elif typ == "whip_out" and t > n_t - dur:
            arr = gfx.whip_blur(arr, 260 * ((t - (n_t - dur)) / dur) ** 2 * o.get("dir", 1))
        elif typ == "shake" and t0 <= t < t0 + dur:
            arr = gfx.apply_shake(arr, *gfx.shake_offset(t, o.get("amp", 24) * (1 - (t - t0) / dur), frame_no))
        elif typ == "glitch" and t0 <= t < t0 + dur:
            arr = gfx.glitch(arr, o.get("amount", 1.0), seed=frame_no)
        elif typ == "flash" and t0 <= t < t0 + dur:
            arr = gfx.flash(arr, o.get("amount", 0.85) * (1 - (t - t0) / dur))
    return arr


def render_video(edl, project_dir, out_path):
    look = load_preset(edl.get("preset", "bay")).look
    style, bars = look.get("clock_style", "bay"), int(edl.get("letterbox", look.get("letterbox", 0)))
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                            "-pix_fmt", "yuv420p", str(out_path)], stdin=subprocess.PIPE)
    frame_no = 0
    try:
        for seg in edl["segments"]:
            src = None
            if seg["kind"] == "capture":
                bbox = seg_bbox(seg)
                src = fr.fetch(Path(project_dir) / seg["source"], [r["raw_t"] for r in seg["_rows"]], bbox)
            for i in range(seg["frames"]):
                t, box = i / FPS, None
                if seg["kind"] == "capture":
                    raw = blur_regions(next(src), seg, seg["_rows"][i]["raw_t"], bbox)
                    box = crop_at(seg, t)
                    x, y = int(round(box[0] - bbox[0])), int(round(box[1] - bbox[1]))
                    sub = Image.fromarray(raw[y:y + int(round(box[3])), x:x + int(round(box[2]))])
                    img = sub.resize((W, H), Image.BICUBIC).convert("RGBA")
                elif seg["kind"] == "graphic":
                    img = scenes.SCENES[seg["scene"]](dict(t=t, dur=seg["dur"], seg=seg, params=seg.get("params", {}),
                                                           project=Path(project_dir), frame_no=frame_no))
                else:
                    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
                _overlays(img, seg, t, box, bars)
                arr = _post_fx(np.asarray(img.convert("RGB")), seg, t, frame_no)
                if bars:                                      # letterbox first: the clock sits on top, whole
                    arr = arr.copy()
                    arr[:bars], arr[H - bars:] = 0, 0
                if seg["kind"] == "capture" and seg.get("clock", False):
                    im2 = Image.fromarray(arr).convert("RGBA")
                    _clock_layer(im2, seg["_rows"][i], style)
                    arr = np.asarray(im2.convert("RGB"))
                enc.stdin.write(np.ascontiguousarray(arr).tobytes())
                frame_no += 1
            if src is not None:
                src.close()
    finally:
        enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("video encode failed")


def build(project_dir, out_mp4, placeholder_audio=False, log=print):
    """Resolve, save <out>.edl.json + frames log + .srt, render video and audio, mux. Returns the duration (s)."""
    project_dir, out_mp4 = Path(project_dir), Path(out_mp4)
    edl = load_project(project_dir)
    rows = resolve(edl, project_dir, placeholder_audio)
    base = str(out_mp4)[:-len(out_mp4.suffix)] if out_mp4.suffix else str(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    save(edl, base + ".edl.json", rows)
    report.write_srt(edl, base + ".srt")
    for note in edl.get("notes", []):
        log(f"NOTE {note}")
    with tempfile.TemporaryDirectory(prefix="promo-video-") as work:
        vid, wav = os.path.join(work, "video.mp4"), os.path.join(work, "mix.wav")
        render_video(edl, project_dir, vid)
        audio.mix_audio(edl, wav, project_dir)
        audio.loudnorm_mux(vid, wav, out_mp4, edl["total"])
    log(f"rendered {out_mp4} ({edl['total']:.2f} s); edit list {base}.edl.json")
    return edl["total"]
