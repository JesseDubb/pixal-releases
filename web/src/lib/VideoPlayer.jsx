// VideoPlayer.jsx — the lightbox's video surface, with zero native chrome.
// The browser's default controls read as a foreign OS widget floating in
// Pixal's room, so the player draws its own: tap the picture to play/pause,
// one slim glass rail underneath — play, elapsed, scrubber, duration, mute —
// and nothing else. Patterns ported from an earlier media chrome of mine (the
// glass play disc with its -4% optical centering, the idle-fade that settles
// the rail to a legible rest while playing and snaps back on hover).
//
// Compositor discipline: the rail animates opacity only; the scrub fill is a
// width change on a 3px strip repainted ~4Hz by timeupdate — cheap, and only
// while the lightbox is open.
import { useEffect, useRef, useState } from "react";
import { Pause, Play, SpeakerSimpleHigh, SpeakerSimpleSlash } from "@phosphor-icons/react";
import { MOTION, RADIUS, SPACE } from "./design-tokens.js";

const MONO = "ui-monospace, Consolas, monospace";
const INK = "#E8EDF0";                     // GLASS ink - fixed light, both themes

const fmt = (s) => {
  if (!Number.isFinite(s)) return "0:00";
  const whole = Math.max(0, Math.floor(s));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
};

const railBtn = {
  display: "inline-flex", alignItems: "center", justifyContent: "center",
  width: 28, height: 28, padding: 0, border: "none", borderRadius: RADIUS.pill,
  background: "transparent", color: INK, cursor: "pointer", flexShrink: 0,
};

// `videoStyle` carries the caller's size caps (the lightbox's vw/vh maxes) so
// the wrapper shrink-wraps the picture exactly like the image path does.
export const VideoPlayer = ({ src, onDims, videoStyle }) => {
  const vid = useRef(null);
  const track = useRef(null);
  const scrubbing = useRef(false);
  const [playing, setPlaying] = useState(true);
  const [muted, setMuted] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const toggle = () => {
    const v = vid.current;
    if (!v) return;
    if (v.paused) v.play().catch(() => setMuted(true));
    else v.pause();
  };

  const seekTo = (clientX) => {
    const v = vid.current, el = track.current;
    if (!v || !el || !duration) return;
    const r = el.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    v.currentTime = frac * duration;
    setTime(frac * duration);            // instant feedback between timeupdates
  };

  // Space/K toggle while the player is mounted - the lightbox owns Esc/arrows.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === " " || e.key.toLowerCase() === "k") { e.preventDefault(); toggle(); }
      if (e.key.toLowerCase() === "m") setMuted((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const pct = duration ? (time / duration) * 100 : 0;

  return (
    <div className="px-vp" onClick={(e) => e.stopPropagation()}
      style={{ position: "relative", display: "inline-flex" }}>
      {/* the rail's idle-fade lives in CSS so it never re-renders the tree */}
      <style>{`
        @keyframes px-vp-rest { 0%, 70% { opacity: 1; } 100% { opacity: 0.55; } }
        .px-vp-rail[data-playing="true"] { animation: px-vp-rest 2.6s ease forwards; }
        .px-vp:hover .px-vp-rail, .px-vp-rail[data-playing="false"] {
          opacity: 1; animation: none; }
        @media (prefers-reduced-motion: reduce) { .px-vp-rail { animation: none; } }
      `}</style>
      <video ref={vid} src={src} autoPlay loop playsInline muted={muted}
        onClick={toggle}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => { if (!scrubbing.current) setTime(e.target.currentTime); }}
        onLoadedMetadata={(e) => {
          setDuration(e.target.duration);
          onDims?.(e.target.videoWidth + "×" + e.target.videoHeight);
        }}
        style={{ borderRadius: RADIUS.card, display: "block", cursor: "pointer",
                 ...videoStyle }} />

      {/* paused: the glass play disc, optically centered (-4%) */}
      {!playing && (
        <div aria-hidden="true" style={{
          position: "absolute", top: "50%", left: "50%",
          transform: "translate(-50%, -50%)", width: 64, height: 64,
          borderRadius: RADIUS.pill, background: "rgba(3,8,10,0.62)",
          display: "flex", alignItems: "center", justifyContent: "center",
          color: INK, pointerEvents: "none",
        }}>
          <Play size={28} weight="fill" style={{ transform: "translateX(-4%)" }} />
        </div>
      )}

      <div className="px-vp-rail" data-playing={playing} role="group"
        aria-label="video controls" style={{
          position: "absolute", left: SPACE[12], right: SPACE[12],
          bottom: SPACE[12], display: "flex", alignItems: "center",
          gap: SPACE[8], padding: `${SPACE[4]}px ${SPACE[10]}px`,
          background: "rgba(3,8,10,0.82)", borderRadius: RADIUS.pill,
          transition: `opacity ${MOTION.hover}`,
        }}>
        <button type="button" onClick={toggle} style={railBtn}
          aria-label={playing ? "pause" : "play"}>
          {playing ? <Pause size={16} weight="fill" />
                   : <Play size={16} weight="fill" style={{ transform: "translateX(-4%)" }} />}
        </button>
        <span style={{ fontFamily: MONO, fontSize: 10, color: INK, flexShrink: 0 }}>
          {fmt(time)}
        </span>
        {/* the scrubber owns its pointer: drag anywhere on the track */}
        <div ref={track} onPointerDown={(e) => {
            scrubbing.current = true;
            e.currentTarget.setPointerCapture(e.pointerId);
            seekTo(e.clientX);
          }}
          onPointerMove={(e) => { if (scrubbing.current) seekTo(e.clientX); }}
          onPointerUp={(e) => {
            scrubbing.current = false;
            try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* gone */ }
          }}
          style={{ flex: 1, padding: "10px 0", cursor: "pointer", touchAction: "none" }}>
          <div style={{ height: 3, borderRadius: RADIUS.pill,
                        background: "rgba(232,237,240,0.22)" }}>
            <div style={{ height: "100%", width: pct + "%",
                          borderRadius: RADIUS.pill, background: "var(--accent)" }} />
          </div>
        </div>
        <span style={{ fontFamily: MONO, fontSize: 10, color: "rgba(232,237,240,0.6)",
                       flexShrink: 0 }}>
          {fmt(duration)}
        </span>
        <button type="button" onClick={() => setMuted((v) => !v)} style={railBtn}
          aria-label={muted ? "unmute" : "mute"}>
          {muted ? <SpeakerSimpleSlash size={16} weight="fill" />
                 : <SpeakerSimpleHigh size={16} weight="fill" />}
        </button>
      </div>
    </div>
  );
};
