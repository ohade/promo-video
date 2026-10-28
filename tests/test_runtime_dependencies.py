"""Launcher fallbacks and an existing installation must include the export-lock dependency."""
import shutil
import subprocess
from pathlib import Path

import pytest

from test_install import ready_mac

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("missing", ["all", "filelock"])
def test_launcher_uses_complete_uv_environment(tmp_path, missing):
    launcher = tmp_path / "repo" / "bin" / "promo-video"
    launcher.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "bin" / "promo-video", launcher)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "bash").symlink_to("/bin/bash")
    (tools / "dirname").symlink_to(shutil.which("dirname"))
    python = tools / "python3"
    python.write_text('#!/bin/bash\nif [ "$1" = -c ]; then\n'
                      '  case "$2" in *filelock*) exit 1 ;; esac\n'
                      f'  [ "{missing}" != all ]; exit\nfi\necho incomplete-python\n')
    python.chmod(0o755)
    uv = tools / "uv"
    uv.write_text('#!/bin/bash\nprintf "%s\\n" uv "$@"\n')
    uv.chmod(0o755)
    result = subprocess.run([str(launcher), "check", "--self-test"], env={"PATH": str(tools)},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    args = result.stdout.splitlines()
    assert args[0] == "uv", "launcher selected an interpreter missing filelock"
    dependencies = [args[i + 1] for i, token in enumerate(args[:-1]) if token == "--with"]
    assert "filelock>=4.2.4" in dependencies, "uv fallback omitted the export-lock dependency"
    assert args[-4:] == ["-m", "promovideo", "check", "--self-test"]


def test_reinstall_repairs_missing_lock_dependency(tmp_path):
    machine = ready_mac(tmp_path)
    first = machine.run("--yes")
    assert first.returncode == 0, first.stdout
    machine.log.unlink()
    interpreter = machine.repo / ".venv" / "bin" / "python"
    interpreter.write_text('''#!/bin/bash
echo "venv-python $*" >> "$STUB_LOG"
marker="$(dirname "$0")/../lock-installed"
case "$*" in
  *version_info*) echo 3.12; exit 0 ;;
  *"import numpy"*)
    case "$*" in *filelock*) [ -f "$marker" ]; exit ;; esac
    exit 0 ;;
esac
if [ "$1" = -m ] && [ "$2" = pip ] && [ "$3" = install ]; then touch "$marker"; fi
exit 0
''')
    second = machine.run("--yes")
    assert second.returncode == 0, second.stdout
    installs = [call for call in machine.calls() if call.startswith("venv-python -m pip install")]
    assert installs, "reinstall accepted an environment missing filelock"
    assert (machine.repo / ".venv" / "lock-installed").exists()
