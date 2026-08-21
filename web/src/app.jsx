// app.jsx — Pixal entry. First-run gate: until the user has named their
// ComfyUI install and consented to the scan, the Setup sequence owns the
// screen; from then on it never appears again. During the landing beat both
// are mounted — the app fades in under the flying status dot.
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Chat, applyThemeCss } from "./components/Chat.jsx";
import { ComfyBoot } from "./components/ComfyBoot.jsx";
import { Setup } from "./components/Setup.jsx";
import { DARK, LIGHT } from "./lib/design-tokens.js";

// Setup renders before Chat, so the theme stylesheet must exist before Chat's
// own applyThemeCss effect runs (same style tag — idempotent).
const applyStoredTheme = () => {
  let pref = "dark";
  try { pref = localStorage.getItem("pixal-theme") || "dark"; } catch { /* blocked */ }
  const light = pref === "light" || (pref === "system" &&
    window.matchMedia("(prefers-color-scheme: light)").matches);
  applyThemeCss(light ? LIGHT : DARK);
};

const App = () => {
  const [phase, setPhase] = useState("check");   // check | setup | landing | app
  // The lane does NOT mount until ComfyUI answers. It used to render straight
  // away with the boot screen merely painted over it, so every cold start ran
  // the whole app - effects, SSE, catalog reads - against a ComfyUI that was
  // still loading, and the first frame after a click was the app itself, with
  // the curtain arriving a poll later. ComfyBoot owns this door now.
  const [comfyReady, setComfyReady] = useState(false);
  useEffect(() => {
    applyStoredTheme();
    fetch("/api/setup").then((r) => r.json())
      .then((d) => setPhase(d.needs_setup ? "setup" : "app"))
      .catch(() => setPhase("app"));             // server odd - never brick the door
  }, []);

  if (phase === "check") return null;
  return (<>
    {(phase === "landing" || (phase === "app" && comfyReady)) && (
      <div style={phase === "landing"
        ? { animation: "px-msg-in 600ms ease both" } : undefined}>
        <Chat />
      </div>
    )}
    {(phase === "setup" || phase === "landing") && (
      <Setup onLanding={() => setPhase("landing")}
             onDone={() => setPhase("app")} />
    )}
    {/* Only once setup is behind us - during first run the Setup sequence owns
        the screen and reports ComfyUI's state in its own language. */}
    {phase === "app" && <ComfyBoot onReady={() => setComfyReady(true)} />}
  </>);
};

createRoot(document.getElementById("root")).render(<App />);
