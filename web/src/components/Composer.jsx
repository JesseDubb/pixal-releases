// Composer.jsx — the options bar inside the chat composer box.
// Docked-widget IA, ported from an earlier chat widget of mine: pills
// bottom-left (model / style / character / size / +ref), with compact
// attached-reference tabs beside the composer. The ordered LoRA chain lives
// in its execution rail (or in-flow on narrow layouts). Phosphor duotone per
// the design system; popovers open upward (composer sits at the page bottom).
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
// Character iconography is the Phosphor UserCircle family, by state:
// dashed = empty/draft, check = locked in, plus = create, plain = the
// automatic identity mode. UserFocus survives ONLY as the identity-REF glyph
// (a face-lock on a photo, not a character entity).
import {
  ArrowCounterClockwise, CaretDown, CaretLeft, CaretRight, CaretUp, Cube, DotsSixVertical,
  FilmSlate, ImageSquare, Lightning, LockSimple, Monitor, Palette, PencilSimple, Plus,
  Sparkle, Stack, TagSimple, Trash, TShirt, UserCircle, UserCircleCheck,
  UserCircleDashed, UserCirclePlus, UserFocus, X,
} from "@phosphor-icons/react";
import { FONT, W, TYPE, SPACE, RADIUS, MOTION, SHADOW } from "../lib/design-tokens.js";
import { familyName, variantName } from "../lib/names.js";
import { inputImages, inputImgUrl, setInputRefType, upload } from "../transport.js";

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

  const panel = (
    <div ref={ref} className={rail ? undefined : "px-scroll"} style={{
      position: rail ? "fixed" : "absolute", zIndex: rail ? 45 : 25,
      ...(rail ? (railGeometry || {}) : {
        ...(down ? { top: "calc(100% + 6px)" } : { bottom: "calc(100% + 6px)" }),
        ...(alignRight ? { right: 0 } : { left: 0 }),
      }),
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
        margin: `2px 4px ${SPACE[8]}px`, flexShrink: 0,
        fontSize: TYPE.micro, fontWeight: W.heading,
        letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--textTer)",
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

const Row = ({ sel, onClick, children, style, disabled = false, title }) => (
  <button
    type="button"
    title={title}
    disabled={disabled}
    onClick={disabled ? undefined : onClick}
    style={{
      display: "flex", alignItems: "center", gap: SPACE[8], width: "100%",
      padding: `${SPACE[6]}px ${SPACE[8]}px`, border: "none", borderRadius: RADIUS.input,
      background: "transparent", color: sel ? "var(--accent)" : "var(--textSec)",
      fontFamily: FONT, fontSize: TYPE.ui, textAlign: "left",
      cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.62 : 1,
      transition: `background ${MOTION.hover}`, ...style,
    }}
    onMouseEnter={(e) => { if (!disabled) e.currentTarget.style.background = "var(--bg3)"; }}
    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
  >
    {children}
  </button>
);

const Tag = ({ children }) => (
  <span style={{ marginLeft: "auto", fontFamily: "ui-monospace, Consolas, monospace",
                 fontSize: 9, color: "var(--textTer)", flexShrink: 0 }}>{children}</span>
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

const SizeChip = ({ on, wide, title, onClick, children }) => (
  <button type="button" title={title} onClick={onClick}
    style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      height: 32, width: "100%", ...(wide ? { marginTop: SPACE[6] } : null),
      border: "1px solid", borderRadius: RADIUS.input,
      borderColor: on ? "var(--accent)" : "var(--border)",
      background: on ? "var(--accentMut)" : "transparent",
      color: on ? "var(--accent)" : "var(--textSec)",
      fontFamily: FONT, fontSize: TYPE.ui, whiteSpace: "nowrap",
      cursor: "pointer", transition: `border-color ${MOTION.hover}`,
    }}
    onMouseEnter={(e) => { if (!on) e.currentTarget.style.borderColor = "var(--borderHov)"; }}
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

const FilterInput = ({ value, onChange, placeholder }) => (
  <input
    value={value}
    onChange={(e) => onChange(e.target.value)}
    placeholder={placeholder}
    style={{
      width: "100%", height: 32, background: "var(--bg2)",
      border: "1px solid var(--border)", borderRadius: RADIUS.input,
      padding: `0 ${SPACE[10]}px`, fontSize: TYPE.ui, color: "var(--text)",
      fontFamily: FONT, outline: "none", marginBottom: SPACE[6],
    }}
  />
);

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

// A LoRA is chosen by its preview, not its filename - lora-manager gives us a
// thumbnail for nearly all of them. A grid of those shows ~15 at a glance where
// the old text rows showed 6, which is the whole difference between browsing a
// collection and scrolling one.
const LoraTile = ({ lora, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    title={(lora.words || []).join(", ") || lora.name}
    style={{
      display: "flex", flexDirection: "column", gap: 4, padding: 4, minWidth: 0,
      border: "1px solid var(--border)", borderRadius: RADIUS.input,
      background: "var(--bg2)", color: "var(--textSec)", fontFamily: FONT,
      fontSize: 10, textAlign: "left", cursor: "pointer",
      contentVisibility: "auto", containIntrinsicSize: "120px 150px",
      transition: `border-color ${MOTION.hover}`,
    }}
    onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; }}
    onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; }}
  >
    <LoraThumb src={lora.thumb} fill />
    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                   lineHeight: 1.3 }}>
      {lora.title || lora.short || lora.name}
    </span>
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
          label={`identity · ${(options && (options.characters || [])
            .find((c) => c.id === opts.character)?.name) || opts.character}`}
          image={`/api/characters/${encodeURIComponent(opts.character)}/ref-thumb`}
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

const loraMatchesProfile = (lora, profile) => !!lora?.supported &&
  lora.family === profile.family &&
  (profile.family !== "zimage" || !["base", "turbo"].includes(profile.variant) ||
    lora.variant === "any" || lora.variant === profile.variant);

const recipeStageLabel = (stage, meta) => stage?.title || meta?.title ||
  (stage?.slot ? stage.slot.replaceAll("_", " ") : short(stage?.name));

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

const LoraToggle = ({ checked, disabled = false, label, onChange, title: hint }) => {
  const action = checked ? "Disable" : "Enable";
  const title = hint
    || (disabled ? `${label} is required by this recipe` : `${action} ${label}`);
  return (
    <button type="button" role="switch" aria-checked={checked}
      aria-label={`${action} ${label}`} title={title} disabled={disabled}
      onClick={onChange}
      style={{ position: "relative", width: 30, height: 17, flexShrink: 0, padding: 0,
               border: `1px solid ${checked ? "var(--accent)" : "var(--borderHov)"}`,
               borderRadius: 999, background: checked ? "var(--accentMut)" : "var(--bg1)",
               cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.5 : 1,
               transition: `background ${MOTION.hover}, border-color ${MOTION.hover}` }}>
      <span aria-hidden="true" style={{ position: "absolute", top: 2,
        left: checked ? 15 : 2, width: 11, height: 11, borderRadius: "50%",
        background: checked ? "var(--accent)" : "var(--textMut)",
        boxShadow: "0 1px 2px rgba(0,0,0,0.35)",
        transition: `left ${MOTION.hover}, background ${MOTION.hover}` }} />
    </button>
  );
};

const LORA_RAIL_COLLAPSED_KEY = "pixal.loraRail.collapsed.v1";

export const LoraChain = ({ opts, options, recipeId, plan, setEntries, resetPlan,
                            setCoreEnabled, rail = false }) => {
  const [adding, setAdding] = useState(false);
  const [filter, setFilter] = useState("");
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
  const inactiveStages = editableStages.filter((stage) => !activeNames.has(stage.name));
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
  const installedAll = (options?.loras || []).filter((lora) =>
    !activeNames.has(lora.name) && !recipeNames.has(lora.name) &&
    loraMatchesProfile(lora, profile) &&
    (!filter || `${lora.title || ""} ${lora.short || ""} ${lora.name}`
      .toLowerCase().includes(filter.toLowerCase())));
  // Cap what is rendered, but say so - a silent truncation reads as "that is
  // everything you have installed", which it is not.
  const installedTotal = installedAll.length;
  const installed = installedAll.slice(0, 120);

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

  const rowBase = {
    display: "grid", gridTemplateColumns: "24px minmax(0,1fr) 56px auto",
    alignItems: "center", gap: SPACE[10], minHeight: 52,
    padding: `${SPACE[8]}px ${SPACE[10]}px`, borderRadius: RADIUS.inner,
    background: "var(--bg2)", border: "1px solid var(--border)",
  };
  let sequence = 0;
  const addSearch = (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 58px",
                  gap: SPACE[6], alignItems: "start" }}>
      <FilterInput value={filter} onChange={setFilter}
                   placeholder="filter compatible installed LoRAs…" />
      <input value={strength} onChange={(e) => setStrength(e.target.value)}
        aria-label="new LoRA strength" inputMode="decimal"
        style={{ width: "100%", height: 32, background: "var(--bg2)",
                 border: "1px solid var(--border)", borderRadius: RADIUS.input,
                 padding: "0 6px", fontFamily: "ui-monospace, Consolas, monospace",
                 fontSize: 10, color: "var(--text)", outline: "none",
                 textAlign: "center" }} />
    </div>
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
        <Pop title="add to editable chain" onClose={() => setAdding(false)} xl
             down={rail} alignRight={rail} rail={rail}
             anchorRef={addAnchorRef} boundsRef={sectionRef}>
          <div style={{ padding: `0 ${SPACE[8]}px ${SPACE[8]}px`,
                        color: "var(--textTer)", fontSize: TYPE.label,
                        lineHeight: 1.4 }}>
            Showing only {profileLabel} LoRAs compatible with the current model profile.
          </div>
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
            <div style={{ borderTop: "1px solid var(--border)", margin: `${SPACE[6]}px 0` }} />
          )}
          {!rail && addSearch}
          {installed.length > 0 && (
            <div style={{ padding: `0 ${SPACE[4]}px ${SPACE[6]}px`,
                          color: "var(--textTer)", fontSize: TYPE.label }}>
              {installedTotal} {profileLabel} LoRA{installedTotal === 1 ? "" : "s"}
              {filter ? ` match “${filter.trim()}”` : " available"}
              {installed.length < installedTotal
                ? ` · showing the first ${installed.length}, search to narrow` : ""}
            </div>
          )}
          <div style={{ display: "grid", gap: SPACE[6],
                        gridTemplateColumns: "repeat(auto-fill, minmax(78px, 1fr))" }}>
            {installed.map((lora) => (
              <LoraTile key={lora.name} lora={lora}
                        onClick={() => addInstalled(lora)} />
            ))}
          </div>
          {!inactiveStages.length && !installed.length && (
            <Row disabled>no installed {profileLabel} LoRAs match this profile</Row>
          )}
        </Pop>
      )}
    </div>
  );

  return (
    <section ref={sectionRef} aria-label={`${recipe.label || recipe.id} LoRA chain`} style={{
      marginBottom: rail ? 0 : SPACE[8], minHeight: 0,
      display: "flex", flexDirection: "column", height: rail ? "100%" : undefined,
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
      ) : (
        <>

      {rail && (
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
          return (
            <div key={`core-${stage.slot}`}
                 style={{ ...rowBase, opacity: on ? 0.78 : 0.5,
                          background: on ? undefined : "transparent" }}>
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
                  {on ? " · core" : " · bypassed"}
                </div>
              </div>
              <span style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 10,
                             color: "var(--textTer)" }}>{planNumber(stage.strength)}</span>
              <LoraToggle checked={on} disabled={!setCoreEnabled} label={label}
                          title={on
                            ? `Bypass ${label} — it is a core ${recipe?.label || "recipe"} stage, so this is an override`
                            : `Restore ${label} to the core chain`}
                          onChange={() => setCoreEnabled && setCoreEnabled(stage.slot, !on)} />
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
                <input type="number" step="0.05" value={entry.strength}
                  aria-label={`${stage ? recipeStageLabel(stage, meta)
                    : (entry.title || short(name))} strength`}
                  onChange={(event) => changeStrength(index, event.target.value)}
                  style={{ width: 56, height: 30, background: "var(--bg1)",
                           border: "1px solid var(--border)", borderRadius: RADIUS.input,
                           padding: "0 5px", fontFamily: "ui-monospace, Consolas, monospace",
                           fontSize: 10, color: "var(--text)", textAlign: "center",
                           outline: "none" }} />
              ) : (
                <span style={{ width: 56, textAlign: "center",
                               fontFamily: "ui-monospace, Consolas, monospace", fontSize: 10,
                               color: "var(--textTer)" }}>{entry.strength}</span>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: SPACE[6] }}>
                <LoraToggle checked={enabled} disabled={!removable} label={label}
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
                              selectSavedStyle, onNewStyle, onEditStyle,
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
  const identityBlocked = (m) => hasIdentitySource &&
    !(m.family === "krea2" && (m.compatible_recipes || []).includes("identity_edit"));
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
  const canvasDims = opts.aspect && opts.mp ? dimsFor(opts.aspect, Number(opts.mp)) : null;
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
    const compatible = selectedModelMeta.compatible_recipes || [];
    return style === "realism"
      ? compatible.some((id) => ["realism", "realism_ii", "zimage"].includes(id))
      : compatible.includes(style);
  };
  const refinedAvailable = !!recipeById("realism_ii")?.available &&
    (!opts.model || selectedModelMeta.family === "krea2");

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
    if (!m.supported || identityBlocked(m)) return;
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
      if (!identityBlocked(m)) group.pickable += 1;
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
          Identity Edit runs on Krea 2. Other families stay listed but are greyed
          until you clear the character or identity reference.
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
        return (
          <Row key={n} sel={opts.model === n} disabled={blocked}
               title={blocked
                 ? `${n}\n\nIdentity Edit runs on Krea 2. Clear the character or identity reference to pick this model.`
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
                    : "Choose the look; Pixal selects the matching execution profile."}
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
                    <button type="button" onClick={onNewStyle}
                      title="Save the current model, LoRA stack and sampler as a style"
                      style={{ marginLeft: "auto", display: "inline-flex",
                               alignItems: "center", gap: SPACE[4], height: 20,
                               padding: `0 ${SPACE[6]}px`, border: "none",
                               background: "transparent", color: "var(--accent)",
                               fontFamily: FONT, fontSize: TYPE.label,
                               textTransform: "none", letterSpacing: 0,
                               cursor: "pointer" }}>
                      <Plus size={10} weight="bold" /> save current
                    </button>
                  </div>
                  {savedStyles.map((saved) => {
                    // Under an identity source a style is pickable only when
                    // its model can carry the identity patch (any Krea 2
                    // build); other bases stay visible but honest about why.
                    const meta = ((options && options.model_meta) || {})[saved.model] || {};
                    const identityOk = meta.family === "krea2" &&
                      (meta.compatible_recipes || []).includes("identity_edit");
                    const locked = hasIdentitySource && !identityOk;
                    return (
                    <Row key={saved.id} sel={opts.saved_style === saved.id}
                         disabled={!saved.available || locked}
                         title={locked
                           ? `${saved.name} runs on ${short(saved.model)}, which ` +
                             "cannot carry the identity patch (Krea 2 only)"
                           : saved.available
                           ? `${saved.base_label} · ${short(saved.model)}`
                           : saved.missing.join("\n")}
                         onClick={() => { chooseSavedStyle(saved.id); }}>
                      <Palette size={12} weight="duotone" />
                      <span style={{ minWidth: 0, overflow: "hidden",
                                     textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {saved.name}
                      </span>
                      <Tag>{saved.available ? saved.base_label : "unavailable"}</Tag>
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
                       title={!recipeById("realism_ii")?.available
                         ? (recipeById("realism_ii")?.missing || []).join("\n")
                         : opts.model && selectedModelMeta.family !== "krea2"
                           ? "Refined is available with Krea 2 models" : undefined}
                       onClick={() => chooseQuality("refined")}>
                    <Stack size={12} weight="duotone" /> Refined
                    <Tag>{!recipeById("realism_ii")?.available ? "assets missing"
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
                return (
                  <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 2 }}>
                    <Row sel={opts.character === c.id} disabled={!!reason || deleting}
                         style={{ flex: 1, width: "auto", minWidth: 0 }}
                         title={reason || `Use ${c.name} with Identity Edit`}
                         onClick={() => { selectCharacter(c.id); setPop(null); }}>
                      {c.name}
                      <Tag>{deleting ? "deleting…" : reason
                        ? (!identityAvailable ? "identity edit unavailable" : "reference required")
                        : [...[c.age, c.sex, c.race].filter(Boolean), "ref"].join(" · ")}</Tag>
                    </Row>
                    <button type="button" disabled={!!deletingCharacter}
                      aria-label={`Edit ${c.name} character anchor`}
                      title={`Edit ${c.name}`}
                      onClick={() => { setPop(null); onEditCharacter && onEditCharacter(c.id); }}
                      style={{ width: 28, height: 28, flexShrink: 0, display: "inline-flex",
                               alignItems: "center", justifyContent: "center",
                               border: "none", borderRadius: RADIUS.control,
                               background: "transparent", color: "var(--textTer)",
                               cursor: deletingCharacter ? "default" : "pointer",
                               opacity: deletingCharacter ? 0.35 : 1 }}>
                      <PencilSimple size={13} weight="duotone" />
                    </button>
                    <button type="button" disabled={!!deletingCharacter}
                      aria-label={`Delete ${c.name} character anchor`}
                      title={`Delete ${c.name} anchor — source image stays`}
                      onClick={() => removeCharacter(c)}
                      style={{ width: 28, height: 28, flexShrink: 0, display: "inline-flex",
                               alignItems: "center", justifyContent: "center",
                               border: "none", borderRadius: RADIUS.control,
                               background: "transparent", color: "var(--textTer)",
                               cursor: deletingCharacter ? "default" : "pointer",
                               opacity: deletingCharacter && !deleting ? 0.35 : 1 }}>
                      <Trash size={13} weight="duotone" />
                    </button>
                  </div>
                );
              })}
              <div style={{ borderTop: "1px solid var(--border)", margin: `${SPACE[6]}px 0` }} />
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
                      {a.split(" ")[0]}
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
                  {[null, ...MP_LADDER].map((v) => (
                    <SizeChip key={String(v)} on={opts.mp === v}
                      title={v === null ? "Let the recipe choose the canvas"
                                        : `${v} megapixels`}
                      onClick={() => setOpts({ mp: v })}>
                      {v === null ? "auto" : <>{v}<Unit>MP</Unit></>}
                    </SizeChip>
                  ))}
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
