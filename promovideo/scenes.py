"""Generic graphic scenes for `kind: graphic` segments. Each takes a context dict and returns an RGBA W x H image.

ctx: t (segment time, s), dur, params (segment "params"), project (Path), frame_no.
Scenes: title, card, meter, intertitle, image, tilt. Register more with @register("name")."""
import math
from pathlib import Path

from PIL import Image, ImageDraw

from . import gfx
from .common import H, W, ease_in_out, font

SCENES = {}


def register(name):
    def deco(fn):
        SCENES[name] = fn
        return fn
    return deco


@register("title")
def title(ctx):
    """Metallic slam title over the teal-orange background, a flare sweep, optional sub line. params: text, sub."""
    p, t = ctx["params"], ctx["t"]
    img = gfx.teal_orange_bg(t, p.get("seed", 0))
    gfx.slam_text(img, p.get("text", ""), (W / 2, H * 0.43), p.get("size", 200), t - 0.05, metallic=True,
                  underline=False)
    k = (t - 0.15) / 0.8
    if 0 <= k < 1:
        gfx.flare(img, -300 + (W + 600) * k, H * 0.43, strength=math.sin(math.pi * k))
    if p.get("sub"):
        gfx.slam_text(img, p["sub"].upper(), (W / 2, H * 0.64), p.get("sub_size", 64), t - p.get("sub_t0", 0.8))
    return img


@register("card")
def card(ctx):
    """Kinetic list: each line slams in on its beat, stacked and centred. params: lines, beat (s), size."""
    p, t = ctx["params"], ctx["t"]
    img = gfx.teal_orange_bg(t, p.get("seed", 1))
    lines = p.get("lines", [])
    size, beat = p.get("size", 110), p.get("beat", 1.0)
    gap = size * 1.45
    y0 = H / 2 - gap * (len(lines) - 1) / 2
    for i, text in enumerate(lines):
        gfx.slam_text(img, text, (W / 2, y0 + i * gap), size, t - i * beat)
    return img


@register("meter")
def meter(ctx):
    """A labelled meter filling from params.from to params.to over the segment (eased)."""
    p, t = ctx["params"], ctx["t"]
    img = gfx.teal_orange_bg(t, p.get("seed", 2))
    frac = p.get("from", 0.0) + (p.get("to", 1.0) - p.get("from", 0.0)) * ease_in_out(t / max(1e-6, ctx["dur"]))
    gfx.meter(img, frac, t, p.get("label", "PROGRESS"))
    return img


@register("intertitle")
def intertitle(ctx):
    """Thin, letter-spaced white caps on black that fade in and out. params: text, sub, size, fade (s)."""
    p, t, dur = ctx["params"], ctx["t"], ctx["dur"]
    fade = p.get("fade", 0.8)
    alpha = min(1.0, t / fade, (dur - t) / fade) if fade > 0 else 1.0
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    d = ImageDraw.Draw(img)
    for text, size, y in ((p.get("text", ""), p.get("size", 72), H * 0.47), (p.get("sub", ""), 30, H * 0.57)):
        if not text:
            continue
        f = font("thin", size)
        spacing = size * 0.35
        chars = list(text.upper())
        widths = [d.textlength(c, font=f) for c in chars]
        x = W / 2 - (sum(widths) + spacing * (len(chars) - 1)) / 2
        a = int(255 * max(0.0, alpha))
        for c, cw in zip(chars, widths, strict=True):
            d.text((x, y - size / 2), c, font=f, fill=(235, 238, 242, a))
            x += cw + spacing
    return img


_images = {}


@register("image")
def image(ctx):
    """A still (params.file, relative to the project) filling the frame with a slow eased push-in (params.push)."""
    p, t = ctx["params"], ctx["t"]
    path = Path(ctx["project"]) / p["file"]
    if path not in _images:
        _images[path] = Image.open(path).convert("RGBA")
    src = _images[path]
    scale = max(W / src.width, H / src.height) * (1 + p.get("push", 0.06) * ease_in_out(t / max(1e-6, ctx["dur"])))
    w, h = int(src.width * scale), int(src.height * scale)
    big = src.resize((w, h), Image.BICUBIC)
    left, top = (w - W) // 2, (h - H) // 2
    return big.crop((left, top, left + W, top + H))


@register("tilt")
def tilt(ctx):
    """A still (params.file) as a 3D-tilted card over the background, yaw easing from params.yaw_from to yaw_to."""
    p, t = ctx["params"], ctx["t"]
    path = Path(ctx["project"]) / p["file"]
    if path not in _images:
        _images[path] = Image.open(path).convert("RGBA")
    k = ease_in_out(t / max(1e-6, ctx["dur"]))
    yaw = p.get("yaw_from", -28) + (p.get("yaw_to", -12) - p.get("yaw_from", -28)) * k
    img = gfx.teal_orange_bg(t, p.get("seed", 3))
    layer, _ = gfx.tilt_card(_images[path], (W / 2, H / 2), p.get("height", H * 0.72), yaw, p.get("pitch", 6))
    img.alpha_composite(layer)
    return img
