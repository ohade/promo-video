"""Script lines: one `<id> "<text>"` per row in script.txt; blank lines and # comments are ignored."""
import difflib
import re
from pathlib import Path

LINE = re.compile(r'^\s*([A-Za-z][\w-]*)\s+"(.*)"\s*$')


def parse_script(text):
    out, seen = [], set()
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = LINE.match(raw)
        if not m:
            raise ValueError(f"script line {n}: expected <id> \"<text>\", got {raw.strip()[:60]!r}")
        if m.group(1) in seen:
            raise ValueError(f"script line {n}: duplicate id {m.group(1)}")
        seen.add(m.group(1))
        out.append((m.group(1), m.group(2)))
    return out


def load_script(project_dir):
    return parse_script((Path(project_dir) / "script.txt").read_text())


def words(s):
    return re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("-", " ")).split()


def match_ratio(expected, heard):
    return difflib.SequenceMatcher(None, words(expected), words(heard)).ratio()
