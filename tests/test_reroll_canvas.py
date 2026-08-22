import asyncio
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock, patch


_SPEC = spec_from_file_location(
    "pixal_server_reroll_canvas", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class RerollCanvasTests(unittest.TestCase):
    """The composer is the truth: a re-roll rolls at the canvas the user is
    LOOKING at, but a bad or absent one degrades to the card's stored canvas
    rather than killing the re-roll."""

    ENTRY = {"id": "abc12345", "template": "realism", "scene": "a shot",
             "seed": 424242, "count": 1,
             "spec": {"aspect": "1:1 (Square)", "mp": 2.0, "standing": True}}

    def roll(self, body, entry=None):
        submit = AsyncMock()
        with patch.object(server.HUB, "ledger_read",
                          return_value=[entry or dict(self.ENTRY)]), \
             patch.object(server.HUB, "submit", submit):
            async def run():
                await server.reroll(FakeRequest(body))
                await asyncio.sleep(0)      # let the created task settle
            asyncio.run(run())
        return submit.call_args

    def test_live_canvas_lands_on_the_resubmitted_spec(self):
        call = self.roll({"id": "abc12345", "aspect": "16:9 (Widescreen)",
                          "mp": 1.5})
        spec = call.args[4]
        self.assertEqual(spec["aspect"], "16:9 (Widescreen)")
        self.assertEqual(spec["mp"], 1.5)

    def test_an_unknown_aspect_falls_back_to_the_stored_one(self):
        call = self.roll({"id": "abc12345", "aspect": "4:5 (IG Portrait)"})
        self.assertEqual(call.args[4]["aspect"], "1:1 (Square)")

    def test_a_bad_mp_falls_back_to_the_stored_one(self):
        # 0 and negatives would divide dims_for into the floor; a string or a
        # bool is not a megapixel count at all. Each degrades, none 4xx-es.
        for bad in (0, -1.5, "lots", True):
            with self.subTest(mp=bad):
                call = self.roll({"id": "abc12345", "mp": bad})
                self.assertEqual(call.args[4]["mp"], 2.0)

    def test_an_omitted_canvas_leaves_the_stored_spec_untouched(self):
        # The stale-bundle regression: a client that predates the canvas keys
        # must get the card's own canvas, not a wiped one.
        call = self.roll({"id": "abc12345"})
        spec = call.args[4]
        self.assertEqual(spec["aspect"], "1:1 (Square)")
        self.assertEqual(spec["mp"], 2.0)

    def test_a_fixed_canvas_recipe_ignores_the_live_canvas(self):
        # qwen_edit's recipe aspect is "" - its dimensions come from the
        # source image, so the composer canvas must not be forced onto it.
        entry = {"id": "q1234567", "template": "qwen_edit",
                 "scene": "make it blue", "seed": 7, "count": 1,
                 "spec": {"megapixels": 1.0}}
        call = self.roll({"id": "q1234567", "aspect": "1:1 (Square)",
                          "mp": 2.0}, entry=entry)
        self.assertEqual(call.args[4], {"megapixels": 1.0})

    def test_seed_lock_still_replays_the_exact_seed_with_a_canvas(self):
        call = self.roll({"id": "abc12345", "lock_seed": True,
                          "aspect": "16:9 (Widescreen)", "mp": 1.5})
        spec = call.args[4]
        self.assertEqual(spec["seed"], 424242)
        self.assertEqual(spec["aspect"], "16:9 (Widescreen)")
        self.assertEqual(spec["mp"], 1.5)


if __name__ == "__main__":
    unittest.main()
