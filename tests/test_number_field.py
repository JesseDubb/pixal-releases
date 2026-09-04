"""A number box in Settings must be typeable, and must not move the panel.

Jesse, 2026-09-03: "when editing the weight field in settings it makes the
entire panel jump" and "I tried to edit a field manually with keyboard and I
couldnt". Both were one control, hand-rolled three times (DLSS 5 tone, film
grain amount, shine removal strength), with one shape:

    const v = parseFloat(e.target.value);
    if (!Number.isFinite(v)) return;          // on a CONTROLLED input

That cannot be typed in. Clearing gives "", parseFloat("") is NaN, the handler
returns, and React re-renders the old number straight back - the box refuses
to empty. "0." parses to 0, so the point is eaten and 0.75 is unreachable by
keyboard. The spin buttons are hidden globally (Chat.jsx's px-root rules), so
only the arrow keys ever worked. It also POSTed and toasted on EVERY
keystroke, and the toast strip was a flex child of a bottom-anchored card, so
the panel resized under the cursor mid-edit.

Static, in the style of test_settings_pills.py - this repo has no JS runner.
Proven RED against the pre-fix tree (0b9cac4): the three inputs were raw
`<input type="number">` with parseFloat-gated onChange, and the note row was
`{note && (<div ...>)}` in normal flow.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")
FIELD = (ROOT / "web" / "src" / "lib" / "NumberField.jsx").read_text(encoding="utf-8")


class NumberFieldIsShared(unittest.TestCase):
    def test_settings_hand_rolls_no_number_input(self):
        """Every numeric box in Settings goes through the shared control.

        DESIGN.md's rule, and the reason this bug existed in triplicate: the
        warning was already written down in Composer's StrengthInput ("a
        controlled box that refills with the default cannot be cleared") and
        Settings hand-rolled past it anyway."""
        self.assertNotIn('type="number"', SETTINGS)
        self.assertIn('import { NumberField } from "../lib/NumberField.jsx";', SETTINGS)

    def test_the_three_dials_use_it(self):
        for label in ("DLSS 5 tone", "Film grain amount", "Shine removal strength"):
            with self.subTest(label=label):
                self.assertRegex(SETTINGS, r"<NumberField[^>]*?" + re.escape(label))

    def test_no_dial_saves_on_every_keystroke(self):
        """`apply` writes config and raises a toast; a keystroke must not.

        Every NumberField callsite hands `apply` to onCommit, which fires on
        blur, Enter or an arrow - a finished edit - never on change."""
        for block in re.findall(r"<NumberField.*?/>", SETTINGS, re.S):
            with self.subTest(block=block[:60]):
                self.assertIn("onCommit=", block)
                self.assertNotIn("onChange=", block)


class NumberFieldIsTypeable(unittest.TestCase):
    def test_typing_is_a_draft_not_a_value(self):
        """onChange stores the RAW string. Nothing may parse it there - that
        is the whole bug."""
        onchange = re.search(r"onChange=\{\(e\) => ([^}]*)\}", FIELD)
        self.assertIsNotNone(onchange, "NumberField must handle onChange")
        self.assertIn("setDraft(e.target.value)", onchange.group(1))
        self.assertNotIn("parseFloat", onchange.group(1))

    def test_the_box_shows_the_draft_while_editing(self):
        """A controlled value that overwrites the draft is the same bug in a
        different place."""
        self.assertIn("value={draft !== null ? draft : value}", FIELD)

    def test_commit_happens_on_blur_and_enter(self):
        self.assertIn("onBlur={commit}", FIELD)
        self.assertRegex(FIELD, r'e\.key === "Enter".*?commit\(\)', )
        self.assertRegex(FIELD, r'e\.key === "Escape".*?setDraft\(null\)')

    def test_commit_clamps_and_only_reports_a_change(self):
        """Out-of-range typing must land in range, and a blur that changed
        nothing must not POST - or tabbing through Settings would save every
        field it passed."""
        self.assertIn("clamp(n, min, max)", FIELD)
        self.assertIn("next !== committed.current", FIELD)


class PanelDoesNotResize(unittest.TestCase):
    def test_the_save_strip_is_out_of_flow(self):
        """The toast floats over the card instead of joining its column.

        Both card shapes are bottom-anchored flex columns, so a strip that
        appears and disappears in normal flow moves the whole panel - under
        the cursor, on the control still being edited."""
        strip = SETTINGS[SETTINGS.index("this strip is where the save talks back"):]
        strip = strip[:strip.index("</div>")]
        self.assertIn('position: "absolute"', strip)
        self.assertNotIn("{note && (", strip)
        self.assertIn("opacity: note ? 1 : 0", strip)

    def test_the_floating_shapes_hold_one_height(self):
        """A cap alone lets the card size to its CONTENT, so it resized on
        every tab change - and both floating shapes are anchored from the
        bottom, so the panel jumped on the way to the tab being aimed at.
        The docked shape was always height:100%; these two match it now."""
        for token in ('height: "82dvh"', 'height: "86vh"'):
            with self.subTest(shape=token):
                self.assertIn(token, SETTINGS)
        self.assertNotIn('maxHeight: "82dvh"', SETTINGS)
        self.assertNotIn('maxHeight: "86vh"', SETTINGS)

    def test_the_docked_card_is_the_positioning_context(self):
        self.assertIsNotNone(re.search(
            r'width: "100%", height: "100%",.*?position: "relative"',
            SETTINGS, re.S),
            "the docked card must be positioned or the strip escapes it")


if __name__ == "__main__":
    unittest.main()
