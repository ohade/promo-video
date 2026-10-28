"""Analog clock overlay: minute ring 0-60, minute hand (one turn per hour), second hand, mode badge.

Trails: each hand leaves ghost copies covering TRAIL_S seconds of its own angular travel, so the trail length
is proportional to its angular speed (rate x the hand's base speed)."""
import math

from PIL import Image, ImageDraw, ImageFilter

from .common import font

SS = 2            # supersampling factor
TRAIL_S = 0.4     # seconds of travel shown as a trail
STYLES = {
    "bay": dict(face_in=(222, 226, 232), face_out=(120, 126, 136), bezel=(70, 74, 82), glow=(255, 130, 20),
                tick=(25, 28, 34), hand=(20, 22, 26), second=(230, 30, 30), numeral=(30, 33, 40),
                badge={"LIVE": ((0, 170, 170), (0, 0, 0)), "SLOW-MO": ((0, 200, 210), (0, 0, 0)),
                       "WAIT": ((255, 140, 20), (0, 0, 0)), "PAUSED": ((235, 235, 235), (0, 0, 0)),
                       "CUT": ((230, 30, 30), (255, 255, 255)), "RESET": ((230, 30, 30), (255, 255, 255))}),
    "nolan": dict(face_in=(196, 202, 210), face_out=(128, 136, 146), bezel=(60, 66, 74), glow=None,
                  tick=(30, 34, 40), hand=(24, 26, 30), second=(200, 30, 30), numeral=(40, 44, 50),
                  badge={"LIVE": ((230, 230, 230), (0, 0, 0)), "SLOW-MO": ((200, 210, 225), (0, 0, 0)),
                         "WAIT": ((150, 170, 195), (0, 0, 0)), "PAUSED": ((240, 240, 240), (0, 0, 0)),
                         "CUT": ((200, 30, 30), (255, 255, 255)), "RESET": ((200, 30, 30), (255, 255, 255))}),
}


def badge_text(mode, speed, jump=None):
    if mode == "HOLD":
        return "PAUSED"
    if mode == "CUT":
        return f"+{int(round(jump))} s"
    if mode == "RESET":
        return "0:00"
    if speed < 0.999:
        return "SLOW-MO"
    if speed <= 1.001:
        return "LIVE"
    return f"x{int(round(speed))}"


def badge_kind(mode, speed):
    if mode in ("HOLD", "CUT", "RESET"):
        return {"HOLD": "PAUSED"}.get(mode, mode)
    if speed < 0.999:
        return "SLOW-MO"
    return "LIVE" if speed <= 1.001 else "WAIT"


def _hand(d, c, r_len, r_tail, ang_deg, width, color):
    a = math.radians(ang_deg - 90)
    x1, y1 = c + r_len * math.cos(a), c + r_len * math.sin(a)
    x0, y0 = c - r_tail * math.cos(a), c - r_tail * math.sin(a)
    d.line([(x0, y0), (x1, y1)], fill=color, width=width)


def render_clock(clock_t, rate, mode, badge, style="bay", diameter=180):
    """Return an RGBA image: clock face on the right, badge on its left. clock_t in seconds, rate = clock s per s."""
    st = STYLES[style]
    D = diameter * SS
    pad = 18 * SS
    face = Image.new("RGBA", (D + 2 * pad, D + 2 * pad), (0, 0, 0, 0))
    c = pad + D / 2
    if st["glow"]:
        g = Image.new("RGBA", face.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).ellipse([pad - 6 * SS, pad - 6 * SS, pad + D + 6 * SS, pad + D + 6 * SS],
                                  fill=st["glow"] + (210,))
        face.alpha_composite(g.filter(ImageFilter.GaussianBlur(9 * SS)))
    d = ImageDraw.Draw(face)
    d.ellipse([pad, pad, pad + D, pad + D], fill=st["bezel"] + (255,))
    steps = 14
    for i in range(steps):                         # radial chrome gradient
        f = i / (steps - 1)
        col = tuple(int(st["face_out"][k] + (st["face_in"][k] - st["face_out"][k]) * f) for k in range(3))
        inset = 7 * SS + f * (D * 0.42 - 7 * SS) * 0.55
        d.ellipse([pad + inset - f * 4 * SS, pad + inset - f * 6 * SS, pad + D - inset - f * 4 * SS,
                   pad + D - inset - f * 6 * SS], fill=col + (255,))
    r = D / 2 - 10 * SS
    for m in range(60):                            # minute ring with ticks
        a = math.radians(m * 6 - 90)
        major = m % 5 == 0
        r0 = r - (13 if major else 7) * SS
        d.line([(c + r0 * math.cos(a), c + r0 * math.sin(a)), (c + r * math.cos(a), c + r * math.sin(a))],
               fill=st["tick"] + (255,), width=(3 if major else 1) * SS)
    nf = font("cond", 15 * SS)
    for m in range(0, 60, 10):
        a = math.radians(m * 6 - 90)
        rr = r - 25 * SS
        txt = str(m)
        tw = d.textlength(txt, font=nf)
        pos = (c + rr * math.cos(a) - tw / 2, c + rr * math.sin(a) - 8 * SS)
        d.text(pos, txt, font=nf, fill=st["numeral"] + (255,))
    sec_ang = (clock_t % 60) * 6
    min_ang = (clock_t / 60.0) % 60 * 6
    trail_layer = Image.new("RGBA", face.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(trail_layer)
    for base_speed, ang, length, width, col in ((0.1, min_ang, r * 0.78, 7 * SS, st["hand"]),
                                                (6.0, sec_ang, r * 0.92, 3 * SS, st["second"])):
        sweep = min(330.0, abs(rate) * base_speed * TRAIL_S)
        n = int(min(28, sweep / 2.5))
        sign = 1 if rate >= 0 else -1
        for k in range(n, 0, -1):
            alpha = int(190 * (1 - k / (n + 1)) ** 1.3)
            _hand(td, c, length, 0, ang - sign * sweep * k / n, width, col + (alpha,))
    face.alpha_composite(trail_layer)
    _hand(d, c, r * 0.78, 14 * SS, min_ang, 7 * SS, st["hand"] + (255,))
    _hand(d, c, r * 0.92, 22 * SS, sec_ang, 3 * SS, st["second"] + (255,))
    d.ellipse([c - 7 * SS, c - 7 * SS, c + 7 * SS, c + 7 * SS], fill=st["second"] + (255,))
    face = face.resize((face.width // SS, face.height // SS), Image.LANCZOS)

    bf = font("cond", 40)
    kind = mode
    fill, ink = st["badge"].get(kind, st["badge"]["WAIT"])
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tw = int(tmp.textlength(badge, font=bf))
    bw, bh = tw + 28, 52
    out = Image.new("RGBA", (face.width + bw + 8, face.height), (0, 0, 0, 0))
    out.alpha_composite(face, (bw + 8, 0))
    bd = ImageDraw.Draw(out)
    by = face.height // 2 - bh // 2
    bd.rounded_rectangle([2, by + 3, bw + 2, by + bh + 3], 9, fill=(0, 0, 0, 150))
    bd.rounded_rectangle([0, by, bw, by + bh], 9, fill=fill + (245,))
    bd.text((14, by + 7), badge, font=bf, fill=ink + (255,))
    return out
