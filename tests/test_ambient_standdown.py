"""Brief 9.98 — ambient surfaces cost zero GPU when unwatched.

Jesse (2026-09-01): "I want that to be extremely light on peoples computers
... dont change the UI or look of the product just if there is anything under
the hood." Zero visible change while the window is focused and idle; the
audit before dispatch found the gallery and BlockLogo already clean and
named the two remaining gaps:

  1. PhotonField never sleeps. BlockLogo's wanted()/sync() discipline (a
     cancelled rAF when calm/hidden/unfocused, listeners on
     visibilitychange/focus/blur, a [calm]-effect resync) is the house
     pattern; PhotonField had none of it — its loop self-perpetuated and the
     calm path kept scheduling a no-op wakeup at display refresh for the
     whole render.
  2. Three backdrop blurs (HistoryGrid, ChatsPanel, SettingsMenu-docked)
     never got Chat.jsx's render-quiet gate
     (`rendering ? "none" : "blur(18px)"`, Chat.jsx:1058 precedent), so an
     open panel kept an 18px backdrop blur sampling against ComfyUI.

These tests are static in the style of test_composer_canvas.py — this repo
has no JS test runner, so the contracts assert the structure of the source.
The two behaviour classes (PhotonFieldSleep, RenderQuietBlurs) were proven
RED against the pre-fix tree. The Guards class pins what the brief forbids
changing (Chat.jsx's existing gates, PhotonField's FRAME_MS and breath
constants, freeze-don't-clear), so it passes on both trees; its teeth were
proven by mutation — each guard fails against a source mutated in exactly
the way it exists to catch.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web" / "src"
PHOTON = (WEB / "lib" / "PhotonField.jsx").read_text(encoding="utf-8")
CHAT = (WEB / "components" / "Chat.jsx").read_text(encoding="utf-8")
HISTORY = (WEB / "components" / "HistoryGrid.jsx").read_text(encoding="utf-8")
CHATS = (WEB / "components" / "ChatsPanel.jsx").read_text(encoding="utf-8")
SETTINGS = (WEB / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")

GATE_18 = 'backdropFilter: rendering ? "none" : "blur(18px)"'
GATE_18_WK = 'WebkitBackdropFilter: rendering ? "none" : "blur(18px)"'
UNCONDITIONAL = 'backdropFilter: "blur(18px)"'  # lowercase b — never a Webkit substring


def _fn_slice(src, decl):
    """The body of one `const name = (...) => { ... };` arrow, from the
    declaration to its closing `};` at the same (four-space) indent."""
    start = src.index(decl)
    end = src.index("\n    };", start)
    return src[start:end]


class PhotonFieldSleep(unittest.TestCase):
    """Gap 1: the loop exists only while the field is watched. BlockLogo's
    wanted()/sync() ported: calm + hidden + focus all gate the rAF, the loop
    is CANCELLED (not a scheduled no-op) whenever unwanted, and it resyncs on
    visibilitychange/focus/blur and on the calm prop itself."""

    def test_wanted_gates_calm_hidden_and_focus(self):
        self.assertIn("const wanted =", PHOTON,
                      "no wanted() gate — the loop has no sleep condition at all")
        wanted = PHOTON[PHOTON.index("const wanted ="):PHOTON.index("\n\n", PHOTON.index("const wanted ="))]
        for token in ("calmRef.current", "document.hidden", "document.hasFocus()"):
            self.assertIn(token, wanted, f"wanted() does not consult {token}")

    def test_sync_cancels_and_restarts_the_loop(self):
        self.assertIn("const sync =", PHOTON,
                      "no sync() — nothing cancels the rAF when the field is unwatched")
        sync = _fn_slice(PHOTON, "const sync =")
        self.assertIn("cancelAnimationFrame(raf)", sync,
                      "sync() never cancels the loop — unwatched still costs GPU")
        self.assertIn("requestAnimationFrame(frame)", sync,
                      "sync() never restarts the loop — waking would stay frozen")

    def test_listeners_cover_visibility_and_focus(self):
        for event in ('addEventListener("visibilitychange"',
                      'addEventListener("focus"',
                      'addEventListener("blur"'):
            self.assertIn(event, PHOTON,
                          f"no {event} listener — sleep/wake misses that transition")

    def test_calm_prop_change_resyncs(self):
        """A cancelled loop cannot notice calm lift on its own (today the
        always-running loop picks it up next frame), so the calm prop must
        actively resync — BlockLogo.jsx:84's effect, verbatim."""
        self.assertRegex(
            PHOTON,
            r"useEffect\(\(\) => \{\s*syncRef\.current\s*&&\s*syncRef\.current\(\);?\s*\},\s*\[calm\]\)",
            "calm-prop changes do not resync — the field would freeze forever mid-render")

    def test_draw_body_schedules_no_raf(self):
        """The old draw opened with `raf = requestAnimationFrame(draw)` and
        the calm path returned AFTER it — a no-op wakeup per frame for the
        whole render. Scheduling now lives in frame(), gated by wanted();
        draw itself must not schedule at all."""
        draw = _fn_slice(PHOTON, "const draw = (now) => {")
        self.assertNotIn("requestAnimationFrame", draw,
                         "draw still schedules rAF — the calm path keeps waking at refresh rate")
        self.assertIn("raf = requestAnimationFrame(frame)", PHOTON,
                      "frame() is not the loop's scheduler")


class RenderQuietBlurs(unittest.TestCase):
    """Gap 2: every 18px backdrop blur goes quiet while ComfyUI samples,
    gated the way Chat.jsx:1058 gates its surface. Idle look byte-identical:
    the blur is exactly what renders when nothing is sampling."""

    def test_history_grid_card_gated(self):
        self.assertIn(GATE_18, HISTORY)
        self.assertIn(GATE_18_WK, HISTORY)
        self.assertNotIn(UNCONDITIONAL, HISTORY,
                         "an unconditional blur(18px) remains on the history card")

    def test_chats_panel_card_gated(self):
        # ChatsPanel already receives the store prop; Chat.jsx:869's own
        # expression is the rendering signal, computed locally.
        self.assertIn("!!store.liveJobs[0]", CHATS,
                      "ChatsPanel does not derive rendering from store.liveJobs")
        self.assertIn(GATE_18, CHATS)
        self.assertIn(GATE_18_WK, CHATS)
        self.assertNotIn(UNCONDITIONAL, CHATS,
                         "an unconditional blur(18px) remains on the chats card")

    def test_settings_menu_docked_card_gated(self):
        # SettingsMenu already computes renderBusy from useStore() (line ~783)
        # for its own mid-render rule — the gate reuses it.
        self.assertIn('backdropFilter: renderBusy ? "none" : "blur(18px)"', SETTINGS)
        self.assertIn('WebkitBackdropFilter: renderBusy ? "none" : "blur(18px)"', SETTINGS)
        self.assertNotIn(UNCONDITIONAL, SETTINGS,
                         "an unconditional blur(18px) remains on the settings card")

    def test_chat_threads_rendering_to_both_history_grids(self):
        """HistoryGrid takes no store, so Chat.jsx passes its own `rendering`
        — at the docked site (line ~1024) and the overlay site (line ~1498).
        One site gated and the other not would un-quiet the narrow layout."""
        self.assertEqual(CHAT.count("rendering={rendering}"), 2,
                         "rendering is not threaded to both HistoryGrid render sites")


class Guards(unittest.TestCase):
    """What the brief forbids changing. Green on both trees; each tooth
    proven by mutation (a source mutated exactly this way fails the guard)."""

    def test_chat_gates_unchanged(self):
        self.assertEqual(CHAT.count(GATE_18), 1, "Chat.jsx's 18px surface gate changed")
        self.assertEqual(CHAT.count(GATE_18_WK), 1)
        self.assertEqual(CHAT.count('backdropFilter: rendering ? "none" : "blur(10px)"'), 1,
                         "Chat.jsx's 10px composer gate changed")
        self.assertIn("const rendering = !!liveJobId;", CHAT)

    def test_photon_field_breath_constants_unchanged(self):
        """FRAME_MS, the breath wave frequencies, the ±0.03-alpha amplitude
        and the dot radius line — the focused-idle look, pinned verbatim."""
        for pinned in (
            "const FRAME_MS = 33;",
            "Math.sin(d.homeX * 0.012 + t * 0.55)",
            "Math.sin(d.homeY * 0.010 - t * 0.4)",
            "const bright = 0.02 + wave * 0.055 + d.activation * 0.25;",
            "const radius = 1 + wave * 0.35 + d.activation * 0.8;",
        ):
            self.assertIn(pinned, PHOTON, f"focused-idle constant changed: {pinned}")

    def test_freeze_dont_clear(self):
        """Stopping the loop must not clear the canvas: the last frame stays
        as the static backdrop, so unwatched looks identical to watched.
        The one clearRect is the render path's per-frame clear."""
        self.assertEqual(PHOTON.count("ctx.clearRect"), 1,
                         "a second clearRect appeared — stopping now blanks the backdrop")

    def test_calm_feed_unchanged(self):
        """Chat.jsx still feeds PhotonField its calm prop — rethreading the
        blurs must not touch the field's own render-quiet wire."""
        self.assertIn("<PhotonField key={resolvedTheme} calm={rendering}", CHAT)


if __name__ == "__main__":
    unittest.main()
