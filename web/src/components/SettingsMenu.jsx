// SettingsMenu.jsx — five tabs split by medium (General / Image / Video /
// Brain / About). The model decisions used to share one Models tab until it
// grew too crowded to scan (Jesse, 2026-08-22). Every control auto-saves.
// Two presentations, same content: `docked` (default path on wide viewports)
// fills the dock lane beside the rail as a sibling surface card — non-modal,
// so the theme toggle previews against the live chat; the fallback is the old
// bottom-left floating panel budding off the rail's settings button.
// Local-first: everything persists to pixal_dm/config.json via /api/settings.
import { useEffect, useRef, useState } from "react";
import { CaretDown, Check, DesktopTower, Envelope, Eye, EyeSlash, FolderOpen, LockKey, Moon, Plus, Sun, X } from "@phosphor-icons/react";
import { FONT, W, TYPE, SPACE, RADIUS, MOTION, SHADOW } from "../lib/design-tokens.js";
import { Lockup } from "../lib/Lockup.jsx";
import { ComfyWordmark, LightricksMark, MiniMaxMark, NvidiaMark } from "../lib/BrandMarks.jsx";
import { useStore } from "../store.js";

const MONO = "ui-monospace, Consolas, monospace";

// A native <select> with 62 optgrouped options renders as an OS list: no search,
// no breathing room, and styled by the platform rather than the app. This is the
// same scroll-and-pick shape the model and LoRA browsers use - filter on top,
// grouped rows with real vertical rhythm, the scale as a chip rather than more
// text run into the name.
const ScrollPicker = ({ value, options, placeholder, onPick, emptyLabel = "none",
                        required = false }) => {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const boxRef = useRef(null);
  const searchRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (!boxRef.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc);
    searchRef.current?.focus();
    return () => {
      document.removeEventListener("mousedown", away);
      window.removeEventListener("keydown", esc);
    };
  }, [open]);

  const needle = filter.trim().toLowerCase();
  const matches = options.filter((item) => !needle ||
    `${item.label} ${item.name} ${item.group || ""}`.toLowerCase().includes(needle));
  const groups = [];
  matches.forEach((item) => {
    const key = item.group || "";
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(item);
    else groups.push({ key, items: [item] });
  });
  const current = options.find((item) => item.name === value);

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      {/* The trigger shape: fixed height, caret in its own right-hand slot
          with a rotation instead of jammed against the label (Jesse, 2026-08-18). */}
      <button type="button" onClick={() => { setOpen(!open); setFilter(""); }}
        style={{
          width: "100%", height: 38, display: "flex", alignItems: "center",
          gap: SPACE[8], padding: `0 ${SPACE[12]}px`, cursor: "pointer",
          background: "var(--bg2)", border: `1px solid ${open ? "var(--accentStr)" : "var(--border)"}`,
          borderRadius: RADIUS.input, color: current ? "var(--text)" : "var(--textTer)",
          fontFamily: FONT, fontSize: TYPE.ui, textAlign: "left",
          transition: `border-color ${MOTION.hover}`,
        }}
        onMouseEnter={(e) => { if (!open) e.currentTarget.style.borderColor = "var(--borderHov)"; }}
        onMouseLeave={(e) => { if (!open) e.currentTarget.style.borderColor = "var(--border)"; }}>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {current ? current.label : placeholder}
        </span>
        {current?.badge && <Chip>{current.badge}</Chip>}
        <CaretDown size={11} weight="bold" style={{
          color: "var(--textTer)", flexShrink: 0, marginLeft: SPACE[4],
          transform: open ? "rotate(180deg)" : "none",
          transition: `transform ${MOTION.hover}`,
        }} />
      </button>

      {open && (
        <div style={{
          position: "absolute", zIndex: 20, top: "calc(100% + 4px)", left: 0, right: 0,
          maxHeight: 320, overflowY: "auto", padding: SPACE[6],
          background: "var(--bg1)", border: "1px solid var(--borderHov)",
          borderRadius: RADIUS.card, boxShadow: SHADOW.xl,
        }} className="px-scroll">
          <input ref={searchRef} value={filter} onChange={(e) => setFilter(e.target.value)}
            placeholder="filter…" className="px-input"
            style={{
              width: "100%", height: 30, marginBottom: SPACE[6], padding: `0 ${SPACE[8]}px`,
              background: "var(--bg2)", border: "1px solid var(--border)",
              borderRadius: RADIUS.input, color: "var(--text)", outline: "none",
              fontFamily: FONT, fontSize: TYPE.label,
            }} />
          {/* required = the setting has no "none" state (the reviewer must
              name a model), so the clear row would be a trap. */}
          {!required && (
            <PickRow selected={!value} onClick={() => { onPick(""); setOpen(false); }}>
              <span style={{ color: "var(--textTer)" }}>{emptyLabel}</span>
            </PickRow>
          )}
          {groups.map((group) => (
            <div key={group.key || "_"}>
              {group.key && (
                <div style={{
                  padding: `${SPACE[8]}px ${SPACE[8]}px ${SPACE[4]}px`, fontFamily: FONT,
                  fontSize: 9, letterSpacing: "0.09em", textTransform: "uppercase",
                  color: "var(--textMut)",
                }}>{group.key}</div>
              )}
              {group.items.map((item) => (
                <PickRow key={item.name} selected={item.name === value}
                  title={item.name}
                  onClick={() => { onPick(item.name); setOpen(false); }}>
                  <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                                 textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {item.label}
                  </span>
                  {item.badge && <Chip>{item.badge}</Chip>}
                </PickRow>
              ))}
            </div>
          ))}
          {matches.length === 0 && (
            <div style={{ padding: SPACE[10], color: "var(--textTer)", fontSize: TYPE.label }}>
              nothing matches “{filter.trim()}”
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const PickRow = ({ selected, onClick, children, title }) => (
  <button type="button" onClick={onClick} title={title}
    style={{
      width: "100%", minHeight: 34, display: "flex", alignItems: "center", gap: SPACE[8],
      padding: `${SPACE[6]}px ${SPACE[8]}px`, cursor: "pointer", textAlign: "left",
      background: selected ? "var(--accentMut)" : "transparent",
      border: `1px solid ${selected ? "var(--accentStr)" : "transparent"}`,
      borderRadius: RADIUS.input, color: selected ? "var(--accent)" : "var(--textSec)",
      fontFamily: FONT, fontSize: TYPE.ui,
      transition: `background ${MOTION.hover}, color ${MOTION.hover}`,
    }}
    onMouseEnter={(e) => { if (!selected) e.currentTarget.style.background = "var(--bg2)"; }}
    onMouseLeave={(e) => { if (!selected) e.currentTarget.style.background = "transparent"; }}
  >{children}</button>
);

const Chip = ({ children }) => (
  <span style={{
    flexShrink: 0, fontFamily: MONO, fontSize: 9, padding: "1px 6px",
    borderRadius: RADIUS.pill, background: "var(--bg3)",
    border: "1px solid var(--border)", color: "var(--textTer)",
  }}>{children}</span>
);

// ── field furniture, ported from an earlier settings system of mine (2026-08-18) ──
// One skeleton for every setting: micro-caps label, the control, a footnote.
// The rhythm IS the component - the ad-hoc marginTops and per-control pill
// styles were what made these panels read as a wall.
const Field = ({ label, hint, children }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: SPACE[6] }}>
    {label && (
      <span style={{ fontSize: 10, color: "var(--textTer)", fontFamily: FONT,
                     textTransform: "uppercase", letterSpacing: "0.08em" }}>
        {label}
      </span>
    )}
    {children}
    {hint && (
      <span style={{ fontSize: TYPE.label, color: "var(--textTer)",
                     lineHeight: 1.5 }}>{hint}</span>
    )}
  </div>
);

// The contained multi-choice: the theme switcher's track, generalized. Equal
// flex radio segments in one bordered capsule; the active one is a filled
// card. Constant fontWeight across states (a ported rule: swapping weight
// makes auto-width labels jump).
const SegRadio = ({ options, value, onChange, ariaLabel }) => (
  <div role="radiogroup" aria-label={ariaLabel} style={{
    display: "flex", background: "var(--bg2)",
    border: "1px solid var(--border)", borderRadius: RADIUS.pill, padding: 3,
  }}>
    {options.map((opt) => {
      const active = value === opt.v;
      const off = !!opt.disabled;
      return (
        <button key={String(opt.v)} role="radio" aria-checked={active}
          disabled={off} title={opt.title}
          onClick={() => { if (!off) onChange(opt.v); }}
          style={{
            flex: 1, minWidth: 0, padding: "8px 6px", fontSize: TYPE.ui,
            background: active ? "var(--bg4)" : "transparent",
            color: active ? "var(--text)" : "var(--textMut)",
            border: "none", borderRadius: RADIUS.pill,
            cursor: off ? "default" : "pointer", opacity: off ? 0.45 : 1,
            display: "flex", alignItems: "center", justifyContent: "center",
            gap: SPACE[6], fontWeight: W.nav, fontFamily: FONT,
            whiteSpace: "nowrap", overflow: "hidden",
            transition: `background ${MOTION.hover}, color ${MOTION.hover}`,
          }}>
          {opt.Icon && <opt.Icon size={14} weight="duotone" style={{ flexShrink: 0 }} />}
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
            {opt.label}
          </span>
        </button>
      );
    })}
  </div>
);

// Cluster heading inside a tab - the information architecture the flat wall
// of Sections was missing. A hairline carries the eye across.
const GroupLabel = ({ children }) => (
  <div style={{ display: "flex", alignItems: "center", gap: SPACE[10] }}>
    <span style={{ fontSize: 10, fontWeight: W.heading, color: "var(--textMut)",
                   textTransform: "uppercase", letterSpacing: "0.12em",
                   fontFamily: FONT, whiteSpace: "nowrap" }}>{children}</span>
    <span aria-hidden="true" style={{ flex: 1, borderTop: "1px solid var(--border)" }} />
  </div>
);

// Two ways to have a brain: any OpenAI-compatible API, or a GGUF on this PC
// (llama.cpp server the sidecar spawns itself). Quick chips just prefill the
// inputs - users point at whatever provider they like.
const QUICK_APIS = [
  { label: "Kimi", url: "https://api.moonshot.ai/v1", model: "kimi-k3" },
  { label: "DeepSeek", url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { label: "OpenRouter", url: "https://openrouter.ai/api/v1", model: "" },
];
const LOCAL_URL = "http://127.0.0.1:8191/v1";

const SETTINGS_TAB_KEY = "pixal.settings.tab";
// Five rooms (2026-08-22, was three): Models grew too crowded to scan, so the
// model decisions split by medium. General is the machine (appearance, the
// ComfyUI box, VRAM, folders), Image and Video each hold their medium's model
// choices and finishers, Brain is the chat brain and the reviewer, About the
// credits. A stale saved id (e.g. "models") fails the TABS check where `tab`
// is initialised and lands on "general".
const TABS = [
  { id: "general", label: "General" },
  { id: "image", label: "Image" },
  { id: "video", label: "Video" },
  { id: "brain", label: "Brain" },
  { id: "about", label: "About" },
];

// Buy-me-a-beer link — paste your buymeacoffee.com (or ko-fi) page URL here
// and the gold button on the About tab appears. Empty string = no button.
const BEER_URL = "";

// One supporter in the About row: quiet mono mark that lights up in the
// brand's own color on hover — the same treatment the Animate dialog gives
// the active engine, so the brands read but never shout.
const Supporter = ({ label, title, Mark, href }) => {
  const [hover, setHover] = useState(false);
  // A mark that credits someone should go to them. Renders as an anchor when
  // there is a destination and a plain div when there is not, so it is never a
  // div pretending to be a link - focusable, middle-clickable, and it shows the
  // target in the status bar like every other link on the machine.
  const Tag = href ? "a" : "div";
  const link = href ? { href, target: "_blank", rel: "noreferrer" } : {};
  return (
    <Tag title={title} {...link}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{
        display: "flex", flexDirection: "column", alignItems: "center",
        gap: SPACE[6], cursor: href ? "pointer" : "default",
        textDecoration: "none",
        color: hover ? "var(--text)" : "var(--textTer)",
        transition: `color ${MOTION.hover}`,
      }}>
      <Mark size={22} active={hover} />
      <span style={{ fontFamily: FONT, fontSize: TYPE.label, fontWeight: W.nav }}>
        {label}
      </span>
    </Tag>
  );
};

// Linear-style tab strip: bottom-border indicator, no fills. A tab is a place,
// not a button - the quiet chrome keeps the sections themselves loud.
const TabStrip = ({ tabs, value, onChange }) => (
  <div role="tablist" style={{ display: "flex", gap: SPACE[16],
                               borderBottom: "1px solid var(--border)" }}>
    {tabs.map((t) => {
      const active = value === t.id;
      return (
        <button key={t.id} type="button" role="tab" aria-selected={active}
          onClick={() => onChange(t.id)}
          style={{ padding: `${SPACE[6]}px 0 ${SPACE[8]}px`, background: "transparent",
                   border: "none", borderBottom: "2px solid",
                   borderBottomColor: active ? "var(--accent)" : "transparent",
                   marginBottom: -1, cursor: "pointer",
                   color: active ? "var(--text)" : "var(--textTer)",
                   fontFamily: FONT, fontSize: TYPE.ui, fontWeight: W.nav,
                   whiteSpace: "nowrap",
                   transition: `color ${MOTION.hover}, border-color ${MOTION.hover}` }}>
          {t.label}
        </button>
      );
    })}
  </div>
);

// One section = a human title + one plain sentence about what it does.
const Section = ({ title, gloss, children }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: SPACE[10] }}>
    <div>
      <div style={{ fontSize: TYPE.body, fontWeight: W.heading, color: "var(--text)" }}>
        {title}
      </div>
      <div style={{ fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
        {gloss}
      </div>
    </div>
    {children}
  </div>
);

const inputStyle = {
  height: 38, background: "var(--bg2)", border: "1px solid var(--border)",
  borderRadius: RADIUS.pill, padding: `0 ${SPACE[16]}px`, fontSize: TYPE.ui,
  color: "var(--text)", fontFamily: FONT, outline: "none", width: "100%",
};

// tiny capability tag on model rows: accent = content rating, neutral = capability
const MiniChip = ({ children, accent }) => (
  <span style={{
    fontSize: 8, fontWeight: W.heading, letterSpacing: 0.5, lineHeight: 1,
    padding: "2px 5px", borderRadius: RADIUS.pill, flexShrink: 0,
    border: `1px solid ${accent ? "var(--accent)" : "var(--borderStr)"}`,
    color: accent ? "var(--accent)" : "var(--textTer)",
  }}>{children}</span>
);

const Btn = ({ children, onClick, primary, disabled }) => (
  <button type="button" onClick={onClick} disabled={disabled}
    style={{
      height: 34, padding: `0 ${SPACE[16]}px`, fontSize: TYPE.ui, fontFamily: FONT,
      fontWeight: primary ? W.heading : W.body, cursor: disabled ? "default" : "pointer",
      color: primary ? "var(--accentInk)" : "var(--textSec)",
      background: primary ? "var(--accent)" : "var(--bg2)",
      border: `1px solid ${primary ? "var(--accent)" : "var(--border)"}`,
      borderRadius: RADIUS.pill, opacity: disabled ? 0.5 : 1,
      transition: `background ${MOTION.hover}`,
    }}>{children}</button>
);

export const SettingsMenu = ({ onClose, docked, phone }) => {
  const store = useStore();
  const [cfg, setCfg] = useState(null);
  const [mode, setMode] = useState("api");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [localModel, setLocalModel] = useState("");
  const [localList, setLocalList] = useState([]);
  const [localKeep, setLocalKeep] = useState(true);
  const [localGpu, setLocalGpu] = useState(-1);
  const scrolledSel = useRef(false);   // scroll the saved pick into view once per open
  const [criticModel, setCriticModel] = useState("");
  const [criticInstalled, setCriticInstalled] = useState([]);
  const [upscale, setUpscale] = useState(null);
  const [editCfg, setEditCfg] = useState(null);
  const [vae, setVae] = useState(null);
  const [pidCfg, setPidCfg] = useState(null);
  const [videoCfg, setVideoCfg] = useState(null);
  const [comfyEditor, setComfyEditor] = useState(false);
  const [comfyConsole, setComfyConsole] = useState("tui");
  const [explicit, setExplicit] = useState("auto");
  const [vramProfile, setVramProfile] = useState("auto");
  const [roots, setRoots] = useState([]);
  const [extraRoots, setExtraRoots] = useState([]);
  const [newRoot, setNewRoot] = useState("");
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [comfyBusy, setComfyBusy] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [comfyUrl, setComfyUrl] = useState("");
  // The last-used tab is remembered - "where was that setting" usually means
  // the tab you were in yesterday.
  const [tab, setTab] = useState(() => {
    try {
      const saved = window.localStorage.getItem(SETTINGS_TAB_KEY);
      return TABS.some((t) => t.id === saved) ? saved : "general";
    } catch { return "general"; }
  });
  const pickTab = (id) => {
    setTab(id);
    try { window.localStorage.setItem(SETTINGS_TAB_KEY, id); }
    catch { /* private mode / storage disabled */ }
  };

  useEffect(() => {
    fetch("/api/settings").then((r) => r.json()).then((d) => {
      setCfg(d);
      setVramProfile((d.vram && d.vram.profile) || "auto");
      const isLocal = d.llm.base_url.includes("127.0.0.1:8191");
      // when saved brain is local, prefill the API inputs with a sane default
      // instead of leaking the internal :8191 address into them
      setBaseUrl(isLocal ? QUICK_APIS[0].url : d.llm.base_url);
      setModel(isLocal ? QUICK_APIS[0].model : d.llm.model);
      setLocalModel(d.llm.local_model || "");
      setLocalList(d.llm.local_llms || []);
      setLocalKeep(d.llm.local_keep !== false);
      setLocalGpu(Number.isInteger(d.llm.local_gpu_layers) ? d.llm.local_gpu_layers : -1);
      setCriticModel(d.critic.model);
      setCriticInstalled(d.critic.installed || []);
      setUpscale(d.upscale || null);
      setEditCfg(d.edit || null);
      setVae(d.vae || null);
      setPidCfg(d.pid || null);
      setVideoCfg(d.video || null);
      setRoots(d.model_roots);
      setExtraRoots(d.extra_model_roots);
      setComfyUrl(d.comfy_url || "");
      setComfyEditor(!!d.comfy_editor);
      setComfyConsole(d.comfy_console === "plain" ? "plain" : "tui");
      setExplicit(["on", "off"].includes(d.explicit) ? d.explicit : "auto");
      setMode(isLocal ? "local" : "api");
    }).catch(() => setNote({ ok: false, text: "settings endpoint unreachable" }));
  }, []);

  // Auto-apply: every control saves the moment it changes - no Save button.
  const apply = async (partial, okText = "saved") => {
    setBusy(true); setNote(null);
    try {
      const r = await fetch("/api/settings", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(partial) });
      const d = await r.json();
      setNote(d.ok ? { ok: true, text: okText } : { ok: false, text: d.error || "failed" });
      setBusy(false);
      return d.ok;
    } catch (e) { setNote({ ok: false, text: e.message }); }
    setBusy(false);
    return false;
  };

  // ComfyUI lifecycle actions hit their own routes rather than /api/settings -
  // they change nothing that persists, so they must not write config.
  const comfyAction = async (url, pending, okText) => {
    setComfyBusy(true); setNote({ ok: true, text: pending });
    try {
      const r = await fetch(url, { method: "POST",
        headers: { "Content-Type": "application/json" }, body: "{}" });
      const d = await r.json();
      setNote(d.ok ? { ok: true, text: okText }
                   : { ok: false, text: d.error || "failed" });
    } catch (e) { setNote({ ok: false, text: e.message }); }
    setComfyBusy(false);
  };

  // The API inputs apply on blur/Enter - but only when actually changed, so
  // tabbing through the panel doesn't spam config writes.
  const apiDirty = cfg && (baseUrl !== cfg.llm.base_url || model !== cfg.llm.model);
  const applyApi = (url = baseUrl, mdl = model) => {
    if (cfg) setCfg({ ...cfg, llm: { ...cfg.llm, base_url: url, model: mdl } });
    apply({ llm: { base_url: url, model: mdl } }, "api brain applied");
  };

  const test = async () => {
    setBusy(true); setNote(null);
    try {
      const r = await fetch("/api/settings/test", { method: "POST" });
      const d = await r.json();
      setNote(d.ok ? { ok: true, text: "connected - " + d.model }
                   : { ok: false, text: d.error || "test failed" });
    } catch (e) { setNote({ ok: false, text: e.message }); }
    setBusy(false);
  };

  const addRoot = () => {
    const r = newRoot.trim();
    if (r && !extraRoots.includes(r)) {
      const next = [...extraRoots, r];
      setExtraRoots(next);
      apply({ extra_model_roots: next }, "folder added - rescan to index it");
    }
    setNewRoot("");
  };

  // The video model picker lists the chosen default engine's models; with no
  // default engine set it lists every engine's, labeled engine · model.
  const videoEngines = (videoCfg && videoCfg.engines) || [];
  const chosenEngine = videoEngines.find(
    (e) => e.id === (videoCfg && videoCfg.default_engine));
  const videoModelOptions = chosenEngine
    ? (chosenEngine.models || [])
    : videoEngines.flatMap((e) => (e.models || []).map((m) => ({
        ...m, label: `${e.label} · ${m.label}` })));

  return (
    <>
      {!docked && (
        <div style={{ position: "fixed", inset: 0, zIndex: 34, background: "rgba(0,0,0,0.45)" }}
             onClick={onClose} />
      )}
      {/* The CARD owns the shape (overflow hidden); the SCROLL lives on an
          inner region inset by margin, so the scrollbar rides an inner edge
          and never cuts through the rounded corners. */}
      <div style={docked ? {
        // A sibling of the content surface — same card language, no scrim.
        width: "100%", height: "100%",
        background: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: RADIUS.surface, boxShadow: SHADOW.md,
        backdropFilter: "blur(18px)", WebkitBackdropFilter: "blur(18px)",
        display: "flex", flexDirection: "column", overflow: "hidden",
      } : phone ? {
        // Phone: a bottom sheet - full width, hugging the safe-area edge.
        position: "fixed", left: 8, right: 8, zIndex: 35,
        bottom: "calc(8px + env(safe-area-inset-bottom))", maxHeight: "82dvh",
        background: "var(--bg1)", border: "1px solid var(--borderHov)",
        borderRadius: 20, boxShadow: SHADOW.xl,
        display: "flex", flexDirection: "column", overflow: "hidden",
      } : {
        // Fallback (narrow viewports): buds off the rail's settings button.
        position: "fixed", left: 84, bottom: 16, zIndex: 35, width: 400, maxWidth: "92vw",
        maxHeight: "86vh",
        background: "var(--bg1)", border: "1px solid var(--borderHov)",
        borderRadius: 20, boxShadow: SHADOW.xl,
        display: "flex", flexDirection: "column", overflow: "hidden",
      }}>
      {/* Header + tabs stay put; only the tab's content scrolls. */}
      <div style={{ padding: `${SPACE[16]}px ${SPACE[20]}px 0`, display: "flex",
                    flexDirection: "column", gap: SPACE[10] }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: TYPE.h3, fontWeight: W.heading }}>Settings</span>
          <button type="button" onClick={onClose} title="close"
            style={{ display: "inline-flex", alignItems: "center", justifyContent: "center",
                     width: 30, height: 30, background: "var(--bg2)", border: "1px solid var(--border)",
                     borderRadius: RADIUS.pill, color: "var(--textTer)", cursor: "pointer" }}>
            <X size={14} weight="bold" />
          </button>
        </div>
        <TabStrip tabs={TABS} value={tab} onChange={pickTab} />
      </div>
      <div className="px-scroll" style={{
        flex: 1, minHeight: 0, overflowY: "auto", padding: SPACE[20],
        display: "flex", flexDirection: "column", gap: SPACE[20],
      }}>
        {tab === "general" && (<>
        <Section title="Appearance" gloss="How the app looks. System follows Windows.">
          <SegRadio ariaLabel="Appearance" value={store.themePref}
            onChange={(v) => store.setTheme(v)}
            options={[
              { v: "light", label: "Light", Icon: Sun },
              { v: "dark", label: "Dark", Icon: Moon },
              { v: "system", label: "System", Icon: DesktopTower },
            ]} />
        </Section>

        <div style={{ borderTop: "1px solid var(--border)" }} />

        <Section title="Compute"
                 gloss="The ComfyUI box that renders. Another rig's address borrows its GPU.">
          <input style={inputStyle} value={comfyUrl}
                 autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
                 onChange={(e) => setComfyUrl(e.target.value)}
                 onBlur={() => {
                   if (cfg && comfyUrl.trim() !== (cfg.comfy_url || "")) {
                     setCfg({ ...cfg, comfy_url: comfyUrl.trim() });
                     apply({ comfy_url: comfyUrl.trim() }, "compute applied");
                   }
                 }}
                 placeholder="http://127.0.0.1:8188 (this PC)" />
          {/* Freeing is deliberately manual: ComfyUI caches models on purpose,
              and the 21GB video stack staying resident is exactly why a second
              render is fast. Restart is for the state no endpoint can fix. */}
          <div style={{ display: "flex", gap: SPACE[8], marginTop: SPACE[12],
                        flexWrap: "wrap" }}>
            <Btn disabled={comfyBusy} onClick={() => comfyAction(
              "/api/comfy/free", "freeing VRAM", "VRAM released - the chat brain is untouched")}>
              free VRAM
            </Btn>
            <Btn disabled={comfyBusy} onClick={() => comfyAction(
              "/api/comfy/restart", "restarting ComfyUI",
              "ComfyUI restarting - the boot meter takes it from here")}>
              restart
            </Btn>
            {/* The one flush the other button deliberately will not do. It is
                here because a chat model with a grown KV cache was measured at
                7.2GB, and MiniMax H3's DiT alone wants ~20GB of the card. */}
            <Btn disabled={comfyBusy} onClick={() => comfyAction(
              "/api/llm/free", "freeing the chat model",
              "chat model unloaded - the next message brings it back")}>
              free brain
            </Btn>
          </div>
          <div style={{ marginTop: SPACE[6], fontSize: TYPE.label,
                        color: "var(--textMut)", lineHeight: 1.5 }}>
            The next render reloads what freeing dropped. The brain rides its
            own process — free it only when a video clip needs the room.
          </div>
          <div style={{ marginTop: SPACE[12] }}>
            <Field label="when ComfyUI boots"
                   hint={"ComfyUI likes to pop its node editor in a browser tab " +
                         "when it starts. Quiet keeps that from interrupting; the " +
                         "editor is always at the compute address above."}>
              <SegRadio ariaLabel="When ComfyUI boots" value={comfyEditor}
                onChange={(on) => {
                  setComfyEditor(on);
                  apply({ comfy_editor: on },
                        on ? "editor tab will open on the next ComfyUI boot"
                           : "quiet boots applied");
                }}
                options={[{ v: false, label: "quiet" },
                          { v: true, label: "open the graph editor" }]} />
            </Field>
          </div>
          <div style={{ marginTop: SPACE[12] }}>
            <Field label="ComfyUI’s console window"
                   hint={"Meters wrap the same launcher in a boot dashboard and " +
                         "keep an errors-only log at logs\\comfy-errors.log. Plain " +
                         "console is the raw ComfyUI output. Either way, closing " +
                         "that window stops ComfyUI."}>
              <SegRadio ariaLabel="ComfyUI console window" value={comfyConsole}
                onChange={(id) => {
                  setComfyConsole(id);
                  apply({ comfy_console: id },
                        id === "tui" ? "meters on the next ComfyUI boot"
                                     : "plain console on the next ComfyUI boot");
                }}
                options={[{ v: "tui", label: "meters" },
                          { v: "plain", label: "plain console" }]} />
            </Field>
          </div>
        </Section>

        <div style={{ borderTop: "1px solid var(--border)" }} />

        <Section title="VRAM profile"
                 gloss={`What this machine can hold resident.${
                   cfg && cfg.vram && cfg.vram.detected_gb
                     ? ` The card reads as ${Math.round(cfg.vram.detected_gb)} GB.`
                     : " Card not read yet - auto follows it once ComfyUI is up."}`}>
          <SegRadio ariaLabel="VRAM profile" value={vramProfile}
            onChange={(t) => {
              setVramProfile(t);
              apply({ vram_profile: t },
                    t === "auto" ? "following the card" : `pinned the ${t} GB profile`);
            }}
            options={[
              { v: "auto", label: `auto${cfg && cfg.vram && cfg.vram.detected
                  ? ` · ${cfg.vram.detected === "low" ? "under 16" : cfg.vram.detected} GB`
                  : ""}` },
              ...["32", "24", "16"].map((t) => ({ v: t, label: `${t} GB` })),
            ]} />
          <span style={{ fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
            Advisory: pickers flag what a tier holds poorly; the VRAM butler
            still manages the card at render time.
          </span>
        </Section>
        <Section title="Explicit content"
                 gloss="Whether a render may be explicit. Only bites with Prompt
                        enhance off - with it on, the chat brain still decides.">
          <SegRadio ariaLabel="Explicit content" value={explicit}
            onChange={(id) => {
              setExplicit(id);
              apply({ explicit: id },
                    id === "auto" ? "reading it from your words"
                      : id === "on" ? "explicit allowed" : "explicit off");
            }}
            options={[{ v: "auto", label: "auto" },
                      { v: "on", label: "allow" },
                      { v: "off", label: "never" }]} />
          <span style={{ fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
            Auto reads your words; never keeps subjects dressed; allow leaves
            your prompt alone.
          </span>
        </Section>

        <div style={{ borderTop: "1px solid var(--border)" }} />

        <Section title="Model folders"
                 gloss={`Where your checkpoints and LoRAs live.${cfg ? ` Found ${cfg.catalog_size} files.` : ""}`}>
          {roots.map((r) => (
            <div key={r} style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                                  fontFamily: MONO, fontSize: 10, color: "var(--textSec)" }}>
              <FolderOpen size={12} weight="duotone" style={{ color: "var(--textTer)",
                                                             flexShrink: 0 }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}>{r}</span>
            </div>
          ))}
          {extraRoots.map((r) => (
            <div key={r} style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                                  fontFamily: MONO, fontSize: 10, color: "var(--text)" }}>
              <FolderOpen size={12} weight="duotone" style={{ color: "var(--accent)",
                                                             flexShrink: 0 }} />
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}>{r}</span>
              <button type="button" onClick={() => {
                  const next = extraRoots.filter((x) => x !== r);
                  setExtraRoots(next);
                  apply({ extra_model_roots: next }, "folder removed");
                }}
                title="remove folder"
                style={{ background: "none", border: "none", color: "var(--textTer)",
                         cursor: "pointer", padding: 2 }}>
                <X size={10} weight="bold" />
              </button>
            </div>
          ))}
          <div style={{ display: "flex", gap: SPACE[6], alignItems: "center" }}>
            <input style={{ ...inputStyle, fontFamily: MONO, fontSize: 10 }} value={newRoot}
                   onChange={(e) => setNewRoot(e.target.value)}
                   placeholder="add a folder, e.g. D:\models"
                   onKeyDown={(e) => e.key === "Enter" && addRoot()} />
            <button type="button" onClick={addRoot} title="add folder"
              style={{
                width: 38, height: 38, flexShrink: 0, cursor: "pointer",
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                background: "var(--bg2)", border: "1px solid var(--border)",
                borderRadius: RADIUS.pill, color: "var(--textSec)",
                transition: `border-color ${MOTION.hover}, color ${MOTION.hover}`,
              }}>
              <Plus size={14} weight="bold" />
            </button>
          </div>
          <div style={{ display: "flex" }}>
            <Btn onClick={async () => {
              setNote(null); setBusy(true);
              try {
                await fetch("/api/settings/rescan", { method: "POST" });
                setNote({ ok: true, text: "rescanning - watch the status row" });
              } catch (e) { setNote({ ok: false, text: e.message }); }
              setBusy(false);
            }} disabled={busy}>rescan folders</Btn>
          </div>
        </Section>
        </>)}

        {tab === "video" && (<>
        <GroupLabel>defaults</GroupLabel>
        <Section title="Video engine"
                 gloss={"Which engine the Animate popup opens on. The popup " +
                        "still switches freely per clip - this only sets where " +
                        "it starts."}>
          <SegRadio ariaLabel="Default video engine"
            value={(videoCfg && videoCfg.default_engine) || ""}
            onChange={(id) => {
              setVideoCfg((v) => ({ ...(v || {}), default_engine: id }));
              const label = id
                ? ((videoCfg?.engines || []).find((e) => e.id === id)?.label || id)
                : "";
              apply({ video: { default_engine: id } },
                    id ? `${label} opens first` : "following the server's order");
            }}
            options={[
              { v: "", label: "auto" },
              ...((videoCfg && videoCfg.engines) || []).map((e) => ({
                v: e.id, label: e.label,
                disabled: e.available === false,
                title: e.available === false ? `${e.label}: assets missing` : undefined,
              })),
            ]} />
        </Section>
        <Section title="Video model"
                 gloss={"Which model the Animate popup opens on inside its " +
                        "engine - the popup still switches freely per clip."}>
          <ScrollPicker
            value={(videoCfg && videoCfg.default_model) || ""}
            placeholder="first available"
            emptyLabel="first available"
            options={videoModelOptions.map((m) => ({
              name: m.id, label: m.label,
              badge: m.available === false ? "missing" : "",
            }))}
            onPick={(id) => {
              setVideoCfg((v) => ({ ...(v || {}), default_model: id }));
              const label = id
                ? (videoModelOptions.find((m) => m.id === id)?.label || id)
                : "";
              apply({ video: { default_model: id } },
                    id ? `${label} opens first` : "first available");
            }} />
        </Section>
        <GroupLabel>finishing</GroupLabel>
        <Section title="Upscaler"
                 gloss="Used by the upscale button on a finished clip.">
          {upscale ? (
            <Field label="video clips"
                   hint={(upscale.video_mode || "").startsWith("LTX")
                     ? "Re-rendered at 2× through the LTX 2.5 latent upsampler — real new detail, audio untouched."
                     : upscale.video_available
                       ? `Doubled at ${upscale.video_scale}× with audio kept.`
                       : "Install the Deno RTX VFX node pack to upscale clips."}>
              <SegRadio ariaLabel="Video upscale engine"
                value={upscale.video_mode || ""}
                onChange={(m) => {
                  setUpscale({ ...upscale, video_mode: m });
                  apply({ upscale: { video_mode: m } }, "clip quality applied");
                }}
                options={(upscale.video_modes || []).map((m) => ({
                  v: m, label: m.replace("VSR ", ""),
                  disabled: !(m.startsWith("LTX")
                    ? upscale.ltx25_video_available : upscale.video_available),
                }))} />
            </Field>
          ) : (
            <span style={{ fontSize: TYPE.label, color: "var(--textTer)" }}>loading…</span>
          )}
        </Section>
        </>)}

        {tab === "image" && (<>
        <GroupLabel>model choices</GroupLabel>
        <Section title="Z-Image decoder"
                 gloss="Z-Image and Flux share a VAE, so sharper drop-in decoders exist. Optional: they can over-sharpen on a single pass.">
          {vae ? (
            <div style={{ display: "flex", flexDirection: "column", gap: SPACE[8] }}>
              <ScrollPicker
                value={vae.zimage || ""}
                placeholder="stock Z-Image VAE (recommended)"
                emptyLabel="stock Z-Image VAE (recommended)"
                options={(vae.installed || []).map((name) => ({ name, label: name }))}
                onPick={(name) => {
                  setVae({ ...vae, zimage: name });
                  apply({ vae: { zimage: name } },
                        name ? "decoder applied" : "stock decoder restored");
                }} />
              <span style={{ fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
                Applies to Z-Image renders only. The clear-anime profile keeps its own
                matched VAE either way.
              </span>
            </div>
          ) : (
            <span style={{ fontSize: TYPE.label, color: "var(--textTer)" }}>loading…</span>
          )}
        </Section>
        <Section title="Edit model"
                 gloss="Runs instruction edits. Qwen-Image-Edit releases differ in encoder node, not just weights - the graph switches on the filename, so any compatible generation works.">
          {editCfg ? (
            <div style={{ display: "flex", flexDirection: "column", gap: SPACE[8] }}>
              <ScrollPicker
                value={editCfg.model || ""}
                placeholder="recipe default"
                emptyLabel="recipe default"
                options={(editCfg.installed || []).map((name) => ({ name, label: name }))}
                onPick={(name) => {
                  setEditCfg({ ...editCfg, model: name });
                  apply({ edit: { model: name } },
                        name ? "edit model applied" : "recipe default restored");
                }} />
              <span style={{ fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
                {(editCfg.installed || []).length} compatible installed. Used by the edit
                button on a finished render and by an attached photo.
              </span>
            </div>
          ) : (
            <span style={{ fontSize: TYPE.label, color: "var(--textTer)" }}>loading…</span>
          )}
        </Section>
        <GroupLabel>finishing</GroupLabel>
        <Section title="Upscaler"
                 gloss="Used by the upscale button on a finished render. Model mode enlarges the frame it already made; PiD mode repaints it tile by tile with NVIDIA's pixel-diffusion decoder.">
          {upscale ? (
            <div style={{ display: "flex", flexDirection: "column", gap: SPACE[8] }}>
              <Field label="still frames"
                     hint={(upscale.image_mode || "model") === "pid"
                       ? "NVIDIA PiD v1.5, INT8 ConvRot. 4-step diffusion in " +
                         "1024px tiles at 4× — any aspect ratio; invents texture " +
                         "instead of sharpening. Models auto-download on first " +
                         "use. Non-commercial license."
                       : upscale.pid_available === false
                         ? "Install the ComfyUI-PiD node pack for PiD."
                         : undefined}>
                <SegRadio ariaLabel="Image upscale mode"
                  value={upscale.image_mode || "model"}
                  onChange={(m) => {
                    setUpscale({ ...upscale, image_mode: m });
                    apply({ upscale: { image_mode: m } },
                          m === "pid" ? "PiD upscaler applied" : "model upscaler applied");
                  }}
                  options={[
                    { v: "model", label: "Model" },
                    { v: "pid", label: "PiD 4×",
                      disabled: upscale.pid_available === false,
                      title: upscale.pid_available === false
                        ? "install the ComfyUI-PiD node pack" : undefined },
                  ]} />
              </Field>
              <ScrollPicker
                value={upscale.image_model || ""}
                placeholder="choose an upscale model…"
                emptyLabel="no upscaler"
                options={(upscale.installed || []).map((item) => ({
                  name: item.name, label: item.short || item.name,
                  group: item.group,
                  badge: item.scale_hint ? `${item.scale_hint}×` : "",
                }))}
                onPick={(name) => {
                  setUpscale({ ...upscale, image_model: name });
                  apply({ upscale: { image_model: name } },
                        name ? "upscaler applied" : "upscaler cleared");
                }} />
              <span style={{ fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
                {(upscale.installed || []).length} installed. The model's own factor
                decides the size — a 4× model on a 1024-wide frame gives 4096.
              </span>
            </div>
          ) : (
            <span style={{ fontSize: TYPE.label, color: "var(--textTer)" }}>loading…</span>
          )}
        </Section>

        <div style={{ borderTop: "1px solid var(--border)" }} />

        <Section title="PiD finish"
                 gloss="Identity Edit renders decode through NVIDIA PiD instead of the Wan VAE: the finished latent is repainted at 4× in a 4-step diffusion pass.">
          {pidCfg ? (
            <Field hint={"Experimental: the canvas snaps to PiD's 1024-class " +
                         "presets and comes back 4× (2:3 → 2688×4032)."}>
              <SegRadio ariaLabel="Identity Edit finish"
                value={!!pidCfg.identity_finish}
                onChange={(on) => {
                  setPidCfg({ ...pidCfg, identity_finish: on });
                  apply({ pid: { identity_finish: on } },
                        on ? "PiD finish on" : "stock decode restored");
                }}
                options={[
                  { v: false, label: "Wan VAE" },
                  { v: true, label: "PiD 4×",
                    disabled: pidCfg.decode_available === false,
                    title: pidCfg.decode_available === false
                      ? "install the ComfyUI-PiD node pack" : undefined },
                ]} />
            </Field>
          ) : (
            <span style={{ fontSize: TYPE.label, color: "var(--textTer)" }}>loading…</span>
          )}
        </Section>
        </>)}

        {tab === "brain" && (<>
        <Section title="Chat brain"
                 gloss="The AI you talk to. It writes the prompts and drives ComfyUI.">
          {/* API | Local swaps the whole panel below it — a control that
              changes what else is on the screen is navigation, so it wears
              the same tab strip as the top-level settings nav, not a pill
              row (Jesse, 2026-08-22). The value controls stay SegRadio. */}
          <TabStrip
            tabs={[{ id: "api", label: "API" }, { id: "local", label: "Local" }]}
            value={mode}
            onChange={(m) => {
              if (m === mode) return;
              setMode(m);
              if (m === "local") {
                if (cfg) setCfg({ ...cfg, llm: { ...cfg.llm, base_url: LOCAL_URL, model: "local" } });
                apply({ llm: { base_url: LOCAL_URL, model: "local", local_model: localModel } },
                      localModel ? "local brain on" : "local brain on - pick a model below");
              } else {
                applyApi();
              }
            }} />
          {mode === "local" ? (<>
            {/* maxHeight bounds whole rows — 6 rows × 36px + 5 × 6px gaps
                = 246. The old 230 sliced a row through its middle at the top
                edge ("Gemma 3 12B Heretic" cut horizontally), which read as a
                rendering fault rather than a scroll. */}
            {localList.length ? (
              <div className="px-scroll" style={{ display: "flex", flexDirection: "column",
                                                  gap: SPACE[6], maxHeight: 246, overflowY: "auto" }}>
                {localList.map((m) => {
                  const sel = localModel === m.path;
                  return (
                    <button key={m.path} type="button" title={m.name}
                      ref={sel ? (el) => {
                        if (el && !scrolledSel.current) {
                          scrolledSel.current = true;
                          el.scrollIntoView({ block: "nearest" });
                        }
                      } : null}
                      onClick={() => {
                        setLocalModel(m.path);
                        apply({ llm: mode === "local"
                                  ? { base_url: LOCAL_URL, model: "local", local_model: m.path }
                                  : { local_model: m.path } },
                              "model applied - loads on your next message");
                      }}
                      style={{
                        display: "flex", alignItems: "center", gap: SPACE[8],
                        height: 36, minHeight: 36, flexShrink: 0, cursor: "pointer",
                        padding: `0 ${SPACE[12]}px`, borderRadius: RADIUS.pill,
                        fontFamily: FONT, fontSize: TYPE.ui, border: "1px solid",
                        borderColor: sel ? "var(--accent)" : "var(--border)",
                        background: sel ? "var(--accentMut)" : "transparent",
                        color: sel ? "var(--accent)" : "var(--textSec)",
                        transition: `border-color ${MOTION.hover}, color ${MOTION.hover}`,
                      }}>
                      {sel && <Check size={13} weight="bold" style={{ flexShrink: 0 }} />}
                      <span style={{ whiteSpace: "nowrap", overflow: "hidden",
                                     textOverflow: "ellipsis" }}>{m.title || m.name}</span>
                      <span style={{ marginLeft: "auto", display: "inline-flex",
                                     alignItems: "center", gap: SPACE[6], flexShrink: 0 }}>
                        {m.vision && <MiniChip>VISION</MiniChip>}
                        {m.nsfw && <MiniChip accent>NSFW</MiniChip>}
                        <span style={{ fontSize: TYPE.label, fontFamily: MONO,
                                       color: sel ? "var(--accent)" : "var(--textTer)" }}>
                          {[m.quant, m.size_gb].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div style={{ fontSize: TYPE.label, color: "var(--textTer)" }}>
                no .gguf chat models found in your model folders
              </div>
            )}
            {/* A stored value, not navigation — stays a SegRadio. With
                "brain runs on" below that is two segment rows in this panel,
                the cap; a third would mean the grouping is wrong. */}
            <SegRadio ariaLabel="memory policy" value={localKeep}
              onChange={(keep) => {
                setLocalKeep(keep);
                apply({ llm: { local_keep: keep } },
                      keep ? "model stays loaded - fast replies"
                           : "will unload after each reply - frees VRAM for renders");
              }}
              options={[{ v: true, label: "keep in memory" },
                        { v: false, label: "unload after reply" }]} />
            <Field label="brain runs on"
                   hint={"GPU replies fast but holds VRAM next to the render; " +
                         "CPU chat is slow but frees the card for rendering."}>
              <SegRadio ariaLabel="brain runs on" value={localGpu}
                onChange={(v) => {
                  setLocalGpu(v);
                  apply({ llm: { local_gpu_layers: v } },
                        v === 0 ? "brain runs on CPU from its next load"
                                : "brain runs on GPU from its next load");
                }}
                options={[
                  { v: -1, label: "GPU" },
                  { v: 0, label: "CPU" },
                ]} />
            </Field>
            <div style={{ display: "flex", alignItems: "center", gap: 5,
                          fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
              <LockKey size={11} weight="duotone" />
              runs entirely on this PC - no key, nothing leaves the machine. Pixal
              starts and stops it for you. Keep in memory = instant replies but the
              model holds a few GB of VRAM; unload = slower first reply, free VRAM.
            </div>
          </>) : (<>
            {/* The quick chips are one-press actions (they prefill the two
                fields below), so they wear Btn — a chosen segment and a
                pressable button must never share one shape, and these hold
                no state of their own. */}
            <div style={{ display: "flex", gap: SPACE[6] }}>
              {QUICK_APIS.map((q) => (
                <Btn key={q.label} onClick={() => {
                  setBaseUrl(q.url);
                  if (q.model) setModel(q.model);
                  applyApi(q.url, q.model || model);
                }}>{q.label}</Btn>
              ))}
            </div>
            <input style={inputStyle} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
                   autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
                   onBlur={() => apiDirty && applyApi()}
                   onKeyDown={(e) => e.key === "Enter" && apiDirty && applyApi()}
                   placeholder="server address (e.g. https://api.deepseek.com/v1)" />
            <input style={inputStyle} value={model} onChange={(e) => setModel(e.target.value)}
                   autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
                   onBlur={() => apiDirty && applyApi()}
                   onKeyDown={(e) => e.key === "Enter" && apiDirty && applyApi()}
                   placeholder="model name (e.g. deepseek-chat)" />
            <div style={{ position: "relative" }}>
              <input style={{ ...inputStyle, paddingRight: 40 }}
                     type={showKey ? "text" : "password"} value={apiKey}
                     autoComplete="off" autoCorrect="off" autoCapitalize="off"
                     spellCheck={false}
                     onChange={(e) => setApiKey(e.target.value)}
                     onBlur={() => {
                       const k = apiKey.trim();
                       if (!k) return;
                       apply({ llm: { api_key: k } }, "key saved");
                       setApiKey("");
                       if (cfg) setCfg({ ...cfg, llm: { ...cfg.llm, key_set: true,
                                                        key_tail: k.slice(-4) } });
                     }}
                     placeholder={cfg && cfg.llm.key_set
                       ? `API key saved (ends …${cfg.llm.key_tail}) - blank keeps it`
                       : "API key (sk-…)"} />
              <button type="button" onClick={() => setShowKey(!showKey)}
                      title={showKey ? "hide key" : "show key"}
                      style={{
                        position: "absolute", right: 6, top: "50%",
                        transform: "translateY(-50%)", width: 28, height: 28,
                        display: "inline-flex", alignItems: "center", justifyContent: "center",
                        background: "none", border: "none", color: "var(--textTer)",
                        cursor: "pointer",
                      }}>
                {showKey ? <EyeSlash size={14} weight="duotone" /> : <Eye size={14} weight="duotone" />}
              </button>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 5,
                          fontSize: TYPE.label, color: "var(--textTer)" }}>
              <LockKey size={11} weight="duotone" />
              what happens local stays local - the key only goes to the provider
              you picked, never into your renders&apos; PNG metadata.
            </div>
          </>)}
        </Section>
        <div style={{ display: "flex" }}>
          <Btn onClick={test} disabled={busy}>Test connection</Btn>
        </div>

        <div style={{ borderTop: "1px solid var(--border)" }} />

        <Section title="Image reviewer"
                 gloss={"Looks at what you made and suggests fixes. When the chat " +
                        "brain has vision, it reviews directly - this ComfyUI model " +
                        "is the fallback for brains without eyes."}>
          <ScrollPicker required
            value={criticModel}
            placeholder="choose a reviewer model…"
            options={criticInstalled.map((m) => ({
              name: m.name || m, label: m.name || m,
              badge: m.nsfw ? "NSFW" : "",
            }))}
            onPick={(nm) => {
              if (!nm) return;
              setCriticModel(nm);
              apply({ critic: { model: nm } }, "reviewer applied");
            }} />
          <span style={{ fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
            Bigger models read hands and text better. First use takes ~30s to warm up.
          </span>
        </Section>
        </>)}

        {tab === "about" && (
        /* The credits card. Centered hero composition — wordmark, the human
           behind it, the beer, the shoulders it stands on. Deliberately the
           one screenshot-friendly view in settings. */
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          textAlign: "center", gap: SPACE[16], padding: `${SPACE[12]}px 0`,
        }}>
          {/* The real lockup, not the wordmark retyped in Syne. Its ink is
              vertically centred inside the viewBox, so alignItems:center lines
              the version up against it with no magic offset - baseline would
              not work here at all, an SVG has none. */}
          <div style={{ display: "flex", alignItems: "center", gap: SPACE[10] }}>
            <Lockup height={52} />
            <span style={{ fontFamily: MONO, fontSize: TYPE.ui,
                           fontVariantNumeric: "tabular-nums",
                           color: "var(--textTer)" }}>
              {cfg?.pixal_version || "—"}
            </span>
            {cfg?.pixal_channel && (
              <span style={{
                fontFamily: FONT, fontSize: 9, fontWeight: W.nav,
                letterSpacing: "0.09em", textTransform: "uppercase",
                color: "var(--textTer)", border: "1px solid var(--border)",
                borderRadius: RADIUS.pill, padding: "3px 8px", lineHeight: 1.3,
              }}>{cfg.pixal_channel}</span>
            )}
          </div>
          <div style={{ fontSize: TYPE.body, color: "var(--textSec)",
                        lineHeight: 1.5, maxWidth: 300 }}>
            Chat with your GPU. Images and video on your own ComfyUI —
            no graphs, no node soup.
          </div>

          <div style={{ width: "100%", borderTop: "1px solid var(--border)" }} />

          <div style={{ display: "flex", flexDirection: "column",
                        alignItems: "center", gap: SPACE[8] }}>
            <span style={{ fontSize: TYPE.body, fontWeight: W.heading,
                           color: "var(--text)" }}>
              Developed by Jesse
            </span>
            <span style={{ fontSize: TYPE.label, color: "var(--textTer)",
                           lineHeight: 1.5 }}>
              Questions? Looking for dev or design?
            </span>
            <a href="mailto:hello@getpixal.com"
               style={{
                 display: "inline-flex", alignItems: "center", gap: SPACE[6],
                 height: 32, padding: `0 ${SPACE[12]}px`, borderRadius: RADIUS.pill,
                 border: "1px solid var(--border)", background: "var(--bg2)",
                 color: "var(--textSec)", textDecoration: "none",
                 fontFamily: FONT, fontSize: TYPE.ui,
                 transition: `border-color ${MOTION.hover}, color ${MOTION.hover}`,
               }}
               onMouseEnter={(e) => {
                 e.currentTarget.style.color = "var(--text)";
                 e.currentTarget.style.borderColor = "var(--borderHov)";
               }}
               onMouseLeave={(e) => {
                 e.currentTarget.style.color = "var(--textSec)";
                 e.currentTarget.style.borderColor = "var(--border)";
               }}>
              <Envelope size={13} weight="duotone" />
              hello@getpixal.com
            </a>
            {BEER_URL && (
              /* Fixed gold + dark ink in BOTH themes (like GLASS) — the beer
                 button is the one loud thing on this card, by design. */
              <a href={BEER_URL} target="_blank" rel="noreferrer"
                 style={{
                   display: "inline-flex", alignItems: "center", gap: SPACE[8],
                   height: 40, padding: `0 ${SPACE[20]}px`, marginTop: SPACE[4],
                   borderRadius: RADIUS.pill, background: "#FFDD00",
                   color: "#1A1200", textDecoration: "none",
                   fontFamily: FONT, fontSize: TYPE.body, fontWeight: W.heading,
                   boxShadow: SHADOW.sm,
                   transition: `transform ${MOTION.press}, box-shadow ${MOTION.press}`,
                 }}
                 onMouseEnter={(e) => {
                   e.currentTarget.style.transform = "translateY(-1px)";
                   e.currentTarget.style.boxShadow = SHADOW.md;
                 }}
                 onMouseLeave={(e) => {
                   e.currentTarget.style.transform = "translateY(0)";
                   e.currentTarget.style.boxShadow = SHADOW.sm;
                 }}>
                🍺 Buy me a beer
              </a>
            )}
          </div>

          <div style={{ width: "100%", borderTop: "1px solid var(--border)" }} />

          <div style={{ display: "flex", flexDirection: "column",
                        alignItems: "center", gap: SPACE[12] }}>
            <span style={{ fontSize: 9, letterSpacing: "0.12em",
                           textTransform: "uppercase", color: "var(--textMut)",
                           fontFamily: FONT, fontWeight: W.nav }}>
              thank you for supporting open source
            </span>
            <div style={{ display: "flex", alignItems: "flex-start", gap: SPACE[24] }}>
              <Supporter label="NVIDIA" Mark={NvidiaMark}
                href="https://huggingface.co/nvidia/PiD"
                title="PiD pixel-diffusion upscaling · RTX video super resolution" />
              <Supporter label="LTX" Mark={LightricksMark}
                href="https://www.lightricks.com"
                title="Lightricks LTX-Video — the fast animate engine" />
              <Supporter label="MiniMax" Mark={MiniMaxMark}
                href="https://www.minimax.io"
                title="MiniMax Hailuo H3 — video with native audio" />
            </div>
            <span style={{ fontSize: 9, color: "var(--textMut)", lineHeight: 1.5 }}>
              Marks are trademarks of their respective owners.
            </span>
          </div>

          <div style={{ width: "100%", borderTop: "1px solid var(--border)" }} />

          {/* The foundation gets its own card, not a slot in the supporter
              row — Pixal exists because ComfyUI does. Hover turns the maze
              its own brand chartreuse. */}
          <Supporter label="" title="comfy.org" Mark={ComfyWordmark}
            href="https://www.comfy.org" />
          <div style={{ fontSize: TYPE.label, color: "var(--textTer)",
                        lineHeight: 1.6, maxWidth: 320, marginTop: -SPACE[8] }}>
            Thank you to the ComfyUI team for building such an amazing
            community of workflow samurais and node builders around the
            open-source model world. Every render here runs on it.
          </div>
        </div>
        )}
      </div>
      {/* Every control auto-saves; this strip is where the save talks back.
          Pinned under the scroll so feedback is visible from any tab. */}
      {note && (
        <div style={{ padding: `${SPACE[8]}px ${SPACE[20]}px`,
                      borderTop: "1px solid var(--border)" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4,
                         fontSize: TYPE.label,
                         color: note.ok ? "#7BB495" : "#E3A7B0" }}>
            {note.ok && <Check size={11} weight="bold" />}{note.text}
          </span>
        </div>
      )}
      </div>
    </>
  );
};
