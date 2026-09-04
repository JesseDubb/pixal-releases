// SegmentedControl.jsx — the ONE segmented control in Pixal (brief 9.23b).
// Three file-local copies (a settings radio row, the Animate dialog's own,
// and a grid switch in the composer) collapsed into this single component
// with two declared variants. A segmented control is for 2–4 short,
// known-in-advance options (DESIGN.md §3); anything longer wants a picker.
//
// variant="flex" (default) — equal segments in one bordered capsule that
//   FILL a fixed width: settings rows, dialog rows. flex:1 + minWidth:0 lets
//   a segment shrink below its own label, so the clip pair is NOT optional
//   (9.21: a shrink rule without a clip rule painted one label over the
//   next), and the composed title keeps the full label in the tooltip.
// variant="pill" (brief 10.0) — THE PILL SELECTOR of the settings control
//   family: options that HUG their label (3px 11px) on a bg3 track, idle ink
//   textSec, the active option full accent with accentInk text — the
//   full-intensity register of the panel's one color story. It sits on a
//   setting row's right rail at natural width, where flex's equal-segment
//   fill would be the wrong shape; there is no sliding indicator because
//   unequal option widths break the 1/n translate trick (the mockup's
//   active state is the option's own background).
// variant="grid" — equal columns that CANNOT shrink below their own label
//   (grid items carry implicit min-width:auto — DESIGN.md's measured proof).
//   Reach for it for a two- or three-option switch whose labels must never
//   clip. Descends from Lumen's segmented toggle (desklight:
//   apps/backoffice/src/components/ui/) — accent-keyed borders and
//   RADIUS.input, not the capsule's bg4 fill. `fill` and option
//   `buttonProps` were carried across from there 2026-08-23; raise any
//   change to this variant back against Lumen so the two do not drift.
//
// options — [{ v, label, chip?, Icon?, disabled?, title?, buttonProps? }].
//   ONE key: `v`. The grid original's `value` key is gone; there is no shim.
// chip — a scale factor ("2×", "4×") rendered as the little Chip badge after
//   the label, never written into the label as prose (Jesse, 2026-09-01).
//   It joins the composed tooltip so the full name survives there.
// title — composed: `label — title` when a distinct title exists, else the
//   title, else the label itself. The full label ALWAYS survives in the
//   tooltip, which is what makes flex clipping honest.
// Icon — the icon contract is { size, weight, active }: phosphor icons
//   consume `weight="duotone"`; Pixal's BrandMarks consume `active` (brand
//   colour only on the selected segment). Each ignores what it does not
//   know — a phosphor icon forwards unknown props to its svg root, where
//   `active` sits inert, and the marks destructure only what they use.
// disabled — first-class in BOTH variants (the grid original had no way to
//   disable an option). Lumen's escape hatch survives too: buttonProps
//   spreads after the built-ins, so it wins.
// size — "md" (default) | "sm". fill — grid only: solid accent active state.
// Radio semantics throughout: radiogroup / radio / aria-checked, and the
// group gets its accessible name from ariaLabel (DESIGN.md §6).

import { FONT, W, TYPE, SPACE, RADIUS, HEIGHT, MOTION } from "./design-tokens.js";
import { Chip } from "./Chip.jsx";
// The pill selector's track (brief 10.0, the mockup's .seg): bg3 with a
// hairline border, 2px padding and gap, pill radius. Module-level so the
// spec has one name; options get theirs in the map below (pillStyle).
// The track is a rail passenger, so it is HEIGHT.rail outside to outside
// and its options are that less the border and padding (1 + 2 each side).
// Fixed, not content-sized: a track that took its height from its label's
// line box was 25-26 depending on the font that loaded, and sat beside
// 24px value pills on the same rail (2026-09-04).
const PILL_TRACK = {
  display: "flex", background: "var(--bg3)", boxSizing: "border-box",
  border: "1px solid var(--border)", borderRadius: RADIUS.pill,
  height: HEIGHT.rail, padding: 2, gap: 2,
};
const PILL_OPTION_H = HEIGHT.rail - 6;

export const SegmentedControl = ({
  options, value, onChange, ariaLabel,
  variant = "flex", size = "md", fill = false, className, style,
}) => {
  const grid = variant === "grid";
  const pill = variant === "pill";
  // The flex capsule's active state is ONE pill that slides between equal
  // segments (transitions.dev "tabs sliding" on MOTION.state; Jesse's
  // reference is Wealthsimple's notification toggle, 2026-08-25). Equal
  // segments mean no measuring: the pill is 1/n wide and translates by
  // whole segment widths - a transform, so it never repaints the track.
  const activeIndex = Math.max(0, options.findIndex((o) => o.v === value));
  const pad = 3;
  return (
    <div role="radiogroup" aria-label={ariaLabel} className={className}
      style={grid ? {
        display: "grid",
        gridTemplateColumns: `repeat(${options.length}, 1fr)`,
        gap: SPACE[4],
        ...style,
      } : pill ? {
        ...PILL_TRACK, ...style,
      } : {
        // The box is the segments' own: 1px border + 3px padding around a
        // row the 8px vertical segment padding makes 32 - 40 outside to
        // outside at md, the box SegGhost in Settings is built to.
        position: "relative", display: "flex", background: "var(--bg2)",
        border: "1px solid var(--border)", borderRadius: RADIUS.pill,
        padding: 3,
        ...style,
      }}>
      {!grid && !pill && options.length > 0 && (
        <span aria-hidden="true" style={{
          position: "absolute", top: pad, bottom: pad, left: pad,
          width: `calc((100% - ${pad * 2}px) / ${options.length})`,
          transform: `translateX(${activeIndex * 100}%)`,
          background: "var(--bg4)",
          borderRadius: RADIUS.pill, boxSizing: "border-box",
          transition: `transform ${MOTION.state}`,
        }} />
      )}
      {options.map((opt) => {
        const active = value === opt.v;
        const off = !!opt.disabled;
        // The composed title: the full label survives in the tooltip even
        // when a distinct title carries a description (9.21's honesty rule).
        // A chip is part of the name ("PiD 4×"), so it rejoins the label here.
        const fullLabel = opt.chip ? `${opt.label} ${opt.chip}` : opt.label;
        const title = opt.title && opt.title !== fullLabel
          ? `${fullLabel} — ${opt.title}` : (opt.title || fullLabel);
        // flex segment style — the shrink rule travels with its clip rules
        // (the label span below carries the ellipsis): a segment that can
        // shrink must clip, never paint over its neighbour.
        const flexStyle = {
          position: "relative", zIndex: 1,
          flex: 1, minWidth: 0, overflow: "hidden",
          padding: size === "sm" ? "4px 8px" : "8px 6px",
          fontSize: TYPE.ui, fontWeight: W.nav, fontFamily: FONT,
          background: "transparent",
          color: active ? "var(--text)" : "var(--textMut)",
          opacity: off && !active ? 0.45 : 1,
          border: "none", borderRadius: RADIUS.pill,
          cursor: off ? "default" : "pointer",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          gap: SPACE[6], whiteSpace: "nowrap",
          transition: `background ${MOTION.hover}, color ${MOTION.hover}`,
        };
        // grid segment style — grid columns cannot shrink below their own
        // label, so this object declares NO shrink rule and NO clip rule:
        // pill option style (brief 10.0, the mockup's .seg span): the label
        // hug - PILL_OPTION_H tall, 11px sides, at label type, idle ink textSec, the active option
        // full accent with accentInk text. No slide: the active state is the
        // option's own background, settling on MOTION.state.
        // 550, half a step: dark ink on full chartreuse is the panel's
        // brightest ground and 500 reads thin on it, but 600 is bold - "I
        // dont want bold I just wanted slightly thicker … like split the
        // difference" (Jesse, 2026-09-04). Half steps only exist because
        // Geist is a VARIABLE face; under the Arial fallback this shipped
        // with, 550 rounded to bold and there was nothing in between.
        // EVERY option carries it, not just the active one: a heavier active
        // label is a wider active label, and the track would reflow its
        // neighbours on every click. State is ground and ink, never width.
        const pillStyle = {
          height: PILL_OPTION_H, padding: "0 11px",
          fontSize: TYPE.label, fontWeight: W.emphasis, fontFamily: FONT,
          background: active ? "var(--accent)" : "transparent",
          color: active ? "var(--accentInk)" : "var(--textSec)",
          opacity: off && !active ? 0.45 : 1,
          border: "none", borderRadius: RADIUS.pill,
          cursor: off ? "default" : "pointer",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          gap: SPACE[6], whiteSpace: "nowrap",
          transition: `background ${MOTION.state}, color ${MOTION.state}`,
        };
        // the label cannot clip, by construction. Do not add minWidth /
        // overflow / textOverflow here — they would be dead code hiding the
        // very contract that makes this variant safe.
        const gridStyle = {
          height: size === "sm" ? 28 : 32,
          padding: `0 ${SPACE[8]}px`,
          border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
          background: active
            ? fill ? "var(--accent)" : "var(--accentMut)"
            : "transparent",
          color: active
            ? fill ? "#0D0F15" : "var(--accent)"
            : "var(--textTer)",
          opacity: off && !active ? 0.45 : 1,
          borderRadius: RADIUS.input,
          fontSize: size === "sm" ? TYPE.label : TYPE.ui,
          fontFamily: FONT, fontWeight: W.nav,
          cursor: off ? "default" : "pointer", outline: "none",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          gap: SPACE[6],
          transition: `all ${MOTION.state}`, whiteSpace: "nowrap",
        };
        return (
          <button key={String(opt.v)} type="button" role="radio" className="px-seg"
            aria-checked={active} disabled={off} title={title}
            onClick={() => { if (!off) onChange(opt.v); }}
            {...(opt.buttonProps || {})}
            style={grid ? gridStyle : pill ? pillStyle : flexStyle}>
            {opt.Icon && (
              <opt.Icon size={pill || size === "sm" ? 13 : 14} weight="duotone"
                active={active} style={{ flexShrink: 0 }} />
            )}
            {grid || pill ? opt.label : (
              <span style={{ minWidth: 0, overflow: "hidden",
                             textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {opt.label}
              </span>
            )}
            {opt.chip && <Chip>{opt.chip}</Chip>}
          </button>
        );
      })}
    </div>
  );
};
