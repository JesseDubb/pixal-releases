// store.js — the chat brain. Keeps the store shape of the chat widget this
// was ported from (conversations / inflight / progressMsg / sendChatMessage /
// stopGeneration / addConversation / removeConversation), backed by
// transport.js instead of the original pipeline. One conversation
// ("local") — a DM, not a mailbox.
import { useCallback, useEffect, useReducer, useSyncExternalStore } from "react";
import * as transport from "./transport.js";
import { prettyTemplate } from "./lib/names.js";

const CONV = "local";
const OPTS_KEY = "pixal-opts-v2";

const state = {
  conversations: { [CONV]: { id: CONV, messages: [] } },
  inflight: new Set(),
  thinkingMode: {},              // convId -> "thinking" | "working"
  progressMsg: {},               // convId -> string | null
  comfy: null,
  gpu: null,                     // { name, used, total, ram_used, ram_total }
  brain: null,                   // { mode, model, device, vision, nsfw }
  scan: null,                    // startup/rescan readout text while scanning
  history: [],
  options: null,
  opts: loadOpts(),
  railOpen: false,
  lb: null,                      // lightbox { images, idx, meta }
  settingsOpen: false,
  chatsOpen: false,              // left chat-list panel
  chats: [],                     // [{id,title,ts,n}] newest-activity first
  activeChat: null,
  themePref: loadTheme(),        // "dark" | "light" | "system"
  // job_ids on the card right now, oldest first. Sampling is GLOBAL — ComfyUI
  // is busy no matter which conversation is on screen — so the render-quiet
  // switch keys off THIS, never off the visible messages (switching chats
  // mid-render used to un-calm the UI and fight CUDA for the compositor).
  liveJobs: [],
};

function loadTheme() {
  try {
    const t = localStorage.getItem("pixal-theme");
    return ["dark", "light", "system"].includes(t) ? t : "dark";
  } catch { return "dark"; }
}

function loadOpts() {
  const defaults = { engine: "auto", style: "realism", quality: "standard",
                     model: "", aspect: "", mp: null, cinematic: false,
                     loras: [], lora_plans: {}, refs: [], character: "",
                     saved_style: "", dials: {}, tuning: {} };
  try {
    const saved = JSON.parse(localStorage.getItem(OPTS_KEY)) || {};
    const o = { ...defaults, ...saved };
    o.loras = Array.isArray(o.loras) ? o.loras : [];
    o.lora_plans = o.lora_plans && typeof o.lora_plans === "object" ? o.lora_plans : {};
    o.dials = o.dials && typeof o.dials === "object" ? o.dials : {};
    o.tuning = o.tuning && typeof o.tuning === "object" ? o.tuning : {};
    o.refs = Array.isArray(o.refs) ? o.refs : [];
    o.cinematic = o.cinematic === true;
    o.saved_style = typeof o.saved_style === "string" ? o.saved_style : "";
    if (!["realism", "anime", "fantasy"].includes(saved.style))
      o.style = o.engine === "anime" || o.engine === "fantasy" ? o.engine : "realism";
    if (!["standard", "refined"].includes(saved.quality))
      o.quality = o.engine === "realism_ii" ? "refined" : "standard";
    // Heal the doubled-prefix bug (the picker once re-prefixed an already
    // folder-relative path): "Krea 2\Krea 2\x" -> "Krea 2\x".
    while (o.model && o.model.startsWith("Krea 2\\Krea 2\\")) o.model = o.model.slice(7);
    return o;
  } catch {
    return defaults;
  }
}

function reconcileOpts(options) {
  const character = !state.opts.character || (options.characters || [])
    .some((c) => c.id === state.opts.character) ? (state.opts.character || "") : "";
  // A style deleted on disk (or in another tab) stops being a selection. Its
  // model and LoRA plan were already mirrored into opts, so letting go of the
  // label leaves the composer exactly as it looks - just no longer claiming a
  // preset that no longer exists.
  const savedStyle = savedStyleFor(state.opts, options) ? state.opts.saved_style : "";
  let healed = withExecutionRecipe({ ...state.opts, character, saved_style: savedStyle,
    loras: state.opts.loras || [], lora_plans: state.opts.lora_plans || {} }, options);
  // Belt to the transport's braces: only a payload that actually carries a
  // catalog may retire a pick. An empty model_meta means "not known yet", and
  // reading that as "unsupported" silently swaps the render to the recipe
  // default while the composer still looks right.
  const catalog = options.model_meta || {};
  const modelMeta = catalog[healed.model];
  if (healed.model && Object.keys(catalog).length && !modelMeta?.supported) {
    healed.model = "";
    healed = withExecutionRecipe(healed, options);
  }
  if (JSON.stringify(healed) !== JSON.stringify(state.opts)) {
    state.opts = healed;
    try { localStorage.setItem(OPTS_KEY, JSON.stringify(state.opts)); } catch { /* full */ }
  }
}

const hasIdentityRef = (opts = state.opts) =>
  (opts.refs || []).some((r) => r.kind === "identity" && r.file);

const recipeById = (id, options = state.options) =>
  ((options && options.recipes) || []).find((r) => r.id === id);

const modelSupportsRecipe = (name, recipeId, options = state.options) => {
  if (!name || !options) return false;
  const meta = (options.model_meta || {})[name];
  return !!meta?.supported && (meta.compatible_recipes || []).includes(recipeId);
};

const loraSupportsProfile = (lora, family, variant) =>
  !!lora?.supported && lora.family === family &&
  (family !== "zimage" || !["base", "turbo"].includes(variant) ||
    lora.variant === "any" || lora.variant === variant);

const LORA_PLAN_VERSION = 1;

// A saved style the server currently agrees is runnable. `available` is the
// gate on purpose: a style whose model was deleted must not silently route a
// render to a graph that cannot load it - it stays visible and greyed instead.
export function savedStyleFor(opts, options) {
  const id = String(opts?.saved_style || "");
  if (!id) return null;
  return ((options || {}).saved_styles || [])
    .find((s) => s.id === id && s.available) || null;
}

export function activeRecipeId(opts, options) {
  opts = opts || {};
  options = options || {};
  if (opts.character || (opts.refs || []).some((r) => r.kind === "identity" && r.file))
    return "identity_edit";
  // Mirrors effective_recipe's precedence exactly - identity first, then a
  // saved style, then style/quality. These two functions duplicate each other's
  // routing and a disagreement means the pill lies about what will render.
  const saved = savedStyleFor(opts, options);
  if (saved) return saved.base;
  const style = ["realism", "anime", "fantasy"].includes(opts.style)
    ? opts.style : "realism";
  const meta = (options.model_meta || {})[opts.model];
  if (meta?.family === "zimage")
    return meta.variant === "base" && (style === "anime" || style === "fantasy")
      ? style : "zimage";
  if (meta?.family === "krea2")
    return style === "realism" && opts.quality === "refined" ? "realism_ii" : "realism";
  // Qwen-Image has one graph and no style or quality variants. Falling through
  // would route it to Realism, which the server rejects as a family mismatch.
  if (meta?.family === "qwen_image") return "qwen_image";
  // Anima IS the style - one graph, no style or quality variants.
  if (meta?.family === "anima") return "anima";
  if (style === "anime" || style === "fantasy") return style;
  return opts.quality === "refined" ? "realism_ii" : "realism";
}

export function withExecutionRecipe(opts, options) {
  let style = ["realism", "anime", "fantasy"].includes(opts.style)
    ? opts.style : "realism";
  let quality = style === "realism" && opts.quality === "refined"
    ? "refined" : "standard";
  // Identity is a temporary execution mode. Its Krea-only model choice must
  // never rewrite the creative style that should return when the anchor/ref is
  // cleared.
  if (opts.character || (opts.refs || []).some((ref) =>
      ref.kind === "identity" && ref.file))
    return { ...opts, style, quality, engine: "identity_edit" };
  // A saved style owns the graph. style/quality are still carried, normalized,
  // so clearing the style returns the composer to a sane creative pick rather
  // than to whatever was in localStorage before.
  const saved = savedStyleFor(opts, options);
  if (saved) return { ...opts, style, quality, engine: saved.base };
  const meta = ((options || {}).model_meta || {})[opts.model];
  // Krea 2 has no anime or fantasy graph, but it can still be DIRECTED into
  // either - the server sends the register as craft direction on the photo
  // recipe. Forcing the selector back to Realism here made the choice look
  // available and then quietly discarded it.
  if (meta?.family === "zimage") {
    quality = "standard";
    if (meta.variant !== "base") style = "realism";
  }
  // Neither control reaches Qwen-Image's graph; pin them so the composer never
  // shows a style the render will not honour.
  if (meta?.family === "qwen_image") { style = "realism"; quality = "standard"; }
  // Anima only draws anime. Pin the selector to it so the pill states what the
  // render will actually be, rather than leaving a stale Realism label on it.
  if (meta?.family === "anima") { style = "anime"; quality = "standard"; }
  if (quality === "refined" && !(options?.recipes || [])
      .some((recipe) => recipe.id === "realism_ii" && recipe.available))
    quality = "standard";
  const normalized = { ...opts, style, quality };
  return { ...normalized, engine: activeRecipeId(normalized, options) };
}

const orderedStages = (recipe) => (recipe?.lora_stages || [])
  .map((stage, index) => ({ ...stage, _index: index }))
  .sort((a, b) => (a.order ?? a._index) - (b.order ?? b._index));

const planStrength = (value, fallback = 1) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : Number(fallback ?? 1);
};

const planEnabled = (value) => value !== false;

function recipeLoraProfile(opts, options, recipe) {
  const picked = (options.model_meta || {})[opts.model];
  const fallback = (options.model_meta || {})[recipe?.default_model];
  return {
    family: picked?.family || recipe?.family || fallback?.family || "krea2",
    variant: picked?.variant || fallback?.variant || recipe?.variants?.[0] || "any",
  };
}

function normalizePlanEntries(entries, recipe, options, opts) {
  const stages = orderedStages(recipe);
  const stageBySlot = new Map(stages.map((s) => [s.slot, s]));
  const stageNames = new Set(stages.map((s) => s.name));
  const loraByName = new Map((options.loras || []).map((l) => [l.name, l]));
  const profile = recipeLoraProfile(opts, options, recipe);
  const seen = new Set();
  const clean = [];

  for (const raw of Array.isArray(entries) ? entries : []) {
    const stage = raw?.slot && stageBySlot.get(raw.slot);
    if (stage) {
      if (stage.zone !== "editable" || seen.has(stage.name)) continue;
      seen.add(stage.name);
      clean.push({
        slot: stage.slot,
        strength: stage.strength_editable
          ? planStrength(raw.strength, stage.strength)
          : planStrength(stage.strength),
        enabled: stage.removable === false ? true : planEnabled(raw.enabled),
      });
      continue;
    }
    const name = String(raw?.name || "");
    const meta = loraByName.get(name);
    if (!name || seen.has(name) || stageNames.has(name) ||
        !loraSupportsProfile(meta, profile.family, profile.variant)) continue;
    seen.add(name);
    const entry = {
      name,
      strength: planStrength(raw.strength),
      enabled: planEnabled(raw.enabled),
    };
    const title = raw.title || meta?.title;
    if (title) entry.title = title;
    clean.push(entry);
  }

  // An active, non-removable recipe stage cannot disappear because of stale
  // localStorage or a partially written plan.
  for (const stage of stages) {
    if (stage.zone !== "editable" || !stage.active_by_default || stage.removable !== false ||
        seen.has(stage.name)) continue;
    clean.push({ slot: stage.slot, strength: planStrength(stage.strength), enabled: true });
    seen.add(stage.name);
  }

  // Order-locked editable recipe stages form a pinned prefix in recipe order;
  // flexible defaults and user LoRAs retain the user's saved ordering after it.
  const locked = [];
  for (const stage of stages.filter((s) => s.zone === "editable" && s.order_locked)) {
    const entry = clean.find((e) => e.slot === stage.slot);
    if (entry) locked.push(entry);
  }
  const lockedSlots = new Set(locked.map((e) => e.slot));
  return [...locked, ...clean.filter((e) => !lockedSlots.has(e.slot))];
}

function defaultPlanEntries(recipe) {
  return orderedStages(recipe)
    .filter((stage) => stage.zone === "editable" && stage.active_by_default)
    .map((stage) => ({
      slot: stage.slot,
      strength: planStrength(stage.strength),
      enabled: true,
    }));
}

// Core stages stay out of the ordered lane - they are structural and hold the
// head of the chain. This map is the escape hatch: one entry per core slot the
// user has unlocked. Only a real deviation is kept, so a plan that changes
// nothing serialises exactly as it did before core overrides existed.
function normalizeCoreOverrides(core, recipe) {
  const slots = new Map((recipe?.lora_stages || [])
    .filter((stage) => stage.zone === "core").map((stage) => [stage.slot, stage]));
  const out = {};
  for (const [slot, raw] of Object.entries(core || {})) {
    const stage = slots.get(slot);
    if (!stage || !raw || typeof raw !== "object") continue;
    const override = {};
    if (raw.enabled === false) override.enabled = false;
    if (raw.strength !== undefined &&
        planStrength(raw.strength, stage.strength) !== stage.strength)
      override.strength = planStrength(raw.strength, stage.strength);
    if (Object.keys(override).length) out[slot] = override;
  }
  return out;
}

// Exported for StyleForm: a saved style holds a plan for a recipe that is not
// the active one, so it cannot go through the setActiveLoraEntries path. Same
// builder either way, so a style's stack obeys the same locking, ordering and
// compatibility rules as the composer's.
export function buildLoraPlan(recipe, entries, options, opts, core) {
  return makeLoraPlan(recipe, entries, options, opts, core);
}

export function defaultLoraEntries(recipe) {
  return defaultPlanEntries(recipe);
}

function makeLoraPlan(recipe, entries, options, opts, core) {
  const overrides = normalizeCoreOverrides(core, recipe);
  return {
    version: LORA_PLAN_VERSION,
    recipe: recipe.id,
    recipe_revision: recipe.lora_stack_revision,
    mode: "replace_editable",
    entries: normalizePlanEntries(entries, recipe, options, opts),
    ...(Object.keys(overrides).length ? { core: overrides } : {}),
  };
}

function planMirror(plan, recipe, options) {
  const stages = new Map(orderedStages(recipe).map((s) => [s.slot, s]));
  const metas = new Map((options.loras || []).map((l) => [l.name, l]));
  return (plan?.entries || []).flatMap((entry) => {
    if (entry.enabled === false) return [];
    const stage = entry.slot && stages.get(entry.slot);
    const name = stage?.name || entry.name;
    if (!name) return [];
    const meta = metas.get(name);
    return [{ name, title: entry.title || meta?.title,
              strength: planStrength(entry.strength, stage?.strength), enabled: true }];
  });
}

function userExtrasFrom(opts, options) {
  const id = activeRecipeId(opts, options);
  const plan = (opts.lora_plans || {})[id];
  const fromPlan = (plan?.entries || []).filter((entry) => entry.name);
  if (plan) return fromPlan;
  const recipeStageNames = new Set((options.recipes || []).flatMap((recipe) =>
    (recipe.lora_stages || []).map((stage) => stage.name)));
  return (opts.loras || []).filter((lora) => !recipeStageNames.has(lora.name))
    .map((lora) => ({ name: lora.name, title: lora.title, strength: lora.strength }));
}

function syncActiveLoraPlan(opts, options, legacyExtras = []) {
  const recipeId = activeRecipeId(opts, options);
  const recipe = recipeById(recipeId, options);
  if (!recipe || !Array.isArray(recipe.lora_stages)) {
    const seen = new Set();
    const loras = legacyExtras.flatMap((entry) => {
      if (entry?.enabled === false) return [];
      const name = String(entry?.name || "");
      if (!name || seen.has(name)) return [];
      seen.add(name);
      return [{ name, ...(entry.title ? { title: entry.title } : {}),
                strength: planStrength(entry.strength) }];
    });
    return { ...opts, loras };
  }
  const plans = { ...(opts.lora_plans || {}) };
  const existing = plans[recipeId];
  const current = existing?.version === LORA_PLAN_VERSION &&
    existing.recipe === recipeId &&
    existing.recipe_revision === recipe.lora_stack_revision;
  let plan;
  if (current) {
    plan = makeLoraPlan(recipe, existing.entries, options, opts, existing.core);
  } else {
    // A stack revision retires the editable lane, but an unlocked core stage is
    // a standing preference about a slot that still exists - carry it across.
    const oldUsers = (existing?.entries || []).filter((entry) => entry.name);
    plan = makeLoraPlan(recipe,
      [...defaultPlanEntries(recipe), ...oldUsers, ...legacyExtras], options, opts,
      existing?.core);
  }
  plans[recipeId] = plan;
  return { ...opts, lora_plans: plans, loras: planMirror(plan, recipe, options) };
}

export function loraPlanFor(opts, options) {
  const id = activeRecipeId(opts, options);
  const recipe = recipeById(id, options);
  const plan = (opts?.lora_plans || {})[id];
  if (!recipe || !plan || plan.recipe_revision !== recipe.lora_stack_revision) return null;
  return plan;
}

// The recipe-card extender's dials are declared server-side per recipe
// (RECIPE_SPECS[..].dials) and ride /api/options exactly like lora_stages, so
// a later recipe gets its own extender by declaring it - no client change.
export function recipeDials(recipeId, options) {
  return recipeById(recipeId, options)?.dials || [];
}

// The composer's dial state is a sparse per-recipe override map, keyed exactly
// like lora_plans: a dial appears only while it deviates from the recipe's own
// number, so dragging back onto it clears the override - there is always a way
// home. Saved styles never carry dials (out of scope, brief 9.14): the composer
// sends them itself and the server applies them over the style's file, the same
// precedence the composer's LoRA stack already has.
export function dialOverrides(opts, options) {
  return ((opts?.dials || {})[activeRecipeId(opts, options)]) || {};
}

// Quick tuning (2026-08-26): the composer's sampler/steps/cfg override for the
// active recipe, sparse exactly like the dials - a key appears only while it
// deviates from what the recipe (or the selected style) already runs at.
// Keyed per recipe, so changing recipe leaves no hidden state behind.
export function tuningOverrides(opts, options) {
  return ((opts?.tuning || {})[activeRecipeId(opts, options)]) || {};
}

// What the composer is LOOKING at: the override where one is set, the recipe's
// own value where it is not. The re-roll sends these so it lands on the
// settings on screen rather than the ones the card was born with - the likeness
// dials and the bypass variant alike (brief 9.15).
export function resolvedDials(opts, options) {
  const id = activeRecipeId(opts, options);
  const overrides = ((opts?.dials || {})[id]) || {};
  const out = {};
  for (const dial of recipeDials(id, options))
    out[dial.key] = overrides[dial.key] ?? dial.default;
  return out;
}
// Prompt enhance is a writer switch, not a render pick, so it lives in its own
// localStorage key rather than opts. Both readers of renderIntent - the
// composer's send and the re-roll - read the same switch.
export const PROMPT_ENHANCE_KEY = "pixal-prompt-enhance";

export function loadPromptEnhance() {
  try {
    const saved = localStorage.getItem(PROMPT_ENHANCE_KEY);
    return saved == null ? true : saved !== "off";
  } catch { return true; }
}

// Keep disabled rows in localStorage/UI, but never transmit them as execution
// candidates. This is also safe during a rolling update: older Pixal servers
// understood version-1 plans but did not know the later `enabled` field.
const executableLoraPlan = (plan) => !plan ? null : ({
  ...plan,
  entries: (plan.entries || []).filter((entry) => entry.enabled !== false)
    .map(({ enabled: _enabled, ...entry }) => entry),
});

// The one render-intent builder, shared by chat and the re-roll (brief 9.42):
// what the composer is LOOKING at, as the opts body the server overlays. Chat
// sends it beside the prompt; a re-roll sends the SAME object, so a character,
// a preset or a style direction refines exactly like a LoRA does. When the
// composer is saying nothing, both callers send no opts at all - the
// stale-bundle contract the server keeps.
export function renderIntent(promptEnhance, o = state.opts) {
  const options = state.options;
  const character = o.character || "";
  const loraPlan = loraPlanFor(o, options);
  // The recipe-card extender's overrides for the active recipe (sparse: only
  // dials moved off the recipe's own number appear here).
  const dialSet = dialOverrides(o, options);
  const tuneSet = tuningOverrides(o, options);
  // A held seed counts as composer intent on its own: with no other pick set,
  // `active` stayed false, no body was built, and the frozen seed never left
  // the browser.
  const frozen = heldSeed ? heldSeed.seed : 0;
  const savedStyle = savedStyleFor(o, options);
  const active = o.style || o.quality || (o.engine !== "auto") || o.model || o.aspect || o.mp ||
                 o.loras.length || o.refs.length || character || loraPlan || !promptEnhance ||
                 o.editSource || o.cinematic || frozen || savedStyle ||
                 Object.keys(dialSet).length || Object.keys(tuneSet).length;
  if (!active) return { summary: null, body: null };
  const bits = [];
  // Leads the line: on an edit turn the rest of the picks are not consulted,
  // so saying so first stops "Realism · 2:3" reading as what just ran.
  if (o.editSource) bits.push("Editing " + o.editSource.split("/").pop());
  // Anime/Fantasy on a Krea 2 model is DIRECTED - it has no graph of its
  // own, it exists only as craft direction the brain writes into the scene.
  // With Prompt enhance off the scene is the user's words verbatim, so the
  // pick never lands; claiming it here made the render look like a bug.
  const styleLands = promptEnhance || !o.style || o.style === "realism" ||
    ((options?.model_meta || {})[o.model] || {}).family !== "krea2";
  // A saved style supersedes style/quality entirely, so it leads the line
  // and they are not mentioned - saying "Realism · Refined" beside a saved
  // style would name two things when only one of them runs.
  if (savedStyle) bits.push(savedStyle.name);
  else if (o.style && styleLands) bits.push(o.style[0].toUpperCase() + o.style.slice(1));
  else if (o.engine !== "auto") bits.push(prettyTemplate(o.engine));
  if (!savedStyle && o.quality === "refined") bits.push("Refined");
  // Cinematic is craft direction the brain writes into the scene, so with
  // Prompt enhance off it never reaches the render - don't claim it here.
  if (o.cinematic && promptEnhance) bits.push("Cinematic");
  if (character) bits.push((options && (options.characters || [])
    .find(c => c.id === character)?.name) || character);
  if (o.model) bits.push(o.model.split("\\").pop().replace(".safetensors", ""));
  if (o.aspect) bits.push(o.aspect.split(" ")[0] + (o.mp ? "@" + o.mp + "MP" : ""));
  else if (o.mp) bits.push(o.mp + "MP");
  // A moved dial is render-affecting, so the note names it like every other
  // pick - only overrides, never the recipe's own numbers.
  const liveDials = recipeDials(activeRecipeId(o, options), options)
    .filter((d) => dialSet[d.key] !== undefined);
  for (const d of liveDials)
    bits.push(`${d.label.toLowerCase()} ${dialSet[d.key]}`);
  if (Object.keys(tuneSet).length) bits.push("tuned");
  if (o.loras.length) bits.push("+" + o.loras.length + " lora");
  if (o.refs.length) bits.push(o.refs.length + " ref");
  if (frozen) bits.push("seed " + frozen + " locked");
  if (!promptEnhance) bits.push("Prompt enhance off");
  const summary = bits.join(" · ");
  const body = {};
  // `engine` is the normalized execution route; style/quality remain
  // creative intent. Send both during the persisted-options migration so
  // old and new servers queue the same proven graph.
  if (o.engine && o.engine !== "auto") body.engine = o.engine;
  // The style id is all the server needs: it reads the FILE for the model,
  // canvas, LoRA plan and sampler, so a stale mirror in this tab cannot
  // change what renders.
  if (savedStyle) body.saved_style = savedStyle.id;
  if (o.style && styleLands) body.style = o.style;
  if (o.quality) body.quality = o.quality;
  if (o.cinematic && promptEnhance) body.cinematic = true;
  if (character) body.character = character;
  if (o.model) body.model = o.model;
  if (o.aspect) body.aspect = o.aspect;
  if (o.mp) body.mp = o.mp;
  // The extender's dials ride as sparse overrides, keyed by builder
  // parameter exactly like the canvas: an untouched dial is absent, so an
  // untouched composer submits precisely what it did before the dials
  // became reachable (the byte-identical-graph rule, brief 9.14).
  for (const d of liveDials) body[d.key] = dialSet[d.key];
  if (Object.keys(tuneSet).length) body.tuning = tuneSet;
  if (o.loras.length) body.loras = o.loras;
  if (loraPlan) body.lora_plan = executableLoraPlan(loraPlan);
  if (o.refs.length) body.refs = o.refs;
  if (o.editSource) body.edit_source = o.editSource;
  // The held seed rides every render, not just the re-roll button.
  if (frozen) body.seed = frozen;
  body.prompt_enhance = promptEnhance;
  return { summary, body };
}

function identityCompatibleSelections(options = state.options) {
  const identity = recipeById("identity_edit", options);
  if (!identity?.available) return null;
  const model = modelSupportsRecipe(state.opts.model, "identity_edit", options)
    ? state.opts.model : "";
  return { model };
}

const listeners = new Set();
const emit = () => listeners.forEach((fn) => fn());

const cid = () => Math.random().toString(16).slice(2, 10);
const conv = () => state.conversations[CONV];

// Every mutation REPLACES the conversation object - subscribers memo on its
// identity, so an in-place array push would render nothing.
function setMessages(next) {
  state.conversations[CONV] = { ...state.conversations[CONV], messages: next };
  emit();
}

function appendMsg(msg) {
  setMessages([...conv().messages, msg]);
}

function patchJob(jobId, patch) {
  setMessages(conv().messages.map((m) =>
    m.job && m.job.job_id === jobId ? { ...m, job: { ...m.job, ...patch } } : m));
}

// Sampling telemetry BYPASSES the message tree. progress fires every sampler
// step and preview ~8x/s; routing them through setMessages re-rendered the
// whole app 10-30x/s for the entire render - the composer, the LoRA rail,
// every message - which is exactly the stutter (2026-08-11: the UI has an
// 8.3ms frame budget at 120fps, and the GPU has nothing spare to composite
// with mid-render). Instead each live job has its own channel; only the one
// JobCard showing it subscribes, and notifications coalesce to one per frame.
const EMPTY_LIVE = { progress: {}, preview: null };
const live = new Map();          // jobId -> { progress, preview }
const liveSubs = new Map();      // jobId -> Set<fn>
const liveDirty = new Set();
let liveFlush = 0;

function touchLive(jobId, patch) {
  live.set(jobId, { ...(live.get(jobId) || EMPTY_LIVE), ...patch });
  liveDirty.add(jobId);
  if (liveFlush) return;
  liveFlush = requestAnimationFrame(() => {
    liveFlush = 0;
    for (const id of liveDirty) liveSubs.get(id)?.forEach((fn) => fn());
    liveDirty.clear();
  });
}

function dropLive(jobId) {
  live.delete(jobId);
  liveDirty.delete(jobId);
}

export function useJobLive(jobId) {
  const subscribe = useCallback((fn) => {
    if (!jobId) return () => {};
    let subs = liveSubs.get(jobId);
    if (!subs) liveSubs.set(jobId, (subs = new Set()));
    subs.add(fn);
    return () => { subs.delete(fn); if (!subs.size) liveSubs.delete(jobId); };
  }, [jobId]);
  const getSnapshot = useCallback(
    () => (jobId && live.get(jobId)) || EMPTY_LIVE, [jobId]);
  return useSyncExternalStore(subscribe, getSnapshot);
}

function setThinking(note) {
  state.inflight.add(CONV);
  state.thinkingMode[CONV] = note ? "working" : "thinking";
  state.progressMsg[CONV] = note;
  emit();
}

function clearThinking() {
  state.inflight.delete(CONV);
  state.progressMsg[CONV] = null;
  emit();
}

function onEvent(d) {
  switch (d.type) {
    // The poll cursor fell off the back of the server's replay ring, so some
    // events are simply gone. Rebuild from the authoritative lists rather than
    // carry on with a hole the UI cannot see.
    case "resync":
      api.loadHistory();
      api.loadOptions();
      break;
    case "status":
      state.comfy = d.comfy;
      emit();
      break;
    case "brain":
      state.brain = { mode: d.mode, model: d.model, device: d.device,
                      vision: !!d.vision, nsfw: !!d.nsfw };
      break;
    case "gpu":
      state.gpu = { name: d.name, used: d.used, total: d.total,
                    ram_used: d.ram_used, ram_total: d.ram_total };
      emit();
      break;
    case "scan":
      if (d.done) {
        state.scan = d.totals ? "catalog · " + d.totals : null;
        api.loadOptions();                    // fresh lists after a rescan
        emit();
        if (d.totals) setTimeout(() => { state.scan = null; emit(); }, 4500);
      } else {
        state.scan = d.text || "scanning…";
        emit();
      }
      break;
    case "thinking":
      setThinking(d.note);
      break;
    case "thinkingdone":
      clearThinking();
      break;
    case "text":
      if (d.text && d.text.trim())
        appendMsg({ id: cid(), role: "assistant", text: d.text, ts: d.ts });
      break;
    case "job":
      // a re-roll launched from the held card hands the lock to the child, so
      // lock -> adjust -> re-roll -> adjust again keeps the same dice throughout
      if (d.cid && pendingLocks.delete(d.cid) && d.seed > 0) {
        heldSeed = { id: d.job_id, seed: d.seed };
        saveSeedLock();
      }
      state.liveJobs = [...state.liveJobs, d.job_id];
      appendMsg({
        id: cid(), role: "assistant", ts: d.ts,
        job: { job_id: d.job_id, template: d.template, scene: d.scene,
               seed: d.seed, count: d.count, images: [], progress: {},
               info: null, done: false, error: null, elapsed: null },
      });
      break;
    case "jobinfo": {
      // The builder reports the model that was actually inserted into the
      // graph. Preserve its resolved family/profile; filenames are not a safe
      // architecture signal (some Z-Image finetunes contain "Krea2").
      const { type: _type, job_id: jobId, cid: _cid, ...info } = d;
      patchJob(jobId, { info });
      break;
    }
    case "progress": {
      const prev = (live.get(d.job_id) || EMPTY_LIVE).progress;
      if (prev.value !== d.value || prev.max !== d.max)
        touchLive(d.job_id, { progress: { value: d.value, max: d.max } });
      break;
    }
    case "preview":
      // sampling preview reduced to a luminance grid — the dot-matrix feed
      touchLive(d.job_id, { preview: { cols: d.cols, rows: d.rows, data: d.data, ts: d.ts } });
      break;
    case "image":
      setMessages(conv().messages.map((m) =>
        m.job && m.job.job_id === d.job_id
          ? { ...m, job: { ...m.job, images: [...m.job.images,
              { filename: d.filename, subfolder: d.subfolder,
                type: d.img_type || "output", media: d.media || "image" }] } }
          : m));
      break;
    case "jobdone":
      dropLive(d.job_id);
      state.liveJobs = state.liveJobs.filter((id) => id !== d.job_id);
      patchJob(d.job_id, { done: true, elapsed: d.elapsed, error: d.error || null });
      clearThinking();
      api.loadHistory();
      break;
    case "review":
      clearThinking();
      appendMsg({ id: cid(), role: "review", text: d.text, fix: d.fix || null,
                  parent: d.parent || null, ts: d.ts });
      break;
    case "error": {
      if (d.job_id) {
        dropLive(d.job_id);
        state.liveJobs = state.liveJobs.filter((id) => id !== d.job_id);
      }
      const hasJob = d.job_id &&
        conv().messages.some((m) => m.job && m.job.job_id === d.job_id);
      if (hasJob) patchJob(d.job_id, { error: d.message, done: true });
      else appendMsg({ id: cid(), role: "error", text: d.message, ts: d.ts });
      clearThinking();
      break;
    }
  }
}

// THE seed lock. One card holds it at a time, and while it is held the dice are
// frozen for EVERYTHING - the next chat render as much as a re-roll - until it
// is clicked off (Jesse, 2026-08-15: "I want that seed frozen until I click to
// unlock it"). It was previously a set of card ids consulted only by the
// re-roll endpoint, so locking a card and then typing a new prompt still rolled
// fresh, which is indistinguishable from the lock not working.
//
// Keyed by CARD ID and carrying the seed VALUE. The id is what the lock icon
// lights on; the value is what the composer sends, so a frozen render needs no
// ledger round-trip. It is deliberately not keyed on the value alone: the
// ledger holds 52 seeds shared by unrelated renders (seed 12345 sits on 16 of
// them), so a value key would light the lock on cards the user never touched.
// Persisted, because "I got a good render, now let me work on it" outlives a
// page load.
const SEEDLOCK_KEY = "pixal-seed-lock";
let heldSeed = (() => {
  try {
    const raw = JSON.parse(localStorage.getItem(SEEDLOCK_KEY));
    return raw && typeof raw.id === "string" && raw.id
      && Number.isFinite(raw.seed) && raw.seed > 0 ? { id: raw.id, seed: raw.seed } : null;
  } catch { return null; }
})();
// cid of a re-roll launched from the held card: the job it produces inherits
// the lock, so lock -> adjust -> re-roll -> adjust again keeps one card lit
// rather than stranding the icon on a render that has scrolled away.
const pendingLocks = new Set();
const saveSeedLock = () => {
  try {
    if (heldSeed) localStorage.setItem(SEEDLOCK_KEY, JSON.stringify(heldSeed));
    else localStorage.removeItem(SEEDLOCK_KEY);
  } catch { /* full */ }
};

export const api = {
  get state() { return state; },
  get conversations() { return state.conversations; },
  get inflight() { return state.inflight; },
  get progressMsg() { return state.progressMsg; },
  get thinkingMode() { return state.thinkingMode; },
  get comfy() { return state.comfy; },
  get gpu() { return state.gpu; },
  get brain() { return state.brain; },
  get liveJobs() { return state.liveJobs; },
  get scan() { return state.scan; },
  get history() { return state.history; },
  get options() { return state.options; },
  get opts() { return state.opts; },
  get activeRecipeId() { return activeRecipeId(state.opts, state.options); },
  get activeLoraPlan() { return loraPlanFor(state.opts, state.options); },
  get railOpen() { return state.railOpen; },
  get lb() { return state.lb; },

  setOpts(patch) {
    const legacyExtras = state.options ? userExtrasFrom(state.opts, state.options) : [];
    let next = { ...state.opts, ...patch };
    // Picking a model, a style or a quality by hand means you have LEFT the
    // saved style: those re-route the graph, so the label would name a preset
    // the render no longer follows.
    //
    // Editing the LoRA stack does NOT. A preset is a base to work from - you
    // keep it and try LoRAs against it - and the server takes the composer's
    // stack over the style's file precisely so that edit renders. Dropping the
    // label here was also silently reverting the SAMPLER: tuning lives only in
    // the style file and only applies while saved_style is set, so adding a
    // LoRA quietly took Ultra Realism's 5 steps back to Realism's 8 with every
    // visible pill unchanged.
    if (next.saved_style && !("saved_style" in patch) &&
        ["model", "style", "quality"].some((k) => k in patch))
      next.saved_style = "";
    if (state.options) {
      next = withExecutionRecipe(next, state.options);
      const catalog = state.options.model_meta || {};
      const meta = catalog[next.model];
      if (next.model && Object.keys(catalog).length && !meta?.supported) {
        next = withExecutionRecipe({ ...next, model: "" }, state.options);
      }
      next = syncActiveLoraPlan(next, state.options, legacyExtras);
    }
    state.opts = next;
    try { localStorage.setItem(OPTS_KEY, JSON.stringify(state.opts)); } catch { /* full */ }
    emit();
  },

  setActiveLoraEntries(entries) {
    const options = state.options;
    const recipeId = activeRecipeId(state.opts, options);
    const recipe = recipeById(recipeId, options);
    if (!recipe || !Array.isArray(recipe.lora_stages)) return false;
    const existing = (state.opts.lora_plans || {})[recipeId];
    const plan = makeLoraPlan(recipe, entries, options, state.opts, existing?.core);
    this.setOpts({ lora_plans: { ...(state.opts.lora_plans || {}), [recipeId]: plan },
                   loras: planMirror(plan, recipe, options) });
    return true;
  },

  // Unlock a structural stage: false bypasses it, true puts it back. The stage
  // keeps its authored position either way - this is a bypass switch, not a
  // way to reorder the core.
  setCoreStageEnabled(slot, enabled) {
    const options = state.options;
    const recipeId = activeRecipeId(state.opts, options);
    const recipe = recipeById(recipeId, options);
    if (!recipe || !(recipe.lora_stages || [])
        .some((stage) => stage.slot === slot && stage.zone === "core")) return false;
    const existing = (state.opts.lora_plans || {})[recipeId];
    const core = { ...(existing?.core || {}),
                   [slot]: { ...(existing?.core || {})[slot], enabled: !!enabled } };
    const plan = makeLoraPlan(recipe, existing?.entries || defaultPlanEntries(recipe),
                              options, state.opts, core);
    this.setOpts({ lora_plans: { ...(state.opts.lora_plans || {}), [recipeId]: plan },
                   loras: planMirror(plan, recipe, options) });
    return true;
  },

  // Retune a structural stage without touching its bypass: the raw value goes
  // into the same core override map and normalizeCoreOverrides coerces it and
  // keeps it only when it deviates from the authored strength, so an edit that
  // lands back on the recipe's own number serialises exactly as before.
  setCoreStageStrength(slot, strength) {
    const options = state.options;
    const recipeId = activeRecipeId(state.opts, options);
    const recipe = recipeById(recipeId, options);
    if (!recipe || !(recipe.lora_stages || [])
        .some((stage) => stage.slot === slot && stage.zone === "core")) return false;
    const existing = (state.opts.lora_plans || {})[recipeId];
    const core = { ...(existing?.core || {}),
                   [slot]: { ...(existing?.core || {})[slot], strength } };
    const plan = makeLoraPlan(recipe, existing?.entries || defaultPlanEntries(recipe),
                              options, state.opts, core);
    this.setOpts({ lora_plans: { ...(state.opts.lora_plans || {}), [recipeId]: plan },
                   loras: planMirror(plan, recipe, options) });
    return true;
  },

  resetActiveLoraPlan() {
    const options = state.options;
    const recipeId = activeRecipeId(state.opts, options);
    const recipe = recipeById(recipeId, options);
    if (!recipe || !Array.isArray(recipe.lora_stages)) return false;
    const plan = makeLoraPlan(recipe, defaultPlanEntries(recipe), options, state.opts);
    this.setOpts({ lora_plans: { ...(state.opts.lora_plans || {}), [recipeId]: plan },
                   loras: planMirror(plan, recipe, options) });
    return true;
  },

  // One dial on the recipe-card extender. Shape-checked only - the server owns
  // the range (and the installed choice set, brief 9.15) and degrades a bad
  // value to the recipe constant. A value back on the recipe's own setting
  // DELETES the override instead of storing it: the same way home the core
  // strength boxes have, where a retune that lands on the authored strength
  // serialises exactly as before. A blanked box clears too (the style dialog's
  // "blank follows the recipe" gesture) - Number("") is 0, and 0 is a real
  // likeness value, not "unset".
  setRecipeDial(key, value) {
    const options = state.options;
    const recipeId = activeRecipeId(state.opts, options);
    const spec = recipeDials(recipeId, options).find((d) => d.key === key);
    if (!spec) return false;
    const raw = value === null || value === undefined ? "" : String(value).trim();
    const n = raw === "" ? null : Number(raw);
    if (raw !== "" && !Number.isFinite(n)) return false;
    const map = { ...(state.opts.dials || {}) };
    const current = { ...(map[recipeId] || {}) };
    if (raw === "" || n === spec.default) delete current[key];
    else current[key] = n;
    if (Object.keys(current).length) map[recipeId] = current;
    else delete map[recipeId];
    this.setOpts({ dials: map });
    return true;
  },

  // Quick tuning: null (or the home value, which the card sends as null)
  // clears the key; an empty map for the recipe is removed outright.
  setTuning(key, value) {
    const recipeId = activeRecipeId(state.opts, state.options);
    const map = { ...(state.opts.tuning || {}) };
    const current = { ...(map[recipeId] || {}) };
    if (value === null || value === undefined || value === "") delete current[key];
    else current[key] = value;
    if (Object.keys(current).length) map[recipeId] = current;
    else delete map[recipeId];
    this.setOpts({ tuning: map });
  },

  get savedStyle() { return savedStyleFor(state.opts, state.options); },

  // Selecting a saved style MIRRORS the file into ordinary opts - model,
  // canvas, LoRA plan - so every pill and the LoRA rail state what will run
  // without any of them learning about styles. The server still reads the file
  // at render time; this is display, and display is allowed to be a copy.
  selectSavedStyle(id) {
    if (!id) { this.setOpts({ saved_style: "" }); return true; }
    const style = ((state.options || {}).saved_styles || []).find((s) => s.id === id);
    if (!style?.available) return false;
    // A style no longer evicts a selected character when its model can carry
    // the identity patch (any Krea 2 build): the style contributes its model
    // and stack to the identity graph server-side. Incompatible bases
    // (Z-Image, Anima) keep the old rule - the click wins, the character goes.
    const keepCharacter = !!state.opts.character &&
      modelSupportsRecipe(style.model, "identity_edit", state.options);
    const patch = { saved_style: id, model: style.model,
                    ...(keepCharacter ? {} : { character: "" }) };
    // The style file owns the schedule: a quick-tuning override left on its
    // base would silently ride over the tuning the user just chose.
    const tuning = { ...(state.opts.tuning || {}) };
    delete tuning[style.base];
    patch.tuning = tuning;
    if (style.aspect) patch.aspect = style.aspect;
    if (style.mp) patch.mp = style.mp;
    // Always restate the base's stack, including when the style carries none.
    // The server now prefers the composer's plan, so a leftover free-mode stack
    // for this recipe would otherwise be adopted as if it were the style's.
    const plans = { ...(state.opts.lora_plans || {}) };
    if (style.lora_plan) plans[style.base] = style.lora_plan;
    else delete plans[style.base];
    patch.lora_plans = plans;
    this.setOpts(patch);
    return true;
  },

  // Snapshot of what the composer is set to right now, as a style record the
  // editor can open pre-filled. This is the "save what I am looking at" path -
  // the one that makes authoring a style cost nothing.
  styleDraftFromComposer() {
    // The base is the recipe actually running - never a stand-in. (The old
    // bases[0] fallback quietly rewrote an Identity Edit draft into "Anime",
    // which is the bug Jesse reported on 2026-08-22.) If the composer state is
    // somehow unset, the most recent render's recipe is the honest fallback:
    // it is the look the user is looking at.
    const recipeId = activeRecipeId(state.opts, state.options);
    const plan = loraPlanFor(state.opts, state.options);
    const lastRendered = (state.history || []).find((e) => e && e.template);
    // loraPlanFor also returns null when the stored stack's revision predates
    // the recipe's current one. That must be SAID, not silently swapped for
    // the default chain - the flag lets the form name what happened.
    const stackDropped = !plan && !!((state.opts.lora_plans || {})[recipeId]);
    return {
      schema_version: 1,
      name: "",
      base: recipeId || (lastRendered || {}).template || "realism",
      model: state.opts.model || "",
      ...(state.opts.aspect ? { aspect: state.opts.aspect } : {}),
      ...(state.opts.mp ? { mp: state.opts.mp } : {}),
      ...(plan ? { lora_plan: plan } : {}),
      ...(stackDropped ? { lora_stack_dropped: true } : {}),
      // A quick-tuning override graduates into the style: "save what I am
      // looking at" includes the schedule on screen.
      tuning: { ...tuningOverrides(state.opts, state.options) },
    };
  },

  async saveStyle(style) {
    try {
      const r = await transport.saveStyle(style);
      if (!r?.ok) return { ok: false, error: r?.error || "the style could not be saved" };
      await this.loadOptions();
      return { ok: true, id: r.id };
    } catch (e) {
      return { ok: false, error: e?.message || "server unreachable" };
    }
  },

  async deleteStyle(id) {
    try {
      const r = await transport.deleteStyle(id);
      if (!r?.ok) return { ok: false, error: r?.error || "the style could not be deleted" };
      if (state.opts.saved_style === id) this.setOpts({ saved_style: "" });
      await this.loadOptions();
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e?.message || "server unreachable" };
    }
  },

  // One authority for character state. A referenced anchor is an Identity Edit
  // choice, not merely extra caption text: it switches the recipe, removes a
  // stale manual face reference, and heals model/LoRA picks to that graph.
  // Returns false when the requested anchor cannot safely run Identity Edit.
  selectCharacter(id) {
    const refs = state.opts.refs || [];
    if (!id) {
      this.setOpts({
        character: "",
        engine: state.opts.engine === "identity_edit" && !hasIdentityRef()
          ? "auto" : state.opts.engine,
      });
      return true;
    }

    const options = state.options;
    const character = ((options && options.characters) || []).find((c) => c.id === id);
    const compatible = identityCompatibleSelections(options);
    if (!character?.has_ref || !compatible) return false;

    // A selected saved style survives the character when its model can carry
    // the identity patch. Naming saved_style in the patch is what keeps the
    // model-change heal from clearing it; the style's model wins the spread.
    const style = savedStyleFor(state.opts, options);
    const styleOk = style &&
      modelSupportsRecipe(style.model, "identity_edit", options);
    this.setOpts({
      character: id,
      engine: "identity_edit",
      ...compatible,
      ...(styleOk ? { saved_style: state.opts.saved_style,
                      model: style.model } : {}),
      refs: refs.filter((r) => r.kind !== "identity"),
    });
    return true;
  },

  // The other valid Identity Edit source mode: one manually selected image,
  // with no character canon. It uses the same compatibility healing as an
  // anchor, and removal cannot strand Identity Edit without a source.
  selectIdentityReference(file) {
    if (!file) {
      const refs = (state.opts.refs || []).filter((r) => r.kind !== "identity");
      this.setOpts({
        refs,
        engine: !state.opts.character && state.opts.engine === "identity_edit"
          ? "auto" : state.opts.engine,
      });
      return true;
    }
    const compatible = identityCompatibleSelections();
    if (!compatible) return false;
    if (state.opts.character) this.selectCharacter("");
    this.setOpts({
      character: "",
      engine: "identity_edit",
      ...compatible,
      refs: [...(state.opts.refs || []).filter((r) => r.kind !== "identity"),
             { kind: "identity", file }],
    });
    return true;
  },

  addReference(kind, file) {
    if (!file) return false;
    if (kind === "identity") return this.selectIdentityReference(file);
    if (!["style", "clothing", "object"].includes(kind)) return false;
    const refs = state.opts.refs || [];
    if (!refs.some((ref) => ref.kind === kind && ref.file === file))
      this.setOpts({ refs: [...refs, { kind, file }] });
    return true;
  },

  removeReference(kind, file) {
    if (kind === "identity") return this.selectIdentityReference("");
    const refs = (state.opts.refs || [])
      .filter((ref) => !(ref.kind === kind && ref.file === file));
    this.setOpts({ refs });
    return true;
  },
  // History, settings and chats share the dock lane — opening one closes the others.
  setRailOpen(v) { state.railOpen = v; if (v) { state.settingsOpen = false; state.chatsOpen = false; } emit(); },
  setChatsOpen(v) { state.chatsOpen = v; if (v) { state.railOpen = false; state.settingsOpen = false; } emit(); },
  get chatsOpen() { return state.chatsOpen; },
  get chats() { return state.chats; },
  get activeChat() { return state.activeChat; },

  async loadChats() {
    try {
      const r = await (await fetch("/api/chats")).json();
      state.chats = r.chats || []; state.activeChat = r.active; emit();
    } catch { /* server down */ }
  },

  // new / select / delete — the server owns the active chat; after any change
  // the lane re-seeds from the newly active chat's transcript.
  async chatAction(action, id) {
    try {
      const r = await (await fetch("/api/chats", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, id }),
      })).json();
      state.chats = r.chats || []; state.activeChat = r.active;
      setMessages([]);
      await this.loadLane();
      emit();
    } catch { /* server down */ }
  },
  setLb(v) { state.lb = v; emit(); },

  addConversation(id, c) { state.conversations[id] = c; emit(); },
  removeConversation(id) { delete state.conversations[id]; emit(); },

  async sendChatMessage(convId, text, opts) {
    const t = (text || "").trim();
    if (!t) return;
    appendMsg({ id: cid(), role: "user", text: t, ts: Date.now() / 1000 });
    if (opts) appendMsg({ id: cid(), role: "optsnote",
                          text: opts.summary || String(opts), ts: Date.now() / 1000 });
    setThinking(null);           // optimistic — dots before the network even answers
    // An armed edit source turns this message into the edit instruction itself:
    // straight to Qwen Image Edit, the user's words verbatim, no brain in
    // between (it is trained on direct commands). One-shot, so the message after
    // it is an ordinary chat turn again.
    const editSource = opts?.body?.edit_source;
    try {
      const r = editSource
        ? await transport.edit(null, cid(), t, editSource)
        : await transport.chat(t, cid(), opts ? opts.body : undefined);
      if (editSource) this.setOpts({ editSource: "" });
      if (!r.ok) {
        appendMsg({ id: cid(), role: "error", text: r.error || "send failed", ts: Date.now() / 1000 });
        clearThinking();
      }
    } catch (e) {
      appendMsg({ id: cid(), role: "error", text: "server unreachable: " + e.message, ts: Date.now() / 1000 });
      clearThinking();
    }
  },

  async stopGeneration() {
    clearThinking();
    try { await transport.stop(null); } catch { /* server down */ }
  },

  // The seed lock, keyed by ledger/job id and persisted. While it is held every
  // render uses that seed - new prompts included - and the held card's re-roll
  // hands the lock to the card it produces.
  seedLocked(id) { return !!heldSeed && heldSeed.id === id; },
  get heldSeed() { return heldSeed ? heldSeed.seed : 0; },
  toggleSeedLock(id, seed) {
    if (!id) return;
    // Locking a second card MOVES the lock rather than adding to it: the seed
    // is frozen or it is not, and two frozen seeds cannot both be next.
    heldSeed = (heldSeed && heldSeed.id === id) || !(seed > 0)
      ? null : { id, seed };
    saveSeedLock();
    emit();               // the composer's frozen-seed chip lives on this
  },
  clearSeedLock() {
    if (!heldSeed) return;
    heldSeed = null;
    saveSeedLock();
    emit();
  },

  // The composer is the truth: a re-roll carries the stack the user is looking
  // at right now. `opts` is the SAME body chat sends (renderIntent), so a
  // character, a preset or a style direction refines exactly like a LoRA does;
  // the legacy fields stay for a server that predates the overlay. Only the
  // ACTIVE recipe's plan is sent - the lora_plans map also holds every recipe
  // that was ever active, and only the active one is kept in sync, so shipping
  // the whole map let a card from another recipe be re-rolled against a stale
  // plan the user was not looking at. The server takes what it is sent only if
  // it fits the card's own graph, so a mismatch falls through to the card's
  // stored plan instead.
  async reroll(jobId) {
    const c = cid();
    // A held seed freezes this re-roll too, whichever card it was thrown from -
    // that is what "frozen until I unlock it" has to mean, or the button
    // silently escapes the lock. Only the held card's own re-roll passes the
    // lock along to its child.
    const frozen = heldSeed ? heldSeed.seed : 0;
    if (heldSeed && heldSeed.id === jobId) pendingLocks.add(c);
    try {
      const rid = activeRecipeId(state.opts, state.options);
      const plan = rid && (state.opts.lora_plans || {})[rid];
      // The recipe dials ride resolved - the override, or the recipe's own
      // number - so the re-roll lands on the likeness the composer SHOWS. An
      // untouched dial reads "follows the recipe" on screen; keeping the card's
      // stored value instead would silently roll a likeness nobody is looking
      // at. A recipe declaring no dials sends none, and the stored ones win.
      const { body: intent } = renderIntent(loadPromptEnhance());
      const result = await transport.reroll(jobId, c, frozen,
                             plan ? { [rid]: plan } : {}, state.opts.model || "",
                             state.opts.aspect || "", state.opts.mp || 0,
                             resolvedDials(state.opts, state.options),
                             intent || undefined);
      // The server refuses with {ok:false} when the ledger entry is already
      // gone - surface it like every sibling does, and release the pending
      // seed lock here too: the catch only sees a network throw, so a
      // refused re-roll would otherwise leak its lock entry.
      if (!result?.ok) {
        pendingLocks.delete(c);
        appendMsg({ id: cid(), role: "error",
                    text: result?.error || "the re-roll could not be started",
                    ts: Date.now() / 1000 });
      }
    } catch { pendingLocks.delete(c); }
  },

  async animate(entryId, hint, seconds, engine, model, loraPlan, fps, shots, script,
                speed, lastId, sparse, upscale, resolution) {
    try {
      const result = await transport.animate(
        entryId, cid(), hint, seconds, engine, model, loraPlan, fps, shots, script,
        speed, lastId, sparse, upscale, resolution);
      if (!result?.ok)
        appendMsg({ id: cid(), role: "error",
                    text: result?.error || "animation could not be started",
                    ts: Date.now() / 1000 });
    } catch (e) {
      appendMsg({ id: cid(), role: "error", text: "server unreachable: " + e.message,
                  ts: Date.now() / 1000 });
    }
  },

  async review(entryId) {
    try {
      const result = await transport.review(entryId, cid());
      // The server refuses with {ok:false} when the ledger entry is already
      // gone - surface it like every sibling does, not a click into silence.
      if (!result?.ok)
        appendMsg({ id: cid(), role: "error",
                    text: result?.error || "the review could not be started",
                    ts: Date.now() / 1000 });
    } catch { /* server down */ }
  },

  async upscale(entryId, model) {
    try {
      const result = await transport.upscale(entryId, cid(), model);
      if (!result?.ok)
        appendMsg({ id: cid(), role: "error",
                    text: result?.error || "the upscale could not be started",
                    ts: Date.now() / 1000 });
    } catch (e) {
      appendMsg({ id: cid(), role: "error", text: "server unreachable: " + e.message,
                  ts: Date.now() / 1000 });
    }
  },

  async edit(entryId, instruction, extra = {}) {
    try {
      // A crop is cut client-side and uploaded like an attached photo; the
      // upload name then replaces the ledger id as the edit source, and any
      // painted mask (already cut to the same crop) rides along.
      let input = null, id = entryId;
      if (extra.cropBlob) {
        const file = new File([extra.cropBlob], "pixal_crop.png",
                             { type: "image/png" });
        input = (await transport.upload(file)).name;
        id = null;
      }
      const result = await transport.edit(id, cid(), instruction, input,
                                          extra.mask || null,
                                          extra.reference || null);
      if (!result?.ok)
        appendMsg({ id: cid(), role: "error",
                    text: result?.error || "the edit could not be started",
                    ts: Date.now() / 1000 });
    } catch (e) {
      appendMsg({ id: cid(), role: "error", text: "server unreachable: " + e.message,
                  ts: Date.now() / 1000 });
    }
  },

  // Same lanes as edit(), sourced from an image already in ComfyUI/input
  // (the character form edits its reference this way). A crop replaces the
  // source the same way it does for a ledger entry.
  async editInput(inputName, instruction, extra = {}) {
    try {
      let input = inputName;
      if (extra.cropBlob) {
        const file = new File([extra.cropBlob], "pixal_crop.png",
                             { type: "image/png" });
        input = (await transport.upload(file)).name;
      }
      const result = await transport.edit(null, cid(), instruction, input,
                                          extra.mask || null,
                                          extra.reference || null);
      if (!result?.ok)
        appendMsg({ id: cid(), role: "error",
                    text: result?.error || "the edit could not be started",
                    ts: Date.now() / 1000 });
      return !!result?.ok;
    } catch (e) {
      appendMsg({ id: cid(), role: "error", text: "server unreachable: " + e.message,
                  ts: Date.now() / 1000 });
      return false;
    }
  },

  async deleteEntry(entryId) {
    state.history = state.history.filter((e) => e.id !== entryId);   // optimistic
    emit();
    try { await transport.histDelete(entryId); } catch { /* server down */ }
    this.loadHistory();
  },

  async deleteCharacter(characterId) {
    try {
      await transport.deleteCharacter(characterId);
      if (state.options) {
        state.options = {
          ...state.options,
          characters: (state.options.characters || [])
            .filter((c) => c.id !== characterId),
        };
      }
      if (state.opts.character === characterId) this.selectCharacter("");
      else emit();
      // Keep the optimistic roster removal if refresh is temporarily offline;
      // otherwise reconcile against the server's canonical character list.
      await this.loadOptions();
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e?.message || "could not delete the character anchor" };
    }
  },

  setSettingsOpen(v) { state.settingsOpen = v; if (v) { state.railOpen = false; state.chatsOpen = false; } emit(); },
  get settingsOpen() { return state.settingsOpen; },

  get themePref() { return state.themePref; },
  setTheme(v) {
    state.themePref = v;
    try { localStorage.setItem("pixal-theme", v); } catch { /* full */ }
    emit();
  },
  bump() { emit(); },            // re-render hook (OS theme change in system mode)

  async loadHistory() {
    try { state.history = await transport.history(); emit(); } catch { /* keep stale */ }
  },

  async loadOptions() {
    try {
      state.options = await transport.options();
      // Remember what localStorage asked for before general reconciliation can
      // erase an anchor that is no longer in the server roster. A saved manual
      // face must never silently take over from that formerly-authoritative
      // character.
      const requestedCharacter = state.opts.character;
      const legacyExtras = userExtrasFrom(state.opts, state.options);
      reconcileOpts(state.options);
      state.opts = syncActiveLoraPlan(state.opts, state.options, legacyExtras);
      try { localStorage.setItem(OPTS_KEY, JSON.stringify(state.opts)); } catch { /* full */ }
      if (requestedCharacter) {
        // Rehydrate old localStorage through the same path as a fresh pick.
        if (!this.selectCharacter(requestedCharacter)) {
          const refs = (state.opts.refs || []).filter((r) => r.kind !== "identity");
          this.setOpts({
            character: "",
            refs,
            engine: state.opts.engine === "identity_edit" ? "auto" : state.opts.engine,
          });
        }
      } else if (hasIdentityRef()) {
        // Older saved settings may contain a face reference while still saying
        // Auto (or another recipe). Reapply it through the canonical action so
        // the visible recipe and compatibility cleanup match what will queue.
        const identity = (state.opts.refs || [])
          .find((r) => r.kind === "identity" && r.file);
        const inputExists = (state.options.inputs || []).includes(identity.file);
        if (!inputExists || !this.selectIdentityReference(identity.file)) {
          this.selectIdentityReference("");
        }
      } else if (state.opts.engine === "identity_edit" && !hasIdentityRef()) {
        // A stale Identity Edit choice with no source would be doomed on send.
        this.setOpts({ engine: "auto" });
      } else {
        emit();
      }
      return state.options;
    } catch { /* keep stale */ }
  },

  async rescan() {
    try { await fetch("/api/settings/rescan", { method: "POST" }); } catch { /* down */ }
  },

  // Replay the server-side lane transcript so a refresh resumes the chat
  // instead of losing it. Runs once at boot, before live events land.
  async loadLane() {
    try {
      const entries = await transport.lane();
      if (!entries.length) return;
      // the lobby greeting may have landed first — replay replaces it, but a
      // lane that already holds real messages is never clobbered
      if (conv().messages.some((m) => m.id !== "greet")) return;
      setMessages(entries.map((e) => {
        if (e.role === "job")
          return { id: cid(), role: "assistant", ts: e.ts,
                   job: { ...e.job, progress: {}, preview: null } };
        if (e.role === "review")
          return { id: cid(), role: "review", text: e.text,
                   fix: e.fix || null, parent: e.parent || null, ts: e.ts };
        return { id: cid(), role: e.role, text: e.text, ts: e.ts };
      }));
    } catch { /* server down - lane stays empty */ }
  },

  init() {
    transport.subscribe(onEvent);
    this.loadLane().finally(() => transport.connect());
    this.loadChats();
    this.loadHistory();
    this.loadOptions();
  },
};

let booted = false;

// useStore — same shape as the ported widget's useStore: subscribe, re-render
// on any mutation, return the action surface + state getters.
export function useStore() {
  const [, force] = useReducer((x) => x + 1, 0);
  useEffect(() => {
    if (!booted) { booted = true; api.init(); }
    listeners.add(force);
    return () => listeners.delete(force);
  }, []);
  return api;
}

// Reactive read of THE seed lock for one card. JobCards sit behind Message's
// msg-identity memo, so a plain api.seedLocked() read latches: the lock moves,
// no prop changes, and the card that lost it keeps wearing a closed padlock.
export function useSeedLocked(id) {
  const subscribe = useCallback(
    (fn) => { listeners.add(fn); return () => listeners.delete(fn); }, []);
  const getSnapshot = useCallback(
    () => !!heldSeed && heldSeed.id === id, [id]);
  return useSyncExternalStore(subscribe, getSnapshot);
}
