import { useLayoutEffect, useRef, useState } from "react";
import { CaretRight } from "@phosphor-icons/react";
import { FONT, SPACE, MOTION } from "./design-tokens.js";

// Disclosure.jsx — the ONE fold (brief 9.23c). A fold animates its height; it
// never mounts. `{open && (…)}` snaps because mounting has no in-between, and
// `maxHeight: "none"` snaps because "none" is not a number. Twenty-odd
// disclosures in this app animated exactly once; now the technique lives here
// and nowhere else.
//
// PORTING.md was checked before writing a line: Lumen ships collapsible
// *sections* (Section.jsx, RailSection.jsx) on the same 0fr↔1fr trick, but
// they do not fit, and what did not fit is named, per the porting rules:
//   - they own their state and persist it to localStorage per-id. Pixal's
//     folds are caller-controlled (fineTune derives from the recipe, JobCard's
//     expanded is per-card), and 9.23c forbids changing what a fold persists.
//   - their chrome is fixed (amber mono-caps title; inspector icon + count).
//     Pixal's four triggers are four different layouts.
//   - no peek mode: JobCard's prompt teaser shows the first lines of the
//     content while collapsed, which a 0fr fold cannot express.
//   - no reduced-motion guard.
// Lumen's AnimatedCaret was not ported either: its spec (CaretDown flipped
// −90°→0° on MOTION.layout with an accent colour crossfade) differs from the
// house caret below (CaretRight rotating to 90° on MOTION.press — the tactile
// curve, because a chevron is an object you pressed), and adopting it would
// repaint every fold's chrome. Raising a shared caret against Lumen is a
// conversation for the next port, not a silent fork here.
//
// The two halves, exported separately:
//   Disclosure        — the fold region. Owns the animation technique and the
//                       reduced-motion guard. Hand it `trigger` + `onToggle`
//                       and it also renders the standard trigger-above unit.
//   DisclosureTrigger — the button. Owns the chevron and its rotation. Render
//                       it standalone when the trigger lives somewhere the
//                       fold cannot wrap (JobCard's footer row).
//
// Technique: `grid-template-rows: 0fr ↔ 1fr` animates an intrinsic-height
// block with no hardcoded pixels; the inner `overflow: hidden` clips during
// the transition and `visibility` keeps tab order out of mid-animation
// content. `peek` (px) is the teaser mode for "show the first lines" folds:
// max-height animates between `peek` and the content's measured height — the
// one place measurement is unavoidable, since a teaser is part of the content
// itself. Peek content stays visible while collapsed, obviously.
//
// Reduced motion drops the transition, never the state change — the fold
// still opens, instantly. House style: matchMedia, as in BlockLogo/DotMatrix/
// GlassLogo. Render-quiet (DESIGN.md §5) is untouched: a fold is a one-shot
// transition on a small subtree, not a loop, so `.px-calm` has nothing to do.

const reducedMotion = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export const DisclosureTrigger = ({ open, onToggle, caretSide = "leading",
                                    caretSize = 11, title, style, caretStyle,
                                    children }) => {
  const caret = (
    <CaretRight size={caretSize} weight="bold" aria-hidden="true"
      style={{ flex: "none",
               transform: open ? "rotate(90deg)" : "none",
               transition: reducedMotion() ? "none" : `transform ${MOTION.press}`,
               ...caretStyle }} />
  );
  return (
    <button type="button" onClick={onToggle} aria-expanded={open} title={title}
      style={{ display: "flex", alignItems: "center", gap: SPACE[8],
               width: "100%", padding: 0, background: "transparent",
               border: "none", cursor: "pointer", fontFamily: FONT,
               textAlign: "left", ...style }}>
      {caretSide === "leading" && caret}
      {children}
      {caretSide === "trailing" && caret}
    </button>
  );
};

// Teaser mode: the collapsed state shows `peek` px of the content, so the
// fold animates max-height between peek and the measured content height. A
// ResizeObserver keeps the open target honest across lane resizes and late
// font loads — the alternative (a hardcoded "big enough" cap) spends most of
// the easing curve traversing pixels that do not exist.
const PeekFold = ({ open, peek, contentRef, style, contentStyle, children }) => {
  const measureRef = useRef(null);
  const [full, setFull] = useState(peek);
  useLayoutEffect(() => {
    const el = measureRef.current;
    if (!el) return undefined;
    const measure = () => setFull(el.scrollHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const setRefs = (el) => {
    measureRef.current = el;
    if (contentRef) contentRef.current = el;
  };
  return (
    <div style={{ maxHeight: open ? full : peek, overflow: "hidden",
                  transition: reducedMotion() ? "none" : `max-height ${MOTION.layout}`,
                  ...style }}>
      <div ref={setRefs} style={contentStyle}>{children}</div>
    </div>
  );
};

export const Disclosure = ({ open, onToggle, trigger, caretSide, caretSize,
                             triggerTitle, triggerStyle, caretStyle,
                             peek, contentRef, style, contentStyle, children }) => {
  const reduced = reducedMotion();
  const fold = peek != null ? (
    <PeekFold open={open} peek={peek} contentRef={contentRef}
      style={trigger == null ? style : undefined} contentStyle={contentStyle}>
      {children}
    </PeekFold>
  ) : (
    <div style={{ display: "grid", gridTemplateRows: open ? "1fr" : "0fr",
                  transition: reduced ? "none" : `grid-template-rows ${MOTION.layout}`,
                  ...(trigger == null ? style : null) }}>
      <div ref={contentRef}
        style={{ overflow: "hidden", visibility: open ? "visible" : "hidden",
                 transition: reduced ? "none" : `visibility ${MOTION.layout}`,
                 ...contentStyle }}>
        {children}
      </div>
    </div>
  );
  if (trigger == null) return fold;
  return (
    <div style={style}>
      <DisclosureTrigger open={open} onToggle={onToggle} caretSide={caretSide}
        caretSize={caretSize} title={triggerTitle}
        style={triggerStyle} caretStyle={caretStyle}>
        {trigger}
      </DisclosureTrigger>
      {fold}
    </div>
  );
};
