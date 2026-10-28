"""Contact sheet: one labelled frame every STEP seconds of a video, tiled 8 across."""
import os
import subprocess

from PIL import Image, ImageDraw

from .common import font, probe_duration

TW, TH, COLS = 384, 216, 8


def grab(clip, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(clip), "-frames:v", "1", "-vf",
                          f"scale={TW}:{TH}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True,
                         check=True).stdout
    return Image.frombytes("RGB", (TW, TH), raw)


def contact_sheet(clip, out_png, step=2.0):
    """Write the sheet; return the number of tiles."""
    tiles, f, t = [], font("mono", 15), 0.0
    dur = probe_duration(clip)
    while t < dur - 0.05:
        im = grab(clip, t)
        d = ImageDraw.Draw(im)
        tag = f"{os.path.splitext(os.path.basename(str(clip)))[0]} {int(t // 60)}:{t % 60:05.2f}"
        d.rectangle([0, 0, d.textlength(tag, font=f) + 8, 20], fill=(0, 0, 0))
        d.text((4, 2), tag, font=f, fill=(255, 255, 0))
        tiles.append(im)
        t += step
    rows = max(1, (len(tiles) + COLS - 1) // COLS)
    cols = min(COLS, max(1, len(tiles)))
    sheet = Image.new("RGB", (cols * (TW + 4) - 4, rows * (TH + 4) - 4), (40, 40, 40))
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % COLS) * (TW + 4), (i // COLS) * (TH + 4)))
    sheet.save(out_png)
    return len(tiles)
