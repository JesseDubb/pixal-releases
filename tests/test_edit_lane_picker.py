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

# The Edit model section: from its heading to the "finishing" group label
# (the Upscaler section). The VAE ScrollPicker sits just ABOVE the heading
# and the upscale one below the label - neither is this brief's control.
EDIT = SRC.split("<Section title={<>Edit model", 1)[1] \
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
