import { useEffect } from "react";
import { RADIUS, BORDER } from "./design-tokens.js";

// Thinking — the live "Pixal is at it" indicator, with TWO modes so it reads
// ALIVE and it's visibly different when Pixal is THINKING (composing a reply)
// vs WORKING (running a tool). Replaces the old flat single-dot pulse, which
// read lifeless.
//   mode="thinking" → three dots bouncing in sequence (gentle, "writing").
//   mode="working"  → an accent bar sweeping back and forth in a pill (busy,
//                     real work in flight — fun to watch).
// var(--accent) per the design-system color budget: the accent IS the active/
// working signal. Adapted from the bouncing typing-indicator pattern.

// Module-singleton keyframe injection so N instances share ONE <style> (the
// dots/bar are pure CSS animation; nothing per-instance to vary).
let _injected = false;
const KEYFRAMES = `
@keyframes px-think-dot {
  0%, 100% { transform: translateY(0); }
  25%      { transform: translateY(-3px); }
  50%      { transform: translateY(0); }
  75%      { transform: translateY(1.5px); }
}
/* The inchworm as a DECOMPOSED CAPSULE, still transform-only. A single scaleX
   pill squashed its round ends into ellipses mid-stretch (caught 2026-08-11:
   "keep the vector round"). Here the two end caps only TRANSLATE - a
   translated circle stays a circle - and a square-edged middle rect between
   their centers carries the stretch via scaleX (no radius, so nothing to
   distort). All three tracks share one duration and easing, so the rect's
   edges ride exactly on the cap centers at every instant: a geometrically
   true capsule through the whole dot -> stretch -> travel -> dot cycle.
   Choreography (31px travel): grow right, collapse rightward to a dot,
   grow back left, collapse leftward home. */
@keyframes px-think-capL {
  0%   { transform: translateX(0); }
  25%  { transform: translateX(0); }
  50%  { transform: translateX(31px); }
  75%  { transform: translateX(0); }
  100% { transform: translateX(0); }
}
@keyframes px-think-capR {
  0%   { transform: translateX(0); }
  25%  { transform: translateX(31px); }
  50%  { transform: translateX(31px); }
  75%  { transform: translateX(31px); }
  100% { transform: translateX(0); }
}
@keyframes px-think-mid {
  0%   { transform: translateX(0)    scaleX(0); }
  25%  { transform: translateX(0)    scaleX(1); }
  50%  { transform: translateX(31px) scaleX(0); }
  75%  { transform: translateX(0)    scaleX(1); }
  100% { transform: translateX(0)    scaleX(0); }
}
@media (prefers-reduced-motion: reduce) {
  .px-think-dot, .px-think-capL, .px-think-capR, .px-think-mid { animation: none !important; }
  .px-think-capL, .px-think-capR, .px-think-mid { opacity: 0.7; }
  .px-think-capR { transform: translateX(31px) !important; }
  .px-think-mid  { transform: translateX(0) scaleX(1) !important; }
}`;
const ensureKeyframes = () => {
  if (_injected || typeof document === "undefined") return;
  const el = document.createElement("style");
  el.id = "px-thinking-kf";
  el.textContent = KEYFRAMES;
  document.head.appendChild(el);
  _injected = true;
};

// `frozen`: even a compositor-only animation forces Chromium to produce a
// frame every vsync, and on a CUDA-saturated GPU every late frame is a visible
// hiccup - worst in the FOCUSED window, which gets foreground GPU priority and
// fights ComfyUI for the card. While a render is sampling, the JobCard's dot
// matrix and step counter are the liveness signal; this indicator holds still.
export const Thinking = ({ mode = "thinking", size = 7, frozen = false }) => {
  useEffect(ensureKeyframes, []);

  if (mode === "working") {
    // Fixed geometry; ONLY transform animates (see the keyframes note).
    // Caps: 7px wide at left 3 and travel 31px -> span 3..41 inside the 44px
    // content box, the original bar's footprint. Middle rect runs cap-center
    // to cap-center (left 6.5, width 31), stretched by scaleX.
    const capStyle = (anim, freeze) => ({
      position: "absolute", top: "50%", height: size, marginTop: -(size / 2),
      width: 7, left: 3, borderRadius: RADIUS.pill, background: "var(--accent)",
      animation: frozen ? "none" : `${anim} 1.5s ease-in-out infinite`,
      transform: frozen ? freeze : undefined,
    });
    return (
      <span
        role="img"
        aria-label="Pixal is working"
        style={{
          position: "relative", display: "inline-block",
          width: 46, height: size + 8,
          border: `1px solid ${BORDER.idle}`, borderRadius: RADIUS.pill,
          flexShrink: 0,
        }}
      >
        <span className="px-think-capL" style={capStyle("px-think-capL", "translateX(15.5px)")} />
        <span className="px-think-capR" style={capStyle("px-think-capR", "translateX(15.5px)")} />
        <span
          className="px-think-mid"
          style={{
            position: "absolute", top: "50%", height: size, marginTop: -(size / 2),
            left: 6.5, width: 31, background: "var(--accent)",
            transformOrigin: "left center",
            animation: frozen ? "none" : "px-think-mid 1.5s ease-in-out infinite",
            transform: frozen ? "translateX(15.5px) scaleX(0)" : undefined,
          }}
        />
      </span>
    );
  }

  const dot = (delay) => ({
    width: size, height: size, borderRadius: RADIUS.pill,
    background: "var(--accent)", display: "inline-block",
    animation: frozen ? "none" : `px-think-dot 1.2s ease-in-out ${delay}s infinite`,
  });
  return (
    <span role="img" aria-label="Pixal is thinking" style={{ display: "inline-flex", gap: 4, alignItems: "center", flexShrink: 0 }}>
      <span className="px-think-dot" style={dot(0)} />
      <span className="px-think-dot" style={dot(0.16)} />
      <span className="px-think-dot" style={dot(0.32)} />
    </span>
  );
};
