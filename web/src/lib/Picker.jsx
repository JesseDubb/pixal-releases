// The app's dropdown: a button trigger and a listbox popover, with a filter
// box once the list is long. Lifted out of MotionDirector (its model picker)
// on 2026-08-26 so the composer's tuning card could stop using a native
// <select> - Jesse: "make the dropdown work like our other ones".
// options: [{ id, label, description?, group? }] - consecutive options sharing
// a `group` sit under one small inline label (Jesse, 2026-08-26: "little
// inline label break for which sampler its under").
import { Fragment, useEffect, useRef, useState } from "react";
import { CaretDown } from "@phosphor-icons/react";
import { FONT, TYPE, SPACE, RADIUS, MOTION, SHADOW } from "./design-tokens.js";

export const Picker = ({ label, options, value, onChange, placeholder }) => {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const boxRef = useRef(null);
  const inputRef = useRef(null);
  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const away = (e) => { if (!boxRef.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  const current = options.find((opt) => opt.id === value);
  const needle = q.trim().toLowerCase();
  const hits = options.filter((opt) => !needle ||
    `${opt.label} ${opt.description || ""}`.toLowerCase().includes(needle));
  const choose = (opt) => { onChange(opt.id); setOpen(false); setQ(""); };
  return (
    <div ref={boxRef} style={{ position: "relative" }}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); setQ(""); }
      }}>
      <button type="button" aria-haspopup="listbox" aria-expanded={open}
        aria-label={label} title={current ? current.label : label}
        onClick={() => setOpen((o) => !o)}
        style={{ width: "100%", height: 28, display: "flex", alignItems: "center",
                 gap: SPACE[8], padding: `0 ${SPACE[10]}px`, cursor: "pointer",
                 background: "var(--bg2)",
                 border: `1px solid ${open ? "var(--borderStr)" : "var(--border)"}`,
                 borderRadius: RADIUS.input, fontFamily: FONT, fontSize: TYPE.ui,
                 color: "var(--text)", textAlign: "left",
                 transition: `border-color ${MOTION.hover}` }}>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {current ? current.label : (placeholder || "choose…")}
        </span>
        <CaretDown size={11} weight="bold" style={{ color: "var(--textTer)",
          flex: "none", transform: open ? "rotate(180deg)" : "none",
          transition: `transform ${MOTION.hover}` }} />
      </button>
      {open && (
        <div role="listbox" aria-label={label} className="px-ov-pop"
          style={{ position: "absolute", left: 0, right: 0, top: "calc(100% + 6px)",
                   transformOrigin: "top center",
                   zIndex: 5, padding: SPACE[4], background: "var(--bg1)",
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
        </div>
      )}
    </div>
  );
};
