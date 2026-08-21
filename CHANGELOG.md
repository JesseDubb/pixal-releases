# Changelog

## 1.0.1b — 2026-08-21

Fixed:

- **The seed lock never worked.** Most seeds were rounded on their way into
  the app, so a locked re-roll replayed different dice than the chip
  promised, and the largest seeds quietly unlocked. Seeds are now drawn so
  they arrive exact, and a locked re-roll replays the exact seed stored with
  the render. Locks on renders from before this release stay as they were —
  the exact value is already gone from everything the browser touched.
- After the PC slept or the connection hiccuped, the app fell back to slow
  polling and stayed there until you reloaded it.
- A local brain that started without working vision reloaded its
  multi-gigabyte model on every chat message, so every reply waited on a
  full model load.
- With a LoRA selected, pieces of the app's own render settings leaked into
  the stored chat history.
- Chat could sit on "thinking" forever when the brain timed out or its
  connection failed.
- Typing "thanks!" with Cinematic on could queue a render of those words.
- Animating a photo or upscaling a clip saved a duplicate, silent copy of
  the video next to the real one.
- Clicking Stop just as a render finished could kill the next render
  instead.
- The crop rectangle was drawn black on a dark background — invisible,
  always.
- Re-roll and Review could fail without saying so; a refused click looked
  like a dead button.
- Dialogue in multishot videos was starved to a third of its budget — a
  5-second shot was told it had 1.67 seconds.
- LTX 2.5 clips waited in the wrong-shaped frame, then jumped when the
  first frame landed.
- A message or render card that had already appeared could vanish again
  right after the greeting.

New:

- FireRed-Image-Edit support, and `edit.speed` in the config (`"turbo"` by
  default) choosing between a model's own distilled fast schedule and its
  full schedule. Accelerators are now paired to the model line they were
  trained for — the wrong pairing used to ruin edits without erroring.
  Config-only for now; there is no settings UI for it.

The installer's SHA-256 hash is published in the release notes for this
version.
