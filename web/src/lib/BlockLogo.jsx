// BlockLogo.jsx — the block P as black glass, live in Three.js. This is the
// getpixal.com mark (site/index.html, mountMark) brought home, 2026-08-25:
// onyx glass body with the house recipe (transmission + clearcoat + a touch
// of iridescence), and the chip breathing between the ComfyUI yellow and a
// dark neon green - never through white, because chartreuse IS the band.
//
// The perf note that made the app drop glass still stands and is still
// honoured: `transmission` was MEASURED at ~30W of a 5090, because three.js
// renders the whole scene to an offscreen target and rebuilds its mipmaps
// before every visible pass. That cost is per FRAME DRAWN, and this loop
// draws almost none: it settles and stops six seconds after the pointer
// leaves (a stopped loop is a CANCELLED rAF), it goes `calm` while a render
// samples (NavRail passes it), and the loading screen only shows while
// ComfyUI boots - nothing is sampling then. On screen and idle it costs
// nothing; the 30W only exists while a hand is on it.
//
// Geometry stays the cheap one: arcs flattened in block-mark.js (steps by
// size - 6 at the 132px loading mark where facets read, 2 at the rail where
// they never do), bevelSegments 3/2, no floor, no glow, no pin light. The
// env is three flat panels baked ONCE at mount (PMREM is a one-off).
//
// The four loop gates and the cancelled-rAF discipline are lifted verbatim from
// GlassLogo, because that part was never the problem - it is the fix.
import { useEffect, useRef, useState } from "react";
import { loadThree } from "./three-loader.js";
import { blockShapes } from "./block-mark.js";

const BODY = 0x0b0b0e;      // onyx: black glass reads on charcoal by its rim
const CHIP_HI = 0xf0ff41;   // the comfyui-dark.svg yellow
const CHIP_LO = 0x66770b;   // the signal, pulled dark

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
// already being drawn, this only changes how far it turns in it. The site's
// marks turn faster per place - the loading mark means "busy" - so the drift
// is a prop and these are its two shipped values.
const DRIFT = 0.013;
export const RAIL_DRIFT = 0.045;
export const BOOT_DRIFT = 0.085;

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

export const BlockLogo = ({ size = 46, calm = false, drift = DRIFT }) => {
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
    // Never below 2: on a 1x display the canvas would rasterize at its CSS
    // size and no MSAA rescues a 54px raster. 2x is supersampling there.
    renderer.setPixelRatio(Math.min(Math.max(window.devicePixelRatio || 1, 2), 3));
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
    // Facets only read at the loading size; the rail takes the cheap arcs.
    const fine = size >= 100;
    const { hull, chip } = blockShapes(THREE, { steps: fine ? 6 : 2, size: 2.4 });
    const extrude = (shape, depth, bevel) => new THREE.ExtrudeGeometry(shape, {
      depth, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel,
      bevelSegments: fine ? 3 : 2, curveSegments: 1,   // arcs are pre-flattened
    });

    const bodyGeo = extrude(hull, 0.34, 0.07);
    bodyGeo.center();
    const bodyMat = new THREE.MeshPhysicalMaterial({
      color: BODY, metalness: 0, roughness: 0.07,
      transmission: 0.9, thickness: 1.2, ior: 1.5,
      attenuationColor: new THREE.Color(0x101204), attenuationDistance: 1.6,
      clearcoat: 1, clearcoatRoughness: 0.05,
      iridescence: 0.25, iridescenceIOR: 1.3, envMapIntensity: 1.35,
      // Glass shows its own interior: without DoubleSide the inner walls of
      // the bubble cutout are culled and the mark reads hollow from most angles.
      side: THREE.DoubleSide,
    });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    group.add(body);

    // The chip is the one bright thing. Unlit and toneMapped:false so ACES
    // cannot desaturate the brand chartreuse toward white - the same fix the
    // hero mark needed. It breathes between its two anchors in draw().
    const chipHi = new THREE.Color(CHIP_HI), chipLo = new THREE.Color(CHIP_LO);
    const chipGeo = extrude(chip, 0.30, 0.05);
    chipGeo.center();
    const chipMat = new THREE.MeshBasicMaterial({
      color: CHIP_HI, toneMapped: false, side: THREE.DoubleSide });
    const chipMesh = new THREE.Mesh(chipGeo, chipMat);
    // Both geometries are centred on their own bbox, so their front faces land
    // at depth/2 + bevel: 0.24 for the body, 0.20 for the chip. Nudging by 0.04
    // makes them exactly COPLANAR - the one value guaranteed to z-fight. Clear
    // the body's face properly instead.
    chipMesh.position.z = 0.12;
    group.add(chipMesh);

    let rotY = reduced ? -0.4 : -0.45, velY = reduced ? 0 : drift;
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

    const IDLE = reduced ? 0 : drift;

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
      // yellow to a darker neon green on a ~5s cycle, never through white
      chipMat.color.lerpColors(chipLo, chipHi, 0.5 + 0.5 * Math.sin(t * 1.25));
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
  }, [size, drift, THREE]);

  return (
    <div ref={hostRef} title="Pixal"
      style={{ width: size, height: size, flexShrink: 0, userSelect: "none" }} />
  );
};
