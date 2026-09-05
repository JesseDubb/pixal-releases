"""Frozen ed5fa71 Z-Image graphs; never regenerate these to fix a failure."""
import json
from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import patch

import server

FIXTURE = Path(__file__).parent / "fixtures" / "zimage_10_14.json"


def build_case(module, case):
    with ExitStack() as stack:
        stack.enter_context(patch.object(module, "resolve_model_entry", return_value=case["model_entry"]))
        stack.enter_context(patch.object(module, "_catalog_has", return_value=True))
        stack.enter_context(patch.object(module, "_catalog_resolve", side_effect=lambda kind, rel: rel))
        stack.enter_context(patch.object(module, "resolve_lora", side_effect=lambda name: name))
        stack.enter_context(patch.object(module, "lora_profile", return_value={"family": "zimage", "variant": "any"}))
        stack.enter_context(patch.object(module, "load_config", return_value={"vae": {}}))
        stack.enter_context(patch.object(module, "CHARACTERS", {}))
        return getattr(module, case["builder"])(case["scene"], case["seed"], **case["options"])


class ZImageFixtureParityTests(unittest.TestCase):
    def test_frozen_checkpoint_graph_caption_and_info_bytes(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["checkpoint"], "ed5fa71")
        self.assertEqual(len(fixture["cases"]), 48)
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                result = build_case(server, case)
                self.assertEqual(json.dumps(result, sort_keys=True), case["expected"])

    def test_patch_points_are_observed_by_the_family_call(self):
        case = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"][0]
        with patch.object(server, "set_unet_loader", wraps=server.set_unet_loader) as unet, \
                patch.object(server, "apply_lora_nodes", wraps=server.apply_lora_nodes) as loras, \
                patch.object(server, "_character_caption", return_value=("patched caption", None)) as caption:
            graph, text, info = build_case(server, case)
        unet.assert_called_once()
        loras.assert_called_once()
        caption.assert_called_once()
        self.assertEqual(text, "patched caption")
        self.assertEqual(graph["4"]["inputs"]["text"], text)

    def test_resolved_assembler_is_repeatable_without_io_or_input_mutation(self):
        import copy
        from pixal.recipes.families import zimage
        case = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"][2]
        with patch.object(zimage, "build_zimage", wraps=zimage.build_zimage) as assembly:
            expected = build_case(server, case)
        inputs = assembly.call_args.kwargs
        before = copy.deepcopy({key: value for key, value in inputs.items() if not callable(value)})
        with ExitStack() as stack:
            for target in ("pathlib.Path.read_text", "pathlib.Path.read_bytes",
                           "pathlib.Path.write_text", "pathlib.Path.open",
                           "subprocess.Popen", "aiohttp.ClientSession"):
                stack.enter_context(patch(target, side_effect=AssertionError("pure assembly performed I/O")))
            for _ in range(2):
                self.assertEqual(zimage.build_zimage(**inputs), expected)
        self.assertEqual({key: value for key, value in inputs.items() if not callable(value)}, before)
