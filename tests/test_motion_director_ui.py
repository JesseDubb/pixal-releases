"""The Animate model row splits base-first, and every Seg pairs shrink with clip.

Jesse's screenshot of the Animate fine-tune fold (brief 9.21): "10Eros Max
Beta2" and "10Eros Max Beta2 Skip Beta2" painted on top of each other, both
unreadable. Two defects compounded:

1. Pixal's hand-rolled ``Seg`` sets ``flex:1`` + ``minWidth:0`` - a shrink
   rule - with ``whiteSpace:"nowrap"`` and NO clip rule, so a long label
   spills out of its segment and over its neighbour. Lumen's SegmentedToggle
   (grid columns) cannot shrink below its content; the hand-rolled one can.
2. Worse, the MODEL row mixed two kinds of thing in one segmented track:
   base checkpoints (FL2VA, REF2VA) and community finetunes OF a base. A
   segmented control is for two to four short, known-in-advance options;
   community names are long, arbitrary, and grow with the catalog.

The fix this pins: the row picks a base first (a real segmented control of
short stock labels), then offers that base's builds - stock and finetunes -
in a picker that holds a long name and shows the selected one at rest. The
base of a finetune is provable from its chip id: the id IS the lowercase
filename stem (server ``h3_model_options``), and the stem carries "fl2va" or
"ref2va" because that token is how the file earned a chip at all. Nothing
else can prove it - ``model_profile`` files the whole family as "video", and
the scraped _civitai_models.json says base "MiniMax H3" for the one
finetune it has a hit for at all.

These are source-level assertions, the same way test_rail_vs_inline.py pins
Chat.jsx: the JSX is the contract, and a regex that stops matching IS the
regression report.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "MotionDirector.jsx").read_text(
    encoding="utf-8")


def _block(start_marker, end_marker):
    """The source from start_marker up to end_marker (both must exist)."""
    i = SRC.index(start_marker)
    j = SRC.index(end_marker, i + len(start_marker))
    return SRC[i:j]


LIB = (ROOT / "web" / "src" / "lib" / "SegmentedControl.jsx").read_text(
    encoding="utf-8")


def _lblock(start_marker, end_marker):
    """The shared segmented control's source, start_marker to end_marker."""
    i = LIB.index(start_marker)
    j = LIB.index(end_marker, i + len(start_marker))
    return LIB[i:j]


class SegClipContract(unittest.TestCase):
    """The shrink rule and the clip rule travel together (9.21, and d115203
    before it: a shrink rule without a clip rule paints text over text).
    The contract moved with the component (9.23b): it is the flex variant
    of lib/SegmentedControl.jsx now. Every pin is unchanged."""

    FLEX = _lblock("const flexStyle = ", "const gridStyle = ")
    LABEL = _lblock("<span style={{", "</span>")

    def test_segments_pair_their_shrink_rule_with_a_clip_rule(self):
        # flex:1 + minWidth:0 permits a segment to shrink below its label;
        # overflow:hidden + textOverflow:ellipsis decide what shows when it
        # does. The nowrap stays - clipping, not wrapping, is the fix.
        self.assertIn("minWidth: 0", self.FLEX)
        self.assertIn('whiteSpace: "nowrap"', self.FLEX)
        self.assertIn('overflow: "hidden"', self.FLEX,
                      "a segment that can shrink must also clip")
        self.assertIn('textOverflow: "ellipsis"', self.LABEL,
                      "a clipped label ends in an ellipsis, not a hard cut")

    def test_the_full_label_survives_in_the_title(self):
        # Clipping is only honest if hover hands the whole label back. The
        # title expression must be built from opt.label, not only from an
        # optional opt.title a caller may have filled with a description.
        m = re.search(r"const title = (.+?);", LIB, re.S)
        self.assertIsNotNone(m, "options carry no composed title at all")
        self.assertIn("opt.label", m.group(1),
                      "a clipped segment's tooltip must contain the full label")


class ModelRowSplit(unittest.TestCase):
    """Base first, then that base's finetunes - never one flat track of
    long community names (the added 9.21 brief)."""

    def test_the_model_row_never_feeds_the_whole_catalog_to_a_seg(self):
        self.assertNotRegex(SRC, r"options=\{availableModels\.map",
                            "the flat catalog is back in a segmented track")

    def test_a_finetunes_base_comes_from_its_filename_token(self):
        # modelBaseId exists and keeps the server's own precedence:
        # "ref2va" is tested before "fl2va" (h3_model_variant, 9.0 trap #6 -
        # a stem naming both lands in ref2va, deterministically).
        body = _block("const modelBaseId = ", "return null;")
        self.assertLess(body.index('"ref2va"'), body.index('"fl2va"'),
                        "ref2va must win when a stem carries both tokens")

    def test_the_base_track_draws_only_from_base_groups(self):
        # The segmented control left in the model row lists base families
        # (short stock labels: FL2VA / REF2VA), never the finetunes.
        self.assertIn("const groupModels = ", SRC)
        self.assertRegex(SRC, r"options=\{modelGroups\.map",
                         "the base track is not fed by the base groups")

    def test_finetunes_pick_from_a_list_that_holds_a_long_name(self):
        # The picker shows the selected build's full label at rest (the
        # trigger clips with an ellipsis and keeps the whole label in its
        # title), and its option rows do the same.
        block = _block("const ModelPicker = ", "const ENGINE_ICONS")
        self.assertIn('textOverflow: "ellipsis"', block)
        self.assertIn('whiteSpace: "nowrap"', block)
        self.assertRegex(block, r"title=\{[^}]*\.label",
                         "the full build name must survive in a title")
        self.assertIn("listbox", block,
                      "the picker is a listbox, not a segmented track")

    def test_the_model_row_uses_the_split(self):
        row = _block('{availableModels.length > 1 && (', "</Row>")
        self.assertIn("<ModelPicker", row,
                      "the model row has no long-name picker")
        if "<SegmentedControl" in row:
            self.assertIn("modelGroups.map", row,
                          "a segmented track in the model row may only list base groups")

    def test_the_short_cases_keep_their_segmented_tracks(self):
        # The regression guard the other way: 5s/10s/15s, engines, frame
        # rates and speed recipes are short and known in advance - they are
        # what a segmented control is FOR and must not be displaced.
        self.assertRegex(SRC, r"options=\{lengths\.map")
        self.assertRegex(SRC, r"options=\{engines\.map")
        self.assertRegex(SRC, r"options=\{fpsChoices\.map")
        self.assertRegex(SRC, r"options=\{speedModes\.map")


class ShotsCaption(unittest.TestCase):
    """The --- scripting trick is a how, not a what: it lives in an InfoTip,
    not in the caption every user reads (brief 9.17's prose rule, applied
    in the same fold)."""

    def test_the_single_take_caption_is_a_clause(self):
        self.assertIn("one continuous take", SRC)
        self.assertNotIn("or separate shots with ---", SRC,
                         "the tutorial is back under the control")

    def test_the_script_trick_lives_in_an_infotip(self):
        self.assertIn('from "./InfoTip.jsx"', SRC)
        m = re.search(r"InfoTip[^>]*text=\{([\"'])(?:(?!\1).)*---", SRC, re.S)
        self.assertIsNotNone(m, "no InfoTip carries the --- script guidance")


if __name__ == "__main__":
    unittest.main()
