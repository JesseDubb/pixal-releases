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
// variant="grid" — equal columns that CANNOT shrink below their own label
//   (grid items carry implicit min-width:auto — DESIGN.md's measured proof).
//   Reach for it for a two- or three-option switch whose labels must never
//   clip. Descends from Lumen's segmented toggle (desklight:
//   apps/backoffice/src/components/ui/) — accent-keyed borders and
//   RADIUS.input, not the capsule's bg4 fill. `fill` and option
//   `buttonProps` were carried across from there 2026-08-23; raise any
//   change to this variant back against Lumen so the two do not drift.
//
// options — [{ v, label, Icon?, disabled?, title?, buttonProps? }]. ONE key:
//   `v`. The grid original's `value` key is gone; there is no shim.
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

import { FONT, W, TYPE, SPACE, RADIUS, MOTION } from "./design-tokens.js";

export const SegmentedControl = ({
  options, value, onChange, ariaLabel,
  variant = "flex", size = "md", fill = false, className, style,
}) => {
  const grid = variant === "grid";
  return (
    <div role="radiogroup" aria-label={ariaLabel} className={className}
      style={grid ? {
        display: "grid",
        gridTemplateColumns: `repeat(${options.length}, 1fr)`,
        gap: SPACE[4],
        ...style,
      } : {
        display: "flex", background: "var(--bg2)",
        border: "1px solid var(--border)", borderRadius: RADIUS.pill,
        padding: 3,
        ...style,
      }}>
      {options.map((opt) => {
        const active = value === opt.v;
        const off = !!opt.disabled;
        // The composed title: the full label survives in the tooltip even
        // when a distinct title carries a description (9.21's honesty rule).
        const title = opt.title && opt.title !== opt.label
          ? `${opt.label} — ${opt.title}` : (opt.title || opt.label);
        // flex segment style — the shrink rule travels with its clip rules
        // (the label span below carries the ellipsis): a segment that can
        // shrink must clip, never paint over its neighbour.
        const flexStyle = {
          flex: 1, minWidth: 0, overflow: "hidden",
          padding: size === "sm" ? "4px 8px" : "8px 6px",
          fontSize: TYPE.ui, fontWeight: W.nav, fontFamily: FONT,
          background: active ? "var(--bg4)" : "transparent",
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
          <button key={String(opt.v)} type="button" role="radio"
            aria-checked={active} disabled={off} title={title}
            onClick={() => { if (!off) onChange(opt.v); }}
            {...(opt.buttonProps || {})}
            style={grid ? gridStyle : flexStyle}>
            {opt.Icon && (
              <opt.Icon size={size === "sm" ? 13 : 14} weight="duotone"
                active={active} style={{ flexShrink: 0 }} />
            )}
            {grid ? opt.label : (
              <span style={{ minWidth: 0, overflow: "hidden",
                             textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {opt.label}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
};
