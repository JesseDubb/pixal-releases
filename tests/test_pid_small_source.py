"""PiD's small-edge cliff, and Pixal stepping over it.

ComfyUI-PiD's 2kto4k profile has small_edge = 1024. At 1024 and above a
1:1 source is a single tile - 4 sampler steps. One pixel below, _planned_pid_calls
takes the other branch: resize to 1024, spend a whole 4x pass to reach 4096,
tile THAT into 5x5, then downsample the stitched 16k canvas back to source*4.
26 passes, 104 steps, for a SMALLER picture.

Measured on the live machine 2026-08-22, same frame and settings:
    832 straight to PiD    26 passes   223.5s   ->  3328x3328
    832 lifted to 1024      4 passes    24.2s   ->  4096x4096

Pixal's own 1:1 @ 1MP canvas is 992 - thirty-two pixels under the cliff - so
this was firing on the most ordinary upscale there is.
"""
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import server


class LiftDecision(unittest.TestCase):
    """pid_lift_small_source, against real files in a temp ComfyUI input dir."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cdir = Path(self.tmp.name)
        (self.cdir / "input").mkdir()
        self.p = patch.object(server, "CDIR", self.cdir)
        self.p.start()
        self.addCleanup(self.p.stop)

    def _make(self, name, size):
        Image.new("RGB", size, (90, 110, 130)).save(self.cdir / "input" / name)
        return name

    def _size(self, name):
        with Image.open(self.cdir / "input" / name) as im:
            return im.size

    def test_a_square_under_the_cliff_is_lifted_to_exactly_1024(self):
        out = server.pid_lift_small_source(self._make("small.png", (832, 832)))
        self.assertNotEqual(out, "small.png")
        self.assertEqual(self._size(out), (1024, 1024))

    def test_pixals_own_1mp_square_is_lifted(self):
        """992 is what 1:1 @ 1MP resolves to. It was 32px from the fast path."""
        out = server.pid_lift_small_source(self._make("mp.png", (992, 992)))
        self.assertEqual(self._size(out), (1024, 1024))

    def test_exactly_1024_is_left_alone(self):
        """small_edge is a >= test in the pack. 1024 is already fast."""
        name = self._make("edge.png", (1024, 1024))
        self.assertEqual(server.pid_lift_small_source(name), name)

    def test_a_big_source_is_left_alone(self):
        name = self._make("big.png", (1536, 2048))
        self.assertEqual(server.pid_lift_small_source(name), name)

    def test_a_portrait_keeps_its_aspect_and_pins_the_long_edge(self):
        out = server.pid_lift_small_source(self._make("tall.png", (512, 768)))
        w, h = self._size(out)
        self.assertEqual(h, 1024)                      # long edge pinned
        self.assertEqual(w % 16, 0)                    # latent-friendly
        self.assertAlmostEqual(w / h, 512 / 768, places=1)

    def test_a_landscape_keeps_its_aspect_and_pins_the_long_edge(self):
        out = server.pid_lift_small_source(self._make("wide.png", (900, 600)))
        w, h = self._size(out)
        self.assertEqual(w, 1024)
        self.assertEqual(h % 16, 0)
        self.assertAlmostEqual(w / h, 900 / 600, places=1)

    def test_the_lift_is_reused_not_rewritten(self):
        name = self._make("again.png", (832, 832))
        first = server.pid_lift_small_source(name)
        stamp = (self.cdir / "input" / first).stat().st_mtime_ns
        self.assertEqual(server.pid_lift_small_source(name), first)
        self.assertEqual((self.cdir / "input" / first).stat().st_mtime_ns, stamp)

    def test_an_unreadable_source_upscales_as_it_always_did(self):
        """A broken lift must never take the upscale down with it."""
        (self.cdir / "input" / "junk.png").write_bytes(b"not a png")
        self.assertEqual(server.pid_lift_small_source("junk.png"), "junk.png")

    def test_a_missing_source_upscales_as_it_always_did(self):
        self.assertEqual(server.pid_lift_small_source("nope.png"), "nope.png")


class GraphWiring(unittest.TestCase):
    """The lifted frame must feed the SAMPLER only - never the captioner."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cdir = Path(self.tmp.name)
        (self.cdir / "input").mkdir()
        for name, size in (("small.png", (832, 832)), ("big.png", (2048, 2048))):
            Image.new("RGB", size, (90, 110, 130)).save(self.cdir / "input" / name)
        for p in (patch.object(server, "CDIR", self.cdir),
                  patch.object(server, "_pid_upscale_available", lambda: True),
                  patch.object(server, "_pid_node_available", lambda _n: True)):
            p.start()
            self.addCleanup(p.stop)

    def _graph(self, image):
        g, _scene, info = server.build_upscale_image("a frame", 1, image=image,
                                                     mode="pid")
        return g, info

    def test_a_small_source_samples_the_lift_and_captions_the_original(self):
        g, info = self._graph("small.png")
        self.assertIn("up:liftimg", g)
        self.assertEqual(g["up:pid"]["inputs"]["image"], ["up:liftimg", 0])
        self.assertEqual(g["up:img"]["inputs"]["image"], "small.png")
        self.assertIn("lifted", info)

    def test_a_large_source_is_wired_exactly_as_before(self):
        g, info = self._graph("big.png")
        self.assertNotIn("up:liftimg", g)
        self.assertNotIn("lifted", info)
        self.assertEqual(g["up:img"]["inputs"]["image"], "big.png")


if __name__ == "__main__":
    unittest.main()
