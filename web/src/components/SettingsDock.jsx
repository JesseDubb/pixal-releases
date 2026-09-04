import { useRef, useState } from "react";
import { SETTINGS, settingsWidth } from "../lib/settings-layout.js";

const WIDTH_KEY = "pixal.settings.width";

export const useSettingsDock = (viewport) => {
  const [preferred, setPreferred] = useState(() => {
    try { return Number(localStorage.getItem(WIDTH_KEY)) || SETTINGS.defaultWidth; }
    catch { return SETTINGS.defaultWidth; }
  });
  const [resizing, setResizing] = useState(false);
  const drag = useRef(null);
  const width = settingsWidth(preferred, viewport);
  const remember = (value) => {
    const next = settingsWidth(value, viewport);
    setPreferred(next);
    try { localStorage.setItem(WIDTH_KEY, String(next)); } catch { /* private mode */ }
  };
  const handle = <div className="px-settings-resize" role="separator" tabIndex={0}
    aria-label="Resize settings" aria-orientation="vertical"
    aria-valuemin={SETTINGS.minWidth} aria-valuemax={settingsWidth(SETTINGS.maxWidth, viewport)}
    aria-valuenow={width} title="Drag to resize · Double-click to reset"
    onDoubleClick={() => remember(SETTINGS.defaultWidth)}
    onPointerDown={(e) => {
      if (e.button !== 0) return;
      e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
      drag.current = { x: e.clientX, width }; setResizing(true);
    }}
    onPointerMove={(e) => {
      if (drag.current) setPreferred(settingsWidth(drag.current.width + e.clientX - drag.current.x, viewport));
    }}
    onPointerUp={(e) => {
      if (!drag.current) return;
      remember(drag.current.width + e.clientX - drag.current.x);
      drag.current = null; setResizing(false); e.currentTarget.releasePointerCapture(e.pointerId);
    }}
    onLostPointerCapture={() => { drag.current = null; setResizing(false); }}
    onKeyDown={(e) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      e.preventDefault(); remember(e.key === "Home" ? SETTINGS.defaultWidth
        : e.key === "End" ? SETTINGS.maxWidth : width + (e.key === "ArrowRight" ? 24 : -24));
    }} />;
  return { width, resizing, handle };
};

// transitions-dev / 01-card-resize. Kept verbatim, with its own variables
// and reduced-motion guard; pointer dragging itself has no interpolation.
export const SettingsDockStyle = () => <style>{`
:root {
  --resize-dur: 300ms;
  --resize-ease: cubic-bezier(0.22, 1, 0.36, 1);
}
.t-resize {
  transition:
    width  var(--resize-dur) var(--resize-ease),
    height var(--resize-dur) var(--resize-ease);
  will-change: width, height;
}
@media (prefers-reduced-motion: reduce) {
  .t-resize { transition: none !important; }
}
.px-settings-resize { position:absolute; top:28px; bottom:28px; right:0; width:12px; cursor:col-resize; touch-action:none; outline:none; }
.px-settings-resize::after { content:""; position:absolute; width:2px; height:44px; top:calc(50% - 22px); left:5px; background:var(--borderStr); border-radius:2px; }
.px-settings-resize:hover::after,.px-settings-resize:focus-visible::after { background:var(--accent); }
`}</style>;
