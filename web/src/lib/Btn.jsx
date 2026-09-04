import { FONT, W, TYPE, SPACE, RADIUS, HEIGHT, MOTION } from "./design-tokens.js";

// Pixal's ONE button. Ported from Lumen's ui/Btn.jsx on 2026-09-04 and put
// on Pixal's role ladder; before this the app carried nine button
// implementations across nine files and none in lib/, and DESIGN.md had no
// button section at all - so "which button, how tall, how loud" was decided
// again at every call site. Every <button> that carries chrome resolves to
// this; a hand-rolled one is a defect on sight (DESIGN.md §3).
//
//   variant   "ghost" (default)  the quiet action: bg2, hairline, textSec.
//                                 Most buttons. Firms on hover, never fills.
//             "primary"          the ONE call to action on a surface: full
//                                 accent with dark ink. Two primaries in view
//                                 is a design error, not a size question.
//             "link"             a tertiary action inline with text: accent
//                                 ink, no chrome, no fixed height.
//             "danger"           destructive, always outlined in oxblood so
//                                 it reads as the brand and not as an alert.
//   size      "sm"  HEIGHT.rail  a passenger on a row's right rail
//             "md"  HEIGHT.row   owns its own line (default)
//             "lg"  HEIGHT.cta   the primary, when it stands alone
//   icon / iconRight   Phosphor element before / after the label
//   iconOnly           a square of the size's height; pass `title`, it
//                      becomes the aria-label
//   as                 "button" | "a" | "label" - an anchor that looks like
//                      a button IS a button here (About's links, an upload
//                      <label> wrapping a hidden file input)
//
// Optical centring is Lumen's: a leading icon pulls the visual mass left,
// so the trailing padding grows by ~a third of the icon (4 / 4 / 6, even);
// iconOnly and two-icon buttons stay symmetric. Hover changes ground and
// ink only, never size - a hover that moves the box moves it out from under
// the cursor (DESIGN.md §3).
const SIZE = {
  sm: { height: HEIGHT.rail, padX: SPACE[12], font: TYPE.label, icon: 12, bump: 4 },
  md: { height: HEIGHT.row,  padX: SPACE[16], font: TYPE.ui,    icon: 14, bump: 4 },
  lg: { height: HEIGHT.cta,  padX: SPACE[20], font: TYPE.ui,    icon: 16, bump: 6 },
};

const VARIANT = {
  ghost: {
    bg: "var(--bg2)", fg: "var(--textSec)", bd: "1px solid var(--border)",
    hoverBg: "var(--bg3)", hoverFg: "var(--text)", hoverBd: "var(--borderHov)",
    weight: W.nav,
  },
  primary: {
    bg: "var(--accent)", fg: "var(--accentInk)", bd: "1px solid var(--accent)",
    hoverBg: "var(--accentHot)", hoverFg: "var(--accentInk)", hoverBd: "var(--accentHot)",
    // 550, not 600: dark ink on full chartreuse is the brightest ground in
    // the app and bold reads heavy there (the pill selector's finding).
    weight: W.emphasis,
  },
  link: {
    bg: "transparent", fg: "var(--accent)", bd: "none",
    hoverBg: "transparent", hoverFg: "var(--accentHot)", hoverBd: null,
    weight: W.nav,
  },
  danger: {
    bg: "transparent", fg: "var(--error)", bd: "1px solid var(--error)",
    hoverBg: "var(--errorMut)", hoverFg: "var(--error)", hoverBd: "var(--error)",
    weight: W.nav,
  },
};

export const Btn = ({
  children, onClick, variant = "ghost", size = "md",
  icon, iconRight, iconOnly = false, disabled = false, title,
  as: Tag = "button", style: styleOverride, ...rest
}) => {
  const s = SIZE[size] || SIZE.md;
  const v = VARIANT[variant] || VARIANT.ghost;
  const link = variant === "link";
  const leading = !!icon && !iconOnly;
  const trailing = !!iconRight && !iconOnly;
  const padL = leading || !trailing ? s.padX : s.padX + s.bump;
  const padR = trailing || !leading ? s.padX : s.padX + s.bump;
  const base = {
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    gap: SPACE[6], boxSizing: "border-box", flexShrink: 0,
    height: link ? "auto" : s.height,
    width: iconOnly ? s.height : undefined,
    padding: iconOnly || link ? 0 : `0 ${padR}px 0 ${padL}px`,
    borderRadius: RADIUS.pill, border: v.bd, background: v.bg, color: v.fg,
    fontFamily: FONT, fontSize: s.font, fontWeight: v.weight, lineHeight: 1,
    whiteSpace: "nowrap", textDecoration: "none",
    cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.5 : 1,
    transition: `background ${MOTION.hover}, border-color ${MOTION.hover}, color ${MOTION.hover}`,
    ...styleOverride,
  };
  const enter = (e) => {
    if (disabled) return;
    e.currentTarget.style.background = v.hoverBg;
    e.currentTarget.style.color = v.hoverFg;
    if (v.hoverBd) e.currentTarget.style.borderColor = v.hoverBd;
  };
  const leave = (e) => {
    if (disabled) return;
    e.currentTarget.style.background = v.bg;
    e.currentTarget.style.color = v.fg;
    if (v.hoverBd) e.currentTarget.style.borderColor = v.bd.split(" ").pop();
  };
  const own = Tag === "button" ? { type: "button", disabled } : {};
  return (
    <Tag {...rest} {...own} onClick={disabled ? undefined : onClick} title={title}
      aria-label={rest["aria-label"] || (iconOnly ? title : undefined)}
      style={base} onMouseEnter={enter} onMouseLeave={leave}>
      {icon}
      {!iconOnly && children}
      {!iconOnly && iconRight}
    </Tag>
  );
};
