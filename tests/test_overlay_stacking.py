"""A viewer sits below the dialogs that open from it.

The still/clip lightbox was pinned at a raw `zIndex: 40` while ModalShell
defaulted to 36/37, so pressing **animate** on an open render mounted the
whole "Direct the clip" dialog underneath the photo. Measured live on
2026-08-24: lightbox 40, dialog 37, its scrim 36. Jesse, on being told it was
an audit rather than a fix: "you cant fix that?"

These pin the band in `design-tokens.js` and the fact that nobody sets a
competing literal, because the next overlay is the one that breaks it.
"""

import re
import unittest
from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "web" / "src"
TOKENS = (WEB / "lib" / "design-tokens.js").read_text(encoding="utf-8")
SHELL = (WEB / "lib" / "ModalShell.jsx").read_text(encoding="utf-8")
CHAT = (WEB / "components" / "Chat.jsx").read_text(encoding="utf-8")


def band():
    body = re.search(r"export const OVERLAY = \{(.*?)\}", TOKENS, re.S).group(1)
    return {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", body)}


class TheBand(unittest.TestCase):
    def test_every_tier_is_present(self):
        self.assertEqual(
            set(band()),
            {"card", "viewer", "panel", "scrim", "modal", "form", "meter", "setup", "boot"})

    def test_the_viewer_is_below_every_dialog(self):
        """The whole point. A dialog opened FROM the viewer lands on top."""
        z = band()
        for tier in ("panel", "scrim", "modal", "form"):
            self.assertLess(z["viewer"], z[tier],
                            f"the lightbox must sit below {tier}")

    def test_the_order_is_the_documented_one(self):
        z = band()
        order = ["card", "viewer", "panel", "scrim", "modal", "form", "meter", "setup", "boot"]
        values = [z[k] for k in order]
        self.assertEqual(values, sorted(values), f"band out of order: {z}")

    def test_a_shell_box_clears_its_own_scrim(self):
        """ModalShell paints the box at z + 1; the band has to leave room."""
        z = band()
        self.assertEqual(z["modal"], z["scrim"] + 1)
        self.assertIn("z = OVERLAY.scrim", SHELL)


class NoCompetingLiterals(unittest.TestCase):
    def test_the_lightbox_uses_the_token(self):
        self.assertIn("zIndex: OVERLAY.viewer", CHAT)

    def test_no_fixed_overlay_hardcodes_a_band_number(self):
        """A raw zIndex in the band's range is how this bug got in. Local
        stacking (single digits, sitting above a sibling) is fine and stays."""
        z = band()
        lo, hi = z["card"], z["boot"]
        for path in sorted(WEB.rglob("*.jsx")):
            src = path.read_text(encoding="utf-8")
            for n in (int(m) for m in re.findall(r"zIndex:\s*(\d+)", src)):
                if lo <= n <= hi:
                    self.fail(f"{path.name} hardcodes zIndex {n} — use OVERLAY")


if __name__ == "__main__":
    unittest.main()
