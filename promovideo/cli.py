"""promo-video command line. Heavy modules (numpy, Pillow) load only for the commands that need them."""
import argparse
import sys
from pathlib import Path

from . import config as C


def _cfg():
    return C.load_config()


def cmd_config(a):
    code, lines = C.check_report(_cfg())
    print("\n".join(lines))
    return code


def cmd_new(a):
    from .project import new_project
    print(new_project(a.topic, a.style))
    return 0


def _project_preset(project):
    import tomllib
    from .presets import load_preset
    meta = Path(project) / "project.toml"
    name = tomllib.loads(meta.read_text()).get("preset", "bay") if meta.exists() else "bay"
    return load_preset(name)


def cmd_plan(a):
    from . import music, voice
    from .script import load_script
    preset = _project_preset(a.project)
    n = len(load_script(a.project))
    whisper = bool(_cfg().whisper_url)
    lo, hi = voice.request_budget(n, preset, whisper)
    m = music.request_budget(preset)
    retries = f" (up to {hi} with Whisper retries)" if hi != lo else ""
    print(f"paid requests: voice: {lo}{retries}, music: {m}; total {lo + m}" + (f"-{hi + m}" if hi != lo else ""))
    print(f"preset {preset.name}: TTS {preset.tts_model} voice {preset.voice}; music {preset.music_model} "
          f"cues {', '.join(preset.cues)}")
    return 0


def cmd_voice(a):
    from . import voice
    from .script import load_script
    from .transport import UrllibTransport
    cfg, preset = _cfg(), _project_preset(a.project)
    key = cfg.api_key()
    only = set(a.only) if a.only else None
    n = sum(1 for i, _ in load_script(a.project) if not only or i in only)
    lo, hi = voice.request_budget(n, preset, bool(cfg.whisper_url))
    print(f"voice: {lo}-{hi} paid TTS requests ({preset.tts_model}, {preset.voice})" if hi != lo
          else f"voice: {lo} paid TTS requests ({preset.tts_model}, {preset.voice})")
    voice.generate(a.project, preset, key, UrllibTransport(), cfg.whisper_url, only)
    return 0


def cmd_music(a):
    from . import music
    from .transport import UrllibTransport
    cfg, preset = _cfg(), _project_preset(a.project)
    key = cfg.api_key()
    only = set(a.cue) if a.cue else None
    print(f"music: {music.request_budget(preset, only)} paid Lyria requests ({preset.music_model})")
    music.generate(a.project, preset, key, UrllibTransport(), only)
    return 0


def cmd_render(a):
    from . import render
    out = a.out or str(Path(a.project) / "out" / "promo.mp4")
    render.build(a.project, out, placeholder_audio=a.placeholder_audio)
    return 0


def cmd_check(a):
    from . import check
    if a.self_test:
        ok, lines = check.self_test()
        print("\n".join(lines))
        return 0 if ok else 1
    if not a.video:
        print("error: give a VIDEO (or --self-test)", file=sys.stderr)
        return 2
    video = Path(a.video)
    edl_path = a.edl or str(video.with_suffix("")) + ".edl.json"
    ok, lines = check.check_video(edl_path, video, whisper_url=_cfg().whisper_url)
    print("\n".join(lines))
    return 0 if ok else 1


def cmd_privacy(a):
    import re
    from . import privacy
    pats = [("pattern", re.compile(p, re.I)) for p in a.pattern] if a.pattern else \
        privacy.machine_patterns(C.REPO_ROOT)
    ok, lines = privacy.scan_video(a.video, a.step, pats)
    print("\n".join(lines))
    return 0 if ok else 1


def cmd_sheet(a):
    from .sheet import contact_sheet
    out = a.out or str(Path(a.video).with_suffix("")) + ".sheet.png"
    n = contact_sheet(a.video, out, a.step)
    print(f"{out}: {n} tiles")
    return 0


def cmd_record(a):
    from .record import record
    return record(a.out, a.seconds, a.screen, a.dry_run)


def parser():
    ap = argparse.ArgumentParser(prog="promo-video", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("config", help="settings")
    p.add_argument("action", choices=["check"])
    p.set_defaults(fn=cmd_config)
    p = sub.add_parser("new", help="create a project folder ($PROMO_VIDEO_OUT or ./promo-video-out)")
    p.add_argument("topic")
    p.add_argument("--style", choices=["bay", "nolan"], required=True)
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("plan", help="print the number of paid requests voice and music would make")
    p.add_argument("project")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("voice", help="generate narration (paid: one TTS request per line, retries with Whisper)")
    p.add_argument("project")
    p.add_argument("--only", nargs="*", help="line ids")
    p.set_defaults(fn=cmd_voice)
    p = sub.add_parser("music", help="generate the preset's music cues (paid: one Lyria request per cue)")
    p.add_argument("project")
    p.add_argument("--cue", nargs="*")
    p.set_defaults(fn=cmd_music)
    p = sub.add_parser("render", help="render the project's edit list to an mp4")
    p.add_argument("project")
    p.add_argument("--out")
    p.add_argument("--placeholder-audio", action="store_true",
                   help="silent narration timed from the script and no music when not generated yet (no API)")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("check", help="check a render against its edit list, or --self-test")
    p.add_argument("video", nargs="?")
    p.add_argument("--edl", help="resolved edit list (default <video>.edl.json)")
    p.add_argument("--self-test", action="store_true")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("privacy", help="OCR the video for personal text (needs tesseract; SKIP when absent)")
    p.add_argument("video")
    p.add_argument("--step", type=float, default=2.0)
    p.add_argument("--pattern", nargs="*", help="regexes (default: home path, user name, .public-denylist.local)")
    p.set_defaults(fn=cmd_privacy)
    p = sub.add_parser("sheet", help="contact sheet: one labelled frame every --step seconds")
    p.add_argument("video")
    p.add_argument("--step", type=float, default=2.0)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_sheet)
    p = sub.add_parser("record", help="record the screen with ffmpeg (UI topics only)")
    p.add_argument("out")
    p.add_argument("--seconds", type=float, required=True)
    p.add_argument("--screen", type=int)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_record)
    return ap


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        return a.fn(a)
    except (C.KeyMissing, C.ConfigError, FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - one line, no traceback that could carry request details
        from .transport import TransportError
        if isinstance(e, TransportError):
            print(f"error: {e}", file=sys.stderr)
            return 3
        raise
