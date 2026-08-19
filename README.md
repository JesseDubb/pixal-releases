# Pixal

**Every model you own. One chat.** — https://getpixal.com

Pixal sits beside the ComfyUI you already run and drives it from a single
conversation. Every checkpoint, LoRA, video model and upscaler on your disk,
with none of the per-model node-graph surgery. You describe a picture, you
correct it in plain sentences, it re-renders — same seed, so a small correction
changes the thing you named and nothing else. Local, no account, no upload,
$0.00 a picture.

**[Download the latest release →](https://github.com/JesseDubb/pixal-releases/releases/latest)**

## What it does

- **Chat-directed rendering.** No prompt engineering: the scene is corrected
  into existence, sentence by sentence. Small changes are same-seed prompt
  surgery, not a re-roll.
- **Image generation** across model families — photoreal, general, and a
  dedicated anime family — each driven with its own tuned direction.
- **Editing, two lanes.** Whole-frame edits via Qwen Image Edit; masked
  inpainting for surgical fixes. Exact logo/brand placement uses a reference
  image, not a lookalike from tokens.
- **Video with sound.** Pixal reads your finished frame and writes the motion
  brief itself — timed beats, a soundscape, dialogue — and renders it with
  audio generated in sync with the picture. Clip upscaling to 2× included.
- **Finishing.** 4× detail upscaling for stills, RTX Video SR for clips.
- **A local brain.** An on-device vision-language model chats, looks at your
  renders, and critiques — nothing leaves your machine.
- **VRAM discipline.** Pixal budgets your card and warns when a model is
  streaming weights instead of rendering, instead of letting Windows page
  itself into a livelock.

## The installer

One normal Windows installer — wizard, progress bar, Add/Remove Programs, real
uninstaller, no admin prompt. It fetches ComfyUI portable, the node packs and
the model weights it needs (~58 GB for everything; pick components to take
less), verifying every file byte-for-byte against pinned hashes and resuming
if the line drops. A failed download of one weight never kills the run.

It installs **beside** your existing ComfyUI, never inside it — remove Pixal
and nothing about your setup has changed.

## Requirements

- Windows 11, x64
- An NVIDIA GPU with a current driver (the more VRAM the better; video
  generation is the hungriest — Pixal tells you honestly what your card can do)
- ~58 GB of disk for the full component set

## Verify your download

Each release's notes carry the installer's sha256. In PowerShell:

    Get-FileHash .\Pixal-Setup-<version>-win-x64.exe -Algorithm SHA256

## License

Pixal is **source-available, not open source** — see [LICENSE](LICENSE).
You can read it, run it, and change it for yourself. You cannot pass it on.
Downloading an installer binds you to that license (it is also shown during
setup). Third-party components — ComfyUI, the models the installer downloads —
keep their own licenses; some model weights are non-commercial.

© 2026 Jesse Dubberke. All rights reserved.
