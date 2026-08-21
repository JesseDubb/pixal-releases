// Setup.jsx — the first-run opening sequence, extremely minimal by design:
// name your ComfyUI install, consent to a scan of it, watch the scan narrate,
// get one clean SUCCESS beat — then the status dot flies home to the lower-left
// rail and the app is just... there. Four phases: pick → scanning → success →
// landing (transparent, dot in flight over the mounted app).
import { useEffect, useRef, useState } from "react";
import { ArrowRight } from "@phosphor-icons/react";
import { CURVE, FONT, LOGO_FONT, W, TYPE, SPACE, RADIUS } from "../lib/design-tokens.js";
import { BlockLogo } from "../lib/BlockLogo.jsx";

const MONO = "ui-monospace, Consolas, monospace";
const GREEN = "#7BB495", PINK = "#E3A7B0";

// Where the rail dot actually lives (NavRail.jsx): desktop = bottom of the
// 76px left rail; narrow = far right of the top bar. Close enough — the
// flight dot cross-fades with the real one at journey's end.
const dotHome = () => (window.innerWidth < 720
  ? { x: window.innerWidth - 19, y: 32 }
  : { x: 34.5, y: window.innerHeight - 23 });

export const Setup = ({ onLanding, onDone }) => {
  const [phase, setPhase] = useState("pick");   // pick | scanning | success | landing
  const [root, setRoot] = useState("");
  const [error, setError] = useState(null);
  const [lines, setLines] = useState([]);       // scan narration, terminal-style
  const [comfyUp, setComfyUp] = useState(false);
  const [totals, setTotals] = useState(null);
  const [flown, setFlown] = useState(false);
  const es = useRef(null);
  const gate = useRef({ post: false, scan: false, fired: false, t0: 0 });

  useEffect(() => {
    fetch("/api/setup").then((r) => r.json())
      .then((d) => setRoot(d.detected || ""))
      .catch(() => {});
    return () => { if (es.current) es.current.close(); };
  }, []);

  const maybeSuccess = () => {
    const g = gate.current;
    if (!(g.post && g.scan) || g.fired) return;
    g.fired = true;
    // a warm-cache scan finishes in a blink; keep the narration readable and
    // absorb the stale done-snapshot an SSE re-join can deliver instantly
    const hold = Math.max(0, 1800 - (Date.now() - g.t0));
    setTimeout(() => {
      setPhase("success");
      setTimeout(() => {                  // hold the beat, then start the flight
        setPhase("landing");
        onLanding();                      // parent mounts the app underneath
        requestAnimationFrame(() => requestAnimationFrame(() => setFlown(true)));
        setTimeout(onDone, 1250);         // flight 800ms + fade, then unmount
      }, 1200);
    }, hold);
  };

  const begin = async () => {
    const path = root.trim();
    if (!path) { setError("name the folder your ComfyUI lives in"); return; }
    setError(null);
    gate.current.t0 = Date.now();
    setPhase("scanning");
    if (!es.current) {
      es.current = new EventSource("/api/events");
      es.current.onmessage = (e) => {
        let d; try { d = JSON.parse(e.data); } catch { return; }
        if (d.type !== "scan") return;
        if (d.done) {
          setTotals(d.totals || "scan complete");
          gate.current.scan = true;
          maybeSuccess();
        } else if (d.text) {
          setLines((ls) => [...ls.slice(-5), d.text]);
        }
      };
    }
    try {
      const r = await fetch("/api/setup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: path }),
      });
      const d = await r.json();
      if (!d.ok) { setPhase("pick"); setError(d.error || "that didn't work"); return; }
      setComfyUp(!!d.comfy);
      gate.current.post = true;
      maybeSuccess();
    } catch (e) {
      setPhase("pick");
      setError("server unreachable: " + e.message);
    }
  };

  const landing = phase === "landing";
  const home = dotHome();
  const dotColor = comfyUp ? GREEN : PINK;

  return (
    <div className="px-root" style={{
      position: "fixed", inset: 0, zIndex: 60,
      display: "flex", alignItems: "center", justifyContent: "center",
      background: landing ? "transparent" : "var(--bg0)",
      transition: "background 500ms ease",
      pointerEvents: landing ? "none" : "auto",
      fontFamily: FONT, color: "var(--text)",
    }}>
      {!landing && <div className="px-lamp" />}

      {/* the dot: centered pulse in success, then one translate to the rail */}
      {(phase === "success" || landing) && (
        <span aria-hidden="true" style={{
          position: "fixed", top: 0, left: 0, width: 7, height: 7,
          borderRadius: 999, background: dotColor, zIndex: 62,
          boxShadow: flown ? "none" : `0 0 14px 2px ${dotColor}66`,
          transform: flown
            ? `translate(${home.x}px, ${home.y}px) scale(1)`
            : `translate(calc(50vw - 3.5px), calc(50vh + 86px)) scale(1.6)`,
          transition: `transform 800ms ${CURVE.spring}, box-shadow 800ms ease, ` +
                      "opacity 300ms ease 900ms",
          opacity: landing && flown ? 0 : 1,
        }} />
      )}

      {!landing && (
        <div style={{ position: "relative", zIndex: 61, width: "min(460px, 88vw)",
                      display: "flex", flexDirection: "column", alignItems: "center",
                      textAlign: "center", gap: SPACE[16],
                      transform: "translateY(-4vh)" }}>
          <BlockLogo size={72} />
          <div style={{ fontFamily: LOGO_FONT, fontWeight: W.heading,
                        fontSize: 26, letterSpacing: "-0.01em" }}>
            pixal
          </div>

          {phase === "pick" && (<>
            <div style={{ fontSize: TYPE.body, color: "var(--textSec)" }}>
              Point me at your ComfyUI install.
            </div>
            <form style={{ width: "100%", display: "flex", gap: SPACE[8] }}
              onSubmit={(e) => { e.preventDefault(); begin(); }}>
              <input className="px-input" value={root} spellCheck={false}
                onChange={(e) => setRoot(e.target.value)}
                placeholder="D:\ComfyUI_windows_portable"
                style={{
                  flex: 1, minWidth: 0, padding: `${SPACE[10]}px ${SPACE[12]}px`,
                  fontFamily: MONO, fontSize: 13, color: "var(--text)",
                  background: "var(--bg2)", border: "1px solid var(--border)",
                  borderRadius: RADIUS.input, outline: "none",
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; }}
                onBlur={(e) => { e.currentTarget.style.borderColor = "var(--border)"; }} />
              <button type="submit" title="allow the scan"
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: `${SPACE[10]}px ${SPACE[14]}px`, cursor: "pointer",
                  fontFamily: FONT, fontSize: TYPE.ui, fontWeight: W.medium,
                  color: "var(--accentInk)", background: "var(--accent)",
                  border: "none", borderRadius: RADIUS.input, whiteSpace: "nowrap",
                }}>
                allow scan <ArrowRight size={14} weight="bold" />
              </button>
            </form>
            <div style={{ fontSize: TYPE.label, color: "var(--textTer)",
                          lineHeight: 1.5, maxWidth: 400 }}>
              pixal reads model <em style={{ fontStyle: "normal",
                color: "var(--textSec)" }}>filenames</em> from that install's
              models folder (plus anything in its extra_model_paths.yaml) —
              nothing else is touched, nothing leaves this machine.
            </div>
            {error && (
              <div style={{ fontSize: TYPE.label, color: PINK }}>{error}</div>
            )}
          </>)}

          {phase === "scanning" && (
            <div style={{ minHeight: 120, display: "flex", flexDirection: "column",
                          alignItems: "center", gap: 4 }}>
              {(lines.length ? lines : ["scanning models…"]).map((l, i, a) => (
                <div key={i} style={{
                  fontFamily: MONO, fontSize: 11, whiteSpace: "nowrap",
                  color: i === a.length - 1 ? "var(--accent)" : "var(--textTer)",
                  opacity: 0.45 + 0.55 * ((i + 1) / a.length),
                }}>{l}</div>
              ))}
            </div>
          )}

          {phase === "success" && (
            <div className="px-msg" style={{ minHeight: 120, display: "flex",
                          flexDirection: "column", alignItems: "center", gap: SPACE[8] }}>
              <div style={{ fontFamily: LOGO_FONT, fontWeight: W.heading,
                            fontSize: 20, letterSpacing: "0.02em",
                            color: comfyUp ? "var(--text)" : "var(--textSec)" }}>
                {comfyUp ? "SUCCESS" : "scan complete"}
              </div>
              <div style={{ fontFamily: MONO, fontSize: 11, color: "var(--textTer)" }}>
                {comfyUp ? "connected to comfyui · " : "comfyui offline — i'll watch for it · "}{totals}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
