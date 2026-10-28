"""Shared fixtures: repo root on sys.path, a recording fake transport, and a clean key environment.

No test may reach the network: every HTTP call goes through promovideo.transport.Transport, and tests pass FakeTransport.
"""
import base64
import os
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def fake_key():
    """A key-shaped placeholder built at runtime, so no key-shaped literal is ever stored in a tracked file."""
    return "AIza" + "Q" * 35


def pcm_bytes(seconds=0.5, rate=24000):
    """Silent 16-bit mono PCM, the shape Gemini TTS returns."""
    return struct.pack("<h", 0) * int(seconds * rate)


class FakeTransport:
    """Records every request; answers Gemini calls with canned audio and Whisper calls with queued transcripts."""

    def __init__(self, heard=None, audio=None, mime="audio/L16;codec=pcm;rate=24000"):
        self.calls = []
        self.heard = list(heard or [])
        self.audio = audio if audio is not None else pcm_bytes()
        self.mime = mime

    def post_json(self, url, body, headers, timeout):
        self.calls.append(("json", url, body, dict(headers)))
        data = base64.b64encode(self.audio).decode()
        return {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": self.mime, "data": data}}]}}]}

    def post_file(self, url, path, fields, timeout):
        self.calls.append(("file", url, str(path), dict(fields)))
        return {"text": self.heard.pop(0) if self.heard else ""}


@pytest.fixture
def fake_transport():
    return FakeTransport


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """No real key and no real config file can leak into a test: env key removed, config pointed at tmp."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("PROMO_VIDEO_CONFIG", str(tmp_path / "absent-config.toml"))
    return tmp_path


def expect_raise(exc_type, fn):
    """Return the exception fn raised if it is exc_type, else None (so the test asserts on it)."""
    try:
        fn()
    except exc_type as e:  # noqa: PERF203
        return e
    return None


@pytest.fixture
def raises():
    return expect_raise


@pytest.fixture
def repo_root():
    return ROOT


@pytest.fixture
def env_without_key():
    env = dict(os.environ)
    env.pop("GEMINI_API_KEY", None)
    return env
