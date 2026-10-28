"""Procedural SFX (numpy, 48 kHz stereo float32): sub hit, impact, whoosh, riser, braam, glitch, pop, tick, flash hit,
low note. No samples, no API: sfx.render(name, **params) -> (n, 2) float32 array."""
import numpy as np

from .common import SR

_rng = np.random.default_rng(7)


def _t(dur):
    return np.arange(int(dur * SR)) / SR


def _stereo(x, pan=0.0):
    gl = np.cos((pan + 1) * np.pi / 4)
    gr = np.sin((pan + 1) * np.pi / 4)
    return np.stack([x * gl, x * gr], axis=1).astype(np.float32) * 1.414


def _onepole_lp(x, cutoff):
    """Time-varying one-pole low-pass; cutoff may be scalar or per-sample array (Hz)."""
    c = np.broadcast_to(np.asarray(cutoff, float), x.shape)
    a = np.exp(-2 * np.pi * c / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


def _norm(x, peak):
    m = np.max(np.abs(x)) or 1.0
    return x / m * peak


def sub_hit(dur=1.6, f0=72, f1=32, peak=0.95):
    t = _t(dur)
    freq = f1 + (f0 - f1) * np.exp(-t * 9)
    ph = 2 * np.pi * np.cumsum(freq) / SR
    env = np.exp(-t * 3.2) * np.minimum(1, t * 400)
    x = np.sin(ph) * env + 0.25 * np.tanh(3 * np.sin(ph)) * env
    click = _rng.standard_normal(len(t)) * np.exp(-t * 180) * 0.4
    return _stereo(_norm(x + click, peak))


def impact(dur=2.4, peak=0.95):
    t = _t(dur)
    n = _onepole_lp(_rng.standard_normal(len(t)), 900 * np.exp(-t * 3) + 120) * np.exp(-t * 4)
    ring = sum(np.sin(2 * np.pi * f * t) * np.exp(-t * d) for f, d in ((143, 2.5), (287, 3.5), (431, 5.0))) * 0.15
    sub = sub_hit(dur, 60, 30)[:, 0]
    return _stereo(_norm(sub * 0.8 + n * 1.6 + ring, peak))


def whoosh(dur=0.55, rising=True, pan_from=-0.7, pan_to=0.7, peak=0.7):
    t = _t(dur)
    x = t / dur
    shape = np.sin(np.pi * x) ** 2 if rising else np.exp(-x * 5) * np.minimum(1, x * 40)
    cut = 300 + 5200 * (np.sin(np.pi * x) ** 2)
    n = _onepole_lp(_rng.standard_normal(len(t)), cut) * shape
    pan = pan_from + (pan_to - pan_from) * x
    out = np.stack([n * np.cos((pan + 1) * np.pi / 4), n * np.sin((pan + 1) * np.pi / 4)], axis=1)
    return (_norm(out, peak)).astype(np.float32)


def riser(dur=1.6, peak=0.6):
    t = _t(dur)
    x = t / dur
    f = 180 * (2 ** (x * 3.5))
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.35
    n = _onepole_lp(_rng.standard_normal(len(t)), 400 + 7000 * x ** 2) * 0.8
    env = x ** 2.2
    return _stereo(_norm((tone + n) * env, peak))


def braam(dur=2.6, peak=0.85):
    t = _t(dur)
    env = np.minimum(1, t * 18) * np.exp(-t * 0.9)
    x = np.zeros_like(t)
    for f, det in ((55, 0.0), (55, 0.6), (82.4, -0.4), (110, 0.3)):
        ph = 2 * np.pi * (f + det) * t
        x += 2 * (ph / (2 * np.pi) % 1) - 1
    x = np.tanh(_onepole_lp(x, 300 + 1500 * np.exp(-t * 2.5)) * 2.5)
    return _stereo(_norm(x * env, peak))


def glitch(dur=0.7, peak=0.6, seed=3):
    rng = np.random.default_rng(seed)
    t = _t(dur)
    x = np.zeros_like(t)
    pos = 0
    while pos < len(t):
        seg = int(rng.uniform(0.015, 0.07) * SR)
        kind = rng.integers(0, 3)
        tt = t[: min(seg, len(t) - pos)]
        if kind == 0:
            x[pos:pos + len(tt)] = np.sign(np.sin(2 * np.pi * rng.uniform(200, 2400) * tt)) * 0.6
        elif kind == 1:
            x[pos:pos + len(tt)] = rng.standard_normal(len(tt)) * 0.7
        pos += seg
    x = np.round(x * 6) / 6
    return _stereo(_norm(x, peak))


def pop(dur=0.12, f=1400, peak=0.45):
    t = _t(dur)
    x = np.sin(2 * np.pi * f * t * (1 - t * 2)) * np.exp(-t * 40)
    return _stereo(_norm(x, peak))


def tick(dur=0.05, peak=0.5):
    t = _t(dur)
    noise = _onepole_lp(_rng.standard_normal(len(t)), 5000) * np.exp(-t * 300)
    x = noise + np.sin(2 * np.pi * 3200 * t) * np.exp(-t * 200)
    return _stereo(_norm(x, peak))


def flash_hit(dur=0.9, peak=0.8):
    """Short punchy hit for each step turning green: sub thump plus bright transient."""
    t = _t(dur)
    s = sub_hit(dur, 95, 45)[:, 0] * 0.8
    b = _onepole_lp(_rng.standard_normal(len(t)), 6000) * np.exp(-t * 35) * 0.6
    return _stereo(_norm(s + b, peak))


def low_note(dur=2.5, f=55.0, peak=0.7):
    """Deep soft note (Nolan act marks): sine plus a quiet octave, slow attack, long decay."""
    t = _t(dur)
    env = np.minimum(1, t * 6) * np.exp(-t * 1.4)
    x = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)
    return _stereo(_norm(x * env, peak))


LIB = {"sub_hit": sub_hit, "impact": impact, "whoosh": whoosh, "riser": riser, "braam": braam, "glitch": glitch,
       "pop": pop, "tick": tick, "flash_hit": flash_hit, "low_note": low_note}
_cache = {}


def render(name, **params):
    if name not in LIB:
        raise ValueError(f"unknown sfx {name!r}; known: {', '.join(sorted(LIB))}")
    key = (name, tuple(sorted(params.items())))
    if key not in _cache:
        _cache[key] = LIB[name](**params)
    return _cache[key]
