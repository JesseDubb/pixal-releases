// EditDirector.jsx — the dialog behind every Edit click. Two lanes share it:
// no mask sends the instruction verbatim to Qwen-Image-Edit (whole frame);
// painting a mask routes the edit to Klein inpaint, where only the painted
// pixels resample. The mask is exported at the source's natural resolution as
// a white-on-black PNG (white = edit here) — the /api/edit contract — and a
// crop uploads a client-side cutout so the model works the region at full
// working resolution.
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowCounterClockwise, ArrowUUpLeft, Crop, Eraser, ImageSquare,
         MagnifyingGlass, PaintBrush, PencilSimple, X } from "@phosphor-icons/react";
import { upload } from "../transport.js";
import { FONT, TYPE, SPACE, RADIUS, MOTION, SHADOW, W } from "../lib/design-tokens.js";
import { ModalShell } from "../lib/ModalShell.jsx";

// Concrete verbs the model responds to, phrased as the user would type them.
const EXAMPLES = [
  "make her jacket red",
  "remove the text",
  "change the background to a snowy street",
  "make it night time",
];
// The masked lane is where a render with one flaw gets rescued. Klein repaints
// only the painted pixels, so the instruction names what should BE there, not
// what is wrong - "five fingers", never "fix the hand".
const EXAMPLES_MASK = [
  "a natural relaxed hand, five fingers",
  "clean skin, same lighting",
  "sharp, even eyes looking at camera",
  "empty background, nothing here",
  "legible sign that reads OPEN",
];
// Mask plus reference is the swap: the painted area is redrawn FROM the
// attached image. Same rule as EXAMPLES_MASK - name what should be there,
// and name which part of the attachment it comes from.
const EXAMPLES_MASK_REF = [
  "her face from the reference image, same lighting",
  "the jacket from the reference image",
  "the hairstyle from the reference image",
  "the logo from the reference image, following the fabric",
];
const ZOOM_MAX = 8;
const BRUSH_MIN = 4, BRUSH_MAX = 128;
const UNDO_DEPTH = 12;
const STAGE_HELP = "scroll to zoom · space-drag or middle-drag to pan · "
                 + "[ ] brush size · ctrl+z undoes a stroke";
// With a reference attached the instruction points at it as "image 2" — that
// exact phrase is what the encoder was trained on, so the examples model it.
const EXAMPLES_REF = [
  "put the logo from image 2 on her shirt",
  "paint image 2 on the wall as a mural",
  "print the logo from image 2 on the billboard",
];

const toolBtn = (active) => ({
  display: "inline-flex", alignItems: "center", gap: SPACE[4],
  height: 28, padding: `0 ${SPACE[10]}px`, cursor: "pointer",
  border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
  borderRadius: RADIUS.pill,
  background: active ? "var(--accentMut)" : "transparent",
  color: active ? "var(--accent)" : "var(--textSec)",
  fontFamily: FONT, fontSize: 12, whiteSpace: "nowrap",
  transition: `border-color ${MOTION.hover}, color ${MOTION.hover}`,
});

export const EditDirector = ({ onClose, onAction, available = true, missing = [],
                               imageUrl = "", kleinAvailable = true,
                               kleinMissing = [] }) => {
  const [instruction, setInstruction] = useState("");
  const [tool, setTool] = useState("paint");
  const [brush, setBrush] = useState(36);
  const [hasMask, setHasMask] = useState(false);
  const [crop, setCrop] = useState(null);          // natural-px {x,y,w,h}
  const [imgDims, setImgDims] = useState(null);    // natural size once loaded
  const [busy, setBusy] = useState(false);
  const [refImg, setRefImg] = useState(null);      // input name of image 2
  const [refErr, setRefErr] = useState("");
  const refFile = useRef(null);
  const taRef = useRef(null);
  const imgRef = useRef(null);
  const viewRef = useRef(null);                    // on-screen overlay canvas
  const maskRef = useRef(null);                    // natural-res mask strokes
  const tintRef = useRef(null);                    // natural-res tint scratch
  const drag = useRef(null);
  // Zoom and pan. A flaw is forty pixels of a megapixel frame shown at half
  // height, so the stage zooms around the cursor (wheel) and pans (space-drag
  // or middle-drag). The transform is a ref, applied straight to the style:
  // a wheel tick must not re-render the dialog. `zoom` is only the readout.
  const stageRef = useRef(null);                   // the clipped window
  const innerRef = useRef(null);                   // the transformed img+canvas
  const viewT = useRef({ z: 1, tx: 0, ty: 0 });
  const pan = useRef(null);
  const spaceHeld = useRef(false);
  const [zoom, setZoom] = useState(1);
  const [panning, setPanning] = useState(false);
  // A brush ring under the pointer; canvas-space coordinates, ref-only.
  const hover = useRef(null);
  // Undo is a stack of mask snapshots taken before each stroke - a 2 MP mask
  // is 8 MB, so the depth is capped rather than unbounded.
  const undoRef = useRef([]);
  const [canUndo, setCanUndo] = useState(false);
  useEffect(() => { taRef.current?.focus(); }, []);

  const text = instruction.trim();
  const masked = hasMask && !!imgDims;
  const laneOk = masked ? kleinAvailable : available;
  const laneMissing = masked ? kleinMissing : missing;

  // Pointer position in the mask's natural coordinates. The overlay canvas is
  // the img's box exactly (the rect is post-transform, so zoom is already in
  // it), so one scale factor covers both axes' mapping. `scale` also keeps
  // the brush a screen-pixel size: zoomed in, the stroke gets finer.
  const toNatural = (e) => {
    const box = viewRef.current.getBoundingClientRect();
    const sx = imgDims.w / box.width, sy = imgDims.h / box.height;
    return { x: (e.clientX - box.left) * sx, y: (e.clientY - box.top) * sy,
             scale: (sx + sy) / 2 };
  };
  // Pointer position in the overlay canvas's own pixels (layout size, never
  // the zoomed size) plus the screen->canvas ratio for the ring's radius.
  const toCanvas = (e) => {
    const view = viewRef.current;
    const box = view.getBoundingClientRect();
    const k = view.width / box.width;
    return { x: (e.clientX - box.left) * k, y: (e.clientY - box.top) * k, k };
  };

  const applyView = () => {
    const inner = innerRef.current, stage = stageRef.current;
    if (!inner || !stage) return;
    const v = viewT.current;
    const W = stage.clientWidth, H = stage.clientHeight;
    // The frame always covers the window: no empty stage past an edge.
    v.tx = Math.min(0, Math.max(W - W * v.z, v.tx));
    v.ty = Math.min(0, Math.max(H - H * v.z, v.ty));
    if (v.z === 1) { v.tx = 0; v.ty = 0; }
    inner.style.transform = `translate(${v.tx}px, ${v.ty}px) scale(${v.z})`;
  };
  const resetView = () => {
    viewT.current = { z: 1, tx: 0, ty: 0 };
    applyView();
    setZoom(1);
  };
  // Wheel zooms about the cursor. Registered by hand: React's onWheel is
  // passive, and a passive listener cannot stop the dialog body scrolling.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || !imgDims) return;
    const onWheel = (e) => {
      e.preventDefault();
      const v = viewT.current;
      const rect = stage.getBoundingClientRect();
      const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
      const nz = Math.min(ZOOM_MAX, Math.max(1, v.z * Math.exp(-e.deltaY * 0.0015)));
      const r = nz / v.z;
      v.tx = cx - (cx - v.tx) * r;
      v.ty = cy - (cy - v.ty) * r;
      v.z = nz;
      applyView();
      setZoom(Math.round(nz * 10) / 10);
    };
    stage.addEventListener("wheel", onWheel, { passive: false });
    return () => stage.removeEventListener("wheel", onWheel);
  }, [imgDims]);

  // Keyboard: space holds pan, [ ] size the brush, ctrl+z undoes a stroke.
  // The textarea keeps its own keys - typing a bracket must stay typing.
  useEffect(() => {
    const typing = (e) => /^(TEXTAREA|INPUT)$/.test(e.target?.tagName || "");
    const down = (e) => {
      if (e.key === "z" && (e.ctrlKey || e.metaKey) && !typing(e)) {
        e.preventDefault(); undo(); return;
      }
      if (typing(e)) return;
      if (e.key === " " && !spaceHeld.current) {
        e.preventDefault(); spaceHeld.current = true; setPanning(true);
      } else if (e.key === "[" || e.key === "]") {
        e.preventDefault();
        setBrush((b) => Math.min(BRUSH_MAX, Math.max(BRUSH_MIN, b + (e.key === "]" ? 4 : -4))));
      }
    };
    const up = (e) => {
      if (e.key === " ") { spaceHeld.current = false; setPanning(false); pan.current = null; }
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  });

  const redraw = () => {
    const view = viewRef.current;
    if (!view || !imgDims) return;
    const ctx = view.getContext("2d");
    ctx.clearRect(0, 0, view.width, view.height);
    const tint = tintRef.current;
    if (tint) {
      // Recolor the white strokes on the scratch canvas so the overlay reads
      // as "this will repaint" rather than hiding the pixels under it.
      const tctx = tint.getContext("2d");
      tctx.globalCompositeOperation = "source-over";
      tctx.clearRect(0, 0, tint.width, tint.height);
      tctx.drawImage(maskRef.current, 0, 0);
      tctx.globalCompositeOperation = "source-in";
      tctx.fillStyle = "rgba(235, 84, 84, 0.5)";
      tctx.fillRect(0, 0, tint.width, tint.height);
      ctx.drawImage(tint, 0, 0, view.width, view.height);
    }
    if (crop) {
      const kx = view.width / imgDims.w, ky = view.height / imgDims.h;
      const r = { x: crop.x * kx, y: crop.y * ky, w: crop.w * kx, h: crop.h * ky };
      ctx.fillStyle = "rgba(0, 0, 0, 0.55)";
      ctx.fillRect(0, 0, view.width, r.y);
      ctx.fillRect(0, r.y + r.h, view.width, view.height - r.y - r.h);
      ctx.fillRect(0, r.y, r.x, r.h);
      ctx.fillRect(r.x + r.w, r.y, view.width - r.x - r.w, r.h);
      // A canvas context has no element to resolve CSS custom properties
      // against, so "var(--accent)" is silently ignored and the rect keeps the
      // initial #000000 - black on the dark scrim, effectively invisible.
      // Resolve the token against the mounted canvas itself.
      ctx.strokeStyle =
        getComputedStyle(view).getPropertyValue("--accent").trim() || "#D6F32F";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(r.x, r.y, r.w, r.h);
    }
    // The brush ring: the exact footprint of the next stroke, in canvas
    // pixels (brush is a screen size, k converts it). Hidden while panning.
    const h = hover.current;
    if (h && !pan.current && (tool === "paint" || tool === "erase")) {
      ctx.beginPath();
      ctx.arc(h.x, h.y, (brush / 2) * h.k, 0, Math.PI * 2);
      ctx.strokeStyle = tool === "erase" ? "rgba(255,255,255,0.9)" : "rgba(235,84,84,0.95)";
      ctx.lineWidth = 1.25 * h.k;
      ctx.stroke();
    }
  };

  const onImgLoad = () => {
    const img = imgRef.current;
    const dims = { w: img.naturalWidth, h: img.naturalHeight };
    setImgDims(dims);
    const mk = document.createElement("canvas");
    mk.width = dims.w; mk.height = dims.h;
    maskRef.current = mk;
    const tn = document.createElement("canvas");
    tn.width = dims.w; tn.height = dims.h;
    tintRef.current = tn;
  };

  // The on-screen canvas tracks the img's LAID-OUT size - offsetWidth, never
  // the bounding rect, which grows with the zoom and would make an 8x view an
  // 8x canvas. CSS scales the overlay with the frame; cheap enough to sync on
  // every render since the dialog is fixed-width.
  useEffect(() => {
    const img = imgRef.current, view = viewRef.current;
    if (!img || !view || !imgDims) return;
    view.width = Math.max(1, img.offsetWidth);
    view.height = Math.max(1, img.offsetHeight);
    redraw();
  });

  // "Is anything painted" from a 64px thumbnail, never megapixel image data.
  const probeMask = () => {
    const probe = document.createElement("canvas");
    probe.width = probe.height = 64;
    probe.getContext("2d").drawImage(maskRef.current, 0, 0, 64, 64);
    const a = probe.getContext("2d").getImageData(0, 0, 64, 64).data;
    for (let i = 3; i < a.length; i += 4) if (a[i] > 0) return true;
    return false;
  };

  const undo = () => {
    const snap = undoRef.current.pop();
    if (!snap || !maskRef.current) return;
    maskRef.current.getContext("2d").putImageData(snap, 0, 0);
    setCanUndo(undoRef.current.length > 0);
    setHasMask(probeMask());
    redraw();
  };

  const strokeAny = useRef(false);
  const down = (e) => {
    if (!imgDims) return;
    e.preventDefault();
    viewRef.current.setPointerCapture(e.pointerId);
    // Pan: the middle button, or any button while space is held.
    if (e.button === 1 || spaceHeld.current) {
      const v = viewT.current;
      pan.current = { x: e.clientX, y: e.clientY, tx: v.tx, ty: v.ty };
      hover.current = null;
      redraw();
      return;
    }
    if (e.button !== 0) return;
    const p = toNatural(e);
    if (tool === "crop") { drag.current = { x0: p.x, y0: p.y }; return; }
    const ctx = maskRef.current.getContext("2d");
    undoRef.current.push(ctx.getImageData(0, 0, maskRef.current.width, maskRef.current.height));
    if (undoRef.current.length > UNDO_DEPTH) undoRef.current.shift();
    setCanUndo(true);
    ctx.lineCap = ctx.lineJoin = "round";
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = brush * p.scale;
    ctx.globalCompositeOperation = tool === "erase" ? "destination-out" : "source-over";
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(p.x + 0.01, p.y + 0.01);   // a click with no move still dots
    ctx.stroke();
    drag.current = { x0: p.x, y0: p.y };
    strokeAny.current = true;
    redraw();
  };
  const move = (e) => {
    if (!imgDims) return;
    if (pan.current) {
      const v = viewT.current, o = pan.current;
      v.tx = o.tx + (e.clientX - o.x);
      v.ty = o.ty + (e.clientY - o.y);
      applyView();
      return;
    }
    // The ring follows the pointer whether or not a stroke is in progress.
    hover.current = toCanvas(e);
    if (!drag.current) { redraw(); return; }
    const p = toNatural(e);
    if (tool === "crop") {
      const x = Math.max(0, Math.min(drag.current.x0, p.x));
      const y = Math.max(0, Math.min(drag.current.y0, p.y));
      const w = Math.min(imgDims.w, Math.max(drag.current.x0, p.x)) - x;
      const h = Math.min(imgDims.h, Math.max(drag.current.y0, p.y)) - y;
      if (w > 8 && h > 8) setCrop({ x, y, w, h });
      return;
    }
    const ctx = maskRef.current.getContext("2d");
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    redraw();
  };
  const up = () => {
    if (pan.current) { pan.current = null; redraw(); return; }
    const wasStroke = !!drag.current && tool !== "crop";
    drag.current = null;
    // Erasing can empty the mask again.
    if (wasStroke) setHasMask(probeMask());
  };
  const leave = () => { hover.current = null; redraw(); };

  const clearMask = () => {
    if (!maskRef.current) return;
    const ctx = maskRef.current.getContext("2d");
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, maskRef.current.width, maskRef.current.height);
    undoRef.current = [];
    setCanUndo(false);
    setHasMask(false);
    redraw();
  };

  // White-on-black PNG of the strokes, cut to the crop when one exists —
  // /api/edit reads white as "edit here" and bakes it into the staged alpha.
  const exportMask = () => {
    const r = crop || { x: 0, y: 0, w: imgDims.w, h: imgDims.h };
    const out = document.createElement("canvas");
    out.width = Math.round(r.w); out.height = Math.round(r.h);
    const ctx = out.getContext("2d");
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(maskRef.current, -Math.round(r.x), -Math.round(r.y));
    return out.toDataURL("image/png");
  };

  const exportCrop = () => new Promise((resolve, reject) => {
    const out = document.createElement("canvas");
    out.width = Math.round(crop.w); out.height = Math.round(crop.h);
    out.getContext("2d").drawImage(imgRef.current,
      crop.x, crop.y, crop.w, crop.h, 0, 0, out.width, out.height);
    out.toBlob((b) => b ? resolve(b) : reject(new Error("crop export failed")), "image/png");
  });

  const attachRef = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setBusy(true);
    setRefErr("");
    try { setRefImg((await upload(f)).name); }
    catch (err) { setRefErr(err.message); }
    finally { setBusy(false); }
  };

  const go = async () => {
    if (!text || !laneOk || busy) return;
    setBusy(true);
    try {
      const extra = {};
      // A mask and a reference together is the face/garment swap: paint the
      // region, attach who or what goes in it. Both lanes take a reference
      // now, so neither one drops the other's attachment.
      if (refImg) extra.reference = refImg;
      if (masked) extra.mask = exportMask();
      if (imgDims && crop) extra.cropBlob = await exportCrop();
      onAction(text, extra);
      onClose();
    } finally { setBusy(false); }
  };

  const lane = useMemo(() => {
    if (masked) return refImg
      ? "the painted area is redrawn from the attached image · Klein inpaint"
      : "only the painted area redraws · Klein inpaint";
    if (refImg) return "your words can point at the attached image as “image 2”";
    if (crop) return "edits just the cropped region";
    return "keeps the frame, changes what you name";
  }, [masked, crop, refImg]);

  return (
    <ModalShell onClose={onClose}
      boxProps={{ role: "dialog", "aria-label": "Edit this image" }}
      boxStyle={{
        // Wide enough for a landscape frame, tall enough that a portrait one
        // reaches the bottom edge at a paintable size (Jesse, 2026-08-25:
        // "it needs to show the entire image so I can paint to the edge").
        width: imageUrl ? "min(1100px, 94vw)" : 480, maxWidth: "94vw", maxHeight: "92vh",
        overflowY: "auto",
        background: "var(--bg1)", border: "1px solid var(--borderHov)",
        borderRadius: 20, boxShadow: SHADOW.xl, padding: SPACE[20],
        display: "flex", flexDirection: "column", gap: SPACE[12], fontFamily: FONT,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: SPACE[8] }}>
          <PencilSimple size={17} weight="duotone" style={{ color: "var(--accent)" }} />
          <span style={{ fontSize: TYPE.h3, fontWeight: W.heading, color: "var(--text)" }}>
            Edit this image
          </span>
          <button type="button" onClick={onClose} title="close"
            style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center",
                     justifyContent: "center", width: 30, height: 30,
                     background: "var(--bg2)", border: "1px solid var(--border)",
                     borderRadius: RADIUS.pill, color: "var(--textTer)", cursor: "pointer" }}>
            <X size={14} weight="bold" />
          </button>
        </div>

        {!laneOk ? (
          <div role="alert" style={{ fontSize: TYPE.ui, lineHeight: 1.5, color: "#E3A7B0" }}>
            {masked ? "Klein inpaint is unavailable." : "Qwen Image Edit is unavailable."}
            {laneMissing.length > 0 && (
              <ul style={{ margin: `${SPACE[6]}px 0 0`, paddingLeft: SPACE[16] }}>
                {laneMissing.map((item) => <li key={item}>{item}</li>)}
              </ul>
            )}
          </div>
        ) : null}

        {imageUrl && (
          <>
            {/* The stage clips; the inner box carries the zoom transform.
                Transforms do not affect layout, so the stage keeps the
                frame's 1x size however far the view is zoomed in. */}
            <div ref={stageRef} title={STAGE_HELP}
                 onContextMenu={(e) => e.preventDefault()}
                 style={{ position: "relative", alignSelf: "center", maxWidth: "100%",
                          overflow: "hidden", borderRadius: RADIUS.card,
                          lineHeight: 0 }}>
              <div ref={innerRef}
                   style={{ position: "relative", transformOrigin: "0 0",
                            willChange: zoom > 1 ? "transform" : "auto" }}>
                <img ref={imgRef} src={imageUrl} alt="edit source" onLoad={onImgLoad}
                     draggable={false}
                     style={{ display: "block", maxWidth: "100%",
                              // the modal's 92vh minus its chrome (header, tools,
                              // prompt row, footer ~ 300px); never below 40vh
                              maxHeight: "max(40vh, calc(92vh - 300px))",
                              userSelect: "none" }} />
                <canvas ref={viewRef}
                  onPointerDown={down} onPointerMove={move}
                  onPointerUp={up} onPointerCancel={up} onPointerLeave={leave}
                  style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
                           touchAction: "none",
                           cursor: !imgDims ? "default"
                             : panning ? "grab"
                             : tool === "crop" ? "crosshair" : "none" }} />
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                          flexWrap: "wrap" }}>
              <button type="button" style={toolBtn(tool === "paint")}
                      onClick={() => setTool("paint")} title="paint the area to redraw">
                <PaintBrush size={13} weight="bold" /> paint
              </button>
              <button type="button" style={toolBtn(tool === "erase")}
                      onClick={() => setTool("erase")} title="erase painted mask">
                <Eraser size={13} weight="bold" /> erase
              </button>
              <button type="button" style={toolBtn(tool === "crop")}
                      onClick={() => setTool("crop")} title="drag a crop rectangle">
                <Crop size={13} weight="bold" /> crop
              </button>
              <label title="brush size" style={{ display: "inline-flex",
                       alignItems: "center", gap: SPACE[6], fontFamily: FONT,
                       fontSize: 10, color: "var(--textTer)",
                       textTransform: "uppercase", letterSpacing: "0.08em" }}>
                brush
                <input type="range" min={BRUSH_MIN} max={BRUSH_MAX} value={brush}
                       onChange={(e) => setBrush(+e.target.value)}
                       style={{ width: 90, accentColor: "var(--accent)" }} />
              </label>
              <button type="button" style={{ ...toolBtn(false), opacity: canUndo ? 1 : 0.45 }}
                      disabled={!canUndo} onClick={undo} title="undo the last stroke (ctrl+z)">
                <ArrowUUpLeft size={13} weight="bold" /> undo
              </button>
              <button type="button" style={{ ...toolBtn(false), fontVariantNumeric: "tabular-nums",
                                             opacity: zoom > 1 ? 1 : 0.6 }}
                      disabled={zoom <= 1} onClick={resetView}
                      title={zoom > 1 ? `back to 1x · ${STAGE_HELP}` : STAGE_HELP}>
                <MagnifyingGlass size={13} weight="bold" /> {zoom.toFixed(1)}x
              </button>
              <button type="button" style={toolBtn(false)} onClick={() => {
                clearMask(); setCrop(null); resetView();
              }} title="clear mask, crop and zoom">
                <ArrowCounterClockwise size={13} weight="bold" /> reset
              </button>
            </div>
          </>
        )}

        <textarea
          ref={taRef} value={instruction} rows={3}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); }
          }}
          placeholder={masked
            ? "What should be there instead? “a natural relaxed hand, five fingers”"
            : "What should change? Say it plainly - the words go to the\n" +
              "editor exactly as typed. “make her jacket red”"}
          className="px-input"
          style={{
            width: "100%", resize: "none", background: "var(--bg2)",
            border: "1px solid var(--border)", borderRadius: RADIUS.card,
            outline: "none", color: "var(--text)", fontFamily: FONT, fontSize: 13,
            lineHeight: 1.5, padding: SPACE[10],
          }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                      flexWrap: "wrap" }}>
          <input ref={refFile} type="file" accept="image/*" hidden
                 onChange={attachRef} />
          {!refImg ? (
            <button type="button" style={toolBtn(false)}
                    onClick={() => refFile.current?.click()}
                    title={masked ? "attach the face or garment that goes in the painted area"
                                  : "attach a logo or reference the words can point at"}>
              <ImageSquare size={13} weight="bold" /> add logo / reference
            </button>
          ) : (
            <span title={refImg} style={{ ...toolBtn(true), cursor: "default",
                    maxWidth: 240 }}>
              <ImageSquare size={13} weight="bold" />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}>{refImg}</span>
              <button type="button" onClick={() => setRefImg(null)}
                      title="remove reference image"
                      style={{ display: "inline-flex", padding: 0, border: "none",
                               background: "transparent", color: "inherit",
                               cursor: "pointer" }}>
                <X size={11} weight="bold" />
              </button>
            </span>
          )}
          {refErr && (
            <span role="alert" style={{ fontSize: TYPE.label, color: "#E3A7B0" }}>
              {refErr}
            </span>
          )}
        </div>

        {/* Examples follow the lane: masked = what goes INSIDE the paint. */}
        <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                      flexWrap: "wrap" }}>
            <span style={{ width: "100%", fontSize: 10, color: "var(--textTer)",
                           textTransform: "uppercase", letterSpacing: "0.08em" }}>
              for example
            </span>
            {(masked ? (refImg ? EXAMPLES_MASK_REF : EXAMPLES_MASK)
                     : refImg ? EXAMPLES_REF : EXAMPLES).map((item) => (
              <button key={item} type="button" onClick={() => setInstruction(item)}
                style={{
                  padding: `${SPACE[4]}px ${SPACE[10]}px`, cursor: "pointer",
                  border: "1px solid var(--border)", borderRadius: RADIUS.pill,
                  background: "transparent", color: "var(--textSec)",
                  fontFamily: FONT, fontSize: 12, whiteSpace: "nowrap",
                  transition: `border-color ${MOTION.hover}, color ${MOTION.hover}`,
                }}>{item}</button>
            ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: SPACE[8] }}>
          <span style={{ fontSize: TYPE.label, color: "var(--textTer)",
                         whiteSpace: "nowrap", overflow: "hidden",
                         textOverflow: "ellipsis" }} title={lane}>
            {lane}
          </span>
          <button type="button" onClick={go} disabled={!text || !laneOk || busy}
            style={{
              marginLeft: "auto", height: 34, padding: `0 ${SPACE[16]}px`,
              border: `1px solid ${text && laneOk ? "var(--accent)" : "var(--border)"}`,
              borderRadius: RADIUS.pill,
              background: text && laneOk ? "var(--accentMut)" : "transparent",
              color: text && laneOk ? "var(--accent)" : "var(--textTer)",
              fontFamily: FONT, fontSize: 13,
              cursor: text && laneOk && !busy ? "pointer" : "default",
            }}>{busy ? "…" : "edit"}</button>
        </div>
    </ModalShell>
  );
};
