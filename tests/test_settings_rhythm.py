"""Settings groups use cards, a comfortable minimum row and one reading inset.

The shared rail remains 26px; the compact 34px row used elsewhere is unchanged.
The workspace has explicit nested groups, not negative-margin sibling rules.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")
TOKENS = (ROOT / "web" / "src" / "lib" / "design-tokens.js").read_text(encoding="utf-8")


def _table(name):
    """The numeric entries of `export const NAME = { ... };` in the tokens."""
    body = re.search(r"export const %s = \{(.*?)\};" % name, TOKENS, re.S).group(1)
    return {k: int(v) for k, v in re.findall(r"^\s*(\w+):\s*(\d+),", body, re.M)}


HEIGHT = _table("HEIGHT")
RHYTHM = _table("RHYTHM")
WORKSPACE = (ROOT / "web/src/components/SettingsWorkspace.jsx").read_text(encoding="utf-8")
LAYOUT = (ROOT / "web/src/lib/settings-layout.js").read_text(encoding="utf-8")
CSS = WORKSPACE.split("export const SETTINGS_CSS = `", 1)[1]


def _tab_blocks():
    marks = list(re.finditer(r'\{tab === "(\w+)" &&', SRC))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(SRC)
        out[m.group(1)] = SRC[m.start():end]
    return out


class SettingsRhythm(unittest.TestCase):

    def test_the_panel_names_its_reading_rhythm(self):
        self.assertIn("min-height:${SETTINGS.row}px", CSS)
        self.assertIn("padding:${SETTINGS.inset}px", CSS)
        self.assertIn("gap:${SETTINGS.groupGap}px", CSS)
        self.assertIn("gap:${SETTINGS.cardGap}px", CSS)
        self.assertIn("row: 44", LAYOUT)
        self.assertIn("inset: 24", LAYOUT)
        self.assertIn("groupGap: 28", LAYOUT)
        self.assertIn("cardGap: 12", LAYOUT)

    def test_the_tokens_hold_the_rhythm_jesse_asked_for(self):
        """Rows touch (the row IS the gap); 8 under a sub label; 16 under a
        break and above a continuing run; 32 between sub-sections; 56 above a
        break. Each grouping step is twice the one below it - the original
        defect was 20 against 10, which reads as nothing."""
        self.assertEqual(HEIGHT["row"], 34)
        self.assertEqual((RHYTHM["rows"], RHYTHM["run"], RHYTHM["cluster"], RHYTHM["break"]),
                         (8, 16, 32, 56))
        self.assertEqual(RHYTHM["run"], RHYTHM["rows"] * 2)
        self.assertEqual(RHYTHM["cluster"], RHYTHM["run"] * 2)
        for value in (RHYTHM["rows"], RHYTHM["run"], RHYTHM["cluster"], RHYTHM["break"]):
            self.assertEqual(value % 8, 0, "the rhythm left the 8pt grid")

    def test_a_cluster_heading_belongs_to_what_is_under_it(self):
        self.assertIn('<section className="px-settings-group"', WORKSPACE)
        self.assertIn("{group.heading}", WORKSPACE)
        self.assertIn('className="px-settings-group-body"', WORKSPACE)
        self.assertIn("gap:12px", CSS)
        self.assertNotIn("margin-top: -", CSS)

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
            if first_section == -1:
                continue          # a break whose sub-sections need no name
            self.assertLess(first_group, first_section,
                            "%s tab opens with an ungrouped section" % tab)

    def test_rows_travel_in_a_card_without_per_row_separators(self):
        self.assertIn("const Rows = ", SRC)
        self.assertNotIn("<Foot", SRC)
        self.assertIn(".px-settings-group-body > .px-set-rows", CSS)
        self.assertNotIn(".px-setting + .px-setting", CSS)
        self.assertNotIn("px-set-rows--cont", SRC)


if __name__ == "__main__":
    unittest.main()
