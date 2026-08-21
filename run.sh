#!/usr/bin/env bash
# POSIX sibling of run.bat: same interpreter discovery, same env contract,
# same port (8190). See LINUX.md for the manual install this expects.
set -u

# Unbuffered, so a crashing sidecar's last words reach the log instead of
# dying in a stdio buffer (same reason run.bat sets it).
export PYTHONUNBUFFERED=1

PIXAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIXAL_PY_EXE=""

# An explicit interpreter always wins.
if [ -n "${PIXAL_PYTHON:-}" ]; then
  if [ ! -f "$PIXAL_PYTHON" ]; then
    echo "[pixal] PIXAL_PYTHON does not point to an existing interpreter:"
    echo "[pixal]   $PIXAL_PYTHON"
    exit 1
  fi
  PIXAL_PY_EXE="$PIXAL_PYTHON"
fi

# One line, the full path to a python - the same pin file run.bat honors, so
# a hand-built install can fix an interpreter choice on disk the same way.
if [ -z "$PIXAL_PY_EXE" ] && [ -f "$PIXAL_ROOT/.pixal_python" ]; then
  while IFS= read -r line; do
    if [ -z "$PIXAL_PY_EXE" ] && [ -n "$line" ] && [ -f "$line" ]; then
      PIXAL_PY_EXE="$line"
    fi
  done < "$PIXAL_ROOT/.pixal_python"
fi

# Normal standalone installation: the venv LINUX.md has you create in the repo.
if [ -z "$PIXAL_PY_EXE" ] && [ -f "$PIXAL_ROOT/.venv/bin/python" ]; then
  PIXAL_PY_EXE="$PIXAL_ROOT/.venv/bin/python"
fi

# A venv shared with the ComfyUI checkout (sibling layout), or one level
# higher when Pixal lives inside the ComfyUI folder.
if [ -z "$PIXAL_PY_EXE" ] && [ -f "$PIXAL_ROOT/../.venv/bin/python" ]; then
  PIXAL_PY_EXE="$PIXAL_ROOT/../.venv/bin/python"
fi
if [ -z "$PIXAL_PY_EXE" ] && [ -f "$PIXAL_ROOT/../../.venv/bin/python" ]; then
  PIXAL_PY_EXE="$PIXAL_ROOT/../../.venv/bin/python"
fi

# Last resort: whatever python3 the system offers.
if [ -z "$PIXAL_PY_EXE" ]; then
  PIXAL_PY_EXE="$(command -v python3 || true)"
fi

if [ -z "$PIXAL_PY_EXE" ]; then
  echo "[pixal] No Python interpreter was found."
  echo "[pixal] Create .venv (see LINUX.md), set PIXAL_PYTHON, or install python3."
  exit 1
fi

cd "$PIXAL_ROOT" || exit 1
exec "$PIXAL_PY_EXE" "$PIXAL_ROOT/server.py" "$@"
