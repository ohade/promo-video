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


def _post(client, method, url, tmp_path):
    if method == "json":
        return client.post_json(url, {"body": "canary"}, {"x-goog-api-key": _key()}, 5)
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"audio")
    return client.post_file(url, audio, {"model": "test"}, 5)


@pytest.mark.parametrize("method", ["json", "file"])
@pytest.mark.parametrize("kind", ["http", "url", "timeout", "value"])
def test_error_url_contains_only_endpoint(monkeypatch, tmp_path, raises, method, kind):
    credentials = "user:pw-" + "SECRET1"
    url = f"https://{credentials}@api.invalid:8443/v1/x?key=SECRET2#SECRET3"

    def opener(req, timeout):
        if kind == "http":
            raise _http_error(req, "body-canary")
        error_type = {"url": urllib.error.URLError, "timeout": TimeoutError, "value": ValueError}[kind]
        raise error_type(url)

    monkeypatch.setattr(transport.urllib.request, "urlopen", opener)
    error = raises(Exception, lambda: _post(transport.UrllibTransport(), method, url, tmp_path))
    assert isinstance(error, transport.TransportError), repr(error)
    text = str(error) + repr(error) + "".join(traceback.format_exception(error))
    assert "https://api.invalid:8443/v1/x" in text, text
    assert all(marker not in text for marker in ("user", "SECRET1", "SECRET2", "SECRET3", "?", "#", "@")), text


@pytest.mark.parametrize("method", ["json", "file"])
@pytest.mark.parametrize("url", ["not-a-url?key=SECRET2#SECRET3", "https://[broken/v1?key=SECRET2#SECRET3",
                                 "https://api.invalid:bad/v1?key=SECRET2#SECRET3"])
def test_unparsable_request_url_has_safe_error(monkeypatch, tmp_path, raises, method, url):
    def opener(req, timeout):
        raise ValueError(url)

    monkeypatch.setattr(transport.urllib.request, "urlopen", opener)
    error = raises(Exception, lambda: _post(transport.UrllibTransport(), method, url, tmp_path))
    assert isinstance(error, transport.TransportError), repr(error)
    text = str(error) + "".join(traceback.format_exception(error))
    assert "<unparsable URL>" in text, text
    assert all(marker not in text for marker in ("SECRET2", "SECRET3", "?", "#")), text


def test_safe_endpoint_keeps_ipv6_and_port(monkeypatch, tmp_path, raises):
    credentials = "reader:pw-" + "SECRET1"
    url = f"https://{credentials}@[::1]:8443/v1/x?key=SECRET2#SECRET3"

    def opener(req, timeout):
        raise TimeoutError(url)

    monkeypatch.setattr(transport.urllib.request, "urlopen", opener)
    error = raises(Exception, lambda: _post(transport.UrllibTransport(), "json", url, tmp_path))
    assert isinstance(error, transport.TransportError), repr(error)
    assert "https://[::1]:8443/v1/x" in str(error)
    assert all(marker not in str(error) for marker in ("SECRET1", "SECRET2", "SECRET3", "reader"))


@pytest.mark.parametrize("method", ["json", "file"])
@pytest.mark.parametrize("separator", [" ", "\n"])
def test_real_http_path_validation_never_leaks_query(monkeypatch, tmp_path, raises, method, separator):
    import socket
    opener = transport.urllib.request.build_opener(transport.urllib.request.ProxyHandler({}))
    connections = []

    def forbidden_connection(*args, **kwargs):
        connections.append(args)
        raise AssertionError("malformed URL reached the network")

    monkeypatch.setattr(socket, "create_connection", forbidden_connection)
    monkeypatch.setattr(transport.urllib.request, "urlopen", opener.open)
    url = f"https://api.invalid/v1/{separator}bad?key=QUERYMARK#FRAGMARK"
    error = raises(Exception, lambda: _post(transport.UrllibTransport(), method, url, tmp_path))
    assert connections == [], "URL validation must run before a connection"
    assert isinstance(error, transport.TransportError), repr(error)
    text = str(error) + repr(error) + "".join(traceback.format_exception(error))
    assert "api.invalid" in text
    assert all(marker not in text for marker in ("QUERYMARK", "FRAGMARK", "?", "#")), text


def test_http_protocol_error_never_leaks_response_line(monkeypatch, tmp_path, raises):
    import http.client

    def opener(req, timeout):
        raise http.client.BadStatusLine("response-QUERYMARK")

    monkeypatch.setattr(transport.urllib.request, "urlopen", opener)
    error = raises(Exception, lambda: _post(transport.UrllibTransport(), "json", "https://api.invalid/v1", tmp_path))
    assert isinstance(error, transport.TransportError), repr(error)
    text = str(error) + repr(error) + "".join(traceback.format_exception(error))
    assert "https://api.invalid/v1" in text and "BadStatusLine" in text
    assert "QUERYMARK" not in text, text
