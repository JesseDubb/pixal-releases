"""One segmented control, two honest variants (brief 9.23b).

Pixal had three file-local segmented controls - a settings radio row, the
Animate dialog's own, and a grid switch in the composer - each missing
something another had. They collapsed into ONE component,
``web/src/lib/SegmentedControl.jsx``, with two declared variants:

- ``variant="flex"`` (default) fills a fixed width and CAN shrink below a
  label, so it carries the 9.21 clip contract (minWidth:0 paired with
  overflow:hidden + textOverflow:ellipsis) and a composed title that keeps
  the full label in the tooltip.
- ``variant="grid`` cannot shrink below its own label (grid items carry
  implicit min-width:auto - DESIGN.md's measured proof), so it declares no
  clip rule at all. Folding the grid switch into the flex recipe would
  reintroduce the exact label-clipping defect 9.21 fixed.

These are source-level assertions, the same way test_rail_vs_inline.py pins
Chat.jsx: the JSX is the contract, and a regex that stops matching IS the
regression report.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web" / "src"
LIB_PATH = WEB / "lib" / "SegmentedControl.jsx"
LIB = LIB_PATH.read_text(encoding="utf-8") if LIB_PATH.exists() else ""

CALLSITE_FILES = [
    WEB / "components" / "SettingsMenu.jsx",
    WEB / "components" / "MotionDirector.jsx",
    WEB / "components" / "Composer.jsx",
    WEB / "components" / "CharacterForm.jsx",
]
CALLSITES = {p.name: p.read_text(encoding="utf-8") for p in CALLSITE_FILES}


def _block(src, start_marker, end_marker):
    """The source from start_marker up to end_marker (both must exist)."""
    i = src.index(start_marker)
    j = src.index(end_marker, i + len(start_marker))
    return src[i:j]


class OneImplementation(unittest.TestCase):
    """Exactly one segmented-control implementation exists in web/src - the
    three old names are gone, not deprecated, and no fourth radiogroup has
    appeared. A dead duplicate is how the next person picks the wrong one."""

    def test_the_three_old_names_appear_nowhere_in_web_src(self):
        # \bSeg\b needs explicit letter boundaries: SegGhost (the skeleton
        # placeholder) and SegmentedControl itself must not trip it.
        old = {
            "SegRadio": re.compile(r"SegRadio"),
            "SegmentedToggle": re.compile(r"SegmentedToggle"),
            "Seg": re.compile(r"(?<![A-Za-z])Seg(?![A-Za-z])"),
        }
        for path in sorted(WEB.rglob("*.jsx")) + sorted(WEB.rglob("*.js")):
            text = path.read_text(encoding="utf-8")
            for name, pat in old.items():
                self.assertIsNone(pat.search(text),
                                  "%s still mentions %s" % (path, name))

    def test_exactly_one_radiogroup_implementation_exists(self):
        owners = []
        for path in sorted(WEB.rglob("*.jsx")):
            if 'role="radiogroup"' in path.read_text(encoding="utf-8"):
                owners.append(path.relative_to(WEB).as_posix())
        self.assertEqual(owners, ["lib/SegmentedControl.jsx"],
                         "a second segmented control is back: %s" % owners)


class GridDoesNotClip(unittest.TestCase):
    """The grid variant's labels do not clip - asserted, not assumed. Its
    segment style declares no shrink rule and no clip rule because grid
    columns cannot shrink below their own label."""

    GRID = _block(LIB, "const gridStyle = ", "return (") if LIB else ""

    def test_grid_declares_no_shrink_or_clip_rule(self):
        self.assertNotIn("minWidth", self.GRID,
                         "a shrink rule on a grid segment is dead code "
                         "hiding the contract that makes this variant safe")
        self.assertNotIn("textOverflow", self.GRID)
        self.assertNotIn("overflow", self.GRID)

    def test_grid_is_equal_columns_that_cannot_shrink(self):
        self.assertIn("gridTemplateColumns", LIB)
        self.assertIn("repeat(", LIB,
                      "grid columns are repeat(n, 1fr) - 1fr floors at the "
                      "content's min-width, which is the whole point")


class FlexKeepsTheClipContract(unittest.TestCase):
    """flex:1 + minWidth:0 permits a segment to shrink below its label;
    the clip pair decides what shows when it does (9.21, d115203 before it)."""

    FLEX = _block(LIB, "const flexStyle = ", "const gridStyle = ") if LIB else ""
    LABEL = _block(LIB, "<span style={{", "</span>") if LIB else ""

    def test_all_four_clip_properties_survive(self):
        self.assertIn("minWidth: 0", self.FLEX)
        self.assertIn('whiteSpace: "nowrap"', self.FLEX)
        self.assertIn('overflow: "hidden"', self.FLEX,
                      "a segment that can shrink must also clip")
        self.assertIn('textOverflow: "ellipsis"', self.LABEL,
                      "a clipped label ends in an ellipsis, not a hard cut")

    def test_the_composed_title_still_guarantees_the_label(self):
        # Clipping is only honest if hover hands the whole label back. The
        # title is built from fullLabel, which itself must be built from
        # opt.label (2026-09-01: the chip rejoins the label there, so a
        # "PiD" + 4× chip still tooltips as "PiD 4×").
        full = re.search(r"const fullLabel = (.+?);", LIB, re.S)
        self.assertIsNotNone(full, "the chip-aware fullLabel is gone")
        self.assertIn("opt.label", full.group(1),
                      "fullLabel must be built from opt.label")
        m = re.search(r"const title = (.+?);", LIB, re.S)
        self.assertIsNotNone(m, "options carry no composed title at all")
        self.assertIn("fullLabel", m.group(1),
                      "a clipped segment's tooltip must contain the full label")


class DisabledInBothVariants(unittest.TestCase):
    """The grid original had NO way to disable an option; Lumen solved it
    with option buttonProps. The merged control makes disabled first-class
    on the option shape AND keeps buttonProps - both must reach the button,
    in both variants (the variants share one button, so one disabled path
    covers both)."""

    def test_opt_disabled_reaches_the_button(self):
        self.assertIn("!!opt.disabled", LIB)
        self.assertIn("disabled={off}", LIB,
                      "the button never reads the option's disabled flag")
        self.assertIn("if (!off) onChange(opt.v)", LIB,
                      "a disabled option can still fire onChange")

    def test_both_variant_styles_show_the_disabled_state(self):
        for marker in ("const flexStyle = ", "const gridStyle = "):
            block = _block(LIB, marker, "};")
            self.assertIn('off ? "default" : "pointer"', block,
                          "%s lost its disabled cursor" % marker)
            self.assertIn("off && !active ? 0.45 : 1", block,
                          "%s lost its disabled dimming" % marker)

    def test_lumen_button_props_still_override(self):
        # {...opt.buttonProps} is how Lumen's version disables an option;
        # it spreads after the built-ins, so it wins.
        i = LIB.index("{...(opt.buttonProps || {})}")
        j = LIB.index("style={grid ? gridStyle : pill ? pillStyle : flexStyle}")
        self.assertLess(i, j, "buttonProps must spread before style")


class OneOptionKey(unittest.TestCase):
    """The option key is `v` everywhere. The grid original's `value` key is
    gone with no compatibility shim - a shim is how a fourth implementation
    starts."""

    def test_the_component_reads_only_v(self):
        self.assertIn("opt.v", LIB)
        self.assertNotIn("opt.value", LIB,
                         "the component still reads the retired key")

    def test_every_call_site_uses_v(self):
        # An option literal carries a label beside its key; no literal with
        # `value:` beside `label:` may survive in a call-site file.
        stray = re.compile(r"\{[^{}]*\bvalue:[^{}]*\blabel:", re.S)
        for name, text in CALLSITES.items():
            self.assertIsNone(stray.search(text),
                              "%s still passes options keyed on `value`" % name)


    def test_all_call_sites_use_the_one_component(self):
        # 17 in SettingsMenu, 6 in MotionDirector, 2 in the Composer - the
        # 9.23b census plus H3's attention row (9.28) and 2x upscale row
        # (9.28), the H3 2× default in Settings (9.31) and the 9.38
        # dialogue-format row, minus the Animate model-family track (9.32 -
        # the dropdown names that choice now), plus the 9.46 brain-idle row
        # and the 9.53 frame-rate row on the clip finisher, plus 9.55's two
        # Resolution rows (the Animate fold's and the Settings default), plus
        # 9.60's official-prompting row on the Brain tab, plus the 9.79 VSR
        # quality row under the still upscaler, plus the 9.82
        # character-anchor sex row, plus 1.1.4b's skin-finish row on
        # the Image tab, plus 9.93's shine-removal row beside it.
        total = sum(text.count("<SegmentedControl")
                    for text in CALLSITES.values())
        total = sum(text.count("<SegmentedControl")
                    for text in CALLSITES.values())
        self.assertEqual(total, 27,
                         "call sites drifted from the 9.23b census" +
                         " (10.0: minus the four binary rows that became " +
                         "pixal toggles - skin finish, shine removal, " +
                         "H3 2× upscale, official prompting)")


if __name__ == "__main__":
    unittest.main()
