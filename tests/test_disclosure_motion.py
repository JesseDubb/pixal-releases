"""One disclosure, and folds stop snapping (brief 9.23c).

Twenty-odd disclosures in this app and exactly one animated. This pins the
fix: a single shared ``Disclosure`` in ``web/src/lib/`` that owns the
grid-rows fold technique, the chevron rotation and the reduced-motion guard,
plus the migration of every fold in the brief's table to it. (The Composer
LoRA-card row of that table is a follow-up — 9.23a owns that file right now.)

These are source-level assertions, the same way test_motion_director_ui.py
pins MotionDirector.jsx: the JSX is the contract, and a regex that stops
matching IS the regression report.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "src"
DISCLOSURE = SRC / "lib" / "Disclosure.jsx"

# The brief's migration table: file -> the open-state variable its fold runs on.
FOLDS = {
    "MotionDirector.jsx": "fineTune",
    "StyleForm.jsx": "tuneOpen",
    "CharacterForm.jsx": "wardOpen",
    "JobCard.jsx": "expanded",
}


def _src(name):
    return (SRC / "components" / name).read_text(encoding="utf-8")


def _disclosure():
    return DISCLOSURE.read_text(encoding="utf-8")


class EveryFoldUsesTheSharedDisclosure(unittest.TestCase):
    """Each fold in the table renders the shared ``Disclosure`` fed by its
    existing open state — not a bare ``{open && (…)}`` mount."""

    def test_disclosure_component_exists(self):
        self.assertTrue(DISCLOSURE.exists(),
                        "web/src/lib/Disclosure.jsx does not exist")

    def test_each_fold_imports_and_renders_disclosure(self):
        for name, state in FOLDS.items():
            with self.subTest(fold=name):
                src = _src(name)
                self.assertIn('../lib/Disclosure.jsx', src,
                              f"{name} does not import the shared Disclosure")
                self.assertRegex(src, r"<Disclosure[\s>]",
                                 f"{name} never renders <Disclosure>")
                self.assertIn(f"open={{{state}}}", src,
                              f"{name}'s fold is not driven by {state}")

    def test_no_bare_mount_folds_remain(self):
        self.assertNotIn("{tuneOpen && (", _src("StyleForm.jsx"),
                         "StyleForm's tuning fold still mounts bare")
        self.assertNotIn("{wardOpen && (", _src("CharacterForm.jsx"),
                         "CharacterForm's wardrobe fold still mounts bare")


class DisclosureOwnsTheTechnique(unittest.TestCase):
    """``grid-template-rows`` 0fr<->1fr on a MOTION token — never a literal
    duration. The token IS the rule; a hand-typed ``ms`` is a defect."""

    def test_grid_rows_fold(self):
        self.assertRegex(_disclosure(),
                         r'gridTemplateRows:\s*open \? "1fr" : "0fr"')

    def test_transitions_use_motion_tokens(self):
        src = _disclosure()
        self.assertIn("grid-template-rows ${MOTION.layout}", src,
                      "the fold height must animate on MOTION.layout")
        self.assertIn("transform ${MOTION.press}", src,
                      "the chevron rotates on MOTION.press — it was pressed")
        self.assertIsNone(re.search(r"\d+\s*ms", src),
                          "a literal duration snuck into Disclosure.jsx — "
                          "durations come from MOTION tokens")

    def test_reduced_motion_guard(self):
        src = _disclosure()
        self.assertIn("prefers-reduced-motion", src)
        self.assertIn("matchMedia", src,
                      "the guard follows the house style — matchMedia, as in "
                      "BlockLogo/DotMatrix/GlassLogo")

    def test_trigger_keeps_aria_expanded(self):
        self.assertIn("aria-expanded", _disclosure())


class JobCardPromptFold(unittest.TestCase):
    """``maxHeight: "none"`` cannot be animated — that was the snap. The 84px
    teaser survives as the fold's collapsed state, not as a deleted feature."""

    def test_no_maxheight_none(self):
        src = _src("JobCard.jsx")
        self.assertIsNone(re.search(r'maxHeight:\s*expanded \? "none"', src))
        self.assertNotIn('maxHeight: "none"', src)

    def test_teaser_height_survives_as_peek(self):
        self.assertIn("peek={SCENE_COLLAPSED}", _src("JobCard.jsx"))


class FineTuneFoldUnchanged(unittest.TestCase):
    """MotionDirector's fine-tune fold was already correct — it becomes the
    first consumer and its behaviour must not move. These pins are migration
    guards: they pass before AND after, and catch a careless port."""

    def test_closed_row_still_narrates(self):
        src = _src("MotionDirector.jsx")
        self.assertIn("{!fineTune && tweaks.length > 0 && (", src,
                      "closed no longer narrates the tweaks it hides")
        self.assertIn('tweaks.join(" · ")', src)

    def test_fold_driven_by_same_state(self):
        self.assertIn("onToggle={toggleFineTune}", _src("MotionDirector.jsx"))


if __name__ == "__main__":
    unittest.main()
