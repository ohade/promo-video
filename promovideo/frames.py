"""Footage access for capture segments: decode the frames a segment needs, cropped to a bounding box."""
import bisect
import subprocess

import numpy as np

from .common import FPS


def select_expr(uniq, max_terms=40):
    """Compress sorted frame indices into constant-stride runs: between(n,a,b)*not(mod(n-a,s)) terms."""
    runs, i = [], 0
    while i < len(uniq):
        j = i + 1
        stride = uniq[j] - uniq[i] if j < len(uniq) else 1
        while j + 1 < len(uniq) and uniq[j + 1] - uniq[j] == stride:
            j += 1
        if j >= len(uniq):
            j = len(uniq) - 1
        runs.append((uniq[i], uniq[j], max(1, stride)))
        i = j + 1
    if len(runs) > max_terms:
        return None
    return "+".join(f"between(n\\,{a}\\,{b})" if s == 1 else f"between(n\\,{a}\\,{b})*not(mod(n-{a}\\,{s}))"
                    for a, b, s in runs)


def fetch(source, times, bbox):
    """Yield one (h, w, 3) uint8 frame per source time in `times` (non-decreasing), cropped to bbox [x, y, w, h]."""
    if not times:
        return
    x, y, w, h = (int(round(v)) for v in bbox)
    start = max(0.0, times[0])
    idx = [max(0, round((t - start) * FPS)) for t in times]
    uniq = sorted(set(idx))
    expr = select_expr(uniq)
    if expr is None:                       # too irregular for one expression: decode the span, keep what we need
        uniq = list(range(uniq[0], uniq[-1] + 1))
        expr = f"between(n\\,{uniq[0]}\\,{uniq[-1]})"
    span = uniq[-1] / FPS + 1.0
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.4f}", "-t", f"{span:.4f}", "-i", str(source), "-vf",
           f"fps={FPS}:start_time=0,select={expr},format=rgb24,crop={w}:{h}:{x}:{y}", "-fps_mode", "passthrough",
           "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = w * h * 3
    try:
        emitted, cur, last_good = -1, None, None
        for want in idx:
            pos = bisect.bisect_left(uniq, want)      # ffmpeg emits the unique selection in order
            while emitted < pos:
                buf = proc.stdout.read(size)
                emitted += 1
                if len(buf) == size:
                    cur = last_good = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
                else:
                    cur = last_good                   # past the end of the clip: repeat the last frame
            if cur is None:
                raise RuntimeError(f"no frame decoded from {source} at {times[0]:.2f}")
            yield cur
    finally:
        proc.stdout.close()
        proc.wait()
