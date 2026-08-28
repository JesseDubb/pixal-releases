"""Brief 9.59 - "Refined" for MiniMax H3 stills: the `h3_still_2x` recipe.

9.58 made H3 a still camera at native 2K; the measured best recipe for those
stills (the Zara hero batch, 2026-08-27) is the in-family 2x latent refine:
the render's own latent re-sampled at 2x through MMH3UltimateUpscale with
the 3D latent upscaler, 6 steps at denoise 0.22 (~3 min total). It resolves
lashes and pores at 3072x4096 and repaints distant-face mush in full-body
shots. This brief makes the composer's Refined quality pill mean that
refine on an H3 build - no new control, no new word.

What these tests pin:

  Recipe      - the spec sits right after h3_still with its own label/tag
                and the same family/variants/default_model/aspect/mp/mp_cap
                and LoRA fields; an image template, never in VIDEO_TEMPLATES;
                registered in BUILDERS and SIGS; the brain's tool enum and
                description carry the one clause.
  GraphShape  - the queued graph IS 9.58's block (nodes 1-14 untouched,
                proven by structural diff against build_h3_still) plus the
                refine block from Jesse's zara_hero.py: up:cond re-conditions
                the SAME prompt at exactly 2x (length 5, no first_frame),
                up:param names the 3D latent upscaler, up:tiles is the exact
                grid, up:sigmas is 6 steps at denoise 0.22 on the authored
                scheduler, up:noise is seed + 1, up:sample is
                MMH3UltimateUpscale, and node 13 reads the 2x decode. No
                temporal split (five frames are one block), no
                ImageScale/ESRGAN anchor (the conditioning is prompt-only).
  Tiling      - every canvas _h3_still_clamp can yield from ASPECTS at mp
                3.1 tiles exactly at 2x, both axes (a sliver tile once put
                noise blocks in a corner).
  Info        - execution_profile h3_still_2x, size the delivered 2x canvas,
                canvas_mp the FIRST pass's (what the butler prices under
                ACT_DEFAULT's still slope), the refine dict for the card;
                validate_job_model_info passes; a ref2va build is refused.
  Gate        - availability flips with h3_upscale_available (the MMH3 pack
                AND the 659 MB weights); unavailable names the exact missing
                label; the builder refuses with a clear ValueError; h3_still
                itself is untouched by the gate.
  Seat        - the seat IS h3_still's map (first pass only; the refine's
                sigmas stay authored - the Realism II rule); defaults report
                the same trio; tuning lands on nodes 7/8 and never reaches
                up:sigmas.
  Routing     - server effective_recipe sends minimax_h3 + refined to
                h3_still_2x on both branches and keeps standard on h3_still;
                store.js routes and gates the same way; the composer's
                refinedAvailable is per-family and the Refined pill's tip
                states the H3 meaning (static, test_lora_card_controls
                style - this repo has no JS runner).
  Butler      - graph_weight_bill prices the latent upscaler (WEIGHT_KEYS
                maps model_name to latent_upscale_models) in the light pile.
  Snapshots   - build_h3_still and build_h3_i2v(upscale=True) are
                byte-identical to before this change (captured from HEAD's
                builders into tests/snapshots/).

Same sanctioned simulation as every sibling file: stubbed catalog, no
generation, no ComfyUI, no GPU.
"""

import json
import unittest
from contextlib import ExitStack
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location(
    "pixal_server_h3_still_refine", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

WEB = ROOT / "web" / "src"
STORE = (WEB / "store.js").read_text(encoding="utf-8")
COMPOSER = (WEB / "components" / "Composer.jsx").read_text(encoding="utf-8")
SNAPSHOTS = ROOT / "tests" / "snapshots"

STOCK = server.H3_MODEL
FINETUNE = "Minimax H3\\10eros_max_fl2va_beta2.safetensors"
REF2VA = server.H3_REF2V_MODEL
UPSCALER = server.H3_LATENT_UPSCALER
MISSING_LABEL = ("MiniMax H3 2x upscale: the MMH3 pack and "
                 "minimax_h3_latent_upscaler_3d_bf16.safetensors")


def h3_entries(root, *, upscale=True):
    """The 9.58 stub catalog, plus the 3D latent upscaler weights when the
    test wants the refine available."""
    def add(kind, rel, size=1):
        return {"rel": rel, "kind": kind, "root": str(root),
                "size": size, "mtime": 0.0}
    entries = [add("diffusion_models", STOCK),
               add("diffusion_models", FINETUNE),
               add("diffusion_models", REF2VA),
               add("vae", server.H3_VIDEO_VAE),
               add("vae", server.H3_AUDIO_VAE),
               add("text_encoders", server.H3_CLIP)]
    if upscale:
        entries.append(add("latent_upscale_models", UPSCALER, 659))
    return entries


def stub_catalog(entries):
    return lambda kind=None: [e for e in entries if kind in (None, e["kind"])]


def no_disk():
    return (patch.object(server, "adjacent_metadata", return_value={}),
            patch.object(server, "model_roots", return_value=[]))


def build(scene="A red barn at dusk", seed=424242, entries=None, **kwargs):
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        entries = h3_entries(root) if entries is None else entries
        sidecar, roots = no_disk()
        with sidecar, roots, \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)):
            return server.build_h3_still_2x(scene, seed, **kwargs)


class RecipeSpecTests(unittest.TestCase):
    """The spec, its place in the registry, and the brain's one clause."""

    def test_the_spec_sits_right_after_h3_still_with_its_own_label(self):
        ids = server.PUBLIC_RECIPE_IDS
        self.assertEqual(ids.index("h3_still_2x"), ids.index("h3_still") + 1)
        spec = server.RECIPE_SPECS["h3_still_2x"]
        base = server.RECIPE_SPECS["h3_still"]
        self.assertEqual(spec["label"], "MiniMax H3 2x")
        self.assertEqual(spec["tag"], "2K still + 2x latent refine · ~3 min")
        # aspect/mp/mp_cap are the FIRST pass's - the refine doubles on top.
        # lora_variants too: the 2x builder re-keys its plan to h3_still
        # (9.74), which is only sound while the two rows' lanes are identical.
        for key in ("family", "variants", "lora_variants", "default_model",
                    "aspect", "mp", "mp_cap", "required_text_encoders",
                    "required_vaes", "lora_stack_revision", "lora_boundary",
                    "lora_stages"):
            self.assertEqual(spec[key], base[key], key)

    def test_the_recipe_is_an_image_template_everywhere(self):
        self.assertNotIn("h3_still_2x", server.VIDEO_TEMPLATES)
        self.assertNotIn("h3_still_2x", server.SOURCE_ONLY_RECIPE_IDS)
        self.assertIs(server.BUILDERS["h3_still_2x"], server.build_h3_still_2x)
        self.assertIn("h3_still_2x", server.PUBLIC_RECIPE_IDS)
        self.assertIn("h3_still_2x", server.SIGS)

    def test_the_brain_tool_lists_and_describes_it(self):
        tool = server.TOOLS[0]["function"]["parameters"]["properties"][
            "template"]
        self.assertIn("h3_still_2x", tool["enum"])
        self.assertIn(
            "h3_still_2x = the H3 still plus its 2x latent refine (~3 min; "
            "the best-looking still in the app; use when the user asks for "
            "maximum detail or a full-body shot)", tool["description"])


class GraphTests(unittest.TestCase):
    """The refine block on top of 9.58's untouched nodes 1-14."""

    def test_nodes_1_to_14_are_build_h3_stills_byte_for_byte(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                base, _, _ = server.build_h3_still("A red barn at dusk", 424242)
                refined, _, _ = server.build_h3_still_2x("A red barn at dusk",
                                                         424242)
        expected = json.loads(json.dumps(base))
        expected["13"]["inputs"]["image"] = ["up:decode", 0]
        carried = {nid: node for nid, node in refined.items()
                   if not nid.startswith("up:")}
        self.assertEqual(carried, expected)

    def test_the_refine_block_is_the_proven_recipe(self):
        g, _cap, _info = build()
        ids = sorted(nid for nid in g if nid.startswith("up:"))
        self.assertEqual(ids, ["up:cond", "up:decode", "up:noise", "up:param",
                               "up:sample", "up:sigmas", "up:tiles"])
        classes = {nid: node["class_type"] for nid, node in g.items()}
        self.assertEqual(classes["up:cond"], "MiniMaxH3ImageToVideo")
        self.assertEqual(classes["up:param"],
                         "MMH3LatentUpscaleWithModelParams")
        self.assertEqual(classes["up:tiles"], "MMH3SpatialSplitParams")
        self.assertEqual(classes["up:sigmas"], "BasicScheduler")
        self.assertEqual(classes["up:noise"], "RandomNoise")
        self.assertEqual(classes["up:sample"], server.H3_UPSCALE_NODE)
        self.assertEqual(classes["up:decode"], "VAEDecode")
        # The SAME prompt, re-conditioned at exactly 2x, length still 5.
        cond = g["up:cond"]["inputs"]
        self.assertEqual(cond, {**g["6"]["inputs"],
                                "width": 3072, "height": 4096})
        self.assertEqual(cond["prompt"], g["6"]["inputs"]["prompt"])
        self.assertEqual(cond["length"], 5)
        self.assertNotIn("first_frame", cond)
        self.assertEqual(g["up:param"]["inputs"], {
            "model_name": UPSCALER, "width": 3072, "height": 4096,
            "device": "cuda", "precision": "bf16"})
        self.assertEqual(g["up:sigmas"]["inputs"], {
            "model": ["1", 0], "scheduler": server.H3_STILL_SCHEDULER,
            "steps": server.H3_UPSCALE_STEPS,
            "denoise": server.H3_UPSCALE_DENOISE})
        # the measured recipe, not a new one
        self.assertEqual((server.H3_UPSCALE_STEPS, server.H3_UPSCALE_DENOISE),
                         (6, 0.22))
        self.assertEqual(g["up:noise"]["inputs"],
                         {"noise_seed": 424242 + 1})
        self.assertEqual(g["10"]["inputs"], {"noise_seed": 424242})
        self.assertEqual(g["up:sample"]["inputs"], {
            "model": ["1", 0], "conditioning": ["up:cond", 0],
            "latent": ["11", 0], "noise": ["up:noise", 0],
            "sampler": ["7", 0], "sigmas": ["up:sigmas", 0], "cfg": 1.0,
            "latent_upscale_param": ["up:param", 0],
            "spatial_split_param": ["up:tiles", 0]})
        self.assertEqual(g["up:decode"]["inputs"], {
            "samples": ["up:sample", 0], "vae": ["3", 0]})
        # still frame 0 only, now off the 2x decode
        self.assertEqual(g["13"]["inputs"], {
            "image": ["up:decode", 0], "batch_index": 0, "length": 1})
        self.assertEqual(g["14"]["inputs"]["images"], ["13", 0])

    def test_no_temporal_split_and_no_image_space_anchor(self):
        g, _cap, _info = build()
        classes = [node["class_type"] for node in g.values()]
        self.assertNotIn("MMH3TemporalSplitParams", classes)
        self.assertNotIn("ImageScale", classes)
        self.assertNotIn("ImageUpscaleWithModel", classes)
        self.assertNotIn("UpscaleModelLoader", classes)
        wire = json.dumps(g)
        self.assertNotIn("temporal_split_param", wire)
        self.assertNotIn("first_frame", wire)

    def test_the_tile_grid_divides_exactly_on_the_default_canvas(self):
        g, _cap, _info = build()
        tiles = g["up:tiles"]["inputs"]
        self.assertEqual(tiles["min_tile_size"], 256)
        self.assertEqual(tiles["overlap_mode"], "earlier")
        self.assertEqual(tiles["overlap_blend"], "smoothstep")
        for size, tile, overlap, fade in (
                (3072, tiles["tile_width"], tiles["spatial_w_overlap"],
                 tiles["fade_width"]),
                (4096, tiles["tile_height"], tiles["spatial_h_overlap"],
                 tiles["fade_height"])):
            hits = [n for n in range(2, 7)
                    if n * tile - (n - 1) * overlap == size]
            self.assertTrue(hits,
                            f"{size}px axis not tiled by {tile}/{overlap}")
            self.assertEqual(fade, max(32, overlap - 32))

    def test_an_explicit_canvas_doubles_exactly(self):
        g, _cap, info = build(width=1536, height=2048)
        cond = g["up:cond"]["inputs"]
        self.assertEqual((cond["width"], cond["height"]), (3072, 4096))
        self.assertEqual((g["6"]["inputs"]["width"], g["6"]["inputs"]["height"]),
                         (1536, 2048))
        self.assertEqual(info["size"], "3072x4096")


class TilingTests(unittest.TestCase):
    """Every canvas the clamp can yield from ASPECTS at mp 3.1 tiles exactly
    at 2x - a sliver tile once put coloured noise blocks in a corner."""

    def test_every_aspect_tiles_exactly_at_2x(self):
        for aspect in server.ASPECTS:
            with self.subTest(aspect=aspect):
                width, height = server.dims_for(
                    aspect, 3.1, multiple=server.H3_CANVAS_MULTIPLE)
                width, height = server._h3_still_clamp(width, height)
                for size in (width * 2, height * 2):
                    tile, overlap = server.h3_tile_axis(size)
                    hits = [n for n in range(2, 7)
                            if n * tile - (n - 1) * overlap == size]
                    self.assertTrue(
                        hits, f"{aspect}: {size}px axis cannot tile exactly")


class InfoTests(unittest.TestCase):
    """The card says what ran, and the butler prices the first pass."""

    def test_the_card_says_what_ran(self):
        g, _cap, info = build()
        self.assertEqual(info["execution_profile"], "h3_still_2x")
        # size is the delivered 2x frame...
        self.assertEqual(info["size"], "3072x4096")
        # ...while canvas_mp stays the FIRST pass's canvas - what the butler
        # prices under ACT_DEFAULT's still slope. The disagreement is the
        # realism_ii convention: priced canvas vs delivered canvas.
        self.assertAlmostEqual(info["canvas_mp"], 3.15, delta=0.01)
        self.assertEqual(info["refine"], {"scale": 2, "steps": 6,
                                          "denoise": 0.22})
        self.assertEqual(info["model_family"], "minimax_h3")
        self.assertEqual(info["model_path"], STOCK)
        self.assertEqual(info["model_variant"], "fl2va")
        self.assertEqual(info["text_encoder"],
                         "qwen3vl_32b_minimax_h3_nvfp4_awq")
        self.assertEqual(info["vae"], "minimax_h3_video_vae_fp16")
        self.assertEqual(info["loras"], [])
        self.assertEqual(info["lora_stack"], [])
        self.assertIsNone(info["character"])
        server.validate_job_model_info("h3_still_2x", info, g)

    def test_a_finetune_build_runs_and_is_attested(self):
        g, _cap, info = build(model=FINETUNE)
        self.assertEqual(g["1"]["inputs"]["unet_name"], FINETUNE)
        self.assertEqual(info["model_path"], FINETUNE)
        self.assertEqual(info["model_variant"], "fl2va")
        server.validate_job_model_info("h3_still_2x", info, g)

    def test_a_ref2va_build_is_refused(self):
        with self.assertRaisesRegex(ValueError, "uses fl2va models"):
            build(model=REF2VA)


class GateTests(unittest.TestCase):
    """The recipe lives and dies with h3_upscale_available(): the MMH3 pack's
    node in the probed list AND the 659 MB weights on disk."""

    def options(self, entries, names=None):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            patches = [patch.object(server, "CDIR", root),
                       patch.object(server, "model_catalog",
                                    side_effect=stub_catalog(entries)),
                       patch.object(server, "model_roots", return_value=[]),
                       patch.object(server, "adjacent_metadata",
                                    return_value={}),
                       patch.object(server, "lm_enrich"),
                       patch.object(server, "_LORA_TITLE_CACHE",
                                    root / "titles.json")]
            if names is not None:
                patches.append(patch.dict(server._COMFY_NODES,
                                          {"names": names}))
            with ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                return server.Hub().options()

    def recipe(self, options):
        return next(r for r in options["recipes"] if r["id"] == "h3_still_2x")

    def test_available_with_the_pack_and_the_weights(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td)))
        recipe = self.recipe(options)
        self.assertTrue(recipe["available"])
        self.assertEqual(recipe["missing"], [])
        self.assertEqual(recipe["label"], "MiniMax H3 2x")
        self.assertEqual(recipe["default_model"], STOCK)
        self.assertEqual(recipe["family"], "minimax_h3")
        self.assertEqual(recipe["variants"], ["fl2va"])
        self.assertEqual(recipe["mp_cap"], 3.15)
        # the composer's defaults row carries the recipe's own (first-pass)
        # canvas
        self.assertEqual(options["defaults"]["h3_still_2x"]["mp"], 3.1)
        self.assertEqual(options["defaults"]["h3_still_2x"]["aspect"],
                         "3:4 (Portrait Standard)")
        # fl2va builds list both still recipes; ref2va lists neither
        meta = options["model_meta"]
        self.assertIn("h3_still_2x", meta[STOCK]["compatible_recipes"])
        self.assertIn("h3_still", meta[STOCK]["compatible_recipes"])
        self.assertNotIn("h3_still_2x", meta[REF2VA]["compatible_recipes"])

    def test_unavailable_without_the_weights_names_the_exact_label(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td), upscale=False))
        recipe = self.recipe(options)
        self.assertFalse(recipe["available"])
        self.assertIn(MISSING_LABEL, recipe["missing"])
        # ...and the base still recipe is untouched by the gate.
        still = next(r for r in options["recipes"] if r["id"] == "h3_still")
        self.assertTrue(still["available"])
        self.assertEqual(still["missing"], [])

    def test_unavailable_without_the_pack_even_with_the_weights(self):
        with TemporaryDirectory() as td:
            # a successful probe that does NOT list MMH3UltimateUpscale
            options = self.options(h3_entries(Path(td)),
                                   names=frozenset({"UNETLoader"}))
        recipe = self.recipe(options)
        self.assertFalse(recipe["available"])
        self.assertIn(MISSING_LABEL, recipe["missing"])

    def test_the_builder_refuses_without_the_upscale_path(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaisesRegex(ValueError, "MMH3 pack"):
                build(entries=h3_entries(root, upscale=False))


class SeatTests(unittest.TestCase):
    """The seat is the FIRST pass's - the refine's sigmas stay authored."""

    def test_the_seat_is_h3_stills_map(self):
        self.assertEqual(server.SAMPLER_SEATS["h3_still_2x"],
                         server.SAMPLER_SEATS["h3_still"])
        keys = server.seat_tuning_keys(server.SAMPLER_SEATS["h3_still_2x"])
        self.assertEqual(keys, ("steps", "sampler_name", "scheduler"))
        self.assertNotIn("cfg", keys)

    def test_defaults_report_the_same_trio(self):
        self.assertEqual(server.sampler_defaults("h3_still_2x"),
                         {"steps": 20, "sampler_name": "dpmpp_sde_gpu",
                          "scheduler": "beta"})

    def test_tuning_lands_on_the_first_pass_only(self):
        overrides = server.tuning_overrides(
            "h3_still_2x", None,
            {"steps": 12, "cfg": 3.5, "sampler_name": "euler",
             "scheduler": "beta", "eta": 0.3})
        self.assertEqual(overrides, [
            {"node": "8", "input": "steps", "value": 12},
            {"node": "7", "input": "sampler_name", "value": "euler"},
            {"node": "8", "input": "scheduler", "value": "beta"}])
        g, _cap, _info = build(overrides=overrides)
        self.assertEqual(g["8"]["inputs"]["steps"], 12)
        self.assertEqual(g["7"]["inputs"]["sampler_name"], "euler")
        # the refine's schedule is what "refined" means - not a dial
        self.assertEqual(g["up:sigmas"]["inputs"]["steps"],
                         server.H3_UPSCALE_STEPS)
        self.assertEqual(g["up:sigmas"]["inputs"]["scheduler"],
                         server.H3_STILL_SCHEDULER)
        self.assertEqual(g["up:sigmas"]["inputs"]["denoise"],
                         server.H3_UPSCALE_DENOISE)
    def test_the_refine_also_samples_at_the_ab_winner(self):
        """9.78: both passes are the same still - the refine's sampler
        input rides the first pass's KSamplerSelect, and its own sigmas
        take the still scheduler."""
        g, _cap, _info = build()
        self.assertEqual(g["7"]["inputs"], {"sampler_name": "dpmpp_sde_gpu"})
        self.assertEqual(g["up:sample"]["inputs"]["sampler"], ["7", 0])
        self.assertEqual(g["up:sigmas"]["inputs"]["scheduler"], "beta")


class RoutingTests(unittest.TestCase):
    """Server and client send minimax_h3 + refined to h3_still_2x."""

    def test_effective_recipe_routes_refined_to_the_2x_recipe(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                self.assertEqual(
                    server.effective_recipe({"model": STOCK,
                                             "style": "realism",
                                             "quality": "refined"}),
                    "h3_still_2x")
                # whatever style the selector last held
                self.assertEqual(
                    server.effective_recipe({"model": STOCK,
                                             "style": "anime",
                                             "quality": "refined"}),
                    "h3_still_2x")
                self.assertEqual(
                    server.effective_recipe({"model": STOCK,
                                             "style": "realism",
                                             "quality": "standard"}),
                    "h3_still")
                # the model-only branch (no style/quality keys) stays h3_still
                self.assertEqual(server.effective_recipe({"model": STOCK}),
                                 "h3_still")


class ButlerBillTests(unittest.TestCase):
    """graph_weight_bill prices the 3D latent upscaler in the light pile:
    WEIGHT_KEYS maps model_name to latent_upscale_models, so the 659 MB ride
    beside the VAE - the video lane's upscale path prices it the same way."""

    def test_the_bill_sees_the_latent_upscaler(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            sizes = {STOCK: 1000, server.H3_CLIP: 500,
                     server.H3_VIDEO_VAE: 100, UPSCALER: 659}
            entries = []
            for kind, rel in (("diffusion_models", STOCK),
                              ("text_encoders", server.H3_CLIP),
                              ("vae", server.H3_VIDEO_VAE),
                              ("latent_upscale_models", UPSCALER)):
                path = root / kind / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x" * sizes[rel])
                entries.append({"rel": rel, "kind": kind, "root": str(root),
                                "size": sizes[rel], "mtime": 0.0})
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)):
                g, _cap, _info = server.build_h3_still_2x("a barn", 1)
                heavy, peak = server.graph_weight_bill(g)
        self.assertEqual(heavy, {STOCK: 1000, server.H3_CLIP: 500})
        # heaviest heavy + the VAE + the latent upscaler
        self.assertEqual(peak, 1000 + 100 + 659)


class SnapshotTests(unittest.TestCase):
    """The two graphs this brief must not move, captured from HEAD's
    builders into tests/snapshots/ (the tools/make_realism_snapshot.py
    contract)."""

    def test_build_h3_still_is_byte_identical_to_before(self):
        snap = json.loads((SNAPSHOTS / "h3_still_graph.json")
                          .read_text(encoding="utf-8"))
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(
                                  h3_entries(root, upscale=False))):
                g, cap, _info = server.build_h3_still("A red barn at dusk",
                                                      424242)
        self.assertEqual(cap, snap["caption"])
        self.assertEqual(g, snap["graph"])

    def test_the_animate_upscale_graph_is_byte_identical_to_before(self):
        snap = json.loads((SNAPSHOTS / "h3_i2v_upscale_graph.json")
                          .read_text(encoding="utf-8"))
        cfg = {"upscale": {"image_model": "4x\\4xPurePhoto-RealPLSKR.pth"}}
        catalog = [{"kind": "upscale_models",
                    "rel": "4x\\4xPurePhoto-RealPLSKR.pth", "mtime": 0}]
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "load_config", return_value=cfg), \
                 patch.object(server, "model_catalog", return_value=catalog), \
                 patch.object(server, "_video_asset",
                              side_effect=lambda _kind, rel: rel), \
                 patch.dict(server._COMFY_NODES,
                            {"names": frozenset({server.H3_UPSCALE_NODE})}):
                g, brief, _info = server.build_h3_i2v(
                    "She turns.", 987, "prepared.png", seconds=5,
                    width=928, height=1120, model="fl2va", upscale=True)
        self.assertEqual(brief, snap["brief"])
        self.assertEqual(g, snap["graph"])


class ClientRoutingTests(unittest.TestCase):
    """Static, in the test_lora_card_controls.py style: the contracts the
    client source must keep for Refined to mean the 2x refine on an H3
    build."""

    def test_store_routes_refined_h3_picks_to_the_2x_recipe(self):
        # 9.67 put the ref2va branch in front; the fl2va rule it guards is
        # unchanged (refined -> 2x, standard -> plain still).
        self.assertRegex(
            STORE,
            r'if \(meta\?\.family === "minimax_h3"\)\s*'
            r'return meta\.variant === "ref2va" \? "h3_ref_still"\s*'
            r': opts\.quality === "refined" \? "h3_still_2x" : "h3_still";')

    def test_store_gates_refined_on_the_2x_recipes_availability(self):
        self.assertRegex(
            STORE,
            r'if \(meta\?\.family === "minimax_h3"\) \{\s*'
            r'style = "realism";\s*'
            r'quality = quality === "refined" && \(options\?\.recipes \|\| \[\]\)\s*'
            r'\.some\(\(recipe\) => recipe\.id === "h3_still_2x" '
            r'&& recipe\.available\)')
        # ...and the Realism II guard must not strip what that gate allowed.
        self.assertIn('quality === "refined" && meta?.family !== "minimax_h3"',
                      STORE)
        self.assertIn('recipe.id === "realism_ii" && recipe.available', STORE)

    def test_the_composers_refined_availability_is_per_family(self):
        self.assertRegex(
            COMPOSER,
            r'const refinedRecipeId = selectedModelMeta\.family === '
            r'"minimax_h3"\s*\? "h3_still_2x" : "realism_ii";')
        self.assertRegex(
            COMPOSER,
            r'const refinedAvailable = !!recipeById\(refinedRecipeId\)'
            r'\?\.available')

    def test_the_refined_pill_states_the_h3_meaning(self):
        # one fact per line: what it is, what it resolves and repairs, cost
        self.assertIn(
            '"2x latent refine in the model\'s own family\\n'
            'lashes and pores at 3072x4096, and it repairs distant faces\\n'
            '~3 min"',
            COMPOSER)
        # the disabled note rides the same per-family recipe
        self.assertIn("recipeById(refinedRecipeId)?.missing", COMPOSER)
        # ...while the Realism II wording is untouched.
        self.assertIn('"Refined is available with Krea 2 models"', COMPOSER)
        self.assertIn('"two-pass finish"', COMPOSER)
        self.assertIn('"Krea 2 only"', COMPOSER)


if __name__ == "__main__":
    unittest.main()
