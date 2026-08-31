"""Brief 9.73 — Settings' two edit-lane pickers become the shared Picker.

9.70 (fe0f939) moved the chat-brain pick onto lib/Picker.jsx; the Edit
model section's whole-frame and masked-area lanes were the follow-up,
still on this panel's bespoke ScrollPicker. Two controls for one job is
the defect, and the shared one is the survivor.

Static, in the test_brain_picker.py style (this repo has no JS runtime):
editLaneOptions' mapping onto Picker's [{ id, label, description?, group? }]
contract (the family folder stays `group`; the too-heavy advisory rides the
description because Picker rows have no per-row tooltip and the filter
searches label + description), the "recipe default" clear row as a real
option with id "", the unchanged apply payloads and toasts, and the ghost
that finally matches the trigger's own 28px box.

ScrollPicker is NOT deleted: four rows still use it (video default, VAE,
upscale, reviewer), so the brief's no-ScrollPicker assertion holds inside
the Edit model section, and the file-wide count pins the survivors.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx") \
    .read_text(encoding="utf-8")
PICKER = (ROOT / "web" / "src" / "lib" / "Picker.jsx").read_text(encoding="utf-8")

# The Edit model section: from its heading to the H3 models section (9.91)
# that follows it - the "finishing" group label used to be the bound. The
# VAE ScrollPicker sits just ABOVE the heading and the upscale one below
# the label - neither is this brief's control.
EDIT = SRC.split("<Section title={<>Edit model", 1)[1] \
          .split("<Section title={<>MiniMax H3", 1)[0]

# The MiniMax H3 section: 9.91's two model pickers plus 9.94's text encoder,
# all on the same shared-Picker contract this file polices and the same 28px
# ghost box. The encoder moved here from VRAM profile on 2026-08-31 - Jesse,
# "I want the option in settings under minimax": the two build rows and the
# encoder row all answer what an H3 render loads, and a MiniMax setting filed
# under a global VRAM list is a setting nobody finds.
H3 = SRC.split("<Section title={<>MiniMax H3", 1)[1] \
        .split("<GroupLabel>finishing</GroupLabel>", 1)[0]


class SharedPickerTests(unittest.TestCase):

    def test_both_edit_fields_render_the_shared_picker(self):
        self.assertEqual(EDIT.count("<Picker"), 2)
        self.assertIn('label="whole frame edit model"', EDIT)
        self.assertIn('label="masked area edit model"', EDIT)
        self.assertIn('value={editCfg.model || ""}', EDIT)
        self.assertIn('value={editCfg.inpaint_model || ""}', EDIT)

    def test_the_edit_section_renders_no_scrollpicker(self):
        self.assertNotIn("<ScrollPicker", EDIT)
        self.assertNotIn("onPick={", EDIT)
        self.assertNotIn("emptyLabel=", EDIT)


class MappingTests(unittest.TestCase):
    """editLaneOptions onto [{ id, label, description?, group? }]: id is the
    raw build name the pick posts (the server payload is unchanged), label
    the pretty name plus the GB run, the too-heavy advisory the description
    line, and group the 9.44 family folder."""

    def test_edit_lane_options_emit_the_picker_shape(self):
        self.assertIn("id: e.name", SRC)
        self.assertNotIn("name: e.name", SRC)  # ScrollPicker's key is gone
        self.assertIn("label: `${prettyModel(e.name)}", SRC)

    def test_the_too_heavy_advisory_rides_the_description(self):
        self.assertIn("description: `larger than this card's", SRC)
        self.assertIn("it will offload and run slowly`", SRC)
        self.assertNotIn("title: heavy", SRC)  # Picker rows have no tooltip

    def test_the_family_grouping_survives_as_group(self):
        self.assertIn("...(group ? { group } : {})", SRC)
        self.assertIn('familyName("qwen_edit")', EDIT)
        self.assertIn('familyName("klein")', EDIT)

    def test_recipe_default_is_an_option_with_an_empty_id(self):
        # Picker has no emptyLabel clear row; value "" matches this option,
        # so the trigger reads "recipe default" - the same meaning as before
        self.assertEqual(EDIT.count('{ id: "", label: "recipe default" }'), 2)
        self.assertIn('placeholder="recipe default"', EDIT)


class PickContractTests(unittest.TestCase):
    """onChange(name) does exactly what onPick(name) did: same state writes,
    same apply payloads, same toasts."""

    def test_the_whole_frame_pick_posts_the_same_payload(self):
        self.assertIn("setEditCfg({ ...editCfg, model: name })", EDIT)
        self.assertIn("apply({ edit: { model: name } },", EDIT)
        self.assertIn('"edit model applied" : "recipe default restored"',
                      EDIT)

    def test_the_masked_pick_posts_the_same_payload(self):
        self.assertIn("setEditCfg({ ...editCfg, inpaint_model: name })", EDIT)
        self.assertIn("apply({ edit: { inpaint_model: name } },", EDIT)
        self.assertIn('"masked edit model applied" : "recipe default restored"',
                      EDIT)


class GhostTests(unittest.TestCase):


    def test_the_ghost_is_the_triggers_own_box(self):
        # the shared trigger is a fixed 28px; the loading hold finally
        # matches it instead of PickerGhost's 38px ScrollPicker stand-in
        self.assertIn("height: 28", PICKER)
        self.assertEqual(EDIT.count("<Bar h={28} />"), 2)
        self.assertNotIn("<PickerGhost", EDIT)


class H3PickerTests(unittest.TestCase):
    """9.91's two H3 model rows: the same shared Picker, the same ghost
    box, and an explicit Automatic option that names what it resolves to."""

    def test_both_h3_fields_render_the_shared_picker(self):
        # three rows since the encoder joined them: two builds, one encoder
        self.assertEqual(H3.count("<Picker"), 3)
        self.assertIn('label="Reference model"', H3)
        self.assertIn('label="First/last-frame model"', H3)
        self.assertIn('value={h3Cfg.ref_model || ""}', H3)
        self.assertIn('value={h3Cfg.fl_model || ""}', H3)

    def test_the_h3_section_renders_no_scrollpicker(self):
        self.assertNotIn("<ScrollPicker", H3)
        self.assertNotIn("onPick={", H3)

    def test_the_h3_picks_post_the_slot_payloads(self):
        self.assertIn("setH3Cfg({ ...h3Cfg, ref_model: name })", H3)
        self.assertIn("apply({ h3: { ref_model: name } },", H3)
        self.assertIn("setH3Cfg({ ...h3Cfg, fl_model: name })", H3)
        self.assertIn("apply({ h3: { fl_model: name } },", H3)

    def test_automatic_is_a_real_option_that_names_its_resolution(self):
        # value "" matches it, so the trigger reads what Automatic resolves
        # to - the screen never hides the actual answer (9.91's whole point)
        self.assertIn('id: "",', SRC)
        self.assertIn('label: resolved ? `Automatic — ${resolved.label}` : "Automatic"',
                      SRC)
        self.assertIn('placeholder="Automatic"', H3)

    def test_a_stale_pick_stays_listed_and_says_automatic_is_running(self):
        self.assertIn("side.stale && stored", SRC)
        self.assertIn("missing, running Automatic", SRC)

    def test_the_h3_ghost_is_the_triggers_own_box(self):
        self.assertEqual(H3.count("<Bar h={28} />"), 3)
        self.assertNotIn("<PickerGhost", H3)


# The VRAM profile section: from its heading to Model folders. The encoder
# row USED to live here and no longer does - the assertion below is what
# keeps it from drifting back.
VRAM = SRC.split("<Section title={<>VRAM profile", 1)[1] \
          .split('<Section title="Model folders"', 1)[0]


class H3TextEncoderTests(unittest.TestCase):
    """9.94's text encoder row: the same shared Picker and 28px ghost box,
    seated with the H3 build slots, posting the h3.text_encoder payload."""

    def test_the_row_renders_the_shared_picker(self):
        self.assertIn('label="Text encoder"', H3)
        self.assertIn('value={h3Cfg.text_encoder || ""}', H3)
        self.assertIn("options={h3EncoderOptions(h3Cfg)}", H3)
        self.assertNotIn("<ScrollPicker", H3)

    def test_it_is_seated_under_minimax_not_under_vram(self):
        # Jesse, 2026-08-31: "I want the option in settings under minimax".
        # VRAM profile keeps its own controls and gains no model pickers.
        self.assertEqual(VRAM.count("<Picker"), 0)
        self.assertNotIn("text_encoder", VRAM)

    def test_the_pick_posts_the_slot_payload(self):
        self.assertIn("setH3Cfg({ ...h3Cfg, text_encoder: id })", H3)
        self.assertIn("apply({ h3: { text_encoder: id } },", H3)

    def test_automatic_names_the_32b_and_every_option_says_its_cost(self):
        # the row is a VRAM control: the size is the point, so Automatic's
        # label and every pair's label carry the encoder's weight
        self.assertIn('label: `Automatic — ${auto.label || "Qwen3-VL 32B"}${gb(auto.size)}`',
                      SRC)
        self.assertIn("label: `${o.label}${gb(o.size)}`", SRC)

    def test_a_stale_pick_stays_listed_and_says_automatic_is_running(self):
        self.assertIn("row.stale && stored", SRC)
        self.assertIn("missing, running Automatic", SRC)

    def test_the_ghost_is_the_triggers_own_box(self):
        self.assertEqual(VRAM.count("<Bar h={28} />"), 0)
        self.assertNotIn("<PickerGhost", H3)


class RetentionTests(unittest.TestCase):
    """The brief's delete-if-unused condition is not met: four rows keep
    ScrollPicker and their gates keep PickerGhost, so both stay."""

    def test_scrollpicker_survives_for_the_other_four_rows(self):
        # video default, VAE, upscale, reviewer
        self.assertIn("const ScrollPicker", SRC)
        self.assertIn("const PickRow", SRC)
        self.assertEqual(SRC.count("<ScrollPicker"), 4)
        self.assertIn('placeholder="first available"', SRC)
        self.assertIn('placeholder="stock Z-Image VAE (recommended)"', SRC)
        self.assertIn("choose local upscale model…", SRC)
        self.assertIn("choose a reviewer model…", SRC)

    def test_pickerghost_survives_for_the_same_four_gates(self):
        self.assertEqual(SRC.count("<PickerGhost />"), 4)

    def test_picker_jsx_is_untouched(self):
        # the brief forbids touching Picker.jsx; its documented contract
        # and its 28px trigger still read as they did for 9.70
        self.assertIn("[{ id, label, description?, group? }]", PICKER)
        self.assertIn("height: 28", PICKER)


if __name__ == "__main__":
    unittest.main()
