"""Edit-list checker: generic rules, a self-test that proves each rule catches a broken copy, optional Whisper."""
import copy
import json

from promovideo import check


def test_check_self_test_all_pass():
    ok, lines = check.self_test()
    assert ok is True
    assert lines and all(x.startswith("PASS") for x in lines), lines
    covered = {x.split("(")[1].split(",")[0] for x in lines if "self-test (" in x}
    assert covered >= {"a", "b", "c", "d", "e", "f", "h"}


def test_check_sample_passes_every_rule():
    edl, rows = check.sample_edl()
    res = check.run_rules(edl, rows, edl["total"], max_shot_s=4.0)
    assert res and all(v == [] for v in res.values()), res


def test_check_pacing_rule_uses_preset_limit():
    edl, rows = check.sample_edl()
    e = copy.deepcopy(edl)
    seg = e["segments"][0]
    seg["dur"], seg["frames"], seg["change_points"] = 6.0, 180, [0.0]
    assert check.run_rules(e, rows, edl["total"], max_shot_s=4.0)["b"]
    assert not check.run_rules(e, rows, edl["total"], max_shot_s=10.0)["b"]


def test_check_clock_rate_must_follow_speed():
    edl, rows = check.sample_edl()
    r = copy.deepcopy(rows)
    row = next(x for x in r if x["clock_visible"] == "1" and float(x["speed"]) > 0)
    row["clock_rate"] = str(float(row["speed"]) + 5)
    assert check.run_rules(edl, r, edl["total"], max_shot_s=4.0)["a"]


def test_check_forbidden_window_from_edl():
    edl, rows = check.sample_edl()
    e = copy.deepcopy(edl)
    cap = next(s for s in e["segments"] if s["kind"] == "capture")
    e["forbidden"] = [[cap["source"], cap["raw_in"], cap["raw_in"] + 0.1]]
    assert check.run_rules(e, rows, edl["total"], max_shot_s=4.0)["e"]


def test_check_whisper_absent_is_one_skip_line(tmp_path):
    edl, rows = check.sample_edl()
    path = check.save_sample(tmp_path)
    ok, lines = check.check_video(path, "unused.mp4", whisper_url=None, duration=edl["total"])
    assert ok is True, lines
    skips = [x for x in lines if x.startswith("SKIP")]
    assert len(skips) == 1 and "(g)" in skips[0]
    assert not any(x.startswith("FAIL") for x in lines)


def test_check_whisper_present_uses_transport(tmp_path, fake_transport):
    edl, _ = check.sample_edl()
    texts = [edl["script"][v["id"]] for v in edl["audio"]["vo"]]
    t = fake_transport(heard=list(texts))
    errs, line = check.transcription(edl, "unused.mp4", "http://whisper.invalid/v1", t,
                                     extract=lambda video, start, dur, out: None)
    assert errs == [] and line.startswith("PASS (g)")
    assert [c[0] for c in t.calls] == ["file"] * len(texts)
    t = fake_transport(heard=["completely different words"] * len(texts))
    errs, line = check.transcription(edl, "unused.mp4", "http://whisper.invalid/v1", t,
                                     extract=lambda video, start, dur, out: None)
    assert errs and line.startswith("FAIL (g)")


def test_check_saved_sample_roundtrip(tmp_path):
    path = check.save_sample(tmp_path)
    data = json.loads(path.read_text())
    assert data["frames_log"].endswith(".frames.tsv")
    assert (tmp_path / data["frames_log"]).exists()
