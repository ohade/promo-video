"""Style presets (voice, music cues, Whisper policy, pacing, look), stored as TOML next to this file."""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRESETS = ("bay", "nolan")


@dataclass(frozen=True)
class Preset:
    name: str = ""
    description: str = ""
    tts_model: str = ""
    voice: str = ""
    profile: str = ""
    notes: str = ""
    music_model: str = ""
    music_suffix: str = ""
    cues: dict = field(default_factory=dict)
    whisper_min_match: float = 0.0
    whisper_tries: int = 0
    max_shot_s: float = 0.0
    look: dict = field(default_factory=dict)

    def music_prompt(self, cue):
        return self.cues[cue] + self.music_suffix

    def tts_prompt(self, line):
        return f"# AUDIO PROFILE: {self.profile}\n### DIRECTOR'S NOTES\n{self.notes}\n### TRANSCRIPT\n{line}"


def load_preset(name):
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose one of: {', '.join(PRESETS)}")
    d = tomllib.loads((HERE / f"{name}.toml").read_text())
    return Preset(name=d["name"], description=d["description"], tts_model=d["voice"]["model"],
                  voice=d["voice"]["name"], profile=d["voice"]["profile"], notes=d["voice"]["notes"],
                  music_model=d["music"]["model"], music_suffix=d["music"]["suffix"], cues=dict(d["music"]["cues"]),
                  whisper_min_match=float(d["whisper"]["min_match"]), whisper_tries=int(d["whisper"]["tries"]),
                  max_shot_s=float(d["max_shot_s"]), look=dict(d.get("look", {})))
