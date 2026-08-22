import asyncio
import json
import struct
import unittest
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch


_SPEC = spec_from_file_location(
    "pixal_server_vector_bypass", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


# Jesse's Krea 2 folder, verbatim (brief 9.15): the authoritative 2-vector has
# no variant digit in its name, its byte-identical twin was filed as
# "...2vector", and the 3-vector has always been installed but unreachable.
BYPASS2 = "Krea 2\\krea2filterbypass.safetensors"
BYPASS2_TWIN = "Krea 2\\krea2filterbypass2vector.safetensors"
BYPASS3 = "Krea 2\\krea2filterbypass3.safetensors"


def patch_bytes(vectors):
    """A projector-patch safetensors: one [1, N] F32 tensor whose non-zero
    count IS the variant - the file layout _vector_patch_count reads."""
    data = struct.pack("<%df" % len(vectors), *vectors)
    header = json.dumps({
        "lora_unet" + server._VECTOR_PATCH_SUFFIX: {
            "dtype": "F32", "shape": [1, len(vectors)],
            "data_offsets": [0, len(data)]},
    }).encode()
    return struct.pack("<Q", len(header)) + header + data


PATCH2 = patch_bytes([0.5, -0.5])
PATCH3 = patch_bytes([0.25, 0.5, -0.25])


@contextmanager
def lora_catalog(files):
    """A faked LoRA catalog: {rel: bytes} written under one temp root, with
    model_catalog returning it for loras and nothing for every other kind."""
    with TemporaryDirectory() as td:
        root = Path(td)
        entries = []
        for rel, data in files.items():
            path = root / "loras" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            entries.append({"rel": rel, "root": str(root), "kind": "loras"})
        with patch.object(server, "model_catalog",
                          side_effect=lambda kind=None, ttl=30:
                          entries if kind == "loras" else []):
            yield root


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
FULL_CATALOG = {BYPASS2: PATCH2, BYPASS2_TWIN: PATCH2, BYPASS3: PATCH3}


def lora_loaders(graph):
    return {nid: node for nid, node in graph.items()
            if node.get("class_type") == "LoraLoaderModelOnly"}


class VectorPatchScanTests(unittest.TestCase):
    """The variant is the TENSOR, never the filename (brief 9.15): people
    rename these on the way in, and this box proves it - the authoritative
    2-vector is krea2filterbypass.safetensors, no digit in the name."""

    def test_a_patch_named_with_no_digits_reports_its_tensor_count(self):
        with TemporaryDirectory() as td:
            for name in ("krea2filterbypass.safetensors", "thebypass.safetensors"):
                with self.subTest(name=name):
                    path = Path(td) / name
                    path.write_bytes(PATCH2)
                    stat = path.stat()
                    self.assertEqual(
                        server._vector_patch_count(str(path), stat.st_mtime_ns,
                                                   stat.st_size), 2)

    def test_byte_identical_twins_collapse_to_one_option(self):
        with lora_catalog({BYPASS2: PATCH2, BYPASS2_TWIN: PATCH2}):
            variants = server.vector_bypass_variants()
        # One 2-vector option, not two - and the authored name represents it
        # (it sorts ahead of its "2vector" twin).
        self.assertEqual(variants, {2: BYPASS2})

    def test_a_3_vector_file_is_offered_as_the_3_vector_option(self):
        with lora_catalog(FULL_CATALOG):
            variants = server.vector_bypass_variants()
        self.assertEqual(variants, {2: BYPASS2, 3: BYPASS3})

    def test_an_unreadable_or_foreign_lora_is_not_a_variant(self):
        with lora_catalog({BYPASS2: PATCH2,
                           "Krea 2\\krea2_identity_edit_v1_2_r128.safetensors":
                               b"not a safetensors file"}):
            variants = server.vector_bypass_variants()
        self.assertEqual(variants, {2: BYPASS2})


class BypassVariantBuildTests(unittest.TestCase):
    def test_the_default_remains_the_2_vector_and_the_graph_is_byte_identical(self):
        """The regression that matters most (brief 9.15): with no variant
        touched the composer path must produce exactly today's graph, and an
        EXPLICIT default - what a re-roll's resolved dials always sends -
        builds the same bytes too."""
        self.assertEqual(server.KREA_BYPASS_VECTORS, 2)
        dial = next(d for d in server.RECIPE_SPECS["identity_edit"]["dials"]
                    if d["key"] == "bypass_variant")
        self.assertEqual(dial["default"], 2)
        with identity_anchor(), assets(KREA), lora_catalog(FULL_CATALOG):
            default_graph, _c, _i = server.build_zara_edit("restage", 7, character="hero")
            args = {}
            server._apply_opts(args, {"engine": "identity_edit", "character": "hero"})
            self.assertNotIn("bypass_variant", args)
            filtered = {k: v for k, v in args.items() if k in server.SIGS["identity_edit"]}
            composer_graph, _c, _i = server.build_zara_edit("restage", 7, **filtered)
            explicit, _c, _i = server.build_zara_edit("restage", 7, character="hero",
                                                      bypass_variant=2)
        self.assertEqual(json.dumps(composer_graph, sort_keys=True),
                         json.dumps(default_graph, sort_keys=True))
        self.assertEqual(json.dumps(explicit, sort_keys=True),
                         json.dumps(default_graph, sort_keys=True))
        bypass = next(n for n in lora_loaders(default_graph).values()
                      if n["inputs"]["lora_name"] == server.KREA_BYPASS_LORA)
        self.assertEqual(bypass["inputs"]["strength_model"], 1.0)

    def test_choosing_3_vector_swaps_only_that_stage(self):
        """Chain order and every other node unchanged: the 3-vector graph is
        today's graph with one loader's lora_name swapped (brief 9.15)."""
        with identity_anchor(), assets(KREA), lora_catalog(FULL_CATALOG):
            base_graph, _c, _i = server.build_zara_edit("restage", 7, character="hero")
            swapped, _c, _i = server.build_zara_edit("restage", 7, character="hero",
                                                     bypass_variant=3)
        self.assertEqual(set(swapped), set(base_graph))
        bypass_id = next(nid for nid, n in lora_loaders(base_graph).items()
                         if n["inputs"]["lora_name"] == server.KREA_BYPASS_LORA)
        for nid, node in base_graph.items():
            if nid == bypass_id:
                continue
            self.assertEqual(swapped[nid], node, nid)
        before = base_graph[bypass_id]["inputs"]
        after = swapped[bypass_id]["inputs"]
        self.assertEqual(after["lora_name"], BYPASS3)
        self.assertEqual(after["strength_model"], before["strength_model"])
        self.assertEqual(after["model"], before["model"])
        # The chain downstream of the swap still hangs off the same node id.
        follower_id = next(nid for nid, n in lora_loaders(base_graph).items()
                           if n["inputs"]["model"] == [bypass_id, 0])
        self.assertEqual(swapped[follower_id]["inputs"]["model"], [bypass_id, 0])

    def test_an_uninstalled_variant_falls_back_to_the_authored_stage(self):
        """The builder-side guard for direct calls: a count the machine does
        not own degrades to the authored 2-vector stage rather than dying."""
        with identity_anchor(), assets(KREA), lora_catalog({BYPASS2: PATCH2}):
            default_graph, _c, _i = server.build_zara_edit("restage", 7, character="hero")
            for bad in (3, 7, "3", None, True, 2.5):
                with self.subTest(bypass_variant=bad):
                    graph, _c, _i = server.build_zara_edit("restage", 7, character="hero",
                                                           bypass_variant=bad)
                    self.assertEqual(json.dumps(graph, sort_keys=True),
                                     json.dumps(default_graph, sort_keys=True))

    def test_composer_choice_validates_on_the_way_in(self):
        """An installed variant passes; an uninstalled one, a non-integral
        number, a bool and None each land on the 2-vector default - degrade,
        never die, the same policy as the number dials."""
        with identity_anchor(), lora_catalog(FULL_CATALOG):
            args = {}
            server._apply_opts(args, {"engine": "identity_edit", "character": "hero",
                                      "bypass_variant": 3})
            self.assertEqual(args["bypass_variant"], 3)
            for bad in (7, 2.5, "lots", None, True, float("nan")):
                with self.subTest(bypass_variant=bad):
                    args = {}
                    server._apply_opts(args, {"engine": "identity_edit",
                                              "character": "hero",
                                              "bypass_variant": bad})
                    self.assertEqual(args["bypass_variant"], 2)


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class BypassVariantRerollTests(unittest.TestCase):
    """The variant rides a re-roll exactly like the 9.14 dials and the canvas
    (28cd662): "switch and re-roll" is the whole point of an A/B control."""

    ENTRY = {"id": "abc12345", "template": "identity_edit", "scene": "restage her",
             "seed": 424242, "count": 1,
             "spec": {"character": "hero", "bypass_variant": 3}}

    def roll(self, body, entry=None):
        submit = AsyncMock()
        with lora_catalog(FULL_CATALOG), \
             patch.object(server.HUB, "ledger_read",
                          return_value=[entry or dict(self.ENTRY)]), \
             patch.object(server.HUB, "submit", submit):
            async def run():
                await server.reroll(FakeRequest(body))
                await asyncio.sleep(0)      # let the created task settle
            asyncio.run(run())
        return submit.call_args

    def test_a_reroll_carries_the_chosen_variant(self):
        call = self.roll({"id": "abc12345", "bypass_variant": 2})
        self.assertEqual(call.args[4]["bypass_variant"], 2)

    def test_an_omitted_variant_keeps_the_stored_value(self):
        call = self.roll({"id": "abc12345"})
        self.assertEqual(call.args[4]["bypass_variant"], 3)

    def test_a_bad_or_uninstalled_variant_falls_back_to_the_default(self):
        # Present-but-bad degrades to the constant, never a 4xx - and never to
        # the card's stored value, which the user has moved away from.
        for bad in (7, 2.5, "lots", True, None):
            with self.subTest(bypass_variant=bad):
                call = self.roll({"id": "abc12345", "bypass_variant": bad})
                self.assertEqual(call.args[4]["bypass_variant"], 2)

    def test_a_recipe_without_the_declaration_never_gets_the_key(self):
        entry = {"id": "r1234567", "template": "realism", "scene": "a shot",
                 "seed": 7, "count": 1,
                 "spec": {"aspect": "1:1 (Square)", "mp": 2.0, "standing": True}}
        call = self.roll({"id": "r1234567", "bypass_variant": 3}, entry=entry)
        self.assertNotIn("bypass_variant", call.args[4])


class BypassVariantOptionsTests(unittest.TestCase):
    """Only what is installed is ever offered (brief 9.15): the choices ride
    /api/options so a variant that would fail at queue time never shows."""

    def options(self, files):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            with lora_catalog(files), \
                 patch.object(server, "CDIR", root), \
                 patch.object(server, "model_roots", return_value=[]), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "lm_enrich"), \
                 patch.object(server, "_LORA_TITLE_CACHE", root / "titles.json"):
                return server.Hub().options()

    def bypass_dial(self, options):
        identity = next(r for r in options["recipes"] if r["id"] == "identity_edit")
        return next(d for d in identity["dials"] if d["key"] == "bypass_variant")

    def test_both_installed_variants_are_offered_by_count(self):
        dial = self.bypass_dial(self.options(FULL_CATALOG))
        self.assertEqual(dial["default"], 2)
        self.assertEqual([(c["value"], c["label"]) for c in dial["choices"]],
                         [(2, "2-vector"), (3, "3-vector")])
        # The graph will load the loader-listed rel, and the byte-identical
        # twin appears nowhere - one option, represented by the authored name.
        names = [c["name"] for c in dial["choices"]]
        self.assertEqual(names, [BYPASS2, BYPASS3])
        self.assertNotIn(BYPASS2_TWIN, names)

    def test_a_variant_that_is_not_installed_is_never_offered(self):
        dial = self.bypass_dial(self.options({BYPASS2: PATCH2,
                                              BYPASS2_TWIN: PATCH2}))
        self.assertEqual([c["value"] for c in dial["choices"]], [2])


if __name__ == "__main__":
    unittest.main()
