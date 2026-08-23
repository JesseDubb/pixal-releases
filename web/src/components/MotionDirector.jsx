// MotionDirector.jsx — the dialog behind every Animate click. The user's note is
// the vision; the motion LLM turns it into a filmable brief (server-side), and the
// brief comes back into the lane so they see what their words became. "Surprise me"
// ships without a note — the director animates what's already in the frame.
//
// LAYOUT (2026-08-11): three zones instead of a flat stack. The note is the hero;
// engine + length are the only decisions every clip needs and sit as two segmented
// tracks (the SettingsMenu Appearance recipe); everything situational — model
// variants, shots, the end-frame bridge, LoRAs, the speed recipe, fps — lives behind one
// "fine-tune" fold. The fold's collapsed row narrates any non-default it is
// hiding, so collapsing never lies about what will render.
import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, CaretDown, FilmStrip,
         Minus, Plus, Trash, X } from "@phosphor-icons/react";
import { FONT, TYPE, SPACE, RADIUS, MOTION, SHADOW, W, LH } from "../lib/design-tokens.js";
import { LightricksMark, MiniMaxMark } from "../lib/BrandMarks.jsx";
import { Disclosure } from "../lib/Disclosure.jsx";
import { SegmentedControl } from "../lib/SegmentedControl.jsx";
import { ModalShell } from "../lib/ModalShell.jsx";
import { InfoTip } from "./InfoTip.jsx";
import { imgUrl, thumbUrl, subscribe } from "../transport.js";

const LENGTHS = [
  { s: 3, label: "3s", gloss: "a beat" },
  { s: 5, label: "5s", gloss: "a moment" },
  { s: 8, label: "8s", gloss: "a take" },
];

// Shown only before the server's engine list arrives.
const FALLBACK_ENGINES = [{
  id: "ltx25", label: "LTX 2.5", tag: "pixel diffusion · audio",
  available: true, lengths: LENGTHS,
  models: [{ id: "default", label: "Distilled", available: true }],
}];

// A note that separates its shots with --- on its own line is a SCRIPT, not a
// note: it reaches the sampler verbatim instead of being rewritten by the motion
// director, and it declares its own shot count. Same separator the server parses.
const SHOT_SPLIT = /^[ \t]*-{3,}[ \t]*$/m;
const countShots = (text) =>
  String(text || "").split(SHOT_SPLIT).filter((part) => part.trim()).length;

const defaultLength = (engine) => {
  const choices = engine?.lengths?.length ? engine.lengths : LENGTHS;
  return choices.find((item) => item.s === 5) || choices[0] || { s: 5 };
};

// Animate LoRAs have a distinct persistence contract from still-image recipes.
// The object is keyed by engine:model so switching engines cannot leak a chain.
const VIDEO_LORA_STORAGE_KEY = "pixal.animate.videoLoraPlans.v1";
const FINE_TUNE_OPEN_KEY = "pixal.animate.fineTune.open";
const videoPlanKey = (engine, model) => `${engine}:${model}`;

const loadVideoLoraPlans = () => {
  if (typeof window === "undefined") return {};
  try {
    const value = JSON.parse(window.localStorage.getItem(VIDEO_LORA_STORAGE_KEY) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
};

const normalizeVideoPlan = (plan, engine, model, catalog) => {
  const allowed = new Map((catalog || []).map((item) => [item.name.toLowerCase(), item]));
  const stored = plan?.version === 1 && plan?.mode === "replace" &&
    plan?.engine === engine && plan?.model === model && Array.isArray(plan?.entries)
    ? plan.entries
    : (catalog || []).filter((item) => item.active_by_default).map((item) => ({
        name: item.name, strength: item.default_strength ?? 1, enabled: true,
      }));
  const seen = new Set();
  const entries = [];
  stored.forEach((row) => {
    const item = allowed.get(String(row?.name || "").replaceAll("/", "\\").toLowerCase());
    if (!item || seen.has(item.name.toLowerCase())) return;
    seen.add(item.name.toLowerCase());
    const parsed = Number(row.strength);
    entries.push({
      name: item.name,
      strength: Number.isFinite(parsed) ? parsed : (item.default_strength ?? 1),
      enabled: row.enabled !== false,
    });
  });
  return { version: 1, mode: "replace", engine, model, entries };
};

// ---------------------------------------------------------------- primitives
// The micro label + caption pair every zone speaks in. One voice, not eight.
const MICRO = { fontSize: TYPE.micro, color: "var(--textTer)", fontWeight: W.label,
                textTransform: "uppercase", letterSpacing: "0.08em" };
const CAPTION = { fontSize: TYPE.label, color: "var(--textTer)", lineHeight: LH.ui };

// One switch recipe for every on/off in the dialog (was hand-rolled per row).
const Switch = ({ on, onChange, disabled, label, title }) => (
  <button type="button" role="switch" aria-checked={on} aria-label={label}
    disabled={disabled} title={title} onClick={() => !disabled && onChange(!on)}
    style={{ position: "relative", width: 30, height: 17, padding: 0, flex: "none",
             cursor: disabled ? "default" : "pointer",
             border: `1px solid ${on ? "var(--accent)" : "var(--borderHov)"}`,
             borderRadius: RADIUS.pill, opacity: disabled ? 0.45 : 1,
             background: on ? "var(--accentMut)" : "var(--bg1)",
             transition: `background ${MOTION.hover}, border-color ${MOTION.hover}` }}>
    <span aria-hidden="true" style={{ position: "absolute", top: 2, left: on ? 15 : 2,
      width: 11, height: 11, borderRadius: "50%",
      background: on ? "var(--accent)" : "var(--textMut)",
      boxShadow: "0 1px 2px rgba(0,0,0,0.35)",
      transition: `left ${MOTION.state}, background ${MOTION.state}` }} />
  </button>
);

// Compact − n + stepper. Eight numbered pills for the shot count was the loudest
// row in the old dialog for the least-changed setting.
const Stepper = ({ value, min, max, onChange, disabled, label }) => {
  const btn = (dir, Icon, edge) => (
    <button type="button" disabled={disabled || edge}
      aria-label={`${dir > 0 ? "more" : "fewer"} ${label}`}
      onClick={() => onChange(Math.min(max, Math.max(min, value + dir)))}
      style={{ width: 26, height: 26, padding: 0, display: "inline-flex",
               alignItems: "center", justifyContent: "center",
               cursor: disabled || edge ? "default" : "pointer",
               border: "1px solid var(--border)", borderRadius: RADIUS.pill,
               background: "transparent",
               color: disabled || edge ? "var(--textMut)" : "var(--textSec)" }}>
      <Icon size={11} weight="bold" />
    </button>
  );
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: SPACE[8],
                  opacity: disabled ? 0.6 : 1 }}>
      {btn(-1, Minus, value <= min)}
      <span style={{ minWidth: 18, textAlign: "center", fontSize: TYPE.body,
                     fontWeight: W.heading, color: "var(--text)",
                     fontVariantNumeric: "tabular-nums" }}>{value}</span>
      {btn(1, Plus, value >= max)}
    </div>
  );
};

// A fine-tune row: micro label in a fixed left column, control + caption right.
// The fixed column is what makes six settings read as one table instead of six
// stacked headings.
const Row = ({ label, hint, children }) => (
  <div style={{ display: "grid", gridTemplateColumns: "92px minmax(0,1fr)",
                gap: SPACE[10], alignItems: "start" }}>
    <span style={{ ...MICRO, paddingTop: 7 }}>{label}</span>
    <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: SPACE[6] }}>
      {children}
      {hint && <span style={CAPTION}>{hint}</span>}
    </div>
  </div>
);

// One "+ add LoRA" trigger with a searchable popover, replacing a header
// button per addable LoRA - which stopped scaling the day the catalog did.
// Esc and click-away close the popover WITHOUT closing the dialog (the
// stopPropagation is what keeps the window-level Esc handler out of it).
const AddLora = ({ options, onAdd }) => {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const boxRef = useRef(null);
  const inputRef = useRef(null);
  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const away = (e) => { if (!boxRef.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  if (!options.length) return null;
  const needle = q.trim().toLowerCase();
  const hits = options.filter((item) =>
    !needle || [item.title, item.name, item.trigger, item.description]
      .some((field) => String(field || "").toLowerCase().includes(needle)));
  const pick = (item) => { onAdd(item); setOpen(false); setQ(""); };
  return (
    <div ref={boxRef} style={{ position: "relative", flex: "none" }}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); setQ(""); }
      }}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        title="add a LoRA to the chain"
        style={{ height: 28, padding: `0 ${SPACE[10]}px`, display: "inline-flex",
                 alignItems: "center", gap: SPACE[4], cursor: "pointer",
                 border: `1px solid ${open ? "var(--borderStr)" : "var(--borderHov)"}`,
                 borderRadius: RADIUS.pill,
                 background: open ? "var(--bg3)" : "transparent",
                 color: "var(--textSec)", fontFamily: FONT, fontSize: 11,
                 transition: `background ${MOTION.hover}, border-color ${MOTION.hover}` }}>
        <Plus size={12} weight="bold" /> add LoRA
        <span style={{ color: "var(--textTer)" }}>{options.length}</span>
      </button>
      {open && (
        <div className="px-ov-pop" style={{ position: "absolute", right: 0, top: "calc(100% + 6px)",
                      transformOrigin: "top right",
                      width: 264, zIndex: 5, padding: SPACE[4],
                      background: "var(--bg1)", border: "1px solid var(--borderHov)",
                      borderRadius: RADIUS.card, boxShadow: SHADOW.lg,
                      display: "flex", flexDirection: "column", gap: SPACE[4] }}>
          {options.length > 6 && (
            <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="find a LoRA…" className="px-input" spellCheck={false}
              style={{ width: "100%", height: 28, padding: `0 ${SPACE[8]}px`,
                       background: "var(--bg2)", border: "1px solid var(--border)",
                       borderRadius: RADIUS.input, outline: "none",
                       color: "var(--text)", fontFamily: FONT, fontSize: 12 }} />
          )}
          <div className="px-scroll" style={{ maxHeight: 236, overflowY: "auto",
                        display: "flex", flexDirection: "column" }}>
            {hits.map((item) => (
              <button key={item.name} type="button" onClick={() => pick(item)}
                title={item.description || item.name}
                style={{ display: "flex", flexDirection: "column", alignItems: "stretch",
                         gap: 1, padding: `${SPACE[6]}px ${SPACE[8]}px`, textAlign: "left",
                         background: "transparent", border: "none",
                         borderRadius: RADIUS.input, cursor: "pointer", fontFamily: FONT }}>
                <span style={{ fontSize: 12, color: "var(--text)", overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {item.title}
                </span>
                <span style={{ fontSize: 9, color: "var(--textTer)", overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {item.trigger ? `trigger: ${item.trigger}` : "no trigger"}
                </span>
              </button>
            ))}
            {!hits.length && (
              <span style={{ padding: SPACE[8], fontSize: 11, color: "var(--textTer)" }}>
                nothing matches “{q.trim()}”
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// ------------------------------------------------------------ model grouping
// Where a finetune's base comes from (9.21, verified against server.py):
// h3_model_options only ever chips a diffusion file whose basename carries
// "fl2va" or "ref2va", and the chip id IS that lowercase filename stem - so
// the id itself proves the base. Nothing richer exists: model_profile() only
// files the whole "Minimax H3\" folder as family "video", and the scraped
// _civitai_models.json says base "MiniMax H3" for the one community build it
// has a hit for at all - neither can tell FL2VA from REF2VA. The filename
// token is the only honest source, and the server's own precedence is kept
// (h3_model_variant): ref2va before fl2va, so a stem naming both lands in
// ref2va, deterministically.
const modelBaseId = (id) => {
  const low = String(id || "").toLowerCase();
  if (low.includes("ref2va")) return "ref2va";
  if (low.includes("fl2va")) return "fl2va";
  return null;
};

// One group per base token, stock build first (it is the base the finetunes
// are OF), finetunes behind it in server order. A model whose id carries no
// token has no provable base - it comes back in `loose`, so the caller shows
// one flat list rather than inventing a family for it.
const groupModels = (models) => {
  const groups = [];
  const byBase = {};
  const loose = [];
  (models || []).forEach((m) => {
    const baseId = modelBaseId(m.id);
    if (!baseId) { loose.push(m); return; }
    if (!byBase[baseId]) {
      byBase[baseId] = { baseId, label: baseId.toUpperCase(), models: [] };
      groups.push(byBase[baseId]);
    }
    if (m.id === baseId) byBase[baseId].label = m.label;
    byBase[baseId].models.push(m);
  });
  groups.forEach((g) => g.models.sort(
    (a, b) => (a.id === g.baseId ? -1 : b.id === g.baseId ? 1 : 0)));
  return { groups, loose };
};

// The build picker: one base's stock build plus its finetunes, at full name.
// AddLora's popover mechanics (Esc closes the list, never the dialog; a
// pointer elsewhere closes it) wearing the ScrollPicker trigger shape - the
// selected build readable at rest, the whole name in the title when it has
// to clip. A segmented track cannot hold a community finetune name; this
// holds twenty.
const ModelPicker = ({ label, options, value, onChange }) => {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const boxRef = useRef(null);
  const inputRef = useRef(null);
  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const away = (e) => { if (!boxRef.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  const current = options.find((opt) => opt.id === value);
  const needle = q.trim().toLowerCase();
  const hits = options.filter((opt) => !needle ||
    `${opt.label} ${opt.description || ""}`.toLowerCase().includes(needle));
  const choose = (opt) => { onChange(opt.id); setOpen(false); setQ(""); };
  return (
    <div ref={boxRef} style={{ position: "relative" }}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); setQ(""); }
      }}>
      <button type="button" aria-haspopup="listbox" aria-expanded={open}
        aria-label={label} title={current ? current.label : label}
        onClick={() => setOpen((o) => !o)}
        style={{ width: "100%", height: 28, display: "flex", alignItems: "center",
                 gap: SPACE[8], padding: `0 ${SPACE[10]}px`, cursor: "pointer",
                 background: "var(--bg2)",
                 border: `1px solid ${open ? "var(--borderStr)" : "var(--border)"}`,
                 borderRadius: RADIUS.input, fontFamily: FONT, fontSize: TYPE.ui,
                 color: "var(--text)", textAlign: "left",
                 transition: `border-color ${MOTION.hover}` }}>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {current ? current.label : "choose a build…"}
        </span>
        <CaretDown size={11} weight="bold" style={{ color: "var(--textTer)",
          flex: "none", transform: open ? "rotate(180deg)" : "none",
          transition: `transform ${MOTION.hover}` }} />
      </button>
      {open && (
        <div role="listbox" aria-label={label} className="px-ov-pop"
          style={{ position: "absolute", left: 0, right: 0, top: "calc(100% + 6px)",
                   transformOrigin: "top center",
                   zIndex: 5, padding: SPACE[4], background: "var(--bg1)",
                   border: "1px solid var(--borderHov)", borderRadius: RADIUS.card,
                   boxShadow: SHADOW.lg, display: "flex", flexDirection: "column",
                   gap: SPACE[4] }}>
          {options.length > 6 && (
            <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="find a build…" className="px-input" spellCheck={false}
              style={{ width: "100%", height: 28, padding: `0 ${SPACE[8]}px`,
                       background: "var(--bg2)", border: "1px solid var(--border)",
                       borderRadius: RADIUS.input, outline: "none",
                       color: "var(--text)", fontFamily: FONT, fontSize: 12 }} />
          )}
          <div className="px-scroll" style={{ maxHeight: 236, overflowY: "auto",
                        display: "flex", flexDirection: "column" }}>
            {hits.map((opt) => {
              const on = opt.id === value;
              return (
                <button key={opt.id} type="button" role="option" aria-selected={on}
                  onClick={() => choose(opt)} title={opt.label}
                  style={{ display: "flex", flexDirection: "column",
                           alignItems: "stretch", gap: 1,
                           padding: `${SPACE[6]}px ${SPACE[8]}px`, textAlign: "left",
                           background: on ? "var(--accentMut)" : "transparent",
                           border: "none", borderRadius: RADIUS.input,
                           cursor: "pointer", fontFamily: FONT }}>
                  <span style={{ fontSize: 12, overflow: "hidden",
                                 textOverflow: "ellipsis", whiteSpace: "nowrap",
                                 color: on ? "var(--accent)" : "var(--text)" }}>
                    {opt.label}
                  </span>
                  {opt.description && (
                    <span style={{ fontSize: 9, color: "var(--textTer)",
                                   overflow: "hidden", textOverflow: "ellipsis",
                                   whiteSpace: "nowrap" }}>
                      {opt.description}
                    </span>
                  )}
                </button>
              );
            })}
            {!hits.length && (
              <span style={{ padding: SPACE[8], fontSize: 11, color: "var(--textTer)" }}>
                nothing matches “{q.trim()}”
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// The model companies' marks, not generic glyphs: Lightricks makes LTX,
// MiniMax makes H3. Mono when idle; the active segment keeps MiniMax's color.
const ENGINE_ICONS = { ltx: LightricksMark, ltx25: LightricksMark, h3: MiniMaxMark };

export const MotionDirector = ({ onClose, onAction, options, history = [],
                                 sourceId }) => {
  const engines = options?.video_engines?.length
    ? options.video_engines : FALLBACK_ENGINES;
  // The Settings-chosen default engine opens first when it can actually run;
  // otherwise the server's order decides, same as before the setting existed.
  const firstEngine = engines.find((item) => item.default && item.available !== false)
    || engines.find((item) => item.available !== false) || engines[0];
  const [note, setNote] = useState("");
  const [engineId, setEngineId] = useState(firstEngine?.id || "ltx25");
  const activeEngine = engines.find((item) => item.id === engineId) || firstEngine;
  const lengths = activeEngine?.lengths?.length ? activeEngine.lengths : LENGTHS;
  // Only engines that expose a rate get the control; H3's is fixed by its
  // trained frame counts, so offering one there would be a lie.
  const fpsChoices = activeEngine?.fps_choices || [];
  const availableModels = (activeEngine?.models || [])
    .filter((item) => item.available !== false);
  const [secs, setSecs] = useState(defaultLength(firstEngine).s);
  const [fps, setFps] = useState(firstEngine?.fps_default || 30);
  // Shots chain one take into the next, each starting from the previous take's
  // last frame. Only H3 does it, and only with its node pack installed - the
  // server reports the ceiling so a missing pack simply hides the row.
  const [shots, setShots] = useState(1);
  const shotsMax = Math.max(1, Number(activeEngine?.shots_max) || 1);
  // Each turbo mode is a whole recipe - step count, sampler, scheduler and a
  // distillation LoRA at a tested strength - not a speed dial. They are listed
  // by the server, which also reports whether each one's LoRA is actually on
  // disk; a missing file greys the segment instead of rendering 4 steps raw.
  const [speed, setSpeed] = useState("");
  const speedModes = activeEngine?.speed_modes || [];
  const defaultSpeed = activeEngine?.speed_default || "quality";
  const speedMode = speedModes.find((m) => m.id === speed && m.available !== false)
    || speedModes.find((m) => m.id === defaultSpeed) || speedModes[0] || null;
  // A pasted script wins over the chips - the shots row then shows what will
  // actually run rather than a count the script is about to override.
  const isScript = shotsMax > 1 && SHOT_SPLIT.test(note);
  const activeShots = isScript
    ? Math.min(countShots(note), shotsMax)
    : Math.min(shots, shotsMax);
  const [model, setModel] = useState(
    ((firstEngine?.models || []).find((item) => item.default && item.available !== false)
     || (firstEngine?.models || []).find((item) => item.available !== false))?.id || "default");
  // FL2VA bridge: a second finished render pinned as the clip's exact FINAL
  // frame. H3-only, one continuous take by definition - the state survives
  // engine/shot flips but is only ever SENT when the combination is legal.
  const [endId, setEndId] = useState("");
  const bridgeChoices = (history || []).filter((e) => e.id !== sourceId &&
    (e.images || []).some((im) => (im.media || "image") === "image")).slice(0, 8);
  const [videoLoraPlans, setVideoLoraPlans] = useState(loadVideoLoraPlans);
  // The fold remembers whether this user works with it open - a power user
  // should not pay a click per clip for yesterday's choice.
  const [fineTune, setFineTune] = useState(() => {
    try { return window.localStorage.getItem(FINE_TUNE_OPEN_KEY) === "1"; }
    catch { return false; }
  });
  const taRef = useRef(null);
  // The vram_note's way out: lighter curated builds of the same model family,
  // listed on demand and fetched one at a time server-side. Progress rides the
  // quant_fetch SSE events; fetchRef pins which download this dialog asked for.
  const [lighter, setLighter] = useState(null);
  const [fetchProg, setFetchProg] = useState(null);
  const fetchRef = useRef(null);
  const activeModel = availableModels.find((item) => item.id === model) || availableModels[0];
  // Eligibility reads activeModel, so it has to be declared below it - as a
  // `const` it would otherwise throw in the dead zone at render time, which
  // builds clean and ships a blank dialog. REF2VA is EXCLUDED rather than
  // FL2VA required, because that is precisely what the server refuses
  // ("bridging is FL2VA-only", server.py); requiring fl2va would be stricter
  // than the server and would block a tokenless finetune it would have run.
  const bridgeEligible = activeEngine?.id === "h3" && activeShots === 1
    && !isScript && modelBaseId(activeModel?.id) !== "ref2va";
  // Base first, then its builds: a finetune belongs to exactly one base, so
  // picking the family narrows the list - the architecture the flat row was
  // missing (9.21). The segmented track only ever lists families (short stock
  // labels); long community names live in the picker, never in a segment.
  const { groups: modelGroups, loose: looseModels } = groupModels(availableModels);
  const modelsSplit = modelGroups.length > 0 && looseModels.length === 0;
  const activeGroup = modelGroups.find(
    (g) => g.models.some((m) => m.id === activeModel?.id)) || modelGroups[0];
  // A base flip lands on the family's stock build, but remembering each
  // family's last pick means flipping away and back never loses the finetune
  // the user was on.
  const baseMemory = useRef({});
  const pickModel = (id) => {
    const baseId = modelBaseId(id);
    if (baseId) baseMemory.current = { ...baseMemory.current, [baseId]: id };
    setModel(id);
  };
  const pickBase = (baseId) => {
    const group = modelGroups.find((g) => g.baseId === baseId);
    if (!group || !group.models.length) return;
    const remembered = baseMemory.current[baseId];
    setModel(group.models.some((m) => m.id === remembered)
      ? remembered : group.models[0].id);
  };
  // The BASE, not the id. A finetune's id is its own filename stem
  // (`10eros_max_fl2va_skip_edges`), so this gate stopped firing for every
  // finetune OF fl2va the moment the model row split into bases and builds -
  // the whole chain vanished with no error, though the server had already
  // attached a real `loras` array to that very entry.
  const showVideoLoraChain = activeEngine?.id === "h3"
    && modelBaseId(activeModel?.id) === "fl2va";
  const videoLoraCatalog = showVideoLoraChain ? (activeModel?.loras || []) : [];
  const activePlanKey = videoPlanKey(activeEngine?.id || "", activeModel?.id || model || "");
  const activeVideoPlan = normalizeVideoPlan(
    videoLoraPlans[activePlanKey], activeEngine?.id, activeModel?.id, videoLoraCatalog);
  const activeNames = new Set(activeVideoPlan.entries.map((row) => row.name.toLowerCase()));
  const addableVideoLoras = videoLoraCatalog.filter(
    (item) => item.available !== false && !activeNames.has(item.name.toLowerCase()));

  useEffect(() => {
    taRef.current?.focus();
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  useEffect(() => subscribe((ev) => {
    if (ev.type !== "quant_fetch" || ev.filename !== fetchRef.current) return;
    setFetchProg({ name: ev.filename, got: ev.got || 0, total: ev.total,
                   done: Boolean(ev.done), error: ev.error || null });
  }), []);

  useEffect(() => {
    try {
      window.localStorage.setItem(VIDEO_LORA_STORAGE_KEY, JSON.stringify(videoLoraPlans));
    } catch { /* private mode / storage disabled */ }
  }, [videoLoraPlans]);

  const toggleFineTune = () => setFineTune((open) => {
    try { window.localStorage.setItem(FINE_TUNE_OPEN_KEY, open ? "0" : "1"); }
    catch { /* private mode / storage disabled */ }
    return !open;
  });

  const chooseEngine = (id) => {
    const item = engines.find((choice) => choice.id === id);
    if (!item || item.available === false) return;
    setEngineId(item.id);
    setSecs(defaultLength(item).s);
    setFps(item.fps_default || 30);
    setShots(1);
    setModel(((item.models || []).find((choice) => choice.default && choice.available !== false)
              || (item.models || []).find((choice) => choice.available !== false))?.id || "default");
  };

  const findLighter = async () => {
    const engine = activeEngine?.id;
    if (!engine) return;
    setLighter({ engine, loading: true });
    try {
      const r = await fetch(`/api/quant_alternatives?engine=${encodeURIComponent(engine)}`);
      const d = await r.json();
      setLighter(d.ok ? { ...d, engine }
                      : { engine, error: d.error || "no answer from the server" });
    } catch (e) {
      setLighter({ engine, error: String(e) });
    }
  };

  const fetchQuant = async (f) => {
    fetchRef.current = f.filename;
    setFetchProg({ name: f.filename, got: 0, total: f.size, done: false, error: null });
    try {
      const r = await fetch("/api/quant_fetch", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo: f.repo, filename: f.filename, kind: f.kind }),
      });
      const d = await r.json();
      if (!d.ok)
        setFetchProg((cur) => ({ ...cur, done: true,
                                 error: d.error || "fetch refused" }));
    } catch (e) {
      setFetchProg((cur) => ({ ...cur, done: true, error: String(e) }));
    }
  };

  const updateVideoLoraRows = (change) => {
    if (!showVideoLoraChain) return;
    setVideoLoraPlans((plans) => {
      const current = normalizeVideoPlan(
        plans[activePlanKey], activeEngine.id, activeModel.id, videoLoraCatalog);
      return { ...plans, [activePlanKey]: { ...current, entries: change(current.entries) } };
    });
  };

  const patchVideoLora = (index, patch) => updateVideoLoraRows((rows) =>
    rows.map((row, i) => i === index ? { ...row, ...patch } : row));

  const moveVideoLora = (index, delta) => updateVideoLoraRows((rows) => {
    const nextIndex = index + delta;
    if (nextIndex < 0 || nextIndex >= rows.length) return rows;
    const next = [...rows];
    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
    return next;
  });

  const go = (hint) => {
    if (!activeEngine || activeEngine.available === false || !model) return;
    onAction(isScript ? null : hint, secs, activeEngine.id, model,
      showVideoLoraChain ? activeVideoPlan : null,
      fpsChoices.length ? fps : null, activeShots,
      isScript ? note.trim() : null, speedMode ? speedMode.id : null,
      bridgeEligible && endId ? endId : null);
    onClose();
  };

  // What the fold is hiding, told on its collapsed row. Every entry is a
  // NON-default - the row stays empty on a stock take, so a word appearing
  // there always means something.
  const activeLoraCount = activeVideoPlan.entries.filter((row) => {
    const item = videoLoraCatalog.find(
      (choice) => choice.name.toLowerCase() === row.name.toLowerCase());
    return row.enabled && item?.available !== false;
  }).length;
  const tweaks = [];
  if (availableModels.length > 1 && activeModel &&
      activeModel.id !== availableModels[0].id) tweaks.push(activeModel.label);
  if (isScript) tweaks.push(`${activeShots}-shot script`);
  else if (activeShots > 1) tweaks.push(`${activeShots} shots`);
  if (bridgeEligible && endId) tweaks.push("end frame set");
  if (speedMode && speedMode.id !== defaultSpeed) tweaks.push(speedMode.label.toLowerCase());
  if (fpsChoices.length > 1 && fps !== (activeEngine?.fps_default || 30))
    tweaks.push(`${fps}fps`);
  if (showVideoLoraChain && activeLoraCount > 0)
    tweaks.push(`${activeLoraCount} LoRA${activeLoraCount > 1 ? "s" : ""}`);

  const activeLength = lengths.find((l) => l.s === secs);
  // The ladder only shows for the engine it was fetched for - switching
  // engines mid-list must not offer another family's builds.
  const ladder = lighter && lighter.engine === activeEngine?.id ? lighter : null;
  const fetching = Boolean(fetchProg && !fetchProg.done);

  return (
    <ModalShell onClose={onClose} boxStyle={{
      width: 560, maxWidth: "94vw", maxHeight: "90vh", overflowY: "auto",
      background: "var(--bg1)", border: "1px solid var(--borderHov)",
      borderRadius: 20, boxShadow: SHADOW.xl, padding: SPACE[20],
      display: "flex", flexDirection: "column", gap: SPACE[16], fontFamily: FONT,
    }}>
        <div style={{ display: "flex", alignItems: "center", gap: SPACE[8] }}>
          <FilmStrip size={17} weight="duotone" style={{ color: "var(--accent)" }} />
          <span style={{ fontSize: TYPE.h3, fontWeight: W.heading, color: "var(--text)" }}>
            Direct the clip
          </span>
          <button type="button" onClick={onClose} title="close"
            style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center",
                     justifyContent: "center", width: 30, height: 30,
                     background: "var(--bg2)", border: "1px solid var(--border)",
                     borderRadius: RADIUS.pill, color: "var(--textTer)", cursor: "pointer" }}>
            <X size={14} weight="bold" />
          </button>
        </div>

        {/* ZONE 1 - the brief. The note IS the product; it gets the room. */}
        <div style={{ display: "flex", flexDirection: "column", gap: SPACE[6] }}>
          <textarea
            ref={taRef} value={note} rows={4}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(note.trim() || null); }
            }}
            placeholder={"What happens? Action, camera, pacing — your words become the brief.\n" +
              "“she pushes off the hood, turns and laughs — handheld follows her”"}
            className="px-input"
            style={{
              width: "100%", resize: "none", background: "var(--bg2)",
              border: "1px solid var(--border)", borderRadius: RADIUS.card,
              outline: "none", color: "var(--text)", fontFamily: FONT, fontSize: 13,
              lineHeight: 1.5, padding: SPACE[12],
            }}
          />
          {isScript && (
            <span style={CAPTION}>
              script mode — {activeShots} shot{activeShots > 1 ? "s" : ""} sent verbatim,
              the director stays out of it
              {countShots(note) > shotsMax ? ` (capped at ${shotsMax})` : ""}
            </span>
          )}
        </div>

        {/* ZONE 2 - the two decisions every clip needs. Everything else is
            fine print, and lives below the fold. */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE[12] }}>
          <div style={{ display: "flex", flexDirection: "column", gap: SPACE[6] }}>
            <span style={MICRO}>engine</span>
            <SegmentedControl ariaLabel="video engine" value={engineId} onChange={chooseEngine}
              options={engines.map((item) => ({
                v: item.id, label: item.label, Icon: ENGINE_ICONS[item.id],
                disabled: item.available === false,
                title: item.available === false
                  ? (item.missing || []).join("\n") || `${item.label} is unavailable`
                  : [item.description || item.tag,
                     item.vram_note ? `⚠ ${item.vram_note}` : null]
                      .filter(Boolean).join("\n"),
              }))} />
            {/* A starved engine stays PICKABLE - the note is honest ("runs,
                ~5x slower"), never a block; the butler decides at render time.
                One-fact line: nowrap + ellipsis + title. */}
            <span title={activeEngine?.vram_note || undefined}
              style={{ ...CAPTION,
                       ...(activeEngine?.vram_note
                         ? { color: "var(--error)", whiteSpace: "nowrap",
                             overflow: "hidden", textOverflow: "ellipsis" }
                         : null) }}>{activeEngine?.vram_note || activeEngine?.tag || activeEngine?.description || " "}</span>
            {/* A starved note is actionable when the family ships lighter
                builds: one click lists the ladder, one more fetches a rung.
                Mono 10px - the register every status line in the app uses. */}
            {activeEngine?.vram_note && activeEngine?.quant_hint && (
              <div style={{ display: "flex", flexDirection: "column", gap: SPACE[4] }}>
                {ladder?.error && (
                  <span style={{ ...CAPTION, color: "var(--error)" }}>{ladder.error}</span>
                )}
                {!fetchProg && (!ladder || ladder.error) && (
                  <button type="button" onClick={findLighter}
                    title="list lighter quantized builds of this model on Hugging Face"
                    style={{ alignSelf: "flex-start", height: 28,
                             padding: `0 ${SPACE[10]}px`, display: "inline-flex",
                             alignItems: "center", cursor: "pointer",
                             border: "1px solid var(--borderHov)",
                             borderRadius: RADIUS.pill, background: "transparent",
                             color: "var(--textSec)", fontFamily: FONT, fontSize: 11,
                             transition: `background ${MOTION.hover}, border-color ${MOTION.hover}` }}>
                    find a lighter build
                  </button>
                )}
                {ladder?.loading && <span style={CAPTION}>asking hugging face…</span>}
                {ladder?.files && (
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    {ladder.files.map((f) => (
                      <button key={`${f.repo}/${f.filename}`} type="button"
                        disabled={fetching} onClick={() => fetchQuant(f)}
                        title={`${f.repo}/${f.filename}`}
                        style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                                 padding: `${SPACE[6]}px ${SPACE[8]}px`, textAlign: "left",
                                 background: "transparent", border: "none",
                                 borderRadius: RADIUS.input, fontFamily: FONT,
                                 cursor: fetching ? "default" : "pointer",
                                 opacity: fetching ? 0.45 : 1 }}>
                        <span style={{ flex: 1, minWidth: 0, fontSize: 12,
                                       color: "var(--text)", overflow: "hidden",
                                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {f.filename.split("/").pop()}
                        </span>
                        <span style={{ fontFamily: "ui-monospace, Consolas, monospace",
                                       fontSize: 10, color: "var(--textTer)",
                                       flexShrink: 0 }}>
                          {(f.size / 1e9).toFixed(1)} GB
                        </span>
                        <span style={{ fontFamily: "ui-monospace, Consolas, monospace",
                                       fontSize: 9, letterSpacing: "0.06em",
                                       textTransform: "uppercase", flexShrink: 0,
                                       padding: "1px 6px", borderRadius: RADIUS.pill,
                                       background: f.picked ? "var(--accentMut)" : "var(--bg3)",
                                       border: `1px solid ${f.picked ? "var(--accentStr)" : "var(--border)"}`,
                                       color: f.picked ? "var(--accent)" : "var(--textTer)" }}>
                          {f.blackwell_only ? "blackwell only" : f.fits ? "fits" : "too big"}
                        </span>
                      </button>
                    ))}
                    {!ladder.files.some((f) => f.fits) && (
                      <span style={CAPTION}>
                        nothing fits {Math.round(ladder.budget_gb)} GB — the smallest is listed above
                      </span>
                    )}
                  </div>
                )}
                {fetchProg && (
                  <span style={{ fontFamily: "ui-monospace, Consolas, monospace",
                                 fontSize: 10,
                                 color: fetchProg.error ? "var(--error)" : "var(--textTer)",
                                 whiteSpace: "nowrap", overflow: "hidden",
                                 textOverflow: "ellipsis" }}>
                    {fetchProg.error ? fetchProg.error
                      : fetchProg.done ? `${fetchProg.name.split("/").pop()} — downloaded`
                      : `${(fetchProg.got / 1e9).toFixed(1)}/${fetchProg.total ? (fetchProg.total / 1e9).toFixed(1) : "?"} GB`}
                  </span>
                )}
              </div>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: SPACE[6] }}>
            <span style={MICRO}>{activeShots > 1 ? "length · per shot" : "length"}</span>
            <SegmentedControl ariaLabel="clip length" value={secs} onChange={setSecs}
              options={lengths.map((l) => ({ v: l.s, label: l.label, title: l.gloss }))} />
            <span style={CAPTION}>
              {activeLength?.gloss || ""}
              {activeShots > 1 ? ` · ~${activeShots * secs}s total` : ""}
            </span>
          </div>
        </div>

        {/* ZONE 3 - the fold. Its collapsed row narrates any non-default it
            hides, so closed never means forgotten. */}
        <Disclosure open={fineTune} onToggle={toggleFineTune}
          caretStyle={{ color: "var(--textTer)" }}
          style={{ display: "flex", flexDirection: "column", gap: SPACE[12] }}
          contentStyle={{ display: "flex", flexDirection: "column", gap: SPACE[12] }}
          trigger={<>
            <span style={{ ...MICRO, color: "var(--textSec)" }}>fine-tune</span>
            {!fineTune && tweaks.length > 0 && (
              <span style={{ ...CAPTION, overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}>{tweaks.join(" · ")}</span>
            )}
            <span aria-hidden="true"
              style={{ flex: 1, borderTop: "1px solid var(--border)", minWidth: SPACE[12] }} />
          </>}>
              {availableModels.length > 1 && (
                <Row label="model"
                  hint={activeModel?.nsfw
                    ? "NSFW finetune — distill LoRA chained automatically"
                    : activeModel?.description || null}>
                  {modelsSplit ? (
                    <>
                      {modelGroups.length > 1 && (
                        <SegmentedControl ariaLabel={`${activeEngine?.label || "video"} model family`}
                          size="sm" value={activeGroup?.baseId} onChange={pickBase}
                          options={modelGroups.map((g) => ({
                            v: g.baseId, label: g.label,
                            title: (g.models.find((m) => m.id === g.baseId)
                              || g.models[0])?.description || g.label,
                          }))} />
                      )}
                      {activeGroup?.models.length > 1 && (
                        <ModelPicker label={`${activeGroup.label} build`}
                          options={activeGroup.models} value={activeModel?.id}
                          onChange={pickModel} />
                      )}
                    </>
                  ) : (
                    <ModelPicker label={`${activeEngine?.label || "video"} model`}
                      options={availableModels} value={activeModel?.id}
                      onChange={pickModel} />
                  )}
                </Row>
              )}

              {shotsMax > 1 && (
                <Row label={<>shots <InfoTip size={11} text={"Shots chain end to end: each one starts from the last frame of the take before. Or write the note as a script — shots separated by --- on its own line ship verbatim, and the script sets the count."} /></>}
                  hint={isScript
                    ? "counted from your script — each shot renders and chains in order"
                    : activeShots === 1
                      ? "one continuous take"
                      : `~${activeShots * secs}s total — each shot continues from the last frame of the one before`}>
                  <Stepper label="shots" value={activeShots} min={1} max={shotsMax}
                    disabled={isScript} onChange={setShots} />
                </Row>
              )}

              {activeEngine?.id === "h3" && (
                <Row label="end frame"
                  hint={!bridgeEligible
                    ? "single continuous takes only — set shots to 1"
                    : bridgeChoices.length === 0
                      ? "render another still first — the clip can converge on it"
                      : endId ? "the clip converges on the selected frame"
                      : "optional — end the clip exactly on another render"}>
                  <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                                flexWrap: "wrap", opacity: bridgeEligible ? 1 : 0.45 }}>
                    <button type="button" disabled={!bridgeEligible}
                      onClick={() => setEndId("")}
                      title="no end frame - the clip ends wherever the motion lands"
                      style={{
                        height: 28, padding: `0 ${SPACE[10]}px`,
                        cursor: bridgeEligible ? "pointer" : "default",
                        border: `1px solid ${endId ? "var(--border)" : "var(--borderStr)"}`,
                        borderRadius: RADIUS.pill,
                        background: endId ? "transparent" : "var(--bg3)",
                        color: endId ? "var(--textTer)" : "var(--text)",
                        fontFamily: FONT, fontSize: TYPE.label,
                        transition: `border-color ${MOTION.hover}, color ${MOTION.hover}`,
                      }}>
                      none
                    </button>
                    {bridgeChoices.map((e) => {
                      const im = (e.images || []).find(
                        (i) => (i.media || "image") === "image");
                      const on = endId === e.id;
                      return (
                        <button key={e.id} type="button" disabled={!bridgeEligible}
                          onClick={() => setEndId(on ? "" : e.id)}
                          title={on ? "clear the end frame"
                            : (e.scene || "").slice(0, 90) || "end on this frame"}
                          style={{
                            padding: 2, lineHeight: 0,
                            cursor: bridgeEligible ? "pointer" : "default",
                            border: `2px solid ${on ? "var(--accent)" : "var(--border)"}`,
                            borderRadius: 10, background: "transparent",
                            transition: `border-color ${MOTION.hover}`,
                          }}>
                          <img src={thumbUrl(im)} alt="" loading="lazy"
                            style={{ width: 44, height: 44, objectFit: "cover",
                                     borderRadius: 7, display: "block",
                                     opacity: on ? 1 : 0.72 }} />
                        </button>
                      );
                    })}
                  </div>
                </Row>
              )}

              {fpsChoices.length > 1 && (
                <Row label="frame rate" hint={`${Math.round(secs * fps)} frames`}>
                  <SegmentedControl ariaLabel="frame rate" size="sm" value={fps} onChange={setFps}
                    options={fpsChoices.map((rate) => ({
                      v: rate, label: `${rate}fps`,
                      title: `${rate} frames per second`,
                    }))} />
                </Row>
              )}

              {speedModes.length > 1 && (
                <Row label="speed"
                  hint={speedMode
                    ? `${speedMode.gloss} · ${speedMode.sampler}`
                    : null}>
                  <SegmentedControl ariaLabel="speed" size="sm"
                    value={speedMode ? speedMode.id : defaultSpeed}
                    onChange={setSpeed}
                    options={speedModes.map((m) => ({
                      v: m.id, label: m.label, disabled: m.available === false,
                      title: m.available === false
                        ? `${m.label}: its LoRA is not in the loras folder, so this recipe can't run`
                        : `${m.label} — ${m.gloss}, ${m.sampler}`,
                    }))} />
                </Row>
              )}

              {showVideoLoraChain && (
                <div style={{ display: "flex", flexDirection: "column", gap: SPACE[6],
                              padding: SPACE[8], border: "1px solid var(--border)",
                              borderRadius: RADIUS.card, background: "var(--bg2)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: SPACE[6] }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={MICRO}>video LoRA chain</div>
                      <div style={{ fontSize: TYPE.micro, color: "var(--textTer)", marginTop: 2 }}>
                        top row loads first
                      </div>
                    </div>
                    <div style={{ flex: 1 }} />
                    <AddLora options={addableVideoLoras}
                      onAdd={(item) => updateVideoLoraRows((rows) => [...rows, {
                        name: item.name, strength: item.default_strength ?? 1, enabled: true,
                      }])} />
                  </div>
                  {activeVideoPlan.entries.length === 0 && (
                    <div style={{ padding: `${SPACE[6]}px ${SPACE[4]}px`, color: "var(--textTer)",
                                  fontSize: 11 }}>
                      No video LoRAs active. Add one when this clip needs it.
                    </div>
                  )}
                  {activeVideoPlan.entries.map((row, index) => {
                    const item = videoLoraCatalog.find(
                      (choice) => choice.name.toLowerCase() === row.name.toLowerCase());
                    const unavailable = item?.available === false;
                    return (
                      <div key={row.name} style={{ display: "grid",
                        gridTemplateColumns: "34px minmax(0,1fr) 70px 28px 28px 28px",
                        gap: 5, alignItems: "center", minHeight: 40,
                        padding: SPACE[4], border: "1px solid var(--border)",
                        borderRadius: RADIUS.card, opacity: unavailable ? 0.5 : 1 }}>
                        <Switch on={row.enabled} disabled={unavailable}
                          label={`${row.enabled ? "Disable" : "Enable"} ${item?.title || row.name}`}
                          title={row.enabled ? "disable this LoRA" : "enable this LoRA"}
                          onChange={(on) => patchVideoLora(index, { enabled: on })} />
                        <div style={{ minWidth: 0 }} title={row.name}>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis",
                                        whiteSpace: "nowrap",
                                        color: row.enabled ? "var(--text)" : "var(--textTer)",
                                        fontSize: 12 }}>
                            {index + 1}. {item?.title || row.name}
                          </div>
                          <div style={{ fontSize: 9, color: "var(--textTer)", marginTop: 1 }}>
                            {item?.trigger ? `trigger: ${item.trigger}` : "no trigger"}
                            {unavailable ? " - not installed" : ""}
                          </div>
                        </div>
                        <input type="number" step="0.05" value={row.strength}
                          aria-label={`${item?.title || row.name} strength`}
                          onChange={(event) => {
                            const value = Number(event.target.value);
                            if (Number.isFinite(value)) patchVideoLora(index, { strength: value });
                          }}
                          style={{ width: 70, height: 28, padding: "0 7px",
                                   border: "1px solid var(--border)", borderRadius: RADIUS.card,
                                   background: "var(--bg1)", color: "var(--text)",
                                   fontFamily: FONT, fontSize: 11 }} />
                        <button type="button" onClick={() => moveVideoLora(index, -1)}
                          disabled={index === 0} title="move earlier"
                          style={{ width: 28, height: 28, padding: 0, display: "inline-flex",
                                   alignItems: "center", justifyContent: "center", cursor: "pointer",
                                   border: "1px solid var(--border)", borderRadius: RADIUS.pill,
                                   background: "transparent", color: "var(--textTer)" }}>
                          <ArrowUp size={12} weight="bold" />
                        </button>
                        <button type="button" onClick={() => moveVideoLora(index, 1)}
                          disabled={index === activeVideoPlan.entries.length - 1} title="move later"
                          style={{ width: 28, height: 28, padding: 0, display: "inline-flex",
                                   alignItems: "center", justifyContent: "center", cursor: "pointer",
                                   border: "1px solid var(--border)", borderRadius: RADIUS.pill,
                                   background: "transparent", color: "var(--textTer)" }}>
                          <ArrowDown size={12} weight="bold" />
                        </button>
                        <button type="button" onClick={() => updateVideoLoraRows(
                          (rows) => rows.filter((_, i) => i !== index))} title="remove"
                          style={{ width: 28, height: 28, padding: 0, display: "inline-flex",
                                   alignItems: "center", justifyContent: "center", cursor: "pointer",
                                   border: "1px solid var(--border)", borderRadius: RADIUS.pill,
                                   background: "transparent", color: "var(--textTer)" }}>
                          <Trash size={12} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
        </Disclosure>

        {/* Footer - the commitment. "surprise me" ships without a note; the
            director animates what's already in the frame. */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end",
                      gap: SPACE[8] }}>
          <button type="button" onClick={() => go(null)}
            disabled={!activeEngine?.available || !model}
            title="no note - the director animates what's already in the frame"
            style={{
              height: 36, padding: `0 ${SPACE[16]}px`, cursor: "pointer",
              display: "inline-flex", alignItems: "center",
              background: "transparent", border: "1px solid var(--border)",
              borderRadius: RADIUS.pill, color: "var(--textSec)",
              fontFamily: FONT, fontSize: 13, whiteSpace: "nowrap",
            }}>
            surprise me
          </button>
          <button type="button" onClick={() => go(note.trim() || null)}
            disabled={!activeEngine?.available || !model}
            style={{
              height: 36, padding: `0 ${SPACE[20]}px`, cursor: "pointer",
              display: "inline-flex", alignItems: "center",
              background: "var(--accent)", border: "none",
              borderRadius: RADIUS.pill, color: "var(--accentInk)",
              fontFamily: FONT, fontSize: 13, fontWeight: W.heading,
            }}>
            action
          </button>
        </div>
    </ModalShell>
  );
};
