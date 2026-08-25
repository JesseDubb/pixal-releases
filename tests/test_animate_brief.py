"""Brief 9.36 - draft the brief before the render.

Jesse, 2026-08-25: "Minimax H3 is an incredible model and I'm not sure our
current 'Animate' flow is top tier UI UX for everything it can do." The
brief is the most consequential text in the product - H3 renders exactly
what it says, dialogue and sound included - and the user first saw it AFTER
committing 2-3 minutes of GPU. POST /api/animate/brief runs the same
preparation, the same look and the same direct_motion call /api/animate
makes, and returns the brief; the popup shows it, the user reads and edits
it, and committing sends it back as `script`.

Pinned here:

- the endpoint returns the brief and queues NOTHING (no ComfyUI post, the
  ledger untouched) and writes no lane line - only the thinking notes;
- a bad body gets the same errors /api/animate gives - both routes share
  prepare_animate, so the parity is by construction and stays that way;
- the round-trip is lossless: a brief sent back as `script` assembles to
  the SAME final prompt the directed path would have built from it. The
  brief is returned post-normalise, pre-assembly - the stage the lane
  narrates as *the brief:* - where every step the script path skips (the
  assembler's lint branch, the settle repair) is a no-op on a
  director-shaped brief, and everything else (music guarantee, header,
  style splice, hanging-line repair) runs identically on both paths.

Same sanctioned simulation as 9.9/9.37/9.38: fixed strings and stubbed
handlers - no generation, no ComfyUI, no GPU.
"""
import asyncio
import json
import unittest
from contextlib import ExitStack
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch


_SPEC = spec_from_file_location(
    "pixal_server_animate_brief",
    Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def all_video_assets(_kind, _rel):
    return _rel


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


ENTRY = {"id": "abc123", "scene": "the subject at a workbench",
         "images": [{"filename": "still.png", "subfolder": "",
                     "media": "image"}]}
BRIDGE_ENTRY = {"id": "def456", "scene": "the lamp lit on the workbench",
                "images": [{"filename": "last.png", "subfolder": "",
                            "media": "image"}]}

# A director-shaped brief: the three trained fields with proper <d> tags, a
# clean (closed-mouth) opening and the after-line silence clause - every
# repair gate passes through it byte-identical.
BRIEF = (
    "integrated_multimodal_description: [Shot 1] Live-action, natural "
    "real-time motion — she stands at the workbench, still for a beat, then "
    "lifts the brass lamp and turns it toward the window light, her "
    "expression easing. (S1) says: <d>[English] It finally works.</d> Her "
    "lips close and she only listens; no further speech.\n\n"
    "overall_soundscape: The room's low hum, the lamp's click, fabric "
    "moving as she turns, synchronized.")

# A 3x5s cut timeline, already stamped to the plan (00:05.000, 00:10.000)
# with every marker at a line start, the way the cut director writes them:
# normalise_cut_timeline is idempotent on it, so what the endpoint returns
# is byte-for-byte what the directed path ships into assembly.
TIMELINE = (
    "integrated_multimodal_description:\n"
    "[Shot 1] Live-action, natural real-time motion — she stands at the "
    "workbench and lifts the brass lamp, turning it toward the window "
    "light. The camera holds locked and level at a fixed framing. End "
    "state: the lamp is up, her hand resting on its base.\n"
    "[Shot 2] At 00:05.000, the shot cuts to a close view of her hands as "
    "she tightens the lamp's screw with a small driver. The camera never "
    "moves - no pan, no push-in, no reframing. End state: the driver is "
    "down, the screw tight.\n"
    "[Shot 3] At 00:10.000, the shot cuts to her stepping back and "
    "switching the lamp on, warm light rising across the bench. The "
    "camera holds locked and level. End state: she faces the camera, both "
    "hands at her sides.\n\n"
    "overall_soundscape: The room's low hum, the lamp's click, the small "
    "driver on metal, synchronized.")


def run_route(handler, root, body, brief=BRIEF, directed=True,
              entry=ENTRY, validate_return=("h3", "fl2va", 5, None)):
    """Run an animate route under the 9.38 harness: every side effect stubbed,
    the mocks handed back for assertions. `load_config` is pinned to the
    local-brain preset so the LOOK stage actually runs (frame_inventory is a
    mock); `llm_call` is booby-trapped so a repair that would spend a brain
    call fails the round-trip by changing its output instead of hanging."""
    submit = AsyncMock(return_value={"id": "videojob", "error": None})
    broadcast = Mock()
    look = AsyncMock(return_value="a woman at a workbench, tools on the bench")
    director = AsyncMock(return_value=(brief, directed))
    ledger_append = Mock()

    async def run():
        response = await handler(FakeRequest(body))
        await asyncio.sleep(0)
        return response

    with ExitStack() as stack:
        stack.enter_context(patch.object(server, "CDIR", root))
        stack.enter_context(patch.object(
            server, "validate_video_selection", return_value=validate_return))
        stack.enter_context(patch.object(
            server, "prepare_h3_frame", return_value=("prepared.png", 1344, 768)))
        stack.enter_context(patch.object(server, "_video_asset",
                                         side_effect=all_video_assets))
        stack.enter_context(patch.object(server, "load_config", return_value={
            "llm": {"base_url": f"http://127.0.0.1:{server.LOCAL_LLM_PORT}/v1"},
            # the parity tests compare against BRIEF's canonical tags; the
            # standing spelling (quotes since 2026-08-25) has its own test
            "video": {"h3_dialogue_tags": "tags"},
            "extra_model_roots": []}))
        stack.enter_context(patch.object(server, "frame_inventory", look))
        stack.enter_context(patch.object(server, "direct_motion", director))
        stack.enter_context(patch.object(
            server, "llm_call",
            AsyncMock(side_effect=AssertionError("no brain in tests"))))
        stack.enter_context(patch.object(server.HUB, "ledger_read",
                                         return_value=[entry] if entry else []))
        stack.enter_context(patch.object(server.HUB, "ledger_append",
                                         ledger_append))
        stack.enter_context(patch.object(server.HUB, "broadcast", broadcast))
        stack.enter_context(patch.object(server.HUB, "submit", submit))
        response = asyncio.run(run())
    return {"response": response, "submit": submit, "broadcast": broadcast,
            "look": look, "director": director, "ledger_append": ledger_append}


def still_dir(root, names=("still.png",)):
    (root / "output").mkdir()
    (root / "input").mkdir()
    for name in names:
        (root / "output" / name).write_bytes(b"still")


BODY = {"id": "abc123", "cid": "cid1", "engine": "h3", "model": "fl2va",
        "seconds": 5, "hint": "she fixes the lamp"}


class AnimateBriefEndpointTests(unittest.TestCase):
    """POST /api/animate/brief: the draft comes back; nothing is queued."""

    def test_the_draft_comes_back_and_nothing_is_queued(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            mocks = run_route(server.animate_brief, root, BODY)
            self.assertEqual(mocks["response"].status, 200)
            self.assertEqual(json.loads(mocks["response"].text), {
                "ok": True, "brief": BRIEF, "directed": True,
                "shots": 1, "engine": "h3"})
            # the ComfyUI post is never made and the ledger is untouched
            mocks["submit"].assert_not_awaited()
            mocks["ledger_append"].assert_not_called()
            # the lane shows the work (thinking notes + done) but no lane line
            types = [c.kwargs.get("type")
                     for c in mocks["broadcast"].call_args_list]
            self.assertNotIn("text", types)
            notes = [c.kwargs.get("note")
                     for c in mocks["broadcast"].call_args_list
                     if c.kwargs.get("type") == "thinking"]
            self.assertEqual(notes, ["looking at the frame",
                                     "directing motion and sound"])
            self.assertEqual(types[-1], "thinkingdone")

    def test_the_look_reads_the_start_frame_and_the_bridge_end_frame(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root, ("still.png", "last.png"))
            ledger = [ENTRY, BRIDGE_ENTRY]
            submit = AsyncMock(return_value={"id": "videojob", "error": None})
            look = AsyncMock(return_value="an inventory")
            director = AsyncMock(return_value=(BRIEF, True))

            async def run():
                return await server.animate_brief(FakeRequest(
                    {**BODY, "last_id": "def456"}))

            with ExitStack() as stack:
                stack.enter_context(patch.object(server, "CDIR", root))
                stack.enter_context(patch.object(
                    server, "validate_video_selection",
                    return_value=("h3", "fl2va", 5, None)))
                stack.enter_context(patch.object(
                    server, "prepare_h3_frame",
                    return_value=("prepared.png", 1344, 768)))
                stack.enter_context(patch.object(
                    server, "_video_asset", side_effect=all_video_assets))
                stack.enter_context(patch.object(server, "load_config",
                    return_value={"llm": {"base_url":
                        f"http://127.0.0.1:{server.LOCAL_LLM_PORT}/v1"},
                        "extra_model_roots": []}))
                stack.enter_context(patch.object(server, "frame_inventory", look))
                stack.enter_context(patch.object(server, "direct_motion", director))
                stack.enter_context(patch.object(server.HUB, "ledger_read",
                                                 return_value=ledger))
                stack.enter_context(patch.object(server.HUB, "broadcast"))
                stack.enter_context(patch.object(server.HUB, "submit", submit))
                response = asyncio.run(run())
            self.assertEqual(response.status, 200)
            # the staged start frame first, the staged end frame second
            self.assertEqual([c.args[:2] for c in look.await_args_list],
                             [("prepared.png", "abc123"),
                              ("pixal_bridge_def456.png", "def456")])
            kwargs = director.await_args.kwargs
            self.assertEqual(kwargs["last_frame"], "pixal_bridge_def456.png")
            self.assertEqual(kwargs["look_end"], "an inventory")
            self.assertEqual(kwargs["look"], "an inventory")
            submit.assert_not_awaited()

    def test_the_director_gets_the_arguments_the_render_would_pass(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            mocks = run_route(server.animate_brief, root,
                              {**BODY, "shots": 3}, brief=TIMELINE)
            self.assertEqual(mocks["response"].status, 200)
            director = mocks["director"]
            self.assertEqual(director.await_args.args[:2],
                             ("the subject at a workbench", "she fixes the lamp"))
            self.assertEqual(director.await_args.kwargs, {
                "engine": "h3", "shots": 3, "cut_times": [5, 10],
                "seconds": 5, "frame": "prepared.png",
                "look": "a woman at a workbench, tools on the bench",
                "last_frame": None, "look_end": "", "model": "fl2va"})
            # a cut-plan draft is returned post-normalise - byte-for-byte the
            # text the directed path ships into assembly
            payload = json.loads(mocks["response"].text)
            self.assertEqual(payload["brief"], TIMELINE)
            self.assertEqual(payload["shots"], 3)

    def test_an_unreachable_director_reports_directed_false(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            mocks = run_route(server.animate_brief, root, BODY, directed=False)
            payload = json.loads(mocks["response"].text)
            self.assertEqual(payload["brief"], BRIEF)
            self.assertFalse(payload["directed"])
            mocks["submit"].assert_not_awaited()


class BadBodyParityTests(unittest.TestCase):
    """A bad body gets the same answer from both routes - one front, one
    validator, so the 400s are shared by construction (9.36 item 1)."""

    def run_both(self, body, entry=ENTRY, stills=("still.png",),
                 validate_return=("h3", "fl2va", 5, None),
                 validate_raise=None):
        outcomes = {}
        for name, handler in (("animate", server.animate),
                              ("brief", server.animate_brief)):
            with TemporaryDirectory() as td:
                root = Path(td)
                still_dir(root, stills)
                submit = AsyncMock(return_value={"id": "j", "error": None})
                director = AsyncMock(return_value=(BRIEF, True))

                async def run():
                    response = await handler(FakeRequest(body))
                    await asyncio.sleep(0)
                    return response

                with ExitStack() as stack:
                    stack.enter_context(patch.object(server, "CDIR", root))
                    if validate_raise is not None:
                        stack.enter_context(patch.object(
                            server, "validate_video_selection",
                            side_effect=validate_raise))
                    else:
                        stack.enter_context(patch.object(
                            server, "validate_video_selection",
                            return_value=validate_return))
                    stack.enter_context(patch.object(
                        server, "prepare_h3_frame",
                        return_value=("prepared.png", 1344, 768)))
                    stack.enter_context(patch.object(
                        server, "_video_asset", side_effect=all_video_assets))
                    stack.enter_context(patch.object(
                        server, "frame_inventory", AsyncMock(return_value="")))
                    stack.enter_context(patch.object(
                        server, "direct_motion", director))
                    stack.enter_context(patch.object(
                        server.HUB, "ledger_read",
                        return_value=[entry] if entry else []))
                    stack.enter_context(patch.object(server.HUB, "broadcast"))
                    stack.enter_context(patch.object(server.HUB, "submit", submit))
                    response = asyncio.run(run())
                outcomes[name] = (response.status, json.loads(response.text))
                submit.assert_not_awaited()
                director.assert_not_awaited()
        return outcomes

    def test_bad_bodies_get_the_same_answer_from_both_routes(self):
        cases = [
            ("a validation refusal", {"id": "abc123", "engine": "wat"},
             dict(validate_raise=ValueError("unknown video engine: wat")),
             400, "unknown video engine"),
            ("an unknown generation", {"id": "nope"}, dict(entry=None),
             404, "no such generation"),
            ("an entry with no still", BODY,
             dict(entry={**ENTRY, "images": []}), 400, "no still"),
            ("a gone file", BODY, dict(stills=()), 404, "file gone"),
            ("a bad seed", {**BODY, "seed": "banana"}, {}, 400, "not a seed"),
            ("a bridge off H3", {**BODY, "engine": "ltx25", "model": "default",
                                 "seconds": 8, "last_id": "zzz"},
             dict(validate_return=("ltx25", "default", 8, None)),
             400, "needs MiniMax H3"),
        ]
        for name, body, kw, status, needle in cases:
            with self.subTest(name):
                outcomes = self.run_both(body, **kw)
                self.assertEqual(outcomes["animate"], outcomes["brief"],
                                 "the routes diverged on the same bad body")
                got_status, payload = outcomes["brief"]
                self.assertEqual(got_status, status)
                self.assertFalse(payload["ok"])
                self.assertIn(needle, payload["error"])


class BriefRoundTripTests(unittest.TestCase):
    """9.36 item 3: a brief returned by /api/animate/brief and sent back
    through /api/animate as `script` assembles to the SAME final prompt the
    directed path would have built from it. The repairs run for real here -
    the fixed brief passes every gate, so both paths converge byte-for-byte."""

    def run_animate(self, root, body, **kw):
        mocks = run_route(server.animate, root, body, **kw)
        self.assertEqual(mocks["response"].status, 200)
        return mocks["submit"].await_args.args

    def test_a_committed_draft_assembles_to_the_directed_prompt(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            # 1. the draft
            draft = run_route(server.animate_brief, root, BODY)
            brief = json.loads(draft["response"].text)["brief"]
            self.assertEqual(brief, BRIEF)
            # 2. the commit: the brief back as `script`
            script_args = self.run_animate(root, {**BODY, "script": brief})
            # 3. the directed render building from the same brief
            directed_args = self.run_animate(root, BODY)
            self.assertEqual(script_args[2], directed_args[2])   # template
            self.assertEqual(script_args[3], directed_args[3])   # final prompt
            self.assertIn("It finally works.", script_args[3])

    def test_the_style_slot_is_filled_the_same_on_both_paths(self):
        # provenance says stylized: h3_style_splice runs on BOTH paths (it is
        # not one of the steps user_script skips), so the committed draft and
        # the directed render carry the same 2D-animated slot.
        stylized = {**ENTRY, "template": "anima",
                    "info": {"model_family": "anima"}}
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            script_args = self.run_animate(root, {**BODY, "script": BRIEF},
                                           entry=stylized)
            directed_args = self.run_animate(root, BODY, entry=stylized)
            self.assertEqual(script_args[3], directed_args[3])
            self.assertIn("2D-animated", script_args[3])
            self.assertNotIn("Live-action", script_args[3])

    def test_a_committed_cut_timeline_keeps_its_cut_plan(self):
        body = {**BODY, "shots": 3}
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            draft = run_route(server.animate_brief, root, body, brief=TIMELINE)
            brief = json.loads(draft["response"].text)["brief"]
            self.assertEqual(brief, TIMELINE)
            script_args = self.run_animate(root, {**body, "script": brief},
                                           brief=TIMELINE)
            directed_args = self.run_animate(root, body, brief=TIMELINE)
            self.assertEqual(script_args[3], directed_args[3])
            # 3x5s is ONE generation with real internal cuts on both paths
            self.assertEqual(script_args[2], "h3_i2v")
            self.assertEqual(script_args[4]["seconds"], 15)
            self.assertIn("[Shot 2] At 00:05.000, the shot cuts to",
                          script_args[3])


if __name__ == "__main__":
    unittest.main()

class DraftRepairTests(unittest.TestCase):
    """A drafted brief ships back as `script`, and the script path runs no
    directed-only repair. So the draft route runs them itself: the text the
    user reads is the finished brief. Pinned on the 9.37 case the round-trip
    test above cannot see - a director brief that opens mid-word."""

    IN_PROGRESS = BRIEF.replace("still for a beat, then lifts",
                                "finishing a word as she lifts")

    def test_the_draft_carries_the_settle_repair(self):
        self.assertIsNotNone(server.h3_speech_in_progress(self.IN_PROGRESS))
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            draft = run_route(server.animate_brief, root, BODY,
                              brief=self.IN_PROGRESS)
            self.assertEqual(draft["response"].status, 200)
            brief = json.loads(draft["response"].text)["brief"]
            # the brain is booby-trapped, so this is the deterministic settle
            self.assertIsNone(server.h3_speech_in_progress(brief))
            self.assertNotIn("finishing a word", brief)
            self.assertIn("It finally works.", brief)
            # and committing it verbatim ships the settled text
            args = run_route(server.animate, root, {**BODY, "script": brief}
                             )["submit"].await_args.args
            self.assertNotIn("finishing a word", args[3])

    def test_the_draft_is_spelled_in_the_standing_format(self):
        # what the user reads is what ships: under quotes the draft carries
        # the #76 form, and committing it verbatim ships the same text
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            with patch.object(server, "h3_dialogue_tags_mode",
                              return_value="quotes"):
                draft = run_route(server.animate_brief, root, BODY)
                brief = json.loads(draft["response"].text)["brief"]
                self.assertIn("(S1) says \"It finally works.\"", brief)
                self.assertNotIn("<d>", brief)
                args = run_route(server.animate, root, {**BODY, "script": brief}
                                 )["submit"].await_args.args
            self.assertIn("(S1) says \"It finally works.\"", args[3])
            self.assertNotIn("<d>", args[3])

    def test_bracket_tags_are_fixed_before_the_user_reads_them(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            draft = run_route(server.animate_brief, root, BODY,
                              brief=BRIEF.replace("<d>", "[d]").replace("</d>", "[/d]"))
            brief = json.loads(draft["response"].text)["brief"]
            self.assertIn("<d>[English] It finally works.</d>", brief)
            self.assertNotIn("[d]", brief)

