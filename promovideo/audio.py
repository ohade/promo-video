"""Mix narration, music and procedural SFX for a resolved edit list; duck music and SFX under the voice;
two-pass loudnorm to TARGET_LUFS with a limiter; keep the encoded true peak at or under TRUE_PEAK_CEILING_DB."""
import json
import subprocess

from .common import SR

TARGET_LUFS = -16.0
TRUE_PEAK_CEILING_DB = -1.3
LRA = 11
PROBE_TP_DB = -2.0
LOUDNORM_TP_DB = -2.5
LIMITER_LIMIT = 0.78
VO_DUCK_DB = 12.0
SFX_DUCK_DB = 10.0
MIX_PEAK = 0.98
DUCK_ATTACK_S, DUCK_RELEASE_S = 0.08, 0.3


def _num(x):
    return f"{x:g}"


def probe_filter():
    return f"loudnorm=I={_num(TARGET_LUFS)}:TP={PROBE_TP_DB:.1f}:LRA={LRA}:print_format=json"


def apply_filter(measured, limit):
    return (f"loudnorm=I={_num(TARGET_LUFS)}:TP={LOUDNORM_TP_DB:.1f}:LRA={LRA}:measured_I={measured['input_i']}:"
            f"measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}:"
            f"measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}:linear=true,"
            f"aresample={SR},alimiter=limit={limit:.3f}:level=disabled:attack=1:release=60")


def second_pass_limit(measured_peak_db, limit=LIMITER_LIMIT):
    """Limiter level for a second mux when the encoded AAC overshoots the ceiling (codec inter-sample peaks), else None."""
    excess = measured_peak_db - TRUE_PEAK_CEILING_DB
    if excess <= 0:
        return None
    return limit * 10 ** (-(excess + 0.2) / 20)


def _db(x):
    return 10 ** (x / 20.0)


def _place(buf, clip, start, gain=1.0):
    i0 = int(round(start * SR))
    if i0 >= len(buf):
        return
    if i0 < 0:
        clip, i0 = clip[-i0:], 0
    n = min(len(clip), len(buf) - i0)
    buf[i0:i0 + n] += clip[:n] * gain


def _env(n, spans, attack=DUCK_ATTACK_S, release=DUCK_RELEASE_S):
    """0..1 envelope: 1 inside spans, linear attack before and release after each span."""
    import numpy as np
    e = np.zeros(n, np.float32)
    for s, t in spans:
        a0, a1 = int((s - attack) * SR), int(s * SR)
        r0, r1 = int(t * SR), int((t + release) * SR)
        idx = np.arange(max(0, a0), min(n, r1))
        val = np.ones(len(idx), np.float32)
        up = idx < a1
        val[up] = (idx[up] - a0) / max(1, a1 - a0)
        dn = idx >= r0
        val[dn] = 1 - (idx[dn] - r0) / max(1, r1 - r0)
        e[idx] = np.maximum(e[idx], val)
    return e


def mix(spec, total, load, sfx_render=None):
    """Mix an edit list's audio section into a float32 (n, 2) buffer. load(path) -> (n, 2) array."""
    import numpy as np
    n = int(round(total * SR))
    vo, mus, fx = (np.zeros((n, 2), np.float32) for _ in range(3))
    spans = []
    for v in spec.get("vo", []):
        if v.get("file"):                                    # placeholder narration has no file: silence, still ducks
            _place(vo, load(v["file"]), v["start"], _db(spec.get("vo_gain_db", 0.0)))
        spans.append((v["start"], v["start"] + v["dur"]))
    for m in spec.get("music", []):
        clip = load(m["file"])
        a = int(m.get("src_in", 0.0) * SR)
        clip = clip[a:a + int(m["dur"] * SR)].copy()
        fi, fo = int(m.get("fade_in", 0.0) * SR), int(m.get("fade_out", 0.0) * SR)
        if fi:
            clip[:fi] *= np.linspace(0, 1, fi)[:, None]
        if fo:
            clip[-fo:] *= np.linspace(1, 0, fo)[:, None]
        _place(mus, clip, m["start"], _db(m.get("gain_db", 0.0)))
    for s in spec.get("sfx", []):
        _place(fx, sfx_render(s["name"], **s.get("params", {})), s["start"], _db(s.get("gain_db", 0.0)))
    duck = _env(n, spans)[:, None]
    mus *= _db(-spec.get("duck_db", VO_DUCK_DB) * duck)
    fx *= _db(-spec.get("sfx_duck_db", SFX_DUCK_DB) * duck)
    out = vo + mus + fx
    for s, t in spec.get("silence", []):
        out[int(s * SR):int(t * SR)] = 0
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > MIX_PEAK:
        out *= MIX_PEAK / peak
    return out


def mix_audio(edl, out_wav, project_dir):
    from . import sfx
    from .common import read_audio, write_wav
    write_wav(out_wav, mix(edl.get("audio", {}), edl["total"], read_audio, sfx.render))


def true_peak_db(path):
    """True peak (dBFS) of a file's audio, measured by ffmpeg ebur128 (4x oversampled)."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f",
                          "null", "-"], capture_output=True, text=True).stderr
    return float(err[err.rindex("Peak:"):].split()[1])


def _mux(video, wav, out_mp4, total, af):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(wav), "-map", "0:v", "-map", "1:a",
                    "-af", af, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-ac", "2",
                    "-t", f"{total:.4f}", "-movflags", "+faststart", str(out_mp4)], check=True)


def loudnorm_mux(video, wav, out_mp4, total):
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af", probe_filter(), "-f", "null",
                            "-"], capture_output=True, text=True).stderr
    measured = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    if measured.get("input_i") in ("-inf", "inf"):           # silent mix: nothing to normalise
        _mux(video, wav, out_mp4, total, f"aresample={SR}")
        return
    _mux(video, wav, out_mp4, total, apply_filter(measured, LIMITER_LIMIT))
    lower = second_pass_limit(true_peak_db(out_mp4))
    if lower is not None:
        _mux(video, wav, out_mp4, total, apply_filter(measured, lower))
