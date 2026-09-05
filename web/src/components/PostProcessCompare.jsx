import { useEffect, useRef, useState } from "react";
import { ArrowsLeftRight, DownloadSimple } from "@phosphor-icons/react";
import { FONT, TYPE, RADIUS, SPACE } from "../lib/design-tokens.js";
import { imgUrl } from "../transport.js";
import { finishChips } from "../lib/names.js";
import { originalImage, wipePosition, clampView, zoomAt } from "../lib/image-compare.js";

// One fixed viewport, two identical content transforms, one untransformed mask.
// Pointer movement writes only a CSS variable; it never re-renders the chat.
export function PostProcessCompare({ image, onDims, onZoom, maxWidth = "88vw" }) {
  const original = originalImage(image);
  const [compare, setCompare] = useState(true);
  const [status, setStatus] = useState("loading");
  const [view, setView] = useState({ s: 1, x: 0, y: 0 });
  const [keyboard, setKeyboard] = useState(false);
  const viewport = useRef(null);
  const baseImage = useRef(null);
  const beforeImage = useRef(null);
  const range = useRef(null);
  const drag = useRef(null);
  const moved = useRef(false);
  const viewRef = useRef(view);
  const position = useRef(50);
  const show = compare && status === "ready";
  const chain = finishChips({ finish: image.finish }, { details: true });
  const checkPair = () => {
    const a = baseImage.current, b = beforeImage.current;
    if (!a?.naturalWidth || !b?.naturalWidth) return;
    setStatus(a.naturalWidth === b.naturalWidth && a.naturalHeight === b.naturalHeight
      ? "ready" : "missing");
  };

  const moveWipe = (value) => {
    position.current = value;
    viewport.current?.style.setProperty("--wipe", `${value}%`);
    if (range.current) range.current.value = value;
  };
  const pointWipe = (event) => {
    const r = viewport.current.getBoundingClientRect();
    moveWipe(wipePosition(event.clientX, r.left, r.width));
  };
  const applyView = (next) => {
    viewRef.current = next;
    setView(next);
    onZoom?.(next.s);
  };
  useEffect(() => {
    const el = viewport.current;
    const wheel = (event) => {
      event.preventDefault();
      const r = el.getBoundingClientRect();
      const v = viewRef.current;
      applyView(zoomAt(v, v.s * Math.exp(-event.deltaY * 0.0015),
        event.clientX - r.left - r.width / 2, event.clientY - r.top - r.height / 2,
        r.width, r.height));
    };
    el.addEventListener("wheel", wheel, { passive: false });
    const resize = new ResizeObserver(() => {
      const v = viewRef.current;
      applyView(clampView(el.clientWidth, el.clientHeight, v.s, v.x, v.y));
    });
    resize.observe(el);
    return () => { el.removeEventListener("wheel", wheel); resize.disconnect(); };
  }, []);
  const endDrag = (event) => {
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const transform = `translate(${view.x}px, ${view.y}px) scale(${view.s})`;
  const button = {
    display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 36, padding: "6px 10px", border: "none", borderRadius: RADIUS.pill,
    background: "var(--bg3)", color: "var(--text)", fontFamily: FONT,
    fontSize: TYPE.label, cursor: "pointer", textDecoration: "none",
  };
  return <div className="px-post-compare" onClick={(e) => e.stopPropagation()}
    style={{ display: "flex", flexDirection: "column", alignItems: "stretch", gap: SPACE[8], maxWidth }}>
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
      <button type="button" aria-pressed={compare} disabled={status === "missing"}
        onClick={() => { setCompare((v) => !v); drag.current = null; }}
        style={{ ...button, marginRight: "auto", color: compare ? "var(--accent)" : "var(--text)" }}>
        <ArrowsLeftRight size={16} /> Compare
      </button>
      {status !== "missing" && <a href={imgUrl(original)} download={original.filename}
        aria-label="Save original" style={button}><DownloadSimple size={15} /> Original</a>}
      <a href={imgUrl(image)} download={image.filename} aria-label="Save processed" style={button}>
        <DownloadSimple size={15} /> Processed
      </a>
    </div>
    <div ref={viewport} className="px-compare-viewport" style={{
      position: "relative", overflow: "hidden", borderRadius: RADIUS.card,
      touchAction: "none", lineHeight: 0, cursor: show ? "ew-resize" : "zoom-in",
      outline: keyboard ? "2px solid var(--accent)" : undefined, outlineOffset: 3,
    }}
      onClick={(e) => {
        if (moved.current) { moved.current = false; return; }
        if (show) return;
        const r = viewport.current.getBoundingClientRect();
        const v = viewRef.current;
        applyView(zoomAt(v, v.s > 1 ? 1 : 2.5, e.clientX - r.left - r.width / 2,
          e.clientY - r.top - r.height / 2, r.width, r.height));
      }}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        moved.current = false;
        e.currentTarget.setPointerCapture(e.pointerId);
        // Touch drags always wipe in Compare. Mouse drag pans when zoomed;
        // hovering continues to wipe, so there is no competing drag gesture.
        drag.current = { x: e.clientX, y: e.clientY,
          pan: viewRef.current.s > 1 && (e.pointerType === "mouse" || !show) };
        if (show && !drag.current.pan) pointWipe(e);
      }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (d) {
          const dx = e.clientX - d.x, dy = e.clientY - d.y;
          if (Math.abs(dx) + Math.abs(dy) > 2) moved.current = true;
          d.x = e.clientX; d.y = e.clientY;
          if (d.pan) {
            const el = viewport.current, v = viewRef.current;
            applyView(clampView(el.clientWidth, el.clientHeight, v.s, v.x + dx, v.y + dy));
            return;
          }
        }
        if (show && (e.pointerType === "mouse" || d)) pointWipe(e);
      }}
      onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={() => { drag.current = null; }}>
      <img ref={baseImage} src={imgUrl(image)} alt="Processed render" draggable={false}
        onLoad={(e) => { onDims?.(`${e.currentTarget.naturalWidth}×${e.currentTarget.naturalHeight}`); checkPair(); }}
        style={{ display: "block", maxWidth, maxHeight: "76vh", transform }} />
      {compare && status !== "missing" && <div className="px-compare-original" style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        visibility: show ? "visible" : "hidden", clipPath: "inset(0 calc(100% - var(--wipe, 50%)) 0 0)",
      }}>
        <img ref={beforeImage} src={imgUrl(original)} alt="Original render before post processing" draggable={false}
          onLoad={checkPair} onError={() => setStatus("missing")}
          style={{ width: "100%", height: "100%", objectFit: "fill", transform }} />
      </div>}
      {show && <>
        <div aria-hidden="true" style={{ position: "absolute", insetBlock: 0,
          left: "var(--wipe, 50%)", width: 1, background: "#fff", pointerEvents: "none",
          boxShadow: "0 0 3px rgba(0,0,0,.6)" }}>
          <div style={{ position: "absolute", top: "50%", left: 0, transform: "translate(-50%,-50%)",
            width: 30, height: 38, borderRadius: 20, background: "rgba(15,18,19,.9)", color: "#fff",
            display: "grid", placeItems: "center", border: "1px solid rgba(255,255,255,.6)" }}>
            <ArrowsLeftRight size={17} />
          </div>
        </div>
        {["Original", "Processed"].map((label, i) => <span key={label} style={{
          position: "absolute", top: 12, [i ? "right" : "left"]: 12,
          padding: "6px 9px", background: "rgba(15,18,19,.82)", color: "#fff",
          borderRadius: RADIUS.pill, fontFamily: FONT, fontSize: TYPE.label, lineHeight: 1.2,
          pointerEvents: "none",
        }}>{label}</span>)}
      </>}
      {show && <input ref={range} type="range" min="0" max="100" step="1" defaultValue={position.current}
        aria-label="Original image reveal" onChange={(e) => moveWipe(Number(e.target.value))}
        onKeyDown={(e) => { if (e.key !== "Escape") e.stopPropagation(); }}
        onFocus={() => setKeyboard(true)} onBlur={() => setKeyboard(false)}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", margin: 0,
          opacity: 0, pointerEvents: "none" }} />}
    </div>
    <div role="status" style={{ fontFamily: FONT, fontSize: TYPE.label, color: "var(--textSec)",
      lineHeight: 1.5, maxWidth, overflowWrap: "anywhere" }}>
      {status === "missing" ? "Original unavailable — processed image is safe."
        : compare && status === "loading" ? "Loading original…" : chain.join(" · ")}
    </div>
  </div>;
}
