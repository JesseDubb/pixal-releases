// The app's dropdown: a button trigger and a listbox popover, with a filter
// box once the list is long. Lifted out of MotionDirector (its model picker)
// on 2026-08-26 so the composer's tuning card could stop using a native
// <select> - Jesse: "make the dropdown work like our other ones".
// The trigger is the control family's VALUE PILL (brief 10.0): 24px, bg3,
// pill radius, the picked value in --text and the chevron in --textTer.
// `hug` shrinks the box to its value (the settings row's right rail) and
// hangs the popover off the trigger's right edge; default keeps the old
// fill-the-row width the composer and MotionDirector are built on.
// options: [{ id, label, description?, group? }] - consecutive options sharing
// a `group` sit under one small inline label (Jesse, 2026-08-26: "little
// inline label break for which sampler its under").
//
// The listbox portals to document.body (9.69): the tuning card's
// AccordionPanel is overflow:hidden (load-bearing for its grid-rows fold),
// so an in-tree absolute popover was cut at the card's foot - Jesse's
// Scheduler showed only its find box (2026-08-27). Geometry comes from the
// trigger's getBoundingClientRect() and the box flips above the trigger
// when the room below runs short. The portal node carries px-root:
// applyThemeCss scopes every theme var to that class and body sits outside
// it (InfoTip documents the same body-plus-px-root pair).
import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CaretDown } from "@phosphor-icons/react";
import { FONT, W, TYPE, SPACE, RADIUS, MOTION, SHADOW, Z } from "./design-tokens.js";
// Trigger-to-popover gap, and the most the box can stand: the 236px list
// cap plus the filter row (28 + the flex gap), padding and border.
const GAP = 6;
const POP_MAX = 236 + 28 + SPACE[4] + SPACE[4] * 2 + 2;

export const Picker = ({ label, options, value, onChange, placeholder, hug = false }) => {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [pop, setPop] = useState(null);
  const boxRef = useRef(null);
  const popRef = useRef(null);
  const inputRef = useRef(null);
  useLayoutEffect(() => {
    if (!open) { setPop(null); return undefined; }
    // Layout effect: the box must land at its rect before the first paint,
    // never open below and then visibly jump above the trigger on a flip.
    const place = () => {
      const r = boxRef.current?.getBoundingClientRect();
      if (!r) return;
      const below = window.innerHeight - r.bottom - GAP;
      const above = r.top - GAP;
      const up = below < POP_MAX && above > below;
      // A hugging trigger (settings' value pill) is only as wide as its
      // value, so the list would open comically narrow under it - floor it
      // at 240 and hang its RIGHT edge off the trigger's, since the pill
      // lives on the row's right rail, hard against the panel's edge.
      const w = hug ? Math.min(340, Math.max(r.width, 240)) : r.width;
      setPop({ left: hug ? r.right - w : r.left, width: w, up,
               top: up ? null : r.bottom + GAP,
               bottom: up ? window.innerHeight - r.top + GAP : null });
    };
    place();
    // Away = outside BOTH the trigger and the portal box - the portal is no
    // longer inside boxRef's subtree, so boxRef.contains alone would read
    // every click in the list as an away click and close on choice.
    const away = (e) => {
      if (boxRef.current?.contains(e.target) || popRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    // Capture-phase scroll catches any ancestor's scroll (the rail, the
    // chain's px-scroll list); a rAF throttle keeps it to one layout a frame.
    let raf = 0;
    const follow = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(place); };
    document.addEventListener("pointerdown", away);
    window.addEventListener("resize", follow);
    window.addEventListener("scroll", follow, true);
    return () => {
      document.removeEventListener("pointerdown", away);
      window.removeEventListener("resize", follow);
      window.removeEventListener("scroll", follow, true);
      cancelAnimationFrame(raf);
    };
  }, [open]);
  // The filter input mounts with the portal box (once `pop` lands), so the
  // focus waits for it in a plain effect - the layout one above runs while
  // the portal's first render is still gated off.
  useEffect(() => { if (open && pop) inputRef.current?.focus(); }, [open, pop]);
  const onEsc = (e) => {
    if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); setQ(""); }
  };
  const current = options.find((opt) => opt.id === value);
  const needle = q.trim().toLowerCase();
  const hits = options.filter((opt) => !needle ||
    `${opt.label} ${opt.description || ""}`.toLowerCase().includes(needle));
  const choose = (opt) => { onChange(opt.id); setOpen(false); setQ(""); };
  return (
    <div ref={boxRef} onKeyDown={onEsc} style={hug ? { width: "fit-content", maxWidth: 260 } : undefined}>
      <button type="button" aria-haspopup="listbox" aria-expanded={open}
        aria-label={label} title={current ? current.label : label}
        onClick={() => setOpen((o) => !o)}
        style={{ width: "100%", height: 24, display: "flex", alignItems: "center",
                 gap: SPACE[8], padding: `0 ${SPACE[12]}px`, cursor: "pointer",
                 background: "var(--bg3)",
                 border: `1px solid ${open ? "var(--borderStr)" : "var(--border)"}`,
                 borderRadius: RADIUS.pill, fontFamily: FONT, fontSize: TYPE.label,
                 fontWeight: W.nav,
                 color: current ? "var(--text)" : "var(--textTer)", textAlign: "left",
                 transition: `border-color ${MOTION.hover}` }}>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {current ? current.label : (placeholder || "choose…")}
        </span>
        <CaretDown size={11} weight="bold" style={{ color: "var(--textTer)",
          flex: "none", transform: open ? "rotate(180deg)" : "none",
          transition: `transform ${MOTION.hover}` }} />
      </button>
      {open && pop && createPortal(
        <div role="listbox" aria-label={label} className="px-root px-ov-pop"
          ref={popRef} onKeyDown={onEsc}
          style={{ position: "fixed", left: pop.left, width: pop.width,
                   ...(pop.up ? { bottom: pop.bottom } : { top: pop.top }),
                   transformOrigin: pop.up ? "bottom center" : "top center",
                   zIndex: Z.dropdown, padding: SPACE[4], background: "var(--bg1)",
                   border: "1px solid var(--borderHov)", borderRadius: RADIUS.card,
                   boxShadow: SHADOW.lg, display: "flex", flexDirection: "column",
                   gap: SPACE[4] }}>
          {options.length > 6 && (
            <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="find…" className="px-input" spellCheck={false}
              style={{ width: "100%", height: 28, padding: `0 ${SPACE[8]}px`,
                       background: "var(--bg2)", border: "1px solid var(--border)",
                       borderRadius: RADIUS.input, outline: "none",
                       color: "var(--text)", fontFamily: FONT, fontSize: 12 }} />
          )}
          <div className="px-scroll" style={{ maxHeight: 236, overflowY: "auto",
                        display: "flex", flexDirection: "column" }}>
            {hits.map((opt, index) => {
              const on = opt.id === value;
              const heads = opt.group && opt.group !== hits[index - 1]?.group;
              return (
                <Fragment key={opt.id}>
                {heads && (
                  <span aria-hidden="true" style={{
                    display: "block", padding: `${SPACE[6]}px ${SPACE[8]}px ${SPACE[2]}px`,
                    marginTop: index ? SPACE[4] : 0,
                    borderTop: index ? "1px solid var(--border)" : "none",
                    fontFamily: FONT, fontSize: 9, fontWeight: 600,
                    letterSpacing: "0.1em", textTransform: "uppercase",
                    color: "var(--textMut)", whiteSpace: "nowrap" }}>
                    {opt.group}
                  </span>
                )}
                <button type="button" role="option" aria-selected={on}
                  onClick={() => choose(opt)} title={opt.label}
                  style={{ display: "flex", flexDirection: "column",
                           alignItems: "stretch", gap: 1,
                           padding: `${SPACE[6]}px ${SPACE[8]}px`, textAlign: "left",
                           background: on ? "var(--accentMut)" : "transparent",
                           border: "none", borderRadius: RADIUS.input,
                           cursor: "pointer", fontFamily: FONT }}>
                  <span style={{ fontSize: 12, overflow: "hidden",
                                 textOverflow: "ellipsis", whiteSpace: "nowrap",
                                 color: on ? "var(--accent)" : "var(--text)" }}>
                    {opt.label}
                  </span>
                  {opt.description && (
                    <span style={{ fontSize: 9, color: "var(--textTer)",
                                   overflow: "hidden", textOverflow: "ellipsis",
                                   whiteSpace: "nowrap" }}>
                      {opt.description}
                    </span>
                  )}
                </button>
                </Fragment>
              );
            })}
            {!hits.length && (
              <span style={{ padding: SPACE[8], fontSize: 11, color: "var(--textTer)" }}>
                nothing matches “{q.trim()}”
              </span>
            )}
          </div>
        </div>,
        document.body)}
    </div>
  );
};
