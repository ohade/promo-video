"""Equivalent destination spellings reserve one export, even before the output exists."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from promovideo import audio


def _stub_probe(monkeypatch):
    measured = {"input_i": "-20.1", "input_tp": "-3.2", "input_lra": "5.0", "input_thresh": "-30.4",
                "target_offset": "0.3"}
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: SimpleNamespace(stderr=json.dumps(measured)))


@pytest.mark.parametrize("names", [("out.mp4", "OUT.mp4"), ("caf\u00e9.mp4", "cafe\u0301.mp4")])
@pytest.mark.parametrize("existing", [False, True])
def test_destination_spelling_variants_share_one_export(monkeypatch, tmp_path, raises, names, existing):
    _stub_probe(monkeypatch)
    output, alias = (tmp_path / name for name in names)
    if existing:
        output.write_bytes(b"old")
    muxed, errors = [], []

    def mux(video, wav, partial, total, filters):
        muxed.append(Path(partial))
        Path(partial).write_bytes(b"measured")
        if len(muxed) == 1:
            errors.append(raises(Exception, lambda: audio.loudnorm_mux("v", "w", alias, 1.0)))

    monkeypatch.setattr(audio, "_mux", mux)
    monkeypatch.setattr(audio, "true_peak_db", lambda p: -1.5)
    audio.loudnorm_mux("v", "w", output, 1.0)
    assert isinstance(errors[0], ValueError) and "in progress" in str(errors[0]), errors
    assert len(muxed) == 1, "a spelling variant bypassed an active export reservation"
    assert output.read_bytes() == b"measured"


def test_failed_export_releases_reservation_for_spelling_variant(monkeypatch, tmp_path, raises):
    _stub_probe(monkeypatch)
    monkeypatch.setattr(audio, "_mux", lambda v, w, p, t, f: Path(p).write_bytes(b"measured"))

    def failed_meter(partial):
        raise ValueError("meter failed")

    monkeypatch.setattr(audio, "true_peak_db", failed_meter)
    error = raises(Exception, lambda: audio.loudnorm_mux("v", "w", tmp_path / "out.mp4", 1.0))
    assert isinstance(error, ValueError) and str(error) == "meter failed", repr(error)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(audio, "true_peak_db", lambda p: -1.5)
    audio.loudnorm_mux("v", "w", tmp_path / "OUT.mp4", 1.0)
    assert (tmp_path / "OUT.mp4").read_bytes() == b"measured"
