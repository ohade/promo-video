"""The single HTTP seam: every Gemini, Lyria and Whisper call goes through a Transport, so tests inject a fake.

Errors never include request headers or bodies (the API key travels in a header)."""
import http.client
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class TransportError(Exception):
    pass


def gemini_url(model):
    return f"{GEMINI_BASE}/{model}:generateContent"


def _safe_endpoint(url):
    """Diagnostic endpoint only: never include userinfo, query or fragment, even on malformed input."""
    if not isinstance(url, str):
        return "<unparsable URL>"
    try:
        parsed = urllib.parse.urlsplit(url)
        host, port = parsed.hostname, parsed.port
        if not parsed.scheme or not host:
            return "<unparsable URL>"
        host = f"[{host}]" if ":" in host else host
        authority = host + (f":{port}" if port is not None else "")
        return urllib.parse.urlunsplit((parsed.scheme, authority, parsed.path, "", ""))
    except ValueError:
        return "<unparsable URL>"


class Transport:
    def post_json(self, url, body, headers, timeout):
        raise NotImplementedError

    def post_file(self, url, path, fields, timeout):
        raise NotImplementedError


class UrllibTransport(Transport):
    def _send(self, req, timeout):
        endpoint = _safe_endpoint(req.full_url)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise TransportError(f"HTTP {e.code} from {endpoint}") from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ValueError) as e:
            raise TransportError(f"request to {endpoint} failed: {e.__class__.__name__}") from None

    def _post(self, url, data, headers, timeout):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        except (ValueError, TypeError, AttributeError) as e:
            # The original request-construction exception can contain credentials or query values.
            raise TransportError(f"request to {_safe_endpoint(url)} failed: {e.__class__.__name__}") from None
        return self._send(req, timeout)

    def post_json(self, url, body, headers, timeout):
        return self._post(url, json.dumps(body).encode(), dict(headers), timeout)

    def post_file(self, url, path, fields, timeout):
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        with open(path, "rb") as f:
            payload = f.read()
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{os.path.basename(path)}"'
                     f"\r\nContent-Type: {ctype}\r\n\r\n".encode() + payload + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self._post(url, b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout)
