# Contributing to Pixal

Help is welcome. Pixal is source-available rather than open source — see
[LICENSE](LICENSE) — but that restricts *redistribution*, not collaboration.
If you can see this repository, you can work on it.

---

## The terms, up front

By submitting a contribution — a pull request, a patch, a commit, a code
snippet in an issue — you agree that:

1. **You grant Jesse Dubberke a perpetual, irrevocable, worldwide,
   royalty-free license** to use, reproduce, modify, sublicense, distribute
   and **relicense** your contribution, including under different license
   terms in future versions of Pixal.
2. **You keep your own copyright.** This is a license grant, not an
   assignment. You can still use your own work elsewhere.
3. **You have the right to grant this** — the work is yours, or you have
   permission, and it is not encumbered by an employer agreement or a
   license that conflicts with the above.
4. **You are not pasting in code you don't have rights to**, from any source
   with an incompatible license, or generated in a way you can't vouch for.

This exists for one practical reason: so Pixal can be **relicensed later —
including as open source — without having to track down every past
contributor.** Nothing forces you to sign anything; opening a PR is the
agreement.

If any of that doesn't work for you, open an issue and say so rather than
sending code.

---

## Licensing traps specific to this project

These are easy to trip over and expensive to unwind, so read them before
writing code.

### ComfyUI custom nodes must be GPL-3.0

**ComfyUI is GPL-3.0.** Pixal is not bound by it, because Pixal is an
independent program that talks to ComfyUI over its HTTP API as a separate
process — [ComfyUI's own licensing guidance](https://github.com/Comfy-Org/ComfyUI/discussions/14346)
is explicit that *"independent tools or remote API services that only connect
to ComfyUI are not bound by GPL."*

**But anything in `custom_nodes/` is a derivative work and must be GPL-3.0.**

So if you write a ComfyUI node for Pixal — the `vae_decode_2x` finish mode is
the obvious upcoming case — it does **not** go in this repository. It goes in
its own repo under GPL-3.0, and Pixal's catalog installs it like any other
pack. Keeping that boundary clean is what lets Pixal stay
source-available.

### Model licenses are not our licenses

Pixal never redistributes weights; it downloads them to the user's machine on
their instruction. Some carry real restrictions — **Anima is non-commercial**,
and is also a derivative of NVIDIA Cosmos-Predict2. If you add a lane or a
recipe, record the model's license in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) in the same style as the
existing entries. A lane whose license nobody wrote down is a liability.

### Vendored code needs a notice

Anything added under `web/vendor/`, `brand/vendor/` or similar needs an entry
in `THIRD_PARTY_NOTICES.md` with its copyright holder and license.

---

## Ground rules for the code

Pixal has strong conventions. Match them rather than importing your own.

- **Comments carry evidence.** Nearly every constant in `server.py` records
  the measured incident that produced it — the peak-not-sum VRAM pricing, the
  flush-then-OOM trio behind `reclaim_vram`'s polling, the reverted TAESD
  previews. If you change a tuned value, **say why, with the measurement.**
  If something looks strange, find the comment before "fixing" it; it usually
  exists.
- **Don't split `server.py` for tidiness.** It is ~12.8k lines and that is a
  known, deliberate state. The render path shares a lot of mutable state, and
  every split proposed so far moved the coupling instead of removing it.
- **The graphs are in `templates/*.json`**, not in `server.py`. An analysis
  that greps only `server.py` will reach false conclusions — this has already
  happened once and produced a whole wrong plan.
- **The installer is stdlib-only.** `install/pixal_install.py` may run on a
  freshly unzipped embeddable Python with nothing in it. No imports beyond
  the standard library, ever.
- **Never `git add -A`.** `config.json` holds a live API key and the access
  key. It is gitignored, and the installer builds hard-fail if it appears in
  a package — keep it that way. Add explicit paths.

## Before you open a PR

- Say what you measured, not just what you changed. Performance claims
  without before/after numbers are the main thing that gets rejected.
- Keep the diff to one concern.
- If you touched the installer, test a real install **and** an uninstall.
  `.venv\Scripts\python.exe install\build_installer.py` rebuilds it.
- If you touched a template, run the same seed before and after and compare.

## Getting oriented

Read [`README.md`](README.md) for what ships, [`HELP.md`](HELP.md) for how it
behaves in the user's hands, and [`PACKAGING.md`](PACKAGING.md) for how a
release is built. After that, the code comments are the documentation: the
tuned constants carry the measurement that produced them, and several carry
the rejected alternative and why it lost. Read the comment before changing
the value.

## Questions

Open an issue, or write to hello@getpixal.com.
