// MiniSlider.jsx — Lumen's MiniSlider, ported from
// desklight/apps/backoffice/src/components/ui/MiniSlider.jsx (2026-08-25).
//
// A native <input type="range"> owns pointer events, keyboard and the
// accessible name; the track, fill and knob are painted underneath so the
// chrome matches the rail. `step` is the whole point here: the input only
// lands on the dial's own steps, so there is nothing to type and nothing to
// erase - the box this replaced refilled with the recipe default the moment
// it was empty, which is why "the 4" could not be cleared (Jesse, 2026-08-25).
//
// Pixal's use is unipolar (min >= 0) with a RESET point that is the recipe's
// own number rather than the track's minimum: double-click returns to
// `resetTo` when given, else to min/centre as in Lumen.
import { useCallback } from "react";
import { FONT, TYPE, SPACE } from "./design-tokens.js";

const defaultFormat = (v) => {
  const n = Math.round(v);
  if (n === 0) return "0";
  return n > 0 ? `+${n}` : `${n}`;
};

export const MiniSlider = ({
  icon: Icon,
  value,
  onChange,
  min = -50,
  max = 50,
  step = 1,
  resetTo,
  format = defaultFormat,
  ariaLabel = "Adjust",
  disabled = false,
  emphasis = false,     // readout in accent - the value is off its home
}) => {
  const range = max - min || 1;
  const clamped = Math.min(max, Math.max(min, Number(value) || 0));
  const fillPct = ((clamped - min) / range) * 100;

  const bipolar = min < 0 && max > 0;
  const centerPct = bipolar ? ((0 - min) / range) * 100 : 0;
  const fillLeftPct = bipolar ? (clamped >= 0 ? centerPct : fillPct) : 0;
  const fillWidthPct = bipolar ? Math.abs(fillPct - centerPct) : fillPct;

  const handleChange = useCallback((e) => {
    const next = Number(e.target.value);
    if (!Number.isNaN(next)) onChange?.(next);
  }, [onChange]);

  const handleDoubleClick = useCallback(() => {
    if (disabled) return;
    onChange?.(resetTo !== undefined ? resetTo : bipolar ? 0 : min);
  }, [bipolar, min, resetTo, onChange, disabled]);

  return (
    <div onDoubleClick={handleDoubleClick}
      style={{ display: "grid",
               gridTemplateColumns: Icon ? "22px 1fr 38px" : "1fr 38px",
               alignItems: "center", gap: SPACE[10],
               opacity: disabled ? 0.5 : 1 }}>
      {Icon && (
        <Icon size={15} weight="duotone"
          style={{ color: "var(--textSec)", justifySelf: "center" }} />
      )}
      {/* The track is inset by half a thumb on each side so the thumb stays
          inside the box at both ends - at the minimum it used to hang 6px
          past the left edge and get clipped (Jesse, 2026-08-26). */}
      <div style={{ position: "relative", height: 16, padding: "0 6px" }}>
        <div style={{ position: "relative", height: "100%" }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: "50%",
                      height: 4, marginTop: -2, background: "var(--bg3)",
                      borderRadius: 2 }} />
        {bipolar && (
          <div style={{ position: "absolute", left: `${centerPct}%`, top: "50%",
                        width: 1, height: 8, marginTop: -4,
                        background: "var(--borderStr)" }} />
        )}
        <div style={{ position: "absolute", left: `${fillLeftPct}%`, top: "50%",
                      width: `${fillWidthPct}%`, height: 4, marginTop: -2,
                      background: "var(--text)", borderRadius: 2 }} />
        <div style={{ position: "absolute", left: `${fillPct}%`, top: "50%",
                      width: 12, height: 12, marginLeft: -6, marginTop: -6,
                      background: "var(--bg1)", border: "1.5px solid var(--text)",
                      borderRadius: "50%", boxShadow: "0 1px 2px rgba(0,0,0,0.18)",
                      pointerEvents: "none" }} />
        </div>
        <input type="range" min={min} max={max} step={step} value={clamped}
          onChange={handleChange} aria-label={ariaLabel} disabled={disabled}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
                   margin: 0, opacity: 0, cursor: disabled ? "default" : "pointer" }} />
      </div>
      <span style={{ fontFamily: FONT, fontSize: TYPE.label,
                     color: emphasis ? "var(--accent)" : "var(--textTer)",
                     fontVariantNumeric: "tabular-nums", textAlign: "right",
                     transition: "color 100ms cubic-bezier(0.22, 1, 0.36, 1)" }}>
        {format(clamped)}
      </span>
    </div>
  );
};
