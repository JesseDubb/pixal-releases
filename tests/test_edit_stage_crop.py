"""The edit dialog's crop behaves exactly like the character form's.

Jesse fixed one crop and the cardinal consistency rule made its twin a bug:
the Edit dialog's crop tool was still draw-once-perfectly - no pre-placed
region, no move, no handles. Both crops now share one interaction: entering
the tool places a region, dragging inside moves it, eight handles at the
design system's locked geometry resize it, and a drag on the dimmed outside
draws fresh. The brush also stops dropping samples on fast strokes and the
native range input is replaced by the lib MiniSlider.

Static pins in the style of test_character_form.py.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRECTOR = (ROOT / "web" / "src" / "components" / "EditDirector.jsx").read_text(
    encoding="utf-8")
FORM = (ROOT / "web" / "src" / "components" / "CharacterForm.jsx").read_text(
    encoding="utf-8")

HANDLE_ROW = re.compile(r'\{ k: "(\w+)",\s+fx: ([\d.]+),\s+fy: ([\d.]+),\s+cursor: "([\w-]+)" \}')


class TheTwoCropsAgree(unittest.TestCase):
    def test_the_handle_tables_are_identical(self):
        """One interaction everywhere: the eight handles carry the same keys,
        anchor fractions and cursors in both files."""
        director = sorted(HANDLE_ROW.findall(DIRECTOR))
        form = sorted(HANDLE_ROW.findall(FORM))
        self.assertEqual(len(director), 8)
        self.assertEqual(director, form)

    def test_both_share_the_minimum_and_the_preplace(self):
        for src, name in ((DIRECTOR, "EditDirector"), (FORM, "CharacterForm")):
            with self.subTest(file=name):
                self.assertIn("const CROP_MIN = 24;", src)
                # 15% inset on all sides = the 70% starting region.
                self.assertIn("0.15", src)
                self.assertIn("0.7", src)


class TheEditCropIsAdjustable(unittest.TestCase):
    def test_entering_the_tool_places_a_region(self):
        crop_btn = DIRECTOR[DIRECTOR.index('setTool("crop")'):]
        crop_btn = crop_btn[:crop_btn.index("</button>")]
        self.assertIn("setCrop({", crop_btn,
                      "the crop tool must never open onto a blank state")

    def test_all_three_drag_modes_exist(self):
        self.assertIn('{ mode: "draw"', DIRECTOR)
        self.assertIn('{ mode: zone.k', DIRECTOR)
        self.assertIn('d.mode === "move"', DIRECTOR)
        self.assertIn("CROP_HANDLES.find((h) => h.k === d.mode)", DIRECTOR)

    def test_the_cursor_follows_the_zone(self):
        """A handle shows its resize cursor, the region shows move, the
        outside shows the draw crosshair - through state, so a mid-drag
        render cannot clobber it back to crosshair."""
        self.assertIn("const [cropCursor, setCropCursor]", DIRECTOR)
        self.assertIn('tool === "crop" ? cropCursor : "none"', DIRECTOR)

    def test_handles_hold_the_spec_at_any_zoom(self):
        """Constant SCREEN size under the zoom transform: canvas sizes are
        multiplied by the screen->canvas factor, and the geometry is the
        locked spec - 10px corner dots, 18x6 edge pills, white frame."""
        self.assertIn("5 * sk, 0, Math.PI * 2", DIRECTOR)
        self.assertIn("6 * sk, 18 * sk", DIRECTOR)
        self.assertIn("18 * sk, 6 * sk", DIRECTOR)
        self.assertIn('ctx.strokeStyle = "#FFFFFF";', DIRECTOR)
        self.assertIn('"rgba(0, 0, 0, 0.25)"', DIRECTOR)


class TheBrushKeepsUp(unittest.TestCase):
    def test_fast_strokes_use_the_coalesced_samples(self):
        """Pointer events coalesce between frames; on a 239Hz display a fast
        stroke without them cuts corners the hand actually drew."""
        self.assertIn("getCoalescedEvents", DIRECTOR)

    def test_the_brush_control_is_the_lib_slider(self):
        self.assertIn('import { MiniSlider } from "../lib/MiniSlider.jsx";', DIRECTOR)
        self.assertNotIn('type="range"', DIRECTOR,
                         "a native range input is a hand-rolled control here")


if __name__ == "__main__":
    unittest.main()
