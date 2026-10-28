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
