"""Brief 9.94 — the H3 text encoder becomes a VRAM setting.

H3_CLIP (the 14.6 GB 32B Qwen3-VL encoder) was a module constant wired into
every H3 graph through a plain CLIPLoader, while the installed 4B/8B encoders
and their mmh3 ClipProj projections sat unreferenced. The fix follows 9.91's
shape: config grows h3.text_encoder ("" = Automatic, the 32B, exactly as
today), one resolver (h3_text_encoder_choice) answers which encoder and
projection an H3 graph uses, every H3 lane consults it through
_h3_asset_paths, and a pick swaps node 2 to ClipProjLoader. A pick is only
offerable when BOTH its files resolve in the catalog; a stale pick or a
probed-absent ClipProjLoader node degrades to the stock CLIPLoader.

What these tests pin:

  ConfigShape     - the h3 block grows text_encoder: "" with backfill and
                    round-trip, through a temp-dir config.
  AutomaticPin    - (accept 1) the safety property: every H3 lane's graph
                    under Automatic equals the fixture captured from the
                    pre-change code (briefs/9.94-capture.py ->
                    tests/fixtures/h3_automatic_encoder_graphs.json), under
                    BOTH a config that names "" and an old config with no
                    text_encoder key at all.
  Swap            - (accept 2) a set encoder swaps node 2 to ClipProjLoader
                    with the right clip_name and projection on every lane,
                    and every other node is unchanged.
  Offerability    - (accept 3) an option is offered only when its encoder
                    AND its projection both resolve; POST refuses an
                    unofferable or unknown pick and clears on "".
  Stale           - (accept 4) a pick whose files left the catalog degrades
                    to Automatic, never raises, and the payload says stale.
  NodeAbsence     - (accept 5) a probed ComfyUI without the ClipProjLoader
                    node NAME degrades the graph to the stock CLIPLoader.
  OneResolver     - (accept 6) structural: patch the one resolver and every
                    lane's graph reflects the mocked answer - no lane grows
                    a second answer.
  OptionsPayload  - the options loop's missing check reads the same
                    resolver: with a small-encoder pick the 32B is not
                    required (it may be deleted); unset, the 32B is.

Same sanctioned simulation as every sibling file: stubbed catalog, stubbed
character, temp-dir configs, no generation, no ComfyUI, no GPU.
"""

import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_h3_text_encoder",
                                ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures"
                      / "h3_automatic_encoder_graphs.json").read_text(
                          encoding="utf-8"))

STOCK = server.H3_MODEL
REF2VA = server.H3_REF2V_MODEL
UPSCALER = server.H3_LATENT_UPSCALER
CLIP_32B = server.H3_CLIP

# The files on Jesse's disk, spelled as the catalog reports them. The 4B
# carries two projections and the 8B one - three (encoder, projection)
# pairs, and picking a winner between them is Jesse's render question,
# not this brief's.
ENC_4B = "Qwen\\qwen3vl_4b_int8_convrot_learned.safetensors"
ENC_8B = "Qwen\\qwen3vl_8b_nvfp4.safetensors"
PROJ_4B = "mmh3-4b-ClipProj-v3.1.safetensors"
PROJ_4B_MLP = "mmh3-4b-ClipProj-v3.1-mlp.safetensors"
PROJ_8B_MLP = "mmh3-8b-ClipProj-v3.1-mlp.safetensors"
PICK_4B = "qwen3vl_4b"
PICK_4B_MLP = "qwen3vl_4b_mlp"
PICK_8B_MLP = "qwen3vl_8b_mlp"

CHARACTER = {"id": "mia", "name": "Mia", "age": 24, "race": "Korean",
             "sex": "female", "style": "silver pixie cut, lean runner's build",
             "identity_ref": "mia.png"}

STILL_LANES = ("h3_still", "h3_still_2x", "h3_ref_still", "h3_ref_still_2x")
VIDEO_LANES = ("h3_i2v", "h3_multishot", "h3_ref2v")
ALL_LANES = STILL_LANES + VIDEO_LANES

# The swap the brief specifies: CLIPLoader's inputs plus the projection,
# the node's own device/mode fixed and never surfaced.
#
# type is "auto", not "minimax". Shipped as "minimax" in 1.1.4b, which
# refused every option the table offers - Jesse hit it on both the 8B and
# the 4B: "is a 4B, but the type is set to minimax. Set it to auto, or to
# krea2." auto reads the checkpoint header, which is what the node's own
# tooltip says to do.
#
# mode is "streaming", not "resident". Same encode speed, but the encoder
# folds back to RAM instead of holding 5-6 GB while the 20 GB DiT samples -
# on a 32 GB card resident makes the DiT page its own weights, which is the
# failure this whole encoder row exists to avoid.
SWAP_4B = {"class_type": "ClipProjLoader",
           "inputs": {"clip_name": ENC_4B, "type": "auto",
                      "projection": PROJ_4B, "device": "cuda:0",
                      "mode": "streaming"}}


def add(root, kind, rel, size=1):
    return {"rel": rel, "kind": kind, "root": str(root), "size": size,
            "mtime": 0.0}


def h3_entries(root, encoders=(), projections=(), upscale=True,
               image_vae=True, clip32=True):
    """The shared H3 stack plus, optionally, the small-encoder files."""
    entries = [add(root, "diffusion_models", STOCK),
               add(root, "diffusion_models", REF2VA),
               add(root, "vae", server.H3_VIDEO_VAE),
               add(root, "vae", server.H3_AUDIO_VAE)]
    if clip32:
        entries.append(add(root, "text_encoders", CLIP_32B, 14600))
    for rel in encoders:
        entries.append(add(root, "text_encoders", rel, 4900))
    for rel in projections:
        entries.append(add(root, "clip_projections", rel, 200))
    if image_vae:
        entries.append(add(root, "vae", server.H3_IMAGE_VAE))
    if upscale:
        entries.append(add(root, "latent_upscale_models", UPSCALER, 659))
    return entries


def stub_catalog(entries):
    return lambda kind=None: [e for e in entries if kind in (None, e["kind"])]


def no_disk():
    return (patch.object(server, "adjacent_metadata", return_value={}),
            patch.object(server, "model_roots", return_value=[]))


def cfg_with(h3=None):
    return {"h3": h3 if h3 is not None else
            {"ref_model": "", "fl_model": "", "text_encoder": ""},
            "extra_model_roots": []}


def full_cfg(h3=None):
    """The settings endpoint's whole-config stand-in, the edit tests' shape."""
    return {"llm": {"base_url": "", "model": ""},
            "critic": {"model": ""}, "upscale": {}, "edit": {}, "vae": {},
            "pid": {}, "video": {"default_engine": "", "default_model": ""},
            "h3": h3 if h3 is not None else
            {"ref_model": "", "fl_model": "", "text_encoder": ""},
            "extra_model_roots": [], "comfy_editor": False,
            "comfy_console": "tui", "explicit": "auto", "vram_profile": "auto"}


class FakeRequest:
    """The aiohttp stand-in every settings_post test file keeps local."""
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def build_still_lane(lane):
    if lane == "h3_still":
        return server.build_h3_still("A red barn at dusk", 424242)
    if lane == "h3_still_2x":
        return server.build_h3_still_2x("A red barn at dusk", 424242)
    if lane == "h3_ref_still":
        return server.build_h3_ref_still("A red barn at dusk", 424242,
                                         character="mia")
    return server.build_h3_ref_still_2x("A red barn at dusk", 424242,
                                        character="mia")


def build_video_lane(lane):
    if lane == "h3_i2v":
        return server.build_h3_i2v("She turns.", 1, "prepared.png",
                                   seconds=5, width=1344, height=768)
    if lane == "h3_multishot":
        return server.build_h3_multishot("One.\n---\nTwo.", 1, "prepared.png",
                                         seconds=5, width=1344, height=768)
    return server.build_h3_ref2v("She browses the shelf.", 1, ["ref0.png"],
                                 seconds=5, width=1344, height=768)


def build_lane(lane, entries, cfg, extra_patches=()):
    """One lane's graph under the harness that captured its fixture - the
    still harness for the still lanes, the 9.91 video harness for the
    Animate ones. The capture (briefs/9.94-capture.py) used the same
    parameters, so the fixture comparison is apples to apples."""
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        (root / "input" / CHARACTER["identity_ref"]).write_bytes(b"reference")
        (root / "input" / "prepared.png").write_bytes(b"prepared")
        (root / "input" / "ref0.png").write_bytes(b"ref")
        sidecar, roots = no_disk()
        patches = [sidecar, roots,
                   patch.object(server, "CDIR", root),
                   patch.object(server, "CHARACTERS",
                                {CHARACTER["id"]: CHARACTER}),
                   patch.object(server, "load_config", return_value=cfg),
                   patch.object(server, "model_catalog",
                                side_effect=stub_catalog(entries)),
                   *extra_patches]
        if lane in VIDEO_LANES:
            patches.append(patch.object(server, "_video_asset",
                                        side_effect=lambda kind, rel: rel))
        for p in patches:
            p.start()
        try:
            if lane in VIDEO_LANES:
                return build_video_lane(lane)
            return build_still_lane(lane)
        finally:
            for p in patches:
                p.stop()


def without_clip_node(graph):
    return {nid: node for nid, node in graph.items() if nid != "2"}


class ConfigShapeTests(unittest.TestCase):
    """The h3 block grows one key: text_encoder, default "" (Automatic)."""

    def test_the_defaults_carry_an_empty_encoder_pick(self):
        with TemporaryDirectory() as td:
            with patch.object(server, "CONFIG", Path(td) / "config.json"):
                self.assertEqual(server.load_config()["h3"],
                                 {"ref_model": "", "fl_model": "",
                                  "text_encoder": ""})

    def test_an_old_config_without_the_key_backfills(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps(
                {"h3": {"ref_model": REF2VA, "fl_model": STOCK}}),
                encoding="utf-8")
            with patch.object(server, "CONFIG", path):
                cfg = server.load_config()
        self.assertEqual(cfg["h3"]["text_encoder"], "")
        self.assertEqual(cfg["h3"]["ref_model"], REF2VA)

    def test_a_saved_pick_round_trips(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps(
                {"h3": {"text_encoder": PICK_4B}}), encoding="utf-8")
            with patch.object(server, "CONFIG", path):
                cfg = server.load_config()
        self.assertEqual(cfg["h3"]["text_encoder"], PICK_4B)


class AutomaticPinTests(unittest.TestCase):
    """Accept 1: Automatic is byte-identical to d0b3117 on every H3 lane.

    The fixture was captured from the pre-change builders
    (briefs/9.94-capture.py). Two config shapes: an explicit "" pick and
    an old config whose h3 block never grew the key - both must render
    the fixture, or an upgraded install changed what it renders."""

    CFG_SHAPES = ({"ref_model": "", "fl_model": "", "text_encoder": ""},
                  {"ref_model": "", "fl_model": ""})     # the pre-9.94 block

    def test_every_lane_matches_the_fixture(self):
        for lane in ALL_LANES:
            for h3 in self.CFG_SHAPES:
                with self.subTest(lane=lane, h3=h3):
                    with TemporaryDirectory() as td:
                        entries = h3_entries(Path(td))
                        g, _a, _b = build_lane(lane, entries, cfg_with(h3))
                    self.assertEqual(g, FIXTURE[lane])


class SwapTests(unittest.TestCase):
    """Accept 2: a set encoder swaps the node - ClipProjLoader with the
    right clip_name and projection - and every other node is unchanged."""

    def test_every_lane_swaps_node_2_and_nothing_else(self):
        cfg = cfg_with({"ref_model": "", "fl_model": "",
                        "text_encoder": PICK_4B})
        for lane in ALL_LANES:
            with self.subTest(lane=lane):
                with TemporaryDirectory() as td:
                    entries = h3_entries(Path(td), encoders=(ENC_4B,),
                                         projections=(PROJ_4B,))
                    g, _a, _b = build_lane(lane, entries, cfg)
                self.assertEqual(g["2"], SWAP_4B)
                self.assertEqual(without_clip_node(g),
                                 without_clip_node(FIXTURE[lane]))

    def test_the_ledger_info_names_the_encoder_that_loaded(self):
        cfg = cfg_with({"ref_model": "", "fl_model": "",
                        "text_encoder": PICK_8B_MLP})
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td), encoders=(ENC_8B,),
                                 projections=(PROJ_8B_MLP,))
            _g, _cap, info = build_lane("h3_still", entries, cfg)
        self.assertEqual(info["text_encoder"], "qwen3vl_8b_nvfp4")


class OfferabilityTests(unittest.TestCase):
    """Accept 3: an option is offered only when BOTH its files resolve -
    encoder present but projection missing, and the reverse, both leave
    it unofferable. POST refuses what the row could not offer."""

    def get_h3(self, entries, cfg):
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()):
            response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        return json.loads(response.text)["h3"]

    def post_h3(self, entries, cfg, body, saved):
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)), \
             patch.object(server, "save_config",
                          side_effect=lambda c: saved.append(c)):
            return asyncio.run(server.settings_post(FakeRequest(body)))

    def test_every_pair_with_both_files_is_offered(self):
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td),
                                 encoders=(ENC_4B, ENC_8B),
                                 projections=(PROJ_4B, PROJ_4B_MLP,
                                              PROJ_8B_MLP))
            h3 = self.get_h3(entries, full_cfg())
        offered = {o["id"] for o in h3["encoder"]["options"]}
        self.assertEqual(offered, {PICK_4B, PICK_4B_MLP, PICK_8B_MLP})
        # the row is a VRAM control: every option says what it weighs
        sizes = {o["id"]: o["size"] for o in h3["encoder"]["options"]}
        self.assertEqual(sizes[PICK_4B], 4900)

    def test_an_encoder_without_its_projection_is_not_offered(self):
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td), encoders=(ENC_4B,),
                                 projections=(PROJ_8B_MLP,))
            h3 = self.get_h3(entries, full_cfg())
        self.assertEqual(h3["encoder"]["options"], [])

    def test_a_projection_without_its_encoder_is_not_offered(self):
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td), projections=(PROJ_4B, PROJ_4B_MLP))
            h3 = self.get_h3(entries, full_cfg())
        self.assertEqual(h3["encoder"]["options"], [])

    def test_automatic_names_the_32b_and_its_weight(self):
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td))
            h3 = self.get_h3(entries, full_cfg())
        self.assertEqual(h3["text_encoder"], "")
        self.assertFalse(h3["encoder"]["stale"])
        self.assertEqual(h3["encoder"]["resolved"]["id"], "")
        self.assertEqual(h3["encoder"]["resolved"]["size"], 14600)
        self.assertEqual(h3["encoder"]["automatic"]["size"], 14600)

    def test_an_offerable_pick_posts_and_saves(self):
        saved = []
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td), encoders=(ENC_4B,),
                                 projections=(PROJ_4B,))
            response = self.post_h3(entries, full_cfg(),
                                    {"h3": {"text_encoder": PICK_4B}}, saved)
        self.assertEqual(response.status, 200)
        self.assertEqual(saved[0]["h3"]["text_encoder"], PICK_4B)

    def test_an_unofferable_pick_is_refused_by_name(self):
        saved = []
        with TemporaryDirectory() as td:
            # encoder on disk, projection gone - the row could not offer it
            entries = h3_entries(Path(td), encoders=(ENC_4B,))
            response = self.post_h3(entries, full_cfg(),
                                    {"h3": {"text_encoder": PICK_4B}}, saved)
        self.assertEqual(response.status, 400)
        self.assertIn(PICK_4B, json.loads(response.text)["error"])
        self.assertEqual(saved, [])     # a rejected write never touches config

    def test_an_unknown_pick_is_refused(self):
        saved = []
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td))
            response = self.post_h3(entries, full_cfg(),
                                    {"h3": {"text_encoder": "qwen3vl_2b"}},
                                    saved)
        self.assertEqual(response.status, 400)
        self.assertEqual(saved, [])

    def test_an_empty_pick_clears_back_to_automatic(self):
        saved = []
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td))
            response = self.post_h3(
                entries,
                full_cfg({"ref_model": "", "fl_model": "",
                          "text_encoder": PICK_4B}),
                {"h3": {"text_encoder": ""}}, saved)
        self.assertEqual(response.status, 200)
        self.assertEqual(saved[0]["h3"]["text_encoder"], "")


class StaleTests(unittest.TestCase):
    """Accept 4: a pick whose file left the catalog degrades to Automatic
    rather than raising, and says so in the payload - 9.91's behaviour."""

    def test_the_render_degrades_to_the_fixture_graph(self):
        cfg = cfg_with({"ref_model": "", "fl_model": "",
                        "text_encoder": PICK_4B})
        with TemporaryDirectory() as td:
            # the projection is gone: the pick cannot resolve
            entries = h3_entries(Path(td), encoders=(ENC_4B,))
            g, _a, _b = build_lane("h3_still", entries, cfg)
        self.assertEqual(g, FIXTURE["h3_still"])

    def test_the_payload_reports_stale_and_keeps_the_pick(self):
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td), encoders=(ENC_4B,))
            h3 = OfferabilityTests.get_h3(
                self, entries,
                full_cfg({"ref_model": "", "fl_model": "",
                          "text_encoder": PICK_4B}))
        self.assertEqual(h3["text_encoder"], PICK_4B)   # the pick survives
        self.assertTrue(h3["encoder"]["stale"])
        # and the render answer is Automatic's
        self.assertEqual(h3["encoder"]["resolved"]["id"], "")

    def test_the_pick_revives_when_the_file_returns(self):
        cfg = cfg_with({"ref_model": "", "fl_model": "",
                        "text_encoder": PICK_4B})
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td), encoders=(ENC_4B,),
                                 projections=(PROJ_4B,))
            g, _a, _b = build_lane("h3_still", entries, cfg)
        self.assertEqual(g["2"], SWAP_4B)


class NodeAbsenceTests(unittest.TestCase):
    """Accept 5: a probed ComfyUI without the ClipProjLoader node name
    degrades the graph to the stock CLIPLoader - probed BY NAME, never
    by pack (comfyui_fearnworksnodes' `from nodes import *` makes
    /object_info mislabel other packs' nodes)."""

    PROBED_WITHOUT = frozenset({"CLIPLoader", "UNETLoader", "VAELoader"})

    def test_a_set_pick_degrades_when_the_node_is_absent(self):
        cfg = cfg_with({"ref_model": "", "fl_model": "",
                        "text_encoder": PICK_4B})
        for lane in ("h3_still", "h3_i2v"):
            with self.subTest(lane=lane):
                with TemporaryDirectory() as td:
                    entries = h3_entries(Path(td), encoders=(ENC_4B,),
                                         projections=(PROJ_4B,))
                    g, _a, _b = build_lane(
                        lane, entries, cfg,
                        extra_patches=(patch.dict(
                            server._COMFY_NODES,
                            {"names": self.PROBED_WITHOUT}),))
                self.assertEqual(g["2"], FIXTURE[lane]["2"])
                self.assertEqual(g["2"]["class_type"], "CLIPLoader")


class OneResolverTests(unittest.TestCase):
    """Accept 6: every H3 lane consults the one resolver. Mock it and every
    lane's graph must reflect the mocked answer - a lane that grew its own
    answer would ignore the mock and fail here."""

    def test_every_lane_reads_h3_text_encoder_choice(self):
        mocked = Mock(return_value={
            "id": PICK_4B, "label": "Qwen3-VL 4B + ClipProj",
            "clip": ENC_4B, "projection": PROJ_4B})
        for lane in ALL_LANES:
            with self.subTest(lane=lane):
                with TemporaryDirectory() as td:
                    entries = h3_entries(Path(td))
                    with patch.object(server, "h3_text_encoder_choice",
                                      mocked):
                        g, _a, _b = build_lane(lane, entries, cfg_with())
                self.assertTrue(mocked.called)
                self.assertEqual(g["2"], SWAP_4B)
                mocked.reset_mock()


class OptionsPayloadTests(unittest.TestCase):
    """The options loop's missing check reads the same resolver - no second
    answer. A set small-encoder pick means the 32B is not required (the
    whole point of the setting: it may be deleted); unset, the 32B is."""

    def hub_options(self, entries, cfg):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            sidecar, roots = no_disk()
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "load_config", return_value=cfg), \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)), \
                 sidecar, roots, \
                 patch.object(server, "lm_enrich"), \
                 patch.object(server, "_LORA_TITLE_CACHE",
                              root / "titles.json"):
                return server.Hub().options()

    def test_a_set_pick_frees_the_32b_requirement(self):
        cfg = cfg_with({"ref_model": "", "fl_model": "",
                        "text_encoder": PICK_4B})
        with TemporaryDirectory() as td:
            # the 32B is DELETED, the 4B pair is installed
            entries = h3_entries(Path(td), encoders=(ENC_4B,),
                                 projections=(PROJ_4B,), clip32=False)
            rows = {r["id"]: r
                    for r in self.hub_options(entries, cfg)["recipes"]}
        self.assertEqual(rows["h3_still"]["missing"], [])
        self.assertTrue(rows["h3_still"]["available"])

    def test_unset_still_requires_the_32b(self):
        with TemporaryDirectory() as td:
            entries = h3_entries(Path(td), clip32=False)
            rows = {r["id"]: r
                    for r in self.hub_options(entries, cfg_with())["recipes"]}
        self.assertIn("text encoder: " + CLIP_32B,
                      rows["h3_still"]["missing"])
        self.assertFalse(rows["h3_still"]["available"])


if __name__ == "__main__":
    unittest.main()
