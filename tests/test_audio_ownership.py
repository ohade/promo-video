"""An export owns its temporary bytes and excludes a competing writer to the same destination."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from promovideo import audio


def _stub_probe(monkeypatch):
    measured = {"input_i": "-20.1", "input_tp": "-3.2", "input_lra": "5.0", "input_thresh": "-30.4",
                "target_offset": "0.3"}
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: SimpleNamespace(stderr=json.dumps(measured)))


def test_same_output_competitor_cannot_publish_unmeasured_bytes(monkeypatch, tmp_path):
    _stub_probe(monkeypatch)
    output = tmp_path / "out.mp4"
    measured_ready, competitor_attempted, first_done = (threading.Event() for _ in range(3))
    errors = {}

    def mux(video, wav, partial, total, filters):
        first = threading.current_thread().name == "first"
        Path(partial).write_bytes(b"first-measured" if first else b"second-unmeasured")
        if not first:
            competitor_attempted.set()

    def meter(partial):
        if threading.current_thread().name == "first":
            assert Path(partial).read_bytes() == b"first-measured"
            measured_ready.set()
            assert competitor_attempted.wait(5), "second export never attempted"
            return -1.5
        assert first_done.wait(5), "first export did not finish"
        raise ValueError("second meter failed")

    def export():
        name = threading.current_thread().name
        try:
            audio.loudnorm_mux("v", "w", output, 1.0)
        except Exception as error:  # collect every thread outcome for assertions below
            errors[name] = error
        finally:
            (first_done if name == "first" else competitor_attempted).set()

    monkeypatch.setattr(audio, "_mux", mux)
    monkeypatch.setattr(audio, "true_peak_db", meter)
    first = threading.Thread(target=export, name="first", daemon=True)
    second = threading.Thread(target=export, name="second", daemon=True)
    first.start()
    assert measured_ready.wait(5), "first export did not reach its meter"
    second.start()
    first.join(6)
    second.join(6)
    assert not first.is_alive() and not second.is_alive(), errors
    assert output.read_bytes() == b"first-measured", "published bytes were never measured by their owner"
    assert "first" not in errors, errors
    assert isinstance(errors.get("second"), ValueError), errors
    assert "in progress" in str(errors["second"]), errors
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.mp4"]


_CHILD_EXPORT = r'''
import json, sys, time
from pathlib import Path
from types import SimpleNamespace
from promovideo import audio
output, started, release = map(Path, sys.argv[1:])
data = {"input_i":"-20.1", "input_tp":"-3.2", "input_lra":"5", "input_thresh":"-30.4", "target_offset":"0.3"}
audio.subprocess.run = lambda *a, **k: SimpleNamespace(stderr=json.dumps(data))
audio._mux = lambda v,w,p,t,f: Path(p).write_bytes(b"child-measured")
def meter(partial):
    started.write_text("ready")
    end = time.monotonic() + 8
    while not release.exists() and time.monotonic() < end:
        time.sleep(0.01)
    assert release.exists(), "parent never released the export"
    return -1.5
audio.true_peak_db = meter
audio.loudnorm_mux("v", "w", output, 1.0)
'''


def test_separate_process_also_excludes_same_output(monkeypatch, tmp_path, raises):
    output, started, release = (tmp_path / name for name in ("out.mp4", "started", "release"))
    child = subprocess.Popen([sys.executable, "-c", _CHILD_EXPORT, str(output), str(started), str(release)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        end = time.monotonic() + 5
        while not started.exists() and child.poll() is None and time.monotonic() < end:
            time.sleep(0.01)
        assert started.exists(), "child did not acquire its export"
        _stub_probe(monkeypatch)
        monkeypatch.setattr(audio, "_mux", lambda v, w, p, t, f: Path(p).write_bytes(b"parent"))
        monkeypatch.setattr(audio, "true_peak_db", lambda p: -1.5)
        error = raises(Exception, lambda: audio.loudnorm_mux("v", "w", output, 1.0))
        assert isinstance(error, ValueError) and "in progress" in str(error), repr(error)
    finally:
        release.write_text("done")
        stdout, stderr = child.communicate(timeout=10)
    assert child.returncode == 0, stdout + stderr
    assert output.read_bytes() == b"child-measured"


def test_each_export_uses_a_fresh_partial_path(monkeypatch, tmp_path):
    _stub_probe(monkeypatch)
    partials = []

    def mux(video, wav, partial, total, filters):
        partials.append(Path(partial))
        Path(partial).write_bytes(b"measured")

    monkeypatch.setattr(audio, "_mux", mux)
    monkeypatch.setattr(audio, "true_peak_db", lambda p: -1.5)
    for _ in range(2):
        audio.loudnorm_mux("v", "w", tmp_path / "out.mp4", 1.0)
    assert len(set(partials)) == 2, "a previous export could still own the shared temporary filename"
    assert all(p.parent == tmp_path and not p.exists() for p in partials)
