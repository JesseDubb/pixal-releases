// SettingsMenu.jsx — six tabs (General / Image / Video / Models / Brain /
// About). The model decisions used to share one Models tab until it grew too
// crowded to scan, so the choosing split by medium (Jesse, 2026-08-22); the
// Models tab that came back (9.30) is the other half of that story — the
// read-only library, everything you own grouped by family. Controls auto-save.
// Two presentations, same content: `docked` (default path on wide viewports)
// fills the dock lane beside the rail as a sibling surface card — non-modal,
// so the theme toggle previews against the live chat; the fallback is the old
// bottom-left floating panel budding off the rail's settings button.
// Local-first: everything persists to pixal_dm/config.json via /api/settings.
import { Fragment, Children, createContext, useContext, useEffect, useRef, useState } from "react";
import { CaretDown, Check, DesktopTower, Envelope, Eye, EyeSlash, FolderOpen, LockKey, Moon, Plus, Sun, ArrowSquareOut, X } from "@phosphor-icons/react";
import { FONT, W, TYPE, SPACE, RADIUS, MOTION, SHADOW, OVERLAY } from "../lib/design-tokens.js";
import { Lockup } from "../lib/Lockup.jsx";
import { ModalShell, OverlayMotionStyle } from "../lib/ModalShell.jsx";
import { Picker } from "../lib/Picker.jsx";
import { Chip } from "../lib/Chip.jsx";
import { SegmentedControl } from "../lib/SegmentedControl.jsx";
import { Switch } from "../lib/Switch.jsx";
import { ComfyWordmark, LightricksMark, MiniMaxMark, NvidiaMark } from "../lib/BrandMarks.jsx";
import { InfoTip } from "./InfoTip.jsx";
import { Bar, LineGhost, PickerGhost, SegGhost, SkeletonStyle, SwitchGhost, ValueGhost } from "./Skeleton.jsx";
import { familyName, prettyModel, prettyTemplate } from "../lib/names.js";
import { useStore } from "../store.js";

const MONO = "ui-monospace, Consolas, monospace";

// NVIDIA's #76B900, always on - Jesse: "should have nvidia logo in full color
// accent". These marks say WHOSE technology an option is, which is the one
// thing a name like "Model" or "Ultra" never told you; that is not selection
// state, so it does not dim when the segment is unselected. The segmented
// control hands its icons a `size`, which is all either mark needs.
const NvidiaAccent = ({ size }) => <NvidiaMark size={size} active />;

// Must match server.py's LTX25_UPSCALE_MODE exactly - it is the stored value,
// not a display string, and the wire has not changed.
const LTX25_VIDEO_MODE = "LTX 2.5 2x";
const VSR_DEFAULT_MODE = "VSR High";

// ── the 34px beat (brief 10.0) ────────────────────────────────────────────
// The stacked wall is gone: every setting row is ONE line, 34px exactly -
// label and its one-fact subline inline on the left, the control on the
// right rail (Field below IS the row). Jesse on the old panel: "really
// loose on the vertical spacing rhythm ... doesnt feel like a professional
// app." The beat is what makes it feel measured:
//
//     0   between consecutive rows in a run - the 34px height IS the gap
//     8   inside a Section: title -> content, block -> block
//    16   above a row run that CONTINUES its cluster after a Section
//         (px-set-rows--cont: the run is a peer of the Section's rows, not
//         a new cluster)
//    12   under a cluster heading (GroupLabel)
//    32   between clusters (the scroll container's own gap)
//    48   above a cluster heading
//
// Rows always travel in a named run (Rows / px-set-rows): the scroll
// container gaps every direct child 32, so unwrapped rows would read as
// clusters of one. The asymmetry that mattered survives: 8 under a
// heading against 48 above it means the heading still opens what follows
// instead of floating between two groups - and 8 is the SAME air a
// Section title keeps above its rows, because heading and title share one
// register now (Jesse, 2026-09-01). The offsets are relative to the
// container's own 32px gap.
const CSS = `
.px-set-group { margin-top: 16px; }
.px-set > .px-set-group:first-child { margin-top: 0; }
.px-set > .px-set-group + * { margin-top: -24px; }
.px-set > .px-set-rows--cont { margin-top: -16px; }
`;

// ── loading: ghosts, not guesses ─────────────────────────────────────────
// Twelve slots below start empty and land together from /api/settings (the
// twelfth, `upd`, is About's update check). A control whose options or
// stored value are still in flight renders a ghost of its FINAL size -
// SegGhost is the 28px pill-selector capsule, PickerGhost the 24px value
// pill, SwitchGhost the 42x16 toggle track - so the panel's scrollHeight is identical before and after the
// fetches land and nothing below a ghost ever moves. The swap is
// px-ghost-in: opacity only, never a height animation (DESIGN.md §5). And a
// segment row never shows a DEFAULTED selection while its stored value is
// in flight - Explicit content lit on "auto" with "on" stored was the lie
// that started this. Where only a value is late - the detected card, the
// installed counts - the value ghosts and the label stays.
// tests/test_settings_loading.py holds all of it.

// A native <select> with 62 optgrouped options renders as an OS list: no search,
// no breathing room, and styled by the platform rather than the app. This is the
// same scroll-and-pick shape the model and LoRA browsers use - filter on top,
// grouped rows with real vertical rhythm, the scale as a chip rather than more
// text run into the name.
const ScrollPicker = ({ value, options, placeholder, onPick, emptyLabel = "none",
                        required = false, className }) => {
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
    <div ref={boxRef} className={className} style={{ position: "relative" }}>
      {/* The trigger shape: fixed height, caret in its own right-hand slot
          with a rotation instead of jammed against the label (Jesse, 2026-08-18). */}
      <button type="button" onClick={() => { setOpen(!open); setFilter(""); }}
        style={{
          width: "fit-content", maxWidth: 260, height: 24, display: "flex", alignItems: "center",
          gap: SPACE[8], padding: `0 ${SPACE[12]}px`, cursor: "pointer",
          background: "var(--bg3)", border: `1px solid ${open ? "var(--accentStr)" : "var(--border)"}`,
          borderRadius: RADIUS.pill, color: current ? "var(--text)" : "var(--textTer)",
          fontFamily: FONT, fontSize: TYPE.label, fontWeight: W.nav, textAlign: "left",
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
          // The pill hugs its value on the row's right rail, so the list hangs
          // off the pill's RIGHT edge (the panel edge is right there) and
          // opens as wide as its rows need, capped.
          position: "absolute", zIndex: 20, top: "calc(100% + 4px)", right: 0,
          minWidth: "100%", width: "max-content", maxWidth: 340,
          transformOrigin: "top right",
          maxHeight: 320, overflowY: "auto", padding: SPACE[6],
          background: "var(--bg1)", border: "1px solid var(--borderHov)",
          borderRadius: RADIUS.card, boxShadow: SHADOW.xl,
        }} className="px-scroll px-ov-pop">
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
                  title={item.title || item.name}
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

// One edit-lane option (9.29), in the shared Picker's shape (9.73): `id` is
// the raw build name the pick posts, `label` the product name plus what the
// build weighs on disk in MotionDirector's GB format. A build heavier than
// the detected card says so on the description line - Picker rows have no
// per-row tooltip, and the filter searches label + description, so the
// warning rides there (9.70's chips move). One honest line, advisory only:
// no badge, no colour, no block. The render-time butler prices the real fit;
// a null detected_gb or an unknown size says nothing at all. `group` folders
// the row under a family name (9.44): the whole-frame lane lists Qwen and
// Klein builds together, and the family is the level someone actually
// chooses at.
const editLaneOptions = (list, detectedGb, group) => (list || []).map((e) => {
  const gb = e.size ? e.size / 1e9 : 0;
  const heavy = gb > 0 && detectedGb > 0 && gb > detectedGb;
  return {
    id: e.name,
    label: `${prettyModel(e.name)}${gb ? ` · ${gb.toFixed(1)} GB` : ""}`,
    ...(heavy
      ? { description: `larger than this card's ${Math.round(detectedGb)} GB — it will offload and run slowly` }
      : {}),
    ...(group ? { group } : {}),
  };
});
// 9.91: one H3 slot's picker options. "Automatic" leads and names what it
// currently resolves to - the row never hides the actual answer, because
// naming one build while loading another is the bug these rows exist to
// end. The installed candidates follow, a hybrid in both rows. A pick
// whose file left the catalog stays listed, marked as missing: the render
// lanes run Automatic over it, and the row says so rather than silently
// showing a name that does nothing.
const h3LaneOptions = (h3, lane) => {
  const side = (h3 && h3[lane]) || {};
  const stored = (h3 && h3[lane === "ref" ? "ref_model" : "fl_model"]) || "";
  const resolved = side.resolved;
  const options = [{
    id: "",
    label: resolved ? `Automatic — ${resolved.label}` : "Automatic",
  }];
  (side.options || []).forEach((o) => options.push({ id: o.rel, label: o.label }));
  if (side.stale && stored) {
    const stem = stored.split("\\").pop().replace(/\.safetensors$/i, "");
    options.push({ id: stored, label: `${stem} — missing, running Automatic` });
  }
  return options;
};
// 9.94: the H3 text encoder row's picker options, the 9.91 shape. Automatic
// leads and names the 32B it resolves to - with what it weighs, because the
// row is a VRAM control and the size is the point, not decoration. The
// offerable pairs follow (the payload only lists a pair when BOTH its files
// resolve), each naming its own cost. A pick whose files left stays listed,
// marked as missing: the render lanes run Automatic over it, and the row
// says so rather than silently showing a name that does nothing.
const h3EncoderOptions = (h3) => {
  const row = (h3 && h3.encoder) || {};
  const stored = (h3 && h3.text_encoder) || "";
  const gb = (size) => (size ? ` · ${(size / 1e9).toFixed(1)} GB` : "");
  const auto = row.automatic || {};
  const options = [{
    id: "",
    label: `Automatic — ${auto.label || "Qwen3-VL 32B"}${gb(auto.size)}`,
  }];
  (row.options || []).forEach((o) =>
    options.push({ id: o.id, label: `${o.label}${gb(o.size)}` }));
  if (row.stale && stored) {
    options.push({ id: stored, label: `${stored} — missing, running Automatic` });
  }
  return options;
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

// The little badge (the pickers' "4×" scale chip) lives in lib/Chip.jsx
// now — shared with SegmentedControl options and the Animate dialog, so a
// factor never renders as prose in one surface and a chip in another.

// ── the search (brief 10.0) ───────────────────────────────────────────────
// The header field filters THIS tab: a case-insensitive match on section
// titles and row labels; non-matching rows and empty sections hide while
// typing, an empty query restores everything. Client-side only - a query
// never touches config.json. The context carries the lowered needle so the
// components below filter themselves.
const SettingsQuery = createContext("");

// The visible TEXT of a label/title prop: strings pass through, fragments
// give up their children, and an InfoTip contributes nothing - its prose is
// help, not the row's name (the filter is titles + labels, not the manual).
const textOf = (node) => {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(" ");
  if (typeof node === "object" && node.props) {
    if (node.type === InfoTip) return "";
    return textOf(node.props.children);
  }
  return "";
};

// Every Field label under a node - a section hides only when neither its
// title nor one of its rows matches.
const collectLabels = (kids) => {
  const out = [];
  Children.forEach(kids, (c) => {
    if (!c || typeof c !== "object") return;
    if (c.type === Field) out.push(textOf(c.props.label));
    else if (c.props && c.props.children) out.push(...collectLabels(c.props.children));
  });
  return out;
};

// ── the 34px row (brief 10.0) ─────────────────────────────────────────────
// ONE line, 34px exactly: the label (TYPE.body at body weight) with its
// one-fact subline INLINE (TYPE.label 300, textTer, nowrap + ellipsis -
// never wraps, [[vertical-rhythm]]), the control on a right-hand rail.
// `hint` keeps its name from the stacked layout, but it is the subline now:
// same words, same copy-budget surface, new seat.
const Field = ({ label, hint, children, className }) => {
  const q = useContext(SettingsQuery);
  if (q && !textOf(label).toLowerCase().includes(q)) return null;
  return (
    <div className={className} style={{ display: "flex", alignItems: "center",
                  height: 34, gap: SPACE[10] }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: SPACE[8],
                    minWidth: 0, flex: "1 1 auto" }}>
        {label && (
          <span style={{ fontSize: TYPE.body, fontWeight: W.body, fontFamily: FONT,
                         color: "var(--text)", whiteSpace: "nowrap" }}>{label}</span>
        )}
        {hint && (
          <span style={{ fontSize: TYPE.label, fontWeight: W.label, fontFamily: FONT,
                         color: "var(--textTer)", whiteSpace: "nowrap", minWidth: 0,
                         overflow: "hidden", textOverflow: "ellipsis" }}>{hint}</span>
        )}
      </div>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center",
                    flex: "0 0 auto" }}>{children}</div>
    </div>
  );
};

// A run of consecutive rows: they touch (the 34px beat IS the spacing), so
// they travel as one child of the 32-gap container. `cont` marks a run that
// continues its cluster after a Section - 16 above it, not a full cluster
// gap, or it would read as a new group.
const Rows = ({ cont, children }) => (
  <div className={cont ? "px-set-rows px-set-rows--cont" : "px-set-rows"}
       style={{ display: "flex", flexDirection: "column" }}>{children}</div>
);

// THE one heading register (Jesse, 2026-09-01: "why would you make a one
// off style") - TYPE.micro, W.nav, uppercase, .09em tracking, textTer,
// the hairline running right. Section titles and cluster GroupLabels both
// render it; neither carries a private look.
const TITLE_STYLE = {
  fontSize: TYPE.micro, fontWeight: W.nav, fontFamily: FONT,
  color: "var(--textTer)", textTransform: "uppercase",
  letterSpacing: "0.09em", whiteSpace: "nowrap",
};
const Hairline = () => (
  <span aria-hidden="true" style={{ flex: 1, borderTop: "1px solid var(--border)" }} />
);

// Cluster heading inside a tab - the information architecture the flat wall
// of Sections was missing. Same register as the Section titles (TITLE_STYLE
// + the hairline); what separates a cluster heading is its 48px of air
// above (the rhythm CSS), not a different look. `badge` slots at the right
// edge (the Models tab's family state).
const GroupLabel = ({ children, badge }) => {
  const q = useContext(SettingsQuery);
  // Searching flattens the panel to matching rows; a heading whose group
  // hid would float, so headings sit the search out entirely.
  if (q) return null;
  return (
    <div className="px-set-group"
         style={{ display: "flex", alignItems: "center", gap: SPACE[10] }}>
      <span style={TITLE_STYLE}>{children}</span>
      <Hairline />
      {badge}
    </div>
  );
};

// One badge, two registers of the panel's one color story (brief 10.0):
// state-satisfied ("Installed") is the DIMMED chartreuse - accentDim on
// accentDimMut, never the success green; action ("Install") is the outlined-mid
// register. VISUAL STATE ONLY: no handler, not even a pointer - the install
// flow is an open product decision.
const Badge = ({ action, children }) => (
  <span style={{ flexShrink: 0, marginLeft: "auto", fontFamily: FONT,
                 fontSize: TYPE.micro, fontWeight: W.nav, letterSpacing: "0.04em",
                 padding: "2px 7px", borderRadius: RADIUS.pill,
                 ...(action
                   ? { color: "var(--accent)", background: "var(--accentMut)",
                       border: "1px solid var(--accentStr)" }
                   : { color: "var(--accentDim)", background: "var(--accentDimMut)" }),
                 }}>{children}</span>
);

// ── the library (9.30) ────────────────────────────────────────────────────
// The Models tab is the read-only inventory: choosing per lane is the Image
// and Video tabs' job, this one only ever REPORTS. One group per family, in
// the order a user actually renders with them; everything without a lane
// (Flux, audio, pipeline parts, unclassified) collapses into Other.
const LIBRARY_ORDER = ["krea2", "zimage", "klein", "qwen_edit", "qwen_image",
                       "anima", "minimax_h3", "video"];

// The server's reason codes, said in the user's language. Keyed by the exact
// reason model_profile writes; an unknown future reason passes through as-is.
const HUMAN_REASON = {
  "video model": "a video model — used by the Animate lanes",
  "Flux needs its own Pixal pipeline": "a Flux model — no lane here runs it yet",
  "audio model": "an audio model — no lane here runs it",
  "auxiliary model, not a standalone image generator":
    "a pipeline part — never renders on its own",
  "no compatible Pixal pipeline yet": "no lane here runs it yet",
};

// One library row: what it is, what it runs, what it weighs — one
// fixed-height line (nowrap + ellipsis, [[vertical-rhythm]]), the raw relpath
// and any advisory in the tooltip. A video model is not dead weight — the
// Animate lanes run it — so it keeps its ink and says where it runs; a model
// nothing here runs goes quiet and says why. Heavier-than-card follows 9.29:
// an honest tooltip line, never a badge, a colour, or a block.
const LibraryRow = ({ rel, name, meta, detectedGb }) => {
  const [hov, setHov] = useState(false);
  const family = meta.family || "unknown";
  const gb = meta.size ? meta.size / 1e9 : 0;
  const heavy = gb > 0 && detectedGb > 0 && gb > detectedGb;
  const lanes = (meta.compatible_recipes || []).map(prettyTemplate);
  const dead = !meta.supported && family !== "video";
  const state = family === "video"
    ? HUMAN_REASON["video model"]
    : (HUMAN_REASON[meta.reason] || meta.reason || "no lane here runs it yet");
  const shown = lanes.slice(0, 3);
  const overflow = lanes.length - shown.length;
  return (
    <div title={rel + (heavy
                 ? `\nlarger than this card's ${Math.round(detectedGb)} GB — it will offload and run slowly`
                 : "")}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ display: "flex", alignItems: "center", gap: SPACE[10], height: 34,
               padding: `0 ${SPACE[8]}px`, borderRadius: RADIUS.input,
               background: hov ? "var(--bg2)" : "transparent",
               transition: `background ${MOTION.hover}` }}>
      <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                     textOverflow: "ellipsis", whiteSpace: "nowrap",
                     fontFamily: FONT, fontSize: TYPE.body,
                     color: dead ? "var(--textTer)" : "var(--textSec)" }}>
        {meta.civitai_url ? (
          <a href={meta.civitai_url} target="_blank" rel="noreferrer"
             style={{ color: "inherit", textDecoration: "none",
                      borderBottom: `1px solid ${hov ? "var(--textTer)" : "transparent"}`,
                      transition: `border-color ${MOTION.hover}` }}>
            {name}
          </a>
        ) : name}
      </span>
      <span title={lanes.length ? lanes.join(" · ") : undefined}
        style={{ flexShrink: 0, maxWidth: "45%", display: "flex",
                 alignItems: "baseline", overflow: "hidden", whiteSpace: "nowrap",
                 fontFamily: FONT, fontSize: TYPE.label, color: "var(--textTer)" }}>
        {meta.supported && family !== "video" ? (<>
          {/* the +N never clips: it is the whole "there is more" signal */}
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
            {shown.join(" · ")}
          </span>
          {overflow > 0 && <span style={{ flexShrink: 0 }}>{` +${overflow}`}</span>}
        </>) : state}
      </span>
      <span style={{ flexShrink: 0, fontFamily: MONO, fontSize: TYPE.label,
                     color: "var(--textTer)", fontVariantNumeric: "tabular-nums" }}>
        {gb ? `${gb.toFixed(1)} GB` : ""}
      </span>
    </div>
  );
};

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
// Six rooms (2026-08-22 was three, 9.30 added the library back): the model
// decisions split by medium when one Models tab grew too crowded to scan.
// General is the machine (appearance, the ComfyUI box, VRAM, folders), Image
// and Video each hold their medium's model choices and finishers, Models is
// the read-only library — browsed, not tuned, so it sits after Video rather
// than pushing a most-touched tab down — Chat is the chat brain and the
// reviewer (10.0 renamed the LABEL, Jesse: "brain should be chat"; the id
// stays "brain" so a saved tab still restores), About the credits. A stale saved id fails the TABS check where
// `tab` is initialised and lands on "general".
const TABS = [
  { id: "general", label: "General" },
  { id: "image", label: "Image" },
  { id: "video", label: "Video" },
  { id: "models", label: "Models" },
  { id: "brain", label: "Chat" },
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
const TabStrip = ({ tabs, value, onChange, className, ariaLabel }) => (
  <div role="tablist" aria-label={ariaLabel} className={className} style={{ display: "flex", gap: SPACE[16],
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

// One section (brief 10.0): the title in the cluster register - TYPE.micro,
// W.nav, uppercase, .09em, textTer, the hairline running right - with any
// live-value gloss INLINE after it (the mockup's card-head title + sub
// pattern: a live value may not hide in a tip, so it rides the title line),
// then its rows and blocks 8 apart. The rows inside travel in a Rows run so
// they touch. Searching hides the section when neither its title nor one of
// its row labels matches.
const Section = ({ title, gloss, children }) => {
  const q = useContext(SettingsQuery);
  if (q) {
    const hay = [textOf(title), ...collectLabels(children)]
      .join("\n").toLowerCase();
    if (!hay.includes(q)) return null;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACE[8] }}>
      <div style={{ display: "flex", alignItems: "center", gap: SPACE[10] }}>
        <span style={TITLE_STYLE}>{title}</span>
        {gloss && (
          <span style={{ fontSize: TYPE.label, fontWeight: W.label, fontFamily: FONT,
                         color: "var(--textTer)", whiteSpace: "nowrap", minWidth: 0,
                         overflow: "hidden", textOverflow: "ellipsis" }}>{gloss}</span>
        )}
        <Hairline />
      </div>
      {children}
    </div>
  );
};

const inputStyle = {
  height: 38, background: "var(--bg3)", border: "1px solid var(--border)",
  borderRadius: RADIUS.pill, padding: `0 ${SPACE[16]}px`, fontSize: TYPE.ui,
  color: "var(--text)", fontFamily: FONT, outline: "none", width: "100%",
};

const Btn = ({ children, onClick, primary, disabled, title }) => (
  <button type="button" onClick={onClick} disabled={disabled} title={title}
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
  // 9.60: whose rulebook the writer runs - the families list is server data
  // (which prompts/official files exist), so the subline grows as data lands.
  const [officialPrompting, setOfficialPrompting] = useState(false);
  const [officialFamilies, setOfficialFamilies] = useState([]);
  // The subline is live data (the families carrying an official file), held
  // as a LineGhost until cfg lands. Computed here, next to vidLtx: a gloss
  // that IS a live value carries no prose, so it costs no visible words.
  const officialGloss = cfg ? (
    <span className="px-ghost-in">{officialFamilies.map(familyName).join(", ")}</span>
  ) : (
    <LineGhost w={64} />
  );
  const [criticModel, setCriticModel] = useState("");
  const [criticInstalled, setCriticInstalled] = useState([]);
  const [criticBrain, setCriticBrain] = useState(null);
  const [upscale, setUpscale] = useState(null);
  // The clip upscaler stores ONE string ("VSR High" / "LTX 2.5 2x"), but it
  // is really an engine plus, for RTX only, a quality. Splitting it in the UI
  // means bouncing to LTX and back would otherwise forget which tier you were
  // on, so remember it - seeded from whatever the config loads with.
  const lastVsr = useRef(VSR_DEFAULT_MODE);
  const vidLtx = String((upscale && upscale.video_mode) || "").startsWith("LTX");
  const [editCfg, setEditCfg] = useState(null);
  const [vae, setVae] = useState(null);
  const [pidCfg, setPidCfg] = useState(null);
  const [videoCfg, setVideoCfg] = useState(null);
  const [stillCfg, setStillCfg] = useState(null);
  const [h3Cfg, setH3Cfg] = useState(null);
  const [comfyEditor, setComfyEditor] = useState(false);
  const [comfyConsole, setComfyConsole] = useState("tui");
  const [explicit, setExplicit] = useState("auto");
  const [vramProfile, setVramProfile] = useState("auto");
  const [roots, setRoots] = useState([]);
  const [extraRoots, setExtraRoots] = useState([]);
  const [newRoot, setNewRoot] = useState("");
  const [note, setNote] = useState(null);
  const [upd, setUpd] = useState(null);
  const [busy, setBusy] = useState(false);
  // The DLSS runtime seat (Jesse, 2026-09-01): Pixal can neither ship nor
  // fetch the DLL (no legal source exists until NVIDIA releases DLSS 5),
  // so the row offers the next best thing - pick your own copy and the
  // server seats it in the node's runtime folder, sha-checked.
  const [dllBusy, setDllBusy] = useState(false);
  const dllInputRef = useRef(null);
  const seatDll = async (file) => {
    if (!file) return;
    setDllBusy(true); setNote(null);
    try {
      const form = new FormData();
      form.append("dll", file, file.name);
      const r = await fetch("/api/dlss5/dll", { method: "POST", body: form });
      const d = await r.json();
      if (d.ok) {
        setStillCfg((s) => ({ ...(s || {}), dlss5_available: true, dlss5_dll: true }));
        setNote(d.verified
          ? { ok: true, text: `DLSS 5 runtime verified — ${d.version}` }
          : { ok: true, text: "runtime seated — unrecognized build, may not run" });
      } else {
        setNote({ ok: false, text: d.error || "failed" });
      }
    } catch (e) { setNote({ ok: false, text: e.message }); }
    setDllBusy(false);
  };
  const [comfyBusy, setComfyBusy] = useState(false);
  // The brain's idle window (9.46): minutes before the local brain unloads
  // itself. 0 = Never, it stays resident.
  const [idleMin, setIdleMin] = useState(10);
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
  // The header search (brief 10.0): filters this tab's rows and sections,
  // client-side only - a keystroke never writes config. "/" focuses the
  // field from anywhere but another text field; Escape in the field clears.
  const [query, setQuery] = useState("");
  const searchRef = useRef(null);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" ||
                t.isContentEditable)) return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const q = query.trim().toLowerCase();

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
      setIdleMin(Number.isFinite(d.llm.local_idle_minutes) ? d.llm.local_idle_minutes : 10);
      setOfficialPrompting(!!d.llm.official_prompting);
      setOfficialFamilies(d.llm.official_families || []);
      setCriticModel(d.critic.model);
      setCriticInstalled(d.critic.installed || []);
      setCriticBrain(d.critic.brain || null);
      setUpscale(d.upscale || null);
      // Seed the remembered RTX tier, so opening Settings on a clip set to
      // LTX and switching to RTX lands on the tier you last chose rather
      // than a hardcoded one.
      const vm = d.upscale && d.upscale.video_mode;
      if (vm && !String(vm).startsWith("LTX")) lastVsr.current = vm;
      setEditCfg(d.edit || null);
      setVae(d.vae || null);
      setPidCfg(d.pid || null);
      setVideoCfg(d.video || null);
      setStillCfg(d.still || null);
      setH3Cfg(d.h3 || null);
      setRoots(d.model_roots);
      setExtraRoots(d.extra_model_roots);
      setComfyUrl(d.comfy_url || "");
      setComfyEditor(!!d.comfy_editor);
      setComfyConsole(d.comfy_console === "plain" ? "plain" : "tui");
      setExplicit(["on", "off"].includes(d.explicit) ? d.explicit : "auto");
      setMode(isLocal ? "local" : "api");
    }).catch(() => setNote({ ok: false, text: "settings endpoint unreachable" }));
  }, []);

  // 9.24a: the update check is advisory end to end. The server caches the
  // answer for hours and replies "unknown" when offline; a failed fetch here
  // surfaces nothing at all - never a note, never a red state. 9.17c: the
  // catch still resolves the slot - { ok: false } renders the same nothing,
  // and the ghost is not left shimmering over a check that is done.
  useEffect(() => {
    fetch("/api/update-check").then((r) => r.json()).then(setUpd)
      .catch(() => setUpd({ ok: false }));
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

  // 9.46: a clean-up action says what it actually freed - "done" teaches
  // nothing. freed_gb rides the response; when the machine cannot measure,
  // the toast says so in plain words rather than inventing a number. A
  // declined UAC is the user's own choice and says exactly that.
  const freeAction = async (url, pending, label) => {
    setComfyBusy(true); setNote({ ok: true, text: pending });
    try {
      const r = await fetch(url, { method: "POST",
        headers: { "Content-Type": "application/json" }, body: "{}" });
      const d = await r.json();
      if (d.ok) {
        const n = d.freed_gb;
        setNote(d.freed === false && d.note ? { ok: true, text: d.note }
          : Number.isFinite(n) ? { ok: true, text: `${label}: ${n} GB back` }
          : { ok: true, text: `${label}: freed - could not measure` });
      } else {
        setNote({ ok: false,
                  text: d.error === "cancelled" ? "Desktop reset cancelled"
                                                : d.error || "failed" });
      }
    } catch (e) { setNote({ ok: false, text: e.message }); }
    setComfyBusy(false);
  };

  // One click, the lot: the four frees in the buttons' order, one toast with
  // the measured total. A declined desktop prompt does not sink the rest.
  const freeAll = async () => {
    setComfyBusy(true); setNote({ ok: true, text: "freeing everything" });
    let total = 0, measured = false, failed = null;
    for (const url of ["/api/comfy/free", "/api/llm/free",
                       "/api/ram/free", "/api/desktop/reset"]) {
      try {
        const r = await fetch(url, { method: "POST",
          headers: { "Content-Type": "application/json" }, body: "{}" });
        const d = await r.json();
        if (d.ok && Number.isFinite(d.freed_gb)) {
          total += d.freed_gb; measured = true;
        } else if (!d.ok && d.error !== "cancelled") {
          failed = failed || d.error || "failed";
        }
      } catch (e) { failed = failed || e.message; }
    }
    setNote(failed && !measured ? { ok: false, text: failed }
      : { ok: true, text: `${Math.round(total * 10) / 10} GB back` });
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

  // The card's total once ComfyUI has answered - the edit lanes' only use is
  // the advisory tooltip on a build heavier than the card (9.29). Null = the
  // card was never read, and the option says nothing at all.
  const detectedGb = (cfg && cfg.vram && cfg.vram.detected_gb) || null;

  // 9.46: the clean-up buttons sleep while the card is working - a flush
  // mid-render would fight the job for the very memory it is using.
  const renderBusy = (store.liveJobs || []).length > 0;

  // 9.30 (Models tab): the whole library, read from the same /api/options
  // payload the composer already holds. Grouped by family in the order a
  // user renders with them, alphabetical by the SHOWN name inside; families
  // with no lane here collapse into "other". The unprofiled-LoRA count is
  // the one fact the app never told anyone: files no family claimed, which
  // render-time stacking skips rather than silently ignores.
  const lib = (store.options && store.options.models) || [];
  const libMeta = (store.options && store.options.model_meta) || {};
  const libLoras = (store.options && store.options.loras) || [];
  const unprofiled = libLoras.filter((l) => !l.supported).length;
  const libGroups = [];
  for (const rel of lib) {
    const fam = (libMeta[rel] || {}).family;
    const key = LIBRARY_ORDER.includes(fam) ? fam : "other";
    let g = libGroups.find((x) => x.key === key);
    if (!g) { g = { key, rows: [] }; libGroups.push(g); }
    g.rows.push(rel);
  }
  libGroups.sort((a, b) =>
    (LIBRARY_ORDER.includes(a.key) ? LIBRARY_ORDER.indexOf(a.key) : LIBRARY_ORDER.length) -
    (LIBRARY_ORDER.includes(b.key) ? LIBRARY_ORDER.indexOf(b.key) : LIBRARY_ORDER.length));
  // Name every row. Two human candidates exist for a build - the matched
  // title (Civitai / lora-manager / embedded) and prettyModel's product
  // name - and neither wins outright: the titles collapse the three Anima
  // builds to "Anima", prettyModel collapses five Krea 2 builds to "Krea
  // 2". So a row takes whichever candidate collides LESS inside its own
  // group, the title on a tie; the raw relpath stays the tooltip, never
  // the label.
  for (const g of libGroups) {
    const cands = g.rows.map((rel) => {
      const m = libMeta[rel] || {};
      const fam = m.family || "unknown";
      // model_profile files H3 under "video"; prettyModel only names its
      // lanes from the minimax_h3 family, so hand it the same hint the
      // classifier used (its own "minimax h3\" path prefix).
      const pmFam = fam === "video" &&
        rel.replace(/\//g, "\\").toLowerCase().startsWith("minimax h3\\")
        ? "minimax_h3" : fam;
      return { rel,
               title: String(m.title || "").trim(),
               pretty: String(prettyModel(rel, pmFam) || "") };
    });
    const tally = (pick) => cands.reduce((seen, c) => {
      const k = c[pick].toLowerCase();
      if (k) seen[k] = (seen[k] || 0) + 1;
      return seen;
    }, {});
    const tSeen = tally("title"), pSeen = tally("pretty");
    g.names = {};
    for (const c of cands) {
      const tLow = c.title.toLowerCase(), pLow = c.pretty.toLowerCase();
      // A candidate that strictly contains the other says strictly more
      // ("Minimax" < "MiniMax H3 I2V"; "Anima" < "Anima Turbo v1.0") and
      // always wins. Otherwise the less-colliding candidate, title on a
      // tie (the picker convention).
      const prettyMore = tLow && pLow && pLow.includes(tLow) && pLow !== tLow;
      const titleMore = tLow && pLow && tLow.includes(pLow) && pLow !== tLow;
      const tN = c.title ? (tSeen[tLow] || 0) : 99;
      const pN = c.pretty ? (pSeen[pLow] || 0) : 99;
      const useTitle = c.title && !prettyMore &&
        (titleMore || tN < pN || (tN === pN && c.title.length >= c.pretty.length));
      g.names[c.rel] = useTitle ? c.title : (c.pretty || c.title);
    }
    g.rows.sort((a, b) =>
      g.names[a].toLowerCase().localeCompare(g.names[b].toLowerCase()) ||
      a.toLowerCase().localeCompare(b.toLowerCase()));
  }
  // 10.0's family badges: the inventory knows which LIBRARY_ORDER families
  // have builds on disk (Installed) and which have none (Install - visual
  // state only; the install flow is an open product decision). It does NOT
  // know a size or a missing-file count, so the action badge carries no
  // "· N GB" the data cannot back. Absent families interleave in the same
  // LIBRARY_ORDER so the list reads as the full roster, not just the
  // present part of it.
  const familyGroups = [];
  for (const key of [...LIBRARY_ORDER, "other"]) {
    const g = libGroups.find((x) => x.key === key);
    if (g) familyGroups.push(g);
    else if (key !== "other") familyGroups.push({ key, rows: null, names: {} });
  }

  // `panel` is the whole content, shared by both presentations below.
  const panel = (
    <SettingsQuery.Provider value={q}>
      {/* Header + tabs stay put; only the tab's content scrolls. */}
      <div style={{ padding: `${SPACE[16]}px ${SPACE[20]}px 0`, display: "flex",
                    flexDirection: "column", gap: SPACE[10] }}>
        <div style={{ display: "flex", alignItems: "center", gap: SPACE[10] }}>
          <span style={{ fontSize: TYPE.h3, fontWeight: W.heading }}>Settings</span>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center",
                        gap: 6, height: 26, width: 180, padding: "0 10px",
                        background: "var(--bg2)", border: "1px solid var(--border)",
                        borderRadius: RADIUS.input }}>
            <input ref={searchRef} value={query} aria-label="Search settings"
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search settings" spellCheck={false}
              autoComplete="off" autoCorrect="off" autoCapitalize="off"
              onKeyDown={(e) => {
                if (e.key === "Escape") { setQuery(""); e.currentTarget.blur(); }
              }}
              style={{ flex: 1, minWidth: 0, padding: 0, background: "transparent",
                       border: "none", outline: "none", color: "var(--text)",
                       fontFamily: FONT, fontSize: TYPE.label }} />
            {!query && (
              <kbd aria-hidden="true" style={{ fontFamily: MONO, fontSize: 10,
                       fontWeight: W.label, color: "var(--textMut)",
                       border: "1px solid var(--border)", borderRadius: 4,
                       padding: "0 4px" }}>/</kbd>
            )}
          </div>
          <button type="button" onClick={onClose} title="close"
            style={{ display: "inline-flex", alignItems: "center", justifyContent: "center",
                     width: 30, height: 30, background: "var(--bg2)", border: "1px solid var(--border)",
                     borderRadius: RADIUS.pill, color: "var(--textTer)", cursor: "pointer" }}>
            <X size={14} weight="bold" />
          </button>
        </div>
        <TabStrip tabs={TABS} value={tab} onChange={pickTab} />
      </div>
      <div className="px-scroll px-set" style={{
        flex: 1, minHeight: 0, overflowY: "auto", padding: SPACE[20],
        display: "flex", flexDirection: "column", gap: SPACE[32],
      }}>
        {tab === "general" && (<>
        <GroupLabel>The app</GroupLabel>
        <Rows>
          <Field label="Appearance" hint="System follows Windows.">
            <SegmentedControl variant="pill" ariaLabel="Appearance" value={store.themePref}
              onChange={(v) => store.setTheme(v)}
              options={[
                { v: "light", label: "Light", Icon: Sun },
                { v: "dark", label: "Dark", Icon: Moon },
                { v: "system", label: "System", Icon: DesktopTower },
              ]} />
          </Field>
          <Field label={<>Explicit content <InfoTip text="Uncensored writing needs a local abliterated model — most APIs refuse NSFW." /></>}
                 hint="Auto reads your prompt · Never keeps everyone clothed.">
            {cfg ? (
              <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="Explicit content" value={explicit}
                onChange={(id) => {
                  setExplicit(id);
                  apply({ explicit: id },
                        id === "auto" ? "reading it from your words"
                          : id === "on" ? "explicit allowed" : "explicit off");
                }}
                options={[{ v: "auto", label: "Auto" },
                          { v: "on", label: "Allow" },
                          { v: "off", label: "Never" }]} />
            ) : (
              /* the stored value is still in flight - a ghost, never a guess
                 (this row lit on "auto" with "on" stored was the defect) */
              <SegGhost segments={3} />
            )}
          </Field>
        </Rows>

        <GroupLabel>This machine</GroupLabel>
        <Section title={<>Compute <InfoTip text="The ComfyUI box that renders. Another rig's address borrows its GPU. Restart is for the state no endpoint can fix." /></>}>
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
          {/* Restart is for the state no endpoint can fix. */}
          <div style={{ display: "flex", gap: SPACE[8], flexWrap: "wrap" }}>
            <Btn disabled={comfyBusy} onClick={() => comfyAction(
              "/api/comfy/restart", "restarting ComfyUI",
              "ComfyUI restarting - the boot meter takes it from here")}>
              Restart
            </Btn>
          </div>
          <Rows>
          <Field label={<>When ComfyUI boots <InfoTip text="ComfyUI likes to pop its node editor in a browser tab when it starts. quiet keeps that from interrupting; the editor is always at the compute address above." /></>}>
            {cfg ? (
              <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="When ComfyUI boots" value={comfyEditor}
                onChange={(on) => {
                  setComfyEditor(on);
                  apply({ comfy_editor: on },
                        on ? "editor tab will open on the next ComfyUI boot"
                           : "quiet boots applied");
                }}
                options={[{ v: false, label: "Quiet" },
                          { v: true, label: "Open the graph editor" }]} />
            ) : (
              <SegGhost segments={2} />
            )}
          </Field>
          <Field label={<>ComfyUI’s console window <InfoTip text="meters wrap the launcher in a boot dashboard and keep an errors-only log at logs\comfy-errors.log. plain console is the raw ComfyUI output. Either way, closing that window stops ComfyUI." /></>}>
            {cfg ? (
              <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="ComfyUI console window" value={comfyConsole}
                onChange={(id) => {
                  setComfyConsole(id);
                  apply({ comfy_console: id },
                        id === "tui" ? "meters on the next ComfyUI boot"
                                     : "plain console on the next ComfyUI boot");
                }}
                options={[{ v: "tui", label: "Meters" },
                          { v: "plain", label: "Plain console" }]} />
            ) : (
              <SegGhost segments={2} />
            )}
          </Field>
          </Rows>
        </Section>

        <Section title={<>Clean up <InfoTip text="Nothing hands memory back until asked. Each button says what it freed. A full card is a slow render." /></>}>
          {/* Freeing is deliberately manual: ComfyUI caches models on purpose,
              and the 21GB video stack staying resident is exactly why a second
              render is fast. These are for when the card needs the room back. */}
          <div style={{ display: "flex", gap: SPACE[8], flexWrap: "wrap", alignItems: "center" }}>
            <Btn disabled={comfyBusy || renderBusy}
                 title={renderBusy ? "wait for the render" : undefined}
                 onClick={() => freeAction("/api/comfy/free", "freeing VRAM", "VRAM")}>
              Free VRAM
            </Btn>
            {/* The one flush the VRAM button deliberately will not do. It is
                here because a chat model with a grown KV cache was measured at
                7.2GB, and MiniMax H3's DiT alone wants ~20GB of the card. */}
            <Btn disabled={comfyBusy || renderBusy}
                 title={renderBusy ? "wait for the render" : undefined}
                 onClick={() => freeAction("/api/llm/free", "freeing the brain", "Brain")}>
              Free brain
            </Btn>
            <Btn disabled={comfyBusy || renderBusy}
                 title={renderBusy ? "wait for the render" : undefined}
                 onClick={() => freeAction("/api/ram/free", "freeing RAM", "RAM")}>
              Free RAM
            </Btn>
            <span style={{ display: "inline-flex", alignItems: "center", gap: SPACE[6] }}>
              <Btn disabled={comfyBusy || renderBusy}
                   title={renderBusy ? "wait for the render" : undefined}
                   onClick={() => freeAction("/api/desktop/reset", "resetting the desktop", "Desktop")}>
                Reset desktop
              </Btn>
              <InfoTip text="Restarts Explorer and the Windows compositor, which hoard video memory. One screen flash, Explorer windows close, admin prompt; an idle ComfyUI may restart." />
            </span>
            <Btn primary disabled={comfyBusy || renderBusy}
                 title={renderBusy ? "wait for the render" : undefined}
                 onClick={freeAll}>
              Free all
            </Btn>
          </div>
          <Rows>
          <Field label={<>Brain idles after <InfoTip text="A warmed brain holds ~8 GB. Idle, it unloads; the next message wakes it in seconds." /></>}>
            {cfg ? (
              <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="Brain idles after" value={idleMin}
                onChange={(v) => {
                  setIdleMin(v);
                  apply({ llm: { local_idle_minutes: v } },
                        v > 0 ? `brain unloads after ${v} min`
                              : "brain stays resident");
                }}
                options={[{ v: 5, label: "5 min" },
                          { v: 10, label: "10 min" },
                          { v: 30, label: "30 min" },
                          { v: 0, label: "Never" }]} />
            ) : (
              <SegGhost segments={4} />
            )}
          </Field>
          </Rows>
        </Section>

        <Rows cont>
          <Field label={<>VRAM profile <InfoTip text="What this machine can hold resident. Advisory: pickers flag what a tier holds poorly — the VRAM butler still manages the card at render time." /></>}
                 hint={!cfg ? (
                   /* saying the card is unread before the fetch landed was
                      the second lie in the screenshot - the label stays,
                      the line ghosts */
                   <LineGhost w={180} />
                 ) : (
                   <span className="px-ghost-in">{cfg.vram && cfg.vram.detected_gb
                     ? `The card reads as ${Math.round(cfg.vram.detected_gb)} GB.`
                     : "Card not read yet — auto follows it."}</span>
                 )}>
            {cfg ? (
              <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="VRAM profile" value={vramProfile}
                onChange={(t) => {
                  setVramProfile(t);
                  apply({ vram_profile: t },
                        t === "auto" ? "following the card" : `pinned the ${t} GB profile`);
                }}
                options={[
                  { v: "auto", label: `Auto${cfg.vram && cfg.vram.detected
                      ? ` · ${cfg.vram.detected === "low" ? "under 16" : cfg.vram.detected} GB`
                      : ""}` },
                  ...["32", "24", "16"].map((t) => ({ v: t, label: `${t} GB` })),
                ]} />
            ) : (
              <SegGhost segments={4} />
            )}
          </Field>
        </Rows>

        <Section title="Model folders"
                 gloss={cfg ? (
                   <span className="px-ghost-in">{`Where checkpoints and LoRAs live. Found ${cfg.catalog_size} files.`}</span>
                 ) : (
                   <>Where checkpoints and LoRAs live. <ValueGhost w={92} /></>
                 )}>
          {cfg ? (<>
            {roots.map((r) => (
              <div key={r} className="px-ghost-in" style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                                    fontFamily: MONO, fontSize: 10, color: "var(--textSec)" }}>
                <FolderOpen size={12} weight="duotone" style={{ color: "var(--textTer)",
                                                               flexShrink: 0 }} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                               whiteSpace: "nowrap" }}>{r}</span>
              </div>
            ))}
            {extraRoots.map((r) => (
              <div key={r} className="px-ghost-in" style={{ display: "flex", alignItems: "center", gap: SPACE[8],
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
          </>) : (<>
            {/* two row ghosts stand in for the install root plus one added
                folder - the real count is the user's own data, and the rows
                are 12px mono lines either way */}
            <Bar h={12} w="72%" />
            <Bar h={12} w="55%" />
          </>)}
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
            }} disabled={busy}>Rescan folders</Btn>
          </div>
        </Section>
        </>)}

        {tab === "video" && (<>
        <GroupLabel>Defaults</GroupLabel>
                <Rows>
<Field label={<>Video engine <InfoTip text="The Animate popup still switches engines freely per clip — this only sets where it starts." /></>}
                 hint="Which engine the popup opens on.">
          {videoCfg ? (
            <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="Default video engine"
              value={videoCfg.default_engine || ""}
              onChange={(id) => {
                setVideoCfg((v) => ({ ...(v || {}), default_engine: id }));
                const label = id
                  ? ((videoCfg.engines || []).find((e) => e.id === id)?.label || id)
                  : "";
                apply({ video: { default_engine: id } },
                      id ? `${label} opens first` : "following the server's order");
              }}
              options={[
                { v: "", label: "Auto" },
                ...(videoCfg.engines || []).map((e) => ({
                  v: e.id, label: e.label,
                  disabled: e.available === false,
                  title: e.available === false ? `${e.label}: assets missing` : undefined,
                })),
              ]} />
          ) : (
            /* the defect that started the brief: one AUTO segment becoming
               LTX / Minimax and pulling the page down. The ghost is the
               40px capsule whatever the engine count turns out to be */
            <SegGhost segments={3} />
          )}
        </Field>
        <Field label={<>Video model <InfoTip text="The popup still switches models freely per clip — this only sets the default." /></>}
                 hint="Which model the popup opens on.">
          {videoCfg ? (
            <ScrollPicker className="px-ghost-in"
              value={videoCfg.default_model || ""}
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
          ) : (
            <PickerGhost />
          )}
        </Field>
        <Field label={<>Dialogue format <InfoTip text="How spoken lines are written in H3 briefs. quotes is the default — (S1) says “…”, the MiniMax-H3 #76 form; it won the same-seed A/B with no opening blip and no cue read aloud. tags is MiniMax's trained (S1) says: <d>[English] …</d>, which some seeds open with a half-second of gibberish." /></>}
                 hint="How H3 briefs write speech.">
          {videoCfg ? (
            <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="Dialogue format"
              value={videoCfg.h3_dialogue_tags || "quotes"}
              onChange={(id) => {
                setVideoCfg((v) => ({ ...(v || {}), h3_dialogue_tags: id }));
                apply({ video: { h3_dialogue_tags: id } },
                      id === "quotes" ? "plain quotes applied" : "trained tags applied");
              }}
              options={[
                { v: "tags", label: "Tags",
                  title: "MiniMax's trained <d>[Language] …</d> form." },
                { v: "quotes", label: "Quotes",
                  title: "Plain quotes — the MiniMax-H3 #76 form; won the same-seed A/B." },
              ]} />
          ) : (
            <SegGhost segments={2} />
          )}
        </Field>
        </Rows>
        <GroupLabel>Finishing</GroupLabel>
        <Section title={<>Upscaler <InfoTip text="The upscale button on finished clips." /></>}>
          {/* Two different things, not one five-step ladder. RTX Super
              Resolution is NVIDIA's image-space filter and its Low..Ultra are
              ITS quality tiers; LTX 2.5 re-renders the clip through the latent
              upsampler and has no quality setting at all. Flattened into one
              row they read as a single scale where "Ultra" and "LTX 2.5 2x"
              are neighbours - and five segments is over DESIGN.md's
              four-option cap either way. Engine first, then only what that
              engine actually has to set. */}
          {upscale ? (
            <Rows>
            <Field className="px-ghost-in" label="Video clips"
                   hint={vidLtx
                     ? "2× re-render: real new detail, heavier VRAM."
                     : upscale.video_available
                       ? undefined
                       : "Install the Deno RTX VFX node pack."}>
              <SegmentedControl variant="pill" ariaLabel="Video upscale engine"
                value={vidLtx ? "ltx" : "vsr"}
                onChange={(id) => {
                  const m = id === "ltx" ? LTX25_VIDEO_MODE : lastVsr.current;
                  setUpscale({ ...upscale, video_mode: m });
                  apply({ upscale: { video_mode: m } }, "clip upscaler applied");
                }}
                options={[
                  { v: "vsr", label: "RTX Super Resolution", Icon: NvidiaAccent,
                    disabled: !upscale.video_available,
                    title: upscale.video_available
                      ? "NVIDIA RTX Super Resolution"
                      : "RTX Super Resolution - install the Deno RTX VFX node pack" },
                  { v: "ltx", label: "LTX 2.5", chip: "2×", Icon: LightricksMark,
                    disabled: !upscale.ltx25_video_available,
                    title: upscale.ltx25_video_available
                      ? "Lightricks LTX 2.5, 2× re-render"
                      : "LTX 2.5 2× - the weights are not installed" },
                ]} />
            </Field>
            {!vidLtx && upscale.video_available && (
              <Field className="px-ghost-in" label="Quality"
                     hint={upscale.video_scale > 1
                       ? `Upscaled ${upscale.video_scale}× with audio kept.`
                       : "Same size, cleaned up. Audio kept."}>
                <SegmentedControl variant="pill" ariaLabel="RTX Super Resolution quality"
                  value={upscale.video_mode || lastVsr.current}
                  onChange={(m) => {
                    lastVsr.current = m;
                    setUpscale({ ...upscale, video_mode: m });
                    apply({ upscale: { video_mode: m } }, "clip quality applied");
                  }}
                  options={(upscale.video_modes || [])
                    .filter((m) => !m.startsWith("LTX"))
                    .map((m) => ({ v: m, label: m.replace("VSR ", "") }))} />
              </Field>
            )}
            {/* 9.53: RIFE interpolation in the same finisher pass as VSR, so
                fps + 2x land in one graph. The tip carries the whole story;
                the control itself states the rate (tip XOR hint). */}
            {!vidLtx && upscale.video_available && (
              <Field className="px-ghost-in" label={<>Frame rate <InfoTip size={12} text="RIFE interpolation, in the same pass as the upscale. Doubles or more the frames, audio kept. Lips can ghost above 2×. LTX 2.5 ignores it — that mode re-renders at the clip's own rate." /></>}>
                <SegmentedControl variant="pill" ariaLabel="Clip frame rate"
                  value={String(upscale.video_fps || 0)}
                  onChange={(id) => {
                    const f = Number(id);
                    setUpscale({ ...upscale, video_fps: f });
                    apply({ upscale: { video_fps: f } },
                          f ? `${f} fps applied` : "native rate applied");
                  }}
                  options={(upscale.video_fps_options || [0, 30, 48, 60])
                    .map((f) => ({ v: String(f),
                                   label: f ? String(f) : "Native" }))} />
              </Field>
            )}
          </Rows>
          ) : (
            <Rows>
            {/* the ghost is the default shape: engine row + quality row +
                frame rate row (a stored LTX clip drops the two sub rows -
                that one-time shrink is the stored setting correcting itself,
                not a load reflow) */}
            <Field label="Video clips">
              <SegGhost segments={2} />
            </Field>
            <Field label="Quality">
              <SegGhost segments={4} />
            </Field>
            <Field label="Frame rate">
              <SegGhost segments={4} />
            </Field>
            </Rows>
          )}
        </Section>
        <Rows cont>
          <Field label={<>H3 <Chip>2×</Chip> upscale <InfoTip text="It runs inside the render — it re-samples the render's own latent, so it can never be a button on a finished clip — and costs roughly 3× the render time." /></>}
                 hint={videoCfg && !videoCfg.upscale_2x_available
                   ? "Needs the MMH3 Ultimate Upscale pack and 659 MB weights."
                   : "The popup still decides per clip — this sets the default."}>
            {/* The MiniMax upscaler re-samples the render's own latent, so it
                can only live on the render itself (9.31) - the per-clip row in
                the Animate popup's fine-tune fold. This is the standing default
                that row opens on, the same contract as Video model above. 10.0:
                an on/off default is a pixal toggle, not a two-option pill. */}
            {videoCfg ? (
              <Switch className="px-ghost-in" label="H3 2× upscale"
                on={videoCfg.upscale_2x}
                disabled={!videoCfg.upscale_2x_available}
                title={videoCfg.upscale_2x_available
                  ? "Twice the size, inside the render — roughly 3× the render time."
                  : "Needs the MMH3 Ultimate Upscale pack and 659 MB weights."}
                onChange={(on) => {
                  setVideoCfg((v) => ({ ...(v || {}), upscale_2x: on }));
                  apply({ video: { upscale_2x: on } },
                        on ? "2× default applied" : "2× default off");
                }} />
            ) : (
              <SwitchGhost />
            )}
          </Field>
          <Field label={<>H3 resolution <InfoTip text="The canvas H3 renders at natively — detail comes from the model, not an upscaler. A bigger canvas re-frames the shot (composition can shift) and multiplies the render time: a 10 s Max clip is ~20 min on a 5090 and fills the card. The 2× row stays the budget option — render small, then upscale." /></>}
                 hint="The popup still decides per clip — this sets the default.">
            {/* 9.55: same contract as Video model above - the standing default
                the Animate popup's Resolution row opens on. The tier list rides
                the settings payload (h3_resolutions); the inline fallback only
                covers an out-of-date server. */}
            {videoCfg ? (
              <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="H3 resolution"
                value={videoCfg.h3_resolution || "standard"}
                onChange={(id) => {
                  setVideoCfg((v) => ({ ...(v || {}), h3_resolution: id }));
                  const label = ((videoCfg.h3_resolutions || [])
                    .find((r) => r.id === id) || {}).label || id;
                  apply({ video: { h3_resolution: id } },
                        `${label} default applied`);
                }}
                options={(videoCfg.h3_resolutions || [
                  { id: "standard", label: "Standard", mp: 1.0 },
                  { id: "high", label: "High", mp: 1.8 },
                  { id: "max", label: "Max", mp: 3.1 },
                ]).map((r) => ({
                  v: r.id, label: r.label,
                  title: r.id === "standard"
                    ? `${r.mp} MP — the fast default.`
                    : `${r.mp} MP — ~${Math.round(r.mp)}x the render time.`,
                }))} />
            ) : (
              <SegGhost segments={3} />
            )}
          </Field>
        </Rows>
        </>)}

        {tab === "image" && (<>
        <GroupLabel>Model choices</GroupLabel>
        <Rows>
          <Field label={<>Z-Image decoder <InfoTip text="Z-Image and Flux share a VAE, so sharper drop-in decoders exist. Applies to Z-Image renders only — the clear-anime profile keeps its own matched VAE either way." /></>}
                 hint="Sharper drop-in; can over-sharpen on one pass.">
          {vae ? (
            <ScrollPicker className="px-ghost-in"
              value={vae.zimage || ""}
              placeholder="stock Z-Image VAE (recommended)"
              emptyLabel="stock Z-Image VAE (recommended)"
              options={(vae.installed || []).map((name) => ({ name, label: name }))}
              onPick={(name) => {
                setVae({ ...vae, zimage: name });
                apply({ vae: { zimage: name } },
                      name ? "decoder applied" : "stock decoder restored");
              }} />
          ) : (
            <PickerGhost />
          )}
        </Field>
        </Rows>
        <GroupLabel>Special decoders</GroupLabel>
        {/* One gate for the group: both rows land together or not at all. */}
        {vae ? (
        <Rows>
          <Field className="px-ghost-in" label={<>Decoder <InfoTip maxWidth={320} text="Replaces the last step of a render, the VAE decode, with a drop-in decoder for the Wan 2.1 / Qwen-Image latent. The Wan 2.1 2× VAE (spacepxl) decodes twice the pixels straight from the sampler's latent — the decode is the upscale, one pass, nothing repainted. Needs the ComfyUI-VAE-Utils node pack. Off leaves every recipe on its own VAE." /></>}
                 hint="Krea 2 stills by default.">
            <Picker hug label="Special decoder"
              value={vae.special || ""}
              placeholder="Off"
              options={[
                { id: "", label: "Off" },
                ...(vae.special_decoders || []).map((d) => ({
                  id: d.id,
                  label: d.label + (!d.file_installed ? " — VAE file missing"
                                    : !d.available ? " — install ComfyUI-VAE-Utils" : ""),
                })),
              ]}
              onChange={(id) => {
                setVae({ ...vae, special: id });
                apply({ vae: { special: id } },
                      id ? "special decoder applied" : "stock decoders restored");
              }} />
          </Field>
          <Field className="px-ghost-in" label={<>Force compatible models <InfoTip text="Every lane whose VAE lives in the Wan 2.1 / Qwen-Image latent — Qwen Image, Anima, the edit and identity lanes — decodes through the special decoder too, not only the Krea 2 still recipes." /></>}
                 hint="All Wan/Qwen-latent lanes, not only Krea 2.">
            <Switch label="Force"
              on={!!vae.special_force}
              disabled={!vae.special}
              onChange={(on) => {
                setVae({ ...vae, special_force: on });
                apply({ vae: { special_force: on } },
                      on ? "forced on every compatible lane" : "Krea 2 stills only");
              }} />
          </Field>
        </Rows>
        ) : (
        <Rows>
          <Field label="Decoder"><PickerGhost /></Field>
          <Field label="Force compatible models"><SwitchGhost /></Field>
        </Rows>
        )}
        <Section title={<>Edit model <InfoTip text="A painted mask routes the edit to the masked lane; no mask runs the whole-frame lane. Whole-frame releases differ in encoder node, not just weights — the graph switches on the filename, so any compatible generation works. Klein keeps skin texture and runs 4 steps; Qwen/FireRed are the Lightning-distilled lanes." /></>}
                 gloss={editCfg ? (
                   <span className="px-ghost-in">{`Runs instruction edits. ${(editCfg.installed || []).length + (editCfg.inpaint_installed || []).length} whole-frame, ${(editCfg.inpaint_installed || []).length} masked compatible installed.`}</span>
                 ) : (
                   <>Runs instruction edits. <ValueGhost w={128} /></>
                 )}>
          {/* Two named lanes (9.29): whole frame runs when there is no mask,
              masked area when a mask is painted. Until tonight the second one
              was hard-pinned to KLEIN_MODEL and invisible here. The whole-frame
              row lists both families (9.44): a Klein pick routes mask-less
              edits to klein_edit, a Qwen pick to qwen_edit. */}
          {/* 9.73: both lane picks are the shared Picker (lib/Picker.jsx), as
              9.70 did for the chat brain - this panel's ScrollPicker predated
              it, and two controls for one job is the defect. "recipe default"
              was ScrollPicker's emptyLabel clear row; Picker has no such
              concept, so it is a real option with id "" - value "" matches it
              and the trigger reads "recipe default", the same meaning as
              before. onChange keeps onPick's body: same state write, same
              apply payload, same toast. */}
          {editCfg ? (
            <Rows>
            <Field className="px-ghost-in" label={<>Whole frame <InfoTip size={12} text="An undistilled build runs ~20 steps and takes about five times longer." /></>}>
              <Picker hug label="whole frame edit model"
                value={editCfg.model || ""}
                placeholder="recipe default"
                options={[
                  { id: "", label: "recipe default" },
                  ...editLaneOptions(editCfg.installed, detectedGb, familyName("qwen_edit")),
                  ...editLaneOptions(editCfg.inpaint_installed, detectedGb, familyName("klein")),
                ]}
                onChange={(name) => {
                  setEditCfg({ ...editCfg, model: name });
                  apply({ edit: { model: name } },
                        name ? "edit model applied" : "recipe default restored");
                }} />
            </Field>
            <Field className="px-ghost-in" label={<>Masked area <InfoTip size={12} text="An undistilled build runs ~20 steps and takes about five times longer." /></>}>
              <Picker hug label="masked area edit model"
                value={editCfg.inpaint_model || ""}
                placeholder="recipe default"
                options={[
                  { id: "", label: "recipe default" },
                  ...editLaneOptions(editCfg.inpaint_installed, detectedGb),
                ]}
                onChange={(name) => {
                  setEditCfg({ ...editCfg, inpaint_model: name });
                  apply({ edit: { inpaint_model: name } },
                        name ? "masked edit model applied" : "recipe default restored");
                }} />
            </Field>
          </Rows>
          ) : (
            <Rows>
            {/* the ghost IS the control's own box: the 24px value pill
                (PickerGhost), one per lane */}
            <Field label="Whole frame">
              <PickerGhost />
            </Field>
            <Field label="Masked area">
              <PickerGhost />
            </Field>
            </Rows>
          )}
        </Section>
        <Section title={<>MiniMax H3 <InfoTip text="H3 has two lanes and they take different builds. Reference renders carry a character's photo into the scene; first/last-frame renders start from a frame. Automatic is the lane's only build, or the preferred one when several are on disk. A hybrid build appears in both rows because it carries both — and a pick whose file leaves the catalog runs Automatic until the file returns. The Animate popup's own chip still wins per clip; these rows answer every render that names no build." /></>}>
          {/* 9.91: Settings owns which H3 build a lane renders with when
              the render names none - the options payload and the sampler
              read the one resolver, so they cannot name one build and load
              another (three instances in one afternoon). The Automatic
              option's label names what Automatic resolves to - the row
              never hides the actual answer, which is the bug this exists
              to end. No gloss and no hints on purpose: the panel's
              visible-word budget (tests/test_settings_copy.py) sat at
              149/150, so the lane facts live in the tip and the state
              lives in the control values - a stale pick shows itself as
              "missing, running Automatic" in its own row. */}
          {h3Cfg ? (
            <Rows>
            <Field className="px-ghost-in" label="Reference model">
              <Picker hug label="Reference model"
                value={h3Cfg.ref_model || ""}
                placeholder="Automatic"
                options={h3LaneOptions(h3Cfg, "ref")}
                onChange={(name) => {
                  setH3Cfg({ ...h3Cfg, ref_model: name });
                  apply({ h3: { ref_model: name } },
                        name ? "reference model applied" : "back to automatic");
                }} />
            </Field>
            <Field className="px-ghost-in" label="First/last-frame model">
              <Picker hug label="First/last-frame model"
                value={h3Cfg.fl_model || ""}
                placeholder="Automatic"
                options={h3LaneOptions(h3Cfg, "fl")}
                onChange={(name) => {
                  setH3Cfg({ ...h3Cfg, fl_model: name });
                  apply({ h3: { fl_model: name } },
                        name ? "first/last-frame model applied" : "back to automatic");
                }} />
            </Field>
            {/* 9.94, seated here rather than under VRAM optimizations
                (Jesse, 2026-08-31: "I want the option in settings under
                minimax"). The two rows above answer WHICH BUILD and this
                answers WHICH ENCODER, but all three answer the same
                question - what an H3 render loads - and nobody hunting for
                a MiniMax setting looks in a global VRAM list. Pickers, not
                segmented rows, so the two-row rule in
                tests/test_settings_tabs.py does not apply; the move is
                word-neutral against the panel's 150-word budget. */}
            <Field className="px-ghost-in" label={<>Text encoder <InfoTip size={12} text="The 32B encoder is the one MiniMax H3 was measured with. A 4B or 8B encoder with a ClipProj projection stands in for it: several GB freed and a faster render, and likeness is slightly less reliable with it. Automatic is the 32B. An option appears only when its encoder and its projection are both on disk; a pick whose files leave runs Automatic until they return." /></>}>
              <Picker hug label="Text encoder"
                value={h3Cfg.text_encoder || ""}
                placeholder="Automatic"
                options={h3EncoderOptions(h3Cfg)}
                onChange={(id) => {
                  setH3Cfg({ ...h3Cfg, text_encoder: id });
                  apply({ h3: { text_encoder: id } },
                        id ? "text encoder applied" : "back to automatic");
                }} />
            </Field>
          </Rows>
          ) : (
            <Rows>
            {/* the edit pickers' ghost shape: the 24px value pill
                (PickerGhost), one per lane, so nothing below moves on land */}
            <Field label="Reference model">
              <PickerGhost />
            </Field>
            <Field label="First/last-frame model">
              <PickerGhost />
            </Field>
            <Field label="Text encoder">
              <PickerGhost />
            </Field>
            </Rows>
          )}
        </Section>
        <GroupLabel>Post processing</GroupLabel>
        {/* One group for the whole delivered-frame chain (Jesse,
            2026-09-01: DLSS 5, film grain and shine removal all belong
            under post processing - the dlss 5 and finishing labels merged
            here). Every row keeps the grain row's exact 34px beat: inline
            value controls appear only while their toggle is on. DLSS 5
            unavailable (node or runtime DLL missing) follows the H3 2x
            idiom - the switch disables with a truthful one-fact subline,
            not a perpetual loading ghost. */}
        <Rows>
          {stillCfg ? (
            <>
            <Field className="px-ghost-in" label={<span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><NvidiaAccent size={13} /> DLSS 5 <InfoTip text="Runs the finished still through NVIDIA's DLSS 5 neural re-render — relights materials and tames glare at the same resolution. Applied first, before shine removal and grain. Needs the ComfyUI-DLSS5-NR node pack plus a DLSS DLL you supply yourself — NVIDIA has not released it publicly, so Pixal can neither ship nor download it. Add DLL copies your own nvngx_dlssnr.dll (about 158 MB) into the node's runtime folder and verifies it by SHA-256 against the known 310.8.0.0 build; an unrecognized build is seated anyway and may not run." /></span>}
                   hint={stillCfg.dlss5_available ? undefined
                     : stillCfg.dlss5_node ? "Bring your own nvngx_dlssnr.dll · 158 MB"
                     : "Install the ComfyUI-DLSS5-NR node pack"}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                {!stillCfg.dlss5_available && stillCfg.dlss5_node ? (
                  <>
                    <input ref={dllInputRef} type="file" accept=".dll" hidden
                      onChange={(e) => {
                        seatDll(e.target.files && e.target.files[0]);
                        e.target.value = "";
                      }} />
                    <button type="button" disabled={dllBusy}
                      title="Copies your own nvngx_dlssnr.dll into the node's runtime folder, SHA-256 checked against the known 310.8.0.0 build."
                      onClick={() => dllInputRef.current && dllInputRef.current.click()}
                      style={{ height: 24, padding: "0 10px",
                               background: "var(--bg3)",
                               border: "1px solid var(--border)",
                               borderRadius: RADIUS.pill, color: "var(--textSec)",
                               fontFamily: FONT, fontSize: TYPE.label,
                               fontWeight: W.nav,
                               cursor: dllBusy ? "default" : "pointer" }}>
                      {dllBusy ? "checking…" : "Add DLL"}
                    </button>
                  </>
                ) : null}
                {stillCfg.dlss5 && stillCfg.dlss5_available ? (
                  <>
                    <select value={stillCfg.dlss5_style ?? "default"}
                      aria-label="DLSS 5 style"
                      title="The re-render's grade."
                      style={{ height: 24, padding: "0 8px",
                               background: "var(--bg3)",
                               border: "1px solid var(--border)",
                               borderRadius: RADIUS.pill, color: "var(--text)",
                               fontFamily: FONT, fontSize: TYPE.label,
                               fontWeight: W.nav }}
                      onChange={(e) => {
                        const v = e.target.value;
                        setStillCfg((s) => ({ ...(s || {}), dlss5_style: v }));
                        apply({ still: { dlss5_style: v } }, "DLSS 5 style");
                      }}>
                      <option value="default">default</option>
                      <option value="natural">natural</option>
                      <option value="cinematic">cinematic</option>
                    </select>
                    <input type="number" step="0.05" min="0" max="2"
                      value={stillCfg.dlss5_intensity ?? 1.0}
                      aria-label="DLSS 5 intensity"
                      title="Re-render strength. 1.0 is the shipped default."
                      style={{ width: 52, height: 24, padding: "0 8px",
                               background: "var(--bg3)",
                               border: "1px solid var(--border)",
                               borderRadius: RADIUS.pill, color: "var(--text)",
                               fontFamily: FONT, fontSize: TYPE.label,
                               fontWeight: W.nav, textAlign: "center" }}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value);
                        if (!Number.isFinite(v)) return;
                        setStillCfg((s) => ({ ...(s || {}), dlss5_intensity: v }));
                        apply({ still: { dlss5_intensity: v } }, "DLSS 5 intensity");
                      }} />
                  </>
                ) : null}
                <Switch label="Nvidia DLSS 5"
                  on={stillCfg.dlss5}
                  disabled={!stillCfg.dlss5_available}
                  title={stillCfg.dlss5_available
                    ? "Neural re-render on the finished still, before shine removal and grain."
                    : "Needs the node pack + your own DLL"}
                  onChange={(on) => {
                    setStillCfg((s) => ({ ...(s || {}), dlss5: on }));
                    apply({ still: { dlss5: on } },
                          on ? "DLSS 5 on" : "DLSS 5 off");
                  }} />
              </span>
            </Field>
            {/* 10.1: film grain holds the seat skin1x had (retired by
                Jesse's eye - it read as skin only on close portraits). The
                judged dewax recipe, applied to the delivered frame after
                shine removal: seeded from the render, so a re-render lands
                identically. */}
            <Field className="px-ghost-in" label={<>Film grain <InfoTip text="A fine monochrome grain over finished stills — the judged recipe from the de-wax session, strongest in the midtones the way negative film behaves. Seeded from the render, so re-renders match. It is the last thing applied, after shine removal and any upscale." /></>}>
              {/* No hint: the tip carries the rule; the amount input only
                  appears once the toggle is on - one row, the 34px beat. */}
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                {stillCfg.film_grain ? (
                  <input type="number" step="0.1" min="0.1" max="8"
                    value={stillCfg.film_grain_amount ?? 1.6}
                    aria-label="Film grain amount"
                    title="Grain strength. 1.6 is the judged default."
                    style={{ width: 52, height: 24, padding: "0 8px",
                             background: "var(--bg3)",
                             border: "1px solid var(--border)",
                             borderRadius: RADIUS.pill, color: "var(--text)",
                             fontFamily: FONT, fontSize: TYPE.label,
                             fontWeight: W.nav, textAlign: "center" }}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      if (!Number.isFinite(v)) return;
                      setStillCfg((s) => ({ ...(s || {}), film_grain_amount: v }));
                      apply({ still: { film_grain_amount: v } }, "film grain amount");
                    }} />
                ) : null}
                <Switch label="Film grain"
                  on={stillCfg.film_grain}
                  title="Seeded monochrome grain on the finished still."
                  onChange={(on) => {
                    setStillCfg((s) => ({ ...(s || {}), film_grain: on }));
                    apply({ still: { film_grain: on } },
                          on ? "film grain on" : "film grain off");
                  }} />
              </span>
            </Field>
            {/* 9.93: "AI Skin Shine Removal". The brief asked for beside
                the upscale-model selection; DESIGN.md's two-segmented-rows
                rule already seats mode + VSR quality in the Upscaler
                section, so the row lives here - the same finishing group,
                the only section with headroom. No availability gate: numpy
                on the delivered frame, nothing to install. Label + tip,
                no gloss and no hint - the budget sat at 149/150
                (tests/test_settings_copy.py). */}
            <Field className="px-ghost-in" label={<>Shine removal <InfoTip size={12} text="Lowers specular highlights on the face toward the tone around them — the shiny hotspots on foreheads, cheeks and noses. A face detector from ComfyUI's ultralytics folder keeps the pass inside the face, so arms, hands and chests keep their light; a frame with no face is left alone. It only darkens, eyes and teeth fall outside the skin range, and it runs on the finished frame, before any upscale." /></>}>
              {/* 10.9: the strength dial rides inline like grain's amount -
                  only while the toggle is on, the same 34px beat. */}
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                {stillCfg.de_shine ? (
                  <input type="number" step="0.05" min="0.1" max="1"
                    value={stillCfg.de_shine_strength ?? 0.85}
                    aria-label="Shine removal strength"
                    title="How far highlights are pulled toward the skin around them. 0.85 is the judged default; 1 is all the way."
                    style={{ width: 52, height: 24, padding: "0 8px",
                             background: "var(--bg3)",
                             border: "1px solid var(--border)",
                             borderRadius: RADIUS.pill, color: "var(--text)",
                             fontFamily: FONT, fontSize: TYPE.label,
                             fontWeight: W.nav, textAlign: "center" }}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      if (!Number.isFinite(v)) return;
                      setStillCfg((s) => ({ ...(s || {}), de_shine_strength: v }));
                      apply({ still: { de_shine_strength: v } }, "shine removal strength");
                    }} />
                ) : null}
                <Switch label="Shine removal"
                  on={stillCfg.de_shine}
                  title="Specular highlights pulled toward local skin tone."
                  onChange={(on) => {
                    setStillCfg((s) => ({ ...(s || {}), de_shine: on }));
                    apply({ still: { de_shine: on } },
                          on ? "shine removal on" : "shine removal off");
                  }} />
              </span>
            </Field>
            </>
          ) : (
            <>
              <Field label={<span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><NvidiaAccent size={13} /> DLSS 5</span>}>
                <SwitchGhost />
              </Field>
              <Field label="Film grain">
                <SwitchGhost />
              </Field>
              <Field label="Shine removal">
                <SwitchGhost />
              </Field>
            </>
          )}
        </Rows>
        <Section title={<>Upscaler <InfoTip text="Used by the upscale button on a finished render. Model is faithful and invents nothing. PiD repaints tile by tile and invents texture. VSR reconstructs detail in about five seconds. The model's own factor decides the size — a 4× model on a 1024-wide frame gives 4096." /></>}
                 gloss={upscale ? (
                   <span className="px-ghost-in">{`Model upscales; PiD repaints. ${(upscale.installed || []).length} installed.`}</span>
                 ) : (
                   <>Model upscales; PiD repaints. <ValueGhost w={56} /></>
                 )}>
          {upscale ? (
            <Rows>
              <Field className="px-ghost-in" label="Still frames"
                     hint={(upscale.image_mode || "model") === "pid"
                       ? "Invents texture; first use downloads it. " +
                         "Non-commercial license."
                       : (upscale.image_mode || "model") === "vsr"
                         ? "Reconstructs detail; about five seconds."
                         : upscale.pid_available === false
                           ? "Install the ComfyUI-PiD node pack for PiD."
                           : upscale.vsr_available === false
                             ? "Install the Deno RTX VFX node pack."
                             : undefined}>
                <SegmentedControl variant="pill" ariaLabel="Image upscale mode"
                  value={upscale.image_mode || "model"}
                  onChange={(m) => {
                    setUpscale({ ...upscale, image_mode: m });
                    apply({ upscale: { image_mode: m } },
                          m === "pid" ? "PiD upscaler applied"
                            : m === "vsr" ? "VSR upscaler applied"
                            : "model upscaler applied");
                  }}
                  options={[
                    { v: "model", label: "Model" },
                    { v: "pid", label: "PiD", chip: "4×", Icon: NvidiaAccent,
                      disabled: upscale.pid_available === false,
                      title: upscale.pid_available === false
                        ? "install the ComfyUI-PiD node pack" : undefined },
                    { v: "vsr", label: "VSR", Icon: NvidiaAccent,
                      disabled: upscale.vsr_available === false,
                      title: upscale.vsr_available === false
                        ? "install the Deno RTX VFX node pack" : undefined },
                  ]} />
              </Field>
              {/* PiD and VSR never read image_model - build_upscale_image
                  returns before it does - so offering an ESRGAN pick in
                  those modes is a control that does nothing. */}
              {(upscale.image_mode || "model") === "model" && (
              <Field className="px-ghost-in" label="Upscale model">
              <ScrollPicker
                value={upscale.image_model || ""}
                placeholder="choose local upscale model…"
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
              </Field>
              )}
              {/* VSR's own tier (9.79) - the same four the clip lane offers,
                  stored under its own key so a still preference never drags
                  the clip setting around. */}
              {(upscale.image_mode || "model") === "vsr" && (
              <Field className="px-ghost-in" label="Quality">
                <SegmentedControl variant="pill" ariaLabel="VSR quality"
                  value={upscale.image_vsr_mode || "VSR Ultra"}
                  onChange={(m) => {
                    setUpscale({ ...upscale, image_vsr_mode: m });
                    apply({ upscale: { image_vsr_mode: m } },
                          "still quality applied");
                  }}
                  options={(upscale.vsr_tiers || []).map((m) => ({ v: m, label: m.replace("VSR ", "") }))} />
              </Field>
              )}
            </Rows>
          ) : (
            <Rows>
              {/* the ghost is the default shape: mode row + the model list
                  under it (a stored PiD mode drops the picker - that
                  one-time shrink is the stored setting correcting itself,
                  not a load reflow) */}
              <Field label="Still frames">
                <SegGhost segments={3} />
              </Field>
              <Field label="Upscale model">
                <PickerGhost />
              </Field>
            </Rows>
          )}
        </Section>

        {/* Titled for the CHOICE, and in the term the thing actually has.
            "PiD finish" over a control reading "Wan VAE" said the section was
            PiD while the setting said it was off, and "finish" was a word
            invented for a step the pipeline calls a VAE decode (Jesse,
            2026-08-24: "Vae decode instead of finish - cmon use proper
            terms"). The hint had the mirror fault: it described the 4x snap
            whichever way the control was set, so the state that needed
            explaining and the state that did not got the same sentence. */}
        <Rows cont>
          <Field label={<>VAE decode <InfoTip maxWidth={300} text="Identity Edit only — no other recipe reads this. Every render ends by decoding the sampler's latent into pixels; normally that is the Wan VAE, at the canvas you picked. PiD hands that last step to NVIDIA's pixel-diffusion decoder instead, which repaints the latent at 4× in a 4-step pass — so the canvas first snaps to a preset it accepts, and a 2:3 comes back 2688×4032. The identity photo still encodes through the real VAE either way; only the decode changes." /></>}
                 hint={pidCfg?.identity_finish
                   ? "Experimental: canvas snaps to 1024-class presets, returns 4×."
                   : "Wan VAE decode at your canvas."}>
            {pidCfg ? (
              <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="VAE decode"
                value={!!pidCfg.identity_finish}
                onChange={(on) => {
                  setPidCfg({ ...pidCfg, identity_finish: on });
                  apply({ pid: { identity_finish: on } },
                        on ? "PiD decode applied" : "Wan VAE decode restored");
                }}
                options={[
                  { v: false, label: "Wan VAE" },
                  { v: true, label: "PiD", chip: "4×", Icon: NvidiaAccent,
                    disabled: pidCfg.decode_available === false,
                    title: pidCfg.decode_available === false
                      ? "install the ComfyUI-PiD node pack" : undefined },
                ]} />
            ) : (
              <SegGhost segments={2} />
            )}
          </Field>
        </Rows>
        </>)}

        {tab === "models" && (<>
        {/* 9.30 — the library. Read-only on purpose: it is the surface that
            finally shows the user what they own and what each thing can and
            cannot do here; the choosing stays on the medium tabs. */}
        <GroupLabel>What you own</GroupLabel>
        <Section title={<>The library <InfoTip text="A profile is what Pixal knows about a file — its family, its variant, and the lanes it can run — and a LoRA without one is skipped at render time rather than stacked blindly." /></>}
                 gloss={store.options ? (
                   <span className="px-ghost-in">{`${lib.length} models · ${libLoras.length} LoRAs · ${unprofiled} have no profile`}</span>
                 ) : (
                   /* the whole line is late, not just the numbers - a
                      half-loaded count would read as a real total */
                   <LineGhost w="70%" />
                 )}>
          {store.options && (
            <span className="px-ghost-in" style={{ fontSize: TYPE.label,
                         fontWeight: W.label, color: "var(--textTer)",
                         lineHeight: 1.5 }}>
              {detectedGb > 0
                ? `The card reads as ${Math.round(detectedGb)} GB. `
                : "Card not read yet — weights are disk size. "}
              <InfoTip text="A build heavier than the card still runs — it offloads to system memory and crawls — so a row's weight is advisory, never a block." />
            </span>
          )}
        </Section>
        <Section title={<>By family <InfoTip text="A family is an architecture, not a brand — every build in one shares a text encoder and a VAE, so a LoRA trained for one fits them all." /></>}>
          {store.options ? (
            /* Nested px-set: the GroupLabel rhythm (48 above a heading, 12
               below it) is a .px-set direct-child rule, and the fragments
               keep the headings as direct children. */
            <div className="px-set px-ghost-in" style={{ display: "flex",
                          flexDirection: "column", gap: SPACE[32] }}>
              {familyGroups.map((g) => (
                <Fragment key={g.key}>
                  <GroupLabel badge={g.rows
                    ? <Badge>Installed</Badge>
                    : <Badge action>Install</Badge>}>
                    {g.key === "other" ? "Other" : familyName(g.key)}
                  </GroupLabel>
                  {g.rows && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      {g.rows.map((rel) => (
                        <LibraryRow key={rel} rel={rel} name={g.names[rel]}
                          meta={libMeta[rel] || {}} detectedGb={detectedGb} />
                      ))}
                    </div>
                  )}
                </Fragment>
              ))}
              {libGroups.length === 0 && (
                <div style={{ fontSize: TYPE.label, color: "var(--textTer)" }}>
                  no models found in your model folders
                </div>
              )}
            </div>
          ) : (
            /* one row ghost - the list's height is the user's own data, so
               no ghost can match it; one 30px row is the smallest honest
               hold (same call as the brain tab's model list) */
            <Bar h={30} />
          )}
        </Section>
        </>)}

        {tab === "brain" && (<>
        <GroupLabel>Chat</GroupLabel>
        <Section title={<>Chat brain <InfoTip text="The AI you talk to — it writes the prompts and drives ComfyUI. Local runs entirely on this PC; Pixal starts and stops it for you." /></>}>
          {/* API | Local swaps the whole panel below it — a control that
              changes what else is on the screen is navigation, so it wears
              the same tab strip as the top-level settings nav, not a pill
              row (Jesse, 2026-08-22). The value controls stay segmented controls. */}
          {cfg ? (
            <TabStrip className="px-ghost-in" ariaLabel="Chat brain source"
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
          ) : (
            /* the strip's ghost: same text-tab line, same hairline under
               it - which tab is lit is the stored brain's call, so no tab
               may be lit before it lands */
            <div aria-hidden="true" style={{ display: "flex", gap: SPACE[16],
              padding: `${SPACE[6]}px 0 ${SPACE[8]}px`,
              borderBottom: "1px solid var(--border)" }}>
              <Bar w={30} h={15} />
              <Bar w={40} h={15} />
            </div>
          )}
          {mode === "local" ? (<>
            {/* 9.70: the chat-brain pick is the shared Picker (lib/Picker.jsx,
                the composer sampler card's dropdown) - this panel's bespoke
                row list predated it, and two controls for one job is the
                defect. id = the gguf path the row posted; the VISION / NSFW
                chips ride the description so the filter still finds them. */}
            {!cfg ? (
              /* the ghost IS the control's own box: the 24px value
                 pill (PickerGhost), labelled so the search still finds it */
              <Rows>
                <Field label="Model">
                  <PickerGhost />
                </Field>
              </Rows>
            ) : (localList.length ? (
              <Rows>
                <Field className="px-ghost-in" label="Model">
                  <Picker hug label="Local brain model" value={localModel}
                  placeholder="pick a model…"
                  options={localList.map((m) => ({
                    id: m.path,
                    label: m.title || m.name,
                    description: [m.vision && "VISION", m.nsfw && "NSFW",
                                  m.quant, m.size_gb].filter(Boolean).join(" · "),
                  }))}
                  onChange={(id) => {
                    setLocalModel(id);
                    apply({ llm: { base_url: LOCAL_URL, model: "local",
                                   local_model: id } },
                          "model applied - loads on your next message");
                  }} />
              </Field>
              </Rows>
            ) : (
              <div className="px-ghost-in" style={{ fontSize: TYPE.label, color: "var(--textTer)" }}>
                no .gguf chat models found in your model folders
              </div>
            ))}
            {/* A stored value, not navigation — stays a segmented control. With
                "brain runs on" below that is two segment rows in this panel,
                the cap; a third would mean the grouping is wrong. */}
                          <Rows>
            <Field label={<>Between replies <InfoTip text="Keeping the model loaded means instant replies, but it holds a few GB of VRAM next to your renders. It steps aside when a render needs the room. Unloading frees the card; the next reply waits for a reload." /></>}>
              {cfg ? (
                <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="memory policy" value={localKeep}
                  onChange={(keep) => {
                    setLocalKeep(keep);
                    apply({ llm: { local_keep: keep } },
                          keep ? "model stays loaded - fast replies"
                               : "will unload after each reply - frees VRAM for renders");
                  }}
                  options={[{ v: true, label: "Keep in memory" },
                            { v: false, label: "Unload after reply" }]} />
              ) : (
                <SegGhost segments={2} />
              )}
            </Field>
            <Field label={<>Brain runs on <InfoTip text="GPU replies fast but holds VRAM next to the render; CPU chat is slow but frees the card for rendering." /></>}>
              {cfg ? (
                <SegmentedControl variant="pill" className="px-ghost-in" ariaLabel="brain runs on" value={localGpu}
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
              ) : (
                <SegGhost segments={2} />
              )}
            </Field>
            </Rows>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 5,
                          fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
              <LockKey size={11} weight="duotone" style={{ flexShrink: 0, marginTop: 4 }} />
              Runs entirely on this PC — nothing leaves the machine.
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
            <div style={{ display: "flex", alignItems: "flex-start", gap: 5,
                          fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
              <LockKey size={11} weight="duotone" style={{ flexShrink: 0, marginTop: 4 }} />
              Only your provider sees the key — never the PNG metadata.
            </div>
          </>)}
          <div style={{ display: "flex" }}>
            <Btn onClick={test} disabled={busy}>Test connection</Btn>
          </div>
        </Section>

        {/* 9.60: whose rulebook the writer runs. Its own row, not one inside
            Chat brain - the families subline is live data (the families
            carrying an official file), so it rides the row's hint slot,
            ghosted until cfg lands. 10.0: an on/off default is a pixal
            toggle, not a two-option pill. */}
        <Rows cont>
          <Field label={<>Official prompting <InfoTip text="Writes scenes the way the model's makers recommend — Krea 2's own expansion prompt on Krea 2 recipes. A family with no official file is unchanged either way. Off uses Pixal's photo-craft rules." /></>}
                 hint={officialGloss}>
            {cfg ? (
              <Switch className="px-ghost-in" label="Official prompting"
                on={officialPrompting}
                onChange={(on) => {
                  setOfficialPrompting(on);
                  apply({ llm: { official_prompting: on } },
                        on ? "writes with the model makers' own prompt"
                           : "writes with Pixal's photo-craft rules");
                }} />
            ) : (
              <SwitchGhost />
            )}
          </Field>
        </Rows>

        <GroupLabel>Vision</GroupLabel>
        {/* This section used to read "Image reviewer" over the ComfyUI picker
            with no mention of the brain, so it looked like the picked model
            was doing the reviewing. It is not: brain_vl_read gets first
            refusal on BOTH the review button and the motion director's look,
            and this picker is only reached when the brain cannot see (Jesse,
            2026-08-24: "how come it doesn't actually have the heretic listed
            for vision"). The heretic can never appear IN this list - the list
            is ComfyUI VLM checkpoints, the brain is a llama.cpp gguf - so the
            title and gloss have to carry the fact instead. They read from
            critic.brain, which is the projector-on-disk-and-not-demoted
            truth, NOT the filename-regex VISION chip in the brain picker. */}
        <Rows>
          <Field label={<>{criticBrain?.sighted ? "Fallback reviewer" : "Image reviewer"} <InfoTip text="The chat brain reviews directly whenever it has working eyes; this ComfyUI model only runs when it does not. Bigger models read hands and text better; first use takes ~30s to warm up." /></>}
                 hint={!criticBrain?.local
                   ? "Suggests fixes for what you made."
                   : criticBrain.sighted
                     ? "Only when the chat brain can’t see."
                     : `The chat brain can’t see — ${criticBrain.why}.`}>
          {cfg ? (
            <ScrollPicker className="px-ghost-in" required
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
          ) : (
            <PickerGhost />
          )}
        </Field>
        </Rows>
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

          {/* 9.24a — the update slot. A 32px floor so the async answer (which
              may be "unknown" = genuinely nothing) never reshapes the card,
              and so 9.24b swaps the CTA for a progress meter in place.
              9.17c — while the check is in flight the floor holds a shimmer
              bar; the answer cross-fades in like every other late slot. */}
          <div style={{ minHeight: 32, display: "flex", flexDirection: "column",
                        alignItems: "center", justifyContent: "center",
                        gap: SPACE[6] }}>
            {upd ? (
              <div className="px-ghost-in" style={{ display: "flex",
                flexDirection: "column", alignItems: "center", gap: SPACE[6] }}>
                {upd?.ok && !upd.update && (
                  <span style={{ fontSize: TYPE.label, color: "var(--textMut)" }}>
                    Up to date{upd.latest ? ` — ${upd.latest} is the latest release` : ""}
                  </span>
                )}
                {upd?.ok && upd.update && (
                  <>
                    <span style={{ fontSize: TYPE.label, color: "var(--textSec)" }}>
                      Pixal {upd.latest} is out
                    </span>
                    <a href={upd.url} target="_blank" rel="noreferrer"
                       style={{
                         display: "inline-flex", alignItems: "center", gap: SPACE[6],
                         height: 32, padding: `0 ${SPACE[12]}px`,
                         borderRadius: RADIUS.pill, border: "1px solid var(--border)",
                         background: "var(--bg2)", color: "var(--textSec)",
                         textDecoration: "none", fontFamily: FONT, fontSize: TYPE.ui,
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
                      Get Pixal {upd.latest}
                      <ArrowSquareOut size={13} weight="duotone" />
                    </a>
                    {/* The reassurance IS the feature — visible, never a tip. */}
                    <span style={{ fontSize: TYPE.label, color: "var(--textTer)",
                                   lineHeight: 1.5, maxWidth: 320 }}>
                      Updating replaces only Pixal's own modules — your recipes, characters, styles, settings and history stay untouched.
                    </span>
                  </>
                )}
              </div>
            ) : (
              <Bar w={150} h={11} />
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
                   transition: `transform ${MOTION.press}`,
                 }}
                 onMouseEnter={(e) => {
                   e.currentTarget.style.transform = "translateY(-1px)";
                 }}
                 onMouseLeave={(e) => {
                   e.currentTarget.style.transform = "translateY(0)";
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
    </SettingsQuery.Provider>
  );

  return (
    <>
      <style>{CSS}</style>
      <SkeletonStyle />
      <OverlayMotionStyle />
      {/* The CARD owns the shape (overflow hidden); the SCROLL lives on an
          inner region inset by margin, so the scrollbar rides an inner edge
          and never cuts through the rounded corners. */}
      {docked ? (
        // Docked: a sibling of the content surface — same card language, no
        // scrim, non-modal, so the theme toggle previews against live chat.
        <div style={{
          width: "100%", height: "100%",
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: RADIUS.surface,
          // Render-quiet, Chat.jsx's surface discipline — reuses the 9.46
          // renderBusy signal; an 18px blur mid-render fights the job.
          backdropFilter: renderBusy ? "none" : "blur(18px)",
          WebkitBackdropFilter: renderBusy ? "none" : "blur(18px)",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}>{panel}</div>
      ) : (
        // Non-docked is the same scrim-plus-fixed-card pattern every modal
        // uses, so it goes through the shared shell — centred={false}
        // because these are positioned panels, not centred boxes.
        <ModalShell onClose={onClose} z={OVERLAY.panel} scrim="rgba(0,0,0,0.45)"
          centred={false} boxStyle={phone ? {
            // Phone: a bottom sheet - full width, hugging the safe-area edge.
            left: 8, right: 8,
            bottom: "calc(8px + env(safe-area-inset-bottom))", maxHeight: "82dvh",
            background: "var(--bg1)", border: "1px solid var(--borderHov)",
            borderRadius: 20, boxShadow: SHADOW.xl,
            display: "flex", flexDirection: "column", overflow: "hidden",
          } : {
            // Fallback (narrow viewports): buds off the rail's settings button.
            left: 84, bottom: 16, width: 400, maxWidth: "92vw", maxHeight: "86vh",
            background: "var(--bg1)", border: "1px solid var(--borderHov)",
            borderRadius: 20, boxShadow: SHADOW.xl,
            display: "flex", flexDirection: "column", overflow: "hidden",
          }}>
          {panel}
        </ModalShell>
      )}
    </>
  );
};
