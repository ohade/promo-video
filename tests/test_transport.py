"""Invariant 2 at the HTTP seam: a failed request never carries the key (it travels in a header) into the error."""
import email.message
import io
import traceback
import urllib.error

import pytest

from promovideo import transport


def _key():
    from conftest import fake_key
    return fake_key()


def _http_error(req, key):
    hdrs = email.message.Message()
    hdrs["x-echo"] = key
    return urllib.error.HTTPError(req.full_url, 403, f"Forbidden for {key}", hdrs, io.BytesIO(key.encode()))


@pytest.mark.parametrize("make", [
    _http_error,
    lambda req, key: urllib.error.URLError(f"refused while sending {key}"),
    lambda req, key: ValueError(f"Invalid header value {(key + chr(13)).encode()!r}"),
], ids=["HTTPError", "URLError", "ValueError"])
def test_transport_error_never_carries_key(monkeypatch, make):
    key = _key() + "\r"
    seen = []

    def opener(req, timeout):
        seen.append(req)
        raise make(req, key.strip())

    monkeypatch.setattr(transport.urllib.request, "urlopen", opener)
    with pytest.raises(transport.TransportError) as info:
        transport.UrllibTransport().post_json("https://api.invalid/v1/x", {"a": 1}, {"x-goog-api-key": key}, 5)
    assert seen, "the stub opener was not reached"
    text = str(info.value) + repr(info.value) + "".join(traceback.format_exception(info.value))
    assert key.strip() not in text and key[:12] not in text
    assert "api.invalid" in text
