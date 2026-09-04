// Chat.jsx — Pixal's single lane, ported from an earlier chat widget of mine:
// one centered typographic lane under the desk-lamp glow, a Thinking indicator
// for live status, the rounded composer box with a circular send/stop.
// Swapped for the image domain: quick-start chips are prompt starters, the
// composer carries the options bar (ComposerBar), and generation renders as
// JobCards in the lane. History lives in a right rail.
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { ArrowClockwise, ArrowUp, ArrowRight, CaretLeft, CaretRight,
         DiceOne, DiceTwo, DiceThree, DiceFour,
         DiceFive, DiceSix, DownloadSimple, LockSimple, Stop, UserCircle, UserCircleCheck,
         UserCirclePlus, Sparkle, X, Brain, ArrowsLeftRight } from "@phosphor-icons/react";
import { CURVE, DARK, LIGHT, FONT, LOGO_FONT, W, TYPE, SPACE, RADIUS, MOTION, SHADOW, OVERLAY, GLASS_SOLID } from "../lib/design-tokens.js";

// The lobby die: every roll spins it a random 1¼–1¾ turns on a spring curve
// and lands on a DIFFERENT face — a real roll, not a button that swaps text.
const DICE_FACES = [DiceOne, DiceTwo, DiceThree, DiceFour, DiceFive, DiceSix];
import { Thinking } from "../lib/Thinking.jsx";
import { VideoPlayer } from "../lib/VideoPlayer.jsx";
import { renderRichText } from "../lib/richtext.js";
import { prettyTemplate, prettyResolvedModel, prettyLora, tuningLine, finishChips } from "../lib/names.js";
import { imgUrl } from "../transport.js";
import { useJobLive, useStore, renderIntent, loadPromptEnhance,
         PROMPT_ENHANCE_KEY } from "../store.js";
import { ComposerBar, LoraChain, AttachmentIcons, AttachmentIcon } from "./Composer.jsx";
import { CharacterForm } from "./CharacterForm.jsx";
import { InstallNudge } from "./InstallNudge.jsx";
import { StyleForm } from "./StyleForm.jsx";
import { MotionDirector } from "./MotionDirector.jsx";
import { EditDirector } from "./EditDirector.jsx";
import { HistoryGrid } from "./HistoryGrid.jsx";
import { ChatsPanel } from "./ChatsPanel.jsx";
import { SettingsMenu } from "./SettingsMenu.jsx";
import { JobCard } from "./JobCard.jsx";
import { NavRail } from "./NavRail.jsx";
import { PhotonField } from "../lib/PhotonField.jsx";

// The little eye ahead of the VRAM numbers is an NVIDIA-inspired mark; its accent
// ink pulled way down via opacity so it reads as a much darker chartreuse on
// bg0 and stays theme-correct (no color literals in components).
// The brain, on the strip that already carries the card. Jesse: "add a little
// chip for Local and CPU or GPU on the chat widget so you know what is
// selected... and one for API and model used... its just so people know what
// is being used. There could be tags for Vision and Uncensored as well."
//
// One line, same monospace and same muted grey as the VRAM readout beside it -
// this is status, not a control, and it must never out-shout the render. The
// tags are the two questions a local model actually raises: can it see, and
// will it refuse. They only appear when true, so the common case stays short.
const BrainChip = ({ brain, narrow }) => {
  if (!brain || !brain.model) return null;
  const tag = (text, title) => (
    <span key={text} title={title}
          style={{ fontSize: 9, lineHeight: 1.6, padding: "0 4px",
                   borderRadius: RADIUS.pill, border: "1px solid var(--border)",
                   color: "var(--textTer)", letterSpacing: "0.04em" }}>
      {text}
    </span>
  );
  return (
    <span title={brain.mode === "local"
          ? `local brain: ${brain.model}, running on ${brain.device}`
          : `API brain: ${brain.model}`}
          style={{ fontFamily: MONO, fontSize: 10, color: "var(--textTer)",
                   display: "inline-flex", alignItems: "center", gap: 5,
                   minWidth: 0, whiteSpace: "nowrap" }}>
      <Brain size={11} weight="duotone" style={{ flexShrink: 0 }} />
      {/* The model name is the one part that can be long, so it is the one
          part allowed to ellipsis - the mode and the device never do. */}
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>
        {brain.model}
      </span>
      {brain.mode === "local"
        ? <span style={{ flexShrink: 0 }}>{"\u00b7 "}{brain.device}</span>
        : <span style={{ flexShrink: 0 }}>{"\u00b7 api"}</span>}
      {!narrow && brain.vision && tag("VISION", "this brain can look at images")}
      {!narrow && brain.nsfw && tag("UNCENSORED", "an unfiltered model")}
    </span>
  );
};

const NvidiaMark = () => (
  <svg width="12" height="8" viewBox="0 0 440 292" aria-hidden="true"
       style={{ flexShrink: 0, opacity: 0.4 }}>
    <path fill="var(--accent)" d="M164.109 86.8594V60.5625C166.656 60.3828 169.234 60.2422 171.859 60.1641C243.734 57.9063 290.93 121.953 290.93 121.953C290.93 121.953 239.984 192.719 185.359 192.719C178.138 192.751 170.96 191.603 164.109 189.32V109.594C192.102 112.977 197.703 125.336 214.555 153.391L251.984 121.828C251.984 121.828 224.641 85.9922 178.617 85.9922C173.772 86.014 168.931 86.3009 164.117 86.8516M164.117 0V39.2812C166.695 39.0703 169.281 38.9141 171.867 38.8203C271.867 35.4531 337 120.852 337 120.852C337 120.852 262.164 211.805 184.211 211.805C177.469 211.805 170.74 211.212 164.102 210.031V234.313C169.654 235.02 175.246 235.375 180.844 235.375C253.383 235.375 305.844 198.328 356.625 154.484C365.039 161.234 399.516 177.633 406.625 184.82C358.32 225.258 245.758 257.852 181.945 257.852C175.797 257.852 169.883 257.484 164.086 256.922V291.039H385.812C415.636 291.039 439.812 266.862 439.812 237.039V54.0063C439.812 24.1835 415.637 0.00713438 385.814 0.00628846L164.117 0ZM164.117 189.305V210.023C97.0078 198.078 78.3828 128.344 78.3828 128.344C78.3828 128.344 110.602 92.6484 164.109 86.875V109.594H164C135.93 106.227 114 132.445 114 132.445C114 132.445 126.297 176.609 164.125 189.32M44.9062 125.305C44.9062 125.305 84.6719 66.625 164.078 60.5625V39.2812C76.1562 46.3125 0 120.812 0 120.812C0 120.812 43.1328 245.531 164.109 256.937V234.281C75.3359 223.141 44.9062 125.305 44.9062 125.305Z" />
  </svg>
);

// The whole-app render meter: a reading-progress hairline, upside down — a
// 3px accent strip pinned to the viewport's bottom edge whenever a job is on
// the card, so "is something cooking" survives any scroll position. It
// subscribes to the live channel alone (a sampler tick re-renders this strip,
// never the lane) and moves by transform only — scaleX on a full-width bar is
// a pure compositor update, nothing for CUDA to fight (render-quiet rule).
// Before the first tick it holds a small nub: honest "started, no steps yet".
const RenderMeter = ({ jobId }) => {
  const liveJob = useJobLive(jobId);
  const p = liveJob.progress || {};
  const frac = p.max ? Math.min(1, p.value / p.max) : 0;
  return (
    <div aria-hidden="true" style={{
      position: "fixed", left: 0, right: 0, bottom: 0, height: 3,
      zIndex: OVERLAY.meter, pointerEvents: "none", overflow: "hidden",
    }}>
      <div style={{
        position: "absolute", inset: 0, background: "var(--accent)",
        transformOrigin: "left center",
        transform: `scaleX(${Math.max(frac, 0.02)})`,
        transition: "transform 300ms linear",
      }} />
    </div>
  );
};

const metaFor = (src) => ({
  scene: src.scene, template: src.template,
  model: src.info && src.info.model, size: src.info && src.info.size,
  model_path: src.info && src.info.model_path,
  model_family: src.info && src.info.model_family,
  model_variant: src.info && src.info.model_variant,
  execution_profile: src.info && src.info.execution_profile,
  loras: (src.info && src.info.loras) || [],
  // video recipes carry more than the still fields - engine, the resolved
  // sampler line, shot/frame counts, audio - so the lightbox readout for a
  // clip is as complete as an image's
  engine: src.info && src.info.engine,
  sampler: src.info && src.info.sampler,
  // stills: the sampler schedule that ran (sampler, scheduler, steps, cfg)
  // and the finish chain - the same facts the card's hover chips read
  tuning: src.info && src.info.tuning,
  finish: src.info && src.info.finish,
  upscaler: src.info && src.info.upscaler,
  shots: src.info && src.info.shots,
  frames: src.info && src.info.frames,
  audio: src.info && src.info.audio,
  seed: src.seed, elapsed: src.elapsed, ts: src.ts,
  // an edit / re-roll / upscale names the render it came from - the
  // lightbox offers the original under a held button
  parent: src.parent || null,
});

const CSS_ID = "pixal-chat-css";
const CONV = "local";
const MONO = "ui-monospace, Consolas, monospace";

// The lobby is CHARACTER-AWARE: {name} is filled from the first (or selected)
// character anchor on disk; with no anchors it speaks to an empty house and
// nudges toward inventing someone. The app ships with no one - the lobby
// must never pretend otherwise.
const GREETINGS_ANCHOR = [
  "What are we making? {name}'s around. So is the rest of the world.",
  "Give me one sentence. I'll give you a frame.",
  "The box is warm and the lamp is on. What do you want to see?",
  "{name} is between shifts. Give them something to do.",
  "Name a person, a place, or a mood. I'll bring the light.",
  "Anything on the box: {name}'s week, someone else's, or no one at all.",
  "Tell me the moment. I'll figure out who's holding the camera.",
  "Where to today - somewhere {name} knows, or somewhere neither of us has been?",
];

const GREETINGS_BARE = [
  "Give me one sentence. I'll give you a frame.",
  "The box is warm and the lamp is on. What do you want to see?",
  "Name a person, a place, or a mood. I'll bring the light.",
  "Nobody lives here yet. Describe someone once and I'll keep them consistent.",
  "Tell me the moment. I'll figure out who's holding the camera.",
  "Start with a place, or start with a person - a character anchor makes them permanent.",
];

// Chip pools - random starters per roll. Each message is a real brief:
// a task in the hands, someone off camera, one named light.
const QUICK_POOL_ANCHOR = [
  { id: "open", label: "The 6am open",
    message: "{name} unlocking the shop's folding shutter at six in the morning, cold blue " +
             "street against warm light spilling out - someone is filming this early " +
             "and {name} has opinions about it" },
  { id: "errand", label: "Caught mid-errand",
    message: "catch {name} mid-errand somewhere unexpected - you pick the place, " +
             "one truthful task in their hands, someone off camera waiting on them" },
  { id: "deadline", label: "The 2am deadline",
    message: "{name} at 2am finishing a commission, monitor glow, the client " +
             "just sent a revision and it hurt" },
  { id: "salt", label: "Sunday salt",
    message: "{name} coming out of the water with a board under one arm, salt-stiff hair, " +
             "squinting into the low sun - someone on the sand just called out" },
  { id: "bonfire", label: "Bonfire shift",
    message: "{name} crouched by a driftwood bonfire feeding it a plank, firelight from " +
             "below, friends with cans behind, someone just said something worth turning for" },
  { id: "not-her", label: "No people tonight",
    message: "no people - surprise me with a place that has a story: one object doing a job, " +
             "any hour, any weather, deep focus" },
  { id: "rain", label: "Rain check",
    message: "{name} stuck under a shop awning waiting out a downpour, watching the street " +
             "run with water, a coffee going cold in hand" },
  { id: "offclock", label: "Off the clock",
    message: "{name} after close, sitting on the counter next to the day's " +
             "till, one lamp on, mid-sentence with whoever stayed late" },
  { id: "drive", label: "The drive back",
    message: "{name} in the passenger seat at golden hour, feet on the dash, singing along " +
             "to something, shot from the driver's seat" },
  { id: "surprise", label: "Surprise me",
    message: "surprise me - any subject, any hour, any corner of {name}'s week or the " +
             "world; make one frame worth posting" },
];

const MAKE_CHAR_CHIP = { id: "mkchar", label: "Invent a character", action: "character" };

const QUICK_POOL_BARE = [
  { id: "place", label: "A place with a story",
    message: "no people - a place with a story: one object doing a job, any hour, " +
             "any weather, deep focus" },
  { id: "stranger", label: "A stranger mid-task",
    message: "a stranger mid-errand in a place you pick - one truthful task in their " +
             "hands, someone off camera waiting on them" },
  { id: "surprise", label: "Surprise me",
    message: "surprise me - any subject, any hour, any corner of the world; make one " +
             "frame worth posting" },
];

const fillName = (s, name) => s.replaceAll("{name}", name || "");

const pickLobby = (anchorName, avoidGreeting) => {
  const gs = (anchorName ? GREETINGS_ANCHOR : GREETINGS_BARE)
    .filter((g) => g !== avoidGreeting);
  const greeting = gs[Math.floor(Math.random() * gs.length)];
  const chips = [...(anchorName ? QUICK_POOL_ANCHOR : QUICK_POOL_BARE)]
    .sort(() => Math.random() - 0.5).slice(0, anchorName ? 3 : 2);
  if (!anchorName) chips.unshift(MAKE_CHAR_CHIP);   // the build-someone door
  return { greeting, chips };
};

// Theme-aware stylesheet: EVERY token becomes a CSS var on .px-root, so a
// theme flip is one style-tag rewrite and no component knows which theme it
// lives in. Vars whose value is a bare rgb triplet (photon, lamp) are meant
// for rgba() composition.
export const applyThemeCss = (tk) => {
  if (typeof document === "undefined") return;
  let el = document.getElementById(CSS_ID);
  if (!el) {
    el = document.createElement("style");
    el.id = CSS_ID;
    document.head.appendChild(el);
  }
  el.textContent = `
    .px-root {
      ${Object.entries(tk).map(([k, v]) => `--${k}: ${v};`).join("\n      ")}
      color-scheme: ${tk === LIGHT ? "light" : "dark"};
    }
    .px-root *, .px-root *::before, .px-root *::after { box-sizing: border-box; }
    /* touch manners: no grey tap flash, no double-tap zoom on buttons, and the
       page never rubber-bands behind the app shell */
    .px-root { -webkit-tap-highlight-color: transparent; overscroll-behavior: none; }
    .px-root button { touch-action: manipulation; }
    @keyframes px-msg-in { from { opacity: 0; transform: translateY(8px); }
                           to { opacity: 1; transform: translateY(0); } }
    .px-msg { animation: px-msg-in 420ms cubic-bezier(0.16,1,0.3,1) both; }
    /* the status dot breathes while it waits for ComfyUI to come up */
    @keyframes px-dot-wait { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
    @keyframes px-spin { to { transform: rotate(360deg); } }
    .px-dot-wait { animation: px-dot-wait 2.4s ease-in-out infinite; }
    /* connected: a brighter-green layer strobes slowly over the dot - alive,
       not busy. Opacity-only, so it stays compositor-cheap while sampling. */
    @keyframes px-dot-breathe { 0%, 100% { opacity: 0; } 50% { opacity: 0.85; } }
    .px-dot-breathe { animation: px-dot-breathe 3.2s ease-in-out infinite; }
    /* one sonar ping when the compat card opens over the dot */
    @keyframes px-dot-ping { from { transform: scale(1); opacity: 0.7; }
                             to { transform: scale(2.9); opacity: 0; } }
    .px-dot-ping { animation: px-dot-ping 700ms cubic-bezier(0.22,1,0.36,1) both; }
    @media (prefers-reduced-motion: reduce) {
      .px-dot-wait, .px-dot-breathe, .px-dot-ping { animation: none; }
    }
    /* lightbox toolbar: the browser's thick default focus box after a mouse
       click read as a goofy white frame around the glyph. Keyboard focus
       keeps a quiet hairline; mouse clicks get nothing. */
    .px-lb-btn:focus { outline: none; }
    .px-lb-btn:focus-visible {
      outline: 1px solid rgba(232,237,240,0.4); outline-offset: 2px;
      border-radius: 8px;
    }
    /* segmented capsules, same rule: the pill already says which segment is
       live, so a click paints no ring; keyboard focus keeps a hairline just
       inside the pill's own shape. */
    .px-seg:focus { outline: none; }
    .px-seg:focus-visible {
      outline: 1px solid rgba(232,237,240,0.4); outline-offset: -3px;
      border-radius: 999px;
    }
    /* boot bar, indeterminate leg: before the launcher has been kicked there is
       no elapsed time to be honest about, so it sweeps instead of pretending to
       a percentage. The calibrated fill takes over the moment there is one. */
    @keyframes px-bar-sweep { 0% { left: -38%; } 100% { left: 100%; } }
    .px-bar-sweep { animation: px-bar-sweep 1.4s cubic-bezier(0.65,0,0.35,1) infinite; }
    .px-lamp { position: fixed; top: -26vh; left: 50%; transform: translateX(-50%);
      width: 130vw; height: 78vh; pointer-events: none; z-index: 0;
      background: radial-gradient(50% 58% at 50% 0%, rgba(${tk.lamp},0.10) 0%,
        rgba(${tk.lamp},0.04) 36%, rgba(${tk.lamp},0) 70%); }
    .px-input::placeholder { color: var(--textTer); }
    /* Native number spinners are the one browser widget no theme reaches -
       they read as a foreign object in every strength field. The value stays
       type=number (keyboard arrows and validation keep working). */
    .px-root input[type="number"]::-webkit-inner-spin-button,
    .px-root input[type="number"]::-webkit-outer-spin-button {
      -webkit-appearance: none; margin: 0; }
    .px-root input[type="number"] { -moz-appearance: textfield; appearance: textfield; }
    /* 3px floating-pill scrollbar. The TRACK margins limit the thumb's travel
       so it stops 24px short of each end — it can never ride into a rounded
       corner and get masked off. Flush with the edge, fully-round ends. */
    .px-scroll::-webkit-scrollbar { width: 3px; }
    .px-scroll::-webkit-scrollbar-track { background: transparent; margin: 24px 0; }
    .px-scroll::-webkit-scrollbar-thumb { background: var(--borderHov); border-radius: 999px; }
    .px-scroll::-webkit-scrollbar-thumb:hover { background: var(--borderStr); }
    /* A dialog body scrolls as a whole; its children never compress. Without
       this, a flex column capped by maxHeight shrinks its overflow:hidden
       panels instead of overflowing - the clipped style dialog of 2026-08-22. */
    .px-dialog-body > * { flex-shrink: 0; }
    @media (prefers-reduced-motion: reduce) { .px-msg { animation: none !important; } }
    .px-prose a { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
    .px-prose strong { font-weight: 600; color: var(--text); }
    .px-prose em { font-style: normal; font-weight: 500; color: var(--text); }
    .px-prose code { font-family: 'Geist', ui-sans-serif, system-ui, sans-serif !important;
      background: var(--bg3); padding: 1px 5px; border-radius: 4px; font-size: 12px;
      color: var(--text); }
    @keyframes px-shim { 0% { background-position: -160px 0; } 100% { background-position: 160px 0; } }
    .px-thumbload { background: linear-gradient(90deg, var(--bg3) 25%, var(--bg4) 50%, var(--bg3) 75%);
      background-size: 320px 100%; animation: px-shim 1.4s ease infinite; }
    /* RENDER-QUIET (.px-calm on the root while ComfyUI samples).
       Every loop below repaints on a timer, and an app that never stops
       animating pins Chrome's compositor - and behind it DWM - to the display
       refresh, so the desktop's graphics pipeline never gets to idle and the
       sampler is preempted for the whole job. One rule, listed by class, so a
       new ambient animation has an obvious place to be switched off rather
       than quietly costing a render. One-shot entrances (px-msg, px-dot-ping,
       px-tile-reveal) are deliberately NOT here: they end on their own, and
       killing them is what makes an app feel dead instead of calm. */
    .px-root.px-calm .px-dot-wait,
    .px-root.px-calm .px-dot-breathe,
    .px-root.px-calm .px-bar-sweep,
    .px-root.px-calm .px-thumbload { animation: none !important; }
  `;
};

// Flat typographic pill — the one chip style.
const Pill = ({ children, onClick, primary, style }) => (
  <button
    type="button"
    onClick={onClick}
    className="px-chip"
    style={{
      display: "inline-flex", alignItems: "center", gap: SPACE[6],
      padding: `${SPACE[8]}px ${SPACE[12]}px`, minHeight: 38,
      fontFamily: FONT, fontSize: TYPE.body, fontWeight: W.body, lineHeight: 1.2,
      color: primary ? "var(--accentInk)" : "var(--text)",
      background: primary ? "var(--accent)" : "transparent",
      border: `1px solid ${primary ? "var(--accent)" : "var(--border)"}`,
      borderRadius: RADIUS.pill, cursor: "pointer", whiteSpace: "nowrap",
      transition: `border-color ${MOTION.hover}, background ${MOTION.hover}, transform ${MOTION.hover}`,
      ...style,
    }}
    onMouseEnter={(e) => {
      if (!primary) { e.currentTarget.style.borderColor = "var(--accent)";
                      e.currentTarget.style.background = "var(--accentMut)";
                      e.currentTarget.style.transform = "translateY(-1px)"; }
    }}
    onMouseLeave={(e) => {
      if (!primary) { e.currentTarget.style.borderColor = "var(--border)";
                      e.currentTarget.style.background = "transparent";
                      e.currentTarget.style.transform = "none"; }
    }}
  >
    {children}
  </button>
);

// Memoized on the message object itself: the store replaces a message's
// identity whenever it changes, so `msg` is the whole truth. The handler props
// are fresh closures every Chat render but over stable things (the store api,
// setState, refs) - comparing them would only defeat the memo. Without this,
// every SSE event (gpu every 3s, each landed image, each text line) re-parsed
// and re-rendered the entire lane.
const Message = memo(({ msg, heroGreeting, onOpen, onIterate, onReroll, onAnimate, onReview,
                   onEdit, onUpscale, onApplyFix }) => {
  if (msg.role === "user") {
    return (
      <div className="px-msg" style={{ display: "flex", justifyContent: "flex-end" }}>
        <div style={{
          maxWidth: "82%", padding: `${SPACE[10]}px ${SPACE[16]}px`,
          border: "1px solid var(--border)", borderRadius: RADIUS.card,
          fontSize: TYPE.body, color: "var(--text)", lineHeight: 1.55, whiteSpace: "pre-wrap",
        }}>{msg.text}</div>
      </div>
    );
  }
  if (msg.role === "optsnote") {
    return (
      <div className="px-msg" style={{ display: "flex", justifyContent: "flex-end" }}>
        <div style={{ fontFamily: MONO, fontSize: 10, color: "var(--textTer)",
                      maxWidth: "82%", textAlign: "right" }}>{msg.text}</div>
      </div>
    );
  }
  if (msg.role === "error") {
    return (
      <div className="px-msg" style={{ display: "flex" }}>
        <div style={{
          padding: `${SPACE[8]}px ${SPACE[12]}px`, fontSize: TYPE.ui,
          color: "#E3A7B0", background: "rgba(107,41,53,0.22)",
          border: "1px solid rgba(107,41,53,0.5)", borderRadius: RADIUS.card,
        }}>{msg.text}</div>
      </div>
    );
  }
  if (msg.role === "review") {
    return (
      <div className="px-msg">
        <div style={{
          borderLeft: "2px solid var(--accent)", background: "var(--bg1)",
          border: "1px solid var(--border)", borderLeftWidth: 2,
          borderLeftColor: "var(--accent)", borderRadius: RADIUS.card,
          padding: `${SPACE[10]}px ${SPACE[12]}px`, maxWidth: "92%",
          display: "flex", flexDirection: "column", gap: SPACE[8],
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: SPACE[8] }}>
            <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--accent)",
                           background: "var(--accentMut)",
                           border: "1px solid var(--accentStr)",
                           borderRadius: RADIUS.chip, padding: "2px 7px" }}>critic</span>
            {msg.parent && <span style={{ fontFamily: MONO, fontSize: 10,
                                          color: "var(--textTer)" }}>on #{msg.parent}</span>}
            <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--textTer)" }}>
              qwen3-vl-4b · local</span>
          </div>
          <div className="px-prose" style={{ fontSize: TYPE.body, lineHeight: 1.6,
                                             color: "var(--text)" }}
               dangerouslySetInnerHTML={{ __html: renderRichText(
                 msg.text.replace(/^(LOOKS|WORKS|PROBLEMS|FIX):/gm, "**$1:**")) }} />
          {msg.fix && msg.parent && (
            <div>
              <Pill onClick={() => onApplyFix(msg)}>
                apply the fix<ArrowRight size={12} weight="bold"
                  style={{ color: "var(--textTer)" }} />
              </Pill>
            </div>
          )}
        </div>
      </div>
    );
  }
  if (msg.job) {
    return (
      <div className="px-msg">
        <JobCard job={msg.job} onOpen={onOpen} onIterate={onIterate} onReroll={onReroll}
                 onAnimate={onAnimate} onReview={onReview}
                 onEdit={onEdit} onUpscale={onUpscale} />
      </div>
    );
  }
  const hero = heroGreeting;
  return (
    <div className="px-msg" style={{ display: "flex", flexDirection: "column", gap: SPACE[16] }}>
      {msg.text && (
        <div
          className="px-prose"
          style={{
            fontSize: hero ? TYPE.hero : TYPE.h3,
            fontWeight: hero ? W.nav : W.body,
            color: hero ? "#F4F8FA" : "var(--text)",
            lineHeight: hero ? 1.28 : 1.6,
            letterSpacing: hero ? "-0.01em" : undefined,
            maxWidth: hero ? "24ch" : undefined,
          }}
          dangerouslySetInnerHTML={{ __html: renderRichText(msg.text) }}
        />
      )}
    </div>
  );
}, (a, b) => a.msg === b.msg && a.heroGreeting === b.heroGreeting);

const Lightbox = ({ lb, onClose, onNav }) => {
  const [dims, setDims] = useState(null);
  // Hold-to-compare: an edited, re-rolled or upscaled render shows its
  // ORIGINAL for as long as the button is held, in the same zoom and pan,
  // so a one-flaw fix is judged at real size. Pointer or keyboard hold.
  const history = useStore().history;
  const [showBefore, setShowBefore] = useState(false);
  const before = (() => {
    const pid = lb.meta && lb.meta.parent;
    if (!pid) return null;
    const p = history.find((e) => String(e.id) === String(pid));
    return p && (p.images || []).find((i) => (i.media || "image") === "image") || null;
  })();
  // Zoom is transform-only (translate+scale about center), so pan/zoom never
  // touches layout and stays on the compositor. `anim` eases click-toggles;
  // wheel and drag snap - a transition under the pointer reads as lag.
  const [zoom, setZoom] = useState({ s: 1, tx: 0, ty: 0, anim: false });
  const imgRef = useRef(null);
  const drag = useRef(null);        // live pointer-drag state
  const dragMoved = useRef(false);  // suppresses the click that ends a drag
  const cur = lb.images[lb.idx];
  const isVideo = cur.media === "video";

  useEffect(() => { setZoom({ s: 1, tx: 0, ty: 0, anim: false }); setShowBefore(false); }, [lb.idx]);

  // Pan can never strand the image: at the clamp the scaled edge sits exactly
  // on the unzoomed footprint's edge. offsetWidth/Height are layout sizes,
  // which transform does not touch - getBoundingClientRect would be scaled.
  const clampPan = (el, s, tx, ty, anim) => {
    const mx = (el.offsetWidth * (s - 1)) / 2, my = (el.offsetHeight * (s - 1)) / 2;
    return { s, tx: Math.min(mx, Math.max(-mx, tx)),
             ty: Math.min(my, Math.max(-my, ty)), anim };
  };

  // Native listener: React's onWheel rides the browser's passive default, and
  // zoom must own the wheel (preventDefault) to feel solid.
  useEffect(() => {
    const el = imgRef.current;
    if (!el || isVideo) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      setZoom((z) => {
        const s = Math.min(6, Math.max(1, z.s * Math.exp(-e.deltaY * 0.0015)));
        if (s === z.s) return z;
        if (s === 1) return { s: 1, tx: 0, ty: 0, anim: false };
        // Keep the pixel under the cursor fixed: transformed center is the
        // layout center displaced by the translate.
        const r = el.getBoundingClientRect();
        const dx = e.clientX - (r.left + r.width / 2 - z.tx);
        const dy = e.clientY - (r.top + r.height / 2 - z.ty);
        const k = s / z.s;
        return clampPan(el, s, dx - (dx - z.tx) * k, dy - (dy - z.ty) * k, false);
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [isVideo]);
  const m = lb.meta || {};
  const rows = [
    prettyResolvedModel(m, m.template), dims, m.size,
    m.seed !== undefined ? "seed " + m.seed : null,
    prettyTemplate(m.template),
    m.sampler,                                     // video: resolved sampler line
    tuningLine(m.tuning) || null,                  // stills: sampler · scheduler · steps
    m.shots > 1 ? m.shots + " shots" : null,
    m.frames ? m.frames + " frames" : null,
    m.audio,
    m.elapsed ? m.elapsed + "s" : null,
    m.loras && m.loras.length ? m.loras.map(prettyLora).join(" · ") : null,
  ].filter(Boolean);
  const chips = finishChips(m);
  return (
    <div onClick={onClose} style={{
      // Below every dialog: animate and edit open FROM this viewer, so they
      // have to land on top of it. See OVERLAY in design-tokens.
      position: "fixed", inset: 0, zIndex: OVERLAY.viewer, background: "rgba(3,8,10,0.94)",
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      {/* Toolbar glyphs: 20px duotone, quiet grey -> near-white on hover
          (the lightbox register - never the accent, and the default
          focus ring is tamed to keyboard-only via .px-lb-btn). */}
      <button onClick={onClose} className="px-lb-btn" aria-label="close" style={{
        position: "absolute", top: 14, right: 16, background: "none", border: "none",
        color: "var(--textTer)", cursor: "pointer", padding: 8, zIndex: 2,
        display: "inline-flex", transition: `color ${MOTION.hover}`,
      }}
        onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(232,237,240,0.95)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = "var(--textTer)"; }}
      ><X size={20} weight="duotone" /></button>
      {/* An <a download> against the same-origin image proxy - the browser
          saves under the render's real filename, no blob dance needed. */}
      <a href={imgUrl(cur)} download={cur.filename} className="px-lb-btn"
         title={"save " + cur.filename} aria-label={"save " + cur.filename}
         onClick={(e) => e.stopPropagation()}
         onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(232,237,240,0.95)"; }}
         onMouseLeave={(e) => { e.currentTarget.style.color = "var(--textTer)"; }}
         style={{
           position: "absolute", top: 14, right: 56, padding: 8, zIndex: 2,
           color: "var(--textTer)", display: "inline-flex",
           transition: `color ${MOTION.hover}`,
         }}><DownloadSimple size={20} weight="duotone" /></a>
      {before && !isVideo && (
        <button className="px-lb-btn" aria-label="hold to see the original"
          title="hold to see the original"
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => { e.stopPropagation(); e.currentTarget.setPointerCapture(e.pointerId); setShowBefore(true); }}
          onPointerUp={() => setShowBefore(false)}
          onPointerCancel={() => setShowBefore(false)}
          onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); setShowBefore(true); } }}
          onKeyUp={(e) => { if (e.key === " " || e.key === "Enter") setShowBefore(false); }}
          onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(232,237,240,0.95)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = showBefore ? "var(--accent)" : "var(--textTer)"; }}
          style={{
            position: "absolute", top: 14, right: 96, padding: 8, zIndex: 2,
            background: "none", border: "none", cursor: "pointer", display: "inline-flex",
            color: showBefore ? "var(--accent)" : "var(--textTer)",
            transition: `color ${MOTION.hover}`, touchAction: "none",
          }}><ArrowsLeftRight size={20} weight="duotone" /></button>
      )}
      {lb.images.length > 1 && (
        <>
          {/* Phosphor thin carets, the lightbox glyph - never text ‹ › */}
          <button onClick={(e) => { e.stopPropagation();
            onNav((lb.idx + lb.images.length - 1) % lb.images.length); }}
            aria-label="previous" className="px-lb-btn"
            style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)",
                     background: "none", border: "none", display: "inline-flex",
                     color: "var(--textTer)", cursor: "pointer", padding: 16, zIndex: 2 }}>
            <CaretLeft size={40} weight="thin" /></button>
          <button onClick={(e) => { e.stopPropagation();
            onNav((lb.idx + 1) % lb.images.length); }}
            aria-label="next" className="px-lb-btn"
            style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
                     background: "none", border: "none", display: "inline-flex",
                     color: "var(--textTer)", cursor: "pointer", padding: 16, zIndex: 2 }}>
            <CaretRight size={40} weight="thin" /></button>
        </>
      )}
      {isVideo ? (
        // Pixal's own transport (VideoPlayer.jsx) - the native browser
        // controls are the one piece of foreign chrome in the whole app.
        <VideoPlayer src={imgUrl(cur)} onDims={setDims}
               videoStyle={{ maxWidth: m.model || m.scene ? "88vw" : "94vw",
                             maxHeight: "90vh" }} />
      ) : (
        <img ref={imgRef} src={imgUrl(showBefore && before ? before : cur)} draggable={false}
             onLoad={(e) => { if (!showBefore) setDims(e.target.naturalWidth + "×" + e.target.naturalHeight); }}
             onClick={(e) => {
               e.stopPropagation();
               // the click that ends a pan is a pan, not a zoom toggle
               if (dragMoved.current) { dragMoved.current = false; return; }
               const el = imgRef.current;
               setZoom((z) => {
                 if (z.s > 1) return { s: 1, tx: 0, ty: 0, anim: true };
                 const r = el.getBoundingClientRect();   // s=1: rect IS layout
                 const dx = e.clientX - (r.left + r.width / 2);
                 const dy = e.clientY - (r.top + r.height / 2);
                 return clampPan(el, 2.5, dx * -1.5, dy * -1.5, true);
               });
             }}
             onPointerDown={(e) => {
               if (zoom.s === 1) return;
               e.preventDefault();
               e.currentTarget.setPointerCapture(e.pointerId);
               drag.current = { x: e.clientX, y: e.clientY };
             }}
             onPointerMove={(e) => {
               const d = drag.current;
               if (!d) return;
               // Read the element NOW: React nulls e.currentTarget after the
               // handler returns, but the setZoom updater runs later - passing
               // it through crashed the updater and unmounted the whole app.
               const el = imgRef.current;
               const dx = e.clientX - d.x, dy = e.clientY - d.y;
               if (Math.abs(dx) + Math.abs(dy) > 2) dragMoved.current = true;
               d.x = e.clientX; d.y = e.clientY;
               if (el) setZoom((z) => clampPan(el, z.s, z.tx + dx, z.ty + dy, false));
             }}
             onPointerUp={(e) => {
               drag.current = null;
               try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* gone */ }
             }}
             style={{ maxWidth: m.model || m.scene ? "88vw" : "94vw",
                      maxHeight: "90vh", borderRadius: RADIUS.card,
                      transform: `translate(${zoom.tx}px, ${zoom.ty}px) scale(${zoom.s})`,
                      transition: zoom.anim ? "transform 200ms ease" : "none",
                      cursor: zoom.s === 1 ? "zoom-in" : drag.current ? "grabbing" : "grab",
                      touchAction: "none" }} />
      )}
      {(m.scene || rows.length > 0 || chips.length > 0) && (
        <div onClick={(e) => e.stopPropagation()} style={{
          position: "absolute", left: 0, bottom: 0, width: "min(380px, 88vw)",
          padding: `${SPACE[16]}px ${SPACE[20]}px`,
          background: "linear-gradient(transparent, rgba(3,8,10,0.92) 30%)",
          borderTopRightRadius: RADIUS.dialog,
        }}>
          {m.scene && (
            <div style={{ fontSize: TYPE.ui, color: "var(--text)", lineHeight: 1.5,
                          marginBottom: SPACE[6], display: "-webkit-box",
                          WebkitLineClamp: 3, WebkitBoxOrient: "vertical",
                          overflow: "hidden" }}>{m.scene}</div>
          )}
          {chips.length > 0 && (
            // The finish chain, the card's hover chips at rest (Jesse,
            // 2026-09-01: "the light box also shows those tags in the lower
            // left where the other information is")
            <div aria-label="Finish chain" style={{
              display: "flex", flexWrap: "wrap", gap: 4, marginBottom: SPACE[6],
            }}>
              {chips.map((chip) => (
                <span key={chip} style={{
                  ...GLASS_SOLID, padding: "2px 6px", fontFamily: MONO,
                  fontSize: 9, letterSpacing: "0.06em", textTransform: "uppercase",
                  border: "1px solid rgba(232,237,240,0.14)",
                }}>{chip}</span>
              ))}
            </div>
          )}
          <div style={{ fontFamily: MONO, fontSize: 10, color: "var(--textTer)",
                        lineHeight: 1.8 }}>
            {rows.map((r, i) => <div key={i}>{r}</div>)}
          </div>
        </div>
      )}
      <div style={{ position: "absolute", bottom: 14, right: 20, fontFamily: MONO,
                    fontSize: 10, color: "var(--textTer)" }}>
        {showBefore && <span style={{ color: "var(--accent)" }}>original{"  ·  "}</span>}
        {zoom.s > 1 && (
          <span style={{ color: "var(--accent)" }}>
            {Math.round(zoom.s * 10) / 10}×{"  ·  "}</span>
        )}
        {lb.idx + 1} / {lb.images.length}
      </div>
    </div>
  );
};

export const Chat = () => {
  const store = useStore();
  const [input, setInput] = useState("");
  const [promptEnhance, setPromptEnhance] = useState(loadPromptEnhance);
  const [promptEnhanceTip, setPromptEnhanceTip] = useState(false);
  useEffect(() => {
    try { localStorage.setItem(PROMPT_ENHANCE_KEY, promptEnhance ? "on" : "off"); }
    catch { /* private mode / full storage */ }
  }, [promptEnhance]);
  const [charFormOpen, setCharFormOpen] = useState(false);
  const [charEditId, setCharEditId] = useState("");   // "" = creating a new one
  // Saved styles. `styleDraft` carries a snapshot of the composer into a NEW
  // style so authoring one costs nothing: tune a render, then name it.
  const [styleFormOpen, setStyleFormOpen] = useState(false);
  const [styleEditId, setStyleEditId] = useState("");
  const [styleDraft, setStyleDraft] = useState(null);
  // Animate never fires blind: the MotionDirector dialog collects the user's
  // vision (and clip length) first; their note becomes the brief server-side.
  const [animFor, setAnimFor] = useState(null);
  // Edit is the same shape as animate: pick the frame, then say what changes.
  const [editFor, setEditFor] = useState(null);
  const editRoutes = (store.options && store.options.edit_routes) || {};
  const recipes = ((store.options && store.options.recipes) || []);
  const editRecipe = recipes
    .find((r) => r.id === (editRoutes.whole_frame || "qwen_edit"));
  const kleinRecipe = recipes
    .find((r) => r.id === (editRoutes.masked || "klein_inpaint"));
  // The lobby (greeting + chips) waits for options so it can speak to the
  // actual character roster; the dice re-rolls it; a first saved character
  // upgrades a bare lobby to their name on the spot.
  const anchorName = useMemo(() => {
    const cs = (store.options && store.options.characters) || [];
    if (!cs.length) return null;
    const sel = cs.find((c) => c.id === store.opts.character);
    return (sel || cs[0]).name;
  }, [store.options, store.opts.character]);
  const [lobby, setLobby] = useState(null);
  useEffect(() => {
    if (store.options && !lobby) setLobby(pickLobby(anchorName, null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.options]);
  useEffect(() => {
    if (lobby && anchorName && lobby.chips.some((c) => c.action))
      setLobby(pickLobby(anchorName, null));      // bare lobby -> named lobby
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchorName]);
  const greeting = lobby ? fillName(lobby.greeting, anchorName) : null;
  const chips = lobby ? lobby.chips : [];
  const diceRot = useRef(0);
  const [diceFace, setDiceFace] = useState(4);   // start on five
  const rerollLobby = () =>
    setLobby((l) => pickLobby(anchorName, l && l.greeting));
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  // @-mentions: typing "@" opens a character autocomplete over the composer.
  // Picking one completes the name inline AND selects the anchor - the fastest
  // path from "thinking about her" to "she's locked in". Unknown names offer
  // to invent the character on the spot.
  const [mention, setMention] = useState(null);   // { q, start } of the live token
  const [mIdx, setMIdx] = useState(0);
  const [characterNotice, setCharacterNotice] = useState(null);
  const roster = (store.options && store.options.characters) || [];
  const identityRecipe = ((store.options && store.options.recipes) || [])
    .find((r) => r.id === "identity_edit");
  const characterProblem = (c) => {
    if (!identityRecipe?.available) return "Identity Edit is unavailable until its assets are installed.";
    if (!c?.has_ref) return `${c?.name || "This character"} needs a reference image for Identity Edit.`;
    return "";
  };
  const mHits = useMemo(() => {
    if (!mention) return [];
    const q = mention.q.toLowerCase();
    const starts = roster.filter((c) => c.name.toLowerCase().startsWith(q));
    const rest = roster.filter(
      (c) => !starts.includes(c) && c.name.toLowerCase().includes(q));
    return [...starts, ...rest].slice(0, 6);
  }, [mention, roster]);
  const detectMention = (val, caret) => {
    const m = /(^|\s)@([a-zA-Z0-9_-]*)$/.exec(val.slice(0, caret));
    return m ? { q: m[2], start: caret - m[2].length - 1 } : null;
  };
  const pickMention = (c) => {
    if (!mention) return;
    const problem = characterProblem(c);
    if (problem || !store.selectCharacter(c.id)) {
      setCharacterNotice(problem || "That character cannot use Identity Edit yet.");
      return;
    }
    const end = mention.start + 1 + mention.q.length;
    const next = input.slice(0, mention.start) + "@" + c.name + " " + input.slice(end);
    const caret = mention.start + c.name.length + 2;
    setInput(next);
    setCharacterNotice(null);
    setMention(null);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (el) { el.focus(); el.setSelectionRange(caret, caret); }
    });
  };

  // Rail panels (settings / history) dock beside the rail and PUSH the content
  // card over instead of covering it — but only while the chat keeps a sane
  // width. Below the breakpoint they fall back to the old overlay behavior.
  const [vw, setVw] = useState(() => (typeof window !== "undefined" ? window.innerWidth : 1280));
  useEffect(() => {
    const onResize = () => setVw(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const wide = vw >= 1100;
  // One measure for the conversation and the composer, so their left and right
  // edges stay flush. 760 was set by reading comfort alone and left the pill
  // row one pill short of fitting - it wrapped 2:3 onto a second line. 880 is
  // the width at which the whole row (attach + model + style + character +
  // aspect) clears the send button on one line.
  const COLUMN = 880;
  // phone layout: rail flips to a top bar, the surface hugs the edges, the
  // textarea holds 16px (below that iOS zooms the whole page on focus)
  const narrow = vw < 720;
  const dock = wide ? (store.settingsOpen ? "settings" : store.railOpen ? "history"
    : store.chatsOpen ? "chats" : null) : null;
  // Lane width INCLUDES the 12px gap to the content card (margins live inside
  // the lane so the whole thing collapses to 0 cleanly).
  const dockW = dock === "settings" ? 412 : dock === "chats" ? 292
    : dock === "history" ? Math.min(Math.round(vw * 0.46), 732) : 0;
  const hasLoraChain = !!store.activeLoraPlan;
  // The chain is a real execution rail, not composer decoration. At desktop
  // widths it owns a reserved right column; compact layouts keep the same
  // component in flow so it never covers the chat or prompt controls.
  const desktopLoraRail = hasLoraChain && vw >= 960 && !dock;
  const inlineLoraChain = hasLoraChain && !desktopLoraRail && !dock;
  // Attachments live as icons beside the prompt-enhance sparkle; the textarea
  // pads right so long prompts never run under the stack.
  // The switch row (attachment chips, seed lock, sparkle) floats over the
  // prompt box's top-right corner, so the textarea's right padding must be
  // its MEASURED width - the old count-based guess ignored the seed chip and
  // the sparkle and let typed text run under the icons (Jesse, 2026-08-27).
  const switchRef = useRef(null);
  const [switchWidth, setSwitchWidth] = useState(0);
  useEffect(() => {
    const el = switchRef.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const measure = () => setSwitchWidth(el.getBoundingClientRect().width);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Theme: user pref (light/dark/system) resolved against the OS; the style
  // tag is rewritten on every change, and system-mode tracks the OS live.
  const resolvedTheme = store.themePref === "system"
    ? (typeof window !== "undefined" &&
       window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")
    : store.themePref;
  useEffect(() => { applyThemeCss(resolvedTheme === "light" ? LIGHT : DARK); }, [resolvedTheme]);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => { if (store.themePref === "system") store.bump(); };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [store]);

  const conv = store.conversations[CONV];
  const messages = useMemo(() => conv?.messages || [], [conv]);
  const generating = store.inflight.has(CONV);
  const progress = store.progressMsg[CONV] || null;
  const thinkMode = store.thinkingMode[CONV] || "thinking";
  const onlyGreeting = messages.length <= 1;
  // A render in flight means ComfyUI needs every scrap of GPU — the ambient
  // field freezes for the duration (an unchanged canvas costs the compositor
  // nothing). Caught fighting CUDA for the card on 2026-08-11: at 99.9% VRAM
  // the app's own compositing was the difference between rendering and
  // stalling until the window was minimized.
  // GLOBAL, deliberately: this used to read the visible messages, so switching
  // chats mid-render un-calmed the whole UI while CUDA owned the card. The
  // store tracks live jobs across every conversation; jobs run serially, so
  // the first id is the one on the card — it also feeds the render meter.
  const liveJobId = store.liveJobs[0] || null;
  const rendering = !!liveJobId;

  // A lane video left looping keeps the GPU's video decoder and the
  // compositor busy for the entire render - pause them all when sampling
  // starts. Deliberately not resumed after: a clip that restarts itself
  // unbidden is creepier than one that waits for a click.
  useEffect(() => {
    if (!rendering) return;
    document.querySelectorAll(".px-root video").forEach((v) => {
      if (!v.paused) v.pause();
    });
  }, [rendering]);

  // The hero renders from the conversation, so every greeting change (first
  // load, dice roll, bare->named upgrade) writes the greet message - but only
  // while the lobby is still the only thing in the lane.
  useEffect(() => {
    if (!greeting) return;
    // Read the lane LIVE, not the render-time `conv` snapshot: effects flush
    // after paint, and an SSE handler can append a message in the gap -
    // greeting off the stale snapshot would replace the whole conversation
    // with just the greet and delete whatever had already landed.
    const msgs = store.conversations[CONV]?.messages || [];
    // already greeted with this exact text - stop, or the rewrite loops forever
    if (msgs.length === 1 && msgs[0].id === "greet" && msgs[0].text === greeting) return;
    if (msgs.length === 0 || (msgs.length === 1 && msgs[0].id === "greet"))
      store.addConversation(CONV, { id: CONV, messages: [
        { id: "greet", role: "assistant", text: greeting, ts: Date.now() / 1000 }] });
    // messages is a dep so a NEW CHAT (lane cleared) re-greets, not just boot
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [greeting, messages]);

  // Sticky-bottom autoscroll: follow new content ONLY while the user is pinned
  // to the bottom. Any upward move (wheel, scrollbar drag, PgUp) unpins;
  // scrolling back down to the bottom re-pins. Progress events fire every
  // sampler step - unconditional scrolling made the lane unscrollable mid-render.
  const pinnedRef = useRef(true);
  const lastTopRef = useRef(0);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      if (el.scrollTop < lastTopRef.current - 1) pinnedRef.current = false;
      if (el.scrollHeight - el.scrollTop - el.clientHeight < 40)
        pinnedRef.current = true;
      lastTopRef.current = el.scrollTop;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedRef.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages, progress, generating]);

  // Any deliberate "make something new" click re-pins the log and rides to the
  // bottom: the job lands there, and staring at the old card while it renders
  // reads as nothing happening. The message effect above keeps following.
  const followLatest = () => {
    pinnedRef.current = true;
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };

  const send = (text) => {
    const t = (text ?? "").trim();
    if (!t || generating) return;
    followLatest();
    let o = store.opts;
    // an "@Name" typed anywhere in the message selects that anchor, even
    // without the autocomplete - the mention IS the character picker
    const atHit = roster.find((c) => new RegExp(
      "@" + c.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i").test(t));
    if (atHit && atHit.id !== o.character) {
      const problem = characterProblem(atHit);
      if (problem || !store.selectCharacter(atHit.id)) {
        setCharacterNotice(problem || "That character cannot use Identity Edit yet.");
        return;
      }
      // selectCharacter is synchronous; build this request from its healed
      // Identity Edit engine/model/LoRA/ref state, not the stale pre-pick object.
      o = store.opts;
    }
    setCharacterNotice(null);
    // The one builder (store.js) shapes what the composer is looking at; the
    // re-roll sends the same body as `opts`, so both routes speak one intent.
    const { summary, body } = renderIntent(promptEnhance, o);
    store.sendChatMessage(CONV, t,
      summary ? { summary, body } : null);
    setInput("");
  };

  const iterate = (job) => {
    setInput("iterate on #" + job.job_id + ": ");
    inputRef.current?.focus();
  };

  // A style bottled from Identity Edit still runs on a character anchor. With
  // none chosen, say what is missing at selection time - one sentence under
  // the input - rather than failing the render later.
  const chooseStyle = (id) => {
    const ok = store.selectSavedStyle(id);
    if (!ok) return ok;
    const picked = ((store.options || {}).saved_styles || []).find((s) => s.id === id);
    const anchored = !!store.opts.character
      || (store.opts.refs || []).some((r) => r.kind === "identity" && r.file);
    setCharacterNotice(picked?.needs_character && !anchored
      ? `${picked.name} runs Identity Edit — pick a character anchor to use it.`
      : null);
    return ok;
  };

  const lb = store.lb;
  useEffect(() => {
    if (!lb) return;
    const onKey = (e) => {
      if (e.key === "Escape") store.setLb(null);
      if (e.key === "ArrowLeft")
        store.setLb({ ...lb, idx: (lb.idx + lb.images.length - 1) % lb.images.length });
      if (e.key === "ArrowRight")
        store.setLb({ ...lb, idx: (lb.idx + 1) % lb.images.length });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lb, store]);

  return (
    <div className={`px-root px-scroll${rendering ? " px-calm" : ""}`} style={{
      position: "fixed", inset: 0, minHeight: "100dvh", width: "100%",
      background: "var(--bg0)", color: "var(--text)", fontFamily: FONT,
      display: "flex", flexDirection: narrow ? "column" : "row", overflow: "hidden",
    }}>
      <div className="px-lamp" aria-hidden="true" />
      <PhotonField key={resolvedTheme} calm={rendering}
                   rgb={resolvedTheme === "light" ? LIGHT.photon : DARK.photon} />

      <NavRail store={store} horizontal={narrow} calm={rendering}
               onNewCharacter={() => setCharFormOpen(true)} />

      {/* The dock lane — rail panels slide in HERE as sibling cards and push
          the content surface over (width-transitioned; the inner panel keeps
          its final width so it's revealed, not squished). Empty = zero width. */}
      <div aria-hidden={!dock} style={{
        flexShrink: 0, width: dockW, overflow: "hidden",
        position: "relative", zIndex: 2,
        transition: `width ${MOTION.layout}`,
      }}>
        {dock && (
          <div style={{ width: dockW - 12, height: "calc(100% - 24px)",
                        margin: `${SPACE[12]}px ${SPACE[12]}px ${SPACE[12]}px 0` }}>
            {dock === "settings" ? (
              <SettingsMenu docked onClose={() => store.setSettingsOpen(false)} />
            ) : dock === "chats" ? (
              <ChatsPanel store={store} onClose={() => store.setChatsOpen(false)} />
            ) : (
              <HistoryGrid docked width={dockW - 12}
                history={store.history}
                rendering={rendering}
                onClose={() => store.setRailOpen(false)}
                onOpen={(e) => store.setLb({ images: e.images, idx: 0, meta: metaFor(e) })}
                onAnimate={(e) => setAnimFor(e.id)}
                onReview={(e) => { followLatest(); store.review(e.id); }}
                onEdit={(e) => setEditFor(e.id)}
                onUpscale={(e) => { followLatest(); store.upscale(e.id); }}
                onReroll={(e) => { followLatest(); store.reroll(e.id); }}
                onDelete={(e) => store.deleteEntry(e.id)} />
            )}
          </div>
        )}
      </div>

      {/* The content SURFACE — the z.ai pattern: nav floats on the page ground,
          content lives on one elevated rounded panel. Translucent so the lamp
          glow and photon field breathe through it. */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "row",
                    overflow: "hidden", position: "relative", zIndex: 1,
                    // Narrow: flush to the window - a floated card at phone
                    // width read as "a box around the chat" (Jesse,
                    // 2026-08-27); the ground shows only on the wide layout.
                    margin: narrow
                      ? `0 0 env(safe-area-inset-bottom)`
                      : `${SPACE[12]}px ${SPACE[12]}px ${SPACE[12]}px 0`,
                    // Same discipline as PhotonField's `calm`: while ComfyUI is
                    // sampling, every progress tick damages this surface, and a
                    // damaged backdrop-filter re-runs an 18px blur over the whole
                    // panel on the GPU CUDA is monopolizing - a hitch per step.
                    // Solid surface + no blur means a step costs one tiny paint.
                    background: rendering ? "var(--surfaceSolid)" : "var(--surface)",
                    border: narrow ? "none" : "1px solid var(--border)",
                    borderRadius: narrow ? 0 : RADIUS.surface,
                    backdropFilter: rendering ? "none" : "blur(18px)",
                    WebkitBackdropFilter: rendering ? "none" : "blur(18px)" }}>

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
                    overflow: "hidden" }}>

      <div ref={scrollRef} className="px-scroll" role="log" aria-live="polite"
        style={{ flex: 1, overflowY: "auto", position: "relative", zIndex: 2,
                 display: "flex", flexDirection: "column",
                 justifyContent: onlyGreeting ? "center" : "flex-start",
                 padding: narrow ? `${SPACE[20]}px ${SPACE[12]}px`
                                 : `${SPACE[32]}px ${SPACE[24]}px` }}>
        <div style={{ maxWidth: COLUMN, margin: "0 auto", width: "100%",
                      display: "flex", flexDirection: "column", gap: SPACE[24] }}>
          {messages.map((m, i) => (
            <Message key={m.id || i} msg={m}
              heroGreeting={onlyGreeting && m.id === "greet"}
              onOpen={(images, idx, job) =>
                store.setLb({ images, idx, meta: job ? metaFor(job) : null })}
              onIterate={iterate}
              onReroll={(job) => { followLatest(); store.reroll(job.job_id); }}
              onAnimate={(job) => setAnimFor(job.job_id)}
              onReview={(job) => { followLatest(); store.review(job.job_id); }}
              onEdit={(job) => setEditFor(job.job_id)}
              onUpscale={(job) => { followLatest(); store.upscale(job.job_id); }}
              onApplyFix={(m) => {
                setInput(`iterate on #${m.parent}: apply the review fix - ${m.fix}`);
                inputRef.current?.focus();
              }} />
          ))}

          {store.draftPending && !generating && (
            // The writer drafted a scene and invited a "go" (Jesse,
            // 2026-09-01: inline buttons after the system asks you
            // something). Generate sends the accept - the 10.4 backstop
            // guarantees a pure accept fires the pending draft; Something
            // else sends a plain redirect the writer answers with a fresh
            // take. Both are ordinary chat turns, visible in the lane, so
            // the transcript stays honest. The strip keys off the server's
            // own draft probe, broadcast at every turn end, and leaves the
            // moment the draft fires, dies, or either button is pressed.
            <div role="toolbar" aria-label="Drafted scene actions"
              style={{ display: "flex", flexWrap: "wrap", gap: SPACE[8] }}>
              <Pill primary onClick={() => send("go")}>
                Generate
                <ArrowRight size={13} weight="bold"
                  style={{ color: "var(--accentInk)" }} />
              </Pill>
              <Pill onClick={() => send("Something else — pitch a different take.")}>
                Something else
              </Pill>
            </div>
          )}

          {onlyGreeting && !generating && lobby && (
            <div role="toolbar" aria-label="Prompt starters"
              style={{ display: "flex", flexWrap: "wrap", gap: SPACE[8] }}>
              {chips.map((qs) => (
                <Pill key={qs.id} primary={qs.action === "character"}
                  onClick={() => (qs.action === "character"
                    ? setCharFormOpen(true)
                    : send(fillName(qs.message, anchorName)))}>
                  {qs.label}
                  <ArrowRight size={13} weight="bold"
                    style={{ color: qs.action === "character"
                      ? "var(--accentInk)" : "var(--textTer)" }} />
                </Pill>
              ))}
              {(() => { const Die = DICE_FACES[diceFace]; return (
              <button type="button" title="re-roll the ideas" aria-label="re-roll the ideas"
                onClick={(e) => {
                  // random 450–630° so consecutive rolls never feel identical
                  diceRot.current += 360 + 90 * (1 + Math.floor(Math.random() * 3));
                  e.currentTarget.style.transform = `rotate(${diceRot.current}deg)`;
                  // swap the face mid-spin, while the glyph is in motion blur
                  setTimeout(() => setDiceFace((f) => {
                    let n; do { n = Math.floor(Math.random() * 6); } while (n === f);
                    return n;
                  }), 200);
                  rerollLobby();
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--accent)";
                  e.currentTarget.style.color = "var(--accent)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "var(--border)";
                  e.currentTarget.style.color = "var(--textSec)";
                }}
                style={{
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  width: 38, height: 38, flexShrink: 0, cursor: "pointer",
                  border: "1px solid var(--border)", borderRadius: RADIUS.pill,
                  background: "transparent", color: "var(--textSec)",
                  transition: `border-color ${MOTION.hover}, color ${MOTION.hover}, ` +
                              `transform 640ms ${CURVE.spring}`,
                }}>
                <Die size={16} weight="duotone" />
              </button>
              ); })()}
            </div>
          )}

          {generating && (
            <div className="px-msg" style={{ display: "flex", alignItems: "center",
                                             gap: SPACE[10], color: "var(--textSec)" }}>
              {/* Deliberately NOT frozen while sampling (tried 2026-08-11, read
                  as broken): the ping-pong is the visible "working" signal and
                  it's transform-only, so it costs the main thread nothing. On a
                  starved GPU it may judder - that's the accepted trade. */}
              <Thinking mode={thinkMode} />
              <span style={{ fontSize: TYPE.body }}>{progress || "pixal is thinking"}</span>
            </div>
          )}
        </div>
      </div>

      <div style={{ position: "relative", zIndex: 3, flexShrink: 0,
                    padding: narrow ? `${SPACE[8]}px ${SPACE[10]}px ${SPACE[12]}px`
                                    : `${SPACE[12]}px ${SPACE[24]}px ${SPACE[20]}px` }}>
        <div style={{ maxWidth: narrow ? COLUMN : COLUMN + 46, margin: "0 auto" }}>
          <div style={{ width: "100%", maxWidth: COLUMN, margin: "0 auto" }}>
            <InstallNudge />
            <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                        padding: `0 ${SPACE[12]}px ${SPACE[8]}px`,
                        color: "var(--textTer)", fontSize: TYPE.label }}>
            <span className={store.comfy ? undefined : "px-dot-wait"} style={{
              width: 7, height: 7, borderRadius: RADIUS.pill, flexShrink: 0,
              background: store.comfy === null ? "var(--textTer)"
                : store.comfy ? "#7BB495" : "#E3A7B0",
            }} />
            {store.comfy === null ? "connecting to comfyui" : store.comfy
              ? "connected to comfyui" : "comfyui offline — watching for it"}
            {store.scan && (
              <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 10,
                             color: "var(--accent)", whiteSpace: "nowrap" }}>
                {store.scan}
              </span>
            )}
            {!store.scan && (
              <span style={{ marginLeft: "auto", minWidth: 0, display: "inline-flex" }}>
                <BrainChip brain={store.brain} narrow={narrow} />
              </span>
            )}
            {!store.scan && store.gpu && (
              <span style={{ marginLeft: store.brain ? 10 : "auto",
                             fontFamily: MONO, fontSize: 10,
                             color: "var(--textTer)", whiteSpace: "nowrap",
                             display: "inline-flex", alignItems: "center", gap: 6 }}>
                <NvidiaMark />
                {narrow
                  ? <>{store.gpu.used}/{store.gpu.total} GB</>
                  : <>{store.gpu.name}{" · "}{store.gpu.used}/{store.gpu.total} GB VRAM
                      {" · "}{store.gpu.ram_used}/{store.gpu.ram_total} GB RAM</>}
              </span>
            )}
            {!store.scan && (
              <button type="button" title="rescan model folders"
                onClick={() => store.rescan()}
                style={{ background: "none", border: "none", padding: 2, cursor: "pointer",
                         color: "var(--textTer)", display: "inline-flex",
                         alignItems: "center", marginLeft: store.gpu ? 4 : "auto" }}
                onMouseEnter={(e) => { e.currentTarget.style.color = "var(--accent)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = "var(--textTer)"; }}>
                <ArrowClockwise size={11} weight="duotone" />
              </button>
            )}
            </div>
            {inlineLoraChain && (
              <LoraChain opts={store.opts} options={store.options}
                         recipeId={store.activeRecipeId} plan={store.activeLoraPlan}
                         onDial={(key, value) => store.setRecipeDial(key, value)}
                         onTuning={(key, value) => store.setTuning(key, value)}
                         setEntries={(entries) => store.setActiveLoraEntries(entries)}
                         setCoreEnabled={(slot, on) => store.setCoreStageEnabled(slot, on)}
                         setCoreStrength={(slot, value) =>
                           // 2026-08-21: core rows edit strength through the same store-owned plan.
                           store.setCoreStageStrength(slot, value)}
                         resetPlan={() => store.resetActiveLoraPlan()} />
            )}
          </div>
          {/* Concentric grid: shell radius 24, uniform pad 12, so anything
              touching a corner (pills, send) rounds at control(12). One shared
              left edge: boxes at 12, text at 12+10=22 (textarea + pill labels).
              Attached refs ride the sparkle's row inside the shell, so the
              composer always owns its full centered width. */}
          <div style={{
            display: "grid", alignItems: "end", justifyContent: "center",
            // Same COLUMN as the status line above and the lane behind it. This
            // was a second hardcoded 760 - widening the other two around it is
            // what left the status text hanging off both edges of the card.
            gridTemplateColumns: `minmax(0, ${COLUMN}px)`,
          }}>
          <div style={{
            position: "relative",
            display: "flex", flexDirection: "column", gap: SPACE[8],
            background: "rgba(255,255,255,0.03)",
            // The lane scrolls beneath this box, so its blur re-samples on any
            // lane damage - off during sampling, same reason as the surface.
            backdropFilter: rendering ? "none" : "blur(10px)",
            WebkitBackdropFilter: rendering ? "none" : "blur(10px)",
            border: "1px solid var(--border)", borderRadius: RADIUS.composer,
            padding: SPACE[12], transition: `border-color ${MOTION.hover}`,
          }}>
            {mention && (mHits.length > 0 || mention.q) && (
              <div className="px-scroll" style={{
                position: "absolute", bottom: "calc(100% + 6px)", left: 0, zIndex: 25,
                minWidth: 230, maxWidth: "min(300px, 86vw)", maxHeight: 262,
                overflowY: "auto", background: "var(--bg1)",
                border: "1px solid var(--borderHov)", borderRadius: RADIUS.card,
                boxShadow: "0 10px 28px rgba(0,0,0,0.5)", padding: SPACE[8],
              }}>
                <div style={{
                  margin: `2px 4px ${SPACE[8]}px`, fontSize: TYPE.micro,
                  fontWeight: W.heading, letterSpacing: "0.08em",
                  textTransform: "uppercase", color: "var(--textTer)",
                }}>character</div>
                {mHits.map((c, i) => {
                  const problem = characterProblem(c);
                  return (
                    <button key={c.id} type="button" disabled={!!problem} title={problem || undefined}
                      onMouseDown={problem ? undefined : (ev) => {
                        ev.preventDefault(); pickMention(c);
                      }}
                      onMouseEnter={() => setMIdx(i)}
                      style={{
                        display: "flex", alignItems: "center", gap: SPACE[8],
                        width: "100%", padding: `${SPACE[6]}px ${SPACE[8]}px`,
                        border: "none", borderRadius: RADIUS.input,
                        background: i === mIdx ? "var(--bg3)" : "transparent",
                        color: c.id === store.opts.character
                          ? "var(--accent)" : "var(--textSec)",
                        fontFamily: FONT, fontSize: TYPE.ui, textAlign: "left",
                        cursor: problem ? "default" : "pointer", opacity: problem ? 0.48 : 1,
                      }}>
                      {c.id === store.opts.character
                        ? <UserCircleCheck size={15} weight="duotone" />
                        : <UserCircle size={15} weight="duotone" />}
                      {c.name}
                      {problem && <span style={{ marginLeft: "auto", fontFamily: MONO,
                                                fontSize: 9, color: "var(--textTer)" }}>
                        {c.has_ref ? "unavailable" : "reference required"}
                      </span>}
                    </button>
                  );
                })}
                {!mHits.length && (
                  <button type="button"
                    onMouseDown={(ev) => {
                      ev.preventDefault(); setMention(null); setCharFormOpen(true);
                    }}
                    style={{
                      display: "flex", alignItems: "center", gap: SPACE[8],
                      width: "100%", padding: `${SPACE[6]}px ${SPACE[8]}px`,
                      border: "none", borderRadius: RADIUS.input,
                      background: "var(--bg3)", color: "var(--textSec)",
                      fontFamily: FONT, fontSize: TYPE.ui, textAlign: "left",
                      cursor: "pointer",
                    }}>
                    <UserCirclePlus size={15} weight="duotone" />
                    invent &ldquo;{mention.q}&rdquo;
                  </button>
                )}
              </div>
            )}
            {/* The switch row: attachment icons stack leftward from the
                sparkle, newest nearest it — every per-send toggle in one
                corner instead of chrome budding off the composer's edge. */}
            <div ref={switchRef}
                 style={{ position: "absolute", top: SPACE[8], right: SPACE[12], zIndex: 5,
                          display: "flex", alignItems: "center" }}>
              <AttachmentIcons opts={store.opts}
                setOpts={(patch) => store.setOpts(patch)}
                selectCharacter={(id) => store.selectCharacter(id)}
                selectIdentityReference={(file) => store.selectIdentityReference(file)}
                removeReference={(kind, file) => store.removeReference(kind, file)}
                options={store.options} />
              {/* THE seed lock, beside the sparkle with the attachments: a
                  global mode needs a global indicator, and the card that holds
                  it may be scrolled far away. Hover names the seed; click is
                  the same unlock as the card's padlock. */}
              {store.heldSeed > 0 && (
                <AttachmentIcon Icon={LockSimple}
                  label={`seed · ${store.heldSeed}`}
                  hint="click to unfreeze — every render reuses this seed while locked"
                  onRemove={() => store.clearSeedLock()} />
              )}
              <button type="button" role="switch" aria-checked={promptEnhance}
                aria-label={`Prompt enhance ${promptEnhance ? "on" : "off"}`}
                onMouseEnter={() => setPromptEnhanceTip(true)}
                onMouseLeave={() => setPromptEnhanceTip(false)}
                onFocus={() => setPromptEnhanceTip(true)}
                onBlur={() => setPromptEnhanceTip(false)}
                onClick={() => setPromptEnhance((value) => !value)}
                style={{
                  width: 40, height: 30, padding: 0,
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  border: "1px solid transparent", borderRadius: RADIUS.pill,
                  background: promptEnhanceTip ? "var(--bg3)" : "transparent",
                  color: promptEnhance ? "var(--accent)" : "var(--textTer)",
                  cursor: "pointer",
                  transition: `color ${MOTION.hover}, background ${MOTION.hover}`,
                }}>
                <Sparkle size={18} weight="duotone" aria-hidden="true" />
              </button>
              {promptEnhanceTip && (
                <div role="tooltip" style={{
                  position: "absolute", top: "50%", right: "calc(100% + 6px)",
                  transform: "translateY(-50%)", pointerEvents: "none",
                  padding: `${SPACE[4]}px ${SPACE[8]}px`, whiteSpace: "nowrap",
                  border: "1px solid var(--borderHov)", borderRadius: RADIUS.pill,
                  background: "var(--bg1)", boxShadow: SHADOW.md,
                  color: promptEnhance ? "var(--accent)" : "var(--textSec)",
                  fontFamily: FONT, fontSize: TYPE.micro,
                }}>
                  Prompt enhance {promptEnhance ? "on" : "off"}
                </div>
              )}
            </div>
            <textarea
              ref={inputRef}
              value={input}
              // Clicking into the prompt box is a statement of intent: the chat
              // drawer folds away so the composer has the floor. Guarded, since
              // setChatsOpen always emits and focus fires on every click.
              onFocus={() => { if (store.chatsOpen) store.setChatsOpen(false); }}
              onChange={(e) => {
                setInput(e.target.value);
                setCharacterNotice(null);
                setMention(detectMention(e.target.value, e.target.selectionStart));
                setMIdx(0);
              }}
              onBlur={() => setTimeout(() => setMention(null), 120)}
              onKeyDown={(e) => {
                if (mention && mHits.length) {
                  if (e.key === "ArrowDown") {
                    e.preventDefault(); setMIdx((i) => (i + 1) % mHits.length); return;
                  }
                  if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setMIdx((i) => (i + mHits.length - 1) % mHits.length); return;
                  }
                  if (e.key === "Enter" || e.key === "Tab") {
                    e.preventDefault(); pickMention(mHits[mIdx]); return;
                  }
                  if (e.key === "Escape") { setMention(null); return; }
                }
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
              }}
              placeholder="Message pixal"
              rows={narrow ? 2 : 3}
              className="px-input"
              style={{
                width: "100%", resize: "none", maxHeight: 220,
                background: "transparent", border: "none", outline: "none",
                color: "var(--text)", fontFamily: FONT,
                fontSize: narrow ? 16 : TYPE.h3,
                lineHeight: 1.5,
                padding: `${SPACE[4]}px ${Math.max(SPACE[48], Math.ceil(switchWidth) + SPACE[12] + SPACE[8])}px 0 ${SPACE[10]}px`,
              }}
            />
            {characterNotice && (
              <div role="status" style={{ padding: `0 ${SPACE[10]}px`, color: "#E3A7B0",
                                           fontSize: TYPE.label, lineHeight: 1.4 }}>
                {characterNotice}
              </div>
            )}
            <div style={{ display: "flex", alignItems: "flex-end", gap: SPACE[8] }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <ComposerBar opts={store.opts} setOpts={(p) => store.setOpts(p)}
                             promptEnhance={promptEnhance}
                             selectCharacter={(id) => {
                               const ok = store.selectCharacter(id);
                               if (ok) setCharacterNotice(null);
                               return ok;
                             }}
                             selectIdentityReference={(file) => {
                               const ok = store.selectIdentityReference(file);
                               if (ok) setCharacterNotice(null);
                               return ok;
                             }}
                             selectSavedStyle={chooseStyle}
                             onNewStyle={() => {
                               setStyleDraft(store.styleDraftFromComposer());
                               setStyleEditId("");
                               setStyleFormOpen(true);
                             }}
                             onEditStyle={(id) => {
                               setStyleDraft(null);
                               setStyleEditId(id);
                               setStyleFormOpen(true);
                             }}
                             // 9.66: a render's ComfyUI metadata, translated
                             // server-side, opens as a draft in the same
                             // editor "save current" uses. unmapped rides
                             // along so the form can name what did not map.
                             onStyleFromImage={(r) => {
                               setStyleDraft({ ...(r.style || {}),
                                               fromImage: { unmapped: r.unmapped || [],
                                                            source: r.source } });
                               setStyleEditId("");
                               setStyleFormOpen(true);
                             }}
                             addReference={(kind, file) => store.addReference(kind, file)}
                             deleteCharacter={(id) => store.deleteCharacter(id)}
                             options={store.options}
                             refreshOptions={() => store.loadOptions()}
                             onNewCharacter={() => { setCharEditId(""); setCharFormOpen(true); }}
                             onEditCharacter={(id) => { setCharEditId(id); setCharFormOpen(true); }} />
              </div>
              <button
                type="button"
                onClick={() => (generating ? store.stopGeneration() : send(input))}
                disabled={!generating && !input.trim()}
                title={generating ? "Stop" : "Send"}
                style={{
                  flexShrink: 0, width: 40, height: 40, borderRadius: RADIUS.pill,
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  border: "none",
                  cursor: (!generating && !input.trim()) ? "default" : "pointer",
                  background: generating ? "var(--bg4)"
                    : (input.trim() ? "var(--accent)" : "var(--bg3)"),
                  color: generating ? "var(--text)"
                    : (input.trim() ? "var(--accentInk)" : "var(--textTer)"),
                  transition: `background ${MOTION.hover}, color ${MOTION.hover}`,
                }}>
                {generating ? <Stop size={16} weight="bold" />
                            : <ArrowUp size={18} weight="bold" />}
              </button>
            </div>
          </div>
          </div>
        </div>
      </div>
      </div>

      {desktopLoraRail && (
        <aside aria-label="Model LoRA execution order" style={{
          position: "sticky", top: 0, alignSelf: "stretch",
          // +12 width carries the wider left padding so the chain's content
          // column keeps its measured width (the narrowest in the app).
          // 24 against the divider: the chain used to hug the rule at 12
          // while the chat side kept a real gutter - the air around the
          // line reads balanced now (Jesse, 2026-09-01).
          width: vw < 1100 ? 300 : 332, height: "100%", flexShrink: 0,
          boxSizing: "border-box", padding: SPACE[12],
          paddingLeft: SPACE[24], overflow: "hidden",
          borderLeft: "1px solid var(--border)", zIndex: 4,
          // The chain owns the rail alone now: its cards carry the recipe
          // dials (9.23a), and the column flexes so the list keeps the
          // leftover height and still scrolls.
          display: "flex", flexDirection: "column",
        }}>
          <LoraChain rail opts={store.opts} options={store.options}
                     recipeId={store.activeRecipeId} plan={store.activeLoraPlan}
                     onDial={(key, value) => store.setRecipeDial(key, value)}
                     onTuning={(key, value) => store.setTuning(key, value)}
                     setEntries={(entries) => store.setActiveLoraEntries(entries)}
                     setCoreEnabled={(slot, on) => store.setCoreStageEnabled(slot, on)}
                     setCoreStrength={(slot, value) =>
                       // 2026-08-21: core rows edit strength through the same store-owned plan.
                       store.setCoreStageStrength(slot, value)}
                     resetPlan={() => store.resetActiveLoraPlan()} />
        </aside>
      )}
      </div>

      {/* Narrow-viewport fallbacks — the same panels as overlays. */}
      {!wide && store.railOpen && (
        <HistoryGrid
          phone={narrow}
          history={store.history}
          rendering={rendering}
          onClose={() => store.setRailOpen(false)}
          onOpen={(e) => store.setLb({ images: e.images, idx: 0, meta: metaFor(e) })}
          onAnimate={(e) => setAnimFor(e.id)}
          onReview={(e) => { followLatest(); store.review(e.id); }}
          onEdit={(e) => setEditFor(e.id)}
          onUpscale={(e) => { followLatest(); store.upscale(e.id); }}
          onReroll={(e) => { followLatest(); store.reroll(e.id); }}
          onDelete={(e) => store.deleteEntry(e.id)} />
      )}

      {!wide && store.settingsOpen &&
        <SettingsMenu phone={narrow} onClose={() => store.setSettingsOpen(false)} />}

      {!wide && store.chatsOpen && (
        // The scrim covers the WHOLE overlay: dimming only the spacer beside
        // the panel left the wrapper's 10px padding un-dimmed - a lighter
        // band down the panel's right edge and across its top (Jesse,
        // 2026-08-27).
        <div style={{ position: "fixed", inset: 0, zIndex: OVERLAY.panel, display: "flex",
                      background: "rgba(0,0,0,0.35)" }}
          onClick={() => store.setChatsOpen(false)}>
          <div style={{ width: 292, maxWidth: "84vw", height: "100%",
                        padding: 10, boxSizing: "border-box" }}
            onClick={(e) => e.stopPropagation()}>
            <ChatsPanel store={store} onClose={() => store.setChatsOpen(false)} />
          </div>
          <div style={{ flex: 1 }} />
        </div>
      )}

      {styleFormOpen && (
        <StyleForm options={store.options} opts={store.opts}
          editId={styleEditId} draft={styleDraft}
          onClose={() => { setStyleFormOpen(false); setStyleEditId(""); setStyleDraft(null); }}
          onSaved={async (record) => {
            const r = await store.saveStyle(record);
            // Selecting it on save is the point: you named what you were
            // already looking at, so the composer should now say so.
            if (r.ok) chooseStyle(r.id);
            return r;
          }} />
      )}

      {charFormOpen && (
        <CharacterForm options={store.options} editId={charEditId}
          onClose={() => { setCharFormOpen(false); setCharEditId(""); }}
          refreshOptions={() => store.loadOptions()}
          history={store.history}
          editInput={(name, instruction, extra) =>
            store.editInput(name, instruction, extra)}
          onSaved={async (id) => {
            await store.loadOptions();
            // Saving the anchor that is ALREADY active is an edit, not a new
            // selection: re-running selectCharacter would wipe a MiniMax H3
            // model pick (9.97). Only a different character gets selected.
            if (store.opts.character !== id && !store.selectCharacter(id))
              setCharacterNotice("That anchor could not be selected for Identity Edit.");
          }} />
      )}

      {animFor && (
        <MotionDirector options={store.options} onClose={() => setAnimFor(null)}
          history={store.history} sourceId={animFor}
          onAction={(hint, secs, engine, model, loraPlan, fps, shots, script, speed,
                     endId, sparse, upscale, resolution) => {
            followLatest();
            store.animate(animFor, hint, secs, engine, model, loraPlan, fps,
                          shots, script, speed, endId, sparse, upscale, resolution);
          }} />
      )}

      {editFor && (() => {
        // The painter needs the source frame; a miss (e.g. a job not yet in
        // history) falls back to the text-only dialog, which still works.
        const ref = String(editFor).toLowerCase();
        const entry = store.history.find((e) =>
          String(e.id || "").toLowerCase().startsWith(ref));
        const still = entry && (entry.images || []).find(
          (i) => (i.media || "image") === "image");
        return (
          <EditDirector onClose={() => setEditFor(null)}
            available={editRecipe ? editRecipe.available !== false : true}
            missing={(editRecipe && editRecipe.missing) || []}
            wholeFrameRecipe={editRecipe}
            kleinAvailable={kleinRecipe ? kleinRecipe.available !== false : true}
            kleinMissing={(kleinRecipe && kleinRecipe.missing) || []}
            imageUrl={still ? imgUrl(still) : ""}
            onAction={(instruction, extra) => {
              followLatest();
              store.edit(editFor, instruction, extra);
            }} />
        );
      })()}

      {lb && <Lightbox lb={lb} onClose={() => store.setLb(null)}
                       onNav={(idx) => store.setLb({ ...lb, idx })} />}

      {rendering && <RenderMeter jobId={liveJobId} />}
    </div>
  );
};

export default Chat;
