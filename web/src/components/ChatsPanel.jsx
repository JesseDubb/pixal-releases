// ChatsPanel.jsx — the left chat list, the familiar LLM-app pattern: newest
// activity first, active chat lit, hover X to close a chat for good, one quiet
// "new chat" action up top. Docks in the same lane as history/settings.
import { Plus, X } from "@phosphor-icons/react";
import { RADIUS, SPACE } from "../lib/design-tokens.js";

const FONT_SIZE = 13;

const when = (ts) => {
  const d = (Date.now() / 1000 - ts) / 60;
  if (d < 1) return "now";
  if (d < 60) return `${Math.round(d)}m`;
  if (d < 60 * 24) return `${Math.round(d / 60)}h`;
  return `${Math.round(d / 1440)}d`;
};

const Row = ({ chat, active, onSelect, onDelete }) => (
  <div role="button" tabIndex={0} onClick={onSelect}
    onKeyDown={(e) => { if (e.key === "Enter") onSelect(); }}
    className="px-chat-row"
    style={{
      display: "flex", alignItems: "center", gap: SPACE[6],
      padding: `${SPACE[8]}px ${SPACE[10]}px`, borderRadius: RADIUS.pill,
      cursor: "pointer", userSelect: "none",
      background: active ? "var(--bg3)" : "transparent",
      color: active ? "var(--text)" : "var(--textSec)",
      transition: "background 140ms ease, color 140ms ease",
    }}
    onMouseEnter={(e) => {
      if (!active) e.currentTarget.style.background = "var(--bg2)";
      e.currentTarget.querySelector(".px-chat-x").style.opacity = 1;
    }}
    onMouseLeave={(e) => {
      if (!active) e.currentTarget.style.background = "transparent";
      e.currentTarget.querySelector(".px-chat-x").style.opacity = 0;
    }}>
    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", whiteSpace: "nowrap",
                   textOverflow: "ellipsis", fontSize: FONT_SIZE }}>
      {chat.title}
    </span>
    <span style={{ fontSize: 11, color: "var(--textTer)", flexShrink: 0 }}>
      {when(chat.ts)}
    </span>
    <button type="button" className="px-chat-x" title="close this chat"
      aria-label={`close chat ${chat.title}`}
      onClick={(e) => { e.stopPropagation(); onDelete(); }}
      style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        width: 22, height: 22, borderRadius: RADIUS.pill, border: "none",
        background: "transparent", color: "var(--textTer)", cursor: "pointer",
        opacity: 0, transition: "opacity 140ms ease", flexShrink: 0,
      }}>
      <X size={13} weight="bold" />
    </button>
  </div>
);

export const ChatsPanel = ({ store, onClose }) => {
  // Render-quiet, Chat.jsx's surface discipline: an 18px backdrop blur left
  // running while ComfyUI samples fights the job for the card.
  const rendering = !!store.liveJobs[0];
  return (
  <div style={{
    height: "100%", display: "flex", flexDirection: "column",
    background: "var(--surface)", border: "1px solid var(--border)",
    borderRadius: RADIUS.surface, overflow: "hidden",
    backdropFilter: rendering ? "none" : "blur(18px)",
    WebkitBackdropFilter: rendering ? "none" : "blur(18px)",
  }}>
    <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                  padding: `${SPACE[12]}px ${SPACE[12]}px ${SPACE[6]}px` }}>
      <span style={{ flex: 1, fontSize: 12, letterSpacing: "0.08em",
                     textTransform: "uppercase", color: "var(--textTer)" }}>
        chats
      </span>
      <button type="button" title="new chat" aria-label="new chat"
        onClick={() => store.chatAction("new")}
        style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          padding: "5px 11px", borderRadius: RADIUS.pill, cursor: "pointer",
          border: "1px solid var(--border)", background: "var(--bg2)",
          color: "var(--textSec)", fontSize: 12,
        }}>
        <Plus size={13} weight="bold" /> new
      </button>
      <button type="button" title="close" aria-label="close chat list"
        onClick={onClose}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 26, height: 26, borderRadius: RADIUS.pill, border: "none",
          background: "transparent", color: "var(--textTer)", cursor: "pointer",
        }}>
        <X size={14} weight="bold" />
      </button>
    </div>
    <div style={{ flex: 1, overflowY: "auto", padding: SPACE[8],
                  display: "flex", flexDirection: "column", gap: 2 }}>
      {store.chats.map((c) => (
        <Row key={c.id} chat={c} active={c.id === store.activeChat}
          onSelect={() => { if (c.id !== store.activeChat) store.chatAction("select", c.id); }}
          onDelete={() => store.chatAction("delete", c.id)} />
      ))}
      {!store.chats.length && (
        <div style={{ padding: SPACE[12], fontSize: FONT_SIZE, color: "var(--textTer)" }}>
          no chats yet
        </div>
      )}
    </div>
  </div>
  );
};
