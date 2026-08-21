// PhotonField.jsx — the ambient
// dot grid behind the lane: dots brighten and drift away from the cursor, and
// the whole field breathes with a slow coherent wave so it's never fully still.
// Ported from an earlier project of mine; its trace-runner lines were removed
// on request (neat but intense).
// Fixed at z 0, pointer-events none. Honors prefers-reduced-motion by not mounting.
//
// Perf rules (2026-08-11, after the field was caught fighting CUDA for the GPU
// during renders): one pre-rendered dot sprite drawn with drawImage — never
// per-dot arc()+fill(), which rasterized ~8k paths per frame — a ~30fps cap
// (the breath is slow; 60 bought nothing), and a `calm` prop that freezes the
// field entirely while a render is in flight. An unchanged canvas costs the
// compositor nothing, so calm means the app stops touching the GPU exactly
// when ComfyUI needs all of it.
import { useEffect, useRef } from "react";

const DOT_SPACING = 32;
const CURSOR_RADIUS = 140;    // area of effect
const PUSH_STRENGTH = 12;     // how far dots drift from cursor
const FRAME_MS = 33;          // ~30fps — indistinguishable for a slow ambient wave

const makeSprite = (rgb) => {
  const s = document.createElement("canvas");
  s.width = s.height = 32;
  const c = s.getContext("2d");
  const g = c.createRadialGradient(16, 16, 0, 16, 16, 16);
  g.addColorStop(0, `rgba(${rgb},1)`);
  g.addColorStop(0.7, `rgba(${rgb},0.9)`);
  g.addColorStop(1, `rgba(${rgb},0)`);
  c.fillStyle = g;
  c.fillRect(0, 0, 32, 32);
  return s;
};

export const PhotonField = ({ rgb = "238,241,235", calm = false }) => {
  const ref = useRef(null);
  const mouse = useRef({ x: -1000, y: -1000 });
  const calmRef = useRef(calm);
  calmRef.current = calm;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = canvas.getContext("2d");
    const sprite = makeSprite(rgb);
    let raf;
    let last = 0;
    let wasCalm = false;
    let dots = [];      // { homeX, homeY, x, y, activation }

    const buildDots = (w, h) => {
      dots = [];
      const cols = Math.ceil(w / DOT_SPACING) + 1;
      const rows = Math.ceil(h / DOT_SPACING) + 1;
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const hx = c * DOT_SPACING;
          const hy = r * DOT_SPACING;
          dots.push({ homeX: hx, homeY: hy, x: hx, y: hy, activation: 0 });
        }
      }
    };

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      canvas.style.width = window.innerWidth + "px";
      canvas.style.height = window.innerHeight + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildDots(window.innerWidth, window.innerHeight);
    };
    resize();
    window.addEventListener("resize", resize);

    const onMouse = (e) => { mouse.current.x = e.clientX; mouse.current.y = e.clientY; };
    window.addEventListener("mousemove", onMouse);

    const draw = (now) => {
      raf = requestAnimationFrame(draw);
      if (calmRef.current) {
        // Freeze, don't clear: the last frame stays as a static backdrop and
        // the untouched canvas drops out of the compositor's work entirely.
        // Fading the whole field out here would itself be an animation.
        wasCalm = true;
        return;
      }
      if (now - last < FRAME_MS) return;
      last = now;
      if (wasCalm) {
        // Waking from a freeze: the cursor moved on without us, so settle the
        // activation state instead of letting every dot lunge at once.
        wasCalm = false;
        for (const d of dots) d.activation = 0;
      }

      const w = window.innerWidth, h = window.innerHeight;
      const mx = mouse.current.x, my = mouse.current.y;
      const t = now / 1000;
      ctx.clearRect(0, 0, w, h);

      for (const d of dots) {
        const dx = d.homeX - mx, dy = d.homeY - my;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const inRange = dist < CURSOR_RADIUS;

        const targetAct = inRange ? (1 - dist / CURSOR_RADIUS) : 0;
        d.activation += (targetAct - d.activation) * (inRange ? 0.08 : 0.025);

        if (dist > 0.1) {
          const ease = d.activation * d.activation * d.activation;
          const pushX = (dx / dist) * PUSH_STRENGTH * ease;
          const pushY = (dy / dist) * PUSH_STRENGTH * ease;
          d.x += (d.homeX + pushX - d.x) * 0.15;
          d.y += (d.homeY + pushY - d.y) * 0.15;
        } else {
          d.x += (d.homeX - d.x) * 0.08;
          d.y += (d.homeY - d.y) * 0.08;
        }

        // The ambient breath: a slow coherent wave rolls across the field so
        // the grid is alive at rest — amplitude kept a whisper (~±0.03 alpha)
        // so it never competes with the content surface.
        const wave =
          (Math.sin(d.homeX * 0.012 + t * 0.55) *
           Math.sin(d.homeY * 0.010 - t * 0.4) + 1) / 2;

        const bright = 0.02 + wave * 0.055 + d.activation * 0.25;
        const radius = 1 + wave * 0.35 + d.activation * 0.8;
        ctx.globalAlpha = bright;
        ctx.drawImage(sprite, d.x - radius, d.y - radius, radius * 2, radius * 2);
      }
      ctx.globalAlpha = 1;
    };

    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMouse);
    };
  }, [rgb]);

  return (
    <canvas ref={ref} style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }} />
  );
};
