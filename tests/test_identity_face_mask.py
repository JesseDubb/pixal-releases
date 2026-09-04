import asyncio
import hashlib
import json
import os
import unittest
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from PIL import Image


_SPEC = spec_from_file_location(
    "pixal_server_identity_face_mask",
    Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


WHOLE = "whole"
FACE = "face"
REFERENCE_SIZE = (37, 23)
# Captured from the pre-brief builder with the fixed fixture below. This pins
# the graph Jesse's existing renders use; adding truthful info is allowed, but
# Whole reference may not add, remove, or change a graph node or input.
PRE_CHANGE_GRAPH_SHA256 = (
    "6f8d8d805f639be4052cc04bb26266c2ad25acce5f45a7da63311d57ffb16ffe")


def model(rel, family, variant="any", **extra):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True, **extra}


KREA = model(server.RECIPE_SPECS["identity_edit"]["default_model"], "krea2")


@contextmanager
def assets(entry=KREA):
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(server, "resolve_model_entry", return_value=entry))
        stack.enter_context(patch.object(server, "_catalog_has", return_value=True))
        stack.enter_context(patch.object(
            server, "_catalog_resolve", side_effect=lambda kind, rel: rel))
        stack.enter_context(
            patch.object(server, "resolve_lora", side_effect=lambda name: name))
        stack.enter_context(patch.object(
            server, "identity_patch_variants",
            return_value={"r128": server.IDENTITY_LORA}))
        yield


@contextmanager
def identity_anchor():
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        Image.new("RGB", REFERENCE_SIZE, "black").save(
            root / "input" / "hero.png")
        character = {"id": "hero", "name": "Hero", "style": "silver hair",
                     "identity_ref": "hero.png"}
        with patch.object(server, "CDIR", root), \
             patch.object(server, "CHARACTERS", {"hero": character}):
            yield root, character


def build(**kwargs):
    return server.build_zara_edit(
        "restage", 7, character="hero", pid=False, **kwargs)


def graph_digest(graph):
    raw = json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def mask_nodes(graph):
    return {node_id: node for node_id, node in graph.items()
            if node.get("class_type") == "LoadImageMask"}


class IdentityFaceMaskBuildTests(unittest.TestCase):
    def test_face_only_wires_a_reference_sized_red_channel_mask(self):
        boxes = [(7.0, 3.0, 25.0, 20.0)]
        with identity_anchor() as (root, _character), assets(), \
             patch.object(server, "find_faces", return_value=boxes) as detector, \
             patch.object(server, "face_mask",
                          wraps=server.face_mask) as ellipse_mask:
            graph, _caption, info = build(ref_boost_mask=FACE)

            detector.assert_called_once_with(root / "input" / "hero.png")
            ellipse_mask.assert_called_once_with(REFERENCE_SIZE, boxes)
            self.assertEqual(len(mask_nodes(graph)), 1)
            node_id, node = next(iter(mask_nodes(graph).items()))
            self.assertEqual(node["inputs"]["channel"], "red")
            self.assertEqual(graph["ed:patch"]["inputs"]["ref_boost_mask"],
                             [node_id, 0])
            self.assertEqual(graph["ed:patch"]["inputs"]["source_image"],
                             ["ed:img", 0])
            staged = root / "input" / node["inputs"]["image"]
            with Image.open(staged) as opened:
                self.assertEqual(opened.size, REFERENCE_SIZE)
                self.assertEqual(opened.mode, "L")
            canvas = (graph["30:5"]["inputs"]["width"],
                      graph["30:5"]["inputs"]["height"])
            self.assertNotEqual(REFERENCE_SIZE, canvas)
            self.assertEqual(info["ref_boost_mask"], "face")

        with identity_anchor(), assets(), \
             patch.object(server, "find_faces", return_value=boxes), \
             patch.object(server, "face_mask", side_effect=OSError("disk full")), \
             patch("builtins.print") as logged:
            graph, _caption, info = build(ref_boost_mask=FACE)
        self.assertEqual(mask_nodes(graph), {})
        self.assertNotIn("ref_boost_mask", graph["ed:patch"]["inputs"])
        self.assertEqual(info["ref_boost_mask"], "whole")
        self.assertTrue(any("unavailable for hero.png" in str(call.args[0])
                            for call in logged.call_args_list if call.args))

    def test_no_face_found_falls_back_to_the_whole_reference(self):
        with identity_anchor(), assets(), \
             patch.object(server, "find_faces", return_value=[]), \
             patch("builtins.print") as logged:
            graph, _caption, info = build(ref_boost_mask=FACE)

        self.assertNotIn("ref_boost_mask", graph["ed:patch"]["inputs"])
        self.assertEqual(mask_nodes(graph), {})
        self.assertEqual(info["ref_boost_mask"], "whole (no face found)")
        lines = [str(call.args[0]) for call in logged.call_args_list if call.args]
        self.assertEqual(
            [line for line in lines if line.startswith("[pixal] identity boost")],
            ["[pixal] identity boost face mask: no face found in hero.png; "
             "using whole reference"])

    def test_no_finder_falls_back_to_the_whole_reference(self):
        with identity_anchor(), assets(), \
             patch.object(server, "find_faces", return_value=None), \
             patch("builtins.print") as logged:
            graph, _caption, info = build(ref_boost_mask=FACE)

        self.assertNotIn("ref_boost_mask", graph["ed:patch"]["inputs"])
        self.assertEqual(mask_nodes(graph), {})
        self.assertEqual(info["ref_boost_mask"], "whole (no finder)")
        lines = [str(call.args[0]) for call in logged.call_args_list if call.args]
        self.assertEqual(
            [line for line in lines if line.startswith("[pixal] identity boost")],
            ["[pixal] identity boost face mask: no finder for hero.png; "
             "using whole reference"])

    def test_whole_reference_preserves_the_pre_change_graph(self):
        with identity_anchor(), assets(), \
             patch.object(server, "find_faces") as detector:
            graph, _caption, info = build()

            self.assertEqual(graph_digest(graph), PRE_CHANGE_GRAPH_SHA256)
            self.assertEqual(mask_nodes(graph), {})
            self.assertNotIn("ref_boost_mask", graph["ed:patch"]["inputs"])
            detector.assert_not_called()
            self.assertEqual(info["ref_boost_mask"], "whole")

            explicit, _caption, explicit_info = build(ref_boost_mask=WHOLE)
            self.assertEqual(graph, explicit)
            self.assertEqual(explicit_info["ref_boost_mask"], "whole")
            detector.assert_not_called()

    def test_unchanged_reference_reuses_the_staged_mask_until_mtime_changes(self):
        boxes = [(7.0, 3.0, 25.0, 20.0)]
        with identity_anchor() as (root, _character), assets(), \
             patch.object(server, "find_faces", return_value=boxes) as detector:
            first, _caption, _info = build(ref_boost_mask=FACE)
            second, _caption, _info = build(ref_boost_mask=FACE)
            first_name = next(iter(mask_nodes(first).values()))["inputs"]["image"]
            second_name = next(iter(mask_nodes(second).values()))["inputs"]["image"]
            self.assertEqual(first_name, second_name)
            self.assertEqual(detector.call_count, 1)
            self.assertEqual(len(list((root / "input").glob("*.png"))), 2)

            ref_path = root / "input" / "hero.png"
            old = ref_path.stat().st_mtime_ns
            other_path = root / "input" / "other.png"
            Image.new("RGB", REFERENCE_SIZE, "black").save(other_path)
            os.utime(other_path, ns=(old, old))
            other_name, status = server._stage_identity_face_mask("other.png")
            self.assertEqual(status, "face")
            self.assertNotEqual(other_name, first_name)
            self.assertEqual(detector.call_count, 2)

            os.utime(ref_path, ns=(old + 10_000_000, old + 10_000_000))
            changed, _caption, _info = build(ref_boost_mask=FACE)
            changed_name = next(iter(mask_nodes(changed).values()))["inputs"]["image"]
            self.assertNotEqual(changed_name, first_name)
            self.assertEqual(detector.call_count, 3)


class IdentityFaceMaskDialTests(unittest.TestCase):
    def test_options_exposes_the_two_choice_identity_card_control(self):
        dial = next(d for d in server.RECIPE_SPECS["identity_edit"]["dials"]
                    if d["key"] == "ref_boost_mask")
        self.assertEqual(dial["kind"], "choice")
        self.assertEqual(dial["stage"], "identity_edit")
        self.assertEqual(dial["label"], "Boost region")
        self.assertEqual(dial["default"], WHOLE)
        self.assertEqual([(c["value"], c["label"]) for c in dial["choices"]],
                         [(WHOLE, "Whole reference"), (FACE, "Face only")])
        self.assertIn("ref_boost_mask", server.SIGS["identity_edit"])

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
        identity = next(r for r in options["recipes"]
                        if r["id"] == "identity_edit")
        payload = next(d for d in identity["dials"]
                       if d["key"] == "ref_boost_mask")
        self.assertEqual(payload, dial)

    def test_submitted_choice_survives_validation_and_bad_input_degrades(self):
        with identity_anchor():
            args = {}
            server._apply_opts(
                args, {"engine": "identity_edit", "character": "hero",
                       "ref_boost_mask": FACE})
            self.assertEqual(args["ref_boost_mask"], FACE)

            args = {}
            server._apply_opts(
                args, {"engine": "identity_edit", "character": "hero",
                       "ref_boost_mask": "not-a-region"})
            self.assertEqual(args["ref_boost_mask"], WHOLE)

        args = {}
        server._apply_opts(
            args, {"engine": "realism", "ref_boost_mask": FACE})
        self.assertNotIn("ref_boost_mask", args)


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class IdentityFaceMaskRerollTests(unittest.TestCase):
    ENTRY = {"id": "abc12345", "template": "identity_edit",
             "scene": "restage her", "seed": 424242, "count": 1,
             "spec": {"character": "hero", "ref_boost_mask": WHOLE}}

    def test_reroll_carries_the_live_boost_region(self):
        submit = AsyncMock()
        with patch.object(server.HUB, "ledger_read",
                          return_value=[dict(self.ENTRY)]), \
             patch.object(server.HUB, "submit", submit):
            async def run():
                await server.reroll(FakeRequest(
                    {"id": "abc12345", "ref_boost_mask": FACE}))
                await asyncio.sleep(0)
            asyncio.run(run())

        self.assertEqual(submit.call_args.args[4]["ref_boost_mask"], FACE)

        # The current composer also sends its complete intent in `opts`; that
        # route clears the card's stored dial and re-applies the live choice.
        submit = AsyncMock()
        with identity_anchor(), \
             patch.object(server.HUB, "ledger_read",
                          return_value=[dict(self.ENTRY)]), \
             patch.object(server.HUB, "submit", submit):
            async def run_current_route():
                await server.reroll(FakeRequest({
                    "id": "abc12345",
                    "opts": {"engine": "identity_edit", "character": "hero",
                             "ref_boost_mask": FACE},
                }))
                await asyncio.sleep(0)
            asyncio.run(run_current_route())

        self.assertEqual(submit.call_args.args[4]["ref_boost_mask"], FACE)


if __name__ == "__main__":
    unittest.main()
