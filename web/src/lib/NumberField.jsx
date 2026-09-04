// NumberField — THE PIXAL NUMBER BOX. A 52×24 pill you can actually type in.
//
// It replaces three hand-rolled copies in Settings (DLSS 5 tone, film grain
// amount, shine removal strength) that shared one bug, in two halves:
//
//   const v = parseFloat(e.target.value);
//   if (!Number.isFinite(v)) return;          // on a CONTROLLED input
//
// Half one: you cannot type. Clearing the box gives "", parseFloat("") is
// NaN, the handler returns, state never changes, and React re-renders the old
// number straight back - the field refuses to empty. Typing a decimal is
// worse: "0." parses to 0, state becomes 0, the input is forced to "0" and
// the point you just typed is gone, so 0.75 is unreachable no matter how you
// type it. The spin buttons are hidden globally (Chat.jsx's px-root rules),
// so the only thing that ever worked was the up/down arrow keys. Composer's
// StrengthInput already carried the warning in a comment - "a controlled box
// that refills with the default cannot be cleared" - and Settings hand-rolled
// it anyway. DESIGN.md: never hand-roll a control a second time.
//
// Half two: it committed on every keystroke, so every digit POSTed
// /api/settings and set a toast, and the toast row lives in the panel's
// normal flow - so the whole panel grew a row and jumped under the cursor
// mid-edit.
//
// The fix is one rule: while the box is focused it owns its own text, and it
// reports a value only when the edit is FINISHED. Typing is a draft (any
// string, including "" and "0."); blur and Enter commit; Escape reverts.
// Arrow keys and the wheel still step, and those commit immediately because
// each one is a whole edit. A committed value is clamped to min/max and
// snapped off the step's decimals, so 0.30000000000000004 never reaches the
// config file.
//
// `onCommit(number)` fires only when the value actually changed - a blur that
// changed nothing must not POST, or tabbing through Settings would save
// everything it passed.
import { useEffect, useRef, useState } from "react";
import { FONT, HEIGHT, RADIUS, TYPE, W } from "./design-tokens.js";

const decimals = (step) => {
  const s = String(step);
  const dot = s.indexOf(".");
  return dot < 0 ? 0 : s.length - dot - 1;
};

const clamp = (n, min, max) => {
  if (min !== undefined && n < min) return min;
  if (max !== undefined && n > max) return max;
  return n;
};

export const NumberField = ({ value, onCommit, label, title, step = 0.05,
                             min, max, width = 52, disabled = false,
                             className }) => {
  const [draft, setDraft] = useState(null);      // non-null only while editing
  const committed = useRef(value);
  useEffect(() => { committed.current = value; }, [value]);

  const settle = (raw) => {
    const n = parseFloat(raw);
    if (!Number.isFinite(n)) return null;
    return parseFloat(clamp(n, min, max).toFixed(decimals(step)));
  };

  // The one exit door: fold the draft into a real number, report it if it
  // moved, and hand the box back to the prop.
  const commit = () => {
    const next = settle(draft);
    setDraft(null);
    if (next !== null && next !== committed.current) {
      committed.current = next;
      onCommit(next);
    }
  };

  const nudge = (delta) => {
    const base = settle(draft !== null ? draft : value);
    const next = settle(String((base === null ? 0 : base) + delta));
    setDraft(null);
    if (next !== null && next !== committed.current) {
      committed.current = next;
      onCommit(next);
    }
  };

  return (
    <input type="number" step={step} className={className}
      value={draft !== null ? draft : value}
      aria-label={label} title={title} disabled={disabled}
      {...(min !== undefined ? { min } : {})}
      {...(max !== undefined ? { max } : {})}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") { e.preventDefault(); commit(); e.target.blur(); }
        else if (e.key === "Escape") { e.preventDefault(); setDraft(null); e.target.blur(); }
        // The arrows are the browser's, but the browser would write them into
        // the draft and wait for a blur. A press of an arrow IS a finished
        // edit, so it commits on the spot - which is also the behaviour that
        // worked before this control existed, and the only one that did.
        else if (e.key === "ArrowUp") { e.preventDefault(); nudge(+step); }
        else if (e.key === "ArrowDown") { e.preventDefault(); nudge(-step); }
      }}
      style={{ width, height: HEIGHT.rail, padding: "0 8px", boxSizing: "border-box",
               background: "var(--bg3)",
               border: "1px solid var(--border)",
               borderRadius: RADIUS.pill, color: "var(--text)",
               fontFamily: FONT, fontSize: TYPE.label, fontWeight: W.nav,
               textAlign: "center", opacity: disabled ? 0.5 : 1 }} />
  );
};
