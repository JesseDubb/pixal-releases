# Pixal on Linux (manual, unsupported)

This is the pre-1.0 manual path. There is no Linux installer, no packages, and
no support promise: you assemble the pieces by hand and keep them working
yourself. If any step here is unfamiliar, stop - this document is a runbook
for people comfortable maintaining their own Python environments.

Windows remains the supported target. Nothing on the Windows path changes.

## What you end up with

`python server.py` reaches the same state `run.bat` reaches on Windows:
the sidecar listens on <http://127.0.0.1:8190>, ComfyUI is bootable from the
UI, the local chat brain is spawnable, and RTX VSR is honestly absent (it is
a Windows driver feature - the setting says so instead of pretending).

## Layout

One folder holding both checkouts, with the venv inside Pixal:

```
~/ai/
  Pixal/          this repo
  ComfyUI/        a ComfyUI checkout (https://github.com/comfyanonymous/ComfyUI)
```

Pixal finds ComfyUI because it sits beside the repo (or set `comfy_root` in
Settings after first boot). Models go where ComfyUI keeps them -
`ComfyUI/models/checkpoints`, `ComfyUI/models/loras`, and so on. Pixal scans
`ComfyUI/models` plus any `extra_model_paths.yaml` entries ComfyUI itself
honors, so a layout that works for ComfyUI works for Pixal.

## Install

```bash
cd ~/ai
git clone <pixal-repo-url> Pixal
cd Pixal
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cd ~/ai
git clone https://github.com/comfyanonymous/ComfyUI.git
Pixal/.venv/bin/pip install -r ComfyUI/requirements.txt
```

One venv serves both: Pixal needs `aiohttp`, `numpy`, `Pillow`, `PyYAML`;
ComfyUI needs `torch` and its own list. Install ComfyUI's GPU build of torch
per its own instructions if you want the card doing the work.

## Run

```bash
cd ~/ai/Pixal
./run.sh
```

Open <http://127.0.0.1:8190>. Serving the page is what starts ComfyUI (this is
deliberate - nothing drags 20 GB of models onto the card behind an idle
sidecar).

Interpreter choice, in the order `run.sh` probes: `$PIXAL_PYTHON`,
`.pixal_python` (one line, full path), `.venv` inside Pixal, a `.venv` beside
Pixal or beside ComfyUI, then the system `python3`.

### Optional: a launcher script for ComfyUI

On Windows Pixal boots ComfyUI through the tuned `run_nvidia_gpu*.bat` because
its flags are measured there. On Linux it looks for `run*.sh` **beside** the
ComfyUI folder first (invoked via `bash`, so the executable bit does not
matter; names containing `cpu` or `test` are skipped). With no such script it
falls back to ComfyUI's own `main.py`, run by the first python found in
`ComfyUI/.venv`, `ComfyUI/venv`, a `.venv` beside ComfyUI, Pixal's own
`.venv`, the interpreter Pixal itself runs on, or the system `python3`.

If you want flags of your own (attention backend, VRAM policy), write
`~/ai/run_nvidia_gpu.sh`:

```bash
#!/usr/bin/env bash
cd "$(dirname "$0")/ComfyUI"
exec ~/ai/Pixal/.venv/bin/python main.py "$@"
```

The `comfy_editor` setting keeps its meaning on the `main.py` path
(`--disable-auto-launch` when off).

## The local brain

Managed mode (default): when the "Local (uncensored)" preset is active and a
chat GGUF is picked in Settings, the sidecar spawns `pixal_brain_server.py` on
`127.0.0.1:8191` by itself. It needs an interpreter that can
`import llama_cpp.server`; it probes the same venv shapes listed above, and
`PIXAL_LLM_PYTHON` overrides everything.

Manual mode (for flags the UI can't express):

```bash
PIXAL_LLM_MODEL=/path/to/chat.gguf ./run_llm.sh
```

Same contract as `run_llm.bat`: `PIXAL_LLM_MODEL`, `PIXAL_LLM_PYTHON`,
`PIXAL_LLM_GPU_LAYERS` (default `-1`, all layers on the card; `0` = CPU),
`KMP_DUPLICATE_LIB_OK=TRUE`, port 8191. A server you start this way is used
as-is and never killed by Pixal.

`llama-cpp-python` is not in `requirements.txt`; install it into the venv
yourself (`Pixal/.venv/bin/pip install llama-cpp-python`, with the CUDA build
if you want GPU offload).

## Restarting

The in-app "restart sidecar" button is Windows-only (it rides `pixal.vbs`).
On Linux it answers with an error instead of doing anything. Restart from
your shell: Ctrl+C, then `./run.sh` again. ComfyUI's own restart button works.

## What works

- Render, edit, and video lanes end to end (the ComfyUI proxy is
  platform-neutral).
- ComfyUI boot/restart from the UI, boot meter, error surfacing.
- The local chat brain, managed or manual, including vision models.
- Model upscaling and the LTX 2.5 2x video upscale lane.
- LAN access, the access key, multiple chats, styles, characters.

## What does not

- **RTX VSR** - a Windows driver feature. The setting reports it unavailable.
- **The installer** (`install/`) - Windows-only; there is no packaged runtime,
  no Start-menu entry, no PWA install flow. This document is the installer.
- **The `.vbs` restart lane** - see above.
- **The comfy console window/TUI** - a Windows console feature. ComfyUI's
  output goes to the terminal session Pixal spawns it in; the error-line
  capture in `logs/` still works.

## Housekeeping notes

- `ffmpeg` is expected on `PATH` for the video lanes (`apt install ffmpeg`).
- Stopping Pixal (Ctrl+C) stops the ComfyUI it spawned and the managed brain,
  same as on Windows. A ComfyUI you started yourself is never touched.
- Port 8190 held by a dead sidecar: free it yourself (`kill <pid>`); the
  Windows self-heal that clears it automatically has no POSIX twin yet.
