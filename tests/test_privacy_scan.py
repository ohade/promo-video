"""OCR privacy scan of a rendered video: optional tesseract, SKIP line when absent."""
import shutil
import subprocess

import pytest

from promovideo import privacy


def test_privacy_scan_skips_without_tesseract():
    ok, lines = privacy.scan_video("unused.mp4", 2.0, [("x", __import__("re").compile("x"))], which=lambda name: None)
    assert ok is True
    assert len(lines) == 1 and lines[0].startswith("SKIP") and "tesseract" in lines[0]


@pytest.mark.skipif(not (shutil.which("tesseract") and shutil.which("ffmpeg")), reason="tesseract/ffmpeg absent")
def test_privacy_scan_finds_text_in_frames(tmp_path):
    import re
    from PIL import Image, ImageDraw
    from promovideo.common import font
    img = Image.new("RGB", (1280, 720), (255, 255, 255))
    ImageDraw.Draw(img).text((80, 300), "ZEBRACORP SECRET", font=font("sans", 110), fill=(0, 0, 0))
    png, mp4 = tmp_path / "f.png", tmp_path / "f.mp4"
    img.save(png)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(png), "-t", "2", "-r", "30", "-pix_fmt",
                    "yuv420p", str(mp4)], check=True)
    ok, lines = privacy.scan_video(str(mp4), 1.0, [("denylist", re.compile("zebracorp", re.I))])
    assert ok is False
    assert any(x.startswith("HIT") for x in lines) and lines[-1].startswith("FAIL")
    ok, lines = privacy.scan_video(str(mp4), 1.0, [("denylist", re.compile("hippogriff", re.I))])
    assert ok is True and lines[-1].startswith("PASS")
