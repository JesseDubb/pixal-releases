"""The curated sampler pairs: our measurements, in the product.

The sampler card's "model" segment reads a "Recommended settings:" line off
the model's own Civitai description. On this machine 3 of 51 models carry one
and all three are Z-Image - so on Krea 2 and MiniMax H3, the two families in
daily use, that control has never once been clickable (Jesse, 2026-08-31:
"Model has never been selectable"). Krea 2's seat also offers 182 sampler
names, which is not a list anyone picks a good one out of.

So the presets. What these tests protect is not the numbers - those will move
as more gets measured - but the two properties that make them safe: a preset
is never offered to a seat that cannot run it, and it never claims a
measurement it does not have.
"""
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch


_SPEC = spec_from_file_location(
    "pixal_server_presets", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

H3_STILL = "h3_ref_still"
KREA = "realism"


def seat_of(base):
    return server.sampler_seat(base, "")


class TableTests(unittest.TestCase):

    def test_the_two_families_in_daily_use_have_presets(self):
        for family in ("minimax_h3", "krea2"):
            with self.subTest(family=family):
                self.assertTrue(server.SAMPLER_PRESETS.get(family))

    def test_every_preset_names_where_it_came_from(self):
        """A preset that does not say whether it was measured here or read off
        somebody's documentation is a preset that gets trusted too hard."""
        for family, presets in server.SAMPLER_PRESETS.items():
            for p in presets:
                with self.subTest(family=family, preset=p["id"]):
                    self.assertTrue(p.get("note", "").strip())
                    self.assertTrue(p.get("label", "").strip())
                    self.assertTrue(p.get("tuning"))

    def test_the_krea_presets_do_not_claim_to_be_measured(self):
        """They are RES4LYF's published figures for the Qwen-Image family, and
        the note says so. Only H3's were rendered on this box."""
        for p in server.SAMPLER_PRESETS["krea2"]:
            if p["id"] == "fast":
                continue        # the shipped default, not a claim about quality
            with self.subTest(preset=p["id"]):
                self.assertIn("not measured here", p["note"].lower())

    def test_no_preset_sets_cfg(self):
        """Both families are distilled and cfg_locked pins cfg at 1. A preset
        that moved it would fight the lock rather than the model."""
        for presets in server.SAMPLER_PRESETS.values():
            for p in presets:
                self.assertNotIn("cfg", p["tuning"])

    def test_h3_never_offers_a_scheduler_it_measured_as_dead(self):
        """karras, exponential and kl_optimal scored 1.1-1.2 stars over
        hundreds of community votes on H3."""
        dead = {"karras", "exponential", "kl_optimal"}
        for p in server.SAMPLER_PRESETS["minimax_h3"]:
            self.assertNotIn(p["tuning"].get("scheduler"), dead)


class FilteringTests(unittest.TestCase):
    """A preset is offered only when the seat can actually run it."""

    def test_a_value_the_seat_does_not_offer_drops_the_whole_preset(self):
        seat = seat_of(H3_STILL)
        self.assertIsNotNone(seat)
        with patch.object(server, "seat_choices",
                          return_value={"sampler_name": ["res_multistep"],
                                        "scheduler": ["simple"]}):
            got = server.sampler_presets(H3_STILL, "")
        ids = {p["id"] for p in got}
        self.assertIn("speed", ids)          # res_multistep/simple survives
        self.assertNotIn("detail", ids)      # dpmpp_sde_gpu/beta does not
        self.assertNotIn("community", ids)

    def test_a_key_the_seat_lacks_is_dropped_not_written(self):
        """H3's KSamplerSelect has no eta. A Krea-shaped preset must not put
        one in the payload - the node has no such input."""
        with patch.object(server, "seat_tuning_keys",
                          return_value=("steps", "sampler_name", "scheduler")), \
             patch.object(server, "seat_choices", return_value={}):
            for p in server.sampler_presets(H3_STILL, ""):
                self.assertNotIn("eta", p["tuning"])

    def test_an_unknown_recipe_yields_nothing_rather_than_raising(self):
        self.assertEqual(server.sampler_presets("no_such_recipe", ""), [])

    def test_a_family_with_no_table_yields_nothing(self):
        with patch.dict(server.SAMPLER_PRESETS, {}, clear=True):
            self.assertEqual(server.sampler_presets(H3_STILL, ""), [])

    def test_h3_stills_and_h3_video_get_different_answers(self):
        """The lanes were A/B'd separately and disagreed, which is why the
        server's own sampler constants are already split."""
        with patch.object(server, "seat_choices", return_value={}):
            still = {p["id"] for p in server.sampler_presets(H3_STILL, "")}
            video = {p["id"] for p in server.sampler_presets("h3_i2v", "")}
        self.assertIn("detail", still)
        self.assertNotIn("video_detail", still)
        if video:
            self.assertNotIn("speed", video)


class PayloadTests(unittest.TestCase):

    def test_the_seat_endpoint_publishes_them(self):
        src = (Path(__file__).resolve().parents[1] / "server.py") \
            .read_text(encoding="utf-8")
        self.assertIn('"presets": sampler_presets(base_id, model) if seat else []',
                      src)

    def test_the_card_renders_and_applies_them(self):
        jsx = (Path(__file__).resolve().parents[1] / "web" / "src" /
               "components" / "Composer.jsx").read_text(encoding="utf-8")
        self.assertIn("const presets = seat.presets || []", jsx)
        self.assertIn("const applyPreset = (p) =>", jsx)
        self.assertIn("known good", jsx)


if __name__ == "__main__":
    unittest.main()
