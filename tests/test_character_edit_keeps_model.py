"""Brief 9.97 — editing a character stops resetting the model pick.

Jesse, 2026-09-01: "when I changed the ref image of Zara it reset my model
selection! ... I don't want this auto stuff happening". Saving the character
form - even a pure ref-image swap on the ALREADY active anchor - re-ran
`selectCharacter`, whose identity_edit heal cleared a picked MiniMax H3
model and flipped the lane off the H3 ref path. Two fixes, pinned
statically in the test_composer_canvas.py style (this repo has no JS test
runner, so the contracts assert the structure of the source; see
test_h3_ref_still.py's ClientRoutingTests for the store.js precedent):

1. Chat.jsx's CharacterForm `onSaved` skips `selectCharacter` when the saved
   id is already the active character - an edit of the active anchor is not
   a new selection. The `await store.loadOptions()` stays: it refreshes
   `ref_rev`, and `reconcileOpts` keeps a still-valid character untouched.
2. store.js's `selectCharacter` learns the 9.67 exception: a picked MiniMax
   H3 build is itself an identity carrier (the anchor's photo rides H3's own
   reference input, never identity_edit), so the model stays and the
   identity_edit availability gate does not apply. Every other model keeps
   today's heal exactly, and the patch no longer pre-empts
   `withExecutionRecipe`'s own engine assignment.

The two behaviour classes were proven RED against the pre-fix tree. The
heal guard passes on both trees; its teeth were proven by mutation
(deleting the clear in `identityCompatibleSelections` fails it).
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = (ROOT / "web" / "src" / "store.js").read_text(encoding="utf-8")
CHAT = (ROOT / "web" / "src" / "components" / "Chat.jsx").read_text(encoding="utf-8")


def _select_character(src=STORE):
    """The selectCharacter method, opening line to the next method."""
    start = src.index("selectCharacter(id) {")
    end = src.index("selectIdentityReference(file) {", start)
    return src[start:end]


def _identity_compatible(src=STORE):
    """The identityCompatibleSelections helper, whole body."""
    start = src.index("function identityCompatibleSelections")
    end = src.index("return { model };", start) + len("return { model };")
    return src[start:end]


def _character_on_saved(src=CHAT):
    """The CharacterForm's onSaved callback in Chat.jsx."""
    form = src.index("<CharacterForm")
    start = src.index("onSaved={async (id) => {", form)
    end = src.index("}} />", start)
    return src[start:end]


class EditGuardTests(unittest.TestCase):
    """Accept 1: saving the ACTIVE anchor never re-runs selection."""

    def test_on_saved_skips_select_character_for_the_active_anchor(self):
        body = _character_on_saved()
        # loadOptions stays - it refreshes ref_rev so thumbnails and the
        # identity pill update through reconcileOpts, which keeps a
        # still-valid character untouched.
        self.assertIn("await store.loadOptions();", body)
        # The guard: an edit of the active anchor is not a selection, so a
        # picked MiniMax H3 model survives the save. Only a save of a
        # DIFFERENT character selects it.
        self.assertIn("store.opts.character !== id", body)
        self.assertLess(
            body.index("store.opts.character !== id"),
            body.index("store.selectCharacter(id)"),
            "the active-anchor guard must precede the selection call")


class H3CarryTests(unittest.TestCase):
    """Accept 2: an H3 pick is an identity carrier; selectCharacter keeps it."""

    def test_select_character_carries_a_minimax_h3_pick(self):
        body = _select_character()
        # The 9.67 exception inside selectCharacter, keyed on the CURRENTLY
        # picked model's family via options.model_meta...
        self.assertIn('family === "minimax_h3"', body)
        self.assertIn("[state.opts.model]", body)
        # ...sitting before the heal's spread can clear the model...
        self.assertLess(
            body.index('family === "minimax_h3"'),
            body.index("...compatible"),
            "the H3 branch must precede the heal spread")
        # ...and carrying the pick explicitly through the patch.
        self.assertIn("{ model: state.opts.model }", body)

    def test_the_non_h3_path_keeps_the_identity_heal(self):
        body = _select_character()
        # Any other model keeps today's heal exactly: the carrier test is a
        # ternary whose else branch is the identity_edit compatibility clear.
        self.assertRegex(
            body,
            r'family === "minimax_h3"\s*\?\s*\{ model: state\.opts\.model \}'
            r"\s*:\s*identityCompatibleSelections\(options\)",
            "the non-H3 path no longer routes through "
            "identityCompatibleSelections")

    def test_no_unconditional_identity_engine_remains_in_the_patch(self):
        body = _select_character()
        # withExecutionRecipe assigns engine on every character path (the h3
        # lane via activeRecipeId, identity_edit otherwise), so the patch
        # must not pre-empt it with a hardcoded lane.
        self.assertNotIn('engine: "identity_edit"', body)


class HealGuardTests(unittest.TestCase):
    """Accept 3: the heal itself is unchanged. Passes on both trees; teeth
    proven by mutation (the clear in identityCompatibleSelections was
    deleted, this class failed, the clear was restored)."""

    def test_the_heal_still_clears_a_model_that_cannot_run_identity_edit(self):
        body = _identity_compatible()
        self.assertIn(
            'modelSupportsRecipe(state.opts.model, "identity_edit", options)',
            body)
        self.assertIn('? state.opts.model : ""', body,
                      "the clear is gone - an incompatible model now survives")

    def test_an_unavailable_identity_recipe_still_refuses_the_selection(self):
        body = _identity_compatible()
        self.assertIn("if (!identity?.available) return null;", body)
        # ...which selectCharacter turns into the "could not be selected"
        # notice (on the non-H3 path - the H3 lane needs no such recipe).
        self.assertIn("if (!character?.has_ref || !compatible) return false;",
                      _select_character())


if __name__ == "__main__":
    unittest.main()
