// ComfyBoot.jsx — the beat between clicking Pixal and having a studio.
// The sidecar starts ComfyUI through its OWN launcher (the flags in that .bat
// are load-bearing), which takes ~30-60s cold. Rather than a dead screen or a
// spinner that lies about progress, the meter is calibrated: the server
// remembers how long the last cold start actually took on this machine and
// reports it as `expected`, so the bar is honest for this box rather than a
// guess. It holds just short of full if the boot runs long — never claims done
// before ComfyUI answers.
import { useEffect, useRef, useState } from "react";
import { BlockLogo } from "../lib/BlockLogo.jsx";
import { PhotonField } from "../lib/PhotonField.jsx";
import { FONT, W, TYPE, SPACE, RADIUS, MOTION, OVERLAY } from "../lib/design-tokens.js";
import { status } from "../transport.js";

const MONO = "ui-monospace, Consolas, monospace";
const POLL_MS = 1000;
const CEILING = 0.94;        // the last sliver belongs to ComfyUI actually answering

// onReady latches the first time ComfyUI answers. It is a one-way door: the app
// mounts behind us and STAYS mounted, so a mid-session ComfyUI death re-raises
// this overlay without tearing down a lane the user is in the middle of.
export const ComfyBoot = ({ onReady }) => {
  const [boot, setBoot] = useState(null);
  const [up, setUp] = useState(null);       // null = not asked yet, never "assume fine"
  // Consecutive status() failures. When the SIDECAR is what's gone, boot state
  // can never arrive - without counting this, the screen swept forever saying
  // "waiting for ComfyUI" about a server that wasn't there (2026-08-11).
  const [fails, setFails] = useState(0);
  // Sticky on purpose: someone who chose to work without ComfyUI is on their
  // way to Settings, and re-raising the curtain would fight them for the screen.
  const [dismissed, setDismissed] = useState(false);
  const timer = useRef(null);
  const ready = useRef(null);
  ready.current = onReady;
  const fired = useRef(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const d = await status();
        if (!alive) return;
        setFails(0);
        setUp(!!d.comfy);
        setBoot(d.boot || null);
        if (d.comfy) enter();
      } catch {
        if (alive) { setUp(false); setFails((n) => n + 1); }
      }
      // 1s is for the boot meter's honesty; once ComfyUI answers, this is a
      // death watchdog and 4s is plenty - the tight poll made the sidecar do
      // per-second work (status, boot state) for the whole session.
      if (alive) timer.current = setTimeout(tick, fired.current ? 4 * POLL_MS : POLL_MS);
    };
    tick();
    return () => { alive = false; clearTimeout(timer.current); };
  }, []);

  // Letting the user in is idempotent - the poll keeps running after the app
  // has mounted, and re-announcing "ready" every second would remount the lane.
  const enter = () => {
    if (fired.current) return;
    fired.current = true;
    ready.current?.();
  };

  if (up === true || dismissed) return null;

  // Five straight failed polls (~5s) is a verdict, not a blip; the poll keeps
  // running underneath, so the screen reconnects by itself if Pixal returns.
  const sidecarDown = fails >= 5;
  const starting = !!boot?.starting;
  // Closing the console used to be impossible: /api/status polls every second
  // and restarted ComfyUI each time it found it down. Now a close stays closed
  // and this screen is what offers it back.
  const closed = !!boot?.closed;
  const expected = Math.max(5, Number(boot?.expected) || 45);
  const elapsed = Number(boot?.elapsed) || 0;
  const overdue = elapsed > expected;
  // Rescue buttons only when the boot is DEAD, not merely slow: a cold cache
  // routinely blows past the estimate, and buttons on every slow start read
  // as alarming noise. 3x the calibrated estimate (floor 180s) is silence no
  // healthy boot on this box has ever produced.
  const deadOverdue = elapsed > Math.max(expected * 3, 180);
  // ComfyUI owns port 8188 but is not answering. The sidecar deliberately will
  // NOT kill that - a big model load is indistinguishable from a wedge from the
  // outside, and killing the wrong one costs a live render - so the way out has
  // to be offered here. Without this the overlay had no buttons at all
  // (starting=false pins elapsed at 0, so deadOverdue never fires) and a wedged
  // ComfyUI covered the whole app with a sweeping bar and no exit.
  const stalled = Number(boot?.stalled || 0);
  const stalledOut = stalled > 120;
  const fill = starting ? Math.min(CEILING, elapsed / expected) : 0;
  // A few words, one line: the sidecar reads ComfyUI's own log and names the
  // real stage; the generic fallbacks only cover the moments before it can.
  const note = sidecarDown
      ? "the Pixal server (port 8190) stopped answering — restart Pixal (run.bat); this screen reconnects on its own"
    : boot?.error ? boot.error
    : stalledOut
      ? "ComfyUI holds port 8188 but isn't answering — it may still be loading a large model, or it may be wedged. Restart ComfyUI from Settings → Compute if this doesn't clear."
    : stalled ? "ComfyUI is busy — loading a large model"
    : closed ? "you closed the ComfyUI window — start it again when you want to render"
    : !starting ? "waiting for ComfyUI…"
    : boot?.phase ? boot.phase
    : overdue ? "cold cache — still loading"
    : "booting ComfyUI";

  return (
    // px-root is what carries every design token: applyThemeCss scopes the CSS
    // vars to that class. Without it --text, --bg0 and --accent all resolve to
    // nothing, so the copy fell back to inherited black on a transparent
    // backdrop and the progress bar had no colour to draw itself in.
    <div className="px-root" style={{
      position: "fixed", inset: 0, zIndex: OVERLAY.boot, display: "flex",
      alignItems: "center", justifyContent: "center", padding: SPACE[20],
      background: "var(--bg0)", fontFamily: FONT,
      animation: "px-msg-in 400ms ease both",
    }}>
      <PhotonField />
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center",
                    gap: SPACE[16], width: "min(340px, 88vw)", zIndex: 1 }}>
        <BlockLogo size={132} />

        {/* On a dead screen the messaging drops clear of the logo so the two
            read as separate moments; while booting it stays snug so the bar
            below still owns the middle. */}
        <div style={{ textAlign: "center",
                      marginTop: (boot?.error || sidecarDown) ? SPACE[32] : 0 }}>
          <div style={{ fontSize: TYPE.h3, fontWeight: W.heading, color: "var(--text)" }}>
            {sidecarDown ? "Pixal isn’t answering"
              : boot?.error ? "ComfyUI didn’t start"
              : closed ? "ComfyUI is closed" : "Starting ComfyUI"}
          </div>
          {(boot?.error || sidecarDown) && (
            <div style={{ marginTop: SPACE[4], fontSize: TYPE.label,
                          color: "var(--textTer)", lineHeight: 1.5 }}>
              {note}
            </div>
          )}
          {/* The console window is gone by the time anyone reads the line
              above, so name the file that isn't. The sidecar only reports this
              once the wrapper has actually written something to it. */}
          {boot?.error && boot?.error_log && (
            <div style={{ marginTop: SPACE[8], fontFamily: MONO, fontSize: 9,
                          color: "var(--textMut)", wordBreak: "break-all" }}>
              {boot.error_log}
            </div>
          )}
        </div>

        {!boot?.error && !sidecarDown && (
          <div style={{ width: "100%" }}>
            <div style={{ position: "relative", height: 2, width: "100%",
                          borderRadius: RADIUS.pill, background: "var(--bg3)",
                          overflow: "hidden" }}>
              {starting ? (
                <div style={{
                  height: "100%", width: `${Math.round(fill * 100)}%`,
                  borderRadius: RADIUS.pill, background: "var(--accent)",
                  // matches the poll interval, so the bar creeps rather than steps
                  transition: `width ${POLL_MS}ms linear`,
                }} />
              ) : (
                // No launcher kicked yet means no elapsed time to be honest
                // about. A zero-width bar read as "dead", so sweep instead of
                // claiming a percentage we have not measured.
                <div className="px-bar-sweep" style={{
                  position: "absolute", top: 0, height: "100%", width: "38%",
                  borderRadius: RADIUS.pill, background: "var(--accent)",
                }} />
              )}
            </div>
            {/* What it is doing sits UNDER the bar, so the bar reads as the
                progress and this reads as the commentary on it - rather than
                two lines of prose with a hairline lost between them. */}
            <div style={{ display: "flex", alignItems: "baseline", gap: SPACE[8],
                          justifyContent: "space-between", marginTop: SPACE[8] }}>
              <span style={{ fontSize: TYPE.label, color: "var(--textTer)",
                             lineHeight: 1.5 }}>{note}</span>
              <span style={{ fontFamily: MONO, fontSize: 9, color: "var(--textMut)",
                             whiteSpace: "nowrap" }}>
                {starting ? `${Math.round(elapsed)}s / ~${Math.round(expected)}s` : ""}
              </span>
            </div>
          </div>
        )}

        {/* The door must never lock. Settings -> Compute lives INSIDE the app, so
            a comfy_url pointing at the wrong box would otherwise be unfixable:
            ComfyUI never answers, the gate never opens, and the one screen that
            could correct the address is behind the gate. Offered ONLY on an
            outright error or a DEAD boot now - merely-overdue showed these on
            every slow cold start, which read as alarming noise (2026-08-11).
            deadOverdue keeps the wrong-address-fails-as-silence case covered. */}
        {(boot?.error || deadOverdue || sidecarDown || stalledOut || closed) && (
          // A column, not a row: retry sits centered under the messaging as
          // THE action; the escape hatch hangs quieter beneath it.
          <div style={{ display: "flex", flexDirection: "column", gap: SPACE[8],
                        alignItems: "center" }}>
            <button type="button" onClick={() => window.location.reload()}
              style={{ height: 32, padding: `0 ${SPACE[16]}px`, cursor: "pointer",
                       border: "1px solid var(--border)", borderRadius: RADIUS.pill,
                       background: "var(--bg2)", color: "var(--textSec)",
                       fontFamily: FONT, fontSize: TYPE.label }}>
              {closed ? "start ComfyUI" : "retry"}
            </button>
            <button type="button"
              onClick={() => { setDismissed(true); enter(); }}
              style={{ height: 32, padding: `0 ${SPACE[16]}px`, cursor: "pointer",
                       border: "1px solid transparent", borderRadius: RADIUS.pill,
                       background: "transparent", color: "var(--textMut)",
                       fontFamily: FONT, fontSize: TYPE.label }}>
              continue without ComfyUI
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
