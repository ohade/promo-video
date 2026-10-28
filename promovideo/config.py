"""Settings: the Google API key and the optional Whisper URL.

Config files, in order: $PROMO_VIDEO_CONFIG (when set, the only file consulted), ~/.config/promo-video/config.toml,
<repo>/config.local.toml. The other settings come from the first file that exists. The key comes from the first source
with a real value: env GEMINI_API_KEY, then `gemini_api_key` in each file in that order. An empty or blank value, or
the placeholder from config.example.toml (PLACEHOLDER_KEY), is no key, so the lookup goes on to the next source.
The key value is never printed, logged, written, or placed in an exception message.
"""
import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ENV_KEY = "GEMINI_API_KEY"
ENV_CONFIG = "PROMO_VIDEO_CONFIG"
FILE_KEY = "gemini_api_key"
PLACEHOLDER_KEY = "YOUR-GOOGLE-AI-STUDIO-KEY"       # the value config.example.toml ships with; never a real key
REPO_ROOT = Path(__file__).resolve().parent.parent


class KeyMissing(Exception):
    """No API key found; the message names the setting and every place searched, never a value."""


class ConfigError(Exception):
    """A config file exists but cannot be parsed."""


@dataclass(frozen=True)
class Config:
    whisper_url: str = None
    key_source: str = None
    searched: tuple = ()
    loaded_from: str = None
    fonts: dict = field(default_factory=dict)
    _key: str = field(default=None, repr=False, compare=False)

    def __str__(self):
        return repr(self)

    def api_key(self):
        if not self._key:
            raise KeyMissing(missing_key_message(self.searched))
        return self._key


def missing_key_message(searched):
    places = "; ".join([f"environment {ENV_KEY}"] + [str(p) for p in searched])
    return (f"Google API key not found. Set {ENV_KEY}, or put {FILE_KEY} = \"...\" in a config file "
            f"(see config.example.toml). Searched: {places}")


def search_paths(env=None, home=None, repo_root=None):
    env = os.environ if env is None else env
    if env.get(ENV_CONFIG):
        return [Path(env[ENV_CONFIG])]
    home = Path.home() if home is None else Path(home)
    repo_root = REPO_ROOT if repo_root is None else Path(repo_root)
    return [home / ".config" / "promo-video" / "config.toml", repo_root / "config.local.toml"]


def _read_toml(path):
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:   # the message holds a position, not the file content
        raise ConfigError(f"{path}: not valid TOML ({e.__class__.__name__} at {getattr(e, 'lineno', '?')})") from e


def _is_real_key(value):
    """False for a missing, non-string (0, false, [] in TOML), empty or blank value and for the example placeholder."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and text != PLACEHOLDER_KEY


def load_config(env=None, home=None, repo_root=None):
    env = os.environ if env is None else env
    searched = tuple(search_paths(env, home, repo_root))
    files = [path for path in searched if path.is_file()]
    loaded = files[0] if files else None
    data = _read_toml(loaded) if loaded else {}
    key, source = None, None
    if _is_real_key(env.get(ENV_KEY)):
        key, source = env[ENV_KEY], f"environment {ENV_KEY}"
    else:
        for path in files:                  # later files are read only while no real key has been found
            value = (data if path == loaded else _read_toml(path)).get(FILE_KEY)
            if _is_real_key(value):
                key, source = str(value), str(path)
                break
    return Config(whisper_url=data.get("whisper_url") or None, key_source=source, searched=searched,
                  loaded_from=str(loaded) if loaded else None, fonts=dict(data.get("fonts", {})), _key=key)


def check_report(cfg, which=shutil.which):
    """(exit code, lines) for `promo-video config check`. Fails when the key or ffmpeg/ffprobe is missing."""
    lines, code = [], 0
    if cfg._key:
        lines.append(f"OK   key: {ENV_KEY} value found (from {cfg.key_source}; value not shown)")
    else:
        code = 1
        lines.append(f"FAIL key: {ENV_KEY} is not set and no config file has a real {FILE_KEY} "
                     f"(empty values and the config.example.toml placeholder do not count)")
        lines.append(f"     searched: environment {ENV_KEY}")
        for p in cfg.searched:
            lines.append(f"     searched: {p} ({'present' if Path(p).is_file() else 'missing'})")
    if cfg.whisper_url:
        lines.append("OK   whisper: whisper_url set; narration is transcribed and matched")
    else:
        lines.append("SKIP whisper: no whisper_url configured; transcription checks will be skipped")
    for tool, needed in (("ffmpeg", True), ("ffprobe", True), ("tesseract", False)):
        if which(tool):
            lines.append(f"OK   {tool}: found")
        elif needed:
            code = 1
            lines.append(f"FAIL {tool}: not found on PATH (required to render)")
        else:
            lines.append(f"SKIP {tool}: not found; the OCR privacy scan will be skipped")
    return code, lines
