import asyncio
import json
import unittest
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch


_SPEC = spec_from_file_location(
    "pixal_server_identity_dials", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def model(rel, family, variant="any", **extra):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True, **extra}


@contextmanager
def assets(entry):
    with ExitStack() as stack:
        stack.enter_context(patch.object(server, "resolve_model_entry", return_value=entry))
        stack.enter_context(patch.object(server, "_catalog_has", return_value=True))
        stack.enter_context(patch.object(server, "_catalog_resolve",
                                         side_effect=lambda kind, rel: rel))
        stack.enter_context(patch.object(server, "resolve_lora", side_effect=lambda name: name))
        yield


@contextmanager
def identity_anchor():
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        character = {"id": "hero", "name": "Hero", "style": "silver hair",
                     "identity_ref": "hero.png"}
        (root / "input" / "hero.png").write_bytes(b"reference")
        with patch.object(server, "CDIR", root), \
             patch.object(server, "CHARACTERS", {"hero": character}):
            yield root, character


KREA = model(server.RECIPE_SPECS["identity_edit"]["default_model"], "krea2")


class IdentityDialDeclarationTests(unittest.TestCase):
    """The dials are declared on the recipe so the composer extender, intake
    validation and the re-roll all read one declaration - a later recipe gets
    its own by declaring it, per brief 9.14."""

    def test_identity_edit_declares_its_dials_in_the_authors_ranges(self):
        dials = {d["key"]: d for d in server.RECIPE_SPECS["identity_edit"]["dials"]}
        # Brief 9.15 added the bypass variant choice, 9.56 the identity patch
        # build choice, to the same declaration.
        self.assertEqual(set(dials), {"ref_boost", "grounding", "ref_boost_mask",
                                      "bypass_variant", "identity_build"})
        likeness = dials["ref_boost"]
        self.assertEqual((likeness["min"], likeness["max"]), (0.0, 10.0))
        self.assertEqual(likeness["default"], server.IDENTITY_REF_BOOST)
        grounding = dials["grounding"]
        self.assertEqual((grounding["min"], grounding["max"]), (384, 1536))
        self.assertEqual(grounding["default"], server.IDENTITY_GROUNDING_PX)
        # The key IS the build_zara_edit parameter, so submit's SIGS filter is
        # the gate that keeps dials off every other recipe's graph.
        for key in dials:
            self.assertIn(key, server.SIGS["identity_edit"])

    def test_no_other_recipe_declares_dials_yet(self):
        for rid, spec in server.RECIPE_SPECS.items():
            if rid != "identity_edit":
                self.assertFalse(spec.get("dials"), rid)


class IdentityDialBuildTests(unittest.TestCase):
    def test_an_untouched_composer_builds_a_byte_identical_graph(self):
        """The regression that matters most (brief 9.14): with no dial touched,
        the composer path must produce exactly today's graph - the defaults
        preserve the render, only reachability changes."""
        with identity_anchor(), assets(KREA):
            default_graph, _c, _i = server.build_zara_edit("restage", 7, character="hero")
            args = {}
            server._apply_opts(args, {"engine": "identity_edit", "character": "hero"})
            self.assertNotIn("ref_boost", args)
            self.assertNotIn("grounding", args)
            filtered = {k: v for k, v in args.items() if k in server.SIGS["identity_edit"]}
            composer_graph, _c, _i = server.build_zara_edit("restage", 7, **filtered)
        self.assertEqual(json.dumps(composer_graph, sort_keys=True),
                         json.dumps(default_graph, sort_keys=True))
        self.assertEqual(default_graph["ed:patch"]["inputs"]["ref_boost"],
                         server.IDENTITY_REF_BOOST)
        self.assertEqual(default_graph["30:6"]["inputs"]["grounding_px"],
                         server.IDENTITY_GROUNDING_PX)

    def test_a_live_ref_boost_reaches_the_edit_patch(self):
        with identity_anchor(), assets(KREA):
            graph, _c, _i = server.build_zara_edit("restage", 7, character="hero",
                                                   ref_boost=2.5)
        self.assertEqual(graph["ed:patch"]["inputs"]["ref_boost"], 2.5)
        # and the untouched dial still sits on its own constant
        self.assertEqual(graph["30:6"]["inputs"]["grounding_px"],
                         server.IDENTITY_GROUNDING_PX)

    def test_a_live_grounding_reaches_the_grounded_encode(self):
        with identity_anchor(), assets(KREA):
            graph, _c, _i = server.build_zara_edit("restage", 7, character="hero",
                                                   grounding=512)
        self.assertEqual(graph["30:6"]["inputs"]["grounding_px"], 512)
        self.assertEqual(graph["ed:patch"]["inputs"]["ref_boost"],
                         server.IDENTITY_REF_BOOST)

    def test_composer_dials_validate_on_the_way_in(self):
        """In-range values pass (coerced the way the builder coerces);
        out-of-range, non-numeric, None and bool each fall back to the recipe
        constant rather than raising - degrade, never die."""
        good = {"ref_boost": 2.5, "grounding": 512}
        bad = {"ref_boost": (10.5, -0.1, "lots", None, True, float("nan"),
                             float("inf")),
               "grounding": (1537, 383, "lots", None, False, float("nan"))}
        with identity_anchor():
            args = {}
            server._apply_opts(args, {"engine": "identity_edit", "character": "hero",
                                      **good})
            self.assertEqual(args["ref_boost"], 2.5)
            self.assertEqual(args["grounding"], 512)
            # zero is a real likeness value (the loosest setting), not "unset"
            args = {}
            server._apply_opts(args, {"engine": "identity_edit", "character": "hero",
                                      "ref_boost": 0})
            self.assertEqual(args["ref_boost"], 0.0)
            for key, values in bad.items():
                for value in values:
                    with self.subTest(key=key, value=value):
                        args = {}
                        server._apply_opts(args, {"engine": "identity_edit",
                                                  "character": "hero", key: value})
                        self.assertEqual(args[key],
                                         getattr(server, "IDENTITY_REF_BOOST")
                                         if key == "ref_boost"
                                         else server.IDENTITY_GROUNDING_PX)

    def test_a_non_identity_render_never_gets_the_dials(self):
        args = {}
        server._apply_opts(args, {"engine": "realism", "ref_boost": 2.5,
                                  "grounding": 512})
        self.assertNotIn("ref_boost", args)
        self.assertNotIn("grounding", args)


class IdentityDialOptionsTests(unittest.TestCase):
    def test_options_carries_the_dial_declaration_to_the_composer(self):
        """The extender is declared server-side: /api/options is the only way
        the composer learns the dials exist, their ranges and their copy - so
        a later recipe's declaration needs no client change either."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "model_catalog", side_effect=lambda kind: []), \
                 patch.object(server, "model_roots", return_value=[]), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "lm_enrich"), \
                 patch.object(server, "_LORA_TITLE_CACHE", root / "titles.json"):
                options = server.Hub().options()
        identity = next(r for r in options["recipes"] if r["id"] == "identity_edit")
        # bypass_variant (brief 9.15) and identity_build (brief 9.56) ride the
        # same declaration; with an empty catalog their live choices are
        # simply empty.
        self.assertEqual([d["key"] for d in identity["dials"]],
                         ["ref_boost", "grounding", "ref_boost_mask",
                          "bypass_variant", "identity_build"])
        likeness = identity["dials"][0]
        self.assertEqual(likeness["label"], "Likeness")
        self.assertEqual(likeness["default"], server.IDENTITY_REF_BOOST)
        for recipe in options["recipes"]:
            if recipe["id"] != "identity_edit":
                self.assertEqual(recipe["dials"], [], recipe["id"])


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class IdentityDialRerollTests(unittest.TestCase):
    """The dials ride a re-roll exactly like the live canvas (28cd662): the
    composer is the truth, so "adjust and re-roll" - the loop a likeness dial
    is FOR - must not silently use the old value."""

    ENTRY = {"id": "abc12345", "template": "identity_edit", "scene": "restage her",
             "seed": 424242, "count": 1,
             "spec": {"character": "hero", "ref_boost": 2.5, "grounding": 512}}

    def roll(self, body, entry=None):
        submit = AsyncMock()
        with patch.object(server.HUB, "ledger_read",
                          return_value=[entry or dict(self.ENTRY)]), \
             patch.object(server.HUB, "submit", submit):
            async def run():
                await server.reroll(FakeRequest(body))
                await asyncio.sleep(0)      # let the created task settle
            asyncio.run(run())
        return submit.call_args

    def test_live_dials_land_on_the_resubmitted_spec(self):
        call = self.roll({"id": "abc12345", "ref_boost": 6.0, "grounding": 768})
        spec = call.args[4]
        self.assertEqual(spec["ref_boost"], 6.0)
        self.assertEqual(spec["grounding"], 768)

    def test_a_bad_dial_falls_back_to_the_recipe_constant(self):
        # Present-but-bad degrades to the constant, never a 4xx - and never to
        # the card's stored value, which the user has moved away from.
        for bad in (10.5, -0.1, "lots", True, None):
            with self.subTest(ref_boost=bad):
                call = self.roll({"id": "abc12345", "ref_boost": bad})
                self.assertEqual(call.args[4]["ref_boost"], server.IDENTITY_REF_BOOST)
        for bad in (1537, 383, "lots", False, None):
            with self.subTest(grounding=bad):
                call = self.roll({"id": "abc12345", "grounding": bad})
                self.assertEqual(call.args[4]["grounding"], server.IDENTITY_GROUNDING_PX)

    def test_an_omitted_dial_keeps_the_stored_value(self):
        # absent != empty: a stale bundle sends neither key, and a partial body
        # touches only what it names.
        call = self.roll({"id": "abc12345", "ref_boost": 6.0})
        spec = call.args[4]
        self.assertEqual(spec["ref_boost"], 6.0)
        self.assertEqual(spec["grounding"], 512)
        call = self.roll({"id": "abc12345"})
        spec = call.args[4]
        self.assertEqual(spec["ref_boost"], 2.5)
        self.assertEqual(spec["grounding"], 512)

    def test_a_recipe_without_dials_never_gets_the_keys(self):
        entry = {"id": "r1234567", "template": "realism", "scene": "a shot",
                 "seed": 7, "count": 1,
                 "spec": {"aspect": "1:1 (Square)", "mp": 2.0, "standing": True}}
        call = self.roll({"id": "r1234567", "ref_boost": 6.0, "grounding": 512},
                         entry=entry)
        spec = call.args[4]
        self.assertNotIn("ref_boost", spec)
        self.assertNotIn("grounding", spec)


class IdentityDialToolSchemaTests(unittest.TestCase):
    """The brain's tool schema used to claim grounding defaults to 1536 and
    that ref_boost should be omitted by default - both wrong against the model
    card, whose own starting points (768, ~4) are what the recipe runs."""

    def schema_description(self, key):
        params = server.TOOLS[0]["function"]["parameters"]["properties"]
        return params[key]["description"]

    def test_grounding_description_names_the_real_default_and_range(self):
        text = self.schema_description("grounding")
        self.assertIn("768", text)
        self.assertNotIn("1536", text)
        self.assertIn("384", text)

    def test_ref_boost_description_names_the_real_default(self):
        text = self.schema_description("ref_boost")
        self.assertIn("4.0", text)
        self.assertNotIn("never by default", text)


if __name__ == "__main__":
    unittest.main()
