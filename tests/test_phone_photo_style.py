"""9.57: a style can carry a negative prompt and a prompt tail.

Arm D of the 2026-08-26 locked-seed Krea 2 A/B won on a real negative and a
closing "smartphone photo" clause with every LoRA off - the two clauses are
style data (recipes/*.json), and build_realism / build_realism_ii wire them
into the graph. Without them the graph is byte-identical to before the
change, pinned here by tests/snapshots/realism_default.json (captured from
the pre-change builder by tools/make_realism_snapshot.py).
"""
import json
import unittest
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests" / "snapshots" / "realism_default.json"

_SPEC = spec_from_file_location("pixal_server", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def model(rel, family, variant="any", **extra):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True, **extra}


KREA = model("Krea 2\\analogMadnessKrea2Turbo_v20.safetensors", "krea2")
CONVROT = model("Krea 2\\krea2_turbo_int8_convrot.safetensors", "krea2")
# The exact entry tools/make_realism_snapshot.py captured the snapshot under;
# the unet name it writes into the graph is part of the compared bytes.
SNAP_ENTRY = model("Krea 2\\phone test.safetensors", "krea2")

NEGATIVE = ("Bokeh. Shallow depth of field. Professional photo. Background "
            "blur. Blurry. Illustration. DSLR photo. Film photo. Film grain.")
TAIL = ("In the style of a high resolution, ultrasharp, high dynamic range, "
        "smartphone photo taken on a Samsung Galaxy 25+ in 2025, with high "
        "contrast and vibrant colors. Candid photo. The entire digital photo "
        "is sharp and detailed.")


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
    base = {"schema_version": 1, "name": "Grainy Portrait", "base": "realism",
            "model": KREA["rel"]}
    base.update(over)
    return base


class ClauseSchemaTests(unittest.TestCase):
    def test_the_two_fields_validate_and_collapse_whitespace(self):
        record = server.validate_saved_style(
            style(negative="waxy  skin,\nplastic\thair", prompt_tail="  coda  "))
        self.assertEqual(record["negative"], "waxy skin, plastic hair")
        self.assertEqual(record["prompt_tail"], "coda")

    def test_rejections_name_the_field(self):
        cases = [
            (style(negative=42), "negative must be a string"),
            (style(prompt_tail=["x"]), "prompt_tail must be a string"),
            (style(negative="x" * 601), "negative is longer than 600"),
            (style(prompt_tail="x" * 601), "prompt_tail is longer than 600"),
        ]
        for raw, fragment in cases:
            with self.subTest(reason=fragment):
                with self.assertRaises(ValueError) as caught:
                    server.validate_saved_style(raw)
                self.assertIn(fragment, str(caught.exception))

    def test_empty_means_absent_and_old_files_stay_valid(self):
        """A style written before the fields existed has neither key; a blank
        one saves as no key at all, so the file says only what was chosen."""
        plain = server.validate_saved_style(style())
        self.assertNotIn("negative", plain)
        self.assertNotIn("prompt_tail", plain)
        blank = server.validate_saved_style(style(negative="   ", prompt_tail=""))
        self.assertNotIn("negative", blank)
        self.assertNotIn("prompt_tail", blank)

    def test_the_fields_survive_the_file_round_trip(self):
        with TemporaryDirectory() as td, \
             patch.object(server, "RECIPE_DIR", Path(td)), \
             patch.dict(server.SAVED_STYLES, {}, clear=True):
            record = server.validate_saved_style(
                style(negative="grain", prompt_tail="coda"))
            server.write_saved_style(record)
            styles, problems = server.load_saved_styles()
        self.assertEqual(problems, [])
        loaded = styles["grainy_portrait"]
        self.assertEqual(loaded["negative"], "grain")
        self.assertEqual(loaded["prompt_tail"], "coda")


class NegativeWiringTests(unittest.TestCase):
    def test_a_negative_replaces_the_zero_out(self):
        with assets(KREA):
            graph, _cap, info = server.build_realism("a portrait", 1,
                                                     negative="waxy skin")
        node = graph["30:neg"]
        self.assertEqual(node["class_type"], "CLIPTextEncode")
        self.assertEqual(node["inputs"]["text"], "waxy skin")
        self.assertEqual(node["inputs"]["clip"], graph["30:6"]["inputs"]["clip"])
        self.assertEqual(graph["30:51"]["inputs"]["negative"], ["30:neg", 0])
        self.assertEqual(info["negative"], "waxy skin")

    def test_no_negative_is_byte_identical_to_before_the_change(self):
        """Existing renders must not move: no clause, no new node, and the
        ZeroOut still feeds the sampler - the whole graph compared against the
        snapshot captured from the pre-change builder."""
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        with assets(SNAP_ENTRY):
            graph, cap, info = server.build_realism("a portrait", 1,
                                                    model=SNAP_ENTRY["rel"])
        self.assertEqual(cap, snap["caption"])
        self.assertEqual(graph, snap["graph"])
        self.assertEqual(graph["30:51"]["inputs"]["negative"], ["30:13", 0])
        self.assertNotIn("negative", info)
        self.assertNotIn("prompt_tail", info)

    def test_realism_ii_points_every_pass_at_the_real_negative(self):
        """realism_ii has no ZeroOut - its three passes take the POSITIVE as
        their negative. A style negative replaces that on all three, or the
        refine and upscale passes would keep steering from the caption."""
        with assets(KREA):
            graph, _cap, info = server.build_realism_ii("a portrait", 1,
                                                        negative="waxy skin")
        node = graph["r2:neg"]
        self.assertEqual(node["class_type"], "CLIPTextEncode")
        self.assertEqual(node["inputs"]["text"], "waxy skin")
        self.assertEqual(node["inputs"]["clip"], graph["6"]["inputs"]["clip"])
        for nid in ("265", "274", "333"):
            self.assertEqual(graph[nid]["inputs"]["negative"], ["r2:neg", 0])
        self.assertEqual(info["negative"], "waxy skin")

    def test_realism_ii_without_a_negative_keeps_its_wiring(self):
        with assets(KREA):
            graph, _cap, info = server.build_realism_ii("a portrait", 1)
        self.assertNotIn("r2:neg", graph)
        for nid in ("265", "274", "333"):
            self.assertEqual(graph[nid]["inputs"]["negative"], ["6", 0])
        self.assertNotIn("negative", info)
        self.assertNotIn("prompt_tail", info)


class PromptTailTests(unittest.TestCase):
    def test_the_tail_is_the_closing_clause_after_the_wardrobe_lock(self):
        with assets(KREA):
            graph, cap, info = server.build_realism("a portrait", 1,
                                                    prompt_tail=TAIL)
        lock = server.wardrobe_lock_for(None)
        self.assertIn(lock, cap)
        self.assertTrue(cap.endswith(TAIL))
        self.assertLess(cap.index(lock), cap.index(TAIL))
        self.assertEqual(graph["30:19"]["inputs"]["value"], cap)
        self.assertEqual(info["prompt_tail"], TAIL)

    def test_realism_ii_tail_lands_last(self):
        with assets(KREA):
            graph, cap, info = server.build_realism_ii("a portrait", 1,
                                                       prompt_tail=TAIL)
        self.assertTrue(cap.endswith(TAIL))
        self.assertEqual(graph["6"]["inputs"]["text"], cap)
        self.assertEqual(info["prompt_tail"], TAIL)


class ResolvedStyleTests(unittest.TestCase):
    def test_the_resolved_styles_clauses_reach_the_built_graph(self):
        """The whole path the composer takes: the style FILE folds into builder
        args in _apply_opts, and the built graph carries both clauses."""
        record = server.validate_saved_style(
            style(negative="waxy skin", prompt_tail="coda"))
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), assets(KREA):
            server._apply_opts(args, {"saved_style": record["id"]})
            # submit() strips the receipt tag before the builder sees the args.
            args.pop("_style", None)
            graph, cap, info = server.build_realism("a portrait", 5, **args)
        self.assertEqual(graph["30:51"]["inputs"]["negative"], ["30:neg", 0])
        self.assertTrue(cap.endswith("coda"))
        self.assertEqual(info["negative"], "waxy skin")
        self.assertEqual(info["prompt_tail"], "coda")
    def test_the_clauses_are_composer_owned_on_reroll(self):
        """Same class as model and overrides: a reroll strips them from the
        old spec and re-derives them from the live composer, so a style the
        user has moved off cannot keep steering the next render."""
        self.assertIn("negative", server._REROLL_COMPOSER_OWNED)
        self.assertIn("prompt_tail", server._REROLL_COMPOSER_OWNED)


@unittest.skipUnless(
    (server.RECIPE_DIR / "phone_photo.json").is_file(),
    "recipes/phone_photo.json is gitignored user data: absent on a clean "
    "checkout and in CI, so there is nothing here to assert on")
class PhonePhotoStyleTests(unittest.TestCase):
    """The shipped arm-D style: recipes/phone_photo.json."""

    def load(self):
        raw = json.loads((server.RECIPE_DIR / "phone_photo.json")
                         .read_text(encoding="utf-8"))
        return server.validate_saved_style(raw)

    def test_the_shipped_file_loads_with_its_clauses_and_plan(self):
        record = self.load()
        self.assertEqual(record["id"], "phone_photo")
        self.assertEqual(record["name"], "Phone photo")
        self.assertEqual(record["base"], "realism")
        self.assertEqual(record["model"], CONVROT["rel"])
        self.assertEqual(record["tuning"],
                         {"steps": 14, "cfg": 1.2, "eta": 0.0,
                          "sampler_name": "linear/euler", "scheduler": "simple"})
        self.assertEqual(record["aspect"], "9:16 (Portrait Widescreen)")
        self.assertEqual(record["mp"], 2.0)
        plan = record["lora_plan"]
        self.assertEqual(plan["entries"], [])
        self.assertIs(plan["core"]["vector_bypass"]["enabled"], False)
        self.assertEqual(record["negative"], NEGATIVE)
        self.assertEqual(record["prompt_tail"], TAIL)
        with assets(CONVROT):
            self.assertIs(server.check_style_runnable(record), record)

    def test_arm_d_builds_with_no_loras_and_a_real_negative(self):
        """What Jesse judged: the convrot core at 14 steps / cfg 1.2 on
        linear/euler + simple, every LoRA off (the core bypass included), the
        A/B negative on the sampler and the phone tail closing the caption."""
        record = self.load()
        args = {}
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}), assets(CONVROT):
            server._apply_opts(args, {"saved_style": "phone_photo"})
            args.pop("_style", None)
            graph, cap, info = server.build_realism("a quiet street", 7, **args)
        sampler = graph["30:51"]["inputs"]
        self.assertEqual((sampler["steps"], sampler["cfg"], sampler["eta"],
                          sampler["sampler_name"], sampler["scheduler"]),
                         (14, 1.2, 0.0, "linear/euler", "simple"))
        self.assertEqual(sampler["negative"], ["30:neg", 0])
        self.assertEqual(graph["30:neg"]["inputs"]["text"], NEGATIVE)
        self.assertEqual(sampler["model"], ["30:10", 0])
        self.assertFalse(any(node["class_type"] == "LoraLoaderModelOnly"
                             for node in graph.values()))
        self.assertTrue(cap.endswith(TAIL))
        self.assertEqual(info["negative"], NEGATIVE)
        self.assertEqual(info["prompt_tail"], TAIL)


if __name__ == "__main__":
    unittest.main()
