// ComfyCompat.jsx — the status dot's hover card. The 7px dot at the rail's foot
// already answers "is ComfyUI there"; this card answers the next question:
// "does THIS ComfyUI have what Pixal needs" — every node pack Pixal can queue,
// checked against the live install, with a copy button so the report can be
// pasted to a friend debugging their setup. Data is server truth
// (/api/comfy/compat reads object_info); nothing here is hand-maintained.
//
// The card leads with a VERDICT — one sentence and one fraction — and then
// gets out of the way. It used to lead with an LED strip: one segment per
// pack, twelve rounded dashes in a row. Nobody could read it. A segmented bar
// only works when the segments mean something individually and there are few
// enough to count; twelve identical green capsules encode exactly one bit
// ("all fine") while looking like they encode twelve. The fraction says the
// same thing, precisely, in characters a person already knows how to read.
//
// Same reason the per-row status dot is gone from healthy packs: a marker that
// is always the same colour is furniture, not information. Only a MISSING pack
// gets a marker, and it gets promoted to the top of the list with the count of
// what its absence costs.
//
// Render-quiet by construction: opaque surface (no backdrop blur), entrance is
// transform+opacity only, and nothing animates after it settles.
import { useEffect, useRef, useState } from "react";
import { CopySimple, Warning, Check } from "@phosphor-icons/react";
import { FONT, HEIGHT, MOTION, RADIUS, SHADOW, SPACE, TYPE, W, Z } from "../lib/design-tokens.js";
import { comfyCompat } from "../transport.js";

const MONO = "ui-monospace, Consolas, monospace";

// The rail dot's own status pair (NavRail/Setup) — the card must agree with it.
const GREEN = "#7BB495", PINK = "#E3A7B0";
const TTL = 60_000;                 // reopening within a minute reuses the read

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// The pasteable version of the card, for "works on my machine" conversations.
const reportText = (d) => {
  const lines = [
    "Pixal × ComfyUI compatibility",
    `comfyui ${d.version || "(version unknown)"} @ ${d.comfy_url} — ` +
      (d.connected ? "connected" : "offline"),
  ];
  for (const p of d.packs) {
    const okCount = p.nodes.filter((n) => n.ok).length;
    lines.push(p.ok
      ? `[ok] ${p.name} — ${okCount}/${p.nodes.length} nodes`
      : `[MISSING] ${p.name} — needs: ` +
        p.nodes.filter((n) => !n.ok).map((n) => n.name).join(", "));
  }
  return lines.join("\n");
};

// A count column that cannot drift: tabular figures, fixed width, and its own
// right padding so the scroll gutter never lands on top of a digit (it did).
const Count = ({ children, dim }) => (
  <span style={{
    fontFamily: MONO, fontSize: 10, fontVariantNumeric: "tabular-nums",
    color: dim ? "var(--textTer)" : "var(--textSec)",
    flexShrink: 0, whiteSpace: "nowrap", textAlign: "right", minWidth: 34,
  }}>{children}</span>
);

// One healthy pack: name, count, nothing else. 24px row.
const PackRow = ({ pack }) => (
  <div style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                height: 24, flexShrink: 0 }}>
    <span style={{
      flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
      whiteSpace: "nowrap", fontFamily: MONO, fontSize: 11,
      color: "var(--textSec)",
    }}>{pack.name}</span>
    <Count dim>{pack.nodes.length}</Count>
  </div>
);

// One missing pack, inside the alert block: name, what its absence costs, and
// the room for the install control that belongs here once Pixal has somewhere
// safe to send the request.
const GapRow = ({ pack }) => {
  const missing = pack.nodes.filter((n) => !n.ok);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACE[4] }}>
      <div style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                    height: 24 }}>
        <span style={{
          flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap", fontFamily: MONO, fontSize: 11, color: "var(--text)",
        }}>{pack.name}</span>
        <Count>{plural(missing.length, "node")}</Count>
      </div>
      <div style={{
        fontSize: TYPE.label, fontWeight: W.label, color: "var(--textTer)",
        lineHeight: 1.4, overflowWrap: "anywhere",
      }}>{missing.map((n) => n.name).join(", ")}</div>
    </div>
  );
};

// ComfyUI-Manager arrives WITH ComfyUI - it is a pip package started by
// main.py, serving under /v2/, and nodes.py blocks any separately installed
// copy as a duplicate. So there is nothing to install here, only two things
// worth saying: this ComfyUI is too old to have it, or there is a stray clone
// in custom_nodes doing nothing. Silent in the normal case.
const ManagerBlock = ({ manager }) => {
  if (!manager || (!manager.too_old && !manager.stray)) return null;
  const old = manager.too_old;
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: SPACE[6],
      border: "1px solid var(--border)", borderRadius: RADIUS.input,
      background: "var(--bg3)", padding: SPACE[12],
    }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: SPACE[8] }}>
        <span style={{ fontSize: TYPE.ui, fontWeight: W.nav, color: "var(--text)",
                       flex: 1 }}>ComfyUI Manager</span>
        <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--textTer)" }}>
          {old ? "not available" : "duplicate"}
        </span>
      </div>
      <span style={{ fontSize: TYPE.label, fontWeight: W.label,
                     color: "var(--textTer)", lineHeight: 1.45 }}>
        {old
          ? "This ComfyUI is older than the one Pixal targets and has no built-in " +
            "Manager. Pixal needs it to install the node packs your recipes ask " +
            "for — update ComfyUI to 0.32 or newer."
          : "A copy of ComfyUI-Manager is sitting in custom_nodes. ComfyUI blocks " +
            "it as a duplicate of the built-in one (“Blocked by policy” in the " +
            "log) — it can be deleted."}
      </span>
    </div>
  );
};

// `horizontal` mirrors NavRail's phone layout: the card drops below the top
// bar instead of flying out beside the rail.
export const ComfyCompatCard = ({ open, horizontal }) => {
  const [data, setData] = useState(null);
  const [copied, setCopied] = useState(false);
  const fetchedAt = useRef(0);

  useEffect(() => {
    if (!open || Date.now() - fetchedAt.current < TTL) return;
    let stale = false;
    comfyCompat().then((d) => {
      if (!stale && d?.ok) { setData(d); fetchedAt.current = Date.now(); }
    }).catch(() => { /* sidecar hiccup - the card just keeps "reading" */ });
    return () => { stale = true; };
  }, [open]);

  if (!open) return null;

  const copy = async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(reportText(data));
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch { /* clipboard denied - the button just stays quiet */ }
  };

  const custom = data ? data.packs.filter((p) => !p.core) : [];
  const core = data ? data.packs.filter((p) => p.core) : [];
  const ordered = [...custom, ...core];
  const gaps = ordered.filter((p) => !p.ok);
  const good = ordered.filter((p) => p.ok);
  const totalNodes = ordered.reduce((n, p) => n + p.nodes.length, 0);
  const okNodes = ordered.reduce(
    (n, p) => n + p.nodes.filter((x) => x.ok).length, 0);
  const missingNodes = totalNodes - okNodes;

  return (
    // One vertical rhythm, period: 12px between every information block (the
    // root gap), 24px rows inside the list, 4px between a line and its own
    // subline. No block invents its own spacing.
    <div role="dialog" aria-label="ComfyUI compatibility" style={{
      position: "absolute", zIndex: Z.dropdown, width: 296,
      ...(horizontal ? { top: "calc(100% + 10px)", right: -6 }
                     : { left: "calc(100% + 12px)", bottom: -8 }),
      background: "var(--surfaceSolid)", border: "1px solid var(--border)",
      borderRadius: RADIUS.dialog, boxShadow: SHADOW.lg,
      padding: SPACE[16], fontFamily: FONT, cursor: "default",
      display: "flex", flexDirection: "column", gap: SPACE[12],
      animation: `px-compat-in ${MOTION.layout}`, transformOrigin:
        horizontal ? "top right" : "bottom left",
    }}>
      <style>{`@keyframes px-compat-in {
        from { opacity: 0; transform: translateY(${horizontal ? -4 : 4}px) scale(0.98); }
        to   { opacity: 1; transform: none; }
      }`}</style>

      {/* The app names itself before it reports on anything else. Both values
          come from server.py (PIXAL_VERSION / PIXAL_CHANNEL) — a number baked
          into the bundle goes stale the moment the sidecar updates alone. The
          chip is the release CHANNEL, not a maturity badge. */}
      <div style={{ display: "flex", alignItems: "center", gap: SPACE[8] }}>
        <span style={{
          fontSize: 9, letterSpacing: "0.09em", textTransform: "uppercase",
          fontWeight: W.nav, color: "var(--textMut)",
        }}>Pixal</span>
        <span style={{ fontFamily: MONO, fontSize: 10, fontVariantNumeric: "tabular-nums",
                       color: "var(--textTer)" }}>
          {data?.pixal_version || "—"}
        </span>
        {data?.pixal_channel && (
          <span style={{
            fontSize: 9, letterSpacing: "0.09em", textTransform: "uppercase",
            fontWeight: W.nav, color: "var(--textTer)",
            border: "1px solid var(--border)", borderRadius: RADIUS.pill,
            padding: "2px 7px", lineHeight: 1.4,
          }}>{data.pixal_channel}</span>
        )}
      </div>

      <ManagerBlock manager={data?.manager} />

      {/* header: product, then the connection as one plain line. The state
          used to be a coloured word wedged between the name and the version,
          which read as part of the title. It is a fact about the link, so it
          sits with the address. */}
      <div style={{ display: "flex", flexDirection: "column", gap: SPACE[4] }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: SPACE[8] }}>
          <span style={{ fontSize: TYPE.h3, fontWeight: W.heading,
                         color: "var(--text)", flex: 1 }}>ComfyUI</span>
          {data?.version && (
            <span style={{ fontFamily: MONO, fontSize: 10,
                           color: "var(--textTer)", flexShrink: 0 }}>
              v{data.version}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: SPACE[6],
                      minWidth: 0 }}>
          <span style={{
            width: 5, height: 5, borderRadius: RADIUS.pill, flexShrink: 0,
            background: data ? (data.connected ? GREEN : PINK) : "var(--textTer)",
          }} />
          <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--textTer)",
                         whiteSpace: "nowrap", overflow: "hidden",
                         textOverflow: "ellipsis" }}>
            {data ? `${data.connected ? "connected" : "offline"} · ` +
                    (data.comfy_url || "").replace(/^https?:\/\//, "")
                  : "reading the node list…"}
          </span>
        </div>
      </div>

      {data && !data.probed && (
        <span style={{ fontSize: TYPE.ui, color: "var(--textTer)", lineHeight: 1.4 }}>
          no contact yet — the pack list appears once ComfyUI answers.
        </span>
      )}

      {data && data.probed && (
        <>
          {/* the verdict. One sentence, one fraction, one colour. */}
          <div style={{
            display: "flex", flexDirection: "column", gap: SPACE[8],
            border: `1px solid ${gaps.length ? "var(--border)" : "transparent"}`,
            borderRadius: RADIUS.input,
            background: gaps.length ? "var(--bg3)" : "transparent",
            padding: gaps.length ? SPACE[12] : 0,
          }}>
            <div style={{ display: "flex", alignItems: "flex-start",
                          gap: SPACE[8] }}>
              {gaps.length
                ? <Warning size={14} weight="fill" color={PINK}
                           style={{ flexShrink: 0, marginTop: 1 }} />
                : <Check size={14} weight="bold" color={GREEN}
                         style={{ flexShrink: 0, marginTop: 1 }} />}
              <span style={{ flex: 1, minWidth: 0, fontSize: TYPE.ui,
                             lineHeight: 1.4, color: "var(--text)" }}>
                {gaps.length
                  ? `${plural(gaps.length, "pack")} missing — ` +
                    `${plural(missingNodes, "node")} Pixal can't queue`
                  : "Everything Pixal renders is installed"}
              </span>
              <Count dim={!gaps.length}>{okNodes}/{totalNodes}</Count>
            </div>

            {gaps.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column",
                            gap: SPACE[8] }}>
                {gaps.map((p) => <GapRow key={p.name} pack={p} />)}
              </div>
            )}
          </div>

          <div style={{ height: 1, background: "var(--border)", flexShrink: 0 }} />

          {/* the inventory: a quiet mono table under one unit header. Healthy
              packs only — anything missing is already stated above, in full,
              and repeating it here would make the gap easy to scroll past. */}
          <div style={{ display: "flex", flexDirection: "column", gap: SPACE[4] }}>
            <div style={{ display: "flex", alignItems: "baseline",
                          justifyContent: "space-between" }}>
              <span style={{
                fontSize: 9, letterSpacing: "0.09em", textTransform: "uppercase",
                fontWeight: W.nav, color: "var(--textMut)",
              }}>installed packs</span>
              <Count dim>{good.length}</Count>
            </div>
            {/* scrollbar-gutter keeps the count column off the scroll track —
                without it the digits sat underneath the thumb. */}
            <div className="px-scroll" style={{
              display: "flex", flexDirection: "column",
              maxHeight: 264, overflowY: "auto", scrollbarGutter: "stable",
            }}>
              {good.map((p) => <PackRow key={p.name} pack={p} />)}
            </div>
          </div>

          <button type="button" onClick={copy} style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            gap: SPACE[6], height: HEIGHT.row, borderRadius: RADIUS.input,
            border: "1px solid var(--border)", cursor: "pointer",
            background: copied ? "var(--accentMut)" : "var(--bg3)",
            color: copied ? "var(--accent)" : "var(--textSec)",
            fontSize: TYPE.ui, fontWeight: W.nav, fontFamily: FONT,
            transition: `background ${MOTION.hover}, color ${MOTION.hover}`,
          }}
            onMouseEnter={(e) => { if (!copied) e.currentTarget.style.background = "var(--bg4)"; }}
            onMouseLeave={(e) => { if (!copied) e.currentTarget.style.background = "var(--bg3)"; }}>
            <CopySimple size={14} weight="bold" />
            {copied ? "copied" : "copy report"}
          </button>
        </>
      )}
    </div>
  );
};
