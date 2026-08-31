"""Brief 9.93 - AI Skin Shine Removal.

The de-shine finish from docs/2026-08-30-h3-ref-realism.md, shipped as one
Settings toggle. The doc's own words were "No home. It is numpy operating on
a decoded frame"; the home it got is the Hub's delivery chokepoint, where it
runs on every still lane's decoded frame before any upscale pass can read
the file. Jesse judged the chain at 1:1 on 2026-08-31 and asked for the
gentler shipped defaults: strength 0.55 at the 93rd percentile (the doc's
0.85 / 88th stay reachable as arguments).

What these tests pin:

  ToneAgnostic    - the same synthetic face at three skin tones yields a
                    mask of comparable relative area. Chrominance-only
                    detection is the whole point; a luminance gate would
                    collapse the dark tone's mask.
  NeverBrightens  - a property over several arrays, not one case: every
                    output pixel <= its input. The min() in step 5 is the
                    mechanism; swapping it for max() must go red.
  WhiteShirt      - a blown-out non-skin region is untouched AND the skin
                    highlight is still darkened. Both halves exist because
                    the percentile is measured inside the skin mask: a
                    frame-wide percentile would let the shirt set the
                    threshold and blind the pass.
  EyesTeeth       - patches outside the skin chrominance range (eye white
                    fails Cb, teeth fail the Cr floor) are unchanged while
                    the skin around them darkens.
  Strength        - 0 is the identity transform, and darkening grows
                    monotonically with strength.
  Defaults        - the shipped defaults ARE 0.55 / 93rd, pinned as code,
                    not a comment; the doc's 0.85 / 88th are pinned as the
                    reachable constants; the shipped setting darkens
                    strictly less than the doc's on the same frame.
  Delivery        - the toggle off is byte-identical; the toggle on
                    rewrites the delivered still in place, keeps the PNG's
                    embedded prompt/workflow, and leaves a no-skin frame
                    byte-identical.
  Order           - with both on, de-shine precedes the upscale model: a
                    still delivery is processed, an upscale_image delivery
                    is exempt, so the file the upscale action stages has
                    already been de-shined and the pass never measures
                    already-textured skin.
  Settings        - load_config defaults the key off, settings_get
                    publishes it (off for a pre-9.93 config), settings_post
                    round-trips a real bool and rejects truthy stand-ins
                    without saving.

Same sanctioned simulation as every sibling file: synthetic numpy/PIL
arrays, stubbed config, no generation, no ComfyUI, no GPU, no server.
"""

import asyncio
import inspect
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
_SPEC = spec_from_file_location("pixal_server_de_shine", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

BG = (28, 32, 38)
EYE = (246, 249, 252)        # eye white: Cb ~130, above the skin range
TEETH = (240, 236, 222)      # teeth: Cr ~131, below the skin range's floor
SHIRT = (252, 252, 252)      # blown-out white: outside both ranges
TONES = [(230, 190, 160), (190, 140, 110), (140, 95, 75)]   # light/mid/dark


def face(tone=(190, 140, 110), size=160, shirt=False, features=False):
    """A synthetic face: `tone` under a smooth left-to-right shading ramp
    (a face has real shading worth keeping), one hotter specular patch on
    the same chroma, on a dark non-skin background. `shirt` adds a blown
    white block well clear of the face; `features` embeds eye and teeth
    patches in the cheek, far from every hot pixel."""
    yy, xx = np.mgrid[0:size, 0:size].astype(float)
    shading = 1.0 + 0.22 * (xx / size)
    img = np.zeros((size, size, 3), np.uint8)
    img[:] = BG
    oval = ((yy - size * 0.42) / (size * 0.28)) ** 2 + \
           ((xx - size * 0.50) / (size * 0.42)) ** 2 <= 1
    tone_arr = np.array(tone, float)
    img[oval] = (tone_arr * shading[oval][:, None]).clip(0, 255).astype(np.uint8)
    img[30:46, 88:118] = (tone_arr + (55, 45, 35)).clip(0, 255).astype(np.uint8)
    if features:
        img[60:66, 30:38] = EYE      # cheek, away from the hot pixels
        img[68:74, 46:56] = TEETH
    if shirt:
        img[int(size * 0.78):, :] = SHIRT
    return Image.fromarray(img)


def arr(im):
    return np.asarray(im.convert("RGB")).astype(int)


class DeShineAlgorithmTests(unittest.TestCase):

    def test_tone_agnostic_mask_area(self):
        covered = []
        for tone in TONES:
            out, cov = server.de_shine(face(tone))
            self.assertGreater(cov, 0.0, f"tone {tone} produced no mask at all")
            covered.append(cov)
        ratio = max(covered) / min(covered)
        self.assertLessEqual(ratio, 1.2,
                             f"mask area swung {ratio:.2f}x across tones: {covered}")

    def test_never_brightens(self):
        cases = [face(tone) for tone in TONES]
        for seed in range(3):
            rng = np.random.default_rng(seed)
            noise = rng.integers(0, 256, (120, 120, 3)).astype(np.uint8)
            blob = (np.array((190, 140, 110)) +
                    rng.integers(-40, 41, (60, 60, 3))).clip(0, 255)
            noise[30:90, 30:90] = blob.astype(np.uint8)
            cases.append(Image.fromarray(noise))
        for im in cases:
            out, _ = server.de_shine(im)
            self.assertTrue((arr(out) <= arr(im)).all(),
                            "an output pixel sits above its input")

    def test_a_white_shirt_is_not_a_highlight(self):
        im = face(shirt=True)
        src = arr(im)
        out, cov = server.de_shine(im)
        dst = arr(out)
        self.assertGreater(cov, 0.0)
        # the shirt never moves by more than rounding
        shirt_rows = slice(int(160 * 0.78), 160)
        self.assertLessEqual(np.abs(dst[shirt_rows] - src[shirt_rows]).max(), 1)
        # and the pass was not blinded by it: the skin highlight still fell
        self.assertGreaterEqual((src[38, 103] - dst[38, 103]).max(), 5,
                                "the specular patch was left at full shine")

    def test_eyes_and_teeth_survive(self):
        im = face(features=True)
        src = arr(im)
        out, cov = server.de_shine(im)
        dst = arr(out)
        self.assertGreater(cov, 0.0)
        self.assertTrue((dst[60:66, 30:38] == src[60:66, 30:38]).all(),
                        "the eye patch moved")
        self.assertTrue((dst[68:74, 46:56] == src[68:74, 46:56]).all(),
                        "the teeth patch moved")
        self.assertGreater((src[38, 103] - dst[38, 103]).max(), 0,
                           "nothing darkened - the assertions above are vacuous")

    def test_strength_zero_is_identity_and_the_effect_is_monotonic(self):
        im = face()
        identical, cov = server.de_shine(im, strength=0.0)
        self.assertEqual(cov, 0.0)
        self.assertTrue(np.array_equal(arr(identical), arr(im)))
        drops = []
        for strength in (0.2, 0.55, 0.85):
            out, _ = server.de_shine(im, strength=strength)
            drops.append((arr(im) - arr(out)).clip(0).sum())
        self.assertLess(drops[0], drops[1])
        self.assertLess(drops[1], drops[2])

    def test_the_shipped_defaults_are_055_at_the_93rd(self):
        sig = inspect.signature(server.de_shine)
        self.assertEqual(sig.parameters["strength"].default, 0.55)
        self.assertEqual(sig.parameters["percentile"].default, 93.0)
        self.assertEqual(server.DE_SHINE_STRENGTH, 0.55)
        self.assertEqual(server.DE_SHINE_PERCENTILE, 93.0)
        # the doc's numbers stay reachable as arguments, pinned as constants
        self.assertEqual(server.DE_SHINE_DOC_STRENGTH, 0.85)
        self.assertEqual(server.DE_SHINE_DOC_PERCENTILE, 88.0)
        # and the shipped setting is strictly gentler on the same frame
        im = face()
        gentle, _ = server.de_shine(im)
        strong, _ = server.de_shine(
            im, strength=server.DE_SHINE_DOC_STRENGTH,
            percentile=server.DE_SHINE_DOC_PERCENTILE)
        drop_g = (arr(im) - arr(gentle)).clip(0).sum()
        drop_s = (arr(im) - arr(strong)).clip(0).sum()
        self.assertGreater(drop_g, 0)
        self.assertLess(drop_g, drop_s)


def _write_png(path, im):
    info = PngInfo()
    info.add_text("prompt", '{"9": {"class_type": "SaveImage"}}')
    im.save(path, pnginfo=info)


class DeliveryTests(unittest.TestCase):
    """The Hub delivery chokepoint: one hook, every still lane."""

    def setUp(self):
        self.hub = object.__new__(server.Hub)
        self.hub.broadcast = lambda **kw: None

    def deliver(self, root, template, cfg, name="still.png"):
        job = {"id": "job0001", "template": template, "seen": set(), "images": []}
        with patch.object(server, "CDIR", root), \
             patch.object(server, "load_config", return_value=cfg):
            self.hub.add_image(job, {"filename": name, "subfolder": "",
                                     "type": "output"})
        return job

    def test_off_is_byte_identical(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            src = root / "output" / "still.png"
            _write_png(src, face())
            before = src.read_bytes()
            self.deliver(root, "realism", {"still": {"de_shine": False}})
            self.assertEqual(src.read_bytes(), before)

    def test_on_rewrites_the_still_and_keeps_the_embedded_graph(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            src = root / "output" / "still.png"
            _write_png(src, face())
            before = src.read_bytes()
            self.deliver(root, "realism", {"still": {"de_shine": True}})
            after = src.read_bytes()
            self.assertNotEqual(after, before)
            with Image.open(src) as im:
                self.assertEqual(im.text.get("prompt"),
                                 '{"9": {"class_type": "SaveImage"}}')
                self.assertTrue((arr(im) <= arr(face())).all())

    def test_a_frame_without_skin_is_left_byte_identical(self):
        rng = np.random.default_rng(11)
        # green-dominant noise: Cr sits far below the skin range for every pixel
        green = np.stack([rng.integers(0, 31, (90, 90)),
                          rng.integers(150, 256, (90, 90)),
                          rng.integers(0, 31, (90, 90))], axis=-1).astype(np.uint8)
        # JPEG on purpose: a pixel-identical PNG re-save is byte-identical and
        # could not catch a missing early-out; a JPEG re-encode always moves
        # bytes, so "left alone" is observable here.
        grey = Image.fromarray(green)
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            src = root / "output" / "still.jpg"
            grey.save(src, "JPEG", quality=90)
            before = src.read_bytes()
            self.deliver(root, "realism", {"still": {"de_shine": True}},
                         name="still.jpg")
            self.assertEqual(src.read_bytes(), before)

    def test_de_shine_precedes_the_upscale_model(self):
        # The ordering is structural: de-shine runs at delivery, the upscale
        # action stages an already-delivered file, and the upscale lane's own
        # output is exempt - so the percentile is never measured on
        # already-textured skin.
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            still = root / "output" / "still.png"
            _write_png(still, face())
            cfg = {"still": {"de_shine": True}}
            self.deliver(root, "realism", cfg)
            de_shined = still.read_bytes()
            self.assertNotEqual(de_shined, None)
            upscaled = root / "output" / "upscaled.png"
            _write_png(upscaled, face())
            before = upscaled.read_bytes()
            self.deliver(root, "upscale_image", cfg, name="upscaled.png")
            self.assertEqual(upscaled.read_bytes(), before,
                             "an upscale delivery must not be de-shined again")


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

    def test_load_config_defaults_the_toggle_off(self):
        with patch.object(server, "CONFIG", Path("does-not-exist.json")):
            self.assertFalse(server.load_config()["still"]["de_shine"])
        # and a config saved before the key existed reads as off too
        with patch.object(server, "load_config", return_value={}):
            self.assertFalse(server.still_de_shine_active())

    def test_settings_round_trip(self):
        cfg = full_cfg()
        saved = []
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "_video_asset", side_effect=lambda _k, rel: rel), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()), \
             patch.object(server, "save_config",
                          side_effect=lambda c: saved.append(c)):
            post = asyncio.run(server.settings_post(
                FakeRequest({"still": {"de_shine": True}})))
            self.assertEqual(post.status, 200)
            self.assertEqual(json.loads(post.text), {"ok": True})
            response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        still = json.loads(response.text)["still"]
        self.assertIs(still["de_shine"], True)
        self.assertIs(saved[0]["still"]["de_shine"], True)

    def test_settings_get_defaults_off_for_an_old_config(self):
        with patch.object(server, "load_config",
                          return_value=full_cfg({"skin_finish": True})), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "_video_asset", side_effect=lambda _k, rel: rel), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()):
            response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        self.assertIs(json.loads(response.text)["still"]["de_shine"], False)

    def test_settings_post_rejects_a_non_bool(self):
        for bad in ("true", 1, 0, None, [True]):
            with self.subTest(bad=bad):
                saved = []
                with patch.object(server, "load_config",
                                  return_value=full_cfg()), \
                     patch.object(server, "save_config",
                                  side_effect=lambda c: saved.append(c)):
                    response = asyncio.run(server.settings_post(
                        FakeRequest({"still": {"de_shine": bad}})))
                self.assertEqual(response.status, 400)
                self.assertEqual(json.loads(response.text),
                                 {"ok": False, "error": f"not a bool: {bad}"})
                self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
