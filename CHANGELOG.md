# Changelog

## 1.1.7b — 2026-09-01

**Settings speaks one design language now.** The panel was six tabs of
controls collected over twenty releases, each in whatever style the week it
shipped had — stacked labels, tall switches, loose spacing that read more
prototype than product. Every control now belongs to one small family: a
wide, low pill toggle with a dark knob on the chartreuse track, pill
selectors for short choices, compact value pills for pickers, and every
setting on a single 34-pixel line — its name, one plain fact about it, and
its control, nothing wrapping. Installed model families wear a quiet
chartreuse badge; a family you could add shows an Install badge instead.
There is a search field at the top (press `/` to jump to it) that filters
the whole tab as you type. And the Brain tab is called Chat now, which is
where you expected it to be all along. No setting moved, changed meaning,
or changed its default — the panel just grew up.

**The sampler suggestions are called Presets.** The tuning card's
"KNOWN GOOD" header read like a warning label; it now says Presets, in
words. The community table-topper pill is gone from the MiniMax H3 stills
row — it measured lowest of the three here and twice pushed the subject
off a position the caption had pinned, and a preset that loses every
audition should not keep its seat. The measured Detail and Speed pairs
remain.

## 1.1.6b — 2026-09-01

**Editing a character no longer resets your model pick.** Swapping a
character's reference photo — or touching any field on their card — quietly
threw away the model you had selected and flipped the render lane, because
saving the card was treated as picking the character all over again, by a
code path that predated MiniMax H3 carrying characters at all. An edit of
the active character now just saves; and selecting a character keeps an H3
model exactly where you put it, since the character's photo rides that
model's own reference input.

**The app now costs your GPU nothing when you are not looking at it.** The
ambient dot field behind the chat kept redrawing itself thirty times a
second even while Pixal sat unfocused behind a game or another tool, and
the gallery, chats and settings panels kept an expensive glass blur running
while a render was sampling. All of it now stands down — the field freezes
in place the moment the window loses focus and wakes when you return, and
every glass surface drops its blur while ComfyUI is working, the same way
the chat surfaces always have. Nothing about the look changes while you are
actually using it; your VRAM-starved render just stops sharing the card
with decoration.

**When the writer talks instead of rendering, its chatter no longer leaks
into the picture.** Occasionally the prompt writer answers a render request
conversationally — "Got it, here's the shot: …" — and Pixal already
rescued those by rendering the scene it described. But the rescue sent the
whole reply to the model, greeting and "want me to tweak it?" included, and
the image conditioned on every one of those words. The scene is now cut
cleanly out of the chatter before it renders: lead-ins and sign-offs are
dropped, the description itself is kept word for word, and a closing line
of spoken dialogue survives because that is part of the shot.

## 1.1.5b — 2026-09-01

**Every text encoder option refused the render it was for.** 1.1.4b put the
MiniMax H3 text encoder in Settings and offered three smaller encoders in place
of the stock 14.6 GB one. All three were unusable. The loader was told to
expect the 32B architecture no matter which file it was handed, so picking any
of them ended the render before it started, with the encoder's own complaint:
"is a 4B, but the type is set to minimax." The setting existed, the files were
on disk, and nothing in the row could be selected without breaking the lane.
It reads the file's own header now, which is what the loader documents as the
right answer.

**And the smaller encoder now gets out of the way.** It was being pinned in
video memory for the whole render - which is the opposite of the point, since
the reason to run a smaller encoder is to leave room for the model that does
the actual work at every step. It hands the memory back once it has read your
prompt, and pays a moment to load again next time. Measured on a still: 41.4
seconds pinned, 42.7 seconds not. That second and a bit buys back five
gigabytes.

Worth knowing what the swap is really for: on a 32 GB card the stock encoder
cannot sit beside the diffusion model, so every render evicts one to load the
other. With the 4B, that stops - and the render is quicker too. Same picture,
same seed, same size: 42.7 and 41.4 seconds on the 4B against 48.9 and 58.6 on
the 32B. Identity is the trade - the smaller encoder brought a face back three
times in four where the stock one managed four - so it stays a switch you own
rather than a new default.

**The character card stops fighting the photo.** A card's look was one
free-text blob doing four jobs at once - build, hair, grooming, wardrobe - so
a render could only take all of it or none. Measured on the reference lane,
all of it was the wrong answer: with the blob sent, framing broke in four of
five renders and the hair colour drifted; with it left out, both held. The
model was reading a paragraph about a body while the reference photo tried to
assert a specific person. The card now has separate fields for build, hair and
grooming, each riding as its own short sentence - and a render with a
reference photo wired sends the hair and grooming but drops the build, because
the photo already carries it completely. Hair is always sent: its colour is
the one thing that drifts without a stated defence. The character form shows
both versions of what will be sent, and cards written before this release
compose exactly as they always did.

**H3 video now encodes at 10 bits.** The three MiniMax H3 video lanes write
their clips through ComfyUI's own video saver at 10-bit depth, which keeps
smoother gradients in skies, skin and shadows - the banding that 8-bit H.264
paints into slow gradients simply is not there. Measured on one render encoded
both ways, the 10-bit file was also the smaller one. Nothing about timing
changes: the 24 frames per second that H3's baked-in audio is synced to stays
pinned everywhere.

**It also carries the known-good sampler settings**, which were built into
1.1.4b's installer but missing from its notes. The sampler card offered
"recipe / model / custom", and "model" - the settings a model's own page
recommends - has never once been clickable on Krea 2 or MiniMax H3: three of
the fifty-one models here publish such a line and all three are Z-Image. Krea
2's sampler menu is 182 names long. So the card carries a row of known-good
pairs, one click each, setting sampler, scheduler, steps and eta together.
H3's three were measured here at a locked seed; Krea 2's three are RES4LYF's
published figures for the Qwen-Image family and say "not measured here" on
their face. Hover a pill for where its numbers came from. A pair the current
sampler node cannot run is never offered.

## 1.1.4b — 2026-08-31

MiniMax H3 reference stills got a night of hard measurement, and almost every
answer turned out to be something Pixal was *adding*. This release takes those
things out, and puts back the two that measured. It also carries everything
from 1.1.3b, which was built but never published.

**The bug that undressed people is fixed, properly this time.** On this model
family the last clause a caption ends on is the one that decides whether the
subject stays dressed - and the wardrobe clause was never actually last. 1.1.3b
moved it to the end of the caption; the builder then wrapped the caption in a
sentence of its own, so what the model read last was "nothing in the frame
moves". At one seed, on both graph shapes, a scene that named only a hoody
rendered the subject in underwear from the waist down. The freeze instruction
now leads and the scene closes, so the wardrobe really is the last thing read.

**H3 reference stills render one frame instead of five.** The still lane was
driving a video model at its five-frame floor and throwing four frames away.
With MiniMax's one-frame node and their T1 image VAE installed it now builds a
true single-frame graph: one VAE doing both ends instead of three, no audio VAE
loaded for audio nobody decodes, and no frame to fish out of a batch. Their
image VAE's encoder is bit-identical to the video one, so nothing is traded for
it. Without those two files, the graph you had before, unchanged.

**Skin finish.** A 1x detail model can now run over an H3 still on its way out
of the render - skin, hair and fabric texture added at the same size, nothing
enlarged and nothing repainted, for a couple of seconds. It measured between
+80% and +220% more fine detail across a whole session of frames. It is a
switch on the Image tab rather than a default, on purpose: those frames were
also being downscaled by half afterwards, which is what buries the slightly
uniform texture it adds, and nothing here does that. Worth turning on and
judging at full size. Greyed out honestly when the file is not installed.

**The three LoRAs that won, as switches.** digicam, GalaxyAce and relim now sit
in the H3 still stack at 0.2 each. Each was picked by eye at full strength, and
a third of each turned out to render a look that is none of their house styles.
All off by default; nothing changes until you turn one on.

**Hybrid H3 builds are preferred, and say what they are.** Stock ref2va is the
degraded build - its own author documents training issues that affect quality
even outside reference work - and an fl2va/ref2va hybrid beat it on skin
texture, hair and fabric with identity intact on every comparison. If you have
one, the reference still opens on it. If you pick something else, that wins.
Hybrids no longer sit in the model list labelled as anonymous community
finetunes.

**Pixal was naming one model and loading another.** Three lanes, all found in
one afternoon, by restarting onto the current build, asking the running app
which model a recipe would use, and then building the render and reading what
the sampler actually loaded.

Editing said FireRed and ran Qwen 2511. The picture was right - Qwen 2511 won
that comparison in August and is the better lane - but the panel named the one
that lost, so anyone reading Settings to find out what made their edit was
told the wrong thing.

The plain image lane was worse. It showed as ready and listed nothing missing,
and it could not render at all: the model it had settled on was a tiled
upscaler's decoder weights, a file that is not a checkpoint and had no business
in that list. Picking the lane and pressing render was the only way to find
out.

And the H3 reference still named stock ref2va in the panel while the sampler
loaded the hybrid.

Every one of them had a passing test agreeing with the bug, because the test
was asking the code the same wrong question the panel was. What they had in
common is the actual fault: two separate pieces of code answering "which model
does this recipe use", written months apart, drifting. There is one answer
now, and the panel and the sampler both read it.

**H3's two lanes get their own model settings.** H3 wants different weights
depending on the job - a reference render carries a character's photograph into
the scene, a first/last-frame render starts from a frame you give it - and
Pixal was choosing for you with nowhere to see the choice or change it.
Settings has a row for each now. If only one build on your disk can serve a
lane, that is the default. Pick another and your pick stands until you change
it. A hybrid build does both jobs, so it appears in both rows. Each row names
what Automatic currently resolves to rather than leaving you to guess, and a
pick whose file you later delete says so and quietly falls back until the file
returns.

**Signs get spelled or they get cut.** Naming a sign without its words is the
fastest way to give a picture away: "a chalkboard price sign" came back
lettered with confident nonsense. Pixal now removes a sign from a caption when
the caption does not say what it reads, and leaves it completely alone when it
does. Two short words is the length that survives.

**The prompt writer was taught the wrong thing about light, and has been
corrected.** It had been told to light a subject from lamps inside the frame.
An entire ten-shot set built that way was thrown out - including three frames
picked as favourites an hour earlier - because a fixture in frame with the
room gone black is a lit set, not a photograph. It now asks for ordinary light
from out of frame and a room that stays lit. It also has a word budget, and
knows to write the moment rather than the expression.

**...and it was being told that somewhere it could not win.** The writer reads a
block of general photo rules before it reads the ones for the recipe in hand,
and on three points the general block said the opposite: sixty to a hundred and
thirty words against about forty-five, one named light source against no fixture
in the shot, and name the shoes against a frame that stops at the waist. A
writer cannot follow a brief that argues with itself, so the three rules that
decide this lane are now restated once, together, right after the general ones
they overrule - and after a model maker's own prompt too, when official
prompting is on.

Asked directly, with everything else held, the writer does noticeably better on
all three: captions came back about a quarter shorter and stopped naming lamps
and strip lights almost entirely. Two things came out of getting there and both
are worth writing down. Rules phrased as prohibitions - "not 60-130 words",
"name no lamp or neon" - bought nothing at all, and one caption came back
reading "the taxi interior glows with warm ambient light from above, but no lamp
or bulb is visible": the writer had copied the rule into the picture as a
negation, which this model family cannot represent. Every rule is now a thing to
do, and a test keeps it that way. And putting the block at the very end of the
prompt - the obvious reading of "obeys the last rule it read" - was wrong; the
end is where the rules about *when* to render live, and a writing rule stranded
past them is cut off from every other writing rule.

**The writer was reading its own rejected drafts back to itself.** This is the
big one, and it had been quietly spoiling every chat render for a while.

When you ask for a picture, Pixal's writer occasionally answers with the scene
written out as a chat message instead of actually rendering it. That has always
happened, and saying "render it" queues it, so it looked harmless. It was not:
those unrendered drafts stayed in the writer's context forever. Six asks in,
the model was being handed seven copies of its own earlier replies - and it did
what a language model does with seven examples in front of it. It copied them.
It answered in prose because its last four "replies" were prose. It matched
their length, so captions ran to a hundred and fifty words. And it reproduced
its own wardrobe word for word - the same crop top, the same shorts, the same
boots - in a laundrette, on a night bus and on a kerb, none of which had asked
for any of it. At that caption length the waist-up instruction stops being
obeyed too, so the pictures came back full length as well.

Pixal already had a filter for exactly this, and it had a blind spot: it only
recognised a written-out scene once you had ACCEPTED it. The ones you ignored -
most of them - were invisible to it. Now they are dropped too, and the draft
stays in view only on the turn that actually uses it: "render it" accepts it,
"make her jacket red" edits it, and a brand new ask gets a clean slate.

The same ask, before and after: a hundred and forty-eight words of recycled
wardrobe, versus ninety-four words of the scene you actually asked for, with
the render fired directly instead of needing a nudge. The picture went from a
posed full-length shot in boots to someone genuinely asleep on a bus.

**What is still not fixed.** Captions run around seventy to ninety words rather
than the forty-five the lane wants, so there is more to win here. The writer
still answers in prose sometimes, and when it does, "render it" sends that chat
message to the sampler as-is - mood paragraph and all - which is worse than the
failure it recovers from. Both are written up in the notes with the numbers, so
the next pass starts from evidence.

**Character references are not just accessories.** The slots beside a
character's identity photo always took any photograph; calling them
"accessories" hid what turned out to be the single biggest fix of that
session. A second person in frame renders badly no matter how well she is
described, because a description is not the identity mechanism - the wired
photograph is. Same feature, honest label.

**The ComfyUI window shows the queue.** It could tell you a render was
sampling, but not that three more were waiting behind it, and it went quiet
during the minutes a job spends loading weights, encoding and decoding. It now
says how many are waiting and shows a job as working when it is alive but not
sampling.

**A guide for Claude Code.** A `CLAUDE.md` ships with the install: how to drive
Pixal headlessly, the endpoints, and the handful of rules that were expensive
to learn - free the card before a batch that changes checkpoint, never write
config.json from PowerShell, put the settings in the filename.

**Saved styles say which model they run on, and which one you are on.** The
shelf listed every style with its lane, so fourteen of them read "Realism" and
nothing told you which was the MiniMax one. Picking a style *sets* the model,
so the model is the fact that separates one from the next - it is now what each
row is tagged with. Tiny pills filter by family and open on the family you are
already using, with a labelled break between each group. The other families
stay one click away rather than being hidden: choosing a style is how you
change model, so a shelf filtered to your current one would be a shelf you
could never leave.

**And a MiniMax style is selectable with a character picked.** It was greyed
out. The rule it hit is the identity patch, which only Krea 2 builds carry -
but MiniMax H3 needs no patch, because the character's photo rides H3's own
reference input, and it was exempted from that rule everywhere except here.
Selecting one also used to drop the character, which is the whole subject of a
reference render. Both fixed.

**Every picker shows what is selected.** The selected row was marked by
recolouring its label and nothing else, which is invisible in a long list. It
now fills, with an accent rail down its edge - the same treatment the pills and
toggles in the same bar already used. Model, style, character, size: all of
them.

**"Can you do one of her..." renders it.** It used to answer with a written
scene and ask you to say go. "Can you *make* one of her in the kitchen" fired
immediately - one verb apart, and the difference was that "do" was not on the
list of words that mean render, so the turn was filed as conversation and the
render tool was withheld from it. "Do" now counts when it is followed by a
person or a picture - one of her, one where she is, some close-ups - and stays
conversation in front of anything else.

**Drop a preset into `recipes/` and it appears.** Saved styles were read once
at startup, so a new file, an edit, or a delete needed a restart before the app
agreed it had happened. The folder is now checked when something asks, and a
broken file is reported by name with the reason instead of vanishing quietly.

**Skin shine removal.** Specular highlights on skin - the hot spots on
foreheads, cheeks and chests - pulled down toward the tone around them. It only
ever darkens, it adds no texture at all, and eyes and teeth fall outside the
range it works in, so it leaves them alone. It costs nothing: no model file, no
VRAM, no extra node. Off by default, on the Image tab beside the other
finishing controls, and it runs before any upscale model rather than after.

**The MiniMax text encoder is a setting.** H3 loaded a 14.6 GB text encoder
with no way to change it. The smaller 4B and 8B encoders now stand in for it
through their projection files, several gigabytes lighter and faster, at some
cost to how reliably a face comes back - so it is a switch you own rather than
a decision baked into the source. Automatic is the big one and renders exactly
what it rendered before. An option only appears when both its files are on
disk, and a pick whose files go missing quietly runs Automatic. It sits with
the two H3 model slots, under MiniMax H3 on the Image tab.

**Known-good sampler settings, one click.** The sampler card offered
"recipe / model / custom", and "model" - the settings a model's own page
recommends - has never once been clickable on Krea 2 or MiniMax H3. Three of
the fifty-one models here publish a recommendation line and all three are
Z-Image. Krea 2's sampler menu is 182 names long, which is not a list anyone
picks a good one out of. So the card carries a row of known-good pairs now, one
click each, setting sampler, scheduler, steps and eta together. H3's three are
what was measured here at a locked seed: Detail, about 74% more fine detail;
Speed, about 35% quicker; and the top pair from a 3,504-vote community table,
which carries a warning rather than a crown, because in both of our rounds it
pushed the subject off a wall the caption had pinned her to. Krea 2's three are
RES4LYF's published figures for the Qwen-Image family and say "not measured
here" on their face, so nobody later reads them as ours. Hover a pill for where
its numbers came from. A pair the current sampler node cannot run is never
offered.

**A busy model provider no longer lands in the chat as raw code.** When a
hosted brain was at capacity, the chat printed the service's own error object,
braces and all. It now says what happened in a sentence - and, because that
particular failure is one nobody can act on and one that clears by itself,
Pixal waits it out and tries again before saying anything.

## 1.1.3b — never published, folded into 1.1.4b

Your character gets a page worth using, H3 stills stop carrying forty words that
never did anything, and the Klein edit lane can finally reach the LoRAs sitting
in your folder.

**The character page, redesigned.** The form that defines a character was a
stack of boxes; it is now laid out like something you would actually sit and
fill in, with the identity photo where your eye goes first and the fields
grouped the way you think about a person rather than the way they are stored.

**Characters can carry their things.** A character can hold reference
photographs of the objects that belong to them - a jacket, a bag, a pair of
glasses - and H3 wires each one into the render beside their identity photo,
every accessory with its own description. Switch one off for a single render
without editing the character. A described object is a guess; a wired
photograph is the object.

**H3 stills stopped shouting at the model.** Every H3 still used to end with
forty words about HDR, low noise and punchy colour - a description of what a
phone does to a photograph after taking it. Rendered with and without, at the
same seed, the two are the same picture: the clause was occupying the strongest
position in the caption and doing nothing with it. It is gone. What now sits
last is the wardrobe, which is the clause that actually matters - this model
family will undress a subject when the last thing it reads is her body, and the
old order had a framing note landing after the lock. That was a real bug and it
is fixed.

**The Klein edit lane takes LoRAs.** Around thirty Klein LoRAs can sit in your
Flux folder and the masked edit lane could reach none of them, because of one
function signature. It can now, and the Enhanced Details LoRA is offered as a
switch on the edit popup when you have the file - at the strength that was
measured, not the author's suggestion. Turn it on and sunglasses stop rendering
as flat black holes with the eyes gone. Leave it off and your edits render
exactly as they did before, to the byte.

## 1.1.2b — 2026-08-28

Your character sits for MiniMax H3, every render you own becomes a recipe, and
Pixal stops running your graphics card to the edge.

**Your character sits for MiniMax H3.** Pick one of H3's reference builds with a
character anchor active and the still is built from their photograph - the
reference image goes straight into the model's own reference input. No identity
LoRA, no edit pass, nothing that thins out as the canvas grows: the likeness
comes from the picture, at 1536x2048, in about a minute. H3's other builds are
pickable under a character too; they work from the written description. Until
now a character greyed out every model that was not Krea 2, which is why H3
looked locked away.

**H3 opens up to LoRAs.** Style LoRAs sitting in your MiniMax H3 folder now
appear for H3 stills and ride the model the way they do everywhere else. The
turbo and step-count distills stay out of that list on purpose - they are speed
modes for the video lanes, the still lane is the quality path, and the picker
says so instead of quietly halving your steps.

**Stills sample at the setting that won.** Four sampler and scheduler pairings,
one locked seed, judged side by side at full size: dpmpp_sde_gpu with beta took
it, and it is the H3 still default now. The video lanes were not in that
comparison, so they keep what they had - a still-only verdict has no business
re-tuning your clips. Your own sampler settings still override both.

**Every render you own is a recipe.** ComfyUI writes the entire workflow into
every PNG it saves, and Pixal reads it now. "from image" in the style picker
turns any render - yours, or one somebody posted - into a style draft: model,
LoRA chain, sampler, scheduler, steps, canvas, and the prompt that made it. It
never saves behind your back, and it names what it could not map rather than
filling in a default and hoping. A model you do not have stays on the draft, so
the save refuses and tells you why.

**A style can ask you a question.** Saved styles carry fill-in slots now, so a
style that is really a formula stops being a file you edit. The new Cosplay
photo style ships with two - who is in the shot, and what they are wearing - and
that second one earns its keep: the captioner formula behind this style has a
habit of forgetting clothing when nothing insists.

**Pixal stops running your card to the edge.** The chat brain holds several
gigabytes of video memory, and until now Pixal only put it down when the
arithmetic said the render would not otherwise fit - arithmetic priced from
constants that were routinely wrong. Thirty-eight of the last fifty renders
finished with under 2 GB free. Now the brain steps aside whenever keeping it
would leave the card under four gigabytes of room, and a render is priced from
what your own renders actually used rather than from a table. A brain that a
*different* Pixal install started can be put down too - before, it sat there
holding about 7 GB nothing could reclaim. Windows never refuses a render for
want of memory; it pages, and everything crawls.

**Your settings survive a model switch.** Move between MiniMax H3 builds and
your custom sampler, scheduler and steps come with you instead of snapping back
to the recipe's.

**One dropdown, and it fits on the screen.** The sampler card's scheduler list
opened inside its own card and was sliced off at the edge, leaving nothing to
click. Dropdowns now open above the page and flip upward near the bottom of the
window. Settings' chat brain and both edit-model pickers use that same
searchable dropdown instead of two more of their own.

**Selfies animate as selfies.** Animating a Selfie Cam still could still come
back as a tripod shot watching somebody hold a phone: the brief only had to
contain the word "selfie" to pass as honouring the note that the camera IS the
phone. Saying "a selfie" is not saying it, and a brief that writes the phone as
a prop besides - held, tapped, glowing on a thigh - now has the note put back
into it.

## 1.1.1b — 2026-08-27

MiniMax H3 takes stills, and the chat writer learns from Krea's own playbook.

**MiniMax H3 is an image model now.** Pick any H3 build in the model shelf -
they sit in their own "MiniMax H3" folder - and a still renders at the
model's native 2K: the video model run for one frame, kept at its floor of
five frames and the first frame saved. About a minute warm on a 5090, the
best skin texture in the app. The canvas tops out at 3.1 MP (the model's Max
tier); rungs above it on the megapixel ladder say so. Reference-video (ref2va)
builds stay with the Animate lanes.

**Refined on an H3 build is a 2x latent refine.** The same still, then its
own latent re-sampled at 2x through the 3D latent upscaler - lashes and pores
at 3072x4096, and distant faces in full-body shots come back sharp. About
three minutes. It needs the MMH3 pack and its upscaler weights; without them
the pill says what is missing.

**Official prompting.** Settings → Brain has a new switch, on by default: the
chat writer writes scenes the way the model's makers recommend - Krea 2's own
expansion prompt on Krea 2 recipes - instead of Pixal's photo-craft rules. A
same-seed comparison through the real chat on fresh asks went the official
way on three of four shots, including every render Jesse picked. Off is the
old writer, unchanged. Each render records which writer produced its scene.

**The writer stops copying the last scene.** Switch directions in a thread
and the new ask no longer inherits the previous render's wardrobe and
setting. The local brain writes most scenes as prose the server then queues;
those were invisible to the writer's history filter, so seven copies of one
outfit out-voted every new idea. A queued prose scene now counts as a render
and leaves the context on a fresh ask.

**Prompt enhance off with a character anchor** means what it says: the anchor
drives the identity graph, its reference photo is no longer attached to the
chat turn as an image, and your typed prompt is the positive prompt - no
brain round-trip, no "[reference image]" leaking into the scene, no error
after it.

**Scenes are tidied before they render.** A small local brain writes things an
image model cannot use: "no crowd, no sky" (an encoder has no negation - it
draws the crowd), stray tool fields, and sentences about the scene instead of
in it ("this moment captures…"). The server now removes those from a
brain-written scene before it reaches the sampler, keeps the positive
remainder, and records what it tidied on the job. Your own words with Prompt
enhance off are never touched.

**The identity Build dial works.** Full / r128 / r64 could be seen but not
switched: the store rejected string-valued choices. Fixed.

**Flat surfaces.** No drop shadows on panels, toggles, segmented controls or
sliders; the chat surface sits flush at narrow widths instead of floating as
a boxed card, and the chats drawer dims the whole window behind it. The
prompt box pads its text by the real width of the icon cluster in its
corner, so typing never runs under the attachments.

## 1.1.0b — 2026-08-26

Every recipe opens its sampler, and H3 gets three new knobs.

**A Sampler card under the recipe card.** Closed, it states the schedule the
render will run at (`linear/euler · simple · 8 steps · cfg 1`). Open, it
offers the sampler, scheduler, steps, CFG and - on RES4LYF seats - eta, for
this render only, with the recipe's own number one click away. A "model"
preset applies the settings from the model's own page when it has any. What
ran is recorded on the job card and in history, and "Save current" carries
the override into a style. Picking another recipe or style starts clean.

**Every recipe has one.** Realism, Identity Edit, Anime, Fantasy, Z-Image
Base and Turbo, Qwen Image, Anima - and Realism II, where it tunes the first
pass (the 2-step refine is what "refined" means and stays put). CFG is
greyed at 1 on distilled builds, with the reason.

**ComfyUI's own samplers on the Krea 2 recipes.** The sampler menu lists
RES4LYF's family first and the stock KSampler's (`er_sde`, `dpmpp_2m_sde`,
`res_multistep`…) under its own label; picking a stock one runs a stock
KSampler in that seat for the render. Eta does not apply there.

**The H3 rows explain themselves.** The model row says what FL2VA and REF2VA
are; the 2x row is a switch, off by default, with a tip that says what native
2x does and what it costs.

**Small fixes.** Recipe sublines state steps, not seconds (a second count
was only true on one machine). A slider at its minimum no longer clips its
handle. An open dial drawer in the LoRA chain pushes the rows below instead
of drawing over them. The style editor's sampler menus fill without Settings
having been opened first. The model picker and the sampler menus share one
dropdown.

**H3 renders at Standard, High or Max natively.** A Resolution row in
the Animate popup: Standard is today's canvas (about 1 MP), High about
1.8 MP, Max about 3.1 MP (1536×2048 on a 3:4 still). The detail comes from
the model itself, not an upscaler - the skin-and-hair difference is visible
at 1:1 - and the row's hint names the exact canvas the picked still will
get. The big tiers are slow (a 10 s Max clip is about 20 minutes on a 5090)
and re-frame the shot a little. The 2x row below is now the budget option;
both can be on at once. Settings → Video → "H3 resolution" sets the default
the popup opens on.

**A clip can finish at 30, 48 or 60 fps.** The clip finisher's frame-rate
option interpolates with RIFE 4.9 in the same pass as RTX VSR, so fps and 2x
land together. Audio is copied untouched and the duration holds, so lip
sync survives; non-multiple targets are interpolated then decimated.

**Long clips through the 2x row stay clean.** A 5 s+ clip re-sampled as one
temporal block grew a sparkle lattice in dark regions; the row now
re-samples in anchored 51-frame chunks (17-frame overlap) and the lattice is
gone. Clips that fit in one chunk are untouched.

**The identity patch's build is a dial on its card.** Full / r128 / r64 -
the author's weights and the two rank reductions, near-identical likeness,
smaller and faster to load. Each option's size on disk rides its tooltip.
Untouched, the card renders exactly today's graph; a box that owns only one
build runs that one.

**A style can carry a negative prompt and a prompt tail.** Two optional
fields in the style editor, under the sampler block: Negative is what the
sampler steers away from (it only does anything above cfg 1); Prompt tail is
appended after the caption as the closing clause, after the wardrobe lock. A
style with a negative encodes it with a real CLIPTextEncode in place of
Realism's zeroed-out conditioning - without one the graph is exactly what it
was. Both are recorded in the job's receipt.

The first style built on them is *Phone photo*: stock Krea 2 turbo
(`krea2_turbo_int8_convrot`), no LoRAs at all, 14 steps, cfg 1.2, 9:16, the
negative `Bokeh. Shallow depth of field. Professional photo. Background blur.
Blurry. Illustration. DSLR photo. Film photo. Film grain.` and a tail asking
for a sharp, high-contrast smartphone photo. On a locked-seed A/B the LoRA
stacks read waxy next to it. It needs the Krea 2 turbo checkpoint, so it is a
recipe to save yourself rather than a shipped starter.

## 1.0.10b — 2026-08-25

Pixal manages the card, and says what it did.

**A Clean up section in Settings.** Under "this machine": Free VRAM, Free
brain, Free RAM, Reset desktop, and Free all. Each button reports the
gigabytes it actually gave back. Reset desktop restarts Explorer and the
Windows compositor (which quietly hoard video memory) behind an admin
prompt. "Brain idles after" lets you choose when the chat brain unloads.

**The butler watches the whole card.** Before a render that will not fit,
Pixal now frees weights no recent job used, rests the chat brain if that is
still not enough, and names the desktop when it is the one holding memory -
each with a short line saying what it did. A render that still ran on a
full card says so, with how much slower it was than usual.

**An undistilled Klein runs at its own pace.** A Klein build that is not
step-distilled (Flux2 Klein 9B True) now samples at 20 steps instead of the
distill's 4, and the job card says so. Expect about five times longer.

**Settings buttons read like buttons.** Every choice and action in Settings
starts with a capital letter. Headings and field names are unchanged.

**Small fixes.** The canvas popover no longer jumps when you pick a size in
a windowed Pixal. Chat no longer repeats a scene twice on one turn. A
character can optionally get a neutral-wardrobe reference (off by default:
in testing, the plain tee leaked into scenes as much as the original outfit
did - a tight head crop is still the best reference). The installer's tidy
step works on case-sensitive drives.

## 1.0.9b — 2026-08-25

Edits keep their skin, and Pixal shows you what you own.

**Klein 9B now edits the whole frame.** Whole-frame edits used to run on
Qwen, which smooths real skin into plastic. Pick a Klein build as your edit
model in Settings and "change her earrings" keeps pores, hair and fabric
intact - and finishes faster. Klein already handled masked edits; now it
handles both.

**A Models tab in Settings.** Every model you have installed, grouped by
family, with how much disk it takes and which lanes can use it. A model that
is too heavy for your card is flagged, not hidden. The number at the top
tells you how many of your LoRAs Pixal cannot use yet.

**Video dialogue sounds right.** No stray noise before the first word, no
"I says", and no line repeated to fill the clip. There is a natural pause
before speaking and after. Animate a selfie and it stays a selfie.

**Re-roll uses everything you have set.** Rolling a card again with a
character, LoRA changes or dials now applies them, instead of replaying the
card's old settings.

**Identity dials are sliders.** Likeness and Grounding are snapped sliders
under the LoRA they belong to. Adding a LoRA is one clean panel. The glass
logo from the website is in the app.

**Memory comes back when you ask.** "Free brain" works again (a restart had
put the brain out of its reach, and idle unloading with it). A second video
clip no longer reloads 25 GB. Trimming no longer clears ComfyUI's cache.

**Small fixes.** The character preview updates when you re-crop. The
installer puts the vision projector next to the brain so chat can see
images. A caption starting with "This" renders instead of being treated as
chat. The edit dialog zooms to the flaw; hold to compare with the original.

## 1.0.8b — 2026-08-24

Pixal stops keeping models to itself, and stops talking in code.

**Both edit lanes name their model.** Editing has always had two lanes — an
instruction edit that rewrites the whole frame, and a masked edit that redraws
only what you painted — but Settings offered a picker for one of them. The
masked lane was pinned to a single build while other compatible ones sat
installed and unreachable. Settings now names both, "whole frame" and "masked
area", and every option says what it weighs on disk; a build heavier than your
card says so in its tooltip rather than being hidden or blocked.

**An anime shot is called an anime shot — this time in the chat too.** 1.0.7b
fixed the render card and told the writer to say it. The writer kept saying
"realism" anyway, because the render tool's own receipt hands it the graph's
name in the last thing it reads before speaking. The correction now travels
with the receipt, and a repair behind it makes sure: on a directed render, the
look you asked for is the word you get.

**Pixal does not speak in ids.** "identity_edit" is not English, and neither is
"rendering klein_inpaint - this takes a moment", which is what the waiting line
said for any recipe without hand-written wording. Every internal name is spoken
as its label now, everywhere the app talks.

**Info bubbles stay on screen.** A tip on a low row ran off the bottom of a
windowed Pixal — the position was clamped sideways and not at all vertically.
Tips now flip to whichever side has room, and never leave the window.

## 1.0.7b — 2026-08-24

The chat brain stops going blind, and Settings stops describing itself wrong.

**Your brain keeps its eyes.** If Pixal lost track of a local brain it had
started — its record on disk gone while the model itself was still loaded and
answering — it treated that brain as somebody else's server and used it as-is.
Every part of Pixal that asks "can this brain see?" reads that record, so a
brain without one was blind for the rest of the session: images you attached to
chat were flattened to "[attached image]", and asking for a look at a frame
fell through to the big ComfyUI reviewer, loading a second model to do a job
the brain could already do. Pixal now recognises its own brain by the model it
is serving and re-registers it, running the same vision check a fresh start
gets — so the eyes come back instead of quietly staying off.

**Settings names the model that actually reviews your images.** The Vision
section was a ComfyUI model picker titled "Image reviewer", which read as
though that model does the reviewing. It does not. Whenever your chat brain has
working vision it reviews directly, and the picker is only the fallback for a
brain without eyes. It says so now — "Fallback reviewer", with the brain
named — and when the brain cannot see, it tells you why.

**An anime shot is called an anime shot.** Krea 2 has no anime graph, so
choosing Anime runs the photo recipe with the anime direction folded into the
writing. That is the right thing to run, and the render card then threw the
choice away: a cel-shaded picture came back labelled "Realism", and the chat
called it a realism shot. The card now names what you chose and keeps the
recipe in its tooltip, and the brain calls the render what you asked for.

**Plainer words.** The upscaler says **Upscale** where it said "Enlarge", and
asks you to choose a local upscale model. The section that was called "PiD
finish" is now **VAE decode**, which is what it is — and its tip explains what
the setting swaps, and that it only ever applies to Identity Edit renders.

**Pixal gets its own taskbar button.** Pin Pixal and you got Chrome's icon;
open it and a second, blurry button appeared beside the one you pinned.

Pixal opens its window through Chrome, and Windows decides which taskbar
button a window belongs to by an identifier the window carries. Chrome's
window carried Chrome's. The shortcut you pinned carried nothing, so the two
could never be the same button — no icon setting could have fixed it. Both now
carry the same identifier, so the window lands on the button you pinned,
wearing Pixal's icon. Nothing to install and nothing to click: it is true from
the first launch.

The desktop shortcut also pointed at a script, and Windows will not pin a
shortcut to a script — dragging it to the taskbar did nothing at all, with no
error to say why. It points at Pixal.exe now.

And the "install it as an app" button could not install anything: Chrome offers
that prompt once, very early, and Pixal was not listening yet, so the button
only ever opened another tab. It catches the offer now and asks properly — and
when Chrome is not offering one, it says so instead of opening a tab that
cannot help either. Installing as an app is optional now; the taskbar is
correct either way.

If you pinned Pixal from an earlier version, unpin and re-pin it once to pick
this up.

**Two things that were simply wrong.** The Video model dropdown painted behind
the rows underneath it. And every info tip in Settings sat a couple of pixels
above the text beside it — in all of them at once, which is why it read as a
tilt rather than a typo.

## 1.0.6b — 2026-08-23

MiniMax H3 renders about a third faster, and you can prove it yourself.

**Sparse attention.** If the H3 sparse-attention pack is installed, Pixal now
uses it on every H3 render — first frame, multi-shot and reference lanes alike.
On this machine the same clip, same seed, one node different, goes from 7.24 to
5.40 seconds a step: **1.34x**, or about forty seconds off a five-second take.
It is on by default, because a speed-up you have to go and find is a speed-up
most people never get.

The Animate dialog gains an **attention** row, sparse or dense, so you can
render the same shot both ways and judge for yourself — that is what the dense
setting is for. The row only appears if the pack is actually installed; Pixal
does not offer a switch that cannot do anything. Sparse attention turns itself
off on short or low-resolution clips, where it would not help, so it costs
nothing there.

Which one ran is recorded with the render, alongside the sampler and the seed.

**And H3 clips can now finish at twice the size.** A new **2x upscale** row in
the Animate dialog re-samples the clip you just rendered at double the canvas —
928x1120 becomes 1856x2240, four times the pixels — with the audio carried
through untouched. It is not a resize: the model re-renders the detail, tile by
tile, so peak memory stays where a single tile puts it and a 4 megapixel clip
fits on a card that could never render one in a single pass.

It is off by default, and the row tells you why: it takes about three times as
long as the render alone. It also runs *inside* the render rather than as a
button on a finished clip, because the upscale needs the raw latent the sampler
produced and that is gone once the video is written.

The first frame gets sharpened by your own configured image upscaler before the
2x pass anchors to it. If you have not set one, it still works — the anchor is
just softer.

---

## 1.0.5b — 2026-08-23

LTX 2.5 stops running out of memory, 28 LoRAs that were being silently thrown
away come back, and the interface stops snapping open.

**LTX 2.5 renders finish.** A clip could sample for forty minutes and then die
in the last step, decoding the frames — the part that happens after all the real
work is done. The decode was being asked for the entire clip in one piece:
Pixal shipped the maximum chunk size on both LTX templates, which handed the
decoder 512 frames at once where 8 was the intended amount. It now decodes in
chunks. And if a decode does run out of room, Pixal turns *the decode* down and
retries, instead of shortening your clip — which threw away sampling that had
already succeeded and changed nothing about the step that actually failed.

**28 LoRAs come back.** Pixal had two separate lists of model families written
by hand, and they disagreed: one knew six families, the other knew two. A LoRA
belonging to a family only the first list knew about was marked "unknown", and
anything unknown gets dropped before the sampler — so it was pickable, it looked
fine, and it did nothing. Families are one table now, and both lists read it.
Klein LoRAs work. Qwen ones work. Adding support for a new family is adding a
row rather than editing code in two places and hoping.

One file changed family, and it is the whole argument: a LoRA sitting in your
Krea 2 folder turns out to declare Flux 2 Klein in its own header. It had been
going into Krea 2 identity chains on the strength of the folder it happened to
sit in. Pixal now believes the file over the folder.

**Your LoRAs wear their own covers.** Pixal could already identify a model by
its contents and fetch its name and artwork — but only for checkpoints. LoRAs
got nothing. On a 415-file library that is 254 covers where there were 220, and
414 real names where there were 397. Because it identifies files by their
contents, renaming one costs nothing: a LoRA you renamed matches exactly as well
as one you left alone. A cover or metadata file sitting next to a LoRA always
wins and skips the lookup entirely.

Also fixed: a LoRA whose file carried no title was remembered as *having* no
title, permanently, and never looked at again. 162 of them were stuck that way.

**The add-LoRA panel is a panel, not an essay.** It opened with a two-line
paragraph explaining itself, then a line restating the same thing in different
words. Both are gone, replaced by `Krea 2 · 107`. The search field has a search
icon and the word `Search`, instead of a sentence too long to fit. Names get two
lines and keep their ends, which is where community LoRAs put the part that
tells them apart. There is a **list view** for when you know what you are
looking for, and anything added in the last week wears a **NEW** badge.

**Controls live on the thing they change.** The dials for Identity Edit sat in
their own "Advanced" fold, floating above the chain they act on. The fold is
gone: the filter-bypass switch is on the bypass card, and the recipe is now the
first card in the chain carrying Likeness and Grounding. Everything in the rail
is a card, every card opens to its own controls, and an override can never hide
inside a closed one.

**The ratios show their shape.** Eight numbers in a grid is arithmetic. Each
aspect now draws itself, so tall and wide are something you see rather than
something you work out — and `3:2` versus `2:3` stops being a transposition you
have to read.

**Nothing snaps open any more.** Roughly twenty things in Pixal appeared and
disappeared instantly — every fold, every dropdown, every dialog, and the
caption and buttons that appear when you hover a tile in your history. They all
move now, on the same three timings, and all of it respects your system's
reduce-motion setting.

**Settings stops rearranging itself while it loads.** It reads eleven things
from your machine at once, and every control used to render collapsed and then
grow as its answer arrived, shoving everything below it down the page. Worse,
some of them *lied* on the way: Explicit content would show "auto" when your
setting was "on". A control that does not know its value yet now holds its final
size and says nothing, rather than guessing.

**Pixal tells you when there's a newer Pixal.** Settings → About shows the
version you are running and the latest released one, with a link when they
differ. It checks quietly, remembers the answer for hours, and if there is no
internet it simply says nothing — no error, no nagging. Updating replaces only
Pixal's own files; your recipes, characters, styles, settings and history are
untouched.

**Fixes**

- Picking a **finetune** of FL2VA made the whole video LoRA chain disappear,
  with no error. Pixal was checking whether the model *was* FL2VA rather than
  whether it was *built on* it.
- A REF2VA render let you choose an end frame and then refused it on send.
  Reference models anchor identity, not frames; the option is no longer offered.
- The Animate model row was one flat list of every build. It splits into the
  base models and the finetunes of each.
- Thirteen help tooltips drew as near-black text on a transparent box —
  invisible. They render properly.
- The Identity Edit dials drew in two places at once when the chat panel was
  open.
- Models kept in subfolders classify correctly on Linux.

## 1.0.4b — 2026-08-22

New controls for likeness and for the filter bypass, a Settings you can actually
scan, and fixes for six things that were quietly wrong — two of them introduced
by the build before this one.

**Identity Edit's likeness is yours to set.** The two dials that decide how hard
an edit holds your reference were reachable only by the chat brain; there was no
way to see what they were set to, let alone move them. They now sit in a fold on
the recipe card. **Likeness** runs 0–10 and starts at 4, which is the model
author's own recommended starting point — and the useful half is *below* it, for
when a face is landing too exactly. **Grounding** balances edit strength against
identity; if you ever see duplicated or split compositions, lower it. Drag either
back to the recipe's own number and your override disappears.

**The 3-vector filter bypass is reachable.** Krea 2's bypass ships in two
versions that differ in how much of the text projector they move, and Pixal could
only ever load one — the 2-vector. If you have the 3-vector installed, it's now a
choice in the same fold. Pixal identifies them by reading the file itself rather
than trusting its name, so a renamed download still lands in the right place.

**Settings is organised by what you're making.** Image and video choices were
interleaved — the video engine under one heading, the video upscaler two
headings away, the image upscaler beside it under a name that fit neither. There
are now Image, Video and Brain tabs holding the choices for one kind of work
each. Choosing between an API brain and a local one is a tab now rather than
another pill, so it reads as the structural choice it is.

**Animate stops stalling on a download nobody asked for.** Before writing a
motion brief, Pixal looks at your start frame. That look is meant to run on the
chat brain — the reason the vision projector sits beside it — but when anything
went wrong it silently fell back to a separate 16 GB reviewer, and if that wasn't
on disk the node fetched it from the internet mid-render. Clicking Animate could
hang for minutes with no explanation. The look now stays on the brain, warms it
and retries if it was cold, and never triggers a surprise download inside a
render. Where vision is genuinely missing, Pixal fetches the small brain and its
projector instead — about 4.8 GB, with visible progress.

**Review, the same.** The Review button carried the identical hidden download.
It now tells you which reviewer is missing and what to do about it instead of
stalling.

**Re-roll now uses the settings you're looking at.** Changing the aspect ratio or
megapixels and hitting re-roll did nothing — the canvas never left the browser,
so the render came back at the size the original card was made with. Re-roll now
takes the live canvas, the same way it already took your LoRA strengths and
model. Edit and inpaint recipes still read their dimensions from the source
image, as they should.

**Pointing at a button on a gallery tile no longer makes it run away.** Hovering
a tile action made the row grow, which pushed the button out from under your
cursor, which collapsed it again — a flicker that repeated as long as you pointed
at it. The eight actions are now a vertical rail down the edge of the image,
where nothing can reflow underneath them.

**The chat brain isn't killed mid-answer.** Pixal releases an idle brain to free
your graphics card, but "idle" was measured from when a question *started*, not
whether one was still being answered. If you'd shortened the idle timeout, a slow
answer could have the brain shut down underneath it — which surfaced as a
connection error with no visible cause. Idle now means nothing in flight and
nothing recent.

**Models kept in subfolders work on Linux.** Pixal matched a model by path
without accounting for Linux's separators, so it handed ComfyUI a filename it
doesn't list and the render failed validation. This affected every model in a
subfolder, including all four starter styles. Windows was never affected.

## 1.0.3b — 2026-08-22

Pixal used to ship a style system with no styles in it. This build is mostly
about a fresh install being useful on a machine that isn't the author's.

**Styles you can actually run.** A new install's recipe folder was empty, so the
first thing Pixal asked a newcomer to do was invent a base, a model, a sampler
and a LoRA chain — the node soup you installed Pixal to get away from. Four
starter styles now ship with it: Everyday, Portrait, Widescreen and Anime Art.
They're built on models the setup already fetches, so they run on your machine
rather than describing someone else's.

**The style dialog opens on the render you're looking at.** Hit "new style"
while running Identity Edit and it opened on Anime, with a model list that
matched nothing you were using and a LoRA chain you'd never seen — and there was
no way to save the setup actually on screen. Character-based recipes were
excluded from being styles at all, so the form quietly fell back to the first
recipe in the list. A style can now name a character-based recipe and record
that it needs an anchor, picked when the style is used. If a recipe genuinely
can't be a style, the form says which one it moved to and why instead of showing
you a menu with nothing in it. It also stops clipping — the name field and the
save button stay on screen no matter how long the LoRA chain gets.

**Z-Image works.** Every Z-Image recipe failed at validation on machines that
keep their VAEs in folders — Pixal matched a file by its bare name, found one
belonging to a different model family, and handed ComfyUI a path it doesn't
offer. On a fresh install the two names happen to coincide, which is why this
shipped and stayed invisible. Pixal now resolves to the path the loader actually
lists, and an ambiguous name falls through to the next candidate instead of
poisoning the graph.

**Upscales are about ten times faster.** Upscaling anything under 1024px took a
staggeringly long way round: 26 sampling passes to reach 4096, via a 16k canvas
it then threw away. Measured on the same frame, same settings: 223s down to 24s
— and the result comes out *bigger* (4096 rather than 3328). A/B'd at 1:1 on
hair and skin, there's no difference worth the extra three and a half minutes.

**The chat brain stops sitting on your graphics card.** Setting the brain to CPU
wrote the setting down and left the running brain exactly where it was, on the
GPU, sometimes for hours. Changing the brain's model or placement now actually
evicts it — measured here at 12.6 GB down to 4.2 GB the moment it went. Beyond
that, an idle brain is now released after ten minutes rather than holding memory
until something else needs it. It only ever touches a brain Pixal started
itself; one you launched yourself is left alone.

**Animate a subject into a scene that never existed.** H3 ships two model
checkpoints and Pixal only ever loaded one. Picking a still now offers a choice:
animate that frame, or carry its subject somewhere new. The second is a
different task with its own prompt format, so it gets its own director rather
than reusing instructions that assume the composition stays put. Images only,
one reference, for now.

**Mouths stop moving after the words run out.** A spoken line with no stated
ending kept articulating past the dialogue, and that tail is where faces come
apart. Pixal now detects a line that hangs and spends one brain call closing it.

**Buttons at the end of a row stop disappearing.** The delete control on a
character anchor and on gallery tiles was being painted past the edge of what
the panel clips — present, but invisible. Both rows now stay inside their
container at every window width.

**A render that starts healthy and then crawls says so.** Pixal watches its own
step rate and notes when a job collapses mid-render, writing the numbers next to
the render in your history. Nothing acts on it yet; it's the measurement a later
build needs. A render that's uniformly slow from the first step is just a big
render, and won't trip it.

**Pixal no longer asks for a seat at Windows startup.** A leftover script could
add Pixal to your login items, which since a recent build also meant opening
ComfyUI's console at every login. It's gone.

## 1.0.2b — 2026-08-21

Pixal now lets you dial in a recipe's built-in LoRAs instead of just switching
them on and off.

**Softer likenesses.** Identity Edit's face LoRA used to run at full strength or
not at all. You can now pull it back for a lighter resemblance — useful when a
face is landing too hard and eating the rest of the image. The Krea vector
bypass is tunable the same way. Drag a stage back to the value the recipe
shipped with and your override disappears, so there's always a way home.
Anything you saved before this build is untouched.

**Fewer mystery slowdowns.** A render that started on a nearly-full graphics
card could crawl for minutes without a word about why. If the previous render
finished close to the edge, Pixal now clears out cached memory before starting
the next one — even if it looked like it would fit. It only trims what isn't
needed. It won't unload a model you're about to use again, and it won't touch
the chat brain to do it.

Pixal also started keeping notes on how full your card was when each render
began, next to what it expected to use and what it actually used. Nothing reads
those numbers yet. They're groundwork for a later build that prices renders from
what really happens on your machine instead of guessing.

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
