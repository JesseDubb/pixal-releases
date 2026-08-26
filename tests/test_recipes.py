import asyncio
import json
import time
import unittest
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch


_SPEC = spec_from_file_location("pixal_server", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def model(rel, family, variant="any", **extra):
    return {
        "rel": rel,
        "kind": "diffusion_models",
        "family": family,
        "variant": variant,
        "supported": True,
        **extra,
    }


def plan(recipe, entries):
    return {
        "version": 1,
        "recipe": recipe,
        "recipe_revision": server.RECIPE_SPECS[recipe]["lora_stack_revision"],
        "mode": "replace_editable",
        "entries": entries,
    }


def lora_chain(graph, sink):
    """Follow a sink's model input backward and return LoRAs in execution order."""
    link = graph[sink]["inputs"]["model"]
    chain = []
    while isinstance(link, list) and link[0] in graph:
        node = graph[link[0]]
        if node.get("class_type") != "LoraLoaderModelOnly":
            break
        chain.append((node["inputs"]["lora_name"], node["inputs"]["strength_model"]))
        link = node["inputs"]["model"]
    return list(reversed(chain))


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
def identity_anchor(with_ref=True):
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        character = {"id": "hero", "name": "Hero", "style": "silver hair"}
        if with_ref:
            character["identity_ref"] = "hero.png"
            (root / "input" / "hero.png").write_bytes(b"reference")
        with patch.object(server, "CDIR", root), \
             patch.object(server, "CHARACTERS", {"hero": character}):
            yield root, character


class RecipeTests(unittest.TestCase):
    def test_public_registry_is_the_api_surface(self):
        self.assertEqual(
            server.PUBLIC_RECIPE_IDS,
            ("realism", "realism_ii", "fantasy", "anime", "zimage", "identity_edit",
             "qwen_edit", "qwen_image", "face_mint", "klein_inpaint", "klein_edit",
             "anima"),
        )
        self.assertTrue(set(server.PUBLIC_RECIPE_IDS).issubset(server.BUILDERS))

    def test_source_only_recipes_are_not_creative_styles(self):
        """qwen_edit and face_mint have no text-to-image path: they must stay
        reachable only from an existing image, and qwen_edit's model must never
        surface in the composer.

        face_mint is source-only for a different reason than qwen_edit. It runs
        ordinary Krea 2 models - which do belong in the composer - but the recipe
        itself rewrites a photograph, so there is nothing for it to do without
        one. Only qwen_edit's *models* are source_only; face_mint's are not.
        """
        self.assertEqual(server.SOURCE_ONLY_RECIPE_IDS,
                         {"qwen_edit", "face_mint", "klein_inpaint", "klein_edit"})
        mint_model = server.model_profile(
            server.RECIPE_SPECS["face_mint"]["default_model"])
        self.assertFalse(mint_model.get("source_only", False))
        profile = server.model_profile("Qwen\\Qwen_Image_Edit-Q6_K.gguf")
        self.assertEqual(profile["family"], "qwen_edit")
        self.assertTrue(profile["supported"])
        self.assertTrue(profile["source_only"])
        self.assertEqual(server.compatible_recipes(profile), ["qwen_edit"])
        # a normal still model must not gain the edit recipe
        krea = server.model_profile("Krea 2\\krea2_turbo_mxfp8.safetensors")
        self.assertNotIn("qwen_edit", server.compatible_recipes(krea))
        self.assertFalse(krea.get("source_only", False))
        # a Klein build serves BOTH klein lanes - the masked picker and the
        # whole-frame one list the same installs
        klein = server.model_profile(server.KLEIN_MODEL)
        self.assertEqual(klein["family"], "klein")
        self.assertTrue(klein["source_only"])
        self.assertEqual(server.compatible_recipes(klein),
                         ["klein_inpaint", "klein_edit"])

    def test_new_model_badge_reads_the_file_not_pixals_memory(self):
        """The picker's NEW chip must mean "you just downloaded this". Reading the
        file's own mtime is what makes that unpoisonable: an earlier first-seen
        ledger re-badged the entire collection the moment any caller handed it a
        partial model list, which the test suite itself did."""
        now = 1_800_000_000.0
        fresh = {"rel": "new.safetensors", "mtime": now - 3600}
        old = {"rel": "old.safetensors", "mtime": now - 400 * 86400}
        self.assertTrue(server.is_new_model(fresh, now))
        self.assertFalse(server.is_new_model(old, now))
        # the badge expires rather than sticking to a model forever
        self.assertFalse(server.is_new_model(
            {"rel": "x", "mtime": now - server.MODEL_NEW_WINDOW - 1}, now))
        # an unreadable stat must not invent newness
        self.assertFalse(server.is_new_model({"rel": "x", "mtime": 0}, now))
        self.assertFalse(server.is_new_model({"rel": "x"}, now))

    def test_catalog_entries_carry_mtime(self):
        """is_new_model reads entry["mtime"], so the scan has to record it."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "models" / "loras").mkdir(parents=True)
            (root / "models" / "loras" / "a.safetensors").write_bytes(b"x")
            with patch.object(server, "model_roots", return_value=[root / "models"]), \
                 patch.dict(server._CATALOG, {"at": 0, "data": None}):
                entries = server.model_catalog("loras")
        self.assertEqual(len(entries), 1)
        self.assertGreater(entries[0]["mtime"], 0)

    def test_identity_edit_runs_the_v1_2_lora_at_its_own_settings(self):
        """The LoRA is v1.2, so the graph must use v1.2's numbers, not v1's.
        grounding_px stayed at 1536 (v1's range) after the weights moved to v1.2,
        which the LoRA's own notes call the most common cause of duplicated or
        split compositions - its trained range is 384-768. ref_boost is the v1.2
        likeness dial and defaults to 1.0 (off), so it has to be set to be used."""
        # Assert on the BUILT graph, not the template: the builder overwrites
        # grounding_px from its own default, so a template-only fix was dead code.
        entry = model("Krea 2\\krea2_turbo_mxfp8.safetensors", "krea2")
        with identity_anchor() as (root, _), assets(entry):
            (root / "input" / "face.png").write_bytes(b"face")
            graph, _c, _i = server.build_zara_edit("on a rooftop", 3, ref="face.png")
        encode = next(n for n in graph.values()
                      if n.get("class_type") == "Krea2EditGroundedEncode")
        patch = next(n for n in graph.values()
                     if n.get("class_type") == "Krea2EditModelPatch")
        self.assertLessEqual(encode["inputs"]["grounding_px"], 1024)
        self.assertGreaterEqual(encode["inputs"]["grounding_px"], 384)
        self.assertGreater(patch["inputs"]["ref_boost"], 1.0)
        # the blur-proof pixel path: without vae + source_image a mismatched
        # source/output resolution comes back soft
        self.assertEqual(patch["inputs"]["fit_mode"], "fit")
        for wired in ("vae", "source_image", "target_latent"):
            with self.subTest(input=wired):
                self.assertIn(wired, patch["inputs"])

    def test_builder_defaults_agree_with_their_template_literals(self):
        """A template literal that the builder always overwrites with a DIFFERENT
        value is a lie about what runs, and editing it fixes nothing. That is how
        identity_edit kept running v1's grounding_px 1536 while the JSON said 768.
        Where both sides name a value, they have to agree."""
        self.assertEqual(server.TEMPLATES["identity_edit"]["30:6"]["inputs"]
                         ["grounding_px"], server.IDENTITY_GROUNDING_PX)
        self.assertEqual(server.TEMPLATES["identity_edit"]["ed:patch"]["inputs"]
                         ["ref_boost"], server.IDENTITY_REF_BOOST)
        # the LTX graph's own frame rate is what seconds are converted at
        self.assertEqual(float(server.TEMPLATES["ltx_i2v"]["285"]["inputs"]["value"]),
                         float(server.LTX_FPS_DEFAULT))
        # a template someone loads straight into ComfyUI should render what Pixal
        # renders, so the empty latent carries the builder's default canvas
        spec = server.RECIPE_SPECS["qwen_image"]
        width, height = server.dims_for(spec["aspect"], spec["mp"])
        latent = server.TEMPLATES["qwen_image"]["qi:latent"]["inputs"]
        self.assertEqual((latent["width"], latent["height"]), (width, height))

    def test_zimage_vae_override_is_opt_in_and_leaves_anime_alone(self):
        """A sharper drop-in decoder (UltraFlux) is a taste call on finished work,
        so an unset override must change nothing. The clear-anime profile ships a
        matched VAE and must not be overridden at all."""
        base = {"vae_candidates": server.ZIMAGE_VAE_CANDIDATES}
        anime = {"vae_candidates": (server.ZIMAGE_ANIME_VAE,)}
        with patch.object(server, "load_config", return_value={"vae": {"zimage": ""}}):
            self.assertEqual(server.zimage_vae_candidates(base),
                             tuple(server.ZIMAGE_VAE_CANDIDATES))
        picked = "Flux\\ultrafluxVAEImproved_v10.safetensors"
        with patch.object(server, "load_config",
                          return_value={"vae": {"zimage": picked}}):
            got = server.zimage_vae_candidates(base)
            self.assertEqual(got[0], picked)
            # the stock VAEs stay as fallbacks rather than being replaced
            self.assertEqual(set(got[1:]), set(server.ZIMAGE_VAE_CANDIDATES))
            self.assertEqual(server.zimage_vae_candidates(anime),
                             (server.ZIMAGE_ANIME_VAE,))

    def test_the_two_qwen_lines_do_not_collide(self):
        """Qwen-Image-Edit and Qwen-Image share a name and their encoder and VAE,
        but they are different pipelines: the edit line is source-only, the image
        line is a normal creative style. Classifying either as the other silently
        sends a render to the wrong graph."""
        edit = server.model_profile("Qwen\\Qwen-Image-Edit-2511-Q6_K.gguf")
        gen = server.model_profile("Qwen\\qwen_image_2512_fp8_e4m3fn.safetensors")
        self.assertEqual(edit["family"], "qwen_edit")
        self.assertEqual(gen["family"], "qwen_image")
        self.assertTrue(edit["source_only"])
        self.assertFalse(gen.get("source_only", False))
        self.assertEqual(server.compatible_recipes(gen), ["qwen_image"])
        self.assertNotIn("qwen_image", server.SOURCE_ONLY_RECIPE_IDS)

    def test_qwen_image_graph_matches_the_shipped_2512_workflow(self):
        gen = model("Qwen\\qwen_image_2512_fp8_e4m3fn.safetensors", "qwen_image", "any")
        with assets(gen):
            graph, cap, info = server.build_qwen_image("a woman at a bar", 5)
        self.assert_graph_links("qwen_image", graph)
        self.assertIn("a woman at a bar", cap)
        self.assertEqual(graph["qi:shift"]["inputs"]["shift"], server.QWEN_IMAGE_SHIFT)
        self.assertEqual(graph["qi:clip"]["inputs"]["type"], "qwen_image")
        self.assertEqual(graph["qi:neg"]["inputs"]["text"], "")
        sampler = graph["qi:sampler"]["inputs"]
        self.assertEqual(
            (sampler["steps"], sampler["cfg"], sampler["sampler_name"],
             sampler["scheduler"], sampler["denoise"], sampler["seed"]),
            (server.QWEN_IMAGE_STEPS, server.QWEN_IMAGE_CFG, "euler", "simple", 1.0, 5))
        # the edit graph's CFGNorm belongs to the edit graph only
        self.assertNotIn("CFGNorm", [n.get("class_type") for n in graph.values()])
        width, height = (int(v) for v in info["size"].split("x"))
        self.assertEqual((graph["qi:latent"]["inputs"]["width"],
                          graph["qi:latent"]["inputs"]["height"]), (width, height))

    def test_qwen_edit_graph_keeps_its_load_bearing_wiring(self):
        """The three ways this graph silently degrades: a zeroed-out negative
        (loses the reference latents CFG needs), a VAE wired into an encoder
        (TextEncodeQwenImageEdit only builds a reference latent when it has one,
        and builds it from its own forced ~1 MP "area" downscale - that is the
        softness and drift this graph exists to avoid), and a reference latent
        that is not the sampler's own latent (they must be one node so they
        cannot desynchronise)."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "shot.png").write_bytes(b"source")
            with patch.object(server, "CDIR", root), \
                 assets(model("Qwen\\Qwen_Image_Edit-Q6_K.gguf", "qwen_edit", "edit")):
                graph, caption, info = server.build_qwen_edit(
                    "make her jacket red", 7, image="shot.png")

        self.assert_graph_links("qwen_edit", graph)
        self.assertEqual(caption, "make her jacket red")
        self.assertEqual(info["source_image"], "shot.png")

        for branch in ("qe:pos", "qe:neg"):
            with self.subTest(branch=branch):
                node = graph[branch]
                self.assertEqual(node["class_type"], "TextEncodeQwenImageEdit")
                self.assertNotIn("vae", node["inputs"])
                self.assertEqual(node["inputs"]["image"], ["qe:img", 0])
        self.assertEqual(graph["qe:pos"]["inputs"]["prompt"], "make her jacket red")
        self.assertEqual(graph["qe:neg"]["inputs"]["prompt"], "")
        self.assertNotIn("ConditioningZeroOut",
                         [n.get("class_type") for n in graph.values()])

        # Both branches carry the reference latent, and it is the very tensor the
        # sampler starts from - one node, so no resize can drift them apart.
        for nid, source in (("qe:ref", "qe:pos"), ("qe:refneg", "qe:neg")):
            with self.subTest(reference=nid):
                node = graph[nid]
                self.assertEqual(node["class_type"], "ReferenceLatent")
                self.assertEqual(node["inputs"]["conditioning"], [source, 0])
                self.assertEqual(node["inputs"]["latent"], ["qe:latent", 0])
        self.assertEqual(graph["qe:sampler"]["inputs"]["positive"], ["qe:ref", 0])
        self.assertEqual(graph["qe:sampler"]["inputs"]["negative"], ["qe:refneg", 0])

        self.assertEqual(graph["qe:clip"]["inputs"]["type"], "qwen_image")
        self.assertEqual(graph["qe:latent"]["inputs"]["pixels"], ["qe:scale", 0])
        self.assertEqual(graph["qe:shift"]["inputs"]["shift"], 3.0)
        self.assertEqual(graph["qe:cfgnorm"]["inputs"]["strength"], 1.0)
        sampler = graph["qe:sampler"]["inputs"]
        self.assertEqual(
            (sampler["steps"], sampler["cfg"], sampler["sampler_name"],
             sampler["scheduler"], sampler["denoise"], sampler["seed"]),
            (20, 2.5, "euler", "simple", 1.0, 7))

    def _qwen_edit_for_source(self, size, model_name="Qwen\\Qwen_Image_Edit-Q6_K.gguf"):
        from PIL import Image
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            Image.new("RGB", size, "#333").save(root / "input" / "shot.png")
            with patch.object(server, "CDIR", root), \
                 assets(model(model_name, "qwen_edit", "edit")):
                return server.build_qwen_edit("make it night", 1, image="shot.png")

    def test_qwen_edit_keeps_the_source_at_its_own_size(self):
        """An edit should hand back the frame it was given, not a 1 MP copy of it.
        The job card also sizes its live preview from info["size"]."""
        _g, _c, info = self._qwen_edit_for_source((1152, 1728))
        self.assertEqual(info["size"], "1152x1728")

    def test_qwen_edit_caps_an_oversized_source(self):
        """Native size is the default, not a promise - the sampler still has a
        ceiling, and the result must stay on the source's aspect."""
        _g, _c, info = self._qwen_edit_for_source((4096, 4096))
        width, height = (int(v) for v in info["size"].split("x"))
        self.assertEqual(width, height)
        # Each side is rounded UP to a multiple of 8 for the VAE, so the area may
        # sit a little over the cap - up to 7px on each side of a ~1450px canvas.
        self.assertLessEqual(width * height,
                             server.QWEN_EDIT_MP_CAP * 1024 * 1024 * 1.02)

    def test_qwen_edit_switches_to_the_plus_encoder_for_dated_releases(self):
        """2509 and later ship as TextEncodeQwenImageEditPlus, which numbers its
        image inputs. Recognising that by filename is what lets a newer Qwed edit
        model drop in without a second template."""
        graph, _c, _i = self._qwen_edit_for_source(
            (1024, 1024), "Qwen\\Qwen_Image_Edit_2511-Q6_K.gguf")
        for branch in ("qe:pos", "qe:neg"):
            with self.subTest(branch=branch):
                node = graph[branch]
                self.assertEqual(node["class_type"], "TextEncodeQwenImageEditPlus")
                self.assertEqual(node["inputs"]["image1"], ["qe:img", 0])
                self.assertNotIn("image", node["inputs"])
                self.assertNotIn("vae", node["inputs"])

    def test_qwen_edit_refuses_a_missing_or_empty_source(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            with patch.object(server, "CDIR", root), \
                 assets(model("Qwen\\Qwen_Image_Edit-Q6_K.gguf", "qwen_edit", "edit")):
                with self.assertRaises(ValueError):
                    server.build_qwen_edit("make it red", 1, image="gone.png")
                (root / "input" / "shot.png").write_bytes(b"source")
                with self.assertRaises(ValueError):
                    server.build_qwen_edit("   ", 1, image="shot.png")
                with self.assertRaises(ValueError):
                    server.build_qwen_edit("make it red", 1, image="../escape.png")

    def test_qwen_edit_lightning_settings_stay_overridable(self):
        """A 4-step Lightning LoRA needs cfg 1.0; both must be drivable without
        editing the template."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "shot.png").write_bytes(b"source")
            with patch.object(server, "CDIR", root), \
                 assets(model("Qwen\\Qwen_Image_Edit-Q6_K.gguf", "qwen_edit", "edit")):
                graph, _caption, _info = server.build_qwen_edit(
                    "make it night", 3, image="shot.png", steps=4, cfg=1.0,
                    megapixels=2.0)
        self.assertEqual(graph["qe:sampler"]["inputs"]["steps"], 4)
        self.assertEqual(graph["qe:sampler"]["inputs"]["cfg"], 1.0)
        self.assertEqual(graph["qe:scale"]["inputs"]["megapixels"], 2.0)

    def test_identity_edit_default_stack_is_structural_only(self):
        """RawGirlV3 is taste, not structure: a plan-less build runs exactly the
        vector bypass and the identity LoRA, and the rawgirl slot stays authored
        for one-tap return without gating the recipe on the file existing."""
        entry = model("Krea 2\\krea2_turbo_mxfp8.safetensors", "krea2")
        with identity_anchor(), assets(entry):
            graph, _c, _i = server.build_zara_edit("restage", 7, character="hero")
        self.assertEqual(lora_chain(graph, "ed:patch"),
                         [(server.KREA_BYPASS_LORA, 1.0),
                          (server.IDENTITY_LORA, 1.0)])
        spec = server.RECIPE_SPECS["identity_edit"]
        self.assertNotIn(server.IDENTITY_STYLE_LORA, spec["required_loras"])
        rawgirl = next(s for s in spec["lora_stages"] if s["slot"] == "rawgirl")
        self.assertFalse(rawgirl["active_by_default"])
        self.assertTrue(rawgirl["removable"])

    def test_identity_edit_refuses_gguf_models(self):
        """A GGUF under the identity patch killed the ComfyUI process outright
        (no traceback, log just stops - gonzalomo, 2026-08-11). The recipe must
        refuse with a sentence at build time, and never offer GGUFs as
        candidates, until the native crash is understood."""
        entry = model("Krea 2\\gonzalomoKrea2_v20.gguf", "krea2")
        with identity_anchor(), assets(entry):
            with self.assertRaisesRegex(ValueError, "GGUF"):
                server.build_zara_edit("restage", 1, character="hero",
                                       model="Krea 2\\gonzalomoKrea2_v20.gguf")
        self.assertTrue(server.RECIPE_SPECS["identity_edit"].get("no_gguf"))

    def test_identity_pid_finish_swaps_only_the_decode_seat(self):
        """PiD replaces VAEDecode with the sampler's final latent at sigma 0;
        the canvas snaps to a 2kto4k preset on aspect, the caption is the live
        edit instruction, and the Wan VAE stays for the ENCODE side (identity
        ref + patch), because PiD has no encoder."""
        entry = model("Krea 2\\krea2_turbo_mxfp8.safetensors", "krea2")
        with identity_anchor(), assets(entry):
            graph, _c, info = server.build_zara_edit(
                "restage on a rooftop", 9, character="hero", pid=True)
        decode = graph["30:8"]
        self.assertEqual(decode["class_type"], "PiDDecode")
        self.assertEqual(decode["inputs"]["latent"], ["30:51", 0])
        self.assertEqual(decode["inputs"]["sigma"], 0.0)
        self.assertEqual(decode["inputs"]["caption"],
                         graph["30:19"]["inputs"]["value"])
        for key, value in server.PID_DECODE_SETTINGS.items():
            self.assertEqual(decode["inputs"][key], value)
        # default 9:16 canvas snapped to the 2kto4k preset list
        canvas = (graph["30:5"]["inputs"]["width"], graph["30:5"]["inputs"]["height"])
        self.assertIn(canvas, server.PID_BASE_CANVASES)
        self.assertEqual(canvas, (576, 1024))
        self.assertIn("(PiD 4×)", info["size"])
        # encode path untouched: ref and patch still run through the real VAE
        self.assertEqual(graph["ed:enc"]["inputs"]["vae"], ["30:12", 0])
        self.assertEqual(graph["ed:patch"]["inputs"]["vae"], ["30:12", 0])
        self.assertEqual(graph["30:12"]["class_type"], "VAELoader")
        self.assertEqual(graph["29"]["inputs"]["images"], ["30:8", 0])

    def test_identity_pid_finish_stays_off_without_the_toggle(self):
        entry = model("Krea 2\\krea2_turbo_mxfp8.safetensors", "krea2")
        with identity_anchor(), assets(entry):
            graph, _c, info = server.build_zara_edit("restage", 9, character="hero")
        self.assertEqual(graph["30:8"]["class_type"], "VAEDecode")
        self.assertNotIn("PiD", info["size"])
        self.assertEqual((graph["30:5"]["inputs"]["width"],
                          graph["30:5"]["inputs"]["height"]), (1152, 2048))

    def test_pid_base_canvas_snaps_by_aspect(self):
        self.assertEqual(server.pid_base_canvas(1152, 2048), (576, 1024))   # 9:16
        self.assertEqual(server.pid_base_canvas(832, 1248), (672, 1008))    # 2:3
        self.assertEqual(server.pid_base_canvas(1248, 832), (1008, 672))    # 3:2
        self.assertEqual(server.pid_base_canvas(1024, 1024), (1024, 1024))  # 1:1

    def test_pid_upscale_ports_the_pack_workflow_and_runs_int8(self):
        """The pid mode builds the ported ComfyUI-PiD graph - caption creator
        feeding the upscaler - at the v1.5 INT8 ConvRot settings, regardless of
        the template's example-workflow literals."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "still.png").write_bytes(b"frame")
            with patch.object(server, "CDIR", root):
                graph, _scene, info = server.build_upscale_image(
                    "golden hour", 1, image="still.png", mode="pid")
        self.assert_graph_links("pid_upscale", graph)
        self.assertEqual(graph["up:pid"]["class_type"], "PiDUpscale")
        self.assertEqual(graph["up:pid"]["inputs"]["caption"], ["up:cap", 1])
        for key, value in server.PID_UPSCALE_SETTINGS.items():
            self.assertEqual(graph["up:pid"]["inputs"][key], value)
        self.assertEqual(graph["up:img"]["inputs"]["image"], "still.png")
        self.assertIn("PiD", info["upscaler"])

    def test_pid_upscale_is_refused_when_the_pack_is_missing(self):
        """A probed ComfyUI without the PiD node hides the failure at build
        time with a plain sentence, not at queue time with a stack trace."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "still.png").write_bytes(b"frame")
            with patch.object(server, "CDIR", root), \
                 patch.dict(server._COMFY_NODES, {"names": frozenset({"KSampler"})}):
                with self.assertRaises(ValueError):
                    server.build_upscale_image("x", 1, image="still.png", mode="pid")

    def test_template_links_target_existing_nodes(self):
        for name in ("realism", "realism_ii", "zimage", "identity_edit", "ltx_i2v",
                     "ltx25_i2v", "qwen_edit", "pid_upscale"):
            graph = server.TEMPLATES[name]
            for node_id, node in graph.items():
                for value in node.get("inputs", {}).values():
                    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                        self.assertIn(value[0], graph, f"{name}:{node_id} has bad link {value}")

    def assert_graph_links(self, name, graph):
        for node_id, node in graph.items():
            for value in node.get("inputs", {}).values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], graph, f"{name}:{node_id} has bad link {value}")

    def test_built_recipe_links_target_existing_nodes(self):
        krea = model("Krea 2\\demo.safetensors", "krea2")
        zbase = model("ZiB\\demo.safetensors", "zimage", "base")
        zturbo = model("ZiT\\demo.safetensors", "zimage", "turbo")
        graphs = []
        with assets(krea):
            graphs.append(("realism", server.build_realism("portrait", 1)[0]))
            graphs.append(("realism_ii", server.build_realism_ii("portrait", 1)[0]))
        with assets(zbase):
            graphs.append(("fantasy", server.build_fantasy("castle", 1)[0]))
            graphs.append(("anime", server.build_anime("courier", 1)[0]))
        with assets(zturbo):
            graphs.append(("zimage", server.build_zimage("lantern", 1)[0]))
        with identity_anchor(), assets(krea):
            graphs.append(("identity_edit", server.build_zara_edit(
                "restage", 1, character="hero")[0]))
        for name, graph in graphs:
            with self.subTest(recipe=name):
                self.assert_graph_links(name, graph)

    def test_recipe_lora_stage_contract_has_literal_defaults(self):
        """recipe -> (lora_stack_revision, [(slot, name, strength, zone)]).

        The Krea 2 vector bypass is structural for the whole family rather than
        one recipe's taste, so every krea2 recipe that samples carries it as the
        first core stage. Realism gained it on 2026-08-13; its revision went to
        2 in the same move so plans saved against revision 1 are refused instead
        of replayed a stage short. Every revision is pinned per recipe here -
        a stage list may only change together with its revision.
        """
        expected = {
            "realism": (2, [
                ("vector_bypass", server.KREA_BYPASS_LORA, 1.0, "core"),
                ("realistic_snapshot", server.REALISM_LORA, 1.0, "editable"),
            ]),
            "realism_ii": (1, [
                ("vector_bypass", server.KREA_BYPASS_LORA, 1.0, "core"),
            ]),
            "fantasy": (1, [("painterly", server.FANTASY_LORA, 0.9, "editable")]),
            "anime": (1, []),
            "zimage": (1, []),
            "identity_edit": (1, [
                ("vector_bypass", server.KREA_BYPASS_LORA, 1.0, "core"),
                ("identity_edit", server.IDENTITY_LORA, 1.0, "core"),
                ("rawgirl", server.IDENTITY_STYLE_LORA, 1.0, "editable"),
            ]),
        }
        for recipe, (revision, wanted) in expected.items():
            spec = server.RECIPE_SPECS[recipe]
            got = [(s["slot"], s["name"], s["strength"], s["zone"])
                   for s in spec["lora_stages"]]
            self.assertEqual(got, wanted)
            self.assertEqual(spec["lora_stack_revision"], revision)
        self.assertNotIn(server.REALISM_LORA,
                         server.RECIPE_SPECS["identity_edit"]["required_loras"])

    def test_last_duplicate_controls_strength_and_literal_position(self):
        with patch.object(server, "resolve_lora", side_effect=lambda name: name), \
             patch.object(server, "lora_profile", return_value={
                 "family": "krea2", "variant": "any", "supported": True,
             }):
            keep, dropped = server.lora_stack(
                ["Krea 2\\a.safetensors:0.1", "Krea 2\\b.safetensors:0.2",
                 "Krea 2\\a.safetensors:0.9"], family="krea2")
        self.assertEqual(dropped, [])
        self.assertEqual(keep, [
            ("Krea 2\\b.safetensors", 0.2),
            ("Krea 2\\a.safetensors", 0.9),
        ])

    def test_zimage_turbo_uses_amazing_v4_two_stage_schedule(self):
        # Marketing filenames are not architecture metadata: this real-world
        # style of Z-Image name contains "Krea2" but remains Z-Image Turbo.
        entry = model("ZiT\\solordzZITZIBKrea2_zitV20.safetensors", "zimage", "turbo")
        with assets(entry):
            graph, _, info = server.build_zimage(
                "a lantern in fog", 42, width=512, height=512)
        self.assertNotIn("7", graph)
        self.assertNotIn("8", graph)
        self.assertEqual(graph["z:v4:sigmas"]["inputs"], {
            "steps": 8, "sigma_max": 0.99, "sigma_min": 0.08, "rho": 0.3})
        self.assertEqual(graph["z:v4:split"]["inputs"]["step"], 2)
        self.assertEqual(graph["z:v4:first"]["inputs"]["sigma"], 0.906)
        self.assertEqual(graph["z:v4:extend"]["inputs"], {
            "sigmas": ["z:v4:first", 0], "steps": 2, "start_at_sigma": 1.0,
            "end_at_sigma": 0.8, "spacing": "linear"})
        self.assertTrue(graph["z:v4:high"]["inputs"]["add_noise"])
        self.assertFalse(graph["z:v4:low"]["inputs"]["add_noise"])
        self.assertEqual(graph["z:v4:low"]["inputs"]["latent_image"], ["z:v4:high", 0])
        self.assertEqual(graph["9"]["inputs"]["samples"], ["z:v4:low", 0])
        self.assertEqual(graph["2"]["inputs"]["clip_name"], server.ZIMAGE_CLIP)
        self.assertNotIn("-vl-", graph["2"]["inputs"]["clip_name"].lower())
        self.assertEqual(info["execution_profile"], "zimage_turbo_v4")
        self.assertEqual(info["model_family"], "zimage")
        self.assertEqual(info["model_variant"], "turbo")
        self.assertEqual(info["model_path"], entry["rel"])
        self.assertEqual(info["model"], "solordzZITZIBKrea2_zitV20")
        self.assertEqual(graph["5"]["class_type"], "ConditioningZeroOut")

    def test_queue_boundary_rejects_contradictory_model_attestation(self):
        zentry = model("ZiT\\hybridKrea2Name.safetensors", "zimage", "turbo")
        zinfo = server.model_job_info(zentry, "zimage_turbo_v4")
        server.validate_job_model_info("zimage", zinfo)
        with self.assertRaisesRegex(RuntimeError, "zimage needs zimage, got krea2"):
            server.validate_job_model_info("zimage", {
                **zinfo, "model_family": "krea2",
            })
        with self.assertRaisesRegex(RuntimeError, "execution profile"):
            server.validate_job_model_info("zimage", {
                **zinfo, "execution_profile": None,
            })

        with assets(zentry):
            graph, _, built_info = server.build_zimage(
                "scene", 1, overrides=[{
                    "node": "1", "input": "unet_name",
                    "value": "Krea 2\\wrong-family.safetensors",
                }])
        with self.assertRaisesRegex(RuntimeError, "resolved model path mismatch"):
            server.validate_job_model_info("zimage", built_info, graph)

        # Old history entries still reroll through the pre-rename alias. They
        # must receive Identity Edit's Krea-family and graph-path checks too.
        legacy_entry = model("Krea 2\\legacy-edit.safetensors", "krea2")
        legacy_info = server.model_job_info(legacy_entry)
        legacy_graph = {"loader": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "ZiT\\wrong-family.safetensors",
        }}}
        with self.assertRaisesRegex(RuntimeError, "resolved model path mismatch"):
            server.validate_job_model_info("zara_edit", legacy_info, legacy_graph)

    def test_zimage_base_and_fantasy_profile(self):
        entry = model("ZiB\\z_image_bf16.safetensors", "zimage", "base")
        with assets(entry):
            graph, caption, info = server.build_fantasy("a knight at the gate", 7,
                                                         width=512, height=512)
        self.assertEqual(graph["8"]["inputs"]["steps"], 25)
        self.assertEqual(graph["8"]["inputs"]["cfg"], 4.0)
        self.assertEqual(graph["5"]["class_type"], "CLIPTextEncode")
        self.assertTrue(caption.startswith("D&D Painterly,"))
        self.assertEqual(graph["z:lora0"]["inputs"]["strength_model"], 0.9)
        self.assertIn("DnDPainterlyCleanZBase@0.9", info["loras"])

    def test_clear_anime_model_applies_measured_override(self):
        entry = model(
            "ZiB\\Z-Image_clear_anime_BF16.safetensors",
            "zimage",
            "base",
            profile_id="clear_anime",
            steps=12,
            cfg=1.0,
            sampler="euler",
            scheduler="beta",
            shift=6.0,
            zero_negative=True,
            vae=server.ZIMAGE_ANIME_VAE,
        )
        with assets(entry):
            graph, caption, _ = server.build_anime("a courier on a rooftop", 11,
                                                    width=512, height=512)
        sampler = graph["8"]["inputs"]
        self.assertEqual(
            (sampler["steps"], sampler["cfg"], sampler["sampler_name"], sampler["scheduler"]),
            (12, 1.0, "euler", "beta"),
        )
        self.assertEqual(graph["7"]["inputs"]["shift"], 6.0)
        self.assertEqual(graph["3"]["inputs"]["vae_name"], server.ZIMAGE_ANIME_VAE)
        self.assertTrue(caption.startswith("anime, Japanese anime,"))

    def test_realism_ii_keeps_only_the_finished_output(self):
        entry = model("Krea 2\\selforaV2Krea2Realistic_fp8Scaled.safetensors", "krea2")
        with assets(entry):
            graph, _, info = server.build_realism_ii("a portrait", 99,
                                                      width=512, height=768)
        saves = [node for node in graph.values() if node["class_type"] == "SaveImage"]
        self.assertEqual(len(saves), 1)
        self.assertEqual(graph["265"]["inputs"]["options"], ["328", 0])
        self.assertEqual(graph["265"]["inputs"]["seed"], 99)
        self.assertEqual(graph["274"]["inputs"]["seed"], 99)
        self.assertEqual(graph["333"]["inputs"]["seed"], 99)
        self.assertEqual(graph["333"]["inputs"]["upscale_by"], 2.0)
        self.assertEqual(info["size"], "1024x1536 (2× finish)")

    def test_identity_plan_keeps_locked_order_before_patch(self):
        entry = model("Krea 2\\krea2_turbo_mxfp8.safetensors", "krea2")
        requested = plan("identity_edit", [
            {"name": "Krea 2\\cinematic.safetensors", "strength": 0.4},
            {"slot": "rawgirl", "strength": 0.75},
            {"name": "Krea 2\\detail.safetensors", "strength": 0.6},
        ])
        with identity_anchor(), assets(entry):
            graph, _, info = server.build_zara_edit(
                "restage", 5, character="hero", lora_plan=requested)
        expected = [
            (server.KREA_BYPASS_LORA, 1.0),
            (server.IDENTITY_LORA, 1.0),
            ("Krea 2\\cinematic.safetensors", 0.4),
            (server.IDENTITY_STYLE_LORA, 0.75),
            ("Krea 2\\detail.safetensors", 0.6),
        ]
        self.assertEqual(lora_chain(graph, "ed:patch"), expected)
        self.assertEqual(info["loras"], [
            f"{server.base(name)}@{strength:g}" for name, strength in expected])
        self.assertEqual([(e["name"], e["strength"]) for e in info["lora_stack"]],
                         expected)
        self.assertNotIn(server.REALISM_LORA, [name for name, _ in expected])

    def test_core_strength_override_reaches_the_identity_lora(self):
        """The composer's core strength input writes core.<slot>.strength: the
        identity LoRA runs at the user's 0.6 instead of the authored 1.0, and
        the bypass ahead of it keeps its own authored strength. The plan must
        validate first - this is the same core override map the bypass toggle
        already writes, so no revision bump came with the unlock."""
        entry = model("Krea 2\\krea2_turbo_mxfp8.safetensors", "krea2")
        requested = plan("identity_edit", [])
        requested["core"] = {"identity_edit": {"strength": 0.6}}
        server.validate_lora_plan("identity_edit", requested)
        with identity_anchor(), assets(entry):
            graph, _, _info = server.build_zara_edit(
                "restage", 5, character="hero", lora_plan=requested)
        self.assertEqual(lora_chain(graph, "ed:patch"),
                         [(server.KREA_BYPASS_LORA, 1.0),
                          (server.IDENTITY_LORA, 0.6)])

    def test_replace_editable_plan_drives_all_non_identity_builders(self):
        cases = [
            ("realism", model("Krea 2\\real.safetensors", "krea2"),
             server.build_realism, "30:51",
             [{"name": "Krea 2\\custom.safetensors", "strength": 0.25},
              {"slot": "realistic_snapshot", "strength": 0.65}],
             [(server.KREA_BYPASS_LORA, 1.0),
              ("Krea 2\\custom.safetensors", 0.25), (server.REALISM_LORA, 0.65)]),
            ("realism_ii", model("Krea 2\\r2.safetensors", "krea2"),
             server.build_realism_ii, "265",
             [{"name": "Krea 2\\custom.safetensors", "strength": 0.3}],
             [(server.KREA_BYPASS_LORA, 1.0), ("Krea 2\\custom.safetensors", 0.3)]),
            ("fantasy", model("ZiB\\fantasy.safetensors", "zimage", "base"),
             server.build_fantasy, "7",
             [{"name": "ZImage\\Base\\custom.safetensors", "strength": 0.35},
              {"slot": "painterly", "strength": 0.7}],
             [("ZImage\\Base\\custom.safetensors", 0.35), (server.FANTASY_LORA, 0.7)]),
            ("anime", model("ZiB\\anime.safetensors", "zimage", "base"),
             server.build_anime, "7",
             [{"name": "ZImage\\Base\\custom.safetensors", "strength": 0.45}],
             [("ZImage\\Base\\custom.safetensors", 0.45)]),
            ("zimage", model("ZiT\\turbo.safetensors", "zimage", "turbo"),
             server.build_zimage, "z:v4:high",
             [{"name": "ZImage\\Turbo\\custom.safetensors", "strength": 0.55}],
             [("ZImage\\Turbo\\custom.safetensors", 0.55)]),
        ]
        for recipe, entry, builder, sink, rows, expected in cases:
            with self.subTest(recipe=recipe), assets(entry):
                graph, _, info = builder("scene", 3, lora_plan=plan(recipe, rows))
            self.assertEqual(lora_chain(graph, sink), expected)
            self.assertEqual([(e["name"], e["strength"]) for e in info["lora_stack"]],
                             expected)
            self.assertEqual(info["loras"], [
                f"{server.base(name)}@{strength:g}" for name, strength in expected])

    def test_replace_editable_can_remove_a_primed_default(self):
        entry = model("ZiB\\fantasy.safetensors", "zimage", "base")
        with assets(entry):
            graph, _, info = server.build_fantasy(
                "scene", 3, lora_plan=plan("fantasy", []))
        self.assertEqual(lora_chain(graph, "7"), [])
        self.assertEqual(info["loras"], [])
        self.assertEqual(info["lora_stack"], [])

    def test_disabled_plan_entries_never_reach_graph_or_applied_info(self):
        entry = model("ZiB\\fantasy.safetensors", "zimage", "base")
        rows = [
            {"slot": "painterly", "strength": 0.63, "enabled": False},
            {"name": "ZImage\\Base\\off.safetensors", "strength": 0.35,
             "enabled": False},
            {"name": "ZImage\\Base\\on.safetensors", "strength": 0.45,
             "enabled": True},
        ]
        with assets(entry):
            graph, _, info = server.build_fantasy(
                "scene", 3, lora_plan=plan("fantasy", rows))
        expected = [("ZImage\\Base\\on.safetensors", 0.45)]
        self.assertEqual(lora_chain(graph, "7"), expected)
        self.assertEqual([(e["name"], e["strength"]) for e in info["lora_stack"]],
                         expected)
        self.assertEqual(info["loras"], ["on@0.45"])
        self.assertEqual(info["lora_warnings"], [])

        rows[1]["enabled"] = True
        with assets(entry):
            graph, _, info = server.build_fantasy(
                "scene", 3, lora_plan=plan("fantasy", rows))
        expected = [("ZImage\\Base\\off.safetensors", 0.35),
                    ("ZImage\\Base\\on.safetensors", 0.45)]
        self.assertEqual(lora_chain(graph, "7"), expected)
        self.assertEqual([(e["name"], e["strength"]) for e in info["lora_stack"]],
                         expected)

    def test_plan_enabled_flag_must_be_boolean(self):
        with self.assertRaisesRegex(ValueError, "enabled must be boolean"):
            server.validate_lora_plan("realism", plan("realism", [{
                "slot": "realistic_snapshot", "strength": 1.0, "enabled": "false",
            }]))

    def test_legacy_extras_still_append_and_recipe_default_wins_duplicates(self):
        """The locked vector bypass leads, the authored default keeps its
        authored strength against a user row that names the same file, and the
        surviving extra appends after both."""
        entry = model("Krea 2\\real.safetensors", "krea2")
        with assets(entry):
            graph, _, info = server.build_realism(
                "scene", 3, loras=["Krea 2\\custom.safetensors:0.4",
                                   f"{server.REALISM_LORA}:0.2"])
        expected = [(server.KREA_BYPASS_LORA, 1.0),
                    (server.REALISM_LORA, 1.0),
                    ("Krea 2\\custom.safetensors", 0.4)]
        self.assertEqual(lora_chain(graph, "30:51"), expected)
        self.assertEqual([(e["name"], e["strength"]) for e in info["lora_stack"]],
                         expected)

    def test_plan_cannot_override_locked_stage(self):
        entry = model("Krea 2\\r2.safetensors", "krea2")
        with assets(entry):
            with self.assertRaisesRegex(ValueError, "not editable"):
                server.build_realism_ii(
                    "scene", 1, lora_plan=plan("realism_ii", [
                        {"slot": "vector_bypass", "strength": 0.0},
                    ]))
            with self.assertRaisesRegex(ValueError, "locked Realism II stage"):
                server.build_realism_ii(
                    "scene", 1, lora_plan=plan("realism_ii", [
                        {"name": server.KREA_BYPASS_LORA, "strength": 0.0},
                    ]))

    def test_plan_dedupe_uses_last_canonical_position(self):
        entry = model("ZiT\\turbo.safetensors", "zimage", "turbo")
        rows = [
            {"name": "ZImage\\Turbo\\a.safetensors", "strength": 0.1},
            {"name": "ZImage\\Turbo\\b.safetensors", "strength": 0.2},
            {"name": "ZImage\\Turbo\\a.safetensors", "strength": 0.9},
        ]
        with assets(entry):
            graph, _, _ = server.build_zimage("scene", 1, lora_plan=plan("zimage", rows))
        self.assertEqual(lora_chain(graph, "z:v4:high"), [
            ("ZImage\\Turbo\\b.safetensors", 0.2),
            ("ZImage\\Turbo\\a.safetensors", 0.9),
        ])

    def test_incompatible_plan_entry_is_not_in_graph_or_applied_info(self):
        entry = model("ZiT\\turbo.safetensors", "zimage", "turbo")
        rows = [{"name": "ZImage\\Base\\wrong.safetensors", "strength": 0.4}]
        with assets(entry):
            graph, _, info = server.build_zimage(
                "scene", 1, lora_plan=plan("zimage", rows))
        self.assertEqual(lora_chain(graph, "z:v4:high"), [])
        self.assertEqual(info["loras"], [])
        self.assertEqual(info["lora_stack"], [])
        self.assertEqual(info["lora_warnings"], ["incompatible wrong"])

    def test_gguf_models_switch_loader_class(self):
        graph = {"1": {}}
        server.set_unet_loader(graph, "1", model("Krea 2\\demo.Q8_0.gguf", "krea2"))
        self.assertEqual(graph["1"]["class_type"], "UnetLoaderGGUF")

    def test_cross_family_model_is_rejected(self):
        entry = model("Krea 2\\demo.safetensors", "krea2")
        with assets(entry):
            with self.assertRaisesRegex(ValueError, "needs zimage"):
                server.build_zimage("a scene", 1, width=512, height=512)

    def test_missing_authored_default_falls_back_to_compatible_installed_model(self):
        fallback = model("ZiT\\another_turbo.safetensors", "zimage", "turbo")
        with patch.object(server, "resolve_model_entry", return_value=None), \
             patch.object(server, "recipe_model_candidates", return_value=[fallback]):
            picked = server.pick_recipe_model(None, "zimage")
        self.assertEqual(picked, fallback)

    def test_unknown_lora_is_not_treated_as_architecture_neutral(self):
        with patch.object(server, "resolve_lora", return_value="misc\\mystery.safetensors"), \
             patch.object(server, "lora_profile", return_value={
                 "family": "unknown", "variant": "any", "supported": False,
             }):
            keep, dropped = server.lora_stack(["mystery:0.8"], family="krea2")
        self.assertEqual(keep, [])
        self.assertEqual(dropped, ["incompatible mystery"])

    def test_lora_sidecar_and_folder_infer_zimage_variant(self):
        with patch.object(server, "adjacent_metadata",
                          return_value={"base_model": "ZImageTurbo"}):
            self.assertEqual(server.lora_profile("misc\\speed.safetensors")["variant"], "turbo")
        with patch.object(server, "adjacent_metadata", return_value={}):
            profile = server.lora_profile("ZImage\\Base\\painter.safetensors")
        self.assertEqual((profile["family"], profile["variant"]), ("zimage", "base"))

    def test_auto_model_routes_to_its_graph_family(self):
        with patch.object(
            server,
            "resolve_model_entry",
            return_value=model("ZiT\\z_image_turbo_bf16.safetensors", "zimage", "turbo"),
        ):
            args = {}
            recipe = server._apply_opts(args, {"engine": "auto", "model": "selected"})
        self.assertEqual(recipe, "zimage")
        self.assertEqual(args["model"], "selected")

    def test_model_first_style_contract_routes_only_safe_recipes(self):
        cases = (
            (model("ZiB\\base.safetensors", "zimage", "base"), "anime", "standard", "anime"),
            (model("ZiB\\base.safetensors", "zimage", "base"), "fantasy", "standard", "fantasy"),
            (model("ZiT\\turbo.safetensors", "zimage", "turbo"), "anime", "standard", "zimage"),
            (model("Krea 2\\photo.safetensors", "krea2"), "fantasy", "standard", "realism"),
            (model("Krea 2\\photo.safetensors", "krea2"), "realism", "refined", "realism_ii"),
        )
        for entry, style, quality, expected in cases:
            with self.subTest(entry=entry["rel"], style=style, quality=quality), \
                 patch.object(server, "resolve_model_entry", return_value=entry):
                self.assertEqual(server.effective_recipe({
                    "model": "selected", "style": style, "quality": quality,
                }), expected)

    def test_identity_still_overrides_model_style_contract(self):
        self.assertEqual(server.effective_recipe({
            "character": "hero", "model": "selected-z", "style": "fantasy",
            "quality": "standard",
        }), "identity_edit")

    def test_qwen_image_never_falls_through_to_a_krea_recipe(self):
        """Qwen-Image has no style or quality variants, so every creative intent
        has to land on its own recipe.

        Without a branch of its own it fell through to the Realism/Realism II
        tail and pick_recipe_model rejected the pairing at the graph layer:
        "... is qwen_image, but Realism needs krea2". The picker offers the
        model, so routing has to have somewhere to put it.
        """
        entry = model("Qwen\\qwen-image-2512-Q6_K.gguf", "qwen_image")
        for style in ("realism", "anime", "fantasy"):
            for quality in ("standard", "refined"):
                with self.subTest(style=style, quality=quality), \
                     patch.object(server, "resolve_model_entry", return_value=entry):
                    self.assertEqual(server.effective_recipe({
                        "model": "selected", "style": style, "quality": quality,
                    }), "qwen_image")

        # The same model with no style keys at all takes the engine/model tail.
        with patch.object(server, "resolve_model_entry", return_value=entry):
            self.assertEqual(server.effective_recipe({"model": "selected"}),
                             "qwen_image")

    def test_anima_never_falls_through_to_the_zimage_anime_recipe(self):
        """The same trap as Qwen-Image, one step worse.

        The composer PINS an Anima model's style to "anime" (withExecutionRecipe
        in store.js), so the fallthrough did not merely mislabel it - it handed
        the checkpoint to the Z-Image clear-anime recipe and pick_recipe_model
        raised "anima-base-v1.0 is anima, but Anime needs zimage" on the first
        render anyone tried. Shipped that way for two commits: build_anima was
        tested directly and the smoke renders went straight to ComfyUI, so
        nothing exercised composer -> effective_recipe -> pick_recipe_model.
        """
        entry = model("Anima\\anima-base-v1.0.safetensors", "anima", "base")
        for style in ("realism", "anime", "fantasy"):
            for quality in ("standard", "refined"):
                with self.subTest(style=style, quality=quality), \
                     patch.object(server, "resolve_model_entry", return_value=entry):
                    self.assertEqual(server.effective_recipe({
                        "model": "selected", "style": style, "quality": quality,
                    }), "anima")

        with patch.object(server, "resolve_model_entry", return_value=entry):
            self.assertEqual(server.effective_recipe({"model": "selected"}),
                             "anima")

        # The half that actually failed: routing has to survive the graph layer.
        with assets(entry):
            recipe = server.effective_recipe(
                {"model": "selected", "style": "anime", "quality": "standard"})
            self.assertEqual(
                server.pick_recipe_model("selected", recipe)["rel"], entry["rel"])

    def test_plan_overlay_requires_a_known_matching_recipe(self):
        realism_plan = plan("realism", [])
        args = {"loras": ["brain:1"]}
        recipe = server._apply_opts(args, {
            "engine": "realism", "lora_plan": realism_plan,
            "loras": [{"name": "legacy", "strength": 0.2}],
        })
        self.assertEqual(recipe, "realism")
        self.assertEqual(args["lora_plan"], realism_plan)
        self.assertNotIn("loras", args)

        with self.assertRaisesRegex(ValueError, "for realism, not fantasy"):
            server._apply_opts({}, {
                "engine": "fantasy", "lora_plan": realism_plan,
            })

        stale = {**realism_plan, "recipe_revision": 0}
        with self.assertRaisesRegex(ValueError, "refresh recipe options"):
            server._apply_opts({}, {"engine": "realism", "lora_plan": stale})

        undecided = {"loras": ["brain:1"]}
        self.assertIsNone(server._apply_opts(undecided, {
            "engine": "auto", "lora_plan": realism_plan,
        }))
        self.assertNotIn("lora_plan", undecided)
        self.assertEqual(undecided["loras"], ["brain:1"])

    def test_options_exposes_installed_lora_stages_and_boundary(self):
        stage_names = {stage["name"] for spec in server.RECIPE_SPECS.values()
                       for stage in spec["lora_stages"]}

        def catalog(kind):
            return ([{"rel": name} for name in stage_names] if kind == "loras" else [])

        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "model_catalog", side_effect=catalog), \
                 patch.object(server, "model_roots", return_value=[]), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "lm_enrich"), \
                 patch.object(server, "_LORA_TITLE_CACHE", root / "titles.json"):
                options = server.Hub().options()
        identity = next(r for r in options["recipes"] if r["id"] == "identity_edit")
        self.assertEqual(identity["lora_stack_revision"], 1)
        self.assertEqual(identity["lora_boundary"], "identity patch")
        self.assertTrue(all(stage["installed"] for stage in identity["lora_stages"]))
        self.assertEqual([stage["slot"] for stage in identity["lora_stages"]],
                         ["vector_bypass", "identity_edit", "rawgirl"])

    def test_selected_character_forces_identity_edit_and_drops_z_model(self):
        zmodel = model("ZiT\\z_image_turbo_bf16.safetensors", "zimage", "turbo")
        with identity_anchor(), patch.object(server, "resolve_model_entry", return_value=zmodel):
            for engine in ("auto", "realism", "realism_ii", "fantasy", "anime", "zimage"):
                with self.subTest(engine=engine):
                    args = {"model": "brain-choice", "ref": "wrong-face.png"}
                    recipe = server._apply_opts(args, {
                        "engine": engine,
                        "character": "hero",
                        "model": "selected-z-model",
                        "refs": [{"kind": "identity", "file": "wrong-face.png"}],
                    })
                    self.assertEqual(recipe, "identity_edit")
                    self.assertEqual(args["character"], "hero")
                    self.assertNotIn("model", args)
                    self.assertNotIn("ref", args)

    def test_selected_character_keeps_compatible_krea_model(self):
        krea = model("Krea 2\\compatible.safetensors", "krea2")
        with identity_anchor(), patch.object(server, "resolve_model_entry", return_value=krea):
            args = {}
            recipe = server._apply_opts(args, {
                "engine": "fantasy", "character": "hero", "model": "chosen-krea",
            })
        self.assertEqual(recipe, "identity_edit")
        self.assertEqual(args["model"], "chosen-krea")

    def test_character_directives_use_identity_prompt_register(self):
        opts = {"engine": "fantasy", "character": "hero", "model": "selected-z"}
        zmodel = model("ZiB\\z_image_bf16.safetensors", "zimage", "base")
        with identity_anchor(), patch.object(server, "resolve_model_entry", return_value=zmodel):
            local, _ = server.build_directive(opts, local=True)
            cloud, _ = server.build_directive(opts, local=False)
        self.assertIn("template=identity_edit", local)
        self.assertIn("template=identity_edit", cloud)
        self.assertNotIn("template=fantasy", local + cloud)
        self.assertNotIn("selected-z", cloud)

    def test_person_reference_rides_first_as_appearance_ground_truth(self):
        # The person photo used to be the one attachment the vision brain
        # never saw - scenes could describe a different person than the
        # reference. It now leads the vision list with a ground-truth block.
        opts = {"engine": "fantasy",
                "refs": [{"kind": "identity", "file": "face.png"},
                         {"kind": "style", "file": "look.png"}]}
        d, vision = server.build_directive(opts, local=False)
        self.assertEqual([v["file"] for v in vision], ["face.png", "look.png"])
        self.assertIn("PERSON REFERENCE", d)
        self.assertIn("APPEARANCE GROUND TRUTH", d)
        # style refs number AFTER the person photo
        self.assertIn("#2 = style reference (look.png)", d)

    def test_character_reference_photo_reaches_the_vision_brain(self):
        opts = {"engine": "fantasy", "character": "hero"}
        with identity_anchor():
            d, vision = server.build_directive(opts, local=False)
        self.assertEqual([v["file"] for v in vision], ["hero.png"])
        self.assertIn("PERSON REFERENCE", d)
        # the private filename stays out of the directive text
        self.assertNotIn("hero.png", d)

    def test_local_writer_ban_covers_skin_and_ethnicity(self):
        opts = {"engine": "fantasy", "character": "hero"}
        # pin the brain blind: with no mmproj the local writer gets no images
        # (on the real box an mmproj may exist and vision attaches - covered
        # by test_local_llm's test_local_directive_attaches_refs_only_with_mmproj)
        with identity_anchor(), patch.object(server, "_local_llm_mmproj",
                                             return_value=None):
            d, vision = server.build_directive(opts, local=True)
        self.assertIn("skin, ethnicity", d)
        self.assertEqual(vision, [])

    def test_server_briefs_never_survive_into_a_scene(self):
        """A local brain that echoes its own [COMPOSER: ...] brief back inside the
        scene would ship that text to the sampler and record it in the ledger as
        if the user had asked for it. Seen live as a rendered prompt beginning
        "[COMPOSER: writing for template=realism]"."""
        leaked = ("[COMPOSER: writing for template=realism. Model, loras, size and "
                  "reference are applied server-side - never mention file names.]\n\n"
                  "A 20-year-old woman standing in a park.")
        self.assertEqual(server._strip_history_directives(leaked),
                         "A 20-year-old woman standing in a park.")
        clean = "A woman standing in a park."
        self.assertEqual(server._strip_history_directives(clean), clean)

    def test_a_bracket_in_a_characters_look_does_not_strand_the_block(self):
        """CHARACTER is the one block that genuinely spans lines, so it keeps
        .*? - and .*? stops at the FIRST ]. A look like "wet-street neon [teal
        and magenta]" left the server's own closing sentence sitting in
        history, where the brain reads it as the user's words and it flatly
        contradicts them: "Never describe her face..." attributed to Jesse.

        The look field is his to write, so a bracket in it is ordinary."""
        user = "she waits at the curb"
        tail = ("\nNever describe her face, age, skin, ethnicity or build - the "
                "reference photo carries them. Place her EXACTLY where the user "
                "asked - no other locations, nothing the user didn't say.]")
        block = "\n[CHARACTER: Mia. Look: wet-street neon [teal and magenta]" + tail
        anchor = ("\n[CHARACTER ANCHOR: Mia. She keeps a [chipped] mug.\nHonor "
                  "this canon in the scene; do not restate their face.]")
        after = "\n[ATTACHED IMAGES: the FIRST is the person to depict.]"
        for label, d in (("look", block), ("anchor", anchor),
                         ("followed by another block", block + after),
                         ("both", anchor + block + after)):
            with self.subTest(shape=label):
                self.assertEqual(server._strip_history_directives(user + d), user)
        # Echoed mid-sentence with no boundary after it, there is no way to
        # know where the block ends. The fallback branch does what it always
        # did - strips to the first ] and leaves the tail - and this change
        # does not make that shape worse. Pinned so a future edit to the
        # fallback is visible rather than silent.
        residue = server._strip_history_directives(user + block + " and then")
        self.assertNotIn("[CHARACTER", residue)
        self.assertIn("Never describe her face", residue)   # still unsolved

    def test_no_server_block_survives_the_scrubber_or_the_render_gate(self):
        """Two hand-kept lists guard this and BOTH were a step behind
        build_directive on 2026-08-23: _HISTORY_DIRECTIVE_RE (history hygiene)
        and _MACHINERY_RE (the render chokepoint, which exists to catch
        exactly this). A leaked brief went through both and rendered as a
        whole prompt - ledger 079b9083.

        Built from the real emitters, both arms, so adding a block without
        teaching the scrubbers fails here rather than in a render."""
        user = "she is sitting in the dark"
        opts = {"refs": [{"kind": "identity", "file": "her.png"},
                         {"kind": "clothing", "file": "jacket.png"}],
                "style": "anime", "cinematic": True, "aspect": "9:16", "mp": 2}
        with patch.object(server, "load_config",
                          return_value={"llm": {"local_model": "g.gguf"}}), \
                patch.object(server, "_local_llm_mmproj",
                             return_value="mmproj.gguf"):
            local, _ = server.build_directive(dict(opts), local=True)
        api, _ = server.build_directive(dict(opts))
        # the two arms really do carry the blocks this is about
        self.assertIn("[ATTACHED IMAGES:", local)
        self.assertIn("[PERSON REFERENCE -", api)
        for arm, d in (("local", local), ("api", api)):
            with self.subTest(arm=arm):
                self.assertEqual(server._strip_history_directives(user + d), user)
                # verbatim=True skips every scrubber, so _MACHINERY_RE alone
                # has to refuse it - that is the backstop being pinned
                _scene, err = server.scene_gate("realism", d.strip(), verbatim=True)
                self.assertIsNotNone(err, f"{arm} directive reached the encoder")

    def test_every_block_name_trips_the_render_gate(self):
        """The blocks whose emitters need a character on disk, pinned by name
        so the gate's list cannot quietly lose one."""
        for block in ("[COMPOSER: writing for template=realism.]",
                      "[COMPOSER HARD CONSTRAINTS - pass these EXACTLY]",
                      "[CHARACTER: Mia. Look: nothing]",
                      "[CHARACTER ANCHOR: Mia. Canon.]",
                      "[PERSON REFERENCE - the FIRST attached image]",
                      "[ATTACHED IMAGES: the FIRST is the person]",
                      "[PRIOR RENDER #079b9083 - its scene was]",
                      "[STYLE: anime.]", "[CINEMATIC: ON.]",
                      "[NOTE - THIS TURN ONLY: generate is not offered]",
                      "[SYSTEM: the server queued that scene]"):
            with self.subTest(block=block):
                _scene, err = server.scene_gate("realism", block, verbatim=True)
                self.assertIsNotNone(err, f"{block} would reach the encoder")

    def test_attached_images_brief_never_survives_into_a_scene(self):
        """The local writer's vision brief was the one bracket the scrubber never
        learned. Every other block came off, so "[ATTACHED IMAGES: the FIRST is
        the person this render must depict..." was what reached the lane as prose
        AND the sampler as the prompt - seen live on a Mia identity_edit shot
        (Jesse, 2026-08-23). Built from build_directive so this cannot drift from
        the template it is meant to catch."""
        opts = {"refs": [{"kind": "identity", "file": "her.png"},
                         {"kind": "clothing", "file": "jacket.png"}]}
        with patch.object(server, "load_config",
                          return_value={"llm": {"local_model": "g.gguf"}}), \
                patch.object(server, "_local_llm_mmproj",
                             return_value="mmproj.gguf"):
            d, _ = server.build_directive(opts, local=True)
        self.assertIn("[ATTACHED IMAGES:", d)
        scene = "A woman sitting in the dark, one lamp burning behind her."
        self.assertEqual(server._strip_history_directives(d + "\n\n" + scene), scene)
        self.assertEqual(server._strip_history_directives(scene + d), scene)
        # the render chokepoint is the one that actually shipped it
        self.assertEqual(server.scene_gate("realism", d + "\n\n" + scene),
                         (scene, None))

    def test_job_reference_carries_the_prior_scene_into_the_turn(self):
        """"iterate on #abc: apply the review fix - relax the hands" must reach the
        brain with the scene that job rendered attached. Without it the only
        concrete words in the turn are the fix, and it writes a new shot."""
        entry = {"id": "9a189484", "template": "realism",
                 "scene": "Rain-soaked street at night, golden streetlights on wet asphalt.",
                 "info": {"model_path": "Krea 2\\fine.safetensors", "size": "1152x1728"}}
        with patch.object(server.HUB, "ledger_read", return_value=[entry]):
            d = server.prior_render_directive(
                "iterate on #9a189484: apply the review fix - relax the hands")
            none = server.prior_render_directive("make me a picture of a dog")
        self.assertIn("Rain-soaked street at night", d)
        self.assertIn("template='realism'", d)
        self.assertIn("fine.safetensors", d)   # repr'd, so the separator is escaped
        self.assertEqual(none, "")
        # and it must not survive into the replayed history the local brain sees
        self.assertEqual(server._strip_history_directives("do the thing" + d),
                         "do the thing")

    def test_a_bracket_in_a_stored_scene_does_not_strand_the_block(self):
        """PRIOR RENDER embeds a verbatim scene, and .*? stopped at the FIRST
        ']'. A scene containing a bracket therefore cut the strip short and
        left the whole tail of the server's own block sitting in history,
        reading to the brain as if the user had typed it. Not hypothetical:
        ledger entry 079b9083's entire scene was a bracketed directive
        (2026-08-23). Both emitters are covered because the fix rests on both
        collapsing the scene to a single line."""
        scene = "A woman in a doorway [the light behind her] holding a cup."
        entry = {"id": "079b9083", "template": "identity_edit",
                 "seed": 8800912903777915, "scene": scene, "info": {}}
        with patch.object(server.HUB, "ledger_read", return_value=[entry]):
            by_id = server.prior_render_directive("iterate on #079b9083: colder")
            with patch.object(server, "last_chat_render_id",
                              return_value="079b9083"):
                by_ref = server.last_render_directive([], "make the last one colder")
        for d in (by_id, by_ref):
            self.assertIn("[the light behind her]", d)   # the block really nests
            self.assertEqual(d.strip().count("\n"), 0)   # single line - the premise
            self.assertEqual(
                server._strip_history_directives("make it colder" + d),
                "make it colder")

    def test_character_reference_wins_over_manual_identity_ref(self):
        entry = model("Krea 2\\krea2_turbo_mxfp8.safetensors", "krea2")
        with identity_anchor() as (root, _), assets(entry):
            (root / "input" / "wrong-face.png").write_bytes(b"wrong")
            graph, _, _ = server.build_zara_edit(
                "restage the portrait", 12, ref="wrong-face.png", character="hero")
        self.assertEqual(graph["ed:img"]["inputs"]["image"], "hero.png")

    def test_unknown_or_refless_character_fails_before_queue(self):
        with identity_anchor(with_ref=False):
            with self.assertRaisesRegex(ValueError, "needs a reference image"):
                server._apply_opts({}, {"engine": "auto", "character": "hero"})
            with self.assertRaisesRegex(ValueError, "character anchor not found"):
                server._apply_opts({}, {"engine": "auto", "character": "missing"})

    def test_invalid_character_opts_fail_before_brain_and_surface_lane_error(self):
        with identity_anchor(with_ref=False), \
             patch.object(server, "llm_call", AsyncMock()) as llm, \
             patch.object(server.HUB, "broadcast") as broadcast, \
             patch.object(server, "_turn_start"), patch.object(server, "_turn_end"):
            asyncio.run(server.kimi_reply(
                "cid", {"role": "user", "content": "render a portrait"}, [],
                {"engine": "auto", "character": "hero"}))
        llm.assert_not_awaited()
        errors = [c.kwargs.get("message") for c in broadcast.call_args_list
                  if c.kwargs.get("type") == "error"]
        self.assertEqual(errors, ["Hero needs a reference image before identity editing"])

    def test_manual_identity_reference_also_selects_identity_edit(self):
        zmodel = model("ZiB\\z_image_bf16.safetensors", "zimage", "base")
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "face.png").write_bytes(b"reference")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "resolve_model_entry", return_value=zmodel):
                args = {"model": "brain-choice", "character": "brain-invented-anchor"}
                recipe = server._apply_opts(args, {
                    "engine": "fantasy",
                    "model": "selected-z-model",
                    "refs": [{"kind": "identity", "file": "face.png"}],
                })
        self.assertEqual(recipe, "identity_edit")
        self.assertEqual(args["ref"], "face.png")
        self.assertNotIn("character", args)
        self.assertNotIn("model", args)


class VramButlerMath(unittest.TestCase):
    def test_weight_bill_prices_each_file_once(self):
        g = {
            "u": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": "Krea 2\\m.safetensors"}},
            "c1": {"class_type": "CLIPLoader",
                   "inputs": {"clip_name": "Qwen\\c.safetensors"}},
            "c2": {"class_type": "TextGenerate",
                   "inputs": {"clip_name": "Qwen\\c.safetensors"}},
            "l": {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"lora_name": "Krea 2\\l.safetensors"}},
            "s": {"class_type": "KSampler", "inputs": {"model": ["u", 0], "seed": 1}},
        }
        sizes = {"Krea 2\\m.safetensors": 10 * 2**30, "Qwen\\c.safetensors": 5 * 2**30,
                 "Krea 2\\l.safetensors": 1 * 2**30}
        with patch.object(server, "_weight_file_bytes",
                          side_effect=lambda kinds, rel: sizes[rel]):
            heavy, peak = server.graph_weight_bill(g)
        # The shared encoder is charged once, and the bill is the PEAK rather
        # than the sum: the biggest heavyweight (10) plus the lora that sits
        # beside it (1). The 5GB encoder is finished before the unet samples.
        self.assertEqual(peak, 11 * 2**30)
        self.assertEqual(heavy, {"Krea 2\\m.safetensors": 10 * 2**30,
                                 "Qwen\\c.safetensors": 5 * 2**30})

    def test_weight_bill_is_the_peak_not_the_sum(self):
        """LTX 2.5 names 45.6GB of files and renders fine on a 31.8GB card,
        because its Gemma text encoders are done before its DiT loads. Summing
        them priced every LTX render as impossible - the butler flushed and
        evicted the chat brain before all of them, and they OOM'd anyway."""
        g = {
            "dit": {"class_type": "UNETLoader",
                    "inputs": {"unet_name": "LTX2\\dit.safetensors"}},
            "te1": {"class_type": "CLIPLoader",
                    "inputs": {"clip_name": "LTX2\\gemma12b.safetensors"}},
            "te2": {"class_type": "CLIPLoader",
                    "inputs": {"clip_name": "LTX2\\gemma_e2b.safetensors"}},
            "vae": {"class_type": "VAELoader",
                    "inputs": {"vae_name": "LTX2\\video_vae.safetensors"}},
        }
        sizes = {"LTX2\\dit.safetensors": 20 * 2**30,
                 "LTX2\\gemma12b.safetensors": 14 * 2**30,
                 "LTX2\\gemma_e2b.safetensors": 9 * 2**30,
                 "LTX2\\video_vae.safetensors": 2 * 2**30}
        with patch.object(server, "_weight_file_bytes",
                          side_effect=lambda kinds, rel: sizes[rel]):
            heavy, peak = server.graph_weight_bill(g)
        self.assertEqual(sum(sizes.values()), 45 * 2**30)   # the old number
        self.assertEqual(peak, 22 * 2**30)                  # dit + vae, staged
        self.assertEqual(len(heavy), 3)     # all three still tracked by name

    def test_weight_bill_charges_the_pid_stack_flat(self):
        g = {"p": {"class_type": server.PID_UPSCALE_NODE, "inputs": {"factor": "4x"}}}
        heavy, total = server.graph_weight_bill(g)
        self.assertEqual(heavy, {})
        self.assertEqual(total, server.PID_STACK_BYTES)

    def test_activation_estimate_grows_with_the_canvas(self):
        def g(w, h):
            return {"lat": {"class_type": "EmptySD3LatentImage",
                            "inputs": {"width": w, "height": h, "batch_size": 1}}}
        small = server.graph_activation_bytes("realism_ii", g(1088, 1936))
        large = server.graph_activation_bytes("realism_ii", g(2176, 3872))
        self.assertGreater(large, small)

    def test_video_pays_by_the_frame_not_by_the_canvas(self):
        _base, per_mp, per_mp_frame = server.ACT_PROFILES["h3_i2v"]
        self.assertEqual(per_mp, 0.0)         # video pays by frame, not by canvas
        self.assertGreater(per_mp_frame, 0.0)

    def test_a_guessed_canvas_is_clamped(self):
        """The scan reads any node that mentions a size - upscale_video.json's
        DenoRTX preset reports 1920x1080 that has nothing to do with the clip.
        A wrong guess must cost a needless flush, not several hundred GB."""
        g = {"preset": {"class_type": "X",
                        "inputs": {"width": 99999, "height": 99999}}}
        priced = server.graph_activation_bytes("h3_i2v", g)
        self.assertLess(priced, 32 * 2**30)

    def test_a_video_graph_without_info_still_finds_its_frames(self):
        """H3's graph is built in code and does carry a literal `length`, so
        the fallback has to read it - defaulting to 1 frame would price a
        362-frame render as a still."""
        def g(length):
            return {"h3": {"class_type": "MiniMaxH3ImageToVideo",
                           "inputs": {"width": 768, "height": 1344,
                                      "length": length}}}
        self.assertGreater(server.graph_activation_bytes("h3_i2v", g(362)),
                           server.graph_activation_bytes("h3_i2v", g(124)))

    def test_video_activation_grows_with_duration(self):
        """The bug behind all three ltx25 OOMs: a 2-second clip and a
        20-second clip were priced identically at a flat 8GB."""
        def price(seconds):
            return server.graph_activation_bytes(
                "ltx25_i2v", {}, {"canvas_mp": 0.9, "frames": 24 * seconds + 1})
        short, long = price(2), price(20)
        self.assertGreater(long, short * 2)
        # and a 20s clip must price above what is left of a 32GB card
        self.assertGreater(long, 20 * 2**30)

    def test_the_builder_beats_the_graph_scan_for_the_canvas(self):
        """klein_inpaint's composite step names the SOURCE's full resolution.
        A max() over every width/height in the graph would charge that as the
        sampling canvas - 30MP for a render that samples at 2."""
        g = {"back": {"class_type": "ImageScale",
                      "inputs": {"width": 4608, "height": 6912}}}
        priced = server.graph_activation_bytes("klein_inpaint", g,
                                               {"canvas_mp": 2.1})
        scanned = server.graph_activation_bytes("klein_inpaint", g)
        self.assertLess(priced, scanned / 10)


class _StubHub:
    """Just enough Hub for ensure_vram: state + spies, the real method."""
    queue_remaining = 0

    def __init__(self, resident=None, critic_hot=False, last_used=None,
                 job_seq=0):
        self.jobs = {}
        self.resident_heavies = dict(resident or {})
        self.critic_hot = critic_hot
        self.prev_job_free_min = None
        # 9.48's watch state: which lane used what, and the priced-job clock.
        self.model_last_used = dict(last_used or {})
        self.job_seq = job_seq
        self.flushed = False
        self.texts = []

    async def flush_comfy_cache(self, why, unload=True, free_memory=True):
        self.flushed = True
        self.flush_free_memory = free_memory
        if unload:
            self.resident_heavies = {}
            self.model_last_used = {}
            self.critic_hot = False
        return True

    def broadcast(self, **kw):
        if kw.get("type") == "text":
            self.texts.append(kw.get("text"))

    ensure_vram = server.Hub.ensure_vram
    reclaim_vram = server.Hub.reclaim_vram
    busy_elsewhere = server.Hub.busy_elsewhere
    forget_residency = server.Hub.forget_residency
    evict_idle_lane = server.Hub.evict_idle_lane
    rest_brain_for_render = server.Hub.rest_brain_for_render
    note_desktop_weight = server.Hub.note_desktop_weight
    idle_lane_weights = server.Hub.idle_lane_weights
    idle_lane_template = server.Hub.idle_lane_template
    _mark_used = server.Hub._mark_used


class VramButlerBehavior(unittest.TestCase):
    """The contract from the chat thread: riffing on a warm stack never costs
    a reload; switching to a stack that cannot fit clears the deck."""

    def test_riffing_on_a_warm_stack_never_flushes(self):
        hub = _StubHub(resident={"Krea 2\\m.safetensors": 12 * 2**30})
        g = {"u": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": "Krea 2\\m.safetensors"}}}
        with ExitStack() as st:
            st.enter_context(patch.object(
                server, "_weight_file_bytes", return_value=12 * 2**30))
            st.enter_context(patch.object(
                server, "comfy_vram_free_bytes", AsyncMock(return_value=8 * 2**30)))
            st.enter_context(patch.object(
                server, "ram_free_bytes", return_value=32 * 2**30))
            asyncio.run(hub.ensure_vram("realism_ii", g, {"id": "j1", "cid": "c"}))
        self.assertFalse(hub.flushed)
        self.assertEqual(hub.texts, [])

    def test_switching_stacks_on_a_full_card_flushes(self):
        # 9.48's order ahead of the flush it always ran: the abandoned lane
        # (no usage record - it predates the watch) goes first as a SOFT
        # unload, then, still short, the hard flush clears the deck.
        hub = _StubHub(resident={"Krea 2\\old.safetensors": 12 * 2**30})
        g = {"u": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": "ZiT\\new.safetensors"}}}
        job = {"id": "j2", "cid": "c"}
        with ExitStack() as st:
            st.enter_context(patch.object(
                server, "_weight_file_bytes", return_value=12 * 2**30))
            st.enter_context(patch.object(
                server, "comfy_vram_free_bytes", AsyncMock(return_value=3 * 2**30)))
            st.enter_context(patch.object(
                server, "gpu_free_bytes", return_value=25 * 2**30))
            st.enter_context(patch.object(
                server, "ram_free_bytes", return_value=32 * 2**30))
            # No resident brain (9.35): nothing to rest first, so the cold
            # path goes straight to the flush it always ran.
            st.enter_context(patch.object(
                server, "brain_vram_estimate", return_value=0))
            st.enter_context(patch.object(
                server, "gpu_process_table", return_value=[]))
            brain = st.enter_context(patch.object(
                server, "free_brain_vram", AsyncMock(return_value=True)))
            st.enter_context(patch.object(
                server.asyncio, "sleep", AsyncMock()))
            asyncio.run(hub.ensure_vram("zimage", g, job))
        self.assertTrue(hub.flushed)
        brain.assert_not_awaited()          # the flush alone made room
        self.assertTrue(job.get("model_switch"))
        self.assertEqual(hub.texts,
                         ["*freed 12 GB of idle lane weights*",
                          "*making room - this render stages ~13GB: "
                          "cleared cached models*"])

    def test_a_stack_too_big_for_the_flush_rests_the_brain(self):
        hub = _StubHub(resident={})
        g = {"u": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": "H3\\dit.safetensors"}}}
        with ExitStack() as st:
            st.enter_context(patch.object(
                server, "_weight_file_bytes", return_value=20 * 2**30))
            st.enter_context(patch.object(
                server, "comfy_vram_free_bytes", AsyncMock(return_value=18 * 2**30)))
            st.enter_context(patch.object(
                server, "gpu_free_bytes", return_value=24 * 2**30))
            st.enter_context(patch.object(
                server, "ram_free_bytes", return_value=32 * 2**30))
            st.enter_context(patch.object(
                server, "gpu_process_table", return_value=[]))
            brain = st.enter_context(patch.object(
                server, "free_brain_vram", AsyncMock(return_value=True)))
            st.enter_context(patch.object(
                server.asyncio, "sleep", AsyncMock()))
            asyncio.run(hub.ensure_vram("h3_i2v", g, {"id": "j3", "cid": "c"}))
        self.assertTrue(hub.flushed)
        brain.assert_awaited()              # 20GB DiT + 8GB flat needs the brain's seat

    def test_the_critic_is_never_butlered(self):
        """The critic never goes through the weight-bill butler.

        Its 8B FP16 loads through transformers inside ComfyUI's process, so
        graph_weight_bill cannot see or price it and comfy's torch-aware free
        number is a lie for it (comfy counts its own reclaimable cache as free;
        a transformers .cuda() cannot reclaim that). So for vl_review/vl_look
        the priced path - comfy_vram_free_bytes, the brain eviction, the
        model_switch narration - must stay untouched, whatever the card looks
        like. A warm critic is left completely alone, and a roomy card is left
        completely alone.
        """
        priced = AsyncMock()
        brain = AsyncMock(return_value=True)
        for template in ("vl_review", "vl_look"):
            for label, hot, free_gb in (("warm", True, 24), ("roomy", False, 24)):
                with self.subTest(template=template, card=label):
                    hub = _StubHub(resident={}, critic_hot=hot)
                    job = {"id": "j4", "cid": "c"}
                    with patch.object(server, "comfy_vram_free_bytes", priced), \
                         patch.object(server, "free_brain_vram", brain), \
                         patch.object(server, "gpu_free_bytes",
                                      return_value=free_gb * 2**30):
                        asyncio.run(hub.ensure_vram(template, {}, job))
                    self.assertFalse(hub.flushed)
                    self.assertEqual(hub.texts, [])
                    self.assertNotIn("model_switch", job)
                    priced.assert_not_awaited()
                    brain.assert_not_awaited()

    def test_a_warm_critic_on_a_starved_card_is_not_trusted(self):
        """critic_hot only ever proved the model loaded ONCE. It survived
        ComfyUI restarts and the Settings "Free VRAM" button, and a heavy
        render between two looks evicts the critic without clearing it - so a
        starved card must still get reclaimed even when the flag says warm."""
        hub = _StubHub(resident={}, critic_hot=True)
        job = {"id": "j4b", "cid": "c"}
        with patch.object(server, "comfy_vram_free_bytes", AsyncMock()), \
             patch.object(server, "free_brain_vram", AsyncMock(return_value=True)), \
             patch.object(server, "gpu_free_bytes",
                          return_value=server.CRITIC_VRAM_NEED - 2**30), \
             patch.object(server.asyncio, "sleep", AsyncMock()):
            asyncio.run(hub.ensure_vram("vl_look", {}, job))
        self.assertTrue(hub.flushed)

    def test_a_cold_critic_on_a_full_card_gets_the_cache_cleared(self):
        """A look right after a heavy render OOM'd on a 30.45GiB-allocated card
        (vl_look 655c4311, 2026-08-12), because the old early-return left the
        critic unmanaged. Below CRITIC_VRAM_NEED on the DRIVER's number, the
        comfy cache goes - still without the priced path - and when the flush
        alone is not enough (here it never is: the driver number stays short),
        the chat brain rests too, because its grown KV cache (measured 7.2GB)
        is exactly the margin a 20GB critic pass is missing."""
        hub = _StubHub(resident={}, critic_hot=False)
        priced, brain = AsyncMock(), AsyncMock(return_value=True)
        job = {"id": "j5", "cid": "c"}
        with patch.object(server, "comfy_vram_free_bytes", priced), \
             patch.object(server, "free_brain_vram", brain), \
             patch.object(server, "gpu_free_bytes",
                          return_value=server.CRITIC_VRAM_NEED - 2**30), \
             patch.object(server.asyncio, "sleep", AsyncMock()):
            asyncio.run(hub.ensure_vram("vl_look", {}, job))
        self.assertTrue(hub.flushed)
        self.assertFalse(hub.critic_hot)     # the flush evicted it too
        priced.assert_not_awaited()
        brain.assert_awaited_once()
        self.assertTrue(any("rested the chat brain" in t for t in hub.texts))
        self.assertNotIn("model_switch", job)


class _StopWatch(Exception):
    """Breaks gpu_watch's infinite poll once the scripted ticks are spent."""


class _FakeStatsResp:
    async def json(self):
        return {}                    # no cuda device -> the SSE block bows out


class _FakeStatsGet:
    async def __aenter__(self):
        return _FakeStatsResp()

    async def __aexit__(self, *exc):
        return False


class _FakeStatsSession:
    """Just enough aiohttp for gpu_watch's /system_stats fetch."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, *a, **kw):
        return _FakeStatsGet()


class _WatchHub:
    """Just enough Hub for gpu_watch's in-flight sampling: the real loop,
    synthetic nvidia-smi readings, no GPU anywhere near it."""

    def __init__(self):
        self.jobs = {}
        self.gpu = None
        self.paging_streak = 0

    def broadcast(self, **kw):
        pass

    gpu_watch = server.Hub.gpu_watch


class VramStartOccupancy(unittest.TestCase):
    """Task 1 of brief 9.8: a job's VRAM story was missing its first page.
    The peak and the floor were recorded, but never how full the card already
    WAS when the job started - so 'the job got hungrier' and 'the card
    started fuller' were indistinguishable in every logged line."""

    def run_watch(self, job, readings):
        """Feed gpu_watch synthetic (free, used, gpu%, membus%) ticks, one per
        loop iteration, then raise out of the poll sleep."""
        hub = _WatchHub()
        hub.jobs[job["id"]] = job
        with patch.object(server.aiohttp, "ClientSession", _FakeStatsSession), \
             patch.object(server, "gpu_stats", side_effect=readings), \
             patch.object(server.asyncio, "sleep",
                          AsyncMock(side_effect=[None] * (len(readings) - 1)
                                    + [_StopWatch()])):
            with self.assertRaises(_StopWatch):
                asyncio.run(hub.gpu_watch())

    def test_start_occupancy_is_set_once_and_never_moved(self):
        gb = 2**30
        job = {"id": "w1", "cid": "c", "started": time.time()}
        # A later, larger read must move the peak but NOT the start figure -
        # the whole point is where the card was when the job arrived.
        self.run_watch(job, [(12 * gb, 20 * gb, 10, 5),
                             (4 * gb, 28 * gb, 10, 5)])
        self.assertEqual(job.get("_vram_start_used"), 20 * gb)
        self.assertEqual(job["_vram_peak"], 28 * gb)
        self.assertEqual(job["_vram_free_min"], 4 * gb)


class PrevFloorGuard(unittest.TestCase):
    """Task 2 of brief 9.8 as a pure decision: the previous job's floor and
    the guard band in, trim/no-trim out. No GPU read, no ComfyUI call, no
    render - injected numbers only (the LIVE-MACHINE RULE's sanctioned
    simulation)."""

    def test_a_previous_job_below_the_band_trims(self):
        self.assertTrue(server.prev_floor_below_guard(
            int(0.9 * 2**30), server.PREV_JOB_FREE_GUARD))

    def test_a_comfortable_previous_job_does_not_trim(self):
        self.assertFalse(server.prev_floor_below_guard(
            int(8.0 * 2**30), server.PREV_JOB_FREE_GUARD))

    def test_an_unsampled_previous_job_is_no_signal_not_zero(self):
        # The stale-value bug class busy_elsewhere and forget_residency were
        # written against: an absent floor must never read as 0.0GB and
        # switch the trim on forever.
        self.assertFalse(server.prev_floor_below_guard(
            None, server.PREV_JOB_FREE_GUARD))

    def test_sitting_exactly_on_the_band_is_not_below_it(self):
        self.assertFalse(server.prev_floor_below_guard(
            server.PREV_JOB_FREE_GUARD, server.PREV_JOB_FREE_GUARD))


class VramPrevFloorTrim(unittest.TestCase):
    """The guard-band rule wired into the butler: 27 of the last 126 priced
    renders ended under 1.0GB free, so a job that fits as the card stands
    still takes headroom back when the LAST job ended inside the band. A
    resident chat brain steps aside first (9.35 - the cheap reload); only
    its absence gets the trim. Never an unload (the reload IS the bill)."""

    GRAPH = {"u": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": "Krea 2\\m.safetensors"}}}

    def run_butler(self, prev_min, brain_alive=False):
        hub = _StubHub(resident={"Krea 2\\m.safetensors": 12 * 2**30})
        hub.prev_job_free_min = prev_min
        with ExitStack() as st:
            st.enter_context(patch.object(
                server, "_weight_file_bytes", return_value=12 * 2**30))
            st.enter_context(patch.object(
                server, "comfy_vram_free_bytes",
                AsyncMock(return_value=8 * 2**30)))
            st.enter_context(patch.object(
                server, "gpu_free_bytes", return_value=25 * 2**30))
            st.enter_context(patch.object(
                server, "ram_free_bytes", return_value=32 * 2**30))
            hub.brain = st.enter_context(patch.object(
                server, "free_brain_vram",
                AsyncMock(return_value=brain_alive)))
            st.enter_context(patch.object(
                server.asyncio, "sleep", AsyncMock()))
            asyncio.run(hub.ensure_vram("realism_ii", dict(self.GRAPH),
                                      {"id": "j9", "cid": "c"}))
        return hub

    def test_a_near_miss_last_job_trims_the_pool_without_unloading(self):
        hub = self.run_butler(int(0.9 * 2**30))     # no brain resident
        hub.brain.assert_awaited_once()             # it is always asked first
        self.assertTrue(hub.flushed)                # ...so the trim happened
        self.assertEqual(hub.resident_heavies,      # ...but unload=False: the
                         {"Krea 2\\m.safetensors": 12 * 2**30})  # stack stayed
        self.assertEqual(hub.texts, [])             # silent in the lane

    def test_a_near_miss_rests_a_resident_brain_instead_of_trimming(self):
        hub = self.run_butler(int(0.9 * 2**30), brain_alive=True)
        hub.brain.assert_awaited_once()
        self.assertFalse(hub.flushed)               # rest, not trim
        self.assertEqual(hub.resident_heavies,      # the stack stays resident
                         {"Krea 2\\m.safetensors": 12 * 2**30})
        self.assertEqual(hub.texts,
                         ["*rested the chat brain for headroom - the last "
                          "render ended at 0.9GB free*"])

    def test_a_comfortable_last_job_costs_the_next_one_nothing(self):
        hub = self.run_butler(int(8 * 2**30))
        hub.brain.assert_not_awaited()
        self.assertFalse(hub.flushed)
        self.assertEqual(hub.texts, [])


class BrainVramEstimate(unittest.TestCase):
    """The estimate the butler spends before flushing: the resident GGUF's
    bytes plus BRAIN_KV_SLACK - and 0 whenever there is nothing of ours to
    rest, so a stranger's server is never spent as headroom we cannot take."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def estimate(self, state):
        with patch.object(server, "_llm_state", return_value=state):
            return server.brain_vram_estimate()

    def test_no_pid_means_nothing_of_ours_is_resident(self):
        self.assertEqual(self.estimate({}), 0)
        self.assertEqual(self.estimate({"pid": None, "model": "x.gguf"}), 0)

    def test_a_missing_model_file_estimates_zero(self):
        gone = str(self.root / "gone.gguf")
        self.assertEqual(self.estimate({"pid": 4242, "model": gone}), 0)

    def test_a_resident_brain_prices_its_gguf_plus_the_kv_slack(self):
        model = self.root / "brain.gguf"
        model.write_bytes(b"\0" * 4_500_000)
        self.assertEqual(self.estimate({"pid": 4242, "model": str(model)}),
                         4_500_000 + server.BRAIN_KV_SLACK)


class VramButlerBrainRest(unittest.TestCase):
    """9.48's fixed order wired into the cold path: idle lane weights first,
    the brain second (it respawns on the next chat message). zimage is
    unprofiled, so the graph below prices at 12GB weights + 1GB act + 2GB
    floor = 15GB need. The resident old lane is stamped as used one job
    ago, so step 1's N=2 rule protects it and the brain is the lever under
    test: when the rest alone closes the gap there is no /free post at all;
    when it falls short the flush runs as priced, and the note cannot fire
    a second time."""

    GRAPH = {"u": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": "ZiT\\new.safetensors"}}}
    # The old lane ran 1 job ago - in play, so the watch cannot evict it.
    LAST_USED = {"Krea 2\\old.safetensors": (2, "realism_ii", 12 * 2**30)}

    def run_butler(self, free_reads, brain_gb, brain_kills, gpu_free_gb=13):
        hub = _StubHub(resident={"Krea 2\\old.safetensors": 12 * 2**30},
                       last_used=dict(self.LAST_USED), job_seq=2)
        job = {"id": "b1", "cid": "c"}
        with ExitStack() as st:
            st.enter_context(patch.object(
                server, "_weight_file_bytes", return_value=12 * 2**30))
            st.enter_context(patch.object(
                server, "comfy_vram_free_bytes",
                AsyncMock(side_effect=[f * 2**30 for f in free_reads])))
            st.enter_context(patch.object(
                server, "gpu_free_bytes", return_value=gpu_free_gb * 2**30))
            st.enter_context(patch.object(
                server, "gpu_hogs", return_value=[]))
            st.enter_context(patch.object(
                server, "ram_free_bytes", return_value=32 * 2**30))
            st.enter_context(patch.object(
                server, "gpu_process_table", return_value=[]))
            st.enter_context(patch.object(
                server, "brain_vram_estimate",
                return_value=brain_gb * 2**30))
            hub.brain = st.enter_context(patch.object(
                server, "free_brain_vram",
                AsyncMock(side_effect=brain_kills)))
            st.enter_context(patch.object(
                server.asyncio, "sleep", AsyncMock()))
            asyncio.run(hub.ensure_vram("zimage", dict(self.GRAPH), job))
        return hub, job

    def test_a_short_job_rests_the_brain_instead_of_flushing(self):
        # 10GB free, need 15GB, a 6GB brain: the rest closes the gap, the
        # post-rest read lands at 16GB - the job fits, the flush is skipped,
        # so NO /free post ever leaves the stub.
        hub, job = self.run_butler([10, 16], 6, [True])
        hub.brain.assert_awaited_once()
        self.assertFalse(hub.flushed)
        self.assertEqual(hub.resident_heavies,
                         {"ZiT\\new.safetensors": 12 * 2**30})
        self.assertEqual(hub.texts,
                         ["*brain rested for the render (6.0 GB)*"])
        self.assertNotIn("model_switch", job)

    def test_a_rest_that_falls_short_still_flushes_without_repeating(self):
        # Same gap, but the post-rest read lands at 12GB - still short of
        # 15GB, so the flush runs as priced. The brain is already gone (the
        # pidfile went with the kill, so the real free_brain_vram answers
        # False the second time): the note must not fire twice.
        hub, job = self.run_butler([10, 12], 6, [True, False])
        self.assertEqual(hub.brain.await_count, 2)
        self.assertTrue(hub.flushed)
        self.assertTrue(job.get("model_switch"))
        self.assertEqual(hub.texts, [
            "*brain rested for the render (6.0 GB)*",
            "*making room - this render stages ~13GB: cleared cached models. "
            "Still tight (13.0GB free) - something outside Pixal holds the "
            "rest, so this one may crawl*"])


class WarmVideoRerun(unittest.TestCase):
    """9.39: the unconditional pre-video flush was right for a DIRTY card
    (three ltx25 OOMs started from a still's stack under a video's) and
    wrong for a warm one - three same-still H3 clips in a row each paid
    ~100s to reload the 24.9GB stack the flush had just evicted. So when
    every heavy file the graph names is already resident and the
    activations fit, the clip keeps the stack and goes. The test is set
    membership, not the still path's hot == weights: weights is a PEAK
    (max heavy + light) where hot is a SUM, so H3's DiT+CLIP pair could
    never satisfy it. Every other video case flushes exactly as today.

    The graph mirrors build_h3_i2v's spine - UNETLoader + CLIPLoader (both
    HEAVY_KEYS) + a VAELoader (light). With no builder info the h3_i2v
    profile prices act at its 5.0GB base, so 7GB free is the bar."""

    GRAPH = {"1": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": "H3\\dit.safetensors"}},
             "2": {"class_type": "CLIPLoader",
                   "inputs": {"clip_name": "H3\\clip.safetensors"}},
             "3": {"class_type": "VAELoader",
                   "inputs": {"vae_name": "H3\\vae.safetensors"}}}
    SIZES = {"H3\\dit.safetensors": 20 * 2**30,
             "H3\\clip.safetensors": 8 * 2**30,
             "H3\\vae.safetensors": 1 * 2**30}
    RESIDENT = {"H3\\dit.safetensors": 20 * 2**30,
                "H3\\clip.safetensors": 8 * 2**30}
    HEAVY = dict(RESIDENT)      # what dict(heavy) re-records after a flush

    def run_butler(self, resident, free_gb, ram_gb=32, prev_min=None,
                   brain_alive=False, template="h3_i2v", last_used=None,
                 job_seq=0):
        hub = _StubHub(resident=resident, last_used=last_used,
                       job_seq=job_seq)
        hub.prev_job_free_min = prev_min
        job = {"id": "v1", "cid": "c"}
        with ExitStack() as st:
            st.enter_context(patch.object(
                server, "_weight_file_bytes",
                side_effect=lambda _kinds, rel: self.SIZES[rel]))
            st.enter_context(patch.object(
                server, "comfy_vram_free_bytes",
                AsyncMock(return_value=free_gb * 2**30)))
            st.enter_context(patch.object(
                server, "gpu_free_bytes", return_value=25 * 2**30))
            st.enter_context(patch.object(
                server, "gpu_hogs", return_value=[]))
            st.enter_context(patch.object(
                server, "gpu_process_table", return_value=[]))
            st.enter_context(patch.object(
                server, "ram_free_bytes", return_value=ram_gb * 2**30))
            hub.brain = st.enter_context(patch.object(
                server, "free_brain_vram",
                AsyncMock(return_value=brain_alive)))
            st.enter_context(patch.object(
                server.asyncio, "sleep", AsyncMock()))
            asyncio.run(hub.ensure_vram(template, dict(self.GRAPH), job))
        return hub, job

    def test_a_second_clip_from_the_same_stack_never_flushes(self):
        # The extra resident entry is the keep-vs-replace tell: the warm
        # path keeps residency as it stands, where the still fit path
        # REPLACES it with dict(heavy).
        warm = {**self.RESIDENT, "H3\\extra.safetensors": 1 * 2**30}
        hub, job = self.run_butler(warm, free_gb=8)
        self.assertFalse(hub.flushed)
        hub.brain.assert_not_awaited()          # no near-miss predecessor
        self.assertEqual(hub.resident_heavies, warm)
        self.assertEqual(hub.texts, [])
        self.assertNotIn("model_switch", job)

    def test_a_missing_heavy_file_flushes_as_today(self):
        # Only the DiT is resident - the 8GB text encoder is not, so this
        # is a cold stack by the brief's own definition, and a cold stack
        # flushes. The set membership test is what makes "any heavy file
        # missing" a veto; a size coincidence (hot == weights with the
        # light VAE excluded from hot) can never stand in for it.
        hub, job = self.run_butler(
            {"H3\\dit.safetensors": 20 * 2**30}, free_gb=8)
        self.assertTrue(hub.flushed)
        self.assertTrue(job.get("model_switch"))
        self.assertEqual(hub.resident_heavies, self.HEAVY)

    def test_a_card_too_short_for_the_activations_flushes_as_today(self):
        hub, job = self.run_butler(self.RESIDENT, free_gb=6)   # bar is 7
        self.assertTrue(hub.flushed)
        self.assertTrue(job.get("model_switch"))

    def test_short_ram_flushes_as_today(self):
        # 1GB against the full 21GB bill + RAM_FLOOR: the warm path wants
        # no reload looming anywhere, RAM included.
        hub, job = self.run_butler(self.RESIDENT, free_gb=8, ram_gb=1)
        self.assertTrue(hub.flushed)
        self.assertTrue(job.get("model_switch"))

    def test_a_cold_video_stack_flushes_exactly_as_today(self):
        # A still's stack resident under the clip: the dirty card the
        # unconditional flush was written for, unchanged by 9.39.
        hub, job = self.run_butler(
            {"Krea 2\\m.safetensors": 12 * 2**30}, free_gb=8)
        self.assertTrue(hub.flushed)
        self.assertTrue(job.get("model_switch"))
        self.assertEqual(hub.resident_heavies, self.HEAVY)

    def test_a_still_template_on_the_same_numbers_is_unchanged(self):
        warm = {**self.RESIDENT, "H3\\extra.safetensors": 1 * 2**30}
        hub, job = self.run_butler(warm, free_gb=8, template="zimage")
        self.assertFalse(hub.flushed)           # the fit path, as today
        self.assertEqual(hub.resident_heavies,  # ...which REPLACES residency
                         self.HEAVY)
        self.assertEqual(hub.texts, [])

    def test_a_near_miss_last_job_rests_the_brain_on_the_warm_path(self):
        # The 9.35 guard applies ahead of the keep-and-return, the same
        # way it does for stills: rest the cheap reload, keep the weights.
        # The extra is stamped as this-lane usage (9.48): with nothing idle
        # to evict, the guard's escalation reaches the brain as before.
        warm = {**self.RESIDENT, "H3\\extra.safetensors": 1 * 2**30}
        hub, job = self.run_butler(warm, free_gb=8,
                                   prev_min=int(0.9 * 2**30),
                                   brain_alive=True,
                                   last_used={"H3\\extra.safetensors":
                                              (0, "h3_i2v", 1 * 2**30)})
        hub.brain.assert_awaited_once()
        self.assertFalse(hub.flushed)           # rest, not trim
        self.assertEqual(hub.resident_heavies, warm)
        self.assertEqual(hub.texts,
                         ["*rested the chat brain for headroom - the last "
                          "render ended at 0.9GB free*"])

    def test_a_near_miss_without_a_brain_trims_without_unloading(self):
        warm = {**self.RESIDENT, "H3\\extra.safetensors": 1 * 2**30}
        hub, job = self.run_butler(warm, free_gb=8,
                                   prev_min=int(0.9 * 2**30),
                                   last_used={"H3\\extra.safetensors":
                                              (0, "h3_i2v", 1 * 2**30)})
        hub.brain.assert_awaited_once()         # it is always asked first
        self.assertTrue(hub.flushed)            # ...so the trim happened
        self.assertEqual(hub.resident_heavies,  # ...but unload=False: the
                         warm)                  # stack stayed, extras too
        self.assertEqual(hub.texts, [])         # silent in the lane


class _FinalizeHub:
    """Just enough Hub for finalize's vram bookkeeping: the real method,
    a job that errored before any output, no ledger write."""

    def __init__(self):
        self.critic_hot = False
        self.prev_job_free_min = None
        self.ledgered = []

    def broadcast(self, **kw):
        pass

    def ledger_append(self, entry):
        self.ledgered.append(entry)

    def ledger_read(self):
        # No history on this stub: the full-card tell finds no baseline and
        # stays silent, which is what the vram-handoff tests need.
        return []

    finalize = server.Hub.finalize
    lane_median_elapsed = server.Hub.lane_median_elapsed


class FinalizeVramHandoff(unittest.TestCase):
    """finalize is where the previous job's floor reaches the butler - and
    where a job that was never sampled must overwrite a low predecessor,
    or one bad night trims every later job forever."""

    def job(self, **extra):
        return {"id": "f1", "cid": "c", "template": "realism",
                "started": time.time(), "images": [], "error": "boom",
                **extra}

    def test_finalize_hands_the_butler_the_jobs_floor(self):
        hub = _FinalizeHub()
        hub.finalize(self.job(_vram_peak=28 * 2**30,
                              _vram_free_min=int(0.8 * 2**30)))
        self.assertEqual(hub.prev_job_free_min, int(0.8 * 2**30))

    def test_an_unsampled_job_clears_a_low_floor_to_no_signal(self):
        hub = _FinalizeHub()
        hub.prev_job_free_min = int(0.8 * 2**30)   # a low predecessor
        hub.finalize(self.job())                    # never got a gpu sample
        self.assertIsNone(hub.prev_job_free_min)

    def test_the_ledger_entry_carries_the_delta_not_just_the_console(self):
        """The log rotates; ACT_PROFILES gets fitted against peak MINUS start,
        so both numbers have to reach history.jsonl or phase 2 has nothing."""
        hub = _FinalizeHub()
        hub.finalize(self.job(images=[{"filename": "a.png"}], error=None,
                              scene="s", seed=1, count=1, spec={}, elapsed=3,
                              _priced={"est": 20 * 2**30},
                              _vram_start_used=11 * 2**30,
                              _vram_peak=28 * 2**30,
                              _vram_free_min=int(0.8 * 2**30)))
        self.assertEqual(len(hub.ledgered), 1)
        vram = hub.ledgered[0]["vram"]
        self.assertEqual(vram["start"], 11 * 2**30)
        self.assertEqual(vram["peak"], 28 * 2**30)
        self.assertEqual(vram["peak"] - vram["start"], 17 * 2**30)

    def test_an_unsampled_job_writes_no_vram_block(self):
        hub = _FinalizeHub()
        hub.finalize(self.job(images=[{"filename": "a.png"}], error=None,
                              scene="s", seed=1, count=1, spec={}, elapsed=3))
        self.assertNotIn("vram", hub.ledgered[0])


class _RetryHub:
    """Just enough Hub for the OOM recovery path: spies + the real methods."""

    def __init__(self):
        self.texts, self.submitted = [], []
        self.resident_heavies, self.critic_hot = {}, False

    def broadcast(self, **kw):
        if kw.get("type") == "text":
            self.texts.append(kw.get("text"))

    async def submit(self, cid, src, template, scene, spec, count=1,
                     parent=None, flags=None):
        self.submitted.append({"template": template, "spec": spec,
                               "flags": flags or {}})
        return {"id": "r1", **(flags or {})}

    async def cancel_siblings(self, job):
        pass

    async def reclaim_vram(self, why, target=None):
        return 30 * 2**30

    forget_residency = server.Hub.forget_residency
    seconds_that_fit = server.Hub.seconds_that_fit
    oom_retry_plan = server.Hub.oom_retry_plan
    retry_after_oom = server.Hub.retry_after_oom


OOM_TEXT = "Allocation on device 0 would exceed allowed memory. (out of memory)"


class OomRecovery(unittest.TestCase):
    """An OOM used to end the render. Every one in the log was marginal, so the
    contract now is: clear the card, come back once, smaller, and say so."""

    def run_retry(self, job, free_gb=30):
        hub = _RetryHub()
        with patch.object(server, "free_brain_vram", AsyncMock(return_value=True)), \
             patch.object(server, "gpu_free_bytes", return_value=free_gb * 2**30):
            asyncio.run(hub.retry_after_oom(job))
        return hub

    def test_the_allocator_message_is_recognised(self):
        self.assertTrue(server.looks_like_oom(OOM_TEXT))
        self.assertTrue(server.looks_like_oom("CUDA out of memory. Tried to allocate"))
        self.assertFalse(server.looks_like_oom("comfy rejected the graph"))
        self.assertFalse(server.looks_like_oom("stopped"))
        self.assertFalse(server.looks_like_oom(None))

    def test_a_long_clip_comes_back_at_a_length_that_fits(self):
        """Halving a 20s clip leaves 10s, which still does not fit - and the
        retry only gets one attempt, so it has to solve rather than guess."""
        job = {"id": "j", "cid": "c", "template": "ltx25_i2v", "scene": "a pan",
               "seed": 7, "count": 1, "error": OOM_TEXT,
               "spec": {"seconds": 20, "image": "s.png"},
               "_priced": {"weights": 22 * 2**30, "mp": 0.9, "frames": 481}}
        hub = self.run_retry(job)
        self.assertEqual(len(hub.submitted), 1)
        secs = hub.submitted[0]["spec"]["seconds"]
        self.assertLess(secs, 20)
        # and the shrunk clip must actually be priceable inside the card
        _b, _p, slope = server.ACT_PROFILES["ltx25_i2v"]
        need = (22 * 2**30 + int(4.0 * 2**30)
                + slope * 0.9 * (24 * secs + 1) * 2**30 + server.VRAM_FLOOR)
        self.assertLessEqual(need, 30 * 2**30)
        self.assertEqual(hub.submitted[0]["spec"]["seed"], 7)   # same frame
        self.assertTrue(hub.submitted[0]["flags"]["_oom_retry"])
        self.assertIn("instead of", hub.texts[0])

    def test_h3_steps_down_a_rung_because_its_lengths_are_a_menu(self):
        job = {"id": "j", "cid": "c", "template": "h3_i2v", "scene": "x",
               "seed": 1, "count": 1, "error": OOM_TEXT, "spec": {"seconds": 15}}
        hub = self.run_retry(job)
        self.assertEqual(hub.submitted[0]["spec"]["seconds"], 10)

    def test_h3_at_its_shortest_has_nothing_left_to_try(self):
        job = {"id": "j", "cid": "c", "template": "h3_i2v", "scene": "x",
               "seed": 1, "count": 1, "error": OOM_TEXT, "spec": {"seconds": 5}}
        hub = self.run_retry(job)
        self.assertEqual(hub.submitted, [])
        self.assertIn("nothing smaller", hub.texts[0])

    def test_an_edit_comes_back_at_half_the_canvas(self):
        """klein_inpaint takes no size argument - its scale nodes are reached
        through the overrides every builder applies last."""
        job = {"id": "j", "cid": "c", "template": "klein_inpaint",
               "scene": "red top", "seed": 3, "count": 1, "error": OOM_TEXT,
               "spec": {"image": "s.png"}, "info": {"megapixels": 2.0}}
        hub = self.run_retry(job)
        overrides = hub.submitted[0]["spec"]["overrides"]
        self.assertEqual({o["node"] for o in overrides},
                         {"ki:scale", "ki:maskscale"})
        self.assertTrue(all(o["input"] == "megapixels" for o in overrides))
        self.assertEqual({o["value"] for o in overrides}, {1.0})

    def test_a_retry_that_ooms_again_is_terminal(self):
        """One retry. A loop here would burn the card for minutes."""
        job = {"id": "j", "cid": "c", "template": "ltx25_i2v", "scene": "x",
               "seed": 1, "count": 1, "error": OOM_TEXT,
               "spec": {"seconds": 10}, "_oom_retry": True}
        hub = _RetryHub()
        self.assertIsNone(hub.oom_retry_plan(job))

    def test_the_retry_survives_finalize_rewriting_the_error(self):
        """finalize replaces the allocator's wording with something the user
        can read, and that friendlier text does not match OOM_MARKERS. Reading
        the verdict back off job["error"] inside the retry task therefore made
        the retry refuse itself - silently, and only in the real call order."""
        job = {"id": "j", "cid": "c", "template": "ltx25_i2v", "scene": "x",
               "seed": 1, "count": 1, "spec": {"seconds": 10},
               "error": OOM_TEXT,
               "_priced": {"weights": 22 * 2**30, "mp": 0.9, "frames": 241}}
        # exactly what finalize does before spawning the task
        self.assertTrue(server.looks_like_oom(job["error"]))
        job["_oom"] = True
        job["error"] = "ran out of VRAM - clearing the card and retrying"
        self.assertFalse(server.looks_like_oom(job["error"]))
        hub = self.run_retry(job)
        self.assertEqual(len(hub.submitted), 1)     # it still retries

    def test_a_failure_that_is_not_an_oom_is_left_alone(self):
        job = {"id": "j", "cid": "c", "template": "ltx25_i2v", "scene": "x",
               "seed": 1, "count": 1, "spec": {},
               "error": "comfy rejected the graph: bad lora name"}
        hub = _RetryHub()
        self.assertIsNone(hub.oom_retry_plan(job))


class LoraWarningLane(unittest.TestCase):
    """Dropped LoRA names get a visible lane line, not only the job-card row."""

    def test_dropped_names_become_a_lane_line(self):
        text = server._lora_warning_text(["incompatible wrong", "ghost"])
        self.assertIn("left out of this render", text)
        self.assertIn("incompatible wrong", text)
        self.assertIn("ghost", text)

    def test_clean_stack_stays_silent(self):
        self.assertIsNone(server._lora_warning_text([]))
        self.assertIsNone(server._lora_warning_text(None))
        self.assertIsNone(server._lora_warning_text(["  "]))


class AnimaRecipeTests(unittest.TestCase):
    """Anima is a Cosmos-Predict2 2B anime model on a Qwen3-0.6B BASE text
    encoder. Every value here is ported from ComfyUI's shipped blueprint,
    "Text to Image (Anima Base 1.0)". The one that is impossible to guess from
    filenames - a CLIPLoader type of "stable_diffusion" rather than any qwen
    type - is pinned deliberately, because getting it wrong still renders.
    """

    def build(self, rel="Anima\\anima-base-v1.0.safetensors", **kw):
        entry = {**model(rel, "anima", variant="turbo" if "turbo" in rel else "base")}
        with assets(entry):
            return server.build_anima("a girl on a rooftop at dusk", 12345, **kw)

    def test_the_graph_matches_the_official_workflow(self):
        g, _, _ = self.build()
        self.assertEqual(g["2"]["inputs"]["type"], "stable_diffusion")
        k = g["8"]["inputs"]
        self.assertEqual((k["sampler_name"], k["scheduler"]), ("er_sde", "simple"))
        self.assertEqual((k["steps"], k["cfg"]), (30, 4.0))
        self.assertEqual(k["seed"], 12345)

    def test_no_shift_node_rides_along(self):
        # supported_models.Anima already declares shift 3.0, so a
        # ModelSamplingAuraFlow node patches in exactly what is there. Pixal
        # shipped one for a commit; an A/B on a fixed seed was pixel-identical.
        g, _, _ = self.build()
        self.assertNotIn("ModelSamplingAuraFlow",
                         [n["class_type"] for n in g.values()])
        self.assertEqual(g["8"]["inputs"]["model"], ["1", 0])

    def test_turbo_brings_its_own_schedule(self):
        # the card is explicit: "Use at CFG 1 and 8-12 steps"
        g, _, _ = self.build("Anima\\anima-turbo-v1.0.safetensors")
        k = g["8"]["inputs"]
        self.assertEqual((k["steps"], k["cfg"]), (10, 1.0))

    def test_the_negative_prompt_is_real_not_zeroed(self):
        # Z-Image runs CFG 1 and zeroes its negative; Anima runs CFG 4, where a
        # zeroed negative throws away the guidance it is tuned for.
        g, _, _ = self.build()
        self.assertEqual(g["5"]["class_type"], "CLIPTextEncode")
        self.assertIn("worst quality", g["5"]["inputs"]["text"])
        self.assertNotIn("ConditioningZeroOut",
                         [n["class_type"] for n in g.values()])

    def test_a_dressed_brief_stays_dressed_unless_asked(self):
        # Observed, not theoretical: every variant rendered this fully-dressed
        # brief in underwear or less, and the negative alone did not hold it -
        # turbo runs CFG 1, where the negative is not read at all. The closing
        # wardrobe clause is the part that works. nsfw=True lifts all of it.
        sfw, _, _ = self.build()
        self.assertTrue(sfw["4"]["inputs"]["text"].rstrip().endswith(
            "is fully dressed in the clothing described above."))
        self.assertIn("fully clothed", sfw["4"]["inputs"]["text"])
        self.assertIn("underwear", sfw["5"]["inputs"]["text"])
        nsfw, _, _ = self.build(nsfw=True)
        self.assertNotIn("fully", nsfw["4"]["inputs"]["text"])
        self.assertNotIn("underwear", nsfw["5"]["inputs"]["text"])

    def test_turbo_is_guarded_too(self):
        # the variant that needs it most: at CFG 1 the caption is the only lever
        g, _, _ = self.build("Anima\\anima-turbo-v1.0.safetensors")
        self.assertIn("fully dressed", g["4"]["inputs"]["text"])

    def test_quality_tags_lead_the_scene(self):
        g, cap, _ = self.build()
        text = g["4"]["inputs"]["text"]
        self.assertTrue(text.startswith("masterpiece, best quality"))
        self.assertIn("rooftop", text)

    def test_it_is_its_own_family_and_claims_only_its_own_recipe(self):
        for rel, variant in (("Anima\\anima-base-v1.0.safetensors", "base"),
                             ("Anima\\anima-turbo-v1.0.safetensors", "turbo"),
                             ("Anima\\anima-aesthetic-v1.1.safetensors", "base")):
            with self.subTest(rel=rel):
                p = server.model_profile(rel)
                self.assertEqual(p["family"], "anima")
                self.assertEqual(p["variant"], variant)
                self.assertTrue(p["supported"])
                self.assertEqual(server.compatible_recipes(p), ["anima"])

    def test_it_does_not_steal_the_qwen_families(self):
        # Anima ships beside a Qwen encoder and VAE; a name-based fall-through
        # would file the checkpoint itself as qwen_image.
        self.assertEqual(server.model_profile(
            "Qwen\\qwen-image-edit-2511-Q6_K.gguf")["family"], "qwen_edit")
        self.assertEqual(server.model_profile(
            "Qwen\\qwen-image-2512-Q6_K.gguf")["family"], "qwen_image")
        self.assertEqual(server.model_profile(
            "ZiB\\Z-Image_clear_anime_BF16.safetensors")["family"], "zimage")

    def test_the_canvas_follows_the_composer(self):
        g, _, _ = self.build(aspect="1:1 (Square)", mp=1.0)
        w, h = g["6"]["inputs"]["width"], g["6"]["inputs"]["height"]
        self.assertEqual(w, h)
        self.assertEqual(w % 16, 0)


class StoredLoraPlanHealing(unittest.TestCase):
    """A ledger spec outlives the recipe revision it was written under. When
    realism went to revision 2, all 181 Realism cards already in history.jsonl
    replayed straight into "LoRA stack changed; refresh recipe options" and
    died at 0.0s - a re-roll the user could never repair, because the stale
    revision lives in the ledger, not in localStorage."""

    def stale(self, recipe="realism"):
        p = plan(recipe, [{"slot": s["slot"]}
                          for s in server.RECIPE_SPECS[recipe]["lora_stages"]
                          if s["zone"] == "editable"][:1])
        p["recipe_revision"] = 0            # written under an older stack
        return {"aspect": "2:3", "lora_plan": p}

    def test_a_stale_revision_is_restamped_not_dropped(self):
        spec = server.heal_stored_lora_plan("realism", self.stale())
        healed = spec["lora_plan"]
        self.assertEqual(healed["recipe_revision"],
                         server.RECIPE_SPECS["realism"]["lora_stack_revision"])
        # the user's actual choices survive the restamp
        self.assertEqual(healed["entries"], self.stale()["lora_plan"]["entries"])
        server.validate_lora_plan("realism", healed)      # now replays

    def test_a_current_plan_is_returned_untouched(self):
        spec = {"aspect": "2:3", "lora_plan": plan("realism", [])}
        self.assertEqual(server.heal_stored_lora_plan("realism", dict(spec)), spec)

    def test_a_plan_that_cannot_be_healed_falls_back_to_defaults(self):
        # a slot that no longer exists cannot be restamped into validity, so the
        # plan is dropped and the render uses the recipe stack rather than dying
        spec = self.stale()
        spec["lora_plan"]["entries"] = [{"slot": "a_slot_that_was_retired"}]
        self.assertNotIn("lora_plan", server.heal_stored_lora_plan("realism", spec))

    def test_a_video_spec_is_never_indexed_into_recipe_specs(self):
        # h3_i2v is not a still recipe; RECIPE_SPECS[template] would KeyError,
        # which would 500 /api/reroll for every video card in the ledger
        spec = {"lora_plan": {"engine": "h3", "model": "fl2va", "mode": "replace"}}
        self.assertEqual(server.heal_stored_lora_plan("h3_i2v", dict(spec)), spec)

    def test_a_spec_with_no_plan_is_left_alone(self):
        self.assertEqual(server.heal_stored_lora_plan("realism", {"aspect": "1:1"}),
                         {"aspect": "1:1"})


class KleinCompositeTests(unittest.TestCase):
    """The inpaint decode must composite back over the source through the
    grown, feathered mask. Saving the raw decode put every untouched pixel
    through a flux2-VAE round trip - global softening plus blotchy
    reconstruction noise in regions the edit never touched."""

    def build(self, size=(1024, 1024), real=True):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            if real:
                from PIL import Image
                Image.new("RGBA", size, (9, 9, 9, 255)).save(root / "input" / "s.png")
            else:
                (root / "input" / "s.png").write_bytes(b"x")   # unreadable
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "pick_recipe_model",
                              return_value=model(server.KLEIN_MODEL, "klein",
                                                 "edit")), \
                 patch.object(server, "_pick_catalog_asset",
                              side_effect=lambda kind, names, *a: names[0]):
                graph, _scene, info = server.build_klein_inpaint(
                    "make the top red", 5, "s.png")
        self.info = info
        return graph

    def test_an_upscaled_source_samples_small_and_saves_native(self):
        """The OOM: a 4608x6912 PiD upscale went into TWO full-resolution VAE
        encodes and asked for a single 17.09GB block, taking ComfyUI down with
        it (job 7f4d20e2, 2026-08-16)."""
        g = self.build(size=(4608, 6912))
        self.assertEqual(g["ki:scale"]["inputs"]["megapixels"],
                         server.KLEIN_INPAINT_MP_CAP)
        # the mask rides the same resize, or it cannot line up with the pixels
        self.assertEqual(g["ki:maskscale"]["inputs"]["megapixels"],
                         g["ki:scale"]["inputs"]["megapixels"])
        self.assertEqual(g["ki:maskscale"]["inputs"]["resolution_steps"],
                         g["ki:scale"]["inputs"]["resolution_steps"])
        # both encodes read the CAPPED canvas, not the source
        self.assertEqual(g["ki:latent"]["inputs"]["pixels"], ["ki:scale", 0])
        self.assertEqual(g["ki:reffull"]["inputs"]["pixels"], ["ki:scale", 0])
        self.assertEqual(g["ki:latent"]["inputs"]["mask"], ["ki:workmask", 0])
        # and the saved frame is still the source's own size
        self.assertEqual(g["ki:back"]["inputs"]["width"], 4608)
        self.assertEqual(g["ki:back"]["inputs"]["height"], 6912)
        self.assertLess(self.info["canvas_mp"], 2.5)
        self.assertIn("sampled at", self.info["size"])

    def test_a_source_under_the_cap_is_never_upscaled(self):
        g = self.build(size=(1024, 1024))
        self.assertLess(g["ki:scale"]["inputs"]["megapixels"],
                        server.KLEIN_INPAINT_MP_CAP)
        self.assertEqual(g["ki:back"]["inputs"]["width"], 1024)

    def test_an_unmeasurable_source_skips_the_cap_rather_than_guessing(self):
        """ki:back has to hold the source's EXACT size for the composite to
        lay the patch down. No size means no cap - capping blind would
        composite a 1024px patch onto a full-size frame."""
        g = self.build(real=False)
        self.assertEqual(g["ki:latent"]["inputs"]["pixels"], ["ki:img", 0])
        self.assertEqual(g["ki:latent"]["inputs"]["mask"], ["ki:img", 1])
        self.assertEqual(g["ki:reffull"]["inputs"]["pixels"], ["ki:img", 0])
        self.assertEqual(g["ki:composite"]["inputs"]["generated_image"],
                         ["ki:decode", 0])

    def test_untouched_pixels_come_from_the_source_not_the_decode(self):
        """The original is the ORIGINAL file, at its own resolution - not the
        scaled sampling copy; ki:back brings the decode up to meet it.

        The tail is KleinEditComposite (Jesse's pick by eye, 2026-08-25,
        render 00010 of the earring edit): background-referenced colour match,
        Poisson-blended seam, feathered edge. The mask-local KJNodes ColorMatch
        it replaced (daf47de) scored better on a saturation mean and worse on
        a face - the seam is what the eye sees, and a mean cannot."""
        g = self.build()
        self.assertEqual(g["ki:save"]["inputs"]["images"], ["ki:composite", 0])
        c = g["ki:composite"]
        self.assertEqual(c["class_type"], "KleinEditComposite")
        self.assertEqual(c["inputs"]["original_image"], ["ki:img", 0])
        self.assertEqual(c["inputs"]["generated_image"], ["ki:back", 0])
        self.assertEqual(c["inputs"]["color_match_blend"], 1.0)
        self.assertTrue(c["inputs"]["poisson_blend_edges"])
        self.assertEqual(g["ki:back"]["inputs"]["image"], ["ki:decode", 0])
        self.assertEqual(g["ki:decode"]["class_type"], "VAEDecode")

    def test_composite_window_covers_everything_the_sampler_resampled(self):
        g = self.build()
        self.assertEqual(g["ki:growmask"]["inputs"]["expand"],
                         g["ki:latent"]["inputs"]["grow_mask_by"])
        # the node's own change detection is overridden by OUR mask - the
        # window is the grown paint, not whatever it thinks moved
        c = g["ki:composite"]["inputs"]
        self.assertEqual(c["custom_mask"], ["ki:growmask", 0])
        self.assertEqual(c["custom_mask_mode"], "replace")
        # and the seam is feathered, not a hard edge
        self.assertGreater(c["feather_pct"], 0)


class KleinEditTests(unittest.TestCase):
    """9.44: the whole-frame Klein lane, ported node-for-node from Comfy-Org's
    shipped image_flux2_klein_image_edit_9b_distilled template. No mask, no
    composite: the whole-frame decode IS the output, scaled back to native -
    every pixel deliberately round-trips the flux2 VAE."""

    def build(self, size=(1024, 1024), real=True, pick=None, **kwargs):
        pick = pick or patch.object(
            server, "pick_recipe_model",
            return_value=model(server.KLEIN_MODEL, "klein", "edit"))
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            if real:
                from PIL import Image
                Image.new("RGB", size, (9, 9, 9)).save(root / "input" / "s.png")
            else:
                (root / "input" / "s.png").write_bytes(b"x")   # unreadable
            with patch.object(server, "CDIR", root), pick, \
                 patch.object(server, "_pick_catalog_asset",
                              side_effect=lambda kind, names, *a: names[0]):
                graph, _scene, info = server.build_klein_edit(
                    "remove her earrings", 5, "s.png", **kwargs)
        self.info = info
        return graph

    def test_loaders_are_the_masked_lanes_constants(self):
        """UNET/CLIP/VAE come through the same helpers and constants as
        klein_inpaint: the int8 convrot stands in for the template's fp8, the
        abliterated Qwen3 8B encodes, the flux2 VAE round-trips the frame."""
        g = self.build()
        self.assertEqual(g["ke:unet"]["class_type"], "UNETLoader")
        self.assertEqual(g["ke:unet"]["inputs"]["unet_name"], server.KLEIN_MODEL)
        self.assertEqual(g["ke:unet"]["inputs"]["weight_dtype"], "default")
        self.assertEqual(g["ke:clip"]["inputs"]["clip_name"], server.KLEIN_CLIP)
        self.assertEqual(g["ke:clip"]["inputs"]["type"], "flux2")
        self.assertEqual(g["ke:vae"]["inputs"]["vae_name"], server.KLEIN_VAE)

    def test_the_reference_latent_chain_is_the_ported_one(self):
        """Both guider branches read the SAME VAEEncode of the scaled source:
        positive from the instruction, negative from the zeroed instruction.
        The source enters only through KV-attention reference latents - the
        sampling latent is empty, which is the distilled edit's design."""
        g = self.build()
        self.assertEqual(g["ke:reflatent"]["class_type"], "VAEEncode")
        self.assertEqual(g["ke:reflatent"]["inputs"]["pixels"], ["ke:scale", 0])
        self.assertEqual(g["ke:reflatent"]["inputs"]["vae"], ["ke:vae", 0])
        self.assertEqual(g["ke:refpos"]["inputs"],
                         {"conditioning": ["ke:pos", 0],
                          "latent": ["ke:reflatent", 0]})
        self.assertEqual(g["ke:neg"]["class_type"], "ConditioningZeroOut")
        self.assertEqual(g["ke:neg"]["inputs"]["conditioning"], ["ke:pos", 0])
        self.assertEqual(g["ke:refneg"]["inputs"],
                         {"conditioning": ["ke:neg", 0],
                          "latent": ["ke:reflatent", 0]})
        self.assertEqual(g["ke:guider"]["inputs"]["positive"], ["ke:refpos", 0])
        self.assertEqual(g["ke:guider"]["inputs"]["negative"], ["ke:refneg", 0])
        self.assertEqual(g["ke:guider"]["inputs"]["model"], ["ke:unet", 0])

    def test_steps_and_cfg_are_the_templates_distilled_schedule(self):
        """4 steps at cfg 1.0 on a Flux2Scheduler, euler - Klein's native
        schedule, not a speed trick."""
        g = self.build()
        self.assertEqual(g["ke:sched"]["class_type"], "Flux2Scheduler")
        self.assertEqual(g["ke:sched"]["inputs"]["steps"], 4)
        self.assertEqual(g["ke:sched"]["inputs"]["width"], ["ke:size", 0])
        self.assertEqual(g["ke:sched"]["inputs"]["height"], ["ke:size", 1])
        self.assertEqual(g["ke:guider"]["inputs"]["cfg"], 1.0)
        self.assertEqual(g["ke:sampler_sel"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(g["ke:latent"]["class_type"], "EmptyFlux2LatentImage")
        self.assertEqual(g["ke:latent"]["inputs"]["width"], ["ke:size", 0])
        self.assertEqual(g["ke:latent"]["inputs"]["height"], ["ke:size", 1])
        s = g["ke:sampler"]["inputs"]
        self.assertEqual(s["noise"], ["ke:noise", 0])
        self.assertEqual(s["guider"], ["ke:guider", 0])
        self.assertEqual(s["sampler"], ["ke:sampler_sel", 0])
        self.assertEqual(s["sigmas"], ["ke:sched", 0])
        self.assertEqual(s["latent_image"], ["ke:latent", 0])
        self.assertEqual(g["ke:noise"]["inputs"]["noise_seed"], 5)

    def test_the_save_is_the_whole_frame_decode_scaled_back(self):
        """No composite - there is no mask. The decode goes through ke:back to
        the source's exact native size and that is what saves."""
        g = self.build()
        self.assertEqual(g["ke:save"]["inputs"]["images"], ["ke:back", 0])
        self.assertEqual(g["ke:back"]["inputs"]["image"], ["ke:decode", 0])
        self.assertEqual(g["ke:back"]["inputs"]["crop"], "disabled")
        self.assertEqual(g["ke:decode"]["class_type"], "VAEDecode")
        self.assertEqual(g["ke:decode"]["inputs"]["samples"], ["ke:sampler", 0])

    def test_an_upscaled_source_samples_small_and_saves_native(self):
        """Same canvas policy as the other edit lanes: the 2 MP ceiling prices
        the VAE round trip, the saved frame stays the source's own size."""
        g = self.build(size=(4608, 6912))
        self.assertEqual(g["ke:scale"]["inputs"]["megapixels"],
                         server.KLEIN_EDIT_MP_CAP)
        self.assertEqual(g["ke:scale"]["inputs"]["resolution_steps"],
                         server.KLEIN_INPAINT_STEPS)
        # the encode reads the CAPPED canvas, not the source
        self.assertEqual(g["ke:reflatent"]["inputs"]["pixels"], ["ke:scale", 0])
        self.assertEqual(g["ke:size"]["inputs"]["image"], ["ke:scale", 0])
        # and the saved frame is still the source's own size
        self.assertEqual(g["ke:back"]["inputs"]["width"], 4608)
        self.assertEqual(g["ke:back"]["inputs"]["height"], 6912)
        self.assertLess(self.info["canvas_mp"], 2.5)
        self.assertIn("sampled at", self.info["size"])

    def test_a_source_under_the_cap_is_never_upscaled(self):
        g = self.build(size=(1024, 1024))
        self.assertLess(g["ke:scale"]["inputs"]["megapixels"],
                        server.KLEIN_EDIT_MP_CAP)
        self.assertEqual(g["ke:back"]["inputs"]["width"], 1024)

    def test_an_explicit_megapixels_wins(self):
        """The OOM retry's lever: it shrinks the canvas through spec
        megapixels, the same way qwen_edit's does."""
        g = self.build(size=(4608, 6912), megapixels=1.0)
        self.assertEqual(g["ke:scale"]["inputs"]["megapixels"], 1.0)

    def test_an_unmeasurable_source_skips_cap_and_scaleback(self):
        """ke:back has to hold the source's EXACT size. No size means no cap
        and no scale-back - capping blind would hand back a 1024px frame, so
        the graph samples native and saves the decode the way the template it
        was ported from always does."""
        g = self.build(real=False)
        self.assertEqual(g["ke:size"]["inputs"]["image"], ["ke:img", 0])
        self.assertEqual(g["ke:reflatent"]["inputs"]["pixels"], ["ke:img", 0])
        self.assertEqual(g["ke:save"]["inputs"]["images"], ["ke:decode", 0])

    def test_a_klein_config_pick_feeds_the_builder(self):
        pick = MagicMock(return_value=model(server.KLEIN_MODEL, "klein", "edit"))
        with patch.object(server, "load_config",
                          return_value={"edit": {"model": server.KLEIN_MODEL}}), \
             patch.object(server, "resolve_model_entry",
                          return_value=model(server.KLEIN_MODEL, "klein", "edit")):
            self.build(pick=patch.object(server, "pick_recipe_model", pick))
        pick.assert_called_once_with(server.KLEIN_MODEL, "klein_edit")

    def test_a_qwen_config_pick_falls_back_to_the_recipe_default(self):
        """The whole-frame slot holds both families now. An explicit klein_edit
        ask while the pick is a Qwen build must not die on the family check -
        it runs the recipe default, the same way an old qwen_edit ledger entry
        rerolled after the pick moved to Klein survives."""
        pick = MagicMock(return_value=model(server.KLEIN_MODEL, "klein", "edit"))
        with patch.object(server, "load_config",
                          return_value={"edit": {"model": "Qwen\\fire.safetensors"}}), \
             patch.object(server, "resolve_model_entry",
                          return_value=model("Qwen\\fire.safetensors",
                                             "qwen_edit", "edit")):
            self.build(pick=patch.object(server, "pick_recipe_model", pick))
        pick.assert_called_once_with(None, "klein_edit")


class KleinScheduleTests(unittest.TestCase):
    """9.52: a Klein build names its own schedule. The official distill IS its
    4-step schedule, so KLEIN_SCHEDULES pairs the schedule to the build by
    filename - an undistilled build (Klein True, the step-distillation trained
    back out) sampled at the distill's 4 steps just looks like mud."""

    TRUE = "Flux\\Flux2-Klein-9B-True-V1-int8mixedrow.safetensors"

    def build_edit(self, rel, size=(4608, 6912)):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            from PIL import Image
            Image.new("RGB", size, (9, 9, 9)).save(root / "input" / "s.png")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "pick_recipe_model",
                              return_value=model(rel, "klein", "edit")), \
                 patch.object(server, "_pick_catalog_asset",
                              side_effect=lambda kind, names, *a: names[0]):
                return server.build_klein_edit("remove her earrings", 5, "s.png")

    def build_inpaint(self, rel, size=(4608, 6912)):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            from PIL import Image
            Image.new("RGBA", size, (9, 9, 9, 255)).save(root / "input" / "s.png")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "pick_recipe_model",
                              return_value=model(rel, "klein", "edit")), \
                 patch.object(server, "_pick_catalog_asset",
                              side_effect=lambda kind, names, *a: names[0]):
                return server.build_klein_inpaint("make the top red", 5, "s.png")

    def test_the_true_build_resolves_to_its_20_step_row(self):
        row = server.klein_schedule(model(self.TRUE, "klein", "edit"))
        self.assertEqual(row["label"], "Klein True (undistilled)")
        self.assertEqual(row["steps"], 20)
        self.assertEqual(row["cfg"], 1.0)

    def test_anything_else_falls_through_to_the_distill(self):
        for rel in (server.KLEIN_MODEL,
                    "Flux\\flux-2-klein-9b_bf16.safetensors",
                    "Flux\\DarkBeast-Klein9b-V2-BFS-FP8.safetensors"):
            row = server.klein_schedule(model(rel, "klein", "edit"))
            self.assertEqual(row["steps"], 4, rel)
            self.assertEqual(row["cfg"], 1.0, rel)

    def test_an_empty_pick_is_the_distill(self):
        self.assertEqual(server.klein_schedule(None)["steps"], 4)
        self.assertEqual(server.klein_schedule({})["steps"], 4)

    def test_the_whole_frame_lane_sets_scheduler_and_guider_from_the_row(self):
        g, _scene, info = self.build_edit(self.TRUE)
        self.assertEqual(g["ke:sched"]["inputs"]["steps"], 20)
        self.assertEqual(g["ke:guider"]["inputs"]["cfg"], 1.0)
        # the card says why this render took five times longer
        self.assertIn("sampled at", info["size"])
        self.assertIn("20 steps", info["size"])

    def test_the_whole_frame_distill_keeps_4_steps_and_a_quiet_card(self):
        g, _scene, info = self.build_edit(server.KLEIN_MODEL)
        self.assertEqual(g["ke:sched"]["inputs"]["steps"], 4)
        self.assertEqual(g["ke:guider"]["inputs"]["cfg"], 1.0)
        self.assertIn("sampled at", info["size"])
        self.assertNotIn("steps", info["size"])

    def test_the_masked_lane_sets_its_sampler_from_the_row(self):
        g, _scene, info = self.build_inpaint(self.TRUE)
        self.assertEqual(g["ki:sampler"]["inputs"]["steps"], 20)
        self.assertEqual(g["ki:sampler"]["inputs"]["cfg"], 1.0)
        self.assertIn("sampled at", info["size"])
        self.assertIn("20 steps", info["size"])

    def test_the_masked_distill_keeps_4_steps_and_a_quiet_card(self):
        g, _scene, info = self.build_inpaint(server.KLEIN_MODEL)
        self.assertEqual(g["ki:sampler"]["inputs"]["steps"], 4)
        self.assertEqual(g["ki:sampler"]["inputs"]["cfg"], 1.0)
        self.assertIn("sampled at", info["size"])
        self.assertNotIn("steps", info["size"])


class EditRoutingTests(unittest.TestCase):
    """9.44: /api/edit sends a mask-less edit to klein_edit when the configured
    edit model is a Klein build, to qwen_edit otherwise; a painted mask always
    takes klein_inpaint; an explicit recipe in the body always wins."""

    QWEN = "Qwen\\qwen-image-edit-2511-Q6_K.gguf"
    KLEIN = "Flux\\flux-2-klein-9b_int8_convrot.safetensors"

    def post(self, body, configured=""):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            from PIL import Image
            Image.new("RGB", (64, 64), (9, 9, 9)).save(root / "input" / "s.png")
            hub = MagicMock()
            hub.submit = AsyncMock(return_value=None)

            def resolve(nm):
                family = "klein" if "klein" in str(nm).lower() else "qwen_edit"
                return model(str(nm), family, "edit")

            async def go():
                with patch.object(server, "CDIR", root), \
                     patch.object(server, "HUB", hub), \
                     patch.object(server, "load_config",
                                  return_value={"edit": {"model": configured}}), \
                     patch.object(server, "resolve_model_entry",
                                  side_effect=resolve):
                    resp = await server.edit(FakeRequest(body))
                await asyncio.sleep(0)      # let the submitted task run its mock
                return resp

            resp = asyncio.run(go())
        self.assertEqual(resp.status, 200, json.loads(resp.text))
        return json.loads(resp.text), hub

    def test_klein_configured_routes_a_maskless_edit_to_klein_edit(self):
        out, hub = self.post({"input": "s.png",
                              "instruction": "make her jacket red"}, self.KLEIN)
        self.assertEqual(out["recipe"], "klein_edit")
        self.assertEqual(hub.submit.call_args[0][2], "klein_edit")

    def test_qwen_configured_keeps_the_qwen_lane(self):
        out, hub = self.post({"input": "s.png",
                              "instruction": "make her jacket red"}, self.QWEN)
        self.assertEqual(out["recipe"], "qwen_edit")
        self.assertEqual(hub.submit.call_args[0][2], "qwen_edit")

    def test_no_config_means_qwen_as_today(self):
        out, _hub = self.post({"input": "s.png",
                               "instruction": "make her jacket red"})
        self.assertEqual(out["recipe"], "qwen_edit")

    def test_a_mask_takes_klein_inpaint_regardless_of_the_pick(self):
        import base64, io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("L", (64, 64), 255).save(buf, format="PNG")
        mask = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        # Klein configured for the whole-frame lane changes nothing for a
        # painted mask; neither does a Qwen pick.
        for configured in (self.KLEIN, self.QWEN):
            out, hub = self.post({"input": "s.png",
                                  "instruction": "make her jacket red",
                                  "mask": mask}, configured)
            self.assertEqual(out["recipe"], "klein_inpaint")
            self.assertEqual(hub.submit.call_args[0][2], "klein_inpaint")

    def test_an_explicit_recipe_wins_over_the_configured_family(self):
        out, hub = self.post({"input": "s.png", "instruction": "x",
                              "recipe": "qwen_edit"}, self.KLEIN)
        self.assertEqual(out["recipe"], "qwen_edit")
        self.assertEqual(hub.submit.call_args[0][2], "qwen_edit")

    def test_a_seed_rides_past_the_sigs_filter(self):
        """Same contract as generate(): submit pops the seed, the recipe
        builders never see it - which is also how same-seed A/B edits work."""
        _out, hub = self.post({"input": "s.png", "instruction": "x",
                               "seed": 424242}, self.QWEN)
        self.assertEqual(hub.submit.call_args[0][4].get("seed"), 424242)

    def test_a_reference_is_refused_when_the_lane_cannot_take_one(self):
        """The reference rides qwen_edit only. Routed to klein_edit it would
        be silently dropped by the SIGS filter - refuse, the same standard the
        masked lane's reference guard already sets."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            from PIL import Image
            Image.new("RGB", (64, 64), (9, 9, 9)).save(root / "input" / "s.png")
            Image.new("RGB", (64, 64), (9, 9, 9)).save(root / "input" / "r.png")
            hub = MagicMock()
            hub.submit = AsyncMock(return_value=None)

            def resolve(nm):
                family = "klein" if "klein" in str(nm).lower() else "qwen_edit"
                return model(str(nm), family, "edit")

            async def go():
                with patch.object(server, "CDIR", root), \
                     patch.object(server, "HUB", hub), \
                     patch.object(server, "load_config",
                                  return_value={"edit": {"model": self.KLEIN}}), \
                     patch.object(server, "resolve_model_entry",
                                  side_effect=resolve):
                    return await server.edit(FakeRequest(
                        {"input": "s.png", "instruction": "add the logo",
                         "reference": "r.png"}))

            resp = asyncio.run(go())
        self.assertEqual(resp.status, 400)
        self.assertIn("reference", json.loads(resp.text)["error"])
        hub.submit.assert_not_called()


class CanvasMath(unittest.TestCase):
    """dims_for turns a shape off a list and a megapixel budget into a canvas.

    The old version derived the height from the UNSNAPPED width and then
    snapped each axis on its own, so the two drifted apart: 3:4 at 2 MP came
    out 1232x1632, a ratio of 0.755 for a shape the user picked as 0.75.
    """

    MPS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.9, 6.0, 8.0)

    def _cases(self):
        for aspect in server.ASPECTS:
            aw, ah = (float(x) for x in aspect.split(" ")[0].split(":"))
            for mp in self.MPS:
                yield aspect, mp, aw / ah, server.dims_for(aspect, mp)

    def test_both_axes_always_land_on_the_grid(self):
        """Off-grid dimensions are the one result a latent cannot use."""
        for aspect, mp, _ratio, (w, h) in self._cases():
            self.assertEqual((w % server.CANVAS_MULTIPLE, h % server.CANVAS_MULTIPLE),
                             (0, 0), f"{aspect} @ {mp}MP -> {w}x{h}")
            self.assertGreaterEqual(min(w, h), server.CANVAS_MULTIPLE)

    def test_the_shape_you_picked_is_the_shape_you_get(self):
        """Within 1%. The grid cannot always hit a ratio exactly - 16:9 at 1 MP
        is the worst case in the whole table - but nothing may drift further."""
        for aspect, mp, ratio, (w, h) in self._cases():
            self.assertLess(abs((w / h) - ratio) / ratio, 0.01,
                            f"{aspect} @ {mp}MP -> {w}x{h} is not that shape")

    def test_the_canvas_is_the_size_that_was_asked_for(self):
        """Holding the ratio is allowed to cost area, but not much of it."""
        for aspect, mp, _ratio, (w, h) in self._cases():
            self.assertLess(abs(w * h - mp * 1e6) / (mp * 1e6), 0.06,
                            f"{aspect} @ {mp}MP -> {w}x{h}")

    def test_asking_for_more_never_returns_less(self):
        """A ladder that goes backwards anywhere is indefensible in a menu."""
        for aspect in server.ASPECTS:
            seen = [server.dims_for(aspect, mp) for mp in self.MPS]
            areas = [w * h for w, h in seen]
            self.assertEqual(areas, sorted(areas), f"{aspect}: {seen}")

    def test_an_exact_ratio_wins_when_it_is_within_reach(self):
        """3:4 at 5.9 MP can be exactly 3:4 one grid step out from the ideal
        width, so it must be - this is the Ultra Realism canvas."""
        self.assertEqual(server.dims_for("3:4 (Portrait Standard)", 5.9), (2112, 2816))

    def test_rounding_is_half_up_so_the_composer_agrees(self):
        """The client mirrors this function to show the canvas before you
        render. Python's bankers round() would disagree with JS Math.round on
        an exact .5, which 4:3 reaches."""
        self.assertEqual(server.dims_for("4:3 (Standard)", 2.0),
                         server.dims_for("4:3 (Standard)", 2.0))
        w, h = server.dims_for("4:3 (Standard)", 2.0)
        self.assertEqual((w % 16, h % 16), (0, 0))


if __name__ == "__main__":
    unittest.main()


class CatalogMatching(unittest.TestCase):
    """_catalog_has decides what a fresh install is told it is MISSING.

    Nobody who downloads from CivitAI inherits our folder layout, so an
    exact-path-only check called a recipe unusable on machines that owned
    every file - while resolve_lora, which has always fallen back to a unique
    basename, would have built the graph fine.
    """

    def catalog(self, *rels):
        return lambda kind=None: [{"rel": r} for r in rels]

    def test_the_exact_path_still_matches(self):
        with patch.object(server, "model_catalog",
                          side_effect=self.catalog(r"Krea 2\bypass.safetensors")):
            self.assertTrue(server._catalog_has(
                "loras", r"Krea 2\bypass.safetensors"))

    def test_the_same_file_in_another_folder_is_still_found(self):
        """The portability fix: their folder, our name."""
        with patch.object(server, "model_catalog",
                          side_effect=self.catalog(r"downloads\bypass.safetensors")):
            self.assertTrue(server._catalog_has(
                "loras", r"Krea 2\bypass.safetensors"))

    def test_a_file_loose_in_the_lora_root_is_found(self):
        with patch.object(server, "model_catalog",
                          side_effect=self.catalog("bypass.safetensors")):
            self.assertTrue(server._catalog_has(
                "loras", r"Krea 2\bypass.safetensors"))

    def test_an_ambiguous_basename_stays_unmatched(self):
        """Two files, one name, no way to tell which - refuse, as before."""
        with patch.object(server, "model_catalog", side_effect=self.catalog(
                r"Krea 2\bypass.safetensors", r"other\bypass.safetensors")):
            self.assertTrue(server._catalog_has(
                "loras", r"Krea 2\bypass.safetensors"))   # exact wins outright
            self.assertFalse(server._catalog_has(
                "loras", r"elsewhere\bypass.safetensors"))

    def test_a_genuinely_absent_file_is_still_missing(self):
        with patch.object(server, "model_catalog",
                          side_effect=self.catalog(r"Krea 2\other.safetensors")):
            self.assertFalse(server._catalog_has(
                "loras", r"Krea 2\bypass.safetensors"))

    def test_forward_slashes_normalise(self):
        with patch.object(server, "model_catalog",
                          side_effect=self.catalog("Krea 2/bypass.safetensors")):
            self.assertTrue(server._catalog_has(
                "loras", r"Krea 2\bypass.safetensors"))

    def test_the_picker_hands_the_loader_the_resolved_name(self):
        """ComfyUI lists a subfoldered file WITH its folder: the only
        ae.safetensors on one box lives under Flux\\, so VAELoader offers
        "Flux\\ae.safetensors" and rejects the bare candidate the basename
        rule matched by. The graph must carry the resolved rel, not the
        literal candidate."""
        with patch.object(server, "model_catalog",
                          side_effect=self.catalog(r"Flux\ae.safetensors")):
            self.assertEqual(
                server._pick_catalog_asset("vae", server.ZIMAGE_VAE_CANDIDATES,
                                           "the Z-Image VAE"),
                r"Flux\ae.safetensors")

    def test_an_ambiguous_basename_falls_through_to_the_next_candidate(self):
        """Two files sharing the candidate's basename resolve to nothing, so
        the next candidate gets its chance instead of dying at the loader."""
        with patch.object(server, "model_catalog", side_effect=self.catalog(
                r"Flux\ae.safetensors", r"copy\ae.safetensors",
                r"ZImage\ZiB_ae.safetensors")):
            self.assertEqual(
                server._pick_catalog_asset("vae", server.ZIMAGE_VAE_CANDIDATES,
                                           "the Z-Image VAE"),
                r"ZImage\ZiB_ae.safetensors")

    def test_an_exact_match_is_returned_as_authored(self):
        with patch.object(server, "model_catalog", side_effect=self.catalog(
                r"ae.safetensors", r"Flux\ae.safetensors")):
            self.assertEqual(
                server._pick_catalog_asset("vae", server.ZIMAGE_VAE_CANDIDATES,
                                           "the Z-Image VAE"),
                "ae.safetensors")


class BypassLoraName(unittest.TestCase):
    """The vector-bypass LoRA is named the way CivitAI ships it, because that
    is the name every machine except this one has it under."""

    def test_the_constant_is_the_civitai_download_name(self):
        self.assertEqual(server.KREA_BYPASS_LORA,
                         r"Krea 2\krea2filterbypass.safetensors")

    def test_no_recipe_still_names_the_local_rename(self):
        for rid, spec in server.RECIPE_SPECS.items():
            for name in spec.get("required_loras", []):
                self.assertNotIn("2vector", name, f"{rid} names a local rename")


class VectorPatchCount(unittest.TestCase):
    """The bypass patches are told apart by what they DO, not their filename -
    two CivitAI versions one character apart, and this box had the 2vector
    filed under a local rename for weeks."""

    def patch_file(self, values, key="diffusion_model.txtfusion.projector.diff"):
        import json as _json, struct as _struct, tempfile, os
        body = _struct.pack("<%df" % len(values), *values)
        header = _json.dumps({key: {"dtype": "F32", "shape": [1, len(values)],
                                    "data_offsets": [0, len(body)]}}).encode()
        blob = _struct.pack("<Q", len(header)) + header + body
        fd, path = tempfile.mkstemp(suffix=".safetensors")
        os.write(fd, blob)
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def count(self, path):
        import os as _os
        st = _os.stat(path)
        return server._vector_patch_count(path, st.st_mtime_ns, st.st_size)

    def test_two_vector(self):
        p = self.patch_file([0.0] * 8 + [-0.5117, -0.8906] + [0.0, 0.0])
        self.assertEqual(self.count(p), 2)

    def test_three_vector(self):
        p = self.patch_file([0.0] * 8 + [-0.5117, -0.8906, -0.6094] + [0.0])
        self.assertEqual(self.count(p), 3)

    def test_an_all_zero_patch_is_not_a_version(self):
        self.assertIsNone(self.count(self.patch_file([0.0] * 12)))

    def test_an_unrelated_tensor_is_ignored(self):
        p = self.patch_file([1.0, 2.0], key="lora_unet_down.lora_up.weight")
        self.assertIsNone(self.count(p))

    def test_a_big_file_is_never_opened(self):
        """The guard that keeps this off every real multi-hundred-MB LoRA."""
        p = self.patch_file([0.0] * 8 + [-0.5, -0.9, 0.0, 0.0])
        self.assertIsNone(server._vector_patch_count(
            p, 0, server._VECTOR_PATCH_MAX_BYTES + 1))

    def test_garbage_is_not_fatal(self):
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".safetensors")
        os.write(fd, b"not a safetensors file at all")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self.assertIsNone(self.count(path))

class FakeRequest:
    """The aiohttp stand-in every settings_post test file keeps local."""
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class KleinInpaintModelPickTests(unittest.TestCase):
    """9.29: the masked lane reads its model pick the way the whole-frame lane
    always has - an explicit per-render pick wins, then Settings
    (edit.inpaint_model), then the recipe default. Until this brief the masked
    lane was hard-pinned to KLEIN_MODEL: Jesse ran a masked edit, saw the job
    report Klein 9B, and three of his four klein builds were unreachable."""

    def pick_seen(self, settings_pick, explicit=None):
        """The model name pick_recipe_model is asked to resolve."""
        seen = []

        def resolve(nm):
            seen.append(nm)
            family = "qwen_edit" if "qwen" in str(nm).lower() else "klein"
            return model(str(nm), family, "edit")

        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "s.png").write_bytes(b"x")   # unmeasurable source
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "load_config",
                              return_value={"edit": {"inpaint_model": settings_pick}}), \
                 patch.object(server, "resolve_model_entry", side_effect=resolve), \
                 patch.object(server, "_pick_catalog_asset",
                              side_effect=lambda kind, names, *a: names[0]):
                server.build_klein_inpaint("make the top red", 5, "s.png",
                                           model=explicit)
        return seen

    def test_the_settings_pick_feeds_the_masked_lane(self):
        seen = self.pick_seen("Flux\\flux-2-klein-9b_bf16.safetensors")
        self.assertEqual(seen, ["Flux\\flux-2-klein-9b_bf16.safetensors"])

    def test_an_explicit_pick_outranks_settings(self):
        seen = self.pick_seen(
            "Flux\\flux-2-klein-9b_bf16.safetensors",
            explicit="Flux\\DarkBeast-Klein9b-V2-BFS-FP8.safetensors")
        self.assertEqual(seen, ["Flux\\DarkBeast-Klein9b-V2-BFS-FP8.safetensors"])

    def test_no_pick_anywhere_keeps_the_recipe_default(self):
        self.assertEqual(self.pick_seen(""), [server.KLEIN_MODEL])

    def test_a_qwen_edit_file_in_the_masked_slot_raises_the_family_error(self):
        with self.assertRaisesRegex(
                ValueError, "is qwen_edit, but Klein Inpaint needs klein"):
            self.pick_seen("Qwen\\qwen-image-edit-2511-Q6_K.gguf")


class EditLaneSettingsTests(unittest.TestCase):
    """9.29: Settings exposes BOTH edit lanes, every option carrying its
    on-disk weight, and the masked lane's pick is validated exactly like the
    whole-frame one - "" is the recipe default, anything else must be an
    installed klein-family build or it is refused with a 400 that names the
    file."""

    QWEN = {"rel": "Qwen\\qwen-image-edit-2511-Q6_K.gguf",
            "kind": "diffusion_models", "size": 10_000_000_000, "mtime": 1}
    KLEIN_BF16 = {"rel": "Flux\\flux-2-klein-9b_bf16.safetensors",
                  "kind": "diffusion_models", "size": 18_000_000_000, "mtime": 1}
    KLEIN_INT8 = {"rel": "Flux\\flux-2-klein-9b_int8_convrot.safetensors",
                  "kind": "diffusion_models", "size": 9_000_000_000, "mtime": 1}

    def _catalog(self, kind=None):
        entries = [self.QWEN, self.KLEIN_BF16, self.KLEIN_INT8]
        return [e for e in entries if kind in (None, e["kind"])]

    def _full_cfg(self, edit):
        return {"llm": {"base_url": "", "model": ""},
                "critic": {"model": ""}, "upscale": {}, "edit": edit, "vae": {},
                "pid": {}, "video": {"default_engine": "", "default_model": ""},
                "extra_model_roots": [], "comfy_editor": False,
                "comfy_console": "tui", "explicit": "auto", "vram_profile": "auto"}

    def _settings_get(self, cfg):
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", side_effect=self._catalog), \
             patch.object(server, "_video_asset", side_effect=lambda k, r: r), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()):
            response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        return json.loads(response.text)["edit"]

    def test_the_edit_block_lists_both_lanes_with_their_weights(self):
        edit = self._settings_get(self._full_cfg(
            {"model": "", "inpaint_model": "", "speed": "turbo"}))
        self.assertEqual(edit["default"], server.QWEN_EDIT_MODEL)
        self.assertEqual(edit["inpaint_default"], server.KLEIN_MODEL)
        self.assertEqual(edit["installed"],
                         [{"name": self.QWEN["rel"], "size": self.QWEN["size"]}])
        # candidates sort by rel: bf16 lands ahead of int8_convrot
        self.assertEqual(edit["inpaint_installed"],
                         [{"name": self.KLEIN_BF16["rel"],
                           "size": self.KLEIN_BF16["size"]},
                          {"name": self.KLEIN_INT8["rel"],
                           "size": self.KLEIN_INT8["size"]}])

    def test_the_masked_pick_round_trips(self):
        cfg = self._full_cfg({"model": "", "inpaint_model": "", "speed": "turbo"})
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", side_effect=self._catalog), \
             patch.object(server, "_video_asset", side_effect=lambda k, r: r), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()), \
             patch.object(server, "save_config", side_effect=lambda c: None):
            post = asyncio.run(server.settings_post(FakeRequest(
                {"edit": {"inpaint_model": self.KLEIN_BF16["rel"]}})))
            self.assertEqual(post.status, 200)
            self.assertEqual(json.loads(post.text), {"ok": True})
            # the cfg object save_config was handed is what the next
            # load_config would return
            edit = self._settings_get(cfg)
        self.assertEqual(edit["inpaint_model"], self.KLEIN_BF16["rel"])

    def test_an_empty_masked_pick_means_the_recipe_default(self):
        saved = []
        with patch.object(server, "load_config",
                          return_value=self._full_cfg(
                              {"model": "", "speed": "turbo"})), \
             patch.object(server, "model_catalog", side_effect=self._catalog), \
             patch.object(server, "save_config",
                          side_effect=lambda cfg: saved.append(cfg)):
            post = asyncio.run(server.settings_post(FakeRequest(
                {"edit": {"inpaint_model": ""}})))
        self.assertEqual(post.status, 200)
        self.assertEqual(saved[0]["edit"]["inpaint_model"], "")

    def test_a_non_klein_file_is_refused_with_a_400_that_names_it(self):
        """The qwen build IS in the catalog - just not in the klein family, so
        the masked lane's candidate list cannot contain it."""
        saved = []
        with patch.object(server, "load_config",
                          return_value=self._full_cfg(
                              {"model": "", "speed": "turbo"})), \
             patch.object(server, "model_catalog", side_effect=self._catalog), \
             patch.object(server, "save_config",
                          side_effect=lambda cfg: saved.append(cfg)):
            response = asyncio.run(server.settings_post(FakeRequest(
                {"edit": {"inpaint_model": self.QWEN["rel"]}})))
        self.assertEqual(response.status, 400)
        self.assertEqual(
            json.loads(response.text),
            {"ok": False, "error": "not an installed Klein Inpaint model: "
                                   + self.QWEN["rel"]})
        self.assertEqual(saved, [])     # a rejected write never touches config

    def test_a_klein_build_is_now_a_valid_whole_frame_pick(self):
        """9.44: the whole-frame slot holds both families - a Klein pick was a
        400 before it routed the mask-less lane to klein_edit."""
        cfg = self._full_cfg({"model": "", "inpaint_model": "", "speed": "turbo"})
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", side_effect=self._catalog), \
             patch.object(server, "_video_asset", side_effect=lambda k, r: r), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()), \
             patch.object(server, "save_config", side_effect=lambda c: None):
            post = asyncio.run(server.settings_post(FakeRequest(
                {"edit": {"model": self.KLEIN_INT8["rel"]}})))
            self.assertEqual(post.status, 200)
            self.assertEqual(json.loads(post.text), {"ok": True})
            edit = self._settings_get(cfg)
        self.assertEqual(edit["model"], self.KLEIN_INT8["rel"])

    def test_a_qwen_build_still_validates_for_the_whole_frame_slot(self):
        cfg = self._full_cfg({"model": "", "inpaint_model": "", "speed": "turbo"})
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", side_effect=self._catalog), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()), \
             patch.object(server, "save_config", side_effect=lambda c: None):
            post = asyncio.run(server.settings_post(FakeRequest(
                {"edit": {"model": self.QWEN["rel"]}})))
        self.assertEqual(post.status, 200)
        self.assertEqual(cfg["edit"]["model"], self.QWEN["rel"])

    def test_an_unknown_edit_model_is_still_refused_with_a_400(self):
        """Both families validate, but a name in NEITHER candidate list is
        refused here rather than failing every later edit."""
        saved = []
        with patch.object(server, "load_config",
                          return_value=self._full_cfg(
                              {"model": "", "speed": "turbo"})), \
             patch.object(server, "model_catalog", side_effect=self._catalog), \
             patch.object(server, "save_config",
                          side_effect=lambda cfg: saved.append(cfg)):
            response = asyncio.run(server.settings_post(FakeRequest(
                {"edit": {"model": "Somewhere\\else.safetensors"}})))
        self.assertEqual(response.status, 400)
        self.assertEqual(
            json.loads(response.text),
            {"ok": False, "error": "not an installed edit model: "
                                   "Somewhere\\else.safetensors"})
        self.assertEqual(saved, [])     # a rejected write never touches config

    def test_the_masked_pick_defaults_to_empty_and_survives_a_save(self):
        with TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            with patch.object(server, "CONFIG", cfg_path):
                # first run: no file at all
                self.assertEqual(server.load_config()["edit"]["inpaint_model"], "")
                # an old config that predates the key still defaults
                cfg_path.write_text(json.dumps({"edit": {"model": "x"}}),
                                    encoding="utf-8")
                self.assertEqual(server.load_config()["edit"]["inpaint_model"], "")
                # and a saved pick round-trips through the file
                cfg_path.write_text(
                    json.dumps({"edit": {"inpaint_model": self.KLEIN_BF16["rel"]}}),
                    encoding="utf-8")
                self.assertEqual(server.load_config()["edit"]["inpaint_model"],
                                 self.KLEIN_BF16["rel"])
