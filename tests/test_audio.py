"""Invariant 5: loudness target and true-peak ceiling keep the v2 values; the mix ducks music and SFX under the voice."""
import pytest

from promovideo import audio


def test_audio_loudness_pins():
    assert audio.TARGET_LUFS == -16.0
    assert audio.TRUE_PEAK_CEILING_DB == -1.3
    assert audio.LRA == 11
    assert audio.PROBE_TP_DB == -2.0
    assert audio.LOUDNORM_TP_DB == -2.5
    assert audio.LIMITER_LIMIT == 0.78
    assert audio.VO_DUCK_DB == 12.0
    assert audio.SFX_DUCK_DB == 10.0
    assert audio.MIX_PEAK == 0.98


def test_audio_probe_filter_exact():
    assert audio.probe_filter() == "loudnorm=I=-16:TP=-2.0:LRA=11:print_format=json"


def test_audio_apply_filter_exact():
    measured = {"input_i": "-20.1", "input_tp": "-3.2", "input_lra": "5.0", "input_thresh": "-30.4",
                "target_offset": "0.3"}
    assert audio.apply_filter(measured, 0.78) == (
        "loudnorm=I=-16:TP=-2.5:LRA=11:measured_I=-20.1:measured_TP=-3.2:measured_LRA=5.0:measured_thresh=-30.4:"
        "offset=0.3:linear=true,aresample=48000,alimiter=limit=0.780:level=disabled:attack=1:release=60")


def test_audio_second_pass_limit():
    assert audio.second_pass_limit(-1.5) is None          # under the -1.3 dBTP ceiling: keep the first mux
    assert audio.second_pass_limit(-1.3) is None
    got = audio.second_pass_limit(-0.8)                    # 0.5 dB over: lower the limiter by 0.5 + 0.2 dB
    assert got == pytest.approx(0.78 * 10 ** (-0.7 / 20), rel=1e-9)


def test_audio_mix_ducks_music_under_voice():
    np = pytest.importorskip("numpy")
    sr = audio.SR
    total = 3.0
    clips = {"vo.wav": np.zeros((sr, 2), np.float32), "music.wav": np.full((int(total * sr), 2), 0.5, np.float32)}
    spec = {"vo": [{"id": "l01", "file": "vo.wav", "start": 1.0, "dur": 1.0}],
            "music": [{"file": "music.wav", "start": 0.0, "dur": total}]}
    mix = audio.mix(spec, total, load=lambda path: clips[path])
    assert mix.shape == (int(total * sr), 2)
    assert mix[int(0.5 * sr), 0] == pytest.approx(0.5, abs=1e-4)               # before the voice: full music
    assert mix[int(1.5 * sr), 0] == pytest.approx(0.5 * 10 ** (-12 / 20), abs=1e-4)   # under the voice: -12 dB
    assert mix[int(2.8 * sr), 0] == pytest.approx(0.5, abs=1e-4)               # after the release: full again


def test_audio_mix_peak_limited():
    np = pytest.importorskip("numpy")
    sr = audio.SR
    loud = np.full((sr, 2), 3.0, np.float32)
    mix = audio.mix({"music": [{"file": "m", "start": 0.0, "dur": 1.0}]}, 1.0, load=lambda p: loud)
    assert float(np.max(np.abs(mix))) == pytest.approx(0.98, abs=1e-4)


def _fake_loudnorm(monkeypatch, tmp_path, peaks, mux_fails_at=None, meter_fails_at=None, input_i="-20.1"):
    """Fake probe, mux and peak meter: no ffmpeg runs. The mux writes the path it is given; the meter logs each path
    it reads and whether out_mp4 existed then. Returns (mux limiter levels, out_mp4 path, meter log)."""
    import re
    import subprocess
    from pathlib import Path
    from types import SimpleNamespace
    measured = ('{"input_i": "%s", "input_tp": "-3.2", "input_lra": "5.0", "input_thresh": "-30.4", '
                '"target_offset": "0.3"}' % input_i)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stderr="loudnorm summary\n" + measured))
    out = tmp_path / "out.mp4"
    limits, readings, meter_log = [], list(peaks), []

    def mux(video, wav, out_mp4, total, af):
        found = re.search(r"alimiter=limit=([0-9.]+)", af)
        limits.append(float(found.group(1)) if found else None)
        if len(limits) == mux_fails_at:
            raise subprocess.CalledProcessError(1, ["ffmpeg"])
        Path(out_mp4).write_bytes(b"mp4")

    def peak(path):
        meter_log.append((Path(path), out.exists()))
        if len(meter_log) == meter_fails_at:
            raise ValueError("meter broke")
        return readings.pop(0) if len(readings) > 1 else readings[0]

    monkeypatch.setattr(audio, "_mux", mux)
    monkeypatch.setattr(audio, "true_peak_db", peak)
    return limits, out, meter_log


def test_audio_loudnorm_mux_measures_every_retry(monkeypatch, tmp_path):
    limits, out, _ = _fake_loudnorm(monkeypatch, tmp_path, [-0.8, -1.2, -1.5])
    audio.loudnorm_mux("v.mp4", "m.wav", out, 3.0)
    assert len(limits) == 3
    assert limits[0] == 0.78 and limits[0] > limits[1] > limits[2]
    assert out.exists()


def test_audio_loudnorm_mux_raises_when_still_over_ceiling(monkeypatch, tmp_path, raises):
    limits, out, _ = _fake_loudnorm(monkeypatch, tmp_path, [-1.0])
    err = raises(Exception, lambda: audio.loudnorm_mux("v.mp4", "m.wav", out, 3.0))
    assert err is not None, "returned with the encoded peak still over the ceiling"
    assert isinstance(err, audio.TruePeakOverCeiling)
    assert err.peak_db == -1.0 and err.ceiling_db == audio.TRUE_PEAK_CEILING_DB
    assert "-1.0" in str(err) and "-1.3" in str(err)
    assert len(limits) == 4 and all(a > b for a, b in zip(limits, limits[1:]))
    assert not out.exists()


def test_audio_loudnorm_mux_under_ceiling_muxes_once(monkeypatch, tmp_path):
    limits, out, _ = _fake_loudnorm(monkeypatch, tmp_path, [-1.5])
    audio.loudnorm_mux("v.mp4", "m.wav", out, 3.0)
    assert limits == [0.78] and out.exists()


def test_audio_loudnorm_mux_never_measures_at_out_mp4(monkeypatch, tmp_path):
    limits, out, meter_log = _fake_loudnorm(monkeypatch, tmp_path, [-0.8, -1.2, -1.5])
    out.write_bytes(b"stale")
    audio.loudnorm_mux("v.mp4", "m.wav", out, 3.0)
    assert len(meter_log) == 3
    assert all(path != out and path.parent == out.parent and not out_existed for path, out_existed in meter_log), meter_log
    assert out.read_bytes() == b"mp4" and [p.name for p in tmp_path.iterdir()] == ["out.mp4"]


@pytest.mark.parametrize("failure, peaks, kwargs, error", [
    ("mux error on the retry", [-0.8], {"mux_fails_at": 2}, "CalledProcessError"),
    ("mux error on the first pass", [-1.5], {"mux_fails_at": 1}, "CalledProcessError"),
    ("meter error on the retry", [-0.8], {"meter_fails_at": 2}, "meter broke"),
    ("meter error on the first pass", [-1.5], {"meter_fails_at": 1}, "meter broke"),
    ("over the ceiling after the cap", [-1.0], {}, "TruePeakOverCeiling"),
    ("silent mix mux error", [-1.5], {"mux_fails_at": 1, "input_i": "-inf"}, "CalledProcessError"),
])
def test_audio_loudnorm_mux_failure_leaves_no_file(monkeypatch, tmp_path, raises, failure, peaks, kwargs, error):
    limits, out, _ = _fake_loudnorm(monkeypatch, tmp_path, peaks, **kwargs)
    out.write_bytes(b"stale export from an earlier run")
    err = raises(Exception, lambda: audio.loudnorm_mux("v.mp4", "m.wav", out, 3.0))
    assert err is not None, failure
    assert error in (type(err).__name__, str(err)), (failure, repr(err))
    assert list(tmp_path.iterdir()) == [], (failure, list(tmp_path.iterdir()))


def test_audio_loudnorm_mux_silent_mix_muxes_once(monkeypatch, tmp_path):
    limits, out, meter_log = _fake_loudnorm(monkeypatch, tmp_path, [-1.5], input_i="-inf")
    audio.loudnorm_mux("v.mp4", "m.wav", out, 3.0)
    assert limits == [None] and meter_log == []
    assert [p.name for p in tmp_path.iterdir()] == ["out.mp4"]


def test_audio_true_peak_error_is_one_cli_line(monkeypatch, tmp_path, capsys):
    from promovideo import cli, render

    def build(project, out, placeholder_audio=False):
        raise audio.TruePeakOverCeiling(-1.04, audio.TRUE_PEAK_CEILING_DB, 4)

    monkeypatch.setattr(render, "build", build)
    try:
        code = cli.main(["render", str(tmp_path), "--out", str(tmp_path / "o.mp4")])
    except audio.TruePeakOverCeiling:
        code = "traceback"
    lines = capsys.readouterr().err.strip().splitlines()
    assert code == 2, code
    assert lines == ["error: encoded true peak -1.04 dBTP is above the -1.3 dBTP ceiling after 4 limiter passes; "
                     "the export was removed"], lines
