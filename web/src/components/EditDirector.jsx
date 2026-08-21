// EditDirector.jsx — the dialog behind every Edit click. Two lanes share it:
// no mask sends the instruction verbatim to Qwen-Image-Edit (whole frame);
// painting a mask routes the edit to Klein inpaint, where only the painted
// pixels resample. The mask is exported at the source's natural resolution as
// a white-on-black PNG (white = edit here) — the /api/edit contract — and a
// crop uploads a client-side cutout so the model works the region at full
// working resolution.
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowCounterClockwise, Crop, Eraser, ImageSquare, PaintBrush,
         PencilSimple, X } from "@phosphor-icons/react";
import { upload } from "../transport.js";
import { FONT, TYPE, SPACE, RADIUS, MOTION, SHADOW, W } from "../lib/design-tokens.js";

// Concrete verbs the model responds to, phrased as the user would type them.
const EXAMPLES = [
  "make her jacket red",
  "remove the text",
  "change the background to a snowy street",
  "make it night time",
];
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
  useEffect(() => { taRef.current?.focus(); }, []);

  const text = instruction.trim();
  const masked = hasMask && !!imgDims;
  const laneOk = masked ? kleinAvailable : available;
  const laneMissing = masked ? kleinMissing : missing;

  // Pointer position in the mask's natural coordinates. The overlay canvas is
  // the img's box exactly, so one scale factor covers both axes' mapping.
  const toNatural = (e) => {
    const box = viewRef.current.getBoundingClientRect();
    const sx = imgDims.w / box.width, sy = imgDims.h / box.height;
    return { x: (e.clientX - box.left) * sx, y: (e.clientY - box.top) * sy,
             scale: (sx + sy) / 2 };
  };

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

  // The on-screen canvas tracks the img's laid-out size; cheap enough to sync
  // on every render since the dialog is fixed-width.
  useEffect(() => {
    const img = imgRef.current, view = viewRef.current;
    if (!img || !view || !imgDims) return;
    const box = img.getBoundingClientRect();
    view.width = Math.round(box.width);
    view.height = Math.round(box.height);
    redraw();
  });

  const strokeAny = useRef(false);
  const down = (e) => {
    if (!imgDims) return;
    e.preventDefault();
    viewRef.current.setPointerCapture(e.pointerId);
    const p = toNatural(e);
    if (tool === "crop") { drag.current = { x0: p.x, y0: p.y }; return; }
    const ctx = maskRef.current.getContext("2d");
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
    if (!drag.current || !imgDims) return;
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
    drag.current = null;
    if (tool === "crop") return;
    // Erasing can empty the mask again; a 64px thumbnail answers "is anything
    // painted" without touching megapixel image data.
    const probe = document.createElement("canvas");
    probe.width = probe.height = 64;
    probe.getContext("2d").drawImage(maskRef.current, 0, 0, 64, 64);
    const a = probe.getContext("2d").getImageData(0, 0, 64, 64).data;
    let any = false;
    for (let i = 3; i < a.length; i += 4) if (a[i] > 0) { any = true; break; }
    setHasMask(any);
  };

  const clearMask = () => {
    if (!maskRef.current) return;
    const ctx = maskRef.current.getContext("2d");
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, maskRef.current.width, maskRef.current.height);
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
      // The masked lane can't take a reference; the mask the user painted wins.
      if (refImg && !masked) extra.reference = refImg;
      if (masked) extra.mask = exportMask();
      if (imgDims && crop) extra.cropBlob = await exportCrop();
      onAction(text, extra);
      onClose();
    } finally { setBusy(false); }
  };

  const lane = useMemo(() => {
    if (masked) return refImg
      ? "painted mask wins - the attached image is not sent · Klein inpaint"
      : "only the painted area redraws · Klein inpaint";
    if (refImg) return "your words can point at the attached image as “image 2”";
    if (crop) return "edits just the cropped region";
    return "keeps the frame, changes what you name";
  }, [masked, crop, refImg]);

  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 36, background: "rgba(0,0,0,0.5)" }}
           onClick={onClose} />
      <div role="dialog" aria-label="Edit this image" style={{
        position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
        zIndex: 37, width: imageUrl ? 640 : 480, maxWidth: "94vw", maxHeight: "92vh",
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
            <div style={{ position: "relative", alignSelf: "center", maxWidth: "100%" }}>
              <img ref={imgRef} src={imageUrl} alt="edit source" onLoad={onImgLoad}
                   draggable={false}
                   style={{ display: "block", maxWidth: "100%", maxHeight: "48vh",
                            borderRadius: RADIUS.card, userSelect: "none" }} />
              <canvas ref={viewRef}
                onPointerDown={down} onPointerMove={move}
                onPointerUp={up} onPointerCancel={up}
                style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
                         borderRadius: RADIUS.card, touchAction: "none",
                         cursor: imgDims ? "crosshair" : "default" }} />
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
                <input type="range" min={8} max={96} value={brush}
                       onChange={(e) => setBrush(+e.target.value)}
                       style={{ width: 90, accentColor: "var(--accent)" }} />
              </label>
              <button type="button" style={toolBtn(false)} onClick={() => {
                clearMask(); setCrop(null);
              }} title="clear mask and crop">
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
            ? "What should appear where you painted? “clean hoodie sleeve”"
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
            <button type="button" style={{ ...toolBtn(false),
                      opacity: masked ? 0.5 : 1 }} disabled={masked}
                    onClick={() => refFile.current?.click()}
                    title={masked ? "clear the painted mask first"
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

        {!masked && (
          <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                        flexWrap: "wrap" }}>
            <span style={{ width: "100%", fontSize: 10, color: "var(--textTer)",
                           textTransform: "uppercase", letterSpacing: "0.08em" }}>
              for example
            </span>
            {(refImg ? EXAMPLES_REF : EXAMPLES).map((item) => (
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
        )}
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
      </div>
    </>
  );
};
