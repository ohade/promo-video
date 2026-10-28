"""Edit-list resolution: timeline, per-frame clock rows, placeholder narration durations."""
import pytest

np = pytest.importorskip("numpy")

from promovideo import edl as E  # noqa: E402


def test_edl_capture_wait_clock_follows_ramped_speed():
    seg = dict(id="c1", kind="capture", mode="WAIT", speed=20.0, raw_in=10.0, frames=60, ramp_from=1.0, ramp_in=0.4,
               clock=True)
    rows = E.capture_timeline(seg)
    assert len(rows) == 60
    assert all(abs(r["clock_rate"] - r["speed"]) < 1e-9 for r in rows)
    assert rows[0]["speed"] < 20.0 and rows[-1]["speed"] == 20.0
    assert rows[-1]["badge"] == "x20"


def test_edl_capture_hold_freezes_clock():
    rows = E.capture_timeline(dict(id="h", kind="capture", mode="HOLD", raw_in=5.0, frames=10, clock=True))
    assert {r["speed"] for r in rows} == {0.0} and {r["badge"] for r in rows} == {"PAUSED"}


def test_edl_resolve_hello_with_placeholder_audio(repo_root):
    project = repo_root / "examples" / "hello"
    e = E.load_project(project)
    rows = E.resolve(e, project, placeholder_audio=True)
    kinds = {s["kind"] for s in e["segments"]}
    assert kinds == {"graphic", "black"}
    assert len(rows) == sum(s["frames"] for s in e["segments"])
    assert e["total"] == pytest.approx(len(rows) / E.FPS, abs=1e-4)
    assert [v["id"] for v in e["audio"]["vo"]] == [i for i, _ in e["script_lines"]]
    assert len(e["script_lines"]) == 2
    assert all(v["dur"] > 0 for v in e["audio"]["vo"])
    assert all(r["clock_visible"] == 0 for r in rows)


def test_edl_placeholder_duration_scales_with_words():
    short, long_ = E.placeholder_duration("Hi."), E.placeholder_duration(" ".join(["word"] * 26))
    assert 0.5 <= short < long_
    assert long_ == pytest.approx(26 / E.PLACEHOLDER_WPS + 0.3, abs=1e-6)


def test_edl_missing_voice_without_placeholder_names_command(repo_root, tmp_path, raises):
    import shutil
    project = tmp_path / "hello"
    shutil.copytree(repo_root / "examples" / "hello", project)
    e = E.load_project(project)
    err = raises(FileNotFoundError, lambda: E.resolve(e, project, placeholder_audio=False))
    assert err is not None and "promo-video voice" in str(err)
