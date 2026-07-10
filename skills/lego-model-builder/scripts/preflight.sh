#!/usr/bin/env bash
# Idempotent environment bootstrap for the lego-model-builder skill.
#
# Ensures three things and prints a one-line status for each:
#   pyldraw3: <ok|installed|MISSING>
#   library:  <ok|generated|MISSING>
#   renderer: <ldview|leocad|NONE>
#
# It never exits non-zero for a missing renderer (the skill degrades to
# validate-only). It performs network installs and downloads that touch the
# user's real machine, so it is meant for interactive local use.

set -u

say()  { printf '%s\n' "$*"; }
note() { printf '  - %s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

# True when the given interpreter reports Python 3.12 or newer.
py_version_ok() { "$1" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' >/dev/null 2>&1; }

PYTHON_BIN=""
select_python() {
  # An activated venv is authoritative: use it only when it meets the version
  # requirement rather than silently escaping to a system interpreter.
  if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
    if py_version_ok "${VIRTUAL_ENV}/bin/python"; then
      PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
      return 0
    fi
    note "The activated virtual environment requires Python 3.12+"
    return 127
  fi

  # Outside a venv, use the first available interpreter that reports 3.12+.
  local candidate
  for candidate in python3 python; do
    if have "$candidate" && py_version_ok "$candidate"; then
      PYTHON_BIN="$(command -v "$candidate")"
      return 0
    fi
  done

  note "Python 3.12+ is required"
  return 127
}

select_python || true

py() {
  [ -n "$PYTHON_BIN" ] || return 127
  "$PYTHON_BIN" "$@"
}

import_ok() { py -c "import ${1}" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# 1. pyldraw3
# ---------------------------------------------------------------------------
pyldraw_status="ok"
if ! import_ok ldraw; then
  note "pyldraw3 not importable; installing"
  installed=0

  # Install into the exact interpreter selected above. A uv tool environment
  # would expose the CLI but would not make `import ldraw` work for model code.
  if [ -n "$PYTHON_BIN" ] && have uv; then
    note "installing pyldraw3 into $PYTHON_BIN with uv"
    uv pip install --python "$PYTHON_BIN" pyldraw3 >&2 2>&1 || true
    import_ok ldraw && installed=1
  fi

  if [ "$installed" -eq 0 ] && [ -n "$PYTHON_BIN" ] && py -m pip --version >/dev/null 2>&1; then
    note "installing pyldraw3 with $PYTHON_BIN -m pip"
    py -m pip install pyldraw3 >&2 2>&1 || true
    import_ok ldraw && installed=1
  fi

  if [ "$installed" -eq 0 ] && [ -z "${VIRTUAL_ENV:-}" ] && [ -n "$PYTHON_BIN" ]; then
    note "interpreter install failed; trying a user install"
    py -m pip install --user pyldraw3 >&2 2>&1 || true
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
  note "Could not install pyldraw3 into a Python 3.12+ interpreter."
  note "Activate a compatible virtual environment, then run: python -m pip install pyldraw3"
  exit 0
fi

# Execute the CLI through the selected interpreter so package installation,
# generated model imports, and CLI commands always share one environment.
run_ldraw() {
  py -m ldraw.cli "$@"
}

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
  run_ldraw download --yes >&2 2>&1 || note "download failed"
  lib_status="generated"
fi

# generated ldraw.library importable? (generate step)
if ! import_ok ldraw.library.colours; then
  note "generating ldraw.library.* modules"
  run_ldraw generate --yes >&2 2>&1 || note "generate failed"
  lib_status="generated"
fi

if parts_lst_present && import_ok ldraw.library.colours; then
  say "library: ${lib_status}"
else
  say "library: MISSING"
  note "Set up the library manually: 'ldraw download --yes' then 'ldraw generate --yes'."
fi

# ---------------------------------------------------------------------------
# 3. Renderer (ldview -> leocad), install one if absent
# ---------------------------------------------------------------------------
detect_renderer() {
  for r in ldview leocad; do
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
