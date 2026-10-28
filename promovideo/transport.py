"""The single HTTP seam: every Gemini, Lyria and Whisper call goes through a Transport, so tests inject a fake.

Errors never include request headers or bodies (the API key travels in a header)."""
import json
import mimetypes
import os
import urllib.error
import urllib.request
import uuid

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class TransportError(Exception):
    pass


def gemini_url(model):
    return f"{GEMINI_BASE}/{model}:generateContent"


class Transport:
    def post_json(self, url, body, headers, timeout):
        raise NotImplementedError

    def post_file(self, url, path, fields, timeout):
        raise NotImplementedError


class UrllibTransport(Transport):
    def _send(self, req, timeout):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise TransportError(f"HTTP {e.code} from {req.full_url}") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise TransportError(f"request to {req.full_url} failed: {e.__class__.__name__}") from None

    def post_json(self, url, body, headers, timeout):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=dict(headers), method="POST")
        return self._send(req, timeout)

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
        req = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        return self._send(req, timeout)
