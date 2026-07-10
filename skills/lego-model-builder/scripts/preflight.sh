#!/usr/bin/env bash
# Idempotent environment bootstrap for the lego-model-builder skill.
#
# Ensures three things and prints a one-line status for each:
#   pyldraw3: <ok|installed|MISSING>
#   library:  <ok|generated|MISSING>
#   renderer: <ldview|leocad|povray|NONE>
#
# It never exits non-zero for a missing renderer (the skill degrades to
# validate-only). It performs network installs and downloads that touch the
# user's real machine, so it is meant for interactive local use.

set -u

say()  { printf '%s\n' "$*"; }
note() { printf '  - %s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

py() {
  # Prefer an activated venv, then python3, then a verified Python 3 executable.
  if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
    "${VIRTUAL_ENV}/bin/python" "$@"
  elif have python3; then
    python3 "$@"
  elif have python && python -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' >/dev/null 2>&1; then
    python "$@"
  else
    note "Python 3.12+ is required"
    return 127
  fi
}

import_ok() { py -c "import ${1}" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# 1. pyldraw3
# ---------------------------------------------------------------------------
pyldraw_status="ok"
if ! import_ok ldraw; then
  note "pyldraw3 not importable; installing"
  installed=0
  # Official installer (preferred).
  if have curl; then
    if curl -LsSf https://uvx.sh/pyldraw3/install.sh | sh >&2 2>&1; then
      import_ok ldraw && installed=1
    fi
  fi
  # Fallbacks.
  if [ "$installed" -eq 0 ] && have uv; then
    note "installer path failed; trying uv"
    uv pip install pyldraw3 >&2 2>&1 || uv tool install pyldraw3 >&2 2>&1 || true
    import_ok ldraw && installed=1
  fi
  if [ "$installed" -eq 0 ] && have pip; then
    note "trying pip"
    pip install pyldraw3 >&2 2>&1 || pip install --user pyldraw3 >&2 2>&1 || true
    import_ok ldraw && installed=1
  fi
  if [ "$installed" -eq 1 ]; then
    pyldraw_status="installed"
  else
    pyldraw_status="MISSING"
  fi
fi
say "pyldraw3: ${pyldraw_status}"

# If pyldraw3 could not be installed, the library/renderer steps are moot.
if [ "$pyldraw_status" = "MISSING" ]; then
  say "library: MISSING"
  say "renderer: NONE"
  note "Could not install pyldraw3. Install it manually, e.g.:"
  note "  curl -LsSf https://uvx.sh/pyldraw3/install.sh | sh   (or: pip install pyldraw3)"
  exit 0
fi

# The CLI is 'ldraw'; make sure it is callable (installers may add it late).
LDRAW="ldraw"
have ldraw || LDRAW="py -m ldraw.cli"

# ---------------------------------------------------------------------------
# 2. Parts library (download) + generated ldraw.library.* (generate)
# ---------------------------------------------------------------------------
lib_status="ok"

# parts.lst present? (download step)
parts_lst_present() {
  py - <<'PY'
import sys
from pathlib import Path
try:
    from ldraw.config import Config
    p = Path(Config.load().ldraw_library_path) / "ldraw" / "parts.lst"
    sys.exit(0 if p.is_file() else 1)
except Exception:
    sys.exit(1)
PY
}

if ! parts_lst_present; then
  note "LDraw parts library not found; downloading the 'complete' release (~80 MB, one-time, slow)"
  # shellcheck disable=SC2086
  $LDRAW download --yes >&2 2>&1 || note "download failed"
  lib_status="generated"
fi

# generated ldraw.library importable? (generate step)
if ! import_ok ldraw.library.colours; then
  note "generating ldraw.library.* modules"
  # shellcheck disable=SC2086
  $LDRAW generate --yes >&2 2>&1 || note "generate failed"
  lib_status="generated"
fi

if parts_lst_present && import_ok ldraw.library.colours; then
  say "library: ${lib_status}"
else
  say "library: MISSING"
  note "Set up the library manually: 'ldraw download --yes' then 'ldraw generate --yes'."
fi

# ---------------------------------------------------------------------------
# 3. Renderer (ldview -> leocad -> povray), install one if absent
# ---------------------------------------------------------------------------
detect_renderer() {
  for r in ldview leocad povray; do
    if have "$r"; then printf '%s' "$r"; return 0; fi
  done
  return 1
}

renderer="$(detect_renderer || true)"

if [ -z "${renderer}" ]; then
  note "No LDraw renderer found; attempting to install one"
  os="$(uname -s)"
  case "$os" in
    Linux)
      if have apt-get; then
        SUDO=""
        [ "$(id -u)" -ne 0 ] && have sudo && SUDO="sudo"
        note "installing leocad + xvfb via apt"
        $SUDO apt-get update -y >&2 2>&1 || true
        $SUDO apt-get install -y leocad xvfb libgl1-mesa-dri >&2 2>&1 || true
      fi
      ;;
    Darwin)
      if have brew; then
        note "installing a renderer via brew"
        brew install --cask ldview >&2 2>&1 || brew install leocad >&2 2>&1 || true
      else
        note "Homebrew not found; install from https://brew.sh then 'brew install --cask ldview'"
      fi
      ;;
  esac
  renderer="$(detect_renderer || true)"
fi

if [ -n "${renderer}" ]; then
  say "renderer: ${renderer}"
else
  say "renderer: NONE"
  note "Continuing in validate-only mode (no images). To enable rendering, install"
  note "LDView (https://tcobbs.github.io/ldview/) or 'leocad' (+ xvfb on Linux)."
fi

exit 0
