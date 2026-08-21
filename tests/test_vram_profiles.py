"""VRAM profiles: tier bucketing, the auto/pinned override, and the honest
H3 note. Advisory layer only - the butler tests live in test_recipes."""
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

_SPEC = spec_from_file_location("pixal_server", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


class TierBuckets(unittest.TestCase):
    def test_real_cards_land_in_their_tier(self):
        self.assertEqual(server.vram_tier(31.8), "32")   # 5090 reads just under
        self.assertEqual(server.vram_tier(23.9), "24")   # 3090/4090 read just under
        self.assertEqual(server.vram_tier(15.9), "16")   # 16GB cards read just under
        self.assertEqual(server.vram_tier(11.9), "low")

    def test_exact_boundaries(self):
        self.assertEqual(server.vram_tier(30.0), "32")
        self.assertEqual(server.vram_tier(22.0), "24")
        self.assertEqual(server.vram_tier(14.0), "16")

    def test_unknown_is_none_not_a_guess(self):
        self.assertIsNone(server.vram_tier(None))
        self.assertIsNone(server.vram_tier(0))
        self.assertIsNone(server.vram_tier("what"))


class ProfileState(unittest.TestCase):
    def test_auto_follows_the_card(self):
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "auto"}), \
             patch.object(server.HUB, "gpu", {"total": 31.8}):
            state = server.vram_profile_state()
        self.assertEqual(state["effective"], "32")
        self.assertEqual(state["detected"], "32")

    def test_pin_overrides_the_card(self):
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "16"}), \
             patch.object(server.HUB, "gpu", {"total": 31.8}):
            state = server.vram_profile_state()
        self.assertEqual(state["effective"], "16")
        self.assertEqual(state["detected"], "32")   # detection stays honest

    def test_comfy_down_means_unknown(self):
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "auto"}), \
             patch.object(server.HUB, "gpu", None):
            state = server.vram_profile_state()
        self.assertIsNone(state["effective"])


class HonestH3Note(unittest.TestCase):
    def test_a_32gb_card_gets_no_note(self):
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "auto"}), \
             patch.object(server.HUB, "gpu", {"total": 31.8}):
            self.assertIsNone(server.vram_fit_note("h3"))

    def test_a_16gb_card_gets_the_measured_truth(self):
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "auto"}), \
             patch.object(server.HUB, "gpu", {"total": 15.9}):
            note = server.vram_fit_note("h3")
        self.assertIn("24", note)
        self.assertIn("15.9", note)
        self.assertIn("5x slower", note)     # runs-but-slower, never "won't run"

    def test_a_pinned_profile_names_the_pin_not_the_card(self):
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "16"}), \
             patch.object(server.HUB, "gpu", {"total": 31.8}):
            note = server.vram_fit_note("h3")
        self.assertIn("pinned profile is 16 GB", note)

    def test_unknown_card_makes_no_claim(self):
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "auto"}), \
             patch.object(server.HUB, "gpu", None):
            self.assertIsNone(server.vram_fit_note("h3"))

    def test_unmeasured_engines_make_no_claim(self):
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "16"}), \
             patch.object(server.HUB, "gpu", {"total": 15.9}):
            self.assertIsNone(server.vram_fit_note("ltx"))


if __name__ == "__main__":
    unittest.main()
