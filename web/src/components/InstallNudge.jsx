// InstallNudge.jsx — the one-time "give Pixal its own taskbar icon" row.
//
// The taskbar identity this row used to sell now arrives by itself: the
// shortcuts carry System.AppUserModel.ID "Chrome.127.0.0.1_/", the same id
// Chrome stamps on the --app= window pixal.vbs always opens, so the pinned
// button and the window fold into one with no PWA involved (2026-08-24).
// pixal.vbs never launches --app-id anymore - a PWA window would carry
// "Chrome._crx_<id>" and BREAK that fold. What installing still adds is a
// Start Menu entry and Chrome's app management; whether this row should keep
// offering it, and with what copy, is an open question (see
// briefs/taskbar-identity-findings.md, part 2). status.pwa still gates it.
//
// Chrome only fires beforeinstallprompt in a real tab. An --app window has no
// omnibox and no menu, so it cannot install anything itself. The button
// adapts: with a captured prompt event it asks natively right here; without
// one it opens a normal tab on the same origin, where the event can fire and
// this same row does the native ask. localStorage is shared across both, and
// the storage listener folds the row in every open window the moment one of
// them finishes the job.
//
// The event is caught in index.html, not here. It fires as soon as Chrome has
// the manifest, which is before a deferred 700KB module has mounted anything,
// and it never fires twice - so a listener that only exists after mount misses
// it in a real tab and leaves this row stuck in its no-event branch forever.
// window.__pixalInstall is that catch; "pixal:installable" is how it says so
// if the event happens to land after mount instead.
//
// And the no-event branch now asks where it IS before opening a tab. In an
// app window a tab is the right answer. In a tab that already has no event,
// Chrome is not offering an install at all, and opening another tab only
// repeats the trick that just failed - so say so instead of looping.
import { useEffect, useState } from "react";
import { RADIUS, SPACE, TYPE } from "../lib/design-tokens.js";
import { status } from "../transport.js";

const KEY = "pixal.install.nudge";
const done = () => { try { localStorage.setItem(KEY, "done"); } catch { /* private mode */ } };

// A real Chrome tab matches display-mode: browser; a --app window (or an
// installed PWA) reports standalone or minimal-ui instead.
const inAppWindow = () => {
  try { return !matchMedia("(display-mode: browser)").matches; }
  catch { return false; }
};

export const InstallNudge = () => {
  const [show, setShow] = useState(false);
  const [evt, setEvt] = useState(() => {
    try { return window.__pixalInstall || null; } catch { return null; }
  });
  const [stuck, setStuck] = useState(false);

  useEffect(() => {
    let seen = null;
    try { seen = localStorage.getItem(KEY); } catch { /* private mode */ }
    if (seen === "done") return undefined;
    let alive = true;
    status().then((d) => { if (alive && d && d.pwa === false) setShow(true); })
      .catch(() => { /* sidecar answers or the row stays hidden - fine */ });
    const onPrompt = (e) => { e.preventDefault(); setEvt(e); setStuck(false); };
    // index.html caught one before we mounted, or catches one later.
    const onEarly = () => { setEvt(window.__pixalInstall || null); setStuck(false); };
    const onInstalled = () => { done(); setShow(false); };
    const onStorage = (e) => { if (e.key === KEY && e.newValue === "done") setShow(false); };
    addEventListener("beforeinstallprompt", onPrompt);
    addEventListener("pixal:installable", onEarly);
    addEventListener("appinstalled", onInstalled);
    addEventListener("storage", onStorage);
    return () => {
      alive = false;
      removeEventListener("beforeinstallprompt", onPrompt);
      removeEventListener("pixal:installable", onEarly);
      removeEventListener("appinstalled", onInstalled);
      removeEventListener("storage", onStorage);
    };
  }, []);

  if (!show) return null;

  const install = async () => {
    let ask = evt;
    if (!ask) { try { ask = window.__pixalInstall || null; } catch { ask = null; } }
    if (ask) {
      ask.prompt();
      const choice = await ask.userChoice.catch(() => null);
      setEvt(null);                       // a prompt event is single-use
      try { window.__pixalInstall = null; } catch { /* nothing to clear */ }
      // Told no to the native dialog: drop the row for this session and ask
      // no further - appinstalled handles yes.
      if (choice && choice.outcome !== "accepted") setShow(false);
    } else if (inAppWindow()) {
      // No omnibox here, so the ask has to happen somewhere that has one.
      open(`${location.origin}/?install=1`, "_blank");
    } else {
      // Already in a tab and STILL no event: Chrome has decided this page is
      // not installable right now - most often because it is already
      // installed under this profile. Another tab would land in exactly the
      // same place, so stop and say so.
      setStuck(true);
    }
  };

  return (
    <div role="status" style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                                padding: `0 ${SPACE[12]}px ${SPACE[8]}px`,
                                color: "var(--textTer)", fontSize: TYPE.label }}>
      <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}
            title="Installed as an app, Pixal gets its own window and taskbar icon — pinning it pins Pixal, not Chrome.">
        {stuck
          ? "Chrome isn’t offering to install this page — it may already be installed."
          : "Pixal can have its own taskbar icon — install it as an app."}
      </span>
      <button type="button" onClick={install} disabled={stuck}
        // The tab this row opens exists only to run this button, so put the
        // cursor on it: Chrome will not let a page call prompt() without a
        // click, and a second identical-looking row is not an obvious ask.
        autoFocus={new URLSearchParams(location.search).has("install")}
        style={{ height: 22, padding: `0 ${SPACE[10]}px`, flexShrink: 0,
                 cursor: stuck ? "default" : "pointer", opacity: stuck ? 0.4 : 1,
                 border: "1px solid var(--accentStr)", borderRadius: RADIUS.pill,
                 background: "var(--accentMut)", color: "var(--accent)",
                 fontFamily: "inherit", fontSize: TYPE.label }}>
        install
      </button>
      <button type="button" aria-label="Not now" title="not now"
        onClick={() => { done(); setShow(false); }}
        style={{ background: "none", border: "none", padding: 2, cursor: "pointer",
                 color: "var(--textTer)", flexShrink: 0, fontSize: TYPE.label }}>
        ✕
      </button>
    </div>
  );
};
