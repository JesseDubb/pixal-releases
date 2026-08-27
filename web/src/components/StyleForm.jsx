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
import { Disclosure } from "../lib/Disclosure.jsx";
import { ModalShell } from "../lib/ModalShell.jsx";
import { InfoTip } from "./InfoTip.jsx";
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
  const [negative, setNegative] = useState(seed.negative || "");
  const [promptTail, setPromptTail] = useState(seed.prompt_tail || "");
  const [sampler, setSampler] = useState(null);   // server's answer for base+model
  // The tuning cluster opens only when there is something to see: a style that
  // already overrides the recipe. A fresh save is "name it, save it".
  const [tuneOpen, setTuneOpen] = useState(
    () => Object.keys(seed.tuning || {}).length > 0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [baseMoved, setBaseMoved] = useState(null);

  const bases = options?.style_bases || [];
  const recipeById = (id) => (options?.recipes || []).find((r) => r.id === id);
  const baseRecipe = recipeById(base);

  // The draft's base is whatever recipe is actually running - that is the
  // point, and the bases[0] fallback that used to hide it is gone. But a
  // recipe that works FROM a finished frame (qwen_edit, klein_inpaint, the
  // upscalers) has no look of its own to bottle, and the <Select> below is
  // built from style_bases, so such a base would match no option: the field
  // would render blank, setBase would never fire, and saving would fail on a
  // server error. Move, but never quietly - name what was dropped and why.
  useEffect(() => {
    if (!bases.length || bases.includes(base)) return;
    const label = recipeById(base)?.label || base;
    setBaseMoved({ from: label, to: recipeById(bases[0])?.label || bases[0] });
    setBase(bases[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, bases.join("|")]);

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
  // "Just name it" only works if the values are VISIBLE. An untouched tuning
  // block inherits the recipe's schedule, so say so with the recipe's own
  // resolved numbers - not with placeholders hidden inside a closed panel.
  const inheritLine = (() => {
    const parts = ["steps", "cfg", "sampler_name", "scheduler", "eta"]
      .filter((k) => tunes(k) && defaults[k] !== undefined)
      .map((k) => `${k === "sampler_name" ? "sampler" : k} ${defaults[k]}`);
    return parts.length ? `follows the recipe · ${parts.join(" · ")}`
                        : "follows the recipe";
  })();

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
      ...(negative.trim() ? { negative: negative.trim() } : {}),
      ...(promptTail.trim() ? { prompt_tail: promptTail.trim() } : {}),
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
      {/* Pinned header and save bar around ONE scrolling body: the dialog's
          whole story is "name it, save it", so both stay on screen no matter
          how long the chain gets. The shell itself never scrolls - a flex
          column under maxHeight would compress its overflow:hidden panels
          (tuning, LoRA chain) instead of overflowing, the clipped-modal bug of
          2026-08-22. The body's children are made non-shrinking by the
          .px-dialog-body rule in the theme stylesheet (Chat.jsx). */}
      <ModalShell onClose={onClose} boxStyle={{
        width: 460, maxWidth: "94vw", maxHeight: "86vh", overflow: "hidden",
        background: "var(--bg1)", border: "1px solid var(--borderHov)",
        borderRadius: RADIUS.dialog, boxShadow: "0 18px 44px rgba(0,0,0,0.6)",
        display: "flex", flexDirection: "column",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                      flex: "0 0 auto", padding: `${SPACE[12]}px ${SPACE[16]}px`,
                      borderBottom: "1px solid var(--border)" }}>
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

        <div className="px-scroll px-dialog-body" style={{
          flex: "1 1 auto", minHeight: 0, overflowY: "auto", padding: SPACE[16],
          display: "flex", flexDirection: "column", gap: SPACE[16],
        }}>
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
        {baseMoved && (
          <span style={{ fontSize: TYPE.label, color: "#E3B98C", lineHeight: 1.5 }}>
            {baseMoved.from} works from a finished frame, so it has no look to
            save — this style is set to {baseMoved.to} instead
          </span>
        )}
        {baseRecipe?.needs_character && (
          <span style={{ fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
            runs on a character anchor — the anchor is chosen when the style is
            used, not saved inside it
          </span>
        )}

        <GroupLabel aside={sampler?.node_class}>tuning</GroupLabel>
        {tunable ? (
          <div style={{ border: "1px solid var(--border)", borderRadius: RADIUS.card,
                        background: "var(--bg2)", overflow: "hidden" }}>
            <Disclosure open={tuneOpen} onToggle={() => setTuneOpen(!tuneOpen)}
              caretSide="trailing" caretStyle={{ color: "var(--textTer)" }}
              triggerStyle={{ minHeight: 38,
                              padding: `${SPACE[6]}px ${SPACE[12]}px`,
                              color: "var(--textSec)", fontSize: TYPE.ui }}
              trigger={
                <span style={{ flex: 1, lineHeight: 1.5 }}>
                  {changed ? `${changed} setting${changed > 1 ? "s" : ""} changed`
                           : inheritLine}
                </span>
              }
              contentStyle={{ padding: SPACE[12], paddingTop: SPACE[4],
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
            </Disclosure>
          </div>
        ) : (
          <span style={{ fontSize: TYPE.label, color: "var(--textSec)", lineHeight: 1.5 }}>
            {sampler?.reason || "Choose a model to see its sampler settings."}
          </span>
        )}
        <Field label={<>Negative <InfoTip size={12} text="Only does anything above cfg 1.0." /></>}
               hint="What the sampler steers away from">
          <input {...hoverable} value={negative}
            onChange={(e) => setNegative(e.target.value)}
            style={{ ...controlBase, padding: `0 ${SPACE[12]}px`,
                     transition: `border-color ${MOTION.hover}` }} />
        </Field>
        <Field label="Prompt tail" hint="Appended after the caption">
          <input {...hoverable} value={promptTail}
            onChange={(e) => setPromptTail(e.target.value)}
            style={{ ...controlBase, padding: `0 ${SPACE[12]}px`,
                     transition: `border-color ${MOTION.hover}` }} />
        </Field>

        {/* loraPlanFor refused the live stack (its revision predates the
            recipe's current one). Say so - the default chain the effect
            rebuilds below must never pass as the user's own. */}
        {seed.lora_stack_dropped && (
          <span style={{ fontSize: TYPE.label, color: "#E3B98C", lineHeight: 1.5 }}>
            your live LoRA stack could not be carried over — the recipe's stack
            changed since you set it, so what you see is the recipe's default
            chain; re-add your picks before saving
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
                { ...(plan.core || {}), [slot]: { ...(plan.core || {})[slot], enabled: !!on } }))}
              setCoreStrength={(slot, value) => setPlan(buildLoraPlan(
                // 2026-08-21: core strength edits rebuild the local plan,
                // mirroring the toggle above - a style's stack obeys the same
                // override map as the composer's.
                baseRecipe, plan.entries, options, planOpts,
                { ...(plan.core || {}), [slot]: { ...(plan.core || {})[slot], strength: value } }))} />
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

        </div>

        {/* Pinned save bar: the one thing this dialog asks for is always on
            screen, with its error/replace note beside it. */}
        <div style={{ flex: "0 0 auto", padding: `${SPACE[12]}px ${SPACE[16]}px`,
                      borderTop: "1px solid var(--border)", display: "flex",
                      flexDirection: "column", gap: SPACE[8] }}>
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
      </ModalShell>
    </>
  );
};
