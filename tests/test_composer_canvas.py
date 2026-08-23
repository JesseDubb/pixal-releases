"""The canvas picker shows the shape, not just the numbers (brief 9.20).

The size popover's aspect grid rendered eight ratios as bare text - 1:1, 2:3,
3:2, ... - which is arithmetic, not a picture: nothing says at a glance which
are tall and which are wide, and 3:2 vs 2:3 is a transposition you have to
read. Jesse asked for "little squares that represent the aspect ratios ...
rectangles for the tall and wides". The fix mounts the already-committed
`AspectShape` (web/src/lib/AspectShape.jsx, ported from Lumen's AspectPicker)
inside each aspect SizeChip, beside its label. The megapixel group gets none:
a proxy there would be meaningless.

These tests are static in the style of test_rail_vs_inline.py - this repo has
no JS test runner, so the contracts assert the structure of the source. The
two behaviour tests (shape present in every aspect chip; shape is the lib
component) were proven RED against the pre-fix tree. The three guard tests
pin behaviour the brief forbids changing, so they pass on both trees; their
teeth were proven by mutation (each fails against a source mutated in exactly
the way it exists to catch).
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSER = (ROOT / "web" / "src" / "components" / "Composer.jsx").read_text(encoding="utf-8")
LIB_SHAPE = ROOT / "web" / "src" / "lib" / "AspectShape.jsx"

# The aspect chip's select/toggle-off wire, pinned verbatim by the brief:
# re-clicking the lit chip writes "" (no aspect), anything else writes it.
ASPECT_ON = "on={opts.aspect === a}"
ASPECT_CLICK = 'onClick={() => setOpts({ aspect: opts.aspect === a ? "" : a })}'

# Every ratio the picker ships, for the nothing-hardcoded check. The list
# lives in the test, not the component: options.aspects is the only source.
KNOWN_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9")


def _size_group(src, label):
    """The JSX of one SizeGroup in the size popover, opening tag to closer.
    SizeGroups never nest, so the first </SizeGroup> ends the slice."""
    start = src.index(f'<SizeGroup label="{label}"')
    end = src.index("</SizeGroup>", start)
    return src[start:end]


class AspectShapeChips(unittest.TestCase):

    def test_every_ratio_renders_a_shape(self):
        """Every entry of options.aspects gets a shape: the one SizeChip
        inside options.aspects.map mounts <AspectShape ratio={a} /> keyed on
        the map variable, so a shape per option is construction, not
        convention. The numeric label stays beside it - if room ran short
        the shape is what yields, never the numbers."""
        group = _size_group(COMPOSER, "Aspect ratio")
        self.assertRegex(group, r"<AspectShape\s+ratio=\{a\}\s*/>")
        self.assertIn('{a.split(" ")[0]}', group,
                      "the numeric label no longer renders beside the shape")

    def test_the_shape_is_the_committed_lib_component(self):
        """The shape is lib/AspectShape.jsx, imported - not a local helper.
        Lumen already ships this proxy and DESIGN.md rule 1 says not to
        re-solve it; a second implementation in Composer.jsx is the fork
        this test exists to catch."""
        self.assertTrue(LIB_SHAPE.is_file(), "web/src/lib/AspectShape.jsx is missing")
        self.assertRegex(
            COMPOSER,
            r'import\s*\{\s*AspectShape\s*\}\s*from\s*["\']\.\./lib/AspectShape\.jsx["\']')
        self.assertIsNone(
            re.search(r"\b(?:const|function)\s+AspectShape\b", COMPOSER),
            "Composer.jsx defines its own AspectShape instead of importing lib's")

    def test_the_megapixel_group_renders_no_shape(self):
        """Megapixels is a different question - a count, not a geometry - so
        its chips stay shapeless."""
        self.assertNotIn("AspectShape", _size_group(COMPOSER, "Megapixels"))

    def test_no_ratio_added_removed_or_reordered(self):
        """options.aspects is the only source, in the server's order: the
        grid is exactly one map over it, keyed by the option string itself,
        and no ratio literal is hardcoded into the group."""
        group = _size_group(COMPOSER, "Aspect ratio")
        self.assertEqual(group.count(".map("), 1,
                         "the aspect grid is no longer a single map")
        self.assertIn("options.aspects.map((a) => (", group)
        self.assertIn("key={a}", group)
        for literal in KNOWN_RATIOS:
            self.assertNotIn(literal, group,
                             f"ratio {literal} is hardcoded into the aspect group")

    def test_aspect_chip_click_behaviour_is_unchanged(self):
        """Selected state and click - toggle-off to "" included - are pinned
        exactly as they were before the shape arrived."""
        group = _size_group(COMPOSER, "Aspect ratio")
        self.assertIn(ASPECT_ON, group)
        self.assertIn(ASPECT_CLICK, group)


if __name__ == "__main__":
    unittest.main()
