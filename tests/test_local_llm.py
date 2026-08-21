import asyncio
import json
import os
import socket
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch


_SPEC = spec_from_file_location(
    "pixal_server_llm_tests", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def generate_call(call_id, scene):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {
                "name": "generate",
                "arguments": json.dumps({"template": "realism", "scene": scene}),
            },
        }],
    }


def generate_receipt(call_id, scene):
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps({"queued": call_id, "scene": scene}),
    }


class LocalHistoryViewTests(unittest.TestCase):
    def test_fresh_ask_drops_old_render_echo_and_old_directives_without_mutation(self):
        messages = [
            {"role": "user", "content": "What can you do?"},
            {"role": "assistant", "content": "I can help direct a shot."},
            {"role": "user", "content": [{"type": "text", "text":
                "Make a portrait.\n\n[COMPOSER: old model settings.]\n"
                "[CHARACTER: Old look. Never move them.]"}]},
            generate_call("old-render", "A person standing among desert dunes."),
            generate_receipt("old-render", "A person standing among desert dunes."),
            {"role": "assistant", "content": "Rendered: the person in desert sand."},
            {"role": "user", "content": [{"type": "text", "text":
                "Put the person in a kitchen.\n\n[COMPOSER: current settings.]"}]},
        ]
        original = json.loads(json.dumps(messages))

        view = server.local_history_view(messages, 6, preserve_latest_render=False)
        encoded = json.dumps(view)

        self.assertNotIn("desert", encoded)
        self.assertNotIn("old-render", encoded)
        self.assertNotIn("old model settings", encoded)
        self.assertNotIn("Old look", encoded)
        self.assertIn("What can you do?", encoded)
        self.assertIn("I can help direct a shot.", encoded)
        self.assertIn("Make a portrait.", encoded)
        self.assertIn("current settings", encoded)
        self.assertEqual(messages, original)

    def test_iteration_keeps_only_latest_prior_render_chain(self):
        messages = [
            {"role": "user", "content": "Old portrait.\n[COMPOSER: old settings.]"},
            generate_call("render-one", "A portrait among desert dunes."),
            generate_receipt("render-one", "A portrait among desert dunes."),
            {"role": "assistant", "content": "Rendered: desert portrait."},
            {"role": "user", "content": "Kitchen portrait.\n[COMPOSER: latest settings.]"},
            generate_call("render-two", "A portrait at the kitchen counter."),
            generate_receipt("render-two", "A portrait at the kitchen counter."),
            {"role": "assistant", "content": "Rendered: kitchen portrait."},
            {"role": "user", "content": "Again, use the same shot.\n[COMPOSER: current settings.]"},
        ]

        view = server.local_history_view(messages, 8, preserve_latest_render=True)
        encoded = json.dumps(view)

        self.assertNotIn("desert", encoded)
        self.assertNotIn("render-one", encoded)
        self.assertNotIn("old settings", encoded)
        self.assertIn("render-two", encoded)
        self.assertIn("kitchen counter", encoded)
        self.assertIn("latest settings", encoded)
        self.assertIn("current settings", encoded)

    def test_current_turn_tool_pair_survives_fresh_history_filter(self):
        messages = [
            {"role": "user", "content": "Old portrait."},
            generate_call("old-render", "A portrait in desert sand."),
            generate_receipt("old-render", "A portrait in desert sand."),
            {"role": "assistant", "content": "Rendered: desert portrait."},
            {"role": "user", "content": "A new portrait in a music studio."},
            generate_call("current-render", "A portrait in a music studio."),
            generate_receipt("current-render", "A portrait in a music studio."),
        ]

        view = server.local_history_view(messages, 4, preserve_latest_render=False)
        encoded = json.dumps(view)

        self.assertNotIn("old-render", encoded)
        self.assertNotIn("desert", encoded)
        self.assertIn("current-render", encoded)
        self.assertIn("music studio", encoded)

    def test_iteration_intent_is_explicit(self):
        for text in ("iterate on it", "same shot", "again please", "reroll this",
                     "change #a1b2c3d4"):
            with self.subTest(text=text):
                self.assertRegex(text, server._LOCAL_ITERATION_RE)
        self.assertNotRegex("make a new portrait", server._LOCAL_ITERATION_RE)


class GemmaMessageShimTests(unittest.TestCase):
    """Gemma's embedded template rejects tool/mid-stream-system roles and
    silently drops the structured tools payload; these shims fold both into
    the one shape it accepts."""

    def test_flatten_folds_tool_and_system_into_alternation(self):
        messages = [
            {"role": "system", "content": "contract"},
            {"role": "user", "content": "make a portrait"},
            {"role": "assistant", "content": "<tool_call>...</tool_call>",
             "name": None},
            {"role": "tool", "tool_call_id": "local_0",
             "content": '{"queued": "j1"}'},
            {"role": "assistant", "content": "Rendering now.", "name": None},
            {"role": "system", "content": "[critic on #j1: soft focus]"},
            {"role": "user", "content": "fix the focus"},
        ]
        out = server._flatten_roles(messages)
        roles = [m["role"] for m in out]
        self.assertEqual(roles, ["system", "user", "assistant", "user",
                                 "assistant", "user"])
        # tool receipt became a user tool_response turn
        self.assertIn("<tool_response>", out[3]["content"])
        self.assertIn('{"queued": "j1"}', out[3]["content"])
        # critic note coalesced into the next user turn, not its own message
        self.assertIn("[critic on #j1: soft focus]", out[5]["content"])
        self.assertIn("fix the focus", out[5]["content"])
        # assistant messages keep the name key llama-cpp-python requires
        for m in out:
            if m["role"] == "assistant":
                self.assertIn("name", m)

    def test_flatten_leaves_simple_system_user_pair_alone(self):
        messages = [{"role": "system", "content": "brief"},
                    {"role": "user", "content": "scene"}]
        self.assertEqual(server._flatten_roles(messages),
                         [{"role": "system", "content": "brief"},
                          {"role": "user", "content": "scene"}])

    def test_flatten_coalesces_consecutive_same_role(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "a", "name": None},
            {"role": "assistant", "content": "b", "name": None},
        ]
        out = server._flatten_roles(messages)
        self.assertEqual([m["role"] for m in out], ["user", "assistant"])
        self.assertIn("first", out[0]["content"])
        self.assertIn("second", out[0]["content"])
        self.assertEqual(out[1]["content"], "a\n\nb")

    def test_flatten_never_opens_with_assistant(self):
        messages = [{"role": "system", "content": "s"},
                    {"role": "assistant", "content": "hello", "name": None},
                    {"role": "user", "content": "hi"}]
        out = server._flatten_roles(messages)
        self.assertEqual([m["role"] for m in out],
                         ["system", "user", "assistant", "user"])

    def test_inline_tools_appends_contract_to_system(self):
        messages = [{"role": "system", "content": "contract"},
                    {"role": "user", "content": "make a portrait"}]
        out = server._inline_tools(messages, server.TOOLS_LOCAL)
        self.assertTrue(out[0]["content"].startswith("contract"))
        self.assertIn("<tools>", out[0]["content"])
        self.assertIn('"generate"', out[0]["content"])
        self.assertIn("<tool_call>", out[0]["content"])
        # source list untouched
        self.assertEqual(messages[0]["content"], "contract")

    def test_scene_from_prose_unwraps_fence_and_drops_config_lines(self):
        text = ("Okay, let's build that.\n\n```\nrealism / realism_ii\n"
                "standing=false\nseed=12345\n\nA silver-haired woman reads "
                "by a rain-streaked window, soft morning light on the knit "
                "of her sweater.\n```")
        out = server._scene_from_prose(text)
        self.assertTrue(out.startswith("A silver-haired woman"))
        for junk in ("```", "Okay, let's", "realism", "seed=", "standing="):
            self.assertNotIn(junk, out)

    def test_scene_from_prose_leaves_plain_scene_alone(self):
        text = ("A mossy stone bridge arches over a creek at golden hour, "
                "warm light raking the stones.")
        self.assertEqual(server._scene_from_prose(text), text)

    def test_mmproj_discovery_prefers_largest_and_gates_on_gemma(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            model = root / "gemma-3-12b-it-abliterated.Q6_K.gguf"
            model.write_bytes(b"m")
            self.assertIsNone(server._local_llm_mmproj(str(model.with_name(
                "qwen3-vl-4b.Q8_0.gguf"))))     # non-gemma name
            self.assertIsNone(server._local_llm_mmproj(str(model)))  # no mmproj
            small = root / "gemma-3-12b-it-abliterated.mmproj-Q8_0.gguf"
            big = root / "gemma-3-12b-it-abliterated.mmproj-f16.gguf"
            small.write_bytes(b"s" * 10)
            big.write_bytes(b"b" * 20)
            self.assertEqual(server._local_llm_mmproj(str(model)), str(big))

    def test_delocalize_vision_keeps_image_parts_else_flattens(self):
        msgs = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
            {"type": "text", "text": "wear this jacket"}]}]
        blind = server._delocalize([dict(m) for m in msgs])
        self.assertEqual(blind[0]["content"], "[attached image]\nwear this jacket")
        seeing = server._delocalize([dict(m) for m in msgs], vision=True)
        self.assertIsInstance(seeing[0]["content"], list)
        self.assertEqual(seeing[0]["content"][0]["type"], "image_url")

    def test_flatten_roles_merges_list_and_text_turns_as_parts(self):
        out = server._flatten_roles([
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:x"}},
                {"type": "text", "text": "the ref"}]},
            {"role": "user", "content": "make it moody"},
        ])
        self.assertEqual(len(out), 1)
        parts = out[0]["content"]
        self.assertIsInstance(parts, list)
        self.assertEqual([p["type"] for p in parts],
                         ["image_url", "text", "text"])
        self.assertEqual(parts[2]["text"], "make it moody")

    def test_local_directive_attaches_refs_only_with_mmproj(self):
        opts = {"refs": [{"kind": "clothing", "file": "jacket.png"},
                         {"kind": "identity", "file": "her.png"}]}
        with patch.object(server, "load_config",
                          return_value={"llm": {"local_model": "g.gguf"}}):
            with patch.object(server, "_local_llm_mmproj", return_value=None):
                d, vision = server.build_directive(dict(opts), local=True)
                self.assertEqual(vision, [])
                self.assertNotIn("ATTACHED IMAGES", d)
            with patch.object(server, "_local_llm_mmproj",
                              return_value="mmproj.gguf"):
                d, vision = server.build_directive(dict(opts), local=True)
                self.assertEqual([v["kind"] for v in vision],
                                 ["identity", "clothing"])
                self.assertIn("ATTACHED IMAGES", d)
                self.assertIn("FIRST is the person", d)
                self.assertNotIn("jacket.png", d)   # no file names for local

    def test_pending_question_arms_on_an_unanswered_assistant_question(self):
        # question with no tool call = the user's next reply is an ANSWER,
        # and the answer turn must get the generate tool back
        convo = [{"role": "user", "content": "her doing something fun"},
                 {"role": "assistant",
                  "content": "What kind of fun is she having?"}]
        self.assertTrue(server._pending_question(convo))
        # already acted -> nothing pending
        self.assertFalse(server._pending_question(
            convo[:1] + [{"role": "assistant", "content": None,
                          "tool_calls": [{"id": "x"}]}]))
        # plain statement, not a question -> nothing pending
        self.assertFalse(server._pending_question(
            convo[:1] + [{"role": "assistant", "content": "Rendering now."}]))
        # unanswered user turn on top -> not a proposal
        self.assertFalse(server._pending_question(
            convo + [{"role": "user", "content": "surfing"}]))
        self.assertFalse(server._pending_question([]))

    def test_brain_display_name_is_the_common_name(self):
        self.assertEqual(server.brain_display_name(
            r"X:\m\gemma-3-12b-it-abliterated.Q6_K.gguf", "mmproj.gguf"),
            "Gemma 3 12b w/ vision")
        self.assertEqual(server.brain_display_name(
            "gemma-3-12b-it-abliterated.Q6_K.gguf"), "Gemma 3 12b")
        self.assertEqual(server.brain_display_name(
            "qwen3-vl-4b-heretic-Q8_0.gguf"), "Qwen3 VL 4b")
        self.assertEqual(server.brain_display_name(""), "local brain")

    def test_localize_repairs_bare_untagged_tool_json(self):
        # the 2026-08-12 lane leak: full contract compliance minus the tags
        blob = ('{"name": "generate", "arguments": {"template": '
                '"identity_edit", "scene": "a portrait", "count": 1}}')
        msg = server._localize({"role": "assistant", "content": blob})
        calls = msg.get("tool_calls") or []
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "generate")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"])["scene"],
                         "a portrait")
        self.assertIsNone(msg["content"])

    def test_localize_repairs_fenced_and_duplicated_tool_json(self):
        blob = ('{"name": "generate", "arguments": {"template": "realism", '
                '"scene": "a fox"}}')
        content = f"```json\n{blob}\n```\n\n{blob}"
        msg = server._localize({"role": "assistant", "content": content})
        calls = msg.get("tool_calls") or []
        self.assertEqual(len(calls), 1)     # byte-identical repeat collapsed
        self.assertIsNone(msg["content"])   # fence litter stripped too

    def test_localize_keeps_prose_around_bare_tool_json(self):
        blob = ('{"name": "generate", "arguments": {"template": "realism", '
                '"scene": "a fox"}}')
        msg = server._localize(
            {"role": "assistant", "content": f"Here we go!\n{blob}"})
        self.assertEqual(len(msg.get("tool_calls") or []), 1)
        self.assertEqual(msg["content"], "Here we go!")

    def test_localize_leaves_plain_prose_and_incidental_json_alone(self):
        for content in ("Just a friendly reply with no JSON at all.",
                        'A caption like {"name": "unfinished',
                        '{"name": "x", "arguments": "not-a-dict"}'):
            msg = server._localize({"role": "assistant", "content": content})
            self.assertIsNone(msg.get("tool_calls"))
            self.assertEqual(msg["content"], content)

    def test_inline_tools_emitted_call_round_trips_through_localize(self):
        # the format the note teaches is the format _localize parses
        reply = {"role": "assistant", "content":
                 '<tool_call>\n{"name": "generate", "arguments": '
                 '{"template": "realism", "scene": "a portrait"}}\n</tool_call>'}
        msg = server._localize(reply)
        calls = msg.get("tool_calls") or []
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "generate")
        self.assertEqual(
            json.loads(calls[0]["function"]["arguments"])["template"], "realism")


class ConversationIntentTests(unittest.IsolatedAsyncioTestCase):
    def test_greetings_and_product_questions_are_not_render_intent(self):
        for text in ("Hey?", "hey", "Thanks!", "nice", "How are you?",
                     "Can I render something?", "I think the model should talk more",
                     "Whatever you did it is talking to me again",
                     "It was really cool not just making images but talking to me",
                     "Also we should have a LoRA toggle",
                     "Be careful not to break that", "Wait.", "Hold on.",
                     "Tell me a joke.", "Help me understand lighting.",
                     "I'm just thinking out loud.", "Don't render yet.",
                     "Do not make an image.", "I don't want an image yet.",
                     "describe the attached style reference for me - "
                     "no render, just tell me what you see",
                     "just tell me what is in this image",
                     "Can you explain how image generation works?",
                     "Can you help me edit my settings?",
                     "Can you talk about portrait lighting?",
                     "Can you make the system more intuitive?",
                     "So be careful not to break that cause whatever you did was positive",
                     "Looking good - the corner radius still needs work",
                     "Those renders look terrible btw",
                     "This workflow has a lot of downloads",
                     "These workflows have a lot of downloads",
                     "I am having a rough day",
                     "I was thinking about our project",
                     "Eventually I want to release this",
                     "Can you make the prompt enhance icon smaller?"):
            with self.subTest(text=text):
                self.assertFalse(server.user_wants_render(text))

    def test_explicit_and_implicit_visual_prompts_are_render_intent(self):
        for text in ("render a portrait", "Can you make a dragon?",
                     "have her sit on the couch", "a red fox in snow",
                     "gothic castle at sunset", "woman sitting on a couch",
                     "neon cyberpunk city", "red dress",
                     "the girl is standing in rain",
                     "I would love to see something NSFW"):
            with self.subTest(text=text):
                self.assertTrue(server.user_wants_render(text))

    def test_unknown_status_statements_never_render(self):
        for text in ("The weather is nice today", "My coffee is cold",
                     "I closed your window by accident",
                     "I am rendering just so you know", "we are almost done",
                     "I want to test this", "The image is done",
                     "My render finished", "That image is terrible"):
            for has_visual in (False, True):
                with self.subTest(text=text, has_visual=has_visual):
                    self.assertFalse(server.user_wants_render(
                        text, has_visual_context=has_visual))

    def test_status_workflow_and_unqualified_requests_stay_in_chat(self):
        for text in ("The model seems faster now",
                     "I found three workflows",
                     "We can use this workflow",
                     "Can you work a little faster I want to test"):
            with self.subTest(text=text):
                self.assertFalse(server.user_wants_render(text))
                self.assertFalse(server.user_wants_render(
                    text, has_visual_context=True))

    def test_natural_iteration_phrasing_uses_prior_visual_context(self):
        for text in ("What about a red dress?", "Could she be sitting instead?",
                     "I think she should be sitting."):
            with self.subTest(text=text):
                self.assertFalse(server.user_wants_render(text))
                self.assertTrue(server.user_wants_render(text, has_visual_context=True))

    def test_direct_visual_wants_are_not_swallowed_as_feedback(self):
        self.assertFalse(server.user_wants_render("I just want her in a red dress"))
        self.assertTrue(server.user_wants_render(
            "I just want her in a red dress", has_visual_context=True))
        self.assertTrue(server.user_wants_render("I just want a fox portrait"))
        self.assertFalse(server.user_wants_render(
            "I'm just thinking out loud", has_visual_context=True))

    async def test_plain_chat_rejects_hallucinated_generate(self):
        first = generate_call("bad-render", "An image nobody requested.")
        second = {"role": "assistant", "content": "Hey - what are we making?"}
        convo = []
        with patch.object(server, "load_config", return_value={"llm": {
                "base_url": server.LOCAL_LLM_URL, "model": "local"}}), \
             patch.object(server, "llm_call", AsyncMock(side_effect=[
                 (200, {"choices": [{"message": first}]}),
                 (200, {"choices": [{"message": second}]}),
             ])) as llm, \
             patch.object(server.HUB, "submit", AsyncMock()) as submit, \
             patch.object(server.HUB, "broadcast") as broadcast:
            await server._kimi_reply(
                "chat1", {"role": "user", "content": "Hey?"}, convo)

        submit.assert_not_awaited()
        # The local lane is ALWAYS offered its full one-tool list, even on a
        # turn scored as conversation: 0449be8 caught the 4B printing the
        # withheld tool's NAME as prose (chat 629d1c68), so withholding moved
        # to call time - the receipt below IS the rejection. Sibling pin:
        # "local lane keeps generate on a chat turn" in test_chat_pipeline.py.
        self.assertEqual(llm.await_args_list[0].kwargs["tools"], server.TOOLS_LOCAL)
        receipt = next(message for message in convo if message.get("role") == "tool")
        # The guard used to assert "The user did not request a render", which is
        # false on every MISclassified turn - and it was false on all three of
        # them in chats/ce52340c.json. It now names the classification instead
        # and forbids the substitute tools the brain reached for.
        self.assertIn("scored this turn as conversation", receipt["content"])
        self.assertIn("do not call list_models, animate, review or upscale",
                      receipt["content"].lower())
        self.assertTrue(any(c.kwargs.get("type") == "text" and
                            "what are we making" in c.kwargs.get("text", "").lower()
                            for c in broadcast.call_args_list))

    def test_a_lead_in_no_longer_hides_the_request(self):
        """Every pattern in the cascade is anchored at position 0, so a turn
        that opened with an interjection fell through to the bare-prompt
        fallback and a question mark finished it off. These three are verbatim
        from chats/ce52340c.json, where all three were scored as conversation,
        generate was withheld, and the brain spent the turn groping through
        list_models before telling Jesse the renderer was broken."""
        for text, has_visual in (
                ("Hey kimi I need to make an 80's movie title card - its "
                 "called THE FLAP DADDIES", False),
                ("perfect!!!! now can you make it look like that is a frame "
                 "from the movie with the title super imposed on it?", True),
                ("better! the girls dont have pants on - can you give them "
                 "80's clothing?", True)):
            with self.subTest(text=text):
                self.assertTrue(server.user_wants_render(text, has_visual))

    def test_a_compliment_is_not_a_render_request(self):
        """The other direction: _CHAT_ONLY matched a single pleasantry token,
        so any SEQUENCE of them fell through to _BARE_VISUAL_PROMPT, which read
        the compliment as a prompt and offered generate on it."""
        for text in ("Thanks, that looks great", "cool thanks", "ok great",
                     "nice, love it", "perfect!!!!", "much better thanks"):
            for has_visual in (False, True):
                with self.subTest(text=text, has_visual=has_visual):
                    self.assertFalse(server.user_wants_render(text, has_visual))

    def test_an_image_that_is_called_a_card_is_still_an_image(self):
        """_PRODUCT_TERMS lists "card" for the UI's job and hover cards, which
        made every "title card" ask read as a UI request."""
        self.assertTrue(server.user_wants_render(
            "I need to make an 80's movie title card"))
        self.assertTrue(server.user_wants_render("a lobby card for a horror film"))
        # the UI sense still has to stay out of the render lane
        self.assertFalse(server.user_wants_render(
            "can you fix the job card in the history grid", True))

    def test_a_request_in_a_later_clause_still_counts(self):
        for text in ("the girls dont have pants on - can you give them a coat",
                     "the sign is wrong, can you redo it",
                     "love the mood; make the light warmer"):
            with self.subTest(text=text):
                self.assertTrue(server.user_wants_render(text, True))

    async def test_a_withheld_generate_is_named_for_the_cloud_brain(self):
        """A vanishing tool used to be invisible, and invisible is what made it
        expensive: in chats/ce52340c.json three turns burned themselves on it,
        calling list_models over and over and then firing upscale, review and
        animate on the user's render, because nothing in the turn said the
        render lane was shut. The composer block in the user's own message was
        still ordering the brain to pass generate() arguments at the time."""
        reply = {"role": "assistant", "content": "Say the word and I'll fire it."}
        with patch.object(server, "load_config", return_value={"llm": {
                "base_url": "https://example.invalid", "model": "cloud"}}), \
             patch.object(server, "llm_call", AsyncMock(return_value=(
                 200, {"choices": [{"message": reply}]}))) as llm, \
             patch.object(server.HUB, "submit", AsyncMock()) as submit, \
             patch.object(server.HUB, "broadcast"):
            await server._kimi_reply(
                "chat-withheld",
                {"role": "user", "content": "How does the LoRA chain work?"}, [])

        submit.assert_not_awaited()
        offered = [(t.get("function") or {}).get("name")
                   for t in llm.await_args.kwargs["tools"]]
        self.assertNotIn("generate", offered)
        user_turn = next(m for m in reversed(llm.await_args.args[0])
                         if m["role"] == "user")
        self.assertIn("[NOTE - THIS TURN ONLY:", user_turn["content"])
        self.assertIn("generate is not offered", user_turn["content"])

    async def test_the_withheld_note_does_not_haunt_later_turns(self):
        """The note is true for exactly one turn. Left in the persisted convo it
        would read as 'rendering is still closed' forever - the very belief the
        note exists to prevent."""
        cfg = {"llm": {"base_url": "https://example.invalid", "model": "cloud"}}
        convo = []
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "llm_call", AsyncMock(return_value=(
                 200, {"choices": [{"message": {"role": "assistant",
                                                "content": "Say the word."}}]}))), \
             patch.object(server.HUB, "submit", AsyncMock()), \
             patch.object(server.HUB, "broadcast"):
            await server._kimi_reply(
                "chat-haunt",
                {"role": "user", "content": "How does the LoRA chain work?"}, convo)
        self.assertTrue(any("[NOTE - THIS TURN ONLY:" in str(m.get("content"))
                            for m in convo), "the note never rode the first turn")

        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "llm_call", AsyncMock(return_value=(
                 200, {"choices": [{"message": {"role": "assistant",
                                                "content": "Rolling."}}]}))) as llm, \
             patch.object(server.HUB, "submit", AsyncMock()), \
             patch.object(server.HUB, "broadcast"):
            await server._kimi_reply(
                "chat-haunt",
                {"role": "user", "content": "render a red fox in snow"}, convo)

        offered = [(t.get("function") or {}).get("name")
                   for t in llm.await_args.kwargs["tools"]]
        self.assertIn("generate", offered)
        self.assertFalse(
            any("[NOTE - THIS TURN ONLY:" in str(m.get("content"))
                for m in llm.await_args.args[0]),
            "a stale note tells the brain the render lane is still closed")

    async def test_prompt_enhance_off_submits_the_users_words_verbatim(self):
        rewritten = generate_call("render-one", "A heavily rewritten unrelated scene.")
        done = {"role": "assistant", "content": "On the way."}
        submit_result = {"id": "job123", "error": None, "seed": 42}
        with patch.object(server, "load_config", return_value={"llm": {
                "base_url": server.LOCAL_LLM_URL, "model": "local"}}), \
             patch.object(server, "llm_call", AsyncMock(side_effect=[
                 (200, {"choices": [{"message": rewritten}]}),
                 (200, {"choices": [{"message": done}]}),
             ])), \
             patch.object(server.HUB, "submit",
                          AsyncMock(return_value=submit_result)) as submit, \
             patch.object(server.HUB, "broadcast"):
            await server._kimi_reply(
                "chat2", {"role": "user", "content": "a red fox in snow"}, [],
                opts={"prompt_enhance": False})

        submit.assert_awaited_once()
        self.assertEqual(submit.await_args.args[3], "a red fox in snow")

    async def test_prompt_enhance_off_queues_even_when_brain_only_chats(self):
        reply = {"role": "assistant", "content": "On it."}
        submit_result = {"id": "job456", "error": None, "seed": 43}
        with patch.object(server, "load_config", return_value={"llm": {
                "base_url": "https://example.invalid", "model": "cloud"}}), \
             patch.object(server, "llm_call", AsyncMock(return_value=(
                 200, {"choices": [{"message": reply}]}))), \
             patch.object(server.HUB, "submit",
                          AsyncMock(return_value=submit_result)) as submit, \
             patch.object(server.HUB, "broadcast"):
            await server._kimi_reply(
                "chat3", {"role": "user", "content": "a silver fox in rain"}, [],
                opts={"prompt_enhance": False})

        submit.assert_awaited_once()
        self.assertEqual(submit.await_args.args[3], "a silver fox in rain")

    async def test_prompt_enhance_off_retains_prefixed_reference_description(self):
        prompt = "a red fox in snow"
        described = (prompt + "\nReference clothing: a cropped indigo denim jacket "
                     "with brass shank buttons and cream shearling cuffs.")
        directed = generate_call("render-ref", described)
        done = {"role": "assistant", "content": "On the way."}
        submit_result = {"id": "job-ref", "error": None, "seed": 45}
        user_msg = {"role": "user", "content": [
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64,AA=="}},
            {"type": "text", "text": prompt + "\n\n[COMPOSER HARD CONSTRAINTS]"},
        ]}
        with patch.object(server, "load_config", return_value={"llm": {
                "base_url": "https://example.invalid", "model": "cloud"}}), \
             patch.object(server, "llm_call", AsyncMock(side_effect=[
                 (200, {"choices": [{"message": directed}]}),
                 (200, {"choices": [{"message": done}]}),
             ])) as llm, \
             patch.object(server.HUB, "submit",
                          AsyncMock(return_value=submit_result)) as submit, \
             patch.object(server.HUB, "broadcast"):
            await server._kimi_reply(
                "chat-ref", user_msg, [], opts={
                    "prompt_enhance": False,
                    "refs": [{"kind": "clothing", "file": "jacket.png"}],
                })

        submit.assert_awaited_once()
        self.assertEqual(submit.await_args.args[3], described)
        first_request = llm.await_args_list[0].args[0]
        self.assertNotIn("[entropy:", json.dumps(first_request[-1]))

    async def test_prompt_enhance_off_rejects_rewritten_reference_scene(self):
        prompt = "a silver fox in rain"
        reply = {"role": "assistant", "content":
                 "A cinematic studio portrait rewritten around the reference."}
        submit_result = {"id": "job-ref-guard", "error": None, "seed": 46}
        user_msg = {"role": "user", "content": [
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64,AA=="}},
            {"type": "text", "text": prompt + "\n\n[COMPOSER HARD CONSTRAINTS]"},
        ]}
        with patch.object(server, "load_config", return_value={"llm": {
                "base_url": "https://example.invalid", "model": "cloud"}}), \
             patch.object(server, "llm_call", AsyncMock(return_value=(
                 200, {"choices": [{"message": reply}]}))), \
             patch.object(server.HUB, "submit",
                          AsyncMock(return_value=submit_result)) as submit, \
             patch.object(server.HUB, "broadcast"):
            await server._kimi_reply(
                "chat-ref-guard", user_msg, [], opts={
                    "prompt_enhance": False,
                    "refs": [{"kind": "style", "file": "look.png"}],
                })

        submit.assert_awaited_once()
        self.assertEqual(submit.await_args.args[3], prompt)

    async def test_prompt_enhance_off_does_not_record_a_failed_direct_queue(self):
        reply = {"role": "assistant", "content": "On it."}
        submit_result = {"id": "job-failed", "error": "comfy is offline", "seed": 44}
        convo = []
        with patch.object(server, "load_config", return_value={"llm": {
                "base_url": "https://example.invalid", "model": "cloud"}}), \
             patch.object(server, "llm_call", AsyncMock(return_value=(
                 200, {"choices": [{"message": reply}]}))), \
             patch.object(server.HUB, "submit",
                          AsyncMock(return_value=submit_result)) as submit, \
             patch.object(server.HUB, "broadcast") as broadcast:
            await server._kimi_reply(
                "chat4", {"role": "user", "content": "a fox in snow"}, convo,
                opts={"prompt_enhance": False})

        submit.assert_awaited_once()
        self.assertFalse(server.conversation_has_visual(convo))
        self.assertFalse(any("server queued that scene" in str(message.get("content"))
                             for message in convo))
        self.assertTrue(any(call.kwargs.get("type") == "thinkingdone"
                            for call in broadcast.call_args_list))

    # _nt pinned: this is the nt cascade. POSIX has its own discovery
    # (run*.sh, then main.py - a .bat is not bootable there), covered in
    # tests/test_linux_lane.py; on the ubuntu CI leg this test would
    # otherwise exercise the POSIX branch against .bat files.
    @patch.object(server, "_nt", lambda: True)
    def test_comfy_launcher_discovery_prefers_the_tuned_bat(self):
        """Starting main.py directly drops --fast fp16_accumulation,
        --use-sage-attention and --disable-dynamic-vram, which is a measurably
        slower machine. The launcher beside the ComfyUI folder is the contract."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            comfy = root / "ComfyUI"
            comfy.mkdir()
            for name in ("run_cpu.bat", "run_nvidia_gpu.bat",
                         "run_TEST_fp32vae.bat",
                         "run_nvidia_gpu_fast_fp16_accumulation.bat"):
                (root / name).write_text("rem", encoding="utf-8")
            self.assertEqual(server.find_comfy_launcher(comfy).name,
                             "run_nvidia_gpu_fast_fp16_accumulation.bat")
            # without the tuned one, the plain nvidia launcher wins - never cpu/test
            (root / "run_nvidia_gpu_fast_fp16_accumulation.bat").unlink()
            self.assertEqual(server.find_comfy_launcher(comfy).name,
                             "run_nvidia_gpu.bat")
            # only cpu/test launchers left: returning None is correct - booting
            # the CPU build would be far worse than saying it cannot start
            (root / "run_nvidia_gpu.bat").unlink()
            self.assertIsNone(server.find_comfy_launcher(comfy))

        with tempfile.TemporaryDirectory() as bare:
            empty = Path(bare) / "ComfyUI"
            empty.mkdir()
            self.assertIsNone(server.find_comfy_launcher(empty))

    def test_opening_the_app_is_what_starts_comfyui(self):
        """Booting from on_start dragged a 21GB model stack up behind a sidecar
        that might sit idle all session. Serving the page is the real signal,
        and a second page load must not start a second ComfyUI."""
        async def run():
            started = []

            async def fake_ensure():
                started.append(1)
                await asyncio.sleep(0.05)

            with patch.object(server, "ensure_comfy_running", fake_ensure), \
                 patch.dict(server.COMFY_BOOT, {"task": None}):
                await server.index(Mock())
                await server.index(Mock())          # still in flight - no second boot
                await asyncio.sleep(0)              # let the scheduled task run
                self.assertEqual(len(started), 1)
                await server.COMFY_BOOT["task"]
                await server.index(Mock())          # finished - a reload may retry
                await asyncio.sleep(0)
                self.assertEqual(len(started), 2)
                await server.COMFY_BOOT["task"]

        asyncio.run(run())

    def test_a_second_sidecar_exits_instead_of_lingering(self):
        """It loses the bind race and then sits there serving nothing, which is
        how two sidecars ended up running at once. A listener that accepts but
        never answers HTTP is a STALE holder, not a running Pixal - the connect
        probe alone could not tell those apart (2026-08-11)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            addr = held.getsockname()
            with patch.object(server, "LISTEN", addr):
                self.assertEqual(server.sidecar_port_state(), "stale")
        # nothing listening on that port any more, so a lone sidecar starts
        with patch.object(server, "LISTEN", addr):
            self.assertIsNone(server.sidecar_port_state())

    def test_untracked_comfy_work_is_still_cancellable(self):
        """HUB.jobs is in-memory, so restarting the sidecar orphans whatever
        ComfyUI is rendering: the card freezes and stop found nothing to
        cancel. ComfyUI's own queue is the truth."""
        queue = {"queue_running": [[0, "run-1", {}]],
                 "queue_pending": [[0, "pend-1", {}], [0, "pend-2", {}]]}
        posted = []

        class Request:
            async def json(self):
                return {}

        class FakeResponse:
            status = 200

            def __init__(self, payload=None):
                self._payload = payload

            async def json(self):
                return self._payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

        class FakeSession:
            def get(self, url, **_):
                return FakeResponse(queue)

            async def post(self, url, json=None, **_):
                posted.append((url.rsplit("/", 1)[-1], json))
                return FakeResponse()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

        with patch.object(server, "aiohttp", Mock(ClientSession=FakeSession)), \
             patch.dict(server.HUB.jobs, {}, clear=True):
            response = asyncio.run(server.stop(Request()))

        body = json.loads(response.text)
        self.assertTrue(body["untracked"])
        self.assertEqual(body["stopped"], 3)
        self.assertIn(("queue", {"delete": ["run-1", "pend-1", "pend-2"]}), posted)
        self.assertIn("interrupt", [name for name, _ in posted])

    def test_comfy_process_is_found_by_its_listening_port(self):
        """We only know the pid when WE launched it, and the usual case is a
        ComfyUI the user started. The port identifies it either way."""
        netstat = (
            "  Proto  Local Address      Foreign Address    State           PID\n"
            "  TCP    127.0.0.1:8188     0.0.0.0:0          LISTENING       11684\n"
            "  TCP    127.0.0.1:8190     0.0.0.0:0          LISTENING       999\n"
            "  TCP    127.0.0.1:54321    127.0.0.1:8188     ESTABLISHED     4242\n")
        with patch.object(server.subprocess, "run",
                          return_value=Mock(stdout=netstat)):
            self.assertEqual(server.comfy_listener_pid(8188), 11684)
            self.assertEqual(server.comfy_listener_pid(8190), 999)
            self.assertIsNone(server.comfy_listener_pid(9999))
        # an ESTABLISHED row to the same port must never be mistaken for it
        with patch.object(server.subprocess, "run",
                          return_value=Mock(stdout=netstat.replace("LISTENING", "TIME_WAIT"))):
            self.assertIsNone(server.comfy_listener_pid(8188))

    def test_boot_meter_is_calibrated_from_the_last_measured_start(self):
        cfg = dict(server.load_config())
        cfg["comfy_boot_seconds"] = 62.0
        with patch.object(server, "load_config", return_value=cfg), \
             patch.dict(server.COMFY_BOOT, {"at": None, "launcher": None,
                                            "error": None}):
            idle = server.comfy_boot_state()
            self.assertFalse(idle["starting"])
            self.assertEqual(idle["expected"], 62.0)
        # Built with Path rather than a literal: a hardcoded "X:\\c\\run.bat" is
        # one string on Linux, where a backslash is not a separator, so the
        # basename assertion below passed on Windows and failed in CI.
        launcher = str(Path("comfy") / "run.bat")
        with patch.object(server, "load_config", return_value=cfg), \
             patch.dict(server.COMFY_BOOT, {"at": server.time.time() - 10,
                                            "launcher": launcher,
                                            "error": None}), \
             patch.object(server.HUB, "comfy_up", False):
            live = server.comfy_boot_state()
            self.assertTrue(live["starting"])
            self.assertGreaterEqual(live["elapsed"], 9.5)
            self.assertEqual(live["launcher"], "run.bat")

    def test_measured_boot_time_survives_a_config_round_trip(self):
        """load_config merges a WHITELIST, so a key it does not name is dropped
        on read and wiped by the next save. The calibration was written to disk
        and thrown away every time until the key was listed."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            with patch.object(server, "CONFIG", cfg_path):
                cfg = server.load_config()
                cfg["comfy_boot_seconds"] = 51.0
                server.save_config(cfg)
                self.assertEqual(server.load_config()["comfy_boot_seconds"], 51.0)
                # an unrelated settings write must not clear it
                other = server.load_config()
                other["comfy_url"] = "http://127.0.0.1:8188"
                server.save_config(other)
                self.assertEqual(server.load_config()["comfy_boot_seconds"], 51.0)

    def test_lane_replay_reports_an_in_flight_job_as_running(self):
        """done was hardcoded True, so hard-refreshing mid-render replayed the
        job as a finished card with no images and no progress."""
        finished = {"id": "done1", "template": "realism", "scene": "a fox",
                    "seed": 1, "count": 1, "images": [{"filename": "a.png"}],
                    "elapsed": 12.5, "error": None}
        running = {"id": "live1", "template": "realism", "scene": "a stoat",
                   "seed": 2, "count": 1, "images": [], "error": None}
        failed = {"id": "bad1", "template": "realism", "scene": "a hare",
                  "seed": 3, "count": 1, "images": [], "error": "comfy offline"}
        lane = [{"role": "job", "job_id": "done1", "ts": 1},
                {"role": "job", "job_id": "live1", "ts": 2},
                {"role": "job", "job_id": "bad1", "ts": 3}]
        # lane is a read-only property, so it patches on the class, not the instance
        with patch.object(server.HUB, "ledger_read", return_value=[finished]), \
             patch.object(server.HUB, "jobs", {"live1": running, "bad1": failed}), \
             patch.object(type(server.HUB), "lane", lane):
            body = json.loads(asyncio.run(server.lane_get(None)).text)
        states = {row["job"]["job_id"]: row["job"]["done"] for row in body["lane"]}
        self.assertTrue(states["done1"])     # in the ledger, has elapsed
        self.assertFalse(states["live1"])    # still sampling
        self.assertTrue(states["bad1"])      # failed jobs are not still running

    def test_realism_caption_scrubbed_on_every_recipe(self):
        """The closing caption was retired from both contracts (2026-08-11, at
        the user's call - it tail-ended every card as boilerplate). Brains that
        learned it from history keep emitting it, so the scrubber now strips it
        on EVERY recipe, and the contracts must no longer teach it."""
        scene = "She sits by the window, one hand on the sill. Rich saturated colour."
        for template in ("realism", "realism_ii", "qwen_image",
                         "identity_edit", "zara_edit", "anime", "fantasy", "zimage"):
            with self.subTest(template=template):
                self.assertEqual(server.scrub_style_caption(scene, template),
                                 "She sits by the window, one hand on the sill.")
        # only the trailing caption goes; the same words mid-scene are content
        mid = "A poster reading rich saturated colour hangs above the bed."
        self.assertEqual(server.scrub_style_caption(mid, "anime"), mid)
        self.assertNotIn(server.REALISM_CAPTION, server.SYSTEM)
        self.assertNotIn(server.REALISM_CAPTION, server.SYSTEM_LOCAL)

    def test_accepting_a_proposed_scene_counts_as_a_render_request(self):
        """The local writer prints the scene as chat and waits. "yes" and the
        typo "shoe me?" both read as conversation to the intent classifier, so
        the user had to ask three times before anything queued."""
        proposal = [{"role": "user", "content": "a woman on a bed"},
                    {"role": "assistant", "content": " ".join(["word"] * 45)}]
        for text in ("yes", "shoe me?", "go", "ok", "do it", "love it"):
            with self.subTest(accept=text):
                self.assertTrue(server._pending_scene(proposal))
                self.assertTrue(server._AFFIRMATIVE.match(text))
        for text in ("what model is that?", "make her hair red instead"):
            with self.subTest(not_accept=text):
                self.assertIsNone(server._AFFIRMATIVE.match(text))
        # nothing pending when the assistant already acted, or only chatted briefly
        acted = [{"role": "user", "content": "go"},
                 {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]}]
        self.assertFalse(server._pending_scene(acted))
        self.assertFalse(server._pending_scene(
            [{"role": "assistant", "content": "What are we making?"}]))

    async def test_queue_receipt_withholds_the_scene_and_forbids_done_claims(self):
        """The receipt used to hand the scene back, so the follow-up turn
        reprinted the whole prompt and opened it with "Rendered!"."""
        directed = generate_call("render-receipt", "a lone fox crossing fresh snow")
        done = {"role": "assistant", "content": "Queued."}
        convo = []
        with patch.object(server, "load_config", return_value={"llm": {
                "base_url": "https://example.invalid", "model": "cloud"}}), \
             patch.object(server, "llm_call", AsyncMock(side_effect=[
                 (200, {"choices": [{"message": directed}]}),
                 (200, {"choices": [{"message": done}]}),
             ])), \
             patch.object(server.HUB, "submit", AsyncMock(
                 return_value={"id": "job-r", "error": None, "seed": 9})), \
             patch.object(server.HUB, "broadcast") as broadcast:
            await server._kimi_reply(
                "cid-receipt", {"role": "user", "content": "show me a fox in snow"},
                convo)

        receipt = next(m for m in convo if m.get("role") == "tool")
        payload = json.loads(receipt["content"]) if isinstance(receipt["content"], str) \
            else receipt["content"]
        self.assertEqual(payload["queued"], "job-r")
        self.assertNotIn("scene", payload)
        self.assertIn("NOT finished", payload["status"])
        notes = [c.kwargs.get("note") for c in broadcast.call_args_list
                 if c.kwargs.get("type") == "thinking"]
        self.assertTrue(any("this takes a moment" in str(n) for n in notes))

    def test_open_ask_detection_separates_a_blank_ask_from_a_written_one(self):
        """A written scene must not receive entropy territories - that is how a
        stated "cozy loft in NYC" picked up neon signage on a daylit street."""
        for text in ("", "surprise me", "a portrait", "anything moody",
                     "you pick", "make me a new image", "another photo please",
                     "surprise me with a moody one"):
            with self.subTest(open=text):
                self.assertTrue(server.ask_is_open(text))
        for text in ("background is a cozy loft in NYC", "a cyberpunk street",
                     "a woman on wet sand at golden hour", "a welder",
                     "a blonde woman wearing a denim jacket", "rainy tokyo alley"):
            with self.subTest(written=text):
                self.assertFalse(server.ask_is_open(text))

    async def test_a_written_scene_is_sent_without_entropy_territories(self):
        reply = {"role": "assistant", "content": "On it."}
        sent = {}

        async def capture(messages, **kwargs):
            # the USER turn only - the system prompt now documents the tag, so
            # searching the whole payload always matches
            sent.setdefault("first", json.dumps(messages[-1]))
            return 200, {"choices": [{"message": reply}]}

        for text, expect_tag in (("background is a cozy loft in NYC", False),
                                 ("surprise me", True)):
            sent.clear()
            with self.subTest(text=text), \
                 patch.object(server, "load_config", return_value={"llm": {
                     "base_url": "https://example.invalid", "model": "cloud"}}), \
                 patch.object(server, "llm_call", AsyncMock(side_effect=capture)), \
                 patch.object(server.HUB, "submit",
                              AsyncMock(return_value={"id": "j", "error": None,
                                                      "seed": 1})), \
                 patch.object(server.HUB, "broadcast"):
                await server._kimi_reply("cid-ent", {"role": "user", "content": text}, [])
                self.assertEqual("[entropy:" in sent["first"], expect_tag)

    async def test_prose_render_strips_a_brief_the_local_brain_echoed(self):
        """The local writer sometimes prints its own server-side brief above the
        scene. On the prose path that text became BOTH the rendered prompt and
        the lane message - the tool-call path stripped it, this one did not.
        Asserting on the call site, not on _strip_history_directives itself: the
        helper was already correct and still shipped the brief."""
        leaked = (
            "[COMPOSER: writing for template=realism. Model, loras, size and "
            "reference are applied server-side - never mention file names.]\n"
            "[CHARACTER ANCHOR: woman, 20 years old, platinum blonde hair, high "
            "cheekbones, brown eyes - wearing a bikini with thin straps.]\n\n"
            "A platinum blonde woman stands barefoot on wet sand at golden hour, "
            "one leg bent, toes curling into the tide, arms loose at her sides "
            "and her head tilted as if catching the breeze while low sunlight "
            "rakes across her collarbone and the wind lifts strands of hair.")
        scene = leaked.split("]\n\n", 1)[1]
        reply = {"role": "assistant", "content": leaked}
        submit_result = {"id": "job-echo", "error": None, "seed": 47}
        with patch.object(server, "load_config", return_value={"llm": {
                "base_url": f"http://127.0.0.1:{server.LOCAL_LLM_PORT}/v1",
                "model": "local"}}), \
             patch.object(server, "llm_call", AsyncMock(return_value=(
                 200, {"choices": [{"message": reply}]}))), \
             patch.object(server.HUB, "submit",
                          AsyncMock(return_value=submit_result)) as submit, \
             patch.object(server.HUB, "broadcast") as broadcast:
            await server._kimi_reply(
                "chat-echo", {"role": "user", "content": "show me"}, [])

        submit.assert_awaited_once()
        self.assertEqual(submit.await_args.args[3], scene)
        said = [c.kwargs.get("text") for c in broadcast.call_args_list
                if c.kwargs.get("type") == "text"]
        self.assertTrue(said)
        for text in said:
            self.assertNotIn("[COMPOSER", text)
            self.assertNotIn("[CHARACTER ANCHOR", text)

    async def test_chat_alongside_a_tool_call_strips_an_echoed_brief(self):
        """Same leak on the third broadcast site: prose the brain emits next to
        its generate() call."""
        directed = generate_call("render-echo", "a lone fox crossing fresh snow")
        chatter = {"role": "assistant",
                   "content": "[COMPOSER: writing for template=realism.] Working on it.",
                   "tool_calls": directed["tool_calls"]}
        done = {"role": "assistant", "content": "Queued."}
        submit_result = {"id": "job-echo2", "error": None, "seed": 48}
        with patch.object(server, "load_config", return_value={"llm": {
                "base_url": "https://example.invalid", "model": "cloud"}}), \
             patch.object(server, "llm_call", AsyncMock(side_effect=[
                 (200, {"choices": [{"message": chatter}]}),
                 (200, {"choices": [{"message": done}]}),
             ])), \
             patch.object(server.HUB, "submit",
                          AsyncMock(return_value=submit_result)), \
             patch.object(server.HUB, "broadcast") as broadcast:
            await server._kimi_reply(
                "chat-echo2", {"role": "user", "content": "show me a fox in snow"}, [])

        said = [c.kwargs.get("text") for c in broadcast.call_args_list
                if c.kwargs.get("type") == "text"]
        self.assertIn("Working on it.", said)
        for text in said:
            self.assertNotIn("[COMPOSER", text)


class LocalLlmPythonResolverTests(unittest.TestCase):
    def test_explicit_override_wins_and_normalizes_quotes(self):
        with tempfile.TemporaryDirectory() as td:
            explicit = Path(td) / "Python With Space" / "python.exe"
            explicit.parent.mkdir()
            explicit.touch()
            with patch.dict(server.os.environ,
                            {"PIXAL_LLM_PYTHON": f'"{explicit}"'}, clear=True), \
                 patch.object(server, "_llm_python_has_server", return_value=True) as probe:
                selected, error = server.resolve_local_llm_python({"comfy_root": ""})
        self.assertEqual(selected, str(explicit.resolve()))
        self.assertIsNone(error)
        probe.assert_called_once_with(explicit.resolve())

    def test_explicit_override_failures_do_not_fall_back(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.exe"
            with patch.dict(server.os.environ,
                            {"PIXAL_LLM_PYTHON": str(missing)}, clear=True), \
                 patch.object(server, "_llm_python_has_server") as probe:
                selected, error = server.resolve_local_llm_python({"comfy_root": ""})
            self.assertIsNone(selected)
            self.assertIn("does not point", error)
            probe.assert_not_called()

            present = Path(td) / "python.exe"
            present.touch()
            with patch.dict(server.os.environ,
                            {"PIXAL_LLM_PYTHON": str(present)}, clear=True), \
                 patch.object(server, "_llm_python_has_server", return_value=False):
                selected, error = server.resolve_local_llm_python({"comfy_root": ""})
            self.assertIsNone(selected)
            self.assertIn("cannot import llama_cpp.server", error)

    def test_importable_current_interpreter_wins(self):
        with tempfile.TemporaryDirectory() as td:
            current = Path(td) / "current" / "python.exe"
            current.parent.mkdir()
            current.touch()
            with patch.dict(server.os.environ, {}, clear=True), \
                 patch.object(server.sys, "executable", str(current)), \
                 patch.object(server, "_llm_python_has_server", return_value=True) as probe:
                selected, error = server.resolve_local_llm_python({"comfy_root": ""})
        self.assertEqual(selected, str(current.resolve()))
        self.assertIsNone(error)
        probe.assert_called_once_with(current.resolve())

    def test_all_configured_portable_root_forms_resolve_the_same_python(self):
        with tempfile.TemporaryDirectory() as td:
            portable_root = Path(td) / "portable"
            comfy = portable_root / "ComfyUI"
            models = comfy / "models"
            models.mkdir(parents=True)
            portable_python = portable_root / "python_embeded" / "python.exe"
            portable_python.parent.mkdir()
            portable_python.touch()
            current = Path(td) / "standalone" / "python.exe"
            current.parent.mkdir()
            current.touch()

            for configured in (portable_root, comfy, models):
                with self.subTest(configured=configured), \
                     patch.dict(server.os.environ, {}, clear=True), \
                     patch.object(server.sys, "executable", str(current)), \
                     patch.object(
                         server, "_llm_python_has_server",
                         side_effect=lambda p: Path(p) == portable_python,
                     ) as probe:
                    selected, error = server.resolve_local_llm_python(
                        {"comfy_root": str(configured)})
                self.assertEqual(selected, str(portable_python))
                self.assertIsNone(error)
                self.assertEqual(probe.call_args_list,
                                 [call(current.resolve()), call(portable_python)])

    def test_no_compatible_interpreter_returns_actionable_error(self):
        with tempfile.TemporaryDirectory() as td:
            current = Path(td) / "python.exe"
            current.touch()
            with patch.dict(server.os.environ, {}, clear=True), \
                 patch.object(server.sys, "executable", str(current)), \
                 patch.object(server, "_llm_python_has_server", return_value=False):
                selected, error = server.resolve_local_llm_python(
                    {"comfy_root": str(Path(td) / "not-comfy")})
        self.assertIsNone(selected)
        self.assertIn("set PIXAL_LLM_PYTHON", error)

    def test_import_probe_uses_candidate_torch_dll_environment(self):
        candidate = Path("C:/portable/python_embeded/python.exe")
        completed = Mock(returncode=0)
        with patch.dict(server.os.environ, {"PATH": "base-path"}, clear=True), \
             patch.object(server.subprocess, "run", return_value=completed) as run:
            self.assertTrue(server._llm_python_has_server(candidate))
        argv = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        self.assertEqual(argv[0], str(candidate))
        self.assertEqual(env["KMP_DUPLICATE_LIB_OK"], "TRUE")
        self.assertTrue(env["PATH"].startswith(
            str(server._torch_lib_for_python(candidate)) + os.pathsep))


class ManagedLocalLlmSpawnTests(unittest.IsolatedAsyncioTestCase):
    async def test_spawn_uses_resolved_python_and_its_dll_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            selected = root / "python_embeded" / "python.exe"
            selected.parent.mkdir()
            selected.touch()
            model = root / "brain.gguf"
            model.touch()
            state_path = root / "llm-state.json"
            log_path = root / "llama.log"
            config = {
                "llm": {
                    "base_url": server.LOCAL_LLM_URL,
                    "local_model": str(model),
                    "local_keep": True,
                },
                "comfy_root": "",
            }
            proc = Mock(pid=4321)
            proc.poll.return_value = None
            with patch.object(server, "load_config", return_value=config), \
                 patch.object(server, "local_llm_port_open",
                              AsyncMock(return_value=False)), \
                 patch.object(server, "local_llm_up", AsyncMock(return_value=True)), \
                 patch.object(server, "resolve_local_llm_python",
                              return_value=(str(selected), None)), \
                 patch.object(server, "LLM_STATE", state_path), \
                 patch.object(server, "LLM_LOG", log_path), \
                 patch.object(server.subprocess, "Popen", return_value=proc) as popen:
                error = await server._ensure_local_llm()

            self.assertIsNone(error)
            argv = popen.call_args.args[0]
            env = popen.call_args.kwargs["env"]
            self.assertEqual(argv[0], str(selected))
            self.assertTrue(env["PATH"].startswith(
                str(server._torch_lib_for_python(selected)) + os.pathsep))
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["model"],
                             str(model))
            popen.call_args.kwargs["stdout"].close()

    async def test_resolver_failure_does_not_kill_owned_server(self):
        with tempfile.TemporaryDirectory() as td:
            model = Path(td) / "new.gguf"
            model.touch()
            config = {
                "llm": {
                    "base_url": server.LOCAL_LLM_URL,
                    "local_model": str(model),
                    "local_keep": True,
                },
                "comfy_root": "",
            }
            with patch.object(server, "load_config", return_value=config), \
                 patch.object(server, "local_llm_port_open",
                              AsyncMock(return_value=True)), \
                 patch.object(server, "_llm_state",
                              return_value={"pid": 99, "model": "old.gguf"}), \
                 patch.object(server, "resolve_local_llm_python",
                              return_value=(None, "no compatible interpreter")), \
                 patch.object(server, "_llm_kill") as kill, \
                 patch.object(server.subprocess, "Popen") as popen:
                error = await server._ensure_local_llm()
            self.assertEqual(error, "no compatible interpreter")
            kill.assert_not_called()
            popen.assert_not_called()


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class LocalGpuLayersConfigTests(unittest.TestCase):
    """llm.local_gpu_layers: how much of the local brain rides the card.
    -1 = every layer on the GPU (byte-identical to the hardcoded flag 8.6
    shipped), 0 = CPU, positive = that many layers on the GPU. On a 16 GB
    card this is the setting that stops the chat brain crowding the render."""

    def test_the_default_is_full_gpu(self):
        # A config.json that predates the key must behave exactly like before:
        # the default merge fills -1, never 0. CONFIG is pointed at an empty
        # folder so load_config returns pure defaults - the real config.json
        # is never read (sanctioned simulation).
        with tempfile.TemporaryDirectory() as td, \
             patch.object(server, "CONFIG", Path(td) / "config.json"):
            cfg = server.load_config()
        self.assertEqual(cfg["llm"].get("local_gpu_layers"), -1)


class LocalGpuLayersSettingsTests(unittest.TestCase):
    """settings_post accepts any int >= -1 (the UI writes only -1/0; partial
    counts are a config.json power move) and rejects the rest WITHOUT saving;
    settings_get always exposes the key, so a pre-flag install reads as GPU."""

    def _full_cfg(self, llm):
        return {"llm": {"base_url": "", "model": "", **llm},
                "critic": {"model": ""}, "upscale": {}, "edit": {}, "vae": {},
                "pid": {}, "video": {"default_engine": "", "default_model": ""},
                "extra_model_roots": [], "comfy_editor": False,
                "comfy_console": "tui", "explicit": "auto",
                "vram_profile": "auto"}

    def _settings_get(self, cfg):
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "_video_asset", side_effect=lambda _k, rel: rel), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()):
            return asyncio.run(server.settings_get(FakeRequest({})))

    def test_settings_get_exposes_minus_one_when_the_key_is_missing(self):
        response = self._settings_get(self._full_cfg({}))
        llm = json.loads(response.text)["llm"]
        self.assertEqual(llm.get("local_gpu_layers"), -1)

    def test_settings_get_exposes_a_configured_count(self):
        response = self._settings_get(self._full_cfg({"local_gpu_layers": 0}))
        llm = json.loads(response.text)["llm"]
        self.assertEqual(llm.get("local_gpu_layers"), 0)

    def test_settings_post_round_trips_gpu_cpu_and_partial_counts(self):
        for want in (-1, 0, 20):
            with self.subTest(want=want):
                cfg = self._full_cfg({})
                saved = []
                with patch.object(server, "load_config", return_value=cfg), \
                     patch.object(server, "save_config",
                                  side_effect=lambda c: saved.append(c)):
                    post = asyncio.run(server.settings_post(
                        FakeRequest({"llm": {"local_gpu_layers": want}})))
                    self.assertEqual(post.status, 200)
                    self.assertEqual(json.loads(post.text), {"ok": True})
                    response = self._settings_get(cfg)
                self.assertEqual(saved[0]["llm"].get("local_gpu_layers"), want)
                llm = json.loads(response.text)["llm"]
                self.assertEqual(llm.get("local_gpu_layers"), want)

    def test_settings_post_rejects_non_ints_and_counts_below_minus_one(self):
        for bad in (True, False, "7", -2, 1.5):
            with self.subTest(bad=bad):
                saved = []
                with patch.object(server, "load_config",
                                  return_value=self._full_cfg({})), \
                     patch.object(server, "save_config",
                                  side_effect=lambda c: saved.append(c)):
                    response = asyncio.run(server.settings_post(
                        FakeRequest({"llm": {"local_gpu_layers": bad}})))
                self.assertEqual(response.status, 400)
                self.assertEqual(json.loads(response.text),
                                 {"ok": False,
                                  "error": f"not a gpu layer count: {bad}"})
                self.assertEqual(saved, [])  # a rejected write never touches config


class LocalGpuLayersSpawnTests(unittest.IsolatedAsyncioTestCase):
    """The flag travels the whole lane: config -> spawn argv -> state json ->
    the next ensure's staleness compare. A state json WITHOUT the key (every
    install running today) must read as stale once - respawn, rewrite, then
    settle - or the setting is a lie."""

    def _cfg(self, model, **llm):
        return {"llm": {"base_url": server.LOCAL_LLM_URL,
                        "local_model": str(model), "local_keep": True, **llm},
                "comfy_root": ""}

    @staticmethod
    def _flag_value(argv):
        return argv[argv.index("--n_gpu_layers") + 1]

    async def _ensure(self, td, cfg, state=None, port_open=(False,),
                      mmproj=None, vision=True):
        """Run _ensure_local_llm with every outside effect stubbed (the
        LIVE-MACHINE RULE: no real spawn, no real port probe, no real config).
        Returns (error, popen, kill, state_path)."""
        root = Path(td)
        selected = root / "python_embeded" / "python.exe"
        selected.parent.mkdir(exist_ok=True)
        selected.touch()
        state_path = root / "llm-state.json"
        log_path = root / "llama.log"
        proc = Mock(pid=4321)
        proc.poll.return_value = None
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "local_llm_port_open",
                          AsyncMock(side_effect=list(port_open))), \
             patch.object(server, "local_llm_up", AsyncMock(return_value=True)), \
             patch.object(server, "_llm_state", return_value=(state or {})), \
             patch.object(server, "_local_llm_mmproj", return_value=mmproj), \
             patch.object(server, "_vision_smoke_test",
                          AsyncMock(return_value=vision)), \
             patch.object(server, "resolve_local_llm_python",
                          return_value=(str(selected), None)), \
             patch.object(server, "_llm_kill") as kill, \
             patch.object(server, "LLM_STATE", state_path), \
             patch.object(server, "LLM_LOG", log_path), \
             patch.object(server.subprocess, "Popen", return_value=proc) as popen:
            error = await server._ensure_local_llm()
        if popen.call_args is not None:
            # The log handle stays open inside Popen's recorded kwargs; free it
            # or Windows refuses to clean the temp dir.
            popen.call_args.kwargs["stdout"].close()
        return error, popen, kill, state_path

    async def test_spawn_without_the_key_is_byte_identical_to_today(self):
        with tempfile.TemporaryDirectory() as td:
            model = Path(td) / "brain.gguf"
            model.touch()
            error, popen, kill, state_path = await self._ensure(
                td, self._cfg(model))
            self.assertIsNone(error)
            self.assertEqual(self._flag_value(popen.call_args.args[0]), "-1")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state.get("gpu_layers"), -1)
            kill.assert_not_called()

    async def test_spawn_passes_the_configured_layer_count(self):
        for layers in (0, 20):
            with self.subTest(layers=layers), \
                 tempfile.TemporaryDirectory() as td:
                model = Path(td) / "brain.gguf"
                model.touch()
                error, popen, _kill, state_path = await self._ensure(
                    td, self._cfg(model, local_gpu_layers=layers))
                self.assertIsNone(error)
                self.assertEqual(self._flag_value(popen.call_args.args[0]),
                                 str(layers))
                state = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual(state.get("gpu_layers"), layers)

    async def test_a_state_json_without_the_key_reads_as_stale(self):
        # Every install running today has {pid, model, mmproj} only. The
        # compare must miss on the absent key, replace the server ONCE, and
        # rewrite the state with the key so the next ensure settles.
        with tempfile.TemporaryDirectory() as td:
            model = Path(td) / "brain.gguf"
            model.touch()
            error, popen, kill, state_path = await self._ensure(
                td, self._cfg(model),
                state={"pid": 99, "model": str(model), "mmproj": None},
                port_open=(True, False))
            self.assertIsNone(error)
            kill.assert_called_once_with(99)
            popen.assert_called_once()
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state.get("gpu_layers"), -1)

    async def test_a_matching_layer_count_settles(self):
        with tempfile.TemporaryDirectory() as td:
            model = Path(td) / "brain.gguf"
            model.touch()
            error, popen, kill, _state_path = await self._ensure(
                td, self._cfg(model),
                state={"pid": 99, "model": str(model), "mmproj": None,
                       "gpu_layers": -1},
                port_open=(True,))
            self.assertIsNone(error)
            kill.assert_not_called()
            popen.assert_not_called()

    async def test_a_changed_layer_count_replaces_the_running_server(self):
        with tempfile.TemporaryDirectory() as td:
            model = Path(td) / "brain.gguf"
            model.touch()
            error, popen, kill, state_path = await self._ensure(
                td, self._cfg(model, local_gpu_layers=0),
                state={"pid": 99, "model": str(model), "mmproj": None,
                       "gpu_layers": -1},
                port_open=(True, False))
            self.assertIsNone(error)
            kill.assert_called_once_with(99)
            self.assertEqual(self._flag_value(popen.call_args.args[0]), "0")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state.get("gpu_layers"), 0)

    async def test_the_blind_demote_preserves_the_layer_count(self):
        # The vision-failed rewrite drops mmproj but must not reset the rest
        # of the state - a demote that lost gpu_layers would respawn-loop.
        with tempfile.TemporaryDirectory() as td:
            model = Path(td) / "brain.gguf"
            model.touch()
            error, _popen, _kill, state_path = await self._ensure(
                td, self._cfg(model, local_gpu_layers=0),
                mmproj=str(Path(td) / "mmproj.gguf"), vision=False)
            self.assertIsNone(error)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIsNone(state["mmproj"])
            self.assertEqual(state.get("gpu_layers"), 0)


class FreeChatModelTests(unittest.IsolatedAsyncioTestCase):
    """The one flush /api/comfy/free deliberately refuses to do.

    It exists because a chat model with a grown KV cache was measured at 7.2GB
    while MiniMax H3's DiT alone stages at ~20GB of a 32GB card - the
    difference between a 700s render and one still going at 55 minutes.
    """

    async def test_it_reports_how_much_came_back(self):
        with patch.object(server, "_llm_state", return_value={"pid": 4242}), \
             patch.object(server, "_llm_kill", return_value=True), \
             patch.object(server, "gpu_free_bytes",
                          side_effect=[10 * 2**30, 17 * 2**30]), \
             patch.object(server, "LLM_STATE", Mock()):
            resp = await server.free_chat_model(None)
        body = json.loads(resp.text)
        self.assertTrue(body["freed"])
        self.assertEqual(body["freed_gb"], 7.0)

    async def test_a_stale_pidfile_does_not_claim_a_win(self):
        """The process can die outside Pixal; saying "freed" then would be a
        lie, and the pidfile still has to go."""
        with patch.object(server, "_llm_state", return_value={"pid": 4242}), \
             patch.object(server, "_llm_kill", return_value=False), \
             patch.object(server, "LLM_STATE", Mock()) as state:
            resp = await server.free_chat_model(None)
        body = json.loads(resp.text)
        self.assertFalse(body["freed"])
        self.assertIn("already gone", body["note"])
        state.unlink.assert_called_once()

    async def test_nothing_to_free_is_not_an_error(self):
        with patch.object(server, "_llm_state", return_value={}):
            resp = await server.free_chat_model(None)
        body = json.loads(resp.text)
        self.assertTrue(body["ok"])
        self.assertFalse(body["freed"])


class SubstantiveRedirectTests(unittest.TestCase):
    """A pending scene or unanswered question makes the next turn the second
    half of a render request. Reading "substantive" as merely "not a question"
    let that rescue hand the generate tool back on an explicit refusal - the
    2026-08-13 failure, re-entered through the rescue door rather than through
    user_wants_render."""

    def test_the_redirect_still_works(self):
        # the whole point of the rescue: shape the pending scene without
        # having to type "show me"
        for text in ("so it's in the style of an 80s slasher flick",
                     "surfing at sunset",
                     "make her hair red instead"):
            with self.subTest(text=text):
                self.assertTrue(server.substantive_redirect(text))

    def test_an_explicit_refusal_never_redirects(self):
        for text in ("no render, just tell me what you see",
                     "Do not make an image.",
                     "I don't want an image yet."):
            with self.subTest(text=text):
                self.assertFalse(server.substantive_redirect(text))

    def test_a_pleasantry_never_redirects(self):
        for text in ("thanks", "cool thanks", "ok cool, thanks!"):
            with self.subTest(text=text):
                self.assertFalse(server.substantive_redirect(text))

    def test_a_chat_request_never_redirects(self):
        for text in ("Tell me a joke.", "explain how loras work"):
            with self.subTest(text=text):
                self.assertFalse(server.substantive_redirect(text))

    def test_a_question_never_redirects(self):
        self.assertFalse(server.substantive_redirect("what would that look like?"))
        self.assertFalse(server.substantive_redirect(""))

    def grants(self, text):
        """The production gate for both rescue branches: an affirmative ACCEPTS
        the pending scene/question, anything substantive REDIRECTS it."""
        return bool(server._AFFIRMATIVE.match(text.strip())
                    or server.substantive_redirect(text))

    def test_a_bare_yes_still_answers_a_pending_question(self):
        # 907b7c2's whole point: the brain asks, the user answers, and the
        # answer turn must GET the render tool. substantive_redirect vetoes
        # these as pleasantries, so the affirmative half has to carry them -
        # gating the pending-question branch on _substantive alone re-closed
        # the door from the other side.
        for text in ("yes", "yeah", "yep", "ok", "okay", "sure",
                     "sounds good", "ready", "do it", "go ahead"):
            with self.subTest(text=text):
                self.assertTrue(self.grants(text))

    def test_the_closed_door_stays_closed(self):
        for text in ("thanks", "cool thanks", "no render, just tell me what you see",
                     "Do not make an image.", "Tell me a joke.", "better"):
            with self.subTest(text=text):
                self.assertFalse(self.grants(text))

    def test_it_agrees_with_user_wants_render_on_refusals(self):
        # the redirect must never be MORE permissive than the queue authority
        # it is rescuing around
        for text in ("no render, just tell me what you see", "thanks",
                     "Do not make an image.", "Tell me a joke."):
            with self.subTest(text=text):
                self.assertFalse(server.user_wants_render(text, True))
                self.assertFalse(server.substantive_redirect(text))


if __name__ == "__main__":
    unittest.main()
