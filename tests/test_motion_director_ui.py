"""The Animate popup is ONE panel (9.32), and every Seg pairs shrink with clip.

Brief 9.32 (Jesse: "Can you make the animate popup not so ugly and
disorganized looking?") found the expanded dialog was three layouts stacked:
Zone 2's labels sat ABOVE their controls while the fold's sat LEFT; the
control column broke at SHOTS (a floating stepper) and END FRAME (a two-row
thumbnail grid); MODEL was two controls for one choice (an FL2VA/REF2VA
segmented track above a dropdown that also read "FL2VA"); the SPEED hint
printed a sampler id (``res_multistep``) on screen; the LoRA chain was the
only bordered card in the dialog; and at 958px tall the footer scrolled out
of reach in a windowed Pixal.

The contract this file pins after the fix:

- ONE label system: engine and length are ``Row``s on the fold's grid, at
  the fold's row height (``size="sm"``).
- MODEL is ONE control: the dropdown names the choice and holds a long
  build name; the family track is gone. The 9.21 grouping survives as the
  picker's ORDER - a finetune's base is still provable from its chip id
  (the id IS the lowercase filename stem, server ``h3_model_options``), so
  ``groupModels`` orders the list stock-first per base.
- END FRAME is one scrollable row of thumbnails, ``none`` pill first.
- The SPEED hint speaks English; the sampler id lives in tooltips.
- The shell's header and footer pin; the body scrolls (StyleForm's
  ``px-dialog-body`` recipe), so the commitment is always reachable.

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


class ModelRowOneControl(unittest.TestCase):
    """MODEL is ONE control (9.32-C): the dropdown names the choice and holds
    a long build name, so the FL2VA/REF2VA family track above it could only
    repeat it - and repeated it in a shape that cannot hold a community
    finetune name (DESIGN.md §3: 2-4 short, known-in-advance options). The
    9.21 base grouping survives as the picker's ORDER."""

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

    def test_the_picker_is_fed_in_base_group_order(self):
        # groupModels still runs; its groups flatten into the picker's feed,
        # stock build first inside each base, the baseless at the end.
        self.assertIn("const groupModels = ", SRC)
        self.assertRegex(SRC, r"flatMap\(\(g\) => g\.models\)",
                         "the picker no longer lists each base's builds together")

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

    def test_the_model_row_is_one_control(self):
        row = _block('{availableModels.length > 1 && (', "</Row>")
        self.assertIn("<ModelPicker", row,
                      "the model row has no long-name picker")
        self.assertNotIn("<SegmentedControl", row,
                         "the family track is back beside the dropdown - "
                         "two controls for one choice, both saying FL2VA")
        self.assertIn("modelOptions", row,
                      "the picker is not fed the base-ordered list")

    def test_the_short_cases_keep_their_segmented_tracks(self):
        # The regression guard the other way: 5s/10s/15s, engines, frame
        # rates and speed recipes are short and known in advance - they are
        # what a segmented control is FOR and must not be displaced.
        self.assertRegex(SRC, r"options=\{lengths\.map")
        self.assertRegex(SRC, r"options=\{engines\.map")
        self.assertRegex(SRC, r"options=\{fpsChoices\.map")
        self.assertRegex(SRC, r"options=\{speedModes\.map")


class OneLabelSystem(unittest.TestCase):
    """Zone 2 sits on the fold's Row grid (9.32-A): labels LEFT in the same
    92px column, controls starting at the same x - the fold is a
    continuation of the panel, not a second layout stacked on top of it."""

    def test_engine_and_length_are_rows_now(self):
        self.assertIn('<Row label="engine"', SRC)
        self.assertRegex(SRC, r"<Row label=\{activeShots > 1",
                         "the length row left the grid")

    def test_zone2_has_no_label_above_control_layout_left(self):
        zone = _block("{/* ZONE 2", "{/* ZONE 3")
        self.assertNotIn('gridTemplateColumns: "1fr 1fr"', zone,
                         "the two-column label-above layout is back")
        self.assertNotIn("<span style={MICRO}>", zone,
                         "a bare micro label above a control is back in zone 2")

    def test_zone2_tracks_are_the_fold_row_height(self):
        zone = _block("{/* ZONE 2", "{/* ZONE 3")
        self.assertEqual(zone.count('size="sm"'), 2,
                         "zone 2's tracks must match the fold's row height")


class SpeedHintPlain(unittest.TestCase):
    """The SPEED hint says what the mode does in English (9.32-E). The
    sampler id is a code word - the same class of leak plain_render_words
    scrubbed from the chat lane - and lives in tooltips only."""

    def test_the_hint_never_prints_the_sampler_id(self):
        self.assertNotIn("${speedMode.gloss} · ${speedMode.sampler}", SRC,
                         "the sampler id is back on screen")

    def test_the_id_survives_in_tooltips(self):
        # The row's title carries the active mode's sampler; each segment's
        # title already carries its own.
        self.assertIn("sampler: ${speedMode.sampler}", SRC)
        self.assertIn("${m.gloss}, ${m.sampler}", SRC)


class EndFrameOneRow(unittest.TestCase):
    """The end-frame strip is ONE row that scrolls sideways (9.32-B); the
    two-row thumbnail grid was the loudest rhythm break in the fold."""

    def test_the_strip_never_wraps(self):
        row = _block('<Row label="end frame"', "</Row>")
        self.assertIn('flexWrap: "nowrap"', row)
        self.assertIn('overflowX: "auto"', row)


class ShellFitsAWindow(unittest.TestCase):
    """Header and footer pin; the body scrolls (9.32-F) - 958px of dialog
    never puts the commitment out of reach in a windowed Pixal."""

    def test_the_shell_itself_never_scrolls(self):
        box = _block("boxStyle={{", "}}>")
        self.assertIn('overflow: "hidden"', box)
        self.assertNotIn('overflowY: "auto"', box,
                         "the whole shell scrolls again - the footer can "
                         "scroll out of reach")

    def test_the_body_is_the_scrolling_region(self):
        self.assertIn('className="px-scroll px-dialog-body"', SRC)


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


class SparseAttentionRow(unittest.TestCase):
    """The attention row: on by default, and only where the pack exists.

    "can you do anything to make this a toggle in the minimax h3 section of
    the app?" / "on by default" / "if its installed" (Jesse, 2026-08-23).
    """

    def test_the_row_only_exists_when_the_server_says_the_node_does(self):
        self.assertIn("{activeEngine?.sparse && (", SRC)

    def test_it_starts_on(self):
        self.assertIn("useState(true)", _block("const [sparse", "const speedModes"))

    def test_it_is_the_shared_segmented_control_not_a_new_switch(self):
        row = _block("{activeEngine?.sparse && (", "showVideoLoraChain")
        self.assertIn("<SegmentedControl", row)
        self.assertIn('value={sparse ? "sparse" : "dense"}', row)

    def test_turning_it_off_is_narrated_on_the_collapsed_fold(self):
        # Every other non-default lands in `tweaks`; an accelerator the user
        # switched off is exactly what a folded summary is for.
        self.assertIn('tweaks.push("dense attention")', SRC)

    def test_the_choice_reaches_the_render(self):
        self.assertIn("activeEngine.sparse ? sparse : undefined", SRC)


class Upscale2xRow(unittest.TestCase):
    """The 2x upscale row: opens on the Settings default (9.31), and only
    where the server says the pack AND its 659 MB upscaler weights exist.

    "OMG put the 2x upscale in this version!" (Jesse, 2026-08-23). Opt-in
    out of the box because it ~triples the render's time - measured 140s ->
    464s on a 928x1120, 124-frame take - and it rides inside the render job:
    Pixal does not store latents, so it can never be an action on a finished
    clip. 9.31 made the opening position a standing Settings default, which
    the server flags on the one engine that has the row - a flip here still
    stays per-clip.
    """

    def test_the_row_only_exists_when_the_server_says_it_can_run(self):
        self.assertIn("{activeEngine?.upscale_2x && (", SRC)

    def test_the_opening_position_comes_from_settings_not_a_literal(self):
        # 9.31: the literal false is gone. The configured default rides
        # video_engine_options as a flag on the h3 engine - the same way
        # default_engine travels - gated on the row being able to run at all.
        block = _block("const [upscale", "const speedModes")
        self.assertNotIn("useState(false)", block,
                         "the hardcoded OFF is back - the Settings default is ignored")
        self.assertIn("item.upscale_2x_default && item.upscale_2x", block)

    def test_it_is_the_shared_segmented_control_not_a_new_switch(self):
        # DESIGN.md: never hand-roll a control.
        row = _block("{activeEngine?.upscale_2x && (", "showVideoLoraChain")
        self.assertIn("<SegmentedControl", row)
        self.assertIn('value={upscale ? "2x" : "off"}', row)

    def test_the_hint_says_what_it_costs_and_where_it_runs(self):
        # "~3x longer" is the honest number (measured 140s -> 464s), and the
        # lane is an option on the render, not an action on a finished clip.
        row = _block("{activeEngine?.upscale_2x && (", "showVideoLoraChain")
        self.assertIn("~3x longer", row)
        self.assertIn("inside this render", row)

    def test_turning_it_on_is_narrated_on_the_collapsed_fold(self):
        # Every other non-default lands in `tweaks`; an expensive option the
        # user switched ON is exactly what a folded summary is for.
        self.assertIn('tweaks.push("2x upscale")', SRC)

    def test_the_choice_reaches_the_render(self):
        self.assertIn("activeEngine.upscale_2x ? upscale : undefined", SRC)


if __name__ == "__main__":
    unittest.main()
