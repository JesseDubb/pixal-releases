"""The compat report behind the status dot: pack attribution and the
/api/comfy/compat handler, exercised without a live ComfyUI."""
import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp

_SPEC = spec_from_file_location("pixal_server", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


class PackAttribution(unittest.TestCase):
    def test_installed_nodes_attribute_through_python_module(self):
        self.assertEqual(server._pack_of("SeedVr2Upscale",
                                         "custom_nodes.seedvr2_videoupscaler"),
                         "seedvr2_videoupscaler")
        self.assertEqual(server._pack_of("KSampler", "nodes"), "ComfyUI core")
        self.assertEqual(server._pack_of("SaveAudio", "comfy_extras.nodes_audio"),
                         "ComfyUI core")

    def test_known_families_attribute_by_name_over_python_module(self):
        # a `from nodes import *` pack (comfyui_fearnworksnodes) makes ComfyUI
        # re-stamp earlier packs' nodes as its own - the name tier must win
        self.assertEqual(server._pack_of("VHS_VideoCombine",
                                         "custom_nodes.comfyui_fearnworksnodes"),
                         "ComfyUI-VideoHelperSuite")
        self.assertEqual(server._pack_of("PiDUpscale",
                                         "custom_nodes.comfyui_fearnworksnodes"),
                         "ComfyUI-PiD")

    def test_missing_nodes_fall_back_to_the_hint_table(self):
        self.assertEqual(server._pack_of("H3MultishotSampler", ""), "ComfyUI-H3-Multishot")
        self.assertEqual(server._pack_of("PiDUpscale", ""), "ComfyUI-PiD")
        self.assertEqual(server._pack_of("LTXVScheduler", ""), "ComfyUI-LTXVideo")
        # a missing core node means ComfyUI itself is the problem
        self.assertEqual(server._pack_of("KSampler", ""), "ComfyUI core")

    def test_wants_covers_templates_and_code_built_graphs(self):
        wanted = server._pixal_node_wants()
        self.assertIn("KSampler", wanted)                       # template library
        self.assertIn(server.H3_MULTISHOT_NODE, wanted)         # built in code
        self.assertIn(server.PID_DECODE_NODE, wanted)
        for node in server.VIDEO_UPSCALE_NODES:
            self.assertIn(node, wanted)


class CompatEndpoint(unittest.TestCase):
    def run_handler(self, names, modules, comfy_up=True):
        with patch.object(server, "refresh_comfy_nodes",
                          AsyncMock(return_value=names)), \
             patch.dict(server._COMFY_NODES, {"names": names, "modules": modules}), \
             patch.object(server.aiohttp, "ClientSession",
                          side_effect=aiohttp.ClientError), \
             patch.object(server.HUB, "comfy_up", comfy_up):
            resp = asyncio.run(server.comfy_compat(None))
        return json.loads(resp.text)

    def test_missing_pack_is_named_and_alternates_collapse(self):
        wanted = server._pixal_node_wants()
        # everything installed except PiD; only Deno's video upscaler present
        names = frozenset(wanted - {server.PID_UPSCALE_NODE, server.PID_DECODE_NODE,
                                    server.VIDEO_UPSCALE_NODES[1]})
        modules = {n: "custom_nodes.SomePack" for n in names}
        data = self.run_handler(names, modules)
        packs = {p["name"]: p for p in data["packs"]}
        self.assertIn("ComfyUI-PiD", packs)
        self.assertFalse(packs["ComfyUI-PiD"]["ok"])
        self.assertEqual({n["name"] for n in packs["ComfyUI-PiD"]["nodes"] if not n["ok"]},
                         {server.PID_UPSCALE_NODE, server.PID_DECODE_NODE})
        # the absent RTX alternative is not reported as a gap
        reported = {n["name"] for p in data["packs"] for n in p["nodes"]}
        self.assertNotIn(server.VIDEO_UPSCALE_NODES[1], reported)
        self.assertTrue(data["connected"])
        self.assertTrue(data["probed"])

    def test_never_probed_reports_nothing_installed(self):
        data = self.run_handler(None, {}, comfy_up=False)
        self.assertFalse(data["probed"])
        self.assertFalse(data["connected"])
        self.assertTrue(all(not n["ok"] for p in data["packs"] for n in p["nodes"]))


if __name__ == "__main__":
    unittest.main()
