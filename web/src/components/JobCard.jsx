// JobCard.jsx — one generation in the chat lane: scene, live sampling progress,
// the image(s) as they land, and the recipe line (model · canvas · LoRA stack)
// with re-roll / iterate / open actions.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { tuningLine, finishChips } from "../lib/names.js";
import { ArrowClockwise, ArrowBendUpLeft, ArrowsOutSimple,
         Check, Copy, FilmStrip, LockSimple, LockSimpleOpen, MagnifyingGlass,
         PaintBrush, Play } from "@phosphor-icons/react";
import { FONT, W, TYPE, SPACE, RADIUS, MOTION, GLASS_SOLID } from "../lib/design-tokens.js";
import { Disclosure, DisclosureTrigger } from "../lib/Disclosure.jsx";
import { DotMatrix } from "../lib/DotMatrix.jsx";
import { prettyTemplate, prettyResolvedModel, prettyLora } from "../lib/names.js";
import { imgUrl, thumbUrl } from "../transport.js";
import { api, useJobLive, useSeedLocked } from "../store.js";

const MONO = "ui-monospace, Consolas, monospace";

const ActionBtn = ({ Icon, label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      height: 26, padding: `0 ${SPACE[10]}px`,
      fontFamily: FONT, fontSize: 11, color: "var(--textSec)",
      border: "1px solid var(--border)", borderRadius: RADIUS.pill,
      background: "var(--bg2)", cursor: "pointer",
      transition: `color ${MOTION.hover}, border-color ${MOTION.hover}, transform ${MOTION.press}`,
    }}
    onMouseEnter={(e) => { e.currentTarget.style.color = "var(--accent)";
                           e.currentTarget.style.borderColor = "var(--accentStr)"; }}
    onMouseLeave={(e) => { e.currentTarget.style.color = "var(--textSec)";
                           e.currentTarget.style.borderColor = "var(--border)"; }}
    onMouseDown={(e) => { e.currentTarget.style.transform = "scale(0.94)"; }}
    onMouseUp={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
  >
    <Icon size={10} weight="duotone" />{label}
  </button>
);

// The finish chain, as hover chips over the still (Jesse, 2026-09-01: "a
// little set of subtle chips over somewhere intuitive on the image when you
// hover") - the gallery tile's GLASS_SOLID chip recipe, faded in only while
// the pointer is over the frame. finishChips (names.js) decides what shows;
// the server re-sends jobinfo at finalize so a live card carries the chain
// the finishers wrote, not the empty info the builder announced.
const StillFrame = ({ im, alt, chips, onClick }) => {
  const [hov, setHov] = useState(false);
  return (
    <div style={{ position: "relative" }}
         onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}>
      <img src={thumbUrl(im)} loading="lazy" alt={alt} onClick={onClick}
           style={{ width: "100%", borderRadius: RADIUS.card, display: "block",
                    cursor: "zoom-in", background: "var(--bg0)" }} />
      {chips.length > 0 && (
        <div aria-hidden="true" style={{
          position: "absolute", top: SPACE[6], left: SPACE[6],
          display: "flex", gap: 4, pointerEvents: "none",
          opacity: hov ? 1 : 0, transition: `opacity ${MOTION.hover}`,
        }}>
          {chips.map((chip) => (
            <span key={chip} style={{
              ...GLASS_SOLID, padding: "2px 6px", fontFamily: MONO,
              fontSize: 9, letterSpacing: "0.06em", textTransform: "uppercase",
            }}>{chip}</span>
          ))}
        </div>
      )}
    </div>
  );
};

// The scene used to be a bare maxHeight:84 with overflow:hidden - it chopped
// mid-word with nothing to say it had, and the full prompt was unreachable from
// the card. Collapsed stays the default (a card should not be a wall of text),
// but the cut is now a fade, expandable, and the text is copyable.
const SCENE_COLLAPSED = 84;

const SceneText = ({ scene }) => {
  const ref = useRef(null);
  const [expanded, setExpanded] = useState(false);
  const [clipped, setClipped] = useState(false);
  const [copied, setCopied] = useState(false);

  // ref is Disclosure's unclipped content box, so scrollHeight is the full
  // prompt height in EITHER state — the clip test no longer depends on being
  // collapsed (expanded used to make scrollHeight === clientHeight, which
  // would have cleared the flag and hidden the control that collapses it).
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) setClipped(el.scrollHeight > SCENE_COLLAPSED + 2);
  }, [scene]);

  useEffect(() => {
    if (!copied) return undefined;
    const t = setTimeout(() => setCopied(false), 1400);
    return () => clearTimeout(t);
  }, [copied]);

  const copy = () => {
    const text = String(scene || "");
    // navigator.clipboard needs a secure context; Pixal is served over plain
    // http on the LAN, so fall back to the legacy path rather than silently
    // doing nothing.
    const done = () => setCopied(true);
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done, () => legacyCopy(text) && done());
    } else if (legacyCopy(text)) {
      done();
    }
  };

  if (!scene) return null;
  return (
    <div style={{ padding: `${SPACE[8]}px ${SPACE[12]}px ${SPACE[4]}px` }}>
      <div style={{ position: "relative" }}>
        <Disclosure open={expanded} peek={SCENE_COLLAPSED} contentRef={ref}
          style={{ fontSize: TYPE.ui, color: "var(--textSec)", whiteSpace: "pre-wrap" }}>
          {scene}
        </Disclosure>
        {clipped && !expanded && (
          <div aria-hidden="true" style={{
            position: "absolute", left: 0, right: 0, bottom: 0, height: 26,
            background: "linear-gradient(to bottom, transparent, var(--bg1))",
            pointerEvents: "none",
          }} />
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                    marginTop: clipped || expanded ? SPACE[4] : 2 }}>
        {(clipped || expanded) && (
          <DisclosureTrigger open={expanded} onToggle={() => setExpanded((v) => !v)}
            caretSize={9}
            title={expanded ? "collapse the prompt" : "show the whole prompt"}
            style={{
              width: "auto", gap: 3, height: 20,
              padding: `0 ${SPACE[6]}px`,
              fontSize: 10, color: "var(--textTer)",
              border: "1px solid var(--border)", borderRadius: RADIUS.pill,
            }}>
            {expanded ? "less" : "more"}
          </DisclosureTrigger>
        )}
        <div style={{ flex: 1 }} />
        <button type="button" onClick={copy}
          title={copied ? "copied" : "copy the prompt"}
          aria-label="copy the prompt"
          style={{
            display: "inline-flex", alignItems: "center", gap: 3, height: 20,
            padding: `0 ${SPACE[6]}px`, cursor: "pointer", fontFamily: FONT,
            fontSize: 10, color: copied ? "var(--accent)" : "var(--textTer)",
            background: "transparent", borderRadius: RADIUS.pill,
            border: `1px solid ${copied ? "var(--accentStr)" : "var(--border)"}`,
            transition: `color ${MOTION.hover}, border-color ${MOTION.hover}`,
          }}>
          {copied ? <Check size={9} weight="bold" /> : <Copy size={9} weight="duotone" />}
          {copied ? "copied" : "copy"}
        </button>
      </div>
    </div>
  );
};

// Plain-http origins are not a secure context, so navigator.clipboard is absent
// in exactly the setup Pixal ships with (a LAN box). execCommand still works.
const legacyCopy = (text) => {
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
};

export const JobCard = ({ job, onOpen, onIterate, onReroll, onAnimate, onReview,
                          onEdit, onUpscale }) => {
  // Sampling progress/preview live outside the message tree (see store.js) so
  // a step tick re-renders THIS card only, never the lane around it.
  const liveJob = useJobLive(job.done ? null : job.job_id);
  const p = liveJob.progress || {};
  // Subscribed, not read-through: this card sits behind Message's msg-identity
  // memo, so a store emit alone never re-renders it - the padlock froze on
  // click until something else moved the lane (Jesse, 2026-08-18).
  const seedLocked = useSeedLocked(job.job_id);
  if (job.template === "vl_review" || job.template === "vl_look") {
    // vl_look is the motion director's eyes (the frame inventory before an
    // animate brief) - same chip, its own words.
    const isLook = job.template === "vl_look";
    return (
      <div style={{
        display: "inline-flex", alignItems: "center", gap: SPACE[8],
        padding: `6px ${SPACE[10]}px`, background: "var(--bg1)",
        border: "1px solid var(--border)", borderRadius: RADIUS.card,
        fontFamily: MONO, fontSize: 10, color: "var(--textTer)",
      }}>
        <span style={{ color: "var(--accent)" }}>{isLook ? "look" : "critic"}</span>
        {job.done
          ? (job.error ? job.error
             : (isLook ? "frame read · " : "review posted below · ") + job.elapsed + "s")
          : (isLook ? "reading the frame…" : "reading the shot…")}
      </div>
    );
  }
  const running = !job.done && !job.error;
  const pct = p.max ? Math.round((100 * p.value) / p.max) : 0;
  const info = job.info;
  // Only renders made since the style was recorded carry this; older cards
  // keep naming their base recipe rather than guessing at a preset.
  const styleName = info && info.style && info.style.name;
  const resolvedModel = prettyResolvedModel(info, job.template);
  const isVideoJob = ["ltx_i2v", "ltx25_i2v", "h3_i2v", "h3_multishot"].includes(job.template) ||
    job.images.some((image) => image.media === "video");
  // info.size is a DISPLAY string, only sometimes bare "WxH" - video cards
  // decorate it ("1216x704 · 121f @ 24fps · 5s", "…x… (PiD 4×)") and a
  // blanket replace("x", " / ") on those yields an invalid aspect-ratio the
  // browser drops, so the waiting canvas sat at its intrinsic 2:1 until the
  // first frame landed. Anchor the parse; anything else keeps the fallback.
  const m = /^(\d+)x(\d+)\b/.exec(info?.size || "");
  const waitingAspect = m ? `${m[1]} / ${m[2]}` : "9 / 16";

  return (
    <div style={{
      width: "min(540px, 92%)", background: "var(--bg1)",
      border: "1px solid var(--border)", borderRadius: RADIUS.dialog,
      overflow: "hidden",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: SPACE[6], flexWrap: "wrap",
        padding: `${SPACE[8]}px ${SPACE[12]}px`, borderBottom: "1px solid var(--border)",
      }}>
        {/* A saved style names itself here. The base recipe is what RAN, but
            it is not what was chosen - a card reading "Realism" for a picture
            made with Ultra Realism loses the only thing that identifies it.
            The base stays in the tooltip, since that is the graph. */}
        <span title={[styleName && prettyTemplate(job.template), job.template]
          .filter(Boolean).join(" · ")} style={{
          fontFamily: FONT, fontSize: 10, color: "var(--accent)",
          background: "var(--accentMut)", border: "1px solid var(--accentStr)",
          borderRadius: RADIUS.chip, padding: "2px 7px",
        }}>{styleName || prettyTemplate(job.template)}</span>
        {resolvedModel && (
          <span title={[info.model_path || info.model, info.execution_profile]
            .filter(Boolean).join(" · ")} style={{
            fontFamily: FONT, fontSize: 10, color: "var(--textSec)",
            background: "var(--bg3)", border: "1px solid var(--border)",
            borderRadius: RADIUS.chip, padding: "2px 7px",
          }}>{resolvedModel}</span>
        )}
        <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--textTer)",
                       display: "inline-flex", alignItems: "center", gap: 3 }}>
          seed {job.seed}{job.count > 1 ? " ×" + job.count : ""}
          <button type="button"
            title={seedLocked
              ? "seed frozen — every render uses it until you unlock"
              : "freeze this seed — every render keeps it until you unlock"}
            aria-pressed={seedLocked}
            onClick={() => api.toggleSeedLock(job.job_id, job.seed)}
            style={{ display: "inline-flex", alignItems: "center", padding: 2,
                     background: "none", border: "none", cursor: "pointer",
                     color: seedLocked ? "var(--accent)" : "var(--textTer)" }}>
            {seedLocked ? <LockSimple size={12} weight="fill" />
                        : <LockSimpleOpen size={12} weight="duotone" />}
          </button>
        </span>
      </div>

      <SceneText scene={job.scene} />

      {running && job.images.length === 0 && (
        // The generation, as structure: sampling previews stream in as
        // luminance grids and pulse into shape. Idle-breathes until the
        // first frame lands (~step 1).
        <div style={{ padding: `${SPACE[8]}px ${SPACE[8]}px 0` }}>
          <DotMatrix preview={liveJob.preview} aspect={waitingAspect} />
        </div>
      )}
      {running && (
        // aria-hidden: this strip changes EVERY sampling step, and the lane is
        // a role="log" live region. When the window is focused, Windows TSF can
        // flip Chromium's accessibility tree on, and each live-region mutation
        // is then serialized on the main thread - a per-step hitch that only
        // happens in the focused window. A step counter is live-region abuse
        // for screen readers anyway (it would announce every step).
        <div aria-hidden="true">
          <div style={{ height: 2, background: "var(--bg3)", marginTop: SPACE[6] }}>
            {/* No width transition: with steps arriving faster than 350ms the
                ease kept this bar animating continuously, forcing compositor
                frames for the entire render. A snap is one paint per step. */}
            <div style={{
              height: "100%", width: pct + "%", background: "var(--accent)",
            }} />
          </div>
          <div style={{ padding: `7px ${SPACE[12]}px`, fontFamily: MONO, fontSize: 10,
                        color: "var(--accent)" }}>
            {p.max ? `sampling ${p.value}/${p.max}` : "queued…"}
          </div>
        </div>
      )}
      {job.error && (
        <div style={{ padding: `7px ${SPACE[12]}px`, fontFamily: MONO, fontSize: 10,
                      color: "#E3A7B0" }}>{job.error}</div>
      )}

      {job.images.length > 0 && (
        <div style={{ display: "grid", gap: SPACE[6], padding: SPACE[8] }}>
          {job.images.map((im, i) => (
            im.media === "video" ? (
              // No native controls in the lane - the clip is a poster that
              // opens the lightbox's own player (sound, scrub, download,
              // recipe readout). The glass play disc marks it as motion.
              <div key={i} onClick={() => onOpen(job.images, i, job)}
                   style={{ position: "relative", cursor: "zoom-in" }}>
                <video src={imgUrl(im)} playsInline muted preload="metadata"
                       style={{ width: "100%", borderRadius: RADIUS.card, display: "block",
                                background: "var(--bg0)", pointerEvents: "none" }} />
                <div aria-hidden="true" style={{
                  position: "absolute", top: "50%", left: "50%",
                  transform: "translate(-50%, -50%)", width: 44, height: 44,
                  borderRadius: RADIUS.pill, background: "rgba(3,8,10,0.62)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  color: "#E8EDF0", pointerEvents: "none",
                }}>
                  <Play size={20} weight="fill" style={{ transform: "translateX(-4%)" }} />
                </div>
              </div>
            ) : (
              <StillFrame key={i} im={im} alt={job.scene}
                          chips={finishChips(info)}
                          onClick={() => onOpen(job.images, i, job)} />
            )
          ))}
        </div>
      )}

      {job.done && !job.error && (
        <>
          <div style={{
            display: "flex", flexDirection: "column", gap: SPACE[8],
            padding: `${SPACE[8]}px ${SPACE[12]}px ${SPACE[10]}px`,
          }}>
          <div title={"#" + job.job_id} style={{
            fontFamily: FONT, fontSize: TYPE.label, color: "var(--textTer)",
          }}>
            {[job.elapsed + "s",
              info && info.size ? info.size.replace("x", " × ") : null,
              job.images.length > 1 ? job.images.length + " frames" : null]
             .filter(Boolean).join("  ·  ")}
          </div>
          <div style={{
            display: "flex", alignItems: "center", gap: SPACE[6], flexWrap: "wrap",
          }}>
            {/* No "finish" (its hardcoded 2x pass is superseded by upscale, which
                works on any model) and no "open" (the image itself opens it). */}
            {!isVideoJob && (
              <ActionBtn Icon={FilmStrip} label="animate" onClick={() => onAnimate(job)} />)}
            {!isVideoJob && onEdit &&
              <ActionBtn Icon={PaintBrush} label="edit" onClick={() => onEdit(job)} />}
            {!isVideoJob &&
              <ActionBtn Icon={MagnifyingGlass} label="review" onClick={() => onReview(job)} />}
            {onUpscale &&
              <ActionBtn Icon={ArrowsOutSimple} label="upscale" onClick={() => onUpscale(job)} />}
            <ActionBtn Icon={ArrowClockwise} label="re-roll" onClick={() => onReroll(job)} />
            <ActionBtn Icon={ArrowBendUpLeft} label="iterate" onClick={() => onIterate(job)} />
          </div>
          {info && info.loras && info.loras.length > 0 && (
            <div title={info.loras.join("\n")} style={{
              fontFamily: FONT,
              fontSize: TYPE.label, color: "var(--textTer)", whiteSpace: "nowrap",
              overflow: "hidden", textOverflow: "ellipsis",
            }}>
              {info.loras.map(prettyLora).join("  ·  ")}
            </div>
          )}
          {info && info.tuning && (
            <div title="the sampler schedule this render ran at" style={{
              fontFamily: FONT,
              fontSize: TYPE.label, color: "var(--textTer)", whiteSpace: "nowrap",
              overflow: "hidden", textOverflow: "ellipsis",
            }}>
              {tuningLine(info.tuning)}
            </div>
          )}
          </div>
        </>
      )}
    </div>
  );
};
