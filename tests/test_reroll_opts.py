import asyncio
import json
import unittest
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch


_SPEC = spec_from_file_location(
    "pixal_server_reroll_opts", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def model(rel, family, variant="any", **extra):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True, **extra}


KREA = model("Krea 2\\analogMadnessKrea2Turbo_v20.safetensors", "krea2")


@contextmanager
def mia_anchor(reference=True):
    """A characters/mia.json-shaped anchor whose identity_ref file exists under
    a temp ComfyUI/input - or is deliberately absent, for the 400."""
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        character = {"id": "mia", "name": "Mia", "style": "copper bob",
                     "identity_ref": "mia.png"}
        if reference:
            (root / "input" / "mia.png").write_bytes(b"reference")
        with patch.object(server, "CDIR", root), \
             patch.object(server, "CHARACTERS", {"mia": character}):
            yield character


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class RerollOptsTests(unittest.TestCase):
    """Brief 9.42: a bundle carrying `opts` - the same object the composer
    sends /api/chat - re-rolls the card's SCENE under the composer's whole
    live state, through the same _apply_opts overlay chat uses. No opts, or a
    card whose recipe is not composer-owned, is today's route byte for byte."""

    # Deliberately dirty: a card born under a preset carries its tuning and
    # receipt, and `ref` rides along to prove the strip list - the point is
    # that nothing the composer owns may leak from the stored spec.
    ENTRY = {"id": "abc12345", "template": "realism", "scene": "a shot",
             "seed": 424242, "count": 1,
             "spec": {"model": "Social\\social_realism.safetensors",
                      "loras": ["social_lora:0.8"],
                      "lora_plan": {"version": 1, "mode": "replace_editable",
                                    "recipe": "realism", "recipe_revision": 1,
                                    "entries": []},
                      "aspect": "1:1 (Square)", "mp": 2.0,
                      "overrides": [{"node": "99", "input": "steps", "value": 4}],
                      "_style": {"id": "social_realism",
                                 "name": "Social Realism", "base": "realism"},
                      "ref": "stale_face.png",
                      "standing": True, "nsfw": False}}

    def roll(self, body, entry=None):
        submit = AsyncMock()
        with patch.object(server.HUB, "ledger_read",
                          return_value=[entry or dict(self.ENTRY)]), \
             patch.object(server.HUB, "submit", submit):
            async def run():
                resp = await server.reroll(FakeRequest(body))
                await asyncio.sleep(0)      # let the created task settle
                return resp
            resp = asyncio.run(run())
        return resp, submit.call_args

    def test_a_character_rerolls_onto_the_identity_graph(self):
        with mia_anchor():
            resp, call = self.roll({"id": "abc12345",
                                    "opts": {"character": "mia",
                                             "prompt_enhance": True}})
        self.assertEqual(resp.status, 200)
        self.assertEqual(call.args[1], "reroll")            # lineage intact
        self.assertEqual(call.args[2], "identity_edit")     # the pinned recipe
        self.assertEqual(call.args[3], "a shot")            # the card's scene
        self.assertEqual(call.kwargs["parent"], "abc12345")
        # The face is Mia's; not one stored field - model, stack, canvas,
        # tuning, receipt, ref - leaks through the overlay.
        self.assertEqual(call.args[4],
                         {"standing": True, "nsfw": False, "character": "mia"})

    def test_a_character_without_a_reference_is_a_400_never_a_stranger(self):
        with mia_anchor(reference=False):
            resp, call = self.roll({"id": "abc12345",
                                    "opts": {"character": "mia"}})
        self.assertEqual(resp.status, 400)
        payload = json.loads(resp.body)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"],
                         "Mia's reference image is missing from ComfyUI/input: "
                         "mia.png")
        self.assertIsNone(call)                     # submit never ran

    def test_a_saved_style_replaces_the_cards_whole_stack(self):
        record = server.validate_saved_style(
            {"schema_version": 1, "name": "Grainy Portrait", "base": "realism",
             "model": KREA["rel"], "tuning": {"steps": 20}})
        with patch.dict(server.SAVED_STYLES, {record["id"]: record}):
            resp, call = self.roll({"id": "abc12345",
                                    "opts": {"saved_style": record["id"],
                                             "prompt_enhance": True}})
        self.assertEqual(resp.status, 200)
        self.assertEqual(call.args[2], "realism")   # the style's own base
        # The card can name the preset, and the tuning is the STYLE'S - the
        # stored spec's overrides are gone, not merged; the stored model,
        # plan and canvas leave with them.
        self.assertEqual(call.args[4],
                         {"standing": True, "nsfw": False,
                          "_style": {"id": record["id"],
                                     "name": "Grainy Portrait",
                                     "base": "realism"},
                          "model": KREA["rel"],
                          "overrides": [{"node": "30:51", "input": "steps",
                                         "value": 20}]})

    def test_no_character_sends_an_identity_card_back_to_the_base_recipe(self):
        # The flip side Jesse hits next: turn Mia OFF and re-roll her card -
        # the child is a plain Realism render, and her ref and dials leave
        # with her.
        entry = {"id": "id123456", "template": "identity_edit",
                 "scene": "mia on a roof", "seed": 99, "count": 1,
                 "spec": {"character": "mia", "model": KREA["rel"],
                          "lora_plan": {"version": 1, "mode": "replace_editable",
                                        "recipe": "identity_edit",
                                        "recipe_revision": 1, "entries": []},
                          "ref_boost": 5.0, "grounding": 640,
                          "bypass_variant": 3,
                          "standing": True}}
        resp, call = self.roll({"id": "id123456",
                                "opts": {"engine": "realism", "style": "realism",
                                         "quality": "standard",
                                         "prompt_enhance": True}}, entry=entry)
        self.assertEqual(resp.status, 200)
        self.assertEqual(call.args[2], "realism")   # the overlay's base recipe
        self.assertEqual(call.kwargs["parent"], "id123456")
        self.assertEqual(call.args[4], {"standing": True})

    def test_opts_on_a_source_only_card_is_todays_route_byte_for_byte(self):
        # qwen_edit's recipe aspect is "" - the composer does not own it, so a
        # bundle WITH opts submits exactly what the same bundle without opts
        # submits (oracle: test_reroll_canvas's fixed-canvas case). Mia is
        # deliberately unpatched: the legacy path must never even read opts.
        entry = {"id": "q1234567", "template": "qwen_edit",
                 "scene": "make it blue", "seed": 7, "count": 1,
                 "spec": {"megapixels": 1.0}}
        resp, call = self.roll({"id": "q1234567", "aspect": "1:1 (Square)",
                                "mp": 2.0, "opts": {"character": "mia"}},
                               entry=entry)
        self.assertEqual(resp.status, 200)
        self.assertEqual(call.args[2], "qwen_edit")
        self.assertEqual(call.args[4], {"megapixels": 1.0})

    def test_no_opts_is_todays_route_byte_for_byte(self):
        # A stale bundle (oracle: test_reroll_canvas's omitted-canvas case):
        # the stored spec rides untouched.
        entry = {"id": "abc12345", "template": "realism", "scene": "a shot",
                 "seed": 424242, "count": 1,
                 "spec": {"aspect": "1:1 (Square)", "mp": 2.0,
                          "standing": True}}
        resp, call = self.roll({"id": "abc12345"}, entry=entry)
        self.assertEqual(resp.status, 200)
        self.assertEqual(call.args[4], {"aspect": "1:1 (Square)", "mp": 2.0,
                                        "standing": True})

    def test_lock_seed_and_the_held_seed_still_land_with_a_character(self):
        with mia_anchor():
            # A locked card replays its own exact seed...
            _, call = self.roll({"id": "abc12345", "lock_seed": True,
                                 "opts": {"character": "mia"}})
            self.assertEqual(call.args[4]["seed"], 424242)
            self.assertEqual(call.args[4]["character"], "mia")
            # ...and the composer's held seed rides when no card is locked.
            _, call = self.roll({"id": "abc12345", "seed": 777,
                                 "opts": {"character": "mia"}})
            self.assertEqual(call.args[4]["seed"], 777)
            self.assertEqual(call.args[4]["character"], "mia")


if __name__ == "__main__":
    unittest.main()
