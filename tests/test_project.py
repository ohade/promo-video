"""Project scaffolding (default output root, env override) and the screen-recording command."""
from promovideo import project, record


def test_project_slug():
    assert project.slug("  My Cool Feature: v2!  ") == "my-cool-feature-v2"
    assert project.slug("!!!") == "promo"


def test_project_new_default_root(tmp_path):
    path = project.new_project("Fast Search", "nolan", env={}, cwd=tmp_path)
    assert path == tmp_path / "promo-video-out" / "fast-search"
    for name in ("script.txt", "edl.json", "project.toml"):
        assert (path / name).exists(), name
    assert (path / "footage").is_dir() and (path / "material").is_dir()
    assert 'preset = "nolan"' in (path / "project.toml").read_text()


def test_project_new_env_root(tmp_path):
    path = project.new_project("Fast Search", "bay", env={"PROMO_VIDEO_OUT": str(tmp_path / "x")}, cwd=tmp_path)
    assert path == tmp_path / "x" / "fast-search"


def test_project_refuses_unknown_style(tmp_path, raises):
    err = raises(ValueError, lambda: project.new_project("T", "western", env={}, cwd=tmp_path))
    assert err is not None


def test_record_command_macos():
    cmd = record.record_command("out.mp4", 12, screen=1, platform="darwin")
    assert cmd[:3] == ["ffmpeg", "-y", "-f"] and "avfoundation" in cmd
    assert cmd[cmd.index("-i") + 1] == "Capture screen 1:none"
    assert cmd[cmd.index("-t") + 1] == "12" and cmd[-1] == "out.mp4"


def test_record_command_linux():
    cmd = record.record_command("out.mp4", 5, platform="linux")
    assert "x11grab" in cmd and cmd[-1] == "out.mp4"
