// HistoryGrid.jsx — "past generations" as a bento, ported 1:1 from an
// earlier gallery of mine:
// shortest-column masonry (lib/masonry.js, the same packer), aspect reserved on
// the WRAPPER before media loads (zero CLS), shimmer skeleton until paint,
// capped-stagger reveal on mount, video tiles that stream + play WITH sound on
// hover and reset on leave, mono-eyebrow hover overlay, sanctioned 2px tile
// lift. The surface itself is a floating rounded panel beside the nav rail —
// the rail stays live while history is open.
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowClockwise, ArrowsOut, ArrowsOutSimple, FilmStrip, ImageSquare,
         LockSimple, LockSimpleOpen, MagnifyingGlass, PencilSimple, Play, Trash,
         X } from "@phosphor-icons/react";
import { BORDER, CURVE, FONT, GLASS_SOLID, MOTION, RADIUS, SHADOW, SPACE, TYPE, W } from "../lib/design-tokens.js";
import { buildColumns } from "../lib/masonry.js";
import { prettyTemplate, prettyResolvedModel } from "../lib/names.js";
import { api } from "../store.js";
import { imgUrl, thumbUrl } from "../transport.js";

const MONO = "ui-monospace, Consolas, monospace";

const SORTS = [
  { key: "new", label: "newest" },
  { key: "old", label: "oldest" },
  { key: "template", label: "by engine" },
];

const CSS = `
@keyframes px-shimmer { 0% { background-position: -400px 0; } 100% { background-position: 400px 0; } }
@keyframes px-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
.px-tile-reveal { animation: px-reveal 360ms cubic-bezier(0.16,1,0.3,1) both; }
/* Tile actions: a vertical rail of icon-only rounds, absolutely positioned over
   the image and anchored to its RIGHT edge. Both halves of that matter.
     Vertical + absolute: eight actions no longer have to fit a 256px tile
   width, so nothing wraps and nothing clips - the two failure modes this row
   has had in turn.
     Right-anchored: a button that gets wider grows LEFTWARD, over the image,
   moving no sibling. That is what makes the armed-delete label free.
     And no hover label. It used to slide out on :hover, which cost up to 78px;
   in a wrapping row anchored to the panel's bottom edge that tipped the row
   onto a second line, pushed it UP, and moved the button out from under the
   cursor - so hover dropped, the label collapsed, the row fell back under the
   cursor, and it oscillated at frame rate for as long as you pointed at it.
   The name lives in the title attribute instead, which costs no layout. Only the
   armed delete still opens, because a click is not a pointer position and
   cannot feed back into itself. */
.px-act { display: inline-flex; align-items: center; justify-content: center;
  height: 28px; min-width: 28px; padding: 0 7px; border-radius: 999px; }
.px-act .lbl { max-width: 0; opacity: 0; overflow: hidden; white-space: nowrap;
  margin-left: 0;
  transition: max-width 200ms cubic-bezier(0.22,1,0.36,1), opacity 150ms ease,
              margin-left 200ms cubic-bezier(0.22,1,0.36,1); }
.px-act.px-armed .lbl { max-width: 72px; opacity: 1; margin-left: 6px; }
.px-rail { position: absolute; top: 8px; right: 8px; z-index: 2;
  display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
@media (prefers-reduced-motion: reduce) { .px-tile-reveal { animation: none !important; }
  .px-act .lbl { transition: none !important; } }
/* Render-quiet: a gradient shimmer is a full repaint every frame, and a grid of
   them is the worst possible thing to be doing while ComfyUI samples - which is
   exactly when you open history to watch the last render land. The root carries
   .px-calm for the duration; !important is what reaches the inline animation. */
.px-calm .px-shim-skel { animation: none !important; }
`;

const Tile = ({ e, dims, onProbed, onOpen, onAnimate, onReroll, onReview, onEdit,
                onUpscale, onDelete, poster }) => {
  const [hov, setHov] = useState(false);
  const [armDel, setArmDel] = useState(false);   // two-stage delete: arm, confirm
  const [loaded, setLoaded] = useState(false);
  // Read through, never latched: the lock moves between cards, and a latched
  // copy strands a closed padlock on the one that lost it.
  const seedLocked = api.seedLocked(e.id);
  const videoRef = useRef(null);
  const d = dims[e.id + e.ts];
  const media = e.images[0];
  const isVideo = media.media === "video";

  // A still-looking first frame hid that a tile was a clip at all, so video
  // tiles now announce themselves twice: ambient muted autoplay while the tile
  // is actually on screen, and a glass play disc in the corner for when it is
  // not moving (decoder pressure, sampling calm, reduced motion). Off-screen
  // tiles pause so a clip-heavy grid never exhausts the browser's decoders,
  // and nothing starts while a render owns the card - the lane-wide pause in
  // Chat.jsx stays the authority mid-render, this just avoids re-poking it.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !api.liveJobs.length && v.muted) {
        v.play().catch(() => {});
      } else if (!entry.isIntersecting) {
        v.pause();
      }
    }, { threshold: 0.25 });
    io.observe(v);
    return () => io.disconnect();
  }, []);
  const aspect = d ? `${d.w} / ${d.h}` : isVideo ? "16 / 9" : "1 / 1";
  // only the upscale builders write info.upscaler; the factor comes from the
  // explicit video_scale, else the name ("PiD 4×", "4x-UltraSharp", "_x2")
  const upscaler = e.info && e.info.upscaler;
  const factorMatch = upscaler &&
    /(?:^|[^0-9a-z])([1248])\s*[x×]|[x×]\s*([1248])/i.exec(upscaler);
  const factor = upscaler &&
    (e.info.video_scale || (factorMatch && (factorMatch[1] || factorMatch[2])));
  const upLabel = upscaler ? (factor ? factor + "×" : "upscaled") : null;

  return (
    <div
      onClick={() => onOpen(e)}
      onMouseEnter={() => {
        setHov(true);
        // Hover previews the clip WITH sound; leave returns
        // it to the ambient muted loop rather than freezing it - the loop is
        // now what says "this is a clip".
        const v = videoRef.current;
        if (v) { v.muted = false; v.volume = 0.7; v.play().catch(() => {}); }
      }}
      onMouseLeave={() => {
        setHov(false);
        setArmDel(false);                        // leaving the tile disarms
        const v = videoRef.current;
        if (v) {
          v.muted = true;
          if (api.liveJobs.length) v.pause();    // sampling calm wins over ambience
        }
      }}
      style={{
        position: "relative", width: "100%", aspectRatio: aspect,
        borderRadius: RADIUS.card, overflow: "hidden",
        background: "var(--bg2)",
        border: `1px solid ${hov ? "var(--borderStr)" : BORDER.idle}`,
        cursor: "pointer",
        // Sanctioned tile-lift — the one transform hover the system allows.
        transform: hov ? "translateY(-2px)" : "translateY(0)",
        transition: `border-color ${MOTION.hover}, transform 220ms ${CURVE.reveal}`,
      }}
    >
      {/* Shimmer skeleton — the wrapper already holds the final aspect, the
          shimmer just fills it until the media paints. */}
      {!loaded && (
        <div className="px-shim-skel" style={{
          position: "absolute", inset: 0,
          background: "linear-gradient(90deg, var(--bg3) 25%, var(--bg4) 50%, var(--bg3) 75%)",
          backgroundSize: "800px 100%",
          animation: "px-shimmer 1.6s ease infinite",
        }} />
      )}

      {isVideo ? (
        <video
          ref={videoRef}
          src={imgUrl(media)}
          poster={poster}
          muted loop playsInline preload="metadata"
          style={{
            position: "absolute", inset: 0, width: "100%", height: "100%",
            objectFit: "contain", display: "block",
          }}
          onLoadedData={() => setLoaded(true)}
          onLoadedMetadata={(ev) => {
            setLoaded(true);
            onProbed(e, ev.currentTarget.videoWidth, ev.currentTarget.videoHeight);
          }}
        />
      ) : null}
      {isVideo && (
        // The click affordance the "vid" chip never was: a glass play disc in
        // the corner, clear even when the loop is paused. The lightbox player
        // (sound, scrub, download) stays the actual destination on click.
        <div aria-hidden="true" style={{
          position: "absolute", bottom: SPACE[6], right: SPACE[6],
          width: 28, height: 28, borderRadius: 999,
          ...GLASS_SOLID,
          display: "flex", alignItems: "center", justifyContent: "center",
          pointerEvents: "none",
        }}>
          <Play size={13} weight="fill" style={{ transform: "translateX(5%)" }} />
        </div>
      )}
      {!isVideo && (
        <img
          src={thumbUrl(media)} alt={e.scene} loading="lazy" decoding="async"
          style={{
            position: "absolute", inset: 0, width: "100%", height: "100%",
            objectFit: "contain", display: "block",
            opacity: loaded ? 1 : 0,
            transition: `opacity ${MOTION.hover}`,
          }}
          onLoad={(ev) => {
            setLoaded(true);
            onProbed(e, ev.currentTarget.naturalWidth, ev.currentTarget.naturalHeight);
          }}
          onError={() => setLoaded(true)}
        />
      )}

      {/* media-type identifier on EVERY tile — img or vid at a glance; an
          upscale wears its factor beside it (info.upscaler is set only by the
          upscale builders; the factor reads from the explicit video_scale or
          the model name — 4x-UltraSharp, _x2, "PiD 4×"). */}
      <div style={{
        position: "absolute", top: SPACE[6], left: SPACE[6],
        display: "flex", gap: 4, pointerEvents: "none",
      }}>
        <span style={{
          ...GLASS_SOLID,
          display: "inline-flex", alignItems: "center", gap: 4,
          padding: "2px 6px", fontFamily: MONO, fontSize: 9,
          letterSpacing: "0.06em", textTransform: "uppercase",
        }}>
          {isVideo ? <FilmStrip size={10} weight="duotone" />
                   : <ImageSquare size={10} weight="duotone" />}
          {isVideo ? "vid" : "img"}
        </span>
        {upLabel && (
          <span style={{
            ...GLASS_SOLID,
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "2px 6px", fontFamily: MONO, fontSize: 9,
            letterSpacing: "0.06em", textTransform: "uppercase",
          }}>
            <ArrowsOutSimple size={10} weight="duotone" />
            {upLabel}
          </span>
        )}
      </div>

      {hov && (
        <div style={{
          position: "absolute", left: 0, right: 0, bottom: 0,
          padding: SPACE[10],
          background: "linear-gradient(to top, rgba(0,0,0,0.85), transparent)",
          color: "#fff", textAlign: "left",
        }}>
          <div style={{
            fontSize: 10, opacity: 0.85, fontFamily: MONO,
            textTransform: "uppercase", letterSpacing: "0.06em",
          }}>
            {prettyTemplate(e.template)}
            {e.info && e.info.model ? " · " + prettyResolvedModel(e.info, e.template) : ""}
            {" · seed " + e.seed}{seedLocked ? " 🔒" : ""}
            {e.elapsed ? " · " + e.elapsed + "s" : ""}
          </div>
          <div style={{
            marginTop: 2, fontSize: TYPE.label, fontWeight: 500, lineHeight: 1.4,
            overflow: "hidden", display: "-webkit-box",
            WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
          }}>{e.scene}</div>
        </div>
      )}
      {hov && (
        <div className="px-rail" onClick={(ev) => ev.stopPropagation()}>
            {[
              ...(!isVideo ? [
                { a: "animate", Icon: FilmStrip, fn: onAnimate },
                ...(onEdit ? [{ a: "edit", Icon: PencilSimple, fn: onEdit }] : []),
                { a: "review", Icon: MagnifyingGlass, fn: onReview },
              ] : []),
              ...(onUpscale ? [{ a: "upscale", Icon: ArrowsOutSimple, fn: onUpscale }] : []),
              { a: "re-roll", Icon: ArrowClockwise, fn: onReroll },
              { a: seedLocked ? "unfreeze seed" : "freeze this seed",
                Icon: seedLocked ? LockSimple : LockSimpleOpen,
                fn: () => api.toggleSeedLock(e.id, e.seed) },
              { a: "open", Icon: ArrowsOut, fn: onOpen },
            ].map(({ a, Icon, fn }) => (
              <button key={a} type="button" className="px-act" title={a}
                onClick={() => fn(e)}
                style={{
                  fontFamily: MONO, fontSize: 10, color: "#E8EDF0",
                  background: "rgba(10,12,14,0.85)",
                  border: "1px solid var(--borderHov)", cursor: "pointer",
                }}>
                <Icon size={14} weight="duotone" />
                <span className="lbl">{a}</span>
              </button>
            ))}
            <button type="button"
              className={"px-act" + (armDel ? " px-armed" : "")}
              title={armDel ? "click again - gone for good" : "delete this generation"}
              onClick={() => (armDel ? onDelete(e) : setArmDel(true))}
              style={{
                fontFamily: MONO, fontSize: 10, color: "#fff",
                background: armDel ? "var(--error)" : "rgba(10,12,14,0.85)",
                border: `1px solid ${armDel ? "var(--error)" : "var(--borderHov)"}`,
                cursor: "pointer",
                transition: `background ${MOTION.hover}, border-color ${MOTION.hover}`,
              }}>
              <Trash size={14} weight="duotone" />
              <span className="lbl">{armDel ? "sure?" : "delete"}</span>
            </button>
        </div>
      )}
    </div>
  );
};

export const HistoryGrid = ({ history, onClose, onOpen, onAnimate, onReroll, onReview,
                              onEdit, onUpscale, onDelete, docked, width, phone }) => {
  const [sort, setSort] = useState("new");
  const [dims, setDims] = useState({});

  const items = useMemo(() => {
    const arr = [...history];
    if (sort === "new") arr.sort((a, b) => b.ts - a.ts);
    else if (sort === "old") arr.sort((a, b) => a.ts - b.ts);
    else arr.sort((a, b) => (a.template + a.id).localeCompare(b.template + b.id));
    return arr;
  }, [history, sort]);

  // Docked: columns come from the panel's own width (64 = its side padding);
  // overlay fallback keeps the old window-derived count.
  const colCount = docked && width
    ? Math.max(2, Math.min(5, Math.floor((width - 64) / 280)))
    : phone ? 2
    : typeof window !== "undefined"
      ? Math.max(2, Math.min(5, Math.floor((window.innerWidth - 220) / 300))) : 3;
  const columns = useMemo(
    () => buildColumns(items, colCount, (e) => {
      const d = dims[e.id + e.ts];
      return d ? { width: d.w, height: d.h } : { width: 1, height: 1 };
    }),
    [items, colCount, dims]);

  // A video tile paints black until its metadata decodes. Its first frame IS
  // the source still (both engines animate a finished frame), so the parent
  // entry's thumb — or the job's own still when it emitted one — is an honest
  // poster. No parent in the ledger → shimmer exactly as before.
  const posterFor = useMemo(() => {
    const stillOf = (en) =>
      en && (en.images || []).find((i) => (i.media || "image") === "image");
    const byId = new Map(history.map((en) => [en.id, en]));
    return (en) => {
      const s = stillOf(en) || stillOf(byId.get(en.parent));
      return s ? thumbUrl(s) : undefined;
    };
  }, [history]);

  const onProbed = (e, w, h) => {
    if (!w || !h) return;
    setDims((m) => (m[e.id + e.ts] ? m : { ...m, [e.id + e.ts]: { w, h } }));
  };

  return (
    // Docked: a sibling surface in the dock lane pushing the chat card aside —
    // the lane stays live while renders tick in. Overlay fallback (narrow
    // viewports) floats over the content the old way; either way the rail
    // stays live, so the history icon keeps its active state and closes it.
    <div style={{
      ...(docked
        ? { width: "100%", height: "100%", position: "relative", boxShadow: SHADOW.md }
        : phone
          ? { position: "fixed", zIndex: 30, boxShadow: SHADOW.xl,
              top: "calc(8px + env(safe-area-inset-top))", right: 8,
              bottom: "calc(8px + env(safe-area-inset-bottom))", left: 8 }
          : { position: "fixed", top: 12, right: 12, bottom: 12, left: 76, zIndex: 30,
              boxShadow: SHADOW.xl }),
      background: "var(--surfaceSolid)",
      border: "1px solid var(--border)", borderRadius: RADIUS.surface,
      backdropFilter: "blur(18px)", WebkitBackdropFilter: "blur(18px)",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <style>{CSS}</style>
      <div style={{
        flexShrink: 0, borderBottom: "1px solid var(--border)",
        padding: `${SPACE[16]}px ${SPACE[32]}px`,
      }}>
        <div style={{ maxWidth: 1100, margin: "0 auto",
                      display: "flex", alignItems: "center", gap: SPACE[12] }}>
          <span style={{ fontFamily: FONT, fontSize: TYPE.h2, fontWeight: W.heading }}>
            Past generations
          </span>
          <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--textTer)" }}>
            {history.length}
          </span>
          <span style={{ flex: 1 }} />
          <div style={{ display: "flex", gap: SPACE[6] }}>
            {SORTS.map((s) => (
              <button key={s.key} type="button" onClick={() => setSort(s.key)}
                style={{
                  height: 28, padding: `0 ${SPACE[12]}px`, fontSize: TYPE.ui,
                  fontFamily: FONT, cursor: "pointer", borderRadius: RADIUS.pill,
                  border: "1px solid",
                  borderColor: sort === s.key ? "var(--accent)" : "var(--border)",
                  background: sort === s.key ? "var(--accentMut)" : "transparent",
                  color: sort === s.key ? "var(--accent)" : "var(--textSec)",
                }}>{s.label}</button>
            ))}
          </div>
          <button type="button" onClick={onClose} title="close"
            style={{ display: "inline-flex", alignItems: "center", justifyContent: "center",
                     width: 28, height: 28, background: "var(--bg2)",
                     border: "1px solid var(--border)", borderRadius: RADIUS.pill,
                     color: "var(--textSec)", cursor: "pointer" }}>
            <X size={13} weight="bold" />
          </button>
        </div>
      </div>

      <div className="px-scroll" style={{ flex: 1, minHeight: 0, overflowY: "auto",
                                          padding: `${SPACE[20]}px ${SPACE[32]}px ${SPACE[48]}px` }}>
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
          {history.length === 0 && (
            <div style={{ color: "var(--textTer)", fontSize: TYPE.body, padding: SPACE[24] }}>
              Nothing yet — everything you make lands here.</div>
          )}
          <div style={{ display: "flex", gap: SPACE[10], alignItems: "flex-start" }}>
            {columns.map((col, ci) => (
              <div key={ci} style={{ flex: "1 1 0", display: "flex", flexDirection: "column",
                                     gap: SPACE[10], minWidth: 0 }}>
                {col.items.map((e, i) => (
                  // Reveal on a WRAPPER so the entrance's fill-mode never
                  // overrides the tile's hover-lift transform. Capped stagger.
                  <div key={e.id + e.ts} className="px-tile-reveal"
                       style={{ animationDelay: `${Math.min(i * 60, 140)}ms` }}>
                    <Tile e={e} dims={dims} onProbed={onProbed}
                          onOpen={onOpen} onAnimate={onAnimate} onReroll={onReroll}
                          onReview={onReview} onEdit={onEdit} onUpscale={onUpscale}
                          onDelete={onDelete} poster={posterFor(e)} />
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
