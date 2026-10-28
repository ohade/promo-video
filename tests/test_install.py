"""scripts/install.sh, run against stub binaries only: nothing is installed and nothing reaches the network.

Each test copies the script into a temporary repo, sets HOME to a temporary folder, and builds PATH from two folders
under tmp_path: stubs (brew, apt-get, apt-cache, sudo, id, uname, curl, pythons, ffmpeg, ffprobe, tesseract) that log
their argv and fake what a package manager would add, and links to the few standard tools the script needs. Pythons
are stubs too: `-m venv` makes a stub venv whose `-m pip install` only logs, so no real pip ever runs.
"""
import os
import re
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASH = "/bin/bash" if os.path.exists("/bin/bash") else shutil.which("bash")
SYSTEM_DIRS = os.pathsep.join(["/usr/bin", "/bin"])
TOOLS = ("basename", "cat", "chmod", "cp", "dirname", "env", "grep", "head", "ln", "mkdir", "mktemp", "readlink",
         "rm", "sed", "touch", "tr")
HOMEBREW_URL = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
INSTALL_CALL = re.compile(r"^(?:brew install|apt-get install|homebrew-installer)|-m (?:venv|ensurepip)|-m pip install")

LOGGER = """#!/bin/bash
echo "NAME $*" >> "$STUB_LOG"
exit 0
"""

PACKAGE_MANAGER = """#!/bin/bash
echo "NAME $*" >> "$STUB_LOG"
if [ "$1" = install ]; then
  for p in "$@"; do
    if [ -d "$STUB_SUPPORT/pkg/$p" ]; then cp "$STUB_SUPPORT/pkg/$p/"* "$(dirname "$0")/"; fi
  done
fi
exit 0
"""

PYTHON = """#!/bin/bash
echo "NAME $*" >> "$STUB_LOG"
case "$*" in *version_info*) echo "VERSION"; exit 0 ;; esac
if [ "$1" = -m ] && [ "$2" = venv ]; then
  for target in "$@"; do :; done
  mkdir -p "$target/bin"
  sed "s/@PYVER@/VERSION/" "$STUB_SUPPORT/venv-python" > "$target/bin/python"
  chmod +x "$target/bin/python"
fi
exit 0
"""

VENV_PYTHON = """#!/bin/bash
echo "venv-python $*" >> "$STUB_LOG"
marker="$(dirname "$0")/../stub-installed"
case "$*" in
  *version_info*) echo "@PYVER@"; exit 0 ;;
  *"import numpy"*) [ -f "$marker" ]; exit ;;
esac
if [ "$1" = -m ] && [ "$2" = pip ] && [ "$3" = install ]; then touch "$marker"; fi
exit 0
"""

SUDO = """#!/bin/bash
echo "sudo $*" >> "$STUB_LOG"
exec "$@"
"""

ID = """#!/bin/bash
if [ "$1" = -u ]; then echo "$STUB_UID"; else echo "uid=$STUB_UID"; fi
"""

UNAME = """#!/bin/bash
echo "$STUB_OS"
"""

APT_CACHE = """#!/bin/bash
echo "apt-cache $*" >> "$STUB_LOG"
printf 'python3:\\n  Installed: (none)\\n  Candidate: %s\\n' "$STUB_APT_PY"
"""

CURL = """#!/bin/bash
echo "curl $*" >> "$STUB_LOG"
cat <<'SCRIPT'
echo "homebrew-installer" >> "$STUB_LOG"
mkdir -p "$STUB_BREW_DIR"
cp "$STUB_SUPPORT/brew" "$STUB_BREW_DIR/brew"
SCRIPT
"""

PROMO_VIDEO = """#!/bin/bash
echo "promo-video $*" >> "$STUB_LOG"
if [ "$*" = "config check" ]; then echo "FAIL key: GEMINI_API_KEY is not set"; exit 1; fi
exit 0
"""


def _write(path, text, name="", version=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("NAME", name).replace("VERSION", version))
    path.chmod(0o755)


class Machine:
    """A fake computer under `base`: HOME, a copy of the repo, stub binaries, and the stub call log."""

    def __init__(self, base, os_name="Darwin", uid=1000, apt_python="3.11.2-1+b1"):
        self.base = base
        self.home = base / "home"
        self.repo = base / "repo"
        self.stubs = base / "stubs"
        self.support = base / "support"
        self.log = base / "stub.log"
        self.brew_dir = base / "brew-prefix" / "bin"
        self.home.mkdir(parents=True)
        self._make_repo()
        self._make_stubs(apt_python)
        tool_dir = base / "tools"
        tool_dir.mkdir()
        for name in TOOLS:
            real = shutil.which(name, path=SYSTEM_DIRS)
            if real:
                (tool_dir / name).symlink_to(real)
        self.env = {"PATH": f"{self.stubs}{os.pathsep}{tool_dir}", "HOME": str(self.home), "TMPDIR": str(base),
                    "LC_ALL": "C", "STUB_LOG": str(self.log), "STUB_SUPPORT": str(self.support),
                    "STUB_OS": os_name, "STUB_UID": str(uid), "STUB_APT_PY": apt_python,
                    "STUB_BREW_DIR": str(self.brew_dir), "PROMO_VIDEO_BREW_DIRS": str(self.brew_dir)}

    def _make_repo(self):
        for rel in ("scripts/install.sh", "pyproject.toml", "config.example.toml", "skills/promo-video/SKILL.md"):
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, self.repo / rel)
        _write(self.repo / "bin" / "promo-video", PROMO_VIDEO)

    def _make_stubs(self, apt_python):
        _write(self.stubs / "uname", UNAME)
        _write(self.stubs / "id", ID)
        _write(self.support / "venv-python", VENV_PYTHON)
        _write(self.support / "brew", PACKAGE_MANAGER, "brew")
        _write(self.support / "pkg" / "python@3.12" / "python3.12", PYTHON, "python3.12", "3.12")
        apt_version = ".".join(apt_python.split(".")[:2])
        _write(self.support / "pkg" / "python3" / "python3", PYTHON, "python3", apt_version)
        for pkg in ("ffmpeg",):
            for tool in ("ffmpeg", "ffprobe"):
                _write(self.support / "pkg" / pkg / tool, LOGGER, tool)
        for pkg in ("tesseract", "tesseract-ocr"):
            _write(self.support / "pkg" / pkg / "tesseract", LOGGER, "tesseract")

    def python(self, name, version):
        _write(self.stubs / name, PYTHON, name, version)

    def tools(self, *names):
        for name in names:
            _write(self.stubs / name, LOGGER, name)

    def brew(self):
        shutil.copy2(self.support / "brew", self.stubs / "brew")

    def apt(self, sudo=True):
        _write(self.stubs / "apt-get", PACKAGE_MANAGER, "apt-get")
        _write(self.stubs / "apt-cache", APT_CACHE)
        if sudo:
            _write(self.stubs / "sudo", SUDO)

    def curl(self):
        _write(self.stubs / "curl", CURL)

    def run(self, *args, env=None, stdin=""):
        full_env = dict(self.env, **(env or {}))
        p = subprocess.run([BASH, str(self.repo / "scripts" / "install.sh"), *args], env=full_env,
                           input=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        return p

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def installs(self):
        return [c for c in self.calls() if INSTALL_CALL.search(c)]

    def package_installs(self, manager):
        return [c.split()[2:] for c in self.calls() if c.startswith(f"{manager} install")]

    @property
    def link(self):
        return self.home / ".claude" / "skills" / "promo-video"

    @property
    def config(self):
        return self.home / ".config" / "promo-video" / "config.toml"


def ready_mac(base, **kw):
    """A Mac that already has Homebrew, Python 3.12 and ffmpeg."""
    m = Machine(base, **kw)
    m.brew()
    m.python("python3.12", "3.12")
    m.tools("ffmpeg", "ffprobe")
    return m


def snapshot(base, skip):
    state = {}
    for dirpath, dirnames, filenames in os.walk(base):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            if p == skip:
                continue
            st = p.lstat()
            target = os.readlink(p) if p.is_symlink() else None
            state[str(p.relative_to(base))] = (stat.S_IFMT(st.st_mode), stat.S_IMODE(st.st_mode), st.st_size,
                                               st.st_mtime_ns, target)
    return state


def pyproject_minimum():
    spec = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["requires-python"]
    m = re.fullmatch(r">=\s*(\d+)\.(\d+)", spec)
    assert m, f"requires-python must be a plain >=X.Y lower bound, got {spec!r}"
    return int(m.group(1)), int(m.group(2))


def test_install_help_lists_every_flag(tmp_path):
    m = Machine(tmp_path)
    p = m.run("--help")
    assert p.returncode == 0, p.stdout
    for flag in ("--dry-run", "--yes", "--with-ocr", "--install-homebrew", "--force-link", "--no-skill", "--help"):
        assert flag in p.stdout, flag
    assert m.installs() == []


def test_install_mac_with_only_system_python_installs_python_with_brew(tmp_path):
    m = Machine(tmp_path)
    m.brew()
    m.python("python3", "3.9")
    m.tools("ffmpeg", "ffprobe")
    p = m.run("--yes")
    assert p.returncode == 0, p.stdout
    assert any("python@3.12" in pkgs for pkgs in m.package_installs("brew")), m.calls()
    assert "python3.12 -m venv " + str(m.repo / ".venv") in m.calls()
    assert not any(c.startswith("python3 -m venv") for c in m.calls())


def test_install_mac_with_python_312_installs_no_python(tmp_path):
    m = ready_mac(tmp_path)
    m.python("python3", "3.9")
    p = m.run("--yes")
    assert p.returncode == 0, p.stdout
    assert m.package_installs("brew") == []
    assert "python3.12 -m venv " + str(m.repo / ".venv") in m.calls()
    assert any(c.startswith("venv-python -m pip install") and c.endswith("-e " + str(m.repo)) for c in m.calls())


def test_install_mac_without_homebrew_exits_2_with_official_command(tmp_path):
    m = Machine(tmp_path)
    m.python("python3", "3.9")
    m.curl()
    p = m.run("--yes")
    assert p.returncode == 2, p.stdout
    assert f'/bin/bash -c "$(curl -fsSL {HOMEBREW_URL})"' in p.stdout
    assert "--install-homebrew" in p.stdout
    assert m.installs() == []
    assert not any(c.startswith("curl") for c in m.calls())


def test_install_homebrew_flag_runs_official_installer(tmp_path):
    m = Machine(tmp_path)
    m.python("python3", "3.9")
    m.tools("ffmpeg", "ffprobe")
    m.curl()
    p = m.run("--yes", "--install-homebrew")
    assert p.returncode == 0, p.stdout
    calls = m.calls()
    assert any(c.startswith("curl") and HOMEBREW_URL in c for c in calls), calls
    assert "homebrew-installer" in calls
    assert calls.index("homebrew-installer") < next(i for i, c in enumerate(calls) if c.startswith("brew install"))
    assert any("python@3.12" in pkgs for pkgs in m.package_installs("brew"))


def test_install_missing_ffmpeg_is_installed(tmp_path):
    m = Machine(tmp_path)
    m.brew()
    m.python("python3.12", "3.12")
    p = m.run("--yes")
    assert p.returncode == 0, p.stdout
    assert any("ffmpeg" in pkgs for pkgs in m.package_installs("brew")), m.calls()


@pytest.mark.parametrize("flags, wanted", [((), False), (("--with-ocr",), True)])
def test_install_tesseract_only_with_ocr_flag(tmp_path, flags, wanted):
    m = ready_mac(tmp_path)
    p = m.run("--yes", *flags)
    assert p.returncode == 0, p.stdout
    asked = any("tesseract" in pkgs for pkgs in m.package_installs("brew"))
    assert asked is wanted, m.calls()


@pytest.mark.parametrize("uid, sudo", [(1000, True), (0, False)])
def test_install_debian_uses_apt_with_sudo_only_when_not_root(tmp_path, uid, sudo):
    m = Machine(tmp_path, os_name="Linux", uid=uid)
    m.apt()
    p = m.run("--yes")
    assert p.returncode == 0, p.stdout
    installs = m.package_installs("apt-get")
    assert installs and {"python3", "python3-venv", "ffmpeg"} <= set(installs[0]), m.calls()
    used_sudo = any(c.startswith("sudo ") for c in m.calls())
    assert used_sudo is sudo, m.calls()
    if sudo:
        assert "sudo" in p.stdout.split("+ sudo", 1)[0], "the script must say it uses sudo before the first sudo call"
    assert "python3 -m venv " + str(m.repo / ".venv") in m.calls()


def test_install_old_debian_python_stops_clearly(tmp_path):
    m = Machine(tmp_path, os_name="Linux", apt_python="3.9.2-3")
    m.apt()
    m.python("python3", "3.9")
    p = m.run("--yes")
    major, minor = pyproject_minimum()
    assert p.returncode == 1, p.stdout
    assert f"{major}.{minor}" in p.stdout and "3.9" in p.stdout, p.stdout
    assert m.installs() == []


def test_install_creates_skill_link(tmp_path):
    m = ready_mac(tmp_path)
    p = m.run("--yes")
    assert p.returncode == 0, p.stdout
    assert m.link.is_symlink()
    assert m.link.resolve() == (m.repo / "skills" / "promo-video").resolve()


def test_install_leaves_correct_link_alone(tmp_path):
    m = ready_mac(tmp_path)
    m.link.parent.mkdir(parents=True)
    m.link.symlink_to(m.repo / "skills" / "promo-video")
    before = m.link.lstat()
    p = m.run("--yes")
    assert p.returncode == 0, p.stdout
    after = m.link.lstat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert "already" in p.stdout


@pytest.mark.parametrize("force", [False, True])
def test_install_real_skill_dir_exits_3_untouched(tmp_path, force):
    m = ready_mac(tmp_path)
    m.link.mkdir(parents=True)
    (m.link / "SKILL.md").write_text("mine\n")
    p = m.run("--yes", *(["--force-link"] if force else []))
    assert p.returncode == 3, p.stdout
    assert not m.link.is_symlink() and (m.link / "SKILL.md").read_text() == "mine\n"
    assert "promo-video" in p.stdout and "not a link" in p.stdout
    assert m.installs() == []


def test_install_other_link_needs_force_link(tmp_path):
    m = ready_mac(tmp_path)
    other = tmp_path / "other-skill"
    other.mkdir()
    m.link.parent.mkdir(parents=True)
    m.link.symlink_to(other)
    p = m.run("--yes")
    assert p.returncode == 3, p.stdout
    assert m.link.resolve() == other.resolve()
    assert "--force-link" in p.stdout
    p = m.run("--yes", "--force-link")
    assert p.returncode == 0, p.stdout
    assert m.link.is_symlink() and m.link.resolve() == (m.repo / "skills" / "promo-video").resolve()
    assert other.is_dir()


def test_install_no_skill_skips_the_link(tmp_path):
    m = ready_mac(tmp_path)
    p = m.run("--yes", "--no-skill")
    assert p.returncode == 0, p.stdout
    assert not os.path.lexists(m.link)


@pytest.mark.parametrize("env_config", [False, True])
def test_install_copies_config_with_mode_600_and_no_key(tmp_path, env_config):
    m = ready_mac(tmp_path)
    target = tmp_path / "elsewhere" / "pv.toml" if env_config else m.config
    p = m.run("--yes", env={"PROMO_VIDEO_CONFIG": str(target)} if env_config else None)
    assert p.returncode == 0, p.stdout
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_bytes() == (ROOT / "config.example.toml").read_bytes()
    assert not re.search(r"AIza[0-9A-Za-z_-]{35}", target.read_text())
    assert "GEMINI_API_KEY" in p.stdout and str(target) in p.stdout


def test_install_keeps_existing_config(tmp_path):
    m = ready_mac(tmp_path)
    key = "AIza" + "Q" * 35
    m.config.parent.mkdir(parents=True)
    m.config.write_text(f'gemini_api_key = "{key}"\n')
    m.config.chmod(0o644)
    before = m.config.stat()
    p = m.run("--yes")
    assert p.returncode == 0, p.stdout
    after = m.config.stat()
    assert m.config.read_text() == f'gemini_api_key = "{key}"\n'
    assert (stat.S_IMODE(after.st_mode), after.st_mtime_ns) == (0o644, before.st_mtime_ns)
    assert key not in p.stdout and "QQQQ" not in p.stdout
    assert "kept" in p.stdout


@pytest.mark.parametrize("has_brew", [True, False])
def test_install_dry_run_changes_nothing(tmp_path, has_brew):
    m = Machine(tmp_path)
    if has_brew:
        m.brew()
    m.python("python3", "3.9")
    m.curl()
    before = snapshot(tmp_path, m.log)
    p = m.run("--dry-run", "--yes", "--install-homebrew")
    assert p.returncode == 0, p.stdout
    assert snapshot(tmp_path, m.log) == before
    assert m.installs() == []
    assert not any(c.startswith("curl") for c in m.calls())
    assert "python@3.12" in p.stdout and "ffmpeg" in p.stdout
    assert str(m.link) in p.stdout and str(m.config) in p.stdout
    assert "-m venv" in p.stdout and "pip install" in p.stdout


def test_install_asks_before_system_packages_without_yes(tmp_path):
    m = Machine(tmp_path)
    m.brew()
    m.python("python3", "3.9")
    p = m.run(stdin="n\n")
    assert p.returncode == 1, p.stdout
    assert "[y/N]" in p.stdout
    assert m.installs() == []


def test_install_second_run_installs_nothing(tmp_path):
    m = Machine(tmp_path)
    m.brew()
    m.python("python3", "3.9")
    first = m.run("--yes", "--with-ocr")
    assert first.returncode == 0, first.stdout
    assert m.installs()
    m.log.unlink()
    second = m.run("--yes", "--with-ocr")
    assert second.returncode == 0, second.stdout
    assert m.installs() == [], m.calls()


def test_install_runs_final_checks_and_a_missing_key_is_not_fatal(tmp_path):
    m = ready_mac(tmp_path)
    p = m.run("--yes")
    assert p.returncode == 0, p.stdout
    calls = m.calls()
    assert "promo-video config check" in calls and "promo-video check --self-test" in calls
    assert "Summary" in p.stdout


def test_install_minimum_python_matches_pyproject(tmp_path):
    major, minor = pyproject_minimum()
    help_text = Machine(tmp_path / "help").run("--help").stdout
    assert f"Python {major}.{minor} or newer" in help_text, help_text

    below = Machine(tmp_path / "below")
    below.brew()
    below.tools("ffmpeg", "ffprobe")
    below.python("python3", f"{major}.{minor - 1}")
    assert below.run("--yes").returncode == 0
    assert "python3 -m venv " + str(below.repo / ".venv") not in below.calls()

    at = Machine(tmp_path / "at")
    at.brew()
    at.tools("ffmpeg", "ffprobe")
    at.python("python3", f"{major}.{minor}")
    assert at.run("--yes").returncode == 0
    assert "python3 -m venv " + str(at.repo / ".venv") in at.calls()
    assert at.package_installs("brew") == []


def test_install_reads_minimum_from_pyproject(tmp_path):
    m = Machine(tmp_path)
    m.brew()
    m.tools("ffmpeg", "ffprobe")
    m.python("python3.11", "3.11")
    pyproject = m.repo / "pyproject.toml"
    text = pyproject.read_text()
    assert re.search(r'^requires-python = ">=\d+\.\d+"$', text, re.M)
    pyproject.write_text(re.sub(r'^requires-python = ".*"$', 'requires-python = ">=3.12"', text, flags=re.M))
    p = m.run("--yes")
    assert p.returncode == 0, p.stdout
    assert any("python@3.12" in pkgs for pkgs in m.package_installs("brew")), m.calls()
    assert "python3.12 -m venv " + str(m.repo / ".venv") in m.calls()


def test_install_copied_config_has_no_key_for_the_real_config_check(tmp_path):
    from conftest import fake_key
    from promovideo import config
    m = ready_mac(tmp_path)
    p = m.run("--yes")
    assert p.returncode == 0, p.stdout
    assert "(mode 600, no key)" in p.stdout
    assert "config check:    reported problems" in p.stdout
    code, lines = config.check_report(config.load_config(env={}, home=m.home, repo_root=m.repo),
                                      which=lambda tool: "/stub/bin/" + tool)
    assert code == 1 and any(x.startswith("FAIL key: GEMINI_API_KEY") for x in lines), lines

    key = fake_key()
    local = m.repo / "config.local.toml"
    local.write_text(f'gemini_api_key = "{key}"\n')
    cfg = config.load_config(env={}, home=m.home, repo_root=m.repo)
    code, lines = config.check_report(cfg, which=lambda tool: "/stub/bin/" + tool)
    assert code == 0 and cfg.key_source == str(local), lines
    assert key not in "\n".join(lines)


@pytest.mark.parametrize("uid, update", [(1000, "sudo apt-get update"), (0, "apt-get update")])
def test_install_debian_with_empty_package_lists_asks_for_apt_update(tmp_path, uid, update):
    m = Machine(tmp_path, os_name="Linux", uid=uid)
    m.apt()
    _write(m.stubs / "apt-cache", LOGGER, "apt-cache")      # empty package lists: apt-cache prints nothing
    p = m.run("--yes")
    assert p.returncode == 2, p.stdout
    assert "package lists" in p.stdout and update in p.stdout, p.stdout
    if uid == 0:
        assert "sudo apt-get update" not in p.stdout
    assert m.installs() == []
    assert not any(c.startswith(("sudo", "apt-get")) for c in m.calls()), m.calls()
