// Composer.jsx — the options bar inside the chat composer box.
// Docked-widget IA, ported from an earlier chat widget of mine: pills
// bottom-left (model / style / character / size / +ref), with compact
// attached-reference tabs beside the composer. The ordered LoRA chain lives
// in its execution rail (or in-flow on narrow layouts). Phosphor duotone per
// the design system; popovers open upward (composer sits at the page bottom).
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
// Character iconography is the Phosphor UserCircle family, by state:
// dashed = empty/draft, check = locked in, plus = create, plain = the
// automatic identity mode. UserFocus survives ONLY as the identity-REF glyph
// (a face-lock on a photo, not a character entity).
import {
  ArrowCounterClockwise, CaretDown, CaretLeft, CaretRight, CaretUp, Cube, DotsSixVertical,
  FilmSlate, ImageSquare, Lightning, LockSimple, MagnifyingGlass, Monitor, Palette, PencilSimple, Plus,
  Sparkle, SlidersHorizontal, Stack, Star, TagSimple, Trash, TShirt, UserCircle, UserCircleCheck,
  UserCircleDashed, UserCirclePlus, UserFocus, X,
} from "@phosphor-icons/react";
import { FONT, W, TYPE, SPACE, RADIUS, MOTION, SHADOW } from "../lib/design-tokens.js";
import { AspectShape } from "../lib/AspectShape.jsx";
import { SegmentedControl } from "../lib/SegmentedControl.jsx";
import { MiniSlider } from "../lib/MiniSlider.jsx";
import { Switch } from "../lib/Switch.jsx";
import { AccordionPanel, AccordionChevron } from "../lib/Accordion.jsx";
import { InfoTip } from "./InfoTip.jsx";
import { Picker } from "../lib/Picker.jsx";
import { familyName, tuningLine, variantName } from "../lib/names.js";
import { forgetCombo, inputImages, inputImgUrl, setInputRefType, starCombo, styleFromImage,
         styleSampler, upload } from "../transport.js";

const REF_KINDS = [
  { key: "identity", label: "identity", Icon: UserFocus },
  { key: "style",    label: "style",    Icon: Palette },
  { key: "clothing", label: "clothing", Icon: TShirt },
  { key: "object",   label: "object",   Icon: Cube },
];
const REF_ICON = Object.fromEntries(REF_KINDS.map((k) => [k.key, k.Icon]));
// "edit photo" rides in the same picker but is NOT a reference kind: the four
// above are conditioning for a render, this one names the source Qwen Image Edit
// rewrites. Kept out of REF_KINDS so no graph, saved tag or attach path can
// mistake it for a ref.
const EDIT_KIND = { key: "edit", label: "edit photo", Icon: PencilSimple };
const PICK_KINDS = [...REF_KINDS, EDIT_KIND];
// Newest-first is the right default and the wrong only option: the reference you
// want is often an old one you remember by name, not by when you uploaded it.
const REF_SORTS = [
  { key: "new",  label: "newest" },
  { key: "old",  label: "oldest" },
  { key: "name", label: "A–Z" },
];

const short = (n) => (n || "").split("\\").pop().split("/").pop()
  .replace(/\.(safetensors|gguf|ckpt|pt|pth)$/i, "");

// ── small shared bits ────────────────────────────────────────────────────────
const PillBtn = ({ Icon, label, active, onClick, children, maxWidth = 190, title }) => (
  <button
    type="button"
    title={title}
    onClick={onClick}
    style={{
      display: "inline-flex", alignItems: "center", gap: SPACE[6],
      height: 28, padding: `0 ${SPACE[10]}px`,
      fontFamily: FONT, fontSize: TYPE.ui, fontWeight: W.body,
      color: active ? "var(--accent)" : "var(--textSec)",
      background: active ? "var(--accentMut)" : "transparent",
      border: "none", borderRadius: RADIUS.control, cursor: "pointer",
      transition: `background ${MOTION.hover}, color ${MOTION.hover}`,
      maxWidth,
    }}
    onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = "var(--bg3)"; }}
    onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}
  >
    {Icon}
    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
    {children}
  </button>
);

// A PillBtn with no label: same 28px height, but round, so it costs one glyph
// of row width instead of a word. The attach control leads the row and is the
// one control there whose meaning is carried entirely by its icon.
const RoundBtn = ({ Icon, active, onClick, title, badge }) => (
  <button
    type="button"
    title={title}
    aria-label={title}
    onClick={onClick}
    style={{
      position: "relative", display: "inline-flex", alignItems: "center",
      justifyContent: "center", flex: "none", width: 28, height: 28, padding: 0,
      color: active ? "var(--accent)" : "var(--textSec)",
      background: active ? "var(--accentMut)" : "transparent",
      border: "none", borderRadius: "50%", cursor: "pointer",
      transition: `background ${MOTION.hover}, color ${MOTION.hover}`,
    }}
    onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = "var(--bg3)"; }}
    onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}
  >
    {Icon}
    {badge ? (
      <span aria-hidden="true" style={{
        position: "absolute", top: -1, right: -1, minWidth: 13, height: 13,
        padding: "0 3px", borderRadius: RADIUS.pill,
        fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
        lineHeight: "13px", textAlign: "center",
        background: "var(--accent)", color: "var(--bg1)",
      }}>{badge}</span>
    ) : null}
  </button>
);

const Pop = ({ title, onClose, wide, xl, down = false, alignRight = false,
               rail = false, anchorRef, boundsRef, children }) => {
  const ref = useRef(null);
  const [railGeometry, setRailGeometry] = useState(null);
  const [shift, setShift] = useState(0);
  const shiftRef = useRef(0);        // measure() reads this, not the closure
  const pinRef = useRef(null);       // viewport-left the panel settled on when it opened
  const measureRef = useRef(null);   // the clamp, re-run on every render (see below)

  useLayoutEffect(() => {
    if (!rail) return undefined;
    const measure = () => {
      const anchor = anchorRef?.current;
      const bounds = boundsRef?.current;
      if (!anchor || !bounds) return;
      const anchorBox = anchor.getBoundingClientRect();
      const boundsBox = bounds.getBoundingClientRect();
      const viewportInset = 8;
      const cardInset = SPACE[8];
      const left = Math.max(viewportInset, boundsBox.left + cardInset);
      const right = Math.min(window.innerWidth - viewportInset, boundsBox.right - cardInset);
      const topBound = Math.max(viewportInset, boundsBox.top + cardInset);
      const bottomBound = Math.min(window.innerHeight - viewportInset,
        boundsBox.bottom - cardInset);
      const belowTop = anchorBox.bottom + SPACE[6];
      const aboveBottom = anchorBox.top - SPACE[6];
      const belowRoom = Math.max(0, bottomBound - belowTop);
      const aboveRoom = Math.max(0, aboveBottom - topBound);
      const opensDown = belowRoom >= 180 || belowRoom >= aboveRoom;
      const available = opensDown ? belowRoom : aboveRoom;
      setRailGeometry({
        left,
        width: Math.max(0, right - left),
        ...(opensDown ? { top: belowTop } : {
          bottom: Math.max(viewportInset, window.innerHeight - aboveBottom),
        }),
        maxHeight: Math.max(0, Math.min(420, available)),
      });
    };
    measure();
    window.addEventListener("resize", measure);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    if (boundsRef?.current) observer?.observe(boundsRef.current);
    return () => {
      window.removeEventListener("resize", measure);
      observer?.disconnect();
    };
  }, [rail, anchorRef, boundsRef]);

  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    // Click-away via a document listener, NOT a fixed scrim: the composer's
    // backdrop-filter makes ancestors containing blocks, which silently traps
    // a position:fixed scrim inside the composer box. The panel's parent is
    // the pill+popover wrapper, so the opener pill keeps its own toggle.
    const down = (e) => {
      const panel = ref.current;
      const host = anchorRef?.current || panel?.parentElement;
      if (panel && !panel.contains(e.target) && (!host || !host.contains(e.target))) onClose();
    };
    window.addEventListener("keydown", k);
    document.addEventListener("pointerdown", down);
    return () => {
      window.removeEventListener("keydown", k);
      document.removeEventListener("pointerdown", down);
    };
  }, [onClose, anchorRef]);

  // A composer popup is position:absolute inside the composer, and the
  // composer clips. So a pill near the right edge opens a panel whose tail is
  // simply cut off - on the character anchor at 1400px wide that removed 26 of
  // the delete button's 28 pixels, leaving a control that looked like it did
  // not exist (2026-08-22). Nothing in the CSS says so; the panel reports its
  // full width and the pixels are just not painted.
  //
  // So measure against whatever actually clips us and slide back inside. A
  // transform, not a left/right change, so the anchoring rules above stay the
  // single source of truth for where the panel wants to be.
  useLayoutEffect(() => {
    if (rail) return;                      // rail mode is already measured
    const panel = ref.current;
    if (!panel) return;
    shiftRef.current = 0;                  // a fresh open measures from scratch
    const clipper = (() => {
      for (let n = panel.parentElement; n && n !== document.body; n = n.parentElement) {
        const ox = getComputedStyle(n).overflowX;
        if (ox && ox !== "visible") return n;
      }
      return null;
    })();
    const pad = SPACE[8];
    pinRef.current = null;
    const measure = () => {
      const box = ref.current?.getBoundingClientRect();
      if (!box) return;
      // The rect already includes whatever shift is on the panel right now, so
      // subtract it to get where the panel WANTS to be. That value has to come
      // from a ref: this closure is built once per open, so reading the state
      // would forever see the shift as 0, "undo" the correction it just made,
      // and settle back on the clipped position - which is exactly what it did
      // (measured: 776 -> shift -37 -> 739 -> shift 0 -> 776).
      const cur = shiftRef.current;
      const bounds = clipper ? clipper.getBoundingClientRect()
                             : { left: 0, right: window.innerWidth };
      const natural = box.left - cur;
      // Pinned while open: picking "1.5 MP" rewrites the opener pill's label,
      // the pill row reflows, and the panel's anchor moves under it - the
      // panel used to follow, half off the composer (Jesse, 2026-08-25, the
      // canvas popover in a windowed Pixal). The first measure decides where
      // the panel sits; later ones only keep it there, re-clamped to the
      // current bounds.
      const want = pinRef.current == null ? natural : pinRef.current;
      const lo = bounds.left + pad;
      const hi = Math.max(lo, bounds.right - pad - box.width);
      const target = Math.min(hi, Math.max(lo, want));
      if (pinRef.current == null) pinRef.current = target;
      const next = Math.round(target - natural);
      if (next === cur) return;
      shiftRef.current = next;
      setShift(next);
    };
    measureRef.current = measure;
    measure();
    // The panel's width is content-driven, so a list that finishes loading can
    // move the edge after mount. Watching the box beats depending on children,
    // which is a fresh object every render and would re-measure on every
    // keystroke inside the popup.
    const ro = typeof ResizeObserver === "function"
      ? new ResizeObserver(measure) : null;
    if (ro) ro.observe(panel);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("resize", measure);
      ro?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rail, wide, xl, alignRight, down]);

  // Every render, not only panel resizes: the anchor moving under the panel
  // (a sibling pill changing width) resizes nothing the observer watches.
  // One rect read per render is nothing.
  useLayoutEffect(() => { if (!rail) measureRef.current?.(); });

  const panel = (
    <div ref={ref} className={rail ? undefined : "px-scroll"} style={{
      position: rail ? "fixed" : "absolute", zIndex: rail ? 45 : 25,
      ...(rail ? (railGeometry || {}) : {
        ...(down ? { top: "calc(100% + 6px)" } : { bottom: "calc(100% + 6px)" }),
        ...(alignRight ? { right: 0 } : { left: 0 }),
      }),
      ...(shift ? { transform: `translateX(${shift}px)` } : null),
      minWidth: rail ? 0 : xl ? 384 : wide ? 300 : 230,
      maxWidth: rail ? "none" : xl ? "min(430px, 92vw)" : "min(340px, 86vw)",
      maxHeight: rail ? railGeometry?.maxHeight || 0
        : xl ? "min(460px, calc(100dvh - 200px))"
             : "min(330px, calc(100dvh - 200px))",
      visibility: rail && !railGeometry ? "hidden" : "visible",
      display: "flex", flexDirection: "column", overflow: "hidden",
      boxSizing: "border-box", background: "var(--bg1)",
      border: "1px solid var(--borderHov)", borderRadius: RADIUS.card,
      boxShadow: "0 10px 28px rgba(0,0,0,0.5)", padding: SPACE[8],
    }}>
      <div style={{
        margin: `2px 4px ${SPACE[10]}px`, flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: SPACE[8], fontSize: TYPE.ui, fontWeight: W.nav, color: "var(--text)",
      }}>{title}</div>
      <div className="px-scroll" style={{ minHeight: 0, overflowY: "auto" }}>
        {children}
      </div>
    </div>
  );
  // Portal to the app root rather than document.body: this escapes the rail's
  // overflow clip while retaining the active theme's CSS custom properties.
  const portalHost = rail
    ? boundsRef?.current?.closest(".px-root") || document.querySelector(".px-root")
    : null;
  return rail ? createPortal(panel, portalHost || document.body) : panel;
};

/* A picker row. The selected one is a SURFACE, not a tinted word: accent-muted
   fill plus an inset accent rail, which is what PillBtn and the toggle rows in
   this file already use for "on". Recolouring the label alone was the whole
   affordance, and in an eighteen-row shelf nobody could tell which one they
   were on. Hover stays --bg3 and never fires on the selected row, so the two
   states can't be confused for each other. */
const Row = ({ sel, onClick, children, style, disabled = false, title }) => (
  <button
    type="button"
    title={title}
    disabled={disabled}
    onClick={disabled ? undefined : onClick}
    style={{
      display: "flex", alignItems: "center", gap: SPACE[8], width: "100%",
      padding: `${SPACE[6]}px ${SPACE[8]}px`, border: "none", borderRadius: RADIUS.input,
      background: sel ? "var(--accentMut)" : "transparent",
      boxShadow: sel ? "inset 2px 0 0 var(--accent)" : "none",
      color: sel ? "var(--accent)" : "var(--textSec)",
      fontFamily: FONT, fontSize: TYPE.ui, fontWeight: sel ? W.nav : W.body,
      textAlign: "left",
      cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.62 : 1,
      transition: `background ${MOTION.hover}`, ...style,
    }}
    onMouseEnter={(e) => {
      if (!disabled && !sel) e.currentTarget.style.background = "var(--bg3)";
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.background = sel ? "var(--accentMut)" : "transparent";
    }}
  >
    {children}
  </button>
);

const Tag = ({ children, title }) => (
  <span title={title}
        style={{ marginLeft: "auto", fontFamily: "ui-monospace, Consolas, monospace",
                 fontSize: 9, color: "var(--textTer)", minWidth: 0,
                 overflow: "hidden", textOverflow: "ellipsis",
                 whiteSpace: "nowrap" }}>{children}</span>
);

const MONO = "ui-monospace, Consolas, monospace";

/* ── canvas menu ───────────────────────────────────────────────────────
   A labelled group with its current value stated on the same line, so the
   menu answers "what is this set to" without you decoding which chip is
   lit. Aspect and megapixels are different questions and now look it. */
const SizeGroup = ({ label, value, children }) => (
  <div>
    <div style={{ display: "flex", alignItems: "baseline", gap: SPACE[8],
                  padding: `0 2px ${SPACE[8]}px` }}>
      <span style={{ fontSize: TYPE.micro, fontWeight: W.heading,
                     letterSpacing: "0.08em", textTransform: "uppercase",
                     color: "var(--textTer)" }}>{label}</span>
      <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 9,
                     color: "var(--textTer)", whiteSpace: "nowrap" }}>{value}</span>
    </div>
    {children}
  </div>
);

/* ── chip census (brief 9.20, 2026-08-23; lines as of that date) ───────
   Eight components answer to "chip". Which are the same control:
   - NewChip (:373) ≡ VariantChip (:383): the identical 9px pill shell,
     filled-accent vs outlined - one badge, two tones.
   - Chip (SettingsMenu.jsx:192), MiniChip (SettingsMenu.jsx:393) and
     BrainChip's inner tag (Chat.jsx:50) are three more size/tone points of
     that same static badge. Five implementations, ONE control: a tiny
     non-interactive label with tone (filled / outlined / accent) and size
     (8-9px) axes - the fold candidate for a future brief.
   - SizeChip (below) and Pill (Chat.jsx:341) are both <button>s but
     genuinely different controls: a grid toggle with selected state vs an
     action button. Neither is a badge.
   - Tag (:289) is a chip in name only - unbordered mono metadata text.
   - BrainChip (Chat.jsx:48) is a composite status line that CONTAINS
     chips, not one itself.
   Reading only, no refactor - the next brief that touches chips inherits
   this map. */
const SizeChip = ({ on, wide, title, onClick, children, disabled = false }) => (
  // aria-disabled, not the attribute: a disabled button swallows mouse events
  // and the title (the cap's explanation) would never show.
  <button type="button" title={title} onClick={disabled ? undefined : onClick}
    aria-disabled={disabled || undefined}
    style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      height: 32, width: "100%", ...(wide ? { marginTop: SPACE[6] } : null),
      border: "1px solid", borderRadius: RADIUS.input,
      borderColor: on ? "var(--accent)" : "var(--border)",
      background: on ? "var(--accentMut)" : "transparent",
      color: on ? "var(--accent)" : "var(--textSec)",
      fontFamily: FONT, fontSize: TYPE.ui, whiteSpace: "nowrap",
      cursor: disabled ? "default" : "pointer",
      opacity: disabled ? 0.35 : 1,
      transition: `border-color ${MOTION.hover}`,
    }}
    onMouseEnter={(e) => { if (!on && !disabled) e.currentTarget.style.borderColor = "var(--borderHov)"; }}
    onMouseLeave={(e) => { if (!on) e.currentTarget.style.borderColor = "var(--border)"; }}
  >{children}</button>
);

// The unit, set small against the figure: the number is what you compare.
const Unit = ({ children }) => (
  <i style={{ fontStyle: "normal", fontSize: TYPE.micro, opacity: 0.6,
              marginLeft: 2 }}>{children}</i>
);

// ASPECTS ship as "3:4 (Portrait Standard)"; the name is the useful half here.
const aspectName = (a) => (String(a).match(/\(([^)]+)\)/) || [, String(a)])[1];

// Mirrors server.py dims_for() exactly — same grid, same candidate search,
// same weighting, same half-up rounding (which is why the server does NOT use
// Python's bankers round()). If that function changes, this changes with it: a
// canvas readout that disagrees with what renders is worse than no readout.
const CANVAS_MULTIPLE = 16;
const CANVAS_RATIO_WEIGHT = 6;
const dimsFor = (aspect, mp, multiple = CANVAS_MULTIPLE) => {
  const [aw, ah] = String(aspect).split(" ")[0].split(":").map(Number);
  const ratio = aw / ah;
  const target = Math.max(0, Number(mp)) * 1e6;
  const step = Math.max(1, Math.trunc(multiple));
  if (!(target > 0) || !(ratio > 0)) return null;
  const centre = Math.max(1, Math.round(Math.sqrt(target * ratio) / step));
  let best = null;
  for (let offset = -3; offset <= 3; offset += 1) {
    const w = (centre + offset) * step;
    if (w < step) continue;
    const h = Math.max(step, Math.round(w / ratio / step) * step);
    const score = Math.abs(w * h - target) / target
      + CANVAS_RATIO_WEIGHT * Math.abs((w / h) - ratio) / ratio;
    // Ties go to the larger canvas, matching the server's (score, -area) key.
    if (!best || score < best.score - 1e-12
        || (score - best.score <= 1e-12 && w * h > best.w * best.h))
      best = { score, w, h };
  }
  return best ? [best.w, best.h] : null;
};

// Badges a model that arrived after Pixal already knew the collection - the
// point of a rescan is finding what you just downloaded.
const NewChip = () => (
  <span style={{
    flexShrink: 0, padding: "0 5px", borderRadius: RADIUS.pill, lineHeight: "13px",
    background: "var(--accent)", color: "var(--bg1)", fontFamily: FONT,
    fontSize: 9, fontWeight: 600,
  }}>New</span>
);

// Quiet outlined counterpart to NewChip: says what is inside without competing
// with it. Z-Image Base vs Turbo is the split this exists for.
const VariantChip = ({ children }) => (
  <span style={{
    flexShrink: 0, padding: "0 5px", borderRadius: RADIUS.pill, lineHeight: "13px",
    border: "1px solid var(--border)", color: "var(--textTer)", fontFamily: FONT,
    fontSize: 9,
  }}>{children}</span>
);

// One family = one folder. Two tight lines: what it is, and what is in it.
// A blocked family is dimmed but still opens: the point of greying rather than
// hiding is that the builds inside stay countable and browsable.
const FamilyCard = ({ family, selected, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    title={`${family.label} · ${family.models.length} installed${
      family.blocked ? " · unavailable while an identity source is set" : ""}`}
    style={{
      display: "flex", flexDirection: "column", alignItems: "flex-start",
      gap: 3, padding: `${SPACE[6]}px ${SPACE[8]}px`, minWidth: 0,
      border: `1px solid ${selected ? "var(--accent)" : "var(--border)"}`,
      borderRadius: RADIUS.input, background: selected ? "var(--bg3)" : "var(--bg2)",
      color: "var(--text)", fontFamily: FONT, fontSize: TYPE.label, textAlign: "left",
      cursor: "pointer", opacity: family.blocked ? 0.55 : 1,
      transition: `background ${MOTION.hover}`,
    }}
    onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg3)"; }}
    onMouseLeave={(e) => {
      e.currentTarget.style.background = selected ? "var(--bg3)" : "var(--bg2)";
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: SPACE[4],
                  width: "100%", minWidth: 0, lineHeight: "15px" }}>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}>{family.label}</span>
      {family.isNew && <NewChip />}
      <CaretRight size={10} weight="bold" style={{ marginLeft: "auto", flexShrink: 0,
                                                   color: "var(--textTer)" }} />
    </div>
    <div style={{ display: "flex", alignItems: "center", gap: SPACE[4],
                  flexWrap: "wrap", minWidth: 0 }}>
      {family.variants.length > 1
        ? family.variants.map((v) => (
          <VariantChip key={v.name}>{v.name} {v.count}</VariantChip>
        ))
        : (
          <span style={{ fontSize: 9, fontFamily: "ui-monospace, Consolas, monospace",
                         color: "var(--textTer)", lineHeight: "13px" }}>
            {family.models.length} {family.models.length === 1 ? "build" : "builds"}
          </span>
        )}
    </div>
  </button>
);

// A search field states itself with its icon, not a sentence of
// placeholder: `icon` pins a glyph inside the field's left edge and the
// input's padding steps aside for it. No icon = the plain full-width input
// it always was.
const FilterInput = ({ value, onChange, autoFocus, placeholder, icon }) => {
  const field = (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      autoFocus={autoFocus}
      style={{
        width: "100%", height: 32, background: "var(--bg2)",
        border: "1px solid var(--border)", borderRadius: RADIUS.input,
        padding: `0 ${SPACE[10]}px 0 ${icon ? 26 : SPACE[10]}px`,
        fontSize: TYPE.ui, color: "var(--text)",
        fontFamily: FONT, outline: "none",
        ...(icon ? {} : { marginBottom: SPACE[6] }),
      }}
    />
  );
  if (!icon) return field;
  return (
    <div style={{ position: "relative", marginBottom: SPACE[6] }}>
      <span aria-hidden="true"
            style={{ position: "absolute", left: 8, top: 0, bottom: 0,
                     display: "inline-flex", alignItems: "center",
                     color: "var(--textTer)", pointerEvents: "none" }}>
        {icon}
      </span>
      {field}
    </div>
  );
};

// ── lora thumbnails ──────────────────────────────────────────────────────────
// Lora-Manager previews: shimmer while loading, 200ms fade-in, video previews
// hold their first frame and play on hover. No preview = quiet Stack glyph.
const thumbMedia = (loaded) => ({
  position: "absolute", inset: 0, width: "100%", height: "100%",
  objectFit: "cover", opacity: loaded ? 1 : 0,
  transition: "opacity 200ms cubic-bezier(0.16,1,0.3,1)",
});

const LoraThumb = ({ src, size = 44, fill = false, Glyph = Stack }) => {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  // fill = stretch to the grid cell instead of a fixed square, for the browse tiles
  const box = fill
    ? { width: "100%", aspectRatio: "1 / 1", borderRadius: RADIUS.inner,
        overflow: "hidden", position: "relative", background: "var(--bg2)" }
    : { width: size, height: size, borderRadius: RADIUS.inner, flexShrink: 0,
        overflow: "hidden", position: "relative", background: "var(--bg2)" };
  if (!src || failed) {
    return (
      <div aria-hidden="true" style={{ ...box, display: "flex", alignItems: "center",
                                       justifyContent: "center", color: "var(--textMut)" }}>
        <Glyph size={Math.round(size * 0.36)} weight="duotone" />
      </div>
    );
  }
  return (
    <div aria-hidden="true" style={box}>
      {!loaded && <div className="px-thumbload" style={{ position: "absolute", inset: 0 }} />}
      {/\.(mp4|webm)(\?|$)/i.test(src) ? (
        <video src={src} muted loop playsInline preload="metadata"
          onLoadedData={() => setLoaded(true)} onError={() => setFailed(true)}
          onMouseEnter={(e) => e.currentTarget.play().catch(() => {})}
          onMouseLeave={(e) => { e.currentTarget.pause(); e.currentTarget.currentTime = 0; }}
          style={thumbMedia(loaded)} />
      ) : (
        <img src={src} alt="" loading="lazy" decoding="async"
          onLoad={() => setLoaded(true)} onError={() => setFailed(true)}
          style={thumbMedia(loaded)} />
      )}
    </div>
  );
};

// The list density: a scan-by-name mode for when you already know the one you
// want. The row has the width the grid tile lacks, so the name stands whole -
// no clamp, no ellipsis; the distinguishing tail of a community LoRA name is
// exactly what this mode is for. Same thumb, same badges, same filtered set -
// a view is a density, not a different screen.
// A list row, not a card: fixed 44px on a hairline, the cover at 32, the name
// at UI size in text colour - one rhythm for the whole list (Jesse,
// 2026-08-25: "the spacing is so poor").
const LoraRow = ({ lora, onClick, reason }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={!!reason}
    title={[reason || null,
            lora.vectors ? `${lora.vectors} Vector` : null,
            (lora.words || []).join(", ") || lora.name]
             .filter(Boolean).join(" — ")}
    style={{
      display: "flex", alignItems: "center", gap: SPACE[10],
      padding: `${SPACE[6]}px ${SPACE[6]}px`, minHeight: 44, boxSizing: "border-box",
      width: "100%", minWidth: 0,
      border: "none", borderBottom: "1px solid var(--border)",
      borderRadius: RADIUS.inner,
      background: "transparent", color: "var(--text)", fontFamily: FONT,
      fontSize: TYPE.ui, textAlign: "left",
      cursor: reason ? "default" : "pointer",
      opacity: reason ? 0.5 : 1,
      transition: `background ${MOTION.hover}`,
    }}
    onMouseEnter={(e) => { if (!reason) e.currentTarget.style.background = "var(--bg2)"; }}
    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
  >
    <LoraThumb src={lora.thumb} size={32} />
    <span style={{ flex: 1, minWidth: 0, lineHeight: 1.3,
                   overflowWrap: "anywhere" }}>
      {lora.title || lora.short || lora.name}
      {reason && (
        <span style={{ display: "block", fontFamily: "ui-monospace, Consolas, monospace",
                       fontSize: 9, color: "var(--textMut)" }}>{reason}</span>
      )}
    </span>
    {lora.is_new && <NewChip />}
    {lora.vectors ? (
      <span style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
                     color: "var(--textMut)", whiteSpace: "nowrap", flexShrink: 0 }}>
        {lora.vectors} Vector
      </span>
    ) : null}
  </button>
);

// A LoRA is chosen by its preview, not its filename - lora-manager gives us a
// thumbnail for nearly all of them. A grid of those shows ~15 at a glance where
// the old text rows showed 6, which is the whole difference between browsing a
// collection and scrolling one.
const LoraTile = ({ lora, onClick, reason }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={!!reason}
    title={[reason || null,
            lora.vectors ? `${lora.vectors} Vector` : null,
            (lora.words || []).join(", ") || lora.name]
             .filter(Boolean).join(" — ")}
    style={{
      display: "flex", flexDirection: "column", gap: SPACE[6], padding: 4, minWidth: 0,
      border: "1px solid transparent", borderRadius: RADIUS.input,
      background: "transparent", color: "var(--textSec)", fontFamily: FONT,
      fontSize: TYPE.label, textAlign: "left",
      cursor: reason ? "default" : "pointer",
      opacity: reason ? 0.5 : 1,
      contentVisibility: "auto", containIntrinsicSize: "120px 150px",
      transition: `border-color ${MOTION.hover}`,
    }}
    onMouseEnter={(e) => { if (!reason) e.currentTarget.style.borderColor = "var(--accent)"; }}
    onMouseLeave={(e) => { e.currentTarget.style.borderColor = "transparent"; }}
  >
    {/* The badge rides the cover, not the name line: the name's two-line
        clamp is 9.19c's measured compromise, and a chip beside it would fight
        for the width the tail needs. */}
    <div style={{ position: "relative" }}>
      <LoraThumb src={lora.thumb} fill />
      {lora.is_new && (
        <span style={{ position: "absolute", top: 6, right: 6 }}>
          <NewChip />
        </span>
      )}
    </div>
    {/* Two lines, and the tail is what matters: a community LoRA's
        distinguishing suffix sits at the END of its name, so mid-token
        breaks are allowed (line two fills instead of the name clipping at
        the first word gap) and the full string rides one hover away. */}
    <span title={lora.title || lora.short || lora.name}
          style={{ lineHeight: 1.3, overflow: "hidden",
                   display: "-webkit-box", WebkitBoxOrient: "vertical",
                   WebkitLineClamp: 2, overflowWrap: "anywhere" }}>
      {lora.title || lora.short || lora.name}
    </span>
    {/* The one micro line under the name goes to the reason when there is one -
        why this file is greyed outranks how many vectors it carries. */}
    {reason ? (
      <span style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
                     color: "var(--textMut)", overflow: "hidden",
                     textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {reason}
      </span>
    ) : lora.vectors ? (
      <span style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
                     color: "var(--textMut)", overflow: "hidden",
                     textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {lora.vectors} Vector
      </span>
    ) : null}
  </button>
);

// ── attached-source icons (composer top-right, beside prompt enhance) ────────
// Every attached identity/character/style/clothing/object is one quiet 40×30
// glyph in the sparkle's own row — same hit target, stacked leftward from it.
// Hover (or focus) lifts a card above the composer showing the actual pixels
// riding the next render; click detaches. Replaced the bud-on-the-edge tab
// strip (2026-08-11): chrome outside the composer read as clutter.
export const AttachmentIcon = ({ Icon, ident, label, image, onRemove,
                                 hint = "click to detach" }) => {
  const [hover, setHover] = useState(false);
  const [thumbFailed, setThumbFailed] = useState(false);
  return (
    <span role="listitem" style={{ position: "relative", display: "inline-flex" }}>
      <button type="button" aria-label={`Remove ${label}`} onClick={onRemove}
        onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
        onFocus={() => setHover(true)} onBlur={() => setHover(false)}
        style={{
          width: 40, height: 30, padding: 0, display: "inline-flex",
          alignItems: "center", justifyContent: "center",
          border: "1px solid transparent", borderRadius: RADIUS.pill,
          background: hover ? "var(--bg3)" : "transparent",
          // Every icon here IS an active attachment, so the whole row reads
          // in the enabled accent (Jesse, 2026-08-18), not just identity.
          color: "var(--accent)", cursor: "pointer",
          transition: `background ${MOTION.hover}, color ${MOTION.hover}`,
        }}>
        <Icon size={18} weight="duotone" aria-hidden="true" />
      </button>
      {hover && (
        <div role="tooltip" style={{
          position: "absolute", bottom: "calc(100% + 8px)", right: 0, width: 148,
          padding: SPACE[6], pointerEvents: "none", zIndex: 8,
          background: "var(--bg1)", border: "1px solid var(--borderHov)",
          borderRadius: RADIUS.card, boxShadow: SHADOW.md,
        }}>
          {image && !thumbFailed && (
            <img src={image} alt="" decoding="async"
                 onError={() => setThumbFailed(true)}
                 style={{ width: "100%", height: 120, objectFit: "cover",
                          borderRadius: RADIUS.input, display: "block" }} />
          )}
          <div style={{ marginTop: image && !thumbFailed ? SPACE[6] : 0,
                        fontFamily: FONT, fontSize: TYPE.label,
                        color: "var(--accent)",
                        // No thumbnail means the label IS the payload (the
                        // frozen seed): wrap it whole instead of ellipsizing.
                        ...(image && !thumbFailed
                          ? { overflow: "hidden", textOverflow: "ellipsis",
                              whiteSpace: "nowrap" }
                          : { overflowWrap: "anywhere" }) }}>{label}</div>
          <div style={{ fontFamily: FONT, fontSize: 9, color: "var(--textTer)" }}>
            {hint}
          </div>
        </div>
      )}
    </span>
  );
};

export const AttachmentIcons = ({ opts, setOpts, selectCharacter, removeReference,
                                  selectIdentityReference, options }) => {
  const imageByName = useMemo(() =>
    new Map(inputImages(options).map((image) => [image.name, image])), [options]);
  if (!(opts.refs.length > 0 || opts.character)) return null;
  const clearRef = (ref, index) => {
    if (removeReference) removeReference(ref.kind, ref.file);
    else if (ref.kind === "identity") selectIdentityReference("");
    else setOpts({ refs: opts.refs.filter((_, itemIndex) => itemIndex !== index) });
  };
  // Identity rides closest to the sparkle: other kinds first, identity refs
  // after them, the character anchor last. Removal keys on the ORIGINAL index.
  const entries = opts.refs.map((ref, index) => ({ ref, index }));
  const ordered = [...entries.filter((e) => e.ref.kind !== "identity"),
                   ...entries.filter((e) => e.ref.kind === "identity")];
  // ?v= makes the hover preview re-fetch when the reference is re-cropped or
  // replaced; ref_rev is the identity file's mtime riding /api/options,
  // never its name (the server keeps the filename private).
  const anchor = opts.character
    ? ((options && options.characters) || []).find((c) => c.id === opts.character)
    : null;
  return (
    <span role="list" aria-label="Attached references"
          style={{ display: "inline-flex", alignItems: "center" }}>
      {ordered.map(({ ref, index }) => {
        const RefIcon = REF_ICON[ref.kind] || ImageSquare;
        return (
          <AttachmentIcon key={`${ref.kind}:${ref.file}:${index}`} Icon={RefIcon}
            ident={ref.kind === "identity"}
            image={inputImgUrl(imageByName.get(ref.file) || { name: ref.file })}
            label={`${ref.kind} · ${short(ref.file) || ref.file}`}
            onRemove={() => clearRef(ref, index)} />
        );
      })}
      {opts.character && (
        <AttachmentIcon Icon={UserCircleCheck} ident
          label={`identity · ${(anchor && anchor.name) || opts.character}`}
          image={`/api/characters/${encodeURIComponent(opts.character)
            }/ref-thumb?v=${(anchor && anchor.ref_rev) || 0}`}
          onRemove={() => selectCharacter("")} />
      )}
    </span>
  );
};

const ReferenceImageCard = ({ image, kind, attached, disabled, onPick, onRetag }) => {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [hover, setHover] = useState(false);
  const [saving, setSaving] = useState(false);
  const savedKind = REF_KINDS.some((item) => item.key === image.kind) ? image.kind : "";
  const SavedKindIcon = REF_ICON[savedKind] || ImageSquare;
  // "edit photo" is a source pick, not a tag: the server stores only real
  // reference kinds, so offering to save one would fail, and honouring a saved
  // tag here would quietly turn "edit this" into "attach this as identity".
  const editing = kind === "edit";
  const canRetag = !!onRetag && !disabled && !editing && savedKind !== kind;
  // A saved label is the answer to "what is this image", so attaching honours it
  // over whatever the picker happens to be set to - otherwise a face tagged
  // identity silently comes in as a style ref and the identity recipe never runs.
  const attachKind = editing ? "edit" : (savedKind || kind);
  return (
    <div style={{ position: "relative", minWidth: 0 }}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
    <button type="button" disabled={disabled} aria-pressed={attached}
      aria-label={editing ? `Edit ${image.name}`
        : `Use ${image.name} as ${attachKind} reference`}
      title={`${image.name}${savedKind ? ` · saved as ${savedKind}` : ""}`}
      onClick={() => onPick(attachKind)}
      style={{
        width: "100%",
        minWidth: 0, padding: 4, display: "flex", flexDirection: "column", gap: 5,
        border: "1px solid", borderRadius: RADIUS.input, overflow: "hidden",
        borderColor: attached ? "var(--accent)" : "var(--border)",
        background: attached ? "var(--accentMut)" : "var(--bg2)",
        color: attached ? "var(--accent)" : "var(--textSec)",
        cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.58 : 1,
        contentVisibility: "auto", containIntrinsicSize: "96px 114px",
      }}>
      <span style={{
        position: "relative", display: "flex", width: "100%", aspectRatio: "1 / 1",
        alignItems: "center", justifyContent: "center", overflow: "hidden",
        borderRadius: RADIUS.inner, background: "var(--bg3)", color: "var(--textMut)",
      }}>
        {!loaded && !failed && <span className="px-thumbload"
          style={{ position: "absolute", inset: 0 }} />}
        {!failed ? (
          <img src={inputImgUrl(image)} alt="" loading="lazy" decoding="async"
            onLoad={() => setLoaded(true)} onError={() => setFailed(true)}
            style={{ width: "100%", height: "100%", objectFit: "cover",
                     opacity: loaded ? 1 : 0, transition: `opacity ${MOTION.hover}` }} />
        ) : <ImageSquare size={22} weight="duotone" aria-hidden="true" />}
        <span aria-hidden="true" style={{
          position: "absolute", left: 5, bottom: 5, height: 22,
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          gap: savedKind ? 4 : 0, padding: savedKind ? "0 7px" : 0,
          width: savedKind ? "auto" : 22,
          border: "1px solid var(--borderHov)", borderRadius: RADIUS.pill,
          background: "rgba(10,12,13,0.82)", color: "var(--accent)",
        }}>
          <SavedKindIcon size={12} weight="duotone" />
          {savedKind && <span style={{ fontSize: 9, lineHeight: 1 }}>{savedKind}</span>}
        </span>
      </span>
      <span style={{ width: "100%", overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap", fontFamily: "ui-monospace, Consolas, monospace",
                     fontSize: 9, textAlign: "left" }}>
        {short(image.name) || image.name}
      </span>
    </button>
    {canRetag && (hover || saving) && (
      // The saved type is what the badge shows on every future visit; picking a
      // card only attaches it for this turn.
      <button type="button" disabled={saving}
        aria-label={`Save ${image.name} as a ${kind} reference`}
        title={`save as ${kind}`}
        onClick={async () => {
          setSaving(true);
          try { await onRetag(image, kind); } finally { setSaving(false); }
        }}
        style={{
          position: "absolute", top: 8, right: 8, height: 22, width: 22,
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          border: "1px solid var(--borderHov)", borderRadius: RADIUS.pill,
          background: "rgba(10,12,13,0.82)", color: "var(--accent)",
          cursor: saving ? "default" : "pointer", opacity: saving ? 0.5 : 1,
        }}>
        <TagSimple size={12} weight="duotone" aria-hidden="true" />
      </button>
    )}
    </div>
  );
};

// ── the bar ──────────────────────────────────────────────────────────────────
// The server owns recipe stages. The browser submits only the ordered editable
// suffix; core stages stay visible here and are prepended by the compiler.
const orderedRecipeStages = (recipe) => (recipe?.lora_stages || [])
  .map((stage, index) => ({ ...stage, _index: index }))
  .sort((a, b) => (a.order ?? a._index) - (b.order ?? b._index));

const planNumber = (value, fallback = 1) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : Number(fallback ?? 1);
};

const planProfile = (opts, options, recipe) => {
  const selected = (options?.model_meta || {})[opts.model];
  const fallback = (options?.model_meta || {})[recipe?.default_model];
  return {
    family: selected?.family || recipe?.family || fallback?.family || "krea2",
    variant: selected?.variant || fallback?.variant || recipe?.variants?.[0] || "any",
  };
};

const loraMatchesProfile = (lora, profile) => !loraIncompatible(lora, profile);

// The compatibility verdict is the SERVER's: options() ships each LoRA a sparse
// "family:variant" -> reason-code map computed by lora_compatible, the one
// callable lora_stack enforces at build time. This used to be a JS restatement
// of the rule (family match + a hardcoded Z-Image base/turbo gate); the day
// 9.19a made the rule table-driven in families.json, the copy became a lie
// waiting for a new row. An absent key means compatible; the "family:any"
// fallback covers a variant the family does not gate on.
const loraIncompatible = (lora, profile) => {
  const code = (lora.incompatible || {})[`${profile.family}:${profile.variant}`] ??
               (lora.incompatible || {})[`${profile.family}:any`];
  return code === "unknown" ? "not identified yet"
    : code === "variant" ? `made for ${familyName(lora.family)} ${variantName(lora.variant)}`.trim()
    : code === "family" ? `made for ${familyName(lora.family)}`
    : code || "";
};

const recipeStageLabel = (stage, meta) => stage?.title || meta?.title ||
  (stage?.slot ? stage.slot.replaceAll("_", " ") : short(stage?.name));

// The number box for LoRA strengths: type, arrows, spinner, and the gesture
// home a value back on the recipe's own number clears the override (the
// store drops it). Brief 9.14 gave the recipe dials this same box; they moved
// to a snapped MiniSlider on 2026-08-25 (see renderDialRow) because a
// controlled box that refills with the default cannot be cleared - the two
// controls now differ on purpose, by what each number is: a strength you
// type, a dial you drag.
const StrengthInput = ({ value, onChange, label, step = 0.05, disabled = false,
                         min, max }) => (
  <input type="number" step={step} value={value} aria-label={label}
    disabled={disabled}
    {...(min !== undefined ? { min } : {})}
    {...(max !== undefined ? { max } : {})}
    onChange={(event) => onChange(event.target.value)}
    style={{ width: 56, height: 30, background: "var(--bg1)",
             border: "1px solid var(--border)", borderRadius: RADIUS.input,
             padding: "0 5px", fontFamily: "ui-monospace, Consolas, monospace",
             fontSize: 10, color: "var(--text)", textAlign: "center",
             outline: "none" }} />
);

const MiniAction = ({ label, disabled, onClick, children }) => (
  <button type="button" aria-label={label} title={label} disabled={disabled} onClick={onClick}
    style={{ width: 25, height: 25, display: "inline-flex", alignItems: "center",
             justifyContent: "center", flexShrink: 0, padding: 0,
             border: "1px solid var(--border)", borderRadius: RADIUS.control,
             background: "transparent", color: "var(--textTer)",
             cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.3 : 1 }}>
    {children}
  </button>
);

// The LoRA row toggle was this same 30x17 switch hand-rolled a second time;
// since 9.83 the ONE recipe is the shared lib/Switch (MotionDirector's was
// the third copy). `onChange` fires with the next value.

const LORA_RAIL_COLLAPSED_KEY = "pixal.loraRail.collapsed.v1";
// Grid browses by look - the default Jesse chose, and the better glance. List
// scans by name when you already know the one you want, and is the one place a
// full community LoRA name (its distinguishing part rides at the END) fits
// without a clamp. Persisted exactly like the collapsed state: one key, a lazy
// read, an effect write - not a second mechanism.
const LORA_PICKER_VIEW_KEY = "pixal.loraPicker.view.v1";
const LORA_PICKER_VIEWS = ["grid", "list"];
// Per-family collapsed state for the grouped popup (filter off / searching):
// {family: bool}. A family with no entry follows the default - the active
// profile's family open, the rest collapsed.
const LORA_PICKER_GROUPS_KEY = "pixal.loraPicker.groups.v1";


// ── quick tuning ─────────────────────────────────────────────────────────────
// Jesse, 2026-08-26: "under the LoRA explorer - a minimized by default
// Sampler, Scheduler, Steps easy adjustment ... only for advanced users". One
// card under the recipe card, closed to a single line stating the schedule
// the render will run at. Which boxes exist, their options and the model's
// own recommendation all come from /api/styles/sampler for the base+model
// pair - the same answer the style editor gets - so nothing here can offer a
// value the graph would refuse. Sparse overrides, like the dials: a key rides
// only while it deviates from what the recipe (or the selected style) runs at.
const TUNE_STEPS = { min: 1, max: 40, step: 1 };
const TUNE_CFG = { min: 1, max: 10, step: 0.5 };
const TUNE_ETA = { min: 0, max: 1, step: 0.05 };
// ModelSamplingAuraFlow accepts 0-100; nothing useful on Z-Image lives
// above 8, and a slider dead over 92% of its travel is not a control.
const TUNE_SHIFT = { min: 0.5, max: 8, step: 0.25 };
// The Picker's value must always name a row it holds, so a pair that is not on
// the shelf rides in under this id rather than falling back to a placeholder.
const COMBO_OFF_SHELF = "__pixal_off_shelf__";

// ── the combo shelf ──────────────────────────────────────────────────────────
// Jesse, 2026-09-02: "make it easy to save combos of sampler scheduler you like
// right in the panel / sampler card ... I want these loaded up and a little
// arrow left right to select the combo presets."
//
// The bar is NOT a second selection state. It reads the pair that will actually
// render - the same two values the Pickers under it show - and the arrows walk a
// shelf to change it. So a community row, the recipe's own pair and two Pickers
// set by hand all read the same way, there is nothing to keep in sync, and the
// star keeps whichever one you are on. The counter reads "–" when the current
// pair is off the shelf, which is a state, not an error.
//
// MotionDirector's `Stepper` is the nearest shared control and does not fit: it
// walks an integer between a min and a max with dead ends at both, this walks a
// wrapping list of named rows and carries provenance and a keep action. Same
// family though - if a third arrow-stepper turns up, that is the one to lift
// into web/src/lib/ and delete both.
// The control family's VALUE PILL, square: 24px, bg3, pill radius - the same
// body as the Picker between them, so the bar reads as one control and not as
// two ghost buttons flanking a real one.
const COMBO_BTN = {
  width: 24, height: 24, padding: 0, flexShrink: 0,
  display: "inline-flex", alignItems: "center", justifyContent: "center",
  border: "1px solid var(--border)", borderRadius: RADIUS.pill,
  background: "var(--bg3)",
  // Colour only. A hover that resized this would move it out from under the
  // cursor at 239 Hz and oscillate (DESIGN.md).
  transition: `color ${MOTION.hover}, border-color ${MOTION.hover}, background ${MOTION.hover}`,
};
const ComboShelf = ({ options, value, note, error, saved, busy, canStar,
                      onStep, onPick, onStar }) => {
  const steppable = options.length > 1;
  const arrow = (dir, Icon, label) => (
    <button type="button" disabled={!steppable} onClick={() => onStep(dir)}
      aria-label={label}
      title={steppable ? label : "nothing to step through on this recipe yet"}
      style={{ ...COMBO_BTN, cursor: steppable ? "pointer" : "default",
               background: steppable ? "var(--bg3)" : "transparent",
               color: steppable ? "var(--textSec)" : "var(--textMut)" }}>
      <Icon size={11} weight="bold" />
    </button>
  );
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACE[6] }}>
      {/* Arrows adjacent rather than bracketing the value: auditioning is a lot
          of alternating clicks, and one spot to aim at beats two. Both stay the
          same 24px as the Picker beside them so the row has one rhythm. */}
      <div role="group" aria-label="sampler combos"
        onKeyDown={(e) => {
          if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
          e.preventDefault();          // never let the arrows scroll the panel too
          if (steppable) onStep(e.key === "ArrowRight" ? 1 : -1);
        }}
        style={{ display: "flex", alignItems: "center", gap: SPACE[6] }}>
        {arrow(-1, CaretLeft, "previous combo")}
        {arrow(1, CaretRight, "next combo")}
        {/* The list under it is the whole shelf, grouped and searchable, so
            walking twenty rows one arrow at a time is a choice, not the only
            way through. No position counter: the group and the rank in the
            line below already say where this pair sits. */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <Picker label="combo" value={value} options={options} onChange={onPick} />
        </div>
        <button type="button" onClick={onStar} disabled={busy || !canStar}
          aria-pressed={saved}
          aria-label={saved ? "forget this combo" : "keep this combo"}
          title={!canStar ? "pick a sampler and a scheduler first"
                 : saved ? "Forget this combo" : "Keep this combo"}
          style={{ ...COMBO_BTN,
                   cursor: busy || !canStar ? "default" : "pointer",
                   opacity: busy ? 0.5 : 1,
                   borderColor: saved ? "var(--accent)" : "var(--border)",
                   background: saved ? "var(--accentMut)"
                             : canStar ? "var(--bg3)" : "transparent",
                   color: saved ? "var(--accent)"
                        : canStar ? "var(--textTer)" : "var(--textMut)" }}>
          <Star size={12} weight={saved ? "fill" : "regular"} />
        </button>
      </div>
      {/* One line, always present: where this pair came from, or why the last
          click did not take. Starring must not reflow the card. */}
      <span aria-live="polite" title={error || note} style={{
        fontSize: TYPE.micro, lineHeight: 1.4, minHeight: 14, overflow: "hidden",
        textOverflow: "ellipsis", whiteSpace: "nowrap",
        color: error ? "var(--error)" : "var(--textMut)" }}>
        {error || note}
      </span>
    </div>
  );
};
const TuningCard = ({ recipeId, model, styleTuning, overrides, onTuning, rowBase,
                      open, onToggle }) => {
  const [seat, setSeat] = useState(null);
  // Both belong to the combo shelf's star and both must be declared BEFORE the
  // early return below - a hook after a conditional return is a hook that stops
  // being called the moment the seat goes away.
  const [comboBusy, setComboBusy] = useState(false);
  const [comboErr, setComboErr] = useState(null);
  useEffect(() => {
    let live = true;
    if (!recipeId) { setSeat(null); return undefined; }
    styleSampler(recipeId, model || "")
      .then((d) => { if (live) setSeat(d?.ok ? d : null); })
      .catch(() => { if (live) setSeat(null); });
    return () => { live = false; };
  }, [recipeId, model]);
  // A stale "could not save that" must not outlive the recipe it was about.
  useEffect(() => { setComboErr(null); }, [recipeId, model]);
  if (!seat?.tunable) return null;
  const keys = seat.keys || [];
  const has = (k) => keys.includes(k);
  const choices = seat.options || {};
  // Home = what runs untouched: the recipe's authored numbers under the
  // selected style's saved tuning. An override equal to home is no override.
  const home = { ...(seat.defaults || {}), ...(styleTuning || {}) };
  const resolved = { ...home, ...overrides };
  const isSet = (k) => overrides[k] !== undefined;
  const any = keys.some(isSet);
  const change = (k, v) => onTuning(k, v === home[k] ? null : v);
  const reset = () => keys.forEach((k) => { if (isSet(k)) onTuning(k, null); });
  const reco = seat.recommended;
  const applyReco = () => {
    if (!reco) return;
    for (const k of keys)
      if (reco[k] !== undefined && !(k === "cfg" && seat.cfg_locked)) change(k, reco[k]);
  };
  const recoLine = reco ? tuningLine(reco) : "";
  // The curated pairs (2026-08-31). "model" reads the model page's own
  // "Recommended settings" line, which 3 of 51 models here carry and none of
  // them are Krea 2 or MiniMax H3 - so that segment has never been clickable
  // on the two families in daily use, and a hundred and eighty-two RES4LYF
  // sampler names is not a list anyone picks a good one out of. These are.
  const presets = seat.presets || [];
  const presetOn = (p) => Object.entries(p.tuning)
    .every(([k, v]) => resolved[k] === v);
  const applyPreset = (p) => {
    for (const [k, v] of Object.entries(p.tuning))
      if (keys.includes(k)) change(k, v);
  };
  // The shelf (2026-09-02). Its position is DERIVED from the pair that will
  // render, never stored: whatever set sampler_name and scheduler - an arrow, a
  // preset pill, a Picker, the recipe itself - the bar says the same thing.
  const shelf = seat.combos || [];
  const canShelf = has("sampler_name") && has("scheduler");
  const samePair = (t) => !!t && t.sampler_name === resolved.sampler_name
                          && t.scheduler === resolved.scheduler;
  const comboIndex = shelf.findIndex((c) => samePair(c.tuning));
  const onShelf = comboIndex >= 0 ? shelf[comboIndex] : null;
  const comboSaved = onShelf?.source === "saved";
  const canStar = !!(resolved.sampler_name && resolved.scheduler);
  const comboPairKey = `${resolved.sampler_name || ""} ${resolved.scheduler || ""}`;
  const stepCombo = (dir) => {
    if (!shelf.length) return;
    // Off the shelf, forward opens at the top and back opens at the end; on it,
    // both wrap. Yours are first, so one step back from the top is never a dead
    // end and the ones you kept are always two clicks away.
    setComboErr(null);
    applyPreset(shelf[comboIndex < 0 ? (dir > 0 ? 0 : shelf.length - 1)
                                     : (comboIndex + dir + shelf.length) % shelf.length]);
  };
  const toggleCombo = async () => {
    if (!canStar || comboBusy) return;
    setComboBusy(true);
    setComboErr(null);
    try {
      const call = comboSaved ? forgetCombo : starCombo;
      const d = await call(recipeId, model || "", resolved.sampler_name, resolved.scheduler);
      // The server answers with the whole shelf rather than the one row, so the
      // card never has to guess where a new pair landed in the order.
      if (d?.ok) setSeat((s) => (s ? { ...s, combos: d.combos || [] } : s));
      else setComboErr({ pair: comboPairKey, message: d?.error || "That pair could not be saved." });
    } catch {
      setComboErr({ pair: comboPairKey, message: "Pixal did not answer - the pair was not saved." });
    } finally {
      setComboBusy(false);
    }
  };
  // One line under the bar, always present so a star cannot reflow the card.
  const comboNote = onShelf ? onShelf.note
    : !canStar ? "Pick a sampler and a scheduler."
    : !isSet("sampler_name") && !isSet("scheduler") ? "The recipe's own pair."
    : shelf.length ? "Not on the shelf. The star keeps it."
    : "Nothing kept yet. The star keeps this pair.";
  // An error belongs to the pair it was about, so moving off that pair retires
  // it. Cheaper and more honest than a timer, and it cannot outlive its subject.
  const comboError = comboErr?.pair === comboPairKey ? comboErr.message : "";
  // The whole shelf as a list, with the current pair carried in its own group
  // when it is not on the shelf - the Picker's value must always name a row, or
  // the trigger falls back to a placeholder and stops saying what will render.
  const comboOptions = [
    ...(onShelf || !canStar ? [] : [{
      id: COMBO_OFF_SHELF, group: "This render", description: comboNote,
      label: tuningLine({ sampler_name: resolved.sampler_name,
                          scheduler: resolved.scheduler }) }]),
    ...shelf.map((c) => ({
      id: c.id, label: tuningLine(c.tuning), description: c.detail || c.note,
      group: c.source === "saved" ? "Yours" : "Community" })),
  ];
  const pickCombo = (id) => {
    const row = shelf.find((c) => c.id === id);
    if (!row) return;                    // "This render" is where you already are
    setComboErr(null);
    applyPreset(row);
  };
  const recoActive = !!reco && keys.every((k) => reco[k] === undefined || resolved[k] === reco[k]);
  const labelStyle = { fontSize: TYPE.label, fontWeight: W.label, color: "var(--textSec)",
                       display: "flex", alignItems: "center", gap: SPACE[6], minWidth: 0,
                       height: 16, whiteSpace: "nowrap", overflow: "hidden" };
  // One line, always: the way home is right-aligned and clips rather than
  // wrapping under the label (a wrapped mark pushed the control down and
  // broke the row's rhythm - Jesse, 2026-08-26).
  const homeMark = (k) => isSet(k) && (
    <span title={`back to ${home[k]}`} style={{ marginLeft: "auto", minWidth: 0,
      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      fontFamily: "ui-monospace, Consolas, monospace", fontSize: TYPE.micro,
      color: "var(--textMut)" }}>recipe {home[k]}</span>
  );
  const field = (label, k, control, tip) => (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACE[4], minWidth: 0 }}>
      <span style={labelStyle}>{label}{tip}{homeMark(k)}</span>
      {control}
    </div>
  );
  // Grouped when the seat offers two families (RES4LYF's own list, then the
  // stock KSampler's - a pick from the second swaps the node at render time).
  const groupOf = (k) => {
    const map = new Map();
    for (const g of (seat.groups || {})[k] || [])
      for (const id of g.ids || []) map.set(id, g.label);
    return map;
  };
  const select = (k) => (choices[k] || []).length ? (
    <Picker label={k} value={resolved[k]}
      options={(() => { const gm = groupOf(k);
        return choices[k].map((v) => ({ id: v, label: v, group: gm.get(v) })); })()}
      onChange={(v) => change(k, v)} />
  ) : (
    <span style={{ fontSize: TYPE.label, color: "var(--textMut)" }}>{resolved[k]}</span>
  );
  return (
    <div style={{ ...rowBase, display: "flex", flexDirection: "column",
                  alignItems: "stretch", gap: 0, marginBottom: SPACE[8] }}>
      <div style={{ display: "flex", alignItems: "center", gap: SPACE[10], minWidth: 0 }}>
        <SlidersHorizontal size={18} weight="duotone" style={{ color: "var(--accent)", flexShrink: 0 }} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                        fontSize: TYPE.body, fontWeight: W.nav, color: "var(--text)",
                        lineHeight: 1.35 }}>
            Sampler
            <InfoTip size={12} text={"Sampler, scheduler and step overrides for this render, on "
              + "this recipe. “model” applies the settings from the model's own page. Save "
              + "the composer as a style to keep them; another recipe or style starts clean."} />
          </div>
          <div title={tuningLine(resolved)}
               style={{ fontSize: TYPE.label, lineHeight: 1.4, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap",
                        fontFamily: "ui-monospace, Consolas, monospace",
                        color: any ? "var(--accent)" : "var(--textTer)" }}>
            {!any && "follows the recipe · "}{tuningLine(resolved)}
          </div>
        </div>
        <button type="button" onClick={onToggle} aria-expanded={open}
          aria-label="sampler settings" title={open ? "collapse sampler settings" : "expand sampler settings"}
          style={{ height: 24, width: 24, display: "inline-flex", alignItems: "center",
                   justifyContent: "center", flexShrink: 0, padding: 0,
                   border: "1px solid var(--border)", borderRadius: RADIUS.control,
                   cursor: "pointer", background: "var(--bg2)", color: "var(--textTer)" }}>
          <AccordionChevron open={open} />
        </button>
      </div>
      <AccordionPanel open={open}>
        <div style={{ display: "flex", flexDirection: "column", gap: SPACE[12],
                      marginTop: SPACE[12], paddingTop: SPACE[12],
                      borderTop: "1px solid var(--border)" }}>
          <SegmentedControl variant="flex" size="sm" ariaLabel="tuning preset"
            value={!any ? "recipe" : recoActive ? "model" : "custom"}
            onChange={(v) => { if (v === "recipe") reset(); else if (v === "model") applyReco(); }}
            options={[
              { v: "recipe", label: "recipe", title: "the recipe's own schedule" },
              { v: "model", label: "model", disabled: !reco,
                title: reco ? `the model page recommends ${recoLine}`
                            : presets.length
                              ? "this model's page lists no settings - the "
                                + "presets below are measured instead"
                              : "no recommendation on the model page" },
              { v: "custom", label: "custom", disabled: !any || recoActive,
                title: "your own settings" },
            ]} />
          {!!presets.length && (
            <div style={{ display: "flex", flexDirection: "column", gap: SPACE[6] }}>
              <span style={{ fontSize: TYPE.micro, fontWeight: W.heading,
                             color: "var(--textTer)" }}>
                Presets
              </span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: SPACE[4] }}>
                {presets.map((p) => {
                  const on = presetOn(p);
                  return (
                    <button key={p.id} type="button" onClick={() => applyPreset(p)}
                      title={`${tuningLine(p.tuning)}\n\n${p.note}`}
                      style={{
                        height: 22, padding: `0 ${SPACE[10]}px`,
                        borderRadius: RADIUS.pill,
                        border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`,
                        background: on ? "var(--accentMut)" : "transparent",
                        color: on ? "var(--accent)" : "var(--textSec)",
                        fontFamily: FONT, fontSize: TYPE.label,
                        fontWeight: on ? W.nav : W.body,
                        cursor: "pointer", whiteSpace: "nowrap",
                      }}>
                      {p.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {reco && (
            <div title={reco._text}
                 style={{ fontSize: TYPE.micro, color: "var(--textMut)",
                          fontFamily: "ui-monospace, Consolas, monospace",
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              model page · {recoLine}
            </div>
          )}
          {/* Directly above the two Pickers it drives, so pressing an arrow and
              watching both fields change is one glance, not two. */}
          {canShelf && (
            <div style={{ display: "flex", flexDirection: "column", gap: SPACE[6] }}>
              <span style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                             fontSize: TYPE.micro, fontWeight: W.heading,
                             color: "var(--textTer)" }}>
                Combos
                <InfoTip size={11} text={"Sampler and scheduler pairs to try, stepped with the "
                  + "arrows. Yours come first, then the MiniMax H3 community table ranked on "
                  + "graphic quality - two to five votes a row, so read those as leads to "
                  + "render, not as measurements. The star keeps the pair you are on, "
                  + "whatever set it, and keeps it for every recipe on this model family."} />
              </span>
              <ComboShelf options={comboOptions} saved={comboSaved}
                value={onShelf ? onShelf.id : COMBO_OFF_SHELF}
                note={comboNote} error={comboError} busy={comboBusy} canStar={canStar}
                onStep={stepCombo} onPick={pickCombo} onStar={toggleCombo} />
            </div>
          )}
          {/* Full width each: RES4LYF's names ("exponential/res_3s_non-monotonic")
              need the whole rail, and so does the list that opens under them. */}
          <div style={{ display: "grid", gap: SPACE[8], gridTemplateColumns: "1fr" }}>
            {has("sampler_name") && field("Sampler", "sampler_name", select("sampler_name"))}
            {has("scheduler") && field("Scheduler", "scheduler", select("scheduler"))}
          </div>
          {has("steps") && field("Steps", "steps",
            <MiniSlider value={resolved.steps} {...TUNE_STEPS} resetTo={home.steps}
              emphasis={isSet("steps")} ariaLabel="steps"
              format={(v) => String(Math.round(v))}
              onChange={(v) => change("steps", Math.round(v))} />)}
          {has("cfg") && (
            <div style={{ opacity: seat.cfg_locked ? 0.55 : 1 }}>
              {field("CFG", "cfg",
                <MiniSlider value={resolved.cfg} {...TUNE_CFG} resetTo={home.cfg}
                  disabled={!!seat.cfg_locked} emphasis={isSet("cfg")} ariaLabel="cfg"
                  format={(v) => Number(v).toFixed(1)}
                  onChange={(v) => change("cfg", Math.round(v * 2) / 2)} />,
                seat.cfg_locked && (
                  <InfoTip size={11} text={"Distilled build - guidance is baked in at cfg 1. "
                    + "Above 1 doubles the render time and burns the image, so it stays put."} />
                ))}
            </div>
          )}
          {has("shift") && field("Shift", "shift",
            <MiniSlider value={resolved.shift} {...TUNE_SHIFT} resetTo={home.shift}
              emphasis={isSet("shift")} ariaLabel="shift"
              format={(v) => Number(v).toFixed(2)}
              onChange={(v) => change("shift", Math.round(v * 4) / 4)} />,
            <InfoTip size={11} text={"How much of the schedule is spent on "
              + "composition rather than detail. Lower locks the layout early "
              + "and sharpens texture; higher rearranges more and comes out "
              + "softer. Raise it as you raise resolution."} />)}
          {has("eta") && field("Eta", "eta",
            <MiniSlider value={resolved.eta || 0} {...TUNE_ETA} resetTo={home.eta || 0}
              emphasis={isSet("eta")} ariaLabel="eta"
              format={(v) => Number(v).toFixed(2)}
              onChange={(v) => change("eta", Math.round(v * 20) / 20)} />,
            <InfoTip size={11} text={"How much fresh noise an SDE sampler re-injects each step "
              + "(0 = none). Only SDE samplers read it."} />)}
        </div>
      </AccordionPanel>
    </div>
  );
};

export const LoraChain = ({ opts, options, recipeId, plan, setEntries, resetPlan,
                            setCoreEnabled, setCoreStrength, onDial, onTuning,
                            rail = false }) => {
  const [adding, setAdding] = useState(false);
  const [filter, setFilter] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [strength, setStrength] = useState("1.0");
  // Collapsing is NOT a rail concern - it was gated to `rail` until 2026-08-16,
  // which is exactly backwards. The rail is the roomy desktop column; the place
  // the chain actually hurts is the phone, where it renders in-flow above the
  // composer and ate roughly a third of the viewport with no way to shrink it
  // ("hard to use with that Lora manager taking up so much mobile space").
  // Collapsed keeps the stack visible as ordered thumbnails - what is loaded and
  // in what order - just not editable.
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      const saved = window.localStorage.getItem(LORA_RAIL_COLLAPSED_KEY);
      if (saved !== null) return saved === "1";
    } catch { /* private mode / storage disabled */ }
    // No stored preference: start collapsed on a phone, open on a desktop.
    // Same breakpoint Chat.jsx uses to decide rail vs in-flow.
    return typeof window.innerWidth === "number" && window.innerWidth < 960;
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(LORA_RAIL_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch { /* private mode / storage disabled */ }
  }, [collapsed]);
  const [pickerView, setPickerView] = useState(() => {
    if (typeof window === "undefined") return "grid";
    try {
      const saved = window.localStorage.getItem(LORA_PICKER_VIEW_KEY);
      // The settings tab's restore guard: a saved value that names no current
      // view (a retired one) cannot restore, and lands on the default.
      if (saved !== null) return LORA_PICKER_VIEWS.includes(saved) ? saved : "grid";
    } catch { /* private mode / storage disabled */ }
    return "grid";
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(LORA_PICKER_VIEW_KEY, pickerView);
    } catch { /* private mode / storage disabled */ }
  }, [pickerView]);
  // Group collapse persists the same way the view does: one key, a lazy read,
  // an effect write. A corrupt saved value restores to the defaults rather
  // than trapping every group shut (or open) forever.
  const [groupsCollapsed, setGroupsCollapsed] = useState(() => {
    if (typeof window === "undefined") return {};
    try {
      const saved = window.localStorage.getItem(LORA_PICKER_GROUPS_KEY);
      if (saved) return JSON.parse(saved) || {};
    } catch { /* private mode / storage disabled / corrupt value */ }
    return {};
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(LORA_PICKER_GROUPS_KEY, JSON.stringify(groupsCollapsed));
    } catch { /* private mode / storage disabled */ }
  }, [groupsCollapsed]);
  const shrunk = collapsed;
  // Pointer-driven reorder. This was HTML5 drag-and-drop until 2026-08-18,
  // which meant the browser's own ghost image, no indication of where the row
  // would land, and no motion whatsoever - "super janky" was the verdict. The
  // pointer is tracked directly instead: the grabbed row lifts and follows it,
  // the rows it displaces slide out of the way, and an accent pill marks the
  // gap it will drop into.
  const [drag, setDrag] = useState(null);   // {from, to, dy, startY, tops}
  const listRef = useRef(null);
  const sectionRef = useRef(null);
  const addAnchorRef = useRef(null);
  const recipe = (options?.recipes || []).find((item) => item.id === recipeId);
  // Brief 9.23a: every dial lives on the card it acts on. The declaration is
  // still the server's (RECIPE_SPECS[..].dials riding /api/options, brief
  // 9.14): a dial with `choices_from` belongs to the stage card whose slot it
  // names - the bypass variant chooses which LoRA file that stage loads, so
  // it sits on that card; the rest are recipe-level (sampler/encode numbers
  // no single LoRA owns) and sit on the recipe card leading the column.
  // onDial is the wire the standalone fold used; without it (the style
  // dialog's plan editor) no dial renders at all.
  const allDials = typeof onDial === "function" ? (recipe?.dials || []) : [];
  // A dial names the LoRA card it lives on: `stage` for a number dial (the
  // identity patch's Likeness and Grounding), `choices_from` for a choice
  // dial whose options come from that slot's scan (the bypass variant). Only
  // a dial naming neither falls back to the recipe card - Jesse, 2026-08-25:
  // "advanced settings should go under the LoRA it is editing, not its own
  // card at the top of the lora explorer".
  const dialHome = (dial) => dial.stage || dial.choices_from || "";
  const recipeCardDials = allDials.filter((dial) => !dialHome(dial));
  const dialsBySlot = new Map();
  for (const dial of allDials) {
    const home = dialHome(dial);
    if (!home) continue;
    dialsBySlot.set(home, [...(dialsBySlot.get(home) || []), dial]);
  }
  // The frozen wire: overrides read from opts.dials[recipeId], written
  // through onDial -> store.setRecipeDial. A dial back on the recipe's own
  // number clears the override there - always a way home.
  const dialOverridesMap = ((opts?.dials || {}))[recipeId] || {};
  // Quick tuning rides beside the dials: same sparse map, keyed by recipe.
  const tuneOverrides = ((opts?.tuning || {}))[recipeId] || {};
  const tuneAny = Object.keys(tuneOverrides).length > 0;
  const savedStyle = opts?.saved_style
    ? (options?.saved_styles || []).find((s) => s.id === opts.saved_style) : null;
  const styleTuning = savedStyle && savedStyle.base === recipeId ? (savedStyle.tuning || {}) : {};
  const tuneModel = opts?.model || recipe?.default_model || "";
  // Open while overridden, like the dial cards: an override never hides.
  const [tuneOpen, setTuneOpen] = useState(tuneAny);
  useEffect(() => { if (tuneAny) setTuneOpen(true); }, [tuneAny]);
  const isSet = (key) => dialOverridesMap[key] !== undefined;
  const resolvedDial = (dial) => dialOverridesMap[dial.key] ?? dial.default;
  // A choice dial's display label is the option's own ("2-vector"), not the
  // bare value - in the collapsed summary and the "recipe" home marker alike.
  const dialValueLabel = (dial, v) => dial.kind === "choice"
    ? (((dial.choices || []).find((c) => c.value === v) || {}).label ?? String(v))
    : v;
  // A choice the machine cannot run is never offered: the server sends only
  // installed variants, and a one-option switch is no choice at all (9.15).
  // Its row stays as a dimmed note instead of vanishing, so a set override
  // can never hide inside its card.
  const dialRunnable = (dial) => dial.kind !== "choice" || (dial.choices || []).length >= 2;
  // Open while overridden: an override must never hide inside a collapsed
  // card, so a card carrying a set dial opens itself (and keeps the resolved
  // values stated on its collapsed line).
  const [openCards, setOpenCards] = useState(() => {
    const open = {};
    for (const dial of allDials)
      if (dialOverridesMap[dial.key] !== undefined)
        open[dialHome(dial) || "recipe"] = true;
    return open;
  });
  const toggleCard = (id) => setOpenCards((open) => ({ ...open, [id]: !open[id] }));
  // Overrides can also arrive while mounted (the chat brain's tool schema
  // writes the same map): open the card that carries the dial, never steal
  // a closed state the user chose for cards it does not touch.
  useEffect(() => {
    setOpenCards((open) => {
      let changed = false;
      const next = { ...open };
      for (const dial of allDials) {
        if (dialOverridesMap[dial.key] === undefined) continue;
        const id = dialHome(dial) || "recipe";
        if (!next[id]) { next[id] = true; changed = true; }
      }
      return changed ? next : open;
    });
  }, [opts?.dials, recipeId, options]);
  const stages = orderedRecipeStages(recipe);
  const core = stages.filter((stage) => stage.zone === "core");
  const editableStages = stages.filter((stage) => stage.zone === "editable");
  const stageBySlot = new Map(stages.map((stage) => [stage.slot, stage]));
  const metaByName = new Map((options?.loras || []).map((lora) => [lora.name, lora]));
  const entries = Array.isArray(plan?.entries) ? plan.entries : [];
  const profile = planProfile(opts, options, recipe);
  const profileLabel = profile.family === "zimage"
    ? `Z-Image${["base", "turbo"].includes(profile.variant)
      ? ` ${profile.variant[0].toUpperCase()}${profile.variant.slice(1)}` : ""}`
    : profile.family === "krea2" ? "Krea 2" : profile.family;

  if (!recipe || !Array.isArray(recipe.lora_stages) || !plan) return null;

  const detailFor = (entry) => {
    const stage = entry.slot ? stageBySlot.get(entry.slot) : null;
    const name = stage?.name || entry.name || "";
    return { stage, name, meta: metaByName.get(name) };
  };
  const activeNames = new Set(entries.map((entry) => detailFor(entry).name));
  const recipeNames = new Set(stages.map((stage) => stage.name));
  // A recipe row that names a file the machine does not have is never
  // offered: the server annotates every stage with `installed` (the same
  // _catalog_has the readiness list reads), and a click that can only fail
  // at build time is worse than no row - "if they have that lora" (9.86).
  const inactiveStages = editableStages.filter((stage) =>
    !activeNames.has(stage.name) && stage.installed !== false);
  // The whole chain in render order, reduced to what a thumbnail can carry:
  // which LoRA, where in the stack, and whether it is on.
  const chainGlyphs = [
    ...core.map((stage) => ({
      name: stage.name,
      enabled: (plan?.core || {})[stage.slot]?.enabled !== false,
      label: recipeStageLabel(stage, metaByName.get(stage.name)),
      thumb: metaByName.get(stage.name)?.thumb,
    })),
    ...entries.map((entry) => {
      const { stage, name, meta } = detailFor(entry);
      return {
        name, enabled: entry.enabled !== false,
        thumb: meta?.thumb,
        label: stage ? recipeStageLabel(stage, meta)
                     : (entry.title || meta?.title || short(name)),
      };
    }),
  ];
  // Everything pickable: the catalog minus what already rides the chain.
  const available = (options?.loras || []).filter((lora) =>
    !activeNames.has(lora.name) && !recipeNames.has(lora.name));
  // The flat list (filter on, not searching) is the compatible set.
  const installedAll = available.filter((lora) => loraMatchesProfile(lora, profile));
  // Cap what is rendered, but say so - a silent truncation reads as "that is
  // everything you have installed", which it is not.
  const installedTotal = installedAll.length;
  const installed = installedAll.slice(0, 120);
  // Searching hunts the WHOLE catalog - name, filename and declared base -
  // regardless of the compatibility filter: finding a file you own is not the
  // filter's decision to make. The verdict still shows, as the dimmed reason.
  const searching = !!filter.trim();
  const textMatch = (lora) =>
    (!filter || `${lora.title || ""} ${lora.short || ""} ${lora.name}`
      .toLowerCase().includes(filter.toLowerCase())) ||
    (lora.base_model || "").toLowerCase().includes(filter.toLowerCase());
  const pool = searching ? available.filter(textMatch) : available;
  // Filter off (or any search): everything, grouped by family. The active
  // profile's family leads and starts open; the rest follow by size, collapsed.
  const familyGroups = (() => {
    if (!searching && !showAll) return [];
    const by = new Map();
    for (const lora of pool) {
      const fam = lora.family || "unknown";
      if (!by.has(fam)) by.set(fam, []);
      by.get(fam).push(lora);
    }
    return [...by.entries()].map(([fam, items]) => ({ fam, items }))
      .sort((a, b) => a.fam === profile.family ? -1
        : b.fam === profile.family ? 1 : b.items.length - a.items.length);
  })();
  const groupLabel = (fam) => fam === "unknown" ? "not identified yet" : familyName(fam);
  const searchSummary = searching
    ? familyGroups.map((g) => g.fam === "unknown"
        ? `${g.items.length} not identified yet`
        : `${g.items.length} in ${groupLabel(g.fam)}`).join(" · ")
    : "";
  // Collapsed is a preference, never a hiding place: a search ignores it,
  // because a search result behind a fold is the junk-drawer bug again.
  const groupCollapsed = (group) =>
    groupsCollapsed[group.fam] ?? (group.fam !== profile.family);
  const toggleGroup = (group) =>
    setGroupsCollapsed((current) => ({ ...current, [group.fam]: !groupCollapsed(group) }));

  const entryLocked = (entry) => !!detailFor(entry).stage?.order_locked;
  const moveEntry = (from, to) => {
    if (from === to || from < 0 || to < 0 || from >= entries.length || to >= entries.length ||
        entryLocked(entries[from]) || entryLocked(entries[to])) return;
    const next = [...entries];
    const [moving] = next.splice(from, 1);
    next.splice(to, 0, moving);
    setEntries(next);
  };
  const adjacentFlexible = (index, direction) => {
    for (let i = index + direction; i >= 0 && i < entries.length; i += direction)
      if (!entryLocked(entries[i])) return i;
    return -1;
  };
  // Row geometry in the scroll container's OWN coordinates: offsetTop, not
  // getBoundingClientRect, so the numbers survive the list scrolling and can be
  // handed straight to the absolutely-positioned drop pill.
  const ROW_GAP = SPACE[8];
  const PILL_H = 3;
  const measureRows = () => {
    const box = listRef.current;
    if (!box) return null;
    return [...box.querySelectorAll("[data-lora-row]")]
      .sort((a, b) => Number(a.dataset.loraRow) - Number(b.dataset.loraRow))
      .map((el) => ({ top: el.offsetTop, height: el.offsetHeight }));
  };
  // Walk out from the grabbed row for as long as its centre has cleared a
  // neighbour's centre. Comparing midpoints rather than edges is what stops the
  // target flickering between two rows while the pointer sits on a boundary.
  const dropTarget = (state, dy) => {
    const centre = state.tops[state.from].top + state.tops[state.from].height / 2 + dy;
    let to = state.from;
    for (let i = state.from - 1; i >= 0; i--) {
      if (centre >= state.tops[i].top + state.tops[i].height / 2) break;
      to = i;
    }
    for (let i = state.from + 1; i < state.tops.length; i++) {
      if (centre <= state.tops[i].top + state.tops[i].height / 2) break;
      to = i;
    }
    // A locked stage cannot be displaced, so never let the pill promise a gap
    // that moveEntry would then refuse.
    while (to !== state.from && entryLocked(entries[to])) to += to > state.from ? -1 : 1;
    return to;
  };
  // The grabbed row follows the pointer; every row between its old home and its
  // new one slides a row-height the other way - the SAME distance for each of
  // them, because what is leaving or arriving is the grabbed row.
  const rowMotion = (index) => {
    if (!drag) return null;
    if (index === drag.from) {
      return { transform: `translateY(${drag.dy}px) scale(1.015)`, zIndex: 3,
               position: "relative", boxShadow: SHADOW.lg, transition: "none",
               cursor: "grabbing" };
    }
    const step = drag.tops[drag.from].height + ROW_GAP;
    const shift = (drag.from < drag.to && index > drag.from && index <= drag.to) ? -step
      : (drag.from > drag.to && index >= drag.to && index < drag.from) ? step : 0;
    return { transform: `translateY(${shift}px)`, transition: `transform ${MOTION.layout}` };
  };
  // Where it will land, drawn as a line IN the gap rather than a highlight on a
  // neighbouring row - a highlight cannot say whether it means above or below.
  const dropPillTop = () => {
    if (!drag) return null;
    const row = drag.tops[drag.to];
    if (!row) return null;
    const raw = (drag.to <= drag.from ? row.top : row.top + row.height) - ROW_GAP / 2;
    // Clamp inside the list. Scrolling is frozen mid-drag, so a pill half a gap
    // above the first row (there is no gap up there when the chain has no core
    // stages) or below the last one lands outside the box and is simply not
    // drawn - the one moment the user most needs to see it.
    const last = drag.tops[drag.tops.length - 1];
    return Math.max(0, Math.min(last.top + last.height - PILL_H, raw));
  };
  const changeStrength = (index, value) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return;
    setEntries(entries.map((entry, i) => i === index ? { ...entry, strength: n } : entry));
  };
  const toggleEntry = (index) => {
    setEntries(entries.map((entry, i) => i === index
      ? { ...entry, enabled: entry.enabled === false }
      : entry));
  };
  const addStage = (stage) => {
    setEntries([...entries, {
      slot: stage.slot,
      strength: planNumber(stage.strength),
      enabled: true,
    }]);
    setAdding(false); setFilter("");
  };
  const addInstalled = (lora) => {
    setEntries([...entries, {
      name: lora.name,
      ...(lora.title ? { title: lora.title } : {}),
      strength: planNumber(strength),
      enabled: true,
    }]);
    setAdding(false); setFilter("");
  };

  // One dial row, on whichever card owns the dial: label + InfoTip + the
  // recipe's own number (only while overridden - an untouched dial already
  // IS the recipe's number, printing it beside itself is noise) on the left,
  // the control on the right. A choice dial's track needs the full width, so
  // it drops to its own row under the label. Numbers use the LoRA strength
  // box unchanged; the choice uses the shared segmented control's grid
  // variant (its labels must never clip).
  // A number dial is a snapped slider on its own line under the label (Lumen's
  // MiniSlider on Pixal's tokens): it only lands on the dial's steps, the
  // readout sits at the right, and a double-click returns to the recipe's own
  // number. The number box it replaced refilled with that default the moment
  // it was emptied, so the value could not be typed over without selecting
  // it first (Jesse, 2026-08-25: "I cannot erase the damn 4"). Choice dials
  // keep the segmented control.
  const dialFormat = (dial) => (v) => {
    const decimals = Math.max(0, Math.ceil(-Math.log10(dial.step || 1)));
    return Number(v).toFixed(decimals);
  };
  // Label line: sentence case at label size (Jesse, 2026-08-25: "not so
  // CAPS"), the tip beside it, and when the dial is off the recipe's number
  // the way home stated quietly at the right - the accent goes on the
  // readout itself, which is the thing that changed.
  const renderDialRow = (dial) => (
    <div key={dial.key} style={{
      display: "grid", gridTemplateColumns: "minmax(0,1fr)",
      gap: SPACE[8], alignItems: "center" }}>
      <span style={{ minWidth: 0, display: "flex", alignItems: "center",
                     gap: SPACE[6], fontSize: TYPE.label, fontWeight: W.label,
                     color: "var(--textSec)" }}>
        {dial.label}
        <InfoTip size={12} text={dial.help} />
        {isSet(dial.key) && (
          <span title={`double-click the slider to return to ${dialValueLabel(dial, dial.default)}`}
                style={{ marginLeft: "auto",
                         fontFamily: "ui-monospace, Consolas, monospace",
                         fontSize: TYPE.micro, color: "var(--textMut)" }}>
            recipe {dialValueLabel(dial, dial.default)}
          </span>
        )}
      </span>
      {dial.kind === "choice" ? (
        dialRunnable(dial) ? (
          <SegmentedControl variant="grid" size="sm" ariaLabel={`${dial.label} variant`}
            options={(dial.choices || []).map((c) =>
              // An option may carry its own title: the Build dial's labels
              // stay short (Full / r128 / r64 - sized labels overflow the
              // drawer's unshrinkable grid) and the size rides the tooltip
              // (9.56). The bypass dial has no title and shows its rel.
              ({ v: c.value, label: c.label, title: c.title || c.name }))}
            value={resolvedDial(dial)}
            onChange={(v) => onDial(dial.key, v)} />
        ) : (
          <span style={{ fontFamily: "ui-monospace, Consolas, monospace",
                         fontSize: 9, color: "var(--textMut)" }}>
            only {(dial.choices || [])[0]?.label || "one variant"} installed
          </span>
        )
      ) : (
        <MiniSlider value={resolvedDial(dial)} step={dial.step}
          min={dial.min} max={dial.max} resetTo={dial.default}
          emphasis={isSet(dial.key)}
          format={dialFormat(dial)} ariaLabel={`${dial.label} dial`}
          onChange={(value) => onDial(dial.key, value)} />
      )}
    </div>
  );

  const rowBase = {
    display: "grid", gridTemplateColumns: "24px minmax(0,1fr) 56px auto",
    alignItems: "center", gap: SPACE[10], minHeight: 52,
    // Never a flex item that shrinks: the list is a scrolling flex column,
    // and an explicit minHeight lets flexbox squeeze a row to 52px when the
    // rail overflows - an open dial drawer then spilled over the rows below
    // instead of pushing them (Jesse, 2026-08-26). The list scrolls; rows do
    // not give.
    flexShrink: 0,
    padding: `${SPACE[8]}px ${SPACE[10]}px`, borderRadius: RADIUS.inner,
    background: "var(--bg2)", border: "1px solid var(--border)",
  };
  let sequence = 0;
  const addSearch = (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACE[10],
                  marginBottom: SPACE[10] }}>
      <FilterInput value={filter} onChange={setFilter} autoFocus
                   icon={<MagnifyingGlass size={13} weight="duotone" />}
                   placeholder="Search" />
      {searching && (
        <div style={{ padding: `0 ${SPACE[4]}px`, color: "var(--textTer)",
                      fontSize: TYPE.label }}>
          {searchSummary || "no matches"}
        </div>
      )}
      {/* Density, not a different screen: the same filtered set feeds both
          views, and the choice persists (LORA_PICKER_VIEW_KEY). */}
      <SegmentedControl variant="flex" size="md" ariaLabel="LoRA picker view"
        options={[{ v: "grid", label: "grid", title: "Browse by cover" },
                  { v: "list", label: "list", title: "Scan by full name" }]}
        value={pickerView} onChange={setPickerView} />
    </div>
  );

  // The filter and what it currently offers are ONE chip on the popover's
  // title row: "Krea 2 · 110" flips to "all · 416". The strength box went -
  // a LoRA enters at 1.0 and its row is where the number lives (Jesse,
  // 2026-08-25). What remains stacks on a 10px rhythm: search, then the
  // view capsule, then the list.
  const pickerTitle = (
    <>
      <span>Add a LoRA</span>
      <button type="button" onClick={() => setShowAll(!showAll)}
        title={showAll ? "back to the LoRAs this profile can run"
                       : "every installed LoRA, grouped by family"}
        style={{ height: 22, padding: `0 ${SPACE[8]}px`, flexShrink: 0,
                 border: `1px solid ${showAll ? "var(--accent)" : "var(--border)"}`,
                 borderRadius: RADIUS.pill,
                 background: showAll ? "var(--accentMut)" : "transparent",
                 color: showAll ? "var(--accent)" : "var(--textTer)",
                 fontFamily: FONT, fontSize: TYPE.label, fontWeight: W.label,
                 cursor: "pointer", whiteSpace: "nowrap",
                 transition: `all ${MOTION.state}` }}>
        {showAll ? `all · ${available.length}`
         : `${profileLabel} · ${installed.length < installedTotal
              ? `${installed.length} of ${installedTotal}` : installedTotal}`}
      </button>
    </>
  );
  // Lifted out of the header so it can sit BELOW the rows: adding is the last
  // thing you do to a chain, and stacking it beside reset made the header wrap
  // onto a second line in the rail.
  const addControl = (
    <div ref={addAnchorRef} style={{ position: "relative", marginTop: SPACE[8] }}>
      <button type="button" onClick={() => { setAdding(!adding); setFilter(""); }}
        style={{ height: 30, width: "100%", display: "inline-flex", alignItems: "center",
                 justifyContent: "center", gap: SPACE[4], padding: `0 ${SPACE[10]}px`,
                 border: "1px dashed var(--border)", borderRadius: RADIUS.control,
                 background: "transparent", color: "var(--textSec)", fontFamily: FONT,
                 fontSize: TYPE.label, cursor: "pointer" }}>
        <Plus size={11} weight="bold" /> add
      </button>
      {adding && (
        <Pop title={pickerTitle} onClose={() => setAdding(false)} xl
             down={rail} alignRight={rail} rail={rail}
             anchorRef={addAnchorRef} boundsRef={sectionRef}>
          {rail && addSearch}
          {inactiveStages.map((stage) => (
            <Row key={stage.slot} onClick={() => addStage(stage)}>
              <LockSimple size={12} weight={stage.order_locked ? "fill" : "duotone"} />
              <span style={{ minWidth: 0 }}>
                <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis",
                               whiteSpace: "nowrap" }}>
                  {recipeStageLabel(stage, metaByName.get(stage.name))}
                </span>
                {stage.role && (
                  <span style={{ display: "block", fontFamily: "ui-monospace, Consolas, monospace",
                                 fontSize: 9, color: "var(--textMut)" }}>{stage.role}</span>
                )}
              </span>
              <Tag>recipe · {planNumber(stage.strength)}</Tag>
            </Row>
          ))}
          {inactiveStages.length > 0 && (
            <div style={{ borderTop: "1px solid var(--border)", margin: `${SPACE[10]}px 0` }} />
          )}
          {!rail && addSearch}
          {(searching || showAll) ? (
            familyGroups.length ? familyGroups.map((group) => {
              const collapsed = !searching && groupCollapsed(group);
              return (
                <div key={group.fam}>
                  <button type="button" onClick={() => toggleGroup(group)}
                    aria-expanded={!collapsed}
                    style={{ display: "flex", alignItems: "center", gap: SPACE[4],
                             width: "100%", padding: `${SPACE[6]}px ${SPACE[4]}px`,
                             background: "none", border: "none", cursor: "pointer",
                             color: "var(--textTer)", fontFamily: FONT,
                             fontSize: TYPE.label, textAlign: "left" }}>
                    <CaretRight size={10} weight="bold"
                      style={{ flexShrink: 0, transform: collapsed ? "none" : "rotate(90deg)",
                               transition: `transform ${MOTION.hover}` }} />
                    {groupLabel(group.fam)} · {group.items.length}
                  </button>
                  {group.fam === "unknown" && !collapsed && (
                    <div style={{ padding: `0 ${SPACE[4]}px ${SPACE[6]}px 22px`,
                                  color: "var(--textMut)", fontSize: TYPE.micro,
                                  lineHeight: 1.5 }}>
                      These will not render - the stack drops every LoRA whose family
                      it cannot identify before the sampler. Run a rescan (settings →
                      rescan folders) to identify one by hash, or drop a .metadata.json
                      sidecar beside the file.
                    </div>
                  )}
                  {!collapsed && (pickerView === "list" ? (
                    <div style={{ display: "flex", flexDirection: "column" }}>
                      {group.items.map((lora) => (
                        <LoraRow key={lora.name} lora={lora}
                                 reason={loraIncompatible(lora, profile)}
                                 onClick={() => addInstalled(lora)} />
                      ))}
                    </div>
                  ) : (
                    <div style={{ display: "grid", gap: SPACE[8],
                                  gridTemplateColumns: "repeat(auto-fill, minmax(78px, 1fr))" }}>
                      {group.items.map((lora) => (
                        <LoraTile key={lora.name} lora={lora}
                                  reason={loraIncompatible(lora, profile)}
                                  onClick={() => addInstalled(lora)} />
                      ))}
                    </div>
                  ))}
                </div>
              );
            }) : (
              <Row disabled>{searching
                ? `no installed LoRA matches “${filter.trim()}”`
                : "every installed LoRA already rides the chain"}</Row>
            )
          ) : (
            <>
          {/* Both densities map the same filtered, capped set - the search and
              the profile filter live upstream in installedAll, so they hold
              here without either view re-implementing them. */}
          {pickerView === "list" ? (
            <div style={{ display: "flex", flexDirection: "column" }}>
              {installed.map((lora) => (
                <LoraRow key={lora.name} lora={lora}
                         onClick={() => addInstalled(lora)} />
              ))}
            </div>
          ) : (
            <div style={{ display: "grid", gap: SPACE[8],
                          gridTemplateColumns: "repeat(auto-fill, minmax(78px, 1fr))" }}>
              {installed.map((lora) => (
                <LoraTile key={lora.name} lora={lora}
                          onClick={() => addInstalled(lora)} />
              ))}
            </div>
          )}
          {!inactiveStages.length && !installed.length && (
            <Row disabled>no installed {profileLabel} LoRAs match this profile</Row>
          )}
            </>
          )}
        </Pop>
      )}
    </div>
  );

  return (
    <section ref={sectionRef} aria-label={`${recipe.label || recipe.id} LoRA chain`} style={{
      marginBottom: rail ? 0 : SPACE[8], minHeight: 0,
      // Rail: a flex child of the aside, not a 100%-height box - flex:1 fills
      // the aside exactly like height:100% did, and the chain's list inside
      // takes the leftover height and scrolls.
      display: "flex", flexDirection: "column",
      flex: rail ? "1 1 auto" : undefined,
      maxHeight: rail ? "100%" : undefined,
      // In the rail the <aside> IS the surface - it already owns the width, the
      // padding and the dividing border. Painting a second tinted, bordered box
      // inside it just draws a frame around a frame, and costs SPACE[10] of
      // width on the narrowest column in the app. In-flow (narrow layouts) the
      // chain sits among other content and still has to read as its own card.
      padding: rail ? 0 : SPACE[10],
      background: rail ? "transparent" : "rgba(255,255,255,0.025)",
      border: rail ? "none" : "1px solid var(--border)",
      borderRadius: rail ? 0 : RADIUS.card,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                    marginBottom: SPACE[8], flexWrap: "wrap" }}>
        <Stack size={14} weight="duotone" style={{ color: "var(--accent)" }} />
        <span style={{ fontSize: TYPE.ui, fontWeight: W.heading, color: "var(--text)" }}>
          LoRA chain
        </span>
        <span style={{ fontSize: TYPE.label, color: "var(--textTer)" }}>
          {recipe.label || recipe.id}
        </span>
        <span style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
                       color: "var(--textMut)" }}>
          {recipe.lora_stack_revision}
        </span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: SPACE[4] }}>
          <button type="button" onClick={resetPlan} title="Restore recipe defaults"
            aria-label="Restore recipe defaults"
            style={{ height: 24, display: "inline-flex", alignItems: "center", gap: SPACE[4],
                     padding: `0 ${shrunk ? SPACE[4] : SPACE[6]}px`, border: "none",
                     background: "transparent", color: "var(--textTer)", fontFamily: FONT,
                     fontSize: TYPE.label, cursor: "pointer" }}>
            <ArrowCounterClockwise size={12} weight="duotone" />{shrunk ? "" : "reset"}
          </button>
          {(
            <button type="button" onClick={() => setCollapsed((v) => !v)}
              title={collapsed ? "expand the chain" : "collapse the chain"}
              aria-expanded={!collapsed}
              style={{ height: 24, width: 24, display: "inline-flex", alignItems: "center",
                       justifyContent: "center", padding: 0, cursor: "pointer",
                       border: "1px solid var(--border)", borderRadius: RADIUS.control,
                       background: "var(--bg2)", color: "var(--textTer)" }}>
              {collapsed ? <CaretDown size={11} weight="bold" />
                         : <CaretUp size={11} weight="bold" />}
            </button>
          )}
        </div>
      </div>

      {shrunk ? (
        // Collapsed: the stack stays legible as ordered thumbnails - what is
        // loaded and in what order - without the rows that eat the height.
        <>
        <button type="button" onClick={() => setCollapsed(false)}
          title="expand the LoRA chain"
          style={{ display: "grid", gap: SPACE[4], width: "100%", padding: 0,
                   gridTemplateColumns: "repeat(auto-fill, minmax(34px, 1fr))",
                   border: "none", background: "transparent", cursor: "pointer" }}>
          {chainGlyphs.map((item, i) => (
            <span key={`${item.name}-${i}`} title={`${i + 1}. ${item.label}`}
              style={{ position: "relative", display: "block",
                       opacity: item.enabled ? 1 : 0.35 }}>
              <LoraThumb src={item.thumb} fill />
              <span aria-hidden="true" style={{
                position: "absolute", left: 2, bottom: 1,
                fontFamily: "ui-monospace, Consolas, monospace", fontSize: 8,
                lineHeight: 1.4, padding: "0 3px", borderRadius: RADIUS.pill,
                background: "rgba(0,0,0,0.66)",
                color: item.enabled ? "var(--accent)" : "var(--textMut)",
              }}>{i + 1}</span>
            </span>
          ))}
          {chainGlyphs.length === 0 && (
            <span style={{ gridColumn: "1 / -1", fontFamily: FONT, fontSize: TYPE.label,
                           color: "var(--textMut)", textAlign: "left" }}>
              no LoRAs in the chain
            </span>
          )}
        </button>
        {/* The dial cards collapse with the chain, but an override never
            hides: while the chain is a glyph strip, a set dial still states
            itself here in accent. */}
        {allDials.some((dial) => isSet(dial.key)) && (
          <div title="expand the chain to change these"
               style={{ marginTop: SPACE[6],
                        fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
                        lineHeight: 1.5, color: "var(--accent)" }}>
            {allDials.filter((dial) => isSet(dial.key))
              .map((dial) => `${dial.label.toLowerCase()} ${dialValueLabel(dial, resolvedDial(dial))}`)
              .join(" · ")}
          </div>
        )}
        {tuneAny && (
          <div title="expand the chain to change these"
               style={{ marginTop: SPACE[6],
                        fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
                        lineHeight: 1.5, color: "var(--accent)" }}>
            sampler · {tuningLine(tuneOverrides)}
          </div>
        )}
        </>
      ) : (
        <>

      {/* 9.23a: the recipe is the first card in the column - same card
          shape as the chain's, same expand affordance - and the recipe-level
          dials live in it. A card with no controls shows no chevron; the
          collapsed card states its overrides; the drawer opens below the
          header, so what is under the cursor never moves mid-click. Pinned
          above the scroll list so the dials stay reachable at any scroll. */}
      {/* The recipe card heads the chain (Jesse, 2026-08-25: "neat idea") and
          carries the chain rule as its subline; the tip only appears when it
          has dials of its own to explain. */}
      {allDials.length > 0 && (
        <div style={{ ...rowBase, display: "flex", flexDirection: "column",
                      alignItems: "stretch", gap: 0, marginBottom: SPACE[8] }}>
          <div style={{ display: "flex", alignItems: "center", gap: SPACE[10] }}>
            {/* Identity Edit is about a face (Jesse, 2026-08-26: UserFocus);
                the other recipes keep the sliders glyph. */}
            {recipe.id === "identity_edit"
              ? <UserFocus size={18} weight="duotone" style={{ color: "var(--accent)", flexShrink: 0 }} />
              : <Palette size={18} weight="duotone" style={{ color: "var(--accent)", flexShrink: 0 }} />}
            <div style={{ minWidth: 0 }}>
              {/* What you have selected: the graph by name, in the text
                  colour and body size a selection deserves, with what it
                  does beneath it - the recipe's own tag, then the chain
                  rule. The "recipe" word went; the card IS the recipe. */}
              <div style={{ fontSize: TYPE.body, fontWeight: W.nav, color: "var(--text)",
                            overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap", lineHeight: 1.35 }}>
                {recipe.label || recipe.id}
              </div>
              <div title="model enters at 1 · top applies first"
                   style={{ fontSize: TYPE.label, color: "var(--textTer)", overflow: "hidden",
                            textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.4 }}>
                {recipe.tag || "recipe"}
              </div>
            </div>
            {/* The way home travels with the dials. The 78 words of prose
                these dials used to carry stay in the InfoTips; what stays
                visible is the label, the override state, and the recipe's
                own number to come back to. */}
            {recipeCardDials.length > 0 && (
              <InfoTip size={12} text={"These override the recipe for this render only. Put a "
                + "dial back on the recipe's own number, or double-click a slider, and "
                + "the override goes away."} />
            )}
            {!openCards.recipe && recipeCardDials.length > 0 && (
              <span style={{ marginLeft: "auto", minWidth: 0, textAlign: "right",
                             // Wraps rather than truncates: at rail width the
                             // resolved numbers take a second line, and a
                             // hidden value is the one thing this line exists
                             // to prevent.
                             whiteSpace: "normal", lineHeight: 1.5,
                             fontFamily: "ui-monospace, Consolas, monospace",
                             fontSize: TYPE.micro, color: "var(--textTer)" }}>
                {!recipeCardDials.some((dial) => isSet(dial.key)) && "follows the recipe · "}
                {recipeCardDials.map((dial, i) => (
                  <span key={dial.key}>
                    {i > 0 && " · "}
                    <span style={isSet(dial.key) ? { color: "var(--accent)" } : undefined}>
                      {dial.label.toLowerCase()} {dialValueLabel(dial, resolvedDial(dial))}
                    </span>
                  </span>
                ))}
              </span>
            )}
            {recipeCardDials.length > 0 && (
              <button type="button" onClick={() => toggleCard("recipe")}
                aria-expanded={!!openCards.recipe}
                aria-label={`${recipe.label || recipe.id} recipe dials`}
                title={openCards.recipe ? "collapse the recipe dials"
                                        : "expand the recipe dials"}
                style={{ height: 24, width: 24, display: "inline-flex",
                         alignItems: "center", justifyContent: "center",
                         flexShrink: 0, marginLeft: "auto", padding: 0,
                         border: "1px solid var(--border)",
                         borderRadius: RADIUS.control, cursor: "pointer",
                         background: "var(--bg2)", color: "var(--textTer)" }}>
                <AccordionChevron open={!!openCards.recipe} />
              </button>
            )}
          </div>
          {recipeCardDials.length > 0 && (
            <AccordionPanel open={!!openCards.recipe}>
              <div style={{ display: "flex", flexDirection: "column", gap: SPACE[16],
                            marginTop: SPACE[12], paddingTop: SPACE[12],
                            borderTop: "1px solid var(--border)" }}>
                {recipeCardDials.map(renderDialRow)}
              </div>
            </AccordionPanel>
          )}
        </div>
      )}
      {typeof onTuning === "function" && (
        <TuningCard recipeId={recipeId} model={tuneModel} styleTuning={styleTuning}
          overrides={tuneOverrides} onTuning={onTuning} rowBase={rowBase}
          open={tuneOpen} onToggle={() => setTuneOpen((v) => !v)} />
      )}
      {rail && allDials.length === 0 && (
        <div style={{ padding: `0 ${SPACE[8]}px ${SPACE[8]}px`,
                      fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
                      color: "var(--textTer)" }}>
          model enters at 1 · top applies first
        </div>
      )}
      <div className="px-scroll" ref={listRef}
           style={{ display: "flex", flexDirection: "column",
                    gap: SPACE[8], minHeight: 0, position: "relative",
                    maxHeight: rail ? undefined : "min(280px, 34dvh)",
                    flex: rail ? 1 : undefined,
                    // Scrolling is frozen for the length of a drag: the row
                    // offsets are measured once at grab time, and letting the
                    // list move under them would aim the pill at the wrong gap.
                    overflowY: drag ? "hidden" : "auto",
                    userSelect: drag ? "none" : undefined }}>
        {drag && dropPillTop() !== null && (
          <div aria-hidden="true"
               style={{ position: "absolute", left: SPACE[10], right: SPACE[10],
                        top: dropPillTop(), height: PILL_H, borderRadius: 999,
                        background: "var(--accent)", boxShadow: SHADOW.glow,
                        // under the lifted row (z 3), over the static ones
                        zIndex: 2, pointerEvents: "none",
                        transition: `top ${MOTION.state}` }} />
        )}
        {core.map((stage) => {
          const meta = metaByName.get(stage.name);
          // Structural, but not compulsory: the toggle bypasses the stage and
          // it leaves the graph entirely. A bypassed stage keeps its row (so
          // it can come back) but surrenders its number - the numbers are the
          // load order of what will actually run.
          const on = (plan?.core || {})[stage.slot]?.enabled !== false;
          if (on) sequence += 1;
          const label = recipeStageLabel(stage, meta);
          // What will actually run when the stage is on: the stored override
          // when one deviates from the recipe, the authored strength
          // otherwise. A bypassed stage keeps the control - dimmed with the
          // rest of the row - so the retune is in place when it comes back.
          const coreStrength = (plan?.core || {})[stage.slot]?.strength ?? stage.strength;
          // The stage's own dials, bound by the declaration: a dial's
          // `choices_from` names the slot of the card it lives on (9.23a), so
          // the bypass variant switch sits on the bypass card itself. A card
          // with no dials gets no chevron - never a disclosure onto an empty
          // drawer. (An editable row is a drag row; a dial bound to an
          // editable slot would need the same treatment there and does not
          // have it yet - no declaration does that today.)
          const stageDials = dialsBySlot.get(stage.slot) || [];
          const cardOpen = !!openCards[stage.slot];
          return (
            <div key={`core-${stage.slot}`}
                 style={{ ...rowBase, display: "flex", flexDirection: "column",
                          alignItems: "stretch", gap: 0,
                          opacity: on ? 1 : 0.5,
                          background: on ? undefined : "transparent" }}>
              <div style={{ display: "grid",
                            gridTemplateColumns: "24px minmax(0,1fr) 56px auto",
                            alignItems: "center", gap: SPACE[10] }}>
                <span style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
                               color: "var(--textTer)", textAlign: "center" }}>
                  {on ? sequence : "—"}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: TYPE.ui, color: "var(--textSec)", overflow: "hidden",
                                textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {label}
                  </div>
                  <div style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
                                color: "var(--textMut)", overflow: "hidden",
                                textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {stage.role ? `${stage.role} · ` : ""}{short(stage.name)}
                    {/* An overridden dial states itself on the collapsed card,
                        in accent, where the vector count usually sits - an
                        override never hides inside a collapsed card. */}
                    {stageDials.length > 0 && stageDials.some((dial) => isSet(dial.key)) ? (
                      <span style={{ color: "var(--accent)" }}>
                        {" · "}{stageDials.map((dial) =>
                          dialValueLabel(dial, resolvedDial(dial))).join(" · ")}
                      </span>
                    ) : (meta?.vectors ? ` · ${meta.vectors} Vector` : "")}
                    {on ? " · core" : " · bypassed"}
                  </div>
                </div>
                <StrengthInput value={coreStrength} label={`${label} strength`}
                  disabled={!setCoreStrength}
                  onChange={(value) => setCoreStrength &&
                    setCoreStrength(stage.slot, value)} />
                <div style={{ display: "flex", alignItems: "center", gap: SPACE[6] }}>
                  {stageDials.length > 0 && (
                    <button type="button" onClick={() => toggleCard(stage.slot)}
                      aria-expanded={cardOpen} aria-label={`${label} controls`}
                      title={cardOpen ? `collapse the ${label} controls`
                                      : `expand the ${label} controls`}
                      style={{ height: 24, width: 24, display: "inline-flex",
                               alignItems: "center", justifyContent: "center",
                               flexShrink: 0, padding: 0, cursor: "pointer",
                               border: "1px solid var(--border)",
                               borderRadius: RADIUS.control,
                               background: "var(--bg2)", color: "var(--textTer)" }}>
                      <AccordionChevron open={cardOpen} />
                    </button>
                  )}
                  <Switch on={on} disabled={!setCoreEnabled} label={label}
                          title={on
                            ? `Bypass ${label} — it is a core ${recipe?.label || "recipe"} stage, so this is an override`
                            : !setCoreEnabled ? `${label} is required by this recipe`
                            : `Restore ${label} to the core chain`}
                          onChange={() => setCoreEnabled && setCoreEnabled(stage.slot, !on)} />
                </div>
              </div>
              {/* The drawer opens BELOW the header row, inside the card, so
                  expanding never moves the header out from under the cursor
                  mid-click. A hairline and a breath of space separate the
                  LoRA's own row from what fine-tunes it. */}
              {stageDials.length > 0 && (
                <AccordionPanel open={cardOpen}>
                  <div style={{ display: "flex", flexDirection: "column", gap: SPACE[16],
                                marginTop: SPACE[12], paddingTop: SPACE[12],
                                borderTop: "1px solid var(--border)" }}>
                    {stageDials.map(renderDialRow)}
                  </div>
                </AccordionPanel>
              )}
            </div>
          );
        })}

        {entries.map((entry, index) => {
          sequence += 1;
          const { stage, name, meta } = detailFor(entry);
          const locked = !!stage?.order_locked;
          const strengthEditable = !stage || stage.strength_editable !== false;
          const removable = !stage || stage.removable !== false;
          const enabled = entry.enabled !== false;
          const label = stage ? recipeStageLabel(stage, meta)
            : (entry.title || meta?.title || short(name));
          return (
            <div key={entry.slot ? `slot-${entry.slot}` : `user-${entry.name}`}
              data-lora-row={index}
              style={{ ...rowBase,
                       background: enabled ? "var(--bg2)" : "transparent",
                       borderColor: drag?.from === index ? "var(--accent)"
                         : locked ? "var(--borderHov)" : "var(--border)",
                       ...(rowMotion(index) || {}) }}>
              {locked ? (
                <span style={{ display: "inline-flex", alignItems: "center",
                               justifyContent: "center", color: "var(--textMut)" }}>
                  <LockSimple size={12} weight="fill" />
                </span>
              ) : (
                <button type="button" aria-label={`Reorder ${label}`}
                  title="Drag to reorder"
                  onPointerDown={(event) => {
                    if (event.button !== 0) return;
                    const tops = measureRows();
                    if (!tops || !tops[index]) return;
                    // Claim the pointer so the drag survives leaving the button,
                    // and stop the browser starting a text selection instead.
                    event.preventDefault();
                    event.currentTarget.setPointerCapture(event.pointerId);
                    setDrag({ from: index, to: index, dy: 0,
                              startY: event.clientY, tops });
                  }}
                  onPointerMove={(event) => {
                    const y = event.clientY;     // read before the updater runs
                    setDrag((state) => {
                      if (!state || state.from !== index) return state;
                      const dy = y - state.startY;
                      return { ...state, dy, to: dropTarget(state, dy) };
                    });
                  }}
                  onPointerUp={(event) => {
                    event.currentTarget.releasePointerCapture?.(event.pointerId);
                    if (drag && drag.to !== drag.from) moveEntry(drag.from, drag.to);
                    setDrag(null);
                  }}
                  onPointerCancel={() => setDrag(null)}
                  onKeyDown={(event) => {
                    const direction = event.key === "ArrowUp" ? -1
                      : event.key === "ArrowDown" ? 1 : 0;
                    if (!direction) return;
                    const target = adjacentFlexible(index, direction);
                    if (target < 0) return;
                    event.preventDefault();
                    moveEntry(index, target);
                  }}
                  style={{ width: 24, height: 30, padding: 0, display: "inline-flex",
                           alignItems: "center", justifyContent: "center", border: "none",
                           borderRadius: RADIUS.control, background: "transparent",
                           color: drag?.from === index ? "var(--accent)" : "var(--textTer)",
                           cursor: drag?.from === index ? "grabbing" : "grab",
                           transition: `color ${MOTION.hover}`, touchAction: "none" }}>
                  <DotsSixVertical size={15} weight="bold" />
                </button>
              )}
              <div style={{ minWidth: 0 }}>
                <div title={label} style={{ fontSize: TYPE.body,
                  color: enabled ? "var(--text)" : "var(--textTer)", overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {label}
                </div>
                <div style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 9,
                              color: "var(--textMut)", overflow: "hidden",
                              textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {sequence} · {stage?.role ? `${stage.role} · ` : ""}{short(name)}
                  {stage ? " · recipe" : " · extra"}
                  {!enabled ? " · off" : ""}
                </div>
              </div>
              {strengthEditable ? (
                <StrengthInput value={entry.strength}
                  label={`${stage ? recipeStageLabel(stage, meta)
                    : (entry.title || short(name))} strength`}
                  onChange={(value) => changeStrength(index, value)} />
              ) : (
                <span style={{ width: 56, textAlign: "center",
                               fontFamily: "ui-monospace, Consolas, monospace", fontSize: 10,
                               color: "var(--textTer)" }}>{entry.strength}</span>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: SPACE[6] }}>
                <Switch on={enabled} disabled={!removable} label={label}
                        title={!removable ? `${label} is required by this recipe`
                                          : `${enabled ? "Disable" : "Enable"} ${label}`}
                        onChange={() => toggleEntry(index)} />
                <MiniAction label="Remove LoRA" disabled={!removable}
                            onClick={() => setEntries(entries.filter((_, i) => i !== index))}>
                  <X size={10} weight="bold" />
                </MiniAction>
              </div>
            </div>
          );
        })}
      </div>

      {addControl}

        </>
      )}
    </section>
  );
};

export const ComposerBar = ({ opts, setOpts, selectCharacter,
                              selectIdentityReference, addReference, deleteCharacter,
                              options, onNewCharacter, onEditCharacter, refreshOptions,
                              selectSavedStyle, onNewStyle, onEditStyle, onStyleFromImage,
                              promptEnhance = true }) => {
  const [pop, setPop] = useState(null);        // model|style|char|size|ref
  const [refKind, setRefKind] = useState("style");
  const [filter, setFilter] = useState("");
  const [refSort, setRefSort] = useState("new");   // new|old|name
  // The model picker is two levels: a short shelf of families, then that
  // family's own builds. null = the shelf. A long flat list of every installed
  // file was the thing nobody could find anything in.
  const [familyOpen, setFamilyOpen] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [refError, setRefError] = useState(null);
  const [deletingCharacter, setDeletingCharacter] = useState(null);
  const [characterDeleteError, setCharacterDeleteError] = useState(null);
  const fileRef = useRef(null);
  const uploadKindRef = useRef("style");
  // 9.66: "from image" reads a render's ComfyUI metadata into a style draft.
  // Its own input beside fileRef - the shared one uploads to ComfyUI/input,
  // which is reference plumbing, not style intake.
  const styleImageRef = useRef(null);
  const [styleImageError, setStyleImageError] = useState(null);
  const [styleImageBusy, setStyleImageBusy] = useState(false);

  const open = (p) => {
    setPop(pop === p ? null : p);
    setFilter("");
    // Reopen the picker on the family the current model belongs to, so the
    // shelf is not a step backwards once a choice has been made.
    if (p === "model")
      setFamilyOpen(opts.model
        ? (((options && options.model_meta) || {})[opts.model] || {}).family || null
        : null);
    if (p === "char") setCharacterDeleteError(null);
    if (p === "ref") setRefError(null);
  };
  const recipes = (options && options.recipes) || [];
  const recipeById = (id) => recipes.find((recipe) => recipe.id === id);
  const hasIdentityRef = (opts.refs || []).some((r) => r.kind === "identity" && r.file);
  const hasIdentitySource = !!opts.character || hasIdentityRef;
  // Identity Edit is a Krea 2 recipe. Everything else stays on the shelf greyed
  // instead of filtered away: a collection that silently shrinks to one family
  // reads as models having gone missing from disk, not as a mode narrowing what
  // can run. The store already clears an incompatible selection when identity
  // engages (identityCompatibleSelections), so nothing here can be left picked.
  // MiniMax H3 is the exemption (9.67): its builds take the anchor's photo as
  // a native reference - h3_ref_still on a ref2va build, the plain caption on
  // fl2va - so the character locks nothing in this family.
  const identityBlocked = (m) => hasIdentitySource && m.family !== "minimax_h3" &&
    !(m.family === "krea2" && (m.compatible_recipes || []).includes("identity_edit"));
  // The H3 ref2va still is the one model row that NEEDS the anchor: with no
  // character there is no reference to carry. Read off the recipe rows'
  // needs_character flag (/api/options), matched by family+variant so
  // identity_edit - which declares no variants - never greys a Krea 2 row.
  const needsCharModel = (m) => !opts.character &&
    recipes.some((r) => r.needs_character && r.family === m.family &&
                 (r.variants || []).includes(m.variant));
  const styleKey = ["realism", "anime", "fantasy"].includes(opts.style)
    ? opts.style : "realism";
  const quality = opts.quality === "refined" ? "refined" : "standard";
  const STYLES = [
    { key: "realism", label: "Realism", Icon: Lightning },
    { key: "anime", label: "Anime", Icon: Palette },
    { key: "fantasy", label: "Fantasy", Icon: Sparkle },
  ];
  const selectedStyle = STYLES.find((style) => style.key === styleKey) || STYLES[0];
  // Canvas megapixels. Seven values plus auto fills two rows of four exactly,
  // which is why the ladder is this length. The list is not closed, though:
  // the server accepts 0.1 to 8, and a saved style can carry anything in that
  // range ported from a ComfyUI graph - Ultra Realism's 5.9 arrived that way.
  // Off-ladder values get the full-width slot rather than a ninth cell, so the
  // grid never ends in one orphan button.
  const MP_LADDER = [1, 1.5, 2, 3, 4, 6, 8];
  const customMp = Number(opts.mp) > 0 && !MP_LADDER.includes(Number(opts.mp))
    ? Number(opts.mp) : null;
  // A recipe can cap the ladder (h3_still tops out at its native 2K): rungs
  // above the cap render disabled and name it, and a stored mp above it reads
  // out the clamped canvas rather than promising one the model cannot render.
  const cappedRecipe = recipeById(opts.engine);
  const mpCap = (cappedRecipe && cappedRecipe.mp_cap) || null;
  const mpCapTitle = mpCap
    ? `${cappedRecipe.label} tops out at ${(((options || {}).defaults || {})[opts.engine] || {}).mp ?? mpCap} MP`
    : "";
  const canvasDims = opts.aspect && opts.mp
    ? dimsFor(opts.aspect, mpCap ? Math.min(Number(opts.mp), mpCap) : Number(opts.mp))
    : null;
  const savedStyles = (options && options.saved_styles) || [];
  // The ACTIVE saved style, gated on availability the same way the store and
  // the server gate it - so the pill can never name a style that will not run.
  const activeSavedStyle = savedStyles.find(
    (s) => s.id === opts.saved_style && s.available) || null;
  // No identity guard: the rows themselves disable styles whose model cannot
  // carry the identity patch, and the store heals the rest.
  const chooseSavedStyle = (id) => {
    selectSavedStyle(id);
    setFilter(""); setPop(null);
  };
  const selectedModelMeta = ((options && options.model_meta) || {})[opts.model] || {};

  /* ── the saved-style shelf, organised by model family ──────────────────
     A saved style SETS the model (selectSavedStyle), so the family is the
     fact that separates one from the next and the axis the shelf is built
     on. Chips filter, breakers label, and the family you are currently on
     leads - which is the whole of "I can't tell which of these is MiniMax".
     `null` on the chip means the family of the model you are on, so opening
     the shelf lands on your own styles without a click; "All" is one chip
     away, because picking a style is also HOW you change family. */
  const savedFamilyOf = (s) =>
    (((options && options.model_meta) || {})[s.model] || {}).family || "unknown";
  const currentFamily = selectedModelMeta.family || null;
  const savedFamilies = [...new Set(savedStyles.map(savedFamilyOf))]
    .sort((a, b) => (a === currentFamily ? -1 : b === currentFamily ? 1 : 0) ||
                    familyName(a).localeCompare(familyName(b)));
  const [savedFamily, setSavedFamily] = useState(null);
  // A chip for a family that no longer has styles (or a model change that
  // moved the shelf under you) must not leave an empty list with no reason.
  const activeFamily = savedFamily && savedFamilies.includes(savedFamily)
    ? savedFamily
    : savedFamily === "all"
      ? "all"
      : (currentFamily && savedFamilies.includes(currentFamily))
        ? currentFamily : "all";
  const savedStyleGroups = savedFamilies
    .filter((f) => activeFamily === "all" || f === activeFamily)
    .map((family) => ({
      family,
      label: familyName(family),
      current: family === currentFamily,
      items: savedStyles.filter((s) => savedFamilyOf(s) === family),
    }))
    .filter((g) => g.items.length);
  const modelLabel = opts.model ? (selectedModelMeta.title || short(opts.model))
    : "let Pixal choose";
  const identityRecipe = recipeById("identity_edit");
  const identityAvailable = !!identityRecipe?.available;
  const identityMissing = (identityRecipe?.missing || []).join("\n");

  // Krea 2 owns no Anime or Fantasy graph, but its photo recipe can still be
  // DIRECTED into either - the server sends the register as craft direction.
  // So the choice is real on Krea; it just isn't a different graph, and it
  // needs none of Z-Image's anime/fantasy assets on disk. The identity graph
  // is a Krea 2 recipe too, so an identity source takes the same direction.
  const styleDirected = (style) => style !== "realism" &&
    (hasIdentitySource || selectedModelMeta.family === "krea2");

  // A DIRECTED style and Cinematic are both craft direction the brain writes
  // into the scene. With Prompt Enhance off the user's words go to the sampler
  // untouched - so there is nowhere for that direction to land, and the render
  // silently came back straight and un-styled while the pill still claimed it.
  // Say so instead: never show a pick the render will not honour.
  const craftNeedsBrain = !promptEnhance;

  const styleAvailable = (style) => styleDirected(style) ? true
    : style === "realism"
      ? hasIdentitySource ||
        ["realism", "realism_ii", "zimage"].some((id) => recipeById(id)?.available)
      : !!recipeById(style)?.available;

  // The selected model is authoritative. Z-Image Turbo uses Realism; Z-Image
  // Base can also run Anime and Fantasy on their own graphs.
  const styleAllowedByModel = (style) => {
    if (!opts.model) return true;
    if (selectedModelMeta.family === "krea2") return true;
    if (selectedModelMeta.family === "zimage" && selectedModelMeta.variant === "turbo")
      return style === "realism";
    if (selectedModelMeta.family === "zimage" && selectedModelMeta.variant === "base")
      return true;
    // Qwen-Image renders one way. Realism stays lit so the pill matches what
    // withExecutionRecipe pins it to, rather than leaving every style inert.
    if (selectedModelMeta.family === "qwen_image") return style === "realism";
    // Anima draws anime and only anime; lighting Anime keeps the pill honest
    // about what withExecutionRecipe pins it to.
    if (selectedModelMeta.family === "anima") return style === "anime";
    // MiniMax H3 renders one still way; Realism stays lit so the pill matches
    // what withExecutionRecipe pins it to (the qwen_image pattern).
    if (selectedModelMeta.family === "minimax_h3") return style === "realism";
    const compatible = selectedModelMeta.compatible_recipes || [];
    return style === "realism"
      ? compatible.some((id) => ["realism", "realism_ii", "zimage"].includes(id))
      : compatible.includes(style);
  };
  // Refined is per-family: Realism II on Krea 2, the in-family 2x latent
  // refine on a MiniMax H3 build - each gated on its own recipe's
  // availability. On H3 the id depends on the LANE: an anchored ref2va build
  // refines through h3_ref_still_2x (9.84). Naming h3_still_2x for every H3
  // model is what let this control render enabled and tagged "two-pass
  // finish" on the one lane whose chooser ignored it, so the row must follow
  // the same condition store.js routes on - family, variant AND character.
  const refinedRecipeId = selectedModelMeta.family !== "minimax_h3"
    ? "realism_ii"
    : (selectedModelMeta.variant === "ref2va" && opts.character
        ? "h3_ref_still_2x" : "h3_still_2x");
  const refinedAvailable = !!recipeById(refinedRecipeId)?.available &&
    (selectedModelMeta.family === "minimax_h3" || !opts.model ||
     selectedModelMeta.family === "krea2");

  const chooseStyle = (style) => {
    if (!styleAvailable(style) || !styleAllowedByModel(style)) return;
    const nextQuality = style === "realism" && (quality !== "refined" || refinedAvailable)
      ? quality : "standard";
    setOpts({ style, quality: nextQuality });
    setFilter(""); setPop(null);
  };

  const chooseQuality = (nextQuality) => {
    if (hasIdentitySource || styleKey !== "realism" ||
        (nextQuality === "refined" && !refinedAvailable)) return;
    setOpts({ quality: nextQuality });
    setFilter(""); setPop(null);
  };

  const chooseModel = (n, m) => {
    if (!m.supported || identityBlocked(m) || needsCharModel(m)) return;
    setOpts({ model: n }); setPop(null);
  };

  const clearModel = () => {
    setOpts({ model: "" }); setFilter(""); setFamilyOpen(null); setPop(null);
  };

  // Every model this composer could legitimately offer, before the two-level
  // navigation narrows it. source_only models (Qwen Image Edit) have no
  // text-to-image path: they are reached from a finished frame's edit action.
  const pickableModels = options ? options.models.filter((n) => {
    const m = (options.model_meta || {})[n] || {};
    return !!m.supported && !m.source_only;
  }) : [];

  const matchesFilter = (n) => {
    const m = (options.model_meta || {})[n] || {};
    const q = filter.trim().toLowerCase();
    if (!q) return true;
    return (m.title || short(n)).toLowerCase().includes(q) ||
      n.toLowerCase().includes(q) ||
      (m.base || "").toLowerCase().includes(q) ||
      familyName(m.family).toLowerCase().includes(q);
  };

  // Families become the folders. Ordered by how many builds each holds, so the
  // collection someone actually invested in leads.
  const families = useMemo(() => {
    const by = new Map();
    for (const n of pickableModels) {
      const m = (options.model_meta || {})[n] || {};
      const key = m.family || "unknown";
      if (!by.has(key))
        by.set(key, { key, label: familyName(key), models: [], isNew: false,
                      thumb: null, counts: new Map(), pickable: 0 });
      const group = by.get(key);
      group.models.push(n);
      if (!identityBlocked(m) && !needsCharModel(m)) group.pickable += 1;
      const variant = variantName(m.variant);
      if (variant) group.counts.set(variant, (group.counts.get(variant) || 0) + 1);
      if (m.is_new) group.isNew = true;
      if (!group.thumb && m.thumb) group.thumb = m.thumb;
    }
    return [...by.values()].map((group) => ({
      ...group,
      // Dimmed, not dropped - the folder still opens so its builds stay visible.
      blocked: group.pickable === 0,
      variants: [...group.counts.entries()]
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    })).sort((a, b) => b.models.length - a.models.length ||
      a.label.localeCompare(b.label));
  }, [pickableModels.join("|"), options && options.model_meta, hasIdentitySource]);

  const searching = !!filter.trim();
  const modelList = searching
    ? pickableModels.filter(matchesFilter)
    : familyOpen
      ? pickableModels.filter((n) =>
        (((options || {}).model_meta || {})[n] || {}).family === familyOpen)
      : [];

  // Inside a family, split by variant. Z-Image Base and Turbo are different
  // schedules, not just different weights, so they are the real choice being
  // made here - interleaving them alphabetically hides it.
  const modelGroups = useMemo(() => {
    if (searching || !familyOpen) return [{ variant: "", models: modelList }];
    const by = new Map();
    for (const n of modelList) {
      const key = variantName(((options || {}).model_meta || {})[n]?.variant);
      if (!by.has(key)) by.set(key, []);
      by.get(key).push(n);
    }
    const groups = [...by.entries()].map(([variant, models]) => ({
      variant, models,
      // The packaging is only worth a tag when it tells the rows apart; five
      // rows all labelled "safetensors" is just noise down the right edge.
      mixedFormats: new Set(models.map((n) =>
        ((options || {}).model_meta || {})[n]?.format)).size > 1,
    }));
    if (groups.length < 2) return [{ variant: "", models: modelList }];
    return groups.sort((a, b) => a.variant.localeCompare(b.variant));
  }, [modelList.join("|"), searching, familyOpen, options && options.model_meta]);
  // ComfyUI/input is a junk drawer that only grows - newest-first alone stops
  // being findable the moment the thing you want is not from today.
  const inputAll = useMemo(() => inputImages(options), [options]);
  const inputList = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const byName = (a, b) => a.name.localeCompare(b.name);
    const rows = q ? inputAll.filter((image) => image.name.toLowerCase().includes(q))
                   : inputAll.slice();
    return rows.sort(
      refSort === "name" ? byName
        : refSort === "old" ? (a, b) => (a.mtime || 0) - (b.mtime || 0) || byName(a, b)
          : (a, b) => (b.mtime || 0) - (a.mtime || 0) || byName(a, b));
  }, [inputAll, filter, refSort]);

  // Everything the next render will actually carry, in one place. The edit
  // source rides along because it is picked from this same popup, even though
  // it is a source and not a reference.
  const attachedNow = useMemo(() => [
    ...(opts.refs || []).map((ref) => ({ kind: ref.kind, file: ref.file })),
    ...(opts.editSource ? [{ kind: "edit", file: opts.editSource }] : []),
  ], [opts.refs, opts.editSource]);

  const detachRef = (item) => {
    if (item.kind === "edit") return setOpts({ editSource: "" });
    if (item.kind === "identity" && selectIdentityReference)
      return selectIdentityReference("");
    setOpts({ refs: (opts.refs || []).filter(
      (ref) => !(ref.kind === item.kind && ref.file === item.file)) });
  };

  const addRef = (kind, file) => {
    // Picking under "edit photo" arms the next message as an edit instruction
    // instead of attaching a reference - one source at a time, so it replaces.
    if (kind === "edit") {
      setOpts({ editSource: file });
      setRefError(null);
      setPop(null); setFilter("");
      return true;
    }
    const added = addReference
      ? addReference(kind, file)
      : kind === "identity" ? selectIdentityReference(file)
        : (setOpts({ refs: [...(opts.refs || []), { kind, file }] }), true);
    if (!added) {
      setRefError(kind === "identity"
        ? "Identity Edit is unavailable with the currently installed recipe assets."
        : "That reference could not be attached.");
      return false;
    }
    setRefError(null);
    setPop(null); setFilter("");
    return true;
  };
  const doRetag = async (image, kind) => {
    setRefError(null);
    try {
      await setInputRefType(image.name, kind);
      if (refreshOptions) await refreshOptions();
    } catch (error) {
      setRefError(error?.message || "The reference type could not be saved.");
    }
  };

  // 9.66: a render file -> a style draft. The server reads the embedded
  // ComfyUI metadata and answers a draft + what it could not map; the draft
  // opens in the style editor (Chat owns the form) and saving stays the
  // editor's own button. No metadata is an answer, not a crash.
  const doStyleFromImage = async (f) => {
    if (!f) return;
    setStyleImageBusy(true); setStyleImageError(null);
    try {
      const r = await styleFromImage(f);
      if (!r?.ok) {
        setStyleImageError(r?.error || "no render metadata in that image");
        return;
      }
      setPop(null);
      onStyleFromImage && onStyleFromImage(r);
    } catch (error) {
      setStyleImageError("the image could not be read");
    } finally {
      setStyleImageBusy(false);
    }
  };

  const doUpload = async (f, kind) => {
    if (!f) return;
    setUploading(true); setRefError(null);
    try {
      const image = await upload(f, kind === "edit" ? "" : kind);
      if (refreshOptions) await refreshOptions();
      addRef(kind, image.name);
    } catch (error) {
      setRefError(error?.message || "The image could not be uploaded.");
    } finally {
      setUploading(false);
    }
  };

  const removeCharacter = async (character) => {
    const confirmed = window.confirm(
      `Delete the "${character.name}" character anchor?\n\n` +
      "This removes only the anchor. Its source image stays in ComfyUI/input.");
    if (!confirmed) return;
    setDeletingCharacter(character.id);
    setCharacterDeleteError(null);
    const result = await deleteCharacter(character.id);
    if (!result?.ok)
      setCharacterDeleteError(result?.error || "Could not delete the character anchor.");
    setDeletingCharacter(null);
  };

  const defaultRecipeId = hasIdentitySource ? "identity_edit"
    : quality === "refined" ? "realism_ii"
    : styleKey === "anime" || styleKey === "fantasy" ? styleKey : "realism";
  const defaultModel = recipeById(defaultRecipeId)?.default_model || "";
  const openFamily = families.find((f) => f.key === familyOpen);

  const modelChoices = options ? (
    <>
      {/* The recommended path, stated as what it does rather than as a shrug. */}
      <Row sel={!opts.model} onClick={clearModel}
           style={{ alignItems: "flex-start", border: `1px solid ${!opts.model
             ? "var(--accent)" : "var(--border)"}`, borderRadius: RADIUS.input,
             padding: `${SPACE[8]}px ${SPACE[10]}px`, marginBottom: SPACE[8] }}>
        <Sparkle size={16} weight="duotone" style={{ flexShrink: 0, marginTop: 1 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: SPACE[6] }}>
            <span style={{ color: "var(--text)" }}>Let Pixal choose</span>
            <span style={{ fontFamily: "ui-monospace, Consolas, monospace",
                           fontSize: 9, color: "var(--accent)" }}>recommended</span>
          </div>
          <div style={{ marginTop: 2, fontSize: TYPE.label, lineHeight: 1.45,
                        color: "var(--textTer)", whiteSpace: "normal" }}>
            {hasIdentitySource
              ? "Matches your character to the edit model that holds a likeness best, at its measured settings."
              : "Reads what you asked for and matches it to the model that renders it best, at that model's measured high-fidelity settings."}
          </div>
        </div>
      </Row>

      {/* Say the rule once, so a shelf of dimmed families is legible at a glance. */}
      {hasIdentitySource && (
        <div style={{ marginBottom: SPACE[8], padding: `${SPACE[6]}px ${SPACE[8]}px`,
                      border: "1px solid var(--border)", borderRadius: RADIUS.input,
                      color: "var(--textTer)", fontSize: TYPE.label, lineHeight: 1.45 }}>
          Identity Edit runs on Krea 2. MiniMax H3 stays pickable - the
          character's photo is its reference. Other families are greyed until
          you clear the character or identity reference.
        </div>
      )}

      <FilterInput value={filter} onChange={setFilter}
                   placeholder="search every installed model…" />

      {/* Level 1: the family shelf. Skipped entirely while searching. */}
      {!searching && !familyOpen && (
        families.length ? (
          <div style={{ display: "grid", gap: SPACE[6],
                        gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}>
            {families.map((family) => (
              <FamilyCard key={family.key} family={family}
                          selected={selectedModelMeta.family === family.key}
                          onClick={() => setFamilyOpen(family.key)} />
            ))}
          </div>
        ) : (
          <div style={{ padding: `${SPACE[10]}px ${SPACE[8]}px`, color: "var(--textTer)",
                        fontSize: TYPE.label, lineHeight: 1.4 }}>
            No installed model has a supported Pixal profile yet.
          </div>
        )
      )}

      {/* Level 2 header: where you are, and the way back. */}
      {!searching && openFamily && (
        <Row onClick={() => setFamilyOpen(null)} style={{ marginBottom: SPACE[4] }}>
          <CaretLeft size={12} weight="bold" />
          <span style={{ color: "var(--text)" }}>{openFamily.label}</span>
          <Tag>{openFamily.models.length} installed · all families</Tag>
        </Row>
      )}

      {searching && (
        <div style={{ padding: `0 ${SPACE[8]}px ${SPACE[6]}px`, color: "var(--textTer)",
                      fontSize: TYPE.label }}>
          {modelList.length} {modelList.length === 1 ? "match" : "matches"} across every family
        </div>
      )}

      {modelGroups.map((group) => (
        <div key={group.variant || "all"}>
          {group.variant && (
            <div style={{ padding: `${SPACE[6]}px ${SPACE[8]}px 2px`,
                          fontFamily: "ui-monospace, Consolas, monospace",
                          fontSize: 9, letterSpacing: 0.4, textTransform: "uppercase",
                          color: "var(--textTer)" }}>
              {group.variant}
            </div>
          )}
          {group.models.map((n) => {
        const m = (options.model_meta || {})[n] || {};
        const recipeDefault = defaultModel === n;
        const variant = variantName(m.variant);
        // Say the thing the reader does not already have. Searching spans
        // families, so name the family; a variant heading above already names
        // the variant, so fall back to the packaging.
        const familyLabel = searching
          ? `${familyName(m.family)}${variant ? ` ${variant}` : ""}`
          : group.variant ? (group.mixedFormats ? m.format || "" : "")
          : variant || familyName(m.family);
        const blocked = identityBlocked(m);
        const needsChar = needsCharModel(m);
        return (
          <Row key={n} sel={opts.model === n} disabled={blocked || needsChar}
               title={blocked
                 ? `${n}\n\nIdentity Edit runs on Krea 2. Clear the character or identity reference to pick this model.`
                 : needsChar
                 ? `${n}\n\nNeeds an active character - the reference photo is the identity.`
                 : n}
               onClick={() => chooseModel(n, m)}>
            <LoraThumb src={m.thumb} size={36} Glyph={Monitor} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                            minWidth: 0 }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                               whiteSpace: "nowrap" }}>
                  {m.title || short(n)}
                </span>
                {m.is_new && <NewChip />}
              </div>
              <div style={{ fontFamily: "ui-monospace, Consolas, monospace",
                            fontSize: 9, color: "var(--textTer)",
                            overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap" }}>
                {m.title ? short(n) : (m.base || familyName(m.family))}
              </div>
              {m.profile_id && (
                <div style={{ marginTop: 2, fontSize: 9, color: "var(--accent)",
                              lineHeight: 1.3 }}>
                  tuned Pixal profile · {m.steps ? `${m.steps} steps · ` : ""}settings included
                </div>
              )}
            </div>
            <Tag>{blocked ? "not for identity"
              : needsChar ? "needs character"
              : recipeDefault ? "profile default"
              : quality === "refined" ? "refined profile"
              : familyLabel}</Tag>
          </Row>
        );
          })}
        </div>
      ))}
      {(searching || familyOpen) && modelList.length === 0 && (
        <div style={{ padding: `${SPACE[10]}px ${SPACE[8]}px`, color: "var(--textTer)",
                      fontSize: TYPE.label, lineHeight: 1.4 }}>
          {searching ? `No installed model matches “${filter.trim()}”.`
                     : "Nothing installed in this family yet."}
        </div>
      )}
    </>
  ) : null;

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: SPACE[6], flexWrap: "wrap" }}>
        {/* Attach leads the row as a bare +, so the four labelled pills after it
            get the width they need to stay on one line. */}
        {refControl()}
        {/* Primary choice: installed model. Technical recipe IDs stay hidden. */}
        <div style={{ position: "relative" }}>
          <PillBtn Icon={<Monitor size={14} weight="duotone" />}
                   label={`model · ${modelLabel}`} title={`Model: ${modelLabel}`}
                   maxWidth={300} active={!!opts.model} onClick={() => open("model")}>
            <CaretDown size={11} weight="bold" style={{ opacity: 0.6 }} />
          </PillBtn>
          {pop === "model" && (
            <Pop title="model" onClose={() => setPop(null)} xl>
              {modelChoices}
            </Pop>
          )}
        </div>

        {/* Creative direction is independent of model family. */}
        <div style={{ position: "relative" }}>
          <PillBtn Icon={hasIdentitySource
                     ? <UserCircle size={14} weight="duotone" />
                     : selectedStyle
                       ? <selectedStyle.Icon size={14} weight="duotone" />
                       : <Palette size={14} weight="duotone" />}
                   label={`style · ${hasIdentitySource
                     ? `identity${!craftNeedsBrain && styleDirected(styleKey)
                         ? ` · ${selectedStyle.label.toLowerCase()}` : ""}`
                     : activeSavedStyle ? activeSavedStyle.name
                     : `${(craftNeedsBrain && styleDirected(styleKey)
                           ? "realism" : selectedStyle.label.toLowerCase())}${
                         quality === "refined" ? " · refined" : ""}`}${
                       opts.cinematic && !craftNeedsBrain ? " · cinematic" : ""}`}
                   title={hasIdentitySource
                     ? "Identity runs on Krea 2; Anime and Fantasy are directed into the identity render"
                     : "Choose a visual style"}
                   active={hasIdentitySource || !!selectedStyle}
                   onClick={() => open("style")}>
            <CaretDown size={11} weight="bold" style={{ opacity: 0.6 }} />
          </PillBtn>
          {pop === "style" && (
            <Pop title="style" onClose={() => setPop(null)} wide>
              <div style={{ padding: `0 ${SPACE[8]}px ${SPACE[8]}px`, color: "var(--textTer)",
                            fontSize: TYPE.label, lineHeight: 1.4 }}>
                {hasIdentitySource
                  ? "Identity runs on Krea 2 with the identity patch and vector bypass always in the chain. Anime and Fantasy are directed into that render; saved styles on a Krea 2 model still apply."
                  : activeSavedStyle
                    ? `“${activeSavedStyle.name}” runs ${activeSavedStyle.base_label} on ${short(activeSavedStyle.model)}. Picking a built-in style below leaves it.`
                    // "Which of these work with my model?" has no answer while
                    // the shelf stays silent about the rule, so state it: a
                    // saved style carries its own model and switches to it.
                    : "Built-in styles keep your model. A saved style brings its own and switches to it."}
              </div>
              {STYLES.map((style) => {
                const assetsReady = styleAvailable(style.key);
                const modelAllows = styleAllowedByModel(style.key);
                // a directed style exists only in the brain's craft direction
                const needsBrain = craftNeedsBrain && styleDirected(style.key);
                const available = assetsReady && modelAllows && !needsBrain;
                return (
                  <Row key={style.key} sel={!activeSavedStyle && styleKey === style.key}
                       disabled={!available}
                       title={!assetsReady ? `${style.label} assets are missing`
                         : !modelAllows ? `${modelLabel} supports Realism only`
                         : needsBrain
                           ? `${modelLabel} has no ${style.label} graph, so this style is written into the scene - turn Prompt enhance on to use it`
                           : undefined}
                       onClick={() => chooseStyle(style.key)}>
                    <style.Icon size={12} weight="duotone" />
                    <span>{style.label}</span>
                    <Tag>{!assetsReady ? "assets missing"
                      : !modelAllows ? "not for this model"
                      : needsBrain ? "needs prompt enhance"
                      : styleDirected(style.key) ? "directed" : "ready"}</Tag>
                  </Row>
                );
              })}

              {/* Frame stays reachable under a character or identity reference:
                  the server applies CINEMATIC_DIRECTIVE on that branch too, so
                  hiding the switch left it armed with no way to turn it off. */}
              {(
                <>
                  <div style={{ borderTop: "1px solid var(--border)",
                                margin: `${SPACE[8]}px 0` }} />
                  <div style={{ padding: `0 ${SPACE[8]}px ${SPACE[6]}px`,
                                fontSize: TYPE.micro, fontWeight: W.heading,
                                letterSpacing: "0.08em", textTransform: "uppercase",
                                color: "var(--textTer)" }}>
                    frame
                  </div>
                  <Row sel={!opts.cinematic} onClick={() => setOpts({ cinematic: false })}>
                    <ImageSquare size={12} weight="duotone" /> Straight
                    <Tag>deep focus</Tag>
                  </Row>
                  <Row sel={!!opts.cinematic && !craftNeedsBrain}
                       disabled={craftNeedsBrain}
                       onClick={() => setOpts({ cinematic: true })}
                       title={craftNeedsBrain
                         ? "Cinematic is written into the scene, so it needs Prompt enhance on"
                         : "Anamorphic lens, a shallow plane of focus, motivated practical light and a graded palette."}>
                    <FilmSlate size={12} weight="duotone" /> Cinematic
                    <Tag>{craftNeedsBrain ? "needs prompt enhance"
                      : "shallow focus · graded"}</Tag>
                  </Row>
                </>
              )}
              {/* Saved styles — user-authored recipes from recipes/*.json.
                  They sit BELOW the built-ins because they are additions to
                  the shelf, not replacements for it, and an unavailable one
                  stays visible with its reason rather than vanishing: a style
                  that disappears reads as data loss, not as a missing file. */}
              {(
                <>
                  <div style={{ borderTop: "1px solid var(--border)",
                                margin: `${SPACE[8]}px 0` }} />
                  <div style={{ display: "flex", alignItems: "center",
                                padding: `0 ${SPACE[8]}px ${SPACE[6]}px`,
                                fontSize: TYPE.micro, fontWeight: W.heading,
                                letterSpacing: "0.08em", textTransform: "uppercase",
                                color: "var(--textTer)" }}>
                    <span>saved styles</span>
                    <button type="button" disabled={styleImageBusy}
                      onClick={() => { setStyleImageError(null); styleImageRef.current?.click(); }}
                      title="From image — reads ComfyUI metadata"
                      style={{ marginLeft: "auto", display: "inline-flex",
                               alignItems: "center", gap: SPACE[4], height: 20,
                               padding: `0 ${SPACE[6]}px`, border: "none",
                               background: "transparent",
                               color: styleImageBusy ? "var(--textTer)" : "var(--accent)",
                               fontFamily: FONT, fontSize: TYPE.label,
                               textTransform: "none", letterSpacing: 0,
                               cursor: styleImageBusy ? "default" : "pointer" }}>
                      <ImageSquare size={10} weight="duotone" /> from image
                    </button>
                    <button type="button" onClick={onNewStyle}
                      title="Save the current model, LoRA stack and sampler as a style"
                      style={{ marginLeft: SPACE[4], display: "inline-flex",
                               alignItems: "center", gap: SPACE[4], height: 20,
                               padding: `0 ${SPACE[6]}px`, border: "none",
                               background: "transparent", color: "var(--accent)",
                               fontFamily: FONT, fontSize: TYPE.label,
                               textTransform: "none", letterSpacing: 0,
                               cursor: "pointer" }}>
                      <Plus size={10} weight="bold" /> save current
                    </button>
                  </div>
                  {styleImageError && (
                    <div style={{ padding: `0 ${SPACE[8]}px ${SPACE[8]}px`,
                                  color: "#E3A7B0", fontSize: TYPE.label,
                                  lineHeight: 1.4 }}>
                      {styleImageError}
                    </div>
                  )}
                  {/* Tiny label chips, one per family that actually has
                      styles. They answer "where are the MiniMax ones" before
                      the list is even read, and they are the only control
                      here that can be wrong in a harmless direction: All is
                      always one click away. */}
                  {savedFamilies.length > 1 && (
                    <div style={{ display: "flex", flexWrap: "wrap",
                                  gap: SPACE[4],
                                  padding: `0 ${SPACE[8]}px ${SPACE[6]}px` }}>
                      {["all", ...savedFamilies].map((f) => {
                        const on = activeFamily === f;
                        return (
                          <button key={f} type="button"
                            onClick={() => setSavedFamily(f)}
                            title={f === "all" ? "Every saved style"
                              : `Saved styles that run on ${familyName(f)}`}
                            style={{
                              height: 20, padding: `0 ${SPACE[10]}px`,
                              borderRadius: RADIUS.pill,
                              border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`,
                              background: on ? "var(--accentMut)" : "transparent",
                              color: on ? "var(--accent)" : "var(--textTer)",
                              fontFamily: FONT, fontSize: 9,
                              fontWeight: on ? W.nav : W.body,
                              letterSpacing: "0.04em", cursor: "pointer",
                              whiteSpace: "nowrap",
                            }}>
                            {f === "all" ? "All" : familyName(f)}
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {savedStyleGroups.map((group) => (
                  <Fragment key={group.family}>
                  {/* A breaker per model family, the family you are ON first
                      and said out loud. Eighteen flat rows gave no way to find
                      the MiniMax ones, and the model is what a saved style
                      actually switches - so the model is what the list is
                      organised by. Other families stay below rather than being
                      filtered away: picking a style IS how you change model,
                      so hiding them would be a shelf you can never leave. */}
                  {savedStyleGroups.length > 1 && (
                    <div style={{ display: "flex", alignItems: "center",
                                  gap: SPACE[8],
                                  padding: `${SPACE[8]}px ${SPACE[8]}px ${SPACE[4]}px`,
                                  fontSize: TYPE.micro, fontWeight: W.heading,
                                  letterSpacing: "0.08em", textTransform: "uppercase",
                                  color: group.current ? "var(--accent)" : "var(--textTer)" }}>
                      <span>{group.label}</span>
                      {group.current && (
                        <span style={{ fontSize: 9, letterSpacing: 0,
                                       textTransform: "none",
                                       color: "var(--textTer)" }}>
                          current model
                        </span>
                      )}
                      <span style={{ flex: 1, height: 1, marginLeft: SPACE[4],
                                     background: "var(--border)" }} />
                    </div>
                  )}
                  {group.items.map((saved) => {
                    // Under an identity source a style is pickable when its
                    // model can carry the identity patch (any Krea 2 build) -
                    // OR when it is MiniMax H3, which needs no patch: the
                    // anchor's photo rides H3's own reference input (9.67).
                    // The model rows have exempted H3 since 9.67; this shelf
                    // never did, so a character greyed out every H3 style -
                    // including Minimax Realism, the settled ref stack.
                    const meta = ((options && options.model_meta) || {})[saved.model] || {};
                    const identityOk = meta.family === "minimax_h3" ||
                      (meta.family === "krea2" &&
                       (meta.compatible_recipes || []).includes("identity_edit"));
                    const locked = hasIdentitySource && !identityOk;
                    return (
                    <Row key={saved.id} sel={opts.saved_style === saved.id}
                         disabled={!saved.available || locked}
                         title={locked
                           ? `${saved.name} runs on ${short(saved.model)}, which ` +
                             "cannot carry the identity patch (Krea 2 and MiniMax H3 only)"
                           : saved.available
                           ? `${saved.base_label} · ${short(saved.model)}`
                           : saved.missing.join("\n")}
                         onClick={() => { chooseSavedStyle(saved.id); }}>
                      <Palette size={12} weight="duotone" />
                      <span style={{ minWidth: 0, overflow: "hidden",
                                     textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {saved.name}
                      </span>
                      {/* The tag names the MODEL, not the lane. Picking a
                          saved style sets opts.model to the style's own build
                          (selectSavedStyle), so the model is the fact that
                          separates one row from the next - fourteen rows all
                          tagged "Realism" is what made the shelf unreadable. */}
                      <Tag title={saved.available
                             ? `${saved.base_label} · ${short(saved.model)}`
                             : saved.missing.join("\n")}>
                        {saved.available ? short(saved.model) : "unavailable"}
                      </Tag>
                      <button type="button" aria-label={`Edit ${saved.name}`}
                        title={`Edit ${saved.name}`}
                        onClick={(e) => { e.stopPropagation(); onEditStyle(saved.id); }}
                        style={{ flexShrink: 0, display: "inline-flex", padding: 2,
                                 border: "none", background: "transparent",
                                 color: "var(--textTer)", cursor: "pointer" }}>
                        <PencilSimple size={11} weight="duotone" />
                      </button>
                    </Row>
                    );
                  })}
                  </Fragment>
                  ))}
                  {!savedStyles.length && (
                    <div style={{ padding: `0 ${SPACE[8]}px ${SPACE[8]}px`,
                                  color: "var(--textTer)", fontSize: TYPE.label,
                                  lineHeight: 1.4 }}>
                      None yet. Tune a render until it looks right, then “save
                      current” keeps the model, LoRA stack and sampler under a
                      name of your own.
                    </div>
                  )}
                  {opts.saved_style && (
                    <Row onClick={() => chooseSavedStyle("")}>
                      <ArrowCounterClockwise size={12} weight="duotone" />
                      <span>back to built-in styles</span>
                    </Row>
                  )}
                  {/* The selected style's {slot} tokens as fields (9.77):
                      the formula is the style's, the fills are the shoot's.
                      Empty renders as the slot's default, so the placeholder
                      IS the empty state - no reset button, no hint essay. */}
                  {activeSavedStyle && Object.entries(activeSavedStyle.slots || {})
                    .map(([name, slot]) => (
                    <label key={name} style={{ display: "flex", flexDirection: "column",
                                               gap: SPACE[4],
                                               padding: `0 ${SPACE[8]}px ${SPACE[8]}px` }}>
                      <span style={{ fontSize: 10, color: "var(--textTer)",
                                     fontFamily: FONT, textTransform: "uppercase",
                                     letterSpacing: "0.08em" }}>
                        {(slot && slot.label) || name}
                      </span>
                      <input value={((opts.style_slots || {})[name]) || ""}
                             placeholder={(slot && slot.default) || ""}
                             onChange={(e) => setOpts({ style_slots:
                               { ...(opts.style_slots || {}), [name]: e.target.value } })}
                             style={{ width: "100%", height: 32, background: "var(--bg2)",
                                      border: "1px solid var(--border)",
                                      borderRadius: RADIUS.input, padding: `0 ${SPACE[10]}px`,
                                      fontSize: TYPE.ui, color: "var(--text)",
                                      fontFamily: FONT, outline: "none" }} />
                    </label>
                  ))}
                </>
              )}
              {!hasIdentitySource && !opts.saved_style && styleKey === "realism" && (
                <>
                  <div style={{ borderTop: "1px solid var(--border)",
                                margin: `${SPACE[8]}px 0` }} />
                  <div style={{ padding: `0 ${SPACE[8]}px ${SPACE[6]}px`,
                                fontSize: TYPE.micro, fontWeight: W.heading,
                                letterSpacing: "0.08em", textTransform: "uppercase",
                                color: "var(--textTer)" }}>
                    realism quality
                  </div>
                  <Row sel={quality === "standard"} onClick={() => chooseQuality("standard")}>
                    <Lightning size={12} weight="duotone" /> Standard
                    <Tag>single pass</Tag>
                  </Row>
                  <Row sel={quality === "refined"}
                       disabled={!refinedAvailable}
                       title={!recipeById(refinedRecipeId)?.available
                         ? (recipeById(refinedRecipeId)?.missing || []).join("\n")
                         : selectedModelMeta.family === "minimax_h3"
                           ? "2x latent refine in the model's own family\nlashes and pores at 3072x4096, and it repairs distant faces\n~3 min"
                           : opts.model && selectedModelMeta.family !== "krea2"
                             ? "Refined is available with Krea 2 models" : undefined}
                       onClick={() => chooseQuality("refined")}>
                    <Stack size={12} weight="duotone" /> Refined
                    <Tag>{!recipeById(refinedRecipeId)?.available ? "assets missing"
                      : refinedAvailable ? "two-pass finish" : "Krea 2 only"}</Tag>
                  </Row>
                </>
              )}
            </Pop>
          )}
        </div>

        {/* character anchor — dashed while empty, check once locked in */}
        <div style={{ position: "relative" }}>
          <PillBtn Icon={opts.character
                     ? <UserCircleCheck size={14} weight="duotone" />
                     : <UserCircleDashed size={14} weight="duotone" />}
                   label={opts.character
                     ? ((options && (options.characters || [])
                         .find(c => c.id === opts.character)?.name) || opts.character)
                     : "character"}
                   active={!!opts.character} onClick={() => open("char")}>
            <CaretDown size={11} weight="bold" style={{ opacity: 0.6 }} />
          </PillBtn>
          {pop === "char" && options && (
            <Pop title="character anchor" onClose={() => setPop(null)}>
              <div style={{ padding: `0 ${SPACE[8]}px ${SPACE[8]}px`, color: "var(--textTer)",
                            fontSize: TYPE.label, lineHeight: 1.4 }}>
                {identityAvailable
                  ? "Identity Edit needs a character with a reference image."
                  : "Identity Edit is unavailable until its missing assets are installed."}
              </div>
              {characterDeleteError && (
                <div role="alert" style={{ margin: `0 ${SPACE[8]}px ${SPACE[8]}px`,
                                           color: "#E3A7B0", fontSize: TYPE.label,
                                           lineHeight: 1.4 }}>
                  {characterDeleteError}
                </div>
              )}
              <Row sel={!opts.character} onClick={() =>
                { selectCharacter(""); setPop(null); }}>none (generic)</Row>
              {(options.characters || []).map((c) => {
                const reason = !identityAvailable
                  ? `Identity Edit unavailable${identityMissing ? `:\n${identityMissing}` : ""}`
                  : !c.has_ref ? "Reference image required for Identity Edit" : "";
                const deleting = deletingCharacter === c.id;
                const meta = [...[c.age, c.sex, c.race].filter(Boolean), "ref"].join(" · ");
                return (
                  <div key={c.id} style={{ display: "flex", alignItems: "center",
                                           gap: SPACE[4] }}>
                    <Row sel={opts.character === c.id} disabled={!!reason || deleting}
                         style={{ flex: 1, width: "auto", minWidth: 0, overflow: "hidden" }}
                         title={reason || `Use ${c.name} with Identity Edit`}
                         onClick={() => { selectCharacter(c.id); setPop(null); }}>
                      {/* The NAME is what the row is scanned for, so it is the
                          one thing that does not yield: both it and the meta
                          Tag could shrink, so a long meta squeezed "Zakra" down
                          to "Z...". The meta is the expendable half. maxWidth
                          keeps a pathological name from evicting it entirely. */}
                      <span style={{ flexShrink: 0, maxWidth: "55%",
                                     overflow: "hidden", textOverflow: "ellipsis",
                                     whiteSpace: "nowrap" }}>{c.name}</span>
                      <Tag title={meta}>{deleting ? "deleting…" : reason
                        ? (!identityAvailable ? "identity edit unavailable" : "reference required")
                        : meta}</Tag>
                    </Row>
                    <button type="button" disabled={!!deletingCharacter}
                      aria-label={`Edit ${c.name} character anchor`}
                      title={`Edit ${c.name}`}
                      onClick={() => { setPop(null); onEditCharacter && onEditCharacter(c.id); }}
                      style={{ width: 28, height: 28, flexShrink: 0, display: "inline-flex",
                               alignItems: "center", justifyContent: "center",
                               border: "none", borderRadius: RADIUS.control,
                               background: "transparent", color: "var(--textSec)",
                               cursor: deletingCharacter ? "default" : "pointer",
                               opacity: deletingCharacter ? 0.35 : 1 }}
                      onMouseEnter={(e) => { if (!deletingCharacter)
                        e.currentTarget.style.background = "var(--bg3)"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
                      <PencilSimple size={13} weight="duotone" />
                    </button>
                    <button type="button" disabled={!!deletingCharacter}
                      aria-label={`Delete ${c.name} character anchor`}
                      title={`Delete ${c.name} anchor — source image stays`}
                      onClick={() => removeCharacter(c)}
                      style={{ width: 28, height: 28, flexShrink: 0, display: "inline-flex",
                               alignItems: "center", justifyContent: "center",
                               border: "none", borderRadius: RADIUS.control,
                               background: "transparent", color: "var(--textSec)",
                               cursor: deletingCharacter ? "default" : "pointer",
                               opacity: deletingCharacter && !deleting ? 0.35 : 1 }}
                      onMouseEnter={(e) => { if (!deletingCharacter)
                        e.currentTarget.style.background = "var(--bg3)"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
                      <Trash size={13} weight="duotone" />
                    </button>
                  </div>
                );
              })}
              {/* 9.83: the per-render suppression for the anchor's wired
                  accessories. Shown only when the selected anchor HAS any -
                  a toggle that cannot change the render is not offered. The
                  switch is the control (role=switch is keyboard-reachable);
                  the row itself is a plain flex line, never a button
                  wrapping a button. */}
              {(() => {
                const sel = (options.characters || [])
                  .find((c) => c.id === opts.character);
                return sel && (sel.accessories || 0) > 0 ? (
                  <div style={{ display: "flex", alignItems: "center",
                                gap: SPACE[6],
                                padding: `${SPACE[4]}px ${SPACE[8]}px` }}>
                    <Switch on={opts.accessories !== false}
                      label={`wire ${sel.name}'s accessories`}
                      title={opts.accessories !== false
                        ? "wired into this render — switch off to leave them behind for this one"
                        : "off — the anchor keeps its list; this render wires the identity photo alone"}
                      onChange={(next) => setOpts({ accessories: next })} />
                    <span style={{ fontSize: TYPE.ui, color: "var(--textSec)" }}>
                      accessories
                    </span>
                    <Tag>{opts.accessories !== false
                      ? `${sel.accessories} wired` : "off"}</Tag>
                    <InfoTip size={11} text={"The anchor's accessory references wire "
                      + "beside its identity photo on the MiniMax H3 lanes. Every "
                      + "wired reference rides every sampling step, so off is the "
                      + "fast render. Per-accessory switches live on the character "
                      + "page (the pencil beside each anchor)."} />
                  </div>
                ) : null;
              })()}
              <div style={{ borderTop: "1px solid var(--border)", margin: `${SPACE[10]}px 0` }} />
              <Row onClick={() => { setPop(null); onNewCharacter && onNewCharacter(); }}>
                <UserCirclePlus size={12} weight="duotone" /> new anchor…
              </Row>
            </Pop>
          )}
        </div>

        {/* size */}
        <div style={{ position: "relative" }}>
          <PillBtn Icon={<ImageSquare size={14} weight="duotone" />}
                   label={(opts.aspect ? opts.aspect.split(" ")[0] : "size") +
                          (opts.mp ? " · " + opts.mp + "MP" : "")}
                   active={!!(opts.aspect || opts.mp)} onClick={() => open("size")}>
            <CaretDown size={11} weight="bold" style={{ opacity: 0.6 }} />
          </PillBtn>
          {pop === "size" && options && (
            <Pop title="canvas" onClose={() => setPop(null)} wide>
              {/* Two different questions, so two labelled groups with a rule
                  between them. Rendered as one undifferentiated field of pills
                  they read as a pile: an aspect and a megapixel count looked
                  like the same kind of choice, and neither said what it was. */}
              <SizeGroup label="Aspect ratio"
                         value={opts.aspect ? aspectName(opts.aspect) : "auto"}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)",
                              gap: SPACE[6] }}>
                  {options.aspects.map((a) => (
                    <SizeChip key={a} on={opts.aspect === a}
                      title={aspectName(a)}
                      onClick={() => setOpts({ aspect: opts.aspect === a ? "" : a })}>
                      {/* The shape is the glanceable half, the numbers the
                          precise one - at this width both fit, but if room
                          ran short the shape is what would yield. The chip's
                          currentColor carries it, lit or not. */}
                      <AspectShape ratio={a} />
                      <span style={{ marginLeft: SPACE[4] }}>{a.split(" ")[0]}</span>
                    </SizeChip>
                  ))}
                </div>
              </SizeGroup>

              <div style={{ height: 1, background: "var(--border)",
                            margin: `${SPACE[12]}px 0` }} />

              <SizeGroup label="Megapixels"
                         value={opts.mp ? `${opts.mp} MP` : "auto"}>
                {/* Eight values, four columns: two full rows, never an orphan.
                    Anything off the ladder gets the full-width slot below
                    instead of being tacked on as a ninth cell. */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)",
                              gap: SPACE[6] }}>
                  {[null, ...MP_LADDER].map((v) => {
                    const capped = v !== null && mpCap && v > mpCap;
                    return (
                    <SizeChip key={String(v)} on={opts.mp === v}
                      disabled={!!capped}
                      title={capped ? mpCapTitle
                                    : v === null ? "Let the recipe choose the canvas"
                                                 : `${v} megapixels`}
                      onClick={() => setOpts({ mp: v })}>
                      {v === null ? "auto" : <>{v}<Unit>MP</Unit></>}
                    </SizeChip>
                    );
                  })}
                </div>
                {customMp !== null && (
                  <SizeChip on={opts.mp === customMp} wide
                    title={`${customMp} megapixels`}
                    onClick={() => setOpts({ mp: customMp })}>
                    {customMp}<Unit>MP</Unit>
                    <span style={{ marginLeft: SPACE[8], fontSize: TYPE.micro,
                                   opacity: 0.55 }}>
                      {activeSavedStyle && activeSavedStyle.mp === customMp
                        ? `from ${activeSavedStyle.name}` : "custom"}
                    </span>
                  </SizeChip>
                )}
              </SizeGroup>

              {/* What those two numbers actually produce. Mirrors the server's
                  dims_for() exactly, including the multiple-of-16 rounding —
                  without it the two rows above are abstractions and you only
                  learn the real canvas after a render. */}
              <div style={{ marginTop: SPACE[12], paddingTop: SPACE[8],
                            borderTop: "1px solid var(--border)",
                            display: "flex", alignItems: "baseline", gap: SPACE[8],
                            fontSize: TYPE.label, color: "var(--textTer)" }}>
                <span>renders at</span>
                <span style={{ marginLeft: "auto", fontFamily: MONO,
                               color: canvasDims ? "var(--textSec)" : "var(--textTer)" }}>
                  {canvasDims ? `${canvasDims[0]} × ${canvasDims[1]} px`
                              : "the recipe’s own canvas"}
                </span>
              </div>
            </Pop>
          )}
        </div>

        {/* The frozen-seed indicator moved to the switch row beside the
            sparkle (Jesse, 2026-08-18): same unlock, hover shows the seed,
            and the pill row keeps its space. */}
      </div>

      <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }}
             onChange={(e) => {
               doUpload(e.target.files[0], uploadKindRef.current);
               e.target.value = "";
             }} />
      <input ref={styleImageRef} type="file" accept="image/*" style={{ display: "none" }}
             onChange={(e) => {
               doStyleFromImage(e.target.files[0]);
               e.target.value = "";
             }} />
    </>
  );

  // Declared below the return deliberately: function declarations hoist, so the
  // row can render the attach control FIRST while its popover - by far the
  // longest markup in this component - stays out of the way of the four pills
  // that follow it. Called, not mounted as <RefControl/>: a component redefined
  // every render would remount the popover on every keystroke.
  function refControl() {
    return (
        <div style={{ position: "relative" }}>
          <RoundBtn Icon={opts.editSource
                      ? <PencilSimple size={14} weight="duotone" />
                      : <Plus size={15} weight="bold" />}
                    badge={!opts.editSource && opts.refs.length
                      ? opts.refs.length : null}
                    title={opts.editSource
                      ? `Next message edits ${short(opts.editSource)}`
                      : opts.refs.length
                        ? `${opts.refs.length} reference image${
                            opts.refs.length > 1 ? "s" : ""} attached`
                        : "Attach a reference image"}
                    active={!!opts.editSource || opts.refs.length > 0}
                    onClick={() => open("ref")} />
          {pop === "ref" && options && (
            <Pop title="reference image" onClose={() => setPop(null)} xl>
              <div role="group" aria-label="Reference type"
                   style={{ display: "flex", gap: SPACE[6], marginBottom: SPACE[10] }}>
                {PICK_KINDS.map((k) => (
                  <button key={k.key} type="button"
                    disabled={k.key === "identity" && !identityAvailable}
                    aria-pressed={refKind === k.key}
                    title={k.key === "identity" && !identityAvailable
                      ? `Identity Edit unavailable${identityMissing ? `:\n${identityMissing}` : ""}`
                      : undefined}
                    onClick={() => { setRefKind(k.key); setRefError(null); }}
                    style={{
                      flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
                      gap: 3, padding: `${SPACE[6]}px 2px`, border: "1px solid",
                      borderRadius: RADIUS.input,
                      cursor: k.key === "identity" && !identityAvailable ? "default" : "pointer",
                      opacity: k.key === "identity" && !identityAvailable ? 0.45 : 1,
                      fontSize: 10,
                      borderColor: refKind === k.key ? "var(--accent)" : "var(--border)",
                      background: refKind === k.key ? "var(--accentMut)" : "transparent",
                      color: refKind === k.key ? "var(--accent)" : "var(--textTer)",
                    }}>
                    <k.Icon size={13} weight="duotone" />{k.label}
                  </button>
                ))}
              </div>
              <Row disabled={uploading}
                   onClick={() => {
                     uploadKindRef.current = refKind;
                     fileRef.current?.click();
                   }}
                   style={{ marginBottom: SPACE[12] }}>
                <ImageSquare size={12} weight="duotone" />
                {uploading ? "uploading…" : "upload from device"}
              </Row>
              {refError && (
                <div role="alert" style={{ margin: `0 ${SPACE[4]}px ${SPACE[10]}px`,
                                            color: "#E3A7B0", fontSize: TYPE.label,
                                            lineHeight: 1.4 }}>
                  {refError}
                </div>
              )}
              {/* What is attached RIGHT NOW, stated rather than hidden as one
                  highlighted tile somewhere down a grid of a hundred. */}
              {(attachedNow.length > 0) && (
                <div role="list" aria-label="Attached now"
                     style={{ display: "flex", flexWrap: "wrap", gap: SPACE[4],
                              margin: `0 ${SPACE[4]}px ${SPACE[8]}px`,
                              paddingBottom: SPACE[8],
                              borderBottom: "1px solid var(--border)" }}>
                  <span style={{ width: "100%", color: "var(--textTer)",
                                 fontSize: TYPE.label, marginBottom: 2 }}>
                    attached now
                  </span>
                  {attachedNow.map((item) => {
                    const ItemIcon = REF_ICON[item.kind] || ImageSquare;
                    return (
                      <span key={`${item.kind}:${item.file}`} role="listitem"
                        title={`${item.kind} · ${item.file}`}
                        style={{ display: "inline-flex", alignItems: "center", gap: 5,
                                 maxWidth: "100%", height: 26, paddingRight: 3,
                                 paddingLeft: 3, border: "1px solid var(--accent)",
                                 borderRadius: RADIUS.pill, background: "var(--accentMut)",
                                 color: "var(--accent)", fontSize: 10 }}>
                        <img src={inputImgUrl({ name: item.file })} alt="" loading="lazy"
                             style={{ width: 20, height: 20, objectFit: "cover",
                                      borderRadius: "50%" }} />
                        <ItemIcon size={11} weight="duotone" aria-hidden="true" />
                        <span style={{ maxWidth: 150, overflow: "hidden",
                                       textOverflow: "ellipsis", whiteSpace: "nowrap",
                                       fontFamily: "ui-monospace, Consolas, monospace" }}>
                          {short(item.file) || item.file}
                        </span>
                        <button type="button" aria-label={`Detach ${item.file}`}
                          onClick={() => detachRef(item)}
                          style={{ display: "inline-flex", alignItems: "center",
                                   justifyContent: "center", width: 18, height: 18,
                                   border: "none", borderRadius: "50%",
                                   background: "transparent", color: "inherit",
                                   cursor: "pointer", padding: 0 }}>
                          <X size={10} weight="bold" />
                        </button>
                      </span>
                    );
                  })}
                </div>
              )}
              <FilterInput value={filter} onChange={setFilter}
                           placeholder="filter input images by name…" />
              <div style={{ display: "flex", alignItems: "center", gap: SPACE[4],
                            margin: `0 ${SPACE[4]}px ${SPACE[8]}px`,
                            color: "var(--textTer)", fontSize: TYPE.label }}>
                <span>ComfyUI/input</span>
                <span style={{ fontFamily: "ui-monospace, Consolas, monospace",
                               fontSize: 9 }}>
                  {filter.trim() ? `${inputList.length} of ${inputAll.length}`
                                 : inputList.length}
                </span>
                <span role="group" aria-label="Sort input images"
                      style={{ marginLeft: "auto", display: "inline-flex", gap: 2 }}>
                  {REF_SORTS.map((s) => (
                    <button key={s.key} type="button" aria-pressed={refSort === s.key}
                      onClick={() => setRefSort(s.key)}
                      style={{ height: 20, padding: `0 ${SPACE[6]}px`,
                               border: "1px solid",
                               borderColor: refSort === s.key ? "var(--accent)" : "var(--border)",
                               borderRadius: RADIUS.pill, cursor: "pointer", fontSize: 9,
                               fontFamily: FONT,
                               background: refSort === s.key ? "var(--accentMut)" : "transparent",
                               color: refSort === s.key ? "var(--accent)" : "var(--textTer)" }}>
                      {s.label}
                    </button>
                  ))}
                </span>
              </div>
              {inputList.length ? (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                              gap: SPACE[6] }}>
                  {inputList.map((image) => {
                    const editMode = refKind === "edit";
                    const attachKind = REF_KINDS.some((k) => k.key === image.kind)
                      ? image.kind : refKind;
                    return (
                      <ReferenceImageCard key={image.name} image={image} kind={refKind}
                        disabled={uploading}
                        attached={editMode
                          ? opts.editSource === image.name
                          : (opts.refs || []).some((ref) =>
                              ref.kind === attachKind && ref.file === image.name)}
                        // The card offers its SAVED tag when it has one, which is
                        // right for a ref and wrong here: an edit pick names the
                        // source, so the tag is ignored rather than obeyed.
                        onPick={(k) => addRef(editMode ? "edit" : k, image.name)}
                        onRetag={doRetag} />
                    );
                  })}
                </div>
              ) : (
                <div style={{ padding: SPACE[16], textAlign: "center",
                              color: "var(--textTer)", fontSize: TYPE.ui }}>
                  No input images yet. Upload one above.
                </div>
              )}
            </Pop>
          )}
        </div>
    );
  }
};
