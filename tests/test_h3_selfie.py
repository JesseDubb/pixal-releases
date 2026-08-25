"""Brief 9.41 - the camera is the phone: a selfie still animates as a selfie.

2026-08-25, Selfie Cam still 6b2f3036 (Krea 2 turbo, krea2-s3lfie-r3alism-9
+ LARP) animated with only a spoken line as the note: both directed briefs
wrote the phone as a PROP watched by a second, tripod-locked camera ("tugs
the phone slightly away from her face", "locked and level"), because nothing
in the pipeline told the director the camera IS the phone. The still's
provenance already carries the signal, so now:

- h3_selfie_source reads it: a selfie LoRA in info.loras or
  spec.lora_plan.entries (the stem - krea2-s3lfie-r3alism-9 hits), else a
  caption saying front camera/selfie; odd entries are False, never a raise;
- the director hears one standing sentence (H3_SELFIE_CAMERA_NOTE) AFTER
  the user's own note, pronouned by the 9.37 settle rule - never on the
  ref2va lane (no frame-zero premise), never on a script (the user's own
  words never see the director);
- repair_selfie_camera restates the sentence inside the description field
  when the brief drops the fact - repair_camera_note's sibling, idempotent,
  and a brief that says it in its own words is left alone;
- the draft route runs the same repair: what the user reads is what ships.

Same sanctioned simulation as 9.36/9.37/9.38: fixed strings and stubbed
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
    "pixal_server_h3_selfie",
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


# The real 6b2f3036 ledger shape (Krea 2 turbo, 2026-08-25): both signals
# fire - the s3lfie stem in info.loras AND the lora_plan names, and the
# caption says "Phone front camera". Fem-majority caption, so the standing
# sentence takes "her".
SELFIE_ENTRY = {
    "id": "6b2f3036",
    "scene": ("A pretty girl in her early 20s with glossy dark hair tucked "
              "behind one ear, sleek black nylon designer jacket over a "
              "white tee, gold hoops, soft daylight from a big window, "
              "blurred modern apartment living room behind her. Phone front "
              "camera at arm's length, mid-sentence expression, eyes on the "
              "lens, shallow depth of field, face and shoulders filling the "
              "frame slightly wide, no phone visible in shot — viewer is "
              "the phone, natural phone look, warm skin tones and soft "
              "shadows from daylight window."),
    "info": {"loras": ["krea2filterbypass@1", "krea2-s3lfie-r3alism-9@0.75",
                       "LARP_v0-5@0.5"]},
    "spec": {"lora_plan": {"entries": [
        {"name": "Krea 2\\krea2-s3lfie-r3alism-9.safetensors",
         "weight": None},
        {"name": "Krea 2\\LARP_v0-5.safetensors", "weight": None}]}},
    "images": [{"filename": "still.png", "subfolder": "", "media": "image"}]}
PLAIN_ENTRY = {"id": "abc123", "scene": "the subject at a workbench",
               "images": [{"filename": "still.png", "subfolder": "",
                           "media": "image"}]}

# A director-shaped brief with no selfie statement: the repair fires on it,
# every older gate passes through byte-identical (9.36's fixture).
BRIEF = (
    "integrated_multimodal_description: [Shot 1] Live-action, natural "
    "real-time motion — she stands at the workbench, still for a beat, then "
    "lifts the brass lamp and turns it toward the window light, her "
    "expression easing. (S1) says: <d>[English] It finally works.</d> Her "
    "lips close and she only listens; no further speech.\n\n"
    "overall_soundscape: The room's low hum, the lamp's click, fabric "
    "moving as she turns, synchronized.")

NOTE_HER = server.H3_SELFIE_CAMERA_NOTE.format(poss="her")

BODY = {"id": "6b2f3036", "cid": "cid1", "engine": "h3", "model": "fl2va",
        "seconds": 5, "hint": "she smiles"}


def run_route(handler, root, body, brief=BRIEF, directed=True,
              entry=SELFIE_ENTRY, validate_return=("h3", "fl2va", 5, None)):
    """The 9.38 harness, copied: every side effect stubbed, the mocks handed
    back for assertions. `load_config` is pinned to the local-brain preset so
    the LOOK stage runs (frame_inventory is a mock); `llm_call` is
    booby-trapped so a repair that would spend a brain call fails loudly."""
    submit = AsyncMock(return_value={"id": "videojob", "error": None})
    broadcast = Mock()
    look = AsyncMock(return_value="a woman holding the frame at arm's length")
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


class SelfieSourceTests(unittest.TestCase):
    """Detection: the still's provenance says selfie, or it does not."""

    def test_the_real_6b2f3036_shape_detects(self):
        self.assertTrue(server.h3_selfie_source(SELFIE_ENTRY))

    def test_the_lora_plan_alone_detects(self):
        entry = {"spec": {"lora_plan": {"entries": [
            {"name": "Krea 2\\krea2-s3lfie-r3alism-9.safetensors",
             "weight": None}]}},
            "scene": "a young woman in a sunny kitchen"}
        self.assertTrue(server.h3_selfie_source(entry))

    def test_a_front_camera_caption_detects(self):
        entry = {"info": {"loras": ["someotherlora@1"]},
                 "scene": "Phone front camera at arm's length, eyes on the "
                          "lens, shallow depth of field"}
        self.assertTrue(server.h3_selfie_source(entry))

    def test_the_match_is_case_insensitive(self):
        self.assertTrue(server.h3_selfie_source(
            {"info": {"loras": ["KREA2-S3LFIE-R3ALISM-9@0.75"]}}))
        self.assertTrue(server.h3_selfie_source(
            {"scene": "a quick SELFIE before dinner"}))

    def test_a_social_realism_entry_does_not_detect(self):
        entry = {"info": {"loras": ["KNP_V2@0.8", "realismstock@1"]},
                 "spec": {"lora_plan": {"entries": [
                     {"name": "Flux\\KNP_V2.safetensors", "weight": None}]}},
                 "scene": "a woman on a busy market street, eye-level "
                          "documentary framing"}
        self.assertFalse(server.h3_selfie_source(entry))

    def test_missing_and_odd_entries_are_false_and_never_raise(self):
        for entry in (None, {}, {"info": None},
                      {"info": {"loras": "krea2-s3lfie-r3alism-9"}},
                      {"spec": "junk"},
                      {"spec": {"lora_plan": {"entries": ["junk", None, 42]}}},
                      {"scene": None},
                      42, "krea2-s3lfie-r3alism-9"):
            with self.subTest(entry=entry):
                self.assertFalse(server.h3_selfie_source(entry))


class SelfieCameraRepairTests(unittest.TestCase):
    """The restatement: dropped fact appended inside the description field,
    honored wording left alone - repair_camera_note's exact shape."""

    def test_the_sentence_lands_before_the_soundscape_field(self):
        out = server.repair_selfie_camera(BRIEF, True)
        self.assertIn("The camera is the front camera of the phone", out)
        self.assertLess(out.find("front camera"),
                        out.find("overall_soundscape:"))

    def test_a_brief_that_says_it_is_left_byte_identical(self):
        forms = ["shot on the front camera at arm's length",
                 "a classic selfie framing, eyes on the lens",
                 "the camera is the phone she holds",
                 "her phone's camera catches the wink",
                 "the phone camera sees her grin",
                 "she speaks into the phone at arm's length"]
        for form in forms:
            with self.subTest(form=form):
                honored = BRIEF.replace("she stands", form + ", she stands")
                self.assertEqual(server.repair_selfie_camera(honored, True),
                                 honored)

    def test_the_repair_is_idempotent(self):
        once = server.repair_selfie_camera(BRIEF, True)
        self.assertEqual(server.repair_selfie_camera(once, True), once)

    def test_selfie_false_is_a_no_op(self):
        self.assertEqual(server.repair_selfie_camera(BRIEF, False), BRIEF)

    def test_an_unlabeled_brief_gets_the_sentence_at_the_end(self):
        out = server.repair_selfie_camera("She winks at the lens.", True)
        self.assertTrue(out.endswith("never visible in the shot."))

    def test_the_pronoun_follows_the_briefs_own_subject(self):
        male = BRIEF.replace("she stands", "he stands").replace(
            "her expression", "his expression").replace(
            "Her lips", "His lips").replace("she only", "he only")
        out = server.repair_selfie_camera(male, True)
        self.assertIn("in his own outstretched hand", out)
        neutral = ("integrated_multimodal_description: [Shot 1] Live-action "
                   "— the subject turns toward the window light and smiles.\n\n"
                   "overall_soundscape: Room tone, synchronized.")
        out = server.repair_selfie_camera(neutral, True)
        self.assertIn("in their own outstretched hand", out)


class SelfieHintTests(unittest.TestCase):
    """The director hears the standing sentence after the user's own note -
    fl2va only, directed path only."""

    def test_the_users_note_comes_first_then_the_sentence(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            mocks = run_route(server.animate, root, BODY)
            self.assertEqual(mocks["response"].status, 200)
            hint = mocks["director"].await_args.args[1]
            self.assertEqual(hint, "she smiles " + NOTE_HER)

    def test_no_user_note_means_the_sentence_is_the_whole_note(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            body = {k: v for k, v in BODY.items() if k != "hint"}
            mocks = run_route(server.animate, root, body)
            hint = mocks["director"].await_args.args[1]
            self.assertEqual(hint, NOTE_HER)

    def test_the_pronoun_follows_the_ledger_scene(self):
        male_entry = {**SELFIE_ENTRY, "scene": (
            "A young man at his kitchen window, his jacket half-zipped, "
            "holding the shot high; his reflection catches the glass.")}
        prep = {"engine": "h3", "model_id": "fl2va", "seconds": 5, "shots": 1,
                "variant": "fl2va", "entry": male_entry, "last_entry": None,
                "args": {"image": "prepared.png"}}
        director = AsyncMock(return_value=(BRIEF, True))
        with patch.object(server, "direct_motion", director), \
             patch.object(server, "load_config", return_value={
                 "llm": {"base_url": "http://brain.invalid/v1"}}), \
             patch.object(server.HUB, "broadcast"):
            asyncio.run(server.look_and_direct({"hint": "he smirks"}, prep,
                                               None, "cid"))
        self.assertEqual(
            director.await_args.args[1],
            "he smirks " + server.H3_SELFIE_CAMERA_NOTE.format(poss="his"))

    def test_a_non_selfie_entry_passes_the_hint_through_untouched(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            mocks = run_route(server.animate, root,
                              {**BODY, "id": "abc123"}, entry=PLAIN_ENTRY)
            hint = mocks["director"].await_args.args[1]
            self.assertEqual(hint, "she smiles")

    def test_the_ref2va_lane_gets_nothing(self):
        prep = {"engine": "h3", "model_id": "ref2va", "seconds": 5, "shots": 1,
                "variant": server.H3_REF2V_MODEL_ID, "entry": SELFIE_ENTRY,
                "last_entry": None, "args": {"refs": ["pixal_ref_6b2f3036.png"]}}
        director = AsyncMock(return_value=(BRIEF, True))
        with patch.object(server, "direct_motion", director), \
             patch.object(server, "load_config", return_value={
                 "llm": {"base_url": "http://brain.invalid/v1"}}), \
             patch.object(server.HUB, "broadcast"):
            asyncio.run(server.look_and_direct({"hint": "she smiles"}, prep,
                                               None, "cid"))
            asyncio.run(server.look_and_direct({}, prep, None, "cid"))
        self.assertEqual(director.await_args_list[0].args[1], "she smiles")
        self.assertIsNone(director.await_args_list[1].args[1])

    def test_a_script_gets_nothing(self):
        script = ("she waves at the lens, a big grin. (S1) says: "
                  "<d>[English] Hey, look at this.</d> Her lips close and "
                  "she only listens; no further speech.")
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            mocks = run_route(server.animate, root,
                              {**BODY, "script": script})
            self.assertEqual(mocks["response"].status, 200)
            mocks["director"].assert_not_awaited()
            prompt = mocks["submit"].await_args.args[3]
            self.assertNotIn("front camera", prompt)


class SelfieRouteRepairTests(unittest.TestCase):
    """The restatement rides both routes: the render's submitted prompt and
    the draft the user reads carry the sentence."""

    def test_the_render_prompt_carries_the_sentence(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            mocks = run_route(server.animate, root, BODY)
            prompt = mocks["submit"].await_args.args[3]
            self.assertIn("The camera is the front camera of the phone",
                          prompt)
            self.assertLess(prompt.find("front camera"),
                            prompt.find("overall_soundscape:"))

    def test_a_non_selfie_render_is_untouched(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            mocks = run_route(server.animate, root,
                              {**BODY, "id": "abc123"}, entry=PLAIN_ENTRY)
            prompt = mocks["submit"].await_args.args[3]
            self.assertNotIn("never visible in the shot", prompt)

    def test_the_draft_route_returns_the_sentence(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            mocks = run_route(server.animate_brief, root, BODY)
            self.assertEqual(mocks["response"].status, 200)
            payload = json.loads(mocks["response"].text)
            brief = payload["brief"]
            self.assertIn("The camera is the front camera of the phone",
                          brief)
            self.assertLess(brief.find("front camera"),
                            brief.find("overall_soundscape:"))
            # and the director heard the note on the draft path too
            hint = mocks["director"].await_args.args[1]
            self.assertEqual(hint, "she smiles " + NOTE_HER)

    def test_a_non_selfie_draft_is_byte_identical(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still_dir(root)
            mocks = run_route(server.animate_brief, root,
                              {**BODY, "id": "abc123"}, entry=PLAIN_ENTRY)
            payload = json.loads(mocks["response"].text)
            self.assertEqual(payload["brief"], BRIEF)


if __name__ == "__main__":
    unittest.main()
