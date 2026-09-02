// Chip.jsx — the little mono badge (the Settings pickers' "4×" scale
// chip, brief 10.0). One recipe, now shared: a scale factor never renders
// as prose ("2x") in one surface and a chip in another (Jesse, 2026-09-01:
// "when we mention 2x and 4x in the app... use the little x chip"). The
// chip carries its own bg3 fill and hairline, so it reads the same on a
// picker row, inside a pill segment (active accent included), and beside
// a field label.
import { RADIUS } from "./design-tokens.js";

const MONO = "ui-monospace, Consolas, monospace";

export const Chip = ({ children }) => (
  <span style={{
    flexShrink: 0, fontFamily: MONO, fontSize: 9, padding: "1px 6px",
    borderRadius: RADIUS.pill, background: "var(--bg3)",
    border: "1px solid var(--border)", color: "var(--textTer)",
  }}>{children}</span>
);
