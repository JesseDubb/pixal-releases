"""Brief 9.66 - drop a render, get a style: ComfyUI workflow metadata ->
saved-style draft.

`style_from_render_metadata` reads the JSON ComfyUI's save nodes embed in
every output file ("prompt" = the API graph, "workflow" = the editor graph,
A1111's "parameters" text as a third, best-effort lane) and drafts a
recipes/*.json-shaped style record from it, with a ledger of what mapped
and what did not. It never saves - styles_post stays the only writer.

What these tests pin:

  RoundTrip   - a Pixal-shaped zimage graph (hand-copied from
                _build_zimage's output) maps every field, unmapped is
                empty, scene is the positive prompt, and the draft passes
                validate_saved_style unchanged.
  Honesty     - an unknown node class and an uninstalled LoRA both land in
                unmapped with reasons while the rest of the fields map;
                nothing raises.
  A1111       - a "parameters" string maps steps/cfg/size/sampler (Euler a
                -> euler_ancestral), resolves the model and LoRA by stem,
                and strips <lora:> tags out of the scene.
  NoMetadata  - a chunk-free PNG answers ok: False with the "no render
                metadata" error.
  BadBytes    - non-image bytes and a truncated PNG answer ok: False and
                never raise.

Fixtures are built in-test with PIL + PngInfo - no binary files in the
repo. Catalog lookups are patched: the test box has no models.
"""

import asyncio
import io
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location(
    "pixal_server_style_from_image", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

MODEL_REL = "ZiT\\z_image_turbo_bf16.safetensors"
KREA_REL = "Krea 2\\test_krea.safetensors"
LORA_REL = "ZImage\\teststyle.safetensors"
SCENE = "a red barn at dusk, cinematic"

H3_REL = "Minimax H3\\minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors"

CATALOG = [
    {"kind": "diffusion_models", "root": "X", "rel": MODEL_REL,
     "mtime": 0, "size": 0},
    {"kind": "diffusion_models", "root": "X", "rel": KREA_REL,
     "mtime": 0, "size": 0},
    {"kind": "diffusion_models", "root": "X", "rel": H3_REL,
     "mtime": 0, "size": 0},
]
LORAS = [
    {"name": LORA_REL, "title": None, "short": "teststyle",
     "group": "ZImage", "krea2": False},
]


def patched_catalogs():
    """The one model and one LoRA this file's graphs name, and nothing else."""
    return (
        patch.object(server, "model_catalog",
                     side_effect=lambda kind=None, ttl=30:
                     [e for e in CATALOG if kind in (None, e["kind"])]),
        patch.object(server, "model_roots", return_value=[]),
        patch.object(server, "adjacent_metadata", return_value={}),
        patch.object(server, "lora_catalog", return_value=LORAS),
    )


def png_bytes(text_chunks=None):
    """A real PNG built in memory: the chunks ride as tEXt, like ComfyUI's
    own save node writes them - no binary fixtures in the repo."""
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    im = Image.new("RGB", (8, 8), (20, 30, 40))
    meta = PngInfo()
    for key, value in (text_chunks or {}).items():
        meta.add_text(key, value)
    buf = io.BytesIO()
    im.save(buf, "PNG", pnginfo=meta)
    return buf.getvalue()


def pixal_zimage_graph(lora_name=LORA_REL, extra_nodes=None):
    """Hand-copied from _build_zimage's output shape (non-zeroed negative):
    same node ids, class_types and wiring the builder emits."""
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": MODEL_REL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_3_4b.safetensors", "type": "zimage"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": SCENE}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": ""}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {
            "width": 1024, "height": 1024, "batch_size": 1}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {
            "model": ["z:lora0", 0], "shift": 3.0}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["7", 0], "seed": 424242, "steps": 8, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "positive": ["4", 0], "negative": ["5", 0],
            "latent_image": ["6", 0], "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {
            "samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {
            "images": ["9", 0], "filename_prefix": "pixal_dm/a_red_barn"}},
        "z:lora0": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "lora_name": lora_name, "strength_model": 0.8, "model": ["1", 0]}},
    }
    graph.update(extra_nodes or {})
    return graph


def from_graph(graph, filename="pixal_roundtrip.png"):
    data = png_bytes({"prompt": json.dumps(graph)})
    patches = patched_catalogs()
    with patches[0], patches[1], patches[2], patches[3]:
        return server.style_from_render_metadata(data, filename)


class RoundTripTests(unittest.TestCase):

    def test_a_pixal_shaped_graph_maps_every_field(self):
        result = from_graph(pixal_zimage_graph())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["source"], "comfy_prompt")
        self.assertEqual(result["scene"], SCENE)
        self.assertEqual(result["unmapped"], [])

        style = result["style"]
        self.assertEqual(style["base"], "zimage")
        self.assertEqual(style["model"], MODEL_REL)
        self.assertEqual(style["name"], "Pixal Roundtrip")
        self.assertEqual(style["id"], "pixal_roundtrip")
        self.assertEqual(style["tuning"], {
            "steps": 8, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple"})
        self.assertNotIn("eta", style["tuning"])
        self.assertEqual(style["aspect"], "1:1 (Square)")
        self.assertEqual(style["mp"], 1.0)
        plan = style["lora_plan"]
        self.assertEqual(plan["recipe"], "zimage")
        self.assertEqual(plan["entries"], [
            {"name": LORA_REL, "strength": 0.8, "enabled": True}])
        self.assertEqual(style["provenance"]["seed"], 424242)
        self.assertIn("pixal_roundtrip.png", style["provenance"]["note"])
        for key in ("model", "steps", "cfg", "sampler_name", "scheduler",
                    "loras", "size"):
            self.assertIn(key, result["mapped"])

    def test_the_draft_is_a_valid_save_shape(self):
        style = from_graph(pixal_zimage_graph())["style"]
        record = server.validate_saved_style(style)
        self.assertEqual(record["id"], "pixal_roundtrip")
        self.assertEqual(record["lora_plan"]["entries"][0]["name"], LORA_REL)


class HonestyTests(unittest.TestCase):

    def test_unknown_node_and_uninstalled_lora_are_named_not_dropped(self):
        graph = pixal_zimage_graph(
            lora_name="foo.safetensors",
            extra_nodes={"12": {"class_type": "FreeU_V2", "inputs": {
                "model": ["1", 0], "b1": 1.1, "b2": 1.2}}})
        result = from_graph(graph)
        self.assertTrue(result["ok"], result)
        style = result["style"]
        self.assertEqual(style["tuning"]["steps"], 8)
        self.assertEqual(style["model"], MODEL_REL)
        whats = {entry["what"]: entry["why"] for entry in result["unmapped"]}
        self.assertEqual(whats.get("node 12 FreeU_V2"), "no Pixal equivalent")
        self.assertEqual(whats.get("foo.safetensors"), "not installed")
        self.assertNotIn("lora_plan", style)         # nothing matched to plan
        self.assertIn("unmapped: 2", style["provenance"]["note"])


class BaseHintTests(unittest.TestCase):
    """Base inference order: the graph's own node signatures before the
    default-model coincidence. An identity patch node exists only on an
    identity graph, so a Krea 2 render carrying one drafts an identity_edit
    style even though realism sorts first for the family."""

    def test_an_identity_patch_node_means_identity_edit(self):
        graph = {
            "1": {"class_type": "UNETLoader", "inputs": {
                "unet_name": KREA_REL, "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {
                "clip_name": "clip.safetensors", "type": "wan"}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {
                "clip": ["2", 0], "text": SCENE}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {
                "clip": ["2", 0], "text": ""}},
            "6": {"class_type": "EmptyLatentImage", "inputs": {
                "width": 1080, "height": 1920, "batch_size": 1}},
            "30:50": {"class_type": "Krea2EditModelPatch", "inputs": {
                "model": ["1", 0], "vectors": 2}},
            "30:51": {"class_type": "ClownsharKSampler_Beta", "inputs": {
                "model": ["30:50", 0], "seed": 7, "steps": 8, "cfg": 1.0,
                "sampler_name": "linear/euler", "scheduler": "simple",
                "eta": 0.5, "positive": ["4", 0], "negative": ["5", 0],
                "latent_image": ["6", 0], "denoise": 1.0}},
            "9": {"class_type": "VAEDecode", "inputs": {
                "samples": ["30:51", 0], "vae": ["3", 0]}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": "v.safetensors"}},
            "10": {"class_type": "SaveImage", "inputs": {
                "images": ["9", 0], "filename_prefix": "pixal_dm/x"}},
        }
        result = from_graph(graph, "zara_portrait_00001_.png")
        self.assertTrue(result["ok"], result)
        style = result["style"]
        self.assertEqual(style["base"], "identity_edit")
        self.assertEqual(style["model"], KREA_REL)
        self.assertEqual(style["tuning"], {
            "steps": 8, "cfg": 1.0, "sampler_name": "linear/euler",
            "scheduler": "simple", "eta": 0.5})
        self.assertEqual(style["aspect"], "9:16 (Portrait Widescreen)")
        self.assertEqual(result["scene"], SCENE)
        self.assertEqual(result["unmapped"], [])

    def h3_ref_graph(self, conditioning):
        """The h3_ref_still spine: node 6 is the reference conditioning node,
        and it carries the canvas the sampler renders."""
        return {
            "1": {"class_type": "UNETLoader", "inputs": {
                "unet_name": H3_REL, "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {
                "clip_name": "qwen3vl.safetensors", "type": "minimax"}},
            "3": {"class_type": "VAELoader", "inputs": {
                "vae_name": "minimax_h3_t1_image_vae.safetensors"}},
            "5": {"class_type": "LoadImage", "inputs": {
                "image": "pixal_exp_zara_g02.png"}},
            "6": {"class_type": conditioning, "inputs": {
                "width": 2304, "height": 3456, "prompt": SCENE,
                "ref_image_size": "match"}},
            "7": {"class_type": "KSamplerSelect", "inputs": {
                "sampler_name": "er_sde"}},
            "8": {"class_type": "BasicScheduler", "inputs": {
                "model": ["1", 0], "scheduler": "simple", "steps": 20,
                "denoise": 1.0}},
            "9": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0]}},
            "10": {"class_type": "RandomNoise", "inputs": {
                "noise_seed": 2058371946628501}},
            "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
                "noise": ["10", 0], "guider": ["9", 0], "sampler": ["7", 0],
                "sigmas": ["8", 0], "latent_image": ["6", 0]}},
            "12": {"class_type": "VAEDecode", "inputs": {
                "samples": ["11", 0], "vae": ["3", 0]}},
            "14": {"class_type": "SaveImage", "inputs": {
                "images": ["12", 0], "filename_prefix": "pixal_dm/x"}},
        }

    def test_the_reference_conditioning_node_means_h3_ref_still(self):
        # Both spellings: the lane emits the one-frame node when the pack and
        # the T1 image VAE are installed, MiniMaxH3ReferenceToVideo when not.
        # Before this the ref graph matched no signature at all and fell
        # through to the default-model coincidence, drafting h3_still - the
        # lane that wires NO reference, so the style rendered a stranger.
        for conditioning in (server.H3_ONE_FRAME_NODE,
                             "MiniMaxH3ReferenceToVideo"):
            with self.subTest(conditioning=conditioning):
                result = from_graph(self.h3_ref_graph(conditioning),
                                    "sf1_tailgate.png")
                self.assertTrue(result["ok"], result)
                style = result["style"]
                self.assertEqual(style["base"], "h3_ref_still")
                self.assertEqual(style["model"], H3_REL)
                self.assertEqual(style["tuning"], {
                    "steps": 20, "sampler_name": "er_sde",
                    "scheduler": "simple"})
                self.assertEqual(style["aspect"], "2:3 (Portrait Photo)")
                # 2304x3456 is the composer ladder's 8 MP rung at 2:3, which
                # only became reachable when the picture lane got its own cap.
                self.assertEqual(style["mp"], 8.0)
                # The recipe's own conditioning node is furniture, not a
                # third-party node the draft has to confess to.
                self.assertEqual(result["unmapped"], [])

    def test_the_refine_row_still_wins_over_the_single_pass_hint(self):
        graph = self.h3_ref_graph("MiniMaxH3ReferenceToVideo")
        graph["h3:up:param"] = {"class_type": "MMH3LatentUpscaleWithModelParams",
                                "inputs": {"scale": 2.0}}
        graph["h3:up:sample"] = {"class_type": "MMH3UltimateUpscale",
                                 "inputs": {"steps": 6, "denoise": 0.22}}
        result = from_graph(graph, "sf1_tailgate_2x.png")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["style"]["base"], "h3_ref_still_2x")


class A1111Tests(unittest.TestCase):

    def test_parameters_map_the_core_fields(self):
        parameters = (
            "a photograph of a red barn <lora:teststyle:0.8>\n"
            "Negative prompt: blurry, lowres\n"
            "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 1234, "
            "Size: 832x1216, Model: z_image_turbo_bf16, Model hash: abc123")
        data = png_bytes({"parameters": parameters})
        patches = patched_catalogs()
        with patches[0], patches[1], patches[2], patches[3]:
            result = server.style_from_render_metadata(data, "00001-1234.png")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["source"], "a1111")
        self.assertEqual(result["scene"], "a photograph of a red barn")

        style = result["style"]
        # The A1111 model title resolves by stem, the LoRA tag by stem too.
        self.assertEqual(style["model"], MODEL_REL)
        self.assertEqual(style["base"], "zimage")
        tuning = style["tuning"]
        self.assertEqual(tuning["steps"], 20)
        self.assertEqual(tuning["cfg"], 7.0)
        self.assertEqual(tuning["sampler_name"], "euler_ancestral")
        self.assertEqual(style["mp"], 1.0)
        self.assertEqual(style["aspect"], "2:3 (Portrait Photo)")
        self.assertEqual(style["lora_plan"]["entries"], [
            {"name": LORA_REL, "strength": 0.8, "enabled": True}])
        self.assertEqual(style["provenance"]["seed"], 1234)


class EndpointTests(unittest.TestCase):
    """POST /api/styles/from-image: the {"filename": ...} intake resolves a
    gallery render out of ComfyUI's output (or input), refuses traversal,
    and hands the bytes to the translator. Saving stays styles_post's job."""

    class FakeRequest:
        content_type = "application/json"

        def __init__(self, body):
            self.body = body

        async def json(self):
            return self.body

    def _post(self, body, root):
        patches = (patch.object(server, "CDIR", root),) + patched_catalogs()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            return asyncio.run(server.style_from_image(self.FakeRequest(body)))

    def test_a_gallery_render_drafts_a_style(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            out = root / "output" / "pixal_dm"
            out.mkdir(parents=True)
            (out / "render_00001.png").write_bytes(
                png_bytes({"prompt": json.dumps(pixal_zimage_graph())}))
            resp = self._post({"filename": "pixal_dm/render_00001.png"}, root)
        payload = json.loads(resp.body)
        self.assertEqual(resp.status, 200)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["style"]["base"], "zimage")
        self.assertEqual(payload["style"]["name"], "Render 00001")

    def test_a_missing_file_is_a_404(self):
        with TemporaryDirectory() as td:
            resp = self._post({"filename": "pixal_dm/gone.png"}, Path(td))
        self.assertEqual(resp.status, 404)

    def test_traversal_never_leaves_the_comfy_roots(self):
        with TemporaryDirectory() as td:
            resp = self._post({"filename": "../../server.py"}, Path(td))
        self.assertEqual(resp.status, 400)


class NoMetadataTests(unittest.TestCase):

    def test_a_chunk_free_png_says_so(self):
        result = server.style_from_render_metadata(png_bytes(), "plain.png")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no render metadata in this image")


class BadBytesTests(unittest.TestCase):

    def test_non_image_bytes_never_raise(self):
        result = server.style_from_render_metadata(b"this is not an image",
                                                   "notes.txt")
        self.assertFalse(result["ok"])

    def test_a_truncated_png_never_raises(self):
        data = png_bytes({"prompt": json.dumps(pixal_zimage_graph())})
        result = server.style_from_render_metadata(data[:20], "half.png")
        self.assertFalse(result["ok"])


CLIENT_TRANSPORT = (ROOT / "web" / "src" / "transport.js").read_text(encoding="utf-8")
CLIENT_COMPOSER = (ROOT / "web" / "src" / "components" / "Composer.jsx") \
    .read_text(encoding="utf-8")
CLIENT_CHAT = (ROOT / "web" / "src" / "components" / "Chat.jsx") \
    .read_text(encoding="utf-8")
CLIENT_FORM = (ROOT / "web" / "src" / "components" / "StyleForm.jsx") \
    .read_text(encoding="utf-8")


class ClientRoutingTests(unittest.TestCase):
    """Static, in the test_lora_card_controls.py style (this repo has no JS
    runner): the from-image intake is wired end to end - transport, composer
    affordance, chat's draft hand-off, and the form's draft handling."""

    def test_the_transport_posts_multipart_to_the_endpoint(self):
        self.assertRegex(
            CLIENT_TRANSPORT,
            r"styleFromImage\s*=\s*async \(file\)[\s\S]{0,300}?"
            r'fetch\("/api/styles/from-image"[\s\S]{0,120}?body: fd',
            "transport.js lost the /api/styles/from-image post")

    def test_the_composer_has_one_from_image_affordance(self):
        self.assertIn("from image", CLIENT_COMPOSER)
        self.assertIn("reads ComfyUI metadata", CLIENT_COMPOSER)
        self.assertRegex(CLIENT_COMPOSER, r"styleImageRef = useRef",
                         "the hidden intake input is gone")
        self.assertRegex(
            CLIENT_COMPOSER,
            r"doStyleFromImage[\s\S]{0,600}?onStyleFromImage && onStyleFromImage\(r\)",
            "a successful read no longer reaches Chat's handler")
        self.assertRegex(CLIENT_COMPOSER, r"styleImageError",
                         "a no-metadata answer has nowhere to be shown")

    def test_chat_opens_the_draft_in_the_style_editor(self):
        self.assertRegex(
            CLIENT_CHAT,
            r"onStyleFromImage=\{\(r\) => \{[\s\S]{0,300}?setStyleDraft\(\{ "
            r"\.\.\.\(r\.style \|\| \{\}\)[\s\S]{0,300}?setStyleFormOpen\(true\)",
            "Chat no longer turns the answer into an open draft")
        self.assertRegex(CLIENT_CHAT, r"fromImage: \{ unmapped",
                         "the unmapped ledger no longer rides the draft")

    def test_the_form_keeps_what_the_draft_pins(self):
        self.assertRegex(CLIENT_FORM, r"draft\?\.model;\s*\n?\s*return seeded",
                         "an uninstalled draft model would be silently swapped")
        self.assertRegex(CLIENT_FORM, r"draft\?\.aspect\) \|\| opts\?\.aspect",
                         "the draft's canvas no longer beats the composer's")
        self.assertRegex(CLIENT_FORM, r"draft\?\.provenance \? \{ provenance",
                         "the translator's provenance note is dropped on save")
        self.assertIn("Not mapped: ", CLIENT_FORM)


if __name__ == "__main__":
    unittest.main()
