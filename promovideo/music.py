"""Music: one Lyria request per preset cue. Writes <project>/audio/music/<cue>.<ext> and audio/music.json."""
import json
import re
import subprocess
from pathlib import Path

from .common import probe_duration
from .transport import gemini_url
from .voice import headers, inline_audio, write_index

EXT = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/ogg": "ogg"}


def _validate_cue(cue):
    if not isinstance(cue, str) or re.fullmatch(r"[A-Za-z0-9_-]+", cue) is None:
        raise ValueError(f"invalid music cue name {cue!r}; use letters, digits, underscores and hyphens")


def music_request(preset, cue):
    body = {"contents": [{"parts": [{"text": preset.music_prompt(cue)}]}],
            "generationConfig": {"responseModalities": ["AUDIO"]}}
    return gemini_url(preset.music_model), body


def request_budget(preset, only=None):
    return sum(1 for c in preset.cues if not only or c in only)


def _duration(path):
    try:
        return round(probe_duration(path), 2)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def generate(project_dir, preset, key, transport, only=None, log=print):
    selected = [cue for cue in preset.cues if not only or cue in only]
    for cue in selected:
        _validate_cue(cue)
    project_dir = Path(project_dir)
    out_dir = project_dir / "audio" / "music"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = project_dir / "audio" / "music.json"
    index = {e["cue"]: e for e in json.loads(index_path.read_text())} if index_path.exists() else {}
    order = list(preset.cues)
    requests = 0
    for cue in selected:
        url, body = music_request(preset, cue)
        requests += 1
        data, mime = inline_audio(transport.post_json(url, body, headers(key), 300), f"music cue {cue}")
        rel = f"audio/music/{cue}.{EXT.get(mime.split(';')[0].strip(), 'mp3')}"
        (project_dir / rel).write_bytes(data)
        dur = _duration(project_dir / rel)
        index[cue] = {"cue": cue, "file": rel, "model": preset.music_model, "prompt": preset.music_prompt(cue),
                      "duration": dur}
        write_index(index_path, index.values(), lambda e: order.index(e["cue"]) if e["cue"] in order else len(order))
        log(f"{preset.name}/{cue} " + (f"{dur:.1f}s" if dur else "written"))
    log(f"requests={requests}")
    return requests


def cue_file(project_dir, cue):
    """Path of a generated cue (any extension) or None."""
    _validate_cue(cue)
    hits = sorted((Path(project_dir) / "audio" / "music").glob(f"{cue}.*"))
    return hits[0] if hits else None
