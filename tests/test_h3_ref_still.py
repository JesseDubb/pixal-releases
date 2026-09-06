"""Brief 9.67 - the H3 ref still: the ref2va build renders a still from the
character's reference.

Jesse (2026-08-27): with a character active, the picker should allow the ref
version of MiniMax for images - "minus identity edit". The ref2va model takes
reference images natively (MiniMaxH3ReferenceToVideo, ref_images.ref_image_N),
so the anchor's identity_ref photo IS the identity mechanism: no identity
LoRA, no identity_edit stage, no bypass chain. The graph is build_h3_ref2v's
spine at the 5-frame floor with the audio decode branch and the VHS tail
removed and h3_still's frame-0 keep + SaveImage tail; the prompt is a
deterministic still-framed brief through assemble_h3_ref2v_prompt.

What these tests pin:

  RecipeRow      - the row exists with needs_character, variants ["ref2va"],
                   the ref2va default model, BOTH VAEs required; the sampler
                   seat resolves and reports the still trio.
  Classification - a ref2va name is a SUPPORTED minimax_h3 still now
                   (variant stays "ref2va"); fl2va is unchanged;
                   compatible_recipes splits the pair by variant.
  GraphShape     - MiniMaxH3ReferenceToVideo at length 5 with the audio_vae
                   LOADER wired (the node takes the input even though nothing
                   decodes audio), exactly one ref_image_0 LoadImage naming
                   the identity ref, no VAEDecodeAudio, no VHS_VideoCombine,
                   ImageFromBatch(0) + SaveImage tail.
  Prompt         - six-section assembly: <Subject 1> defined from <Picture 1>
                   with the fully_preserved retention line, the h3_still
                   frame sentence, room-tone soundscape - and NO face/age
                   words from the character card (hair/build/race stay).
  CharacterGate  - no character (or one without a ready photo) is a
                   ValueError naming the need; an fl2va model is refused by
                   the variants check.
  PromptContract - 9.80: the seamless/studio/plain backdrop scrub, the
                   waist-up framing floor (default + full-length rewrite,
                   mirror excluded), every action in info, and the
                   SYSTEM_LOCAL template line that teaches the lane.
                   9.85: locomotion rewritten to a held pose or scrubbed
                   ("mid-sentence" exempt - a held facial state, not a
                   body in motion), eyes-closing expressions scrubbed
                   (smiling/grinning/smirking stay), an unchanged caption
                   byte-identical. 1.1.3b: NO camera clause, and the
                   wardrobe lock dead last after every repair.
  Routing        - effective_recipe: ref2va model -> h3_ref_still (with or
                   without style/quality), fl2va unchanged; character + an H3
                   model NEVER yields identity_edit; _apply_opts carries the
                   H3 model under the anchor.
  Options        - /api/options lists the recipe available with the stock
                   ref2va default and needs_character true, names the audio
                   VAE when it is missing, and marks ref2va models supported.
  ClientRouting  - static, in the test_h3_still.py style (no JS runner):
                   identityBlocked exempts minimax_h3, the no-character
                   disable reads needs_character off the recipe rows, the
                   store mirrors the server routing, the label is named.

Same sanctioned simulation as every sibling file: stubbed catalog, stubbed
character, no generation, no ComfyUI, no GPU.
"""

import json
import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location(
    "pixal_server_h3_ref_still", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

WEB = ROOT / "web" / "src"
STORE = (WEB / "store.js").read_text(encoding="utf-8")
NAMES = (WEB / "lib" / "names.js").read_text(encoding="utf-8")
COMPOSER = (WEB / "components" / "Composer.jsx").read_text(encoding="utf-8")

STOCK = server.H3_MODEL
FINETUNE = "Minimax H3\\10eros_max_fl2va_beta2.safetensors"
REF2VA = server.H3_REF2V_MODEL
MAX_PIXELS = server.H3_STILL_MAX_PIXELS   # the picture lane, not the video Max tier


def h3_entries(root, *, encoder=True, audio_vae=True):
    """This box's H3 stack as catalog entries: both stock builds, one fl2va
    finetune, the shared encoder and both VAEs."""
    def add(kind, rel, size=1):
        return {"rel": rel, "kind": kind, "root": str(root),
                "size": size, "mtime": 0.0}
    entries = [add("diffusion_models", STOCK),
               add("diffusion_models", FINETUNE),
               add("diffusion_models", REF2VA),
               add("vae", server.H3_VIDEO_VAE)]
    if audio_vae:
        entries.append(add("vae", server.H3_AUDIO_VAE))
    if encoder:
        entries.append(add("text_encoders", server.H3_CLIP))
    return entries


def stub_catalog(entries):
    return lambda kind=None: [e for e in entries if kind in (None, e["kind"])]


def no_disk():
    return (patch.object(server, "adjacent_metadata", return_value={}),
            patch.object(server, "model_roots", return_value=[]))


CHARACTER = {"id": "mia", "name": "Mia", "age": 24, "race": "Korean",
             "sex": "female", "style": "silver pixie cut, lean runner's build",
             "identity_ref": "mia.png"}


def anchored(root, character=CHARACTER):
    """A temp ComfyUI dir whose input/ holds the anchor's reference photo."""
    (root / "input").mkdir(exist_ok=True)
    (root / "input" / character["identity_ref"]).write_bytes(b"reference")
    return (patch.object(server, "CDIR", root),
            patch.object(server, "CHARACTERS", {character["id"]: character}))


class RecipeRowTests(unittest.TestCase):
    """The spec row and its seat."""

    def test_the_recipe_spec(self):
        spec = server.RECIPE_SPECS["h3_ref_still"]
        self.assertEqual(spec["label"], "MiniMax H3 Ref")
        self.assertEqual(spec["tag"],
                         "2K still from a reference · 20 steps · ~2 min")
        self.assertEqual(spec["family"], "minimax_h3")
        self.assertEqual(spec["variants"], ["ref2va"])
        self.assertEqual(spec["default_model"], REF2VA)
        self.assertTrue(spec["needs_character"])
        self.assertEqual(spec["aspect"], "3:4 (Portrait Standard)")
        self.assertEqual(spec["mp"], 3.1)
        self.assertEqual(spec["mp_cap"], server.H3_STILL_MP_CAP)
        self.assertEqual(spec["required_text_encoders"], [server.H3_CLIP])
        # The ReferenceToVideo node takes audio_vae even with no audio
        # decoded, so the audio VAE is a real requirement (unlike h3_still).
        self.assertEqual(spec["required_vaes"],
                         [server.H3_VIDEO_VAE, server.H3_AUDIO_VAE])
        # 9.74: an editable style lane, every row off by default. 1.1.4b
        # added the reference-realism trio at the 0.2 stack strength and
        # moved the revision to 3, which discards plans saved against 2.
        self.assertEqual(spec["lora_variants"], ["any"])
        self.assertEqual(spec["lora_stack_revision"], 3)
        self.assertEqual(
            [(s["slot"], s["name"], s["zone"], s["active_by_default"])
             for s in spec["lora_stages"]],
            [("style", server.H3_HMNSFW_LORA, "editable", False),
             ("digicam", server.H3_DIGICAM_LORA, "editable", False),
             ("galaxyace", server.H3_GALAXYACE_LORA, "editable", False),
             ("relim", server.H3_RELIM_LORA, "editable", False)])
        self.assertNotIn("dials", spec)
        self.assertNotIn("h3_ref_still", server.VIDEO_TEMPLATES)

    def test_the_builder_is_registered(self):
        self.assertIs(server.BUILDERS["h3_ref_still"], server.build_h3_ref_still)
        self.assertIn("h3_ref_still", server.PUBLIC_RECIPE_IDS)
        self.assertIn("h3_ref_still", server.SIGS)

    def test_the_seat_resolves_the_still_trio(self):
        seat = server.SAMPLER_SEATS["h3_ref_still"]
        self.assertEqual(seat["node"], "7")
        self.assertEqual(seat["class"], "KSamplerSelect")
        self.assertEqual(seat["map"], {
            "sampler_name": [("7", "sampler_name")],
            "steps": [("8", "steps")],
            "scheduler": [("8", "scheduler")]})
        self.assertEqual(server.seat_tuning_keys(seat),
                         ("steps", "sampler_name", "scheduler"))
        self.assertEqual(server.sampler_defaults("h3_ref_still"),
                         {"steps": 20, "sampler_name": "dpmpp_sde_gpu",
                          "scheduler": "beta"})

    def test_the_popup_key_space_covers_the_ref2va_profile(self):
        self.assertIn("minimax_h3:ref2va", server._LORA_PROFILE_KEYS)


class ClassificationTests(unittest.TestCase):
    """model_profile: ref2va builds are supported stills; fl2va unchanged."""

    def profile(self, rel):
        sidecar, roots = no_disk()
        with sidecar, roots:
            return server.model_profile(rel)

    def test_ref2va_is_a_supported_minimax_h3_still(self):
        profile = self.profile(REF2VA)
        self.assertEqual((profile["family"], profile["variant"]),
                         ("minimax_h3", "ref2va"))
        self.assertEqual(profile["media"], "video")     # they ARE video models
        self.assertTrue(profile["supported"])
        self.assertEqual(profile["reason"], "")

    def test_fl2va_is_unchanged(self):
        profile = self.profile(STOCK)
        self.assertEqual((profile["family"], profile["variant"]),
                         ("minimax_h3", "fl2va"))
        self.assertTrue(profile["supported"])
        self.assertEqual(profile["reason"], "")

    def test_compatible_recipes_splits_the_still_pair_by_variant(self):
        self.assertEqual(server.compatible_recipes(self.profile(REF2VA)),
                         ["h3_ref_still", "h3_ref_still_2x"])
        self.assertEqual(server.compatible_recipes(self.profile(STOCK)),
                         ["h3_still", "h3_still_2x"])


class GraphTests(unittest.TestCase):
    """build_h3_ref_still: the ref2v spine at the 5-frame floor."""

    def build(self, scene="A red barn at dusk", seed=424242, entries=None,
              character="mia", **kwargs):
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root)
            entries = h3_entries(root) if entries is None else entries
            sidecar, roots = no_disk()
            with cdir, chars, sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)):
                return server.build_h3_ref_still(scene, seed, character=character,
                                                 **kwargs)

    def test_the_graph_is_the_ported_ref2v_block(self):
        g, _cap, _info = self.build()
        self.assertEqual(sorted(g, key=int),
                         ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
                          "11", "12", "13", "14"])
        classes = {nid: node["class_type"] for nid, node in g.items()}
        self.assertEqual(classes, {
            "1": "UNETLoader", "2": "CLIPLoader", "3": "VAELoader",
            "4": "VAELoader", "5": "LoadImage",
            "6": "MiniMaxH3ReferenceToVideo", "7": "KSamplerSelect",
            "8": "BasicScheduler", "9": "BasicGuider",
            "10": "RandomNoise", "11": "SamplerCustomAdvanced",
            "12": "VAEDecode", "13": "ImageFromBatch", "14": "SaveImage"})
        self.assertNotIn("CFGGuider", classes.values())
        self.assertEqual(g["1"]["inputs"],
                         {"unet_name": REF2VA, "weight_dtype": "default"})
        self.assertEqual(g["4"]["inputs"],
                         {"vae_name": server.H3_AUDIO_VAE})
        self.assertEqual(g["6"]["inputs"]["audio_vae"], ["4", 0])
        self.assertEqual(g["6"]["inputs"]["length"], 5)
        self.assertEqual(g["6"]["inputs"]["ref_image_size"], "match")
        self.assertEqual(g["8"]["inputs"], {"model": ["1", 0],
                                            "scheduler": "beta",
                                            "steps": 20, "denoise": 1.0})
        self.assertEqual(g["10"]["inputs"], {"noise_seed": 424242})
        self.assertEqual(g["13"]["inputs"], {"image": ["12", 0],
                                             "batch_index": 0, "length": 1})
        self.assertEqual(g["14"]["inputs"]["images"], ["13", 0])
        self.assertEqual(g["14"]["inputs"]["filename_prefix"],
                         "pixal_dm/a_red_barn_at_dusk")
    def test_the_identity_lane_keeps_its_own_measured_pair(self):
        """The reference lanes do NOT follow the prompt-only lane's trio.
        Jesse asked for res_2s x bong_tangent x 8 "for h3 image" and it went
        onto all four still lanes on 2026-09-06; the identity lanes were never
        part of that ask. bong_tangent discards H3's shift 12 (RES4LYF
        sigmas.py:4076-4088 takes model_sampling and never reads it), which
        collapses the high-sigma steps where a face is decided, and stock
        res_2s is an eta-0.5 SDE. 8 steps was never measured here; every
        locked identity recipe on this lane is 20."""
        g, _cap, _info = self.build()
        self.assertEqual(g["7"]["inputs"], {"sampler_name": "dpmpp_sde_gpu"})
        self.assertEqual(g["8"]["inputs"]["scheduler"], "beta")
        self.assertEqual(g["8"]["inputs"]["steps"], 20)
        # and the prompt-only lane still carries what he asked for
        self.assertEqual((server.H3_STILL_SAMPLER, server.H3_STILL_SCHEDULER,
                          server.H3_STILL_STEPS), ("res_2s", "bong_tangent", 8))

    def test_exactly_one_reference_naming_the_identity_photo(self):
        g, _cap, info = self.build()
        self.assertEqual(g["5"]["class_type"], "LoadImage")
        self.assertEqual(g["5"]["inputs"], {"image": "mia.png"})
        wired = [key for key in g["6"]["inputs"] if key.startswith("ref_images.")]
        self.assertEqual(wired, ["ref_images.ref_image_0"])
        self.assertEqual(g["6"]["inputs"]["ref_images.ref_image_0"], ["5", 0])
        self.assertEqual(info["references"], 1)

    def test_no_audio_decode_and_no_video_tail(self):
        g, _cap, _info = self.build()
        classes = [node["class_type"] for node in g.values()]
        self.assertNotIn("VAEDecodeAudio", classes)
        self.assertNotIn("VHS_VideoCombine", classes)

    def test_the_prompt_is_the_six_section_still_brief(self):
        g, cap, _info = self.build()
        prompt = g["6"]["inputs"]["prompt"]
        self.assertIn("detailed_description:\n"
                      + server.H3_REF2V_STYLE_PHOTOREAL + "\n"
                      "[Shot 1] Live-action, a frozen instant held completely "
                      "still - ", prompt)
        self.assertIn(cap, prompt)
        # 1.1.4b: freeze first, caption last. Asserted on the PROMPT, not
        # the caption - 1.1.3b moved the wardrobe lock to the end of the
        # caption and the builder then wrapped a sentence around it, so
        # "last in the caption" turned out to be a property nothing renders.
        self.assertIn("still - the subject holds the pose and nothing in "
                      "the frame moves. ", prompt)
        description = prompt.split("detailed_description:\n", 1)[1]
        self.assertTrue(description.split("\n\n")[0].rstrip().endswith(cap))
        self.assertIn("subject_definitions:\n"
                      "<Subject 1> is the person in <Picture 1>.", prompt)
        self.assertIn("retention_analysis:\n"
                      "<Subject 1>: fully_preserved", prompt)
        self.assertIn("summary:\n[reference generation]", prompt)
        self.assertTrue(prompt.endswith(
            "overall_soundscape:\nRoom tone, steady, synchronized.\n\n"
            "non_diegetic_music:\nN/A"))

    def test_the_caption_strips_face_and_age_but_keeps_the_rest(self):
        g, cap, _info = self.build()
        prompt = g["6"]["inputs"]["prompt"]
        # The reference carries the face and age: the card's age never ships.
        self.assertNotIn("24-year-old", prompt)
        self.assertNotIn("24", prompt)
        # Hair, build and race are canon that does not fight the photo.
        self.assertIn("She is a Korean woman.", prompt)
        self.assertIn("Silver pixie cut, lean runner's build.", prompt)
        # The wardrobe lock still closes the scene portion (the
        # _character_caption shape: it jams onto an unpunctuated scene, as on
        # h3_still); 9.80's camera clause closes the caption itself.
        self.assertIn("She is fully dressed in the clothing described above.",
                      prompt)
        self.assertIn("A red barn at dusk", prompt)

    def test_the_default_canvas_is_the_max_tier_3_4(self):
        g, _cap, info = self.build()
        self.assertEqual(g["6"]["inputs"]["width"], 1536)
        self.assertEqual(g["6"]["inputs"]["height"], 2048)
        self.assertEqual(info["size"], "1536x2048")
        self.assertAlmostEqual(info["canvas_mp"], 3.15, delta=0.01)

    def test_the_8mp_rung_renders_at_8mp(self):
        # 1.2.1b: the reference lane is the one the 2026-09-02 lookdev ran
        # above 2K all day (1984x2976), so the ladder's top rung has to
        # reach the canvas the button names.
        g, _cap, info = self.build(mp=8)
        width, height = g["6"]["inputs"]["width"], g["6"]["inputs"]["height"]
        self.assertEqual((width % 32, height % 32), (0, 0))
        self.assertLessEqual(width * height, MAX_PIXELS)
        self.assertEqual((width, height), (2464, 3296))
        self.assertEqual(info["canvas_mp"], width * height / 1e6)

    def test_info_names_the_stack_and_no_loras_ran(self):
        g, _cap, info = self.build()
        self.assertEqual(info["model"], "MiniMax H3 REF2VA still")
        self.assertEqual(info["model_path"], REF2VA)
        self.assertEqual(info["model_family"], "minimax_h3")
        self.assertEqual(info["model_variant"], "ref2va")
        self.assertEqual(info["execution_profile"], "minimax_h3_ref2v_still")
        self.assertEqual(info["text_encoder"],
                         "qwen3vl_32b_minimax_h3_nvfp4_awq")
        self.assertEqual(info["vae"], "minimax_h3_video_vae_fp16")
        self.assertEqual(info["loras"], [])
        self.assertEqual(info["lora_stack"], [])
        self.assertEqual(info["character"], "Mia")
        server.validate_job_model_info("h3_ref_still", info, g)

    def test_overrides_apply_after_the_seed(self):
        g, _cap, _info = self.build(overrides=[
            {"node": "8", "input": "steps", "value": 12},
            {"node": "10", "input": "noise_seed", "value": 7}])
        self.assertEqual(g["8"]["inputs"]["steps"], 12)
        self.assertEqual(g["10"]["inputs"]["noise_seed"], 7)


class CharacterGateTests(unittest.TestCase):
    """The recipe's defining gate: an active character with a ready photo."""

    def test_no_character_is_a_refusal_naming_the_need(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                with self.assertRaisesRegex(
                        ValueError,
                        "needs an active character with a reference photo"):
                    server.build_h3_ref_still("a barn", 1)

    def test_an_unknown_character_is_the_same_refusal(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root)
            sidecar, roots = no_disk()
            with cdir, chars, sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                with self.assertRaisesRegex(
                        ValueError,
                        "needs an active character with a reference photo"):
                    server.build_h3_ref_still("a barn", 1, character="nobody")

    def test_a_character_whose_photo_is_gone_is_the_same_refusal(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()      # no mia.png written
            sidecar, roots = no_disk()
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "CHARACTERS", {"mia": CHARACTER}), \
                 sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                with self.assertRaisesRegex(
                        ValueError,
                        "needs an active character with a reference photo"):
                    server.build_h3_ref_still("a barn", 1, character="mia")

    def test_an_fl2va_build_is_refused(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root)
            sidecar, roots = no_disk()
            with cdir, chars, sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                with self.assertRaisesRegex(ValueError, "uses ref2va models"):
                    server.build_h3_ref_still("a barn", 1, character="mia",
                                              model=STOCK)


class RoutingTests(unittest.TestCase):
    """effective_recipe: the variant picks the recipe; the anchor never
    forces identity_edit onto an H3 pick."""

    @staticmethod
    def entry(rel, variant):
        return {"rel": rel, "kind": "diffusion_models", "family": "minimax_h3",
                "variant": variant, "supported": True}

    def recipe(self, opts, entry=None):
        with patch.object(server, "resolve_model_entry", return_value=entry):
            return server.effective_recipe(opts)

    def test_a_ref2va_pick_routes_to_the_ref_still(self):
        ref = self.entry(REF2VA, "ref2va")
        self.assertEqual(self.recipe({"model": REF2VA}, ref), "h3_ref_still")
        # The style selector is still ignored on an H3 pick...
        self.assertEqual(
            self.recipe({"model": REF2VA, "style": "anime"}, ref),
            "h3_ref_still")

    def test_refined_on_a_ref2va_pick_reaches_the_2x_lane(self):
        """Brief 9.84. Until it, all three chooser branches returned
        h3_ref_still without consulting `quality`, so Refined was accepted
        and silently dropped on every anchored render - while the composer
        still rendered the row enabled and tagged "two-pass finish"."""
        ref = self.entry(REF2VA, "ref2va")
        self.assertEqual(
            self.recipe({"model": REF2VA, "quality": "refined"}, ref),
            "h3_ref_still_2x")
        # ...whatever style the selector last held, as on the fl2va pair.
        self.assertEqual(
            self.recipe({"model": REF2VA, "style": "anime",
                         "quality": "refined"}, ref),
            "h3_ref_still_2x")
        self.assertEqual(
            self.recipe({"model": REF2VA, "quality": "standard"}, ref),
            "h3_ref_still")
        # and under an anchor, which is the only way this lane is reachable
        self.assertEqual(
            self.recipe({"character": "mia", "model": REF2VA,
                         "quality": "refined"}, ref),
            "h3_ref_still_2x")

    def test_an_fl2va_pick_keeps_the_still_pair(self):
        fl = self.entry(STOCK, "fl2va")
        self.assertEqual(self.recipe({"model": STOCK}, fl), "h3_still")
        self.assertEqual(
            self.recipe({"model": STOCK, "style": "realism",
                         "quality": "refined"}, fl),
            "h3_still_2x")

    def test_a_character_never_forces_identity_edit_onto_an_h3_pick(self):
        ref = self.entry(REF2VA, "ref2va")
        fl = self.entry(STOCK, "fl2va")
        self.assertEqual(
            self.recipe({"character": "mia", "model": REF2VA}, ref),
            "h3_ref_still")
        self.assertEqual(
            self.recipe({"character": "mia", "model": STOCK}, fl), "h3_still")
        self.assertEqual(
            self.recipe({"character": "mia", "model": STOCK,
                         "quality": "refined"}, fl),
            "h3_still_2x")

    def test_a_character_without_an_h3_pick_stays_identity_edit(self):
        zmodel = {"rel": "ZiT\\z_image_turbo_bf16.safetensors",
                  "kind": "diffusion_models", "family": "zimage",
                  "variant": "turbo", "supported": True}
        self.assertEqual(self.recipe({"character": "mia"}), "identity_edit")
        self.assertEqual(
            self.recipe({"character": "mia", "model": "selected-z"}, zmodel),
            "identity_edit")
        # A standalone identity ref is not a character: the ref still wires
        # characters only, so the identity chain keeps this case.
        self.assertEqual(
            self.recipe({"refs": [{"kind": "identity", "file": "x.png"}],
                         "model": REF2VA}, self.entry(REF2VA, "ref2va")),
            "identity_edit")

    def test_apply_opts_routes_and_carries_the_h3_model_under_the_anchor(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root)
            sidecar, roots = no_disk()
            with cdir, chars, sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                args = {}
                recipe = server._apply_opts(
                    args, {"character": "mia", "model": REF2VA,
                           "style": "realism", "quality": "standard"})
        self.assertEqual(recipe, "h3_ref_still")
        self.assertEqual(args["model"], REF2VA)
        self.assertEqual(args["character"], "mia")


class OptionsTests(unittest.TestCase):
    """/api/options on a stub catalog: the recipe row and the shelf."""

    def options(self, entries):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)), \
                 patch.object(server, "model_roots", return_value=[]), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "lm_enrich"), \
                 patch.object(server, "_LORA_TITLE_CACHE",
                              root / "titles.json"):
                return server.Hub().options()

    def test_the_recipe_is_available_with_the_ref2va_default(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td)))
        recipe = next(r for r in options["recipes"] if r["id"] == "h3_ref_still")
        self.assertTrue(recipe["available"])
        self.assertEqual(recipe["missing"], [])
        self.assertEqual(recipe["default_model"], REF2VA)
        self.assertEqual(recipe["family"], "minimax_h3")
        self.assertEqual(recipe["variants"], ["ref2va"])
        self.assertTrue(recipe["needs_character"])
        self.assertEqual(recipe["mp_cap"], server.H3_STILL_MP_CAP)
        self.assertEqual(options["defaults"]["h3_ref_still"]["mp"], 3.1)

    def test_a_stub_without_the_audio_vae_names_it(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td), audio_vae=False))
        recipe = next(r for r in options["recipes"] if r["id"] == "h3_ref_still")
        self.assertFalse(recipe["available"])
        self.assertEqual(recipe["missing"], ["VAE: " + server.H3_AUDIO_VAE])

    def test_the_shelf_marks_both_variants_supported(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td)))
        meta = options["model_meta"]
        self.assertTrue(meta[REF2VA]["supported"])
        self.assertEqual(meta[REF2VA]["reason"], "")
        self.assertIn("h3_ref_still", meta[REF2VA]["compatible_recipes"])
        self.assertNotIn("h3_still", meta[REF2VA]["compatible_recipes"])
        self.assertTrue(meta[STOCK]["supported"])
        self.assertIn("h3_still", meta[STOCK]["compatible_recipes"])
        self.assertNotIn("h3_ref_still", meta[STOCK]["compatible_recipes"])


class PromptContractTests(unittest.TestCase):
    """9.80 + 9.85: the deterministic half of the H3 still prompt contract,
    enforced on the composed caption (never requested) and reported in
    info - the backdrop killer scrubbed, locomotion rewritten to a held
    pose or scrubbed, eyes-closing expressions scrubbed, framing floored
    at waist-up, the measured skin clause penultimate and the measured
    camera clause at the tail."""

    def build(self, scene, seed=424242, **kwargs):
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root)
            sidecar, roots = no_disk()
            with cdir, chars, sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                return server.build_h3_ref_still(scene, seed, character="mia",
                                                 **kwargs)

    def test_the_wardrobe_lock_takes_the_tail(self):
        # 1.1.3b: the camera clause used to sit after the wardrobe lock.
        # It measured inert three separate ways on 2026-08-30 and it was
        # holding the caption's strongest position, so it is gone and the
        # wardrobe lock inherits the tail - which is where it has to be,
        # because this family undresses a subject when the last thing it
        # reads is her body.
        g, cap, info = self.build("She waits in the lift lobby, lamps low.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertFalse(hasattr(server, "H3_STILL_CAMERA"))
        self.assertNotIn("camera_clause", info)
        self.assertNotIn("HDR holding the highlights", prompt)
        self.assertIn("fully dressed", cap)
        # nothing at all comes after the lock
        self.assertTrue(cap.rstrip().endswith("described above."), cap[-90:])

    def test_a_seamless_backdrop_is_scrubbed_and_logged(self):
        g, _cap, info = self.build(
            "She poses against a seamless charcoal backdrop in a black "
            "dress, lamps low.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("seamless", prompt.lower())
        self.assertIn("backdrop: against a seamless charcoal backdrop",
                      info["prompt_repairs"])
        # the rest of the sentence survives the removal
        self.assertIn("She poses in a black dress", prompt)

    def test_studio_and_plain_backdrop_variants_are_scrubbed(self):
        g, _cap, info = self.build(
            "In front of a studio backdrop she checks her phone, then "
            "turns from a plain white background.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("studio backdrop", prompt.lower())
        self.assertNotIn("plain white background", prompt.lower())
        self.assertEqual(
            sum(1 for r in info["prompt_repairs"] if r.startswith("backdrop:")),
            2)

    def test_a_recording_studio_is_a_real_place_and_stays(self):
        g, _cap, info = self.build(
            "She leans on the mixing desk in the recording studio, "
            "waist-up, a reel still turning.")
        self.assertIn("recording studio", g["6"]["inputs"]["prompt"])
        self.assertEqual(info["prompt_repairs"], [])

    def test_a_backdrop_repair_that_would_gut_the_caption_is_refused(self):
        # standing=False: the scene IS the caption, so a scene that is one
        # backdrop clause has nothing left after the scrub - the repair is
        # refused (repair_scene's rule) and the refusal is what is logged.
        _g, _cap, info = self.build("on a seamless", standing=False)
        self.assertIn("kept: backdrop repair would gut the caption",
                      info["prompt_repairs"])

    def test_framing_defaults_to_waist_up_when_unnamed(self):
        g, cap, info = self.build("She waits in the hotel lift lobby, warm "
                                  "lamps overhead.")
        self.assertIn("Framed waist-up.", g["6"]["inputs"]["prompt"])
        # the default lands between the scene and the wardrobe lock
        self.assertLess(cap.index("Framed waist-up."),
                        cap.index("fully dressed"))
        self.assertIn("framing: defaulted waist-up", info["prompt_repairs"])

    def test_a_full_length_framing_is_rewritten_never_silently_allowed(self):
        g, cap, info = self.build("Full-length portrait in the marble "
                                  "foyer, a doorman out of focus behind her.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("ull-length", prompt)
        self.assertNotIn("ull length", prompt.lower())
        self.assertIn("Waist-up portrait in the marble foyer", prompt)
        self.assertIn("framing: full-length -> waist-up",
                      info["prompt_repairs"])
        # the repair already named the framing: no default rides along
        self.assertNotIn("Framed waist-up.", prompt)
        self.assertNotIn("framing: defaulted waist-up", info["prompt_repairs"])

    def test_a_full_length_mirror_is_furniture_not_a_framing(self):
        g, _cap, info = self.build(
            "She stands before a full length mirror in the suite, "
            "adjusting a cuff.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertIn("full length mirror", prompt.lower())
        self.assertNotIn("framing: full-length -> waist-up",
                         info["prompt_repairs"])
        self.assertIn("framing: defaulted waist-up", info["prompt_repairs"])

    def test_a_named_framing_is_respected(self):
        g, _cap, info = self.build(
            "Close-up of her at the restaurant booth, candlelight from the "
            "left.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("Framed waist-up.", prompt)
        self.assertEqual(info["prompt_repairs"], [])

    def test_a_compliant_scene_repairs_nothing_and_still_reports(self):
        _g, _cap, info = self.build(
            "Waist-up, she leans on the bar, a tumbler in hand, the brass "
            "rail lamp warm from the right.")
        self.assertEqual(info["prompt_repairs"], [])
        # 1.1.3b: no camera clause is reported because none is appended.
        self.assertNotIn("camera_clause", info)

    def test_the_local_brains_template_line_names_the_lane(self):
        # Both reference recipes share active-turn guidance rather than
        # duplicating a fixed influencer look in the global template menu.
        templates = server.SYSTEM_LOCAL.split("Templates:")[1]
        self.assertIn("- h3_ref_still / h3_ref_still_2x: the anchored character, photographed.",
                      templates)
        self.assertIn("H3 REFERENCE DIRECTION", templates)
        self.assertIn("character facts and the current request supply age", templates)
        self.assertNotIn("INSIDE a real place", templates)
        self.assertIn("Waist-up or closer", templates)
        self.assertIn("clear of the face", templates)
        self.assertNotIn("HDR holding the highlights", server.SYSTEM_LOCAL)
    # -- 9.85: the three measured rules ----------------------------------

    def test_mid_sentence_survives_the_motion_scrub(self):
        # THE 9.85 regression: "mid-sentence" is a held FACIAL state - the
        # construction on the lane's best-rated frame - not a body in
        # motion. A blanket mid-\w+ rule would quietly undo that result.
        g, _cap, info = self.build(
            "Waist-up, she is caught mid-sentence, a glass halfway to her "
            "lips, the bar lamp warm.")
        self.assertIn("mid-sentence", g["6"]["inputs"]["prompt"])
        self.assertEqual(info["prompt_repairs"], [])

    def test_a_locomotion_verb_is_rewritten_to_a_held_pose(self):
        g, _cap, info = self.build(
            "She is walking along a carpeted hotel corridor, a key card "
            "in hand.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("walking", prompt)
        # the pose is held AND the setting survives
        self.assertIn("standing in a carpeted hotel corridor", prompt)
        self.assertIn("motion: walking -> standing", info["prompt_repairs"])

    def test_caught_mid_laugh_loses_the_clause_not_the_sentence(self):
        g, _cap, info = self.build(
            "Waist-up, she sits at the hotel bar, caught mid-laugh at "
            "something off to the side, a tumbler in hand.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("mid-laugh", prompt)
        self.assertNotIn("off to the side", prompt)
        self.assertIn("she sits at the hotel bar, a tumbler in hand", prompt)
        self.assertIn("motion: caught mid-laugh", info["prompt_repairs"])

    def test_the_measured_counter_caption_is_repaired_unpadded(self):
        # The shot Jesse called wrong every time, at its own length. It
        # loses 8 of 14 words, so 9.80's removed-more-than-half rule
        # refuses it and the clause survives - the caption this contract
        # exists to fix would be the one it declines to fix. The motion
        # and expression classes measure the survivor instead.
        g, _cap, info = self.build(
            "Waist-up at the kitchen island, caught mid-laugh at something "
            "off to the side.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("mid-laugh", prompt)
        self.assertIn("Waist-up at the kitchen island.", prompt)
        self.assertIn("motion: caught mid-laugh", info["prompt_repairs"])

    def test_a_caption_left_with_only_its_framing_is_refused(self):
        # The other end of the same rule, on the contract itself: build()
        # composes the character scaffold around the scene, so the survivor
        # is never bare there. Strip this scene and all that is left is the
        # framing token, which stages no shot.
        cap, repairs = server._h3_still_caption_contract(
            "Waist-up, laughing, eyes crinkled, head tipped back.")
        self.assertIn("kept: expression repair would gut the caption",
                      repairs)
        self.assertIn("laughing", cap)

    def test_a_caption_that_is_only_a_motion_clause_is_refused(self):
        # standing=False: the scene IS the caption, so a scene that is one
        # motion clause has nothing left after the scrub - the repair is
        # refused (repair_scene's rule) and the refusal is what is logged.
        _g, cap, info = self.build("Spinning on her heel.", standing=False)
        self.assertIn("kept: motion repair would gut the caption",
                      info["prompt_repairs"])
        self.assertIn("Spinning", cap)

    def test_capitalization_survives_a_sentence_initial_motion_scrub(self):
        g, _cap, info = self.build(
            "Spinning to face him, she waits by the elevator.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("Spinning", prompt)
        self.assertIn("She waits by the elevator.", prompt)
        self.assertIn("motion: Spinning", info["prompt_repairs"])

    def test_eyes_closing_expressions_are_scrubbed(self):
        g, _cap, info = self.build(
            "Waist-up, she leans on the bar, laughing at his joke, a "
            "tumbler in hand.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("laughing", prompt)
        self.assertIn("she leans on the bar, a tumbler in hand", prompt)
        self.assertIn("expression: laughing", info["prompt_repairs"])

    def test_eyes_closed_dies_with_its_possessive(self):
        g, _cap, info = self.build(
            "Waist-up at the window, with her eyes closed, she listens to "
            "the rain.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("eyes closed", prompt)
        self.assertIn("she listens to the rain", prompt)
        self.assertIn("expression: with her eyes closed",
                      info["prompt_repairs"])

    def test_smiling_grinning_and_smirking_survive(self):
        g, _cap, info = self.build(
            "Waist-up, she is smiling, grinning, almost smirking at him.")
        prompt = g["6"]["inputs"]["prompt"]
        for word in ("smiling", "grinning", "smirking"):
            self.assertIn(word, prompt)
        self.assertEqual(info["prompt_repairs"], [])

    def test_no_skin_clause_is_appended(self):
        # The +73% that justified one was a single frame; re-run across an
        # eight-shot set it came out at a median of 1.00x, better on 2 of 8.
        # The camera clause keeps the tail on its own.
        g, cap, info = self.build("She waits in the lift lobby, lamps low.")
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("vellus", prompt)
        self.assertFalse(hasattr(server, "H3_STILL_SKIN"))
        self.assertNotIn("skin_clause", info)
        self.assertTrue(cap.rstrip().endswith("described above."))

    def test_an_unchanged_caption_renders_the_byte_identical_graph(self):
        scene = ("Waist-up, she leans on the bar, a tumbler in hand, the "
                 "brass rail lamp warm from the right.")
        g1, cap1, info1 = self.build(scene)
        g2, cap2, info2 = self.build(scene)
        self.assertEqual(json.dumps(g1, sort_keys=True),
                         json.dumps(g2, sort_keys=True))
        self.assertEqual(cap1, cap2)
        self.assertEqual(info1["prompt_repairs"], [])
        self.assertEqual(info2["prompt_repairs"], [])


class ClientRoutingTests(unittest.TestCase):
    """Static, in the test_h3_still.py style: the client contracts that keep
    the row pickable under an anchor and honest without one."""

    def test_the_composer_exempts_minimax_h3_from_the_identity_lock(self):
        match = re.search(r"const identityBlocked = \(m\) =>([^;]+);", COMPOSER)
        self.assertIsNotNone(match)
        self.assertIn('m.family !== "minimax_h3"', match.group(1))

    def test_the_no_character_disable_reads_the_recipe_rows(self):
        match = re.search(r"const needsCharModel = \(m\) =>([^;]+);", COMPOSER)
        self.assertIsNotNone(match)
        body = match.group(1)
        # The needs_character flag comes off /api/options' recipe rows,
        # matched by family+variant - the family is not hardcoded again.
        self.assertIn("needs_character", body)
        self.assertIn("variants", body)
        self.assertNotIn("minimax_h3", body)
        self.assertIn("Needs an active character - the reference photo is the "
                      "identity.", COMPOSER)

    def test_the_store_mirrors_the_variant_routing(self):
        # Both chooser branches split on the variant, and since 9.84 each
        # side carries its own quality pair rather than dropping refined.
        self.assertEqual(
            len(re.findall(r'variant === "ref2va"\s*\n?\s*\?\s*\(opts\.quality'
                           r' === "refined" \? "h3_ref_still_2x"'
                           r' : "h3_ref_still"\)', STORE)), 2)
        # Under an anchor the store must not force identity_edit on an H3 pick.
        self.assertRegex(
            STORE, r'idMeta\?\.family === "minimax_h3"')

    def test_the_store_gates_refined_on_the_lanes_own_2x_recipe(self):
        """9.84: withExecutionRecipe used to force quality to "standard"
        whenever the variant was ref2va, and to check h3_still_2x's
        availability for every H3 pick. Both are per-lane now."""
        self.assertIn('idMeta.variant === "ref2va"\n        ? "h3_ref_still_2x"'
                      ' : "h3_still_2x"', STORE)
        self.assertNotIn('idMeta.variant !== "ref2va"', STORE)
        self.assertRegex(STORE, r'r\.id === refineId && r\.available')

    def test_the_label_is_named(self):
        self.assertRegex(NAMES, r'h3_ref_still: "MiniMax H3 Ref"')


if __name__ == "__main__":
    unittest.main()
