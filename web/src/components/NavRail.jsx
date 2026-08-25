// NavRail.jsx — the ultra-light left rail: the glass ComfyUI puck up top, then a
// short stack of quiet icon targets (history, new character, settings). Active
// target gets the lamp accent. Deliberately narrow and calm — the lane is
// the star, the rail just holds the doors.
import { useEffect, useRef, useState } from "react";
import { ChatsCircle, GearSix, Images, UserCirclePlus } from "@phosphor-icons/react";
import { RADIUS, SPACE } from "../lib/design-tokens.js";
import { BlockLogo, RAIL_DRIFT } from "../lib/BlockLogo.jsx";
import { ComfyCompatCard } from "./ComfyCompat.jsx";

// Round, bubbly, and barless: the icons float straight on the page ground —
// no background, no divider. The CONTENT is the surface; the nav is just air.
const RailButton = ({ icon: Icon, label, active, onClick }) => (
  <button type="button" onClick={onClick} title={label} aria-label={label}
    style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: 48, height: 48, borderRadius: RADIUS.pill, cursor: "pointer",
      background: active ? "var(--bg3)" : "transparent",
      border: "none",
      color: active ? "var(--accent)" : "var(--textTer)",
      transition: "color 160ms ease, background 160ms ease, transform 160ms ease",
    }}
    onMouseEnter={(e) => {
      if (!active) {
        e.currentTarget.style.color = "var(--textSec)";
        e.currentTarget.style.background = "var(--bg2)";
      }
      e.currentTarget.style.transform = "scale(1.08)";
    }}
    onMouseLeave={(e) => {
      if (!active) {
        e.currentTarget.style.color = "var(--textTer)";
        e.currentTarget.style.background = "transparent";
      }
      e.currentTarget.style.transform = "scale(1)";
    }}>
    <Icon size={24} weight={active ? "duotone" : "light"} />
  </button>
);

// The status dot, now a door of its own: hover (or tap) opens the compat card —
// what this ComfyUI install covers of Pixal's node needs. The 7px dot keeps its
// exact look; it just gained a 24px hit target and something to say. Close is
// on a short delay so the cursor can cross the gap into the card.
const ComfyDot = ({ store, horizontal }) => {
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);
  const closeTimer = useRef(null);
  const openNow = () => { clearTimeout(closeTimer.current); setOpen(true); };
  const closeSoon = () => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpen(false), 160);
  };
  useEffect(() => {                 // touch has no mouseleave — tap-away closes
    if (!open) return undefined;
    const away = (e) => {
      if (wrap.current && !wrap.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  return (
    <div ref={wrap} onMouseEnter={openNow} onMouseLeave={closeSoon}
      style={{
        position: "relative", display: "flex", alignItems: "center",
        justifyContent: "center", flexShrink: 0,
        ...(horizontal ? { marginLeft: SPACE[4] } : { marginTop: SPACE[6] }),
      }}>
      <button type="button" onClick={openNow}
        aria-label="comfyui compatibility"
        title={open ? undefined
          : store.comfy ? "comfyui connected" : "comfyui offline — watching for it"}
        style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          width: 24, height: 24, padding: 0, border: "none",
          borderRadius: RADIUS.pill, background: "transparent", cursor: "pointer",
        }}>
        {/* three layers: the dot, a brighter green that breathes over it while
            connected, and a one-shot sonar ring when the compat card opens
            (remounted per open so the animation restarts). All opacity/transform. */}
        <span aria-hidden="true" style={{ position: "relative", width: 7, height: 7 }}>
          <span className={store.comfy ? undefined : "px-dot-wait"}
            style={{
              position: "absolute", inset: 0, borderRadius: RADIUS.pill,
              background: store.comfy === null ? "var(--textTer)"
                : store.comfy ? "#7BB495" : "#E3A7B0",
            }} />
          {store.comfy && (
            <span className="px-dot-breathe" style={{
              position: "absolute", inset: 0, borderRadius: RADIUS.pill,
              background: "#A8E6C4", opacity: 0,
            }} />
          )}
          {store.comfy && open && (
            <span className="px-dot-ping" style={{
              position: "absolute", inset: -2, borderRadius: RADIUS.pill,
              border: "1.5px solid #7BB495",
            }} />
          )}
        </span>
      </button>
      <ComfyCompatCard open={open} horizontal={horizontal} />
    </div>
  );
};

// horizontal=true is the phone layout: the same rail laid across the top —
// logo left, doors right — so the composer keeps the whole bottom edge.
// `calm` is the render-quiet switch, and the rail carries it because the glass
// puck lives here: it is the app's only WebGL and the most expensive thing on
// screen. Everything else ambient (PhotonField, DotMatrix, lane videos, the
// surface blur) already stands down while ComfyUI samples; the puck was the
// one holdout, and the one the GPU actually noticed.
export const NavRail = ({ store, onNewCharacter, horizontal, calm }) => (
  <nav aria-label="Primary" style={horizontal ? {
    width: "100%", flexShrink: 0, position: "relative", zIndex: 4,
    display: "flex", flexDirection: "row", alignItems: "center",
    padding: `calc(${SPACE[8]}px + env(safe-area-inset-top)) ${SPACE[12]}px ${SPACE[4]}px`,
    gap: SPACE[6],
  } : {
    width: 76, flexShrink: 0, position: "relative", zIndex: 4,
    display: "flex", flexDirection: "column", alignItems: "center",
    padding: `${SPACE[16]}px 0 ${SPACE[16]}px`, gap: SPACE[10],
  }}>
    <BlockLogo size={horizontal ? 40 : 54} calm={calm} drift={RAIL_DRIFT} />
    <div style={horizontal ? { flex: 1 } : { height: SPACE[8] }} />
    <RailButton icon={ChatsCircle} label={`chats (${store.chats.length})`}
      active={store.chatsOpen} onClick={() => store.setChatsOpen(!store.chatsOpen)} />
    <RailButton icon={Images} label={`past generations (${store.history.length})`}
      active={store.railOpen} onClick={() => store.setRailOpen(!store.railOpen)} />
    <RailButton icon={UserCirclePlus} label="new character"
      active={false} onClick={onNewCharacter} />
    {!horizontal && <div style={{ flex: 1 }} />}
    <RailButton icon={GearSix} label="settings"
      active={store.settingsOpen} onClick={() => store.setSettingsOpen(!store.settingsOpen)} />
    <ComfyDot store={store} horizontal={horizontal} />
  </nav>
);
