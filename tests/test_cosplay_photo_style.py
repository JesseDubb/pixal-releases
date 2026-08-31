"""9.72: the "Cosplay photo" saved style and its prompt_prefix frame.

Jesse's Reddit captioner formula (2026-08-27) renders cartoon characters as
real people on Analog Madness: "A photograph of one {subject} cosplaying as
[Character] from the [Franchise], <pose>; <wig>; <makeup>; <gaze>; close-up
selfie crop, top-down, shallow depth of field on the eyes; single frontal
flash; <material textures>". Three locked-seed shots read as real flash
selfies, but Velma rendered topless - the formula names no garment and Analog
Madness undresses when nothing says otherwise. The style therefore carries a
FRAME: a prompt_prefix that opens the caption (new schema field, extended in
validate_saved_style) and a prompt_tail whose LAST clause is the wardrobe
clause, the position this model obeys. See briefs/9.72-findings.md.
"""
import json
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


def model(rel, family, variant="any", **extra):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True, **extra}


KREA = model("Krea 2\\analogMadnessKrea2Turbo_v20.safetensors", "krea2")

PREFIX = "A photograph of one {subject} cosplaying as"
TAIL = ("close-up selfie crop, top-down, shallow depth of field on the eyes; "
        "single frontal flash; cotton wrinkles, synthetic wig fibre; "
        "wearing {outfit top}")


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


class PrefixSchemaTests(unittest.TestCase):
    def test_the_prefix_validates_and_collapses_whitespace(self):
        record = server.validate_saved_style(
            style(prompt_prefix="  A photograph of one\nyoung woman  cosplaying as  "))
        self.assertEqual(record["prompt_prefix"],
                         "A photograph of one young woman cosplaying as")

    def test_rejections_name_the_field(self):
        cases = [
            (style(prompt_prefix=42), "prompt_prefix must be a string"),
            (style(prompt_prefix=["x"]), "prompt_prefix must be a string"),
            (style(prompt_prefix="x" * 601), "prompt_prefix is longer than 600"),
        ]
        for raw, fragment in cases:
            with self.subTest(reason=fragment):
                with self.assertRaises(ValueError) as caught:
                    server.validate_saved_style(raw)
                self.assertIn(fragment, str(caught.exception))

    def test_empty_means_absent(self):
        """A blank prefix is no key at all, same contract as prompt_tail."""
        record = server.validate_saved_style(style(prompt_prefix="   "))
        self.assertNotIn("prompt_prefix", record)


class PromptPrefixTests(unittest.TestCase):
    def test_the_prefix_opens_ahead_of_the_subject_block(self):
        """Assembly order: prefix, then subject/scene/wardrobe lock, then the
        tail - the frame wraps the whole caption."""
        with assets(KREA):
            graph, cap, info = server.build_realism(
                "Elsa from Frozen, seated cross-legged", 1,
                prompt_prefix=PREFIX, prompt_tail=TAIL)
        lock = server.wardrobe_lock_for(None)
        self.assertTrue(cap.startswith(PREFIX + " "))
        self.assertIn(lock, cap)
        self.assertTrue(cap.endswith(TAIL))
        self.assertEqual(graph["30:19"]["inputs"]["value"], cap)
        self.assertEqual(info["prompt_prefix"], PREFIX)
        self.assertEqual(info["prompt_tail"], TAIL)

    def test_realism_ii_prefix_lands_first(self):
        with assets(KREA):
            graph, cap, info = server.build_realism_ii(
                "Elsa from Frozen, seated cross-legged", 1,
                prompt_prefix=PREFIX, prompt_tail=TAIL)
        self.assertTrue(cap.startswith(PREFIX + " "))
        self.assertTrue(cap.endswith(TAIL))
        self.assertEqual(graph["6"]["inputs"]["text"], cap)
        self.assertEqual(info["prompt_prefix"], PREFIX)

    def test_no_prefix_builds_the_caption_it_always_has(self):
        with assets(KREA):
            _, cap, info = server.build_realism("a quiet street", 1)
        self.assertFalse(cap.startswith(PREFIX))
        self.assertNotIn("prompt_prefix", info)


class ResolvedStyleTests(unittest.TestCase):
    def test_the_styles_frame_reaches_the_built_graph(self):
        """The whole path the composer takes: the style FILE folds into builder
        args in _apply_opts, and the built graph carries the whole frame."""
        record = server.validate_saved_style(
            style(prompt_prefix=PREFIX, prompt_tail=TAIL))
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), assets(KREA):
            server._apply_opts(args, {"saved_style": record["id"],
                              # 9.77: the frame's tokens are slots now - the
                              # composer's fills render where the file folds in.
                              "style_slots": {"subject": "young woman",
                                              "outfit top": "an orange turtleneck"}})
            # submit() strips the receipt tag before the builder sees the args.
            args.pop("_style", None)
            graph, cap, info = server.build_realism("a portrait", 5, **args)
        filled_prefix = PREFIX.replace("{subject}", "young woman")
        filled_tail = TAIL.replace("{outfit top}", "an orange turtleneck")
        self.assertTrue(cap.startswith(filled_prefix + " "))
        self.assertTrue(cap.endswith(filled_tail))
        self.assertEqual(info["prompt_prefix"], filled_prefix)
        self.assertEqual(info["prompt_tail"], filled_tail)

    def test_the_prefix_is_composer_owned_on_reroll(self):
        """Same class as negative/prompt_tail: a reroll strips the old spec's
        copy and re-derives it from the live composer."""
        self.assertIn("prompt_prefix", server._REROLL_COMPOSER_OWNED)


@unittest.skipUnless(
    (server.RECIPE_DIR / "cosplay_photo.json").is_file(),
    "recipes/cosplay_photo.json is gitignored user data: absent on a clean "
    "checkout and in CI, so there is nothing here to assert on")
class CosplayPhotoStyleTests(unittest.TestCase):
    """The shipped style: recipes/cosplay_photo.json."""

    def load(self):
        raw = json.loads((server.RECIPE_DIR / "cosplay_photo.json")
                         .read_text(encoding="utf-8"))
        return server.validate_saved_style(raw)

    def test_the_file_loads_with_no_style_problems(self):
        """The shipped bytes through the real loader: usable, nothing named."""
        with TemporaryDirectory() as td:
            shutil.copy(server.RECIPE_DIR / "cosplay_photo.json", td)
            with patch.object(server, "RECIPE_DIR", Path(td)):
                styles, problems = server.load_saved_styles()
        self.assertEqual(problems, [])
        self.assertEqual(styles["cosplay_photo"]["name"], "Cosplay photo")

    def test_the_frame_and_the_analog_film_stack(self):
        record = self.load()
        self.assertEqual(record["id"], "cosplay_photo")
        self.assertEqual(record["base"], "realism")
        self.assertEqual(record["model"], KREA["rel"])
        self.assertIn("cosplaying as", record["prompt_prefix"])
        # The wardrobe clause is the LAST clause - the position Analog
        # Madness obeys (the topless-Velma fix).
        clauses = [c.strip() for c in record["prompt_tail"].split(";")]
        self.assertTrue(clauses[-1].startswith("wearing"),
                        f"the wardrobe clause must close the tail: {clauses[-1]!r}")
        # analog_film's frame and LoRA plan, copied per the brief.
        self.assertEqual(record["aspect"], "3:2 (Photo)")
        self.assertEqual(record["mp"], 2.0)
        plan = record["lora_plan"]
        self.assertEqual(plan["mode"], "replace_editable")
        self.assertEqual(plan["entries"][0]["name"],
                         "Krea 2\\Krea 2\\kodak.safetensors")
        self.assertEqual(plan["entries"][0]["strength"], 0.8)
        with assets(KREA):
            self.assertIs(server.check_style_runnable(record), record)

    def test_the_shipped_frame_builds(self):
        """What a render gets: the formula opening, the wardrobe lock mid
        caption, and the camera/light/texture chain closing on the wardrobe
        clause, with analog_film's chain on the graph - the core vector
        bypass (no core override in the copied plan) plus Kodak Gold."""
        record = self.load()
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), assets(KREA):
            server._apply_opts(args, {"saved_style": "cosplay_photo"})
            args.pop("_style", None)
            graph, cap, info = server.build_realism(
                "Elsa from Frozen, seated cross-legged on the bed", 7, **args)
        # 9.77: the slots are declared with defaults, so an unfilled render gets
        # the formula with the defaults in place - never literal braces.
        filled_prefix = PREFIX.replace("{subject}", "young woman")
        filled_tail = TAIL.replace("{outfit top}", "a plain tee")
        self.assertTrue(cap.startswith(filled_prefix + " "))
        self.assertIn(server.wardrobe_lock_for(None), cap)
        self.assertTrue(cap.endswith(filled_tail))
        loras = sorted(n["inputs"]["lora_name"] for n in graph.values()
                       if n["class_type"] == "LoraLoaderModelOnly")
        self.assertEqual(loras, ["Krea 2\\Krea 2\\kodak.safetensors",
                                 server.KREA_BYPASS_LORA])
        self.assertEqual(info["prompt_prefix"], filled_prefix)
        self.assertEqual(info["prompt_tail"], filled_tail)


if __name__ == "__main__":
    unittest.main()
