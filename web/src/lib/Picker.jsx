// The app's dropdown: a button trigger and a listbox popover, with a filter
// box once the list is long. Lifted out of MotionDirector (its model picker)
// on 2026-08-26 so the composer's tuning card could stop using a native
// <select> - Jesse: "make the dropdown work like our other ones".
// The trigger is the control family's VALUE PILL (brief 10.0): HEIGHT.rail, bg3,
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
import { FONT, W, TYPE, SPACE, RADIUS, HEIGHT, MOTION, SHADOW, Z } from "./design-tokens.js";
// Trigger-to-popover gap, and the most the box can stand: the 236px list
// cap plus the filter row (HEIGHT.rail + the flex gap), padding and border.
const GAP = 6;
const POP_MAX = 236 + HEIGHT.rail + SPACE[4] + SPACE[4] * 2 + 2;

export const Picker = ({ label, options, value, onChange, placeholder, hug = false }) => {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [pop, setPop] = useState(null);
  const boxRef = useRef(null);
  const popRef = useRef(null);
  const inputRef = useRef(null);
  const triggerRef = useRef(null);
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
      // at 340 and hang its RIGHT edge off the trigger's, since the pill
      // lives on the row's right rail, hard against the panel's edge.
      const w = Math.min(window.innerWidth - 24, hug ? Math.max(r.width, 340) : r.width);
      const left = Math.max(12, Math.min(hug ? r.right - w : r.left, window.innerWidth - w - 12));
      setPop({ left, width: w, up, settings: !!boxRef.current?.closest(".px-settings"),
               maxHeight: Math.max(80, Math.min(236, (up ? above : below) - 54)),
               top: up ? null : r.bottom + GAP,
               bottom: up ? window.innerHeight - r.top + GAP : null });
    };
    place();
    // Away = outside BOTH the trigger and the portal box - the portal is no
    // longer inside boxRef's subtree, so boxRef.contains alone would read
    // every click in the list as an away click and close on choice.
    const away = (e) => {
      if (boxRef.current?.contains(e.target) || popRef.current?.contains(e.target)) return;
      setOpen(false); setQ("");
    };
    const escape = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      e.preventDefault(); e.stopPropagation();
      setOpen(false); setQ(""); triggerRef.current?.focus();
    };
    // Capture-phase scroll catches any ancestor's scroll (the rail, the
    // chain's px-scroll list); a rAF throttle keeps it to one layout a frame.
    let raf = 0;
    const follow = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(place); };
    document.addEventListener("pointerdown", away);
    window.addEventListener("keydown", escape, true);
    window.addEventListener("resize", follow);
    window.addEventListener("scroll", follow, true);
    return () => {
      document.removeEventListener("pointerdown", away);
      window.removeEventListener("keydown", escape, true);
      window.removeEventListener("resize", follow);
      window.removeEventListener("scroll", follow, true);
      cancelAnimationFrame(raf);
    };
  }, [open]);
  // The filter input mounts with the portal box (once `pop` lands), so the
  // focus waits for it in a plain effect - the layout one above runs while
  // the portal's first render is still gated off.
  useEffect(() => {
    if (!open || !pop) return;
    const target = inputRef.current || popRef.current?.querySelector('[aria-selected="true"]')
      || popRef.current?.querySelector('[role="option"]');
    target?.focus({ preventScroll: true });
  }, [open, !!pop]);
  const close = () => { setOpen(false); setQ(""); triggerRef.current?.focus(); };
  const onEsc = (e) => {
    if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); close(); }
  };
  const current = options.find((opt) => opt.id === value);
  const needle = q.trim().toLowerCase();
  const hits = options.filter((opt) => !needle ||
    `${opt.label} ${opt.description || ""} ${opt.group || ""}`.toLowerCase().includes(needle));
  const choose = (opt) => { if (!opt.disabled) { onChange(opt.id); close(); } };
  const navigate = (e) => {
    onEsc(e);
    const options = [...(popRef.current?.querySelectorAll('[role="option"]:not(:disabled)') || [])];
    if (!options.length) return;
    const i = options.indexOf(document.activeElement);
    if (e.key === "Enter" && e.target === inputRef.current) { e.preventDefault(); options[0].click(); return; }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    if (e.target === inputRef.current && ["Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const next = e.key === "Home" ? 0 : e.key === "End" ? options.length - 1
      : i < 0 ? (e.key === "ArrowDown" ? 0 : options.length - 1)
      : (i + (e.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
    options[next].focus();
  };
  return (
    <div ref={boxRef} onKeyDown={onEsc} style={hug ? { width: "fit-content", maxWidth: "var(--picker-max-width, 260px)" } : undefined}>
      <button ref={triggerRef} type="button" aria-haspopup="listbox" aria-expanded={open}
        aria-label={label} title={current ? current.label : label}
        onClick={() => { setQ(""); setOpen((o) => !o); }}
        onKeyDown={(e) => {
          if (["ArrowDown", "ArrowUp"].includes(e.key)) { e.preventDefault(); setOpen(true); }
        }}
        style={{ width: "100%", height: HEIGHT.rail, display: "flex", alignItems: "center",
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
        <div role="listbox" aria-label={label} className="px-root px-picker px-ov-pop"
          data-settings={pop.settings ? "true" : undefined} ref={popRef} onKeyDown={navigate}
          style={{ position: "fixed", left: pop.left, width: pop.width,
                   ...(pop.up ? { bottom: pop.bottom } : { top: pop.top }),
                   transformOrigin: pop.up ? "bottom center" : "top center",
                   zIndex: Z.dropdown, padding: SPACE[4], background: "var(--bg1)",
                   border: "1px solid var(--borderHov)", borderRadius: RADIUS.card,
                   boxShadow: SHADOW.lg, display: "flex", flexDirection: "column",
                   gap: SPACE[4] }}>
          {options.length > 6 && (
            <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Search" aria-label={`Filter ${label}`} className="px-input" spellCheck={false}
              style={{ width: "100%", height: HEIGHT.rail, padding: `0 ${SPACE[8]}px`,
                       background: "var(--bg2)", border: "1px solid var(--border)",
                       borderRadius: RADIUS.input, outline: "none",
                       color: "var(--text)", fontFamily: FONT, fontSize: 12 }} />
          )}
          <div className="px-scroll" style={{ maxHeight: pop.maxHeight, overflowY: "auto",
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
                <button type="button" role="option" aria-selected={on} disabled={opt.disabled}
                  onClick={() => choose(opt)} title={opt.label}
                  style={{ display: "flex", flexDirection: "column",
                           alignItems: "stretch", gap: 1,
                           padding: `${SPACE[8]}px ${SPACE[10]}px`, textAlign: "left",
                           background: on ? "var(--accentMut)" : "transparent",
                           border: "none", borderRadius: RADIUS.input,
                           cursor: "pointer", fontFamily: FONT }}>
                  <span style={{ fontSize: 12, lineHeight: 1.4, overflowWrap: "anywhere",
                                 color: on ? "var(--accent)" : "var(--text)" }}>
                    {opt.label}
                  </span>
                  {opt.description && (
                    <span style={{ fontSize: 10, lineHeight: 1.4, color: "var(--textSec)",
                                   overflowWrap: "anywhere" }}>
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
