"""Narration: one Gemini TTS request per script line, optionally checked by a Whisper transcription with retries.

Writes <project>/audio/vo/<id>.wav and <project>/audio/vo.json. The key is sent only in the request header."""
import base64
import io
import json
import os
import re
import wave
from pathlib import Path

from . import script as S
from .transport import TransportError, gemini_url


def tts_request(preset, line):
    body = {"contents": [{"parts": [{"text": preset.tts_prompt(line)}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": preset.voice}}}}}
    return gemini_url(preset.tts_model), body


def headers(key):
    return {"x-goog-api-key": key, "Content-Type": "application/json"}


class NoAudioReply(TransportError):
    """A generateContent reply with no inline audio part (blocked, or stopped before any audio)."""


def inline_audio(response, item):
    """(bytes, mime) of the first inline audio part of a generateContent response for `item` (a cue or line id).

    A reply without one raises NoAudioReply naming the item and the reply's finishReason and promptFeedback
    blockReason; never the key or the body."""
    candidate = (response.get("candidates") or [{}])[0]
    parts = candidate.get("content", {}).get("parts", [])
    data = next((p["inlineData"] for p in parts if "inlineData" in p), None)
    if data is None:
        finish = candidate.get("finishReason", "none")
        block = response.get("promptFeedback", {}).get("blockReason", "none")
        raise NoAudioReply(f"{item}: the reply has no audio (finishReason {finish}, blockReason {block})")
    return base64.b64decode(data["data"]), data.get("mimeType", "")


def write_index(index_path, entries, key):
    """Write the index file sorted by `key`; called after every item, so a later failure keeps the items written."""
    index_path.write_text(json.dumps(sorted(entries, key=key), indent=1))


def to_wav(data, mime):
    """Gemini TTS returns raw 16-bit PCM (audio/L16;rate=N); wrap it in a WAV header. WAV input passes through."""
    if data[:4] == b"RIFF":
        return data
    m = re.search(r"rate=(\d+)", mime or "")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(m.group(1)) if m else 24000)
        w.writeframes(data)
    return buf.getvalue()


def wav_duration(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def transcribe(transport, whisper_url, path):
    out = transport.post_file(whisper_url, path, {"model": "whisper-1", "response_format": "json"}, 60)
    return str(out.get("text", "")).strip()


def request_budget(n_lines, preset, whisper):
    """(fewest, most) paid TTS requests: retries happen only when a Whisper check is configured."""
    return n_lines, n_lines * (preset.whisper_tries if whisper else 1)


def generate(project_dir, preset, key, transport, whisper_url=None, only=None, log=print):
    project_dir = Path(project_dir)
    out_dir = project_dir / "audio" / "vo"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = project_dir / "audio" / "vo.json"
    index = {e["id"]: e for e in json.loads(index_path.read_text())} if index_path.exists() else {}
    if not whisper_url:
        log("SKIP whisper: no whisper_url configured; narration is not transcribed (one request per line)")
    tries = preset.whisper_tries if whisper_url else 1
    requests = 0
    for line_id, line in S.load_script(project_dir):
        if only and line_id not in only:
            continue
        path, tmp = out_dir / f"{line_id}.wav", out_dir / f"{line_id}.wav.try"
        best = None
        for attempt in range(1, tries + 1):
            url, body = tts_request(preset, line)
            requests += 1
            reply = transport.post_json(url, body, headers(key), 120)
            tmp.write_bytes(to_wav(*inline_audio(reply, f"voice line {line_id}")))
            if not whisper_url:
                best = (None, None, attempt)
                os.replace(tmp, path)
                break
            heard = transcribe(transport, whisper_url, tmp)
            score = S.match_ratio(line, heard)
            if best is None or score > best[0]:
                best = (score, heard, attempt)
                os.replace(tmp, path)
            if score >= preset.whisper_min_match:
                break
        if tmp.exists():
            tmp.unlink()
        score, heard, attempt = best
        index[line_id] = {"id": line_id, "text": line, "voice": preset.voice, "model": preset.tts_model,
                          "duration": round(wav_duration(path), 3), "whisper": heard,
                          "match": None if score is None else round(score, 3), "attempts": attempt}
        write_index(index_path, index.values(), lambda e: e["id"])
        log(f"{line_id} dur={index[line_id]['duration']:.2f}s tries={attempt}"
            + ("" if score is None else f" match={score:.2f}"))
    log(f"requests={requests}")
    return requests
