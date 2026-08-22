"""Brief 9.12 - the ref2va lane: put THIS subject in a new scene.

The model chip is the lane switch, per render: a ref2va build gets the
reference graph (MiniMaxH3ReferenceToVideo) and the six-section trained
prompt format; an fl2va build keeps the proven first-frame graph. Everything
here is structural validation against the node source or fixed strings
through the assembler - the live-machine rule forbids queueing a render.
"""
import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from PIL import Image


_SPEC = spec_from_file_location(
    "pixal_server_ref2va", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

# The fl2va golden, captured at briefed-at (cd86a8e, 2026-08-22) BEFORE any
# 9.12 edit - a golden captured after the fact just records your own output.
# The capture artifact also lives at briefs/ref/fl2va_golden_briefed_at.json.
GOLDEN = {
    "wellformed": "For the target video, at 0.00 seconds into the target "
                  "video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
                  "integrated_multimodal_description: [Shot 1] Live-action, "
                  "natural real-time motion. She turns from the window, rain "
                  "sliding down the glass behind her, and says: <d>[English] "
                  "We leave at dawn.</d> Her jaw settles as she reaches for "
                  "the coat.\n\noverall_soundscape: Rain against the window, "
                  "low room tone.\n\nnon_diegetic_music: N/A",
    "wellformed_bridge": "How the reference pictures align with the target "
                  "video — Picture 1 (from Shot 1) aligns with the 0.00-second "
                  "mark of the target video; Picture 2 (from Shot 1) aligns "
                  "with the 5.00-second mark of the target video.\n\n"
                  "integrated_multimodal_description: [Shot 1] Live-action, "
                  "natural real-time motion. She turns from the window, rain "
                  "sliding down the glass behind her, and says: <d>[English] "
                  "We leave at dawn.</d> Her jaw settles as she reaches for "
                  "the coat.\n\noverall_soundscape: Rain against the window, "
                  "low room tone.\n\nnon_diegetic_music: N/A",
    "bare_prose": "For the target video, at 0.00 seconds into the target "
                  "video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
                  "integrated_multimodal_description: [Shot 1] She crosses "
                  "the room and sits.\n\noverall_soundscape: The natural "
                  "ambience of the scene and the sounds of the visible "
                  "actions, synchronized.\n\nnon_diegetic_music: N/A",
    "user_script": "For the target video, at 0.00 seconds into the target "
                  "video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
                  "[Shot 1] She looks up. (S1) says: <d>[English] Hello "
                  "there.</d> She smiles.",
    "style_splice": "For the target video, at 0.00 seconds into the target "
                  "video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
                  "integrated_multimodal_description: [Shot 1] 2D-animated, "
                  "natural real-time motion. She turns from the window, rain "
                  "sliding down the glass behind her, and says: <d>[English] "
                  "We leave at dawn.</d> Her jaw settles as she reaches for "
                  "the coat.\n\noverall_soundscape: Rain against the window, "
                  "low room tone.\n\nnon_diegetic_music: N/A",
    "slug": "Live-action, natural real-time motion. She turns from the "
            "window, rain sliding down the glass behind her, and says: "
            "<d>[English] We leave at dawn.</d> Her jaw settles as she reaches "
            "for the coat.\n\noverall_soundscape: Rain against the window, "
            "low room tone.\n\nnon_diegetic_music: N/A",
}
GOLDEN["style_splice_none"] = GOLDEN["wellformed"]

REF2VA_REL = "Minimax H3\\minimax_h3_ref2va_pruned_int8_convrot.safetensors"


def all_video_assets(_kind, _rel):
    return _rel


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def catalog_with(*rels):
    def catalog(kind=None):
        if kind != "diffusion_models":
            return []
        return [{"rel": rel, "kind": "diffusion_models", "mtime": 1}
                for rel in rels]
    return catalog


def build_ref2v(brief, refs=("ref0.png",), **kw):
    """A one- or two-ref graph with all assets resolving and staged refs."""
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        for name in refs:
            Image.new("RGB", (1920, 1080), (25, 80, 140)).save(root / "input" / name)
        with patch.object(server, "CDIR", root), \
             patch.object(server, "_video_asset", side_effect=all_video_assets):
            kw.setdefault("seconds", 5)
            kw.setdefault("width", 1344)
            kw.setdefault("height", 768)
            kw.setdefault("model", "ref2va")
            return server.build_h3_ref2v(brief, 987, list(refs), **kw)


# A complete, correct six-section brief in the canonical block shape - the
# shape the model card's case-Ref2VA prompt and the guide's §7 example share.
def director_brief(desc="[Shot 1] <Subject 1> crosses the new market square, "
                          "coat catching the wind, and says: <d>[English] "
                          "Keep the change.</d> Her jaw settles as she turns "
                          "toward the stalls.",
                   subjects=("<Subject 1> is the woman in <Picture 1>, with "
                             "the same face, copper hair and green coat.",),
                   retention=("<Subject 1> (appears in [Shot 1]): "
                              "fully_preserved - her face, copper hair and "
                              "green coat are retained.",),
                   two_refs=False):
    subjects = list(subjects)
    retention = list(retention)
    if two_refs:
        subjects.append("<Subject 2> is the terrier in <Picture 2>, with the "
                        "same wiry grey fur.")
        retention.append("<Subject 2> (appears in [Shot 1]): fully_preserved "
                         "- the terrier's wiry grey fur is retained.")
    return ("subject_definitions:\n" + "\n".join(subjects) + "\n\n"
            "summary:\n[reference generation] The target video carries "
            "<Subject 1> into a market square.\n\n"
            "retention_analysis:\n" + "\n".join(retention) + "\n\n"
            "detailed_description:\n" + desc + "\n\n"
            "overall_soundscape:\nMarket crowd murmur, distant gulls.\n\n"
            "non_diegetic_music:\nN/A")


class VariantPlumbingTests(unittest.TestCase):
    def test_both_stock_chips_are_listed_stock_first(self):
        with patch.object(server, "model_catalog",
                          side_effect=catalog_with(server.H3_MODEL, REF2VA_REL)):
            options = server.h3_model_options()
        self.assertEqual([o["id"] for o in options], ["fl2va", "ref2va"])
        self.assertEqual([o["label"] for o in options], ["FL2VA", "REF2VA"])
        self.assertEqual(options[0]["rel"], server.H3_MODEL)
        self.assertEqual(options[1]["rel"], REF2VA_REL)

    def test_both_stock_chips_survive_a_bare_catalog(self):
        # The 8.2 legacy-id guarantee, extended: selection and validation must
        # name both stock builds on a machine with neither file.
        with patch.object(server, "model_catalog", return_value=[]):
            options = server.h3_model_options()
        self.assertEqual([o["id"] for o in options], ["fl2va", "ref2va"])
        self.assertEqual(server.h3_model_rel("ref2va"), server.H3_REF2V_MODEL)
        self.assertEqual(server.h3_model_variant("ref2va"), "ref2va")

    def test_finetunes_of_either_lane_get_a_chip_and_a_clean_label(self):
        with patch.object(server, "model_catalog", side_effect=catalog_with(
                server.H3_MODEL, REF2VA_REL,
                "Minimax H3\\10Eros_Max_FL2VA_skip_edges.safetensors",
                "Minimax H3\\surrealism_ref2va_v2.safetensors")):
            options = server.h3_model_options()
        ids = [o["id"] for o in options]
        self.assertEqual(ids[:2], ["fl2va", "ref2va"])
        # the id is the full lowercase stem (stable across rescans); the
        # LABEL drops the packaging tokens, including "ref2va"
        self.assertIn("10eros_max_fl2va_skip_edges", ids)
        self.assertIn("surrealism_ref2va_v2", ids)
        by_id = {o["id"]: o for o in options}
        self.assertEqual(by_id["surrealism_ref2va_v2"]["label"], "Surrealism V2")
        self.assertIn("REF2VA", by_id["surrealism_ref2va_v2"]["description"])
        self.assertIn("FL2VA", by_id["10eros_max_fl2va_skip_edges"]["description"])

    def test_variant_precedence_is_exact_then_ref2va_then_fl2va(self):
        with patch.object(server, "model_catalog", side_effect=catalog_with(
                server.H3_MODEL, REF2VA_REL,
                "Minimax H3\\merged_fl2va_ref2va.safetensors",
                "Minimax H3\\plain_fl2va_tune.safetensors")):
            # (a) exact stock rels map to their own variants
            self.assertEqual(server.h3_model_variant("fl2va"), "fl2va")
            self.assertEqual(server.h3_model_variant("ref2va"), "ref2va")
            # (b) a both-token finetune lands in ref2va, on purpose (9.0 trap 6)
            self.assertEqual(server.h3_model_variant("merged_fl2va_ref2va"),
                             "ref2va")
            # (c) a plain fl2va finetune stays fl2va
            self.assertEqual(server.h3_model_variant("plain_fl2va_tune"), "fl2va")
            # (d) unknown ids are None, as today
            self.assertIsNone(server.h3_model_variant("wan2"))

    def test_speed_modes_carry_the_variant_gates(self):
        modes = {m["id"]: m for m in server.H3_SPEED_MODES}
        # ref2va IS quality at 20 steps; refusing it the quality id would
        # refuse the only mode it has.
        self.assertEqual(tuple(modes["quality"]["variants"]), ("fl2va", "ref2va"))
        # every distillation rung is fl2va-only: no ref2v turbo LoRA on disk
        for rung in ("turbo8", "turbo4", "turbo_v4"):
            with self.subTest(rung=rung):
                self.assertEqual(tuple(modes[rung]["variants"]), ("fl2va",))

    def test_hmnsfw_stays_fl2va_only(self):
        self.assertEqual(server.H3_VIDEO_LORAS[0]["variants"], ("fl2va",))
        self.assertEqual(server.h3_video_lora_options("ref2va"), [])
        self.assertEqual([r["name"] for r in server.h3_video_lora_options("fl2va")],
                         [server.H3_HMNSFW_LORA])
        # its own description says FL2VA, so a ref2va plan naming it refuses
        plan = {"version": 1, "mode": "replace", "engine": "h3", "model": "ref2va",
                "entries": [{"name": server.H3_HMNSFW_LORA, "enabled": True}]}
        with self.assertRaisesRegex(ValueError, "not compatible.*REF2VA"):
            server.validate_video_lora_plan("h3", "ref2va", plan)

    def test_per_chip_availability_tracks_the_picked_build(self):
        # Only the fl2va transformer is missing: its chip greys, the ref2va
        # chip and the engine stay available - and vice versa. A machine must
        # not fail the availability check on a file its lane never needed.
        def no_fl2va(kind, rel):
            return None if rel == server.H3_MODEL else rel

        with patch.object(server, "_video_asset", side_effect=no_fl2va):
            h3 = next(e for e in server.video_engine_options() if e["id"] == "h3")
        chips = {m["id"]: m["available"] for m in h3["models"]}
        self.assertFalse(chips["fl2va"])
        self.assertTrue(chips["ref2va"])
        self.assertTrue(h3["available"])


class Ref2VAGraphTests(unittest.TestCase):
    """Accept 2: the graph, structurally. Input names frozen from the node
    source (comfy_extras/nodes_minimax_h3.py:164-198, re-verified 2026-08-22):
    required clip/vae/audio_vae/prompt/width/height/length/ref_image_size;
    Autogrows ref_images.ref_image_N (max 9), ref_videos.ref_video_N,
    ref_video_audios.ref_video_audio_N, ref_audios.ref_audio_N (max 3 each),
    arriving as flat dotted keys in the API format."""

    REQUIRED = {"clip", "vae", "audio_vae", "prompt", "width", "height",
                "length", "ref_image_size"}

    def test_node6_is_the_reference_node_with_flat_dotted_keys(self):
        for refs in (("ref0.png",), ("ref0.png", "ref1.png")):
            with self.subTest(refs=len(refs)):
                graph, _, info = build_ref2v(director_brief(two_refs=len(refs) > 1),
                                             refs)
                node = graph["6"]
                self.assertEqual(node["class_type"], "MiniMaxH3ReferenceToVideo")
                inputs = node["inputs"]
                self.assertEqual(inputs["clip"], ["2", 0])
                self.assertEqual(inputs["vae"], ["3", 0])
                # the fl2va node has no audio_vae input; this one does
                self.assertEqual(inputs["audio_vae"], ["4", 0])
                for i in range(len(refs)):
                    self.assertEqual(inputs[f"ref_images.ref_image_{i}"],
                                     ["5" if i == 0 else f"5{chr(ord('a') + i)}", 0])
                # every input name is one the node declares - nothing else
                self.assertEqual(
                    set(inputs) - self.REQUIRED,
                    {f"ref_images.ref_image_{i}" for i in range(len(refs))})
                self.assertEqual(info["references"], len(refs))

    def test_no_unwired_ref_slots_and_no_frame_keys(self):
        graph, _, _ = build_ref2v(director_brief(), ("ref0.png",))
        keys = set(graph["6"]["inputs"])
        # an unwired Autogrow slot is omitted, never present-but-empty
        self.assertFalse(any(k.startswith(("ref_videos", "ref_audios",
                                           "ref_video_audios"))
                             for k in keys))
        self.assertFalse(any(k.endswith(("_1", "_2")) for k in keys))
        # the reference node has no frame-anchor inputs at all
        self.assertNotIn("first_frame", keys)
        self.assertNotIn("last_frame", keys)
        self.assertEqual(graph["6"]["inputs"]["ref_image_size"], "match")

    def test_the_unet_points_at_the_ref2va_build(self):
        graph, _, _ = build_ref2v(director_brief(), ("ref0.png",))
        self.assertEqual(graph["1"]["inputs"]["unet_name"], server.H3_REF2V_MODEL)

    def test_the_spine_and_vhs_tail_are_byte_identical_to_fl2va(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                fl2va, _, _ = server.build_h3_i2v(
                    "She turns toward the window.", 987, "prepared.png",
                    seconds=5, width=1344, height=768, model="fl2va")
        ref2v, _, _ = build_ref2v(director_brief(), ("ref0.png",))
        # Nodes 7-13 are the proven sampler spine; 14 is the VHS tail with
        # only the filename prefix differing between lanes.
        for node_id in ("7", "8", "9", "10", "11", "12", "13"):
            self.assertEqual(ref2v[node_id], fl2va[node_id], node_id)
        tail = dict(ref2v["14"]["inputs"])
        expected = dict(fl2va["14"]["inputs"])
        self.assertTrue(tail.pop("filename_prefix").startswith("pixal_dm/h3_ref_"))
        self.assertTrue(expected.pop("filename_prefix").startswith("pixal_dm/h3_"))
        self.assertEqual(ref2v["14"]["class_type"], fl2va["14"]["class_type"])
        self.assertEqual(tail, expected)

    def test_every_link_resolves(self):
        graph, _, _ = build_ref2v(director_brief(two_refs=True),
                                  ("ref0.png", "ref1.png"))
        for node_id, node in graph.items():
            for value in node.get("inputs", {}).values():
                if isinstance(value, list) and len(value) == 2 \
                        and isinstance(value[0], str):
                    self.assertIn(value[0], graph, f"{node_id} has bad link {value}")

    def test_the_canvas_derives_from_the_reference_when_unspecified(self):
        # No prepared frame defines the canvas in this lane; the still's own
        # aspect goes through the same adaptive-canvas logic.
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            Image.new("RGB", (1080, 1920), (0, 0, 0)).save(root / "input" / "r.png")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                graph, _, info = server.build_h3_ref2v(
                    director_brief(), 7, ["r.png"], seconds=5, model="ref2va")
        self.assertEqual(graph["6"]["inputs"]["width"], 768)
        self.assertEqual(graph["6"]["inputs"]["height"], 1344)
        self.assertEqual(info["size"], "768x1344")


class LaneIsolationTests(unittest.TestCase):
    """Accept 3: an fl2va chip builds the fl2va graph, a ref2va chip the
    ref2va graph, and every crossing path refuses by name."""

    def test_each_chip_builds_its_own_graph(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            Image.new("RGB", (1344, 768)).save(root / "input" / "ref0.png")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                fl2va, _, info_f = server.build_h3_i2v(
                    "She turns.", 1, "prepared.png", seconds=5,
                    width=1344, height=768, model="fl2va")
                ref2v, _, info_r = server.build_h3_ref2v(
                    director_brief(), 1, ["ref0.png"], seconds=5,
                    width=1344, height=768, model="ref2va")
        self.assertEqual(fl2va["6"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(ref2v["6"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(info_f["model_variant"], "fl2va")
        self.assertEqual(info_r["model_variant"], "ref2va")

    def test_the_reciprocal_guards(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            Image.new("RGB", (1344, 768)).save(root / "input" / "ref0.png")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                with self.assertRaisesRegex(ValueError, "ref2va build"):
                    server.build_h3_i2v("She turns.", 1, "prepared.png", seconds=5,
                                        width=1344, height=768, model="ref2va")
                with self.assertRaisesRegex(ValueError, "not a ref2va build"):
                    server.build_h3_ref2v(director_brief(), 1, ["ref0.png"],
                                          seconds=5, width=1344, height=768,
                                          model="fl2va")
                with self.assertRaisesRegex(ValueError, "FL2VA-only"):
                    server.build_h3_multishot("One.\n---\nTwo.", 1, "prepared.png",
                                              seconds=5, width=1344, height=768,
                                              model="ref2va")

    def test_a_both_token_finetune_takes_the_ref2va_lane(self):
        with patch.object(server, "model_catalog", side_effect=catalog_with(
                REF2VA_REL, "Minimax H3\\merged_fl2va_ref2va.safetensors")):
            self.assertEqual(server.h3_model_variant("merged_fl2va_ref2va"),
                             "ref2va")
            with TemporaryDirectory() as td:
                root = Path(td)
                (root / "input").mkdir()
                (root / "input" / "prepared.png").write_bytes(b"prepared")
                Image.new("RGB", (1344, 768)).save(root / "input" / "ref0.png")
                with patch.object(server, "CDIR", root), \
                     patch.object(server, "_video_asset",
                                  side_effect=all_video_assets):
                    with self.assertRaisesRegex(ValueError, "ref2va build"):
                        server.build_h3_i2v("She turns.", 1, "prepared.png",
                                            seconds=5, width=1344, height=768,
                                            model="merged_fl2va_ref2va")
                    graph, _, info = server.build_h3_ref2v(
                        director_brief(), 1, ["ref0.png"], seconds=5,
                        width=1344, height=768, model="merged_fl2va_ref2va")
                self.assertEqual(graph["1"]["inputs"]["unet_name"],
                                 "Minimax H3\\merged_fl2va_ref2va.safetensors")
                self.assertEqual(info["model_variant"], "ref2va")

    def test_shots_over_one_are_refused_before_any_cut_plan(self):
        # The cut-plan path hardcodes template="h3_i2v" for a truthy plan, so
        # the refusal must land inside validate_shot_count, upstream of it.
        with self.assertRaisesRegex(ValueError, "single-shot"):
            server.validate_shot_count("h3", 2, 5, "ref2va")
        self.assertEqual(server.validate_shot_count("h3", 1, 5, "ref2va"), 1)
        # fl2va keeps its multishot
        self.assertEqual(server.validate_shot_count("h3", 2, 5, "fl2va"), 2)

    def test_a_distillation_mode_on_a_ref2va_chip_is_a_400_not_a_fallback(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "input").mkdir()
            Image.new("RGB", (1920, 1080)).save(root / "output" / "still.png")
            entry = {"id": "abc123", "scene": "the subject at a workbench",
                     "images": [{"filename": "still.png", "subfolder": "",
                                 "media": "image"}]}
            submit = AsyncMock(return_value={"id": "videojob", "error": None})

            async def run(body):
                response = await server.animate(FakeRequest(body))
                await asyncio.sleep(0)
                return response

            base = {"id": "abc123", "cid": "cid1", "engine": "h3",
                    "model": "ref2va", "seconds": 5, "hint": "she lifts the tool"}
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "validate_video_selection",
                              return_value=("h3", "ref2va", 5, None)), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets), \
                 patch.object(server, "direct_motion",
                              AsyncMock(return_value=("a brief", True))), \
                 patch.object(server.HUB, "ledger_read", return_value=[entry]), \
                 patch.object(server.HUB, "broadcast"), \
                 patch.object(server.HUB, "submit", submit):
                for ask in ({"speed": "turbo4"}, {"speed": "turbo8"},
                            {"turbo": True}):
                    with self.subTest(ask=ask):
                        response = asyncio.run(run({**base, **ask}))
                        self.assertEqual(response.status, 400)
                        self.assertIn("Quality", json.loads(response.text)["error"])
                submit.assert_not_awaited()
                # quality is the one mode ref2va has, and it is accepted
                response = asyncio.run(run({**base, "speed": "quality"}))
                self.assertEqual(response.status, 200)
                submit.assert_awaited_once()
                self.assertEqual(submit.await_args.args[2], "h3_ref2v")
                self.assertEqual(submit.await_args.args[4]["turbo"], "quality")

    def test_a_bridge_is_refused_on_a_ref2va_chip(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "input").mkdir()
            Image.new("RGB", (1920, 1080)).save(root / "output" / "still.png")
            entry = {"id": "abc123", "scene": "the subject",
                     "images": [{"filename": "still.png", "subfolder": "",
                                 "media": "image"}]}
            submit = AsyncMock()

            async def run():
                return await server.animate(FakeRequest({
                    "id": "abc123", "cid": "cid1", "engine": "h3",
                    "model": "ref2va", "seconds": 5, "last_id": "abc123"}))

            with patch.object(server, "CDIR", root), \
                 patch.object(server, "validate_video_selection",
                              return_value=("h3", "ref2va", 5, None)), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets), \
                 patch.object(server.HUB, "ledger_read", return_value=[entry]), \
                 patch.object(server.HUB, "broadcast"), \
                 patch.object(server.HUB, "submit", submit):
                response = asyncio.run(run())
        self.assertEqual(response.status, 400)
        self.assertIn("no end frame", json.loads(response.text)["error"])
        submit.assert_not_awaited()


class AssemblerTests(unittest.TestCase):
    """Accept 4: the six sections, on literal strings."""

    def test_all_six_sections_in_order_and_block_shaped(self):
        out, warnings = server.assemble_h3_ref2v_prompt(
            director_brief(), [{}])
        self.assertEqual(warnings, [])
        blocks = out.split("\n\n")
        self.assertEqual([b.split(":\n", 1)[0] for b in blocks],
                         ["subject_definitions", "summary", "retention_analysis",
                          "detailed_description", "overall_soundscape",
                          "non_diegetic_music"])
        for block in blocks:
            header, _, value = block.partition(":\n")
            # header at column 0, trailing colon, content on the NEXT line
            self.assertEqual(header, header.lower())
            self.assertNotIn(" ", header)
            self.assertTrue(value, header)
            self.assertFalse(value.startswith("\n"), header)

    def test_a_director_brief_passes_through_with_its_content_intact(self):
        brief = director_brief()
        out, _ = server.assemble_h3_ref2v_prompt(brief, [{}])
        for fragment in ("<Subject 1> is the woman in <Picture 1>",
                         "copper hair and green coat",
                         "fully_preserved - her face",
                         "Market crowd murmur, distant gulls."):
            self.assertIn(fragment, out)

    def test_no_alignment_header_no_audio_prompt_one_music_field(self):
        poisoned = (server.H3_I2VA_HEADER + "\n\n" + director_brief() + "\n\n"
                    + server.H3_AUDIO_PROMPT)
        out, _ = server.assemble_h3_ref2v_prompt(poisoned, [{}])
        self.assertNotIn("For the target video", out)
        self.assertNotIn("How the reference pictures align", out)
        self.assertNotIn("Generate synchronized ambience", out)
        self.assertEqual(out.count("non_diegetic_music:"), 1)
        self.assertTrue(out.startswith("subject_definitions:"))

    def test_reference_generation_is_the_only_task_prefix(self):
        out, _ = server.assemble_h3_ref2v_prompt(director_brief(), [{}])
        self.assertIn("summary:\n[reference generation] ", out)
        # a prefix the director invented is replaced, not kept
        brief = director_brief().replace("[reference generation]",
                                         "[video editing + audio reuse]")
        out, _ = server.assemble_h3_ref2v_prompt(brief, [{}])
        self.assertIn("summary:\n[reference generation] ", out)
        self.assertNotIn("video editing", out)

    def test_subjects_bind_1_to_1_to_their_wired_picture(self):
        # a missing section is filled from the wired ref list
        out, _ = server.assemble_h3_ref2v_prompt("She browses the stalls.",
                                                 [{}, {}])
        self.assertIn("subject_definitions:\n<Subject 1> is the subject of "
                      "<Picture 1>.\n<Subject 2> is the subject of <Picture 2>.",
                      out)
        # a partial section gains only the missing binding
        brief = director_brief()  # binds Subject 1 only
        out, _ = server.assemble_h3_ref2v_prompt(brief, [{}, {}])
        self.assertIn("<Subject 1> is the woman in <Picture 1>", out)
        self.assertIn("<Subject 2> is the subject of <Picture 2>.", out)
        # and a ref's stored kind becomes the sentence (ref guide §2.1)
        out, _ = server.assemble_h3_ref2v_prompt(
            "She browses.", [{"kind": "identity"}])
        self.assertIn("<Subject 1> is the person in <Picture 1>.", out)

    def test_retention_lines_are_subject_keyed_with_the_separator(self):
        out, _ = server.assemble_h3_ref2v_prompt("She browses the stalls.",
                                                 [{}, {}])
        self.assertIn("retention_analysis:\n<Subject 1>: fully_preserved - "
                      "the features named in subject_definitions are retained.\n"
                      "<Subject 2>: fully_preserved - the features named in "
                      "subject_definitions are retained.", out)
        # the repair omits the shot-appearance parenthetical rather than
        # inventing one, and never keys on <Picture N> (§2.2)
        section = out.split("retention_analysis:\n")[1].split("\n\n")[0]
        self.assertNotIn("(appears in", section)
        self.assertNotIn("<Picture", section)

    def test_the_style_sentence_is_the_first_line_of_the_description(self):
        out, _ = server.assemble_h3_ref2v_prompt(director_brief(), [{}])
        value = out.split("detailed_description:\n")[1].split("\n\n")[0]
        lines = value.splitlines()
        self.assertEqual(lines[0], server.H3_REF2V_STYLE_PHOTOREAL)
        self.assertTrue(lines[1].startswith("[Shot 1]"))

    def test_the_style_slot_is_replaced_not_doubled(self):
        # The director was told not to write one; when it does anyway, the
        # assembler owns the slot outright - everything before [Shot 1] goes.
        brief = director_brief(desc="The target video uses a dreamy VHS style.\n"
                                    "[Shot 1] She browses the stalls.")
        out, _ = server.assemble_h3_ref2v_prompt(brief, [{}], style=None)
        value = out.split("detailed_description:\n")[1].split("\n\n")[0]
        self.assertEqual(value.splitlines()[0], server.H3_REF2V_STYLE_PHOTOREAL)
        self.assertNotIn("dreamy VHS", value)
        self.assertIn("[Shot 1] She browses the stalls.", value)

    def test_a_user_script_wraps_its_scene_verbatim(self):
        script = "[Shot 1] my own words, exactly as typed"
        out, _ = server.assemble_h3_ref2v_prompt(script, [{}], user_script=True)
        self.assertIn("[Shot 1] my own words, exactly as typed", out)
        self.assertEqual([b.split(":\n", 1)[0] for b in out.split("\n\n")],
                         list(server.H3_REF2V_FIELDS))


class NineNineRepairsReachThisLaneTests(unittest.TestCase):
    """Accept 5: brief 9.9's repairs are keyed to the field SPAN; the widened
    alternation carries them to detailed_description: with the fl2va matcher
    itself byte-identical."""

    def test_the_fl2va_field_regex_is_byte_identical(self):
        self.assertEqual(server._H3_DESC_FIELD_RE.pattern,
                         r"(?im)^\s*integrated_multimodal_description\s*:")

    def test_a_hanging_line_is_detected_and_closed(self):
        out, _ = server.assemble_h3_ref2v_prompt(director_brief(
            desc="[Shot 1] She looks up. (S1) says: <d>[English] Do not watch</d>"),
            [{}])
        self.assertTrue(server.h3_hanging_dialogue(out))
        with patch.object(server, "llm_call",
                          AsyncMock(return_value=(200, {"choices": [
                              {"message": {"content": "Her lips press shut."}}]}))):
            repaired = asyncio.run(server.repair_h3_hanging_dialogue(out, "cid"))
        self.assertIn("</d> Her lips press shut.", repaired)
        self.assertFalse(server.h3_hanging_dialogue(repaired))

    def test_a_beat_that_already_ends_the_motion_is_untouched(self):
        out, _ = server.assemble_h3_ref2v_prompt(director_brief(), [{}])
        self.assertFalse(server.h3_hanging_dialogue(out))
        stub = AsyncMock()
        with patch.object(server, "llm_call", stub):
            repaired = asyncio.run(server.repair_h3_hanging_dialogue(out, "cid"))
        self.assertEqual(repaired, out)
        stub.assert_not_awaited()

    def test_the_style_sentence_follows_provenance_byte_for_byte(self):
        anima = {"template": "anima", "info": {"model_family": "anima"}}
        realism = {"template": "realism", "info": {"model_family": "krea2"}}
        out, _ = server.assemble_h3_ref2v_prompt(
            director_brief(), [{}], style=server.h3_style_for_entry(anima))
        self.assertIn("detailed_description:\n"
                      "The target video is in 2D-animated style.\n[Shot 1]", out)
        out, _ = server.assemble_h3_ref2v_prompt(
            director_brief(), [{}], style=server.h3_style_for_entry(realism))
        self.assertIn("detailed_description:\n"
                      "The target video is in realistic photographic style.\n"
                      "[Shot 1]", out)

    def test_en_normalizes_inside_the_six_sections(self):
        # repair_h3_dialogue_tags works on a body string and is field-name
        # agnostic - proven here rather than by inspection (9.12 Task 4.3).
        brief = director_brief(desc="[Shot 1] (S1) says: <d>[EN] Hello.</d> "
                                    "She smiles.")
        out, _ = server.assemble_h3_ref2v_prompt(brief, [{}])
        self.assertIn("<d>[English] Hello.</d>", out)
        self.assertNotIn("[EN]", out)

    def test_the_fl2va_lane_is_byte_identical_to_briefed_at(self):
        """The golden regression, captured at briefed-at BEFORE any edit:
        every assemble_h3_prompt path the ref2va work sits beside."""
        self.assertEqual(server.assemble_h3_prompt(
            "integrated_multimodal_description: [Shot 1] Live-action, natural "
            "real-time motion. She turns from the window, rain sliding down "
            "the glass behind her, and says: <d>[English] We leave at dawn."
            "</d> Her jaw settles as she reaches for the coat.\n\n"
            "overall_soundscape: Rain against the window, low room tone.\n\n"
            "non_diegetic_music: N/A"), GOLDEN["wellformed"])
        self.assertEqual(server.assemble_h3_prompt(
            "integrated_multimodal_description: [Shot 1] Live-action, natural "
            "real-time motion. She turns from the window, rain sliding down "
            "the glass behind her, and says: <d>[English] We leave at dawn."
            "</d> Her jaw settles as she reaches for the coat.\n\n"
            "overall_soundscape: Rain against the window, low room tone.\n\n"
            "non_diegetic_music: N/A", last_frame=True, seconds=5),
            GOLDEN["wellformed_bridge"])
        self.assertEqual(server.assemble_h3_prompt("She crosses the room and sits."),
                         GOLDEN["bare_prose"])
        self.assertEqual(server.assemble_h3_prompt(
            "[Shot 1] She looks up. (S1) says: <d>[English] Hello there.</d> "
            "She smiles.", user_script=True), GOLDEN["user_script"])
        self.assertEqual(server.h3_style_splice(GOLDEN["wellformed"], "2D-animated"),
                         GOLDEN["style_splice"])
        self.assertEqual(server.h3_style_splice(GOLDEN["wellformed"], None),
                         GOLDEN["style_splice_none"])
        self.assertEqual(server.h3_slug_source(GOLDEN["wellformed"]),
                         GOLDEN["slug"])


class EnforcementTests(unittest.TestCase):
    """Accept 6: what the node will not enforce, Pixal does (9.0 Q3)."""

    def test_zero_refs_is_refused_at_build_time(self):
        # minimax.py's falsy path: no ref_items, no minimax_refs payload, no
        # error anywhere - a ref2va render with nothing wired is t2va on
        # ref2va weights.
        with patch.object(server, "_video_asset", side_effect=all_video_assets):
            for refs in (None, [], ["", None]):
                with self.subTest(refs=refs):
                    with self.assertRaisesRegex(ValueError, "at least one reference"):
                        server.build_h3_ref2v(director_brief(), 1, refs, seconds=5,
                                              width=1344, height=768, model="ref2va")

    def test_a_dangling_picture_is_demoted_with_one_ref_wired(self):
        brief = director_brief(desc="[Shot 1] She waves at <Picture 4> and "
                                    "moves on.")
        out, warnings = server.assemble_h3_ref2v_prompt(brief, [{}])
        self.assertIn("<Picture 1>", out)
        self.assertNotIn("<Picture 4>", out)
        self.assertEqual(len(warnings), 1)
        self.assertIn("not wired", warnings[0])

    def test_a_dangling_picture_is_refused_with_two_refs_wired(self):
        brief = director_brief(desc="[Shot 1] She waves at <Picture 3>.",
                               two_refs=True)
        with self.assertRaisesRegex(ValueError, "not wired"):
            server.assemble_h3_ref2v_prompt(brief, [{}, {}])

    def test_video_and_audio_tags_are_dangling_by_definition_in_v1(self):
        # v1 wires no videos and no audios - the exact mistake the official
        # template ships (its stock prompt names <Audio 1> with nothing there).
        brief = director_brief(desc="[Shot 1] <Video 1> plays as <Audio 1> "
                                    "swells.")
        out, warnings = server.assemble_h3_ref2v_prompt(brief, [{}])
        self.assertNotIn("<Video", out)
        self.assertNotIn("<Audio", out)
        self.assertEqual(len(warnings), 2)
        with self.assertRaisesRegex(ValueError, "not wired"):
            server.assemble_h3_ref2v_prompt(brief, [{}, {}])

    def test_a_wired_but_unnamed_ref_warns(self):
        # its vision block enters the Qwen context and its latent rides every
        # sampling step - paid for in full, with no job assigned
        warnings = server.h3_ref2v_unnamed_lint(director_brief(), 2)
        self.assertEqual(len(warnings), 1)
        self.assertIn("<Picture 2>", warnings[0])
        _, _, info = build_ref2v(director_brief(two_refs=True),
                                 ("ref0.png", "ref1.png"))
        self.assertFalse(any("never names" in w for w in info["h3_warnings"]))

    def test_the_caps_are_named_constants(self):
        self.assertEqual(server.H3_REF2V_MAX_IMAGES, 9)   # the node's schema max
        self.assertEqual(server.H3_REF2V_MAX_FILES, 12)   # the model card's row
        with patch.object(server, "_video_asset", side_effect=all_video_assets):
            with self.assertRaisesRegex(ValueError, "at most 9"):
                server.build_h3_ref2v(director_brief(), 1,
                                      [f"ref{i}.png" for i in range(10)],
                                      seconds=5, width=1344, height=768,
                                      model="ref2va")


class AnimateRoutingTests(unittest.TestCase):
    """The lane as actually reached: the picked still becomes
    ref_images.ref_image_0 as a RAW copy, the canvas derives from its aspect,
    and the director gets the six-section variant."""

    def run_animate(self, root, body, director):
        entry = {"id": "abc123", "scene": "the subject at a workbench",
                 "images": [{"filename": "still.png", "subfolder": "",
                             "media": "image"}]}
        submit = AsyncMock(return_value={"id": "videojob", "error": None})

        async def run():
            response = await server.animate(FakeRequest(body))
            await asyncio.sleep(0)
            return response

        with patch.object(server, "CDIR", root), \
             patch.object(server, "validate_video_selection",
                          return_value=("h3", body["model"], body["seconds"], None)), \
             patch.object(server, "prepare_h3_frame") as prepare, \
             patch.object(server, "_video_asset", side_effect=all_video_assets), \
             patch.object(server, "direct_motion", director), \
             patch.object(server.HUB, "ledger_read", return_value=[entry]), \
             patch.object(server.HUB, "broadcast"), \
             patch.object(server.HUB, "submit", submit):
            response = asyncio.run(run())
        return response, submit, prepare

    def test_the_picked_still_stages_raw_and_routes_the_reference_graph(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "input").mkdir()
            Image.new("RGB", (1920, 1080), (9, 9, 9)).save(root / "output" / "still.png")
            director = AsyncMock(return_value=("She browses the stalls.", True))
            response, submit, prepare = self.run_animate(
                root, {"id": "abc123", "cid": "cid1", "engine": "h3",
                       "model": "ref2va", "seconds": 5,
                       "hint": "she lifts the tool"}, director)

            self.assertEqual(response.status, 200)
            # a raw copy, never prepare_h3_frame: cropping the subject to the
            # canvas aspect throws away exactly the identity the ref carries
            prepare.assert_not_called()
            staged = root / "input" / "pixal_ref_abc123.png"
            self.assertTrue(staged.is_file())
            with Image.open(staged) as still:
                self.assertEqual(still.size, (1920, 1080))   # uncropped
            submit.assert_awaited_once()
            args = submit.await_args.args
            self.assertEqual(args[2], "h3_ref2v")
            self.assertEqual(args[4], {"seconds": 5, "model": "ref2va",
                                       "refs": ["pixal_ref_abc123.png"],
                                       "width": 1344, "height": 768})
            # the director was handed the model id and picked the variant
            self.assertEqual(director.await_args.kwargs.get("model"), "ref2va")
            # the submitted brief is the six-section format, wrapped around
            # the director's scene - not manufactured around fl2va fields
            motion = args[3]
            self.assertTrue(motion.startswith("subject_definitions:"))
            self.assertIn("detailed_description:\n"
                          "The target video is in realistic photographic style.\n"
                          "[Shot 1] She browses the stalls.", motion)
            self.assertNotIn("integrated_multimodal_description", motion)
            self.assertNotIn("For the target video, at 0.00", motion)

    def test_the_director_variant_is_selected_by_the_model_id(self):
        response = {"choices": [{"message": {"content": "A directed brief."}}]}
        with patch.object(server, "llm_call",
                          AsyncMock(return_value=(200, response))) as call, \
             patch.object(server, "_turn_start"), patch.object(server, "_turn_end"):
            brief, directed = asyncio.run(server.direct_motion(
                "a still scene", engine="h3", shots=1, seconds=5,
                model="ref2va"))
        self.assertTrue(directed)
        system = call.await_args.args[0][0]["content"]
        self.assertIn(server.H3_REF2V_MOTION_SYSTEM, system)
        self.assertIn("350-500", system)          # the ref2va length note
        self.assertNotIn("literal frame zero", system)
        user = call.await_args.args[0][1]["content"]
        self.assertIn("<Picture 1>", user)         # the wired-reference line
        # and fl2va is untouched: no model id means the proven prompt
        with patch.object(server, "llm_call",
                          AsyncMock(return_value=(200, response))) as call, \
             patch.object(server, "_turn_start"), patch.object(server, "_turn_end"):
            asyncio.run(server.direct_motion("a still scene", engine="h3",
                                             shots=1, seconds=5))
        self.assertIn(server.H3_MOTION_SYSTEM, call.await_args.args[0][0]["content"])


if __name__ == "__main__":
    unittest.main()
