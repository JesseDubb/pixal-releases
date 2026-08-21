// InstallNudge.jsx — the one-time "give Pixal its own taskbar icon" row.
//
// Windows attributes the fallback chrome --app= window to CHROME: pin it and
// the taskbar shows Chrome's icon (Jesse, 2026-08-20). The cure is having the
// PWA installed - pixal.vbs then launches by --app-id and the window carries
// the block icon with its own identity. The sidecar reports whether that is
// already true (status.pwa - the same _crx_ folder check the launcher makes),
// so this row only exists on machines where pinning would actually go wrong.
//
// Chrome only fires beforeinstallprompt in a real tab. An --app window has no
// omnibox and no menu, so it cannot install anything itself. The button
// adapts: with a captured prompt event it asks natively right here; without
// one it opens a normal tab on the same origin, where the event can fire and
// this same row does the native ask. localStorage is shared across both, and
// the storage listener folds the row in every open window the moment one of
// them finishes the job.
import { useEffect, useState } from "react";
import { RADIUS, SPACE, TYPE } from "../lib/design-tokens.js";
import { status } from "../transport.js";

const KEY = "pixal.install.nudge";
const done = () => { try { localStorage.setItem(KEY, "done"); } catch { /* private mode */ } };

export const InstallNudge = () => {
  const [show, setShow] = useState(false);
  const [evt, setEvt] = useState(null);

  useEffect(() => {
    let seen = null;
    try { seen = localStorage.getItem(KEY); } catch { /* private mode */ }
    if (seen === "done") return undefined;
    let alive = true;
    status().then((d) => { if (alive && d && d.pwa === false) setShow(true); })
      .catch(() => { /* sidecar answers or the row stays hidden - fine */ });
    const onPrompt = (e) => { e.preventDefault(); setEvt(e); };
    const onInstalled = () => { done(); setShow(false); };
    const onStorage = (e) => { if (e.key === KEY && e.newValue === "done") setShow(false); };
    addEventListener("beforeinstallprompt", onPrompt);
    addEventListener("appinstalled", onInstalled);
    addEventListener("storage", onStorage);
    return () => {
      alive = false;
      removeEventListener("beforeinstallprompt", onPrompt);
      removeEventListener("appinstalled", onInstalled);
      removeEventListener("storage", onStorage);
    };
  }, []);

  if (!show) return null;

  const install = async () => {
    if (evt) {
      evt.prompt();
      const choice = await evt.userChoice.catch(() => null);
      setEvt(null);                       // a prompt event is single-use
      // Told no to the native dialog: drop the row for this session and ask
      // no further - appinstalled handles yes.
      if (choice && choice.outcome !== "accepted") setShow(false);
    } else {
      open(`${location.origin}/?install=1`, "_blank");
    }
  };

  return (
    <div role="status" style={{ display: "flex", alignItems: "center", gap: SPACE[8],
                                padding: `0 ${SPACE[12]}px ${SPACE[8]}px`,
                                color: "var(--textTer)", fontSize: TYPE.label }}>
      <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}
            title="Installed as an app, Pixal gets its own window and taskbar icon — pinning it pins Pixal, not Chrome.">
        Pixal can have its own taskbar icon — install it as an app.
      </span>
      <button type="button" onClick={install}
        style={{ height: 22, padding: `0 ${SPACE[10]}px`, cursor: "pointer", flexShrink: 0,
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
