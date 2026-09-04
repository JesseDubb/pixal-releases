// DotMatrix.jsx — the generation preview as a living dot matrix. The sidecar
// reduces each ComfyUI sampling preview to a tiny luminance grid; this renders
// it as pulsing dots, so you watch the image's STRUCTURE breathe into existence
// without ever seeing the pixels. Before the first frame arrives the field
// breathes with a coherent idle wave, and each new frame eases in (no pops).
//
// Built to be liftable into other projects of mine, so the perf rules are strict:
// one canvas, one pre-rendered dot sprite (drawImage, never per-dot arc+fill),
// Float32Array state, ~30fps cap, zero allocations inside the loop.
import { useEffect, useRef } from "react";

const WARM = "244,246,240";   // paper-neutral dot
const BLOOM = "214,243,47";   // the chartreuse accent — emerges in the highlights

const makeSprite = (rgb) => {
  const s = document.createElement("canvas");
  s.width = s.height = 64;
  const c = s.getContext("2d");
  const g = c.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, `rgba(${rgb},1)`);
  g.addColorStop(0.55, `rgba(${rgb},0.55)`);
  g.addColorStop(1, `rgba(${rgb},0)`);
  c.fillStyle = g;
  c.fillRect(0, 0, 64, 64);
  return s;
};

const decode = (b64) => Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));

// `fill` — cover the positioned parent edge to edge instead of holding an
// aspect. A tile that already IS 3/4 and then puts a 3/4 canvas inside its
// own padding letterboxes twice, which is the un-dotted margin Jesse saw
// around the edit veil ("the dot effect isnt even covering the full frame",
// 2026-09-04). The loop measures with getBoundingClientRect, so a
// height-driven box needs nothing else.
export const DotMatrix = ({ preview, aspect = "9 / 16", fill = false }) => {
  const canvasRef = useRef(null);
  const gridRef = useRef(null);    // { cols, rows, target: Float32Array }

  // Ingest frames without restarting the render loop. Same-size frames just
  // swap targets; the easing in the loop does the morph.
  useEffect(() => {
    if (!preview || !preview.data) return;
    const bytes = decode(preview.data);
    const g = gridRef.current;
    if (g && g.cols === preview.cols && g.rows === preview.rows) {
      for (let i = 0; i < bytes.length; i++) g.target[i] = bytes[i] / 255;
      g.rev++;                       // wake the loop out of its settled hold
    } else {
      gridRef.current = {
        cols: preview.cols, rows: preview.rows, rev: 1,
        target: Float32Array.from(bytes, (v) => v / 255),
      };
    }
  }, [preview]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext("2d");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const warm = makeSprite(WARM);
    const bloom = makeSprite(BLOOM);

    let cur = null, phase = null, curN = 0;
    let raf = 0, last = 0;
    // Settle-and-stop: once a live frame has finished easing in, the canvas
    // holds it untouched (zero compositor work - the PhotonField freeze trick)
    // until the next preview bumps `rev`. On slow steps this is most of the
    // render; on a starved GPU it is the difference between a hitch per step
    // and a card that only moves when the image actually changed.
    let seenRev = 0, settled = false;

    const loop = (now) => {
      raf = requestAnimationFrame(loop);
      if (now - last < (reduced ? 250 : 33)) return;   // ~30fps (4fps reduced)
      last = now;

      const rect = canvas.getBoundingClientRect();
      if (!rect.width) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const W = Math.round(rect.width * dpr), H = Math.round(rect.height * dpr);
      if (canvas.width !== W || canvas.height !== H) {
        canvas.width = W; canvas.height = H;
        settled = false;             // the resize blanked the held frame
      }

      const g = gridRef.current;
      if (g && g.rev !== seenRev) { seenRev = g.rev; settled = false; }
      if (g && settled) return;
      // Until the first frame lands, borrow a grid shaped like the canvas.
      const cols = g ? g.cols : 36;
      const rows = g ? g.rows : Math.max(8, Math.round(36 * (H / W)));
      const n = cols * rows;
      if (curN !== n) {
        cur = new Float32Array(n);
        phase = new Float32Array(n);
        for (let i = 0; i < n; i++) phase[i] = ((i * 2654435761) % 6283) / 1000;
        curN = n;
      }

      const cell = Math.min(W / cols, H / rows);
      const ox = (W - cell * cols) / 2 + cell / 2;
      const oy = (H - cell * rows) / 2 + cell / 2;
      const t = now / 1000;

      ctx.clearRect(0, 0, W, H);
      let maxDelta = 0;
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const i = r * cols + c;
          // Idle: a slow coherent wave. Live: the frame's luminance.
          const target = g ? g.target[i]
            : 0.05 + 0.09 * (Math.sin(c * 0.5 + t * 1.1) * Math.sin(r * 0.32 - t * 0.7) + 1) / 2;
          const delta = target - cur[i];
          if (delta > maxDelta) maxDelta = delta;
          else if (-delta > maxDelta) maxDelta = -delta;
          cur[i] += delta * (reduced ? 1 : 0.14);
          const v = cur[i];
          if (v < 0.015) continue;                      // skip the void
          // The pulse is idle-only: while live frames stream, wobbling every
          // dot would keep the canvas dirty forever and defeat the settle.
          const pulse = (g || reduced) ? 1 : 1 + 0.13 * Math.sin(t * 2.1 + phase[i]);
          const rad = cell * 0.62 * (0.16 + 0.9 * v) * pulse;
          const x = ox + c * cell, y = oy + r * cell;
          ctx.globalAlpha = Math.min(1, 0.12 + 0.88 * v);
          ctx.drawImage(warm, x - rad, y - rad, rad * 2, rad * 2);
          // Highlights catch the accent — chartreuse blooms only where it's bright.
          if (v > 0.68) {
            ctx.globalAlpha = (v - 0.68) * 1.6;
            ctx.drawImage(bloom, x - rad, y - rad, rad * 2, rad * 2);
          }
        }
      }
      ctx.globalAlpha = 1;
      if (g && maxDelta < 0.004) settled = true;   // hold this frame until rev moves
    };

    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <canvas ref={canvasRef}
      style={fill
        ? { position: "absolute", inset: 0, width: "100%", height: "100%",
            display: "block", background: "var(--bg0)" }
        : { width: "100%", aspectRatio: aspect, display: "block",
            background: "var(--bg0)", borderRadius: 8 }} />
  );
};
