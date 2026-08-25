# Pixal — the manual

Pixal is a chat window that drives a ComfyUI install on your own PC. You say
what you want to see; it picks the model, writes the prompt, builds the graph,
renders it, and puts the result in the conversation. Images and video happen
on your GPU, and the files land on your disk.

This manual walks the app the way you meet it: install, first render, the
buttons on a result, video, upscaling, every Settings control, the chat brain,
using it from another device, and what to do when something is wrong. Every
label and message quoted here is the text you will actually see on screen.

---

## 1. Quick start

### Install

1. Download the installer (`Pixal-Setup-…-win-x64.exe`) from getpixal.com and
   run it. You need Windows 10 (1809 or newer), 64-bit, and an NVIDIA GPU
   with driver 580 or newer. Setup checks the driver before it lets you
   continue; with no NVIDIA driver it stops with "No NVIDIA driver responded.
   Pixal renders on NVIDIA GPUs. If you have one, install its driver from
   nvidia.com and run Setup again."
2. The welcome page tells you what you are looking at: "Pixal is a studio for
   making images and video on your own machine. This installs Pixal itself,
   then downloads ComfyUI and the models you choose. Everything stays on this
   computer - nothing is uploaded."
3. Accept the license. It is a source-available license: you can run Pixal
   for any purpose and your renders are yours, but you cannot pass the
   software itself on. (The full text is in `LICENSE`; the FAQ at the bottom
   of this manual covers the commercial-use question.)
4. Choose where Pixal lives. The default is
   `C:\Users\<you>\AppData\Local\Programs\Pixal`. It never asks for admin.
5. Choose what to download. The setup type "Everything (recommended)" ticks
   all five components; "Choose what to download" lets you untick. The wizard
   lists each with its size: **Anima — anime** (5.2 GB), **Anima Turbo**
   (3.9 GB), **Z-Image Turbo — general** (19.3 GB), **Qwen Image Edit —
   editing** (24.7 GB), and **Local chat brain — Qwen3-VL 4B (uncensored)**
   (4.8 GB). Re-running **Pixal Setup** later describes them in its own
   words — "The whole anime lane. Stock ComfyUI nodes only, nothing to
   install but the weights.", "The everything-else model: photographic,
   painterly, fast, 8 steps.", "Type a change in plain words and the frame
   comes back changed." — and adds one model family the wizard cannot fetch:
   **Krea 2 — photoreal** lives on Civitai behind a login. "Civitai, and
   behind a login. The installer will not pretend it can fetch these." Pixal
   works without it; add it later if you want the photoreal model.
6. Tell it where ComfyUI is. "If you already have ComfyUI, point Pixal at
   it - nothing inside it is changed except the node packs Pixal needs. If
   you do not have it, Pixal will install its own copy at this location."
   A fresh ComfyUI is about 9 GB before models.
7. Decide whether you want a desktop shortcut ("Create a desktop shortcut")
   and let it run. The progress page is headed "Setting up" and says
   "Downloading ComfyUI and the models you chose. This resumes if it is
   interrupted - you can close Setup and run it again without losing work."
   That is literal: every interrupted download picks up where it stopped.
8. When it finishes you get "Pixal is ready" with "Open Pixal now" ticked.
   Finish opens the app.

Setup leaves three things on your machine: Pixal itself, a ComfyUI (yours or
a fresh portable one), and the model weights inside that ComfyUI's `models`
folders. Start Menu gets **Pixal**, **Pixal Setup** ("Add or repair ComfyUI
and models" — run it again to add components later) and **Uninstall Pixal**.

### First launch

1. Open Pixal from the shortcut. There is no console window; after a moment
   an app window opens at `http://127.0.0.1:8190` (a Chrome app window if
   Chrome is installed, otherwise your default browser).
2. Starting Pixal starts ComfyUI. While it boots you see a full-screen card
   headed **"Starting ComfyUI"** with a progress bar and a note naming the
   real stage it is in — "waking Python", "prestart hooks", "loading node
   packs", "final checks", then "starting the web server". The right end of
   the bar shows elapsed versus expected, like `12s / ~45s`. The expected
   number is calibrated: Pixal remembers how long the last boot actually took
   on this machine and uses that. Until it has measured one, it estimates 45
   seconds; a cold start is typically in the 30–60 second range.
3. If the estimate passes and ComfyUI is still loading, the note changes to
   "cold cache — still loading". Nothing is wrong; big models simply take a
   while the first time.
4. When ComfyUI answers, the boot screen lifts and you are in the chat.

If you installed Pixal by hand rather than through the installer, the very
first screen is a one-step setup instead: "Point me at your ComfyUI install."
Type or paste the folder (the placeholder shows the shape:
`D:\ComfyUI_windows_portable`) and press **allow scan**. The line under it
tells you exactly what happens next: "pixal reads model filenames from that
install's models folder (plus anything in its extra_model_paths.yaml) —
nothing else is touched, nothing leaves this machine." It scans ("scanning
models…"), reports "SUCCESS" or "scan complete", and drops you into the
chat.

### First render

1. You are looking at the chat. The empty conversation opens with a short
   greeting (it varies — something like "Give me one sentence. I'll give you
   a frame.") and a few quick-start chips such as "A place with a story" or
   "Surprise me". The chips are prompts; clicking one sends it.
2. Type your own sentence in the box at the bottom — the placeholder reads
   "Message pixal" — and press Enter. (Enter sends; Shift+Enter makes a new
   line.) Describe the picture, not the settings: *a woman closing a bookshop
   at night, rain on the window, warm lamp light* is a fine first prompt.
3. While the brain writes, the status row above the box says "pixal is
   thinking" and then names what it is doing ("writing the workflow", stage
   by stage: "loading the model", "encoding the prompt", "sampling"…).
4. A card appears in the conversation. While it renders you see a dot-matrix
   preview breathe into shape and a thin progress bar with a counter like
   "sampling 6/8".
5. Done. The image lands in the card with its recipe chips across the top —
   the style or recipe name, the model, "seed" and its number — and a row of
   buttons underneath: **animate**, **edit**, **review**, **upscale**,
   **re-roll**, **iterate**. The next sections walk each one.

Everything you make also lands on disk, under
`<ComfyUI>\output\pixal_dm\…`, and in the **Past generations** panel (the
history icon in the left rail).

---

## 2. Rendering from chat

### How asking works

Every message you send goes to the chat brain, which writes the actual scene
text the model renders. Two switches on the composer change how literally it
takes you:

- **Prompt enhance** (the sparkle beside the send button) defaults to on.
  With it on, the brain keeps your subject, action, setting and constraints
  and fills in the visual craft — composition, light, lens language. The
  tooltip reads "Prompt enhance on" / "Prompt enhance off". With it off, your
  words go to the model verbatim: Pixal does not rewrite, polish or expand
  them. The composer says so on the message itself: a "Prompt enhance off"
  note rides under your turn.
- The **style** pill (next section) steers the look; the **model** pill pins
  which checkpoint renders it. Leave the model on "Let Pixal choose" — its
  own words for what it does: "Reads what you asked for and matches it to the
  model that renders it best, at that model's measured high-fidelity
  settings."

### Small corrections keep the seed

Ask for a small change in plain words — *same shot, but make her jacket
red* — and Pixal treats it as a correction, not a new picture:

1. The brain is told what the newest render in the chat was, its scene, and
   its seed.
2. For a small change it reuses that scene almost word for word with only
   your change edited in, and passes the same seed, so the composition
   survives and only the named thing moves.
3. If your change restages the picture — new pose, new camera, new light —
   it deliberately drops the seed, because keeping it would fight the change.
4. A genuinely new idea gets a fresh scene and a fresh seed; nothing carries
   over.

You do not have to manage any of this; it follows from how you phrase the
ask. The visible tell is the seed number on the card: a correction keeps it,
a restage changes it.

### Re-roll vs iterate

They are different buttons on purpose:

- **re-roll** renders the same scene again with a new seed. Same words, new
  dice — use it when the description was right and the draw was wrong. It
  keeps the card's scene and takes everything else from the composer — LoRAs,
  model, canvas, preset, character — so "turn a character on and re-roll"
  puts their face on the shot you liked.
- **iterate** does not render anything. It drops a pre-filled line into your
  message box — `iterate on #42: ` — and waits for you to type the change.
  You are telling the brain what to move; it does the small-correction dance
  above.

### Freezing the seed

Every card shows "seed" and its number, with a small padlock beside it.

1. Click the padlock on a card you like. Its tooltip, before you click, says
   "freeze this seed — every render keeps it until you unlock".
2. While frozen, the composer carries a "seed · 1042" chip; hovering it tells
   you "click to unfreeze — every render reuses this seed while locked", and
   each message you send is annotated "seed 1042 locked".
3. Every render from now on — chat prompts, re-rolls, whichever card you
   throw them from — uses that seed until you unlock it. A frozen seed
   freezes re-rolls too; that is what "frozen" has to mean.
4. Click the padlock again (or the chip) to let go. Cards made while frozen
   show the lock in the history grid's hover line as 🔒.

### Styles and the style picker

Click the **style** pill in the composer. The popup is headed "style" and
lists the built-ins — **Realism**, **Anime**, **Fantasy** — each tagged with
its honest state: "ready", "directed", "assets missing", "not for this
model", or "needs prompt enhance". The tags matter:

- "directed" means there is no dedicated graph for that style on the selected
  model, so the look is written into the scene as direction instead. Anime
  and Fantasy on a Krea 2 model work this way.
- "needs prompt enhance" means the style only exists as direction, and with
  Prompt enhance off nothing would write it into the scene — so the row is
  greyed until you turn the sparkle back on.
- "assets missing" lists what to install when you hover.

Under the built-ins is **frame**: "Straight" (tagged "deep focus") or
"Cinematic" ("shallow focus · graded"). Cinematic's tooltip says what you are
asking for: "Anamorphic lens, a shallow plane of focus, motivated practical
light and a graded palette." It is scene direction too, so it also needs
Prompt enhance.

With Realism selected you also get **realism quality**: "Standard" ("single
pass") or "Refined" ("two-pass finish"). Refined runs the two-pass workflow
and is tagged "Krea 2 only" — hovering a greyed row tells you "Refined is
available with Krea 2 models".

**Saved styles.** When a render comes back exactly right, you can keep its
whole setup:

1. Open the style popup and press **save current** (tooltip: "Save the
   current model, LoRA stack and sampler as a style").
2. The "new style" dialog opens pre-filled from the composer: name it
   ("name your style…"), check the **runs on** rows (base recipe and model),
   and open the tuning fold if you want to override steps, cfg, sampler or
   scheduler. Leave a field blank and it "follows the recipe" — the dialog's
   own footnote: "Blank follows the recipe, so the style keeps improving when
   the recipe does — only what you change is saved."
3. If you had a canvas pinned in the composer, it is saved too ("canvas 3:2
   @ 2MP — saved with the style"); otherwise "no canvas pinned — the recipe's
   default is used".
4. **save style**. It now sits in the popup under "saved styles" and selects
   like a built-in. The pencil reopens the editor; the dialog warns you if a
   name collides ("saving replaces the existing “…” style").

A saved style is a plain JSON file in the Pixal folder under `recipes\` — you
can read it, back it up, or hand it to someone. If its model or a LoRA is
later deleted, its row greys out with the reason instead of failing at render
time. Changing the model, style, quality or LoRA stack after picking a saved
style releases it, because the composer no longer matches what was saved.

### Characters

Pixal ships with no people in it; you invent them. A **character anchor** is
a named person with one reference photo; once one exists, renders can keep
that person consistent across scenes.

Make one:

1. Click the **new character** button in the left rail (or the "Invent a
   character" chip in an empty chat, or "new anchor…" in the composer's
   character popup). The dialog is headed "new character anchor".
2. Fill in who they are. **name** ("Mia"), **age** ("24"), **race**
   ("Korean"), **sex** (female / male / other), **style** — "how they read
   at a glance", placeholder "short black bob, silver rings, oversized work
   jackets" — and **notes** — "who they are off-camera", placeholder "barista
   by day, queues ranked by night; hair changes daily; never poses, always
   mid-task". As you type, the "every caption will carry" card previews the
   exact sentence future prompts will inject.
3. The wardrobe lock closes every caption because, in the dialog's words,
   "the last clause is the strongest one — leave it blank for the generic
   lock. An explicit NSFW ask lifts it." Open "customize the wardrobe lock"
   to write your own.
4. Set the **identity reference** — marked "(required)", and the dialog is
   blunt about why: "The identity source — the anchor becomes selectable
   once a face is set." Pick any image from the `ComfyUI/input` grid, or
   **upload** one. Two tools fix the photo first: **edit** ("change
   accessories, clothing or background — Identity Edit carries over
   everything in this photo, so fix it here") and **crop** ("keep only a
   region — Identity Edit sees just what you crop to").
5. **save anchor**. Naming someone whose name is taken warns first: "saving
   replaces the existing “…” anchor".

Use one:

1. Type `@` in the message box and pick them from the "character" popup — or
   just type their @Name anywhere in the message — or pick them from the
   composer's **character** pill.
2. The composer shows an "identity · Mia" chip, and selecting an anchor
   switches the render to Identity Edit automatically (it runs on Krea 2;
   the model picker tells you "Identity Edit runs on Krea 2…" while one is
   selected).
3. Write the scene as usual. The reference carries the face; the caption
   carries the rest. Rows in the picker that cannot run say why —
   "reference required" or "identity edit unavailable".

Deleting an anchor (trash icon in the character popup) asks first: "Delete
the "Mia" character anchor? This removes only the anchor. Its source image
stays in ComfyUI/input."

### Attaching reference images

The round attach button beside the composer ("Attach a reference image")
opens your `ComfyUI/input` library as thumbnails. Each image gets a type —
**identity**, **style**, **clothing**, **object**, or **edit photo**:

- **identity** is a person's face, for Identity Edit (same engine the
  characters use).
- **style**, **clothing** and **object** are shown to a vision-capable chat
  brain, which describes their salient traits into the scene — garment cut
  and colour, palette, material.
- **edit photo** arms the whole frame for editing: the button turns into
  "Next message edits photo.png" and your next message is treated as an
  instruction edit of that picture.

"upload from device" adds a file (images up to 40 MB; bigger files are
refused with "image is larger than the 40 MB upload limit"). Attachments show
as chips beside the composer — "style · photo.png" — and clicking a chip
detaches it. Nothing is deleted from disk either way.

### The size pill

The **size** pill opens "canvas": **Aspect ratio** chips (the ratio with its
name in the tooltip), **Megapixels** chips ("auto" lets the recipe choose),
and a "renders at" readout showing the exact pixel dimensions your pick
implies, or "the recipe’s own canvas" when you leave it automatic.

---

## 3. The buttons on a render

A finished card carries up to six buttons. Most of them ride every tile in
**Past generations** too, joined there by a seed-freeze toggle, **open** and
a two-step **delete** ("delete" arms to "sure?"; the tooltip warns "click
again - gone for good"). Clicking the picture itself opens the lightbox: full size, its recipe readout (model,
dimensions, seed, sampler, elapsed), a save button, and arrow keys to move
through the set.

**animate** — opens the Animate dialog with this frame as the first frame of
a video. Section 4 walks it. (Stills only; a clip is already motion.)

**edit** — opens "Edit this image": type a change in plain words and the
frame comes back changed. Section 3.1 below walks it.

**review** — asks the image reviewer to look at the render and critique it.
A "critic" chip appears in the chat ("reading the shot…", then "review
posted below · 12s"), followed by the review itself: what works, what does
not, and a concrete fix. When the review names a fix, an **apply the fix**
pill appears under it; clicking pre-fills your message box with
`iterate on #42: apply the review fix - …` so you send the correction in one
tap. Which brain does the looking depends on your setup: when the chat brain
has vision it reviews directly, and the ComfyUI reviewer model from Settings
is the fallback for brains without eyes. First-ever use takes about 30
seconds while the reviewer warms up.

**upscale** — enlarges the frame or the clip with whatever Settings has
configured (Section 5). No dialog; it just runs and lands as a new card.

**re-roll** — same scene, new seed, rendered immediately. See Section 2.

**iterate** — pre-fills `iterate on #42: ` in the message box and waits for
your correction. See Section 2.

### 3.1 The edit dialog

"Edit this image" is an instruction editor. The words you type go to the
editor model exactly as typed — the placeholder says so: "What should change?
Say it plainly - the words go to the editor exactly as typed. “make her
jacket red”". Enter submits; Shift+Enter makes a new line.

**Whole-frame edit (no mask):**

1. Click **edit** on a card.
2. Type the change. The "for example" chips are clickable starters: "make
   her jacket red", "remove the text", "change the background to a snowy
   street", "make it night time".
3. The footer states what will happen: "keeps the frame, changes what you
   name".
4. Press **edit**. The dialog closes and the result arrives in the chat as a
   new render.

**Masked edit (repaint one area):**

1. Click **edit**, then choose **paint** ("paint the area to redraw") and
   scrub over the thing you want changed. The painted area shows as a red
   tint; **brush** sets the stroke size, **erase** unpaints, **reset**
   ("clear mask and crop") starts over.
2. The placeholder changes to match: "What should appear where you painted?
   “clean hoodie sleeve”" — and the footer to "only the painted area redraws
   · Klein inpaint".
3. Describe what goes *in the painted area*, press **edit**. Everything
   outside the mask is kept.

**Crop first:** the **crop** tool ("drag a crop rectangle") cuts the working
frame to a region before editing; with no mask the footer reads "edits just
the cropped region". Cropping is how you give the editor more pixels to work
with on one detail.

**Reference image ("image 2"):** press **add logo / reference** ("attach a
logo or reference the words can point at") and pick an image. Your words can
now point at it as "image 2" — the example chips change to show the idiom:
"put the logo from image 2 on her shirt", "paint image 2 on the wall as a
mural", "print the logo from image 2 on the billboard". One rule the footer
enforces ahead of time: paint a mask and the reference is not sent —
"painted mask wins - the attached image is not sent · Klein inpaint".

If the edit models are not installed, the dialog says so up front — "Qwen
Image Edit is unavailable." or "Klein inpaint is unavailable." — with the
list of what is missing. The Qwen editor ships with the editing component of
**Pixal Setup** (Start Menu). Klein's weights are a gated download on
Hugging Face — fetching them there means accepting their license — so those
you add yourself.

---

## 4. Video

Click **animate** on any finished still and the "Direct the clip" dialog
opens. The still you clicked is the first frame; everything in this dialog
is per-clip — none of it changes your defaults.

### The note

The big field is the note. Its placeholder teaches the grammar: "What
happens? Action, camera, pacing — your words become the brief." followed by
an example: “she pushes off the hood, turns and laughs — handheld follows
her”. Write what moves and how the camera behaves. Enter submits;
Shift+Enter makes a new line.

Three ways to go:

- **action** (the accent button) sends your note. The chat brain turns it
  into a shot-by-shot plan for the engine and you watch the status line work
  through it ("directing…", "planning the shot list", "directing shot 2/4",
  "stitching the trailer").
- **surprise me** sends no note at all — its tooltip: "no note - the director
  animates what's already in the frame".
- **draft the brief** asks the director for the brief without rendering — the
  note is replaced by what it wrote, so you can read and edit it before any
  GPU time is spent. A drafted brief then ships as written, exactly like a
  script, until you change the engine, model, length, shots or end frame —
  the brief was written for that configuration.

A still rendered through the selfie chain animates as a selfie — the
director is told the camera is the phone in the subject's own outstretched
hand, and there is no setting for it: you already chose Selfie Cam when you
rendered the still.

### Script mode

Separate shots with a line containing only `---` and the note stops being a
note: it becomes a script, sent to the sampler verbatim, declaring its own
shot count. The dialog tells you when you have crossed over: "script mode —
3 shots sent verbatim, the director stays out of it". Each shot renders and
chains from the last frame of the one before.

### Engines

The "engine" track shows the engines as the server offers them — today that
is two:

- **LTX 2.5** — tagged "pixel diffusion · audio". Hovering gives its full
  line: "Lightricks' keyframes-first generation: sharper faces and text,
  synchronized audio, two-pass upscale built in." Length choices: 3s ("a
  beat"), 5s ("a moment"), 8s ("a take"), 12s ("a long take"), 15s ("a
  scene").
- **MiniMax H3** — tagged "long takes · audio". Hovering: "FL2VA
  image-to-video with synchronized generated sound, and the longer takes of
  the two engines." Length choices: 5s ("a scene"), 10s ("a full take"), 15s
  ("a long take").

Both engines generate their sound natively with the clip — there is no
separate audio step and no mute toggle. What you hear is directed by your
note, so if sound or speech matters, write it in. Spoken lines have to fit
the clip: the budget the director is held to is about two and a half words
per second, and the last word must complete before the final second. A line
that overruns can end mid-word, and the overflow can surface as a stray sound
fragment over the opening frames — if a clip opens with a phantom syllable,
that is what happened; shorten the line.

An engine whose assets are not installed is greyed out; hovering names the
missing pieces (for example "LTX 2.5 transformer", "Gemma 4 text encoder").
An engine that will not fit your card comfortably still runs but warns: a
line under the picker reads like "wants 24 GB+ of VRAM and this card reads as
16 GB - it still runs, but streams weights instead of holding them - about
5x slower".

### Length

The "length" track offers the current engine's durations with plain glosses
("a moment"). With more than one shot it relabels itself "length · per shot"
and the caption adds the total, e.g. "a moment · ~10s total".

### The fine-tune fold

Everything situational hides behind **fine-tune**. The closed row narrates
whatever non-defaults it is hiding — "5 shots · end frame set · turbo 8 ·
24fps · 2 LoRAs" — so a collapsed fold never lies about what will render.
Inside, in order:

- **model** — when the engine has more than one build installed. LTX 2.5
  ships "Distilled" ("LTX 2.5 22B distilled INT8; the official two-pass graph
  with the x2 latent upscaler."). H3 splits its builds base-first: a
  segmented track picks the family ("FL2VA", "REF2VA"), and a picker under
  it lists that family's builds at full name — the stock build first
  ("First-frame video with native synchronized audio."), then its community
  finetunes ("Community FL2VA finetune - same encoder, VAEs and LoRA catalog
  as stock."). An NSFW finetune is flagged "NSFW finetune — distill LoRA
  chained automatically".
- **shots** — H3 only. One clip is one continuous take ("one continuous
  take"); the row's ⓘ tip explains the chaining and that shots separated by
  --- on its own line in the note ship verbatim as a script. Step it up and
  each shot continues from the last frame of the one before, with the
  caption doing the math ("~10s total — each shot continues from the last
  frame of the one before").
- **end frame** — H3, single takes only. Pick another still from your
  history and the clip converges on it: "the clip converges on the selected
  frame". "none" clears it ("no end frame - the clip ends wherever the
  motion lands"). Greyed with multiple shots: "single continuous takes only
  — set shots to 1".
- **frame rate** — when the engine offers a choice, chips like "24fps" with
  the frame count as the hint ("360 frames").
- **speed** — H3's ladder: "Quality" ("20 steps, no distillation"), "Turbo 8"
  ("8 steps, lightx2v v1.0 @0.8"), "Turbo 4" ("4 steps, Kijai's recipe
  @0.75"), "Turbo v4 (old)" ("8 steps, superseded"). A speed whose LoRA file
  is not on disk is greyed; hovering says why: "Turbo 8: its LoRA is not in
  the loras folder, so this recipe can't run".
- **attention** — H3, and only when the sparse-attention pack is installed.
  "sparse" (the default, hinted "sparse · ~1.3x faster on this size") or
  "dense" ("dense on every step · the quality reference"). Sparse attention
  skips most of the attention work on long, high-resolution clips: measured
  here at 1.34x on a 1MP, 124-frame take. It switches itself off on short or
  low-resolution clips where it would not help, so it costs nothing there.
  The reason "dense" exists is so you can render the same shot both ways and
  judge the difference yourself. If the pack is not installed the row is not
  shown at all.
- **2x upscale** — H3, and only when the upscale pack and its 659 MB
  upscaler weights are installed. "off" (the default, hinted "the render's
  native size") or "2x" ("~3x longer · runs inside this render, not after").
  The clip is re-sampled at twice the size as part of the same render — the
  pass needs the latent the sampler just produced, so it is an option on the
  render, never an action on a finished clip. Measured here: a 928x1120,
  124-frame take went from about 140s to 464s, peaking at 30.9 of 32.6 GB —
  off by default because it roughly triples the wait. If the pack or the
  weights are missing the row is not shown at all.
- **video LoRA chain** — H3 with the FL2VA model. "top row loads first":
  **add LoRA** opens a searchable list ("find a LoRA…") of your installed
  video LoRAs with their trigger words; each chain row gets an enable switch,
  a strength slider, and move/remove buttons ("move earlier", "move later",
  "remove"). Empty, it says so: "No video LoRAs active. Add one when this
  clip needs it." The chain is remembered per engine-and-model, so switching
  engines never leaks a chain across.

### When VRAM is short

If the engine warns about your card, a **find a lighter build** button
appears ("list lighter quantized builds of this model on Hugging Face"). It
asks Hugging Face ("asking hugging face…"), then lists downloadable quantized
builds with their sizes and a verdict per file — "fits", "too big", or
"blackwell only" — and downloads the one you pick into place, with progress
("1.2/4.2 GB"). If nothing fits your card it tells you straight:
"nothing fits 16 GB — the smallest is listed above".

### Video defaults in Settings

The dialog always opens on your defaults. Change them under **Settings →
Video**:

- **Video engine** — "Which engine the Animate popup opens on. The popup
  still switches freely per clip - this only sets where it starts." Leave it
  on "auto" to follow the server's order.
- **Video model** — "Which model the Animate popup opens on inside its
  engine - the popup still switches freely per clip." Lists the chosen
  engine's models, or every engine's (labeled "engine · model") when no
  default engine is set. A model whose assets are missing is badged
  "missing".

---

## 5. Finishing

**upscale** on a card runs whatever the Settings upscaler has
configured — still frames under Settings → Image, video clips under
Settings → Video. The result lands in the chat as a new card, in Past
generations
(marked with a "4×" chip), and on disk under `ComfyUI\output\pixal_dm\…`
beside everything else.

### Still frames

Two modes, named exactly as Settings names them:

- **Model** — an ESRGAN-style enlarger model repaints nothing: it enlarges
  the frame it already made. Pick the model from the installed list (each row
  shows its scale as a chip, like "4×"). The footnote does the arithmetic:
  "The model's own factor decides the size — a 4× model on a 1024-wide frame
  gives 4096."
- **PiD 4×** — "NVIDIA PiD v1.5, INT8 ConvRot. 4-step diffusion in 1024px
  tiles at 4× — any aspect ratio; invents texture instead of sharpening.
  Models auto-download on first use. Non-commercial license." Where Model
  mode sharpens what exists, PiD hallucinates new fine detail. It needs the
  ComfyUI-PiD node pack; without it the option is greyed ("Install the
  ComfyUI-PiD node pack for PiD.").

### Video clips

The "video clips" control lists the clip upscalers:

- **VSR Low / Medium / High / Ultra** — RTX Video Super Resolution, a
  Windows driver feature. The hint states the deal: "Doubled at 2× with
  audio kept." (The scale figure follows your setting.) Without the Deno RTX
  VFX node pack the row is greyed: "Install the Deno RTX VFX node pack to
  upscale clips."
- **LTX 2.5 2x** — a generative re-render: "Re-rendered at 2× — real new
  detail, audio untouched." Slower than
  VSR, and it invents detail rather than interpolating it.

### PiD finish

A separate switch, "PiD finish", changes how Identity Edit renders decode at
all; the tip beside it explains: "Identity Edit renders decode through NVIDIA
PiD instead of the Wan VAE — the finished latent is repainted at 4× in a
4-step diffusion pass. A 2:3 canvas comes back 2688×4032." The trade-off is
stated where you flip it: "Experimental: canvas snaps to 1024-class presets
and returns 4×."

---

## 6. Settings reference

Open Settings from the rail's gear. Six tabs — **General**, **Image**,
**Video**, **Models**, **Brain**, **About** — and every control saves the moment you
change it; the strip at the bottom confirms ("saved", "upscaler applied", …).
The tab you used last is remembered.

### General

**Appearance** — Light, Dark, or System. "System follows Windows."

**Explicit content** — three positions: "auto", "allow", "never". The
footnote reads "auto reads your words; never keeps subjects dressed." The
tip adds that allow leaves your prompt exactly as written, and that the
switch only bites with Prompt enhance off — with it on, the chat brain
still decides.

**Compute** — the ComfyUI box that renders: "Another rig's address borrows
its GPU." The address field's placeholder shows the default,
`http://127.0.0.1:8188 (this PC)`; point it at another machine's ComfyUI to
render there. Three buttons beside it:

- **free VRAM** — drops the models ComfyUI has cached on the card. Confirms
  "VRAM released - the chat brain is untouched".
- **restart** — restarts ComfyUI itself. "ComfyUI restarting - the boot
  meter takes it from here". This is the fix for a wedged sampler or a node
  that will not let go.
- **free brain** — unloads the chat model. "chat model unloaded - the next
  message brings it back".

The tip holds the deliberate laziness: freeing is safe — the next render
reloads what was dropped, and the chat brain rides its own process, so free
it only when a video clip needs the room. (The 21 GB video stack staying
resident is exactly why a second render is fast.)

**when ComfyUI boots** — "quiet" or "open the graph editor". The tip:
ComfyUI likes to pop its node editor in a browser tab when it starts; quiet
keeps that from interrupting, and the editor is always at the compute
address above.

**ComfyUI's console window** — "meters" or "plain console". The tip: meters
wrap the launcher in a boot dashboard and keep an errors-only log at
logs\comfy-errors.log; plain console is the raw ComfyUI output. Either way,
closing that window stops ComfyUI. The meters console has keys: `E` opens
the errors log, `L` the full transcript, `V` toggles the raw output, `Q`
stops ComfyUI.

**VRAM profile** — once ComfyUI has booted, the line under the title tells
you what it found ("The card reads as 16 GB."); before that, "Card not read
yet — auto follows it." "auto" follows the detected card; pin 32, 24 or 16
GB to preview what that tier honestly gets. The tip: what the machine can
hold resident is advisory — pickers flag what a tier holds poorly; the card
itself is still managed at render time.

**Model folders** — "Where your checkpoints and LoRAs live." plus the count
it indexed ("Found 412 files."). The list is every folder Pixal scans: your
ComfyUI's `models` tree plus anything you add. Add a folder ("add a folder,
e.g. D:\models"), remove one with its ×, then **rescan folders** — the note
says "rescanning - watch the status row" and the status row above the message
box narrates the scan. This is how your existing checkpoint and LoRA library
joins Pixal without moving a file.

### Image

**Z-Image decoder** — "Sharper drop-in; can over-sharpen on one pass."
Default is "stock Z-Image VAE (recommended)". The tip: Z-Image and Flux
share a VAE, so sharper drop-ins exist; it applies to Z-Image renders only,
and the clear-anime profile keeps its own matched VAE either way.

**Edit model** — two lanes, two pickers. "Runs instruction edits." plus both
counts ("3 whole-frame, 2 masked compatible installed."). **whole frame**
runs when there is no mask; **masked area** runs when a mask is painted.
Each option names the build and what it weighs on disk ("Qwen Image Edit
2511 · 10.4 GB"); a build heavier than your card says so in its tooltip —
it will offload and run slowly, nothing is blocked. Both default to the
recipe's own. The tip: a painted mask routes the edit to the masked lane;
no mask runs the whole-frame lane. Whole-frame releases differ in encoder
node, not just weights — the graph switches on the filename, so any
compatible generation works.

**Edit speed** — there is no Settings control for this one; it lives only
in `config.json` in the Pixal folder. `"edit": {"speed": "turbo"}` is the
default; the other value is `"full"`. Turbo runs the edit model's own
distilled fast schedule — "Qwen-Image Lightning 4-step V2" on the Qwen
line, "FireRed 8-step Lightning" on FireRed — and only when that LoRA is
actually in the loras folder; `"full"`, or a missing LoRA, runs the model's
un-accelerated schedule instead. The pairing is deliberate: a distillation
is trained against one set of weights, so the wrong accelerator does not
error — it quietly ruins the edit. `config.json` is re-read on every edit,
so the next one picks the change up; no restart.

**Upscaler** — "Model enlarges; PiD repaints." plus the installed count. The
still-frame mode (Model / PiD 4×) and the upscale model picker are walked in
Section 5; the tip holds the size math (the model's own factor decides — a
4× model on a 1024-wide frame gives 4096). The clip side sits on the Video
tab.

**PiD finish** — the Identity Edit decode switch; walked in Section 5.

### Video


**Video engine** — "Which engine the Animate popup opens on." **Video
model** — "Which model the popup opens on." The Animate dialog's defaults
(see Section 4); each tip notes the popup still switches freely per clip.

**Dialogue format** — "How H3 briefs write spoken lines." **quotes** is the
default — `(S1) says "…"`, the MiniMax-H3 discussion #76 form; it won the
same-seed A/B with no opening blip and no cue read aloud. **tags** is
MiniMax's trained `(S1) says: <d>[English] …</d>`, which some seeds open
with a half-second of gibberish.

**Upscaler** — "Used by the upscale button on a finished clip." The "video
clips" engine (VSR, or LTX 2.5 2x); walked in Section 5.

**H3 2× upscale** — "The popup still decides per clip — this sets the
default." The MiniMax 2× pass runs inside the render — it re-samples the
render's own latent, so it can never be a button on a finished clip — and
costs roughly 3× the render time. Greyed until the MMH3 Ultimate Upscale
pack and its 659 MB weights are installed.

### Models

The library — read-only; choosing per lane stays on the Image and Video
tabs. The summary line counts what you own ("47 models · 416 LoRAs · 141
have no profile") beside what the card measured ("The card reads as
32 GB."); the tip there explains that a LoRA with no profile is skipped at
render time rather than stacked blindly. Below it, every build you own
grouped by family — Krea 2, Z-Image, Klein, Qwen Image Edit, Qwen Image,
Anima, Video, then Other — one line each: the product name (the raw
filename is the tooltip; a Civitai-matched name links out), the lanes it
runs, and its weight on disk. A build heavier than the card says so in its
tooltip — it will offload and run slowly; nothing is blocked. A model
nothing here can run says why ("a Flux model — no lane here runs it yet"),
and video models point at the Animate lanes.

### Brain

**Chat brain** — two tabs: **API** and **Local**. The tip: the AI you talk
to — it writes the prompts and drives ComfyUI; local runs entirely on this
PC, and Pixal starts and stops it for you. Section 7 covers both in depth.
In short:

- API: the Kimi, DeepSeek and OpenRouter buttons prefill the two fields
  ("server address (e.g. https://api.deepseek.com/v1)", "model name (e.g.
  deepseek-chat)"); the key field shows "API key (sk-…)" until one is saved,
  then "API key saved (ends …XXXX) - blank keeps it". The lock note: "Only
  your provider sees the key — never the PNG metadata." **Test connection**
  answers "connected - <model>" or the provider's error.
- Local: a list of the .gguf chat models found in your model folders, each
  with its quant, size, and VISION / NSFW chips. The lock note: "Runs
  entirely on this PC — nothing leaves the machine." "keep in memory" vs
  "unload after reply" — the tip holds the trade-off (loaded: instant
  replies, but a few GB of VRAM held next to your renders; unloaded: the
  card is free, but the next reply waits for a reload). **brain runs on** —
  GPU or CPU; the tip: GPU replies fast but holds VRAM next to the render,
  CPU chat is slow but frees the card.

**Image reviewer** — "Suggests fixes for what you made." Pick from the
reviewer models you have installed (NSFW-capable ones are badged). The tip:
when the chat brain has vision it reviews directly — this ComfyUI model is
the fallback for brains without eyes; bigger models read hands and text
better, and first use takes ~30s to warm up.

### About

The credits card: version and channel chip, the one-line pitch ("Chat with
your GPU. Images and video on your own ComfyUI — no graphs, no node soup."),
"Developed by Jesse" with a mail link (hello@getpixal.com, "Questions?
Looking for dev or design?"), and the projects Pixal stands on — NVIDIA
(PiD upscaling, RTX video super resolution), LTX (the fast animate engine),
MiniMax (video with native audio) — and a thank-you to the ComfyUI team,
"Every render here runs on it."

---

## 7. The local brain

The chat brain is the model that reads your messages, writes the prompts,
and decides which recipe renders them. Settings → Brain → **Chat brain**
gives you two ways to have one.

**API** means any OpenAI-compatible chat-completions endpoint. The Kimi,
DeepSeek and OpenRouter buttons only prefill the address and model fields;
point it at whatever provider you like. Your messages — and, for reference
images, the images themselves — go to that provider under your key and their
policies.

**Local** is a GGUF model on your own disk that Pixal starts
and stops for you (a llama.cpp server on `127.0.0.1:8191`). The installer's
brain component is a 4.8 GB vision-capable build; its own pitch is "Chat,
prompt writing and routing run on your own GPU. No API key, no account."
and the in-app note completes the promise: "runs entirely on this PC - no
key, nothing leaves the machine." Rows badged VISION can read the images
you attach; a brain without vision gets a placeholder instead of your
picture, and reference types like style and clothing have nothing to look
at.

Three local behaviors to know:

- **keep in memory** vs **unload after reply**. Kept: instant replies, but
  the model holds a few GB of VRAM next to your renders. Unloaded: the card
  is free for rendering, but the first message after a render waits for the
  model to load again ("waking the local brain - …"). The "free brain"
  button in Settings → General → Compute unloads it on demand.
- **brain runs on** — GPU or CPU. The hint is the whole trade: "GPU replies
  fast but holds VRAM next to the render; CPU chat is slow but frees the
  card for rendering."
- On a 16 GB card the local brain is the component that crowds VRAM — the
  image models themselves run fine quantized. If renders start running out
  of room, the honest options are: switch the brain to "unload after reply",
  run it on CPU, or point chat at an API brain (one Settings field) and take
  the headroom back.

If no local model is picked, chat tells you what it needs: "pick a local
chat model in settings first". With an API brain and no key: "no API key set
- add one in settings or switch to Local".

---

## 8. Remote use

Out of the box Pixal listens on loopback only — `127.0.0.1:8190` — which
means only this PC can reach it. Two keys in `config.json` (in the Pixal
folder) open it up:

1. Set `"lan_access": true`. Pixal then binds every interface, so a phone,
   tablet or laptop on the same network can open the studio.
2. Find `"access_key"`. If it is empty, a random key is minted at first
   boot, so there is always one.
3. On the other device, open `http://<this machine>:8190/?key=<access_key>`
   once. The key sets a `pixal_key` cookie good for 30 days, so the daily
   URL is just `http://<this machine>:8190`.
4. Anything arriving over the network without the key gets "pixal: key
   required" and nothing else — there is no login page to guess at.
   Requests from the PC itself pass free.

Two cautions, both deliberate design:

- That single shared key is the entire lock, and the app can write files and
  drive a GPU on the host. Put Pixal on networks you trust, and do not
  port-forward it to the public internet.
- By default the studio exists to be looked at: when no window has been
  connected for 30 seconds, Pixal closes itself (and the ComfyUI it
  started), so an idle GPU stack never outlives its UI. A phone tab that
  backgrounds trips that timer. Set `"stay_up": true` in `config.json` to
  keep the studio running with no window connected.

On the phone, the browser's add-to-home-screen gives you the standalone
app window (the manifest's own description: "A DM with this ComfyUI box -
chat in, images out.").

---

## 9. Troubleshooting

Each entry: what you see, what it means, what to do.

**"Starting ComfyUI" that never ends.**
The bar holds at the end and the note reads "cold cache — still loading".
Meaning: boot is taking longer than the calibrated estimate, usually a cold
model cache. Give it a few minutes the first time. If ComfyUI stops
responding for two minutes, or runs far past its estimate, two buttons
appear on their own: **retry** reloads the page, **continue without
ComfyUI** lets you into the app anyway.

**"ComfyUI is busy — loading a large model".**
ComfyUI holds its port but is not answering yet. That is a load, not a
wedge — wait. Past two minutes the note escalates: "ComfyUI holds port 8188
but isn't answering — it may still be loading a large model, or it may be
wedged. Restart ComfyUI from Settings → General → Compute if this doesn't clear."

**"ComfyUI didn’t start".**
The boot gave up, and the message under the heading is the specific reason:

- "ComfyUI exited during boot - …" / "ComfyUI did not come up within 6
  minutes" — open `logs\comfy-errors.log` in the Pixal folder: errors only,
  each with its boot phase. `logs\comfy.log` has the whole transcript of the
  last boot; `logs\comfy.prev.log` has the one before (what you want when it
  is crash-looping).
- "no ComfyUI launcher (.bat) found beside the ComfyUI folder - start it
  yourself" — Pixal looked next to your ComfyUI for its launcher and found
  nothing it can run. Check the ComfyUI path (Settings → General →
  Compute shows where
  it renders; the installer wrote the root into `config.json`), or start
  ComfyUI yourself — Pixal adopts whatever is already answering on its
  address.

**"ComfyUI is closed".**
"you closed the ComfyUI window — start it again when you want to render".
Closing ComfyUI's console window stops ComfyUI (that is also what `Q` does
in the meters console). The **start ComfyUI** button on the boot screen
brings it back.

**"Pixal isn’t answering".**
"the Pixal server (port 8190) stopped answering — restart Pixal (run.bat);
this screen reconnects on its own." The app lost its own server. Start
Pixal again from the shortcut; the open window rejoins by itself. If the
window never opened at all and you got a "Pixal couldn't start." message box
instead, the detail is in `logs\sidecar.log`.

**Double-clicking Pixal does nothing.**
Almost always: it is already running. Started from a console it tells you
plainly — "Pixal is ALREADY RUNNING at http://127.0.0.1:8190 - use that one;
this window can close." Open the address in a browser. A stale dead process
holding the port is called out with the exact `taskkill` line to free it.

**"pick a local chat model in settings first" / "local model file is gone:
…".** The brain is set to Local but no model is chosen (or the chosen file
was moved). Settings → Brain → Chat brain → pick one of the listed .gguf
files.

**"the local brain crashed loading … - inspect llama_server.log"** (also:
"the local brain didn't come up with … (2 min timeout)").
The model file failed to load — usually a damaged download or a backend
problem; `llama_server.log` in the Pixal folder has the load transcript.
Re-running **Pixal Setup** re-fetches the brain component.

**"the local brain started without vision - attached images will not be
read".** The model loaded but its vision projector did not, so chat is
text-only this session and your attachments flatten to placeholders. The
cause is logged in `llama_server.log`; a reinstall of the brain component
(Pixal Setup) replaces both files. Workaround with zero waiting: switch Chat
brain to API — a vision-capable API model reads attachments directly.

**Chat is suddenly slow.**
Three honest causes, in the order to check:
1. "unload after reply" is on — every first reply pays the model-load time.
   "keep in memory" trades a few GB of VRAM for instant replies.
2. **brain runs on** is set to CPU. The setting's own words: "CPU chat is
   slow but frees the card for rendering."
3. Neither, and it is still slow: the local brain may have silently fallen
   back to running on the CPU because its CUDA pieces failed to load. That
   failure is visible in `llama_server.log`; a broken llama.cpp install is
   the usual cause, and Pixal Setup's brain component reinstalls it.

**"no API key set - add one in settings or switch to Local".** Chat brain is
set to API and the key field is empty. Paste a key (it saves on blur) or
flip to Local.

**"something is still rendering - try again when idle".** Pixal refuses to
restart itself while work is in flight — a queue with renders left, a chat
turn still running, or ComfyUI still booting. Wait for the studio to go
quiet and ask again.

**A render dies with "ran out of VRAM - clearing the card and retrying",
then an italic note in the chat.**
Pixal watches the card and manages it in the open. The notes you can meet:

- "*making room - this render stages ~21GB: cleared cached models; rested
  the chat brain - it returns on your next message*" — it freed what it
  could before starting. Sometimes: ". Still tight (…GB free) - … so this
  one may crawl".
- "*that render ran out of VRAM. Cleared the card and trying again at 5s
  instead of 10s. Ask for it again if you want the full-size version.*" —
  it retried smaller on its own (shorter clip, smaller canvas, cleared
  card). Or, when nothing smaller exists: "*…ran out of VRAM and there is
  nothing smaller to try automatically. The card is clear now, so running
  it again may well land.*"
- "*this render is crawling - … The model is being streamed from system
  memory rather than sitting on the card. … It will finish and it will look
  right … If it is unbearable, restarting ComfyUI is the quick way out.*"

What to do, in escalating order: let it finish (it will be right, just
slow); **free VRAM** and **free brain** in Settings → General → Compute;
set the chat
brain to "unload after reply" or CPU; drop the megapixels or the clip
length; use the Animate dialog's "find a lighter build".

**The status dot says packs are missing.**
The dot in the rail (green when connected) opens the ComfyUI compatibility
card. Healthy: "Everything Pixal renders is installed". Otherwise it names
the count — "2 packs missing — 3 nodes Pixal can't queue" — and which packs
and nodes. Run **Pixal Setup** and tick the components that pull those node
packs. The card's **copy report** button puts the whole inventory on the
clipboard for a bug report.

**"Klein inpaint is unavailable." / "Qwen Image Edit is unavailable."**
The edit dialog found its models missing; the bullet list names the exact
files. The Qwen editor comes with the editing component in **Pixal Setup**;
Klein's weights are a gated Hugging Face download you add yourself (accepting
their license there), in the folders the list names.

**"image is larger than the 40 MB upload limit".** Uploads cap at 40 MB.
Downscale or recompress the image and attach again.

**After an update the app looks old or half-loaded.**
The app shell is cached by your browser (that is what makes it start
instantly and work as a home-screen app). Hard-refresh once — Ctrl+F5 — to
force the new shell in.

**A video opens with a stray sound fragment, or a spoken line cuts off
mid-word.** The line did not fit the clip: speech runs about two and a half
words per second and must complete before the final second. Shorten the
spoken line in your note and render again. See Section 4.

---

## 10. Linux

There is no Linux installer and no packages: on Linux you assemble the
pieces by hand (git, a venv, ComfyUI beside the repo) and keep them working
yourself — manual and unsupported today. `LINUX.md` in the Pixal folder is
the runbook, including what works (rendering, editing, video, the local
brain, LAN) and what honestly does not (RTX VSR, the installer, the meters
console). Windows remains the supported target.

---

## 11. FAQ

**Is Pixal free? Is anything metered?**
Pixal itself costs nothing and has no accounts, subscriptions, or meters —
the license is royalty-free to install and run. Downloads go to your machine
and stay there. The one thing that can cost money is optional: if you point
the chat brain at an API provider, that provider meters your key under your
account with them. The local brain has no key and no account.

**Does anything leave my machine?**
By default, nothing: Pixal listens on 127.0.0.1, chats, characters, settings
and history stay in the Pixal folder, and renders stay under
`ComfyUI\output\pixal_dm`. The installer's welcome says it flatly:
"Everything stays on this computer - nothing is uploaded." Two deliberate
exceptions: an API chat brain receives your messages (and attached images)
under that provider's policies, and turning on LAN access (Section 8) puts
the app on your local network behind its access key.

**What GPU do I need?**
An NVIDIA GPU with driver 580 or newer — Setup checks and refuses without
one ("Pixal renders on NVIDIA GPUs"). How much VRAM decides what is
comfortable, in the installer's own words: 24 GB and up is "everything,
video included"; 16 GB is "everything but H3 video"; 8–16 GB should "use
quantized builds — GGUF, INT8, NVFP4"; below 8 GB is "tight — Anima only,
quantized". H3 video wants 24 GB. Below the comfortable tier things still run — they
stream weights and slow down rather than refuse.

**What actually works on 16 GB?**
Every still-image model (Anima, Z-Image, Krea 2, the editors) and LTX 2.5
video, with the local brain set to "unload after reply" or CPU when things
get tight. MiniMax H3 video runs but streams weights — the dialog warns "about
5x slower". The local brain is the piece that crowds a 16 GB card; the image
models run fine quantized.

**Can it use the models and LoRAs I already have?**
Yes — that is the point of Model folders in Settings. Point Pixal at your
existing ComfyUI (or add any extra folder) and **rescan folders**; nothing
is moved or copied. Your checkpoints appear in the **model** pill as long as
they belong to a family Pixal has a profile for (Krea 2, Z-Image and Anima
today; the picker says "No installed model has a supported Pixal profile
yet." when none match), and your LoRAs join the LoRA chain filtered to the
ones compatible with the selected model ("Showing only Z-Image LoRAs
compatible with the current model profile.").

**Do I need to know ComfyUI?**
No. Pixal builds and queues the graphs; you never see a node. If you are
curious, the full editor is one setting away ("open the graph editor" in
Settings → General) or at the ComfyUI address any time — but nothing in the
normal flow asks for it.

**Can Pixal break my existing ComfyUI install?**
The installer changes nothing inside an existing ComfyUI except adding the
node packs Pixal needs, in its own words. It will not update a ComfyUI that
has local edits ("local changes - left alone"), it never overwrites a model
file when tidying (the undo list of what moved is written to `install\_work`),
and it refuses to install over an existing folder. At run time Pixal reads
your models and writes only to its own corner: `output\pixal_dm` for renders,
`input` for your uploads.

**Why is chat suddenly slow?**
Usually the local brain is unloading after each reply (Settings → Brain →
"keep in memory" fixes it) or running on CPU on purpose ("brain runs on").
If neither is set, its CUDA backend may have failed to load and silently
dropped it to the CPU — `llama_server.log` says which. Section 9 walks all
three.

**Why did my video come out silent, or with weird speech?**
Both engines generate the soundtrack as part of the render — there is no
separate audio step — and the sound follows your note: if speech or music
matters, write it in. Spoken lines have a budget of about two and a half
words per second and must finish before the final second; an over-long line
ends mid-word, and the overflow can surface as a stray fragment over the
opening frames. Shorten the line and re-render.

**Can I use it from my phone?**
Yes, on the same network: set `lan_access` in `config.json`, open
`http://<the PC>:8190/?key=<access key>` once, and optionally add it to your
home screen for the standalone window. Set `stay_up` too, or a backgrounded
phone tab lets the studio close itself after 30 seconds. Section 8 has the
whole flow and the trust warning — the access key is the only lock, so keep
it to networks you trust.

**Can I use my renders commercially?**
The license is plain: "Images, video and other output You create with the
Software are Yours." and you may run Pixal itself "for any purpose including
commercial purposes". What you may not do is pass the *software* on.
Model licenses ride on top, and three components in the box carry
non-commercial terms — the license on the checkpoint, not on your pictures:
the Anima anime model ("CircleStone Labs Non-Commercial v1.2. The images are
yours; the checkpoint is not for commercial use."), FLUX.2 Klein (the masked
inpaint editor and the Klein whole-frame editor; FLUX Non-Commercial License
v2.1), and the PiD upscaler
("Non-commercial license"). Everything else follows its own authors' terms;
`THIRD_PARTY_NOTICES.md` lists what Pixal is aware of.

**How do I update?**
Download the newer installer and run it over the same install — it refreshes
the code and keeps your `config.json`, history, chats, characters, styles and
logs untouched. Interrupted or partial runs resume: "Nothing is lost. Open
Pixal Setup from the Start Menu and it picks up where it stopped."

**How do I uninstall?**
"Uninstall Pixal" in the Start Menu (or Apps & features, "Pixal 1.0.9b").
It removes the app itself. It does not remove ComfyUI or any downloaded
models — those live outside the app folder — and your renders stay under
`ComfyUI\output\pixal_dm`. Your characters and saved styles are left behind
in the install folder rather than deleted; remove that folder by hand if you
want them gone too.

**Mac? Linux?**
Windows is the supported target today. Linux has a manual, unsupported path
— `LINUX.md` is the runbook and makes no promises. There is no Mac build.

**Where are my images on disk?**
Everything Pixal renders lands under `<ComfyUI>\output\pixal_dm\`, named
after the scene. Videos and upscales land there too. Images you uploaded or
attached live in `<ComfyUI>\input`. The reviews the critic writes sit beside
the renders as `review_….txt` files.

**Where are my chats, characters and styles saved?**
In the Pixal folder: `history.jsonl` and `chats\` for conversations (a chat
is titled from your first message), `characters\` for anchors, `recipes\`
for saved styles, `config.json` for every setting. All plain JSON you can
read, back up, or copy to another machine.

**What does the padlock on a card do?**
Freezes that render's seed. While it is locked, every render — chat, re-roll,
anything — reuses the seed until you unlock it. See Section 2.

**Can two copies of Pixal run at once?**
No — the port is the single instance. The second one tells you "Pixal is
ALREADY RUNNING at http://127.0.0.1:8190 - use that one; this window can
close."

**Where do I report a problem or ask for help?**
hello@getpixal.com — the address is on the Settings → About card. The
compatibility card's **copy report** button (hover the status dot in the
rail) puts a full ComfyUI/node-pack inventory on your clipboard, which is
the right thing to paste into the mail.
