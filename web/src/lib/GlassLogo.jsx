// GlassLogo.jsx — the ComfyUI mark as a chamfered candy-glass puck, live in Three.js.
// A beveled rounded-square slab of blue glass (transmission + clearcoat) with the
// yellow C glyph floating inside it. Idle slow spin; tilts toward the pointer when
// the mouse comes near (window-level proximity, not just hover); drag to spin with
// inertia. Env reflections are baked from a tiny procedural scene so the highlights
// sit in the app's own palette — no external HDRI (CSP-safe, fully local).
//
// Perf rules (2026-08-15, after the puck was measured as the reason a focused
// window cost ~10x on render times). This is the app's only real WebGL, and a
// `transmission` material is the expensive kind: three.js renders the whole
// scene into an offscreen target and builds its mipmap chain BEFORE the visible
// pass, every single frame. Worse than its own cost, a canvas that never stops
// animating pins Chrome's compositor and DWM to the display refresh, so the
// desktop's graphics pipeline never idles and CUDA is preempted forever.
// Measured on an RTX 5090 with nothing else running: window minimised 0.5% GPU
// / 79W, window focused 9.1% GPU / 109W. That 30W was this file.
//
// So the loop is gated four ways, and a stopped loop is a CANCELLED rAF - an
// early-returning callback still wakes the page 60 times a second:
//   calm     - a render is in flight, so CUDA gets the whole card
//   hidden   - minimised or backgrounded (this was the ONLY gate before)
//   blurred  - another window owns the screen; nobody is watching the spin
//   settled  - the pointer has been still a while; it holds its last frame
// Any pointer movement wakes it, so it stays alive whenever the app is in use.
import { useEffect, useRef, useState } from "react";
import { loadThree } from "./three-loader.js";
import { C_PATHS } from "./comfyui-c-path.js";

// The candy palette: ComfyUI brand blue for the glass; the C in ComfyUI's own
// logo yellow (sampled from the .ico: #F0FF41). The app's chartreuse stays on
// the pin light / env so the puck still sits in the app palette.
const GLASS_BLUE = 0x2b3cf0;
const CHARTREUSE = 0xd6f32f;
const COMFY_YELLOW = 0xf0ff41;

// 30fps for a drift this slow is indistinguishable from 60 and costs half.
// Interaction (drag, or the pointer close enough to tilt it) lifts the cap so
// the puck still answers the hand at full rate - that part is the fun.
const FRAME_MS = 33;
// Pointer quiet for this long and the puck settles: it keeps its last frame and
// the loop stops. Any movement anywhere in the window wakes it again.
const SETTLE_MS = 6000;

const roundedRectShape = (THREE, w, h, r) => {
  const s = new THREE.Shape();
  const x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y);
  s.absarc(x + w - r, y + r, r, -Math.PI / 2, 0);
  s.lineTo(x + w, y + h - r);
  s.absarc(x + w - r, y + h - r, r, 0, Math.PI / 2);
  s.lineTo(x + r, y + h);
  s.absarc(x + r, y + h - r, r, Math.PI / 2, Math.PI);
  s.lineTo(x, y + r);
  s.absarc(x + r, y + r, r, Math.PI, Math.PI * 1.5);
  return s;
};

// A little lightbox to bake reflections from: one big cool key overhead, a warm
// amber card on the right (the lamp), a faint blue fill left. Baked once via PMREM.
const buildEnvScene = (THREE) => {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x05090c);
  const panel = (rgb, w, h, pos, rot) => {
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ color: new THREE.Color().setRGB(...rgb), side: THREE.DoubleSide }),
    );
    m.position.set(...pos); m.rotation.set(...rot);
    scene.add(m);
  };
  panel([7, 7, 7.5], 6, 2.4, [0, 4, 0], [Math.PI / 2, 0, 0]);          // cool key above
  panel([3.4, 3.9, 0.6], 2.2, 5, [4, 0.4, 1], [0, -Math.PI / 2.6, 0]); // chartreuse card right
  panel([0.7, 1.1, 2.6], 2.6, 4, [-4, -0.5, 0.5], [0, Math.PI / 2.4, 0]); // blue fill left
  panel([0.9, 0.9, 1.0], 5, 1.2, [0, -3.4, 1.5], [-Math.PI / 2.4, 0, 0]); // floor bounce
  return scene;
};

export const GlassLogo = ({ size = 46, calm = false }) => {
  const hostRef = useRef(null);
  // `calm` rides a ref, never the effect deps: rebuilding the scene on every
  // job start would recompile shaders and re-bake the PMREM env map mid-render,
  // which is the exact GPU spike the freeze exists to avoid.
  const calmRef = useRef(calm);
  const syncRef = useRef(null);
  calmRef.current = calm;
  // THREE is a runtime import now, not bundled: it lands one beat after
  // mount from /vendor/ (service-worker precached). The sized box below
  // renders empty until then; the scene effect re-runs when it arrives.
  const [THREE, setTHREE] = useState(null);
  useEffect(() => {
    let live = true;
    loadThree().then((m) => { if (live) setTHREE(m); }).catch(() => {});
    return () => { live = false; };
  }, []);
  useEffect(() => { syncRef.current && syncRef.current(); }, [calm]);

  useEffect(() => {
    const host = hostRef.current;
    if (!THREE || !host || typeof WebGL2RenderingContext === "undefined") return undefined;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(size, size);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    renderer.domElement.style.cssText =
      "display:block;width:100%;height:100%;cursor:grab;touch-action:none;";
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 30);
    camera.position.set(0, 0, 7.2);

    const pmrem = new THREE.PMREMGenerator(renderer);
    const envScene = buildEnvScene(THREE);
    scene.environment = pmrem.fromScene(envScene, 0.06).texture;

    const group = new THREE.Group();
    scene.add(group);

    // The chamfered slab. Bevel = the chamfer; five segments rounds it to candy.
    const slabGeo = new THREE.ExtrudeGeometry(roundedRectShape(THREE, 2.3, 2.3, 0.62), {
      depth: 0.42, bevelEnabled: true, bevelThickness: 0.16, bevelSize: 0.15,
      bevelSegments: 5, curveSegments: 28,
    });
    slabGeo.center();
    const slab = new THREE.Mesh(slabGeo, new THREE.MeshPhysicalMaterial({
      color: GLASS_BLUE, metalness: 0, roughness: 0.07,
      transmission: 1, thickness: 1.4, ior: 1.5, attenuationDistance: 6,
      attenuationColor: new THREE.Color(GLASS_BLUE),
      clearcoat: 1, clearcoatRoughness: 0.05,
      iridescence: 0.3, iridescenceIOR: 1.3, envMapIntensity: 1.25,
      specularIntensity: 1,
    }));
    group.add(slab);

    // The C as real geometry — inset enamel: the traced glyph outline
    // (comfyui-c-path.js, baked from the .ico) is extruded with a bevel and
    // set so its FACE sits just proud of the slab's front surface while the
    // beveled walls stay inside the glass. The face must clear the surface —
    // any blue glass over it filters the yellow toward black (complementary),
    // which is exactly the dark-C bug this position fixes.
    const SCALE = 1.17;
    const cShape = new THREE.Shape(
      C_PATHS[0].pts.map(([x, y]) => new THREE.Vector2(x * SCALE, y * SCALE)));
    const glyphGeo = new THREE.ExtrudeGeometry(cShape, {
      depth: 0.10, bevelEnabled: true, bevelThickness: 0.055, bevelSize: 0.045,
      bevelSegments: 2, curveSegments: 4,
    });
    const glyphMat = new THREE.MeshStandardMaterial({
      color: COMFY_YELLOW, roughness: 0.32, metalness: 0,
      emissive: COMFY_YELLOW, emissiveIntensity: 0.34, envMapIntensity: 1.1,
    });
    const glyph = new THREE.Mesh(glyphGeo, glyphMat);
    glyph.position.z = 0.23;   // face at ~0.385, just proud of the ~0.37 surface
    group.add(glyph);

    // A pin light that follows the pointer a little, so proximity visibly answers.
    const pin = new THREE.PointLight(CHARTREUSE, 0, 12, 2);
    pin.position.set(0, 0, 3);
    scene.add(pin);

    // ---- interaction state -------------------------------------------------
    // Reduced motion opens on the composed still instead of the drift, and its
    // idle velocity is zero, so the settle gate below stops it after one frame.
    let rotY = reduced ? -0.45 : -0.5, velY = reduced ? 0 : 0.004;
    let tiltX = reduced ? -0.12 : 0, tiltY = 0;
    let targetTiltX = tiltX, targetTiltY = 0;
    let near = 0, targetNear = 0;
    let dragging = false, lastX = 0, lastY = 0, raf = 0, t = 0;
    let running = false, last = 0, awake = 0;

    const PROX_RADIUS = 230;
    const onMove = (e) => {
      awake = performance.now();
      if (!reduced) {
        const r = renderer.domElement.getBoundingClientRect();
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        const dx = e.clientX - cx, dy = e.clientY - cy;
        const dist = Math.hypot(dx, dy);
        const s = Math.max(0, 1 - dist / PROX_RADIUS);
        targetNear = s;
        targetTiltY = (dx / PROX_RADIUS) * s * 0.55;
        targetTiltX = (dy / PROX_RADIUS) * s * 0.55;
        pin.position.set(dx / 60, -dy / 60, 2.6);
      }
      if (dragging) {
        velY = (e.clientX - lastX) * 0.011;
        targetTiltX += (e.clientY - lastY) * 0.004;
        lastX = e.clientX; lastY = e.clientY;
      }
      sync();
    };
    const onDown = (e) => {
      dragging = true; lastX = e.clientX; lastY = e.clientY; awake = performance.now();
      renderer.domElement.setPointerCapture(e.pointerId);
      renderer.domElement.style.cursor = "grabbing";
      sync();
    };
    const onUp = (e) => {
      dragging = false; awake = performance.now();
      try { renderer.domElement.releasePointerCapture(e.pointerId); } catch { /* gone */ }
      renderer.domElement.style.cursor = "grab";
      sync();
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    renderer.domElement.addEventListener("pointerdown", onDown);
    window.addEventListener("pointerup", onUp);

    const IDLE = reduced ? 0 : 0.004;

    // May the puck touch the GPU at all right now? Interaction always wins;
    // otherwise it must be visible, focused, out of calm, and recently poked.
    const wanted = (now) => {
      if (dragging) return true;
      // Reduced motion has no drift and no bob, so every extra frame would be
      // byte-identical to the last one: compose the still and stop.
      if (reduced) return false;
      if (calmRef.current || document.hidden || !document.hasFocus()) return false;
      return now - awake < SETTLE_MS;
    };

    const draw = (now) => {
      // Interaction gets every frame it asks for; the ambient drift is capped.
      const busy = dragging || near > 0.01;
      if (!busy && now - last < FRAME_MS) return;
      // Real elapsed, not the cap: interaction lifts the cap to 60fps, and a
      // fixed step would run the bob at double speed the moment you touch it.
      // Clamped so waking from a settle eases in rather than jumping.
      const dt = last ? Math.min(now - last, 100) : FRAME_MS;
      last = now;
      t += dt / 1000;
      // inertia decays back to the idle drift, never to a dead stop
      if (!dragging) velY = IDLE + (velY - IDLE) * 0.955;
      rotY += velY;
      tiltX += (targetTiltX - tiltX) * 0.12;
      tiltY += (targetTiltY - tiltY) * 0.12;
      near += (targetNear - near) * 0.1;
      group.rotation.set(tiltX, rotY + tiltY, 0);
      group.position.y = reduced ? 0 : Math.sin(t * 1.3) * 0.045;
      group.scale.setScalar(1 + near * 0.07);
      pin.intensity = near * 9;
      slab.material.envMapIntensity = 1.25 + near * 0.9;
      renderer.render(scene, camera);
    };

    const frame = (now) => {
      if (!wanted(now)) { running = false; raf = 0; return; }   // stop, don't spin
      raf = requestAnimationFrame(frame);
      draw(now);
    };

    // The one way the loop starts or stops. Idempotent, so every wake path
    // (pointer, focus, visibility, calm lifting) can just call it.
    function sync() {
      const now = performance.now();
      if (wanted(now)) {
        if (!running) { running = true; last = 0; raf = requestAnimationFrame(frame); }
      } else if (running) {
        cancelAnimationFrame(raf); running = false; raf = 0;
      }
    }
    syncRef.current = sync;

    // Compose the opening frame once, so a puck that never wakes is still drawn.
    group.rotation.set(tiltX, rotY, 0);
    renderer.render(scene, camera);
    awake = performance.now();
    sync();

    const onVis = () => sync();
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("focus", onVis);
    window.addEventListener("blur", onVis);

    return () => {
      cancelAnimationFrame(raf);
      syncRef.current = null;
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("focus", onVis);
      window.removeEventListener("blur", onVis);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("pointerdown", onDown);
      slabGeo.dispose(); glyphGeo.dispose();
      slab.material.dispose(); glyphMat.dispose();
      envScene.traverse((o) => { o.geometry && o.geometry.dispose(); o.material && o.material.dispose(); });
      pmrem.dispose(); renderer.dispose();
      host.contains(renderer.domElement) && host.removeChild(renderer.domElement);
    };
  }, [size, THREE]);

  return (
    <div ref={hostRef} title="ComfyUI"
      style={{ width: size, height: size, flexShrink: 0, userSelect: "none" }} />
  );
};
