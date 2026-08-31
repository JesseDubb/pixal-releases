// Switch — the Lumen on/off: a 30×17 pill with role="switch", lifted out of
// Composer's LoraToggle and MotionDirector's Switch (brief 9.83), which were
// the same control hand-rolled twice with different prop names. One recipe
// now: `on`, `onChange(next)`, `disabled`, `label` (the accessible name -
// aria-checked announces the state), `title`. DESIGN.md: never hand-roll a
// control a second time; the third consumer (the character page's accessory
// rows) is what forced the lift.
import { MOTION, RADIUS } from "./design-tokens.js";

export const Switch = ({ on, onChange, disabled = false, label, title }) => (
  <button type="button" role="switch" aria-checked={!!on} aria-label={label}
    disabled={disabled} title={title} onClick={() => !disabled && onChange(!on)}
    style={{ position: "relative", width: 30, height: 17, padding: 0, flex: "none",
             cursor: disabled ? "default" : "pointer",
             border: `1px solid ${on ? "var(--accent)" : "var(--borderHov)"}`,
             borderRadius: RADIUS.pill, opacity: disabled ? 0.5 : 1,
             background: on ? "var(--accentMut)" : "var(--bg1)",
             transition: `background ${MOTION.hover}, border-color ${MOTION.hover}` }}>
    <span aria-hidden="true" style={{ position: "absolute", top: 2, left: on ? 15 : 2,
      width: 11, height: 11, borderRadius: "50%",
      background: on ? "var(--accent)" : "var(--textMut)",
      transition: `left ${MOTION.hover}, background ${MOTION.hover}` }} />
  </button>
);
