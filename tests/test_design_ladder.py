"""The height ladder, the rhythm table, the one button, the one tip.

2026-09-04. Jesse, after a month of Settings passes: "he keeps making one off
sizes for things, changes info bubble size whenever he likes, button use and
how to use CTAs, primary, secondary, tert." Measured that day, the Settings
panel carried eight distinct control heights - 24, 26, 28, 30, 32, 34, 38, 40
- and every one of them could cite an authority: the token file's xs/sm/md/lg
ladder (24/28/32/40), DESIGN.md's 34px beat, or Lumen's own 28/32/40. Pixal
had nine button implementations and none in lib/, no button section in
DESIGN.md, and an InfoTip whose size and width were props (two call sites had
already grown their own).

The fix is not another rule; it is fewer choices. HEIGHT has three entries by
ROLE (rail / row / cta), RHYTHM has five distances by RELATIONSHIP, lib/Btn is
the button, and InfoTip has no size. This file pins the ladder and the fact
that the rail family reads it instead of typing numbers.

Static assertions on the source; tests/test_settings_geometry.py measures
the rendered panel against the same tokens.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web" / "src"


def _read(rel):
    return (WEB / rel).read_text(encoding="utf-8")


TOKENS = _read("lib/design-tokens.js")
BTN = _read("lib/Btn.jsx")
TIP = _read("components/InfoTip.jsx")
MENU = _read("components/SettingsMenu.jsx")


def _table(name):
    body = re.search(r"export const %s = \{(.*?)\};" % name, TOKENS, re.S).group(1)
    return {k: int(v) for k, v in re.findall(r"^\s*(\w+):\s*(\d+),", body, re.M)}


class TheLadder(unittest.TestCase):

    def test_three_heights_by_role_and_no_others(self):
        """rail 26 / row 34 / cta 40. A size ladder (xs/sm/md/lg) invites
        picking; a role ladder answers the question. 26 in a 34 row is 4px of
        air each side - even, like every distance in the app."""
        height = _table("HEIGHT")
        self.assertEqual(height, {"rail": 26, "row": 34, "cta": 40})
        self.assertEqual((height["row"] - height["rail"]) % 4, 0,
                         "a rail control must sit an even number of pixels inside its row")
        for v in height.values():
            self.assertEqual(v % 2, 0, "an odd height lands hairlines on half pixels")
        self.assertNotRegex(TOKENS, r"^\s*(xs|sm|md|lg):", "the size-named ladder is back")

    def test_five_distances_by_relationship(self):
        rhythm = _table("RHYTHM")
        self.assertEqual(rhythm, {"control": 6, "rows": 8, "run": 16, "cluster": 32, "break": 56})
        self.assertEqual(rhythm["run"], 2 * rhythm["rows"])
        self.assertEqual(rhythm["cluster"], 2 * rhythm["run"])
        self.assertGreater(rhythm["break"], 3 * rhythm["run"],
                           "a heading's air above must dwarf the air below it")


# The About tab is frozen byte-for-byte at Jesse's instruction ("I like the
# about page so dont touch that" - AboutByteIdentical in test_settings_pills).
# Its two anchors-styled-as-buttons and the 40px beer button are therefore the
# one sanctioned exception to everything below, and the scan stops at it.
ABOUT = '{tab === "about" && ('
MENU_LIVE = MENU[:MENU.index(ABOUT)]


class TheRailFamilyReadsTheLadder(unittest.TestCase):
    """Nothing you click on the Settings panel, or in the controls that ride
    its rail, states its height as a number. A number is a second authority."""

    FILES = ("lib/Picker.jsx", "lib/NumberField.jsx", "components/Skeleton.jsx",
             "lib/Btn.jsx", "components/InfoTip.jsx")

    def test_no_literal_control_heights(self):
        offenders = []
        sources = [("components/SettingsMenu.jsx", MENU_LIVE)] + [(rel, _read(rel)) for rel in self.FILES]
        for rel, src in sources:
            for m in re.finditer(r"(?<![A-Za-z])height: (\d+)\b", src):
                if int(m.group(1)) >= 20:          # hairlines, knobs and bars stay literal
                    offenders.append("%s: %s" % (rel, m.group(0)))
        self.assertEqual(offenders, [], "a control typed its own height: %s" % offenders)

    def test_the_rail_controls_are_rail_height(self):
        self.assertIn("height: HEIGHT.rail", _read("lib/Picker.jsx"))
        self.assertIn("height: HEIGHT.rail", _read("lib/NumberField.jsx"))
        seg = _read("lib/SegmentedControl.jsx")
        self.assertRegex(seg, re.compile(r"const PILL_TRACK = \{.*?height: HEIGHT\.rail", re.S))
        self.assertIn("const PILL_OPTION_H = HEIGHT.rail - 6;", seg)
        skeleton = _read("components/Skeleton.jsx")
        self.assertIn("height: HEIGHT.rail, width: 180", skeleton, "PickerGhost left the rail")
        self.assertIn("h={HEIGHT.rail - 6}", skeleton, "SegGhost's options left the rail")

    def test_settings_rows_can_grow_while_inputs_keep_their_role_height(self):
        workspace = _read("components/SettingsWorkspace.jsx")
        self.assertIn("min-height:${SETTINGS.row}px", workspace)
        self.assertRegex(MENU, re.compile(r"const inputStyle = \{\s*height: HEIGHT\.row", re.S))
        self.assertIn("overflow-wrap:anywhere", workspace)


class TheOneButton(unittest.TestCase):

    def test_settings_imports_the_button_and_owns_none(self):
        self.assertIn('import { Btn } from "../lib/Btn.jsx";', MENU)
        self.assertNotIn("const Btn = ", MENU, "Settings grew its own button again")
        self.assertNotIn("RAIL_H", MENU, "a locally measured height is a second ladder")

    def test_sizes_are_the_ladder_and_variants_are_the_hierarchy(self):
        self.assertIn("sm: { height: HEIGHT.rail", BTN)
        self.assertIn("md: { height: HEIGHT.row", BTN)
        self.assertIn("lg: { height: HEIGHT.cta", BTN)
        for variant in ("ghost", "primary", "link", "danger"):
            self.assertRegex(BTN, re.compile(r"^  %s: \{" % variant, re.M),
                             "Btn lost its %s variant" % variant)
        self.assertIn("borderRadius: RADIUS.pill", BTN)

    def test_rail_buttons_ride_at_rail_height(self):
        """Every button on a setting row is size="sm" - at HEIGHT.row they
        filled the row and buttons in consecutive rows touched (Jesse,
        2026-09-04: "buttons crammed and overlapping")."""
        self.assertGreaterEqual(len(re.findall(r'<Btn size="sm"', MENU)), 9)

    def test_one_primary_on_the_panel(self):
        """A primary is the ONE call to action; a second one is a design
        error, not a size question."""
        self.assertLessEqual(len(re.findall(r'variant="primary"', MENU)), 1)
        # Auto-saving Settings has no primary CTA. Maintenance is not the
        # task a user opened Settings to accomplish, so Free all stays quiet.
        self.assertNotRegex(MENU, r'variant="primary"[^>]*onClick=\{freeAll\}')

    def test_the_selects_are_gone(self):
        self.assertNotRegex(MENU, r"<select\s+value=", "a native <select> is a defect on sight (DESIGN.md §1)")
        self.assertIn('<Picker hug label="DLSS 5 style"', MENU)


class TheOneTip(unittest.TestCase):

    def test_infotip_has_no_size_props(self):
        self.assertIn('export const InfoTip = ({ text, side = "bottom" })', TIP)
        self.assertNotRegex(TIP, r"\b(size|maxWidth) = \d+")
        self.assertIn("const ICON = 14;", TIP)
        self.assertIn("const WIDTH = 260;", TIP)

    def test_no_call_site_resizes_a_tip(self):
        offenders = []
        for path in sorted(WEB.rglob("*.jsx")):
            for m in re.finditer(r"<InfoTip\b[^>]*\b(size|maxWidth)=", path.read_text(encoding="utf-8")):
                offenders.append("%s: %s" % (path.name, m.group(0)[:60]))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
