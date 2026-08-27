import asyncio
import json
import os
import struct
import unittest
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch


_SPEC = spec_from_file_location(
    "pixal_server_identity_build", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


# This box's Krea 2 folder, verbatim (brief 9.56): the three v1.2 builds side
# by side, plus the byte-identical copy of the full build at the loras/ root.
FULL = "Krea 2\\krea2_identity_edit_v1_2.safetensors"
FULL_TWIN = "krea2_identity_edit_v1_2.safetensors"
R128 = "Krea 2\\krea2_identity_edit_v1_2_r128.safetensors"
R64 = "Krea 2\\krea2_identity_edit_v1_2_r64.safetensors"
BYPASS2 = "Krea 2\\krea2filterbypass.safetensors"

# The real weights' sizes, so the option titles can be asserted against the
# model card's own numbers.
FULL_SIZE = 1828256432      # "1.8 GB"
R128_SIZE = 914159744       # "914 MB"
R64_SIZE = 457111048        # "457 MB"


def patch_bytes(vectors):
    """A projector-patch safetensors, the layout _vector_patch_count reads -
    needed so the identity recipe's OTHER locked stage resolves in these
    catalogs."""
    data = struct.pack("<%df" % len(vectors), *vectors)
    header = json.dumps({
        "lora_unet" + server._VECTOR_PATCH_SUFFIX: {
            "dtype": "F32", "shape": [1, len(vectors)],
            "data_offsets": [0, len(data)]},
    }).encode()
    return struct.pack("<Q", len(header)) + header + data


PATCH2 = patch_bytes([0.5, -0.5])


@contextmanager
def lora_catalog(files):
    """A faked LoRA catalog: {rel: bytes | (bytes, size)} written under one
    temp root, with model_catalog returning it for loras and nothing for
    every other kind. A (bytes, size) pair truncates the file to the size so
    the catalog's measured weight - and therefore the option title - is the
    real build's. The Civitai by-hash cache is emptied for the duration so no
    record from a real run can leak into the sha path."""
    with TemporaryDirectory() as td:
        root = Path(td)
        entries = []
        for rel, spec in files.items():
            data, size = spec if isinstance(spec, tuple) else (spec, None)
            path = root / "loras" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if size is not None:
                os.truncate(path, size)
            stat = path.stat()
            entries.append({"rel": rel, "root": str(root), "kind": "loras",
                            "mtime": stat.st_mtime, "size": stat.st_size})
        with patch.object(server, "model_catalog",
                          side_effect=lambda kind=None, ttl=30:
                          entries if kind == "loras" else []), \
             patch.dict(server._CIV, {"data": {}}):
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
FULL_CATALOG = {FULL: b"full-build-bytes", FULL_TWIN: b"full-build-bytes",
                R128: b"r128-build-bytes", R64: b"r64-build-bytes",
                BYPASS2: PATCH2}


def lora_loaders(graph):
    return {nid: node for nid, node in graph.items()
            if node.get("class_type") == "LoraLoaderModelOnly"}


class IdentityPatchScanTests(unittest.TestCase):
    """Which v1.2 builds are installed (brief 9.56): the build id comes out
    of the filename, only v1.2 counts, and byte-identical twins are ONE
    option."""

    def test_the_three_builds_parse_in_the_authors_quality_order(self):
        with lora_catalog({R64: b"r64", FULL: b"full", R128: b"r128"}):
            variants = server.identity_patch_variants()
        self.assertEqual(list(variants), ["full", "r128", "r64"])
        self.assertEqual(variants, {"full": FULL, "r128": R128, "r64": R64})

    def test_older_versions_on_disk_are_ignored(self):
        with lora_catalog({
                R128: b"r128",
                "Krea 2\\krea2_identity_edit_v1_1.safetensors": b"old",
                "Krea 2\\krea2_identity_edit_v1_1_r128.safetensors": b"old",
                "Krea 2\\krea2_identity_edit_v1.safetensors": b"older",
                "Krea 2\\krea2filterbypass.safetensors": PATCH2}):
            variants = server.identity_patch_variants()
        self.assertEqual(variants, {"r128": R128})

    def test_byte_identical_twins_collapse_to_one_option(self):
        with lora_catalog({FULL: b"same-bytes", FULL_TWIN: b"same-bytes",
                           R128: b"r128"}):
            variants = server.identity_patch_variants()
        # One full-build option, not two - and the foldered rel represents it
        # (it sorts ahead of the root twin, the same rule the bypass scan
        # uses for its "2vector" twin).
        self.assertEqual(variants, {"full": FULL, "r128": R128})


class IdentityBuildChoiceTests(unittest.TestCase):
    """Choice values are strings here (brief 9.56): an installed build
    passes, an unknown one degrades to the r128 default, and the default
    itself always passes - the same degrade-never-die policy as the number
    dials."""

    DIAL = server.IDENTITY_BUILD_DIAL

    def test_an_installed_build_passes(self):
        with lora_catalog(FULL_CATALOG):
            for build in ("full", "r128", "r64"):
                with self.subTest(identity_build=build):
                    self.assertEqual(
                        server.recipe_dial_value(self.DIAL, build), build)

    def test_an_unknown_build_lands_on_the_default(self):
        with lora_catalog(FULL_CATALOG):
            for bad in ("r256", "v1_2", "", 128, 2.5, True, None):
                with self.subTest(identity_build=bad):
                    self.assertEqual(
                        server.recipe_dial_value(self.DIAL, bad), "r128")

    def test_the_default_always_passes(self):
        # Even on a box whose r128 file is gone: the default names the
        # authored stage, which runs exactly as it always has.
        with lora_catalog({R64: b"r64", BYPASS2: PATCH2}):
            self.assertEqual(server.recipe_dial_value(self.DIAL, "r128"), "r128")

    def test_composer_choice_validates_on_the_way_in(self):
        with identity_anchor(), lora_catalog(FULL_CATALOG):
            args = {}
            server._apply_opts(args, {"engine": "identity_edit", "character": "hero",
                                      "identity_build": "full"})
            self.assertEqual(args["identity_build"], "full")
            for bad in ("r256", 128, 2.5, True, None):
                with self.subTest(identity_build=bad):
                    args = {}
                    server._apply_opts(args, {"engine": "identity_edit",
                                              "character": "hero",
                                              "identity_build": bad})
                    self.assertEqual(args["identity_build"], "r128")


class IdentityBuildBuildTests(unittest.TestCase):
    def test_the_default_remains_r128_and_the_graph_is_byte_identical(self):
        """The regression that matters most (brief 9.56): with no build
        touched the composer path must produce exactly today's graph, and an
        EXPLICIT default - what a re-roll's resolved dials always sends -
        builds the same bytes too."""
        dial = next(d for d in server.RECIPE_SPECS["identity_edit"]["dials"]
                    if d["key"] == "identity_build")
        self.assertEqual(dial["default"], "r128")
        with identity_anchor(), assets(KREA), lora_catalog(FULL_CATALOG):
            default_graph, _c, _i = server.build_zara_edit("restage", 7, character="hero")
            args = {}
            server._apply_opts(args, {"engine": "identity_edit", "character": "hero"})
            self.assertNotIn("identity_build", args)
            filtered = {k: v for k, v in args.items() if k in server.SIGS["identity_edit"]}
            composer_graph, _c, _i = server.build_zara_edit("restage", 7, **filtered)
            explicit, _c, _i = server.build_zara_edit("restage", 7, character="hero",
                                                      identity_build="r128")
        self.assertEqual(json.dumps(composer_graph, sort_keys=True),
                         json.dumps(default_graph, sort_keys=True))
        self.assertEqual(json.dumps(explicit, sort_keys=True),
                         json.dumps(default_graph, sort_keys=True))
        identity = next(n for n in lora_loaders(default_graph).values()
                        if n["inputs"]["lora_name"] == server.IDENTITY_LORA)
        self.assertEqual(identity["inputs"]["strength_model"], 1.0)

    def test_choosing_a_build_swaps_only_that_stage(self):
        """Chain order and every other node unchanged: the full-build graph
        is today's graph with one loader's lora_name swapped (brief 9.56) -
        the bypass stage in particular keeps its own file."""
        with identity_anchor(), assets(KREA), lora_catalog(FULL_CATALOG):
            base_graph, _c, _i = server.build_zara_edit("restage", 7, character="hero")
            for build, rel in (("full", FULL), ("r64", R64)):
                with self.subTest(identity_build=build):
                    swapped, _c, _i = server.build_zara_edit(
                        "restage", 7, character="hero", identity_build=build)
                    self.assertEqual(set(swapped), set(base_graph))
                    identity_id = next(
                        nid for nid, n in lora_loaders(base_graph).items()
                        if n["inputs"]["lora_name"] == server.IDENTITY_LORA)
                    for nid, node in base_graph.items():
                        if nid == identity_id:
                            continue
                        self.assertEqual(swapped[nid], node, nid)
                    before = base_graph[identity_id]["inputs"]
                    after = swapped[identity_id]["inputs"]
                    self.assertEqual(after["lora_name"], rel)
                    self.assertEqual(after["strength_model"], before["strength_model"])
                    self.assertEqual(after["model"], before["model"])
                    # The edit patch still hangs off the swapped node id.
                    self.assertEqual(swapped["ed:patch"]["inputs"]["model"],
                                     [identity_id, 0])

    def test_an_uninstalled_build_falls_back_to_the_authored_stage(self):
        """The builder-side guard for direct calls: a build the machine does
        not own degrades to the authored r128 stage rather than dying."""
        with identity_anchor(), assets(KREA), lora_catalog(FULL_CATALOG):
            default_graph, _c, _i = server.build_zara_edit("restage", 7, character="hero")
            for bad in ("r256", "v1_2", 128, 2.5, True):
                with self.subTest(identity_build=bad):
                    graph, _c, _i = server.build_zara_edit(
                        "restage", 7, character="hero", identity_build=bad)
                    self.assertEqual(json.dumps(graph, sort_keys=True),
                                     json.dumps(default_graph, sort_keys=True))

    def test_history_info_records_the_build_that_ran(self):
        """The row's name IS the swapped rel: the history lists the stack
        that actually ran, not the authored one."""
        with identity_anchor(), assets(KREA), lora_catalog(FULL_CATALOG):
            _g, _c, info = server.build_zara_edit("restage", 7, character="hero",
                                                  identity_build="r64")
        row = next(r for r in info["lora_stack"] if r.get("slot") == "identity_edit")
        self.assertEqual(row["name"], R64)
        self.assertIn("krea2_identity_edit_v1_2_r64@1", info["loras"])


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class IdentityBuildRerollTests(unittest.TestCase):
    """The build rides a re-roll exactly like the 9.14 dials and the bypass
    variant: "switch and re-roll" is the whole point of the control."""

    ENTRY = {"id": "abc12345", "template": "identity_edit", "scene": "restage her",
             "seed": 424242, "count": 1,
             "spec": {"character": "hero", "identity_build": "full"}}

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

    def test_a_reroll_carries_the_chosen_build(self):
        call = self.roll({"id": "abc12345", "identity_build": "r64"})
        self.assertEqual(call.args[4]["identity_build"], "r64")

    def test_an_omitted_build_keeps_the_stored_value(self):
        call = self.roll({"id": "abc12345"})
        self.assertEqual(call.args[4]["identity_build"], "full")

    def test_a_bad_or_uninstalled_build_falls_back_to_the_default(self):
        # Present-but-bad degrades to the constant, never a 4xx - and never to
        # the card's stored value, which the user has moved away from.
        for bad in ("r256", 128, 2.5, True, None):
            with self.subTest(identity_build=bad):
                call = self.roll({"id": "abc12345", "identity_build": bad})
                self.assertEqual(call.args[4]["identity_build"], "r128")

    def test_a_recipe_without_the_declaration_never_gets_the_key(self):
        entry = {"id": "r1234567", "template": "realism", "scene": "a shot",
                 "seed": 7, "count": 1,
                 "spec": {"aspect": "1:1 (Square)", "mp": 2.0, "standing": True}}
        call = self.roll({"id": "r1234567", "identity_build": "r64"}, entry=entry)
        self.assertNotIn("identity_build", call.args[4])


class IdentityBuildOptionsTests(unittest.TestCase):
    """Only what is installed is ever offered (brief 9.56): the choices ride
    /api/options so a build that would fail at queue time never shows, and
    the sizes ride the option titles (the labels stay short)."""

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

    def build_dial(self, options):
        identity = next(r for r in options["recipes"] if r["id"] == "identity_edit")
        return next(d for d in identity["dials"] if d["key"] == "identity_build")

    def test_all_three_builds_are_offered_with_sizes_in_the_titles(self):
        sized = {FULL: (b"full", FULL_SIZE), R128: (b"r128", R128_SIZE),
                 R64: (b"r64", R64_SIZE), BYPASS2: PATCH2}
        dial = self.build_dial(self.options(sized))
        self.assertEqual(dial["default"], "r128")
        self.assertEqual([(c["value"], c["label"]) for c in dial["choices"]],
                         [("full", "Full"), ("r128", "r128"), ("r64", "r64")])
        titles = [c["title"] for c in dial["choices"]]
        self.assertEqual(titles, [f"1.8 GB · {FULL}",
                                  f"914 MB · {R128}",
                                  f"457 MB · {R64}"])
        # The graph will load the loader-listed rel.
        self.assertEqual([c["name"] for c in dial["choices"]],
                         [FULL, R128, R64])

    def test_the_root_twin_appears_nowhere(self):
        dial = self.build_dial(self.options(FULL_CATALOG))
        names = [c["name"] for c in dial["choices"]]
        self.assertEqual(names, [FULL, R128, R64])
        self.assertNotIn(FULL_TWIN, names)

    def test_a_box_with_only_r128_lists_one_choice(self):
        dial = self.build_dial(self.options({R128: b"r128", BYPASS2: PATCH2}))
        self.assertEqual([c["value"] for c in dial["choices"]], ["r128"])

    def test_any_installed_build_makes_the_recipe_ready(self):
        # An r64-only box is as ready as an r128 one (brief 9.56): no missing
        # line names the identity LoRA. (Other lines - the diffusion model,
        # encoders - are absent from the stub catalog and expected here.)
        options = self.options({R64: b"r64", BYPASS2: PATCH2})
        identity = next(r for r in options["recipes"] if r["id"] == "identity_edit")
        self.assertFalse(any("krea2_identity" in m for m in identity["missing"]),
                         identity["missing"])

    def test_no_installed_build_still_names_the_lora(self):
        options = self.options({BYPASS2: PATCH2})
        identity = next(r for r in options["recipes"] if r["id"] == "identity_edit")
        self.assertIn("LoRA: " + server.IDENTITY_LORA, identity["missing"])


if __name__ == "__main__":
    unittest.main()
