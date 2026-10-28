"""Project folders: <root>/<slug>/ with project.toml, script.txt, edl.json, footage/ and material/.
<root> is $PROMO_VIDEO_OUT when set, else ./promo-video-out."""
import json
import os
import re
from pathlib import Path

from .presets import PRESETS

SCRIPT_TEMPLATE = """# One narration line per row: <id> "<text>". The voice speaks exactly these lines.
# l01 "Your opening line: the problem, in one breath."
"""


def slug(topic):
    s = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return s[:60].strip("-") or "promo"


def new_project(topic, style, env=None, cwd=None):
    if style not in PRESETS:
        raise ValueError(f"unknown style {style!r}; choose one of: {', '.join(PRESETS)}")
    env = os.environ if env is None else env
    root = Path(env["PROMO_VIDEO_OUT"]) if env.get("PROMO_VIDEO_OUT") else Path(cwd or os.getcwd()) / "promo-video-out"
    path = root / slug(topic)
    for sub in ("footage", "material"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    files = {"project.toml": f"title = {json.dumps(topic)}\npreset = \"{style}\"\n",
             "script.txt": SCRIPT_TEMPLATE,
             "edl.json": json.dumps({"segments": [], "audio": {"vo": [], "music": [], "sfx": []}}, indent=1) + "\n"}
    for name, text in files.items():
        if not (path / name).exists():            # never overwrite an existing project's work
            (path / name).write_text(text)
    return path
