import asyncio
import json
import re
import os
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from PIL import Image


_SPEC = spec_from_file_location(
    "pixal_server_video", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def all_video_assets(_kind, _rel):
    return _rel


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class MiniMaxH3Tests(unittest.TestCase):
    def test_h3_durations_use_the_17k_plus_5_grid(self):
        self.assertEqual([server.h3_frame_count(s) for s in (5, 10, 15)],
                         [124, 243, 362])
        for bad in (3, 8, 12, 15.5, "long"):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                    ValueError, "5, 10, or 15"):
                server.h3_frame_count(bad)

    def test_adaptive_canvas_matches_the_proven_h3_tool(self):
        self.assertEqual(server.h3_adapt_canvas(1920, 1080), (1344, 768))
        self.assertEqual(server.h3_adapt_canvas(1080, 1920), (768, 1344))
        self.assertEqual(server.h3_adapt_canvas(1024, 1024), (768, 768))

    def test_no_canvas_exceeds_the_pixel_cap(self):
        """The cap was applied BEFORE rounding each edge up to the 32 grid, so
        rounding put the canvas back over it - a 9:19.5 phone frame landed 2.6%
        above, an ultrawide 2.1%, 96 of 239 possible canvases in total."""
        canvases = set()
        for width in range(256, 4097, 16):
            for height in range(256, 4097, 16):
                canvases.add(server.h3_adapt_canvas(width, height))
        oversized = [c for c in canvases if c[0] * c[1] > server.H3_MAX_PIXELS]
        self.assertEqual(oversized, [], f"over the pixel cap: {sorted(oversized)}")
        misaligned = [c for c in canvases
                      if c[0] % server.H3_CANVAS_MULTIPLE
                      or c[1] % server.H3_CANVAS_MULTIPLE]
        self.assertEqual(misaligned, [], f"off the 32 grid: {sorted(misaligned)}")
        # the shapes that actually come out of Pixal must be untouched by the fix
        self.assertEqual(server.h3_adapt_canvas(832, 1248), (768, 1152))
        self.assertEqual(server.h3_adapt_canvas(1179, 2556), (704, 1440))

    def test_prepare_h3_frame_is_exact_canvas_and_content_addressed(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            source = root / "source.png"
            Image.new("RGB", (640, 360), (25, 80, 140)).save(source)
            with patch.object(server, "CDIR", root):
                first = server.prepare_h3_frame(source)
                second = server.prepare_h3_frame(source)
            self.assertEqual(first, second)
            name, width, height = first
            self.assertTrue(name.startswith("pixal_h3_"))
            self.assertEqual((width, height), (1344, 768))
            with Image.open(root / "input" / name) as staged:
                self.assertEqual(staged.size, (1344, 768))

    def test_video_options_are_separate_and_data_driven(self):
        with patch.object(server, "_video_asset", side_effect=all_video_assets):
            engines = server.video_engine_options()
        # 2.3 left the picker 2026-08-12: two chips, and 2.5 is the LTX.
        self.assertEqual([engine["id"] for engine in engines], ["ltx25", "h3"])
        ltx25 = engines[0]
        # The 2.5 graph computes frames as fps*seconds+1 internally, so the
        # engine deliberately exposes no frame-rate control.
        self.assertNotIn("fps_choices", ltx25)
        self.assertEqual([model["id"] for model in ltx25["models"]], ["default"])
        self.assertTrue(ltx25["available"])
        self.assertIn("audio", ltx25["tag"])
        h3 = engines[1]
        self.assertEqual([item["s"] for item in h3["lengths"]], [5, 10, 15])
        # Brief 9.12: both stock lanes are chips now - the chip IS the lane
        # switch. Stock first, finetunes after.
        self.assertEqual([model["id"] for model in h3["models"]], ["fl2va", "ref2va"])
        self.assertTrue(h3["available"])
        # Both engines generate audio, so neither chip may imply it is the only
        # one that does - LTX has its own audio VAE in the graph.
        self.assertIn("audio", h3["tag"])
        self.assertIn("audio", engines[0]["tag"])
        self.assertNotIn("native audio", h3["tag"])
        loras = h3["models"][0]["loras"]
        self.assertEqual([item["name"] for item in loras], [server.H3_HMNSFW_LORA])
        self.assertEqual(loras[0]["trigger"], "hmmotion")
        self.assertEqual(loras[0]["default_strength"], 1.0)
        self.assertFalse(loras[0]["active_by_default"])
        self.assertTrue(loras[0]["available"])

        # 9.58: fl2va builds joined the still picker via h3_still, under their
        # own family - media stays "video", and the Animate lanes never read
        # either flag (they resolve builds by catalog rel, proven unchanged by
        # the chip assertions above).
        with patch.object(server, "adjacent_metadata", return_value={}):
            profile = server.model_profile(server.H3_MODEL)
        self.assertEqual(profile["family"], "minimax_h3")
        self.assertEqual(profile["media"], "video")
        self.assertTrue(profile["supported"])
        # The ref2va chip is real now (9.12), but the LoRA fence holds:
        # HMNSFW's own description says FL2VA, so the ref2va chip lists none.
        ref2va = next(m for m in h3["models"] if m["id"] == "ref2va")
        self.assertEqual(ref2va["loras"], [])
        self.assertTrue(server.video_lora_profile(server.H3_HMNSFW_LORA)["supported"])
        self.assertEqual(
            server.video_lora_profile(server.H3_HMNSFW_LORA)["variants"], ["fl2va"])
        self.assertFalse(server.video_lora_profile("some-folder\\unknown.safetensors")
                         ["supported"])

    def test_video_selection_rejects_cross_engine_models_and_lengths(self):
        with patch.object(server, "_video_asset", side_effect=all_video_assets):
            self.assertEqual(server.validate_video_selection("h3", "fl2va", 10),
                             ("h3", "fl2va", 10, None))
            with self.assertRaisesRegex(ValueError, "does not have model"):
                server.validate_video_selection("h3", "eros", 10)
            with self.assertRaisesRegex(ValueError, "length must be one of"):
                server.validate_video_selection("h3", "fl2va", 8)
            with self.assertRaisesRegex(ValueError, "unknown video engine"):
                server.validate_video_selection("wan", "default", 5)
            # "ltx" aliases to 2.5 now, whose 24fps is fixed - a requested
            # frame rate is ignored rather than validated.
            self.assertEqual(server.validate_video_selection("ltx", None, 15, 24),
                             ("ltx25", "default", 15, None))
            self.assertEqual(server.validate_video_selection(None, None, 5)[0],
                             "ltx25")
            self.assertIsNone(server.validate_video_selection("h3", "fl2va", 10, 24)[3])

    def test_ltx_clip_length_uses_the_graphs_own_frame_rate(self):
        """The muxer and the audio latent both read node 285, so seconds must be
        converted at that rate. Converting at a hardcoded 24 against a graph
        shipping 30 made every clip a fifth short - an "8s" request measured
        6.43s on disk."""
        with patch.object(server, "_video_asset", side_effect=all_video_assets):
            graph, _m, info = server.build_ltx_i2v("she turns", 1, "a.png", seconds=8)
            frames = graph["108"]["inputs"]["length"]
            rate = float(graph["285"]["inputs"]["value"])
            self.assertEqual(graph["199"]["inputs"]["frames_number"], frames)
            self.assertAlmostEqual(frames / rate, 8, delta=0.2)
            self.assertIn(f"{rate:g}fps", info["size"])
            # picking a rate re-derives the frame count rather than just relabelling
            slow, _m2, _i2 = server.build_ltx_i2v("she turns", 1, "a.png",
                                                  seconds=8, fps=24)
            self.assertEqual(float(slow["285"]["inputs"]["value"]), 24)
            self.assertLess(slow["108"]["inputs"]["length"], frames)
            self.assertAlmostEqual(slow["108"]["inputs"]["length"] / 24, 8, delta=0.2)

    def test_video_lora_plan_is_h3_fl2va_only_and_rejects_bad_rows(self):
        plan = {"version": 1, "mode": "replace", "engine": "h3", "model": "fl2va",
                "entries": [{"name": server.H3_HMNSFW_LORA,
                             "strength": 0.85, "enabled": True}]}
        with patch.object(server, "_video_asset", side_effect=all_video_assets):
            self.assertIs(server.validate_video_lora_plan("h3", "fl2va", plan), plan)
            with self.assertRaisesRegex(ValueError, "only supported"):
                server.validate_video_lora_plan("ltx", "default", plan)
            with self.assertRaisesRegex(ValueError, "not compatible"):
                server.validate_video_lora_plan("h3", "fl2va", {
                    **plan, "entries": [{"name": "Krea 2\\still.safetensors"}]})
            with self.assertRaisesRegex(ValueError, "duplicate"):
                server.validate_video_lora_plan("h3", "fl2va", {
                    **plan, "entries": plan["entries"] * 2})
            with self.assertRaisesRegex(ValueError, "enabled must be boolean"):
                server.validate_video_lora_plan("h3", "fl2va", {
                    **plan, "entries": [{"name": server.H3_HMNSFW_LORA,
                                         "enabled": "yes"}]})

    def test_h3_builder_is_the_verified_native_fl2va_graph(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                # sparse=False: this is the official FL2VA graph, node for
                # node. The optional accelerator that rides on top of it has
                # its own contract in MiniMaxH3SparseAttentionTests.
                graph, brief, info = server.build_h3_i2v(
                    "She turns toward the window.", 987, "prepared.png",
                    seconds=10, width=768, height=1344, model="fl2va",
                    sparse=False)

        self.assertEqual(graph["1"]["inputs"]["unet_name"], server.H3_MODEL)
        self.assertEqual(graph["2"]["inputs"], {
            "clip_name": server.H3_CLIP, "type": "minimax", "device": "default"})
        self.assertEqual(graph["3"]["inputs"]["vae_name"], server.H3_VIDEO_VAE)
        self.assertEqual(graph["4"]["inputs"]["vae_name"], server.H3_AUDIO_VAE)
        self.assertEqual(graph["6"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(graph["6"]["inputs"]["length"], 243)
        self.assertEqual(graph["6"]["inputs"]["first_frame"], ["5", 0])
        self.assertEqual(graph["7"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(graph["8"]["inputs"], {
            "model": ["1", 0], "scheduler": "simple", "steps": 20, "denoise": 1.0})
        self.assertEqual(graph["9"]["class_type"], "BasicGuider")
        self.assertEqual(graph["14"]["class_type"], "VHS_VideoCombine")
        self.assertEqual(graph["14"]["inputs"]["audio"], ["13", 0])
        self.assertEqual(graph["14"]["inputs"]["crf"], 14)
        self.assertIn("do not invent speech", brief)
        self.assertEqual(info["model_family"], "minimax_h3")
        self.assertEqual(info["model_variant"], "fl2va")
        self.assertEqual(info["size"], "768x1344")
        self.assertEqual(info["frames"], 243)
        self.assertEqual(info["audio"], "native synchronized audio")
        self.assertEqual(info["loras"], [])
        self.assertEqual(info["lora_stack"], [])
        self.assertEqual(info["lora_triggers"], [])
        self.assertNotIn("hmmotion", brief.lower())
        for node_id, node in graph.items():
            for value in node.get("inputs", {}).values():
                if isinstance(value, list) and len(value) == 2 \
                        and isinstance(value[0], str):
                    self.assertIn(value[0], graph, f"{node_id} has bad link {value}")

    
    def test_the_video_lane_keeps_the_shared_default(self):
        """The guard 9.78 exists for: the STILL recipes moved to
        dpmpp_sde_gpu x beta on their own constants after a locked-seed
        stills A/B - a stills verdict must never re-tune a 5-10 s clip,
        so every video lane keeps res_multistep x simple."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset",
                              side_effect=all_video_assets):
                graph, _brief, _info = server.build_h3_i2v(
                    "She turns toward the window.", 987, "prepared.png",
                    seconds=10, width=768, height=1344, model="fl2va",
                    sparse=False)
        self.assertEqual(graph["7"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(graph["8"]["inputs"]["scheduler"], "simple")
        self.assertEqual(graph["8"]["inputs"]["steps"], 20)
        # The shared constants ARE the video default now; the still pair
        # lives beside them and must never move them.
        self.assertEqual((server.H3_SAMPLER, server.H3_SCHEDULER),
                         ("res_multistep", "simple"))
        self.assertEqual((server.H3_STILL_SAMPLER, server.H3_STILL_SCHEDULER),
                         ("dpmpp_sde_gpu", "beta"))
# Frozen from the installed pack's INPUT_TYPES and cross-checked live against
    # GET /object_info/H3MultishotSampler. The graph must supply every required
    # input and nothing else: a stray key is a queue-time rejection that would
    # otherwise only surface once the job reaches the GPU.
    MULTISHOT_REQUIRED = {
        "model", "clip", "video_vae", "audio_vae", "script", "shot_count",
        "width", "height", "frames_per_shot", "seed", "steps", "seed_per_shot"}
    # sampler_name/scheduler are declared optional on BOTH samplers and are
    # supplied because Turbo needs euler+beta rather than res_multistep+simple.
    MULTISHOT_OPTIONAL = {"start_image", "sampler_name", "scheduler"}
    # H3MultishotMemorySampler is a superset - same required set plus these two,
    # both REQUIRED there (checked live against GET /object_info). It drops
    # voice_ref from its optionals, which is why the plain node still exists.
    MULTISHOT_MEMORY_EXTRA = {"anchor_frames", "memory_frames"}

    def build_multishot(self, motion, **kw):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                kw.setdefault("width", 768)
                kw.setdefault("height", 1344)
                kw.setdefault("model", "fl2va")
                return server.build_h3_multishot(motion, 987, "prepared.png", **kw)

    def test_multishot_graph_supplies_exactly_the_nodes_inputs(self):
        self.assertIn("h3_multishot", server.BUILDERS)
        graph, _brief, _info = self.build_multishot("Shot one.\n---\nShot two.")
        node = graph["6"]
        self.assertEqual(node["class_type"], server.H3_MULTISHOT_MEMORY_NODE)
        self.assertEqual(set(node["inputs"]), self.MULTISHOT_REQUIRED
                         | self.MULTISHOT_MEMORY_EXTRA | self.MULTISHOT_OPTIONAL)
        self.assertEqual(node["inputs"]["start_image"], ["5", 0])
        self.assertEqual(node["inputs"]["seed_per_shot"], True)
        self.assertEqual(node["inputs"]["steps"], 20)
        # the one node replaces the whole conditioning/guider/sampler/decode chain
        self.assertEqual(graph["7"]["inputs"]["images"], ["6", 0])
        self.assertEqual(graph["7"]["inputs"]["audio"], ["6", 1])
        self.assertEqual(graph["1"]["inputs"]["unet_name"], server.H3_MODEL)
        self.assertEqual(graph["3"]["inputs"]["vae_name"], server.H3_VIDEO_VAE)
        self.assertEqual(graph["4"]["inputs"]["vae_name"], server.H3_AUDIO_VAE)
        for node_id, entry in graph.items():
            for value in entry.get("inputs", {}).values():
                if isinstance(value, list) and len(value) == 2 \
                        and isinstance(value[0], str):
                    self.assertIn(value[0], graph, f"{node_id} has bad link {value}")

    def test_multishot_anchors_identity_on_the_original_frame_by_default(self):
        """The drift fix. Chaining on the previous last frame alone is a copy of
        a copy; anchor_frames pins the ORIGINAL start image into every shot."""
        graph, _brief, _info = self.build_multishot("One.\n---\nTwo.\n---\nThree.")
        self.assertGreaterEqual(graph["6"]["inputs"]["anchor_frames"], 1)
        self.assertEqual(graph["6"]["inputs"]["anchor_frames"], server.H3_ANCHOR_FRAMES)
        self.assertEqual(graph["6"]["inputs"]["memory_frames"], server.H3_MEMORY_FRAMES)

    def test_multishot_without_memory_uses_the_plain_sampler(self):
        """Both off is the pack's own definition of stock behaviour, and the
        plain node must not be handed inputs it does not declare."""
        graph, _brief, _info = self.build_multishot(
            "One.\n---\nTwo.", anchor=0, memory=0)
        self.assertEqual(graph["6"]["class_type"], server.H3_MULTISHOT_NODE)
        self.assertEqual(set(graph["6"]["inputs"]),
                         self.MULTISHOT_REQUIRED | self.MULTISHOT_OPTIONAL)

    def test_multishot_falls_back_when_the_pack_predates_the_memory_node(self):
        """An older install has only the plain sampler. Queueing a graph naming
        a class ComfyUI cannot resolve fails at the GPU; degrade instead."""
        with patch.dict(server._COMFY_NODES,
                        {"names": {server.H3_MULTISHOT_NODE}}):
            graph, _brief, _info = self.build_multishot("One.\n---\nTwo.")
        self.assertEqual(graph["6"]["class_type"], server.H3_MULTISHOT_NODE)
        self.assertNotIn("anchor_frames", graph["6"]["inputs"])

    def test_multishot_clamps_memory_settings_to_the_nodes_range(self):
        graph, _brief, _info = self.build_multishot(
            "One.\n---\nTwo.", anchor=9, memory=99)
        self.assertEqual(graph["6"]["inputs"]["anchor_frames"], 2)
        self.assertEqual(graph["6"]["inputs"]["memory_frames"], 6)

    def test_multishot_frame_total_accounts_for_the_trimmed_seam(self):
        """The node drops each later shot's duplicated first frame, so the master
        is not simply shots * frames_per_shot."""
        for shots, seconds, expected in ((1, 5, 124), (2, 5, 247), (3, 10, 727)):
            graph, _brief, info = self.build_multishot(
                "\n---\n".join(f"She moves, beat {i}." for i in range(shots)),
                seconds=seconds)
            with self.subTest(shots=shots):
                self.assertEqual(graph["6"]["inputs"]["shot_count"], shots)
                self.assertEqual(graph["6"]["inputs"]["frames_per_shot"],
                                 server.h3_frame_count(seconds))
                self.assertEqual(info["shots"], shots)
                self.assertEqual(info["frames"], expected)

    def test_every_shot_carries_the_audio_direction_and_lora_trigger(self):
        """The node tokenizes each prompt on its own, so anything present only in
        shot one is absent from the rest of the take."""
        plan = {"version": 1, "mode": "replace", "engine": "h3", "model": "fl2va",
                "entries": [{"name": server.H3_HMNSFW_LORA, "strength": 1.0}]}
        graph, brief, _info = self.build_multishot(
            "She turns.\n---\nShe crosses the room.\n---\nShe looks back.",
            lora_plan=plan)
        shots = server.split_shot_script(graph["6"]["inputs"]["script"])
        self.assertEqual(len(shots), 3)
        trigger = server.H3_VIDEO_LORAS[0].get("trigger")
        for shot in shots:
            self.assertIn(server.H3_AUDIO_PROMPT, shot)
            if trigger:
                self.assertEqual(shot.lower().count(trigger.lower()), 1)
        self.assertEqual(brief, graph["6"]["inputs"]["script"])

    def test_shot_script_splits_on_a_bare_separator_line_only(self):
        self.assertEqual(server.split_shot_script("one\n---\ntwo\n---\nthree"),
                         ["one", "two", "three"])
        self.assertEqual(server.split_shot_script("  one  \n  ----  \n two "),
                         ["one", "two"])
        # an em-dash style pause mid-sentence is not a shot boundary
        self.assertEqual(server.split_shot_script("she turns --- slowly --- away"),
                         ["she turns --- slowly --- away"])
        self.assertEqual(server.split_shot_script("   \n---\n  "), [])

    def test_shot_headings_never_reach_the_text_encoder(self):
        """Observed on the first live take: the director wrote "SHOT 1" above each
        brief and that label was conditioned on as if it were scene description."""
        script = ("SHOT 1  \nShe turns to the window.\n---\n"
                  "Shot 2: She crosses the room.\n---\n"
                  "SHOT #3 - She looks back.")
        self.assertEqual(server.split_shot_script(script),
                         ["She turns to the window.", "She crosses the room.",
                          "She looks back."])
        # a real sentence that merely starts with those words is left alone
        for kept in ("Shot 1 of the roll is overexposed.",
                     "Shots ring out as she runs."):
            with self.subTest(kept=kept):
                self.assertEqual(server.split_shot_script(kept), [kept])

    def test_multishot_is_h3_only_and_bounded(self):
        self.assertEqual(server.validate_shot_count("h3", None), 1)
        self.assertEqual(server.validate_shot_count("h3", 1), 1)
        self.assertEqual(server.validate_shot_count("h3", server.H3_SHOTS_MAX),
                         server.H3_SHOTS_MAX)
        with self.assertRaisesRegex(ValueError, "only MiniMax H3"):
            server.validate_shot_count("ltx", 3)
        for bad in (0, -1, server.H3_SHOTS_MAX + 1):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "1-8"):
                server.validate_shot_count("h3", bad)
        with self.assertRaisesRegex(ValueError, "1-8"):
            self.build_multishot("Shot one.", shots=server.H3_SHOTS_MAX + 1)

    def test_missing_multishot_pack_is_refused_before_the_gpu(self):
        with patch.dict(server._COMFY_NODES, {"names": frozenset({"KSampler"})}):
            self.assertFalse(server.h3_multishot_available())
            with self.assertRaisesRegex(ValueError, "ComfyUI-H3-Multishot"):
                server.validate_shot_count("h3", 2)
            with self.assertRaisesRegex(ValueError, "ComfyUI-H3-Multishot"):
                self.build_multishot("Shot one.\n---\nShot two.")
            with patch.object(server, "_video_asset", side_effect=all_video_assets):
                h3 = next(e for e in server.video_engine_options()
                          if e["id"] == "h3")
            self.assertEqual(h3["shots_max"], 1)
        # unprobed ComfyUI must not hide the control
        with patch.dict(server._COMFY_NODES, {"names": None}):
            self.assertTrue(server.h3_multishot_available())

    def test_multishot_keeps_only_the_audio_bearing_video(self):
        self.assertTrue(server.keep_video_output("h3_multishot", "take-audio.mp4"))
        self.assertFalse(server.keep_video_output("h3_multishot", "take.mp4"))

    def test_both_h3_builders_validate_the_canvas_identically(self):
        """One shared helper, so the single-shot and multishot paths cannot drift
        on what a legal first frame is."""
        for build in (server.build_h3_i2v, server.build_h3_multishot):
            with self.subTest(build=build.__name__), TemporaryDirectory() as td:
                root = Path(td)
                (root / "input").mkdir()
                (root / "input" / "prepared.png").write_bytes(b"prepared")
                with patch.object(server, "CDIR", root), \
                     patch.object(server, "_video_asset",
                                  side_effect=all_video_assets):
                    with self.assertRaisesRegex(ValueError, "multiples of 32"):
                        build("A shot.", 1, "prepared.png", seconds=5,
                              width=770, height=1344, model="fl2va")
                    with self.assertRaisesRegex(ValueError, "missing from"):
                        build("A shot.", 1, "gone.png", seconds=5,
                              width=768, height=1344, model="fl2va")

    def test_multishot_brief_is_directed_as_a_shot_script(self):
        system = server.h3_multishot_system(3)
        self.assertIn(server.H3_MOTION_SYSTEM, system)   # additive, not a rewrite
        self.assertIn("exactly 3 shots", system)
        self.assertIn(server.H3_SHOT_SEPARATOR, system)
        self.assertEqual(server.h3_multishot_system(2).count("exactly 2 shots"), 1)

    def test_h3_lora_rows_are_the_literal_model_chain_and_triggers_are_once(self):
        first = dict(server.H3_VIDEO_LORAS[0])
        second = {"name": "Minimax H3\\SecondMotion.safetensors",
                  "title": "Second Motion", "family": "minimax_h3",
                  "variants": ("fl2va",), "default_strength": 0.6,
                  "trigger": "secondmotion", "description": "test motion LoRA",
                  "active_by_default": False}
        plan = {"version": 1, "mode": "replace", "engine": "h3", "model": "fl2va",
                "entries": [
                    {"name": first["name"], "strength": 0.75, "enabled": True},
                    {"name": second["name"], "strength": 0.4, "enabled": True},
                ]}
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "H3_VIDEO_LORAS", (first, second)), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                graph, brief, info = server.build_h3_i2v(
                    "hmmotion, she crosses the room.", 123, "prepared.png",
                    seconds=5, width=768, height=768, model="fl2va",
                    lora_plan=plan, sparse=False)

        self.assertEqual(graph["h3:lora0"]["inputs"], {
            "lora_name": first["name"], "strength_model": 0.75, "model": ["1", 0]})
        self.assertEqual(graph["h3:lora1"]["inputs"], {
            "lora_name": second["name"], "strength_model": 0.4,
            "model": ["h3:lora0", 0]})
        self.assertEqual(graph["8"]["inputs"]["model"], ["h3:lora1", 0])
        self.assertEqual(graph["9"]["inputs"]["model"], ["h3:lora1", 0])
        self.assertEqual([row["name"] for row in info["lora_stack"]],
                         [first["name"], second["name"]])
        self.assertEqual(info["lora_triggers"], ["hmmotion", "secondmotion"])
        self.assertEqual(brief.lower().count("hmmotion"), 1)
        self.assertEqual(brief.lower().count("secondmotion"), 1)

    def test_h3_graph_uses_exact_posix_catalog_paths_for_every_asset(self):
        canonical = {
            "diffusion_models": {
                server.H3_MODEL.replace("\\", "/").replace("Minimax H3", "MINIMAX H3")},
            "text_encoders": {
                server.H3_CLIP.replace("\\", "/").replace("Qwen/", "qwen/")},
            "vae": {
                server.H3_VIDEO_VAE.replace("\\", "/").replace("MiniMax-H3", "minimax-h3"),
                server.H3_AUDIO_VAE.replace("\\", "/").replace("MiniMax-H3", "minimax-h3"),
            },
            "loras": {
                server.H3_HMNSFW_LORA.replace("\\", "/").replace(
                    "Minimax H3", "MINIMAX H3")},
        }

        def posix_catalog(kind=None, ttl=30):
            entries = [{"kind": asset_kind, "rel": rel}
                       for asset_kind, rels in canonical.items() for rel in rels]
            return [entry for entry in entries if entry["kind"] == kind] \
                if kind else entries

        plan = {"version": 1, "mode": "replace", "engine": "h3", "model": "fl2va",
                "entries": [{"name": server.H3_HMNSFW_LORA,
                             "strength": 0.8, "enabled": True}]}
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "model_catalog", side_effect=posix_catalog):
                self.assertIs(
                    server.validate_video_lora_plan("h3", "fl2va", plan), plan)
                graph, _, info = server.build_h3_i2v(
                    "She crosses the room.", 123, "prepared.png", seconds=5,
                    width=768, height=768, model="fl2va", lora_plan=plan)
                h3_options = next(
                    engine for engine in server.video_engine_options()
                    if engine["id"] == "h3")["models"][0]

        model_rel = next(iter(canonical["diffusion_models"]))
        clip_rel = next(iter(canonical["text_encoders"]))
        video_vae_rel = next(rel for rel in canonical["vae"] if "video_vae" in rel)
        audio_vae_rel = next(rel for rel in canonical["vae"] if "audio_vae" in rel)
        lora_rel = next(iter(canonical["loras"]))
        self.assertEqual(graph["1"]["inputs"]["unet_name"], model_rel)
        self.assertEqual(graph["2"]["inputs"]["clip_name"], clip_rel)
        self.assertEqual(graph["3"]["inputs"]["vae_name"], video_vae_rel)
        self.assertEqual(graph["4"]["inputs"]["vae_name"], audio_vae_rel)
        self.assertEqual(graph["h3:lora0"]["inputs"]["lora_name"], lora_rel)
        self.assertEqual(info["model_path"], model_rel)
        self.assertEqual(info["lora_stack"][0]["name"], lora_rel)
        self.assertEqual(h3_options["loras"][0]["name"], server.H3_HMNSFW_LORA)
        self.assertTrue(h3_options["loras"][0]["available"])

    def test_disabled_h3_lora_has_neither_loader_nor_trigger(self):
        plan = {"version": 1, "mode": "replace", "engine": "h3", "model": "fl2va",
                "entries": [{"name": server.H3_HMNSFW_LORA,
                             "strength": 1.0, "enabled": False}]}
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                graph, brief, info = server.build_h3_i2v(
                    "She crosses the room.", 123, "prepared.png", seconds=5,
                    width=768, height=768, model="fl2va", lora_plan=plan,
                    sparse=False)
        self.assertFalse(any(node.startswith("h3:lora") for node in graph))
        self.assertEqual(graph["8"]["inputs"]["model"], ["1", 0])
        self.assertEqual(graph["9"]["inputs"]["model"], ["1", 0])
        self.assertNotIn("hmmotion", brief.lower())
        self.assertEqual(info["loras"], [])
        self.assertEqual(info["lora_triggers"], [])

    def test_h3_motion_director_uses_audio_aware_system_prompt(self):
        response = {"choices": [{"message": {"content": "A directed H3 brief."}}]}
        with patch.object(server, "llm_call", AsyncMock(return_value=(200, response))) as call, \
             patch.object(server, "_turn_start"), patch.object(server, "_turn_end"):
            result = asyncio.run(server.direct_motion("portrait", "turn left", engine="h3"))
        self.assertEqual(result, ("A directed H3 brief.", True))
        messages = call.await_args.args[0]
        self.assertIn("motion-and-sound director", messages[0]["content"])
        self.assertIn("synchronized sound", messages[0]["content"])

    def test_motion_director_is_shown_the_frame_it_is_animating(self):
        """The brain is a VL model and the start frame is on disk. Directing from
        the scene TEXT alone is where invented props and people come from."""
        response = {"choices": [{"message": {"content": "A grounded brief."}}]}
        with patch.object(server, "llm_call", AsyncMock(return_value=(200, response))) as call, \
             patch.object(server, "data_url_for", return_value="data:image/jpeg;base64,AAA"), \
             patch.object(server, "_turn_start"), patch.object(server, "_turn_end"):
            asyncio.run(server.direct_motion("portrait", engine="h3", frame="prepared.png"))
        messages = call.await_args.args[0]
        parts = messages[1]["content"]
        self.assertEqual(parts[0]["type"], "image_url")
        self.assertEqual(parts[0]["image_url"]["url"], "data:image/jpeg;base64,AAA")
        self.assertIn("Still scene: portrait", parts[1]["text"])
        # and the system prompt must actually tell it to obey the picture
        self.assertIn("exact frame this video starts from", messages[0]["content"])

    def test_motion_director_never_claims_an_image_it_could_not_attach(self):
        """Promising an attachment that is not there is worse than sending none:
        the brief would describe a picture nobody supplied."""
        response = {"choices": [{"message": {"content": "A brief."}}]}
        with patch.object(server, "llm_call", AsyncMock(return_value=(200, response))) as call, \
             patch.object(server, "data_url_for", return_value=None), \
             patch.object(server, "_turn_start"), patch.object(server, "_turn_end"):
            asyncio.run(server.direct_motion("portrait", engine="h3", frame="gone.png"))
        messages = call.await_args.args[0]
        self.assertIsInstance(messages[1]["content"], str)
        self.assertNotIn("exact frame this video starts from", messages[0]["content"])

    def test_motion_director_without_a_frame_sends_plain_text(self):
        response = {"choices": [{"message": {"content": "A brief."}}]}
        with patch.object(server, "llm_call", AsyncMock(return_value=(200, response))) as call, \
             patch.object(server, "_turn_start"), patch.object(server, "_turn_end"):
            asyncio.run(server.direct_motion("portrait", engine="ltx"))
        self.assertIsInstance(call.await_args.args[0][1]["content"], str)

    def test_vhs_silent_twin_is_not_published(self):
        self.assertFalse(server.keep_video_output("h3_i2v", "clip_00001.mp4"))
        self.assertTrue(server.keep_video_output("h3_i2v", "clip_00001-audio.mp4"))
        # ltx_i2v's VHS_VideoCombine has its audio input wired (node 140 <- 201
        # in templates/ltx_i2v.json), so it produces the same silent twin.
        self.assertFalse(server.keep_video_output("ltx_i2v", "clip_00001.mp4"))
        self.assertTrue(server.keep_video_output("ltx_i2v", "clip_00001-audio.mp4"))
        # upscale_video keeps the clip's audio intact through the same VHS
        # save, so it leaves the same silent twin behind.
        self.assertFalse(server.keep_video_output("upscale_video", "clip_00001.mp4"))
        self.assertTrue(server.keep_video_output("upscale_video", "clip_00001-audio.mp4"))

    def test_animate_routes_h3_with_prepared_dimensions(self):
        plan = {"version": 1, "mode": "replace", "engine": "h3", "model": "fl2va",
                "entries": [{"name": server.H3_HMNSFW_LORA,
                             "strength": 0.9, "enabled": True}]}
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "input").mkdir()
            (root / "output" / "still.png").write_bytes(b"still")
            entry = {"id": "abc123", "scene": "the subject at a workbench", "images": [{
                "filename": "still.png", "subfolder": "", "media": "image"}]}
            submit = AsyncMock(return_value={"id": "videojob", "error": None})

            async def run():
                response = await server.animate(FakeRequest({
                    "id": "abc123", "cid": "cid1", "engine": "h3",
                    "model": "fl2va", "seconds": 10, "hint": "she lifts the tool",
                    "lora_plan": plan,
                }))
                await asyncio.sleep(0)
                return response

            director = AsyncMock(return_value=("H3 motion and audio brief", True))
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "validate_video_selection",
                              return_value=("h3", "fl2va", 10, None)), \
                 patch.object(server, "prepare_h3_frame",
                              return_value=("pixal_h3_ready.png", 1344, 768)), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets), \
                 patch.object(server, "direct_motion", director), \
                 patch.object(server.HUB, "ledger_read", return_value=[entry]), \
                 patch.object(server.HUB, "broadcast"), \
                 patch.object(server.HUB, "submit", submit):
                response = asyncio.run(run())

        # animate never passed the length through, so the director wrote blind
        # and a long clip got a short clip's worth of content.
        self.assertEqual(director.await_args.kwargs.get("seconds"), 10)

        self.assertEqual(response.status, 200)
        body = json.loads(response.text)
        self.assertEqual((body["engine"], body["model"], body["seconds"]),
                         ("h3", "fl2va", 10))
        submit.assert_awaited_once()
        args = submit.await_args.args
        self.assertEqual(args[2], "h3_i2v")
        self.assertEqual(args[4], {
            "seconds": 10, "model": "fl2va", "image": "pixal_h3_ready.png",
            "width": 1344, "height": 768, "resolution": "standard", "lora_plan": plan})

    def test_animate_sends_a_pasted_script_verbatim_and_counts_its_own_shots(self):
        """A script is the user's own words: the motion director is not called at
        all, and the script's own shot count wins when the caller names none."""
        script = ("She turns to the window.\n---\n"
                  "She crosses the room.\n---\n"
                  "She looks back over her shoulder.")
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "input").mkdir()
            (root / "output" / "still.png").write_bytes(b"still")
            entry = {"id": "abc123", "scene": "the subject at a workbench",
                     "images": [{"filename": "still.png", "subfolder": "",
                                 "media": "image"}]}
            submit = AsyncMock(return_value={"id": "videojob", "error": None})
            director = AsyncMock(return_value=("a rewritten brief", True))

            async def run():
                response = await server.animate(FakeRequest({
                    "id": "abc123", "cid": "cid1", "engine": "h3",
                    "model": "fl2va", "seconds": 5, "script": script}))
                await asyncio.sleep(0)
                return response

            with patch.object(server, "CDIR", root), \
                 patch.object(server, "validate_video_selection",
                              return_value=("h3", "fl2va", 5, None)), \
                 patch.object(server, "prepare_h3_frame",
                              return_value=("pixal_h3_ready.png", 768, 1152)), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets), \
                 patch.object(server, "direct_motion", director), \
                 patch.object(server.HUB, "ledger_read", return_value=[entry]), \
                 patch.object(server.HUB, "broadcast"), \
                 patch.object(server.HUB, "submit", submit):
                response = asyncio.run(run())

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text)["shots"], 3)
        director.assert_not_awaited()
        args = submit.await_args.args
        # 3x5s fits H3's 15s ceiling, so it is ONE generation with real cuts
        self.assertEqual(args[2], "h3_i2v")
        self.assertEqual(args[4]["seconds"], 15)
        self.assertNotIn("shots", args[4])
        # the user's sentences survive verbatim; only H3's cut syntax is added
        for line in ("She turns to the window.", "She crosses the room.",
                     "She looks back over her shoulder."):
            self.assertIn(line, args[3])
        self.assertIn("[Shot 1] ", args[3])
        self.assertIn("[Shot 2] At 00:05.000, the shot cuts to", args[3])
        self.assertIn("[Shot 3] At 00:10.000, the shot cuts to", args[3])
        self.assertNotIn(server.H3_SHOT_SEPARATOR, args[3])


class VideoDefaultModelTests(unittest.TestCase):
    """video.default_model: the Animate dialog's standing model choice. Same
    discipline as default_engine - flag the chip, never reorder the list."""

    FINETUNE_ID = "10eros_max_fl2va_skip_edges"
    FINETUNE_REL = "diffusion_models\\10Eros_Max_FL2VA_skip_edges.safetensors"

    def _catalog(self, kind=None):
        # Only the finetune is "on disk"; the 8.2 fallback inserts the stock
        # chip ahead of it, so this also proves stock keeps its first slot.
        return ([{"rel": self.FINETUNE_REL, "kind": "diffusion_models",
                   "mtime": 1}]
                if kind == "diffusion_models" else [])

    def _full_cfg(self, video):
        return {"llm": {"base_url": "", "model": ""},
                "critic": {"model": ""}, "upscale": {}, "edit": {}, "vae": {},
                "pid": {}, "video": video, "extra_model_roots": [],
                "comfy_editor": False, "comfy_console": "tui",
                "explicit": "auto", "vram_profile": "auto"}

    def _options(self, video_cfg):
        with patch.object(server, "load_config",
                          return_value={"video": video_cfg,
                                        "vram_profile": "auto"}), \
             patch.object(server, "model_catalog", side_effect=self._catalog), \
             patch.object(server, "_video_asset", side_effect=all_video_assets):
            return server.video_engine_options()

    def test_the_flag_lands_on_the_configured_chip_and_never_reorders(self):
        engines = self._options({"default_model": self.FINETUNE_ID})
        h3 = next(e for e in engines if e["id"] == "h3")
        self.assertEqual([m["id"] for m in h3["models"]],
                         ["fl2va", "ref2va", self.FINETUNE_ID])
        self.assertNotIn("default", h3["models"][0])
        self.assertTrue(h3["models"][2]["default"])

    def test_an_empty_or_unknown_default_flags_nothing(self):
        for video_cfg in ({}, {"default_model": ""}, {"default_model": "wan2"}):
            with self.subTest(video_cfg=video_cfg):
                for engine in self._options(video_cfg):
                    for model in engine["models"]:
                        self.assertNotIn("default", model)

    def test_settings_post_rejects_an_unknown_model(self):
        saved = []
        with patch.object(server, "load_config",
                          return_value=self._full_cfg({"default_engine": "",
                                                       "default_model": ""})), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "save_config",
                          side_effect=lambda cfg: saved.append(cfg)):
            response = asyncio.run(server.settings_post(
                FakeRequest({"video": {"default_model": "wan2"}})))
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.text),
                         {"ok": False, "error": "not a video model: wan2"})
        self.assertEqual(saved, [])     # a rejected write never touches config

    def test_an_unavailable_model_is_still_settable(self):
        """The stock chip resolves on a bare catalog (8.2) with available:
        False - its file may land later; the render gates stay where they are."""
        saved = []
        with patch.object(server, "load_config",
                          return_value=self._full_cfg({"default_engine": "",
                                                       "default_model": ""})), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "save_config",
                          side_effect=lambda cfg: saved.append(cfg)):
            response = asyncio.run(server.settings_post(
                FakeRequest({"video": {"default_model": "fl2va"}})))
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text), {"ok": True})
        self.assertEqual(saved[0]["video"]["default_model"], "fl2va")

    def test_settings_round_trip_exposes_the_default_and_the_model_lists(self):
        cfg = self._full_cfg({"default_engine": "h3", "default_model": ""})
        saved = []
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", side_effect=self._catalog), \
             patch.object(server, "_video_asset", side_effect=all_video_assets), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()), \
             patch.object(server, "save_config",
                          side_effect=lambda c: saved.append(c)):
            post = asyncio.run(server.settings_post(
                FakeRequest({"video": {"default_model": self.FINETUNE_ID}})))
            self.assertEqual(post.status, 200)
            response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        video = json.loads(response.text)["video"]
        self.assertEqual(video["default_engine"], "h3")
        self.assertEqual(video["default_model"], self.FINETUNE_ID)
        h3 = next(e for e in video["engines"] if e["id"] == "h3")
        self.assertEqual(h3["models"],
                         [{"id": "fl2va", "label": "FL2VA", "available": True},
                          {"id": "ref2va", "label": "REF2VA", "available": True},
                          {"id": self.FINETUNE_ID,
                           "label": "10Eros Max Skip Edges", "available": True}])


class VideoUpscale2xDefaultTests(unittest.TestCase):
    """video.upscale_2x (9.31): the H3 2x row's standing default. It can
    never be a finished-clip action - the upscaler re-samples the render's
    own latent - so a Settings toggle that sets the popup's opening
    position is the whole setting. Same flag discipline as default_engine:
    the value rides video_engine_options as a flag on the one engine that
    has the row, and availability stays a separately published fact."""

    def _full_cfg(self, video):
        return {"llm": {"base_url": "", "model": ""},
                "critic": {"model": ""}, "upscale": {}, "edit": {}, "vae": {},
                "pid": {}, "video": video, "extra_model_roots": [],
                "comfy_editor": False, "comfy_console": "tui",
                "explicit": "auto", "vram_profile": "auto"}

    def _options(self, video_cfg):
        with patch.object(server, "load_config",
                          return_value={"video": video_cfg,
                                        "vram_profile": "auto"}), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "_video_asset", side_effect=all_video_assets):
            return server.video_engine_options()

    def test_the_flag_lands_on_h3_alone_when_the_default_is_set(self):
        engines = self._options({"upscale_2x": True})
        h3 = next(e for e in engines if e["id"] == "h3")
        self.assertTrue(h3["upscale_2x_default"])
        # availability stays its own fact, published either way
        self.assertTrue(h3["upscale_2x"])
        for engine in engines:
            if engine["id"] != "h3":
                self.assertNotIn("upscale_2x_default", engine)

    def test_an_unset_or_off_default_flags_nothing(self):
        for video_cfg in ({}, {"upscale_2x": False}):
            with self.subTest(video_cfg=video_cfg):
                for engine in self._options(video_cfg):
                    self.assertNotIn("upscale_2x_default", engine)

    def test_settings_post_rejects_a_non_bool(self):
        # "true" and 1 are the trap: JSON has real bools, and a truthy
        # stand-in would silently stand a ~3x-cost default ON.
        for bad in ("true", 1, 0, None, [True]):
            with self.subTest(bad=bad):
                saved = []
                with patch.object(server, "load_config",
                                  return_value=self._full_cfg(
                                      {"default_engine": "",
                                       "default_model": ""})), \
                     patch.object(server, "model_catalog", return_value=[]), \
                     patch.object(server, "save_config",
                                  side_effect=lambda cfg: saved.append(cfg)):
                    response = asyncio.run(server.settings_post(
                        FakeRequest({"video": {"upscale_2x": bad}})))
                self.assertEqual(response.status, 400)
                self.assertEqual(json.loads(response.text),
                                 {"ok": False, "error": f"not a bool: {bad}"})
                self.assertEqual(saved, [])  # a rejected write never touches config

    def test_settings_round_trip_exposes_the_default_and_its_availability(self):
        cfg = self._full_cfg({"default_engine": "", "default_model": ""})
        saved = []
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "_video_asset", side_effect=all_video_assets), \
             patch.object(server, "h3_upscale_available", return_value=True), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()), \
             patch.object(server, "save_config",
                          side_effect=lambda c: saved.append(c)):
            post = asyncio.run(server.settings_post(
                FakeRequest({"video": {"upscale_2x": True}})))
            self.assertEqual(post.status, 200)
            self.assertEqual(json.loads(post.text), {"ok": True})
            response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        video = json.loads(response.text)["video"]
        self.assertIs(video["upscale_2x"], True)
        self.assertIs(video["upscale_2x_available"], True)
        self.assertEqual(saved[0]["video"]["upscale_2x"], True)


class MiniMaxH3TurboTests(unittest.TestCase):
    """A distillation is a speed MODE, not a creative LoRA: fewer steps, and
    its own sampler and scheduler travel with it. There is now a ladder of
    them (H3_SPEED_MODES) and the bare boolean names one of its rungs."""

    def turbo_graph(self, turbo, **kw):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                kw.setdefault("sparse", False)   # the speed LADDER is what
                return server.build_h3_i2v("a brief", 7, "prepared.png",  # is under
                                           seconds=5, width=768,          # test here
                                           height=1152, turbo=turbo, **kw)

    def test_turbo_changes_steps_sampler_and_scheduler_together(self):
        # The bare boolean is no longer its own recipe: it names one rung of
        # the ladder, and that rung is lightx2v 8-step (euler/simple).
        self.assertEqual(server.H3_SPEED_LEGACY_TURBO, "turbo8")
        graph, _p, _i = self.turbo_graph(True)
        self.assertEqual(graph["8"]["inputs"]["steps"], 8)
        self.assertEqual(graph["7"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(graph["8"]["inputs"]["scheduler"], "simple")
        # Every rung wires all three of its own numbers into the graph: each
        # distillation has a sampler/scheduler its author trained it for, and
        # res_multistep+simple at 8 or 4 steps is not a faster render, it is a
        # broken one. turbo_v4 is the rung that still moves the scheduler.
        for mode, steps, sampler, scheduler in (
                ("quality", 20, "res_multistep", "simple"),
                ("turbo8", 8, "euler", "simple"),
                ("turbo4", 4, "er_sde", "simple"),
                ("turbo_v4", 8, "euler", "beta")):
            picked, _p, _i = self.turbo_graph(mode)
            with self.subTest(mode=mode):
                self.assertEqual(picked["8"]["inputs"]["steps"], steps)
                self.assertEqual(picked["7"]["inputs"]["sampler_name"], sampler)
                self.assertEqual(picked["8"]["inputs"]["scheduler"], scheduler)
        plain, _p, _i = self.turbo_graph(False)
        self.assertEqual(plain["8"]["inputs"]["steps"], 20)
        self.assertEqual(plain["7"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(plain["8"]["inputs"]["scheduler"], "simple")

    def test_turbo_patches_the_model_the_scheduler_and_guider_both_read(self):
        graph, _p, _i = self.turbo_graph(True)
        loaders = [nid for nid, n in graph.items()
                   if n["class_type"] == "LoraLoaderModelOnly"]
        self.assertEqual(len(loaders), 1)
        tail = [loaders[0], 0]
        self.assertEqual(graph["8"]["inputs"]["model"], tail)
        self.assertEqual(graph["9"]["inputs"]["model"], tail)

    def test_turbo_is_reachable_from_the_request(self):
        """It was threaded through both builders and nothing ever passed it
        True - a speed mode no caller could ask for."""
        self.assertIn("turbo", server.SIGS["h3_i2v"])
        self.assertIn("turbo", server.SIGS["h3_multishot"])
        # and LTX, which has no such mode, must not be handed one
        self.assertNotIn("turbo", server.SIGS["ltx_i2v"])

    def test_the_h3_engine_advertises_whether_turbo_is_installed(self):
        """The UI cannot offer a control for a LoRA that is not on disk."""
        with patch.object(server, "_video_asset", side_effect=all_video_assets):
            h3 = next(e for e in server.video_engine_options() if e["id"] == "h3")
        self.assertTrue(h3["turbo"])
        with patch.object(server, "_video_asset",
                          side_effect=lambda k, n: None if k == "loras" and "turbo" in n.lower()
                          else all_video_assets(k, n)):
            h3 = next(e for e in server.video_engine_options() if e["id"] == "h3")
        self.assertFalse(h3["turbo"])

    def test_the_reported_sampler_is_the_one_that_ran(self):
        """The info line was a hardcoded "res_multistep - simple - 20 steps",
        so a turbo render described itself as a 20-step res_multistep render in
        the one place the user can check what actually happened."""
        _g, _p, turbo = self.turbo_graph(True)
        self.assertIn("euler", turbo["sampler"])
        self.assertIn("simple", turbo["sampler"])
        self.assertIn("8 steps", turbo["sampler"])
        self.assertNotIn("res_multistep", turbo["sampler"])
        self.assertNotIn("20 steps", turbo["sampler"])
        self.assertEqual(turbo["speed_mode"], server.H3_SPEED_LEGACY_TURBO)
        # every rung reports itself, scheduler included: turbo_v4 is the one
        # that still moves it, so it is the proof the line is read back rather
        # than reconstructed from the default constants
        _g, _p, old = self.turbo_graph("turbo_v4")
        self.assertIn("euler", old["sampler"])
        self.assertIn("beta", old["sampler"])
        self.assertIn("8 steps", old["sampler"])
        self.assertEqual(old["speed_mode"], "turbo_v4")
        _g, _p, four = self.turbo_graph("turbo4")
        self.assertIn("er_sde", four["sampler"])
        self.assertIn("4 steps", four["sampler"])
        self.assertEqual(four["speed_mode"], "turbo4")
        _g, _p, plain = self.turbo_graph(False)
        self.assertIn("res_multistep", plain["sampler"])
        self.assertIn("simple", plain["sampler"])
        self.assertIn("20 steps", plain["sampler"])
        self.assertEqual(plain["speed_mode"], server.H3_SPEED_DEFAULT)

    def test_turbo_contributes_no_trigger_word(self):
        """A distillation is not a style - injecting a trigger would pollute
        the conditioning for nothing."""
        _g, prompt, _i = self.turbo_graph(True)
        self.assertNotIn("turbo", prompt.lower())

    def test_a_missing_turbo_lora_falls_back_to_the_full_step_count(self):
        """8 steps without the distillation is unusable, not merely slower."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            def no_turbo(kind, name):
                if kind == "loras" and "turbo" in name.lower():
                    return None
                return all_video_assets(kind, name)
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=no_turbo):
                graph, _p, _i = server.build_h3_i2v(
                    "a brief", 7, "prepared.png", seconds=5,
                    width=768, height=1152, turbo=True)
        self.assertEqual(graph["8"]["inputs"]["steps"], 20)
        self.assertEqual(graph["7"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual([n for n in graph.values()
                          if n["class_type"] == "LoraLoaderModelOnly"], [])


class MiniMaxH3SparseAttentionTests(unittest.TestCase):
    """Sparse attention (ComfyUI-PlagueKind-Nodes, H3SLAAttention).

    Measured on this machine - 5090, 928x1120 x 124 frames, 20 steps
    res_multistep, four full runs alternating dense/sparse on distinct seeds:

        Sage attention            7.25, 7.23 s/step
        + sparse attention 0.9    5.42, 5.37 s/step     1.34x

    So it is ON wherever the pack is installed, and the control exists to
    turn it OFF for a like-for-like quality reference. It engages only past
    the node's min_seq_len, which is why the low-resolution reports see
    nothing; every canvas Pixal renders at is far past that.
    """

    def build(self, **kw):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                kw.setdefault("width", 768)
                kw.setdefault("height", 1344)
                kw.setdefault("model", "fl2va")
                return server.build_h3_i2v("She turns.", 987, "prepared.png",
                                           seconds=5, **kw)

    def build_multishot(self, motion, **kw):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                kw.setdefault("width", 768)
                kw.setdefault("height", 1344)
                kw.setdefault("model", "fl2va")
                return server.build_h3_multishot(motion, 987, "prepared.png", **kw)

    def test_it_is_on_by_default_and_only_off_when_asked(self):
        # Jesse, 2026-08-23: "on by default" / "if its installed".
        with patch.dict(server._COMFY_NODES,
                        {"names": frozenset({server.H3_SLA_NODE})}):
            self.assertTrue(server.h3_sparse_active())
            self.assertTrue(server.h3_sparse_active(True))
            self.assertFalse(server.h3_sparse_active(False))

    def test_the_patch_rides_after_the_lora_chain(self):
        """A LoRA stacked ON TOP of the patch would be applied to a model
        that no longer attends densely; the node's contract is that it goes
        last."""
        first = {"name": "Minimax H3\\HmMotion.safetensors", "title": "HM",
                 "family": "minimax_h3", "variants": ("fl2va",),
                 "default_strength": 0.8, "trigger": "hmmotion",
                 "description": "test motion LoRA", "active_by_default": False}
        plan = {"version": 1, "mode": "replace", "engine": "h3",
                "model": "fl2va",
                "entries": [{"name": first["name"], "strength": 0.75,
                             "enabled": True}]}
        with patch.object(server, "H3_VIDEO_LORAS", (first,)), \
             patch.dict(server._COMFY_NODES,
                        {"names": frozenset({server.H3_SLA_NODE})}):
            graph, _brief, info = self.build(lora_plan=plan)
        self.assertEqual(graph["h3:sla"]["class_type"], server.H3_SLA_NODE)
        self.assertEqual(graph["h3:sla"]["inputs"]["model"], ["h3:lora0", 0])
        # and the sampler and the guider both read the patched model, never
        # the raw loader - a guider left on the unpatched model renders at the
        # old speed and silently disagrees with the sampler about the weights
        self.assertEqual(graph["8"]["inputs"]["model"], ["h3:sla", 0])
        self.assertEqual(graph["9"]["inputs"]["model"], ["h3:sla", 0])
        self.assertTrue(info["sparse_attention"])

    def test_the_sparsity_is_the_ratio_its_author_validated(self):
        with patch.dict(server._COMFY_NODES,
                        {"names": frozenset({server.H3_SLA_NODE})}):
            graph, _b, _i = self.build()
        self.assertEqual(server.H3_SLA_SPARSITY, 0.9)
        self.assertEqual(graph["h3:sla"]["inputs"]["sparsity_ratio"], 0.9)
        # block_size is a STRING enum on this node, not an int
        self.assertEqual(graph["h3:sla"]["inputs"]["block_size"], "64")

    def test_dense_builds_the_graph_exactly_as_before(self):
        with patch.dict(server._COMFY_NODES,
                        {"names": frozenset({server.H3_SLA_NODE})}):
            graph, _b, info = self.build(sparse=False)
        self.assertNotIn("h3:sla", graph)
        self.assertEqual(graph["8"]["inputs"]["model"], ["1", 0])
        self.assertEqual(graph["9"]["inputs"]["model"], ["1", 0])
        self.assertFalse(info["sparse_attention"])

    def test_an_absent_pack_is_not_offered_and_not_wired(self):
        """"if its installed" - the row hides rather than offering a toggle
        that cannot do anything, and asking for it anyway builds the plain
        graph instead of queueing a prompt that fails validation."""
        with patch.dict(server._COMFY_NODES, {"names": frozenset({"KSampler"})}):
            self.assertFalse(server.h3_sla_available())
            self.assertFalse(server.h3_sparse_active(True))
            graph, _b, info = self.build(sparse=True)
            engine = [e for e in server.video_engine_options()
                      if e["id"] == "h3"][0]
        self.assertNotIn("h3:sla", graph)
        self.assertFalse(info["sparse_attention"])
        self.assertFalse(engine["sparse"])

    def test_a_cold_probe_still_offers_it(self):
        """Same contract as multishot: before the first successful
        /object_info the answer is yes, so a cold start never hides a control
        it would show a second later."""
        with patch.dict(server._COMFY_NODES, {"names": None}):
            self.assertTrue(server.h3_sla_available())
            engine = [e for e in server.video_engine_options()
                      if e["id"] == "h3"][0]
        self.assertTrue(engine["sparse"])
        self.assertTrue(engine["sparse_default"])

    def test_every_h3_lane_carries_it_and_no_other_engine_does(self):
        for recipe in ("h3_i2v", "h3_multishot", "h3_ref2v"):
            with self.subTest(recipe=recipe):
                self.assertIn("sparse", server.SIGS[recipe])
        self.assertNotIn("sparse", server.SIGS["ltx_i2v"])

    def test_the_request_can_only_ever_turn_it_off(self):
        """The default lives in ONE place. A client that sends sparse:true
        must not be able to force the node in where the pack is missing."""
        src = (Path(server.__file__).resolve()).read_text(encoding="utf-8")
        self.assertIn('if body.get("sparse") is False:', src)
        self.assertNotIn('args["sparse"] = True', src)

    def test_multishot_is_patched_too(self):
        with patch.dict(server._COMFY_NODES,
                        {"names": frozenset({server.H3_SLA_NODE,
                                             server.H3_MULTISHOT_NODE,
                                             server.H3_MULTISHOT_MEMORY_NODE})}):
            graph, _b, info = self.build_multishot("Shot one.\n---\nShot two.")
        # the chained sampler is a single node here, and it is node 6
        self.assertEqual(graph["h3:sla"]["inputs"]["model"], ["1", 0])
        self.assertEqual(graph["6"]["inputs"]["model"], ["h3:sla", 0])
        self.assertTrue(info["sparse_attention"])


class MiniMaxH3UpscaleTests(unittest.TestCase):
    """The 2x upscale lane (Comfyui-MMH3-UltimateUpscale), riding INSIDE the
    render job: it re-samples the latent the sampler just produced, and Pixal
    does not store latents, so it is an option on the render, never an action
    on a finished clip.

    The recipe was settled by measurement on 2026-08-23 - five takes at
    928x1120 -> 1856x2240 x 124 frames (docs/2026-08-23-h3-speed-and-upscale.md):
    6 steps at denoise 0.22, DENSE attention on the refine (the flicker
    number preferred sparse, Jesse's eye picked dense), a tile grid that
    divides EXACTLY (3x768 - 2x224 = 1856, 3x896 - 2x224 = 2240), and the 3D
    latent upscaler weights - never the model-free path, which smears hair
    across the face in wet streaks ("v5 is broken").

    Cost: ~3x the render (140s -> 464s), peaking at 30.9 GB of 32.6 - so it
    is opt-in, the OPPOSITE default from sparse attention.
    """

    CFG = {"upscale": {"image_model": "4x\\4xPurePhoto-RealPLSKR.pth"}}
    CATALOG = [{"kind": "upscale_models", "rel": "4x\\4xPurePhoto-RealPLSKR.pth",
                "mtime": 0}]

    def build(self, upscale=True, names=None, assets=all_video_assets,
              cfg=None, **kw):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "load_config",
                              return_value=cfg or self.CFG), \
                 patch.object(server, "model_catalog",
                              return_value=self.CATALOG), \
                 patch.object(server, "_video_asset", side_effect=assets), \
                 patch.dict(server._COMFY_NODES,
                            {"names": names if names is not None
                             else frozenset({server.H3_UPSCALE_NODE})}):
                kw.setdefault("width", 928)
                kw.setdefault("height", 1120)
                kw.setdefault("model", "fl2va")
                if upscale is not None:
                    kw["upscale"] = upscale
                return server.build_h3_i2v("She turns.", 987, "prepared.png",
                                           seconds=5, **kw)

    def test_a_fresh_install_with_no_image_upscaler_still_renders(self):
        """The shipped config default is image_model="" and a fresh install
        may carry no ESRGAN weights at all. resolve_upscale_model RAISES on
        both, so calling it unguarded meant ticking 2x killed the render with
        "choose an upscale model in Settings first". The anchor falls back to
        a plain lanczos resize instead: take 1's defect was the conditioning's
        SIZE, which is still right either way, not its sharpness."""
        unset = {"upscale": {"image_model": ""}}
        gone = {"upscale": {"image_model": "4x" + os.sep + "Uninstalled.pth"}}
        for label, cfg in (("unset", unset), ("not installed", gone)):
            with self.subTest(image_model=label):
                graph, _b, info = self.build(cfg=cfg)
                # the pass still runs, at the right size, off the raw frame
                self.assertNotIn("h3:up:imgloader", graph)
                self.assertNotIn("h3:up:imgup", graph)
                self.assertEqual(graph["h3:up:imgfit"]["inputs"]["image"], ["5", 0])
                self.assertEqual(graph["h3:up:imgfit"]["inputs"]["width"], 1856)
                self.assertEqual(graph["h3:up:cond"]["inputs"]["first_frame"],
                                 ["h3:up:imgfit", 0])
                self.assertEqual(info["upscale"], "2x")

    def test_a_configured_image_upscaler_sharpens_the_anchor(self):
        graph, _b, _i = self.build()
        self.assertEqual(graph["h3:up:imgloader"]["inputs"]["model_name"],
                         self.CFG["upscale"]["image_model"])
        self.assertEqual(graph["h3:up:imgup"]["inputs"]["image"], ["5", 0])
        self.assertEqual(graph["h3:up:imgfit"]["inputs"]["image"],
                         ["h3:up:imgup", 0])

    def test_the_grid_divides_exactly(self):
        # The pick Jesse made: 3x768 - 2x224 = 1856 and 3x896 - 2x224 = 2240.
        self.assertEqual(server.h3_tile_axis(1856), (768, 224))
        self.assertEqual(server.h3_tile_axis(2240), (896, 224))
        # A grid that does not divide exactly leaves a sliver tile at the far
        # edge, re-sampled semi-independently - the coloured noise blocks in
        # the corner of take 1. For a spread of canvases the helper must hit
        # n*tile - (n-1)*overlap == size EXACTLY, on the node's 32px step.
        for size in (1024, 1280, 1344, 1536, 1856, 2048, 2240, 2560, 2688,
                     3072, 3360, 4096):
            with self.subTest(size=size):
                tile, overlap = server.h3_tile_axis(size)
                exact = [n for n in range(2, 7)
                         if (size + (n - 1) * overlap) % n == 0
                         and (size + (n - 1) * overlap) // n == tile]
                self.assertTrue(
                    exact, f"{size}px: {tile}/{overlap} leaves a sliver tile")
                self.assertLess(overlap, tile)
                self.assertEqual(tile % 32, 0)
                self.assertEqual(overlap % 32, 0)

    def test_the_upscale_branch_is_the_measured_graph(self):
        graph, _b, _i = self.build()
        # The 2x first frame goes through the user's configured IMAGE
        # upscaler - take 1 fed the 1x conditioning and the node bilinear-
        # resized the frozen frame-0 keyframe, so the clip opened on a blur.
        self.assertEqual(graph["h3:up:imgloader"]["class_type"],
                         "UpscaleModelLoader")
        self.assertEqual(graph["h3:up:imgloader"]["inputs"]["model_name"],
                         "4x\\4xPurePhoto-RealPLSKR.pth")
        self.assertEqual(graph["h3:up:imgup"]["inputs"], {
            "upscale_model": ["h3:up:imgloader", 0], "image": ["5", 0]})
        self.assertEqual(graph["h3:up:imgfit"]["inputs"], {
            "image": ["h3:up:imgup", 0], "upscale_method": "lanczos",
            "width": 1856, "height": 2240, "crop": "disabled"})
        # Conditioning rebuilt AT the 2x canvas, every other input identical
        # to the render's own node 6.
        cond = graph["h3:up:cond"]["inputs"]
        self.assertEqual(graph["h3:up:cond"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(cond["clip"], ["2", 0])
        self.assertEqual(cond["vae"], ["3", 0])
        self.assertEqual(cond["prompt"], graph["6"]["inputs"]["prompt"])
        self.assertEqual(cond["length"], graph["6"]["inputs"]["length"])
        self.assertEqual(cond["width"], 1856)
        self.assertEqual(cond["height"], 2240)
        self.assertEqual(cond["first_frame"], ["h3:up:imgfit", 0])
        # ...while the render's own conditioning keeps the 1x canvas.
        self.assertEqual(graph["6"]["inputs"]["first_frame"], ["5", 0])
        self.assertEqual(graph["6"]["inputs"]["width"], 928)
        self.assertEqual(graph["h3:up:param"]["inputs"], {
            "model_name": server.H3_LATENT_UPSCALER, "width": 1856,
            "height": 2240, "device": "cuda", "precision": "bf16"})
        self.assertEqual(graph["h3:up:noise"]["inputs"], {"noise_seed": 988})
        sample = graph["h3:up:sample"]["inputs"]
        self.assertEqual(graph["h3:up:sample"]["class_type"],
                         server.H3_UPSCALE_NODE)
        self.assertEqual(sample["conditioning"], ["h3:up:cond", 0])
        self.assertEqual(sample["latent"], ["11", 0])
        self.assertEqual(sample["noise"], ["h3:up:noise", 0])
        self.assertEqual(sample["sampler"], ["7", 0])
        self.assertEqual(sample["sigmas"], ["h3:up:sigmas", 0])
        self.assertEqual(sample["cfg"], 1.0)
        self.assertEqual(sample["latent_upscale_param"], ["h3:up:param", 0])
        self.assertEqual(sample["spatial_split_param"], ["h3:up:tiles", 0])
        self.assertNotIn("negative", sample)
        # The model-free path is forbidden, not an option: bilinear smears
        # hair across the face in wet streaks ("v5 is broken"), and both
        # metrics had ranked that clip first.
        classes = {node["class_type"] for node in graph.values()}
        self.assertNotIn("MMH3LatentUpscaleParams", classes)

    def test_the_refine_samples_the_lora_tail_not_the_sparse_patch(self):
        """THE case that can silently go wrong: a LoRA plan applied AND
        sparse attention on. The render samples the patched chain; the
        refine must sample the LoRA chain WITHOUT the patch - at 6 steps
        dense scored 14.87 flicker against sparse's 14.16 and Jesse picked
        dense anyway ("the artifact is gone in this one - best so far"), and
        sparse buys ~3% on a tile."""
        first = {"name": "Minimax H3\\HmMotion.safetensors", "title": "HM",
                 "family": "minimax_h3", "variants": ("fl2va",),
                 "default_strength": 0.8, "trigger": "hmmotion",
                 "description": "test motion LoRA", "active_by_default": False}
        plan = {"version": 1, "mode": "replace", "engine": "h3",
                "model": "fl2va",
                "entries": [{"name": first["name"], "strength": 0.75,
                             "enabled": True}]}
        with patch.object(server, "H3_VIDEO_LORAS", (first,)):
            graph, _b, _i = self.build(
                lora_plan=plan,
                names=frozenset({server.H3_SLA_NODE, server.H3_UPSCALE_NODE}))
        # the render itself IS sparse...
        self.assertEqual(graph["h3:sla"]["inputs"]["model"], ["h3:lora0", 0])
        self.assertEqual(graph["8"]["inputs"]["model"], ["h3:sla", 0])
        self.assertEqual(graph["9"]["inputs"]["model"], ["h3:sla", 0])
        # ...and the refine is NOT: dense, but still through the LoRA chain
        self.assertEqual(graph["h3:up:sample"]["inputs"]["model"],
                         ["h3:lora0", 0])
        self.assertEqual(graph["h3:up:sigmas"]["inputs"]["model"],
                         ["h3:lora0", 0])
        self.assertEqual(graph["h3:up:sample"]["inputs"]["latent"], ["11", 0])

    def test_node_14_muxes_the_2x_decode_with_the_render_audio(self):
        graph, _b, _i = self.build()
        # One video output, the 2x - no second VHS_VideoCombine.
        self.assertEqual([n for n in graph
                          if graph[n]["class_type"] == "VHS_VideoCombine"],
                         ["14"])
        self.assertEqual(graph["14"]["inputs"]["images"], ["h3:up:decode", 0])
        # Audio stays the render's own decode: the pack carries the
        # 32-channel audio latent through untouched and never re-samples it.
        self.assertEqual(graph["14"]["inputs"]["audio"], ["13", 0])
        self.assertEqual(graph["h3:up:decode"]["inputs"], {
            "samples": ["h3:up:sample", 0], "vae": ["3", 0]})

    def test_the_refine_schedule_is_six_steps_at_the_measured_denoise(self):
        # 20 steps at 0.35 ran 180 sampler steps of shimmer; 6 at 0.22 is
        # the measured settle - the step count, not attention, was what
        # moved warble.
        self.assertEqual(server.H3_UPSCALE_STEPS, 6)
        self.assertEqual(server.H3_UPSCALE_DENOISE, 0.22)
        graph, _b, _i = self.build()
        sigmas = graph["h3:up:sigmas"]["inputs"]
        self.assertEqual(graph["h3:up:sigmas"]["class_type"], "BasicScheduler")
        self.assertEqual(sigmas["steps"], 6)
        self.assertEqual(sigmas["denoise"], 0.22)
        # the run's own scheduler travels into the refine
        self.assertEqual(sigmas["scheduler"], server.H3_SCHEDULER)

    def test_the_tile_node_carries_the_measured_split(self):
        graph, _b, _i = self.build()
        tiles = graph["h3:up:tiles"]["inputs"]
        self.assertEqual(graph["h3:up:tiles"]["class_type"],
                         "MMH3SpatialSplitParams")
        self.assertEqual((tiles["tile_width"], tiles["spatial_w_overlap"]),
                         (768, 224))
        self.assertEqual((tiles["tile_height"], tiles["spatial_h_overlap"]),
                         (896, 224))
        # fade = max(32, overlap - 32) per axis: 12 of the 14 latent cells
        # ramp instead of 2 (take 1's failure)
        self.assertEqual(tiles["fade_width"], 192)
        self.assertEqual(tiles["fade_height"], 192)
        self.assertEqual(tiles["min_tile_size"], 256)
        self.assertEqual(tiles["overlap_mode"], "earlier")
        self.assertEqual(tiles["overlap_blend"], "smoothstep")

    def test_long_clips_are_resampled_in_anchored_time_chunks(self):
        """The 2026-08-26 A/B: a 5s clip (124 frames) through the 3D
        upscaler as ONE temporal block grows a sparkle lattice in dark
        regions; 51-frame chunks at 17 overlap with the anchor pinned
        collapsed it to a few faint dots (tsplit5s.mp4)."""
        graph, _b, info = self.build()
        self.assertEqual(graph["h3:up:time"]["class_type"],
                         "MMH3TemporalSplitParams")
        self.assertEqual(graph["h3:up:time"]["inputs"], {
            "chunk_length": server.H3_UPSCALE_CHUNK,
            "temporal_overlap": server.H3_UPSCALE_CHUNK_OVERLAP,
            "anchor_strength": server.H3_UPSCALE_ANCHOR})
        self.assertEqual(
            graph["h3:up:sample"]["inputs"]["temporal_split_param"],
            ["h3:up:time", 0])
        # history says which recipe produced the clip
        self.assertEqual(info["upscale"], "2x")
        self.assertEqual(info["upscale_chunk"], server.H3_UPSCALE_CHUNK)

    def test_a_single_chunk_clip_skips_the_temporal_split(self):
        """A clip that fits in one chunk IS the clean case already measured
        (2s/49 frames was lattice-free with the same settings), so the node
        stays out. Simulated by lifting the chunk past 124 frames."""
        with patch.object(server, "H3_UPSCALE_CHUNK", 136):
            graph, _b, info = self.build()
        self.assertNotIn("h3:up:time", graph)
        self.assertNotIn("temporal_split_param",
                         graph["h3:up:sample"]["inputs"])
        self.assertEqual(info["upscale_chunk"], 136)

    def test_the_temporal_split_constants_pass_the_nodes_own_rules(self):
        # chunk 51 / overlap 17 / anchor 0.999 - the measured recipe
        self.assertEqual((server.H3_UPSCALE_CHUNK,
                          server.H3_UPSCALE_CHUNK_OVERLAP,
                          server.H3_UPSCALE_ANCHOR), (51, 17, 0.999))
        ok = server._h3_temporal_split_ok
        self.assertTrue(ok(server.H3_UPSCALE_CHUNK,
                           server.H3_UPSCALE_CHUNK_OVERLAP,
                           server.H3_UPSCALE_ANCHOR))
        # ...and the import-time assert cannot be edited into a graph
        # ComfyUI rejects: off the 17k+5 grid, or overlap >= chunk
        self.assertFalse(ok(50, 17, 0.999))
        self.assertFalse(ok(51, 16, 0.999))
        self.assertFalse(ok(51, 51, 0.999))
        self.assertFalse(ok(51, 68, 0.999))
        self.assertFalse(ok(51, 17, 1.5))

    def test_option_off_builds_the_old_graph_byte_for_byte(self):
        asked, _b, info = self.build(upscale=False)
        plain, _b2, info2 = self.build(upscale=None)   # the kwarg never sent
        self.assertEqual(asked, plain)
        self.assertEqual(info, info2)
        self.assertFalse(any(str(n).startswith("h3:up") for n in asked))
        self.assertEqual(asked["14"]["inputs"]["images"], ["12", 0])
        self.assertEqual(asked["14"]["inputs"]["audio"], ["13", 0])
        self.assertNotIn("upscale", info)
        self.assertEqual(info["size"], "928x1120")

    def test_pack_absent_builds_plain_and_hides_the_row(self):
        """Asking for 2x where the pack is missing builds the plain graph
        rather than queueing a prompt that fails validation - and the engine
        options stop offering the row. (Simulation = patched _COMFY_NODES
        and _video_asset; the real 659 MB file is never touched.)"""
        with patch.dict(server._COMFY_NODES, {"names": frozenset({"KSampler"})}):
            self.assertFalse(server.h3_upscale_available())
            self.assertFalse(server.h3_upscale_active(True))
            graph, _b, info = self.build(names=frozenset({"KSampler"}))
            with patch.object(server, "_video_asset",
                              side_effect=all_video_assets):
                engine = [e for e in server.video_engine_options()
                          if e["id"] == "h3"][0]
        self.assertFalse(any(str(n).startswith("h3:up") for n in graph))
        self.assertEqual(graph["14"]["inputs"]["images"], ["12", 0])
        self.assertNotIn("upscale", info)
        self.assertFalse(engine["upscale_2x"])

    def test_weights_absent_builds_plain_and_hides_the_row(self):
        """The cold-probe contract is NOT enough here: unlike sparse
        attention this lane needs a 659 MB file on disk, so an unprobed
        node list with the weights simply absent must still read
        unavailable."""
        def no_upscaler(kind, rel):
            return None if rel == server.H3_LATENT_UPSCALER else rel
        with patch.dict(server._COMFY_NODES, {"names": None}), \
             patch.object(server, "_video_asset", side_effect=no_upscaler):
            self.assertFalse(server.h3_upscale_available())
            engine = [e for e in server.video_engine_options()
                      if e["id"] == "h3"][0]
        self.assertFalse(engine["upscale_2x"])
        graph, _b, info = self.build(assets=no_upscaler)
        self.assertFalse(any(str(n).startswith("h3:up") for n in graph))
        self.assertNotIn("upscale", info)

    def test_a_cold_probe_still_offers_it_when_the_weights_exist(self):
        """Same contract as multishot and sparse: before the first
        successful /object_info the node answer is yes, so a cold start
        never hides a control it would show a second later."""
        with patch.dict(server._COMFY_NODES, {"names": None}), \
             patch.object(server, "_video_asset", side_effect=all_video_assets):
            self.assertTrue(server.h3_upscale_available())
            engine = [e for e in server.video_engine_options()
                      if e["id"] == "h3"][0]
        self.assertTrue(engine["upscale_2x"])

    def test_the_lane_switch_is_i2v_only(self):
        """One change per brief: the multishot latent is a chained thing
        this graph has never been tested against, and ref2v's reference
        conditioning is untested here too."""
        self.assertIn("upscale", server.SIGS["h3_i2v"])
        for recipe in ("h3_multishot", "h3_ref2v", "ltx_i2v"):
            with self.subTest(recipe=recipe):
                self.assertNotIn("upscale", server.SIGS[recipe])

    def test_the_ledger_reports_the_canvas_the_clip_actually_has(self):
        _g, _b, info = self.build()
        self.assertEqual(info["upscale"], "2x")
        self.assertEqual(info["size"], "1856x2240")
        self.assertAlmostEqual(info["canvas_mp"], 1856 * 2240 / 1e6)
        # the take itself is unchanged - same frames, same duration
        self.assertEqual(info["frames"], 124)
        self.assertEqual(info["duration"], "5.17s @ 24fps")

    def test_the_request_can_only_opt_in(self):
        """Opt-in only: the handler forwards an ask, and there is no path
        that forces 2x on - it ~triples the cost of a render."""
        src = (Path(server.__file__).resolve()).read_text(encoding="utf-8")
        self.assertIn('if body.get("upscale"):\n                '
                      'args["upscale"] = True', src)
        self.assertNotIn('args["upscale"] = False', src)


class MotionBeatBudgetTests(unittest.TestCase):
    """The directors were told to write "for the requested clip length" and
    never told what it was, so a 15s brief carried 5s of content."""

    def test_the_event_budget_scales_with_the_clip(self):
        for seconds, events in ((5, "1 real event"), (10, "2 real events"),
                                (15, "3 real events")):
            note = server.motion_length_note(seconds)
            with self.subTest(seconds=seconds):
                self.assertIn(f"THIS CLIP IS {seconds} SECONDS", note)
                self.assertIn(events, note)

    def test_a_cut_timeline_budgets_one_event_per_shot(self):
        note = server.motion_length_note(15, 3)
        self.assertIn("THIS CLIP IS 15 SECONDS", note)
        self.assertIn("3 real events", note)

    def test_the_director_is_actually_told_the_length(self):
        """The wiring, not the wording: animate never passed seconds through."""
        captured = {}

        async def fake_llm(messages, timeout=None):
            captured["system"] = messages[0]["content"]
            return 200, {"choices": [{"message": {"content": "a brief"}}]}

        with patch.object(server, "llm_call", fake_llm):
            asyncio.run(server.direct_motion("a scene", engine="h3", seconds=15))
        self.assertIn("THIS CLIP IS 15 SECONDS", captured["system"])
        self.assertIn("3 real events", captured["system"])

        with patch.object(server, "llm_call", fake_llm):
            asyncio.run(server.direct_motion("a scene", engine="ltx", seconds=5))
        self.assertIn("THIS CLIP IS 5 SECONDS", captured["system"])
        self.assertIn("1 real event", captured["system"])

    def test_the_sentence_budget_scales_with_the_clip(self):
        """A fixed cap plus a scaling budget inverts the result.

        Measured on one still: the 5s brief came back at 687 characters
        carrying five events, the 15s brief at 483 carrying three. The 2-4
        sentence cap, not the clip length, was deciding how much got written.
        """
        widths = []
        for seconds in (5, 10, 15):
            note = server.motion_length_note(seconds)
            span = re.search(r"Write (\d+)-(\d+) sentences", note)
            self.assertIsNotNone(span, f"no sentence budget at {seconds}s")
            low, high = int(span.group(1)), int(span.group(2))
            self.assertLess(low, high)
            widths.append((low, high))
        for (lo_a, hi_a), (lo_b, hi_b) in zip(widths, widths[1:]):
            self.assertGreater(lo_b, lo_a)      # a longer clip earns more room
            self.assertGreater(hi_b, hi_a)

    def test_neither_prompt_carries_a_competing_sentence_cap(self):
        """The budget is only authoritative if it is the only number there."""
        for name in ("MOTION_SYSTEM", "H3_MOTION_SYSTEM"):
            with self.subTest(prompt=name):
                self.assertNotRegex(getattr(server, name), r"\d+-\d+ sentences")

    def test_the_length_note_survives_a_missing_seconds(self):
        """With the caps gone it is the only length guidance left, so it can no
        longer be conditional on the caller passing a length."""
        captured = {}

        async def fake_llm(messages, timeout=None):
            captured["system"] = messages[0]["content"]
            return 200, {"choices": [{"message": {"content": "a brief"}}]}

        with patch.object(server, "llm_call", fake_llm):
            asyncio.run(server.direct_motion("a scene", engine="ltx"))
        self.assertIn("THIS CLIP IS 5 SECONDS", captured["system"])
        self.assertRegex(captured["system"], r"Write \d+-\d+ sentences")


class VramStarvationWarningTests(unittest.TestCase):
    """Measured 2026-08-10: the same 15s H3 render took 677s with the card to
    itself and was still going at 55 minutes with ~22.9GB free, because ComfyUI
    silently streams the 20GB DiT from host memory rather than failing. Nothing
    in the app said so, and Stop could not land between minute-wide steps.

    The check watches the step rate rather than free VRAM. A pre-flight VRAM
    check is wrong in the ordinary case: right after a render ComfyUI is still
    HOLDING ~25GB of resident models, so free reads low exactly when the next
    render is the fast one."""

    def setUp(self):
        self.hub = server.Hub.__new__(server.Hub)
        self.hub.subs = set()
        self.sent = []
        self.hub.broadcast = lambda **kw: self.sent.append(kw)

    def feed(self, job, steps, gap):
        """Walk the sampler forward, one progress event per step."""
        now = [1000.0]
        with patch.object(server.time, "time", lambda: now[0]), \
             patch.object(server, "gpu_free_bytes", return_value=2 * 2**30):
            for i in range(1, steps + 1):
                self.hub.note_step_rate(job, {"value": i, "max": 20})
                now[0] += gap

    def test_a_healthy_step_rate_says_nothing(self):
        self.feed({"id": "j", "cid": "c"}, steps=6, gap=33.0)
        self.assertEqual(self.sent, [])

    def test_sustained_slow_steps_warn_once(self):
        job = {"id": "j", "cid": "c"}
        self.feed(job, steps=8, gap=180.0)
        texts = [m for m in self.sent if m.get("type") == "text"]
        self.assertEqual(len(texts), 1, "one message per job, not one per step")
        self.assertIn("streamed from system memory", texts[0]["text"])
        self.assertEqual(texts[0]["cid"], "c")

    def test_a_single_slow_step_is_not_enough(self):
        """The first step pays for the model load; that is not starvation."""
        job = {"id": "j", "cid": "c"}
        now = [1000.0]
        with patch.object(server.time, "time", lambda: now[0]), \
             patch.object(server, "gpu_free_bytes", return_value=2 * 2**30):
            self.hub.note_step_rate(job, {"value": 1, "max": 20})
            now[0] += 300.0                      # one very slow step
            self.hub.note_step_rate(job, {"value": 2, "max": 20})
            now[0] += 33.0                       # then healthy again
            self.hub.note_step_rate(job, {"value": 3, "max": 20})
        self.assertEqual([m for m in self.sent if m.get("type") == "text"], [])

    def test_an_unreadable_gpu_still_warns(self):
        """The step rate is the evidence; nvidia-smi only colours it in."""
        job = {"id": "j", "cid": "c"}
        now = [1000.0]
        with patch.object(server.time, "time", lambda: now[0]), \
             patch.object(server, "gpu_free_bytes", return_value=None):
            for i in range(1, 6):
                self.hub.note_step_rate(job, {"value": i, "max": 20})
                now[0] += 200.0
        texts = [m for m in self.sent if m.get("type") == "text"]
        self.assertEqual(len(texts), 1)
        self.assertIn("VRAM is short", texts[0]["text"])


class SpokenLineTests(unittest.TestCase):
    """Both engines decode an audio track, so both need directing.

    The rule lived only in the H3 prompt. A spectrogram of an undirected LTX
    clip showed a harmonic stack at speech pitch modulated at syllable rate -
    LTX had been improvising dialogue the whole time with nobody choosing it.
    """

    def test_both_engines_get_the_spoken_line_rule(self):
        for name in ("MOTION_SYSTEM", "H3_MOTION_SYSTEM"):
            with self.subTest(prompt=name):
                self.assertIn(server.SPOKEN_LINE_RULE, getattr(server, name))

    def test_the_registers_the_user_asked_for_survive_in_both(self):
        """Always ABOUT this scene, never ad copy - and two people in frame talk
        to each other, not the camera (2026-08-11). Sharing one constant is what
        keeps these in step.

        "dry aside" used to be pinned here too. It was removed 2026-08-16 with
        the rest of the registers: see the next test for why.
        """
        for phrase in ("ABOUT THIS SCENE", "talk to each other", "NEVER slogans"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, server.MOTION_SYSTEM)
                self.assertIn(phrase, server.H3_MOTION_SYSTEM)

    def test_the_registers_that_produced_the_quip_are_gone(self):
        """Ten unprompted lines across five days of history.jsonl converged on
        one voice - a poised quip aimed past the room at the viewer, usually a
        boast phrased as a denial. The rule had been ASKING for it, and the
        worst offender was "self-aware": the line Jesse flagged was a character
        noticing she was in a video. Naming a register names a performer.
        """
        for phrase in ("dry aside", "self-aware", "funny or unimpressed"):
            for name in ("MOTION_SYSTEM", "LTX25_MOTION_SYSTEM", "H3_MOTION_SYSTEM"):
                with self.subTest(phrase=phrase, prompt=name):
                    self.assertNotIn(phrase, getattr(server, name))

    def test_every_engine_gets_the_line_shape_that_replaced_them(self):
        """The replacement is a SHAPE, not a register: the clip joins talk
        already underway, so the line is a reply spoken to a named listener,
        written the way a mouth moves. All three prompts share the constant."""
        for phrase in ("SHE IS ALREADY TALKING", "NAME WHO HEARS IT",
                       "WRITE HOW A MOUTH MOVES", "HER REGISTER IS HERS"):
            for name in ("MOTION_SYSTEM", "LTX25_MOTION_SYSTEM", "H3_MOTION_SYSTEM"):
                with self.subTest(phrase=phrase, prompt=name):
                    self.assertIn(phrase, getattr(server, name))

    def test_the_line_is_checked_where_a_small_brain_actually_looks(self):
        """Mid-prompt rules are what the 12B skims; end contracts are what it
        obeys (see the brief harness). The tag syntax landed because H3's
        OUTPUT CONTRACT checked it and the WORDS did not because nothing did -
        and the LTX prompts, which produced the flagged line, ended with no
        contract at all."""
        for name in ("MOTION_SYSTEM", "LTX25_MOTION_SYSTEM"):
            with self.subTest(prompt=name):
                prompt = getattr(server, name)
                self.assertIn(server.SPOKEN_LINE_CHECK, prompt)
                # A check the model reads BEFORE writing is not a check.
                self.assertGreater(prompt.index(server.SPOKEN_LINE_CHECK),
                                   prompt.index(server.SPOKEN_LINE_RULE))
        contract = server.H3_MOTION_SYSTEM.split("OUTPUT CONTRACT")[-1]
        self.assertIn("with the picture covered", contract)

    def test_ltx_is_also_told_what_the_scene_should_sound_like(self):
        """H3 had a native-audio direction and LTX had none, despite decoding
        an audio latent of its own in node 199."""
        self.assertIn("sound direction", server.MOTION_SYSTEM)
        self.assertIn("no background music", server.MOTION_SYSTEM)

    def test_every_line_the_attractor_produced_is_detected(self):
        """The real ones, lifted from history.jsonl - every unprompted line the
        old rule shipped across five days, plus the two the rewritten rule still
        could not stop on the 4B harness. Prose could not reach these; the
        detector is what actually holds the floor."""
        for line in ("You're gonna have to catch me this time.",
                     "You’re gonna make me forget how to walk.",
                     "You're gonna regret this",
                     "You’re not gonna stop me now",
                     "You'll never guess who called",
                     # Waved through by an earlier, too-broad exemption that
                     # spared anything ending in a question mark.
                     "You'll be late for that meeting, ain't you?",
                     "You're gonna love this, aren't you?",
                     "I'm not late,",
                     "I’m not done yet.",
                     "That's not a bug... that's a feature.",
                     "Not even close.",
                     "Still got it?",
                     "did I really say ‘goodnight’? I'm still here."):
            with self.subTest(line=line):
                self.assertIsNotNone(server.spoken_line_fault(line))

    def test_real_talk_is_left_alone(self):
        """The detector must not eat working dialogue - lines the engines really
        shipped from notes, and the best the rewritten rule managed unaided.

        The first two are its own near-misses. "you gonna get that fixed?" drops
        the copula: a real vernacular construction and exactly the speech
        SPOKEN_LINE_RULE asks for, so killing it would enforce standard grammar
        in the name of sounding real. A question is not a prediction. And
        "You're still here?" is something you say to someone in the room - it
        was "I'M still here" that was winking at the viewer."""
        for line in ("you gonna get that machine fixed or just let it burn?",
                     "You're still here?",
                     "I'm telling you, it's like a little Vienna sausage.",
                     "They're all just trees. Hours and hours of trees.",
                     "This drink's colder than I thought.",
                     "You're supposed to breathe it in, dummy.",
                     "Whoa, that sneaker ain't even finished spinning.",
                     # Set dressing, not speech - both real, from history.jsonl.
                     "WELCOME TO GALLOWS CREEK",
                     "GET BACK TO THE TRUCKS!",
                     "That's a quarter, not a dime,",
                     "just checkin'"):
            with self.subTest(line=line):
                self.assertIsNone(server.spoken_line_fault(line))

    FRAME = ("Woman, late 20s, denim jacket. Paper coffee cup in her right "
             "hand. Four dryers behind her, one turning with a red sneaker "
             "in it. Roll of quarters on the counter.")

    def test_the_frame_can_tell_a_grounded_line_from_a_generic_one(self):
        """The covered-picture test, asked in code. "late" is stemmed out of the
        way because every VL inventory ages its subject ("Woman, late 20s") and
        "You're late," scored as grounded against it the first time this ran."""
        for line in ("You're late,", "Dude.", "That one's not going anywhere,"):
            with self.subTest(line=line):
                self.assertIsNotNone(server.spoken_line_fault(line, self.FRAME))
                # Shape-only when there is no ground truth to check against.
                self.assertIsNone(server.spoken_line_fault(line))
        for line in ("Still need that quarter?",          # quarters, stemmed
                     "Yeah, that dryer's got a sneaker in it.",
                     "your coffee's been cold since we got here"):
            with self.subTest(line=line):
                self.assertIsNone(server.spoken_line_fault(line, self.FRAME))

    def test_being_generic_validates_a_rewrite_but_never_triggers_one(self):
        """Measured and reverted (2026-08-16). As a TRIGGER, grounding fired on
        seven lines in ten, pulled every one onto the same prop and the same
        flat declarative, and took spoken texture from 77% to 31% while
        grounding itself went DOWN - it even ate "you gonna get that machine
        fixed or just let it burn?" for saying machine instead of dryer. A bag
        of words cannot judge what a line is ABOUT. It can confirm a rewrite
        landed somewhere real, so that is the only job it kept."""
        generic = 'She turns. "Dude."'
        with patch.object(server, "llm_call", AsyncMock()) as call:
            out = asyncio.run(server.repair_spoken_line(
                generic, "a laundromat", self.FRAME, None, 5))
        self.assertEqual(out, generic)
        call.assert_not_awaited()

        # ...but a replacement for a REAL fault still has to land in the frame.
        broken = 'She turns. "You’re gonna love this."'
        with patch.object(server, "llm_call", AsyncMock(return_value=(
                200, {"choices": [{"message": {"content": "yeah, whatever"}}]}))):
            self.assertEqual(asyncio.run(server.repair_spoken_line(
                broken, "a laundromat", self.FRAME, None, 5)), broken)
        with patch.object(server, "llm_call", AsyncMock(return_value=(
                200, {"choices": [{"message": {
                    "content": "that dryer’s still going, huh"}}]}))):
            self.assertIn("that dryer’s still going, huh", asyncio.run(
                server.repair_spoken_line(broken, "a laundromat", self.FRAME, None, 5)))

    def test_a_dead_brain_never_costs_a_character_her_voice(self):
        """Muting somebody silently is worse than shipping a weak line, so
        every failure path - no brain, a refusal, a repair that trips the same
        wire - returns the brief untouched."""
        brief = 'She turns. (S1) says: <d>[English] I’m not done yet.</d> Lips close.'

        def said(text):
            return AsyncMock(return_value=(200, {"choices": [
                {"message": {"content": text}}]}))

        for label, stub in (
                ("unreachable", AsyncMock(side_effect=RuntimeError("brain down"))),
                ("refused", AsyncMock(return_value=(500, {}))),
                ("same attractor", said("You're gonna love this")),
                ("echoed it back", said("I’m not done yet.")),
                ("ran long", said("well the thing is that I have not actually "
                                  "finished any of this yet you know")),
                ("empty", said("  "))):
            with self.subTest(case=label):
                with patch.object(server, "llm_call", stub):
                    out = asyncio.run(server.repair_spoken_line(
                        brief, "a room", "a room, a mug", None, 5))
                self.assertEqual(out, brief)

    def test_a_good_replacement_lands_inside_the_tag(self):
        """Only the words change - the speaker id, the tag and the delivery
        prose either side of it survive, because that is scene text H3 reads."""
        brief = ('She turns. (S1) says: <d>[English] You’re gonna regret this.</d> '
                 'Her lips close and the speaking stops.')
        with patch.object(server, "llm_call", AsyncMock(return_value=(
                200, {"choices": [{"message": {
                    "content": "yeah, the mug’s still in the sink"}}]}))):
            out = asyncio.run(server.repair_spoken_line(
                brief, "a kitchen", "a kitchen, a mug in the sink", None, 5))
        self.assertIn("<d>[English] yeah, the mug’s still in the sink</d>", out)
        self.assertIn("She turns. (S1) says:", out)
        self.assertIn("Her lips close and the speaking stops.", out)
        self.assertIsNone(server.spoken_line_fault("yeah, the mug’s still in the sink"))

    def test_words_the_user_wrote_are_never_rewritten(self):
        """"Obey the note's exact words" outranks every attractor: a quoted
        line in the note is the vision, however it scans."""
        brief = 'She grins. "You’re gonna regret this."'
        with patch.object(server, "llm_call", AsyncMock(return_value=(
                200, {"choices": [{"message": {"content": "whatever"}}]}))):
            out = asyncio.run(server.repair_spoken_line(
                brief, "a kitchen", None, 'have her say "You’re gonna regret this"', 5))
        self.assertEqual(out, brief)

    def test_neither_engine_may_conjure_a_prop(self):
        """One brief reached for a pen and a napkin "already folded in half",
        neither in the frame nor in her hands. The rule covered subjects and
        outfits but never objects, and hands are what break first."""
        for name in ("MOTION_SYSTEM", "H3_MOTION_SYSTEM"):
            with self.subTest(prompt=name):
                self.assertIn("appear from nowhere", getattr(server, name))


class MiniMaxH3CutPlanTests(unittest.TestCase):
    """Which of the two multi-shot mechanisms a request compiles to.

    Measured on one still, one script: chained 814s (identity lost) and 985s
    (identity held) against a single 362-frame pass at 677s that held identity
    best AND could actually cut. So the chain is for lengths a single
    generation cannot reach, not the default.
    """

    def test_requests_within_h3s_ceiling_become_one_generation(self):
        self.assertEqual(server.h3_cut_plan(3, 5), (15, [5, 10]))
        self.assertEqual(server.h3_cut_plan(2, 5), (10, [5]))
        self.assertEqual(server.h3_cut_plan(3, 5)[0], 15)

    def test_requests_past_the_ceiling_still_chain(self):
        for shots, seconds in ((2, 10), (3, 10), (4, 5), (2, 15), (8, 5)):
            with self.subTest(shots=shots, seconds=seconds):
                self.assertIsNone(server.h3_cut_plan(shots, seconds))

    def test_a_single_shot_is_never_a_cut_plan(self):
        self.assertIsNone(server.h3_cut_plan(1, 5))
        self.assertIsNone(server.h3_cut_plan(1, 15))

    def test_cut_times_use_h3s_timestamp_format(self):
        self.assertEqual(server.h3_cut_timestamp(5), "00:05.000")
        self.assertEqual(server.h3_cut_timestamp(10), "00:10.000")
        self.assertEqual(server.h3_cut_timestamp(65), "01:05.000")

    def test_shot_one_carries_no_timestamp(self):
        """H3's own rule - a timestamp on shot 1 is a malformed timeline."""
        out = server.compile_cut_script(["A.", "B.", "C."], [5, 10])
        self.assertTrue(out.startswith("[Shot 1] A."))
        self.assertNotIn("[Shot 1] At", out)

    def test_a_cut_past_the_end_of_the_clip_is_pulled_back(self):
        """H3 cannot act on a cut beyond the clip - it just mis-cuts silently.
        The planned times are already known, so the repair is arithmetic."""
        drifted = ("[Shot 1] At 00:00.000, she stands.\n\n"
                   "[Shot 2] At 00:09.000, the shot cuts to the street.\n\n"
                   "[Shot 3] At 00:20.000, the shot cuts to the cab.")
        fixed = server.normalise_cut_timeline(drifted, [5, 10])
        self.assertIn("[Shot 1] she stands.", fixed)          # never stamped
        self.assertIn("[Shot 2] At 00:05.000, the shot cuts to", fixed)
        self.assertIn("[Shot 3] At 00:10.000, the shot cuts to", fixed)
        self.assertNotIn("00:20.000", fixed)
        self.assertNotIn("00:09.000", fixed)

    def test_malformed_and_misnumbered_markers_are_rewritten(self):
        drifted = ("[Shot 1] she stands.\n\n"
                   "[shot 2] At 00:5.0, the shot cuts to the street.\n\n"
                   "[Shot 4] the shot cuts to the cab.")
        fixed = server.normalise_cut_timeline(drifted, [5, 10])
        self.assertIn("[Shot 2] At 00:05.000, the shot cuts to the street.", fixed)
        self.assertIn("[Shot 3] At 00:10.000, the shot cuts to the cab.", fixed)
        self.assertNotIn("00:5.0", fixed)
        self.assertNotIn("[Shot 4]", fixed)

    def test_prose_without_a_timeline_is_left_alone(self):
        """A one-shot brief has no markers and must not be mangled."""
        prose = "She rises from the crouch and looks into the lens."
        self.assertEqual(server.normalise_cut_timeline(prose, [5, 10]), prose)

    def test_single_pass_does_not_require_the_multishot_pack(self):
        """It runs on core ComfyUI nodes, so a missing pack must not block it -
        while a genuinely chained request still reports the missing pack."""
        with patch.dict(server._COMFY_NODES, {"names": set()}):
            self.assertEqual(server.validate_shot_count("h3", 3, 5), 3)
            with self.assertRaises(ValueError):
                server.validate_shot_count("h3", 3, 10)


class H3PromptAssemblyTests(unittest.TestCase):
    """The official trained structure (MiniMaxAI/MiniMax-H3 prompt guide),
    assembled deterministically around whatever the director wrote."""

    def test_bare_prose_is_wrapped_into_the_official_fields(self):
        out = server.assemble_h3_prompt("She turns from the window and smiles.")
        self.assertTrue(out.startswith(server.H3_I2VA_HEADER + "\n\n"))
        self.assertIn("integrated_multimodal_description: [Shot 1] She turns", out)
        self.assertIn("overall_soundscape:", out)
        self.assertTrue(out.endswith("non_diegetic_music: N/A"))

    def test_a_labeled_brief_only_gains_the_header(self):
        brief = ("integrated_multimodal_description: [Shot 1] Live-action, "
                 "cinematic, she turns.\n\noverall_soundscape: Rain on glass.\n\n"
                 "non_diegetic_music: N/A")
        out = server.assemble_h3_prompt(brief)
        self.assertEqual(out, server.H3_I2VA_HEADER + "\n\n" + brief)
        # idempotent - assembling twice must not double the header
        self.assertEqual(server.assemble_h3_prompt(out), out)

    def test_fl2va_header_names_picture_2_at_the_exact_final_second(self):
        out = server.assemble_h3_prompt("She reaches the door.",
                                        last_frame=True, seconds=8)
        first = out.splitlines()[0]
        # Ported verbatim: fl2va uses bare Picture/Shot with no brackets.
        self.assertIn("How the reference pictures align with the target video", first)
        self.assertIn("Picture 1 (from Shot 1) aligns with the 0.00-second mark", first)
        self.assertIn("Picture 2 (from Shot 1) aligns with the 8.00-second mark", first)
        self.assertNotIn("<Picture", first)

    def test_a_user_script_gets_the_header_and_nothing_creative(self):
        out = server.assemble_h3_prompt("[Shot 1] my own words", user_script=True)
        # 9.37: the no-score music field is not creative - the appended audio
        # contract used to carry it for scripts (wrong token), so the
        # assembler now guarantees exactly one on every path
        self.assertEqual(out, server.H3_I2VA_HEADER + "\n\n[Shot 1] my own words"
                              "\n\nnon_diegetic_music: N/A")
        self.assertNotIn("overall_soundscape", out)

    def test_slug_source_skips_header_and_shot_marker(self):
        out = server.assemble_h3_prompt("She turns from the window.")
        self.assertTrue(server.h3_slug_source(out).startswith("She turns"))

    def test_appended_dialogue_moves_into_the_description(self):
        # The director's recurring slips, verbatim shape from a real brief
        # (2026-08-11): square-bracket dialogue tags, and the spoken block
        # appended after the three fields as a fourth.
        brief = ("integrated_multimodal_description: [Shot 1] She dances.\n\n"
                 "overall_soundscape: Pavement crunch, dawn birdsong.\n\n"
                 "non_diegetic_music: N/A\n\n"
                 "(S1) says: [d]“Watch the boots.”</d> "
                 "— hair flying sideways.")
        out = server.assemble_h3_prompt(brief)
        desc = out.split("overall_soundscape:")[0]
        # The tag repair also normalizes the moved block to the trained form:
        # quotes stripped, honest language tag added.
        self.assertIn("(S1) says: <d>[English] Watch the boots.</d>", desc)
        self.assertNotIn("[d]", out)
        self.assertTrue(out.endswith("non_diegetic_music: N/A"))

    def test_dialogue_between_fields_moves_without_eating_the_music_field(self):
        brief = ("integrated_multimodal_description: [Shot 1] She dances.\n\n"
                 "overall_soundscape: Pavement crunch.\n\n"
                 "(S1) says: <d>“Watch the boots.”</d>\n\n"
                 "non_diegetic_music: N/A")
        out = server.assemble_h3_prompt(brief)
        desc = out.split("overall_soundscape:")[0]
        self.assertIn("Watch the boots", desc)
        self.assertNotIn("non_diegetic_music", desc)
        self.assertTrue(out.endswith("non_diegetic_music: N/A"))

    def test_a_user_script_keeps_its_own_dialogue_placement(self):
        script = ("[Shot 1] my words\n\noverall_soundscape: rain\n\n"
                  "(S1) says: [d]exactly as typed</d>")
        out = server.assemble_h3_prompt(script, user_script=True)
        self.assertIn(script, out)
        self.assertTrue(out.endswith("non_diegetic_music: N/A"))


class DialogueRepairTests(unittest.TestCase):
    """Every case is a REAL capture: the 2026-08-12 "I'm not late" render and
    the live-brain harness samples that motivated the repair."""

    def test_quotes_plus_mangled_tag_around_delivery_prose(self):
        body = ('(S1) says: “I’m not late,” d>she glances back '
                'at the strap — then continues walking.</d>')
        out = server.repair_h3_dialogue_tags(body)
        self.assertIn("says: <d>[English] I’m not late</d>", out)
        self.assertNotIn("d>she", out)
        self.assertIn("she glances back", out)      # prose survives, untagged
        self.assertEqual(out.count("<d>"), 1)
        self.assertEqual(out.count("</d>"), 1)

    def test_plain_quotes_get_tagged_and_prose_stays_out(self):
        out = server.repair_h3_dialogue_tags(
            '(S1) says: “Gotcha,” — lips part mid-sentence.')
        self.assertIn("says: <d>[English] Gotcha</d>", out)
        self.assertIn("lips part mid-sentence", out)

    def test_tagged_but_unlanguaged_line_gains_the_language_tag(self):
        out = server.repair_h3_dialogue_tags(
            '(S1) says: <d>“catch me at the gallery at nine”</d>')
        self.assertIn("<d>[English] catch me at the gallery at nine</d>", out)

    def test_correct_syntax_and_no_dialogue_pass_through_unchanged(self):
        for body in ('(S1) says: <d>[English] I packed the blue one</d> then '
                     'she turns.',
                     'She walks out of frame. The camera never moves.'):
            self.assertEqual(server.repair_h3_dialogue_tags(body), body)

    def test_assemble_h3_prompt_ships_the_repair(self):
        out = server.assemble_h3_prompt(
            'integrated_multimodal_description: [Shot 1] She stops. '
            '(S1) says: “I’m not late,” d>she glances back.</d>\n\n'
            'overall_soundscape: Footsteps echo.\n\nnon_diegetic_music: N/A')
        self.assertIn("says: <d>[English] I’m not late</d>", out)
        self.assertNotIn("d>she", out)

    def test_a_user_script_is_never_rewritten(self):
        script = '(S1) says: “exactly as I typed it”'
        out = server.assemble_h3_prompt(script, user_script=True)
        self.assertIn(script, out)


class MotionDirectorRoutingTests(unittest.TestCase):
    def test_each_engine_gets_its_own_system_prompt(self):
        # The prompts are engine dialects: H3 speaks <d> tags, 2.5 speaks the
        # official flowing paragraph, 2.3 keeps its original brief shape.
        self.assertIn("<d>[Language]", server.H3_MOTION_SYSTEM)
        self.assertIn("LTX 2.5", server.LTX25_MOTION_SYSTEM)
        self.assertIn("ONE FLOWING PARAGRAPH", server.LTX25_MOTION_SYSTEM)
        self.assertNotIn("<d>", server.LTX25_MOTION_SYSTEM)
        self.assertIn("LTX 2.3", server.MOTION_SYSTEM)


class LTX25Tests(unittest.TestCase):
    def test_builder_patches_the_official_graph_without_reshaping_it(self):
        from PIL import Image
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            Image.new("RGB", (832, 1216)).save(root / "input" / "prepared.png")
            with patch.object(server, "CDIR", root):
                graph, motion, info = server.build_ltx25_i2v(
                    "She turns toward the window.", 123, "prepared.png",
                    seconds=8)
        self.assertEqual(graph["33"]["inputs"]["value"], motion)
        self.assertEqual(graph["1"]["inputs"]["image"], "prepared.png")
        self.assertEqual(graph["3"]["inputs"]["noise_seed"], 123)
        self.assertEqual(graph["20"]["inputs"]["value"], 8)
        # The director's brief is final - the built-in enhancer must stay off.
        self.assertIs(graph["38"]["inputs"]["value"], False)
        # Canvas from the frame's own aspect at the official 0.9MP budget,
        # snapped to the /32 grid the graph's halving math expects.
        width, height = graph["30"]["inputs"]["value"], graph["18"]["inputs"]["value"]
        self.assertEqual((width % 32, height % 32), (0, 0))
        self.assertAlmostEqual(width * height / 1e6, 0.9, delta=0.12)
        self.assertAlmostEqual(width / height, 832 / 1216, delta=0.08)
        # 24fps stays the graph's own; the in-graph formula lands on 8k+1.
        self.assertEqual(graph["19"]["inputs"]["value"], 24)
        self.assertEqual((24 * 8 + 1) % 8, 1)
        self.assertIn("8s", info["size"])

    def test_builder_clamps_seconds_to_whole_grid_safe_values(self):
        from PIL import Image
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            Image.new("RGB", (1024, 1024)).save(root / "input" / "prepared.png")
            with patch.object(server, "CDIR", root):
                graph, _, _ = server.build_ltx25_i2v(
                    "slow pan", 7, "prepared.png", seconds=999)
        self.assertEqual(graph["20"]["inputs"]["value"],
                         server.LTX25_SECONDS_RANGE[1])

    def _ltx25(self, size=(832, 1216), **kw):
        from PIL import Image
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            Image.new("RGB", size).save(root / "input" / "prepared.png")
            with patch.object(server, "CDIR", root):
                return server.build_ltx25_i2v("she turns", 5, "prepared.png", **kw)

    def test_the_transformer_is_evicted_before_the_diffusion_decoder_runs(self):
        """LTX 2.5's video VAE is a DIFFUSION decoder built lazily at decode
        time, and ComfyUI does not evict the sampled 22B DiT first - so the
        decode OOMs inside the tiled path, where no tile size can help
        (Comfy-Org/ComfyUI#15606). The graph frees the transformer itself, and
        because the gate is a node it also pins the ordering: the decoder cannot
        be constructed until it has run."""
        with patch.dict(server._COMFY_NODES,
                        {"names": frozenset({server.LTX25_VRAM_GATE_NODE})}):
            graph, _, _ = self._ltx25()
        gate = graph[server.LTX25_VRAM_GATE_ID]
        self.assertEqual(gate["class_type"], "VRAM_Debug")
        self.assertIs(gate["inputs"]["unload_all_models"], True)
        self.assertIs(gate["inputs"]["empty_cache"], True)
        # It sits BETWEEN the refine sampler's video latent and the decode -
        # after all sampling, or it would evict the model still being sampled.
        self.assertEqual(gate["inputs"]["any_input"], ["27", 0])
        self.assertEqual(graph["32"]["inputs"]["samples"],
                         [server.LTX25_VRAM_GATE_ID, 0])
        self.assertEqual(graph["27"]["inputs"]["av_latent"], ["26", 0])

    def test_without_kjnodes_the_decode_falls_back_to_upstreams_wiring(self):
        """The gate is a mitigation, not a dependency: an install without
        KJNodes must render exactly as upstream does, not fail on a node class
        ComfyUI cannot resolve."""
        with patch.dict(server._COMFY_NODES, {"names": frozenset({"VAEDecodeTiled"})}):
            graph, _, _ = self._ltx25()
        self.assertNotIn(server.LTX25_VRAM_GATE_ID, graph)
        self.assertEqual(graph["32"]["inputs"]["samples"], ["27", 0])

    def test_missing_start_frame_is_a_user_facing_error(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            with patch.object(server, "CDIR", root):
                with self.assertRaisesRegex(ValueError, "missing from ComfyUI/input"):
                    server.build_ltx25_i2v("pan", 7, "gone.png")


class LTX25ClipUpscaleTests(unittest.TestCase):
    """The "LTX 2.5 2x" clip upscale mode: a generative 2x re-render ported
    from the community MiniMax H3 + LTX 2.5 graph, branching off the same
    build_upscale_video the VSR filter uses."""

    CFG = {"upscale": {"video_mode": "VSR High", "video_scale": 2.0}}
    SAGE = "LTX2MemoryEfficientSageAttentionPatch"

    def build(self, clip, mode=server.LTX25_UPSCALE_MODE, prompt=None,
              assets=all_video_assets, names=None, cfg=None):
        with patch.object(server, "load_config",
                          return_value=cfg or self.CFG), \
             patch.object(server, "_video_asset", side_effect=assets), \
             patch.dict(server._COMFY_NODES,
                        {"names": names if names is not None
                         else frozenset({self.SAGE})}):
            return server.build_upscale_video("test clip", 7, video=str(clip),
                                              mode=mode, prompt=prompt)

    def test_ltx25_mode_builds_the_latent_upscale_graph(self):
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            graph, _scene, info = self.build(clip, prompt="the original brief")
        self.assertEqual(graph["lu:load"]["inputs"]["video"], str(clip))
        self.assertEqual(graph["lu:noise"]["inputs"]["noise_seed"], 7)
        self.assertEqual(graph["lu:pos"]["inputs"]["text"], "the original brief")
        # The refine denoises the AV latent for lip sync, but the SAVED track
        # is the source clip's own audio - the re-decoded one sounds underwater.
        self.assertEqual(graph["lu:save"]["inputs"]["audio"], ["lu:load", 2])
        # And the clip keeps its own frame rate (H3 bakes audio at 24fps).
        self.assertEqual(graph["lu:save"]["inputs"]["frame_rate"], ["lu:info", 0])
        self.assertEqual(graph["lu:sched"]["inputs"]["denoise"], 0.15)
        self.assertEqual(graph["lu:lora"]["inputs"]["lora_name"],
                         server.LTX25_DETAILER_LORA)
        self.assertIn("LTX 2.5", info["upscaler"])

    def test_optional_detailer_lora_is_skipped_when_absent(self):
        def no_lora(kind, rel):
            return None if rel == server.LTX25_DETAILER_LORA else rel
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            graph, _scene, _info = self.build(clip, assets=no_lora)
        self.assertNotIn("lu:lora", graph)
        self.assertEqual(graph["lu:sage"]["inputs"]["model"], ["lu:unet", 0])

    def test_sage_patch_is_dropped_when_the_pack_is_missing(self):
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            graph, _scene, _info = self.build(clip,
                                              names=frozenset({"KSampler"}))
        self.assertNotIn("lu:sage", graph)
        self.assertEqual(graph["lu:sched"]["inputs"]["model"], ["lu:lora", 0])
        self.assertEqual(graph["lu:guider"]["inputs"]["model"], ["lu:lora", 0])

    def test_missing_25_stack_is_a_user_facing_error(self):
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "LTX 2.5 upscale needs"):
                self.build(clip, assets=lambda _kind, _rel: None)

    def test_configured_mode_routes_without_an_explicit_mode(self):
        cfg = {"upscale": {"video_mode": server.LTX25_UPSCALE_MODE,
                           "video_scale": 2.0}}
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            graph, _scene, _info = self.build(clip, mode=None, cfg=cfg)
        self.assertIn("lu:sample", graph)

    def test_vsr_path_is_untouched_and_ignores_the_prompt(self):
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            with patch.object(server, "load_config", return_value=self.CFG), \
                 patch.object(server, "_video_upscale_node",
                              return_value="DenoRTXVFXEasyUpscale"):
                graph, _scene, info = server.build_upscale_video(
                    "test clip", 7, video=str(clip), mode="VSR High",
                    prompt="ignored")
        self.assertIn("uv:vsr", graph)
        self.assertNotIn("lu:sample", graph)
        self.assertEqual(info["upscaler"], "RTX VSR High")


class ClipFrameRateTests(unittest.TestCase):
    """9.53: frame-rate finishing on the clip finisher. RIFE interpolates in
    the SAME graph as the VSR pass - splice uv:rife (+ uv:decimate for
    non-multiples) between uv:load and uv:vsr, set the combine's frame_rate
    to the literal target, and the copied audio track keeps sync. The source
    rate is read from the file (clip_shape), never assumed 24: with source s
    and target t, g = gcd(s, t), multiplier = t//g, select_every_nth = s//g."""

    CFG = {"upscale": {"video_mode": "VSR High", "video_scale": 2.0,
                       "video_fps": 0}}
    RIFE = "RIFE VFI"
    # The proven H3 clip: 5.167 s at 24 fps.
    SHAPE = (768, 1024, 124, 24)

    def build(self, clip, cfg=None, names=None, shape=SHAPE, **kwargs):
        with patch.object(server, "load_config",
                          return_value=cfg or self.CFG), \
             patch.object(server, "_video_upscale_node",
                          return_value="DenoRTXVFXEasyUpscale"), \
             patch.object(server, "clip_shape", return_value=shape), \
             patch.dict(server._COMFY_NODES,
                        {"names": names if names is not None
                         else frozenset({self.RIFE})}):
            return server.build_upscale_video("test clip", 7, video=str(clip),
                                              **kwargs)

    def test_24_to_30_interpolates_x5_and_keeps_every_4th(self):
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            graph, _scene, info = self.build(clip, fps=30)
        rife = graph["uv:rife"]
        self.assertEqual(rife["class_type"], "RIFE VFI")
        self.assertEqual(rife["inputs"]["frames"], ["uv:load", 0])
        self.assertEqual(rife["inputs"]["ckpt_name"], "rife49.pth")
        self.assertEqual(rife["inputs"]["multiplier"], 5)
        self.assertTrue(rife["inputs"]["fast_mode"])
        self.assertTrue(rife["inputs"]["ensemble"])
        self.assertEqual(rife["inputs"]["scale_factor"], 1.0)
        self.assertEqual(rife["inputs"]["clear_cache_after_n_frames"], 10)
        self.assertEqual(graph["uv:decimate"]["class_type"],
                         "VHS_SelectEveryNthImage")
        self.assertEqual(graph["uv:decimate"]["inputs"],
                         {"images": ["uv:rife", 0], "select_every_nth": 4,
                          # required by the installed VHS build - omitting it
                          # failed validation at queue time, which broke every
                          # rate that is not a whole multiple of 24 (30 and 60).
                          "skip_first_images": 0})
        # interpolate at the SMALL size, then enlarge.
        self.assertEqual(graph["uv:vsr"]["inputs"]["images"],
                         ["uv:decimate", 0])
        # The literal target, not the source rate - duration and audio hold.
        self.assertEqual(graph["uv:save"]["inputs"]["frame_rate"], 30)
        self.assertEqual(graph["uv:save"]["inputs"]["audio"], ["uv:load", 2])
        self.assertEqual(info["fps"], 30)
        self.assertEqual(info["frames"], 154)      # ceil((5*123+1) / 4)
        self.assertEqual(info["upscaler"], "RTX VSR High · 30 fps")

    def test_24_to_48_doubles_without_a_decimate(self):
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            graph, _scene, info = self.build(clip, fps=48)
        self.assertEqual(graph["uv:rife"]["inputs"]["multiplier"], 2)
        self.assertNotIn("uv:decimate", graph)
        self.assertEqual(graph["uv:vsr"]["inputs"]["images"], ["uv:rife", 0])
        self.assertEqual(graph["uv:save"]["inputs"]["frame_rate"], 48)
        self.assertEqual(info["fps"], 48)
        self.assertEqual(info["frames"], 247)      # 2*123+1
        self.assertEqual(info["upscaler"], "RTX VSR High · 48 fps")

    def test_24_to_60_comes_from_the_config_when_no_fps_is_posted(self):
        cfg = {"upscale": {"video_mode": "VSR High", "video_scale": 2.0,
                           "video_fps": 60}}
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            graph, _scene, info = self.build(clip, cfg=cfg)
        self.assertEqual(graph["uv:rife"]["inputs"]["multiplier"], 5)
        self.assertEqual(graph["uv:decimate"]["inputs"]["select_every_nth"], 2)
        self.assertEqual(graph["uv:save"]["inputs"]["frame_rate"], 60)
        self.assertEqual(info["frames"], 308)      # ceil((5*123+1) / 2)

    def test_native_rate_splices_nothing(self):
        # Unset, explicit 0, and a target equal to the clip's own rate all
        # keep the template exactly as it ships.
        for fps in (None, 0, 24):
            with self.subTest(fps=fps), TemporaryDirectory() as td:
                clip = Path(td) / "clip.mp4"
                clip.write_bytes(b"x")
                graph, _scene, info = self.build(clip, fps=fps)
                self.assertNotIn("uv:rife", graph)
                self.assertNotIn("uv:decimate", graph)
                self.assertEqual(graph["uv:vsr"]["inputs"]["images"],
                                 ["uv:load", 0])
                self.assertEqual(graph["uv:save"]["inputs"]["frame_rate"],
                                 ["uv:info", 0])
                self.assertNotIn("fps", info)
                self.assertEqual(info["upscaler"], "RTX VSR High")
                self.assertEqual(info["frames"], 124)

    def test_fps_only_at_unit_scale_names_no_upscale(self):
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            graph, _scene, info = self.build(clip, scale=1.0, fps=48)
        self.assertIn("uv:rife", graph)
        self.assertEqual(info["upscaler"], "48 fps")

    def test_ltx_mode_ignores_fps(self):
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            with patch.object(server, "load_config", return_value=self.CFG), \
                 patch.object(server, "_video_asset",
                              side_effect=all_video_assets), \
                 patch.dict(server._COMFY_NODES, {"names": frozenset()}):
                graph, _scene, _info = server.build_upscale_video(
                    "test clip", 7, video=str(clip),
                    mode=server.LTX25_UPSCALE_MODE, fps=30)
        self.assertNotIn("uv:rife", graph)
        self.assertIn("lu:sample", graph)
        self.assertEqual(graph["lu:save"]["inputs"]["frame_rate"],
                         ["lu:info", 0])

    def test_a_missing_rife_pack_is_a_loud_error_never_a_silent_24(self):
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            with self.assertRaisesRegex(
                    ValueError, "frame interpolation needs "
                                "ComfyUI-Frame-Interpolation"):
                self.build(clip, fps=48, names=frozenset({"KSampler"}))

    def test_an_unreadable_clip_rate_is_a_loud_error_too(self):
        with TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            clip.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "cannot read the clip"):
                self.build(clip, fps=48, shape=None)

    def test_settings_clamp_snaps_to_the_offered_rates(self):
        for posted, want in ((0, 0), (30, 30), (48, 48), (60, 60),
                             (1, 0), (25, 30), (47, 48), (100, 60)):
            with self.subTest(posted=posted):
                saved = []
                cfg = {"llm": {}, "critic": {}, "edit": {}, "vae": {},
                       "pid": {}, "video": {}, "extra_model_roots": [],
                       "upscale": {"video_mode": "VSR High",
                                   "video_scale": 2.0, "video_fps": 0},
                       "comfy_editor": False, "comfy_console": "tui",
                       "explicit": "auto", "vram_profile": "auto"}
                with patch.object(server, "load_config", return_value=cfg), \
                     patch.object(server, "save_config",
                                  side_effect=lambda c: saved.append(c)):
                    response = asyncio.run(server.settings_post(
                        FakeRequest({"upscale": {"video_fps": posted}})))
                self.assertEqual(response.status, 200)
                self.assertEqual(saved[0]["upscale"]["video_fps"], want)

    def test_settings_publishes_the_rate_options(self):
        self.assertEqual(list(server.UPSCALE_VIDEO_FPS_OPTIONS),
                         [0, 30, 48, 60])


class CameraNoteRepairTests(unittest.TestCase):
    """A DIRECTOR'S NOTE pinning the camera is the instruction models drop
    most (11/18 hinted briefs in the 3-model bake-off) - the deterministic
    repair restates it. Repair-only by measurement: a fourth contract point
    collapsed brief length instead (Gemma, 2026-08-12)."""

    # Real shape: every H3 brief contains this camera-mention boilerplate,
    # which must NOT satisfy the gate.
    BRIEF = ("integrated_multimodal_description: Live-action - the camera "
             "cuts into a scene already underway. She winks and walks out "
             "of frame to the left.\n\n"
             "overall_soundscape: Footsteps echo.\n\nnon_diegetic_music: N/A")
    HINT = "She winks, then walks out of frame. The camera never moves."

    def test_static_pin_is_restated_inside_the_description_field(self):
        out = server.repair_camera_note(self.BRIEF, self.HINT)
        self.assertIn("The camera holds locked and level", out)
        # inside the description field, not appended after the other fields
        self.assertLess(out.find("locked and level"),
                        out.find("overall_soundscape:"))

    def test_a_brief_that_honored_the_pin_is_left_alone(self):
        honored = self.BRIEF.replace(
            "She winks", "The camera holds locked and level. She winks")
        self.assertEqual(server.repair_camera_note(honored, self.HINT), honored)

    def test_no_hint_and_non_camera_hints_change_nothing(self):
        self.assertEqual(server.repair_camera_note(self.BRIEF, None), self.BRIEF)
        self.assertEqual(
            server.repair_camera_note(self.BRIEF, "She winks and leaves."),
            self.BRIEF)

    def test_a_directed_camera_move_is_never_rewritten(self):
        # Only the static case repairs deterministically - inventing language
        # for "slow push-in" would be worse than trusting the model.
        hint = "Slow push-in toward her face as she speaks."
        self.assertEqual(server.repair_camera_note(self.BRIEF, hint), self.BRIEF)

    def test_ltx_flowing_paragraph_gets_the_sentence_appended(self):
        brief = "She winks at the lens and strolls left, coat swinging."
        out = server.repair_camera_note(brief, self.HINT)
        self.assertTrue(out.endswith("for the entire take."))


class SeedLockRerollTests(unittest.TestCase):
    """Re-roll draws fresh dice unless the card's seed is locked - then the
    entry's exact seed rides back in through the spec."""

    ENTRY = {"id": "abc12345", "template": "realism", "scene": "a shot",
             "seed": 424242, "count": 1, "spec": {"standing": True}}

    def roll(self, body):
        submit = AsyncMock()
        with patch.object(server.HUB, "ledger_read",
                          return_value=[dict(self.ENTRY)]), \
             patch.object(server.HUB, "submit", submit):
            async def run():
                await server.reroll(FakeRequest(body))
                await asyncio.sleep(0)      # let the created task settle
            asyncio.run(run())
        return submit.call_args

    def test_plain_reroll_never_carries_a_seed(self):
        call = self.roll({"id": "abc12345"})
        self.assertNotIn("seed", call.args[4])

    def test_locked_reroll_replays_the_entrys_exact_seed(self):
        call = self.roll({"id": "abc12345", "lock_seed": True})
        self.assertEqual(call.args[4]["seed"], 424242)

    def test_locked_reroll_keeps_the_exact_seed_over_a_rounded_echo(self):
        # JSON integers past 2**53 reach the browser as doubles, so a locked
        # seed above it echoes back rounded (2**53 + 1 arrives as 2**53) -
        # the ledger's exact value wins, not the client's copy of it.
        entry = {**self.ENTRY, "seed": 2**53 + 1}
        submit = AsyncMock()
        with patch.object(server.HUB, "ledger_read", return_value=[entry]), \
             patch.object(server.HUB, "submit", submit):
            async def run():
                await server.reroll(FakeRequest({"id": "abc12345",
                                                 "lock_seed": True,
                                                 "seed": 2**53}))
                await asyncio.sleep(0)
            asyncio.run(run())
        self.assertEqual(submit.call_args.args[4]["seed"], 2**53 + 1)

    def test_lock_on_a_seedless_entry_stays_a_fresh_draw(self):
        entry = {**self.ENTRY, "seed": None}
        submit = AsyncMock()
        with patch.object(server.HUB, "ledger_read", return_value=[entry]), \
             patch.object(server.HUB, "submit", submit):
            async def run():
                await server.reroll(FakeRequest({"id": "abc12345",
                                                 "lock_seed": True}))
                await asyncio.sleep(0)
            asyncio.run(run())
        self.assertNotIn("seed", submit.call_args.args[4])


if __name__ == "__main__":
    unittest.main()
