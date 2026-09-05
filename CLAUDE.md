# Pixal, from a terminal

You are Claude Code, working inside a Pixal install. This file is what the
studio's own sessions learned about driving it from a terminal — the parts
that are not guessable, and the ones that cost a session to find out.

Pixal is a local image and video studio: a Python sidecar on **8190** that
talks to a ComfyUI on **8188**. The browser UI is one surface on top of the
sidecar's HTTP API. Everything the UI can do, you can do — and there are
things you can do that it cannot, because it renders one picture at a time
and you can queue forty.

For code changes, start with [ARCHITECTURE.md](ARCHITECTURE.md): current owners,
verification gates and remaining legacy boundaries. This terminal guide is not
a complete architecture map.

---

## The three processes

| | port | what it is |
|---|---|---|
| **Pixal sidecar** | 8190 | the API, the brain, the ledger. This is "Pixal". |
| **ComfyUI** | 8188 | the renderer. Pixal starts it and owns its window. |
| **The local chat brain** | 8191 | separate `pixal_brain_server.py` helper; the sidecar owns orchestration. A configured remote provider replaces this local inference path. |

**Start Pixal only through its own launcher.** `pixal.vbs`, spawned so it does
not inherit your console:

```powershell
(Get-WmiObject -List Win32_Process).Create('wscript.exe "<install>\pixal.vbs"')
```

Spawn it as a child of your shell and it dies when your session ends, which
looks exactly like a crash an hour later. A visible console gets closed by
someone tidying up, and **closing ComfyUI's window takes ComfyUI down with
it** — that window IS the VRAM indicator, deliberately.

**There is no `/api/health`.** Any HTTP response from 8190, 404 included,
means the sidecar is up:

```bash
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8190/api/status
```

**ComfyUI boots itself** when the first client asks — about 30–60 seconds,
longer cold. `GET /api/status` returns `{comfy, queue, history, boot}`; wait
for `comfy: true` before queueing anything.

**Restart only when idle.** `POST /api/sidecar/restart` answers 409 while a
render is running — retry rather than force. A `queue: 0` reading is a point
sample, not a promise: check the ledger's newest timestamp too, say what you
are about to do, and never chain a stop and a relaunch in one long command.

---

## Rendering without the UI

The render path is `POST /api/chat`. With `prompt_enhance: false` the text
goes to the sampler verbatim — no brain call, no rewriting, which is what you
want for a batch where the whole point is that only one variable moves.

```jsonc
POST http://127.0.0.1:8190/api/chat
{
  "text": "<the scene, exactly as it should render>",
  "opts": {
    "engine": "h3_ref_still",
    "character": "zara",
    "prompt_enhance": false,
    "model": "minimax_h3_hybrid_fl2va_ref2va_b30-49-int8",
    "aspect": "3:4 (Portrait Standard)",
    "mp": 3.1,
    "lora_plan": {
      "version": 1,
      "recipe": "h3_ref_still",
      "recipe_revision": 3,
      "mode": "replace_editable",
      "entries": [{ "slot": "digicam", "strength": 0.2, "enabled": true }]
    }
  }
}
```

Then match the finished job in `GET /api/history` by `scene === text && ts >=
start`, and read the file at
`<comfy_root>/ComfyUI/output/<subfolder>/<filename>`.

**Filter the ledger on `template ==`, never `startswith`, and check the
date.** `h3_ref` matches `h3_ref_still` (an image) and `h3_ref2v` (a video),
and `history.jsonl` holds months. Both mistakes hand you a real row from the
wrong lane or the wrong day, which reads exactly like a result. `info.writer`
says who wrote the caption: `pixal` / `official` is the brain, `verbatim` is
whatever you sent with `prompt_enhance: false`.

Five things that will bite you:

- **The lane key is `engine`, not `template`.** `opts.template` is read
  NOWHERE on this path - it is the brain's own render-tool argument, and in
  `opts` it is silently ignored. This page said `template` until 2026-09-03,
  and it looked correct because the `model` beside it did the routing:
  `effective_recipe` sends an H3 ref2va build to `h3_ref_still` on its own.
  Send a lane with no model to match and the job renders on **Realism**, which
  reads exactly like a lane that ignored your settings. `engine` must name a
  recipe in `GET /api/options`; a character, a saved style or an identity
  reference outrank it.
- **Aspect names are exact strings.** `3:4 (Portrait Standard)`,
  `2:3 (Portrait Photo)`, `4:3 (Standard)`. A near miss is a 400.
- **`recipe_revision` must match the server's.** Read it from
  `GET /api/options`; a stale one is refused on purpose, because the stage
  list it was written against no longer exists.
- **Read `info.loras` back.** The plan is what you asked for; `info` is what
  ran. They have disagreed.
- **A shell heredoc eats backslashes.** Not just in JSON - `\\` collapses
  on the way in, so a Windows path in a heredoc'd Python patch silently stops
  matching the file it is meant to edit, and JSON gets `Invalid \escape`.
  Write the script to a file, or build the string from `chr(92)`.

`GET /api/options` is the map: every recipe, its label, its LoRA stages and
revision, which models are installed, and what is missing. Read it first
rather than guessing ids.

### Talking to ComfyUI directly

For an experiment — a sweep over samplers, a checkpoint A/B — it is often
cleaner to build the graph with Pixal's own builder and post it to ComfyUI
yourself:

```python
import json, urllib.request
import server  # Live-studio experiment only: this still initializes legacy state.
server.apply_comfy_root(server.load_config()["comfy_root"])   # ← easy to forget

g, caption, info = server.build_h3_ref_still("<scene>", 424242, character="zara")
urllib.request.urlopen(urllib.request.Request(
    "http://127.0.0.1:8188/prompt",
    data=json.dumps({"prompt": g, "client_id": "probe"}).encode(),
    headers={"Content-Type": "application/json"}))
```

**`apply_comfy_root` is not optional.** Import `server.py` on its own and
`CDIR` points at the repo, the model catalog is empty, every capability probe
answers "not installed", and characters do not resolve. It looks like a broken
install; it is a missing line.

The job is `ok` when its prompt id appears in `GET /history` with
`status.status_str == "success"`. `execution_start` and `execution_success`
timestamps in `status.messages` are the real render time — and the first job
after a checkpoint change pays the model load, so never compare a cold arm to
a warm one.

---

## The rules that were paid for

**Free VRAM before a batch that changes checkpoint.**

```bash
curl -s -X POST http://127.0.0.1:8188/free \
  -H 'Content-Type: application/json' \
  -d '{"unload_models":true,"free_memory":true}'
```

Two 21 GB models do not fit on a 32 GB card. The signature is `'NoneType'
object has no attribute 'model_size'` at the sampler and then `executed: []`
for every job after — which reads exactly like a corrupt file and is not.
Write the call *and call it*: a defined-and-never-called `free()` has killed
two 39-job batches.

**Use `POST /api/settings` for live preference changes.** Do not rewrite
`config.json` with PowerShell: BOM-producing encodings make it unreadable by
the current loader. The loader may fall back to defaults, but the configuration
store now refuses to overwrite the unreadable original (Settings returns 409).
Repair or restore it deliberately; do not bypass that guard by deleting it.

**Never put Pixal code inside the ComfyUI install.** Pixal lives beside
ComfyUI and stages files into `ComfyUI/input`. That is the whole contract.

**Windows can OOM or page through WDDM.** At 99.9% VRAM even window compositing
can stall alongside CUDA. A cleared card does not make an oversized sampling
canvas fit: reduce the workload after an allocation failure. System RAM and
commit exhaustion are separate from GPU exhaustion. On a slow render read the
per-process GPU counter in Task Manager's Details tab, not `nvidia-smi` —
`nvidia-smi` hides DWM and the chat brain on WDDM.

**Put the settings in the filename.** Any render you will later form an
opinion about should carry its checkpoint, steps, sampler, scheduler and LoRAs
(or `RAW`) in its name, read back from the PNG's own embedded graph rather
than from what you meant to send. A day of verdicts was once invalidated by
one LoRA strength nobody could see.

**Fetch models with `huggingface_hub`, never `curl`.** Given a Hugging Face
link, download it from Python with ComfyUI's `python_embeded` interpreter —
that environment already carries `huggingface_hub` with **hf_xet** and
**hf_transfer**, which pull in parallel chunks:

```python
import os; os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
from huggingface_hub import hf_hub_download
p = hf_hub_download(repo_id="<owner>/<repo>", filename="<file>.safetensors",
                    local_dir=r"<comfy_root>\_hf_staging")
```

Measured on a 21 GB checkpoint: **76 MiB/s**, against 11 MB/s for the best a
single-stream `curl` ever managed on the same file. Worse than slow, that curl
then wedged at 0.7 KB/s after 582 MB — a dead socket that reads exactly like a
slow mirror, and a resume will not notice. The `hf` CLI in that interpreter is
broken (`Typer.__init__() got an unexpected keyword argument
'suggest_commands'`, a Typer version mismatch); the library under it is fine,
so call it from Python rather than the shell.

Stage to a folder on the **same volume** and move the finished file into
`models\...` — a `.incomplete` sitting where ComfyUI scans reads as a corrupt
model, and a same-volume move costs nothing. Check free space first: these
files are 20 GB and up.

---

## Writing a caption that renders

Hard-won, on the MiniMax H3 reference lane, and most of it generalises.
`docs/2026-08-30-h3-ref-realism.md` has the measurements — if that file is not
in your copy, it was pruned from the installer as internal, and the summary
here is the whole of it.

- **Short sentences, about fifteen words each — as many as the shot needs.**
  Adherence is finite PER SENTENCE, not per caption. A drink described as
  "turned away, mostly hidden behind her fingers" rendered label-out because
  that was clause six of a ninety-word sentence. Anything that must land gets
  its own short sentence. This read "about 45 words" until 2026-09-02, when
  the day's four keeper sets were measured back out of the PNGs: the frames
  that hold up run 240–330 words as a median of sixteen sentences, longest 47.
  A budget on the caption bought long sentences to fit it, which is the one
  thing that actually breaks.
- **The last clause is the strongest position.** On this model family, the
  final thing it reads decides whether the subject stays dressed. Nothing may
  follow the wardrobe clause — not a framing note, not a freeze instruction,
  nothing. Instructions lead; the scene closes.
- **Negations measure exactly zero.** "No specular" scored 0.485 against an
  unchanged 0.486. The model has no representation of absence. State what IS
  there.
- **Verbs are literal.** "Sprawled on the tailgate" put them face-down on it;
  "her eyeliner has run" drew two black tear tracks. Use the word you would
  actually use.
- **Spell any sign, or leave it out.** "A chalkboard price sign" rendered as
  `DCAEENT / Forward 00%` — confident, well-lettered nonsense, and the
  clearest tell there is. Two short words is the reliable ceiling; Pixal
  scrubs an unspelled sign for you rather than obeying it.
- **Write the moment, not the expression.** Instructing an eyeline half-lands.
  Give the subject something to *do* — asleep on a shoulder, mid-yawn, eating
  with their mouth full — and the face follows.
- **Take something out.** Every rejected direction in that session was *more*
  composed, *more* styled and *more* described than the ones that worked.

---

## Ground rules for working here

- **Use Pixal's own interpreter.** `run.bat` picks it in this order:
  `%PIXAL_PYTHON%`, then a path in `.pixal_python`, then `.venv\Scripts\
  python.exe`, then the ComfyUI portable's `python_embeded\python.exe`. Use
  the same one for any script that imports `server.py`, or you will debug a
  missing dependency that is not missing.
- **Run the verification gate** with that interpreter: `tools/verify.py`.
  It checks generated assets, scopes pytest to `tests/`, and discovers the
  JavaScript suites. Never bare `pytest`: installer staging has duplicate tests.
- **Build the frontend with `web\build.bat` or `npm run build`**. Both use
  `tools/build_web.mjs`, which stamps the complete service-worker shell.
  `npm run watch` is development-only; run the real build before committing.
- **Look at the render.** The metric ranks candidates; it does not settle
  them. Laplacian variance rewards grain as readily as detail, and more than
  one measured winner lost on sight.
- **Say what actually happened.** If a batch half-failed, say so with the
  error. Renders are slow and a confident wrong summary costs an hour.
