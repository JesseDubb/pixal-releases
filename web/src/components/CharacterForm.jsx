// CharacterForm.jsx — create OR edit a character anchor: who they are (age /
// race / sex / style), the free-form notes that make them THEM, the wardrobe
// lock that closes their captions, and the required reference image (upload or
// pick from ComfyUI/input) that locks their face for Identity Edit. Saved as
// data to pixal_dm/characters/<id>.json.
//
// An anchor is two things: a sentence and a face. The dialog is shaped around
// exactly that — a landscape two-pane modal where the left pane writes the
// sentence (facts, style, notes, and the live caption preview the server
// renders through the same character_subject()/wardrobe_lock_for() the
// builders call) and the right pane picks the face. The wardrobe-lock
// machinery hides behind a disclosure because most anchors ride the generic
// lock; header and save bar stay put while the panes scroll.
import { useEffect, useMemo, useRef, useState } from "react";
// Dashed user-circle = a DRAFT anchor (the character icon family's empty state).
import { Crop, ImageSquare, PencilSimple, UserCircleDashed, X }
  from "@phosphor-icons/react";
import { FONT, W, TYPE, SPACE, RADIUS, OVERLAY } from "../lib/design-tokens.js";
import { Disclosure } from "../lib/Disclosure.jsx";
import { ModalShell } from "../lib/ModalShell.jsx";
import { characterPreview, characterRecord, inputFullUrl, inputImages,
         inputImgUrl, stageInput, upload } from "../transport.js";
import { EditDirector } from "./EditDirector.jsx";

const MONO = "ui-monospace, Consolas, monospace";
// Same three as the reference picker: newest-first alone stops being findable
// the moment the face you want is not from today.
const SORTS = [
  { key: "new", label: "newest" },
  { key: "old", label: "oldest" },
  { key: "name", label: "A–Z" },
];

// `grow` lets one field absorb the pane's spare height (the notes textarea),
// so the left column bottoms out with the picker instead of above it. `hint`
// trails the label in a thin lowercase parenthetical — a long bold uppercase
// label is unreadable, so the label stays one word and the hint stays quiet.
const Field = ({ label, hint, children, grow }) => (
  <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0,
                  flex: grow ? "1 1 auto" : "0 0 auto" }}>
    <span style={{ fontSize: TYPE.micro, fontWeight: W.heading, letterSpacing: "0.08em",
                   textTransform: "uppercase", color: "var(--textTer)",
                   overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          title={hint}>
      {label}
      {hint && <span style={{ fontWeight: W.label, textTransform: "none",
                              letterSpacing: 0 }}> ({hint})</span>}
    </span>
    {children}
  </label>
);

const inputStyle = {
  background: "var(--bg2)", border: "1px solid var(--border)",
  borderRadius: RADIUS.input, padding: `7px ${SPACE[10]}px`, fontSize: TYPE.ui,
  color: "var(--text)", fontFamily: FONT, outline: "none", width: "100%",
};

// The dialog goes side-by-side only when the viewport can afford it; on a
// phone the panes stack and the whole body scrolls as one.
const useNarrow = () => {
  const [narrow, setNarrow] = useState(
    () => window.matchMedia("(max-width: 760px)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 760px)");
    const on = (e) => setNarrow(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
};

const InputCard = ({ image, selected, onPick }) => {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <button type="button" aria-pressed={selected}
      aria-label={`Use ${image.name} as the identity reference`} title={image.name}
      onClick={onPick}
      style={{ minWidth: 0, padding: 4, display: "flex", flexDirection: "column", gap: 4,
               border: "1px solid", borderRadius: RADIUS.input,
               borderColor: selected ? "var(--accent)" : "var(--border)",
               background: selected ? "var(--accentMut)" : "var(--bg2)",
               color: selected ? "var(--accent)" : "var(--textSec)", cursor: "pointer",
               contentVisibility: "auto", containIntrinsicSize: "112px 130px" }}>
      <span style={{ position: "relative", width: "100%", aspectRatio: "1 / 1",
                     display: "flex", alignItems: "center", justifyContent: "center",
                     overflow: "hidden", borderRadius: RADIUS.inner,
                     background: "var(--bg3)", color: "var(--textMut)" }}>
        {!loaded && !failed && <span className="px-thumbload"
          style={{ position: "absolute", inset: 0 }} />}
        {!failed ? (
          <img src={inputImgUrl(image)} alt="" loading="lazy" decoding="async"
            onLoad={() => setLoaded(true)} onError={() => setFailed(true)}
            style={{ width: "100%", height: "100%", objectFit: "cover",
                     opacity: loaded ? 1 : 0 }} />
        ) : <ImageSquare size={22} weight="duotone" aria-hidden="true" />}
      </span>
      <span style={{ width: "100%", overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap", fontFamily: MONO, fontSize: 9,
                     textAlign: "left" }}>
        {image.name.split("/").pop()}
      </span>
    </button>
  );
};

// CropDialog — drag a rectangle over the full-res reference and keep only that
// region. No model runs: the cutout is uploaded as a new input image and
// becomes the identity source, so Identity Edit sees exactly the region that
// matters (it faithfully carries over everything in the frame, accessories
// and background included — cropping is how you leave those behind).
const CropDialog = ({ imageUrl, busy, onClose, onUse }) => {
  const [crop, setCrop] = useState(null);       // natural-px {x,y,w,h}
  const [dims, setDims] = useState(null);
  const imgRef = useRef(null);
  const viewRef = useRef(null);
  const drag = useRef(null);

  const toNatural = (e) => {
    const box = viewRef.current.getBoundingClientRect();
    return { x: (e.clientX - box.left) * (dims.w / box.width),
             y: (e.clientY - box.top) * (dims.h / box.height) };
  };
  const redraw = () => {
    const view = viewRef.current;
    if (!view || !dims) return;
    const ctx = view.getContext("2d");
    ctx.clearRect(0, 0, view.width, view.height);
    if (!crop) return;
    const kx = view.width / dims.w, ky = view.height / dims.h;
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
  };
  useEffect(() => {
    const img = imgRef.current, view = viewRef.current;
    if (!img || !view || !dims) return;
    const box = img.getBoundingClientRect();
    view.width = Math.round(box.width);
    view.height = Math.round(box.height);
    redraw();
  });

  const down = (e) => {
    if (!dims) return;
    e.preventDefault();
    viewRef.current.setPointerCapture(e.pointerId);
    drag.current = toNatural(e);
  };
  const move = (e) => {
    if (!drag.current || !dims) return;
    const p = toNatural(e);
    const x = Math.max(0, Math.min(drag.current.x, p.x));
    const y = Math.max(0, Math.min(drag.current.y, p.y));
    const w = Math.min(dims.w, Math.max(drag.current.x, p.x)) - x;
    const h = Math.min(dims.h, Math.max(drag.current.y, p.y)) - y;
    if (w > 8 && h > 8) setCrop({ x, y, w, h });
  };
  const up = () => { drag.current = null; };

  const use = () => {
    if (!crop || busy) return;
    const out = document.createElement("canvas");
    out.width = Math.round(crop.w); out.height = Math.round(crop.h);
    out.getContext("2d").drawImage(imgRef.current,
      crop.x, crop.y, crop.w, crop.h, 0, 0, out.width, out.height);
    out.toBlob((b) => b && onUse(b), "image/png");
  };

  return (
    <ModalShell onClose={onClose} z={OVERLAY.form}
      boxProps={{ role: "dialog", "aria-label": "Crop the reference" }}
      boxStyle={{
        width: 560, maxWidth: "94vw", maxHeight: "92vh", overflowY: "auto",
        background: "var(--bg1)", border: "1px solid var(--borderHov)",
        borderRadius: RADIUS.dialog, boxShadow: "0 18px 44px rgba(0,0,0,0.6)",
        padding: SPACE[16], display: "flex", flexDirection: "column", gap: SPACE[12],
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: SPACE[6],
                         fontSize: TYPE.h3, fontWeight: W.heading }}>
            <Crop size={15} weight="duotone" style={{ color: "var(--accent)" }} />
            crop the reference
          </span>
          <button type="button" onClick={onClose}
            style={{ background: "none", border: "none", color: "var(--textTer)",
                     cursor: "pointer", padding: 4 }}>
            <X size={14} weight="bold" />
          </button>
        </div>
        <div style={{ position: "relative", alignSelf: "center", maxWidth: "100%" }}>
          <img ref={imgRef} src={imageUrl} alt="crop source" draggable={false}
            onLoad={() => setDims({ w: imgRef.current.naturalWidth,
                                    h: imgRef.current.naturalHeight })}
            style={{ display: "block", maxWidth: "100%", maxHeight: "56vh",
                     borderRadius: RADIUS.card, userSelect: "none" }} />
          <canvas ref={viewRef}
            onPointerDown={down} onPointerMove={move}
            onPointerUp={up} onPointerCancel={up}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
                     borderRadius: RADIUS.card, touchAction: "none",
                     cursor: dims ? "crosshair" : "default" }} />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: SPACE[8] }}>
          <span style={{ fontSize: TYPE.label, color: "var(--textTer)",
                         overflow: "hidden", textOverflow: "ellipsis",
                         whiteSpace: "nowrap" }}>
            {crop ? `${Math.round(crop.w)} × ${Math.round(crop.h)} px`
                  : "drag the region Identity Edit should see"}
          </span>
          <button type="button" onClick={use} disabled={!crop || busy}
            style={{
              marginLeft: "auto", height: 30, padding: `0 ${SPACE[16]}px`,
              fontSize: TYPE.ui, fontWeight: W.heading, color: "#050507",
              background: "var(--accent)", border: "none", borderRadius: RADIUS.input,
              cursor: crop && !busy ? "pointer" : "default",
              opacity: crop && !busy ? 1 : 0.5,
            }}>{busy ? "uploading…" : "use this region"}</button>
        </div>
    </ModalShell>
  );
};

export const CharacterForm = ({ options, onClose, onSaved, refreshOptions,
                                history = [], editInput, editId = "" }) => {
  const [name, setName] = useState("");
  const [age, setAge] = useState("");
  const [race, setRace] = useState("");
  const [sex, setSex] = useState("female");
  const [style, setStyle] = useState("");
  const [notes, setNotes] = useState("");
  const [wardrobe, setWardrobe] = useState("");
  const [wardOpen, setWardOpen] = useState(false);
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState("new");
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(!!editId);
  const [editOpen, setEditOpen] = useState(false);
  const [cropOpen, setCropOpen] = useState(false);
  // Armed when an edit render is in flight for the reference: a snapshot of
  // history ids at launch, so the one entry that appears after it is ours.
  const [pendingEdit, setPendingEdit] = useState(null);
  const narrow = useNarrow();

  // Edit mode: /api/options carries only the picker's summary, so the rest of
  // the record has to be fetched before the fields can be filled.
  useEffect(() => {
    if (!editId) return;
    let live = true;
    characterRecord(editId)
      .then((ch) => {
        if (!live || !ch) return;
        setName(ch.name || "");
        setAge(ch.age == null ? "" : String(ch.age));
        setRace(ch.race || "");
        setSex(ch.sex || "female");
        setStyle(ch.style || "");
        setNotes(ch.notes || "");
        setWardrobe(ch.wardrobe_lock || "");
        // A custom lock is the one thing worth un-hiding on open: they wrote
        // it once, so they should see it is still in force.
        if (ch.wardrobe_lock) setWardOpen(true);
        setRef(ch.identity_ref || "");
      })
      .catch((e) => live && setErr(e?.message || "that anchor could not be loaded"))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [editId]);

  // Debounced so typing a name does not fire a request per keystroke.
  useEffect(() => {
    const ch = { name: name.trim(), sex, style: style.trim(),
                 wardrobe_lock: wardrobe.trim() };
    if (age.trim()) ch.age = parseInt(age, 10) || age.trim();
    if (race.trim()) ch.race = race.trim();
    let live = true;
    const t = setTimeout(() => {
      characterPreview(ch).then((p) => live && setPreview(p)).catch(() => {});
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [name, age, race, sex, style, wardrobe]);

  const inputAll = useMemo(() => inputImages(options), [options]);
  const inputList = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const byName = (a, b) => a.name.localeCompare(b.name);
    const rows = q ? inputAll.filter((i) => i.name.toLowerCase().includes(q))
                   : inputAll.slice();
    return rows.sort(
      sort === "name" ? byName
        : sort === "old" ? (a, b) => (a.mtime || 0) - (b.mtime || 0) || byName(a, b)
          : (a, b) => (b.mtime || 0) - (a.mtime || 0) || byName(a, b));
  }, [inputAll, filter, sort]);
  const refRecord = useMemo(
    () => (ref ? inputAll.find((i) => i.name === ref) || { name: ref } : null),
    [inputAll, ref]);
  const editRecipe = (options?.recipes || []).find((r) => r.id === "qwen_edit");
  const kleinRecipe = (options?.recipes || []).find((r) => r.id === "klein_inpaint");

  // Adopt the edit render the moment it lands: the first edit-lane entry that
  // was not in the launch snapshot is staged back into ComfyUI/input and
  // becomes the reference, closing the edit → reference loop in place.
  useEffect(() => {
    if (!pendingEdit) return undefined;
    const entry = (history || []).find((e) =>
      !pendingEdit.seen.has(e.id) &&
      (e.template === "qwen_edit" || e.template === "klein_inpaint") &&
      (e.images || []).some((i) => (i.media || "image") === "image"));
    if (!entry) return undefined;
    let live = true;
    (async () => {
      try {
        const d = await stageInput(entry.id);
        if (!live) return;
        if (!d?.ok || !d.name)
          throw new Error(d?.error || "the edited reference could not be staged");
        if (refreshOptions) await refreshOptions();
        if (!live) return;
        setRef(d.name);
        setPendingEdit(null);
      } catch (e) {
        if (!live) return;
        setPendingEdit(null);
        setErr(e?.message || "the edited reference could not be adopted");
      }
    })();
    return () => { live = false; };
  }, [history, pendingEdit, refreshOptions]);

  // Saving keys on a slug of the name, so a new anchor named like an existing
  // one silently replaces it. Say so before they press the button.
  const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const clash = !editId && slug
    && (options?.characters || []).find((c) => c.id === slug);

  const doUpload = async (f) => {
    if (!f) return;
    setBusy(true); setErr(null);
    try {
      const image = await upload(f, "identity");
      setRef(image.name);
      if (refreshOptions) await refreshOptions();
    } catch (error) {
      setErr(error?.message || "The reference image could not be uploaded.");
    } finally {
      setBusy(false);
    }
  };

  // The cutout uploads like any attached photo and immediately becomes the
  // reference — cropping never touches the original input image.
  const adoptCrop = async (blob) => {
    setBusy(true); setErr(null);
    try {
      const base = (ref.split("/").pop() || "ref").replace(/\.[^.]+$/, "");
      const file = new File([blob], `pixal_refcrop_${base.slice(0, 48)}.png`,
                           { type: "image/png" });
      const image = await upload(file, "identity");
      if (refreshOptions) await refreshOptions();
      setRef(image.name);
      setCropOpen(false);
    } catch (error) {
      setErr(error?.message || "The cropped reference could not be uploaded.");
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!name.trim()) { setErr("give them a name"); return; }
    if (!ref) { setErr("choose or upload a reference image"); return; }
    setBusy(true); setErr(null);
    const ch = { name: name.trim(), sex, style: style.trim(), notes: notes.trim() };
    if (age.trim()) ch.age = parseInt(age, 10) || age.trim();
    if (race.trim()) ch.race = race.trim();
    if (wardrobe.trim()) ch.wardrobe_lock = wardrobe.trim();
    // The id is what makes this an EDIT rather than a second anchor: without it
    // the server re-slugs the name, and a renamed character forks in two.
    if (editId) ch.id = editId;
    ch.identity_ref = ref;
    try {
      const r = await fetch("/api/characters", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character: ch }) });
      const d = await r.json();
      if (d.ok) { onSaved(d.id); onClose(); }
      else setErr(d.error || "save failed");
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };

  const sectionLabel = {
    fontSize: TYPE.micro, fontWeight: W.heading, letterSpacing: "0.08em",
    textTransform: "uppercase", color: "var(--textTer)",
  };

  return (
    <>
      <ModalShell onClose={onClose} boxStyle={{
        width: "min(880px, 94vw)",
        height: narrow ? "auto" : "min(660px, 88vh)", maxHeight: "88vh",
        background: "var(--bg1)", border: "1px solid var(--borderHov)",
        borderRadius: RADIUS.dialog, boxShadow: "0 18px 44px rgba(0,0,0,0.6)",
        display: "flex", flexDirection: "column", overflow: "hidden",
      }}>
        <div style={{ display: "flex", alignItems: "center",
                      justifyContent: "space-between", flex: "0 0 auto",
                      padding: `${SPACE[12]}px ${SPACE[16]}px`,
                      borderBottom: "1px solid var(--border)" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: SPACE[6],
                         fontSize: TYPE.h3, fontWeight: W.heading }}>
            <UserCircleDashed size={15} weight="duotone" style={{ color: "var(--accent)" }} />
            {editId ? `edit ${name || "anchor"}` : "new character anchor"}
          </span>
          <button type="button" onClick={onClose}
            style={{ background: "none", border: "none", color: "var(--textTer)",
                     cursor: "pointer", padding: 4 }}>
            <X size={14} weight="bold" />
          </button>
        </div>

        <div className={narrow ? "px-scroll" : undefined}
             style={{ flex: "1 1 auto", minHeight: 0, display: "flex",
                      flexDirection: narrow ? "column" : "row",
                      overflowY: narrow ? "auto" : "hidden" }}>

          {/* LEFT — write the sentence: facts, look, notes, and the caption
              they add up to. */}
          <div className={narrow ? undefined : "px-scroll"}
               style={{ flex: narrow ? "0 0 auto" : "1.15 1 0", minWidth: 0,
                        minHeight: 0, overflowY: narrow ? "visible" : "auto",
                        padding: SPACE[16], display: "flex",
                        flexDirection: "column", gap: SPACE[12] }}>
            <div style={{ display: "flex", gap: SPACE[8] }}>
              <div style={{ flex: 2, minWidth: 0 }}><Field label="name">
                <input style={inputStyle} value={name} onChange={(e) => setName(e.target.value)}
                       placeholder="Mia" autoFocus />
              </Field></div>
              <div style={{ flex: 1, minWidth: 0 }}><Field label="age">
                <input style={inputStyle} value={age} onChange={(e) => setAge(e.target.value)}
                       placeholder="24" />
              </Field></div>
            </div>
            <div style={{ display: "flex", gap: SPACE[8] }}>
              <div style={{ flex: 1, minWidth: 0 }}><Field label="race">
                <input style={inputStyle} value={race} onChange={(e) => setRace(e.target.value)}
                       placeholder="Korean" />
              </Field></div>
              <div style={{ flex: 1, minWidth: 0 }}><Field label="sex">
                <div style={{ display: "flex", gap: SPACE[6] }}>
                  {["female", "male", "other"].map((s) => (
                    <button key={s} type="button" onClick={() => setSex(s)}
                      style={{
                        flex: 1, height: 30, fontSize: TYPE.label, cursor: "pointer",
                        borderRadius: RADIUS.input, border: "1px solid",
                        borderColor: sex === s ? "var(--accent)" : "var(--border)",
                        background: sex === s ? "var(--accentMut)" : "transparent",
                        color: sex === s ? "var(--accent)" : "var(--textSec)",
                      }}>{s}</button>
                  ))}
                </div>
              </Field></div>
            </div>
            <Field label="style" hint="how they read at a glance">
              <input style={inputStyle} value={style} onChange={(e) => setStyle(e.target.value)}
                     placeholder="short black bob, silver rings, oversized work jackets" />
            </Field>
            <Field label="notes" hint="who they are off-camera" grow={!narrow}>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
                placeholder="barista by day, queues ranked by night; hair changes daily; never poses, always mid-task"
                style={{ ...inputStyle, resize: "vertical", lineHeight: 1.5,
                         padding: `${SPACE[8]}px ${SPACE[10]}px`,
                         flex: narrow ? undefined : "1 1 auto",
                         minHeight: narrow ? undefined : 66 }} />
            </Field>

            {/* An anchor is a sentence, not a profile. Show the sentence; keep
                the machinery that shapes its last clause folded away. */}
            <div style={{ border: "1px solid var(--border)", borderRadius: RADIUS.card,
                          background: "var(--bg2)", padding: SPACE[12],
                          display: "flex", flexDirection: "column", gap: SPACE[6] }}>
              <span style={sectionLabel}>every caption will carry</span>
              <span style={{ fontSize: TYPE.body, lineHeight: 1.5, color: "var(--text)" }}>
                {preview?.subject || "…"}
              </span>
              <span style={{ fontSize: TYPE.label, lineHeight: 1.5, color: "var(--textTer)",
                             overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}
                    title={preview?.wardrobe || ""}>
                …scene… <span style={{ color: "var(--textSec)" }}>{preview?.wardrobe || ""}</span>
              </span>
              <Disclosure open={wardOpen} onToggle={() => setWardOpen((o) => !o)}
                caretSize={9}
                triggerStyle={{ display: "inline-flex", alignSelf: "flex-start",
                                width: "auto", gap: SPACE[4], marginTop: 2,
                                fontSize: TYPE.label,
                                color: wardrobe.trim() ? "var(--accent)" : "var(--textTer)" }}
                trigger={wardrobe.trim() ? "custom wardrobe lock"
                                         : "customize the wardrobe lock"}
                contentStyle={{ display: "flex", flexDirection: "column",
                               gap: SPACE[6], paddingTop: SPACE[6] }}>
                  <input style={inputStyle} value={wardrobe}
                         onChange={(e) => setWardrobe(e.target.value)}
                         placeholder="She is fully dressed in the clothing described above." />
                  <span style={{ fontSize: TYPE.label, color: "var(--textTer)",
                                 lineHeight: 1.4 }}>
                    The wardrobe clause closes the caption because the last clause
                    is the strongest one — leave it blank for the generic lock. An
                    explicit NSFW ask lifts it.
                  </span>
              </Disclosure>
            </div>
          </div>

          {/* RIGHT — pick the face. The picker is a pane of its own instead of
              a grid buried under the form. */}
          <div style={{ flex: narrow ? "0 0 auto" : "1 1 0", minWidth: 0, minHeight: 0,
                        display: "flex", flexDirection: "column", gap: SPACE[6],
                        padding: SPACE[16],
                        borderLeft: narrow ? "none" : "1px solid var(--border)",
                        borderTop: narrow ? "1px solid var(--border)" : "none" }}>
            <div style={{ display: "flex", alignItems: "center", gap: SPACE[8] }}>
              <span style={sectionLabel}>
                identity reference
                <span style={{ fontWeight: W.label, textTransform: "none",
                               letterSpacing: 0 }}> (required)</span>
              </span>
              <label style={{
                marginLeft: "auto", display: "inline-flex", alignItems: "center",
                gap: SPACE[6], height: 26, padding: `0 ${SPACE[10]}px`,
                background: "var(--bg2)", cursor: "pointer",
                border: "1px solid var(--border)", borderRadius: RADIUS.input,
                fontSize: TYPE.ui, color: "var(--textSec)",
              }}>
                <ImageSquare size={12} weight="duotone" />
                {busy ? "uploading…" : "upload"}
                <input type="file" accept="image/*" style={{ display: "none" }}
                       onChange={(e) => { doUpload(e.target.files[0]); e.target.value = ""; }} />
              </label>
            </div>
            {refRecord ? (
              <div style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                            minWidth: 0, height: 40 }}>
                <img src={inputImgUrl(refRecord)} alt="" decoding="async"
                  style={{ width: 32, height: 32, objectFit: "cover", flex: "0 0 auto",
                           borderRadius: RADIUS.chip,
                           border: "1px solid var(--accentStr)" }} />
                <span title={ref}
                  style={{ flex: "1 1 auto", minWidth: 0,
                           fontFamily: MONO, fontSize: 10, color: "var(--accent)",
                           overflow: "hidden", textOverflow: "ellipsis",
                           whiteSpace: "nowrap" }}>{ref}</span>
                {pendingEdit ? (
                  <span style={{ flex: "0 0 auto", display: "inline-flex",
                                 alignItems: "center", gap: SPACE[4],
                                 fontSize: TYPE.label, color: "var(--textSec)" }}>
                    editing — the result will replace it
                    <button type="button" onClick={() => setPendingEdit(null)}
                      title="stop waiting for the edit"
                      style={{ background: "none", border: "none", padding: 2,
                               color: "var(--textTer)", cursor: "pointer",
                               display: "inline-flex" }}>
                      <X size={11} weight="bold" />
                    </button>
                  </span>
                ) : (
                  <span style={{ flex: "0 0 auto", display: "inline-flex",
                                 gap: SPACE[4] }}>
                    {[{ key: "edit", icon: PencilSimple, act: () => setEditOpen(true),
                        tip: "change accessories, clothing or background — Identity Edit carries over everything in this photo, so fix it here" },
                      { key: "crop", icon: Crop, act: () => setCropOpen(true),
                        tip: "keep only a region — Identity Edit sees just what you crop to" },
                    ].map(({ key, icon: Icon, act, tip }) => (
                      <button key={key} type="button" onClick={act} title={tip}
                        style={{ display: "inline-flex", alignItems: "center",
                                 gap: SPACE[4], height: 26, padding: `0 ${SPACE[8]}px`,
                                 background: "var(--bg2)", cursor: "pointer",
                                 border: "1px solid var(--border)",
                                 borderRadius: RADIUS.input,
                                 fontSize: TYPE.ui, fontFamily: FONT,
                                 color: "var(--textSec)" }}>
                        <Icon size={12} weight="bold" /> {key}
                      </button>
                    ))}
                  </span>
                )}
              </div>
            ) : (
              <div style={{ fontSize: TYPE.label, color: "var(--textTer)",
                            lineHeight: 1.4, display: "flex", alignItems: "center",
                            height: 40 }}>
                The identity source — the anchor becomes selectable once a
                face is set.
              </div>
            )}
            <input value={filter} onChange={(e) => setFilter(e.target.value)}
                   placeholder="filter input images by name…"
                   style={{ ...inputStyle, height: 30, padding: `0 ${SPACE[10]}px` }} />
            <div style={{ display: "flex", alignItems: "center", gap: SPACE[4],
                          color: "var(--textTer)", fontSize: TYPE.label }}>
              <span>ComfyUI/input</span>
              <span style={{ fontFamily: MONO, fontSize: 9 }}>
                {filter.trim() ? `${inputList.length} of ${inputAll.length}`
                               : inputList.length}
              </span>
              <span role="group" aria-label="Sort input images"
                    style={{ marginLeft: "auto", display: "inline-flex", gap: 2 }}>
                {SORTS.map((s) => (
                  <button key={s.key} type="button" aria-pressed={sort === s.key}
                    onClick={() => setSort(s.key)}
                    style={{ height: 20, padding: `0 ${SPACE[6]}px`, border: "1px solid",
                             borderColor: sort === s.key ? "var(--accent)" : "var(--border)",
                             borderRadius: RADIUS.pill, cursor: "pointer", fontSize: 9,
                             fontFamily: FONT,
                             background: sort === s.key ? "var(--accentMut)" : "transparent",
                             color: sort === s.key ? "var(--accent)" : "var(--textTer)" }}>
                    {s.label}
                  </button>
                ))}
              </span>
            </div>
            <div className="px-scroll"
                 style={{ flex: narrow ? "0 0 auto" : "1 1 0", minHeight: 0,
                          maxHeight: narrow ? 260 : "none", overflowY: "auto",
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))",
                          gap: SPACE[6], alignContent: "start",
                          border: "1px solid var(--border)", borderRadius: RADIUS.input,
                          padding: SPACE[6] }}>
              {inputList.map((image) => (
                <InputCard key={image.name} image={image} selected={ref === image.name}
                           onPick={() => setRef(image.name)} />
              ))}
            </div>
          </div>
        </div>

        {/* The save bar never scrolls away — in the old single-column layout it
            lived below the picker grid and left the screen entirely. */}
        <div style={{ display: "flex", gap: SPACE[8], alignItems: "center",
                      flex: "0 0 auto", padding: `${SPACE[10]}px ${SPACE[16]}px`,
                      borderTop: "1px solid var(--border)" }}>
          {err && <span style={{ fontSize: TYPE.label, color: "#E3A7B0" }}>{err}</span>}
          {!err && clash && (
            <span style={{ fontSize: TYPE.label, color: "#E3B98C", lineHeight: 1.4 }}>
              saving replaces the existing “{clash.name}” anchor
            </span>
          )}
          <button type="button" onClick={save} disabled={busy || loading}
            style={{
              marginLeft: "auto", height: 30, padding: `0 ${SPACE[16]}px`,
              fontSize: TYPE.ui, fontWeight: W.heading,
              color: "#050507", background: "var(--accent)", border: "none",
              borderRadius: RADIUS.input,
              cursor: busy || loading ? "default" : "pointer",
              opacity: busy || loading ? 0.5 : 1,
            }}>{loading ? "loading…" : editId ? "save changes" : "save anchor"}</button>
        </div>
      </ModalShell>

      {/* Rendered after the form so both stack above it. The editor is the
          same dialog every Edit click opens — no mask runs Qwen whole-frame,
          a painted mask runs Klein inpaint — pointed at the full-res input. */}
      {editOpen && refRecord && (
        <EditDirector onClose={() => setEditOpen(false)}
          available={editRecipe ? editRecipe.available !== false : true}
          missing={(editRecipe && editRecipe.missing) || []}
          kleinAvailable={kleinRecipe ? kleinRecipe.available !== false : true}
          kleinMissing={(kleinRecipe && kleinRecipe.missing) || []}
          imageUrl={inputFullUrl(ref)}
          onAction={async (instruction, extra) => {
            setPendingEdit({ seen: new Set((history || []).map((e) => e.id)) });
            setErr(null);
            const ok = await (editInput
              ? editInput(ref, instruction, extra) : Promise.resolve(false));
            if (!ok) {
              setPendingEdit(null);
              setErr("the edit could not be started");
            }
          }} />
      )}
      {cropOpen && refRecord && (
        <CropDialog imageUrl={inputFullUrl(ref)} busy={busy}
          onClose={() => setCropOpen(false)} onUse={adoptCrop} />
      )}
    </>
  );
};
