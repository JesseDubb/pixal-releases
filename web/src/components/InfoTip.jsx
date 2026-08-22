import { useState, useRef, useCallback, useEffect } from "react";
import { createPortal } from "react-dom";
import { Info } from "@phosphor-icons/react";
import { FONT, TYPE, SPACE, RADIUS, MOTION, LH, SHADOW, Z } from "../lib/design-tokens.js";

// Hover-revealed help tip, ported from desklight's ui/InfoTip.jsx (2026-08-22)
// - the only change is the design-tokens import path. Phosphor Info (duotone)
// icon, accent-colored on hover, tooltip rendered through a portal to
// document.body so it escapes every overflow:hidden ancestor (tables, cards,
// modals). Position is fixed to the icon's bounding rect; horizontal
// placement nudges into view if the centered default would clip the viewport
// edge.
//
// Geometry uses a callback ref + getBoundingClientRect at attach time so
// the measurement happens the moment the portal node enters the DOM —
// no flash, no second render needed.
export const InfoTip = ({ text, size = 14, maxWidth = 260, side = "bottom" }) => {
  const [show, setShow] = useState(false);
  const iconRef = useRef(null);
  const tipNodeRef = useRef(null);
  const [pos, setPos] = useState(null);

  const measure = useCallback(() => {
    const icon = iconRef.current;
    const tip = tipNodeRef.current;
    if (!icon || !tip) return;
    const ir = icon.getBoundingClientRect();
    const tr = tip.getBoundingClientRect();
    const pad = 12;
    const top = side === "top" ? ir.top - tr.height - 6 : ir.bottom + 6;
    let left = ir.left + ir.width / 2 - tr.width / 2;
    if (left + tr.width > window.innerWidth - pad) left = window.innerWidth - pad - tr.width;
    if (left < pad) left = pad;
    setPos({ left, top });
  }, [side]);

  // Callback ref fires synchronously when the portal node mounts/unmounts,
  // so we measure exactly once per show without waiting for a useEffect tick.
  const tipRef = useCallback((node) => {
    tipNodeRef.current = node;
    if (node) measure();
  }, [measure]);

  useEffect(() => {
    if (!show) return;
    const onScroll = () => measure();
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [show, measure]);

  return (
    <span
      ref={iconRef}
      tabIndex={0}
      role="img"
      aria-label={text}
      style={{ display: "inline-flex", alignItems: "center", marginLeft: SPACE[4] }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => { setShow(false); setPos(null); }}
      onFocus={() => setShow(true)}
      onBlur={() => { setShow(false); setPos(null); }}
    >
      <Info
        size={size}
        weight="duotone"
        style={{
          opacity: show ? 1 : 0.55,
          color: show ? "var(--accent)" : "var(--textSec)",
          cursor: "help",
          transition: `color ${MOTION.hover}, opacity ${MOTION.hover}`,
        }}
      />
      {show && createPortal(
        <div
          ref={tipRef}
          style={{
            position: "fixed",
            left: pos ? pos.left : -9999,
            top: pos ? pos.top : -9999,
            background: "var(--bg3)",
            border: "1px solid var(--borderStr)",
            borderRadius: RADIUS.input,
            padding: `${SPACE[8]}px ${SPACE[12]}px`,
            fontSize: TYPE.ui,
            fontFamily: FONT,
            color: "var(--textSec)",
            maxWidth: `${maxWidth}px`,
            width: "max-content",
            boxSizing: "border-box",
            lineHeight: LH.body,
            boxShadow: SHADOW.md,
            zIndex: Z.toast,
            pointerEvents: "none",
            whiteSpace: "normal",
            overflowWrap: "anywhere",
          }}
        >
          {text}
        </div>,
        document.body,
      )}
    </span>
  );
};
