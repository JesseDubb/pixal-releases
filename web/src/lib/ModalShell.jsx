import { MOTION } from "./design-tokens.js";

// ModalShell.jsx — the ONE overlay entrance and the ONE modal shell (brief
// 9.23d). Two classes of overlay used to mount bare — `{open && (…)}`, the
// panel existed or it did not:
//   - six popovers: history tile caption + action rail, add-LoRA search,
//     model picker, ScrollPicker dropdown, InfoTip's tooltip
//   - five byte-identical "fixed, centred box over a scrim" modals:
//     MotionDirector, CharacterForm (anchor form + crop dialog), StyleForm,
//     EditDirector, and SettingsMenu's non-docked panel
//
// The entrance is promoted from ComfyCompat's px-compat-in — opacity plus a
// small translate/scale on MOTION.layout, the position token DESIGN.md §7
// assigns to overlays. HistoryGrid's px-reveal was the other candidate and
// stays where it is: it runs on MOTION.reveal, the slow entrance token, for
// staggered tile MOUNTS — while the tile caption and rail fire on every hover
// of the app's core loop, where a reveal-token entrance would read as lag.
// px-compat-in's per-placement transformOrigin survives as an inline style at
// each site; the shared class owns only the timing.
//
// An overlay fades and moves; it never grows. Grid rows are Disclosure's
// technique (the fold, 9.23c) and stay there — an overlay displaces nothing,
// so there is nothing to measure. The reduced-motion guard lives IN the
// shared CSS, so a consumer cannot forget it: the animation drops, the mount
// never does.
//
// PORTING.md maps our dialogs to Lumen's ModalShell (portal, backdrop, focus
// trap, scroll-lock). Not ported — named, per the porting rules: a focus trap
// and scroll-lock CHANGE dismissal and containment, and 9.23d forbids that.
// MotionDirector's window Esc listener stays the only keyboard dismissal,
// each scrim-click closes exactly as it did, and none of these modals portal
// today. The port is the same conversation as Disclosure's caret: for the
// next port, not a silent fork here.

export const OVERLAY_CSS = `
@keyframes px-overlay-in {
  from { opacity: 0; transform: translateY(4px) scale(0.98); }
  to   { opacity: 1; transform: none; }
}
@keyframes px-modal-in {
  from { opacity: 0; transform: translate(-50%,-50%) translateY(6px) scale(0.98); }
  to   { opacity: 1; transform: translate(-50%,-50%); }
}
@keyframes px-scrim-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
.px-ov-pop   { animation: px-overlay-in ${MOTION.layout} both; }
.px-ov-modal { animation: px-modal-in ${MOTION.layout} both; }
.px-ov-scrim { animation: px-scrim-in ${MOTION.layout} both; }
@media (prefers-reduced-motion: reduce) {
  .px-ov-pop, .px-ov-modal, .px-ov-scrim { animation: none !important; }
}
`;

// Rendered by ModalShell itself, and by every popover site that cannot count
// on a modal being open (SettingsMenu's docked panel, InfoTip's trigger, the
// history grid). Identical style tags are idempotent; a second copy changes
// nothing.
export const OverlayMotionStyle = () => <style>{OVERLAY_CSS}</style>;

// Scrim + box as SIBLINGS — the shape every modal here already had — so the
// scrim carries the click-away and the box never has to stopPropagation. The
// shell adds no keyboard dismissal of its own; what each modal does today
// keeps working because the box's props and the close path pass straight
// through. `centred` is the fixed centred box (the entrance keeps the
// centring transform in its keyframes, so the animated and resting values
// agree); centred={false} is a positioned panel — SettingsMenu's phone sheet
// or fallback card — which takes the popover entrance instead. Contents,
// size and chrome stay in the caller's boxStyle/boxProps.
export const ModalShell = ({ onClose, z = 36, scrim = "rgba(0,0,0,0.5)",
                             centred = true, boxStyle, boxProps = {}, children }) => (
  <>
    <OverlayMotionStyle />
    <div className="px-ov-scrim" onClick={onClose}
      style={{ position: "fixed", inset: 0, zIndex: z, background: scrim }} />
    <div {...boxProps} className={centred ? "px-ov-modal" : "px-ov-pop"}
      style={{
        position: "fixed", zIndex: z + 1,
        ...(centred ? { top: "50%", left: "50%",
                        transform: "translate(-50%,-50%)" } : null),
        ...boxStyle,
      }}>
      {children}
    </div>
  </>
);
