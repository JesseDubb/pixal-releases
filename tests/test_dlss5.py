"""Brief 10.5 - DLSS 5 as a finishing setting, its own group.

The installed ComfyUI-DLSS5-NR node (DLSS5NeuralRendering) re-renders every
delivered still neurally - relights materials and tames glare at the SAME
resolution, it is not an upscaler. It seats FIRST in the delivery chain
(dlss5 -> de-shine -> grain) because a whole-frame pass must see the raw
render, and it never goes inside a build_* graph: a native failure there
would kill the render, out here the same failure is a no-op with one log
line. Jesse's judged style pick off the 9-arm ladder is "default" (with
"cinematic" also approved); preset 3, neutral tone/structure, skin mask
off, still-image batch, gpu 0 and channel auto are fixed constants, not
settings - exposing them waits on a judged reason.

What these tests pin:

  Defaults     - a fresh config is off / "default" / 1.0, and a config
                 written before the keys existed reads the same way.
  Resolvers    - intensity clamps 0-2 with nan refused; an unknown style
                 reads as "default"; the ledger token is dlss5@default with
                 intensity only when it left 1.0.
  Settings     - strict-bool dlss5, strict-enum dlss5_style (the numeric
                 experimental arms 400 by name), strict-number
                 dlss5_intensity - all 400 without saving on garbage; a
                 valid write round-trips; GET publishes the three keys plus
                 dlss5_available, which is False on a cold ComfyUI, on an
                 empty object_info, and when the runtime DLL is missing.
  Order        - with every finisher on, one delivered frame runs dlss5
                 BEFORE _de_shine_delivered and BEFORE grain; the finish
                 ledger reads dlss5@default+grain@1.6. upscale_image
                 deliveries are exempt (the pre-upscale file already
                 carries it - a second pass would double-apply).
  Finisher     - DLL missing, ComfyUI unreachable, a rejected graph, a
                 native error status, a timeout and a missing output frame
                 are all no-ops: the delivered file stays byte-identical,
                 nothing raises, finish stays unset, temp files are gone.
                 On success the node's pixels overwrite the delivered PNG
                 while its original tEXt chunks (the embedded workflow the
                 audit reads) survive, and the temp input/output are
                 cleaned. "front": true rides the POST so a queued batch
                 cannot starve the finisher past its timeout.

Same sanctioned simulation as every sibling file: synthetic PIL frames,
stubbed config, a stubbed HTTP seam, no generation, no ComfyUI, no GPU,
no server.
"""

import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_dlss5", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

DLL_REL = Path("custom_nodes") / "ComfyUI-DLSS5-NR" / "runtime" / "nvngx_dlssnr.dll"


def _write_png(path, im, text={"prompt": '{"9": {"class_type": "SaveImage"}}'}):
    info = PngInfo()
    for key, value in text.items():
        info.add_text(key, value)
    im.save(path, pnginfo=info)


def _frame(seed=7, size=(48, 36)):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (*size[::-1], 3))
                           .astype(np.uint8))


def _stage_root(root):
    """A fake ComfyUI root: output/ for the delivered file, input/ for the
    staging copy, and the node's runtime DLL so the finisher's gate opens."""
    (root / "output").mkdir(parents=True, exist_ok=True)
    dll = root / DLL_REL
    dll.parent.mkdir(parents=True, exist_ok=True)
    dll.write_bytes(b"dll")


class FakeComfy:
    """The finisher's HTTP seam, stubbed at _dlss5_http. Learns the temp
    prefix out of the POSTed graph, checks the front-of-queue flag and the
    fixed node inputs, then answers /history with a success record whose
    SaveImage output it materializes under the fake root."""

    def __init__(self, root, pixels, status="success", with_output=True):
        self.root = root
        self.pixels = pixels
        self.status = status
        self.with_output = with_output
        self.posts = []

    def __call__(self, url, payload=None, timeout=10.0):
        if url.endswith("/prompt"):
            self.posts.append(payload)
            return {"prompt_id": "pid_dlss5"}
        if "/history" in url:
            outputs = {}
            if self.with_output:
                prefix = self.posts[-1]["prompt"]["3"]["inputs"][
                    "filename_prefix"]
                name = f"{prefix}_00001_.png"
                Image.fromarray(self.pixels).save(self.root / "output" / name)
                outputs = {"3": {"images": [{"filename": name,
                                             "subfolder": "",
                                             "type": "output"}]}}
            return {"pid_dlss5": {"status": {"status_str": self.status,
                                             "completed":
                                                 self.status == "success"},
                                  "outputs": outputs}}
        raise AssertionError(f"unexpected url: {url}")


class DefaultsAndResolversTests(unittest.TestCase):

    def test_load_config_defaults(self):
        with patch.object(server, "CONFIG", Path("does-not-exist.json")):
            still = server.load_config()["still"]
            self.assertFalse(still["dlss5"])
            self.assertEqual(still["dlss5_style"], "default")
            self.assertEqual(still["dlss5_intensity"], 1.0)

    def test_a_legacy_config_reads_as_the_defaults(self):
        with patch.object(server, "load_config",
                          return_value={"still": {"film_grain": True}}):
            self.assertFalse(server.still_dlss5_active())
            self.assertEqual(server.still_dlss5_style(), "default")
            self.assertEqual(server.still_dlss5_intensity(), 1.0)

    def test_the_style_resolver_refuses_the_experimental_arms(self):
        for stored in ("3", "6", "cinematic ", "", 3, None):
            with patch.object(server, "load_config", return_value={
                    "still": {"dlss5_style": stored}}):
                self.assertEqual(server.still_dlss5_style(), "default",
                                 f"{stored!r} must read as default")
        for stored in ("default", "natural", "cinematic"):
            with patch.object(server, "load_config", return_value={
                    "still": {"dlss5_style": stored}}):
                self.assertEqual(server.still_dlss5_style(), stored)

    def test_the_intensity_resolver_clamps_corruption(self):
        for stored, want in ((1.0, 1.0), (0.0, 0.0), (99.0, 2.0), (-1.0, 0.0),
                             (float("nan"), 1.0), ("x", 1.0), (None, 1.0),
                             (1.5, 1.5)):
            with patch.object(server, "load_config", return_value={
                    "still": {"dlss5": True, "dlss5_intensity": stored}}):
                self.assertEqual(server.still_dlss5_intensity(), want,
                                 f"{stored!r}")

    def test_the_fixed_node_inputs_are_the_briefs_constants(self):
        self.assertEqual(server.DLSS5_NODE, "DLSS5NeuralRendering")
        self.assertEqual(server.DLSS5_STYLES, ("default", "natural",
                                               "cinematic"))
        self.assertEqual(server.DLSS5_FIXED,
                         {"preset": 3, "tone": 1.0, "structure": 1.0,
                          "skin": -1.0, "auto_mask": False,
                          "batch_mode": "still images", "gpu_index": 0,
                          "channel_order": "auto"})

    def test_the_finish_tag_carries_intensity_only_off_default(self):
        self.assertEqual(server.dlss5_finish_tag("default", 1.0),
                         "dlss5@default")
        self.assertEqual(server.dlss5_finish_tag("default", 1.5),
                         "dlss5@default:1.5")
        self.assertEqual(server.dlss5_finish_tag("cinematic", 1.0),
                         "dlss5@cinematic")

    def test_the_finish_chain_joins_in_run_order(self):
        job = {"info": {}}
        server._record_finish(job, "dlss5@default")
        server._record_finish(job, "grain@1.6")
        self.assertEqual(job["info"]["finish"], "dlss5@default+grain@1.6")
        # a job with no info dict never gains one and never raises
        server._record_finish({"id": "x"}, "dlss5@default")


class AvailabilityTests(unittest.TestCase):

    def test_available_needs_the_node_and_the_dll(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            with patch.object(server, "CDIR", root), \
                 patch.dict(server._COMFY_NODES,
                            {"names": frozenset({server.DLSS5_NODE})}):
                self.assertTrue(server.dlss5_available())

    def test_unavailable_on_a_cold_probe_an_empty_catalog_or_a_missing_dll(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            with patch.object(server, "CDIR", root), \
                 patch.dict(server._COMFY_NODES, {"names": None}):
                self.assertFalse(server.dlss5_available(),
                                 "comfy down must read as unavailable")
            with patch.object(server, "CDIR", root), \
                 patch.dict(server._COMFY_NODES, {"names": frozenset()}):
                self.assertFalse(server.dlss5_available(),
                                 "an empty object_info is unavailable")
            with patch.object(server, "CDIR", root), \
                 patch.dict(server._COMFY_NODES,
                            {"names": frozenset({"SomeOtherNode"})}):
                self.assertFalse(server.dlss5_available())
            (root / DLL_REL).unlink()
            with patch.object(server, "CDIR", root), \
                 patch.dict(server._COMFY_NODES,
                            {"names": frozenset({server.DLSS5_NODE})}):
                self.assertFalse(server.dlss5_available(),
                                 "the node without its DLL is unavailable")


class FinisherTests(unittest.TestCase):
    """_dlss5_delivered: every failure is a no-op with the file untouched;
    success overwrites pixels and keeps the embedded workflow."""

    def deliverable(self, root):
        src = root / "output" / "still.png"
        _write_png(src, _frame())
        return src

    def test_the_missing_dll_is_a_byte_identical_no_op(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            src = self.deliverable(root)
            before = src.read_bytes()
            with patch.object(server, "CDIR", root):
                self.assertFalse(
                    server._dlss5_delivered(src, "default", 1.0))
            self.assertEqual(src.read_bytes(), before)

    def test_an_unreachable_comfy_is_a_byte_identical_no_op(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            src = self.deliverable(root)
            before = src.read_bytes()
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_dlss5_http",
                              side_effect=OSError("connection refused")):
                self.assertFalse(
                    server._dlss5_delivered(src, "default", 1.0))
            self.assertEqual(src.read_bytes(), before)
            self.assertEqual(list((root / "input").glob("pixal_dlss5_*")), [],
                             "the staged temp input must be cleaned up")

    def test_a_rejected_graph_is_a_no_op(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            src = self.deliverable(root)
            before = src.read_bytes()

            def reject(url, payload=None, timeout=10.0):
                return {"error": "invalid node", "node_errors": {}}

            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_dlss5_http", side_effect=reject):
                self.assertFalse(
                    server._dlss5_delivered(src, "default", 1.0))
            self.assertEqual(src.read_bytes(), before)

    def test_a_native_error_status_is_a_no_op(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            src = self.deliverable(root)
            before = src.read_bytes()
            comfy = FakeComfy(root, np.zeros((4, 4, 3), np.uint8),
                              status="error")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_dlss5_http", side_effect=comfy):
                self.assertFalse(
                    server._dlss5_delivered(src, "default", 1.0))
            self.assertEqual(src.read_bytes(), before)

    def test_a_timeout_is_a_byte_identical_no_op(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            src = self.deliverable(root)
            before = src.read_bytes()

            def never_done(url, payload=None, timeout=10.0):
                if url.endswith("/prompt"):
                    return {"prompt_id": "pid_dlss5"}
                return {}          # history never completes

            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_dlss5_http", side_effect=never_done):
                self.assertFalse(server._dlss5_delivered(
                    src, "default", 1.0, timeout=0.3, interval=0.02))
            self.assertEqual(src.read_bytes(), before)

    def test_a_timeout_yanks_the_pending_pass_before_cleanup(self):
        # Found live 2026-09-01, first batch: front:true cannot preempt the
        # render already executing, so mid-batch the poll times out while
        # the pass is still PENDING - and cleaning the temps then left a
        # poison graph whose LoadImage failed loudly in the console. The
        # rescue must delete the prompt from ComfyUI's queue BEFORE any
        # temp cleanup.
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            src = self.deliverable(root)
            before = src.read_bytes()
            calls = []

            def pending(url, payload=None, timeout=10.0):
                calls.append((url, payload))
                if url.endswith("/prompt"):
                    return {"prompt_id": "pid_dlss5"}
                if url.endswith("/queue") and payload is not None:
                    staged = list((root / "input").glob("pixal_dlss5_*"))
                    assert staged, "temps cleaned before the queue delete"
                    return {}
                if url.endswith("/queue"):
                    return {"queue_running": [],
                            "queue_pending": [[0, "pid_dlss5"]]}
                return {}          # history never completes

            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_dlss5_http", side_effect=pending):
                self.assertFalse(server._dlss5_delivered(
                    src, "default", 1.0, timeout=0.3, interval=0.02))
            deletes = [p for u, p in calls
                       if u.endswith("/queue") and p is not None]
            self.assertEqual(deletes, [{"delete": ["pid_dlss5"]}])
            self.assertEqual(src.read_bytes(), before)
            self.assertEqual(
                list((root / "input").glob("pixal_dlss5_*")), [])

    def test_a_timeout_on_an_executing_pass_waits_the_grace_lap(self):
        # The rescue's other half: a pass ComfyUI is EXECUTING at the
        # deadline finishes in seconds - the grace lap collects it instead
        # of cancelling, and the frame still gets its re-render.
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            src = self.deliverable(root)
            polls = {"n": 0}
            comfy = FakeComfy(root, np.full((4, 4, 3), 128, np.uint8))

            def executing(url, payload=None, timeout=10.0):
                if url.endswith("/prompt"):
                    return comfy(url, payload, timeout)
                if url.endswith("/queue"):
                    assert payload is None, "must not cancel a running pass"
                    return {"queue_running": [[0, "pid_dlss5"]],
                            "queue_pending": []}
                polls["n"] += 1
                if polls["n"] < 3:
                    return {}      # not done inside the base deadline
                return comfy(url, payload, timeout)

            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_dlss5_http", side_effect=executing):
                self.assertTrue(server._dlss5_delivered(
                    src, "default", 1.0, timeout=0.05, interval=0.02))

    def test_a_success_record_without_an_output_frame_is_a_no_op(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            src = self.deliverable(root)
            before = src.read_bytes()
            comfy = FakeComfy(root, np.zeros((4, 4, 3), np.uint8),
                              with_output=False)
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_dlss5_http", side_effect=comfy):
                self.assertFalse(
                    server._dlss5_delivered(src, "default", 1.0))
            self.assertEqual(src.read_bytes(), before)

    def test_success_overwrites_pixels_and_keeps_the_workflow_chunks(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            src = self.deliverable(root)
            before = src.read_bytes()
            pixels = np.asarray(_frame(seed=99)).copy()
            pixels[:] = 255                       # an all-white re-render
            comfy = FakeComfy(root, pixels)
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_dlss5_http", side_effect=comfy):
                self.assertTrue(
                    server._dlss5_delivered(src, "cinematic", 1.5))
            self.assertNotEqual(src.read_bytes(), before)
            with Image.open(src) as out:
                self.assertEqual(out.info.get("prompt"),
                                 '{"9": {"class_type": "SaveImage"}}')
                self.assertTrue((np.asarray(out) == 255).all(),
                                "the delivered pixels are the node's output")
            # the graph went to the FRONT of the queue, with the brief's
            # fixed inputs and the caller's style/intensity
            post = comfy.posts[0]
            self.assertIs(post.get("front"), True)
            inputs = post["prompt"]["2"]["inputs"]
            self.assertEqual(post["prompt"]["2"]["class_type"],
                             "DLSS5NeuralRendering")
            self.assertEqual(inputs["style"], "cinematic")
            self.assertEqual(inputs["intensity"], 1.5)
            for key, want in server.DLSS5_FIXED.items():
                self.assertEqual(inputs[key], want, key)
            self.assertEqual(post["prompt"]["1"]["class_type"], "LoadImage")
            self.assertEqual(post["prompt"]["3"]["class_type"], "SaveImage")
            # temp files on BOTH sides are gone
            self.assertEqual(list((root / "input").glob("pixal_dlss5_*")), [])
            self.assertEqual(list((root / "output").glob("pixal_dlss5_*")), [])


class ChainOrderTests(unittest.TestCase):
    """The Hub delivery chokepoint: dlss5 first, upscale exempt."""

    def setUp(self):
        self.hub = object.__new__(server.Hub)
        self.hub.broadcast = lambda **kw: None

    def deliver(self, root, template, cfg, job=None, name="still.png"):
        job = job or {"id": "job0001", "template": template, "seen": set(),
                      "images": [], "seed": 424242, "info": {}}
        with patch.object(server, "CDIR", root), \
             patch.object(server, "load_config", return_value=cfg):
            self.hub.add_image(job, {"filename": name, "subfolder": "",
                                     "type": "output"})
        return job

    def test_dlss5_runs_before_de_shine_and_grain(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            _write_png(root / "output" / "still.png", _frame())
            calls = []
            cfg = {"still": {"dlss5": True, "de_shine": True,
                             "film_grain": True, "film_grain_amount": 1.6}}
            with patch.object(server, "_dlss5_delivered",
                              side_effect=lambda *a, **k: calls.append(
                                  "dlss5") or True), \
                 patch.object(server, "_de_shine_delivered",
                              side_effect=lambda *a, **k: calls.append(
                                  "de_shine") or True), \
                 patch.object(server, "_film_grain_delivered",
                              side_effect=lambda *a, **k: calls.append(
                                  "grain") or True):
                job = self.deliver(root, "realism", cfg)
            self.assertEqual(calls, ["dlss5", "de_shine", "grain"])
            # de-shine records itself since the hover chips (2026-09-01):
            # the chain reads in run order, dlss5 -> deshine -> grain
            self.assertEqual(job["info"]["finish"],
                             "dlss5@default+deshine+grain@1.6")

    def test_the_tag_records_the_style_and_a_non_default_intensity(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            _write_png(root / "output" / "still.png", _frame())
            cfg = {"still": {"dlss5": True, "dlss5_style": "cinematic",
                             "dlss5_intensity": 1.5}}
            with patch.object(server, "_dlss5_delivered", return_value=True):
                job = self.deliver(root, "realism", cfg)
            self.assertEqual(job["info"]["finish"], "dlss5@cinematic:1.5")

    def test_upscale_image_deliveries_are_exempt(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            _write_png(root / "output" / "upscaled.png", _frame())
            calls = []
            cfg = {"still": {"dlss5": True, "de_shine": True,
                             "film_grain": True, "film_grain_amount": 1.6}}
            with patch.object(server, "_dlss5_delivered",
                              side_effect=lambda *a, **k: calls.append(
                                  "dlss5") or True), \
                 patch.object(server, "_de_shine_delivered",
                              side_effect=lambda *a, **k: calls.append(
                                  "de_shine")), \
                 patch.object(server, "_film_grain_delivered",
                              side_effect=lambda *a, **k: calls.append(
                                  "grain") or True):
                job = self.deliver(root, "upscale_image", cfg,
                                   name="upscaled.png")
            self.assertEqual(calls, ["grain"],
                             "an upscale output must not be re-rendered; "
                             "grain belongs to final pixels and stays")
            self.assertEqual(job["info"]["finish"], "grain@1.6")

    def test_a_no_op_finisher_leaves_finish_unset(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            _write_png(root / "output" / "still.png", _frame())
            cfg = {"still": {"dlss5": True}}
            with patch.object(server, "_dlss5_delivered", return_value=False):
                job = self.deliver(root, "realism", cfg)
            self.assertNotIn("finish", job["info"])

    def test_the_toggle_off_is_byte_identical(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            src = root / "output" / "still.png"
            _write_png(src, _frame())
            before = src.read_bytes()
            self.deliver(root, "realism", {"still": {"dlss5": False}})
            self.assertEqual(src.read_bytes(), before)


class FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def full_cfg(still=None):
    return {"llm": {"base_url": "", "model": ""},
            "critic": {"model": ""}, "upscale": {}, "edit": {}, "vae": {},
            "pid": {}, "video": {"default_engine": "", "default_model": ""},
            "still": still or {}, "extra_model_roots": [],
            "comfy_editor": False, "comfy_console": "tui",
            "explicit": "auto", "vram_profile": "auto"}


class SettingsTests(unittest.TestCase):

    def post(self, body, cfg):
        saved = []
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "save_config",
                          side_effect=lambda c: saved.append(c)):
            response = asyncio.run(server.settings_post(FakeRequest(body)))
        return response, saved

    def get(self, cfg, names=None, root=None):
        patches = [patch.object(server, "load_config", return_value=cfg),
                   patch.object(server, "model_catalog", return_value=[]),
                   patch.object(server, "_video_asset",
                                side_effect=lambda _k, rel: rel),
                   patch.object(server, "refresh_comfy_nodes", AsyncMock()),
                   patch.dict(server._COMFY_NODES, {"names": names})]
        if root is not None:
            patches.append(patch.object(server, "CDIR", root))
        for p in patches:
            p.start()
        try:
            response = asyncio.run(server.settings_get(FakeRequest({})))
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(response.status, 200)
        return json.loads(response.text)["still"]

    def test_settings_round_trip(self):
        cfg = full_cfg()
        response, saved = self.post(
            {"still": {"dlss5": True, "dlss5_style": "cinematic",
                       "dlss5_intensity": 1.5}}, cfg)
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text), {"ok": True})
        self.assertIs(saved[0]["still"]["dlss5"], True)
        self.assertEqual(saved[0]["still"]["dlss5_style"], "cinematic")
        self.assertEqual(saved[0]["still"]["dlss5_intensity"], 1.5)

    def test_the_intensity_write_clamps_like_the_resolver(self):
        cfg = full_cfg()
        response, saved = self.post({"still": {"dlss5_intensity": 9.5}}, cfg)
        self.assertEqual(response.status, 200)
        self.assertEqual(saved[0]["still"]["dlss5_intensity"], 2.0)

    def test_settings_post_rejects_a_non_bool(self):
        for bad in ("true", 1, 0, None, [True]):
            with self.subTest(bad=bad):
                response, saved = self.post({"still": {"dlss5": bad}},
                                            full_cfg())
                self.assertEqual(response.status, 400)
                self.assertEqual(saved, [])

    def test_settings_post_rejects_an_unknown_style(self):
        for bad in ("3", "6", "Default", "", 3, None, ["default"]):
            with self.subTest(bad=bad):
                response, saved = self.post(
                    {"still": {"dlss5_style": bad}}, full_cfg())
                self.assertEqual(response.status, 400)
                self.assertEqual(saved, [])

    def test_settings_post_rejects_a_non_number_intensity(self):
        for bad in ("high", None, [1.0], float("nan")):
            with self.subTest(bad=bad):
                response, saved = self.post(
                    {"still": {"dlss5_intensity": bad}}, full_cfg())
                self.assertEqual(response.status, 400)
                self.assertEqual(saved, [])

    def test_settings_get_publishes_the_keys_for_an_old_config(self):
        still = self.get(full_cfg({"skin_finish": True}))
        self.assertIs(still["dlss5"], False)
        self.assertEqual(still["dlss5_style"], "default")
        self.assertEqual(still["dlss5_intensity"], 1.0)

    def test_settings_get_publishes_availability(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _stage_root(root)
            still = self.get(full_cfg(), names=frozenset({server.DLSS5_NODE}),
                             root=root)
            self.assertIs(still["dlss5_available"], True)
            still = self.get(full_cfg(), names=frozenset(), root=root)
            self.assertIs(still["dlss5_available"], False,
                          "an empty object_info is unavailable")
            still = self.get(full_cfg(), names=None, root=root)
            self.assertIs(still["dlss5_available"], False,
                          "a cold ComfyUI is unavailable")


if __name__ == "__main__":
    unittest.main()
