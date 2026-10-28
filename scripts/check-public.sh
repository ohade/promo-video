#!/usr/bin/env bash
# Public-safety gate. Run before every push; exit 0 only when both checks are clean.
#  1. tests/test_public.py over every entry git would publish (git ls-files --cached --others --exclude-standard):
#     its path, a symlink's target text and the file's bytes (latin-1, UTF-16, and inflated gzip, PNG text, zip
#     members and PDF Flate streams included), against this machine's home path, user name and installed skill
#     names, .public-denylist.local lines (literal or re:), generic home and macOS private paths, token shapes,
#     private keys, secret-like assignments and e-mails.
#  2. gitleaks over exactly those regular files (copied to a temporary folder, so .venv and ignored local config are
#     out; symlinks are skipped, step 1 scans their target text).
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
py="${PROMO_VIDEO_PYTHON:-python3}"
if [ -z "${PROMO_VIDEO_PYTHON:-}" ] && [ -x .venv/bin/python ]; then py=.venv/bin/python; fi

"$py" -m pytest -q -p no:cacheprovider tests/test_public.py

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "FAIL public-safety: gitleaks not found (install it, e.g. brew install gitleaks)" >&2
  exit 1
fi
stage="$(mktemp -d)"
trap 'rm -r "$stage"' EXIT
git ls-files -z --cached --others --exclude-standard | while IFS= read -r -d '' f; do
  if [ -f "$f" ] && [ ! -L "$f" ]; then
    mkdir -p "$stage/$(dirname "$f")"
    cp -p "$f" "$stage/$f"
  fi
done
gitleaks dir "$stage" --no-banner --redact --exit-code 1
echo "PASS public-safety: published files clean; gitleaks found nothing"
