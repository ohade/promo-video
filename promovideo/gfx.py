"""Graphic primitives: labels, slam text, red arrows, flare, glitch, shake, whip blur, 3D tilt, meter, flash."""
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .common import H, W, ease_out, ease_out_back, font

ORANGE = (255, 128, 16)
TEAL = (0, 150, 160)
RED = (235, 30, 35)
WHITE = (255, 255, 255)


def red_arrow(d, tip, tail, scale=1.0):
    """Red arrow with a dark outline from tail to tip (output pixel coordinates)."""
    tx, ty = tip
    sx, sy = tail
    ang = math.atan2(ty - sy, tx - sx)
    L, Wd = 34 * scale, 19 * scale
    bx, by = tx - L * math.cos(ang), ty - L * math.sin(ang)
    for col, w in (((0, 0, 0, 210), int(16 * scale)), (RED + (255,), int(10 * scale))):
        d.line([(sx, sy), (bx, by)], fill=col, width=max(2, w))
    px, py = -math.sin(ang), math.cos(ang)
    tri = [(tx, ty), (bx + px * Wd, by + py * Wd), (bx - px * Wd, by - py * Wd)]
    d.polygon(tri, fill=RED + (255,), outline=(0, 0, 0, 230))


def slam_text(img, text, center, size, age, fnt="cond", color=WHITE, underline=True, metallic=False,
              slam_dur=0.18, alpha=1.0):
    """Kinetic text that slams in from 1.8x scale over slam_dur seconds; orange underline grows after impact."""
    if age < 0 or alpha <= 0:
        return
    f = font(fnt, size)
    tmp = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    left, top, right, bottom = tmp.textbbox((0, 0), text, font=f)
    tw, th = right - left, bottom - top
    layer = Image.new("RGBA", (tw + 40, th + 60), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if metallic:
        mask = Image.new("L", layer.size, 0)
        ImageDraw.Draw(mask).text((20 - left, 20 - top), text, font=f, fill=255)
        grad = np.zeros((layer.height, layer.width, 4), np.uint8)
        ys = np.linspace(0, 1, layer.height)[:, None]
        band = 0.5 + 0.5 * np.cos((ys - 0.45) * 7.0)
        for k, (lo, hi) in enumerate(((150, 255), (155, 250), (165, 255))):
            grad[..., k] = (lo + (hi - lo) * band).astype(np.uint8)
        grad[..., 3] = 255
        g = Image.fromarray(grad, "RGBA")
        g.putalpha(mask)
        shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).text((24 - left, 26 - top), text, font=f, fill=(0, 0, 0, 200))
        layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4)))
        layer.alpha_composite(g)
    else:
        ld.text((23 - left, 24 - top), text, font=f, fill=(0, 0, 0, 170))
        ld.text((20 - left, 20 - top), text, font=f, fill=color + (255,))
    if underline:
        grow = ease_out((age - slam_dur * 0.6) / 0.25)
        if grow > 0:
            uw = int(tw * grow)
            ld.rectangle([20, th + 30, 20 + uw, th + 30 + max(4, size // 14)], fill=ORANGE + (255,))
    k = ease_out_back(age / slam_dur) if age < slam_dur else 1.0
    scale = 1.8 - 0.8 * k
    if abs(scale - 1) > 1e-3:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.BILINEAR)
    if alpha < 1:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer.putalpha(a)
    img.alpha_composite(layer, (int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)))


def label(img, text, pos, age, size=46):
    """Shot label (<= 6 words): condensed caps on a dark plate with an orange underline; slams in."""
    if age < 0:
        return
    text = text.upper()
    f = font("cond", size)
    tmp = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    left, top, right, bottom = tmp.textbbox((0, 0), text, font=f)
    tw, th = right - left, bottom - top
    plate = Image.new("RGBA", (tw + 44, th + 40), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    pd.rectangle([0, 0, plate.width, plate.height], fill=(8, 12, 16, 205))
    pd.text((22 - left, 16 - top), text, font=f, fill=WHITE + (255,))
    grow = ease_out((age - 0.08) / 0.22)
    pd.rectangle([0, plate.height - 6, int(plate.width * grow), plate.height], fill=ORANGE + (255,))
    k = ease_out_back(age / 0.16) if age < 0.16 else 1.0
    s = 1.5 - 0.5 * k
    if abs(s - 1) > 1e-3:
        plate = plate.resize((int(plate.width * s), int(plate.height * s)), Image.BILINEAR)
    x, y = pos
    if x < 0:
        x = W + x - plate.width
    img.alpha_composite(plate, (int(x), int(y - (plate.height - th - 40) / 2)))


def flare(img, cx, cy, strength=1.0, length=1400):
    """Anamorphic lens streak: a thin bright horizontal line with teal/orange halo, added on top."""
    if strength <= 0:
        return
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for half_h, col, a in ((26, TEAL, 70), (12, ORANGE, 110), (3, (255, 245, 230), 255)):
        d.ellipse([cx - length / 2, cy - half_h, cx + length / 2, cy + half_h], fill=col + (int(a * strength),))
    d.ellipse([cx - 60, cy - 60, cx + 60, cy + 60], fill=(255, 240, 220, int(160 * strength)))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(6)))


def glitch(arr, amount, seed=0):
    """RGB split plus random horizontal slice displacement. arr: (H, W, 3) uint8."""
    if amount <= 0:
        return arr
    rnd = random.Random(seed)
    out = arr.copy()
    sh = int(6 + 34 * amount)
    out[..., 0] = np.roll(arr[..., 0], -sh, axis=1)
    out[..., 2] = np.roll(arr[..., 2], sh, axis=1)
    for _ in range(int(4 + 10 * amount)):
        y0 = rnd.randrange(0, arr.shape[0] - 20)
        hh = rnd.randrange(8, 60)
        out[y0:y0 + hh] = np.roll(out[y0:y0 + hh], rnd.randrange(-120, 120), axis=1)
    return out


def shake_offset(t, amp, seed=0):
    rnd = random.Random(int(t * 30) + seed * 1000)
    return int(rnd.uniform(-amp, amp)), int(rnd.uniform(-amp, amp))


def apply_shake(arr, dx, dy):
    return np.roll(np.roll(arr, dy, axis=0), dx, axis=1)


def whip_blur(arr, dx):
    """Horizontal motion blur of length |dx| px plus a shift by dx (whip pan)."""
    k = int(abs(dx))
    if k < 2:
        return arr
    a = arr.astype(np.float32)
    c = np.cumsum(np.pad(a, ((0, 0), (k, 0), (0, 0)), mode="edge"), axis=1)
    blur = (c[:, k:] - c[:, :-k]) / k
    blur = np.roll(blur, int(dx / 2), axis=1)
    return blur.clip(0, 255).astype(np.uint8)


def perspective_coeffs(dst, src):
    """Coefficients for PIL Image.transform(PERSPECTIVE) mapping output points dst to input points src."""
    m = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        m.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        m.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    A = np.array(m, float)
    b = np.array(src, float).reshape(8)
    return np.linalg.solve(A, b).tolist()


def tilt_card(src_img, center, height, yaw_deg, pitch_deg=0.0):
    """Place src_img as a 3D-tilted card (rotation about the vertical axis by yaw, about x by pitch).
    Returns (RGBA layer W x H, quad corners in output px)."""
    w0, h0 = src_img.size
    hh = height / 2
    ww = hh * w0 / h0
    f = 1600.0
    pts = []
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    for x, y in ((-ww, -hh), (ww, -hh), (ww, hh), (-ww, hh)):
        X = x * math.cos(yaw)
        Z = x * math.sin(yaw)
        Y = y * math.cos(pitch) - Z * math.sin(pitch)
        Z = Z * math.cos(pitch) + y * math.sin(pitch)
        s = f / (f + Z)
        pts.append((center[0] + X * s, center[1] + Y * s))
    coeffs = perspective_coeffs(pts, [(0, 0), (w0, 0), (w0, h0), (0, h0)])
    src = src_img.convert("RGBA")
    layer = src.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    layer.putalpha(mask)
    return layer, pts


def teal_orange_bg(t, seed=0):
    """Dark teal-orange graphic background with a slow drifting orange glow."""
    ys, xs = np.mgrid[0:H:4, 0:W:4]
    gx = W * (0.7 + 0.08 * math.sin(t * 0.7 + seed))
    gy = H * (0.35 + 0.05 * math.cos(t * 0.5 + seed))
    dist = np.sqrt((xs - gx) ** 2 + (ys - gy) ** 2) / W
    glow = np.exp(-dist * 4.0)[..., None]
    base = np.array([4, 22, 28], np.float32) * (1 - ys[..., None] / H * 0.6)
    col = base + glow * np.array([120, 55, 8], np.float32)
    small = Image.fromarray(col.clip(0, 255).astype(np.uint8), "RGB")
    return small.resize((W, H), Image.BILINEAR).convert("RGBA")


def meter(img, frac, age, label_text="PROGRESS"):
    """Horizontal meter with a label that slams in; fill shifts orange -> red as frac -> 1."""
    if age < 0:
        return
    k = ease_out_back(age / 0.2) if age < 0.2 else 1.0
    x0, x1 = 360, 1560
    yc = 600
    hgt = int(90 * (0.4 + 0.6 * k))
    d = ImageDraw.Draw(img)
    slam_text(img, label_text, (960, 430), 120, age, underline=False)
    d.rectangle([x0 - 8, yc - hgt // 2 - 8, x1 + 8, yc + hgt // 2 + 8], outline=(230, 230, 230, 255), width=5)
    frac = max(0.0, min(1.0, frac))
    fill_w = int((x1 - x0) * frac)
    if fill_w > 0:
        col = tuple(int(ORANGE[i] + (RED[i] - ORANGE[i]) * frac ** 2) for i in range(3))
        d.rectangle([x0, yc - hgt // 2, x0 + fill_w, yc + hgt // 2], fill=col + (255,))
        for sx in range(x0 + 30, x0 + fill_w, 60):
            d.line([(sx, yc - hgt // 2), (sx - 30, yc + hgt // 2)], fill=(255, 255, 255, 40), width=10)
    pct = f"{int(round(frac * 100))}%"
    pf = font("cond", 96)
    pw = d.textlength(pct, font=pf)
    d.text((960 - pw / 2, yc + 80), pct, font=pf, fill=(255, 255, 255, 255) if frac < 0.98 else RED + (255,))


def flash(arr, amount):
    if amount <= 0:
        return arr
    return (arr.astype(np.float32) * (1 - amount) + 255 * amount).astype(np.uint8)

