"""End-to-end through bin/promo-video: config check without a key, checker self-test, and a placeholder render."""
import json
import shutil
import subprocess

import pytest


def _run(repo_root, args, env):
    return subprocess.run([str(repo_root / "bin" / "promo-video"), *args], cwd=repo_root, env=env,
                          capture_output=True, text=True, timeout=600)


def test_cli_config_check_without_key(repo_root, env_without_key):
    env = dict(env_without_key, PROMO_VIDEO_CONFIG="/nonexistent")
    r = _run(repo_root, ["config", "check"], env)
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "GEMINI_API_KEY" in out and "/nonexistent" in out


def test_cli_check_self_test(repo_root, env_without_key):
    r = _run(repo_root, ["check", "--self-test"], env_without_key)
    lines = [x for x in r.stdout.splitlines() if x.strip()]
    assert r.returncode == 0, r.stdout + r.stderr
    assert lines and all(x.startswith("PASS") for x in lines)


def test_cli_plan_states_paid_requests(repo_root, env_without_key):
    r = _run(repo_root, ["plan", "examples/hello"], env_without_key)
    assert r.returncode == 0, r.stderr
    assert "paid requests" in r.stdout and "voice: 2" in r.stdout and "music: 4" in r.stdout


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_cli_render_check_privacy_sheet(repo_root, env_without_key, tmp_path):
    out = tmp_path / "hello.mp4"
    env = dict(env_without_key, PROMO_VIDEO_CONFIG="/nonexistent")
    r = _run(repo_root, ["render", "examples/hello", "--placeholder-audio", "--out", str(out)], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.exists() and (tmp_path / "hello.edl.json").exists(), r.stdout + r.stderr
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(out)], capture_output=True, text=True, check=True).stdout)
    edl = json.loads((tmp_path / "hello.edl.json").read_text())
    assert dur > 0 and abs(dur - edl["total"]) <= 0.1
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,sample_rate",
                            "-of", "json", str(out)], capture_output=True, text=True, check=True).stdout
    streams = {s["codec_type"]: s for s in json.loads(probe)["streams"]}
    assert streams["video"]["width"] == 1920 and streams["video"]["height"] == 1080
    assert streams["audio"]["sample_rate"] == "48000"
    r = _run(repo_root, ["check", str(out)], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sum(1 for x in r.stdout.splitlines() if x.startswith("SKIP")) == 1
    r = _run(repo_root, ["privacy", str(out), "--step", "2"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    sheet = tmp_path / "sheet.png"
    r = _run(repo_root, ["sheet", str(out), "--step", "2", "--out", str(sheet)], env)
    assert r.returncode == 0 and sheet.exists(), r.stdout + r.stderr
