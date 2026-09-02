"""10.7 - "go" fires the pending draft mechanically, before the brain.

Jesse, 2026-09-02: "If I say go the system should just literally and
mechanically fire the render!" A pure accept of a drafted scene used to pay
one full brain round (and, that night, a "kimi-k3 is busy - trying again in
3s" retry) before 10.4's backstop queued the draft the server already held.
Now the accept turn never reaches the brain: the draft is scrubbed and
queued straight away, the receipt lands in the convo, and the pending walk
comes up empty so the Generate / Something else pills retire.

Every other shape of turn still goes to the brain exactly as before.
"""

import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_accept_fires", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

DRAFT = ("She squats low on her haunches, elbows on knees, directly in "
         "front of a lime-green supercar with a low wedge nose and black "
         "wheels, camera at her eye level a few steps back, late sun "
         "raking the flank, an empty rooftop car park and a low skyline "
         "behind her, platinum ponytail, a small challenging half-smile. "
         "Say go and I'll fire it.")


def run_turn(user_text, convo, enhance=True):
    """One turn with the GPU and the brain replaced by capture stubs.
    Returns (scenes submitted, brain calls made, lane texts)."""
    submitted, brain_calls, said = [], [], []

    async def fake_submit(cid, src, template, scene, spec, count=1,
                          parent=None, flags=None, verbatim=False):
        submitted.append({"template": template, "scene": scene, "spec": spec})
        return {"id": "ab12cd34", "error": None}

    async def fake_llm(messages, tools=None, cid=None):
        brain_calls.append([t.get("function", {}).get("name")
                            for t in (tools or [])])
        return 200, {"choices": [{"message": {"role": "assistant",
                                              "content": "Done."}}]}

    cfg = json.loads(json.dumps(server.load_config()))
    cfg["llm"]["base_url"] = "https://api.moonshot.example/v1"
    real = (server.HUB.submit, server.llm_call, server.HUB.broadcast)
    server.HUB.submit, server.llm_call = fake_submit, fake_llm
    server.HUB.broadcast = lambda **kw: (
        said.append(kw.get("text")) if kw.get("type") == "text" else None)
    try:
        with patch.object(server, "load_config", return_value=cfg):
            asyncio.run(server._kimi_reply(
                "testcid", {"role": "user", "content": user_text}, convo,
                {"prompt_enhance": enhance}))
    finally:
        server.HUB.submit, server.llm_call, server.HUB.broadcast = real
    return submitted, brain_calls, said


def drafted():
    return [{"role": "user", "content": "zara by a supercar"},
            {"role": "assistant", "content": DRAFT}]


class APureAcceptFiresWithoutTheBrain(unittest.TestCase):

    def test_go_queues_the_draft_and_never_calls_the_brain(self):
        convo = drafted()
        submitted, brain_calls, said = run_turn("go", convo)
        self.assertEqual(brain_calls, [], "the accept turn paid a brain round")
        self.assertEqual(len(submitted), 1)
        self.assertIn("lime-green supercar", submitted[0]["scene"])
        self.assertNotIn("Say go", submitted[0]["scene"],
                         "the invite tail must be stripped")
        self.assertIn("Got it — firing the draft.", said)

    def test_the_queued_scene_is_exactly_what_the_backstop_queued(self):
        """Byte-identical to 10.4's rescue: the same scrub chain on the same
        draft, the same template resolution, the same writer tag."""
        convo = drafted()
        submitted, _, _ = run_turn("go", convo)
        expected = server.strip_seed_prose(server.scrub_style_caption(
            server._scene_from_prose(DRAFT), "realism"))
        self.assertEqual(submitted[0]["scene"], expected)
        self.assertEqual(submitted[0]["template"], "realism")
        self.assertEqual(submitted[0]["spec"].get("_writer"), "pixal")

    def test_every_accept_phrase_fires(self):
        for phrase in ("go", "render it", "show me", "yes", "do it"):
            with self.subTest(phrase=phrase):
                submitted, brain_calls, _ = run_turn(phrase, drafted())
                self.assertEqual(brain_calls, [])
                self.assertEqual(len(submitted), 1)

    def test_the_receipt_lands_and_the_draft_stops_pending(self):
        convo = drafted()
        run_turn("go", convo)
        self.assertEqual(convo[-1]["role"], "user")
        self.assertRegex(convo[-1]["content"], server._QUEUED_SCENE_RECEIPT_RE)
        self.assertIsNone(server._pending_scene(convo),
                          "the pills would stay armed on a fired draft")

    def test_the_go_itself_is_in_the_history_before_the_receipt(self):
        convo = drafted()
        run_turn("go", convo)
        self.assertEqual(convo[-2], {"role": "user", "content": "go"})

    def test_a_buried_draft_still_fires_after_brain_chatter(self):
        """The 10.4 cascade: a short apology between the draft and the
        accept must not hide the draft from the mechanical path."""
        convo = drafted() + [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "That go didn't arm the trigger "
             "on my side - say render it and I'll fire the shot."}]
        submitted, brain_calls, _ = run_turn("render it", convo)
        self.assertEqual(brain_calls, [])
        self.assertEqual(len(submitted), 1)
        self.assertIn("lime-green supercar", submitted[0]["scene"])


class EveryOtherTurnStillReachesTheBrain(unittest.TestCase):

    def test_a_substantive_redirect_is_the_brains_merge(self):
        submitted, brain_calls, _ = run_turn("make the car sunset orange",
                                             drafted())
        self.assertEqual(len(brain_calls), 1)
        self.assertEqual(submitted, [])

    def test_an_accept_with_nothing_pending_is_a_brain_turn(self):
        convo = [{"role": "user", "content": "hi"},
                 {"role": "assistant", "content": "Hey - what shall we shoot?"}]
        _, brain_calls, _ = run_turn("go", convo)
        self.assertEqual(len(brain_calls), 1)

    def test_a_pending_question_answer_is_shaped_by_the_brain(self):
        convo = [{"role": "user", "content": "zara having fun"},
                 {"role": "assistant",
                  "content": "What kind of fun - beach, arcade, rooftop?"}]
        _, brain_calls, _ = run_turn("yes", convo)
        self.assertEqual(len(brain_calls), 1)

    def test_an_iteration_on_the_draft_is_the_brains_merge(self):
        _, brain_calls, _ = run_turn("same but her jacket red", drafted())
        self.assertEqual(len(brain_calls), 1)

    def test_a_fired_draft_does_not_fire_twice(self):
        convo = drafted()
        run_turn("go", convo)
        submitted, brain_calls, _ = run_turn("go", convo)
        self.assertEqual(submitted, [], "the receipt must close the draft")
        self.assertEqual(len(brain_calls), 1)


class TheRescueBranchSharesTheHelper(unittest.TestCase):
    """Source pins: one queue path, not two copies that drift."""

    SRC = (ROOT / "server.py").read_text(encoding="utf-8")

    def test_the_helper_exists_and_both_paths_call_it(self):
        self.assertIn("async def _fire_scene(", self.SRC)
        self.assertEqual(self.SRC.count("await _fire_scene("), 2)

    def test_the_short_circuit_runs_before_the_brain_is_asked(self):
        short = self.SRC.index("if _pure_accept and prompt_enhance and not local_iteration:")
        ask = self.SRC.index('note=f"asking {brain_name()} to direct the shot"')
        self.assertLess(short, ask)

    def test_the_short_circuit_uses_the_backstops_own_condition(self):
        self.assertIn("accept_backstop = (_pure_accept and prompt_enhance\n"
                      "                                   and not local_iteration)",
                      self.SRC)


if __name__ == "__main__":
    unittest.main()
