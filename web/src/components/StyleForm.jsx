// StyleForm.jsx — create OR edit a saved style: the graph it runs on, the
// model, the exact sampler schedule, the LoRA stack, and a name of your own.
// Saved as data to pixal_dm/recipes/<id>.json, the same way characters are.
//
// It opens pre-filled from whatever the composer is set to right now, because
// that is how styles actually get authored: you tune a render until it is
// right, then name it. Starting from an empty form would mean re-picking
// everything you just picked — so the dialog's whole story is "name it, save
// it", with everything else a quiet cluster you only open to double-check.
//
// The sampler section is deliberately not a free text box. Which settings even
// EXIST depends on the base+model pairing — Z-Image Turbo replaces its KSampler
// with a sigma schedule and has none, and RES4LYF's Clownshar sampler takes
// compound names ("linear/euler") a stock KSampler rejects — so the options come
// from the server, which reads them out of ComfyUI's own /object_info.
import { useEffect, useMemo, useState } from "react";
import { CaretDown, Palette, X } from "@phosphor-icons/react";
import { FONT, W, TYPE, SPACE, RADIUS, MOTION } from "../lib/design-tokens.js";
import { styleSampler } from "../transport.js";
import { buildLoraPlan, defaultLoraEntries } from "../store.js";
import { LoraChain } from "./Composer.jsx";

const MONO = "ui-monospace, Consolas, monospace";

// The same field furniture as SettingsMenu: micro-caps label over the
// control, hairline cluster headings, 38px triggers with the caret in its own
// right-hand slot. The rhythm IS the design — one gap between clusters, one
// inside them.
const Field = ({ label, hint, children }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: SPACE[6] }}>
    {label && (
      <span style={{ fontSize: 10, color: "var(--textTer)", fontFamily: FONT,
                     textTransform: "uppercase", letterSpacing: "0.08em" }}>
        {label}
      </span>
    )}
    {children}
    {hint && (
      <span style={{ fontSize: TYPE.label, color: "var(--textTer)",
                     lineHeight: 1.5 }}>{hint}</span>
    )}
  </div>
);

const GroupLabel = ({ children, aside }) => (
  <div style={{ display: "flex", alignItems: "center", gap: SPACE[10] }}>
    <span style={{ fontSize: 10, fontWeight: W.heading, color: "var(--textMut)",
                   textTransform: "uppercase", letterSpacing: "0.12em",
                   fontFamily: FONT, whiteSpace: "nowrap" }}>{children}</span>
    <span aria-hidden="true" style={{ flex: 1, borderTop: "1px solid var(--border)" }} />
    {aside && (
      <span style={{ fontFamily: MONO, fontSize: 9, color: "var(--textMut)",
                     whiteSpace: "nowrap" }}>{aside}</span>
    )}
  </div>
);

const controlBase = {
  width: "100%", height: 38, background: "var(--bg2)",
  border: "1px solid var(--border)", borderRadius: RADIUS.input,
  color: "var(--text)", fontFamily: FONT, fontSize: TYPE.ui, outline: "none",
};

const hoverable = {
  onMouseEnter: (e) => { e.currentTarget.style.borderColor = "var(--borderHov)"; },
  onMouseLeave: (e) => { e.currentTarget.style.borderColor = "var(--border)"; },
};

// Native select for the dropdown itself (it is the one control the OS still
// does best), but the trigger is drawn by us: appearance off, caret in a
// padded slot instead of jammed against the label.
const Select = ({ value, onChange, children }) => (
  <div style={{ position: "relative" }}>
    <select value={value} onChange={onChange} {...hoverable}
      style={{ ...controlBase, appearance: "none", WebkitAppearance: "none",
               padding: `0 32px 0 ${SPACE[12]}px`, cursor: "pointer",
               transition: `border-color ${MOTION.hover}` }}>
      {children}
    </select>
    <CaretDown size={11} weight="bold" style={{
      position: "absolute", right: SPACE[12], top: "50%",
      transform: "translateY(-50%)", pointerEvents: "none",
      color: "var(--textTer)" }} />
  </div>
);

// An unset field means "whatever the recipe already does". That is the whole
// contract of the tuning block: it is a sparse override map, not a snapshot, so
// a style does not silently freeze a default that later improves.
const INHERIT = "";

export const StyleForm = ({ options, opts, draft, editId = "", onClose, onSaved }) => {
  const existing = useMemo(
    () => (options?.saved_styles || []).find((s) => s.id === editId) || null,
    [options, editId]);
  const seed = existing || draft || {};

  const [name, setName] = useState(seed.name || "");
  const [base, setBase] = useState(seed.base || "realism");
  const [model, setModel] = useState(seed.model || "");
  const [tuning, setTuning] = useState(seed.tuning || {});
  const [plan, setPlan] = useState(seed.lora_plan || null);
  const [sampler, setSampler] = useState(null);   // server's answer for base+model
  // The tuning cluster opens only when there is something to see: a style that
  // already overrides the recipe. A fresh save is "name it, save it".
  const [tuneOpen, setTuneOpen] = useState(
    () => Object.keys(seed.tuning || {}).length > 0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const bases = options?.style_bases || [];
  const recipeById = (id) => (options?.recipes || []).find((r) => r.id === id);
  const baseRecipe = recipeById(base);

  // Only models that can actually drive this graph. Offering the rest and
  // failing on save would be a worse version of the same information.
  const models = useMemo(() => (options?.models || []).filter((n) => {
    const m = (options.model_meta || {})[n] || {};
    return m.supported && !m.source_only && (m.compatible_recipes || []).includes(base);
  }), [options, base]);

  // Changing the base can strand a model from another family. Move to that
  // recipe's own default rather than leaving an invalid pairing on screen.
  useEffect(() => {
    if (model && models.includes(model)) return;
    setModel(models.includes(baseRecipe?.default_model)
      ? baseRecipe.default_model : (models[0] || ""));
  }, [base, models, baseRecipe, model]);

  // A plan belongs to ONE recipe: a Realism stack is meaningless on Anima, and
  // the server refuses it by name. Rebuild whenever the base moves, keeping the
  // user's own picks only while they still apply.
  const planOpts = useMemo(() => ({ ...opts, model }), [opts, model]);
  useEffect(() => {
    if (!baseRecipe || !Array.isArray(baseRecipe.lora_stages)) { setPlan(null); return; }
    setPlan((prev) => buildLoraPlan(
      baseRecipe,
      prev && prev.recipe === base ? prev.entries : defaultLoraEntries(baseRecipe),
      options, planOpts, prev && prev.recipe === base ? prev.core : undefined));
  }, [base, baseRecipe, options, planOpts]);

  // The seat is a property of the PAIRING, so re-ask on every change.
  useEffect(() => {
    let live = true;
    if (!base || !model) { setSampler(null); return undefined; }
    styleSampler(base, model)
      .then((d) => { if (live) setSampler(d?.ok ? d : null); })
      .catch(() => { if (live) setSampler(null); });
    return () => { live = false; };
  }, [base, model]);

  const setTune = (key, value) => setTuning((prev) => {
    const next = { ...prev };
    if (value === INHERIT || value === null) delete next[key];
    else next[key] = value;
    return next;
  });

  const defaults = sampler?.defaults || {};
  const choices = sampler?.options || {};
  const tunable = !!sampler?.tunable;
  // Which boxes this seat's node can even take. RES4LYF's Clownshar sampler has
  // eta; a stock KSampler has no such input, so drawing the box everywhere
  // would offer a setting the server refuses on save.
  const tunes = (key) => (sampler?.keys || ["steps", "cfg", "sampler_name", "scheduler"])
    .includes(key);
  const changed = Object.keys(tuning).length;

  const numberField = (key, label) => (
    <Field label={label}>
      <input {...hoverable}
        style={{ ...controlBase, padding: `0 ${SPACE[12]}px`,
                 transition: `border-color ${MOTION.hover}` }}
        inputMode="decimal" value={tuning[key] ?? ""}
        placeholder={defaults[key] !== undefined ? `${defaults[key]}` : "recipe"}
        onChange={(e) => {
          const raw = e.target.value.trim();
          if (!raw) return setTune(key, INHERIT);
          const n = Number(raw);
          return setTune(key, Number.isFinite(n) ? n : raw);
        }} />
    </Field>
  );

  const comboField = (key, label) => (
    <Field label={label}>
      <Select value={tuning[key] ?? INHERIT}
        onChange={(e) => setTune(key, e.target.value)}>
        <option value={INHERIT}>
          {defaults[key] !== undefined ? `recipe · ${defaults[key]}` : "recipe default"}
        </option>
        {(choices[key] || []).map((v) => <option key={v} value={v}>{v}</option>)}
      </Select>
    </Field>
  );

  const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const clash = !editId && slug
    && (options?.saved_styles || []).find((s) => s.id === slug);

  const save = async () => {
    if (!name.trim()) { setErr("give the style a name"); return; }
    if (!model) { setErr("choose the model this style runs on"); return; }
    setBusy(true); setErr(null);
    const record = {
      schema_version: 1, name: name.trim(), base, model,
      tuning: tunable ? tuning : {},
      ...(opts?.aspect ? { aspect: opts.aspect } : {}),
      ...(opts?.mp ? { mp: opts.mp } : {}),
      ...(plan ? { lora_plan: plan } : {}),
      ...(editId ? { id: editId } : {}),
      ...(existing?.provenance ? { provenance: existing.provenance } : {}),
    };
    const r = await onSaved(record);
    setBusy(false);
    if (r?.ok) onClose();
    else setErr(r?.error || "save failed");
  };

  const short = (n) => (n || "").split("\\").pop().split("/").pop()
    .replace(/\.(safetensors|gguf|ckpt|pt|pth)$/i, "");

  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 36, background: "rgba(0,0,0,0.5)" }}
           onClick={onClose} />
      <div className="px-scroll" style={{
        position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
        zIndex: 37, width: 460, maxWidth: "94vw", maxHeight: "86vh", overflowY: "auto",
        background: "var(--bg1)", border: "1px solid var(--borderHov)",
        borderRadius: RADIUS.dialog, boxShadow: "0 18px 44px rgba(0,0,0,0.6)",
        padding: SPACE[16], display: "flex", flexDirection: "column", gap: SPACE[16],
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: SPACE[6],
                         fontSize: TYPE.h3, fontWeight: W.heading }}>
            <Palette size={15} weight="duotone" style={{ color: "var(--accent)" }} />
            {editId ? `edit ${existing?.name || "style"}` : "new style"}
          </span>
          <button type="button" onClick={onClose}
            style={{ background: "none", border: "none", color: "var(--textTer)",
                     cursor: "pointer", padding: 4 }}>
            <X size={14} weight="bold" />
          </button>
        </div>

        {/* The name is the star — you just tuned the render, now you bottle it.
            No essay label; the dialog title already says what this is. */}
        <input {...hoverable} value={name} onChange={(e) => setName(e.target.value)}
               placeholder="name your style…" autoFocus
               style={{ ...controlBase, height: 44, fontSize: TYPE.h3,
                        fontWeight: W.nav, padding: `0 ${SPACE[12]}px`,
                        transition: `border-color ${MOTION.hover}` }} />

        <GroupLabel>runs on</GroupLabel>
        <Field label="base"
               hint={[baseRecipe?.tag, baseRecipe?.speed].filter(Boolean).join(" · ")}>
          <Select value={base} onChange={(e) => setBase(e.target.value)}>
            {bases.map((id) => (
              <option key={id} value={id}>{recipeById(id)?.label || id}</option>
            ))}
          </Select>
        </Field>
        <Field label="model"
               hint={models.length ? undefined
                 : `No installed model can drive ${baseRecipe?.label || base}.`}>
          <Select value={model} onChange={(e) => setModel(e.target.value)}>
            {models.map((n) => (
              <option key={n} value={n}>
                {((options.model_meta || {})[n] || {}).title || short(n)}
              </option>
            ))}
          </Select>
        </Field>

        <GroupLabel aside={sampler?.node_class}>tuning</GroupLabel>
        {tunable ? (
          <div style={{ border: "1px solid var(--border)", borderRadius: RADIUS.card,
                        background: "var(--bg2)", overflow: "hidden" }}>
            <button type="button" onClick={() => setTuneOpen(!tuneOpen)}
              style={{
                width: "100%", height: 38, display: "flex", alignItems: "center",
                gap: SPACE[8], padding: `0 ${SPACE[12]}px`, cursor: "pointer",
                background: "none", border: "none", color: "var(--textSec)",
                fontFamily: FONT, fontSize: TYPE.ui, textAlign: "left",
              }}>
              <span style={{ flex: 1 }}>
                {changed ? `${changed} setting${changed > 1 ? "s" : ""} changed`
                         : "follows the recipe"}
              </span>
              <CaretDown size={11} weight="bold" style={{
                color: "var(--textTer)", flexShrink: 0,
                transform: tuneOpen ? "rotate(180deg)" : "none",
                transition: `transform ${MOTION.hover}`,
              }} />
            </button>
            {tuneOpen && (
              <div style={{ padding: SPACE[12], paddingTop: SPACE[4],
                            display: "flex", flexDirection: "column", gap: SPACE[10] }}>
                <div style={{ display: "grid", gap: SPACE[8],
                              gridTemplateColumns: tunes("eta") ? "1fr 1fr 1fr" : "1fr 1fr" }}>
                  {numberField("steps", "steps")}
                  {numberField("cfg", "cfg")}
                  {tunes("eta") && numberField("eta", "eta")}
                </div>
                {comboField("sampler_name", "sampler")}
                {comboField("scheduler", "scheduler")}
                <span style={{ fontSize: TYPE.label, color: "var(--textTer)",
                               lineHeight: 1.5 }}>
                  Blank follows the recipe, so the style keeps improving when the
                  recipe does — only what you change is saved.
                </span>
              </div>
            )}
          </div>
        ) : (
          <span style={{ fontSize: TYPE.label, color: "var(--textSec)", lineHeight: 1.5 }}>
            {sampler?.reason || "Choose a model to see its sampler settings."}
          </span>
        )}

        {/* The LoRA chain is the composer's own component, driven by a plan held
            here. Reusing it means a style's stack is edited with exactly the
            controls, ordering rules and locked core stages as everywhere else.
            Contained in its own card so its thumbnails cannot bleed into the
            rows below (the overlap Jesse screenshotted, 2026-08-19). */}
        {plan && baseRecipe && (
          <div style={{ border: "1px solid var(--border)", borderRadius: RADIUS.card,
                        background: "var(--bg2)", padding: SPACE[10],
                        overflow: "hidden" }}>
            <LoraChain
              opts={planOpts} options={options} recipeId={base} plan={plan}
              setEntries={(entries) => setPlan(
                buildLoraPlan(baseRecipe, entries, options, planOpts, plan.core))}
              resetPlan={() => setPlan(buildLoraPlan(
                baseRecipe, defaultLoraEntries(baseRecipe), options, planOpts))}
              setCoreEnabled={(slot, on) => setPlan(buildLoraPlan(
                baseRecipe, plan.entries, options, planOpts,
                { ...(plan.core || {}), [slot]: { ...(plan.core || {})[slot], enabled: !!on } }))} />
          </div>
        )}

        {/* One-fact line: never wraps, never collides. */}
        <div title={opts?.aspect ? `canvas ${opts.aspect}${opts.mp ? ` @ ${opts.mp}MP` : ""}` : undefined}
             style={{ fontSize: TYPE.label, color: "var(--textTer)", whiteSpace: "nowrap",
                      overflow: "hidden", textOverflow: "ellipsis" }}>
          {opts?.aspect
            ? <>canvas <span style={{ color: "var(--textSec)" }}>{opts.aspect}
                {opts.mp ? ` @ ${opts.mp}MP` : ""}</span> — saved with the style</>
            : "no canvas pinned — the recipe's default is used"}
        </div>

        {(err || clash) && (
          <span style={{ fontSize: TYPE.label, lineHeight: 1.4,
                         color: err ? "#E3A7B0" : "#E3B98C" }}>
            {err || `saving replaces the existing “${clash.name}” style`}
          </span>
        )}
        <button type="button" onClick={save} disabled={busy}
          style={{
            height: 36, width: "100%", fontSize: TYPE.ui,
            fontWeight: W.heading, color: "#050507", background: "var(--accent)",
            border: "none", borderRadius: RADIUS.input, fontFamily: FONT,
            cursor: busy ? "default" : "pointer", opacity: busy ? 0.5 : 1,
          }}>{busy ? "saving…" : editId ? "save changes" : "save style"}</button>
      </div>
    </>
  );
};
