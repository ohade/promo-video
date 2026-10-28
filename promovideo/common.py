"""Shared constants, fonts, easing, and ffmpeg helpers. numpy is imported lazily so stdlib-only commands still run."""
import os
import subprocess

FPS = 30
W, H = 1920, 1080
SR = 48000

# First existing file wins; override any slot with PROMO_VIDEO_FONT_<NAME>=/path/to/font.
FONT_CANDIDATES = {
    "cond": ["/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"],
    "impact": ["/System/Library/Fonts/Supplemental/Impact.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "sans": ["/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "thin": ["/System/Library/Fonts/Supplemental/Futura.ttc", "/System/Library/Fonts/Helvetica.ttc",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf"],
    "mono": ["/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
}
_font_cache = {}


def font_path(name):
    override = os.environ.get(f"PROMO_VIDEO_FONT_{name.upper()}")
    for path in ([override] if override else []) + FONT_CANDIDATES.get(name, []):
        if path and os.path.exists(path):
            return path
    return None


def font(name, size):
    from PIL import ImageFont
    key = (name, int(size))
    if key not in _font_cache:
        path = font_path(name)
        _font_cache[key] = ImageFont.truetype(path, int(size)) if path else ImageFont.load_default(int(size))
    return _font_cache[key]


def ease_in_out(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def ease_out_back(x, s=1.70158):
    x = min(1.0, max(0.0, x)) - 1
    return x * x * ((s + 1) * x + s) + 1


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


def probe_size(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0:s=x", str(path)], capture_output=True, text=True, check=True).stdout
    w, h = out.strip().split("x")[:2]
    return int(w), int(h)


def read_audio(path, sr=SR):
    """Decode any audio file to float32 stereo (n, 2) at sr."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(sr), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def write_wav(path, audio, sr=SR):
    import numpy as np
    a = np.clip(audio, -1, 1).astype(np.float32)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ac", "2", "-ar", str(sr), "-i", "-",
                    "-c:a", "pcm_s16le", str(path)], input=a.tobytes(), check=True)
