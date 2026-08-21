#!/usr/bin/env bash
# MANUAL FALLBACK - Pixal normally spawns this server itself when the
# "Local (uncensored)" preset is active (see ensure_local_llm in server.py).
# Start by hand only to run a model/flags combo the settings UI can't express;
# the sidecar detects an external :8191 server and uses it as-is.
# POSIX sibling of run_llm.bat: same env contract, same flags, same port.
# KMP guard: some CUDA llama.cpp builds otherwise clash with Torch's OMP runtime.
set -u
export KMP_DUPLICATE_LIB_OK=TRUE

PIXAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_LD="${LD_LIBRARY_PATH:-}"

PIXAL_LLM_PY=""
PIXAL_LLM_TORCHLIB=""

# Probe one interpreter: does it import llama_cpp.server with its torch libs
# reachable? On success records the interpreter AND its torch lib dir - the
# server itself needs those on LD_LIBRARY_PATH at load time, not just the
# probe (the POSIX form of run_llm.bat's PATH prepend).
try_python() {
  [ -n "$PIXAL_LLM_PY" ] && return 0
  [ -n "$1" ] && [ -f "$1" ] || return 0
  local home torchlib=""
  home="$(cd "$(dirname "$1")" && pwd)"
  case "$(basename "$home")" in
    bin|Scripts) home="$(dirname "$home")" ;;
  esac
  local d
  for d in "$home"/lib/python3*/site-packages/torch/lib \
           "$home"/Lib/site-packages/torch/lib; do
    if [ -d "$d" ]; then
      torchlib="$d"
      break
    fi
  done
  if env LD_LIBRARY_PATH="${torchlib}${BASE_LD:+:$BASE_LD}" \
      "$1" -c "import llama_cpp.server" >/dev/null 2>&1; then
    PIXAL_LLM_PY="$1"
    PIXAL_LLM_TORCHLIB="$torchlib"
  fi
  return 0
}

if [ -n "${PIXAL_LLM_PYTHON:-}" ]; then
  if [ ! -f "$PIXAL_LLM_PYTHON" ]; then
    echo "[pixal] PIXAL_LLM_PYTHON does not point to an existing interpreter:"
    echo "[pixal]   $PIXAL_LLM_PYTHON"
    exit 1
  fi
  try_python "$PIXAL_LLM_PYTHON"
  if [ -z "$PIXAL_LLM_PY" ]; then
    echo "[pixal] PIXAL_LLM_PYTHON cannot import llama_cpp.server:"
    echo "[pixal]   $PIXAL_LLM_PYTHON"
    exit 1
  fi
else
  [ -n "${PIXAL_PYTHON:-}" ] && try_python "$PIXAL_PYTHON"
  [ -z "$PIXAL_LLM_PY" ] && try_python "$PIXAL_ROOT/.venv/bin/python"
  [ -z "$PIXAL_LLM_PY" ] && try_python "$PIXAL_ROOT/../.venv/bin/python"
  [ -z "$PIXAL_LLM_PY" ] && try_python "$PIXAL_ROOT/../../.venv/bin/python"
  [ -z "$PIXAL_LLM_PY" ] && try_python "$(command -v python3 || true)"
fi

PIXAL_LLM_FILE="${PIXAL_LLM_MODEL:-}"
DEFAULT_MODEL="$PIXAL_ROOT/../models/LLM/GGUF/Josiefied-Qwen3-4B-abliterated-v2.Q8_0.gguf"
if [ -z "$PIXAL_LLM_FILE" ] && [ -f "$DEFAULT_MODEL" ]; then
  PIXAL_LLM_FILE="$DEFAULT_MODEL"
fi

if [ -z "$PIXAL_LLM_PY" ]; then
  echo "[pixal] No Python interpreter with llama_cpp.server was found."
  echo "[pixal] Set PIXAL_LLM_PYTHON or install llama-cpp-python in Pixal's venv (see LINUX.md)."
  exit 1
fi
if [ -z "$PIXAL_LLM_FILE" ]; then
  echo "[pixal] Set PIXAL_LLM_MODEL to the full path of a chat-capable GGUF."
  exit 1
fi

# GPU layers for the brain: PIXAL_LLM_GPU_LAYERS overrides (0 = CPU), -1 = all.
PIXAL_LLM_GPU_LAYERS="${PIXAL_LLM_GPU_LAYERS:--1}"

if [ -n "$PIXAL_LLM_TORCHLIB" ]; then
  export LD_LIBRARY_PATH="$PIXAL_LLM_TORCHLIB${BASE_LD:+:$BASE_LD}"
fi

exec "$PIXAL_LLM_PY" -m llama_cpp.server \
  --model "$PIXAL_LLM_FILE" \
  --n_gpu_layers "$PIXAL_LLM_GPU_LAYERS" --n_ctx 16384 --host 127.0.0.1 --port 8191
