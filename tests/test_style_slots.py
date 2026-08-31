"""9.77: style prompt slots - {subject} / {outfit top} become fields, not file edits.

A saved style whose prompt_prefix / prompt_tail carry {slot} tokens declares
those slots (a `slots` map, or inferred from the tokens when the map is
absent). The composer shows one field per slot while the style is selected,
the fills ride the chat/reroll body as `style_slots`, and _apply_opts renders
them into the frame where 9.72 hands the frame to the builders: a fill wins,
an unfilled slot renders as its default, and a slot with neither collapses
its whole clause - "wearing {outfit top}" with nothing to wear never leaves
a dangling "wearing". See briefs/9.77-findings.md.
"""
import json
import re
import shutil
import unittest
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

_SPEC = spec_from_file_location("pixal_server", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

WEB = ROOT / "web" / "src"
STORE = (WEB / "store.js").read_text(encoding="utf-8")
COMPOSER = (WEB / "components" / "Composer.jsx").read_text(encoding="utf-8")
STYLEFORM = (WEB / "components" / "StyleForm.jsx").read_text(encoding="utf-8")


def model(rel, family, variant="any", **extra):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True, **extra}


KREA = model("Krea 2\\analogMadnessKrea2Turbo_v20.safetensors", "krea2")

PREFIX = "A photograph of one {subject} cosplaying as"
TAIL = ("close-up selfie crop, top-down, shallow depth of field on the eyes; "
        "single frontal flash; cotton wrinkles, synthetic wig fibre; "
        "wearing {outfit top}")
SLOTS = {"subject": {"label": "subject", "default": "young woman"},
         "outfit top": {"label": "outfit", "default": "a plain tee"}}


@contextmanager
def assets(entry):
    """Pretend `entry` is the only installed model, and every LoRA resolves."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(server, "resolve_model_entry",
                                         return_value=entry))
        stack.enter_context(patch.object(server, "_catalog_has", return_value=True))
        stack.enter_context(patch.object(server, "_catalog_resolve",
                                         side_effect=lambda kind, rel: rel))
        stack.enter_context(patch.object(server, "resolve_lora",
                                         side_effect=lambda name: name))
        yield


def style(**over):
    base = {"schema_version": 1, "name": "Cosplay photo", "base": "realism",
            "model": KREA["rel"]}
    base.update(over)
    return base


class SlotSchemaTests(unittest.TestCase):

    def test_declared_slots_validate_and_normalize(self):
        record = server.validate_saved_style(style(
            prompt_prefix=PREFIX, prompt_tail=TAIL,
            slots={"subject": {"label": "  subject ", "default": "young   woman"},
                   "outfit top": {"default": "a plain tee"}}))
        self.assertEqual(record["slots"], {
            "subject": {"label": "subject", "default": "young woman"},
            "outfit top": {"label": "", "default": "a plain tee"}})

    def test_rejections_name_the_field(self):
        cases = [
            (style(slots=[]), "slots must be an object"),
            (style(slots={"x": 42}), "slot 'x' must be an object"),
            (style(slots={"x": {"label": 1}}), "slot 'x': label must be a string"),
            (style(slots={"x": {"default": 1}}), "slot 'x': default must be a string"),
            (style(slots={"x": {"label": "y" * 65}}),
             "slot 'x': label is longer than 64"),
            (style(slots={"x": {"default": "y" * 601}}),
             "slot 'x': default is longer than 600"),
            (style(slots={"{bad}": {}}), "slot name '{bad}' is not a usable"),
            (style(slots={f"s{i}": {} for i in range(33)}),
             "at most 32 slots"),
        ]
        for raw, fragment in cases:
            with self.subTest(reason=fragment):
                with self.assertRaisesRegex(ValueError, re.escape(fragment)):
                    server.validate_saved_style(raw)

    def test_slots_are_inferred_from_the_frame_when_the_map_is_absent(self):
        """9.72's file shape - tokens in the text, no map - still loads, and
        its slots surface in the composer with an empty default each."""
        record = server.validate_saved_style(
            style(prompt_prefix=PREFIX + " {subject}", prompt_tail=TAIL))
        self.assertEqual(record["slots"], {
            "subject": {"label": "", "default": ""},
            "outfit top": {"label": "", "default": ""}})

    def test_a_declared_map_is_the_whole_declaration(self):
        """A map present means no inference: a token the author did not
        declare fills empty at render time, it does not grow a field."""
        record = server.validate_saved_style(style(
            prompt_prefix=PREFIX, slots={"subject": {"default": "young woman"}}))
        self.assertEqual(list(record["slots"]), ["subject"])

    def test_a_frame_without_tokens_declares_no_slots(self):
        record = server.validate_saved_style(
            style(prompt_prefix="A photograph", prompt_tail="coda"))
        self.assertNotIn("slots", record)

    def test_the_slots_survive_the_file_round_trip(self):
        with TemporaryDirectory() as td, \
                patch.object(server, "RECIPE_DIR", Path(td)):
            record = server.validate_saved_style(
                style(prompt_prefix=PREFIX, slots=SLOTS))
            server.write_saved_style(record)
            styles, problems = server.load_saved_styles()
        self.assertEqual(problems, [])
        self.assertEqual(styles[record["id"]]["slots"],
                         {name: dict(spec) for name, spec in SLOTS.items()})


class FillSlotsTests(unittest.TestCase):
    """server.fill_style_slots: the render-time half."""

    def fill(self, text, slots=None, fills=None):
        return server.fill_style_slots(text, slots, fills)

    def test_a_fill_wins_over_the_default(self):
        self.assertEqual(self.fill(PREFIX, SLOTS, {"subject": "Velma"}),
                         "A photograph of one Velma cosplaying as")

    def test_an_unfilled_slot_renders_as_its_default(self):
        self.assertEqual(self.fill("wearing {outfit top}", SLOTS, {}),
                         "wearing a plain tee")

    def test_fill_whitespace_collapses_like_the_frame_does(self):
        self.assertEqual(self.fill("wearing {outfit top}", SLOTS,
                                   {"outfit top": "  an  orange\nturtleneck "}),
                         "wearing an orange turtleneck")

    def test_an_empty_result_collapses_its_clause(self):
        """The brief's case: no fill and no default, so the wardrobe clause
        drops whole - no dangling 'wearing', the other clauses untouched."""
        bare = {name: {"label": "", "default": ""} for name in SLOTS}
        self.assertEqual(
            self.fill(TAIL, bare, {}),
            "close-up selfie crop, top-down, shallow depth of field on the "
            "eyes; single frontal flash; cotton wrinkles, synthetic wig fibre")

    def test_a_frame_that_empties_vanishes(self):
        self.assertEqual(self.fill("{subject}", {}, {}), "")
        self.assertEqual(
            self.fill("{subject}", {"subject": {"label": "", "default": ""}},
                      {"subject": "   "}),
            "")

    def test_an_undeclared_token_never_leaks_braces_into_a_caption(self):
        self.assertEqual(self.fill("a {typo} here", {}, {}), "")
        self.assertEqual(self.fill(TAIL, SLOTS, {"outfit top": "a plain tee"}),
                         TAIL.replace("{outfit top}", "a plain tee"))

    def test_fills_that_are_not_a_map_are_ignored(self):
        self.assertEqual(self.fill("wearing {outfit top}", SLOTS, 42),
                         "wearing a plain tee")

    def test_a_frame_without_tokens_passes_through(self):
        self.assertEqual(self.fill("no tokens", SLOTS, {"subject": "x"}),
                         "no tokens")


class ResolvedStyleTests(unittest.TestCase):
    """The composer path whole: opts -> _apply_opts -> build_realism."""

    def build(self, record, opts):
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), assets(KREA):
            server._apply_opts(args, {"saved_style": record["id"], **opts})
            # submit() strips the receipt tag before the builder sees the args.
            args.pop("_style", None)
            return server.build_realism("Elsa from Frozen, seated", 5, **args)

    def test_the_fills_reach_the_built_graph(self):
        record = server.validate_saved_style(
            style(prompt_prefix=PREFIX, prompt_tail=TAIL, slots=SLOTS))
        graph, cap, info = self.build(record, {
            "style_slots": {"subject": "Velma",
                            "outfit top": "an orange turtleneck"}})
        self.assertTrue(cap.startswith(
            "A photograph of one Velma cosplaying as "))
        self.assertTrue(cap.endswith(
            "synthetic wig fibre; wearing an orange turtleneck"))
        self.assertEqual(info["prompt_prefix"],
                         "A photograph of one Velma cosplaying as")
        self.assertEqual(graph["30:19"]["inputs"]["value"], cap)

    def test_an_unfilled_slot_renders_as_its_default(self):
        record = server.validate_saved_style(
            style(prompt_prefix=PREFIX, prompt_tail=TAIL, slots=SLOTS))
        _, cap, _ = self.build(record, {})
        self.assertTrue(cap.startswith(
            "A photograph of one young woman cosplaying as "))
        self.assertTrue(cap.endswith("wearing a plain tee"))

    def test_a_slot_with_no_default_collapses_out_of_the_caption(self):
        """The inferred-slots file (9.72's shape) with nothing filled: the
        wardrobe clause is gone from the caption, not dangling."""
        record = server.validate_saved_style(
            style(prompt_prefix=PREFIX, prompt_tail=TAIL))
        _, cap, info = self.build(record, {})
        self.assertNotIn("wearing", cap)
        self.assertNotIn("{", cap)
        self.assertTrue(cap.endswith("cotton wrinkles, synthetic wig fibre"))
        self.assertNotIn("prompt_prefix", info)   # the emptied prefix vanished

    def test_style_slots_are_composer_owned_on_reroll(self):
        """Same class as prompt_prefix/prompt_tail: a reroll re-derives the
        fills from the live composer, never from the old spec."""
        self.assertIn("style_slots", server._REROLL_COMPOSER_OWNED)


class ClientWiringTests(unittest.TestCase):
    """Static, test_lora_card_controls style - this repo has no JS runner."""

    def test_the_body_carries_the_fills_where_saved_style_rides(self):
        self.assertIn("body.saved_style = savedStyle.id", STORE)
        # Sparse like the dials: only slots the style declares, only non-blank
        # fills - an untouched slot renders as its default server-side.
        self.assertIn("Object.keys((savedStyle && savedStyle.slots) || {})",
                      STORE)
        self.assertIn("(o.style_slots || {})[name]", STORE)
        self.assertIn("body.style_slots = slotFills", STORE)

    def test_style_slots_are_opts_state_with_the_style(self):
        self.assertRegex(STORE, r'saved_style: "", dials: \{\}, tuning: \{\}, '
                                r'style_slots: \{\}')
        # The bound is a scan window that isolates the function body, not an
        # assertion about its length - the claim under test is the
        # style_slots reset below. selectSavedStyle grew when MiniMax H3 was
        # added to the keep-the-character rule, and a too-small window fails
        # as "selectSavedStyle not found", which reads like a deletion.
        body = re.search(r"selectSavedStyle\(id\) \{([\s\S]{0,3000}?)\n  \},", STORE)
        self.assertIsNotNone(body, "selectSavedStyle not found in store.js")
        # Cleared when the style changes - both the pick and the leave paths.
        self.assertGreaterEqual(body.group(1).count("style_slots: {}"), 2)

    def test_the_fields_render_from_the_styles_slots(self):
        # One field per slot the SELECTED style declares; label = the slot's
        # label or its name, placeholder = the default, value in
        # opts.style_slots, written back through setOpts.
        self.assertIn("Object.entries(activeSavedStyle.slots || {})", COMPOSER)
        self.assertIn("(slot && slot.label) || name", COMPOSER)
        self.assertIn("placeholder={(slot && slot.default) || \"\"}", COMPOSER)
        self.assertIn("((opts.style_slots || {})[name]) || \"\"", COMPOSER)
        self.assertIn("setOpts({ style_slots:", COMPOSER)
    def test_the_editor_preserves_the_declarations(self):
        # StyleForm has no slot editor, so an edit must carry the existing
        # map through untouched - like provenance - or saving any other
        # field would silently strip the slots and their defaults.
        self.assertIn("...(existing?.slots ? { slots: existing.slots } : {})",
                      STYLEFORM)


@unittest.skipUnless(
    (server.RECIPE_DIR / "cosplay_photo.json").is_file(),
    "recipes/cosplay_photo.json is gitignored user data: absent on a clean "
    "checkout and in CI, so there is nothing here to assert on")
class CosplayPhotoSlotTests(unittest.TestCase):
    """The shipped style, recipes/cosplay_photo.json (gitignored user data,
    copied into this worktree): the brief's two slots with their defaults."""

    def test_the_shipped_style_declares_its_slots(self):
        raw = json.loads((server.RECIPE_DIR / "cosplay_photo.json")
                         .read_text(encoding="utf-8"))
        record = server.validate_saved_style(raw)
        self.assertEqual(record["slots"], {
            "subject": {"label": "subject", "default": "young woman"},
            "outfit top": {"label": "outfit", "default": "a plain tee"}})


if __name__ == "__main__":
    unittest.main()
