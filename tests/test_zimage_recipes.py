"""Z-Image's schedule and its negative, re-sourced 2026-09-03.

Jesse, looking at three sets of base renders: "Zimage recipes are completely
broken." They were, in a specific and traceable way. Every number in the base
profile came from ONE CivitAI card (ZiB_unstableRevolution) generalised to all
five installed base checkpoints, and only half-transcribed - that card says
"Scheduler: Bong Tangent" and Pixal shipped `simple`. Two community grids then
rated the sampler it named, res_multistep, red against every scheduler on this
architecture.

The bigger one was quieter. Z-Image Base is the only variant in the family that
is NOT distilled: it samples at cfg 4, which means every step pushes the image
away from the negative conditioning. Pixal sent an empty string there. cfg 4
against nothing is what "flat and plastic" looks like.

What these tests protect is not the numbers - those move as things get measured
- but the properties that made the old ones wrong: a realism negative must
never land on a painterly recipe, a distilled profile must never grow one, and
a sampler pair must never be offered to a graph that has no scheduler to put it
in.
"""
import unittest
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

_SPEC = spec_from_file_location(
    "pixal_server_zimage", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

BASE = "ZiB\\z_image_bf16.safetensors"
TURBO = "ZiT\\z_image_turbo_bf16.safetensors"
ANIME = "ZiB\\Z-Image_clear_anime_BF16.safetensors"


def model(rel, variant, profile):
    return {"rel": rel, "kind": "diffusion_models", "family": "zimage",
            "variant": variant, "supported": True, "execution_profile": profile}


@contextmanager
def assets(entry):
    with ExitStack() as stack:
        stack.enter_context(patch.object(server, "resolve_model_entry",
                                         return_value=entry))
        stack.enter_context(patch.object(server, "_catalog_has", return_value=True))
        stack.enter_context(patch.object(server, "_catalog_resolve",
                                         side_effect=lambda kind, rel: rel))
        stack.enter_context(patch.object(server, "resolve_lora",
                                         side_effect=lambda name: name))
        yield


class NegativeTests(unittest.TestCase):

    def test_base_realism_gets_the_full_negative(self):
        entry = model(BASE, "base", "zimage_base")
        with assets(entry):
            graph, _cap, info = server.build_zimage("a woman in a kitchen", 7,
                                                    width=512, height=512)
        neg = graph["5"]["inputs"]["text"]
        self.assertEqual(graph["5"]["class_type"], "CLIPTextEncode")
        self.assertIn(server.ZIMAGE_BASE_NEGATIVE_REALISM, neg)
        self.assertIn(server.ZIMAGE_BASE_NEGATIVE_QUALITY, neg)
        # It has to reach the ledger too, or a render nobody can explain later
        # looks like the model changed when it was the negative.
        self.assertEqual(info["negative"], neg)

    def test_a_painterly_recipe_never_negates_its_own_medium(self):
        """`fantasy` runs the same profile and the same graph. Telling it to
        avoid "digital painting" would fight the D&D LoRA it exists to run."""
        entry = model(BASE, "base", "zimage_base")
        with assets(entry):
            graph, _cap, _info = server.build_fantasy("a knight", 7,
                                                      width=512, height=512)
        neg = graph["5"]["inputs"]["text"]
        self.assertEqual(neg, server.ZIMAGE_BASE_NEGATIVE_QUALITY)
        for banned in ("digital painting", "illustrated", "drawing", "CGI"):
            self.assertNotIn(banned, neg)

    def test_a_distilled_profile_still_zeroes_its_negative(self):
        """Turbo's official pipeline does not read a negative at all, and at
        cfg 1 there is no second pass for one to land in."""
        entry = model(TURBO, "turbo", "zimage_turbo_v4")
        with assets(entry):
            graph, _cap, info = server.build_zimage("a woman", 7,
                                                    width=512, height=512)
        self.assertEqual(graph["5"]["class_type"], "ConditioningZeroOut")
        self.assertNotIn("negative", info)

    def test_a_saved_preset_may_carry_its_own(self):
        """Until this landed the builder took no `negative` at all, so a style
        that set one had it dropped by the chat path's kwarg filter and
        silently rendered without it."""
        entry = model(BASE, "base", "zimage_base")
        with assets(entry):
            graph, _cap, info = server.build_zimage(
                "a woman", 7, width=512, height=512, negative="mine only")
        self.assertEqual(graph["5"]["inputs"]["text"], "mine only")
        self.assertEqual(info["negative"], "mine only")

    def test_a_preset_negative_cannot_un_zero_a_distilled_profile(self):
        entry = model(TURBO, "turbo", "zimage_turbo_v4")
        with assets(entry):
            graph, _cap, _info = server.build_zimage(
                "a woman", 7, width=512, height=512, negative="mine only")
        self.assertEqual(graph["5"]["class_type"], "ConditioningZeroOut")


class ScheduleTests(unittest.TestCase):

    def test_the_base_schedule_is_the_guide_block(self):
        s = server.ZIMAGE_EXECUTION_PROFILES["zimage_base"]
        self.assertEqual((s["sampler"], s["scheduler"], s["steps"], s["cfg"],
                          s["shift"]),
                         ("res_2s", "beta", 22, 4.0, 1.0))

    def test_base_is_never_put_back_on_the_red_sampler(self):
        """res_multistep is what shipped, and it rates red against every
        scheduler on two independent community grids for this architecture."""
        self.assertNotEqual(
            server.ZIMAGE_EXECUTION_PROFILES["zimage_base"]["sampler"],
            "res_multistep")
        for p in server.SAMPLER_PRESETS["zimage"]:
            self.assertNotEqual(p["tuning"].get("sampler_name"), "res_multistep")

    def test_base_keeps_a_real_cfg(self):
        """Base is the one Z-Image variant that is not distilled. The guide is
        blunt that below cfg 4 it falls apart, so cfg_locked must leave it
        alone - and no preset may quietly move it."""
        s = server.ZIMAGE_EXECUTION_PROFILES["zimage_base"]
        self.assertGreaterEqual(s["cfg"], 4.0)
        self.assertFalse(s["zero_negative"])


class PresetTests(unittest.TestCase):

    def test_the_family_has_presets_at_all(self):
        """It had none until 2026-09-03, so every Z-Image build showed an empty
        shelf while its seat offered 63 sampler names."""
        self.assertTrue(server.SAMPLER_PRESETS.get("zimage"))

    def test_none_of_them_claim_to_be_measured_here(self):
        for p in server.SAMPLER_PRESETS["zimage"]:
            with self.subTest(preset=p["id"]):
                self.assertIn("not measured", p["note"].lower())

    def test_none_of_them_name_a_scheduler_this_family_rates_dead(self):
        for p in server.SAMPLER_PRESETS["zimage"]:
            self.assertNotIn(p["tuning"].get("scheduler"),
                             {"karras", "exponential"})

    def test_they_reach_a_base_build(self):
        entry = model(BASE, "base", "zimage_base")
        with patch.object(server, "resolve_model_entry", return_value=entry), \
             patch.object(server, "seat_choices", return_value={}):
            ids = {p["id"] for p in server.sampler_presets("zimage", BASE)}
        self.assertTrue(ids)

    def test_they_are_withheld_from_a_graph_with_no_scheduler(self):
        """Amazing v4 deletes the KSampler and drives two SamplerCustom passes
        off a sigma chain. Offering it a sampler/scheduler PAIR would drop the
        scheduler on the way through the key filter and apply a combo nobody
        rendered."""
        entry = model(TURBO, "turbo", "zimage_turbo_v4")
        with patch.object(server, "resolve_model_entry", return_value=entry), \
             patch.object(server, "seat_choices", return_value={}):
            got = server.sampler_presets("zimage", TURBO)
        self.assertEqual(got, [])

    def test_they_are_withheld_from_the_distilled_anime_merge(self):
        """clear_anime HAS a KSampler, so the profile filter is doing the work
        here, not the seat: it runs 12 steps at cfg 1 with its own matched VAE,
        and a 22-step cfg-4 realism pair is not advice about that model."""
        entry = model(ANIME, "base", "zimage_clear_anime")
        with patch.object(server, "resolve_model_entry", return_value=entry), \
             patch.object(server, "seat_choices", return_value={}):
            got = server.sampler_presets("anime", ANIME)
        self.assertEqual(got, [])


class ShippedPresetFileTests(unittest.TestCase):
    """The SHIPPED starter styles survive the real loader.

    This class used to assert five `recipes/zimage_*.json` files existed, and
    it broke CI on every push from 1.2.2b (2026-09-03) onward while passing on
    the author's machine. `recipes/` is the USER's folder and `.gitignore`
    line 22 ignores its contents on purpose, so those five were never in a
    commit, never in `git archive HEAD`, and therefore never in an installer -
    a test can only see them on a machine that happens to have them.

    They were also never shippable. They name private Civitai checkpoints
    (`pornmasterZImage_baseV1`, `nsgirlZImage_002`, `cyberrealisticZImage_v70`)
    while the starter set is deliberately built ONLY on checkpoints the
    installer itself lays down, "so every one of them runs on a machine that
    has never seen a Civitai login" (see seed_starter_styles). They are
    personal saved styles, and personal saved styles are exactly what
    `recipes/` is for.

    So the subject is the real shipped set - `server.STARTER_STYLE_DIR`, read
    from the module rather than rebuilt from `parents[1]`, so the test cannot
    drift from what the seeder actually copies.
    """

    def _shipped(self):
        import json
        out = []
        for path in sorted(server.STARTER_STYLE_DIR.glob("*.json")):
            out.append((path, json.loads(path.read_text(encoding="utf-8"))))
        return out

    def test_there_is_a_starter_set_at_all(self):
        self.assertTrue(self._shipped(), "no starter styles ship at all")

    def test_each_one_loads_and_validates(self):
        for path, raw in self._shipped():
            with self.subTest(preset=path.stem):
                record = server.validate_saved_style(raw)
                self.assertEqual(record["id"], path.stem)
                self.assertIn(record["base"], server.PUBLIC_RECIPE_IDS)

    def test_a_zimage_base_style_carries_a_negative_and_turbo_does_not(self):
        """cfg 1 has no guidance to steer, so a negative there is a field that
        never reaches the graph."""
        for path, raw in self._shipped():
            if raw.get("base") != "zimage":
                continue
            with self.subTest(preset=path.stem):
                if "turbo" in path.stem:
                    self.assertNotIn("negative", raw)

    def test_every_shipped_style_is_tracked_by_git(self):
        """The guard the old version of this class needed.

        A shipped asset that git does not track cannot reach a user: the
        installer packages `git archive HEAD`, never the working tree. Anything
        under a gitignored path is invisible to a release and green only on the
        machine that wrote it - which is the exact way this file broke.
        """
        import subprocess
        root = Path(__file__).resolve().parents[1]
        if not (root / ".git").exists():
            self.skipTest("not a git checkout (shipped source tree)")
        tracked = subprocess.run(
            ["git", "ls-files", "--", str(server.STARTER_STYLE_DIR)],
            cwd=root, capture_output=True, text=True)
        if tracked.returncode != 0:
            self.skipTest("git unavailable")
        names = {Path(line).name for line in tracked.stdout.split("\n") if line.strip()}
        for path, _ in self._shipped():
            with self.subTest(preset=path.name):
                self.assertIn(path.name, names,
                              f"{path.name} ships but git does not track it - "
                              f"it would be absent from every installer")


if __name__ == "__main__":
    unittest.main()
