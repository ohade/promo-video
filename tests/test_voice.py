"""Narration: one Gemini TTS request per line through the injected transport; optional Whisper check with retries."""
import json
import wave

import pytest

from promovideo import script, voice
from promovideo.transport import TransportError
from promovideo.presets import load_preset


def _project(tmp_path, lines):
    (tmp_path / "script.txt").write_text("".join(f'{i} "{t}"\n' for i, t in lines))
    return tmp_path


def _all_text(root):
    out = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p.read_bytes().decode("latin-1"))
    return "\n".join(out)


def test_voice_request_shape():
    p = load_preset("nolan")
    url, body = voice.tts_request(p, "Every session begins.")
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-tts:generateContent"
    assert body == {"contents": [{"parts": [{"text": p.tts_prompt("Every session begins.")}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"],
                                         "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig":
                                                                          {"voiceName": "Algenib"}}}}}


def test_voice_generate_without_whisper(tmp_path, fake_transport, capsys):
    from conftest import fake_key
    key = fake_key()
    proj = _project(tmp_path, [("l01", "Hello there."), ("l02", "Second line.")])
    t = fake_transport()
    n = voice.generate(proj, load_preset("bay"), key, t, whisper_url=None)
    assert n == 2
    assert [c[0] for c in t.calls] == ["json", "json"]
    for _, url, body, headers in t.calls:
        assert headers.get("x-goog-api-key") == key
        assert key not in url and key not in json.dumps(body)
    for i in ("l01", "l02"):
        with wave.open(str(proj / "audio" / "vo" / f"{i}.wav")) as w:
            assert w.getframerate() == 24000 and w.getnchannels() == 1 and w.getnframes() == 12000
    index = json.loads((proj / "audio" / "vo.json").read_text())
    assert [e["id"] for e in index] == ["l01", "l02"]
    assert index[0]["voice"] == "Fenrir" and index[0]["duration"] == 0.5 and index[0]["attempts"] == 1
    out = capsys.readouterr().out
    assert sum(1 for x in out.splitlines() if x.startswith("SKIP")) == 1
    assert key not in out and key not in _all_text(proj)


def test_voice_whisper_retry_until_match(tmp_path, fake_transport):
    proj = _project(tmp_path, [("l01", "Hello there friend."), ("l02", "Second line.")])
    t = fake_transport(heard=["Yellow chair bend.", "Hello there, friend.", "Second line."])
    n = voice.generate(proj, load_preset("bay"), "k", t, whisper_url="http://whisper.invalid/v1")
    assert n == 3
    assert [c[0] for c in t.calls] == ["json", "file", "json", "file", "json", "file"]
    assert t.calls[1][3] == {"model": "whisper-1", "response_format": "json"}
    index = {e["id"]: e for e in json.loads((proj / "audio" / "vo.json").read_text())}
    assert index["l01"]["attempts"] == 2 and index["l01"]["match"] == 1.0
    assert index["l02"]["attempts"] == 1


def test_voice_whisper_gives_up_after_three_tries(tmp_path, fake_transport):
    proj = _project(tmp_path, [("l01", "Hello there friend.")])
    t = fake_transport(heard=["no", "nope", "never"])
    n = voice.generate(proj, load_preset("nolan"), "k", t, whisper_url="http://whisper.invalid/v1")
    assert n == 3
    index = json.loads((proj / "audio" / "vo.json").read_text())
    assert index[0]["match"] < 0.90
    assert (proj / "audio" / "vo" / "l01.wav").exists()
    assert not list((proj / "audio" / "vo").glob("*.try"))


def test_voice_only_selected_ids(tmp_path, fake_transport):
    proj = _project(tmp_path, [("l01", "One."), ("l02", "Two.")])
    t = fake_transport()
    assert voice.generate(proj, load_preset("bay"), "k", t, only={"l02"}) == 1
    assert not (proj / "audio" / "vo" / "l01.wav").exists()


def test_voice_pcm_wrapped_and_wav_passthrough():
    from conftest import pcm_bytes
    wav = voice.to_wav(pcm_bytes(0.25), "audio/L16;codec=pcm;rate=24000")
    assert wav[:4] == b"RIFF" and len(wav) == 44 + 12000
    assert voice.to_wav(wav, "audio/wav") == wav


def test_voice_request_budget():
    assert voice.request_budget(5, load_preset("bay"), whisper=False) == (5, 5)
    assert voice.request_budget(5, load_preset("bay"), whisper=True) == (5, 15)


def test_voice_whisper_stops_at_exact_threshold(tmp_path, fake_transport):
    line = "one two three four five six seven eight nine ten"
    heard = "one two three four five six seven eight nine eleven"
    assert script.match_ratio(line, heard) == 0.90
    proj = _project(tmp_path, [("l01", line)])
    t = fake_transport(heard=[heard, line, line])
    n = voice.generate(proj, load_preset("bay"), "k", t, whisper_url="http://whisper.invalid/v1")
    index = json.loads((proj / "audio" / "vo.json").read_text())
    assert n == 1 and index[0]["attempts"] == 1 and index[0]["match"] == 0.9


@pytest.mark.parametrize("reply, reason", [({"candidates": [{"finishReason": "OTHER"}]}, "OTHER"),
                                           ({"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}},
                                            "PROHIBITED_CONTENT")])
def test_voice_reply_without_content_names_line_and_reason(tmp_path, fake_transport, raises, reply, reason):
    from conftest import fake_key
    key = fake_key()
    proj = _project(tmp_path, [("l01", "Hello there.")])
    t = fake_transport()
    t.post_json = lambda *a: reply
    err = raises(Exception, lambda: voice.generate(proj, load_preset("bay"), key, t))
    assert err is not None and "l01" in str(err) and reason in str(err), repr(err)
    assert key not in str(err) and "candidates" not in str(err) and "promptFeedback" not in str(err)
    assert isinstance(err, voice.NoAudioReply)


def test_voice_failure_keeps_written_lines_in_index(tmp_path, fake_transport):
    proj = _project(tmp_path, [("l01", "One."), ("l02", "Two.")])
    t = fake_transport()
    replies = iter([t.post_json, TransportError("HTTP 500 from tts")])

    def post_json(*a):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply(*a)
    t.post_json = post_json
    with pytest.raises(TransportError):
        voice.generate(proj, load_preset("bay"), "k", t)
    index_path = proj / "audio" / "vo.json"
    assert index_path.exists()
    assert [e["id"] for e in json.loads(index_path.read_text())] == ["l01"]


def test_voice_no_audio_reply_is_a_transport_error():
    # cli.main turns a TransportError into one "error: ..." line and exit 3; a no-content reply must take that path.
    assert issubclass(voice.NoAudioReply, TransportError)
