"""Caller-controlled temporary directories cannot split a destination's reservation."""
import os
import subprocess
import sys
import time
from pathlib import Path

from promovideo import audio
from test_audio_ownership import _CHILD_EXPORT, _stub_probe


def test_distinct_temp_environments_share_export_reservation(monkeypatch, tmp_path, raises):
    output, started, release = (tmp_path / name for name in ("out.mp4", "started", "release"))
    child_temp = tmp_path / "other-temp"
    child_temp.mkdir()
    env = dict(os.environ, TMPDIR=str(child_temp), TEMP=str(child_temp), TMP=str(child_temp))
    child = subprocess.Popen([sys.executable, "-c", _CHILD_EXPORT, str(output), str(started), str(release)],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        end = time.monotonic() + 5
        while not started.exists() and child.poll() is None and time.monotonic() < end:
            time.sleep(0.01)
        assert started.exists(), "child did not acquire its export"
        _stub_probe(monkeypatch)
        monkeypatch.setattr(audio, "_mux", lambda v, w, p, t, f: Path(p).write_bytes(b"parent"))
        monkeypatch.setattr(audio, "true_peak_db", lambda p: -1.5)
        error = raises(Exception, lambda: audio.loudnorm_mux("v", "w", output, 1.0))
        assert isinstance(error, ValueError) and "in progress" in str(error), (
            "competing export bypassed reservation when TMPDIR differs", repr(error))
        assert not output.exists(), "competitor published while the first export was still active"
    finally:
        release.write_text("done")
        stdout, stderr = child.communicate(timeout=10)
    assert child.returncode == 0, stdout + stderr
    assert output.read_bytes() == b"child-measured"
