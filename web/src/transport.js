// transport.js — the wire between the chat store and the Pixal sidecar.
// REST for actions, one SSE stream for everything the server pushes
// (assistant text, thinking state, job lifecycle, progress, images).

const listeners = new Set();
let es = null;
let polling = false;          // switched on for good once SSE is judged dead
let pollSeq = 0;
let pollTimer = 0;
let sseWatchdog = 0;

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit(ev) {
  listeners.forEach((fn) => fn(ev));
}

// How long a silent SSE stream is given before we stop believing in it. The
// server seeds every new subscriber with a status frame immediately, so on a
// working connection the first message lands in milliseconds - local or LAN.
// Silence here does not mean "quiet studio", it means "nothing is arriving".
const SSE_FIRST_MESSAGE_MS = 6000;
const POLL_INTERVAL_MS = 1200;

// Polling exists because a never-ending HTTP response does not survive the free
// tunnels a remote session runs over: Cloudflare's edge buffers the stream and
// releases nothing, and localtunnel hands it the whole connection pool, so
// every image request alongside it fails. Short requests have neither problem.
async function pollOnce() {
  const r = await fetch("/api/poll?since=" + pollSeq, { cache: "no-store" });
  if (!r.ok) throw new Error("poll " + r.status);
  const d = await r.json();
  pollSeq = typeof d.seq === "number" ? d.seq : pollSeq;
  for (const ev of d.events || []) emit(ev);
  // The server lost our place in the ring. Tell the app to rebuild from
  // authoritative state rather than carry on with an invisible gap.
  if (d.resync) emit({ type: "resync" });
}

function startPolling() {
  if (polling) return;
  polling = true;
  if (es) { try { es.close(); } catch { /* already gone */ } es = null; }
  clearTimeout(sseWatchdog);
  const loop = async () => {
    try { await pollOnce(); } catch { /* server down - try again next tick */ }
    pollTimer = setTimeout(loop, POLL_INTERVAL_MS);
  };
  loop();
}

export function connect() {
  if (es || polling) return;
  es = new EventSource("/api/events");
  // If the stream opens but stays silent, it is being buffered by something in
  // the middle. Nothing will ever arrive on it, so stop waiting and poll.
  clearTimeout(sseWatchdog);
  sseWatchdog = setTimeout(startPolling, SSE_FIRST_MESSAGE_MS);
  es.onmessage = (e) => {
    clearTimeout(sseWatchdog);
    sseWatchdog = 0;
    try {
      const ev = JSON.parse(e.data);
      // Keep the poll cursor current while SSE is healthy, so a later fallback
      // resumes from here instead of replaying or skipping.
      if (typeof ev.seq === "number") pollSeq = ev.seq;
      emit(ev);
    } catch { /* malformed frame */ }
  };
  es.onerror = () => {
    // Disarm first: the pending watchdog would fire against a stream that no
    // longer exists and flip polling on - one-way by design - so the
    // reconnect below would no-op and the session would poll until reload.
    // connect() re-arms the watchdog itself.
    clearTimeout(sseWatchdog);
    sseWatchdog = 0;
    es.close();
    es = null;
    if (polling) return;
    setTimeout(connect, 3000);
  };
}

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

export const chat = (text, cid, opts) => post("/api/chat", { text, cid, opts });
// `seed` is the held lock (0 = free dice). `lock_seed` stays on the wire for a
// server that predates it, where it means "replay this card's own seed".
export const reroll = (id, cid, seed, loraPlans, model, aspect, mp, dials, opts) =>
  post("/api/reroll", { id, cid, seed: seed || 0, lock_seed: !!seed,
                        lora_plans: loraPlans || {}, model: model || "",
                        // absent, never "" - an empty canvas must not read as
                        // "the user asked for empty" server-side
                        ...(aspect ? { aspect } : {}),
                        ...(mp ? { mp } : {}),
                        // The recipe dials ride resolved (the override, or the
                        // recipe's own value), keyed by builder parameter just
                        // like the canvas; a recipe declaring none sends none.
                        // Choice dials (brief 9.15's bypass variant) ride the
                        // same spread.
                        ...(dials || {}),
                        // The composer's whole intent - the same body /api/chat
                        // gets - so the re-roll is the card's scene under the
                        // stack the user is LOOKING at (brief 9.42). A server
                        // that predates it ignores the key and the legacy
                        // fields above still say their piece.
                        ...(opts ? { opts } : {}) });
export const stop = (jobId) => post("/api/stop", { job_id: jobId });
export const animate = (id, cid, hint, seconds, engine, model, loraPlan, fps,
                        shots, script, speed, lastId, sparse, upscale, resolution) =>
  post("/api/animate", { id, cid, hint, seconds, engine, model,
    ...(loraPlan ? { lora_plan: loraPlan } : {}),
    ...(fps ? { fps } : {}),
    ...(shots > 1 ? { shots } : {}),
    ...(script ? { script } : {}),
    // a named recipe (steps + sampler + scheduler + distill LoRA); the server
    // still honours the old boolean `turbo`, which now means the 8-step one
    ...(speed ? { speed } : {}),
    // FL2VA bridge: a second render pinned as the clip's exact final frame
    ...(lastId ? { last_id: lastId } : {}),
    // Sparse attention is the server's default wherever the pack is on disk,
    // so the only thing worth sending is a refusal of it.
    ...(sparse === false ? { sparse: false } : {}),
    // 2x upscale is the opposite default: opt-in, because it ~triples the
    // render's time. It rides INSIDE the render job (it re-samples the
    // latent the sampler just produced), never an action on a finished clip.
    ...(upscale ? { upscale: true } : {}),
    // 9.55: the canvas tier H3 renders at natively. "standard" is the
    // server's own default, so only a real pick rides - an absent key renders
    // today's 1 MP canvas.
    ...(resolution ? { resolution } : {}) });
// 9.36: the brief WITHOUT the render. The body is animate's minus `script`
// and `cid` (the thinking notes are cid-agnostic in the lane), so the
// director writes for exactly the configuration the commit would send.
export const animateBrief = (id, hint, seconds, engine, model, loraPlan, fps,
                             shots, speed, lastId, sparse, upscale, resolution) =>
  post("/api/animate/brief", { id, hint, seconds, engine, model,
    ...(loraPlan ? { lora_plan: loraPlan } : {}),
    ...(fps ? { fps } : {}),
    ...(shots > 1 ? { shots } : {}),
    ...(speed ? { speed } : {}),
    ...(lastId ? { last_id: lastId } : {}),
    ...(sparse === false ? { sparse: false } : {}),
    ...(upscale ? { upscale: true } : {}),
    ...(resolution ? { resolution } : {}) });
export const review = (id, cid) => post("/api/review", { id, cid });

// Saved styles — user-authored recipes in recipes/*.json.
export const saveStyle = (style) => post("/api/styles", { style });
// 9.66: draft a style from an image's embedded ComfyUI metadata. The answer
// is a draft for review (style + mapped/unmapped + scene), never a save -
// the user still presses save in the editor, which is saveStyle above.
export const styleFromImage = async (file) => {
  const fd = new FormData();
  fd.append("image", file, file.name || "render.png");
  const r = await fetch("/api/styles/from-image", { method: "POST", body: fd });
  return r.json();
};
export const deleteStyle = async (id) =>
  (await fetch("/api/styles/" + encodeURIComponent(id), { method: "DELETE" })).json();
// Whether this base+model pairing has a tunable sampler at all, what values it
// accepts, and what it runs at today. One call because the answers depend on
// each other: a Z-Image seat exists only for models that keep the KSampler.
export const styleSampler = async (base, model) =>
  (await fetch("/api/styles/sampler?base=" + encodeURIComponent(base) +
               "&model=" + encodeURIComponent(model || ""))).json();
// `input` names a photo already in ComfyUI/input (an attached one); `id` names a
// finished render. Exactly one is needed - the server stages the render, the
// attachment is already where the graph reads from.
// `mask` is a white-on-black PNG data URL (white = edit here); the server
// bakes it into the staged copy's alpha and routes the edit to Klein inpaint.
// `reference` names a second image in ComfyUI/input (a logo, a product shot)
// the instruction can point at as "image 2" — whole-frame edits only.
export const edit = (id, cid, instruction, input, mask, reference) =>
  post("/api/edit", { id, cid, instruction, ...(input ? { input } : {}),
                      ...(mask ? { mask } : {}),
                      ...(reference ? { reference } : {}) });
// Stage a finished render's still into ComfyUI/input (no edit queued) so it
// can be picked like an upload — the character form adopts edit results this way.
export const stageInput = (id) => post("/api/input/stage", { id });
// fps (9.53) rides only when a caller sets one; omitted it falls to the
// Settings default, same as mode/scale which no caller sends today.
export const upscale = (id, cid, model, fps) =>
  post("/api/upscale", { id, cid, model, ...(fps ? { fps } : {}) });
export const histDelete = (id) => post("/api/history/delete", { id });

// The full anchor record (style, notes, wardrobe_lock, identity_ref) — more
// than /api/options carries, and what the edit form fills itself from.
export async function characterRecord(id) {
  const r = await fetch("/api/characters/" + encodeURIComponent(id));
  const data = await r.json().catch(() => ({}));
  if (!r.ok || !data.ok)
    throw new Error(data.error || `that anchor could not be loaded (${r.status})`);
  return data.character;
}

// What this anchor will actually bake into a caption. Rendered server-side
// through the same functions the builders call, so the form cannot drift from
// the render. Best-effort: a failed preview must never block editing.
export async function characterPreview(character) {
  const data = await post("/api/characters/preview", { character });
  return data?.ok ? { subject: data.subject, subject_ref: data.subject_ref,
                      wardrobe: data.wardrobe } : null;
}

export async function deleteCharacter(id) {
  const r = await fetch("/api/characters/" + encodeURIComponent(id), { method: "DELETE" });
  let data = {};
  try { data = await r.json(); } catch { /* non-JSON proxy/server failure */ }
  if (!r.ok || !data.ok)
    throw new Error(data.error || `character deletion failed (${r.status})`);
  return data;
}

export async function lane() {
  const r = await fetch("/api/lane");
  return (await r.json()).lane || [];
}

export async function history() {
  const r = await fetch("/api/history");
  return (await r.json()).entries || [];
}

export async function options() {
  const r = await fetch("/api/options");
  // A 403 from the access gate (expired key cookie) or a 500 still parses as
  // JSON, and adopting that body as the options payload is destructive: it has
  // no model_meta, so the store reads every saved pick as "unsupported" and
  // erases the model, the identity reference and the LoRA plan - into
  // localStorage. Throw instead, and the caller keeps the options it had.
  if (!r.ok) throw new Error(`options ${r.status}`);
  const data = await r.json();
  if (!data || typeof data !== "object" || !data.model_meta)
    throw new Error("options payload has no model catalog");
  return data;
}

export async function status() {
  const r = await fetch("/api/status");
  return r.json();
}

// The green dot's hover card: Pixal's node needs checked against this ComfyUI.
export async function comfyCompat() {
  const r = await fetch("/api/comfy/compat");
  return r.json();
}

export async function upload(file, kind = "") {
  const fd = new FormData();
  fd.append("image", file);
  if (kind) fd.append("kind", kind);
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  const raw = await r.text();
  let data = null;
  try { data = raw ? JSON.parse(raw) : null; } catch { /* handled below */ }
  if (!r.ok || data?.ok === false) {
    const detail = data?.error || raw.trim() || `upload failed (${r.status})`;
    throw new Error(detail);
  }
  if (!data?.name) throw new Error("upload finished without an input image name");
  return data;
}

// Re-label an image already in ComfyUI/input. The saved type is durable and
// independent of whichever picker tab happens to be active.
export async function setInputRefType(name, kind) {
  const data = await post("/api/input-ref-type", { name, kind });
  if (!data?.ok) throw new Error(data?.error || "the reference type could not be saved");
  return data;
}

export const imgUrl = (im) =>
  "/api/image?filename=" + encodeURIComponent(im.filename) +
  "&subfolder=" + encodeURIComponent(im.subfolder || "") +
  "&type=" + (im.type || "output");

// Lane/tile previews ride a bounded WebP (the same recipe the input
// thumbs already use) - a PiD 4x render is a 50MB PNG, and decoding those in
// the chat lane is what ate the framerate. The RAW file in output/ never
// moves: the lightbox and download always read imgUrl. Videos pass through.
// v= is the encode generation, not a cache key: previews are served immutable,
// so a quality change server-side needs a new URL or the old crush never heals.
export const thumbUrl = (im) => im.media === "video" ? imgUrl(im)
  : "/api/thumb?filename=" + encodeURIComponent(im.filename) +
    "&subfolder=" + encodeURIComponent(im.subfolder || "") +
    "&type=" + (im.type || "output") + "&v=2";

const inputRecord = (name) => {
  const canonical = String(name || "").replaceAll("\\", "/");
  const parts = canonical.split("/");
  return {
    name: canonical,
    filename: parts.pop() || "",
    subfolder: parts.join("/"),
    type: "input",
    mtime: 0,
  };
};

export const inputImages = (options) => {
  const records = Array.isArray(options?.input_images) && options.input_images.length
    ? options.input_images : (options?.inputs || []).map(inputRecord);
  return records.map((record) => ({ ...inputRecord(record.name), ...record, type: "input" }));
};

export const inputImgUrl = (record) => {
  const image = { ...inputRecord(record?.name), ...record };
  return "/api/input-thumb?name=" + encodeURIComponent(image.name) +
    (image.mtime ? "&v=" + encodeURIComponent(image.mtime) : "");
};

// Full-resolution input image through the /view proxy — the 192px input thumb
// is for tiles; cropping and mask painting need the real pixels.
export const inputFullUrl = (name) => imgUrl(inputRecord(name));
