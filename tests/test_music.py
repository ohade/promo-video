"""Music: one Lyria request per cue through the injected transport; prompts carry the instrumental-only suffix."""
import json

import pytest

from promovideo import music, voice
from promovideo.transport import TransportError
from promovideo.presets import load_preset


def test_music_request_shape():
    p = load_preset("bay")
    url, body = music.music_request(p, "drive")
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/lyria-3.5:generateContent"
    assert body == {"contents": [{"parts": [{"text": p.music_prompt("drive")}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"]}}


def test_music_generate_writes_cues(tmp_path, fake_transport):
    from conftest import fake_key
    key = fake_key()
    t = fake_transport(audio=b"ID3fake-mp3", mime="audio/mpeg")
    n = music.generate(tmp_path, load_preset("nolan"), key, t, only={"pulse", "organ"})
    assert n == 2
    assert all(c[3].get("x-goog-api-key") == key for c in t.calls)
    assert (tmp_path / "audio" / "music" / "pulse.mp3").read_bytes() == b"ID3fake-mp3"
    index = json.loads((tmp_path / "audio" / "music.json").read_text())
    assert [e["cue"] for e in index] == ["pulse", "organ"]
    assert index[0]["prompt"] == load_preset("nolan").music_prompt("pulse")
    assert index[0]["file"] == "audio/music/pulse.mp3" and index[0]["model"] == "lyria-3.5"
    assert key not in (tmp_path / "audio" / "music.json").read_text()


def test_music_request_budget():
    assert music.request_budget(load_preset("bay")) == 4
    assert music.request_budget(load_preset("nolan"), only={"rise"}) == 1


def test_music_reply_without_content_names_cue_and_reason(tmp_path, fake_transport, raises):
    from conftest import fake_key
    key = fake_key()
    t = fake_transport()
    t.post_json = lambda *a: {"candidates": [{"finishReason": "OTHER"}]}
    err = raises(Exception, lambda: music.generate(tmp_path, load_preset("nolan"), key, t, only={"pulse"}))
    assert err is not None and "pulse" in str(err) and "OTHER" in str(err), repr(err)
    assert key not in str(err) and "candidates" not in str(err)
    assert isinstance(err, voice.NoAudioReply)


def test_music_failure_keeps_written_cues_in_index(tmp_path, fake_transport):
    t = fake_transport(audio=b"ID3fake-mp3", mime="audio/mpeg")
    replies = iter([t.post_json, TransportError("HTTP 500 from lyria")])

    def post_json(*a):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply(*a)
    t.post_json = post_json
    with pytest.raises(TransportError):
        music.generate(tmp_path, load_preset("nolan"), "k", t, only={"pulse", "organ"})
    index_path = tmp_path / "audio" / "music.json"
    assert index_path.exists()
    assert [e["cue"] for e in json.loads(index_path.read_text())] == ["pulse"]


BAD_CUES = ("", "*", "a*", "../x", "a/b", ".x", "a b")


@pytest.mark.parametrize("cue", BAD_CUES)
def test_invalid_cue_rejected_before_glob(monkeypatch, tmp_path, raises, cue):
    from pathlib import Path
    globs = []
    monkeypatch.setattr(Path, "glob", lambda path, pattern: globs.append(pattern) or [])
    error = raises(Exception, lambda: music.cue_file(tmp_path, cue))
    assert isinstance(error, ValueError) and repr(cue) in str(error), repr(error)
    assert globs == [], "invalid name reached glob"


@pytest.mark.parametrize("cue", BAD_CUES)
@pytest.mark.parametrize("only", [None, set()])
def test_all_selected_cues_validated_before_any_side_effect(monkeypatch, tmp_path, fake_transport, raises, cue, only):
    from dataclasses import replace
    preset = replace(load_preset("nolan"), cues={"valid": "first cue", cue: "invalid later cue"})
    project = tmp_path / "project"
    transport = fake_transport(audio=b"music", mime="audio/mpeg")
    monkeypatch.setattr(music, "_duration", lambda path: None)
    error = raises(Exception, lambda: music.generate(project, preset, "k", transport, only=only))
    assert transport.calls == [], "a paid request preceded validation of the later cue"
    assert not project.exists(), "generation wrote files or directories before validating every selected cue"
    assert isinstance(error, ValueError) and repr(cue) in str(error), repr(error)


def test_only_filter_ignores_invalid_excluded_cue(monkeypatch, tmp_path, fake_transport):
    from dataclasses import replace
    preset = replace(load_preset("nolan"), cues={"../excluded": "invalid", "Valid-1_ok": "selected"})
    transport = fake_transport(audio=b"music", mime="audio/mpeg")
    monkeypatch.setattr(music, "_duration", lambda path: None)
    assert music.generate(tmp_path, preset, "k", transport, only={"Valid-1_ok"}) == 1
    assert len(transport.calls) == 1
    assert music.cue_file(tmp_path, "Valid-1_ok").read_bytes() == b"music"
