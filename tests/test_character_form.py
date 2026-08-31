"""9.82 - the character page, designed.

The anchor form read as a database record: name/age/race/sex/style/notes in a
column, and the composed caption those fields feed rendered BELOW them,
framed as output. The redesign (briefs/9.82-character-page-redesign.md) leads
the left pane with the live sentence and groups the fields by where their
words go - identity (the photo decides the face), always true (rides every
render), for the writer (guidance the scene writer sees, not backstory).

Source-level pins on web/src/components/CharacterForm.jsx, the same way
test_segmented_control.py pins its callsites: the JSX is the contract, and a
regex that stops matching IS the regression report.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "CharacterForm.jsx").read_text(
    encoding="utf-8")


def _block(src, start_marker, end_marker):
    """The source from start_marker up to end_marker (both must exist)."""
    i = src.index(start_marker)
    j = src.index(end_marker, i + len(start_marker))
    return src[i:j]


class TheSentenceLeads(unittest.TestCase):
    """The composed caption is the point of the page, so it opens the left
    pane; everything below it is a way to change the sentence."""

    def test_the_caption_card_precedes_every_group(self):
        card = SRC.index("every caption will carry")
        for marker in ('label="identity"', 'label="always true"',
                       'label="for the writer"'):
            self.assertGreater(SRC.index(marker), card,
                               "%s sits above the caption card" % marker)

    def test_the_wardrobe_lock_travels_with_the_card(self):
        # The lock is the caption's last clause - it lives inside the card,
        # folded, not down with the fields.
        self.assertLess(SRC.index("<Disclosure"), SRC.index('label="identity"'))


class SexIsTheSharedControl(unittest.TestCase):
    """The hand-rolled three-button row is replaced by the ONE segmented
    control (9.23b) - the grid variant, so the three labels can never clip."""

    def test_the_hand_rolled_row_is_gone(self):
        self.assertNotIn('["female", "male", "other"].map', SRC,
                         "the hand-rolled sex buttons are back")
        self.assertNotIn('role="radiogroup"', SRC,
                         "radiogroup semantics belong to the lib component")

    def test_the_callsite_is_the_grid_variant(self):
        self.assertIn('from "../lib/SegmentedControl.jsx"', SRC)
        self.assertEqual(SRC.count("<SegmentedControl"), 1,
                         "exactly one segmented control - the sex row")
        m = re.search(r"<SegmentedControl\b(.+?)/>", SRC, re.S)
        self.assertIsNotNone(m, "no SegmentedControl callsite at all")
        call = m.group(1)
        self.assertIn('variant="grid"', call)
        self.assertIn("ariaLabel", call,
                      "the group takes its accessible name from ariaLabel")
        self.assertIn('{ v: "female", label: "female" }', call,
                      "options drifted from the one-key `v` contract")

    def test_the_label_no_longer_adopts_the_first_button(self):
        # Field renders a <label> by default, and a <label> adopts the first
        # labelable descendant as its labeled control - wrapped around the old
        # buttons, clicking the word "sex" selected female. The radiogroup
        # cell renders as a div; SegmentedControl names itself via ariaLabel.
        self.assertIn('as: Tag = "label"', SRC)
        self.assertIn('label="sex" as="div"', SRC)


class ThePreviewTracksItsFields(unittest.TestCase):
    """The preview re-runs from every field that feeds the composed sentence;
    a field missing from the effect types into a stale card."""

    EFFECT = _block(SRC, "// Debounced so typing a name", "characterPreview(ch)")

    def test_the_payload_carries_all_six_composed_fields(self):
        for piece in ("name: name.trim()", "sex,", "style: style.trim()",
                      "wardrobe_lock: wardrobe.trim()", "ch.age", "ch.race"):
            self.assertIn(piece, self.EFFECT,
                          "%s no longer feeds the preview" % piece)

    def test_the_dep_array_lists_all_six(self):
        self.assertIn("}, [name, age, race, sex, style, wardrobe]);", SRC,
                      "a field was dropped from the preview effect's deps")


class TheFieldsTellTheTruth(unittest.TestCase):
    """Labels say where the words go. The copy that taught false things -
    notes inviting the jobs-and-lifestyle backstory SYSTEM_LOCAL tells the
    writer to discard - is gone."""

    def test_the_false_teaching_is_gone(self):
        for dead in ("who they are off-camera", "barista",
                     "how they read at a glance"):
            self.assertNotIn(dead, SRC, '"%s" is back' % dead)

    def test_the_groups_state_their_rules(self):
        self.assertIn("the photo decides the face", SRC)
        self.assertIn("only what is true in every picture", SRC)
        self.assertIn("look and identity only, not jobs or lifestyle", SRC)


if __name__ == "__main__":
    unittest.main()
