// CharacterForm.jsx — create OR edit a character anchor: who they are, what
// is always true of them, the references wired beside their photo, and the
// identity photo itself. Saved as data to pixal_dm/characters/<id>.json.
//
// Casting-card reskin 10.13 (2026-09-04): their face is the fixed left rail,
// the person is the right sheet, and the composed sentence is a full-width
// footer. The business state and every transport path remain unchanged.
import { useEffect, useMemo, useRef, useState } from "react";
// Dashed user-circle = a DRAFT anchor (the character icon family's empty state).
import { Crop, ImageSquare, MagnifyingGlass, PencilSimple, Plus,
         UserCircleDashed, X } from "@phosphor-icons/react";
import { FONT, W, TYPE, SPACE, RADIUS, MOTION, OVERLAY, SHADOW, GLASS_INK,
         GLASS_SOLID } from "../lib/design-tokens.js";
import { Disclosure, DisclosureTrigger } from "../lib/Disclosure.jsx";
import { ModalShell } from "../lib/ModalShell.jsx";
import { SegmentedControl } from "../lib/SegmentedControl.jsx";
import { Switch } from "../lib/Switch.jsx";
import { characterPreview, characterRecord, inputFullUrl, inputImages,
         inputImgUrl, stageInput, upload } from "../transport.js";
import { api, useJobLive, useStore } from "../store.js";
import { DotMatrix } from "../lib/DotMatrix.jsx";
import { EditDirector } from "./EditDirector.jsx";
import { InfoTip } from "./InfoTip.jsx";

const MONO = "ui-monospace, Consolas, monospace";
// Same three as the reference picker: newest-first alone stops being findable
// the moment the face you want is not from today.
const SORTS = [
  { key: "new", label: "Newest" },
  { key: "old", label: "Oldest" },
  { key: "name", label: "A–Z" },
];

// ---------------------------------------------------------------- shared bits
// One button, three duties. This file used to hand-roll five button styles
// (save, upload, edit/crop, use-region, add-reference) that were the same
// control wearing different inline CSS — the "half baked" read. `as` exists
// because upload is a <label> wrapping a hidden file input.
const Btn = ({ kind = "quiet", as: Tag = "button", disabled, style, children,
               ...rest }) => (
  <Tag {...(Tag === "button" ? { type: "button", disabled } : {})} {...rest}
    style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      gap: SPACE[6], height: 30, padding: `0 ${SPACE[12]}px`,
      fontFamily: FONT, fontSize: TYPE.ui,
      fontWeight: kind === "primary" ? W.heading : W.label,
      border: kind === "primary" ? "none" : "1px solid var(--border)",
      borderRadius: RADIUS.input, whiteSpace: "nowrap",
      background: kind === "primary" ? "var(--accent)" : "var(--bg2)",
      color: kind === "primary" ? "#050507" : "var(--textSec)",
      cursor: disabled ? "default" : "pointer",
      opacity: disabled ? 0.5 : 1,
      ...style,
    }}>{children}</Tag>
);

// The three face actions are a grid, not a flex row: the rail is 276 wide,
// so 3 x 88 + 2 x 6 lands every chip on a whole even pixel (flex's 1fr split
// gave 86.666 and a 7.9px gap). Content is left-aligned at one inset, which
// puts all three icons on the same vertical axis - equal boxes with centred
// content start their glyphs at three different x's, which is what read as
// unbalanced (Jesse, 2026-09-04).
// ONE control height for the whole form - DESIGN.md's 34 beat. Not just the
// controls that share a row: age and race at 30 beside 34px Look/Build/Hair
// fields were one-offs, and the fix is never to shrink two fields to match a
// toggle, it is to put the toggle on the same beat as everything else
// (Jesse, 2026-09-04).
const FIELD_H = 34;
// The name is display type but still a field: it gets a field's radius (so its
// focus ring is not a bare square), a field's 12px text inset (so the name and
// the age below it start on one axis) and an even height - 28px at line-height
// 1.2 computed to 33.6, a fraction (Jesse, 2026-09-04).
const NAME_H = 44;

const FACE_ACTION_GAP = SPACE[6];
// Three equal boxes on the rail's own grid: 276 = 3 x 88 + 2 x 6, on the
// form's one height. Content is CENTRED - flushing it left left a hole to the
// right of the short labels, which reads worse than the icons not sharing an
// axis (Jesse, 2026-09-04). The hairline is an inset shadow rather than a
// border so the box stays a whole 88 x 34 with nothing added outside it.
const FACE_ACTION = {
  minWidth: 0, height: FIELD_H, justifyContent: "center",
  gap: SPACE[8], padding: `0 ${SPACE[12]}px`, borderRadius: RADIUS.card,
  border: "none", boxShadow: "inset 0 0 0 1px var(--border)",
};

// The bare × in a dialog corner.
const CloseBtn = ({ onClose }) => (
  <button type="button" onClick={onClose} aria-label="Close"
    style={{ background: "none", border: "none", color: "var(--textTer)",
             cursor: "pointer", padding: 4, display: "inline-flex" }}>
    <X size={14} weight="bold" />
  </button>
);

// `grow` lets one field absorb the pane's spare height (the notes textarea),
// so the left column bottoms out with the picker instead of above it.
// `as="div"` is for the one field that is not a single input (the sex
// radiogroup): a <label> adopts the first labelable descendant as its labeled
// control, so wrapping the buttons made the word "Sex" select Female on click.
const Field = ({ label, children, grow, as: Tag = "label" }) => (
  <Tag style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0,
                flex: grow ? "1 1 auto" : "0 0 auto" }}>
    <span style={{ fontSize: TYPE.label, fontWeight: W.nav,
                   color: "var(--textSec)", overflow: "hidden",
                   textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
      {label}
    </span>
    {children}
  </Tag>
);

const inputStyle = {
  background: "var(--bg2)", border: "1px solid var(--border)",
  borderRadius: RADIUS.input, padding: `7px ${SPACE[10]}px`, fontSize: TYPE.ui,
  color: "var(--text)", fontFamily: FONT, outline: "none", width: "100%",
};

// The eyebrow — group and pane headings. Uppercase letter-spaced micro is the
// kicker idiom; FIELD labels are sentence case (Field above), never this.
const sectionLabel = {
  fontSize: TYPE.micro, fontWeight: W.heading, letterSpacing: "0.08em",
  textTransform: "uppercase", color: "var(--textTer)",
};

// The H3 reference node has nine slots and the identity photo holds slot 0,
// so eight accessories is the ceiling (the server enforces the same number).
const ACCESSORY_MAX = 8;

// A group is a label and one subline — what these fields are, and the one
// rule that governs them. Not an accordion, not a card: the pane stays one
// scrolling column (9.82). The accessories group (9.83) is one of these.
const Group = ({ label, sub, children, style }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: SPACE[10], ...style }}>
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={sectionLabel}>{label}</span>
      {sub && <span style={{ fontSize: TYPE.label, lineHeight: 1.4,
                             color: "var(--textTer)" }}>{sub}</span>}
    </div>
    {children}
  </div>
);

// The dialog goes side-by-side only when the viewport can afford it; on a
// phone the panes stack and the whole body scrolls as one.
const useNarrow = () => {
  const [narrow, setNarrow] = useState(
    () => window.matchMedia("(max-width: 760px)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 760px)");
    const on = (e) => setNarrow(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
};

const InputCard = ({ image, selected, onPick, purpose = "the identity reference" }) => {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <button type="button" aria-pressed={selected}
      aria-label={`Use ${image.name} as ${purpose}`} title={image.name}
      onClick={onPick}
      style={{ minWidth: 0, padding: 4, display: "flex", flexDirection: "column", gap: 4,
               border: "1px solid", borderRadius: RADIUS.input,
               borderColor: selected ? "var(--accent)" : "var(--border)",
               background: selected ? "var(--accentMut)" : "var(--bg2)",
               color: selected ? "var(--accent)" : "var(--textSec)", cursor: "pointer",
               contentVisibility: "auto", containIntrinsicSize: "112px 130px" }}>
      <span style={{ position: "relative", width: "100%", aspectRatio: "1 / 1",
                     display: "flex", alignItems: "center", justifyContent: "center",
                     overflow: "hidden", borderRadius: RADIUS.inner,
                     background: "var(--bg3)", color: "var(--textMut)" }}>
        {!loaded && !failed && <span className="px-thumbload"
          style={{ position: "absolute", inset: 0 }} />}
        {!failed ? (
          <img src={inputImgUrl(image)} alt="" loading="lazy" decoding="async"
            onLoad={() => setLoaded(true)} onError={() => setFailed(true)}
            style={{ width: "100%", height: "100%", objectFit: "cover",
                     opacity: loaded ? 1 : 0 }} />
        ) : <ImageSquare size={22} weight="duotone" aria-hidden="true" />}
      </span>
      <span style={{ width: "100%", overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap", fontFamily: MONO, fontSize: 9,
                     textAlign: "left" }}>
        {image.name.split("/").pop()}
      </span>
    </button>
  );
};

// InputBrowser — filter, sort and pick from ComfyUI/input. The identity pane
// and the AccessoryPicker rendered this same block as two hand-kept copies;
// each instance owns its filter and sort, because the two pickers are used
// for different hunts at different times.
const InputBrowser = ({ options, selectedName = "", onPick,
                        purpose = "the identity reference",
                        gridStyle }) => {
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState("new");
  const inputAll = useMemo(() => inputImages(options), [options]);
  const inputList = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const byName = (a, b) => a.name.localeCompare(b.name);
    const rows = q ? inputAll.filter((i) => i.name.toLowerCase().includes(q))
                   : inputAll.slice();
    return rows.sort(
      sort === "name" ? byName
        : sort === "old" ? (a, b) => (a.mtime || 0) - (b.mtime || 0) || byName(a, b)
          : (a, b) => (b.mtime || 0) - (a.mtime || 0) || byName(a, b));
  }, [inputAll, filter, sort]);
  return (
    <>
      <input value={filter} onChange={(e) => setFilter(e.target.value)}
             placeholder="Filter by name…"
             style={{ ...inputStyle, height: 30, padding: `0 ${SPACE[10]}px` }} />
      <div style={{ display: "flex", alignItems: "center", gap: SPACE[4],
                    color: "var(--textTer)", fontSize: TYPE.label }}>
        <span>ComfyUI/input</span>
        <span style={{ fontFamily: MONO, fontSize: 9 }}>
          {filter.trim() ? `${inputList.length} of ${inputAll.length}` : inputList.length}
        </span>
        <span role="group" aria-label="Sort input images"
              style={{ marginLeft: "auto", display: "inline-flex", gap: 2 }}>
          {SORTS.map((s) => (
            <button key={s.key} type="button" aria-pressed={sort === s.key}
              onClick={() => setSort(s.key)}
              style={{ height: 20, padding: `0 ${SPACE[6]}px`, border: "1px solid",
                       borderColor: sort === s.key ? "var(--accent)" : "var(--border)",
                       borderRadius: RADIUS.pill, cursor: "pointer", fontSize: 9,
                       fontFamily: FONT,
                       background: sort === s.key ? "var(--accentMut)" : "transparent",
                       color: sort === s.key ? "var(--accent)" : "var(--textTer)" }}>
              {s.label}
            </button>
          ))}
        </span>
      </div>
      <div className="px-scroll"
           style={{ minHeight: 0, overflowY: "auto", display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))",
                    gap: SPACE[6], alignContent: "start",
                    border: "1px solid var(--border)", borderRadius: RADIUS.input,
                    padding: SPACE[6], ...gridStyle }}>
        {inputList.map((image) => (
          <InputCard key={image.name} image={image}
                     selected={selectedName === image.name} purpose={purpose}
                     onPick={() => onPick(image.name)} />
        ))}
      </div>
    </>
  );
};

// The casting card's pseudo-states stay local to this surface. Inline style
// objects cannot express hover/focus/press, so the class hooks own only those
// states; geometry and palette remain visible beside the JSX that uses them.
const CHARACTER_FORM_CSS = `
.px-cast-control {
  transition: border-color ${MOTION.hover}, box-shadow ${MOTION.hover};
}
.px-cast-control:not(:disabled):hover { border-color: var(--borderHov) !important; }
.px-cast-control:focus { outline: none; }
.px-cast-control:focus-visible {
  border-color: var(--accentStr) !important;
  box-shadow: 0 0 0 1px var(--accentStr);
}
.px-cast-control::placeholder { color: var(--textMut) !important; }
.px-cast-segment .px-seg {
  height: 28px !important;
  transition: transform ${MOTION.press}, border-color ${MOTION.state},
              background ${MOTION.state}, color ${MOTION.state},
              box-shadow ${MOTION.hover} !important;
}
.px-cast-switch {
  transition: transform ${MOTION.press}, border-color ${MOTION.state},
              background ${MOTION.state}, box-shadow ${MOTION.hover} !important;
}
.px-cast-btn, .px-cast-icon, .px-cast-close > button, .px-cast-drop,
.px-cast-disclosure button {
  transition: transform ${MOTION.press}, border-color ${MOTION.hover},
              background ${MOTION.hover}, color ${MOTION.hover},
              box-shadow ${MOTION.hover};
}
.px-cast-btn { overflow: hidden; text-overflow: ellipsis; }
/* The face actions carry their hairline as an inset shadow so the layout
   starts on an even pixel; hover and focus recolour it in place. */
.px-cast-face:not([disabled]):not(.is-busy):hover,
.px-cast-face:not([aria-disabled="true"]):hover {
  box-shadow: inset 0 0 0 1px var(--borderHov) !important;
}
.px-cast-face:focus-visible, .px-cast-face:focus-within {
  box-shadow: inset 0 0 0 1px var(--accentStr),
              0 0 0 1px var(--accentStr) !important;
}
.px-cast-btn:not(.px-cast-save):not([disabled]):not(.is-busy):hover,
.px-cast-drop:not([aria-disabled="true"]):hover {
  border-color: var(--borderHov) !important;
  color: var(--text) !important;
}
.px-cast-segment .px-seg:not([aria-checked="true"]):not([disabled]):hover {
  border-color: var(--borderHov) !important;
  color: var(--textSec) !important;
}
.px-cast-segment .px-seg[aria-checked="true"]:hover,
.px-cast-switch[aria-checked="true"]:not([disabled]):hover {
  box-shadow: 0 0 0 1px var(--accentStr);
}
.px-cast-switch[aria-checked="false"]:not([disabled]):hover {
  box-shadow: 0 0 0 1px var(--borderHov);
}
.px-cast-save:not([disabled]):hover {
  background: var(--accentHot) !important;
  color: var(--accentInk) !important;
}
.px-cast-icon:hover, .px-cast-close > button:hover,
.px-cast-disclosure button:hover {
  color: var(--text) !important;
}
.px-cast-close > button {
  border-radius: ${RADIUS.card}px;
  transition: transform ${MOTION.press}, color ${MOTION.hover},
              box-shadow ${MOTION.hover};
}
.px-cast-btn:focus, .px-cast-icon:focus,
.px-cast-close > button:focus, .px-cast-disclosure button:focus,
.px-cast-switch:focus { outline: none; }
.px-cast-btn:focus-visible, .px-cast-btn:focus-within,
.px-cast-icon:focus-visible,
.px-cast-close > button:focus-visible, .px-cast-drop:focus-visible,
.px-cast-drop:focus-within,
.px-cast-disclosure button:focus-visible,
.px-cast-segment .px-seg:focus-visible, .px-cast-switch:focus-visible {
  box-shadow: 0 0 0 1px var(--accentStr) !important;
}
.px-cast-segment .px-seg:focus-visible { outline: none !important; }
.px-cast-btn:not(.px-cast-save):not([disabled]):not(.is-busy):active,
.px-cast-icon:active,
.px-cast-close > button:active,
.px-cast-drop:not([aria-disabled="true"]):active,
.px-cast-disclosure button:active,
.px-cast-segment .px-seg:active, .px-cast-switch:active {
  transform: scale(0.96);
}
.px-cast-btn.is-busy { opacity: 0.5 !important; }
.px-cast-strip-wrap:disabled { opacity: 0.5; }
.px-cast-strip-wrap:disabled .px-cast-thumb > button {
  cursor: wait !important;
}
.px-cast-strip-wrap:disabled .px-cast-control { cursor: wait; }
.px-cast-save:not([disabled]):active { transform: scale(0.95); }
.px-cast-thumb > button {
  width: 100% !important;
  height: 100% !important;
  padding: 0 !important;
  gap: 0 !important;
  border-radius: ${RADIUS.card}px !important;
  transition: transform ${MOTION.press}, border-color ${MOTION.hover},
              box-shadow ${MOTION.hover};
}
.px-cast-thumb > button > span:first-child {
  height: 100% !important;
  aspect-ratio: auto !important;
  border-radius: ${RADIUS.card}px !important;
}
.px-cast-thumb > button > span:last-child { display: none !important; }
.px-cast-thumb:not(.is-selected) > button:not(:disabled):hover {
  border-color: var(--borderHov) !important;
}
.px-cast-thumb.is-selected > button:not(:disabled):hover {
  border-color: var(--accentHot) !important;
}
.px-cast-thumb > button:focus { outline: none; }
.px-cast-thumb > button:focus-visible {
  box-shadow: 0 0 0 1px var(--accentStr) !important;
}
.px-cast-thumb.is-selected > button:focus-visible {
  border-color: var(--accentHot) !important;
  outline: 2px solid var(--accentStr) !important;
}
.px-cast-thumb > button:not(:disabled):active { transform: scale(0.96); }
/* No scrollbars in this dialog: they are the noise Jesse called out, and
   every pane here either fits or scrolls silently under the wheel/caret. */
.px-cast-strip-wrap .px-scroll, .px-cast-notes { scrollbar-width: none; }
.px-cast-strip-wrap .px-scroll::-webkit-scrollbar,
.px-cast-notes::-webkit-scrollbar { display: none; width: 0; height: 0; }
.px-cast-search {
  position: relative; display: flex; align-items: center; min-width: 0;
}
.px-cast-search > svg {
  position: absolute; left: ${SPACE[10]}px; pointer-events: none;
  color: var(--textTer);
}
@media (prefers-reduced-motion: reduce) {
  .px-cast-control, .px-cast-btn, .px-cast-icon, .px-cast-drop,
  .px-cast-close > button,
  .px-cast-disclosure button, .px-cast-segment .px-seg,
  .px-cast-switch, .px-cast-thumb > button { transition: none !important; }
}
`;

// While the edit samples, the work must read HERE - the modal is what the
// user is looking at, and the render was happening behind it (Jesse,
// 2026-09-04). The same effect a job card shows: DotMatrix breathing the
// preview's structure, then the 2px accent bar and the step counter. Same
// telemetry channel too - subscribed per job, so a step tick repaints this
// tile and nothing else in the dialog.
const EditingVeil = ({ label }) => {
  // The id is read HERE, not passed in. The form does not subscribe to the
  // store, so a jobId derived up there was a snapshot taken before the job
  // existed: useJobLive(null) subscribes to nothing, no step ever arrives,
  // and the veil sat on "queued…" for the whole render (Jesse, 2026-09-04:
  // "there is no status update to the fact it is doing anything"). Reading
  // it inside the veil also keeps the repaint here - a store subscription on
  // the form would re-render the whole dialog on every sampling tick, which
  // is exactly what render-quiet forbids.
  const store = useStore();
  const jobId = (store.liveJobs || [])[0] || null;
  const live = useJobLive(jobId);
  const p = live.progress || {};
  const pct = p.max ? Math.round((100 * p.value) / p.max) : 0;
  return (
    <div aria-hidden="true"
      style={{ position: "absolute", inset: 0, overflow: "hidden",
               borderRadius: RADIUS.dialog,
               background: GLASS_SOLID.background }}>
      {/* Edge to edge: the tile is already 3/4, so an aspect-held canvas
          inside its padding letterboxed inside a box that had no room to
          give. */}
      <DotMatrix preview={live.preview} fill />
      <div style={{ position: "absolute", left: SPACE[12], right: SPACE[12],
                    bottom: SPACE[12] }}>
        <span style={{ display: "block", marginBottom: SPACE[6],
                       fontSize: TYPE.label, fontWeight: W.nav,
                       color: GLASS_INK, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {label}
        </span>
        {/* JobCard's bar, verbatim in behaviour: no width transition, because
            steps arrive faster than an ease can settle. */}
        <div style={{ height: 2, background: "var(--bg3)",
                      borderRadius: RADIUS.pill, overflow: "hidden" }}>
          <div style={{ height: "100%", width: pct + "%",
                        background: "var(--accent)" }} />
        </div>
        <span style={{ display: "block", marginTop: SPACE[6], fontFamily: MONO,
                       fontSize: TYPE.micro, color: "var(--accent)" }}>
          {p.max ? `sampling ${p.value}/${p.max}` : "queued…"}
        </span>
      </div>
    </div>
  );
};

// The identity browser deliberately has one order: newest first. It reuses
// InputCard's lazy image, failure state and px-thumbload shimmer, then trims
// that card to the mockup's square strip through the scoped rules above.
const IdentityStrip = ({ options, selectedName, onPick, disabled = false }) => {
  const [filter, setFilter] = useState("");
  const inputAll = useMemo(() => inputImages(options), [options]);
  const inputList = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const byName = (a, b) => a.name.localeCompare(b.name);
    const rows = q ? inputAll.filter((i) => i.name.toLowerCase().includes(q))
                   : inputAll.slice();
    return rows.sort((a, b) => (b.mtime || 0) - (a.mtime || 0) || byName(a, b));
  }, [inputAll, filter]);
  // The count and the folder live in the field's tooltip, not in a line of
   // their own: "Swap the photo - ComfyUI/input - 482" was business the strip
   // already shows (Jesse, 2026-09-04).
  const count = filter.trim() ? `${inputList.length} of ${inputAll.length}`
                              : inputAll.length;
  const summary = `Swap the photo — ComfyUI/input · ${count}`;
  const empty = inputAll.length ? "No matching photos." : "No input images yet.";

  return (
    <fieldset className="px-cast-strip-wrap" disabled={disabled}
      aria-label="Swap the identity photo" aria-busy={disabled}
      style={{ width: "100%", display: "flex", flexDirection: "column",
               gap: SPACE[8], minWidth: 0, minInlineSize: 0,
               margin: 0, padding: 0, border: "none" }}>
      <div className="px-cast-search" title={summary}>
        <MagnifyingGlass size={13} weight="bold" aria-hidden="true" />
        <input className="px-input px-cast-control" value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Search the identity photos"
          placeholder="Search photos"
          style={{ ...inputStyle, width: "100%", minWidth: 0, height: FIELD_H,
                   padding: 0, paddingLeft: SPACE[10] + 18,
                   paddingRight: SPACE[10], borderRadius: RADIUS.card }} />
      </div>
      <div className="px-scroll" role="list" aria-label="Identity photos"
        onWheel={(e) => { if (e.deltaY && !e.deltaX) e.currentTarget.scrollLeft += e.deltaY; }}
        style={{ minWidth: 0, display: "flex", gap: SPACE[6],
                 overflowX: "auto", overflowY: "hidden",
                 padding: SPACE[2] }}>
        {inputList.map((image) => {
          const selected = selectedName === image.name;
          return (
            <div key={image.name} role="listitem"
              className={`px-cast-thumb${selected ? " is-selected" : ""}`}
              style={{ width: 56, height: 56, flex: "0 0 auto",
                       borderRadius: RADIUS.card,
                       boxShadow: selected ? "0 0 0 1px var(--accentStr)" : "none" }}>
              <InputCard image={image} selected={selected} onPick={() => onPick(image.name)} />
            </div>
          );
        })}
        {!inputList.length && (
          <div role="listitem"
            style={{ minWidth: 0, height: 56, display: "flex",
                     alignItems: "center", alignSelf: "center" }}>
            <span role="status" aria-live="polite" title={empty}
              style={{ display: "block", minWidth: 0, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap",
                       fontSize: TYPE.label, color: "var(--textTer)" }}>
              {empty}
            </span>
          </div>
        )}
      </div>
    </fieldset>
  );
};

// ------------------------------------------------------------------ CropDialog
// Drag a region over the full-res reference and keep only that part. No model
// runs: the cutout is uploaded as a new input image and becomes the identity
// source, so Identity Edit sees exactly the region that matters (it
// faithfully carries over everything in the frame, accessories and background
// included — cropping is how you leave those behind).
//
// The region is ADJUSTABLE, not draw-once (Jesse, 2026-09-04: "you need to
// draw the square perfect, there are no handles"): it opens with a centred
// region already placed, dragging inside moves it, eight handles resize it,
// and dragging on the dimmed outside draws a fresh one. Handle geometry is
// the design system's locked spec — corner dots 10px, edge pills 18×6, white
// with a 25%-alpha hairline, no shadows, integer offsets.
const CROP_MIN = 24;          // natural px — below this a drag is a misclick
const CROP_HANDLES = [
  { k: "nw", fx: 0,   fy: 0,   cursor: "nwse-resize" },
  { k: "n",  fx: 0.5, fy: 0,   cursor: "ns-resize" },
  { k: "ne", fx: 1,   fy: 0,   cursor: "nesw-resize" },
  { k: "w",  fx: 0,   fy: 0.5, cursor: "ew-resize" },
  { k: "e",  fx: 1,   fy: 0.5, cursor: "ew-resize" },
  { k: "sw", fx: 0,   fy: 1,   cursor: "nesw-resize" },
  { k: "s",  fx: 0.5, fy: 1,   cursor: "ns-resize" },
  { k: "se", fx: 1,   fy: 1,   cursor: "nwse-resize" },
];

const CropDialog = ({ imageUrl, busy, onClose, onUse }) => {
  const [crop, setCrop] = useState(null);       // natural-px {x,y,w,h}
  const [dims, setDims] = useState(null);
  const imgRef = useRef(null);
  const overlayRef = useRef(null);
  const drag = useRef(null);                    // { mode, start, from }

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const toNatural = (e) => {
    const box = overlayRef.current.getBoundingClientRect();
    return { x: clamp((e.clientX - box.left) * (dims.w / box.width), 0, dims.w),
             y: clamp((e.clientY - box.top) * (dims.h / box.height), 0, dims.h) };
  };

  // The photo arrives with a region already placed — there is always
  // something to adjust, never a blank state to get right on the first try.
  const loaded = () => {
    const d = { w: imgRef.current.naturalWidth, h: imgRef.current.naturalHeight };
    setDims(d);
    setCrop({ x: Math.round(d.w * 0.15), y: Math.round(d.h * 0.15),
              w: Math.round(d.w * 0.7), h: Math.round(d.h * 0.7) });
  };

  const begin = (mode) => (e) => {
    if (!dims) return;
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { mode, start: toNatural(e), from: crop };
  };
  const move = (e) => {
    const d = drag.current;
    if (!d || !dims) return;
    const p = toNatural(e);
    const dx = p.x - d.start.x, dy = p.y - d.start.y;
    if (d.mode === "draw") {
      const x = Math.min(d.start.x, p.x), y = Math.min(d.start.y, p.y);
      const w = Math.abs(p.x - d.start.x), h = Math.abs(p.y - d.start.y);
      if (w > 8 && h > 8) setCrop({ x, y, w, h });
      return;
    }
    if (d.mode === "move") {
      setCrop({ ...d.from,
                x: clamp(d.from.x + dx, 0, dims.w - d.from.w),
                y: clamp(d.from.y + dy, 0, dims.h - d.from.h) });
      return;
    }
    const spec = CROP_HANDLES.find((h) => h.k === d.mode);
    let { x, y, w, h } = d.from;
    if (spec.fx === 0) {                        // left edge moves
      const nx = clamp(d.from.x + dx, 0, d.from.x + d.from.w - CROP_MIN);
      w = d.from.x + d.from.w - nx; x = nx;
    } else if (spec.fx === 1) {                 // right edge moves
      w = clamp(d.from.w + dx, CROP_MIN, dims.w - d.from.x);
    }
    if (spec.fy === 0) {                        // top edge moves
      const ny = clamp(d.from.y + dy, 0, d.from.y + d.from.h - CROP_MIN);
      h = d.from.y + d.from.h - ny; y = ny;
    } else if (spec.fy === 1) {                 // bottom edge moves
      h = clamp(d.from.h + dy, CROP_MIN, dims.h - d.from.y);
    }
    setCrop({ x, y, w, h });
  };
  const up = () => { drag.current = null; };

  const use = () => {
    if (!crop || busy) return;
    const out = document.createElement("canvas");
    out.width = Math.round(crop.w); out.height = Math.round(crop.h);
    out.getContext("2d").drawImage(imgRef.current,
      crop.x, crop.y, crop.w, crop.h, 0, 0, out.width, out.height);
    out.toBlob((b) => b && onUse(b), "image/png");
  };

  const pct = (v, total) => `${(v / total) * 100}%`;

  return (
    <ModalShell onClose={onClose} z={OVERLAY.form}
      boxProps={{ role: "dialog", "aria-label": "Crop the photo" }}
      boxStyle={{
        width: 560, maxWidth: "94vw", maxHeight: "92vh", overflowY: "auto",
        background: "var(--bg1)", border: "1px solid var(--borderHov)",
        borderRadius: RADIUS.dialog, boxShadow: "0 18px 44px rgba(0,0,0,0.6)",
        padding: SPACE[16], display: "flex", flexDirection: "column", gap: SPACE[12],
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: SPACE[6],
                         fontSize: TYPE.h3, fontWeight: W.heading }}>
            <Crop size={15} weight="duotone" style={{ color: "var(--accent)" }} />
            Crop the photo
          </span>
          <CloseBtn onClose={onClose} />
        </div>
        <div style={{ position: "relative", alignSelf: "center", maxWidth: "100%" }}>
          <img ref={imgRef} src={imageUrl} alt="Crop source" draggable={false}
            onLoad={loaded}
            style={{ display: "block", maxWidth: "100%", maxHeight: "56vh",
                     borderRadius: RADIUS.card, userSelect: "none" }} />
          {/* The interactive surface. Pointer events resolve on whichever
              child is grabbed: the dimmed outside draws a new region, the
              region moves, a handle resizes. */}
          <div ref={overlayRef}
            onPointerDown={begin("draw")} onPointerMove={move}
            onPointerUp={up} onPointerCancel={up}
            style={{ position: "absolute", inset: 0, overflow: "hidden",
                     borderRadius: RADIUS.card, touchAction: "none",
                     cursor: dims ? "crosshair" : "default" }}>
            {crop && dims && (
              <div
                onPointerDown={begin("move")}
                style={{
                  position: "absolute",
                  left: pct(crop.x, dims.w), top: pct(crop.y, dims.h),
                  width: pct(crop.w, dims.w), height: pct(crop.h, dims.h),
                  border: "1px solid #FFFFFF", boxSizing: "border-box",
                  // One div scrims all four sides: the spread paints the
                  // outside, the container's overflow clips it to the photo.
                  boxShadow: "0 0 0 100vmax rgba(0, 0, 0, 0.55)",
                  cursor: "move", touchAction: "none",
                }}>
                {CROP_HANDLES.map(({ k, fx, fy, cursor }) => {
                  const dot = fx !== 0.5 && fy !== 0.5;
                  return (
                    <div key={k} onPointerDown={begin(k)}
                      style={{
                        // 20px invisible hit target, centred on the frame
                        // boundary; the visual sits inside at spec size.
                        position: "absolute", width: 20, height: 20,
                        left: `calc(${fx * 100}% - 10px)`,
                        top: `calc(${fy * 100}% - 10px)`,
                        display: "flex", alignItems: "center",
                        justifyContent: "center",
                        cursor, touchAction: "none",
                      }}>
                      <div style={{
                        background: "#FFFFFF",
                        border: "1px solid rgba(0, 0, 0, 0.25)",
                        boxSizing: "border-box",
                        ...(dot
                          ? { width: 10, height: 10, borderRadius: 999 }
                          : fy === 0.5
                            ? { width: 6, height: 18, borderRadius: 3 }
                            : { width: 18, height: 6, borderRadius: 3 }),
                      }} />
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: SPACE[8] }}>
          <span style={{ fontSize: TYPE.label, color: "var(--textTer)",
                         fontFamily: MONO,
                         overflow: "hidden", textOverflow: "ellipsis",
                         whiteSpace: "nowrap" }}>
            {crop ? `${Math.round(crop.w)} × ${Math.round(crop.h)} px` : ""}
          </span>
          <Btn kind="primary" onClick={use} disabled={!crop || busy}
               style={{ marginLeft: "auto" }}>
            {busy ? "Uploading…" : "Use this crop"}
          </Btn>
        </div>
    </ModalShell>
  );
};

// AccessoryPicker — the add-a-reference dialog (9.83): the same InputBrowser
// as the identity pane, pointed at picking ONE input image to wire as an
// accessory reference. Uploads are tagged kind "object" — that is what an
// accessory is to the model. Stacks above the form exactly like the crop and
// edit dialogs.
const AccessoryPicker = ({ options, onClose, onPick, refreshOptions }) => {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const doUpload = async (f) => {
    if (!f) return;
    setBusy(true); setErr(null);
    try {
      const image = await upload(f, "object");
      if (refreshOptions) await refreshOptions();
      onPick(image.name);
    } catch (error) {
      setErr(error?.message || "The accessory image could not be uploaded.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell onClose={onClose} z={OVERLAY.form}
      boxProps={{ role: "dialog", "aria-label": "Add a wired reference" }}
      boxStyle={{
        width: 480, maxWidth: "94vw", maxHeight: "88vh",
        background: "var(--bg1)", border: "1px solid var(--borderHov)",
        borderRadius: RADIUS.dialog, boxShadow: "0 18px 44px rgba(0,0,0,0.6)",
        padding: SPACE[16], display: "flex", flexDirection: "column", gap: SPACE[8],
      }}>
      <div style={{ display: "flex", alignItems: "center", gap: SPACE[8] }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: SPACE[6],
                       fontSize: TYPE.h3, fontWeight: W.heading }}>
          <ImageSquare size={15} weight="duotone" style={{ color: "var(--accent)" }} />
          Add a reference
        </span>
        <Btn as="label" style={{ marginLeft: "auto", height: 26 }}>
          <ImageSquare size={12} weight="duotone" />
          {busy ? "Uploading…" : "Upload"}
          <input type="file" accept="image/*" style={{ display: "none" }}
                 onChange={(e) => { doUpload(e.target.files[0]); e.target.value = ""; }} />
        </Btn>
        <CloseBtn onClose={onClose} />
      </div>
      <InputBrowser options={options} onPick={onPick}
                    purpose="an accessory reference"
                    gridStyle={{ maxHeight: "56vh" }} />
      {err && (
        <span role="alert" style={{ fontSize: TYPE.label, color: "#E3A7B0",
                                    lineHeight: 1.4 }}>{err}</span>
      )}
    </ModalShell>
  );
};

export const CharacterForm = ({ options, onClose, onSaved, refreshOptions,
                                history = [], editInput, editId = "" }) => {
  const [name, setName] = useState("");
  const [age, setAge] = useState("");
  const [race, setRace] = useState("");
  const [sex, setSex] = useState("female");
  const [style, setStyle] = useState("");
  // 9.95: the typed canon fields - build, hair, grooming - each composed as
  // its own sentence, build skipped on lanes with a wired reference.
  const [build, setBuild] = useState("");
  const [hair, setHair] = useState("");
  const [grooming, setGrooming] = useState("");
  const [notes, setNotes] = useState("");
  const [wardrobe, setWardrobe] = useState("");
  const [wardOpen, setWardOpen] = useState(false);
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(!!editId);
  const [editOpen, setEditOpen] = useState(false);
  const [cropOpen, setCropOpen] = useState(false);
  // Armed when an edit render is in flight for the reference: a snapshot of
  // history ids at launch, so the one entry that appears after it is ours.
  const [pendingEdit, setPendingEdit] = useState(null);
  // 9.83: the accessory reference rows — {k, image, description, enabled}.
  // `k` is a dialog-local uid so a removed row never shifts another's key;
  // it is stripped at save (the server stores image/description/enabled).
  const [accessories, setAccessories] = useState([]);
  const [accPickerOpen, setAccPickerOpen] = useState(false);
  // The uid of the row just added: its description input takes focus once.
  const [lastAcc, setLastAcc] = useState(null);
  const accKey = useRef(0);
  const narrow = useNarrow();

  // Edit mode: /api/options carries only the picker's summary, so the rest of
  // the record has to be fetched before the fields can be filled.
  useEffect(() => {
    if (!editId) return;
    let live = true;
    characterRecord(editId)
      .then((ch) => {
        if (!live || !ch) return;
        setName(ch.name || "");
        setAge(ch.age == null ? "" : String(ch.age));
        setRace(ch.race || "");
        setSex(ch.sex || "female");
        setStyle(ch.style || "");
        setBuild(ch.build || "");
        setHair(ch.hair || "");
        setGrooming(ch.grooming || "");
        setNotes(ch.notes || "");
        setWardrobe(ch.wardrobe_lock || "");
        // A custom lock is the one thing worth un-hiding on open: they wrote
        // it once, so they should see it is still in force.
        if (ch.wardrobe_lock) setWardOpen(true);
        setRef(ch.identity_ref || "");
        setAccessories((Array.isArray(ch.accessories) ? ch.accessories : [])
          .map((a) => ({ k: ++accKey.current, image: a.image || "",
                         description: a.description || "",
                         enabled: a.enabled !== false })));
      })
      .catch((e) => live && setErr(e?.message || "That anchor could not be loaded."))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [editId]);

  // Debounced so typing a name does not fire a request per keystroke.
  useEffect(() => {
    const ch = { name: name.trim(), sex, style: style.trim(),
                 wardrobe_lock: wardrobe.trim(), build: build.trim(),
                 hair: hair.trim(), grooming: grooming.trim() };
    if (age.trim()) ch.age = parseInt(age, 10) || age.trim();
    if (race.trim()) ch.race = race.trim();
    let live = true;
    const t = setTimeout(() => {
      characterPreview(ch).then((p) => live && setPreview(p)).catch(() => {});
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [name, age, race, sex, style, wardrobe, build, hair, grooming]);

  const inputAll = useMemo(() => inputImages(options), [options]);
  const refRecord = useMemo(
    () => (ref ? inputAll.find((i) => i.name === ref) || { name: ref } : null),
    [inputAll, ref]);
  // The lanes the Edit button can land on come from the server's own routing
  // answer (10.11's edit_routes), never a hard-coded recipe id — Settings can
  // route whole-frame edits to Klein, and this caller must follow.
  const editRoutes = options?.edit_routes || {};
  const editRecipe = (options?.recipes || [])
    .find((r) => r.id === (editRoutes.whole_frame || "qwen_edit"));
  const kleinRecipe = (options?.recipes || [])
    .find((r) => r.id === (editRoutes.masked || "klein_inpaint"));

  // Adopt the edit render the moment it lands: the first edit-lane entry that
  // was not in the launch snapshot is staged back into ComfyUI/input and
  // becomes the reference, closing the edit → reference loop in place.
  useEffect(() => {
    if (!pendingEdit) return undefined;
    const entry = (history || []).find((e) =>
      !pendingEdit.seen.has(e.id) &&
      (e.template === "qwen_edit" || e.template === "klein_edit" ||
       e.template === "klein_inpaint") &&
      (e.images || []).some((i) => (i.media || "image") === "image"));
    if (!entry) return undefined;
    let live = true;
    (async () => {
      try {
        const d = await stageInput(entry.id);
        if (!live) return;
        if (!d?.ok || !d.name)
          throw new Error(d?.error || "The edited reference could not be staged.");
        if (refreshOptions) await refreshOptions();
        if (!live) return;
        setRef(d.name);
        setPendingEdit(null);
      } catch (e) {
        if (!live) return;
        setPendingEdit(null);
        setErr(e?.message || "The edited reference could not be adopted.");
      }
    })();
    return () => { live = false; };
  }, [history, pendingEdit, refreshOptions]);

  // A picked (or freshly uploaded) image becomes a new enabled row with an
  // empty description - the one field the user must write, so it takes focus.
  const addAccessory = (name) => {
    const k = ++accKey.current;
    setAccessories((rows) => [...rows, { k, image: name, description: "",
                                         enabled: true }]);
    setLastAcc(k);
    setAccPickerOpen(false);
  };

  // Saving keys on a slug of the name, so a new anchor named like an existing
  // one silently replaces it. Say so before they press the button.
  const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const clash = !editId && slug
    && (options?.characters || []).find((c) => c.id === slug);

  const doUpload = async (f) => {
    if (!f) return;
    setBusy(true); setErr(null);
    try {
      const image = await upload(f, "identity");
      setRef(image.name);
      if (refreshOptions) await refreshOptions();
    } catch (error) {
      setErr(error?.message || "The reference image could not be uploaded.");
    } finally {
      setBusy(false);
    }
  };

  // The cutout uploads like any attached photo and immediately becomes the
  // reference — cropping never touches the original input image.
  const adoptCrop = async (blob) => {
    setBusy(true); setErr(null);
    try {
      const base = (ref.split("/").pop() || "ref").replace(/\.[^.]+$/, "");
      const file = new File([blob], `pixal_refcrop_${base.slice(0, 48)}.png`,
                           { type: "image/png" });
      const image = await upload(file, "identity");
      if (refreshOptions) await refreshOptions();
      setRef(image.name);
      setCropOpen(false);
    } catch (error) {
      setErr(error?.message || "The cropped reference could not be uploaded.");
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!name.trim()) { setErr("Give them a name."); return; }
    if (!ref) { setErr("Pick or upload their photo."); return; }
    // The description is load-bearing, not a caption: the model addresses a
    // wired reference by its <Subject N> definition, so an accessory without
    // one is refused here with the server's own words rather than as a 400.
    const accOut = accessories.map((a) => ({
      image: a.image,
      description: a.description.replace(/\s+/g, " ").trim(),
      enabled: a.enabled !== false,
    }));
    if (accOut.some((a) => !a.description)) {
      setErr("every accessory needs a description - the model names the wired picture by it");
      return;
    }
    setBusy(true); setErr(null);
    const ch = { name: name.trim(), sex, style: style.trim(), notes: notes.trim() };
    if (age.trim()) ch.age = parseInt(age, 10) || age.trim();
    if (race.trim()) ch.race = race.trim();
    if (wardrobe.trim()) ch.wardrobe_lock = wardrobe.trim();
    if (build.trim()) ch.build = build.trim();
    if (hair.trim()) ch.hair = hair.trim();
    if (grooming.trim()) ch.grooming = grooming.trim();
    if (accOut.length) ch.accessories = accOut;
    // The id is what makes this an EDIT rather than a second anchor: without it
    // the server re-slugs the name, and a renamed character forks in two.
    if (editId) ch.id = editId;
    ch.identity_ref = ref;
    try {
      const r = await fetch("/api/characters", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character: ch }) });
      const d = await r.json();
      if (d.ok) { onSaved(d.id); onClose(); }
      else setErr(d.error || "save failed");
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };

  return (
    <>
      <style>{CHARACTER_FORM_CSS}</style>
      <ModalShell onClose={onClose}
        boxProps={{ role: "dialog",
                    "aria-label": editId ? "Edit " + (name || "character") : "New character" }}
        boxStyle={{
          width: "min(960px, 94vw)",
          height: "min(720px, 88vh)", maxHeight: "88vh",
          background: "var(--bg1)", border: "1px solid var(--borderHov)",
          borderRadius: RADIUS.dialog, boxShadow: SHADOW.xl,
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}>
        <header style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                         flex: "0 0 auto", padding: SPACE[16],
                         paddingLeft: SPACE[24], paddingRight: SPACE[24],
                         borderBottom: "1px solid var(--border)" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: SPACE[8],
                         minWidth: 0, fontSize: TYPE.body, fontWeight: W.heading }}>
            <UserCircleDashed size={15} weight="duotone"
              style={{ color: "var(--accent)", flex: "0 0 auto" }} />
            <span title={editId ? "Edit " + (name || "character") : "New character"}
              style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>
              {editId ? "Edit " + (name || "character") : "New character"}
            </span>
          </span>
          <span className="px-cast-close" style={{ marginLeft: "auto",
                                                    display: "inline-flex",
                                                    borderRadius: RADIUS.card }}>
            <CloseBtn onClose={onClose} />
          </span>
        </header>

        <div className={narrow ? "px-scroll" : undefined}
          style={{ flex: "1 1 auto", minHeight: 0, minWidth: 0, display: "flex",
                   flexDirection: narrow ? "column" : "row",
                   overflowX: "hidden", overflowY: narrow ? "auto" : "hidden" }}>

          {/* LEFT - the face. The full-resolution portrait is the identity
              mechanism; actions and the compact swap strip stay with it. */}
          <aside aria-label="Identity photo"
            className={narrow ? undefined : "px-scroll"}
            style={{ width: narrow ? "100%" : 300,
                     flex: narrow ? "0 0 auto" : "0 0 300px",
                     minWidth: 0, minHeight: 0,
                     // The rail NEVER scrolls: the portrait gives up height
                     // first (its 3:4 is a maximum, not a floor), so no
                     // scrollbar can appear beside the face.
                     overflowX: "hidden", overflowY: narrow ? "visible" : "hidden",
                     paddingTop: SPACE[24], paddingBottom: SPACE[24],
                     paddingLeft: SPACE[24], paddingRight: narrow ? SPACE[24] : 0,
                     display: "flex", flexDirection: "column", gap: SPACE[12] }}>
            <div style={{ width: narrow ? "min(276px, 30vh)" : 276,
                          maxWidth: "100%", display: "flex", minHeight: 0,
                          flex: narrow ? "0 0 auto" : "0 1 auto",
                          flexDirection: "column", gap: SPACE[12] }}>
              {/* PORTRAIT TILE */}
              {refRecord ? (
                <div title="The photo decides the face — nothing typed here changes it."
                  style={{ position: "relative", width: "100%", aspectRatio: "3 / 4",
                           overflow: "hidden", borderRadius: RADIUS.dialog,
                           background: "var(--bg3)", minHeight: 0,
                           flex: narrow ? "0 0 auto" : "0 1 auto" }}>
                  <img src={inputFullUrl(ref)} alt={"Identity photo — " + ref}
                    decoding="async"
                    style={{ position: "absolute", inset: -1,
                             width: "calc(100% + 2px)",
                             height: "calc(100% + 2px)",
                             objectFit: "cover" }} />
                  {pendingEdit ? (
                    <EditingVeil label={pendingEdit.label || "Editing her photo"} />
                  ) : null}
                  {!pendingEdit && (
                  <div aria-hidden="true"
                    style={{ position: "absolute", left: -1, right: -1, bottom: -1,
                             height: 64,
                             background: `linear-gradient(transparent, ${GLASS_SOLID.background})`,
                             display: "flex", alignItems: "flex-end",
                             padding: SPACE[10], paddingLeft: SPACE[12],
                             paddingRight: SPACE[12] }}>
                    <span title={ref}
                      style={{ minWidth: 0, width: "100%", fontFamily: MONO,
                               fontSize: TYPE.micro,
                               color: `color-mix(in srgb, ${GLASS_INK} 75%, transparent)`,
                               overflow: "hidden", textOverflow: "ellipsis",
                               whiteSpace: "nowrap" }}>
                      {ref.split("/").pop()}
                    </span>
                  </div>
                  )}
                </div>
              ) : (
                <label className={"px-cast-drop" + (busy ? " is-busy" : "")}
                  title="The photo decides the face — nothing typed here changes it."
                  aria-busy={busy} aria-disabled={busy}
                  style={{ width: "100%", aspectRatio: "3 / 4",
                           position: "relative",
                           display: "flex", flexDirection: "column",
                           alignItems: "center", justifyContent: "center",
                           gap: SPACE[6], cursor: busy ? "wait" : "pointer",
                           border: "1px dashed var(--borderHov)",
                           borderRadius: RADIUS.dialog, background: "var(--bg2)",
                           color: "var(--textTer)", textAlign: "center",
                           padding: SPACE[12], opacity: busy ? 0.5 : 1 }}>
                  <UserCircleDashed size={26} weight="duotone" aria-hidden="true" />
                  <span style={{ fontSize: TYPE.ui, color: "var(--textSec)" }}>
                    {busy ? "Uploading…" : "Upload their photo"}
                  </span>
                  <span title="or pick one below — the anchor becomes selectable once a face is set"
                    style={{ maxWidth: "100%", fontSize: TYPE.label, lineHeight: 1.4 }}>
                    or pick one below — the anchor becomes selectable once a face is set
                  </span>
                  <input type="file" accept="image/*" aria-label="Upload identity photo"
                    disabled={busy}
                    style={{ position: "absolute", inset: 0, width: "100%",
                             height: "100%", opacity: 0,
                             cursor: busy ? "wait" : "pointer" }}
                    onChange={(e) => { doUpload(e.target.files[0]); e.target.value = ""; }} />
                </label>
              )}

              {/* FACE ACTIONS */}
              {refRecord && (pendingEdit ? (
                <span title="Editing — the result will replace it"
                  style={{ width: "100%", minWidth: 0, height: FIELD_H,
                           display: "inline-flex", alignItems: "center",
                           gap: SPACE[4], fontSize: TYPE.label,
                           color: "var(--textSec)", overflow: "hidden" }}>
                  <span style={{ flex: "1 1 auto", minWidth: 0, overflow: "hidden",
                                 textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    Editing — the result will replace it
                  </span>
                  <button type="button" className="px-cast-icon"
                    onClick={() => setPendingEdit(null)}
                    aria-label="Stop waiting for the edit"
                    title="Stop waiting for the edit"
                    style={{ flex: "0 0 auto", background: "none", border: "none",
                             borderRadius: RADIUS.card, padding: SPACE[2],
                             color: "var(--textTer)", cursor: "pointer",
                             display: "inline-flex" }}>
                    <X size={11} weight="bold" />
                  </button>
                </span>
              ) : (
                <div style={{ width: "100%", display: "grid",
                              gridTemplateColumns: "repeat(3, 1fr)",
                              gap: FACE_ACTION_GAP }}>
                  <Btn as="label"
                    className={"px-cast-btn px-cast-face" + (busy ? " is-busy" : "")}
                    aria-busy={busy} aria-disabled={busy}
                    title="Upload a different identity photo"
                    style={{ ...FACE_ACTION, position: "relative",
                             cursor: busy ? "wait" : "pointer" }}>
                    <ImageSquare size={12} weight="duotone"
                      style={{ flex: "0 0 auto" }} />
                    <span style={{ minWidth: 0, overflow: "hidden",
                                   textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {busy ? "Uploading…" : "Upload"}
                    </span>
                    <input type="file" accept="image/*" aria-label="Upload identity photo"
                      disabled={busy}
                      style={{ position: "absolute", inset: 0, width: "100%",
                               height: "100%", opacity: 0,
                               cursor: busy ? "wait" : "pointer" }}
                      onChange={(e) => { doUpload(e.target.files[0]); e.target.value = ""; }} />
                  </Btn>
                  <Btn className="px-cast-btn px-cast-face" disabled={busy}
                    onClick={() => setEditOpen(true)}
                    title="Change accessories, clothing or background — Identity Edit carries over everything in this photo, so fix it here"
                    style={FACE_ACTION}>
                    <PencilSimple size={12} weight="bold"
                      style={{ flex: "0 0 auto" }} />
                    <span style={{ minWidth: 0, overflow: "hidden",
                                   textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      Edit
                    </span>
                  </Btn>
                  <Btn className="px-cast-btn px-cast-face" disabled={busy}
                    onClick={() => setCropOpen(true)}
                    title="Keep only a region — Identity Edit sees just what you crop to"
                    style={FACE_ACTION}>
                    <Crop size={12} weight="bold" style={{ flex: "0 0 auto" }} />
                    <span style={{ minWidth: 0, overflow: "hidden",
                                   textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      Crop
                    </span>
                  </Btn>
                </div>
              ))}
            </div>

            <IdentityStrip options={options} selectedName={ref} onPick={setRef}
              disabled={busy} />
          </aside>

          {/* RIGHT - the person. Display name first, then the compact facts and
              three sentence-case groups from the approved casting sheet. */}
          <section aria-label="Character details"
            className={narrow ? undefined : "px-scroll"}
            style={{ flex: narrow ? "0 0 auto" : "1 1 0", minWidth: 0,
                     width: "100%", minHeight: 0,
                     overflowX: "hidden", overflowY: narrow ? "visible" : "auto",
                     padding: SPACE[24], display: "flex",
                     flexDirection: "column", gap: SPACE[20] }}>
            <div style={{ flex: "0 0 auto", minWidth: 0 }}>
              <input className="px-input px-cast-control px-cast-name"
                aria-label="Name" value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Mia" autoFocus
                style={{ width: "100%", minWidth: 0, height: NAME_H,
                         padding: `0 ${SPACE[12]}px`,
                         background: "transparent", border: "none",
                         borderRadius: RADIUS.card,
                         outline: "none", color: "var(--text)", fontFamily: FONT,
                         // Approved display-name exception: TYPE has no 28px step.
                         fontSize: 28, fontWeight: W.heading,
                         letterSpacing: "-0.01em", caretColor: "var(--accent)" }} />
              <div className="px-cast-meta"
                style={{ height: narrow ? "auto" : FIELD_H, minWidth: 0,
                         display: "flex", flexWrap: narrow ? "wrap" : "nowrap",
                         alignItems: "center", gap: SPACE[8],
                         marginTop: SPACE[12] }}>
                <div title={"Renders that wire the reference take face and age from the photo. " +
                            "Scenes without one still read this."}
                  style={{ width: 64, flex: "0 0 auto" }}>
                  <input className="px-input px-cast-control" aria-label="Age"
                    style={{ ...inputStyle, width: 64, height: FIELD_H,
                             borderRadius: RADIUS.card, padding: 0,
                             paddingLeft: SPACE[10], paddingRight: SPACE[10] }}
                    value={age} onChange={(e) => setAge(e.target.value)}
                    placeholder="24" />
                </div>
                <input className="px-input px-cast-control" aria-label="Race"
                  style={{ ...inputStyle, width: 120, height: FIELD_H, flex: "0 0 auto",
                           borderRadius: RADIUS.card, padding: 0,
                           paddingLeft: SPACE[10], paddingRight: SPACE[10] }}
                  value={race} onChange={(e) => setRace(e.target.value)}
                  placeholder="Korean" />
                <div className="px-cast-segment" style={{ flex: "0 0 auto" }}>
                  {/* Height-matched to the inputs beside it: controls sharing a
                      row are the same height outside to outside, always. */}
                  <SegmentedControl variant="pill" ariaLabel="sex" value={sex} onChange={setSex}
                    options={[{ v: "female", label: "Female" }, { v: "male", label: "Male" },
                              { v: "other", label: "Other" }]}
                    style={{ height: FIELD_H }} />
                </div>
              </div>
            </div>

            <Group label={<>Always true <InfoTip
                     text="only what is true in every picture — what changes shot to shot belongs in the prompt" /></>}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                            gap: SPACE[10], columnGap: SPACE[12], minWidth: 0 }}>
                <div style={{ gridColumn: "1 / -1", minWidth: 0 }}>
                  <Field label="Look">
                    <input className="px-input px-cast-control"
                      style={{ ...inputStyle, height: 34, borderRadius: RADIUS.card,
                               padding: 0, paddingLeft: SPACE[12],
                               paddingRight: SPACE[12], fontSize: TYPE.body }}
                      value={style} onChange={(e) => setStyle(e.target.value)}
                      placeholder="dresses down, one designer bag as the accent" />
                  </Field>
                </div>
                <div style={{ minWidth: 0 }}>
                  <Field label={<>Build <InfoTip text={"The photo already carries the "
                           + "build — prose here fights it. This field is skipped when a reference "
                           + "photo is wired."} /></>}>
                    <input className="px-input px-cast-control"
                      style={{ ...inputStyle, height: 34, borderRadius: RADIUS.card,
                               padding: 0, paddingLeft: SPACE[12],
                               paddingRight: SPACE[12], fontSize: TYPE.body }}
                      value={build} onChange={(e) => setBuild(e.target.value)}
                      placeholder="five foot seven, soft hourglass" />
                  </Field>
                </div>
                <div style={{ minWidth: 0 }}>
                  <Field label={<>Hair <InfoTip text="always sent — state the colour" /></>}>
                    <input className="px-input px-cast-control"
                      style={{ ...inputStyle, height: 34, borderRadius: RADIUS.card,
                               padding: 0, paddingLeft: SPACE[12],
                               paddingRight: SPACE[12], fontSize: TYPE.body }}
                      value={hair} onChange={(e) => setHair(e.target.value)}
                      placeholder="platinum, straight, to her lower back" />
                  </Field>
                </div>
                <div style={{ gridColumn: "1 / -1", minWidth: 0 }}>
                  <Field label="Grooming">
                    <input className="px-input px-cast-control"
                      style={{ ...inputStyle, height: 34, borderRadius: RADIUS.card,
                               padding: 0, paddingLeft: SPACE[12],
                               paddingRight: SPACE[12], fontSize: TYPE.body }}
                      value={grooming} onChange={(e) => setGrooming(e.target.value)}
                      placeholder="manicured nails, small hoop earrings, natural makeup" />
                  </Field>
                </div>
              </div>
            </Group>

            {/* 9.83: reference images wired beside the identity photo on the
                H3 lanes, each independently toggleable. The description is
                load-bearing - it becomes the wired picture's <Subject N>
                definition - and the count is the cost: every wired reference
                rides every sampling step.

                Called "accessories" until 1.1.4b, which undersold it. The
                single biggest fix of the 2026-08-30 reference session was
                wiring a SECOND PERSON here: a friend in frame rendered badly
                no matter how she was described, because a description is not
                the identity mechanism - the wired photograph is, and in a
                two-up she also gets half the pixels. Nothing in the data
                changed; the label was the whole barrier. */}
            <Group label={<>Wired references <InfoTip text={"On references are wired into "
                     + "every render of this anchor and ride every sampling step. Switch one "
                     + "off to keep it on the anchor but out of the graph, never sent to the "
                     + "model. Eight references fill the nine slots beside the identity photo. "
                     + "A reference can be a bag, a jacket, or a second person."} />
                     <span title={accessories.filter((a) => a.enabled).length +
                                  " / " + ACCESSORY_MAX + " wired references"}
                       style={{ marginLeft: SPACE[6], fontFamily: MONO,
                                fontSize: TYPE.micro, fontWeight: W.body,
                                letterSpacing: 0 }}>
                       {accessories.filter((a) => a.enabled).length} / {ACCESSORY_MAX}
                     </span></>}>
              <div style={{ display: "flex", flexDirection: "column", gap: SPACE[10] }}>
                {accessories.map((row) => {
                  const rec = inputAll.find((i) => i.name === row.image)
                    || { name: row.image };
                  return (
                    <div key={row.k}
                      style={{ display: "flex", alignItems: "center",
                               gap: SPACE[10], minWidth: 0 }}>
                      <img src={inputImgUrl(rec)} alt="" decoding="async" loading="lazy"
                        title={row.image}
                        style={{ width: 34, height: 34, objectFit: "cover",
                                 flex: "0 0 auto", borderRadius: RADIUS.card,
                                 border: "1px solid var(--border)" }} />
                      <input className="px-input px-cast-control"
                        style={{ ...inputStyle, height: 34, minWidth: 0,
                                 borderRadius: RADIUS.card, padding: 0,
                                 paddingLeft: SPACE[12], paddingRight: SPACE[12],
                                 fontSize: TYPE.body }}
                        value={row.description}
                        title={row.description || row.image.split("/").pop()}
                        aria-label={"Describe " + row.image.split("/").pop()}
                        autoFocus={row.k === lastAcc}
                        onChange={(e) => setAccessories(accessories.map((a) =>
                          a.k === row.k ? { ...a, description: e.target.value } : a))}
                        placeholder="green pebbled leather phone case" />
                      <Switch className="px-cast-switch" on={row.enabled}
                        label={row.description || row.image.split("/").pop()}
                        onChange={(next) => setAccessories(accessories.map((a) =>
                          a.k === row.k ? { ...a, enabled: next } : a))} />
                      <button type="button" className="px-cast-icon"
                        aria-label={"Remove " + (row.description || row.image.split("/").pop())}
                        title={"Remove " + (row.description || row.image.split("/").pop())}
                        onClick={() => setAccessories(accessories.filter((a) => a.k !== row.k))}
                        style={{ display: "inline-flex", alignItems: "center",
                                 padding: SPACE[4], background: "none", border: "none",
                                 borderRadius: RADIUS.card, cursor: "pointer",
                                 color: "var(--textTer)", flex: "0 0 auto" }}>
                        <X size={12} weight="bold" />
                      </button>
                    </div>
                  );
                })}
                <Btn className="px-cast-btn" disabled={accessories.length >= ACCESSORY_MAX}
                  onClick={() => setAccPickerOpen(true)}
                  style={{ alignSelf: "flex-start", height: FIELD_H,
                           border: "1px dashed var(--borderHov)",
                           borderRadius: RADIUS.card, background: "transparent" }}>
                  <Plus size={12} weight="bold" /> Add reference
                </Btn>
              </div>
            </Group>

            <Group label={<>For the writer <InfoTip
                     text="look and identity only, not jobs or lifestyle" /></>}
              style={{ flex: "1 1 auto" }}>
              <textarea className="px-input px-cast-control px-scroll px-cast-notes"
                aria-label="For the writer" value={notes}
                onChange={(e) => setNotes(e.target.value)} rows={3}
                placeholder="dry humour, competitive; hair changes daily; never poses, always mid-task"
                style={{ ...inputStyle, flex: "1 1 auto", minHeight: 64, resize: "none",
                         borderRadius: RADIUS.card,
                         lineHeight: 1.5, padding: SPACE[10],
                         paddingLeft: SPACE[12], paddingRight: SPACE[12],
                         fontSize: TYPE.body }} />
            </Group>
          </section>
        </div>

        <footer style={{ flex: "0 0 auto", minWidth: 0,
                         display: "flex", alignItems: "center", gap: SPACE[20],
                         padding: SPACE[16], paddingLeft: SPACE[24],
                         paddingRight: SPACE[24],
                         borderTop: "1px solid var(--border)",
                         background: "var(--bg0)" }}>
          <div style={{ flex: "1 1 auto", minWidth: 0 }}>
            <Disclosure open={wardOpen}
              contentStyle={{ minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center",
                            gap: SPACE[8], minWidth: 0,
                            paddingBottom: SPACE[10] }}>
                <input className="px-input px-cast-control"
                  aria-label="Wardrobe lock" style={{ ...inputStyle, height: 34,
                    minWidth: 0, borderRadius: RADIUS.card, padding: 0,
                    paddingLeft: SPACE[12], paddingRight: SPACE[12],
                    fontSize: TYPE.body }}
                  value={wardrobe} onChange={(e) => setWardrobe(e.target.value)}
                  placeholder="She is fully dressed in the clothing described above." />
                <InfoTip text={"The wardrobe clause closes the caption because "
                  + "the last clause is the strongest one — leave it blank for the generic "
                  + "lock. An explicit NSFW ask lifts it."} />
              </div>
            </Disclosure>
            <div title={(preview?.subject || "…") + "\nwith the reference wired — " +
                        (preview?.subject_ref || "…")}
              style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap", fontSize: TYPE.body, lineHeight: 1.5,
                       color: "var(--cream)" }}>
              {preview?.subject || "…"}
            </div>
            <div style={{ minWidth: 0, display: "flex",
                          alignItems: "center", gap: SPACE[6], marginTop: SPACE[2],
                          overflow: "hidden", fontSize: TYPE.label, lineHeight: 1.5,
                          color: "var(--textTer)" }}>
              {err ? (
                <span role="alert" title={err}
                  style={{ flex: "0 1 auto", minWidth: 0, overflow: "hidden",
                           textOverflow: "ellipsis", whiteSpace: "nowrap",
                           color: "#E3A7B0" }}>
                  {err}
                </span>
              ) : clash ? (
                <span role="status"
                  title={"Saving replaces the existing “" + clash.name + "” anchor"}
                  style={{ flex: "0 1 auto", minWidth: 0, overflow: "hidden",
                           textOverflow: "ellipsis", whiteSpace: "nowrap",
                           color: "#E3B98C" }}>
                  Saving replaces the existing “{clash.name}” anchor
                </span>
              ) : (
                <span title={"…scene… " + (preview?.wardrobe || "…")}
                  style={{ flex: "0 1 auto", minWidth: 0, overflow: "hidden",
                           textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  …scene… {preview?.wardrobe || "…"}
                </span>
              )}
              <span aria-hidden="true" style={{ flex: "0 0 auto" }}>·</span>
              <span className="px-cast-disclosure"
                style={{ minWidth: 0, flex: "0 1 auto" }}>
                <DisclosureTrigger open={wardOpen}
                  onToggle={() => setWardOpen((o) => !o)} caretSize={9}
                  title={wardrobe.trim() ? "Custom wardrobe lock"
                                         : "Customize the wardrobe lock"}
                  style={{ width: "auto", maxWidth: "100%", minWidth: 0,
                           display: "inline-flex", gap: SPACE[4],
                           borderRadius: RADIUS.card, color: "var(--textTer)",
                           fontSize: TYPE.label, textDecoration: "underline dotted",
                           textUnderlineOffset: SPACE[2] }}>
                  <span style={{ minWidth: 0, overflow: "hidden",
                                 textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {wardrobe.trim() ? "Custom wardrobe lock"
                                     : "Customize the wardrobe lock"}
                  </span>
                </DisclosureTrigger>
              </span>
            </div>
          </div>
          <Btn kind="primary" className="px-cast-btn px-cast-save"
            onClick={save} disabled={busy || loading}
            aria-busy={busy || loading}
            title={loading ? "Loading…" : editId ? "Save changes" : "Save character"}
            style={{ flex: "0 0 auto", alignSelf: "center",
                     height: 34, padding: 0, paddingLeft: SPACE[20],
                     paddingRight: SPACE[20], borderRadius: RADIUS.pill,
                     color: "var(--accentInk)", fontSize: TYPE.body,
                     fontWeight: W.heading }}>
            {loading ? "Loading…" : editId ? "Save changes" : "Save character"}
          </Btn>
        </footer>
      </ModalShell>

      {/* Rendered after the form so both stack above it. The editor is the
          same dialog every Edit click opens — no mask runs the configured
          whole-frame lane, a painted mask runs Klein inpaint — pointed at
          the full-res input. */}
      {editOpen && refRecord && (
        <EditDirector onClose={() => setEditOpen(false)}
          available={editRecipe ? editRecipe.available !== false : true}
          missing={(editRecipe && editRecipe.missing) || []}
          wholeFrameRecipe={editRecipe}
          kleinAvailable={kleinRecipe ? kleinRecipe.available !== false : true}
          kleinMissing={(kleinRecipe && kleinRecipe.missing) || []}
          imageUrl={inputFullUrl(ref)}
          onAction={async (instruction, extra) => {
            setPendingEdit({ seen: new Set((history || []).map((e) => e.id)) });
            setErr(null);
            const ok = await (editInput
              ? editInput(ref, instruction, extra) : Promise.resolve(false));
            if (!ok) {
              setPendingEdit(null);
              setErr("The edit could not be started.");
            }
          }} />
      )}
      {cropOpen && refRecord && (
        <CropDialog imageUrl={inputFullUrl(ref)} busy={busy}
          onClose={() => setCropOpen(false)} onUse={adoptCrop} />
      )}
      {accPickerOpen && (
        <AccessoryPicker options={options} refreshOptions={refreshOptions}
          onClose={() => setAccPickerOpen(false)} onPick={addAccessory} />
      )}
    </>
  );
};
