"""Spawn wrapper around llama_cpp.server that can actually serve Qwen3-VL.

Why this file exists
--------------------
llama-cpp-python 0.3.39 (the JamePeng Windows CUDA fork Pixal installs) DEFINES
`Qwen3VLChatHandler` in llama_chat_format.py but never dispatches it: the
`--chat_format` if/elif chain in `llama_cpp/server/model.py` stops at
"qwen2.5-vl", and there is no registry entry either. `--chat_format qwen3-vl`
raises "Invalid chat handler". The class is reachable only from Python.

Two things were measured on 2026-08-18 with qwen3-vl-4b-heretic-Q8_0 + the
base-model qwen3vl mmproj:

  * Borrowing the 2.5 handler does NOT work. It encodes the image fine (432
    tokens, 88 ms) but advances position by rows (+24) instead of by image
    tokens (+432). The model then sees a corrupt position stream and emits EOS
    immediately - an EMPTY reply, not a crash. Silent quality failure.
  * With the real Qwen3VLChatHandler and image_min_tokens=1024 the same pair
    answers accurately in ~1.0-1.5 s.

`server/model.py` resolves the handler class by ATTRIBUTE LOOKUP at call time,
so pointing that attribute at a Qwen3-VL subclass makes the existing dispatch
construct the right thing. We do that here rather than patching site-packages,
which the installer would overwrite on every wheel refresh.

Defensive, because the wheel version floats at install time (it is resolved from
a third-party fork's GitHub releases):
  * if a released version ever gains a native "qwen3-vl" branch, we use it and
    skip the rebind entirely;
  * every attribute we touch is hasattr-guarded, and a failure to patch is
    reported loudly rather than silently serving a blind brain.

Usage is identical to `python -m llama_cpp.server ...`; the family is inferred
from --model and --chat_format is set accordingly.
"""
import runpy
import sys
from pathlib import PurePath

IMAGE_MIN_TOKENS = 1024   # default (-1) yields 432 tokens - too coarse to ground on


def _arg(argv, name):
    """Value of `--name X` (or `--name=X`) in argv, or None."""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def _family(model_path):
    """Which multimodal handler family this gguf belongs to, by filename."""
    n = PurePath(model_path or "").name.lower()
    if "gemma" in n:
        return "gemma"
    # qwen3-vl, qwen3_vl, qwen3vl - all seen in the wild
    if "qwen3" in n and "vl" in n:
        return "qwen3-vl"
    return None


def _server_has_native(fmt):
    """True when the installed llama_cpp.server dispatch already knows `fmt`."""
    try:
        import inspect

        import llama_cpp.server.model as m
        return f'"{fmt}"' in inspect.getsource(m) or f"'{fmt}'" in inspect.getsource(m)
    except Exception:
        return False


def _install_qwen3vl():
    """Point the 'qwen2.5-vl' dispatch at Qwen3-VL. Returns the chat_format to use."""
    import llama_cpp.llama_chat_format as fmt

    if not hasattr(fmt, "Qwen3VLChatHandler"):
        raise RuntimeError(
            "this llama-cpp-python has no Qwen3VLChatHandler - the local brain "
            "cannot see. Reinstall the brain runtime or pick an API key.")
    if not hasattr(fmt, "Qwen25VLChatHandler"):
        raise RuntimeError(
            "this llama-cpp-python has no Qwen25VLChatHandler to borrow the "
            "dispatch slot from - the server cannot route Qwen3-VL.")

    base = fmt.Qwen3VLChatHandler

    class PixalQwen3VL(base):
        """Qwen3-VL with a grounding-grade image budget.

        The CLI has no --image_min_tokens, and the default (-1) resolves to 432
        image tokens, which measurably under-resolves faces and small text.
        """

        def __init__(self, *a, **kw):
            kw.setdefault("image_min_tokens", IMAGE_MIN_TOKENS)
            super().__init__(*a, **kw)

    fmt.Qwen25VLChatHandler = PixalQwen3VL
    return "qwen2.5-vl"


def main(argv):
    model = _arg(argv, "--model")
    fam = _family(model)
    has_mmproj = bool(_arg(argv, "--clip_model_path"))

    if fam == "qwen3-vl" and has_mmproj:
        if _server_has_native("qwen3-vl"):
            chat_format = "qwen3-vl"
            print("[brain] native qwen3-vl dispatch present - using it", flush=True)
        else:
            chat_format = _install_qwen3vl()
            print(f"[brain] Qwen3-VL via rebound dispatch, "
                  f"image_min_tokens={IMAGE_MIN_TOKENS}", flush=True)
    elif fam == "gemma" and has_mmproj:
        chat_format = "gemma3"
        print("[brain] Gemma 3 vision", flush=True)
    else:
        chat_format = None      # text-only; let llama_cpp.server pick from the gguf

    if chat_format:
        argv = [a for a in argv if not a.startswith("--chat_format")]
        # drop a bare "--chat_format X" pair too
        out, skip = [], False
        for a in argv:
            if skip:
                skip = False
                continue
            if a == "--chat_format":
                skip = True
                continue
            out.append(a)
        argv = out + ["--chat_format", chat_format]

    sys.argv = ["llama_cpp.server"] + argv
    runpy.run_module("llama_cpp.server", run_name="__main__")


if __name__ == "__main__":
    main(sys.argv[1:])
