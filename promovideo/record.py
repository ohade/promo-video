"""Screen recording with ffmpeg (macOS avfoundation, Linux x11grab). Use it only when the topic is a UI."""
import os
import subprocess
import sys


def record_command(out, seconds, screen=None, platform=None, fps=30):
    platform = platform or sys.platform
    if platform == "darwin":
        src = ["-f", "avfoundation", "-framerate", str(fps), "-capture_cursor", "1",
               "-i", f"Capture screen {screen or 0}:none"]
    elif platform.startswith("linux"):
        src = ["-f", "x11grab", "-framerate", str(fps), "-i", os.environ.get("DISPLAY", ":0")]
    else:
        raise ValueError(f"screen recording is not supported on {platform}")
    return ["ffmpeg", "-y", *src, "-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", str(out)]


def record(out, seconds, screen=None, dry_run=False, log=print):
    cmd = record_command(out, seconds, screen)
    log(" ".join(cmd))
    if dry_run:
        return 0
    return subprocess.run(cmd).returncode
