#!/bin/bash
# promo-video installer for a fresh macOS (Homebrew) or Debian/Ubuntu (apt) computer. Safe to run again: it installs
# only what is missing, and a second run changes nothing.
#   - Python at least the version in pyproject.toml `requires-python` (never the macOS system Python 3.9)
#   - ffmpeg and ffprobe; tesseract only with --with-ocr
#   - a virtual environment at <repo>/.venv with this package installed (`pip install -e`)
#   - the Claude Code skill link ~/.claude/skills/promo-video -> <repo>/skills/promo-video
#   - a key-less user config copied from config.example.toml (mode 600); an existing config is never changed
# Then it runs `bin/promo-video config check` (a missing key is reported, not fatal) and `check --self-test`.
# Bash 3.2 compatible (macOS /bin/bash): no arrays, no ${var,,}.
set -euo pipefail

HOMEBREW_URL="https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
HOMEBREW_COMMAND="/bin/bash -c \"\$(curl -fsSL $HOMEBREW_URL)\""
BREW_PYTHON="python@3.12"
# Where a freshly installed brew lives before the shell profile puts it on PATH (overridable for tests).
BREW_DIRS="${PROMO_VIDEO_BREW_DIRS:-/opt/homebrew/bin /usr/local/bin}"

say() { printf '%s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

# ---- repo and minimum Python --------------------------------------------------------------------------------------
src="${BASH_SOURCE[0]}"
while [ -L "$src" ]; do
  dir="$(cd -P "$(dirname "$src")" && pwd)"
  src="$(readlink "$src")"
  case "$src" in /*) ;; *) src="$dir/$src" ;; esac
done
REPO="$(cd -P "$(dirname "$src")/.." && pwd)"

MIN_PY="$(sed -n 's/^requires-python *= *">= *\([0-9][0-9]*\.[0-9][0-9]*\)".*/\1/p' "$REPO/pyproject.toml")"
[ -n "$MIN_PY" ] || die "cannot read requires-python (\">=X.Y\") from $REPO/pyproject.toml"
MIN_MAJOR="${MIN_PY%%.*}"
MIN_MINOR="${MIN_PY#*.}"

usage() {
  cat <<EOF
Usage: scripts/install.sh [options]

Sets up promo-video on this computer: macOS with Homebrew, or Debian/Ubuntu with apt. Safe to run again.
Installs what is missing: Python $MIN_PY or newer (pyproject.toml requires-python), ffmpeg and ffprobe, optionally
tesseract; creates .venv in the repo with the package; links the Claude Code skill; copies a key-less user config.

Options:
  --dry-run           print every action and change nothing
  --yes               do not ask before installing system packages
  --with-ocr          also install tesseract (used by the OCR privacy scan)
  --install-homebrew  on macOS, run the official Homebrew installer when brew is missing
  --force-link        replace an existing ~/.claude/skills/promo-video link that points elsewhere (never a real folder)
  --no-skill          do not link the Claude Code skill
  -h, --help          show this help

Exit codes: 0 done, 1 error or stopped, 2 a package manager step comes first (Homebrew missing on macOS, or empty
apt package lists: run apt-get update), 3 the skill path is taken by something else.
EOF
}

DRY_RUN=0 YES=0 WITH_OCR=0 INSTALL_HOMEBREW=0 FORCE_LINK=0 NO_SKILL=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes) YES=1 ;;
    --with-ocr) WITH_OCR=1 ;;
    --install-homebrew) INSTALL_HOMEBREW=1 ;;
    --force-link) FORCE_LINK=1 ;;
    --no-skill) NO_SKILL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'install.sh: unknown option: %s (see --help)\n' "$arg" >&2; exit 1 ;;
  esac
done

# ---- helpers ------------------------------------------------------------------------------------------------------
have() { command -v "$1" >/dev/null 2>&1; }

# Print a command, then run it unless --dry-run.
run() {
  printf '+ %s\n' "$*"
  if [ "$DRY_RUN" = 1 ]; then return 0; fi
  "$@"
}

# "X.Y" of a Python interpreter, or nothing when it does not run.
py_version() { PYTHONDONTWRITEBYTECODE=1 "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null; }

version_ok() {
  local major minor
  major="${1%%.*}"
  minor="${1#*.}"
  minor="${minor%%.*}"
  case "$major$minor" in ''|*[!0-9]*) return 1 ;; esac
  [ "$major" -gt "$MIN_MAJOR" ] || { [ "$major" -eq "$MIN_MAJOR" ] && [ "$minor" -ge "$MIN_MINOR" ]; }
}

# Sets PY, PY_NAME, PY_VERSION to the first suitable Python on PATH; OLD_PY lists the too-old ones it saw.
find_python() {
  local name path v
  PY="" PY_NAME="" PY_VERSION="" OLD_PY=""
  for name in python3.13 python3.12 python3.11 python3; do
    path="$(command -v "$name" 2>/dev/null)" || continue
    if [ "$OS" = Darwin ] && [ "$path" = /usr/bin/python3 ]; then continue; fi   # the macOS system Python (3.9)
    v="$(py_version "$path")" || v=""
    if [ -n "$v" ] && version_ok "$v"; then
      PY="$path" PY_NAME="$name" PY_VERSION="$v"
      return 0
    fi
    OLD_PY="${OLD_PY:+$OLD_PY, }$name ${v:-(does not run)}"
  done
  return 1
}

find_brew() {
  local d
  BREW="$(command -v brew 2>/dev/null)" && return 0
  for d in $BREW_DIRS; do
    if [ -x "$d/brew" ]; then BREW="$d/brew"; return 0; fi
  done
  BREW=""
  return 1
}

PKGS=""
add_pkg() { PKGS="${PKGS:+$PKGS }$1"; }

# The real directory a path leads to, or nothing (a dangling link, a missing path).
real_dir() { (cd -P "$1" 2>/dev/null && pwd) || true; }

# Probe the venv from outside the repo, so `promovideo` imports only when it is installed there.
venv_ready() { (cd / && PYTHONDONTWRITEBYTECODE=1 "$VPY" -c 'import numpy, PIL, promovideo' >/dev/null 2>&1); }

# ---- plan: look at the machine, change nothing --------------------------------------------------------------------
OS="$(uname -s)"
case "$OS" in
  Darwin) PM=brew ;;
  Linux)
    have apt-get || die "this installer supports macOS (Homebrew) and Debian/Ubuntu (apt). Install by hand: Python $MIN_PY+, ffmpeg, ffprobe, then: python3 -m venv .venv && .venv/bin/pip install -e ."
    PM=apt ;;
  *) die "unsupported system $OS: this installer supports macOS and Debian/Ubuntu" ;;
esac

say "promo-video installer"
say "  repo: $REPO"
say "  needs Python $MIN_PY or newer (pyproject.toml requires-python)"
[ "$DRY_RUN" = 1 ] && say "  dry run: printing every action, changing nothing"

PY_PLAN=""
if find_python; then
  PY_PLAN="use $PY ($PY_VERSION)"
  if [ "$PM" = apt ] && ! PYTHONDONTWRITEBYTECODE=1 "$PY" -c 'import ensurepip, venv' >/dev/null 2>&1; then
    add_pkg "${PY_NAME}-venv"
  fi
elif [ "$PM" = brew ]; then
  add_pkg "$BREW_PYTHON"
  PY_PLAN="install $BREW_PYTHON with Homebrew${OLD_PY:+ (too old: $OLD_PY)}"
else
  candidate="$(apt-cache policy python3 2>/dev/null | sed -n 's/^ *Candidate: *\([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1)" || candidate=""
  if [ -z "$candidate" ]; then
    # No candidate usually means empty package lists (a fresh system or a minimal container): the user refreshes them.
    if [ "$(id -u)" = 0 ]; then apt_update="apt-get update"; else apt_update="sudo apt-get update"; fi
    say ""
    say "apt offers no python3 package: the package lists may be empty (common on a fresh system or a container)."
    say "Refresh them with this command, then run this script again:"
    say "  $apt_update"
    say "If python3 is still not offered after that, install Python $MIN_PY+ another way (pyenv or uv), then rerun."
    exit 2
  fi
  if version_ok "$candidate"; then
    add_pkg python3
    add_pkg python3-venv
    PY_PLAN="install python3 $candidate and python3-venv with apt"
  else
    die "promo-video needs Python $MIN_PY or newer, but this system's python3 package is $candidate${OLD_PY:+ (found: $OLD_PY)}. Install Python $MIN_PY+ another way (a newer distribution release, pyenv or uv) so that python3.X is on PATH, then rerun."
  fi
fi

FFMPEG_PLAN="found"
if ! have ffmpeg || ! have ffprobe; then
  add_pkg ffmpeg
  FFMPEG_PLAN="install ffmpeg"
fi

OCR_PLAN="skipped (add --with-ocr to install it; the OCR privacy scan prints a SKIP line without it)"
if have tesseract; then
  OCR_PLAN="found"
elif [ "$WITH_OCR" = 1 ]; then
  if [ "$PM" = brew ]; then add_pkg tesseract; else add_pkg tesseract-ocr; fi
  OCR_PLAN="install tesseract"
fi

BREW="" HOMEBREW_PLAN=""
if [ "$PM" = brew ] && [ -n "$PKGS" ] && ! find_brew; then
  if [ "$INSTALL_HOMEBREW" = 1 ]; then
    HOMEBREW_PLAN="run the official Homebrew installer"
  else
    say ""
    say "Homebrew is needed to install: $PKGS"
    say "Install it with the official command, then run this script again:"
    say "  $HOMEBREW_COMMAND"
    say "Or rerun this script with --install-homebrew to run that installer for you."
    exit 2
  fi
fi

SUDO=""
if [ "$PM" = apt ] && [ -n "$PKGS" ] && [ "$(id -u)" != 0 ]; then
  have sudo || die "installing $PKGS needs root: rerun as root or install sudo"
  SUDO=sudo
fi

VENV="$REPO/.venv"
VPY="$VENV/bin/python"
if [ -e "$VENV" ] || [ -L "$VENV" ]; then
  v="$(py_version "$VPY")" || v=""
  if [ -z "$v" ] || ! version_ok "$v"; then
    die "$VENV exists but has no working Python $MIN_PY+ (found: ${v:-none}). Remove that folder and run this script again."
  fi
  VENV_PLAN="reuse $VENV (Python $v)"
  if venv_ready; then PIP_PLAN="already installed"; else PIP_PLAN="install the package (pip install -e)"; fi
else
  VENV_PLAN="create $VENV"
  PIP_PLAN="install the package (pip install -e)"
fi

SKILL_SRC="$REPO/skills/promo-video"
SKILL_LINK="$HOME/.claude/skills/promo-video"
if [ "$NO_SKILL" = 1 ]; then
  LINK_PLAN="skipped (--no-skill)"
elif [ -L "$SKILL_LINK" ]; then
  if [ "$(real_dir "$SKILL_LINK")" = "$(real_dir "$SKILL_SRC")" ]; then
    LINK_PLAN="already linked: $SKILL_LINK"
  elif [ "$FORCE_LINK" = 1 ]; then
    LINK_PLAN="replace the link $SKILL_LINK (--force-link)"
  else
    say "Skill link: $SKILL_LINK points to $(readlink "$SKILL_LINK"), not to this repo; left unchanged." >&2
    say "Rerun with --force-link to replace that link, or with --no-skill to skip the skill." >&2
    exit 3
  fi
elif [ -e "$SKILL_LINK" ]; then
  say "Skill link: $SKILL_LINK is a real file or folder, not a link; left unchanged." >&2
  say "Move it away and rerun, or rerun with --no-skill. --force-link replaces only a link, never a real folder." >&2
  exit 3
else
  LINK_PLAN="create $SKILL_LINK -> $SKILL_SRC"
fi

CONFIG="${PROMO_VIDEO_CONFIG:-$HOME/.config/promo-video/config.toml}"
if [ -e "$CONFIG" ] || [ -L "$CONFIG" ]; then
  CONFIG_PLAN="kept $CONFIG (not changed)"
else
  CONFIG_PLAN="create $CONFIG from config.example.toml (mode 600, no key)"
fi

say ""
say "Plan:"
say "  Python:          $PY_PLAN"
say "  ffmpeg/ffprobe:  $FFMPEG_PLAN"
say "  tesseract:       $OCR_PLAN"
[ -n "$HOMEBREW_PLAN" ] && say "  Homebrew:        $HOMEBREW_PLAN (it may ask for your password, for sudo)"
if [ -n "$PKGS" ]; then
  if [ "$PM" = brew ]; then
    say "  system packages: brew install $PKGS"
  else
    say "  system packages: ${SUDO:+$SUDO }apt-get install -y $PKGS${SUDO:+ (with sudo: it may ask for your password)}"
  fi
fi
say "  venv:            $VENV_PLAN; $PIP_PLAN"
say "  skill link:      $LINK_PLAN"
say "  config:          $CONFIG_PLAN"
say ""

if [ -n "$PKGS$HOMEBREW_PLAN" ] && [ "$YES" = 0 ] && [ "$DRY_RUN" = 0 ]; then
  printf 'Install the system packages above? [y/N] '
  answer=""
  read -r answer || true          # end of input (no terminal) counts as "no" below
  case "$answer" in
    y|Y|yes|Yes|YES) ;;
    *) die "stopped; nothing was installed (rerun with --yes to skip this question)" ;;
  esac
fi

# ---- act ----------------------------------------------------------------------------------------------------------
as_root() {
  if [ -n "$SUDO" ]; then run sudo "$@"; else run "$@"; fi
}

if [ -n "$HOMEBREW_PLAN" ]; then
  say "Running the official Homebrew installer:"
  printf '+ %s\n' "$HOMEBREW_COMMAND"
  if [ "$DRY_RUN" = 0 ]; then
    installer="$(curl -fsSL "$HOMEBREW_URL")" || die "could not download the Homebrew installer from $HOMEBREW_URL"
    if [ "$YES" = 1 ]; then
      NONINTERACTIVE=1 /bin/bash -c "$installer"
    else
      /bin/bash -c "$installer"
    fi
    find_brew || die "the Homebrew installer finished, but brew is not on PATH or in: $BREW_DIRS"
  fi
fi

if [ -n "$PKGS" ]; then
  if [ "$PM" = brew ]; then
    [ -n "$BREW" ] || BREW=brew                       # dry run before Homebrew exists
    case "$BREW" in */*) PATH="$(dirname "$BREW"):$PATH" ;; esac
    # shellcheck disable=SC2086  # PKGS is a space-separated package list
    run "$BREW" install $PKGS
  else
    [ -n "$SUDO" ] && say "Using sudo for apt-get (it may ask for your password)."
    as_root apt-get update
    # shellcheck disable=SC2086  # PKGS is a space-separated package list
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y $PKGS
  fi
  if [ "$DRY_RUN" = 0 ]; then
    hash -r
    find_python || die "installed $PKGS, but no Python $MIN_PY+ is on PATH${OLD_PY:+ (found: $OLD_PY)}; open a new shell and rerun"
    { have ffmpeg && have ffprobe; } || die "installed $PKGS, but ffmpeg/ffprobe are not on PATH; open a new shell and rerun"
  fi
fi

PY_SHOWN="${PY:-python$MIN_PY}"
if [ ! -e "$VENV" ] && [ ! -L "$VENV" ]; then
  run "$PY_SHOWN" -m venv "$VENV"
fi
if [ "$DRY_RUN" = 1 ] || ! venv_ready; then
  if [ "$PIP_PLAN" != "already installed" ]; then
    # A venv made by another tool (uv, for one) may have no pip; checking is read-only, so a dry run shows it too.
    if [ -x "$VPY" ] && ! PYTHONDONTWRITEBYTECODE=1 "$VPY" -m pip --version >/dev/null 2>&1; then
      run "$VPY" -m ensurepip --upgrade
    fi
    run "$VPY" -m pip install --quiet -e "$REPO"
    if [ "$DRY_RUN" = 0 ]; then
      venv_ready || die "pip finished, but $VPY cannot import numpy, PIL and promovideo"
    fi
  fi
fi

case "$LINK_PLAN" in
  create*)
    run mkdir -p "$(dirname "$SKILL_LINK")"
    run ln -s "$SKILL_SRC" "$SKILL_LINK" ;;
  replace*)
    run ln -sfn "$SKILL_SRC" "$SKILL_LINK" ;;
esac

case "$CONFIG_PLAN" in
  create*)
    printf '+ %s\n' "cp config.example.toml $CONFIG (mode 600)"
    if [ "$DRY_RUN" = 0 ]; then
      (umask 077 && mkdir -p "$(dirname "$CONFIG")" && cp "$REPO/config.example.toml" "$CONFIG")
      chmod 600 "$CONFIG"
    fi ;;
esac

# ---- checks and summary -------------------------------------------------------------------------------------------
CHECK_PLAN="not run (dry run)" SELF_TEST="not run (dry run)"
if [ "$DRY_RUN" = 1 ]; then
  printf '+ %s\n' "bin/promo-video config check" "bin/promo-video check --self-test"
else
  export PROMO_VIDEO_PYTHON="$VPY"
  say ""
  say "+ bin/promo-video config check"
  if "$REPO/bin/promo-video" config check; then
    CHECK_PLAN="ok"
  else
    CHECK_PLAN="reported problems above (a missing key is expected until you add one)"
  fi
  say "+ bin/promo-video check --self-test"
  if "$REPO/bin/promo-video" check --self-test; then SELF_TEST="PASS"; else SELF_TEST="FAIL"; fi
fi

say ""
say "Summary:"
say "  Python:          ${PY:-$PY_SHOWN (after install)}${PY_VERSION:+ ($PY_VERSION)}"
say "  ffmpeg/ffprobe:  $FFMPEG_PLAN"
say "  tesseract:       $OCR_PLAN"
say "  venv:            $VENV_PLAN; $PIP_PLAN"
say "  skill link:      $LINK_PLAN"
say "  config:          $CONFIG_PLAN"
say "  config check:    $CHECK_PLAN"
say "  self-test:       $SELF_TEST"
case "$CONFIG_PLAN" in
  create*)
    say ""
    say "Add your Google AI Studio key (narration and music) in one of two ways:"
    say "  export GEMINI_API_KEY=<your key>     (in your shell profile), or"
    say "  replace the placeholder gemini_api_key in $CONFIG (keep it mode 600)." ;;
esac
say ""
say "Run: $REPO/bin/promo-video --help"
[ "$SELF_TEST" != FAIL ] || die "check --self-test failed; see its output above"
exit 0
