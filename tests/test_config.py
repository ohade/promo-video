"""Invariants 2 and 6: key lookup order, the key is never shown, Whisper is optional with no default URL."""
import tomllib
from pathlib import Path

import pytest

from promovideo import config


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_config_search_paths_default_order(tmp_path):
    home, repo = tmp_path / "home", tmp_path / "repo"
    paths = config.search_paths(env={}, home=home, repo_root=repo)
    assert paths == [home / ".config" / "promo-video" / "config.toml", repo / "config.local.toml"]


def test_config_env_path_replaces_defaults(tmp_path):
    paths = config.search_paths(env={"PROMO_VIDEO_CONFIG": str(tmp_path / "x.toml")}, home=tmp_path, repo_root=tmp_path)
    assert paths == [tmp_path / "x.toml"]


def test_config_env_key_wins_over_file(tmp_path):
    from conftest import fake_key
    cfg_file = _write(tmp_path / "c.toml", 'gemini_api_key = "from-file"\n')
    cfg = config.load_config(env={"GEMINI_API_KEY": fake_key(), "PROMO_VIDEO_CONFIG": str(cfg_file)},
                             home=tmp_path, repo_root=tmp_path)
    assert cfg.api_key() == fake_key()
    assert cfg.key_source == "environment GEMINI_API_KEY"


def test_config_key_from_user_config_then_repo_local(tmp_path):
    home, repo = tmp_path / "home", tmp_path / "repo"
    _write(repo / "config.local.toml", 'gemini_api_key = "repo-local"\n')
    cfg = config.load_config(env={}, home=home, repo_root=repo)
    assert cfg.api_key() == "repo-local"
    assert cfg.key_source == str(repo / "config.local.toml")
    _write(home / ".config" / "promo-video" / "config.toml", 'gemini_api_key = "user-config"\n')
    cfg = config.load_config(env={}, home=home, repo_root=repo)
    assert cfg.api_key() == "user-config"


def test_config_missing_key_error_names_setting_and_paths(tmp_path, raises):
    cfg = config.load_config(env={"PROMO_VIDEO_CONFIG": "/nonexistent"}, home=tmp_path, repo_root=tmp_path)
    err = raises(config.KeyMissing, cfg.api_key)
    assert err is not None
    msg = str(err)
    assert "GEMINI_API_KEY" in msg and "/nonexistent" in msg and "gemini_api_key" in msg


def test_config_key_never_in_repr_or_report(tmp_path):
    from conftest import fake_key
    key = fake_key()
    cfg = config.load_config(env={"GEMINI_API_KEY": key}, home=tmp_path, repo_root=tmp_path)
    assert key not in repr(cfg) and key not in str(cfg)
    code, lines = config.check_report(cfg)
    text = "\n".join(lines)
    assert key not in text and key[:12] not in text
    assert "GEMINI_API_KEY" in text


def test_config_check_report_fails_without_key(tmp_path):
    cfg = config.load_config(env={"PROMO_VIDEO_CONFIG": "/nonexistent"}, home=tmp_path, repo_root=tmp_path)
    code, lines = config.check_report(cfg)
    text = "\n".join(lines)
    assert code != 0
    assert "GEMINI_API_KEY" in text and "/nonexistent" in text


def test_config_whisper_optional_no_default(tmp_path):
    cfg = config.load_config(env={"PROMO_VIDEO_CONFIG": "/nonexistent"}, home=tmp_path, repo_root=tmp_path)
    assert cfg.whisper_url is None
    _, lines = config.check_report(cfg)
    assert sum(1 for x in lines if x.startswith("SKIP") and "whisper" in x.lower()) == 1
    f = _write(tmp_path / "w.toml", 'whisper_url = "http://localhost:9/v1/audio/transcriptions"\n')
    cfg = config.load_config(env={"PROMO_VIDEO_CONFIG": str(f)}, home=tmp_path, repo_root=tmp_path)
    assert cfg.whisper_url == "http://localhost:9/v1/audio/transcriptions"


def test_config_no_hardcoded_whisper_port():
    src = (Path(config.__file__).resolve().parent).glob("*.py")
    for path in src:
        text = path.read_text()
        assert "127.0.0.1:" not in text and "localhost:" not in text, path.name


def test_config_example_has_placeholders_only(repo_root):
    text = (repo_root / "config.example.toml").read_text()
    assert "gemini_api_key" in text and "whisper_url" in text
    assert "AIza" not in text


def test_config_local_files_are_gitignored(repo_root):
    import subprocess
    for name in ("config.local.toml", ".public-denylist.local"):
        r = subprocess.run(["git", "-C", str(repo_root), "check-ignore", "-q", name])
        assert r.returncode == 0, name


def _never_shows(err, key):
    """The key is absent from the message, the repr and the whole formatted traceback (cause and context included)."""
    import traceback
    text = str(err) + repr(err) + "".join(traceback.format_exception(err))
    return key not in text and key[:12] not in text


def test_config_misspelled_setting_key_not_in_missing_message(tmp_path, raises):
    from conftest import fake_key
    key = fake_key()
    f = _write(tmp_path / "c.toml", f'GEMINI_API_KEY = "{key}"\ngemini_api_kye = "{key}"\n')
    cfg = config.load_config(env={"PROMO_VIDEO_CONFIG": str(f)}, home=tmp_path, repo_root=tmp_path)
    err = raises(config.KeyMissing, cfg.api_key)
    assert err is not None and "GEMINI_API_KEY" in str(err)
    assert _never_shows(err, key)
    _, lines = config.check_report(cfg)
    assert key not in "\n".join(lines)


def test_config_invalid_toml_key_not_in_error(tmp_path, raises):
    from conftest import fake_key
    key = fake_key()
    f = _write(tmp_path / "c.toml", f"whisper_url = 1\ngemini_api_key = {key}\n")
    err = raises(config.ConfigError, lambda: config.load_config(env={"PROMO_VIDEO_CONFIG": str(f)}, home=tmp_path,
                                                                repo_root=tmp_path))
    assert err is not None and str(f) in str(err)
    assert _never_shows(err, key)


def _placeholder_value(repo_root):
    return tomllib.loads((repo_root / "config.example.toml").read_text())["gemini_api_key"]


def _any_tool(tool):
    return "/stub/bin/" + tool


def test_config_placeholder_constant_matches_example(repo_root):
    assert getattr(config, "PLACEHOLDER_KEY", None) == _placeholder_value(repo_root)


def test_config_example_copy_as_user_config_reports_no_key(tmp_path, repo_root):
    home, repo = tmp_path / "home", tmp_path / "repo"
    user_cfg = home / ".config" / "promo-video" / "config.toml"
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_bytes((repo_root / "config.example.toml").read_bytes())
    cfg = config.load_config(env={}, home=home, repo_root=repo)
    code, lines = config.check_report(cfg, which=_any_tool)
    assert code == 1, lines
    assert any(x.startswith("FAIL key: GEMINI_API_KEY") for x in lines), lines
    assert _placeholder_value(repo_root) not in "\n".join(lines)


@pytest.mark.parametrize("value", ["", "   ", "PLACEHOLDER"])
def test_config_no_real_key_in_user_config_falls_through_to_repo_local(tmp_path, repo_root, value):
    from conftest import fake_key
    key = fake_key()
    if value == "PLACEHOLDER":
        value = _placeholder_value(repo_root)
    home, repo = tmp_path / "home", tmp_path / "repo"
    user_cfg = _write(home / ".config" / "promo-video" / "config.toml",
                      f'gemini_api_key = "{value}"\nwhisper_url = "http://whisper.invalid/v1"\n')
    local = _write(repo / "config.local.toml", f'gemini_api_key = "{key}"\nwhisper_url = "http://other.invalid/v1"\n')
    cfg = config.load_config(env={}, home=home, repo_root=repo)
    code, lines = config.check_report(cfg, which=_any_tool)
    assert code == 0, lines
    assert cfg.key_source == str(local)
    assert cfg.api_key() == key
    assert cfg.loaded_from == str(user_cfg) and cfg.whisper_url == "http://whisper.invalid/v1"
    assert key not in "\n".join(lines)


def test_config_real_key_in_user_config_wins_over_repo_local(tmp_path):
    from conftest import fake_key
    user_key = fake_key()
    local_key = "AIza" + "R" * 35
    home, repo = tmp_path / "home", tmp_path / "repo"
    user_cfg = _write(home / ".config" / "promo-video" / "config.toml", f'gemini_api_key = "{user_key}"\n')
    _write(repo / "config.local.toml", f'gemini_api_key = "{local_key}"\n')
    cfg = config.load_config(env={}, home=home, repo_root=repo)
    assert cfg.api_key() == user_key and cfg.key_source == str(user_cfg)


def test_config_placeholder_or_blank_env_key_is_not_a_key(tmp_path, repo_root):
    from conftest import fake_key
    key = fake_key()
    local = _write(tmp_path / "repo" / "config.local.toml", f'gemini_api_key = "{key}"\n')
    for value in (_placeholder_value(repo_root), "  "):
        cfg = config.load_config(env={"GEMINI_API_KEY": value}, home=tmp_path / "home", repo_root=tmp_path / "repo")
        assert cfg.key_source == str(local) and cfg.api_key() == key, repr(value)
