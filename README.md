# Pixal

Pixal is a local conversational layer for [ComfyUI](https://github.com/comfyanonymous/ComfyUI). Describe the image you want in chat; Pixal selects a compatible recipe, turns the request into a model-ready prompt, patches a proven ComfyUI API graph, queues it, and streams the result back into the conversation.

The point is repeatability. Model files remain interchangeable within their supported family, while sampler, scheduler, resolution, VAE, text encoder, LoRA, and finishing choices live in named recipes instead of being rediscovered for every render.

Pixal does **not** include ComfyUI, checkpoints, LoRAs, VAEs, text encoders, upscalers, or language models.

Current build: **1.0.9b** (channel `stable`). Both values live in `PIXAL_VERSION` / `PIXAL_CHANNEL` in `server.py` and travel on `/api/settings` and `/api/comfy/compat`; the web bundle carries no version string of its own.

## What works

- Chat-directed still generation with model-aware recipe selection.
- A model-first composer with Realism, Anime, and Fantasy style choices; Pixal
  keeps the technical recipe, encoder, VAE, sampler, and modifier nodes hidden.
- A Prompt Enhance switch, typed identity/style/clothing/object references, and
  compact reference tabs that keep active attachments visible around the composer.
- A literal per-recipe LoRA execution chain with enable switches, strength
  controls, and grab-handle reordering for editable stages.
- Krea 2 realism, a two-pass Realism II profile, Z-Image Base fantasy and anime profiles, general Z-Image Base/Turbo generation, and Anima — a 2B anime model on its own graph.
- Character anchors and Krea 2 identity edits from a reference image.
- Instruction editing of any finished frame with Qwen-Image-Edit ("make her
  jacket red"), launched from a job card or the history grid.
- Two separate first-frame animation engines: MiniMax H3 with native audio and
  LTX 2.3, both launched from a finished still.
- Chat as the studio's hands: with a remote chat brain, "animate this", "review
  it", and "make it bigger" act on the conversation's renders through the same
  verified paths as the buttons. The managed local GGUF lane deliberately keeps
  its narrower prompt-writer contract.
- Optional local Qwen-VL review of generated images.
- VRAM profiles: the card's tier is detected automatically, a smaller tier can
  be pinned in Settings to preview what that card honestly gets, and engines
  with measured minimums say so in the Animate dialog (H3 below 24 GB runs,
  about five times slower).
- An OpenAI-compatible remote chat model or a managed local GGUF chat model.
- Local history, multiple chats, model discovery, progress events, previews, rerolls, and saved ComfyUI outputs.

Windows is the supported launch path today. The sidecar itself is Python, but the managed local-GGUF process controls and the included launch/build scripts are Windows-oriented.

## Install

### The short way

Double-click **`install.bat`**. It opens a page in your browser that looks the
machine over, finds ComfyUI or installs the portable build this Pixal is
developed against, downloads the model lanes you tick to the exact paths the
graphs look for, installs the node packs those lanes need, writes `config.json`
and leaves a Pixal shortcut on the Desktop.

**Where things land.** ComfyUI goes where you point it (or stays where it was
found), weights go to `<ComfyUI>\models\...`, and Pixal itself moves to the
folder named under *Where Pixal lives* — by default `<ComfyUI>\pixal_dm`, the
portable layout `run.bat` already understands. It is a copy, not a move, so the
folder you unzipped can be deleted afterwards; a Pixal that is already somewhere
sensible is left exactly where it is. Re-running over an existing install
refreshes the code and keeps `config.json`, `history.jsonl`, `characters\` and
`chats\` untouched.

It needs nothing on the machine first — if there is no Python it fetches the
11 MB official embeddable build into `install\runtime` rather than installing
anything system-wide. Every download resumes, so a dropped connection or a
closed lid costs only the bytes that were actually in flight. Closing the
browser tab does not stop it either; reopening the page lands back on the
progress.

If Windows blocks the file because it came out of a zip, right-click
`install.bat` → **Properties** → **Unblock**, or unzip with something that
does not mark the contents.

The smallest useful install is the **Anima** lane: 5.6 GB, no custom nodes at
all, and it renders in about nine seconds. Krea 2 is the one lane the installer
will not fetch — those weights live on Civitai behind a login, so the page lists
the exact filenames with a search link and leaves them to you.

**It reads your ComfyUI before it offers you anything.** Every model file under
`models\` (and any `base_path` in `extra_model_paths.yaml`) is checked against
what each recipe actually loads, by the same rules `server.py` uses: diffusion
models are matched the way `model_profile` classifies them — by name as well as
folder, so `anima-aesthetic-v1.1.safetensors` satisfies the Anima lane — while
text encoders and VAEs must sit at one of the exact paths `_catalog_has` looks
for. Each file then reads as one of three things:

- **on disk** — Pixal can already load it. Not downloaded, and the lane says
  *ready* rather than offering you 5 GB you own.
- **wrong folder** — the file is here, in a folder Pixal does not read. The
  optional tidy step moves those into place: only catalogued names, only within
  the same category and drive, never over an existing file, and every move is
  written to a JSON list under `install\_work` so it can be undone.
- **not here** — downloaded, with a link to the official HuggingFace repo next
  to it so you can see exactly where it comes from first.

Where a setting names a file, it is pointed at what you actually have: a
`qwen-image-edit-2511-Q4_K_M.gguf` already on the disk becomes `edit.model`
rather than being replaced by the Q6 build the catalogue lists.

What it installs from, all pinned in `install\catalog.json`: ComfyUI portable
from GitHub releases, weights from HuggingFace, node packs from GitHub zipballs,
and — for the local chat brain — a prebuilt `llama-cpp-python` CUDA wheel. If no
wheel matches the machine, the brain's model still lands on disk and chat falls
back to an API key rather than the install failing.

### By hand

You need:

- Python 3.10 or newer.
- A working ComfyUI installation, normally listening at `http://127.0.0.1:8188`.
- The custom nodes and model assets required by the recipes you intend to use.
- Node.js 20 or newer only if you want to rebuild the web UI.

From a standalone Pixal checkout:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run:

```bat
run.bat
```

ComfyUI does not have to be started first. When the app page is opened Pixal
looks for ComfyUI, and if it is not answering, starts it through its **own**
launcher `.bat` beside the ComfyUI folder — the flags in that file (sage
attention, fp16 accumulation, static VRAM) are load-bearing, and launching
`main.py` directly is a measurably slower machine. It runs hidden, and the app
shows a boot meter calibrated from how long the last cold start actually took on
this box. The boot is deliberately tied to opening the page rather than to
starting the sidecar, so a sidecar left running does not hold a model stack in
VRAM all session. Starting ComfyUI yourself beforehand still works and is
detected.

One case is deliberately left alone. If something already owns port 8188 but is
not answering, Pixal neither starts a second ComfyUI nor kills the first: from
out here a large model load and a wedge look identical, and reaping the wrong one
costs a live render. The boot screen says **ComfyUI is busy — loading a large
model** instead, and if that has not cleared after two minutes it names the wedge
as a possibility and offers *retry* and *continue without ComfyUI*, leaving the
restart to you in **Settings → Compute**.

`pixal.vbs` is the one-click version of all of this for a taskbar or desktop
shortcut: it starts the sidecar if it is not already answering, waits for it,
then opens the app window. Launching it twice is safe.

Open `http://127.0.0.1:8190`. On first run, Pixal asks for the ComfyUI root. It accepts a normal `ComfyUI` directory, a Windows-portable root containing `ComfyUI`, or the `models` directory itself.

`run.bat` chooses Python in this order:

1. The interpreter named by `PIXAL_PYTHON`.
2. The path on the single line of `.pixal_python`, if that file exists. The
   installer writes it when Pixal will run on an interpreter it did not create —
   normally a ComfyUI portable's `python_embeded` from a Pixal folder that is not
   inside that portable. An embeddable Python cannot make a `.venv`, and
   `pixal.vbs` starts `run.bat` with a bare environment, so the choice has to
   live on disk.
3. `.venv\Scripts\python.exe` beside Pixal.
4. The `python_embeded` interpreter when Pixal is installed at `ComfyUI\pixal_dm` inside ComfyUI Windows portable.

To provide an interpreter explicitly:

```bat
set "PIXAL_PYTHON=C:\path\to\python.exe"
run.bat
```

`config.json` is generated by the app. To preconfigure it, copy `config.example.json` to `config.json`, edit the copy, and never commit it. An empty `access_key` is replaced with a random local access key at startup.

### Opening it from another device

Pixal listens on loopback only. Setting `lan_access` binds every interface
instead, so a phone, tablet or headset on the same network can open the studio —
this is the one setting that puts Pixal on a network, and it is off by default.

The access gate stands regardless of that setting. **Locality is read off the
socket, never off anything the caller can type**: a request is let through
without a key only when its TCP peer is genuinely loopback and no proxy header
is forwarding on its behalf. Everything arriving over a network — LAN, tailnet,
or a tunnel — presents `?key=<access_key>` once, which sets a `pixal_key` cookie
good for 30 days. The key is minted at first boot if the config leaves it empty,
so the URL to send to a phone is
`http://<this machine>:8190/?key=<access_key>`.

There is deliberately **no free pass for tailnet devices**. An earlier version
trusted the `Tailscale-User-Login` header, and an earlier one still read
locality from the `Host` header — both are supplied by the caller, and only
`tailscale serve` strips the former, while `lan_access` is a bare `0.0.0.0` bind
with nothing in front of it. A single `-H "Host: localhost"` walked past that
gate on every route. A tailnet device now visits the keyed URL once, like any
other device. Key comparison is constant-time.

There is no authentication beyond that single shared key, and the app can write
files and drive a GPU on the host, so put Pixal on trusted networks only. A
tailnet is the safe way to reach it from outside the house; exposing it to the
public internet — Tailscale Funnel, a port forward, a tunnel — is not something
this design is hardened for.

## Chat model

Pixal's chat brain must expose an OpenAI-compatible chat-completions API.

- **Remote:** enter the provider base URL, API key, and model in Settings. The included example contains no key.
- **Local:** install `llama-cpp-python` with the backend appropriate for your GPU, select a chat-capable GGUF in Settings, and use `http://127.0.0.1:8191/v1`. Pixal starts that local server on demand and can release it after a turn to return VRAM to ComfyUI.

`llama-cpp-python` is deliberately not in `requirements.txt`: CUDA, Metal, Vulkan, and CPU wheels/build flags are platform-specific. Follow its installation instructions for your machine.

The managed local server may use a different Python from the Pixal sidecar. It checks `PIXAL_LLM_PYTHON` first, then the running interpreter when that interpreter can import `llama_cpp.server`, then the `python_embeded` interpreter beside the configured ComfyUI Windows-portable install. This lets a lightweight standalone `.venv` use the backend already installed with ComfyUI. For the manual `run_llm.bat` fallback, set both `PIXAL_LLM_PYTHON` and `PIXAL_LLM_MODEL` when they cannot be inferred from the checkout layout.

## Prompt and reference controls

The sparkle control in the prompt box is **Prompt Enhance** and defaults to on.
With it on, Pixal preserves the stated subject, action, setting, medium, and
constraints while the chat brain may fill in unspecified visual craft such as
composition and lighting. With it off, a render starts with the user's visible
prompt verbatim: Pixal does not rewrite, polish, expand, or embellish those words.
Technical composer choices still route the graph in either mode, and concrete
traits read from attached style, clothing, or object images may still be appended
as reference grounding. The switch is remembered in that browser.

The **+ ref** picker has four attachment types: identity, style, clothing, and
object. It scans every supported image below `ComfyUI\input`, including nested
subfolders, and presents a three-column thumbnail library sorted newest first.
There is intentionally no search field; the full library remains scrollable.
Identity references drive the Krea 2 Identity Edit graph. Style, clothing, and
object images are vision context for a compatible remote chat model; the managed
local GGUF lane does not currently have a vision projector.

Uploading from the picker captures the type that was active when the device
chooser opened, uploads the image, refreshes the library, and immediately attaches
the returned ComfyUI input as that type. Uploads are limited to 40 MB
(40,000,000 bytes). Pixal does not request overwrite mode: if the same filename
already exists, ComfyUI assigns
a unique name instead of silently replacing it. The upload's semantic type is
stored in the ignored `input_ref_types.json`.

Merely switching the picker type does not relabel existing thumbnails. To correct
a saved label, hover the card and click its tag button: that writes the currently
selected type as the image's durable label. Clicking the card itself only attaches
it for the next request.

Manual references stay visible as compact thumbnail tabs with their type icons in
a reserved column beside the composer; a selected character gets an icon-only
identity tab. On narrow screens the same tabs become a horizontal row inside the
composer. Clicking a tab removes that attachment from the next request without
deleting its source file from `ComfyUI\input`.

## Styles and compatible model families

The composer exposes **Model** and **Style**, not raw workflow names. Realism has
Standard and Refined quality; Refined is the two-pass Realism II workflow under
the hood. A selected model is authoritative: Z-Image Turbo offers Realism,
Z-Image Base offers Anime and Fantasy on their own graphs, and an Anima
checkpoint offers Anime alone — Anima is one graph with no style or quality
variants, so the picker pins the style to what the render will actually be.
Clearing the model expands the picker to every installed model with a supported
Pixal profile.

**Krea 2 offers all three styles, but only Realism as a graph.** Krea has no
anime or fantasy workflow, so choosing either on a Krea model keeps the photo
recipe and sends the register as craft *direction* instead — linework, cel
shading and palette for anime; silhouettes, materials, scale and one motivated
magical effect for fantasy — with the photo-caption rules (grain, skin defects,
lens language) explicitly dropped. The style picker tags these **directed**
rather than *ready* so the difference is visible at the point of choosing, and
greys them out entirely when Prompt Enhance is off, under a **needs prompt
enhance** tag — direction nothing writes into the scene is not a style. They
need none of Z-Image's anime/fantasy assets on disk.

### Saved styles

**Save current** in the styles section writes whatever the composer is set to as
a reusable style, and the pencil beside a saved style reopens it in a small
editor: name, base recipe, model, aspect and megapixels, the LoRA stack, and the
exact sampler, scheduler, steps and cfg. Saved styles then sit in the picker
beside the built-in ones and select the same way.

Each is a plain file — `recipes/<id>.json` — so a style is something you can
read, diff, back up, or hand to somebody else. The folder ships; its contents do
not.

A blank field **inherits the recipe's own default** rather than pinning today's
value, so a style does not silently freeze a setting that later improves. The
sampler and scheduler menus are read from your live ComfyUI install, so they
list what this machine can actually run. If a style's model or one of its LoRAs
is later deleted, the row greys out with the reason instead of failing when you
queue it.

Choosing a saved style and then changing the model, style, quality or LoRA stack
by hand releases the style, because the composer no longer matches what was
saved.

### Frame: Straight or Cinematic

Under the style picker, **Straight** (the default) and **Cinematic** decide how
the brain writes focus. Straight means *deep* focus: the room, the far wall and
the street behind the subject stay legible, and the subject is separated by
placement, light direction and camera distance. Cinematic lifts that for the
turn — an anamorphic-leaning lens, a shallow plane of focus, motivated
practicals and a graded palette.

Straight is the default because its opposite is not "flat", it is a photograph
you can read. Left to itself the brain writes "a shallow depth of field that
blurs the background into warm tones" into scene after scene and every render
converges on the same stock portrait with the room thrown away behind it.

Cinematic is craft direction too — words the brain writes into the scene, not a
graph — so it needs Prompt Enhance on. With the switch off the row greys out
under a **needs prompt enhance** tag instead of setting a pill the render will
not honour.

| User control | Family | Internal profile | Default model |
| --- | --- | --- | --- |
| Realism · Standard | Krea 2 | Fast single-pass portrait recipe | `Krea 2\finepornV31TURBOFP8_v3FIXFP8.safetensors` |
| Realism · Refined | Krea 2 | Realism II: detail pass, latent refinement, and 2x tiled SCUNet finish | `Krea 2\analogMadnessKrea2Turbo_v20.safetensors` |
| Fantasy | Z-Image Base | Painterly fantasy profile with a matched Base LoRA | `ZiB\z_image_bf16.safetensors` |
| Anime | Z-Image Base | Clear-anime profile, natural anime VAE, 12 steps | `ZiB\Z-Image_clear_anime_BF16.safetensors` |
| Anime | Anima | Anima's own 2B graph: `er_sde`/`simple`, a real negative, 30 steps | `Anima\anima-base-v1.0.safetensors` |
| Realism | Z-Image Base or Turbo | General Z-Image route with variant-aware sampling | `ZiT\z_image_turbo_bf16.safetensors` |
| Character selected | Krea 2 | Automatic reference-grounded Identity Edit | `Krea 2\krea2_turbo_mxfp8.safetensors` |

Character selection is intent, not extra setup. Choosing a referenced character
automatically activates Identity Edit, uses that character's saved face reference,
and clears incompatible model, LoRA, or stale identity-reference state. The style
picker stays live while Identity Edit is active: the render keeps the identity
chain (vector bypass + identity LoRA), Anime and Fantasy are written into it as
craft direction, and saved styles on a Krea 2 model contribute their stack and
model. Only styles whose base cannot carry the identity patch (Z-Image, Anima
graphs) are disabled, each with its reason. New character anchors require a
reference image. A standalone identity reference can still be used without an anchor.

Anchors can be deleted from the character picker; Pixal removes only its character
record and deliberately leaves the source image in ComfyUI's input folder.

Each active recipe exposes its literal LoRA chain in a dedicated execution rail on
desktop and inline on compact layouts. Editable recipe and user LoRAs can be added,
removed, re-strengthened, and switched on or off; an off row remains visible in the
saved chain but is excluded from the queued graph. Flexible rows reorder through the
grab handle—there are no separate up/down arrow buttons (the focused handle also
supports the keyboard arrow keys). The displayed top-to-bottom order is the
model-patch order Pixal queues, including the vector-bypass and Identity Edit stages.

**Re-roll rolls what you are looking at.** Rolling a finished card again rebuilds
it with the LoRA plan and model currently in the composer, not the ones the card
was born with — that is the refine loop: good render, adjust the stack, go again.
A live plan lands only if it fits that card's own graph; otherwise the card's
stored plan is used, restamped when it predates a stack-revision bump so an old
history card rolls instead of dying at 0.0s. A card's seed lock is per card,
survives a page load, and is handed to the frame a locked re-roll produces, so
the dice stay held for the whole loop. While any card holds the lock, a padlock
sits in the composer's top-right icon row: hovering shows the frozen seed value,
clicking it is the same unlock as the card's own padlock.

**Core stages are structural, not compulsory.** They hold the head of the chain and
cannot be reordered or removed, but each carries a live toggle that bypasses it: a
bypassed stage leaves the graph entirely rather than loading at zero strength (a
`LoraLoader` at 0 still costs the load and still perturbs the chain), keeps its row
so it can come back, and surrenders its chain number since the numbers are the load
order of what will actually run. While a core stage is on, adding the same LoRA by
name to the editable lane is still rejected as a double-load; once bypassed, it is
yours to re-add at your own strength. Overrides ride in the plan's `core` map, so a
plan that changes nothing serialises exactly as it did before the map existed, and
they survive a stack-revision bump as a standing preference.

**Krea 2's vector bypass** (`Krea 2\krea2filterbypass2vector.safetensors`) is
structural for the whole family, not one recipe's taste: every Krea graph that
samples runs it as the first locked stage, whichever checkpoint is selected. Realism
gained it in stack revision 2; Realism II and Identity Edit always carried it. New
Face is the one Krea recipe without it — that builder wires no LoRAs at all, so a
stage there would show in the UI and do nothing.

The model picker scans installed model roots and classifies model family and variant.
After a model is selected, reopening the picker shows only that family; choose
**Let Pixal choose** to expand back to all supported families. “Any installed model”
therefore means any model compatible with an existing Pixal pipeline—not an arbitrary
checkpoint forced through the wrong graph. Krea 2, Z-Image and Anima are supported still-image
families today. Flux, video, audio, and unknown architectures need their own execution
profile before Pixal will queue them.

Z-Image Base and Turbo are not treated as interchangeable presets. Turbo uses its short low-CFG schedule; Base uses the longer Base schedule. Fantasy and Anime accept Base models only, and Pixal rejects a Base/Turbo LoRA mismatch.

Pixal's Z-Image Turbo execution profile adapts the hand-tuned split-sigma
schedule from [Amazing Z-Image Workflow v4](https://github.com/martin-rizzo/AmazingZImageWorkflow).
The implementation remains native/API-only: Pixal constructs its own graph and
does not embed or require the upstream browser workflow. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for attribution and license details.

## ComfyUI custom nodes

Install only the packs needed by the features you use. Keep ComfyUI current as several Z-Image and LTX nodes now ship in core.

**ComfyUI Manager is not in this list, and Pixal will never install it.** ComfyUI
0.32 and newer ship Manager built in — a pip package (`comfyui_manager`) started
by `main.py`, serving its API under `/v2/`. `nodes.py` actively blocks a second
copy dropped into `custom_nodes` (`Blocked by policy` in the log), so cloning it
produces a folder that looks installed and never answers. Pixal only *detects*
it, by probing `/v2/manager/queue/status` — note that the older standalone
pack's `/api/manager/version` returns 404 on a modern ComfyUI whether Manager is
present or not, so that route cannot be used as a test. Missing packs are named
by Pixal and installed by you, in Manager.

| Feature | Node pack |
| --- | --- |
| Krea 2 still recipes | `RES4LYF` |
| GGUF Z-Image/LTX models and text encoders | `ComfyUI-GGUF` |
| Identity Edit | `comfyui-krea2edit` |
| Qwen Image Edit (GGUF builds) | `ComfyUI-GGUF` |
| Realism II tiled finish | `ComfyUI_UltimateSDUpscale` |
| Realism II color correction | `ComfyUI-post-processing-nodes` |
| LTX 2.3 animation | `ComfyUI-LTXVideo`, `ComfyUI-KJNodes`, `rgthree-comfy`, `ComfyUI-VideoHelperSuite`, and `comfyui-easy-use` |
| MiniMax H3 multishot | [`ComfyUI-H3-Multishot`](https://github.com/jlucasmcrell/ComfyUI-H3-Multishot) |
| PiD 4× identity upscale | `ComfyUI-PiD` (non-commercial license) |
| Video upscale | `Deno RTX VFX` pack (or the NVIDIA RTX Video pack as fallback) |
| Local image review | `ComfyUI-QwenVL` and `ComfyUI-Custom-Scripts` (pysssss) |

**Checking a setup is self-serve**: hover the status dot at the foot of the nav
rail. The compatibility card lists every node pack Pixal can queue against what
your ComfyUI actually has loaded, names any missing nodes per pack, and its
copy-report button produces a pasteable summary (`GET /api/comfy/compat` returns
the same data as JSON). Missing packs degrade gracefully — the affected feature
sits out and says why.

If ComfyUI reports an unknown node, load the corresponding file from `templates` in ComfyUI and use ComfyUI Manager's **Install Missing Custom Nodes** action. Node ownership changes as features move into ComfyUI core, so the loaded graph is the most reliable check for your installed version.

## Model assets

Paths below are relative to the matching ComfyUI model category (`diffusion_models`, `loras`, `vae`, `text_encoders`, or `upscale_models`). They are the defaults referenced by the built-in graphs; compatible substitutions can be selected where Pixal exposes a picker.

### Krea 2

- Realism: `Krea 2\finepornV31TURBOFP8_v3FIXFP8.safetensors`, `Qwen\qwen3-vl-4b-heretic_nvfp4.safetensors`, `Qwen-Image\qwenImageVAESharpKrea2_fp32.safetensors`, `Krea 2\krea2filterbypass2vector.safetensors`, and `Krea 2\RealisticSnapshotKrea2.safetensors`.
- Realism II: `Krea 2\analogMadnessKrea2Turbo_v20.safetensors`, the same Krea text encoder, `Wan\Wan2_1_VAE_fp32.safetensors`, `Krea 2\krea2filterbypass2vector.safetensors`, and `scunet_color_real_gan.pth`.
- Identity Edit: `Krea 2\krea2_turbo_mxfp8.safetensors`, `Qwen\qwen3vl_4b_bf16.safetensors`, `Wan\Wan2_1_VAE_fp32.safetensors`, `Krea 2\krea2filterbypass2vector.safetensors`, and `Krea 2\krea2_identity_edit_v1_2.safetensors`. It also needs a reference image in `ComfyUI\input`. `Krea 2\RawGirlV3.safetensors` is offered as an optional style stage and is only checked for when switched on.

### Z-Image

- Shared text encoder: a Z-Image-compatible non-VL Qwen3-4B encoder such as
  `qwen_3_4b.safetensors` or `Qwen3-4B.i1-Q5_K_S.gguf`, loaded as `lumina2`.
  A Qwen3-VL vision encoder is the wrong conditioning stack for Z-Image.
- General/fantasy VAE: `Flux\ae.safetensors`.
- Fantasy: `ZiB\z_image_bf16.safetensors` plus `ZImage\Base\DnDPainterlyCleanZBase.safetensors`.
- Anime: `ZiB\Z-Image_clear_anime_BF16.safetensors` plus `ZImage\zImageClearVae_natural.safetensors`.
- General Turbo default: `ZiT\z_image_turbo_bf16.safetensors`.

Both `.safetensors` and GGUF Z-Image diffusion models are supported when the GGUF node pack is installed.

### Anima

Anima is a 2B Cosmos-Predict2 anime model with its own family and one graph — no
style or quality variants, because the model *is* the style. ComfyUI supports the
architecture natively, so the graph is core nodes only and needs no node pack;
Pixal's is a port of ComfyUI's own shipped blueprint, `Text to Image (Anima Base
1.0)`.

- Checkpoints: `Anima\anima-base-v1.0.safetensors` (the default),
  `Anima\anima-aesthetic-v1.1.safetensors`, and `Anima\anima-turbo-v1.0.safetensors`.
- Text encoder: `Anima\qwen_3_06b_base.safetensors` — a Qwen3-0.6B **base**
  model, loaded as `stable_diffusion` rather than as a Qwen encoder type. This is
  the one setting no filename would tell you.
- VAE: `Qwen-Image\Qwen_Image_VAE.safetensors`, borrowed from the Qwen family;
  Pixal accepts the usual spellings of that filename.

Base and Aesthetic sample 30 steps at CFG 4 (~9s at 896×1152); Turbo brings its
own schedule, 10 steps at CFG 1 (~3s), read off the filename the way Z-Image
splits Base from Turbo. Do not add a `ModelSamplingAuraFlow` shift node: ComfyUI's
Anima model class already declares shift 3.0, so one changes nothing — verified
by a pixel-identical A/B on a fixed seed. Unlike Pixal's Z-Image recipes the
negative prompt is real rather than zeroed: CFG 4 is where Anima was tuned, and
zeroing it throws that guidance away.

Anima is uncensored and its prior leans that way — all three checkpoints returned
a fully-dressed brief in underwear or less. So the positive prompt leads with
`masterpiece, best quality, score_7, fully clothed`, the caption keeps its closing
wardrobe clause even with no character anchor, and the negative carries `nsfw,
nude, topless, underwear, lingerie, ass focus`. The closing clause is the part
that holds: Turbo samples at CFG 1, where the negative is not read at all. An
explicit ask lifts all three.

The weights are **non-commercial** (CircleStone Labs Non-Commercial License v1.2,
over a base under the NVIDIA Open Model License). The licence disclaims ownership
of what the model produces, so the images are yours; the checkpoints are the part
you may not use commercially.

### Qwen Image Edit

The **edit** action on a finished still opens a one-line instruction box and
routes to Qwen-Image-Edit. It is an editor, not a style: it never appears in the
composer's model picker and has no text-to-image path. The instruction is sent
verbatim — Prompt Enhance and the chat brain are deliberately bypassed, because
the model is trained on direct edit commands.

It needs `diffusion_models\Qwen\qwen-image-edit-2511-Q6_K.gguf` (or another
Qwen-Image-Edit build), the `Qwen\qwen_2.5_vl_7b_fp8_scaled.safetensors` text
encoder loaded as `qwen_image`, and `Qwen-Image\Qwen_Image_VAE.safetensors`.
Dated releases from 2509 on encode through `TextEncodeQwenImageEditPlus`; the
graph switches node class off the filename, so either generation just works.
GGUF builds need the `ComfyUI-GGUF` node pack; the graph itself is native.

Pixal's graph is a port of ComfyUI's shipped `image_qwen_image_edit` template
with its Lightning branch resolved to the full-quality side: `ModelSamplingAuraFlow`
shift 3.0, `CFGNorm` 1.0, and 20 steps at CFG 2.5 on euler/simple.

Edits run at the source frame's own resolution, capped at 2 MP. A 1152×1728
render comes back 1152×1728, so editing no longer costs you a trip down to
1 MP and back.

That takes one deliberate divergence from the shipped template: **the encoders
are given no VAE.** Reading `comfy_extras/nodes_qwen.py`,
`TextEncodeQwenImageEdit` always squashes the image to 1024×1024 px with `area`
resampling, and it builds `ref_latent = vae.encode(...)` from that squashed copy
only when a VAE is connected. Connecting one therefore forces every edit through
a ~1 MP downscale that no parameter can turn off — the real source of the
softness, zoom and pixel drift people hit when they chain edits. With the VAE
left off, that resize only feeds the Qwen2.5-VL semantic tokens, where a 1 MP
view is all the encoder ever wanted.

The reference latent instead comes from Pixal's own `VAEEncode` through a
`ReferenceLatent` node, which appends to the same `reference_latents`
conditioning key the encoder would have set. Because the sampler's
`latent_image` and the reference latent are now literally the same node output,
they cannot fall out of sync — which is what the old fixed-1 MP canvas existed
to prevent. Both the positive and the empty negative branch get the same
reference latent, so CFG measures the instruction rather than the presence of
the source image.

A `Qwen-Image-Edit` release dated 2509 or later ships as
`TextEncodeQwenImageEditPlus`, which numbers its image inputs; Pixal reads the
date out of the filename and swaps the node class, so a newer edit model drops
in without a second template. Note the dates run per model line —
`Qwen-Image-2512` is a *base* text-to-image release, not an edit one.

Only the original Qwen-Image-Edit is wired today. The 2509 and 2511 releases
take multiple reference images through `TextEncodeQwenImageEditPlus` and are not
drop-in substitutes for the single-image node used here.

### LTX 2.3 animation

The default animation model is `LTX2\ltx-2.3-22b-distilled-1.1-Q8_0.gguf`. The optional `LTX2\10Eros_v1.4-Q8_0.gguf` and `LTX2\sulphur_dev-Q8_0.gguf` profiles are non-distilled and require `LTX\ltx-2.3-22b-distilled-lora-384-1.1.safetensors` on this few-step graph.

The animation template also references its LTX 2.3 video/audio VAEs, text encoder/connector, and `ltx-2.3-spatial-upscaler-x2-1.1.safetensors`. Load `templates\ltx_i2v.json` in ComfyUI once to resolve those auxiliary files against your LTX node version and replace unavailable example assets before using Animate.

LTX remains its own animation engine. It does not share the MiniMax H3 model,
conditioning, VAE, sampler, or native-audio path.

### MiniMax H3 animation

MiniMax H3 is a dedicated first-frame image-to-video engine with 5, 10, and
15-second duration choices. Its workflow uses the H3 FL2VA diffusion model,
Qwen3-VL conditioning, and H3-specific video and audio VAEs. Audio is generated
natively with the clip rather than added by the LTX workflow or a separate
post-processing pass.

The optional H3 video LoRA `Minimax H3\HMNSFW_AIO_V2.safetensors` appears as
**HMNSFW AIO V2** in the Animate dialog when installed. It is off by default and
is accepted only by the MiniMax H3 FL2VA profile; its saved chain is isolated from
still-image and LTX LoRAs. When enabled, Pixal patches it into the H3 model in the
displayed order and injects its `hmmotion` activation token into the motion brief
exactly once. Animate plans are remembered per engine and model, so switching to
LTX cannot leak the H3 chain into that workflow.

H3 and LTX are intentionally separate engines in the Animate dialog. H3 REF2VA
is not part of the current path: it is deferred until Pixal has a reference-video
input flow, because REF2VA needs video reference input rather than only the
finished first frame used by FL2VA.

#### Multiple shots

The Animate dialog has a **shots** row for MiniMax H3 (up to 8), and the length
choice is per shot: 3 shots at 10s is a single ~30s video. How those shots are
produced depends on whether they fit one generation.

**Up to 15s — one generation with real cuts (the default).** H3 cuts natively
inside a single take: shot 1 carries no timestamp, later shots open with
`[Shot N] At MM:SS.mmm, the shot cuts to ...`. Pixal compiles the request into
that timeline, so 3 shots × 5s becomes one 15s / 362-frame generation. This
path uses only core ComfyUI nodes.

Measured on one still and one script, three ways:

| | time | transitions | identity at the end |
|---|---|---|---|
| chained, plain sampler | 814s | morph | wardrobe swapped |
| chained, anchored | 985s | morph | held |
| **single pass, internal cuts** | **677s** | **hard cuts** | **held, closest face** |

Chaining re-enters through the previous shot's last frame, so it can only morph
between shots — a real cut is impossible — and it pays a text encode per shot.
Below the ceiling the single pass wins on all three axes, so the chain is kept
for lengths one generation cannot reach.

#### Speed modes

A distillation is not a row in the LoRA chain: it rides first so creative LoRAs
stack on top of it, contributes no trigger word, and brings its own sampler,
scheduler and step count, because 8 steps on `res_multistep`/`simple` is a
broken render rather than a fast one. Pixal therefore ships each one as a whole
**speed mode** — a named recipe, not a speed dial — picked from a segmented
track in the Animate dialog's fine-tune fold:

| Mode | Steps | Sampler | Distillation |
| --- | --- | --- | --- |
| Quality *(default)* | 20 | `res_multistep` · `simple` | none |
| Turbo 8 | 8 | `euler` · `simple` | lightx2v 8-step v1.0 @ 0.8 |
| Turbo 4 | 4 | `er_sde` · `simple` | lightx2v 4-step v1.0 768p @ 0.75 (Kijai's) |
| Turbo v4 (old) | 8 | `euler` · `beta` | `minimax_h3_turbo_v4_step600_ema_pruned` |

The server reports the ladder with a per-mode `available` flag read off disk, so
a mode whose LoRA is missing greys out instead of rendering 4 steps raw. Any
mode other than Quality names itself on the fold's collapsed row, so a turbo
take never renders unannounced. The wire field is `speed`; the older boolean
`turbo` still works and now means Turbo 8.

Measured on one still, one script, same seed, both sides warmed the same way:

| | steps | sampler | s/step | total |
|---|---|---|---|---|
| default | 20 | res_multistep · simple | 33.1 | 701.8s |
| **turbo** | **8** | **euler · beta** | 40.9 | **362.8s** |

**1.93× faster** — 5.6 minutes off a 15s clip. The per-step cost goes *up*; the
win is entirely in doing twelve fewer of them. Identity, wardrobe and the
internal cuts survived intact at 8 steps. The one visible difference in that
pair: where the still's setting contradicted the brief, the 20-step render
adopted the brief's setting from frame one while turbo held the still's through
the first shot.

Unlike Spectrum and EasyCache, turbo does not skip or approximate transformer
evaluations, so it does not carry their motion-deviation failure — which is why
it is the acceleration Pixal ships.

#### It needs the card to itself

A 15s H3 clip stages about 40 GB of models — ComfyUI prints the numbers itself:
text encoder 14,956 MB, video VAE 4,965 MB, DiT 19,995 MB. That fits in 32 GB
only because ComfyUI evicts between stages, which leaves the DiT wanting roughly
25 GB to itself. Below that, ComfyUI does not fail and does not warn: it streams
the weights from system memory every forward, and the render takes about five
times as long. The same clip measured 701.8s with the card clear and was still
sampling at 55 minutes with ~22.9 GB free.

The signature, if you ever want to check by hand:

| | GPU util | memory util | power | s/step |
|---|---|---|---|---|
| healthy | 99% | ~50% | 575 W | 33 |
| streaming from host | 100% | **0%** | **160 W** | >165 |

Cancelling looks broken while this is happening, and isn't: ComfyUI only checks
the interrupt between sampling steps, so Stop reports success and waits out a
step that is minutes wide. Restarting ComfyUI is the way out. Pixal now says so
in the lane after two consecutive steps over 120s, rather than leaving you to
guess.

The usual culprit is the local chat model — llama.cpp holding a 4B GGUF was
measured at 7.2 GB once its KV cache had grown. **Settings → Compute → free chat
model** hands that back; the next message reloads it. This is deliberately a
separate button from **free VRAM**, which never touches the chat brain.

Pixal also says this up front: the Animate dialog flags H3 whenever the active
VRAM profile is under 24 GB — the flag is advisory (the render still runs), and
the profile itself can be pinned in **Settings → Render models** to preview a
smaller card. Only measured minimums are flagged; engines without a measured
number make no claim.

**Past 15s — chained takes.** This needs the
[ComfyUI-H3-Multishot](https://github.com/jlucasmcrell/ComfyUI-H3-Multishot)
node pack. Each shot starts from the previous shot's last frame. The motion
director writes one brief per shot separated by `---` on its own line, and the
audio direction plus any LoRA trigger is repeated into every shot because the
node encodes each prompt independently. Because the next shot is generated from
that last frame, the director is told to end every shot with the subject framed
in full and unoccluded, and to close it with a checkable `End state:` line.

`H3MultishotSampler` runs the same stack the single-shot builder wires by hand
(`BasicScheduler` simple → `res_multistep` → `BasicGuider` →
`SamplerCustomAdvanced`, 20 steps), so the look matches; what it adds is the
chain, the seam trim (each later shot's duplicated first frame and its 1/24s of
audio), and the audio crossfade. `seed_per_shot` is left on — the pack's author
measured that a single seed across shots drifts both the face and the voice.

Chaining on the last frame alone is a copy of a copy, and by the third shot the
face has visibly slid. So Pixal prefers `H3MultishotMemorySampler` when the
installed pack has it, with `anchor_frames=1` — one frame from the *original*
still is shown to every shot, which is the pack's own answer to that drift — and
`memory_frames=2` recent shot-end frames. Older packs fall back to the plain
sampler automatically. Note the memory sampler does not expose `voice_ref`, so
pinning the face and pinning the voice are currently an either/or.

Pixal detects the pack through ComfyUI's `/object_info`. Without it the shots row
simply does not appear, and single-shot H3 is unaffected: it uses only core
ComfyUI nodes and has no dependency on the pack.

For the optional review button, install a `ComfyUI-QwenVL` model and select its exact installed name in Pixal Settings. The example setting is `Qwen3-VL-4B-Instruct`.

## Rebuild the web UI

The checked-in `web\app.js` is the runnable bundle, so Node.js is not needed for normal use. To rebuild it from `web\src`:

```bat
npm install
web\build.bat
```

The build script resolves React, Phosphor Icons, and esbuild only from this checkout's `node_modules`; it has no machine-specific paths. You can also use `npm run build` or `npm run watch`.

## Privacy and local data

Pixal binds to `127.0.0.1:8190` by default and talks to ComfyUI at `127.0.0.1:8188` by default. Chats, characters, settings, history, logs, local-model state, and metadata caches stay in the Pixal directory and are excluded by `.gitignore`. Generated media and reviews are written below `ComfyUI\output\pixal_dm`; uploaded reference images go to ComfyUI's input directory.

If you configure a remote chat provider, your chat messages and any context sent for that request leave the machine under that provider's policies. ComfyUI and installed custom nodes may also have their own network features. Review those components before exposing Pixal or processing sensitive material.

The ignored private files include:

- `config.json` and local API credentials. The ignore rule is `config.json*`, so a
  stray backup or a hand-written `config.json.defaults` — each carrying the same
  live access key — cannot ride along in a `git add -A`.
- `history.jsonl`, legacy `lane.json`, and `chats\*.json`.
- `characters\*.json` and identity metadata.
- `input_ref_types.json`, which stores durable identity/style/clothing/object
  labels for ComfyUI input paths but no image pixels.
- `.local_llm.json`, `_lora_titles.json`, logs, caches, virtual environments, and `node_modules`.

The empty `chats` and `characters` directories are retained with `.gitkeep`; personal JSON files already in those directories are left untouched and remain untracked.

## Troubleshooting

- **A style says it is unavailable:** install the model, LoRA, VAE, text encoder, or upscaler named by its missing-assets hint.
- **A style is disabled for a selected model:** that model does not have a safe measured profile for the combination yet. Choose another model or use its available style.
- **ComfyUI says a node is missing:** update ComfyUI, load the relevant template, and use ComfyUI Manager to install missing nodes.
- **Pixal cannot find models:** verify the ComfyUI root in Settings. Extra model roots can be added there. When compute points to another ComfyUI server, discovery still reads the model library available to the Pixal host.
- **A reference upload fails:** files above 40 MB are rejected before ComfyUI; for
  smaller files, Pixal shows the rejection returned by ComfyUI instead of silently
  ignoring it. Confirm ComfyUI is online and the selected file is a readable image.
- **The local brain will not start:** verify the selected GGUF path and your `llama-cpp-python` backend. If Pixal reports that no compatible interpreter exists, set `PIXAL_LLM_PYTHON` to a Python that can run `-m llama_cpp.server`, then inspect `llama_server.log` for backend errors.
- **ComfyUI did not start, and its window is already gone:** open `logs\comfy-errors.log`. Pixal runs ComfyUI's own launcher inside a console that keeps that file — errors only, each with its traceback and the boot phase it happened in — so a failed start is still readable afterwards. `logs\comfy.log` has the whole transcript of the last boot, stamped with seconds since launch, and `logs\comfy.prev.log` has the one before it (which is what you want when it is crash-looping).

### ComfyUI's console

Starting Pixal starts ComfyUI, and that window is a dashboard rather than a wall of text: the boot as a phase list calibrated against the last good boot on this machine, a card meter, and the sampler's own progress once it is up. Keys: `E` opens the errors log, `L` the full transcript, `V` toggles the raw ComfyUI output, `Q` stops ComfyUI. Closing the window still stops ComfyUI, exactly as before — an open window means something is still on the card.

Settings → Compute → *ComfyUI's console window* → **plain console** puts the unwrapped launcher back. That is the escape hatch, not a preference: the plain console is ComfyUI's raw output with no file behind it, so the logs above only exist while meters are on.

Model licenses and usage terms belong to their respective authors and are not granted by this repository. You are responsible for obtaining the assets you use and complying with their licenses.

## License

Pixal is **source-available, not open source**: read it, run it, change it for
yourself — you cannot pass it on. The full terms are in [LICENSE](LICENSE), and
the installer shows them during setup. Images and video you make with it are
yours; the licensor claims no rights in your output.

Third-party components keep their own licenses and notices — see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Model weights carry their own
terms, some of them non-commercial. Pixal redistributes no weights; it downloads
them to your machine on your instruction, and complying with their licenses is
yours to do.

## Reading and verifying a build

Nothing here is compiled, bundled or obfuscated. The installer payload is a
`git archive` of this repository with the build, brand and marketing-site
directories pruned, so the Python that runs on your machine is the Python in
this tree — you can read every line of it after setup, in the install folder.

You do not have to run the installer to read what is inside it:

- **Read the source without touching the .exe.** Every release attaches
  `pixal-<version>-source.zip` with its own sha256 — the same tree the
  installer lays down, produced by `git archive` from the commit the installer
  was compiled from. Unzip it, read it, diff it against this repository.
- **Verify the installer.** Every release publishes its sha256 in the release
  notes. On Windows:
  `certutil -hashfile Pixal-Setup-<version>-win-x64.exe SHA256`
- **Unpacking the .exe itself is not practical today**, and that is worth
  saying plainly rather than pointing you at a tool that will fail. Pixal is
  built with Inno Setup 6.4; neither 7-Zip nor the current `innoextract`
  release (1.9, which supports up to Inno Setup 6.0.5) can open that archive.
  The source zip exists so that route is not needed.
