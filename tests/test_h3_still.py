"""Brief 9.58 - MiniMax H3 as a still camera: the `h3_still` recipe.

H3's fl2va transformers are video models that also render excellent single
images: a prompt-only MiniMaxH3ImageToVideo at its 5-frame floor decodes to
one real image (frame 0 gets the causal VAE's standalone latent; frames 1-4
share one motion-carrying chunk and decode darker and softer - they are
dropped by ImageFromBatch). The proven graph is Jesse's h3_image.py block,
ported, not redesigned. 20 steps of res_multistep/simple at up to the Max
tier (1536x2048, both sides on the 32 grid); no turbo anything, no audio
VAE, no director pass - the prompt wraps the image lane's own caption in two
deterministic fields.

What these tests pin:

  Classification    - Minimax H3\\ builds file as family minimax_h3, media
                      stays "video", variant ref2va iff the basename carries
                      the token; fl2va supported, ref2va not (with its
                      reason); ltx keeps the plain "video" classification.
  GraphShape        - the queued graph IS the proven block: class per node
                      id, length 5, batch_index 0, seed on RandomNoise, no
                      audio nodes, BasicGuider (CFG-distilled - never
                      CFGGuider), prefix pixal_dm/<slug>.
  Prompt            - both deterministic headers around the image lane's
                      caption.
  Canvas            - mp clamps to the Max-tier ceiling, both sides % 32,
                      info["canvas_mp"] reports the clamped canvas; explicit
                      width/height snap and clamp the same way.
  ModelGate         - a ref2va build is refused by the recipe's variants
                      check; a finetune fl2va build runs.
  Options           - /api/options lists h3_still available with the stock
                      build as default_model, and unavailable with the exact
                      missing label on a stub without the encoder.
  Seat              - the sampler seat writes steps/sampler/scheduler through
                      its map and never offers cfg; defaults report
                      20/res_multistep/simple; existing seats unchanged.
  LoraGate          - lora_compatible refuses every LoRA for minimax_h3 and
                      the popup's key space covers the family, so the picker
                      can never promise a video LoRA the graph would drop.
  AnimateUnchanged  - h3_model_options() is byte-identical on the stub.
  ClientRouting     - static, in the test_lora_card_controls.py style (this
                      repo has no JS runner): store routes the family, the
                      style pill lights Realism only, the MP ladder disables
                      rungs above mp_cap, the Library orders minimax_h3
                      before video, and the labels read like the Animate
                      picker.

Same sanctioned simulation as every sibling file: stubbed catalog, no
generation, no ComfyUI, no GPU.
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
    "pixal_server_h3_still", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

WEB = ROOT / "web" / "src"
STORE = (WEB / "store.js").read_text(encoding="utf-8")
NAMES = (WEB / "lib" / "names.js").read_text(encoding="utf-8")
COMPOSER = (WEB / "components" / "Composer.jsx").read_text(encoding="utf-8")
SETTINGS = (WEB / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")

STOCK = server.H3_MODEL
FINETUNE = "Minimax H3\\10eros_max_fl2va_beta2.safetensors"
REF2VA = server.H3_REF2V_MODEL
LTX = "LTX2\\ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
REF2VA_REASON = "reference-video build - used by the Animate lanes"
MAX_PIXELS = 1536 * 2048


def h3_entries(root, *, encoder=True):
    """This box's H3 stack as catalog entries: the two stock builds, one
    fl2va finetune, the shared encoder and both VAEs (the audio VAE is the
    video lane's - the still graph must never reference it, but it is
    installed)."""
    def add(kind, rel, size=1):
        return {"rel": rel, "kind": kind, "root": str(root),
                "size": size, "mtime": 0.0}
    entries = [add("diffusion_models", STOCK),
               add("diffusion_models", FINETUNE),
               add("diffusion_models", REF2VA),
               add("vae", server.H3_VIDEO_VAE),
               add("vae", server.H3_AUDIO_VAE)]
    if encoder:
        entries.append(add("text_encoders", server.H3_CLIP))
    return entries


def stub_catalog(entries):
    return lambda kind=None: [e for e in entries if kind in (None, e["kind"])]


def no_disk():
    return (patch.object(server, "adjacent_metadata", return_value={}),
            patch.object(server, "model_roots", return_value=[]))


class ClassificationTests(unittest.TestCase):
    """model_profile files the three H3 name shapes; ltx is untouched."""

    def profile(self, rel):
        sidecar, roots = no_disk()
        with sidecar, roots:
            return server.model_profile(rel)

    def test_stock_fl2va_is_a_supported_minimax_h3(self):
        profile = self.profile(STOCK)
        self.assertEqual(profile["family"], "minimax_h3")
        self.assertEqual(profile["variant"], "fl2va")
        self.assertEqual(profile["media"], "video")     # they ARE video models
        self.assertTrue(profile["supported"])
        self.assertEqual(profile["reason"], "")

    def test_a_finetune_fl2va_reads_the_same(self):
        profile = self.profile(FINETUNE)
        self.assertEqual((profile["family"], profile["variant"]),
                         ("minimax_h3", "fl2va"))
        self.assertTrue(profile["supported"])

    def test_ref2va_stays_out_of_the_still_picker(self):
        profile = self.profile(REF2VA)
        self.assertEqual((profile["family"], profile["variant"]),
                         ("minimax_h3", "ref2va"))
        self.assertEqual(profile["media"], "video")
        self.assertFalse(profile["supported"])
        self.assertEqual(profile["reason"], REF2VA_REASON)

    def test_ltx_keeps_the_plain_video_classification(self):
        profile = self.profile(LTX)
        self.assertEqual((profile["family"], profile["variant"]),
                         ("video", "video"))
        self.assertEqual(profile["media"], "video")
        self.assertFalse(profile["supported"])
        self.assertEqual(profile["reason"], "video model")

    def test_compatible_recipes_names_the_still_pair_for_fl2va_only(self):
        # 9.59: fl2va builds serve the still AND its 2x latent refine.
        self.assertEqual(server.compatible_recipes(self.profile(STOCK)),
                         ["h3_still", "h3_still_2x"])
        self.assertEqual(server.compatible_recipes(self.profile(FINETUNE)),
                         ["h3_still", "h3_still_2x"])
        self.assertEqual(server.compatible_recipes(self.profile(REF2VA)), [])
        self.assertEqual(server.compatible_recipes(self.profile(LTX)), [])

    def test_the_recipe_spec(self):
        spec = server.RECIPE_SPECS["h3_still"]
        self.assertEqual(spec["label"], "MiniMax H3")
        self.assertEqual(spec["family"], "minimax_h3")
        self.assertEqual(spec["variants"], ["fl2va"])
        self.assertEqual(spec["default_model"], STOCK)
        self.assertEqual(spec["aspect"], "3:4 (Portrait Standard)")
        self.assertEqual(spec["mp"], 3.1)
        self.assertEqual(spec["mp_cap"], 3.15)
        self.assertEqual(spec["required_text_encoders"], [server.H3_CLIP])
        self.assertEqual(spec["required_vaes"], [server.H3_VIDEO_VAE])
        self.assertNotIn("h3_still", server.VIDEO_TEMPLATES)


class GraphTests(unittest.TestCase):
    """build_h3_still emits the proven block, nothing more."""

    def build(self, scene="A red barn at dusk", seed=424242, entries=None,
              **kwargs):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            entries = h3_entries(root) if entries is None else entries
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)):
                return server.build_h3_still(scene, seed, **kwargs)

    def test_the_graph_is_the_proven_block(self):
        g, _cap, _info = self.build()
        self.assertEqual(sorted(g, key=int),
                         ["1", "2", "3", "6", "7", "8", "9", "10",
                          "11", "12", "13", "14"])
        classes = {nid: node["class_type"] for nid, node in g.items()}
        self.assertEqual(classes, {
            "1": "UNETLoader", "2": "CLIPLoader", "3": "VAELoader",
            "6": "MiniMaxH3ImageToVideo", "7": "KSamplerSelect",
            "8": "BasicScheduler", "9": "BasicGuider",
            "10": "RandomNoise", "11": "SamplerCustomAdvanced",
            "12": "VAEDecode", "13": "ImageFromBatch", "14": "SaveImage"})
        self.assertNotIn("CFGGuider", classes.values())
        self.assertEqual(g["1"]["inputs"],
                         {"unet_name": STOCK, "weight_dtype": "default"})
        self.assertEqual(g["2"]["inputs"], {"clip_name": server.H3_CLIP,
                                            "type": "minimax",
                                            "device": "default"})
        self.assertEqual(g["3"]["inputs"],
                         {"vae_name": server.H3_VIDEO_VAE})
        self.assertEqual(g["6"]["inputs"]["clip"], ["2", 0])
        self.assertEqual(g["6"]["inputs"]["vae"], ["3", 0])
        self.assertEqual(g["6"]["inputs"]["length"], 5)
        self.assertEqual(g["7"]["inputs"], {"sampler_name": "res_multistep"})
        self.assertEqual(g["8"]["inputs"], {"model": ["1", 0],
                                            "scheduler": "simple",
                                            "steps": 20, "denoise": 1.0})
        self.assertEqual(g["9"]["inputs"], {"model": ["1", 0],
                                            "conditioning": ["6", 0]})
        self.assertEqual(g["10"]["inputs"], {"noise_seed": 424242})
        self.assertEqual(g["11"]["inputs"], {"noise": ["10", 0],
                                             "guider": ["9", 0],
                                             "sampler": ["7", 0],
                                             "sigmas": ["8", 0],
                                             "latent_image": ["6", 1]})
        self.assertEqual(g["12"]["inputs"], {"samples": ["11", 0],
                                             "vae": ["3", 0]})
        self.assertEqual(g["13"]["inputs"], {"image": ["12", 0],
                                             "batch_index": 0, "length": 1})
        self.assertEqual(g["14"]["inputs"]["images"], ["13", 0])
        self.assertEqual(g["14"]["inputs"]["filename_prefix"],
                         "pixal_dm/a_red_barn_at_dusk")

    def test_no_audio_anywhere(self):
        g, _cap, _info = self.build()
        wire = json.dumps(g).lower()
        for nid, node in g.items():
            self.assertNotIn("audio", node["class_type"].lower(), nid)
        self.assertNotIn("audio_vae", wire)
        self.assertNotIn(server.H3_AUDIO_VAE.lower(), wire)
        self.assertNotIn("videocombine", wire)

    def test_the_prompt_wraps_the_caption_deterministically(self):
        g, cap, _info = self.build()
        prompt = g["6"]["inputs"]["prompt"]
        self.assertTrue(prompt.startswith(
            "integrated_multimodal_description: [Shot 1] Live-action, "
            "a frozen instant held completely still - "))
        self.assertIn(cap, prompt)
        self.assertIn("A red barn at dusk", prompt)
        self.assertIn("The subject holds the pose; nothing in the frame "
                      "moves.", prompt)
        self.assertTrue(prompt.endswith(
            "\n\noverall_soundscape: Room tone, steady, synchronized."))
        # The still lane never calls the director: no H3 video fields.
        self.assertNotIn("non_diegetic_music", prompt)
        self.assertNotIn("Audio:", prompt)

    def test_the_default_canvas_is_the_max_tier_3_4(self):
        g, _cap, info = self.build()
        self.assertEqual(g["6"]["inputs"]["width"], 1536)
        self.assertEqual(g["6"]["inputs"]["height"], 2048)
        self.assertEqual(info["size"], "1536x2048")
        self.assertAlmostEqual(info["canvas_mp"], 3.15, delta=0.01)

    def test_an_8mp_ask_clamps_to_the_ceiling_on_the_32_grid(self):
        g, _cap, info = self.build(mp=8)
        width, height = g["6"]["inputs"]["width"], g["6"]["inputs"]["height"]
        self.assertEqual((width % 32, height % 32), (0, 0))
        self.assertLessEqual(width * height, MAX_PIXELS)
        self.assertEqual((width, height), (1536, 2048))
        self.assertEqual(info["canvas_mp"], width * height / 1e6)

    def test_a_wide_aspect_never_exceeds_the_ceiling(self):
        # dims_for alone overshoots the cap on wide aspects (2368x1344 at
        # 3.15 MP): the builder walks the long edge back under it.
        g, _cap, info = self.build(aspect="16:9 (Widescreen)", mp=3.15)
        width, height = g["6"]["inputs"]["width"], g["6"]["inputs"]["height"]
        self.assertEqual((width % 32, height % 32), (0, 0))
        self.assertLessEqual(width * height, MAX_PIXELS)
        self.assertEqual(info["canvas_mp"], width * height / 1e6)

    def test_an_explicit_canvas_is_snapped_and_clamped(self):
        g, _cap, info = self.build(width=2000, height=2000)
        width, height = g["6"]["inputs"]["width"], g["6"]["inputs"]["height"]
        self.assertEqual((width % 32, height % 32), (0, 0))
        self.assertLessEqual(width * height, MAX_PIXELS)
        self.assertEqual(info["size"], f"{width}x{height}")

    def test_a_finetune_build_runs_and_is_attested(self):
        g, _cap, info = self.build(model=FINETUNE)
        self.assertEqual(g["1"]["inputs"]["unet_name"], FINETUNE)
        self.assertEqual(info["model_path"], FINETUNE)
        self.assertEqual(info["model_family"], "minimax_h3")
        self.assertEqual(info["model_variant"], "fl2va")
        server.validate_job_model_info("h3_still", info, g)

    def test_a_ref2va_build_is_refused(self):
        with self.assertRaisesRegex(ValueError, "uses fl2va models"):
            self.build(model=REF2VA)

    def test_info_names_the_stack_and_no_loras_ran(self):
        g, _cap, info = self.build()
        self.assertEqual(info["execution_profile"], "h3_still")
        self.assertEqual(info["text_encoder"],
                         "qwen3vl_32b_minimax_h3_nvfp4_awq")
        self.assertEqual(info["vae"], "minimax_h3_video_vae_fp16")
        self.assertEqual(info["loras"], [])
        self.assertEqual(info["lora_stack"], [])
        self.assertIsNone(info["character"])
        server.validate_job_model_info("h3_still", info, g)

    def test_overrides_apply_after_the_seed(self):
        g, _cap, _info = self.build(overrides=[
            {"node": "8", "input": "steps", "value": 12},
            {"node": "10", "input": "noise_seed", "value": 7}])
        self.assertEqual(g["8"]["inputs"]["steps"], 12)
        self.assertEqual(g["10"]["inputs"]["noise_seed"], 7)

    def test_the_builder_is_registered(self):
        self.assertIs(server.BUILDERS["h3_still"], server.build_h3_still)
        self.assertIn("h3_still", server.PUBLIC_RECIPE_IDS)
        self.assertIn("h3_still", server.SIGS)

    def test_effective_recipe_routes_an_h3_pick(self):
        # 9.59: the style still never routes away from the H3 family; the
        # Refined quality now picks the 2x refine, standard stays h3_still.
        with TemporaryDirectory() as td:
            root = Path(td)
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                self.assertEqual(
                    server.effective_recipe({"model": STOCK, "style": "anime",
                                             "quality": "refined"}),
                    "h3_still_2x")
                self.assertEqual(
                    server.effective_recipe({"model": STOCK, "style": "anime",
                                             "quality": "standard"}),
                    "h3_still")
                self.assertEqual(server.effective_recipe({"model": STOCK}),
                                 "h3_still")


class OptionsTests(unittest.TestCase):
    """/api/options on a stub catalog: the recipe, the shelf, the gate."""

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

    def test_h3_still_is_available_with_the_stock_default(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td)))
        recipe = next(r for r in options["recipes"] if r["id"] == "h3_still")
        self.assertTrue(recipe["available"])
        self.assertEqual(recipe["missing"], [])
        self.assertEqual(recipe["default_model"], STOCK)
        self.assertEqual(recipe["family"], "minimax_h3")
        self.assertEqual(recipe["variants"], ["fl2va"])
        self.assertEqual(recipe["mp_cap"], 3.15)
        # The composer's defaults row carries the recipe's own canvas.
        self.assertEqual(options["defaults"]["h3_still"]["mp"], 3.1)
        self.assertEqual(options["defaults"]["h3_still"]["aspect"],
                         "3:4 (Portrait Standard)")

    def test_the_shelf_marks_fl2va_supported_and_ref2va_not(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td)))
        meta = options["model_meta"]
        for rel in (STOCK, FINETUNE):
            self.assertEqual(meta[rel]["family"], "minimax_h3")
            self.assertTrue(meta[rel]["supported"])
            self.assertIn("h3_still", meta[rel]["compatible_recipes"])
        self.assertEqual(meta[REF2VA]["family"], "minimax_h3")
        self.assertFalse(meta[REF2VA]["supported"])
        self.assertEqual(meta[REF2VA]["reason"], REF2VA_REASON)
        self.assertNotIn("h3_still", meta[REF2VA]["compatible_recipes"])

    def test_a_stub_without_the_encoder_names_the_missing_piece(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td), encoder=False))
        recipe = next(r for r in options["recipes"] if r["id"] == "h3_still")
        self.assertFalse(recipe["available"])
        self.assertEqual(recipe["missing"],
                         ["text encoder: " + server.H3_CLIP])

    def test_a_stub_without_any_h3_build_names_the_family(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            entries = [e for e in h3_entries(root)
                       if e["kind"] != "diffusion_models"]
            options = self.options(entries)
        recipe = next(r for r in options["recipes"] if r["id"] == "h3_still")
        self.assertFalse(recipe["available"])
        self.assertIn("compatible minimax_h3 diffusion model",
                      recipe["missing"])


class SeatTests(unittest.TestCase):
    """The seat maps its keys onto three nodes and never offers cfg."""

    def test_the_seat_is_the_mapped_ksamplerselect(self):
        seat = server.SAMPLER_SEATS["h3_still"]
        self.assertEqual(seat["node"], "7")
        self.assertEqual(seat["class"], "KSamplerSelect")
        self.assertEqual(seat["map"], {
            "sampler_name": [("7", "sampler_name")],
            "steps": [("8", "steps")],
            "scheduler": [("8", "scheduler")]})

    def test_cfg_is_not_a_tunable_here(self):
        keys = server.seat_tuning_keys(server.SAMPLER_SEATS["h3_still"])
        self.assertEqual(keys, ("steps", "sampler_name", "scheduler"))
        self.assertNotIn("cfg", keys)

    def test_existing_seats_are_unchanged(self):
        # The Amazing v4 seat's map carries exactly its old tuning set.
        self.assertEqual(server.seat_tuning_keys(server.ZIMAGE_V4_SEAT),
                         ("steps", "cfg", "sampler_name"))
        # A mapless seat still reads its class row.
        self.assertEqual(
            server.seat_tuning_keys({"node": "8", "class": "KSampler"}),
            ("steps", "cfg", "sampler_name", "scheduler"))
        self.assertEqual(
            server.seat_tuning_keys({"node": "30:51",
                                     "class": "ClownsharKSampler_Beta"}),
            ("steps", "cfg", "sampler_name", "scheduler", "eta"))

    def test_defaults_report_the_still_recipe(self):
        self.assertEqual(server.sampler_defaults("h3_still"),
                         {"steps": 20, "sampler_name": "res_multistep",
                          "scheduler": "simple"})

    def test_tuning_writes_through_the_map_and_drops_cfg(self):
        overrides = server.tuning_overrides(
            "h3_still", None,
            {"steps": 12, "cfg": 3.5, "sampler_name": "euler",
             "scheduler": "beta", "eta": 0.3})
        self.assertEqual(overrides, [
            {"node": "8", "input": "steps", "value": 12},
            {"node": "7", "input": "sampler_name", "value": "euler"},
            {"node": "8", "input": "scheduler", "value": "beta"}])


class LoraGateTests(unittest.TestCase):
    """The add-LoRA popup can offer nothing for minimax_h3: no LoRA
    classifies to the family, so every verdict is a refusal - and the
    popup's key space covers the family, so the client lookup finds that
    refusal instead of falling through to 'compatible'."""

    def test_every_lora_is_refused_for_minimax_h3(self):
        sidecar, roots = no_disk()
        with sidecar, roots:
            self.assertEqual(
                server.lora_compatible("Krea 2\\whatever.safetensors",
                                       "minimax_h3", "fl2va"),
                "family")
            # An H3 VIDEO LoRA is no still LoRA: the loras catalog knows no
            # minimax_h3 row, so it files unknown and refuses as unknown.
            self.assertEqual(
                server.lora_compatible(server.H3_HMNSFW_LORA,
                                       "minimax_h3", "fl2va"),
                "unknown")

    def test_the_popup_key_space_covers_minimax_h3(self):
        self.assertIn("minimax_h3:any", server._LORA_PROFILE_KEYS)
        self.assertIn("minimax_h3:fl2va", server._LORA_PROFILE_KEYS)


class AnimatePickerUnchangedTests(unittest.TestCase):
    """The Animate lanes resolve H3 builds by catalog rel and never read
    model_profile's family: the classification change must not move their
    picker. Snapshot on the stub catalog."""

    def test_h3_model_options_is_byte_identical(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                options = server.h3_model_options()
        self.assertEqual(options, [
            {"id": "fl2va", "rel": STOCK, "label": "FL2VA",
             "description": "First-frame video with native synchronized "
                            "audio."},
            {"id": "ref2va", "rel": REF2VA, "label": "REF2VA",
             "description": "Reference-to-video: this subject, carried into "
                            "a new scene, with native synchronized audio."},
            {"id": "10eros_max_fl2va_beta2", "rel": FINETUNE,
             "label": "10Eros Max Beta2",
             "description": "Community FL2VA finetune - same encoder, VAEs "
                            "and LoRA catalog as stock."}])

    def test_the_video_lanes_four_asset_check_is_unchanged(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                paths, missing = server._h3_asset_paths(STOCK)
        self.assertEqual(missing, [])
        self.assertEqual(paths, {"model": STOCK, "clip": server.H3_CLIP,
                                 "video_vae": server.H3_VIDEO_VAE,
                                 "audio_vae": server.H3_AUDIO_VAE})

    def test_the_still_lane_drops_the_audio_vae_requirement(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            entries = [e for e in h3_entries(root)
                       if e["rel"] != server.H3_AUDIO_VAE]
            with patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)):
                paths, missing = server._h3_asset_paths(STOCK, audio=False)
                self.assertEqual(missing, [])
                self.assertNotIn("audio_vae", paths)
                # ...while the video lane still demands it.
                _paths, missing = server._h3_asset_paths(STOCK)
                self.assertEqual(missing, ["MiniMax H3 audio VAE"])


class ButlerBillTests(unittest.TestCase):
    """graph_weight_bill prices what the graph pages in: the transformer and
    the nvfp4 encoder are the heavies, the video VAE rides the light pile."""

    def test_the_bill_sees_all_three_loaders(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            sizes = {STOCK: 1000, server.H3_CLIP: 500,
                     server.H3_VIDEO_VAE: 100}
            entries = []
            for kind, rel in (("diffusion_models", STOCK),
                              ("text_encoders", server.H3_CLIP),
                              ("vae", server.H3_VIDEO_VAE)):
                path = root / kind / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x" * sizes[rel])
                entries.append({"rel": rel, "kind": kind, "root": str(root),
                                "size": sizes[rel], "mtime": 0.0})
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)):
                g, _cap, _info = server.build_h3_still("a barn", 1)
                heavy, peak = server.graph_weight_bill(g)
        self.assertEqual(heavy, {STOCK: 1000, server.H3_CLIP: 500})
        self.assertEqual(peak, 1000 + 100)   # heaviest heavy + the VAE


class ClientRoutingTests(unittest.TestCase):
    """Static, in the test_lora_card_controls.py style: the contracts the
    client source must keep for the family to be pickable and honest."""

    def test_store_routes_minimax_h3_to_the_h3_still_pair(self):
        # 9.59: refined goes to the 2x refine, standard to the plain still.
        self.assertRegex(
            STORE, r'meta\?\.family === "minimax_h3"\)\s*'
                   r'return opts\.quality === "refined" '
                   r'\? "h3_still_2x" : "h3_still";')

    def test_store_pins_realism_and_gates_refined_for_minimax_h3(self):
        # 9.59: the style pin stays; quality is refined exactly when the
        # h3_still_2x recipe is available, standard otherwise.
        self.assertRegex(
            STORE, r'meta\?\.family === "minimax_h3"\) \{\s*'
                   r'style = "realism";')
        self.assertIn('recipe.id === "h3_still_2x" && recipe.available', STORE)

    def test_the_style_pill_lights_realism_only(self):
        self.assertRegex(
            COMPOSER, r'selectedModelMeta\.family === "minimax_h3"\)\s*'
                      r'return style === "realism"')

    def test_the_mp_ladder_caps_at_the_recipe_ceiling(self):
        # The cap rides the recipe payload...
        self.assertIn("mp_cap", COMPOSER)
        # ...rungs above it render disabled with the cap named...
        self.assertRegex(COMPOSER, r"tops out at")
        # ...and the readout clamps a stored mp instead of promising a
        # canvas the model cannot render.
        lines = COMPOSER.splitlines()
        at = next(i for i, l in enumerate(lines) if "const canvasDims" in l)
        self.assertIn("Math.min", "\n".join(lines[at:at + 3]))

    def test_family_labels_and_template_names(self):
        self.assertRegex(NAMES, r'minimax_h3: "MiniMax H3"')
        self.assertRegex(NAMES, r'h3_still: "MiniMax H3"')

    def test_the_library_orders_minimax_h3_before_video(self):
        match = re.search(r"LIBRARY_ORDER = \[([^\]]*)\]", SETTINGS)
        self.assertIsNotNone(match)
        order = re.findall(r'"(\w+)"', match.group(1))
        self.assertIn("minimax_h3", order)
        self.assertLess(order.index("minimax_h3"), order.index("video"))

    def test_the_library_knows_the_ref2va_reason(self):
        self.assertIn(REF2VA_REASON, SETTINGS)

    def test_model_labels_read_like_the_animate_picker(self):
        match = re.search(r'family === "minimax_h3"([\s\S]*?)\n  \}', NAMES)
        self.assertIsNotNone(match)
        branch = match.group(1)
        # The server's _h3_finetune_label drop set, mirrored: packaging words
        # drop and the finetune's identity words survive.
        for word in ("h3", "fl2va", "ref2va", "pruned", "int8", "convrot",
                     "comfyui", "minimax"):
            self.assertIn(word, branch)
        # A stem that is ALL packaging (the stock builds) composes family +
        # variant + quant instead - "H3 FL2VA int8".
        self.assertIn('"H3"', branch)
        self.assertIn('"FL2VA"', branch)
        self.assertIn('"REF2VA"', branch)
        # The old one-label-per-lane collapse is gone.
        self.assertNotIn("MiniMax H3 I2V", branch)
        self.assertNotIn("MiniMax H3 Reference", branch)


if __name__ == "__main__":
    unittest.main()
