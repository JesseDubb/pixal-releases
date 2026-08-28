"""Brief 9.70 — the chat-brain model pick is the shared Picker.

Jesse (2026-08-27), looking at the composer sampler card's dropdown: "the
chat brain selection should use this same dropdown. Not a custom one." The
Brain tab's Local lane grew a bespoke scrolling row list before
lib/Picker.jsx existed (lifted out of MotionDirector 2026-08-26); two
controls for one job is the defect, and the shared one is the survivor.

Static, in the test_lora_card_controls.py style (this repo has no JS
runtime): the mapping onto Picker's [{ id, label, description? }] contract,
the unchanged apply payload and toast, the ghost that finally matches the
trigger's own box, and the retirement of the bespoke list (MiniChip and the
scroll-into-view ref went with it - nothing else used them). The edit-lane
ScrollPickers followed in 9.73; ScrollPicker itself stays for the rest.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx") \
    .read_text(encoding="utf-8")
PICKER = (ROOT / "web" / "src" / "lib" / "Picker.jsx").read_text(encoding="utf-8")

# The Chat brain section: from its heading to the next section (9.60's
# Official prompting). The reviewer ScrollPicker sits further down the tab
# and is NOT this brief's control.
CHAT_BRAIN = SRC.split("<Section title={<>Chat brain", 1)[1] \
               .split("<Section title={<>Official prompting", 1)[0]


class SharedPickerTests(unittest.TestCase):

    def test_settings_imports_the_shared_picker(self):
        self.assertIn('import { Picker } from "../lib/Picker.jsx";', SRC)

    def test_the_chat_brain_section_renders_the_picker(self):
        self.assertIn("<Picker", CHAT_BRAIN)
        self.assertIn('label="Local brain model"', CHAT_BRAIN)
        self.assertIn("value={localModel}", CHAT_BRAIN)

    def test_the_chat_brain_section_renders_no_scrollpicker(self):
        self.assertNotIn("<ScrollPicker", CHAT_BRAIN)


class MappingTests(unittest.TestCase):
    """localList's row shape onto [{ id, label, description? }]: id is the
    gguf path the row's onClick posted, label the pretty title, and the
    VISION / NSFW chips ride the description so the Picker's filter (which
    searches label + description) still finds them."""

    def test_options_come_from_local_list(self):
        self.assertIn("options={localList.map((m) => ({", CHAT_BRAIN)
        self.assertIn("id: m.path", CHAT_BRAIN)
        self.assertIn("label: m.title || m.name", CHAT_BRAIN)

    def test_the_description_carries_the_chips_and_the_meta_run(self):
        self.assertIn('m.vision && "VISION"', CHAT_BRAIN)
        self.assertIn('m.nsfw && "NSFW"', CHAT_BRAIN)
        self.assertIn("m.quant, m.size_gb", CHAT_BRAIN)
        self.assertIn('.join(" · ")', CHAT_BRAIN)


class PickContractTests(unittest.TestCase):
    """onChange(id) does exactly what the row's onClick did: same state
    write, same apply payload, same toast."""

    def test_the_pick_posts_the_local_brain_payload(self):
        self.assertIn("setLocalModel(id)", CHAT_BRAIN)
        self.assertIn("apply({ llm: { base_url: LOCAL_URL, model: \"local\",",
                      CHAT_BRAIN)
        self.assertIn("local_model: id } }", CHAT_BRAIN)

    def test_the_toast_is_unchanged(self):
        self.assertIn('"model applied - loads on your next message"', CHAT_BRAIN)

    def test_the_empty_state_copy_survives(self):
        self.assertIn("no .gguf chat models found in your model folders",
                      CHAT_BRAIN)


class GhostTests(unittest.TestCase):

    def test_the_ghost_is_the_triggers_own_box(self):
        # the shared trigger is a fixed 28px; the loading hold finally
        # matches it instead of the list's one-36px-row stand-in
        self.assertIn("height: 28", PICKER)
        self.assertIn("<Bar h={28} />", CHAT_BRAIN)
        self.assertNotIn("h={36}", CHAT_BRAIN)


class RetirementTests(unittest.TestCase):

    def test_the_bespoke_list_is_gone(self):
        self.assertNotIn("scrolledSel", SRC)
        self.assertNotIn("scrollIntoView", SRC)
        self.assertNotIn("MiniChip", SRC)
        self.assertNotIn("maxHeight: 246", SRC)

    def test_scrollpicker_survives_for_the_other_four_rows(self):
        # video default, VAE, upscale, reviewer - the edit lanes moved to
        # the shared Picker in 9.73; do NOT delete ScrollPicker until the
        # remaining four move too
        self.assertIn("const ScrollPicker", SRC)
        self.assertEqual(SRC.count("<ScrollPicker"), 4)
        self.assertIn("choose a reviewer model…", SRC)


if __name__ == "__main__":
    unittest.main()
