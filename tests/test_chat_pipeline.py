r"""Regression tests for the chat -> sampler path.

    .venv\Scripts\python.exe tests\test_chat_pipeline.py

No pytest: the project has no test dependency and the installer's engine is
stdlib-only, so the harness is too. Every case below is a real incident, not a
hypothetical - the fixture text is lifted from chat 629d1c68 and from the four
contaminated entries in history.jsonl.

The point of this file, in one line: a render must never be given a string the
user did not mean as a prompt.

Two entry points, one body: direct run prints its own pass/fail summary and
exits with it; unittest discovery runs the same checks once through
ChatPipelineTests. Importing the module runs nothing.
"""
import asyncio
import json
import re
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import server  # noqa: E402

PASS, FAIL = [], []


def check(name, got, want):
    (PASS if got == want else FAIL).append(name)
    if got != want:
        print(f"  FAIL {name}\n       got:  {got!r}\n       want: {want!r}")


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL {name} {detail}")


# The 717-character scene from turn [6] of chat 629d1c68. The brain answered it
# with the bare word "generate" and the card rendered that word.
TURN6 = (
    "The platinum blonde anime girl is seated cross-legged on the shoulder of her "
    "Japanese black mech, Onyx. She wears a crop top green t-shirt with a centered "
    "logo - no sleeves, no embellishment beyond that mark. Her hair falls in soft "
    "waves over one shoulder; she gazes forward with calm eyes, not looking at the "
    "camera. Onyx's black metallic frame curves beneath her like a throne and "
    "protector of her, its joints visible and sleek, designed for mobility and "
    "speed. She is positioned on his left shoulder. she looks like she is having "
    "the most fun of her life. Ultra modern anime style")

COMPOSER = ("\n\n[COMPOSER: writing for template=identity_edit. Model, loras, size "
            "and reference are applied server-side - never mention file names.]")


# ------------------------------------------------------- the full turn path --
def replay(user_text, convo, enhance=False):
    """Run one turn with the GPU and the brain replaced by capture stubs."""
    captured = {}

    async def fake_submit(cid, src, template, scene, spec, count=1, parent=None,
                          flags=None, verbatim=False):
        clean, fault = server.scene_gate(template, scene, verbatim=verbatim)
        captured.update(template=template, scene=clean, verbatim=verbatim, error=fault)
        return {"id": "test1234", "error": fault}

    async def fake_llm(messages, tools=None, cid=None):
        captured["tools"] = [t["function"]["name"] for t in (tools or [])]
        return 200, {"choices": [{"message": {"role": "assistant",
                                              "content": "generate"}}]}

    # broadcast is stubbed too, or a test run writes its chatter into the real
    # lane.json - the dev lane filled up with "Got it - rendering your prompt
    # exactly as written" from the suite before this was noticed.
    real = (server.HUB.submit, server.llm_call, server.HUB.broadcast)
    server.HUB.submit, server.llm_call = fake_submit, fake_llm
    server.HUB.broadcast = lambda **kw: captured.setdefault(
        "said", []).append(kw.get("text")) if kw.get("type") == "text" else None
    try:
        asyncio.run(server._kimi_reply(
            "testcid", {"role": "user", "content": user_text}, convo,
            {"prompt_enhance": enhance}))
    finally:
        server.HUB.submit, server.llm_call, server.HUB.broadcast = real
    return captured


def main():
    # ----------------------------------------------------------- scene_gate --
    print("scene_gate - the seed forms that used to leak")
    for form in ("Seed = 8979871423", "seed: 8979871423", "seed=8979871423",
                 "SEED = 8979871423."):
        clean, err = server.scene_gate("realism", f"A fox in snow. {form}")
        ok(f"strips {form!r}", err is None and "8979871423" not in clean, repr(clean))

    print("scene_gate - shapes that are not a prompt")
    for bad, why in (("generate", "a bare tool name"),
                     ("Show me", "an accept turn"),
                     ("show me!", "an accept turn with punctuation"),
                     ("go", "an affirmative"),
                     ('{"name": "generate", "arguments": {"scene": "a fox"}}',
                      "a printed tool call")):
        _, err = server.scene_gate("realism", bad)
        ok(f"refuses {why}", err is not None, f"accepted {bad!r}")

    # A composer block is CLEANED rather than refused - it rides on legitimate user
    # turns by design, so the scene around it is still what they meant. In verbatim
    # mode nothing is rewritten, so there it has to be refused instead.
    dirty = "A fox in snow. [COMPOSER: writing for template=realism.]"
    clean, err = server.scene_gate("realism", dirty)
    ok("composer block is stripped", err is None and "[COMPOSER" not in clean, repr(clean))
    _, err = server.scene_gate("realism", dirty, verbatim=True)
    ok("composer block is refused when verbatim", err is not None)

    print("scene_gate - things it must NOT touch")
    clean, err = server.scene_gate("realism", TURN6)
    ok("a real scene passes", err is None and clean == TURN6)
    clean, err = server.scene_gate("realism", "render a cyberpunk street at noon")
    ok("a render verb WITH a scene passes", err is None, repr(err))
    # qwen_edit takes an instruction, not a scene: "make her jacket red" is the
    # whole legitimate prompt there and the prose rules would destroy it.
    clean, err = server.scene_gate("qwen_edit", "make her jacket red")
    check("qwen_edit is exempt", (clean, err), ("make her jacket red", None))
    clean, err = server.scene_gate("h3_i2v", "she turns to camera. Seed = 42")
    ok("motion briefs are exempt", err is None and clean.endswith("Seed = 42"))

    print("scene_gate - verbatim leaves the user's words alone")
    typed = "A fox in snow. Rich saturated colour."   # the retired house caption
    clean, err = server.scene_gate("realism", typed, verbatim=True)
    check("verbatim does not rewrite", (clean, err), (typed, None))
    clean, _ = server.scene_gate("realism", typed)
    ok("non-verbatim still scrubs the caption", "saturated" not in clean, repr(clean))
    _, err = server.scene_gate("realism", "generate", verbatim=True)
    ok("verbatim still refuses a bare command", err is not None)


    # --------------------------------------------------- scene_is_command --
    # The line between "please render THIS" and "please render what I already
    # wrote". A three-word cap was tried first and refused "draw a cat".
    print("scene_is_command - accepts vs. short prompts")
    for text, want in (
            # short, but they name something to look at
            ("draw a cat", False), ("shoot a portrait", False),
            ("render a cyberpunk street", False), ("a fox in snow", False),
            ("make me a sandwich", False), ("show me a photo", False),
            ("create an image of a dog", False),
            ("show me the girl on the mech", False),
            # longer, but they only point back at something already written
            ("generate", True), ("show me", True), ("render it", True),
            ("render it now", True), ("show me please", True),
            ("show it to me", True), ("render that one", True),
            ("make it", True), ("go", True), ("go ahead", True),
            ("yes", True), ("", True)):
        ok(f"{text!r} command={want}", server.scene_is_command(text) is want)


    # ------------------------------------------------------ captured_prompt --
    print("captured_prompt - an accept turn reaches back for the real prompt")
    convo = [
        {"role": "user", "content": TURN6 + COMPOSER},
        {"role": "assistant", "content": "generate"},
        {"role": "user", "content": "generate" + COMPOSER},
    ]
    check("'generate' resolves to the scene", server.captured_prompt(convo, "generate"), TURN6)
    check("'show me' resolves to the scene", server.captured_prompt(convo, "show me"), TURN6)
    check("a real turn is used as-is", server.captured_prompt(convo, TURN6), TURN6)
    check("no prior prompt -> the turn itself",
          server.captured_prompt([], "generate"), "generate")

    # The composer block is appended to the user's turn by the server; it must never
    # come back out as part of the prompt.
    ok("composer block never rides along", "[COMPOSER" not in server.captured_prompt(convo, "go"))


    # A queue receipt is appended with role "user" so the brain can see a render
    # happened. captured_prompt walked back onto one and rendered a picture of the
    # words (2026-08-18, first live pass). Both the capture and the gate must refuse it.
    RECEIPT = "[SYSTEM: the server queued that prompt as job 8bbda870 (realism) - no reply needed.]"
    after_render = [
        {"role": "user", "content": TURN6 + COMPOSER},
        {"role": "user", "content": RECEIPT},
    ]
    check("an accept after a render skips the receipt",
          server.captured_prompt(after_render, "show me"), TURN6)
    _, err = server.scene_gate("realism", RECEIPT)
    ok("the gate refuses a queue receipt", err is not None)
    _, err = server.scene_gate("realism", RECEIPT, verbatim=True)
    ok("verbatim refuses it too", err is not None)


    # --------------------------------------------------- the full turn path --
    print("_kimi_reply - the 629d1c68 replay")

    # The exact transcript that shipped the word "generate" to the sampler.
    got = replay("generate" + COMPOSER,
                 [{"role": "user", "content": TURN6 + COMPOSER},
                  {"role": "assistant", "content": "generate"}])
    ok("the word 'generate' never reaches the sampler",
       got.get("scene") != "generate", repr(got.get("scene")))
    check("it renders the scene the user actually wrote", got.get("scene"), TURN6)
    ok("and it goes verbatim", got.get("verbatim") is True)
    ok("with no error", got.get("error") is None, repr(got.get("error")))

    # A fresh, fully-written prompt with enhancement off: straight through, no brain.
    got = replay(TURN6 + COMPOSER, [])
    check("a written prompt passes through untouched", got.get("scene"), TURN6)
    ok("the brain was never called", "tools" not in got)

    # Enhancement ON must still go to the brain rather than the bypass.
    got = replay(TURN6 + COMPOSER, [], enhance=True)
    ok("enhance ON still consults the brain", "tools" in got)

    # 10.10 (Jesse, 2026-09-02): "I do not want that when it is off - I want
    # direct to text encoder!" Iteration words are no exception any more:
    # with enhance OFF nothing pays a brain round, whatever the turn says.
    got = replay("make her jacket red" + COMPOSER,
                 [{"role": "user", "content": TURN6 + COMPOSER}])
    ok("enhance OFF never calls the brain, even on iteration words",
       "tools" not in got, repr(got.get("tools")))

    # The local lane must keep generate even on a turn scored as conversation.
    if server.load_config()["llm"]["base_url"].find("127.0.0.1") >= 0:
        got = replay("hey there", [], enhance=True)
        ok("local lane keeps generate on a chat turn",
           "generate" in got.get("tools", []), repr(got.get("tools")))
    else:
        print("  skip local-lane tool test (configured brain is not local)")


    # What the person actually sees. A bare tool name must never be one of them.
    got = replay("generate" + COMPOSER,
                 [{"role": "user", "content": TURN6 + COMPOSER},
                  {"role": "assistant", "content": "generate"}])
    said = got.get("said") or []
    ok("nothing shown to the user is a bare tool name",
       not any(server.scene_is_command(s or "") for s in said), repr(said))


    # ------------------------------------------------------------- verdict --
    print()
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed:", ", ".join(FAIL))
    return 1 if FAIL else 0


class EchoedBriefIsNotTheUsersFault(unittest.TestCase):
    r"""The local writer sometimes answers with nothing but its own brief.

    Real turn, 2026-08-23: Jesse asked "can you make her fully dressed but
    wearing tight clothing" and the 4B replied with [COMPOSER ...],
    [CHARACTER ... Look: <the scene it had actually written>] and
    [ATTACHED IMAGES ...] - machinery all the way down. The scrubbers took
    every block, correctly, and the turn went empty. scene_is_command("") is
    True on purpose (scene_gate needs "empty is not renderable"), so an
    emptied turn was indistinguishable from a model printing "generate", and
    Pixal answered "Tell me what you'd like to see and I'll render it" one
    line after he had said exactly what he wanted. Twice, and it rendered
    nothing either time.

    The user telling us what they want, and the writer failing to write it,
    are opposite problems. They must not share a reply.
    """

    ECHOED = (
        "[COMPOSER: writing for template=identity_edit. Model, loras, size and "
        "reference are applied server-side - never mention file names.]\n\n"
        "[CHARACTER: Mia. Look:\nShe sits in the dark - no other setting, no "
        "background. Her posture is relaxed but still, facing slightly away from "
        "the camera as if lost in thought, dimly lit by a single low-angle "
        "spotlight from the left.]\n\n"
        "[ATTACHED IMAGES: the FIRST is the person this render must depict - "
        "never write a skin tone, hair colour, age or body type.]")

    def _replay(self, brain_says, user_text="can you make her fully dressed"):
        said, submitted = [], []

        async def fake_submit(cid, src, template, scene, spec, count=1, parent=None,
                              flags=None, verbatim=False):
            submitted.append(scene)
            return {"id": "test1234", "error": None}

        async def fake_llm(messages, tools=None, cid=None):
            return 200, {"choices": [{"message": {"role": "assistant",
                                                  "content": brain_says}}]}

        real = (server.HUB.submit, server.llm_call, server.HUB.broadcast)
        server.HUB.submit, server.llm_call = fake_submit, fake_llm
        server.HUB.broadcast = lambda **kw: (
            said.append(kw.get("text")) if kw.get("type") == "text" else None)
        try:
            asyncio.run(server._kimi_reply(
                "testcid", {"role": "user", "content": user_text}, [],
                {"prompt_enhance": True}))
        finally:
            server.HUB.submit, server.llm_call, server.HUB.broadcast = real
        return " ".join(t for t in said if t), submitted

    def test_an_echoed_brief_does_not_blame_the_user(self):
        reply, submitted = self._replay(self.ECHOED)
        self.assertNotIn("Tell me what you'd like to see", reply)
        self.assertIn("brief", reply.lower())
        self.assertEqual(submitted, [])          # still nothing to render
        # and not one bracket of the machinery reaches the lane
        for block in ("[COMPOSER", "[CHARACTER", "[ATTACHED IMAGES"):
            self.assertNotIn(block, reply)

    def test_a_bare_command_still_gets_the_original_line(self):
        """The control. This is the case that line was written for - a model
        printing the tool's name as prose - and it must not change."""
        reply, submitted = self._replay("generate")
        self.assertIn("Tell me what you'd like to see", reply)
        self.assertEqual(submitted, [])

    def test_a_reply_that_is_only_whitespace_is_not_an_echoed_brief(self):
        """Genuinely empty is not the same as emptied BY the scrubbers - there
        was no brief to echo, so the original line is still the right answer."""
        reply, _ = self._replay("   \n  ")
        self.assertNotIn("brief", reply.lower())


class StoredMachineryNeverReplays(unittest.TestCase):
    r"""Guarding new writes was not enough - the old ones replay forever.

    scene_gate refuses server machinery on the way IN now, but ledger entry
    079b9083 is already written: a real render whose entire prompt is an
    [ATTACHED IMAGES: ...] block. history.jsonl and the persisted lane are
    both replayed to the browser on every tab open, so that wall of machinery
    was still on screen in the gallery and the chat after the fix - which is
    exactly what Jesse pasted at the start of the session.

    Scrubbing on the way OUT repairs every stored chat and card at once and
    rewrites none of his data.
    """

    POISON = ("[ATTACHED IMAGES: the FIRST is the person this render must depict "
              "- never write a skin tone, hair colour, age or body type that "
              "contradicts it, and do not describe the face in detail; describe "
              "each style/clothing/object reference's salient traits faithfully "
              "into the scene (garment cut/colour/texture, palette/light/medium, "
              "form/material).]")

    ENTRY = {"id": "079b9083", "template": "identity_edit", "seed": 8800912903777915,
             "count": 1, "elapsed": 38.3, "scene": POISON,
             "images": [{"filename": "attached_images_the_first_is_the_per_00001_.png",
                         "subfolder": "pixal_dm", "type": "output"}]}

    def _stub_media(self):
        return patch.object(server, "_existing_media",
                            return_value=self.ENTRY["images"])

    def test_the_gallery_does_not_replay_it(self):
        with patch.object(server.HUB, "ledger_read", return_value=[dict(self.ENTRY)]), \
                self._stub_media():
            resp = asyncio.run(server.history(None))
        body = json.loads(resp.text)
        self.assertEqual(body["entries"][0]["scene"], "")
        self.assertNotIn("ATTACHED IMAGES", resp.text)

    def test_the_chat_replay_drops_a_line_that_is_only_machinery(self):
        lane = [{"role": "user", "text": "this girl sitting in the dark"},
                {"role": "assistant", "text": self.POISON},
                {"role": "job", "job_id": "079b9083", "ts": 1}]
        with patch.object(server.HUB, "chats", {"c1": {"id": "c1", "lane": lane}}), \
                patch.object(server.HUB, "active_chat", "c1"), \
                patch.object(server.HUB, "ledger_read", return_value=[dict(self.ENTRY)]), \
                self._stub_media():
            resp = asyncio.run(server.lane_get(None))
        body = json.loads(resp.text)
        said = [e.get("text") for e in body["lane"] if e.get("role") != "job"]
        self.assertEqual(said, ["this girl sitting in the dark"])   # the echo is gone
        card = next(e for e in body["lane"] if e.get("role") == "job")
        self.assertEqual(card["job"]["scene"], "")
        self.assertNotIn("ATTACHED IMAGES", resp.text)
        # the record itself is untouched - this is a display guard, not an edit
        self.assertEqual(lane[1]["text"], self.POISON)

    def test_a_real_scene_and_a_real_message_pass_through(self):
        good = "She sits in the dark, one lamp burning behind her."
        entry = {**self.ENTRY, "scene": good}
        lane = [{"role": "user", "text": "make it colder"},
                {"role": "job", "job_id": "079b9083", "ts": 1}]
        with patch.object(server.HUB, "chats", {"c1": {"id": "c1", "lane": lane}}), \
                patch.object(server.HUB, "active_chat", "c1"), \
                patch.object(server.HUB, "ledger_read", return_value=[entry]), \
                self._stub_media():
            resp = asyncio.run(server.lane_get(None))
        body = json.loads(resp.text)
        self.assertEqual([e.get("text") for e in body["lane"]
                          if e.get("role") != "job"], ["make it colder"])
        card = next(e for e in body["lane"] if e.get("role") == "job")
        self.assertEqual(card["job"]["scene"], good)


class ChatPipelineTests(unittest.TestCase):
    def test_chat_pipeline(self):
        self.assertEqual(main(), 0, f"chat pipeline checks failed: {FAIL}")


if __name__ == "__main__":
    sys.exit(main())


class OneReplyPerTurn(unittest.TestCase):
    """Chat 952084e3 (2026-08-25): on a conversation-scored turn the brain
    called generate AND printed the scene; the gate refused the call, the
    prose had already gone out, and the next round - no calls now - wrapped
    the same scene again as "here's the prompt I'd render". Two replies, one
    turn, the whole scene twice. The wrapper is the machinery; it yields."""

    SCENE = ("A blonde woman in a cropped leather jacket stands centre frame "
             "under a single hard spotlight, one hand on her hip, chin lifted, "
             "the studio backdrop falling away into black behind her, dust in "
             "the beam, a faint smile just starting at the corner of her mouth.")

    def _replay(self, rounds, user_text="what do you think of that idea"):
        said, submitted = [], []
        queue = list(rounds)

        async def fake_submit(cid, src, template, scene, spec, count=1, parent=None,
                              flags=None, verbatim=False):
            submitted.append(scene)
            return {"id": "test1234", "error": None}

        async def fake_llm(messages, tools=None, cid=None):
            msg = queue.pop(0) if queue else {"role": "assistant", "content": ""}
            return 200, {"choices": [{"message": msg}]}

        real = (server.HUB.submit, server.llm_call, server.HUB.broadcast)
        server.HUB.submit, server.llm_call = fake_submit, fake_llm
        server.HUB.broadcast = lambda **kw: (
            said.append(kw.get("text")) if kw.get("type") == "text" else None)
        try:
            asyncio.run(server._kimi_reply(
                "testcid", {"role": "user", "content": user_text}, [],
                {"prompt_enhance": True}))
        finally:
            server.HUB.submit, server.llm_call, server.HUB.broadcast = real
        return [t for t in said if t], submitted

    def test_a_refused_generate_call_does_not_speak_the_scene_twice(self):
        call = {"id": "c1", "type": "function",
                "function": {"name": "generate",
                             "arguments": '{"prompt": "' + self.SCENE + '"}'}}
        texts, submitted = self._replay([
            {"role": "assistant", "content": self.SCENE + " Render it and I'll fire it.",
             "tool_calls": [call]},
            {"role": "assistant", "content": self.SCENE},
        ])
        joined = "\n".join(texts)
        self.assertEqual(joined.count("single hard spotlight"), 1, texts)
        self.assertEqual(joined.count("Want me to run it?"), 1, texts)
        self.assertEqual(submitted, [])

    def test_a_scene_spoken_once_still_gets_the_full_offer(self):
        """The control: no prior scene this turn, the wrapper is unchanged."""
        texts, _ = self._replay([{"role": "assistant", "content": self.SCENE}])
        joined = "\n".join(texts)
        self.assertIn("here", joined)
        self.assertEqual(joined.count("single hard spotlight"), 1)
        self.assertIn("Want me to run it?", joined)


class ProseRescueOnlyWithEnhance(unittest.TestCase):
    """9.99: _scene_from_prose is reached ONLY with prompt_enhance on.

    The prose rescue at server.py:18605 reads
    `_scene_from_prose(scene_text) if prompt_enhance else _direct_prompt_scene(...)`
    and that must remain true: with enhance off the verbatim contract ("the
    user's words ARE the prompt") is sacred and the furniture trimmer has no
    business anywhere near it. With enhance on, the queued scene is the
    trimmed one."""

    PROSE = ("Sure! Here's the shot: A silver-haired woman reads by a "
             "rain-streaked window, soft morning light on the knit of her "
             "sweater, an open paperback held loosely in both hands, the rest "
             "of the room falling away into quiet shadow behind her. "
             "Say go and I'll fire it.")
    CLEAN = ("A silver-haired woman reads by a rain-streaked window, soft "
             "morning light on the knit of her sweater, an open paperback "
             "held loosely in both hands, the rest of the room falling away "
             "into quiet shadow behind her.")

    def _replay(self, user_text, convo, enhance, brain_says):
        submitted = []

        async def fake_submit(cid, src, template, scene, spec, count=1,
                              parent=None, flags=None, verbatim=False):
            submitted.append(scene)
            return {"id": "test1234", "error": None}

        async def fake_llm(messages, tools=None, cid=None):
            return 200, {"choices": [{"message": {"role": "assistant",
                                                  "content": brain_says}}]}

        # The rescue's local-brain gate reads the live config; pin it local.
        cfg = json.loads(json.dumps(server.load_config()))
        cfg["llm"]["base_url"] = f"http://127.0.0.1:{server.LOCAL_LLM_PORT}/v1"
        real = (server.HUB.submit, server.llm_call, server.HUB.broadcast)
        server.HUB.submit, server.llm_call = fake_submit, fake_llm
        server.HUB.broadcast = lambda **kw: None
        try:
            with patch.object(server, "load_config", return_value=cfg):
                asyncio.run(server._kimi_reply(
                    "testcid", {"role": "user", "content": user_text}, convo,
                    {"prompt_enhance": enhance}))
        finally:
            server.HUB.submit, server.llm_call, server.HUB.broadcast = real
        return submitted

    def test_enhance_on_queues_the_trimmed_scene(self):
        convo = [{"role": "user", "content": TURN6 + COMPOSER},
                 {"role": "assistant", "content": "generate"}]
        with patch.object(server, "_scene_from_prose",
                          wraps=server._scene_from_prose) as spy, \
                patch.object(server, "_direct_prompt_scene",
                             side_effect=AssertionError(
                                 "_direct_prompt_scene with enhance ON")):
            submitted = self._replay("generate" + COMPOSER, convo, True,
                                     self.PROSE)
        self.assertTrue(spy.called)
        self.assertEqual(submitted, [self.CLEAN])

    def test_enhance_off_never_reaches_scene_from_prose(self):
        # 10.10: an iteration turn no longer holds the fast path back, so the
        # prose rescue is never reached at all with enhance OFF - neither
        # helper runs, the typed words go straight to submit.
        convo = [{"role": "user", "content": TURN6 + COMPOSER}]
        with patch.object(server, "_scene_from_prose",
                          side_effect=AssertionError(
                              "_scene_from_prose reached with enhance OFF")), \
                patch.object(server, "_direct_prompt_scene",
                             return_value="the user's own words") as dps:
            submitted = self._replay("make her jacket red" + COMPOSER, convo,
                                     False, self.PROSE)
        self.assertFalse(dps.called)
        self.assertEqual(submitted, ["make her jacket red"])


class ACritiqueIsNotACaption(unittest.TestCase):
    """10.3, chat 4bf386fc: with Prompt enhance OFF, a substantive redirect
    of a pending draft - "Yeah just not sexy enough and the environment
    sucks" - sailed down the verbatim path and job 7e717049 rendered the
    critique as the caption. The direct path fires only on the turn's OWN
    prompt or a bare accept; a redirect takes the brain path (with the
    generate tool still offered) so the brain can merge it into the draft."""

    CRITIQUE = "Yeah just not sexy enough and the environment sucks"
    DRAFT = ("She squats low on her haunches in front of a lime-green "
             "supercar with a low wedge nose and black wheels, camera at eye "
             "level, late sun raking the car's flank, an empty rooftop car "
             "park behind her, high ponytail, a small challenging half-smile. "
             "Say go and I'll fire it.")
    PROMPT = ("A young woman with copper hair sits on the floor of a sunlit "
              "artist studio surrounded by canvases and jars of brushes, "
              "laughing as she ties her hair back, golden afternoon light "
              "through tall windows, wearing a paint-flecked denim apron "
              "over a white tee")

    def _replay(self, user_text, convo, enhance, brain_says="Toned down."):
        submitted, tool_lists = [], []

        async def fake_submit(cid, src, template, scene, spec, count=1,
                              parent=None, flags=None, verbatim=False):
            submitted.append(scene)
            return {"id": "test1234", "error": None}

        async def fake_llm(messages, tools=None, cid=None):
            tool_lists.append([t.get("function", {}).get("name")
                               for t in (tools or [])])
            return 200, {"choices": [{"message": {"role": "assistant",
                                                  "content": brain_says}}]}

        # Pin the cloud lane: the incident was kimi-k3, and the local lane
        # has its own rescue arm out of this brief's scope.
        cfg = json.loads(json.dumps(server.load_config()))
        cfg["llm"]["base_url"] = "https://api.moonshot.example/v1"
        real = (server.HUB.submit, server.llm_call, server.HUB.broadcast)
        server.HUB.submit, server.llm_call = fake_submit, fake_llm
        server.HUB.broadcast = lambda **kw: None
        try:
            with patch.object(server, "load_config", return_value=cfg):
                asyncio.run(server._kimi_reply(
                    "testcid", {"role": "user", "content": user_text}, convo,
                    {"prompt_enhance": enhance}))
        finally:
            server.HUB.submit, server.llm_call, server.HUB.broadcast = real
        return submitted, tool_lists

    def test_the_incident_replay_a_redirect_renders_verbatim_with_enhance_off(self):
        # 10.10 reverses the enhance-OFF half of 10.3 on Jesse's word: OFF
        # means no brain, so a critique typed with the writer off IS the
        # prompt. The merge lives on the enhance-ON path (next test).
        convo = [{"role": "user", "content": "zara by a supercar" + COMPOSER},
                 {"role": "assistant", "content": self.DRAFT}]
        submitted, tool_lists = self._replay(
            self.CRITIQUE + COMPOSER, convo, enhance=False)
        self.assertEqual(submitted, [self.CRITIQUE])
        self.assertEqual(tool_lists, [], "enhance OFF never pays a brain call")

    def test_a_redirect_with_enhance_on_still_goes_to_the_brain(self):
        convo = [{"role": "user", "content": "zara by a supercar" + COMPOSER},
                 {"role": "assistant", "content": self.DRAFT}]
        submitted, tool_lists = self._replay(
            self.CRITIQUE + COMPOSER, convo, enhance=True)
        self.assertEqual(submitted, [], "the critique was queued as a caption")
        self.assertTrue(tool_lists, "the redirect never reached the brain")
        self.assertIn("generate", tool_lists[0],
                      "the redirect must still OFFER the tool")

    def test_a_real_typed_prompt_still_goes_verbatim(self):
        submitted, tool_lists = self._replay(
            self.PROMPT + COMPOSER, [], enhance=False)
        self.assertEqual(submitted, [self.PROMPT])
        self.assertEqual(tool_lists, [], "a typed prompt never pays a brain call")

    def test_an_accept_of_a_pending_draft_is_unchanged(self):
        """'go' renders the user's own last prompt (captured_prompt's reach-
        back), exactly as before this brief - on the direct path, no brain."""
        convo = [{"role": "user", "content": self.PROMPT + COMPOSER},
                 {"role": "assistant", "content": self.DRAFT}]
        submitted, tool_lists = self._replay("go" + COMPOSER, convo,
                                             enhance=False)
        self.assertEqual(submitted, [self.PROMPT])
        self.assertEqual(tool_lists, [])

    def test_a_pending_question_answer_is_not_backstopped(self):
        """An answer may legitimately need another shaping round - only a
        pending DRAFT accept gets the 10.4 backstop, never a question."""
        convo = [{"role": "user", "content": "zara somewhere fun" + COMPOSER},
                 {"role": "assistant",
                  "content": "What kind of fun is she having?"}]
        submitted, tool_lists = self._replay("surfing at sunset" + COMPOSER,
                                             convo, enhance=True)
        self.assertEqual(submitted, [])
        self.assertTrue(tool_lists and "generate" in tool_lists[0])

    def test_enhance_on_composite_is_untouched(self):
        """The brief's accept #4: with enhance ON the tool-offering logic
        still reads the COMPOSITE render_intent - a redirect arm must keep
        offering generate to the brain. Source-pinned."""
        src = (Path(__file__).resolve().parents[1] / "server.py") \
            .read_text(encoding="utf-8")
        self.assertIn("tools = base_tools if (render_intent or local_brain)",
                      src)
        self.assertIn(
            "render_intent = user_wants_render(_utext, "
            "conversation_has_visual(convo))", src)
        # and the direct gate reads no intent score at all any more (10.10):
        # enhance OFF is the whole gate, a pure accept of a draft the only
        # exception
        self.assertIn("if not prompt_enhance:   # OFF now means off", src)
        self.assertNotIn("and (render_intent or enhance_off_is_prompt", src)
        self.assertNotIn("and (direct_intent or enhance_off_is_prompt", src)


class AnAcceptedDraftAlwaysFires(unittest.TestCase):
    """10.4, chat 5a045b81: three armed accepts ("go", "render it",
    "SHOW ME!") of a written draft produced zero renders - the cloud brain
    recited its no-tool invite line despite holding generate, and each
    short apology then buried the draft below _pending_scene's word floor.
    The accept backstop queues the draft when the accept round ends in
    prose; the pending walk survives the chatter."""

    DRAFT = ("She squats low on her haunches, elbows on knees, directly in "
             "front of a lime-green supercar with a low wedge nose and black "
             "wheels, camera at her eye level a few steps back, late sun "
             "raking the flank, an empty rooftop car park and a low skyline "
             "behind her, platinum ponytail, a small challenging half-smile. "
             "Say go and I'll fire it.")
    APOLOGY = ("That go didn't arm the trigger on my side - one more nudge: "
               "say render it and I'll fire the shot exactly as written.")

    def _replay(self, user_text, convo, rounds):
        submitted, tool_lists = [], []
        queue = list(rounds)

        async def fake_submit(cid, src, template, scene, spec, count=1,
                              parent=None, flags=None, verbatim=False):
            submitted.append(scene)
            return {"id": "test1234", "error": None}

        async def fake_llm(messages, tools=None, cid=None):
            tool_lists.append([t.get("function", {}).get("name")
                               for t in (tools or [])])
            msg = queue.pop(0) if queue else {"role": "assistant",
                                              "content": "Done."}
            return 200, {"choices": [{"message": msg}]}

        cfg = json.loads(json.dumps(server.load_config()))
        cfg["llm"]["base_url"] = "https://api.moonshot.example/v1"
        real = (server.HUB.submit, server.llm_call, server.HUB.broadcast)
        server.HUB.submit, server.llm_call = fake_submit, fake_llm
        server.HUB.broadcast = lambda **kw: None
        try:
            with patch.object(server, "load_config", return_value=cfg):
                asyncio.run(server._kimi_reply(
                    "testcid", {"role": "user", "content": user_text}, convo,
                    {"prompt_enhance": True}))
        finally:
            server.HUB.submit, server.llm_call, server.HUB.broadcast = real
        return submitted, tool_lists

    def test_the_incident_replay_go_fires_the_draft(self):
        convo = [{"role": "user", "content": "zara by a supercar" + COMPOSER},
                 {"role": "assistant", "content": self.DRAFT}]
        submitted, tool_lists = self._replay(
            "go" + COMPOSER, convo,
            [{"role": "assistant", "content": self.APOLOGY}])
        self.assertEqual(len(submitted), 1,
                         "the accepted draft was never queued")
        self.assertIn("lime-green supercar", submitted[0])
        self.assertNotIn("Say go", submitted[0],
                         "the invite tail must be stripped")
        # 10.7: the accept never reaches the brain - the apology round this
        # replay queued up is never consumed (tests/test_accept_fires_mechanically.py)
        self.assertEqual(tool_lists, [])

    def test_the_cascade_render_it_still_sees_the_buried_draft(self):
        """After a short apology turn the draft is no longer the newest
        assistant message - the walk must still find it."""
        convo = [{"role": "user", "content": "zara by a supercar" + COMPOSER},
                 {"role": "assistant", "content": self.DRAFT},
                 {"role": "user", "content": "go" + COMPOSER},
                 {"role": "assistant", "content": self.APOLOGY}]
        submitted, _ = self._replay(
            "render it" + COMPOSER, convo,
            [{"role": "assistant", "content": self.APOLOGY}])
        self.assertEqual(len(submitted), 1)
        self.assertIn("lime-green supercar", submitted[0])

    def test_a_brain_that_fires_properly_queues_exactly_once(self):
        convo = [{"role": "user", "content": "zara by a supercar" + COMPOSER},
                 {"role": "assistant", "content": self.DRAFT}]
        call = {"id": "c1", "type": "function",
                "function": {"name": "generate",
                             "arguments": json.dumps({"prompt": self.DRAFT})}}
        submitted, _ = self._replay(
            "go" + COMPOSER, convo,
            [{"role": "assistant", "content": "", "tool_calls": [call]},
             {"role": "assistant", "content": "Fired!"}])
        self.assertEqual(len(submitted), 1, "backstop double-queued the draft")

    def test_a_go_renders_the_draft_the_user_read_not_a_silent_rewrite(self):
        """10.4 let the brain's own rewrite win when the accept round came
        back as a scene. 10.7 removes that round: "go" means the draft the
        user just read, and a brain that would have quietly recoloured it
        is never asked. A redirect ("make it sunset orange") is still the
        brain's merge - that is the other test class."""
        rewrite = self.DRAFT.replace("lime-green", "sunset-orange")
        convo = [{"role": "user", "content": "zara by a supercar" + COMPOSER},
                 {"role": "assistant", "content": self.DRAFT}]
        submitted, tool_lists = self._replay(
            "go" + COMPOSER, convo,
            [{"role": "assistant", "content": rewrite}])
        self.assertEqual(len(submitted), 1)
        self.assertIn("lime-green", submitted[0])
        self.assertEqual(tool_lists, [])


class PendingSceneWalk(unittest.TestCase):
    """10.4's _pending_scene: survives short chatter, stops at anything
    that acted, capped at six messages."""

    DRAFT = ("A tall figure stands at the end of a rain-slicked pier at "
             "dusk, coat lifting in the wind, gulls scattering off the "
             "railing, the last orange light breaking under a shelf of "
             "storm cloud far out over the water beyond them.")
    SHORT = "One more nudge and I'll fire it."

    def test_a_short_apology_does_not_bury_the_draft(self):
        convo = [{"role": "assistant", "content": self.DRAFT},
                 {"role": "user", "content": "go"},
                 {"role": "assistant", "content": self.SHORT}]
        self.assertEqual(server._pending_scene(convo), self.DRAFT)

    def test_a_queued_receipt_closes_it(self):
        convo = [{"role": "assistant", "content": self.DRAFT},
                 {"role": "user", "content":
                  "[SYSTEM: the server queued that scene as job deadbeef "
                  "(h3_ref_still) - no reply needed.]"}]
        self.assertIsNone(server._pending_scene(convo))

    def test_a_tool_call_turn_closes_it(self):
        convo = [{"role": "assistant", "content": self.DRAFT},
                 {"role": "user", "content": "go"},
                 {"role": "assistant", "content": "",
                  "tool_calls": [{"id": "c1"}]}]
        self.assertIsNone(server._pending_scene(convo))

    def test_the_walk_is_capped_at_six_messages(self):
        chatter = [{"role": "user", "content": "hm"},
                   {"role": "assistant", "content": self.SHORT}]
        convo = [{"role": "assistant", "content": self.DRAFT}] + chatter * 3
        self.assertIsNone(server._pending_scene(convo))

    def test_turn_policy_carries_the_accept_sentence(self):
        self.assertIn("that is the fire signal", server.TURN_POLICY)
        self.assertIn("never\n  invite again", server.TURN_POLICY)
