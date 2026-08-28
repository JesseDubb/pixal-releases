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
import { Fragment, useEffect, useRef, useState } from "react";
import { CaretDown, Check, DesktopTower, Envelope, Eye, EyeSlash, FolderOpen, LockKey, Moon, Plus, Sun, ArrowSquareOut, X } from "@phosphor-icons/react";
import { FONT, W, TYPE, SPACE, RADIUS, MOTION, SHADOW, OVERLAY } from "../lib/design-tokens.js";
import { Lockup } from "../lib/Lockup.jsx";
import { ModalShell, OverlayMotionStyle } from "../lib/ModalShell.jsx";
import { Picker } from "../lib/Picker.jsx";
import { SegmentedControl } from "../lib/SegmentedControl.jsx";
import { ComfyWordmark, LightricksMark, MiniMaxMark, NvidiaMark } from "../lib/BrandMarks.jsx";
import { InfoTip } from "./InfoTip.jsx";
import { Bar, LineGhost, PickerGhost, SegGhost, SkeletonStyle, ValueGhost } from "./Skeleton.jsx";
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

// ── vertical rhythm ───────────────────────────────────────────────────────
// One scale for the whole panel, each step ~3x the last, so a control reads as
// having a start and an end:
//
//     6   inside one control  label -> control -> its footnote
//     8   a section title block -> the first control under it
//    16   between sibling controls in a section
//    32   between sections (the flex gap below)
//    48   above a cluster heading, 12 below it
//
// 6 against 16 is the ratio that gives a control a start and an end: its own
// footnote sits nearly three times closer than the next control's label, so
// the eye stops reading at the right place.
//
// That last asymmetry is the whole point. The old panel gave a heading the
// same air above and below, so it floated between two sections instead of
// opening the one under it - and where there was no heading it used an
// anonymous hairline, which announced a boundary without naming it. One
// mechanism now: every cluster has a name, and the name belongs to what
// follows. The offsets are relative to the container's own 24px gap.
const CSS = `
.px-set-group { margin-top: 16px; }
.px-set > .px-set-group:first-child { margin-top: 0; }
.px-set > .px-set-group + * { margin-top: -20px; }
`;

// ── loading: ghosts, not guesses ─────────────────────────────────────────
// Twelve slots below start empty and land together from /api/settings (the
// twelfth, `upd`, is About's update check). A control whose options or
// stored value are still in flight renders a ghost of its FINAL size -
// SegGhost is the 40px segmented-control capsule, PickerGhost the 38px ScrollPicker
// trigger - so the panel's scrollHeight is identical before and after the
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
          transformOrigin: "top center",
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
const Field = ({ label, hint, children, sub, className }) => (
  // `sub` is for a control that only exists because of the one above it - the
  // RTX quality tiers, the model list under "Upscale". Left at the section's
  // 16 the two segment rows read as unrelated peers, which is the exact
  // confusion the old five-option row had. 12 is the whole usable band: it
  // has to beat a field's internal 6 (or the sub-label looks like it belongs
  // to the control ABOVE it) while staying under a peer's 16.
  <div className={className} style={{ display: "flex", flexDirection: "column", gap: SPACE[6],
                marginTop: sub ? -SPACE[4] : undefined }}>
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

// Cluster heading inside a tab - the information architecture the flat wall
// of Sections was missing. A hairline carries the eye across.
const GroupLabel = ({ children }) => (
  <div className="px-set-group"
       style={{ display: "flex", alignItems: "center", gap: SPACE[10] }}>
    <span style={{ fontSize: 10, fontWeight: W.heading, color: "var(--textMut)",
                   textTransform: "uppercase", letterSpacing: "0.12em",
                   fontFamily: FONT, whiteSpace: "nowrap" }}>{children}</span>
    <span aria-hidden="true" style={{ flex: 1, borderTop: "1px solid var(--border)" }} />
  </div>
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
      style={{ display: "flex", alignItems: "center", gap: SPACE[10], height: 30,
               padding: `0 ${SPACE[8]}px`, borderRadius: RADIUS.input,
               background: hov ? "var(--bg2)" : "transparent",
               transition: `background ${MOTION.hover}` }}>
      <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                     textOverflow: "ellipsis", whiteSpace: "nowrap",
                     fontFamily: FONT, fontSize: TYPE.ui,
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
// than pushing a most-touched tab down — Brain is the chat brain and the
// reviewer, About the credits. A stale saved id fails the TABS check where
// `tab` is initialised and lands on "general".
const TABS = [
  { id: "general", label: "General" },
  { id: "image", label: "Image" },
  { id: "video", label: "Video" },
  { id: "models", label: "Models" },
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

// One section = a human title + one plain sentence about what it does, then
// its controls 16 apart. The title block and any closing footnote carry a
// negative margin back against that gap: they belong to the control they
// touch, not to the ladder of controls.
const Section = ({ title, gloss, children }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: SPACE[16] }}>
    <div style={{ marginBottom: -SPACE[8] }}>
      <div style={{ fontSize: TYPE.body, fontWeight: W.heading, color: "var(--text)" }}>
        {title}
      </div>
      {gloss && (
        <div style={{ fontSize: TYPE.label, color: "var(--textTer)", lineHeight: 1.5 }}>
          {gloss}
        </div>
      )}
    </div>
    {children}
  </div>
);

// A section's closing sentence. It reads as belonging to the control above it
// only if it sits closer to that control than the next one does - 6, not 16.
const Foot = ({ children }) => (
  <span style={{ marginTop: -SPACE[10], fontSize: TYPE.label,
                 color: "var(--textTer)", lineHeight: 1.5 }}>{children}</span>
);

const inputStyle = {
  height: 38, background: "var(--bg2)", border: "1px solid var(--border)",
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

  // `panel` is the whole content, shared by both presentations below.
  const panel = (
    <>
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
      <div className="px-scroll px-set" style={{
        flex: 1, minHeight: 0, overflowY: "auto", padding: SPACE[20],
        display: "flex", flexDirection: "column", gap: SPACE[32],
      }}>
        {tab === "general" && (<>
        <GroupLabel>the app</GroupLabel>
        <Section title="Appearance" gloss="System follows Windows.">
          <SegmentedControl ariaLabel="Appearance" value={store.themePref}
            onChange={(v) => store.setTheme(v)}
            options={[
              { v: "light", label: "Light", Icon: Sun },
              { v: "dark", label: "Dark", Icon: Moon },
              { v: "system", label: "System", Icon: DesktopTower },
            ]} />
        </Section>

        <Section title={<>Explicit content <InfoTip text="Uncensored writing needs a local abliterated model — most APIs refuse NSFW." /></>}>
          {cfg ? (
            <SegmentedControl className="px-ghost-in" ariaLabel="Explicit content" value={explicit}
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
          <Foot>
            Auto reads your prompt · Never keeps everyone clothed.
          </Foot>
        </Section>

        <GroupLabel>this machine</GroupLabel>
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
          <Field label={<>when ComfyUI boots <InfoTip text="ComfyUI likes to pop its node editor in a browser tab when it starts. quiet keeps that from interrupting; the editor is always at the compute address above." /></>}>
            {cfg ? (
              <SegmentedControl className="px-ghost-in" ariaLabel="When ComfyUI boots" value={comfyEditor}
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
              <SegmentedControl className="px-ghost-in" ariaLabel="ComfyUI console window" value={comfyConsole}
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
        </Section>

        <Section title={<>Clean up <InfoTip text="Nothing hands memory back until asked. Each button says what it freed." /></>}
                 gloss="A full card is a slow render.">
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
          <Field label={<>Brain idles after <InfoTip text="A warmed brain holds ~8 GB. Idle, it unloads; the next message wakes it in seconds." /></>}>
            {cfg ? (
              <SegmentedControl className="px-ghost-in" ariaLabel="Brain idles after" value={idleMin}
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
        </Section>

        <Section title={<>VRAM profile <InfoTip text="What this machine can hold resident. Advisory: pickers flag what a tier holds poorly — the VRAM butler still manages the card at render time." /></>}
                 gloss={!cfg ? (
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
            <SegmentedControl className="px-ghost-in" ariaLabel="VRAM profile" value={vramProfile}
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
        </Section>

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
        <GroupLabel>defaults</GroupLabel>
        <Section title={<>Video engine <InfoTip text="The Animate popup still switches engines freely per clip — this only sets where it starts." /></>}
                 gloss="Which engine the popup opens on.">
          {videoCfg ? (
            <SegmentedControl className="px-ghost-in" ariaLabel="Default video engine"
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
        </Section>
        <Section title={<>Video model <InfoTip text="The popup still switches models freely per clip — this only sets the default." /></>}
                 gloss="Which model the popup opens on.">
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
        </Section>
        <Section title={<>Dialogue format <InfoTip text="How spoken lines are written in H3 briefs. quotes is the default — (S1) says “…”, the MiniMax-H3 #76 form; it won the same-seed A/B with no opening blip and no cue read aloud. tags is MiniMax's trained (S1) says: <d>[English] …</d>, which some seeds open with a half-second of gibberish." /></>}
                 gloss="How H3 briefs write speech.">
          {videoCfg ? (
            <SegmentedControl className="px-ghost-in" ariaLabel="Dialogue format"
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
        </Section>
        <GroupLabel>finishing</GroupLabel>
        <Section title="Upscaler"
                 gloss="The upscale button on finished clips.">
          {/* Two different things, not one five-step ladder. RTX Super
              Resolution is NVIDIA's image-space filter and its Low..Ultra are
              ITS quality tiers; LTX 2.5 re-renders the clip through the latent
              upsampler and has no quality setting at all. Flattened into one
              row they read as a single scale where "Ultra" and "LTX 2.5 2x"
              are neighbours - and five segments is over DESIGN.md's
              four-option cap either way. Engine first, then only what that
              engine actually has to set. */}
          {upscale ? (<>
            <Field className="px-ghost-in" label="video clips"
                   hint={vidLtx
                     ? "2× re-render: real new detail, heavier VRAM."
                     : upscale.video_available
                       ? undefined
                       : "Install the Deno RTX VFX node pack."}>
              <SegmentedControl ariaLabel="Video upscale engine"
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
                  { v: "ltx", label: "LTX 2.5 2×", Icon: LightricksMark,
                    disabled: !upscale.ltx25_video_available,
                    title: upscale.ltx25_video_available
                      ? "Lightricks LTX 2.5, 2× re-render"
                      : "LTX 2.5 2× - the weights are not installed" },
                ]} />
            </Field>
            {!vidLtx && upscale.video_available && (
              <Field className="px-ghost-in" sub label="quality"
                     hint={upscale.video_scale > 1
                       ? `Upscaled ${upscale.video_scale}× with audio kept.`
                       : "Same size, cleaned up. Audio kept."}>
                <SegmentedControl ariaLabel="RTX Super Resolution quality"
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
              <Field className="px-ghost-in" sub
                     label={<>frame rate <InfoTip size={12} text="RIFE interpolation, in the same pass as the upscale. Doubles or more the frames, audio kept. Lips can ghost above 2×. LTX 2.5 ignores it — that mode re-renders at the clip's own rate." /></>}>
                <SegmentedControl ariaLabel="Clip frame rate"
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
          </>) : (<>
            {/* the ghost is the default shape: engine row + quality row +
                frame rate row (a stored LTX clip drops the two sub rows -
                that one-time shrink is the stored setting correcting itself,
                not a load reflow) */}
            <Field label="video clips">
              <SegGhost segments={2} />
            </Field>
            <Field sub label="quality">
              <SegGhost segments={4} />
            </Field>
            <Field sub label="frame rate">
              <SegGhost segments={4} />
            </Field>
          </>)}
        </Section>
        <Section title={<>H3 2× upscale <InfoTip text="It runs inside the render — it re-samples the render's own latent, so it can never be a button on a finished clip — and costs roughly 3× the render time." /></>}
                 gloss="The popup still decides per clip — this sets the default.">
          {/* The MiniMax upscaler re-samples the render's own latent, so it
              can only live on the render itself (9.31) - the per-clip row in
              the Animate popup's fine-tune fold. This is the standing default
              that row opens on, the same contract as Video model above. No
              quality sub-row: 2× is the only size this upscaler does. */}
          {videoCfg ? (
            <Field className="px-ghost-in"
                   hint={videoCfg.upscale_2x_available
                     ? undefined
                     : "Needs the MMH3 Ultimate Upscale pack and 659 MB weights."}>
              <SegmentedControl ariaLabel="H3 2× upscale"
                value={videoCfg.upscale_2x ? "2x" : "off"}
                onChange={(id) => {
                  const on = id === "2x";
                  setVideoCfg((v) => ({ ...(v || {}), upscale_2x: on }));
                  apply({ video: { upscale_2x: on } },
                        on ? "2× default applied" : "2× default off");
                }}
                options={[
                  { v: "off", label: "Off",
                    disabled: !videoCfg.upscale_2x_available,
                    title: videoCfg.upscale_2x_available
                      ? "The render's native canvas — the fast path."
                      : "Needs the MMH3 Ultimate Upscale pack and 659 MB weights." },
                  { v: "2x", label: "2×",
                    disabled: !videoCfg.upscale_2x_available,
                    title: videoCfg.upscale_2x_available
                      ? "Twice the size, inside the render — roughly 3× the render time."
                      : "Needs the MMH3 Ultimate Upscale pack and 659 MB weights." },
                ]} />
            </Field>
          ) : (
            <SegGhost segments={2} />
          )}
        </Section>
        <Section title={<>H3 resolution <InfoTip text="The canvas H3 renders at natively — detail comes from the model, not an upscaler. A bigger canvas re-frames the shot (composition can shift) and multiplies the render time: a 10 s Max clip is ~20 min on a 5090 and fills the card. The 2× row stays the budget option — render small, then upscale." /></>}
                 gloss="The popup still decides per clip — this sets the default.">
          {/* 9.55: same contract as Video model above - the standing default
              the Animate popup's Resolution row opens on. The tier list rides
              the settings payload (h3_resolutions); the inline fallback only
              covers an out-of-date server. */}
          {videoCfg ? (
            <SegmentedControl className="px-ghost-in" ariaLabel="H3 resolution"
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
        </Section>
        </>)}

        {tab === "image" && (<>
        <GroupLabel>model choices</GroupLabel>
        <Section title={<>Z-Image decoder <InfoTip text="Z-Image and Flux share a VAE, so sharper drop-in decoders exist. Applies to Z-Image renders only — the clear-anime profile keeps its own matched VAE either way." /></>}
                 gloss="Sharper drop-in; can over-sharpen on one pass.">
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
        </Section>
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
          {editCfg ? (<>
            <Field className="px-ghost-in" label={<>whole frame <InfoTip size={12} text="An undistilled build runs ~20 steps and takes about five times longer." /></>}>
              <Picker label="whole frame edit model"
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
            <Field className="px-ghost-in" label={<>masked area <InfoTip size={12} text="An undistilled build runs ~20 steps and takes about five times longer." /></>}>
              <Picker label="masked area edit model"
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
          </>) : (<>
            {/* the shared trigger is a fixed 28px, so the ghost finally IS
                the control's own box - 9.70's call for the chat brain, here
                for both lanes (PickerGhost's 38px was the ScrollPicker
                trigger's height) */}
            <Field label="whole frame">
              <Bar h={28} />
            </Field>
            <Field label="masked area">
              <Bar h={28} />
            </Field>
          </>)}
        </Section>
        <GroupLabel>finishing</GroupLabel>
        <Section title={<>Upscaler <InfoTip text="Used by the upscale button on a finished render. Model mode upscales the frame it already made; PiD mode repaints it tile by tile with NVIDIA's pixel-diffusion decoder. The model's own factor decides the size — a 4× model on a 1024-wide frame gives 4096." /></>}
                 gloss={upscale ? (
                   <span className="px-ghost-in">{`Model upscales; PiD repaints. ${(upscale.installed || []).length} installed.`}</span>
                 ) : (
                   <>Model upscales; PiD repaints. <ValueGhost w={56} /></>
                 )}>
          {upscale ? (
            <>
              <Field className="px-ghost-in" label="still frames"
                     hint={(upscale.image_mode || "model") === "pid"
                       ? "Invents texture; first use downloads it. " +
                         "Non-commercial license."
                       : upscale.pid_available === false
                         ? "Install the ComfyUI-PiD node pack for PiD."
                         : undefined}>
                <SegmentedControl ariaLabel="Image upscale mode"
                  value={upscale.image_mode || "model"}
                  onChange={(m) => {
                    setUpscale({ ...upscale, image_mode: m });
                    apply({ upscale: { image_mode: m } },
                          m === "pid" ? "PiD upscaler applied" : "model upscaler applied");
                  }}
                  options={[
                    { v: "model", label: "Upscale" },
                    { v: "pid", label: "PiD 4×", Icon: NvidiaAccent,
                      disabled: upscale.pid_available === false,
                      title: upscale.pid_available === false
                        ? "install the ComfyUI-PiD node pack" : undefined },
                  ]} />
              </Field>
              {/* PiD never reads image_model - build_upscale_image returns
                  before it does - so offering an ESRGAN pick in PiD mode is
                  a control that does nothing. */}
              {(upscale.image_mode || "model") !== "pid" && (
              <Field className="px-ghost-in" sub label="upscale model">
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
            </>
          ) : (
            <>
              {/* the ghost is the default shape: mode row + the model list
                  under it (a stored PiD mode drops the picker - that
                  one-time shrink is the stored setting correcting itself,
                  not a load reflow) */}
              <Field label="still frames">
                <SegGhost segments={2} />
              </Field>
              <Field sub label="upscale model">
                <PickerGhost />
              </Field>
            </>
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
        <Section title={<>VAE decode <InfoTip maxWidth={300} text="Identity Edit only — no other recipe reads this. Every render ends by decoding the sampler's latent into pixels; normally that is the Wan VAE, at the canvas you picked. PiD hands that last step to NVIDIA's pixel-diffusion decoder instead, which repaints the latent at 4× in a 4-step pass — so the canvas first snaps to a preset it accepts, and a 2:3 comes back 2688×4032. The identity photo still encodes through the real VAE either way; only the decode changes." /></>}>
          <Field hint={pidCfg?.identity_finish
            ? "Experimental: canvas snaps to 1024-class presets, returns 4×."
            : "Wan VAE decode at your canvas."}>
            {pidCfg ? (
              <SegmentedControl className="px-ghost-in" ariaLabel="VAE decode"
                value={!!pidCfg.identity_finish}
                onChange={(on) => {
                  setPidCfg({ ...pidCfg, identity_finish: on });
                  apply({ pid: { identity_finish: on } },
                        on ? "PiD decode applied" : "Wan VAE decode restored");
                }}
                options={[
                  { v: false, label: "Wan VAE" },
                  { v: true, label: "PiD 4×", Icon: NvidiaAccent,
                    disabled: pidCfg.decode_available === false,
                    title: pidCfg.decode_available === false
                      ? "install the ComfyUI-PiD node pack" : undefined },
                ]} />
            ) : (
              <SegGhost segments={2} />
            )}
          </Field>
        </Section>
        </>)}

        {tab === "models" && (<>
        {/* 9.30 — the library. Read-only on purpose: it is the surface that
            finally shows the user what they own and what each thing can and
            cannot do here; the choosing stays on the medium tabs. */}
        <GroupLabel>what you own</GroupLabel>
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
                         color: "var(--textTer)", lineHeight: 1.5 }}>
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
              {libGroups.map((g) => (
                <Fragment key={g.key}>
                  <GroupLabel>{g.key === "other" ? "Other" : familyName(g.key)}</GroupLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    {g.rows.map((rel) => (
                      <LibraryRow key={rel} rel={rel} name={g.names[rel]}
                        meta={libMeta[rel] || {}} detectedGb={detectedGb} />
                    ))}
                  </div>
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
        <GroupLabel>chat</GroupLabel>
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
              /* the shared trigger is a fixed 28px, so the ghost finally IS
                 the control's own box - the list's 36px row ghost was the
                 smallest honest hold for a variable-height list */
              <Bar h={28} />
            ) : (localList.length ? (
              <div className="px-ghost-in">
                <Picker label="Local brain model" value={localModel}
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
              </div>
            ) : (
              <div className="px-ghost-in" style={{ fontSize: TYPE.label, color: "var(--textTer)" }}>
                no .gguf chat models found in your model folders
              </div>
            ))}
            {/* A stored value, not navigation — stays a segmented control. With
                "brain runs on" below that is two segment rows in this panel,
                the cap; a third would mean the grouping is wrong. */}
                          <Field label={<>between replies <InfoTip text="Keeping the model loaded means instant replies, but it holds a few GB of VRAM next to your renders. It steps aside when a render needs the room. Unloading frees the card; the next reply waits for a reload." /></>}>
              {cfg ? (
                <SegmentedControl className="px-ghost-in" ariaLabel="memory policy" value={localKeep}
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
            <Field label={<>brain runs on <InfoTip text="GPU replies fast but holds VRAM next to the render; CPU chat is slow but frees the card for rendering." /></>}>
              {cfg ? (
                <SegmentedControl className="px-ghost-in" ariaLabel="brain runs on" value={localGpu}
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

        {/* 9.60: whose rulebook the writer runs. Own section, not a row inside
            Chat brain - a Field cannot carry both a tip and a hint (the copy
            contract), so the families subline is the section gloss, and the
            Chat brain section is already at the two-segmented-row cap. */}
        <Section title={<>Official prompting <InfoTip text="Writes scenes the way the model's makers recommend — Krea 2's own expansion prompt on Krea 2 recipes. A family with no official file is unchanged either way. Off uses Pixal's photo-craft rules." /></>}
                 gloss={officialGloss}>
          {cfg ? (
            <SegmentedControl className="px-ghost-in" ariaLabel="Official prompting" value={officialPrompting}
              onChange={(on) => {
                setOfficialPrompting(on);
                apply({ llm: { official_prompting: on } },
                      on ? "writes with the model makers' own prompt"
                         : "writes with Pixal's photo-craft rules");
              }}
              options={[{ v: true, label: "On" },
                        { v: false, label: "Off" }]} />
          ) : (
            <SegGhost segments={2} />
          )}
        </Section>

        <GroupLabel>vision</GroupLabel>
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
        <Section title={<>{criticBrain?.sighted ? "Fallback reviewer" : "Image reviewer"} <InfoTip text="The chat brain reviews directly whenever it has working eyes; this ComfyUI model only runs when it does not. Bigger models read hands and text better; first use takes ~30s to warm up." /></>}
                 gloss={!criticBrain?.local
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
    </>
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
          backdropFilter: "blur(18px)", WebkitBackdropFilter: "blur(18px)",
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
