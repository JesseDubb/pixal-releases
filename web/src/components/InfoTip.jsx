import { useState, useRef, useCallback, useEffect } from "react";
import { createPortal } from "react-dom";
import { Info } from "@phosphor-icons/react";
import { FONT, TYPE, SPACE, RADIUS, MOTION, LH, SHADOW, Z } from "../lib/design-tokens.js";
import { OverlayMotionStyle } from "../lib/ModalShell.jsx";

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
      // An inline-flex box takes its baseline from its first flex item, and a
      // replaced element's baseline is its BOTTOM edge - so by default the
      // icon stands on the text baseline with its whole body above it. At the
      // sizes this is used (a 14px icon beside 13px Geist, whose cap height is
      // 0.7em = 9.1px) that put the icon's centre ~2.4px above the text's, and
      // every tip in the app read as floating (Jesse, 2026-08-24: "the info
      // bubbles aren't vertically centered with the text beside it").
      //
      // vertical-align takes a LENGTH, which shifts this box's baseline - so
      // ask for the offset that lands the icon's centre on the cap centre:
      // bottom = capHeight/2 - size/2, with 0.35em being half of Geist's cap.
      // In em, so it stays right at every font size the tip is dropped into -
      // the uppercase Field labels are 11px and the section titles 13px.
      style={{ display: "inline-flex", alignItems: "center", marginLeft: SPACE[4],
               verticalAlign: `calc(0.35em - ${size / 2}px)` }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => { setShow(false); setPos(null); }}
      onFocus={() => setShow(true)}
      onBlur={() => { setShow(false); setPos(null); }}
    >
      <OverlayMotionStyle />
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
          // px-root carries the theme. applyThemeCss scopes every token to
          // that class, and document.body sits OUTSIDE it - so without this
          // the tip drew as inherited black on a fully transparent box, with
          // the control it covers showing straight through the text. Exactly
          // the failure ComfyBoot.jsx documents, and Composer.jsx avoids by
          // portalling into .px-root instead. Body plus the class is the
          // safer pair here: the tip still escapes every overflow ancestor,
          // and it stops depending on where in the tree it was mounted.
          className="px-root px-ov-pop"
          style={{
            position: "fixed",
            transformOrigin: side === "top" ? "bottom center" : "top center",
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
