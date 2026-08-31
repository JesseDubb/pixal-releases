"""Brief 9.55 — H3 renders at the size you choose: the Resolution control.

The canvas cap was the quality problem ("1024x768 is insanely low res",
Jesse): the upscaler A/B column everyone preferred was just H3 rendered
natively at the big canvas. `h3_adapt_canvas` gets a tier - Standard (the
pre-9.55 cap, still the default), High, Max - and every H3 path threads it:
the builders record info["resolution"], /api/animate parses it (unknown tier
is a 400 naming the option list), the popup and Settings each get a Lumen
three-way (the popup's opening position is the Settings default, the 9.31
flag discipline), and the butler keeps pricing info["canvas_mp"] - a Max 10s
request prices at ~3.1 MP x 243 frames and is refused or evicted exactly
like a 2x request, with no change to the formula.

Pinned here:

- per-tier canvases for 3:4, 4:3, 9:16 and 1:1 sources: multiples of 32,
  under the tier's pixel cap, in-aspect after prepare_h3_frame's crop rule;
  the brief's exact accepts ((1024,1365) -> 1536x2048 at Max, 1152x1536 at
  High); an unknown tier raises everywhere;
- the default is byte-identical to before: the resolution="standard" graph
  equals the fixture captured from the pre-change code;
- builder info["resolution"] and size at each tier, i2v + ref2va + multishot;
- the route: a body with resolution "max" produces the Max canvas on node 6
  and canvas_mp ~3.1; an unknown tier is a 400, and nothing queues;
- /api/options publishes the tier list + the opening-position flag on the
  h3 engine alone; /api/settings round-trips the value and rejects an
  unknown tier naming the option list;
- GET /api/h3/canvas answers from the server's own math (the popup hints
  from it) and 400s/404s honestly.

Same sanctioned simulation as every sibling file: stubbed assets and
handlers - no generation, no ComfyUI, no GPU.
"""
import asyncio
import json
import types
import unittest
from contextlib import ExitStack
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image


_SPEC = spec_from_file_location(
    "pixal_server_h3_resolution",
    Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures"
                      / "h3_i2v_standard_graph.json").read_text(
                          encoding="utf-8"))


def all_video_assets(_kind, _rel):
    return _rel


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class FakeGetRequest:
    """The aiohttp stand-in for GET handlers: rel_url.query is all they read."""

    def __init__(self, query):
        self.rel_url = types.SimpleNamespace(query=query)


ENTRY = {"id": "abc123", "scene": "the subject at a workbench",
         "images": [{"filename": "still.png", "subfolder": "",
                     "media": "image"}]}

# A director-shaped brief every repair gate passes through byte-identical
# (same fixture as test_animate_brief).
BRIEF = (
    "integrated_multimodal_description: [Shot 1] Live-action, natural "
    "real-time motion — she stands at the workbench, still for a beat, then "
    "lifts the brass lamp and turns it toward the window light, her "
    "expression easing. (S1) says: <d>[English] It finally works.</d> Her "
    "lips close and she only listens; no further speech.\n\n"
    "overall_soundscape: The room's low hum, the lamp's click, fabric "
    "moving as she turns, synchronized.")

BODY = {"id": "abc123", "cid": "cid1", "engine": "h3", "model": "fl2va",
        "seconds": 5, "hint": "she fixes the lamp"}

# (source, aspect name) - the four shapes the brief names, 3:4 first because
# it is the accept criterion's own source.
SOURCES = [((1024, 1365), "3:4"), ((1600, 1200), "4:3"),
           ((1080, 1920), "9:16"), ((1024, 1024), "1:1")]


def crop_rule_brings_aspect_within_tolerance(sw, sh, width, height):
    """Simulate prepare_h3_frame's cover crop: the rendered frame always
    lands within H3_ASPECT_TOLERANCE of the canvas, because a canvas whose
    rounding pushed it past the tolerance gets the SOURCE cropped to the
    canvas aspect first."""
    target, source = width / height, sw / sh
    if abs(source - target) / target > server.H3_ASPECT_TOLERANCE:
        if source > target:
            sw = int(round(sh * target))
        else:
            sh = int(round(sw / target))
        source = sw / sh
    return abs(source - target) / target <= server.H3_ASPECT_TOLERANCE


class TieredCanvasTests(unittest.TestCase):
    """h3_adapt_canvas per tier: the 32 grid, the tier's cap, the crop rule."""

    def test_the_briefs_exact_accepts(self):
        self.assertEqual(server.h3_adapt_canvas(1024, 1365, "max"), (1536, 2048))
        self.assertEqual(server.h3_adapt_canvas(1024, 1365, "high"), (1152, 1536))
        self.assertEqual(server.h3_adapt_canvas(1024, 1365), (768, 1024))

    def test_every_tier_stays_on_the_grid_and_under_its_cap(self):
        for (sw, sh), aspect in SOURCES:
            for tier, spec in server.H3_RESOLUTIONS.items():
                with self.subTest(aspect=aspect, tier=tier):
                    width, height = server.h3_adapt_canvas(sw, sh, tier)
                    self.assertEqual(width % server.H3_CANVAS_MULTIPLE, 0)
                    self.assertEqual(height % server.H3_CANVAS_MULTIPLE, 0)
                    self.assertLessEqual(width * height, spec["max_pixels"])
                    self.assertTrue(
                        crop_rule_brings_aspect_within_tolerance(
                            sw, sh, width, height),
                        f"{aspect} at {tier}: {width}x{height} out of aspect "
                        f"even after the crop rule")

    def test_landscape_and_square_land_under_the_tier_cap(self):
        # The exact-cap cases: 4:3 and 1:1 hit each tier's max_pixels dead on.
        self.assertEqual(server.h3_adapt_canvas(1600, 1200, "max"), (2048, 1536))
        self.assertEqual(server.h3_adapt_canvas(1024, 1024, "max"), (1536, 1536))
        # 9:16's cap is a walk-down case (rounding up overshoots, the loop
        # trims the long edge back under): still on the grid, under the cap.
        width, height = server.h3_adapt_canvas(1080, 1920, "max")
        self.assertLessEqual(width * height,
                             server.H3_RESOLUTIONS["max"]["max_pixels"])
        self.assertEqual((width % 32, height % 32), (0, 0))

    def test_the_default_tier_is_the_pre_9_55_canvas(self):
        for (sw, sh), aspect in SOURCES:
            with self.subTest(aspect=aspect):
                self.assertEqual(server.h3_adapt_canvas(sw, sh),
                                 server.h3_adapt_canvas(sw, sh, "standard"))

    def test_an_unknown_tier_raises_naming_the_option_list(self):
        for bad in ("ultra", "2k", "", 4, ["high"]):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "standard, high, max"):
                    server.h3_adapt_canvas(1024, 1024, bad)


class PrepareH3FrameTierTests(unittest.TestCase):
    """The staged first frame is content-addressed PER TIER: without the tier
    in the name a Standard render's file would shadow a later Max render of
    the same still."""

    def test_each_tier_stages_its_own_exact_canvas(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            source = root / "source.png"
            Image.new("RGB", (1024, 1365), (25, 80, 140)).save(source)
            with patch.object(server, "CDIR", root):
                standard = server.prepare_h3_frame(source)
                standard_again = server.prepare_h3_frame(source)
                high = server.prepare_h3_frame(source, "high")
                top = server.prepare_h3_frame(source, "max")
            self.assertEqual(standard, standard_again)   # content-addressed
            names = {standard[0], high[0], top[0]}
            self.assertEqual(len(names), 3, "tiers must not shadow each other")
            self.assertEqual((standard[1], standard[2]), (768, 1024))
            self.assertEqual((high[1], high[2]), (1152, 1536))
            self.assertEqual((top[1], top[2]), (1536, 2048))
            for name, width, height in (standard, high, top):
                with Image.open(root / "input" / name) as staged:
                    self.assertEqual(staged.size, (width, height))

    def test_an_unknown_tier_raises_before_anything_is_written(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            source = root / "source.png"
            Image.new("RGB", (640, 360), (25, 80, 140)).save(source)
            with patch.object(server, "CDIR", root):
                with self.assertRaisesRegex(ValueError, "standard, high, max"):
                    server.prepare_h3_frame(source, "ultra")
            self.assertEqual(list((root / "input").iterdir()), [])


class BuilderResolutionTests(unittest.TestCase):
    """The builders take resolution= and record info["resolution"]; size and
    canvas_mp keep reading the real width*height - no second formula."""

    def build_i2v(self, tier, width, height):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset",
                              side_effect=all_video_assets):
                return server.build_h3_i2v(
                    "She turns toward the window.", 987, "prepared.png",
                    seconds=10, width=width, height=height, model="fl2va",
                    sparse=False, resolution=tier)

    def test_info_records_the_tier_and_the_real_canvas(self):
        for tier, canvas, mp in (("standard", (768, 1344), 1.03),
                                 ("high", (1152, 1536), 1.77),
                                 ("max", (1536, 2048), 3.15)):
            with self.subTest(tier=tier):
                graph, _brief, info = self.build_i2v(tier, *canvas)
                self.assertEqual(info["resolution"], tier)
                self.assertEqual(info["size"], f"{canvas[0]}x{canvas[1]}")
                self.assertAlmostEqual(info["canvas_mp"], mp, delta=0.01)
                self.assertEqual(graph["6"]["inputs"]["width"], canvas[0])
                self.assertEqual(graph["6"]["inputs"]["height"], canvas[1])

    def test_an_unknown_tier_raises_in_every_builder(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            (root / "input" / "ref0.png").write_bytes(b"ref")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset",
                              side_effect=all_video_assets):
                with self.assertRaisesRegex(ValueError, "standard, high, max"):
                    server.build_h3_i2v("She turns.", 987, "prepared.png",
                                        seconds=5, width=768, height=1344,
                                        model="fl2va", resolution="ultra")
                with self.assertRaisesRegex(ValueError, "standard, high, max"):
                    server.build_h3_multishot("One.\n---\nTwo.", 987,
                                              "prepared.png", width=768,
                                              height=1344, model="fl2va",
                                              resolution="ultra")
                with self.assertRaisesRegex(ValueError, "standard, high, max"):
                    server.build_h3_ref2v("a brief", 987, ["ref0.png"],
                                          seconds=5, width=768, height=1344,
                                          model="ref2va", resolution="ultra")

    def test_ref2v_derives_the_tier_canvas_when_no_size_is_passed(self):
        """The reference lane has no prepared first frame: its canvas comes
        from h3_adapt_canvas on the first reference, so the tier must thread
        all the way through."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            Image.new("RGB", (1024, 1365), (25, 80, 140)).save(
                root / "input" / "ref0.png")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset",
                              side_effect=all_video_assets):
                graph, _brief, info = server.build_h3_ref2v(
                    "a brief", 987, ["ref0.png"], seconds=5, model="ref2va",
                    resolution="max")
        self.assertEqual(graph["6"]["inputs"]["width"], 1536)
        self.assertEqual(graph["6"]["inputs"]["height"], 2048)
        self.assertEqual(info["resolution"], "max")
        self.assertEqual(info["size"], "1536x2048")

    def test_multishot_records_the_tier(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset",
                              side_effect=all_video_assets):
                _graph, _brief, info = server.build_h3_multishot(
                    "One.\n---\nTwo.", 987, "prepared.png", width=1536,
                    height=2048, model="fl2va", resolution="max")
        self.assertEqual(info["resolution"], "max")
        self.assertEqual(info["size"], "1536x2048")


class StandardGraphUnchangedTests(unittest.TestCase):
    """The default config renders exactly today's canvas: the
    resolution="standard" graph equals the fixture captured from the
    pre-change code (tests/fixtures/h3_i2v_standard_graph.json)."""

    def rebuild(self, **kw):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "load_config", return_value={
                     # 9.94: the encoder resolver reads config, and this
                     # kind-blind asset stub would resolve a real pick -
                     # pin Automatic or the machine's own settings decide
                     # what "the fixture" means.
                     "h3": {"ref_model": "", "fl_model": "",
                            "text_encoder": ""},
                     "extra_model_roots": []}), \
                 patch.object(server, "_video_asset",
                              side_effect=all_video_assets):
                return server.build_h3_i2v(
                    "She turns toward the window.", 987, "prepared.png",
                    seconds=10, width=768, height=1344, model="fl2va",
                    sparse=False, **kw)

    def test_the_default_tier_graph_is_byte_identical_to_the_fixture(self):
        for kw in ({}, {"resolution": "standard"}):
            with self.subTest(kw=kw):
                graph, brief, info = self.rebuild(**kw)
                self.assertEqual(graph, FIXTURE["graph"])
                self.assertEqual(brief, FIXTURE["brief"])
                self.assertEqual(info.pop("resolution"), "standard")
                self.assertEqual(info, FIXTURE["info"])


class AnimateRouteResolutionTests(unittest.TestCase):
    """The body carries resolution beside sparse/upscale; the route validates
    it, threads it through staging, and the spec records it for rerolls."""

    def run_animate(self, root, body):
        """POST /api/animate under the sibling files' harness: every side
        effect stubbed except the REAL prepare_h3_frame - the staged canvas
        is what this brief is about."""
        submit = AsyncMock(return_value={"id": "videojob", "error": None})
        director = AsyncMock(return_value=(BRIEF, True))

        async def run():
            response = await server.animate(FakeRequest(body))
            await asyncio.sleep(0)
            return response

        with ExitStack() as stack:
            stack.enter_context(patch.object(server, "CDIR", root))
            stack.enter_context(patch.object(
                server, "validate_video_selection",
                return_value=("h3", "fl2va", 5, None)))
            stack.enter_context(patch.object(server, "_video_asset",
                                             side_effect=all_video_assets))
            stack.enter_context(patch.object(server, "load_config", return_value={
                # a cloud brain: the LOOK stage skips frame_inventory, and
                # the standing dialogue spelling reads video.h3_dialogue_tags
                "llm": {"base_url": "http://brain.invalid/v1"},
                "video": {"h3_dialogue_tags": "quotes"},
                "extra_model_roots": []}))
            stack.enter_context(patch.object(server, "direct_motion", director))
            stack.enter_context(patch.object(
                server, "llm_call",
                AsyncMock(side_effect=AssertionError("no brain in tests"))))
            stack.enter_context(patch.object(server.HUB, "ledger_read",
                                             return_value=[ENTRY]))
            stack.enter_context(patch.object(server.HUB, "broadcast"))
            stack.enter_context(patch.object(server.HUB, "submit", submit))
            response = asyncio.run(run())
        return response, submit

    def stage_source(self, root, size=(1024, 1365)):
        (root / "output").mkdir()
        (root / "input").mkdir()
        Image.new("RGB", size, (25, 80, 140)).save(root / "output" / "still.png")

    def build_from_submit(self, root, submit):
        """The graph the submitted args produce - node 6 is the canvas the
        clip renders at."""
        args = submit.await_args.args[4]
        with patch.object(server, "CDIR", root), \
             patch.object(server, "_video_asset", side_effect=all_video_assets):
            return server.build_h3_i2v(
                "a brief", 987, args["image"], seconds=args["seconds"],
                width=args["width"], height=args["height"], model="fl2va",
                sparse=False, resolution=args.get("resolution", "standard"))

    def test_a_max_body_produces_the_max_canvas(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self.stage_source(root)
            response, submit = self.run_animate(
                root, {**BODY, "resolution": "max"})
            self.assertEqual(response.status, 200)
            submit.assert_awaited_once()
            args = submit.await_args.args[4]
            self.assertEqual(args["resolution"], "max")
            self.assertEqual((args["width"], args["height"]), (1536, 2048))
            graph, _brief, info = self.build_from_submit(root, submit)
            self.assertEqual(graph["6"]["inputs"]["width"], 1536)
            self.assertEqual(graph["6"]["inputs"]["height"], 2048)
            self.assertAlmostEqual(info["canvas_mp"], 3.1, delta=0.05)
            self.assertEqual(info["resolution"], "max")

    def test_an_absent_tier_renders_todays_canvas(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self.stage_source(root)
            response, submit = self.run_animate(root, dict(BODY))
            self.assertEqual(response.status, 200)
            args = submit.await_args.args[4]
            self.assertEqual(args["resolution"], "standard")
            self.assertEqual((args["width"], args["height"]), (768, 1024))

    def test_an_unknown_tier_is_a_400_and_nothing_queues(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self.stage_source(root)
            response, submit = self.run_animate(
                root, {**BODY, "resolution": "ultra"})
            self.assertEqual(response.status, 400)
            payload = json.loads(response.text)
            self.assertFalse(payload["ok"])
            self.assertIn("standard, high, max", payload["error"])
            submit.assert_not_awaited()


class OptionsAndSettingsTests(unittest.TestCase):
    """The tier list and the opening position ride /api/options on the h3
    engine alone; /api/settings round-trips the value and refuses junk."""

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

    def test_options_publishes_the_tier_list_on_the_h3_engine_alone(self):
        engines = self._options({})
        h3 = next(e for e in engines if e["id"] == "h3")
        self.assertEqual(h3["h3_resolutions"], [
            {"id": "standard", "label": "Standard", "mp": 1.0},
            {"id": "high", "label": "High", "mp": 1.8},
            {"id": "max", "label": "Max", "mp": 3.1}])
        self.assertEqual(h3["resolution_default"], "standard")
        for engine in engines:
            if engine["id"] != "h3":
                self.assertNotIn("h3_resolutions", engine)
                self.assertNotIn("resolution_default", engine)

    def test_the_opening_position_flag_follows_the_configured_default(self):
        h3 = next(e for e in self._options({"h3_resolution": "high"})
                  if e["id"] == "h3")
        self.assertEqual(h3["resolution_default"], "high")
        # a stale value degrades to the default rather than hiding the row
        h3 = next(e for e in self._options({"h3_resolution": "ultra"})
                  if e["id"] == "h3")
        self.assertEqual(h3["resolution_default"], "standard")

    def test_settings_post_rejects_an_unknown_tier_naming_the_list(self):
        for bad in ("ultra", "", True, 1, None, ["high"]):
            with self.subTest(bad=bad):
                saved = []
                with patch.object(server, "load_config",
                                  return_value=self._full_cfg({})), \
                     patch.object(server, "model_catalog", return_value=[]), \
                     patch.object(server, "save_config",
                                  side_effect=lambda cfg: saved.append(cfg)):
                    response = asyncio.run(server.settings_post(
                        FakeRequest({"video": {"h3_resolution": bad}})))
                self.assertEqual(response.status, 400)
                self.assertEqual(
                    json.loads(response.text),
                    {"ok": False,
                     "error": f"not one of standard|high|max: {bad}"})
                self.assertEqual(saved, [])  # a rejected write never touches config

    def test_settings_round_trip_exposes_the_value_and_the_tier_list(self):
        cfg = self._full_cfg({"default_engine": "", "default_model": ""})
        saved = []
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "_video_asset", side_effect=all_video_assets), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()), \
             patch.object(server, "save_config",
                          side_effect=lambda c: saved.append(c)):
            post = asyncio.run(server.settings_post(
                FakeRequest({"video": {"h3_resolution": "max"}})))
            self.assertEqual(post.status, 200)
            self.assertEqual(json.loads(post.text), {"ok": True})
            response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        video = json.loads(response.text)["video"]
        self.assertEqual(video["h3_resolution"], "max")
        self.assertEqual([r["id"] for r in video["h3_resolutions"]],
                         ["standard", "high", "max"])
        self.assertEqual(saved[0]["video"]["h3_resolution"], "max")


class H3CanvasEndpointTests(unittest.TestCase):
    """GET /api/h3/canvas: the popup's hint, from the server's own math."""

    def run_endpoint(self, root, query):
        with patch.object(server, "CDIR", root), \
             patch.object(server.HUB, "ledger_read", return_value=[ENTRY]):
            return asyncio.run(server.h3_canvas(FakeGetRequest(query)))

    def test_the_canvas_for_this_still_at_each_tier(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            Image.new("RGB", (1024, 1365), (25, 80, 140)).save(
                root / "output" / "still.png")
            for tier, canvas in (("standard", (768, 1024)),
                                 ("high", (1152, 1536)),
                                 ("max", (1536, 2048))):
                with self.subTest(tier=tier):
                    response = self.run_endpoint(
                        root, {"id": "abc123", "resolution": tier})
                    self.assertEqual(response.status, 200)
                    payload = json.loads(response.text)
                    self.assertEqual(payload, {"ok": True, "resolution": tier,
                                               "width": canvas[0],
                                               "height": canvas[1]})

    def test_an_unknown_tier_is_a_400_and_an_unknown_still_a_404(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            Image.new("RGB", (1024, 1365), (25, 80, 140)).save(
                root / "output" / "still.png")
            response = self.run_endpoint(
                root, {"id": "abc123", "resolution": "ultra"})
            self.assertEqual(response.status, 400)
            self.assertIn("standard, high, max",
                          json.loads(response.text)["error"])
            response = self.run_endpoint(
                root, {"id": "nobody", "resolution": "max"})
            self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
