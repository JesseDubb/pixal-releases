"""Special decoders (Settings > Image): the Wan 2.1 2x VAE swapped in for the
recipe's VAEDecode, through ComfyUI-VAE-Utils.

  Off          - default config leaves every graph untouched.
  Krea2Only    - without force only realism / realism_ii change; a Qwen-latent
                 edit lane keeps its VAEDecode.
  Force        - with force the same edit lane decodes through the 2x VAE,
                 while its VAEEncode still reads the recipe's own VAE loader.
  Foreign      - a Flux-VAE graph (Klein) is never touched, forced or not.
  Missing      - a missing node pack or VAE file records why and leaves the
                 graph alone rather than posting a graph ComfyUI rejects.
  Settings     - the save endpoint refuses an unknown decoder id.
"""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("server", Path(__file__).resolve().parents[1] / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

WAN2X = server.SPECIAL_DECODERS["wan2x"]


def krea_graph():
    return {"1": {"class_type": "VAELoader", "inputs": {"vae_name": server.KREA_VAE_REALISM}},
            "2": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["1", 0]}},
            "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}}}


def edit_graph():
    return {"1": {"class_type": "VAELoader", "inputs": {"vae_name": server.QWEN_EDIT_VAE}},
            "2": {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0], "vae": ["1", 0]}},
            "3": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["1", 0]}}}


def klein_graph():
    return {"1": {"class_type": "VAELoader", "inputs": {"vae_name": server.KLEIN_VAE}},
            "2": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["1", 0]}}}


def cfg(special="wan2x", force=False):
    return {"vae": {"zimage": "", "special": special, "special_force": force}}


class SpecialDecoderTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.object(server, "_catalog_has", return_value=True),
                        patch.object(server, "_node_available", return_value=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_off_by_default_leaves_the_graph_alone(self):
        g = krea_graph(); info = {}
        self.assertIsNone(server.apply_special_decoder(g, "realism", info, cfg(special="")))
        self.assertEqual(g["2"]["class_type"], "VAEDecode")
        self.assertNotIn("decoder", info)
        with patch.object(server, "CONFIG", Path("nope") / "missing.json"):
            self.assertEqual(server.load_config()["vae"]["special"], "")

    def test_krea2_stills_decode_through_the_2x_vae(self):
        g = krea_graph(); info = {}
        self.assertIs(server.apply_special_decoder(g, "realism", info, cfg()), WAN2X)
        self.assertEqual(g["2"]["class_type"], WAN2X["decoder"])
        self.assertEqual(g["2"]["inputs"]["upscale"], -1)
        loader = g[g["2"]["inputs"]["vae"][0]]
        self.assertEqual(loader["class_type"], WAN2X["loader"])
        self.assertEqual(loader["inputs"]["vae_name"], WAN2X["vae"])
        self.assertEqual(info["decoder"], WAN2X["label"])
        self.assertEqual(info["decoder_factor"], 2)

    def test_without_force_only_the_krea2_stills_change(self):
        g = edit_graph(); info = {}
        self.assertIsNone(server.apply_special_decoder(g, "qwen_edit", info, cfg()))
        self.assertEqual(g["3"]["class_type"], "VAEDecode")

    def test_force_widens_to_the_edit_lane_but_the_encoder_keeps_its_vae(self):
        g = edit_graph(); info = {}
        self.assertIs(server.apply_special_decoder(g, "qwen_edit", info, cfg(force=True)), WAN2X)
        self.assertEqual(g["3"]["class_type"], WAN2X["decoder"])
        self.assertEqual(g["2"]["class_type"], "VAEEncode")
        self.assertEqual(g["2"]["inputs"]["vae"], ["1", 0])          # the recipe's own loader
        self.assertEqual(g["1"]["inputs"]["vae_name"], server.QWEN_EDIT_VAE)
        self.assertNotEqual(g["3"]["inputs"]["vae"][0], "1")

    def test_a_flux_vae_graph_is_never_touched(self):
        for force in (False, True):
            g = klein_graph(); info = {}
            self.assertIsNone(server.apply_special_decoder(g, "klein_edit", info, cfg(force=force)))
            self.assertEqual(g["2"]["class_type"], "VAEDecode")

    def test_missing_pack_or_file_records_why_and_skips(self):
        with patch.object(server, "_node_available", return_value=False):
            g = krea_graph(); info = {}
            self.assertIsNone(server.apply_special_decoder(g, "realism", info, cfg()))
            self.assertIn("ComfyUI-VAE-Utils", info["special_decoder_skipped"])
            self.assertEqual(g["2"]["class_type"], "VAEDecode")
        with patch.object(server, "_catalog_has", return_value=False):
            g = krea_graph(); info = {}
            self.assertIsNone(server.apply_special_decoder(g, "realism", info, cfg()))
            self.assertIn("missing", info["special_decoder_skipped"])

    def test_the_render_path_calls_the_swap_after_the_sampler_swap(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        i = src.index("swap_sampler_node(g, sampler_swap_tag)")
        j = src.index("apply_special_decoder(g, template, info)")
        k = src.index("validate_job_model_info(template, info, g)")
        self.assertTrue(i < j < k)


if __name__ == "__main__":
    unittest.main()
