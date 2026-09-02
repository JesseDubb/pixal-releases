"""Settings' vertical rhythm and grouping.

Jesse, on the panel this replaces: "things were not systematically grouped,
the vertical spacing didn't allow each control to feel like it had a start and
an end and a little space before the next feature - I call it not having any
vertical spacing rhythm."

Three things had gone wrong and each gets a rule here:

  1. One scale, applied. Between-section air was only twice the within-section
     air, so nothing read as grouped. The ladder is 6 / 16 / 32, plus 48 above
     a cluster heading.
  2. Ad-hoc margins. Five hand-placed marginTops sat outside the scale, so the
     grid was a suggestion rather than a grid.
  3. One grouping mechanism. The panel used three interchangeably - a plain
     gap, an anonymous hairline rule, and a named GroupLabel - and rendered
     the same relationship differently on different tabs.

Static assertions on the source; no JS runtime.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")


def _tab_blocks():
    marks = list(re.finditer(r'\{tab === "(\w+)" &&', SRC))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(SRC)
        out[m.group(1)] = SRC[m.start():end]
    return out


class SettingsRhythm(unittest.TestCase):

    def test_the_ladder_is_the_one_in_the_comment(self):
        """10.0's beat: every setting row is ONE 34px line, rows in a run
        touch (the height IS the gap), 8 inside a section, 32 between
        clusters. The ratio that matters survives: cluster air is multiples
        of the within-section air, or nothing reads as grouped."""
        field = re.search(r'const Field = .*?height: (\d+), gap: SPACE', SRC, re.S)
        section = re.search(r'const Section = .*?gap: SPACE\[(\d+)\]', SRC, re.S)
        scroll = re.search(r'className="px-scroll px-set".*?gap: SPACE\[(\d+)\]', SRC, re.S)
        self.assertIsNotNone(field, "Field lost its 34px row")
        self.assertIsNotNone(section, "Section lost its gap")
        self.assertIsNotNone(scroll, "the scroll container lost px-set or its gap")
        row, mid, outer = (int(m.group(1)) for m in (field, section, scroll))
        self.assertEqual((row, mid, outer), (34, 8, 32))
        self.assertGreaterEqual(outer, mid * 2, "clusters do not read as separate")

    def test_a_cluster_heading_belongs_to_what_is_under_it(self):
        """48 above, 8 below. Equal air on both sides was the old bug: the
        heading floated between two sections instead of opening one. 8 is
        the Section's own title-to-rows gap - heading and title share one
        register since 2026-09-01, so they share one below-air too."""
        css = re.search(r'const CSS = `(.*?)`;', SRC, re.S)
        self.assertIsNotNone(css, "the rhythm stylesheet is gone")
        css = css.group(1)
        above = int(re.search(r'\.px-set-group \{ margin-top: (\d+)px', css).group(1))
        below = int(re.search(r'\.px-set-group \+ \* \{ margin-top: -(\d+)px', css).group(1))
        gap = int(re.search(r'className="px-scroll px-set".*?gap: SPACE\[(\d+)\]',
                            SRC, re.S).group(1))
        self.assertEqual(gap + above, 48)
        self.assertEqual(gap - below, 8)
        section = re.search(r'const Section = .*?gap: SPACE\[(\d+)\]', SRC, re.S)
        self.assertEqual(gap - below, int(section.group(1)),
                         "a heading's below-air drifted from the Section title's")
        self.assertLess(gap - below, gap + above,
                        "the heading must hug the group it names")
        self.assertIn('.px-set > .px-set-group:first-child { margin-top: 0; }', css,
                      "the first heading on a tab would carry dead space above it")

    def test_no_ad_hoc_margins_inside_the_tabs(self):
        """The five hand-placed marginTops that broke the grid. A control that
        needs different spacing needs a component, not a nudge."""
        offenders = []
        for tab, block in _tab_blocks().items():
            if tab == "about":
                continue  # the About card is its own composition, not a control grid
            for m in re.finditer(r'margin(?:Top|Bottom): SPACE\[\d+\]', block):
                offenders.append("%s: %s" % (tab, m.group(0)))
        self.assertEqual(offenders, [], "ad-hoc spacing is back: %s" % offenders)

    def test_every_cluster_boundary_is_named(self):
        """The anonymous hairline said "something changes here" without saying
        what, and it was used interchangeably with GroupLabel - which is why
        the same relationship looked different on different tabs."""
        anon = '<div style={{ borderTop: "1px solid var(--border)" }} />'
        for tab, block in _tab_blocks().items():
            if tab == "about":
                continue
            self.assertNotIn(anon, block,
                             "%s tab still separates sections with an unnamed rule" % tab)

    def test_every_section_sits_under_a_heading(self):
        """A tab is a list of named clusters. A section that appears before any
        heading belongs to no group, which is the state this replaced."""
        for tab, block in _tab_blocks().items():
            if tab == "about":
                continue
            first_group = block.find("<GroupLabel>")
            first_section = block.find("<Section title=")
            self.assertNotEqual(first_group, -1, "%s tab has no cluster heading" % tab)
            self.assertLess(first_group, first_section,
                            "%s tab opens with an ungrouped section" % tab)

    def test_rows_touch_and_a_continuing_run_sits_16_under_its_section(self):
        """10.0: Foot died with the stacked layout - a section's last fact is
        a row's inline subline now, so the thing to pin is the run rule:
        consecutive rows travel in one Rows run (they touch), and a run
        continuing its cluster after a Section sits 16 under it, not a full
        cluster gap away, or it would read as a new group."""
        self.assertIn("const Rows = ", SRC)
        self.assertNotIn("<Foot", SRC)
        css = re.search(r'const CSS = `(.*?)`;', SRC, re.S).group(1)
        self.assertIn(".px-set-rows--cont { margin-top: -16px; }", css)
        gap = int(re.search(r'className="px-scroll px-set".*?gap: SPACE\[(\d+)\]',
                            SRC, re.S).group(1))
        self.assertEqual(gap - 16, 16,
                         "the continuing run is not 16 under its section")


if __name__ == "__main__":
    unittest.main()
