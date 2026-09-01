// Switch — THE PIXAL TOGGLE (brief 10.0): a wide, low 42×16 pill with the
// signature dark-ink knob on chartreuse — the inverse of every white-knob
// toggle out there, and the control Jesse asked for by name ("pill toggles,
// the wider not so high toggle style … make them unique to pixal"). Lifted
// out of Composer's LoraToggle and MotionDirector's Switch (brief 9.83) as a
// 30×17 accentMut-wash control; 10.0 gave it the control family's geometry:
// OFF is a bg4 track with a hairline border and a bg1 knob, ON is the full
// accent track with the accentInk knob. One recipe now: `on`,
// `onChange(next)`, `disabled`, `label` (the accessible name -
// aria-checked announces the state), `title`. DESIGN.md: never hand-roll a
// control a second time.
//
// The knob rides left:2 + translateX(25px) rather than swapping left/right,
// so the slide is one transform on MOTION.state and never repaints the
// track. The ON track keeps its 1px border (accent on accent, invisible) so
// the padding box - and the knob's 2px inset - is identical in both states.
import { MOTION, RADIUS } from "./design-tokens.js";

export const Switch = ({ on, onChange, disabled = false, label, title, className }) => (
  <button type="button" role="switch" aria-checked={!!on} aria-label={label}
    className={className}
    disabled={disabled} title={title} onClick={() => !disabled && onChange(!on)}
    style={{ position: "relative", width: 42, height: 16, padding: 0, flex: "none",
             boxSizing: "border-box",
             cursor: disabled ? "default" : "pointer",
             border: `1px solid ${on ? "var(--accent)" : "var(--borderStr)"}`,
             borderRadius: RADIUS.pill, opacity: disabled ? 0.5 : 1,
             background: on ? "var(--accent)" : "var(--bg4)",
             transition: `background ${MOTION.state}, border-color ${MOTION.state}` }}>
    <span aria-hidden="true" style={{ position: "absolute", top: 2, left: 2,
      width: 11, height: 11, borderRadius: "50%", boxSizing: "border-box",
      background: on ? "var(--accentInk)" : "var(--bg1)",
      border: `1px solid ${on ? "transparent" : "var(--borderStr)"}`,
      transform: on ? "translateX(25px)" : "none",
      transition: `transform ${MOTION.state}, background ${MOTION.state}, ` +
                  `border-color ${MOTION.state}` }} />
  </button>
);
