// BlockLogo.jsx — the block P as a chamfered solid, live in Three.js.
//
// This is the cheap replacement for GlassLogo. Read that file's perf note
// first: the puck was MEASURED at ~30W of a 5090 while merely on screen, and
// the cost was NOT polygon count. It was `transmission`, which makes three.js
// render the whole scene into an offscreen target and rebuild its mipmap chain
// BEFORE the visible pass, every frame. So the savings here are, in order:
//
//   1. no transmission, no clearcoat, no iridescence - MeshStandardMaterial.
//      One forward pass instead of two, and a much shorter shader.
//   2. arcs flattened to 2 segments in block-mark.js instead of
//      curveSegments:14, and bevelSegments 2 instead of 3-5.
//   3. no floor, no glow sprite, no pin light - the env map alone lights it.
//
// The chamfer survives all of that, because a chamfer reads from SHADING, not
// from silhouette. What sells it is a smooth normal across the bevel ring and
// something bright for it to reflect - which is what the baked env is for. The
// env is generated ONCE at mount (PMREM is a one-off, not a per-frame cost);
// dropping it and using lights instead looks flatter for no frame-time win.
//
// The four loop gates and the cancelled-rAF discipline are lifted verbatim from
// GlassLogo, because that part was never the problem - it is the fix.
import { useEffect, useRef, useState } from "react";
import { loadThree } from "./three-loader.js";
import { blockShapes } from "./block-mark.js";

const SIGNAL = 0xd6f32f;
const BODY = 0xe8e7e1;      // warm off-white: the mark has to read on charcoal

const FRAME_MS = 33;        // 30fps; the drift is too slow for 60 to show
// Interaction lifts the cap, but NOT to infinity. Jesse's panel runs at 239Hz,
// so "uncapped" meant 239fps of WebGL for a logo - eight times the frames of
// the idle drift for no visible gain, on the one machine that must keep its GPU
// free for sampling. 60 is already past the point a hand can tell.
const BUSY_FRAME_MS = 16;
const SETTLE_MS = 6000;
// Radians per frame of ambient spin, i.e. what it does when the pointer is
// nowhere near it. At 30fps, 0.013 is a full turn every ~16s; the old 0.004
// took ~52s, which read as standing still. Costs nothing - the frame was
// already being drawn, this only changes how far it turns in it.
const DRIFT = 0.013;

// Three flat panels, baked once. Cheaper and more controllable than an HDRI,
// and CSP-safe because nothing is fetched.
const buildEnvScene = (THREE) => {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x07080a);
  const panel = (rgb, w, h, pos, rot) => {
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color().setRGB(...rgb), side: THREE.DoubleSide,
      }));
    m.position.set(...pos);
    m.rotation.set(...rot);
    scene.add(m);
  };
  panel([6, 6, 6.4], 6, 2.4, [0, 4, 0], [Math.PI / 2, 0, 0]);           // key above
  panel([2.6, 3.1, 0.5], 2.4, 5, [4, 0.4, 1], [0, -Math.PI / 2.6, 0]);  // chartreuse right
  panel([0.5, 0.7, 1.5], 2.6, 4, [-4, -0.5, 0.5], [0, Math.PI / 2.4, 0]); // cool fill left
  return scene;
};

export const BlockLogo = ({ size = 46, calm = false }) => {
  const hostRef = useRef(null);
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
    renderer.toneMappingExposure = 1.1;
    renderer.domElement.style.cssText =
      "display:block;width:100%;height:100%;cursor:grab;touch-action:none;";
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 30);
    camera.position.set(0, 0, 7.4);

    const pmrem = new THREE.PMREMGenerator(renderer);
    const envScene = buildEnvScene(THREE);
    scene.environment = pmrem.fromScene(envScene, 0.05).texture;

    const group = new THREE.Group();
    scene.add(group);

    // bevelSize is the chamfer width. Keep it generous relative to depth - a
    // wide shallow chamfer catches the env across a broad band and reads soft,
    // where a narrow one needs segments to avoid looking like a hard facet.
    const { hull, chip } = blockShapes(THREE, { steps: 2, size: 2.4 });
    const extrude = (shape, depth, bevel) => new THREE.ExtrudeGeometry(shape, {
      depth, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel,
      bevelSegments: 2, curveSegments: 1,   // arcs are pre-flattened, see module
    });

    const bodyGeo = extrude(hull, 0.34, 0.07);
    bodyGeo.center();
    // Low metalness on purpose: at 0.18 against a dark env the body sampled as
    // mid-grey rather than off-white, because a metal has no diffuse term and
    // there is very little in this env for it to reflect.
    const bodyMat = new THREE.MeshStandardMaterial({
      color: BODY, roughness: 0.34, metalness: 0.06, envMapIntensity: 1.35,
    });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    group.add(body);

    // The chip is the one bright thing. Unlit and toneMapped:false so ACES
    // cannot desaturate the brand chartreuse toward white - the same fix the
    // hero mark needed.
    const chipGeo = extrude(chip, 0.30, 0.05);
    chipGeo.center();
    const chipMat = new THREE.MeshBasicMaterial({ color: SIGNAL, toneMapped: false });
    const chipMesh = new THREE.Mesh(chipGeo, chipMat);
    // Both geometries are centred on their own bbox, so their front faces land
    // at depth/2 + bevel: 0.24 for the body, 0.20 for the chip. Nudging by 0.04
    // makes them exactly COPLANAR - the one value guaranteed to z-fight. Clear
    // the body's face properly instead.
    chipMesh.position.z = 0.12;
    group.add(chipMesh);

    let rotY = reduced ? -0.4 : -0.45, velY = reduced ? 0 : DRIFT;
    let tiltX = reduced ? -0.1 : 0, tiltY = 0;
    let targetTiltX = tiltX, targetTiltY = 0;
    let near = 0, targetNear = 0;
    let dragging = false, lastX = 0, lastY = 0, raf = 0, t = 0;
    let running = false, last = 0, awake = 0;

    const PROX_RADIUS = 230;
    const onMove = (e) => {
      awake = performance.now();
      if (!reduced) {
        const r = renderer.domElement.getBoundingClientRect();
        const dx = e.clientX - (r.left + r.width / 2);
        const dy = e.clientY - (r.top + r.height / 2);
        const s = Math.max(0, 1 - Math.hypot(dx, dy) / PROX_RADIUS);
        targetNear = s;
        targetTiltY = (dx / PROX_RADIUS) * s * 0.55;
        targetTiltX = (dy / PROX_RADIUS) * s * 0.55;
      }
      if (dragging) {
        velY = (e.clientX - lastX) * 0.011;
        targetTiltX += (e.clientY - lastY) * 0.004;
        lastX = e.clientX; lastY = e.clientY;
      }
      sync();
    };
    const onDown = (e) => {
      dragging = true; lastX = e.clientX; lastY = e.clientY;
      awake = performance.now();
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

    const IDLE = reduced ? 0 : DRIFT;

    const wanted = (now) => {
      if (dragging) return true;
      if (reduced) return false;
      if (calmRef.current || document.hidden || !document.hasFocus()) return false;
      return now - awake < SETTLE_MS;
    };

    const draw = (now) => {
      const busy = dragging || near > 0.01;
      if (now - last < (busy ? BUSY_FRAME_MS : FRAME_MS)) return;
      const dt = last ? Math.min(now - last, 100) : FRAME_MS;
      last = now;
      t += dt / 1000;
      // Everything below is per-SECOND, expressed as multiples of a 30fps step.
      // It used to be per-FRAME, which tied the spin speed to the refresh rate:
      // the same code drifted at one speed idling and eight times that while the
      // pointer was near, purely because the cap came off.
      const rate = dt / FRAME_MS;
      const ease = (k) => 1 - Math.pow(1 - k, rate);
      if (!dragging) velY = IDLE + (velY - IDLE) * Math.pow(0.955, rate);
      // Proximity still adds a little lift, but a chosen 25% rather than
      // whatever the monitor happened to be doing.
      rotY += velY * rate * (1 + near * 0.25);
      tiltX += (targetTiltX - tiltX) * ease(0.12);
      tiltY += (targetTiltY - tiltY) * ease(0.12);
      near += (targetNear - near) * ease(0.1);
      group.rotation.set(tiltX, rotY + tiltY, 0);
      group.position.y = reduced ? 0 : Math.sin(t * 1.3) * 0.04;
      group.scale.setScalar(1 + near * 0.07);
      bodyMat.envMapIntensity = 1.5 + near * 0.8;
      renderer.render(scene, camera);
    };

    const frame = (now) => {
      if (!wanted(now)) { running = false; raf = 0; return; }
      raf = requestAnimationFrame(frame);
      draw(now);
    };

    function sync() {
      const now = performance.now();
      if (wanted(now)) {
        if (!running) { running = true; last = 0; raf = requestAnimationFrame(frame); }
      } else if (running) {
        cancelAnimationFrame(raf); running = false; raf = 0;
      }
    }
    syncRef.current = sync;

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
      bodyGeo.dispose(); chipGeo.dispose();
      bodyMat.dispose(); chipMat.dispose();
      envScene.traverse((o) => {
        o.geometry && o.geometry.dispose();
        o.material && o.material.dispose();
      });
      pmrem.dispose(); renderer.dispose();
      host.contains(renderer.domElement) && host.removeChild(renderer.domElement);
    };
  }, [size, THREE]);

  return (
    <div ref={hostRef} title="Pixal"
      style={{ width: size, height: size, flexShrink: 0, userSelect: "none" }} />
  );
};
