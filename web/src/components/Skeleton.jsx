// Skeleton.jsx — ghost-loading kit, ported from desklight's ui/Skeleton.jsx
// (2026-08-22) and cut to what Settings uses. The rule it exists for: a
// control whose options are still loading renders a ghost of its FINAL size,
// never a collapsed partial - so nothing below it moves when the real thing
// arrives. The swap is opacity-only (px-ghost-in), never a height animation.
//
// One shimmer for the whole app: the geometry and the px-shimmer keyframe
// name are HistoryGrid's, and the px-shim-skel class hooks the same
// render-quiet rule (.px-calm stills every shimmer while ComfyUI samples).
// This file injects its own copy of the keyframes so Settings never depends
// on HistoryGrid having mounted first; identical definitions dedupe in the
// cascade.
import { SPACE, RADIUS } from "../lib/design-tokens.js";

const CSS = `
@keyframes px-shimmer { 0% { background-position: -400px 0; } 100% { background-position: 400px 0; } }
@keyframes px-ghost-in { from { opacity: 0; } to { opacity: 1; } }
.px-ghost-in { animation: px-ghost-in 160ms ease-out; }
/* No fill-mode ("both"/"forwards"), on purpose: a filling opacity animation
   keeps will-change semantics AFTER it ends, so the element stays a stacking
   context forever - and any popover it wraps (the ScrollPicker dropdown) gets
   its z-index trapped behind later px-ghost-in siblings (2026-08-24: the Video
   model dropdown painted under the Upscaler rows). The fade is identical
   without it - the end keyframe IS the resting state. */
.px-calm .px-shim-skel { animation: none !important; }
@media (prefers-reduced-motion: reduce) {
  .px-shim-skel, .px-ghost-in { animation: none !important; }
}
`;

export const SkeletonStyle = () => <style>{CSS}</style>;

export const Bar = ({ w = "100%", h = 14, style }) => (
  <div aria-hidden="true" className="px-shim-skel" style={{
    width: w, height: h, borderRadius: RADIUS.input, flexShrink: 0,
    background: "linear-gradient(90deg, var(--bg3) 25%, var(--bg4) 50%, var(--bg3) 75%)",
    backgroundSize: "800px 100%",
    animation: "px-shimmer 1.6s ease infinite",
    ...style,
  }} />
);

// Segmented-control ghost: the same 40px capsule SegmentedControl renders
// (3px padding, 1px border, 32px segments) - height-identical, so the real
// options land without pushing anything down.
export const SegGhost = ({ segments = 3 }) => (
  <div aria-hidden="true" style={{
    display: "flex", gap: 3, background: "var(--bg2)",
    border: "1px solid var(--border)", borderRadius: RADIUS.pill, padding: 3,
  }}>
    {Array.from({ length: segments }).map((_, i) => (
      <Bar key={i} h={32} style={{ flex: 1, borderRadius: RADIUS.pill }} />
    ))}
  </div>
);

// Picker ghost: the 38px bordered trigger with a shimmer bar where the
// value text will sit.
export const PickerGhost = () => (
  <div aria-hidden="true" style={{
    height: 38, boxSizing: "border-box", display: "flex", alignItems: "center",
    padding: `0 ${SPACE[12]}px`, background: "var(--bg2)",
    border: "1px solid var(--border)", borderRadius: RADIUS.input,
  }}>
    <Bar w="45%" h={11} />
  </div>
);

// Whole-line ghost for a prose value that arrives late and takes the line
// with it - the detected-card gloss is one sentence, so the whole line
// ghosts. The flex wrapper pins the line box to the 1.5em the text will
// occupy (gloss and footnote both run lineHeight 1.5), so the line neither
// shrinks nor grows when the words land; the bar inside is just the shimmer.
export const LineGhost = ({ w = "55%" }) => (
  <span aria-hidden="true" style={{
    display: "flex", alignItems: "center", height: "1.5em",
  }}>
    <Bar w={w} h={10} />
  </span>
);

// Inline value ghost: the count in "Found 614 files." - the sentence is
// known, the number is not. Sits in the text line at x-height, so the line
// box stays the text's own; only the number's width is a guess.
export const ValueGhost = ({ w = 64 }) => (
  <Bar w={w} h={10} style={{ display: "inline-block", verticalAlign: "middle" }} />
);
