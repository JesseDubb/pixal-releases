"""9.62 - Prompt enhance OFF with a reference attached.

A chat turn with an attached image is a content LIST, and the substitution
loop in _kimi_reply rewrites every image_url part to the literal text part
"[reference image]" so base64 is not resent forever. captured_prompt joins
EVERY text part of a list turn, so a walk-back returned
"[reference image] <the user's words>" - and _direct_prompt_scene keeps the
user's text immutable, so nothing downstream repaired it (Jesse's Zara
session, chat 7d77102e, 2026-08-27: every persisted user turn carries the
placeholder part, one "go" away from a leaked scene).

The contract with enhance OFF: the anchor's identity photo drives the
identity graph server-side but is never attached to the chat turn as a
vision image (the attach flips has_vision_refs and forces a brain
round-trip on the direct path), the typed text passes through as the
positive prompt, and the placeholder can never reach the encoder.
"""
import unittest
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

_SPEC = spec_from_file_location(
    "pixal_server_verbatim_ref_tests", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

# Jesse's actual turn from chat 7d77102e (2026-08-27), 38 words - long enough
# that enhance_off_is_prompt scores it a prompt with no render verb needed.
PROMPT = ("Close-up portrait at a cafe window, golden hour sun raking across "
          "her face, hair tucked behind one ear, small round gold earrings, "
          "soft genuine smile, sharp eyes, shallow depth of field. She wears "
          "an oversized cream knit sweater.")

LOCAL_COMPOSER = ("\n\n[COMPOSER: writing for template=identity_edit. Model, "
                  "loras, size and reference are applied server-side - never "
                  "mention file names.]")


@contextmanager
def identity_anchor():
    """A temp ComfyUI root whose input/ holds the anchor's reference photo."""
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        character = {"id": "hero", "name": "Hero", "style": "silver hair",
                     "identity_ref": "hero.png"}
        (root / "input" / "hero.png").write_bytes(b"reference")
        with patch.object(server, "CDIR", root), \
             patch.object(server, "CHARACTERS", {"hero": character}):
            yield root, character


def substituted_turn(text):
    """A past user turn AFTER the _kimi_reply substitution loop: the image
    part has become the placeholder text part (the 7d77102e shape)."""
    return {"role": "user", "content": [
        {"type": "text", "text": server.REF_IMAGE_PLACEHOLDER},
        {"type": "text", "text": text + LOCAL_COMPOSER}]}


class CapturedPromptPlaceholderTests(unittest.TestCase):
    def test_an_accept_turn_walks_back_past_the_placeholder(self):
        # the leak itself: today this returns "[reference image] " + PROMPT
        convo = [substituted_turn(PROMPT),
                 {"role": "user", "content":
                  "[SYSTEM: the server queued that prompt as job 72b185a2 "
                  "(identity_edit) - no reply needed.]"}]
        self.assertEqual(server.captured_prompt(convo, "go"), PROMPT)

    def test_a_direct_turn_returns_the_typed_words_untouched(self):
        convo = [substituted_turn(PROMPT)]
        typed = "a silver fox in the rain, neon reflections on wet asphalt"
        self.assertEqual(server.captured_prompt(convo, typed), typed)

    def test_every_placeholder_part_is_skipped(self):
        convo = [{"role": "user", "content": [
            {"type": "text", "text": server.REF_IMAGE_PLACEHOLDER},
            {"type": "text", "text": server.REF_IMAGE_PLACEHOLDER},
            {"type": "text", "text": PROMPT + LOCAL_COMPOSER}]}]
        self.assertEqual(server.captured_prompt(convo, "go"), PROMPT)

    def test_an_unsubstituted_image_part_was_already_excluded(self):
        # the live-turn shape (image still image_url) must stay byte-identical
        convo = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            {"type": "text", "text": PROMPT}]}]
        self.assertEqual(server.captured_prompt(convo, "go"), PROMPT)

    def test_a_brain_folded_token_is_stripped_from_the_head(self):
        # the token folded into a text part's head, walk-back and current turn
        convo = [{"role": "user", "content": [
            {"type": "text", "text": "[reference image] " + PROMPT}]}]
        self.assertEqual(server.captured_prompt(convo, "go"), PROMPT)
        self.assertEqual(
            server.captured_prompt([], "[reference image] " + PROMPT), PROMPT)
        # repeated tokens collapse too
        self.assertEqual(
            server.captured_prompt([], "[reference image] [reference image] go"),
            "go")

    def test_a_placeholder_alone_is_not_a_prompt(self):
        # before the fix this returned "[reference image]" AS the scene
        self.assertEqual(server.captured_prompt([], "[reference image]"), "")

    def test_a_poisoned_accept_turn_does_not_win_the_walk_back(self):
        # Second-order poisoning: once a "go" turn with an attached ref is
        # itself substituted, its joined body is "[reference image] go" -
        # not command-shaped (the bracket defeats both anchored regexes), so
        # today it becomes the captured prompt for every later accept turn.
        convo = [substituted_turn(PROMPT),
                 {"role": "user", "content":
                  "[SYSTEM: the server queued that prompt as job 72b185a2 "
                  "(identity_edit) - no reply needed.]"},
                 {"role": "user", "content": [
                     {"type": "text", "text": server.REF_IMAGE_PLACEHOLDER},
                     {"type": "text", "text": "go" + LOCAL_COMPOSER}]}]
        self.assertEqual(server.captured_prompt(convo, "show me"), PROMPT)

    def test_a_mid_body_token_is_left_for_the_gate(self):
        # head-strip only: anything else is the machinery gate's job (below)
        body = PROMPT + " [reference image]"
        self.assertEqual(server.captured_prompt([], body), body)

    def test_text_only_convo_is_byte_identical_to_before(self):
        convo = [{"role": "user", "content": "a red fox in snow"},
                 {"role": "assistant", "content": "On the way."},
                 {"role": "user", "content":
                  "[SYSTEM: the server queued that prompt as job 8bbda870 "
                  "(realism) - no reply needed.]"}]
        self.assertEqual(server.captured_prompt(convo, "go"), "a red fox in snow")
        self.assertEqual(server.captured_prompt(convo, "a silver fox in rain"),
                         "a silver fox in rain")
        self.assertEqual(server.captured_prompt([], "go"), "go")


class SceneGatePlaceholderTests(unittest.TestCase):
    def test_a_scene_beginning_with_the_placeholder_is_refused(self):
        for template in ("realism", "identity_edit"):
            with self.subTest(template=template):
                _, err = server.scene_gate(
                    template, "[reference image] " + PROMPT, verbatim=True)
                self.assertIsNotNone(err)
                self.assertIn("server machinery", err)

    def test_the_placeholder_alone_is_refused_verbatim(self):
        # the accept-turn-renders-the-placeholder-alone backstop
        _, err = server.scene_gate("realism", "[reference image]", verbatim=True)
        self.assertIsNotNone(err)
        self.assertIn("server machinery", err)

    def test_scrub_mode_does_not_rescue_it(self):
        # _strip_history_directives does not know the token (right - it is not
        # a directive), so the machinery check is what refuses it there too
        _, err = server.scene_gate("realism", "[reference image] " + PROMPT)
        self.assertIsNotNone(err)
        self.assertIn("server machinery", err)

    def test_a_mid_scene_token_is_refused_as_machinery(self):
        _, err = server.scene_gate(
            "realism", PROMPT + " [reference image]", verbatim=True)
        self.assertIsNotNone(err)

    def test_the_users_own_words_still_pass_untouched(self):
        clean, err = server.scene_gate("identity_edit", PROMPT, verbatim=True)
        self.assertEqual((clean, err), (PROMPT, None))


class BuildDirectiveEnhanceOffTests(unittest.TestCase):
    def test_no_anchor_identity_vision_ref_when_enhance_off_cloud(self):
        opts = {"engine": "fantasy", "character": "hero", "prompt_enhance": False}
        with identity_anchor():
            d, vision = server.build_directive(opts, local=False)
        self.assertEqual(vision, [])
        self.assertNotIn("PERSON REFERENCE", d)
        # the character is still USED - the identity graph's own directive text
        self.assertIn("character='hero'", d)

    def test_no_anchor_identity_vision_ref_when_enhance_off_local(self):
        # mmproj present is the whole point: the attach condition holds and
        # the enhance-off suppression must still win
        opts = {"character": "hero", "prompt_enhance": False}
        with identity_anchor(), \
             patch.object(server, "load_config",
                          return_value={"llm": {"local_model": "g.gguf"}}), \
             patch.object(server, "_local_llm_mmproj", return_value="mmproj.gguf"):
            d, vision = server.build_directive(opts, local=True)
        self.assertEqual(vision, [])
        self.assertNotIn("ATTACHED IMAGES", d)

    def test_anchor_identity_ref_never_attaches_in_either_mode(self):
        # 2026-08-27: an anchor's photo is never a chat vision image - enhance
        # on or off - so the brain cannot describe its background or garment.
        for opts in ({"engine": "fantasy", "character": "hero"},
                     {"engine": "fantasy", "character": "hero", "prompt_enhance": True}):
            with self.subTest(opts=opts), identity_anchor():
                d, vision = server.build_directive(opts, local=False)
            self.assertEqual(vision, [])
            self.assertNotIn("PERSON REFERENCE", d)

    def test_a_user_attached_identity_ref_keeps_attaching_when_enhance_off(self):
        opts = {"engine": "fantasy", "prompt_enhance": False,
                "refs": [{"kind": "identity", "file": "her.png"}]}
        d, vision = server.build_directive(opts, local=False)
        self.assertEqual(vision, [{"kind": "identity", "file": "her.png"}])
        with patch.object(server, "load_config",
                          return_value={"llm": {"local_model": "g.gguf"}}), \
             patch.object(server, "_local_llm_mmproj", return_value="mmproj.gguf"):
            d, vision = server.build_directive(dict(opts), local=True)
        self.assertEqual(vision, [{"kind": "identity", "file": "her.png"}])


class EnhanceOffEndToEndTests(unittest.IsolatedAsyncioTestCase):
    @contextmanager
    def _patched(self, submit_result):
        """The turn harness: local lane, no mmproj loaded at runtime (so
        has_vision_refs can only come from a chat-turn image part), a brain
        that fails loudly if an enhance-off render turn calls it, and a
        captured submit."""
        cfg = {"llm": {"base_url": server.LOCAL_LLM_URL, "model": "local",
                       "local_model": "g.gguf"},
               "explicit": "auto"}
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "_llm_state", return_value={}), \
             patch.object(server, "llm_call", AsyncMock(
                 side_effect=AssertionError(
                     "brain called on a prompt-enhance-off render turn"))) as llm, \
             patch.object(server.HUB, "submit",
                          AsyncMock(return_value=submit_result)) as submit, \
             patch.object(server.HUB, "broadcast"):
            yield llm, submit

    async def test_enhance_off_with_anchor_never_calls_the_brain(self):
        """The contract, end to end at the _kimi_reply seam: with enhance off
        and a character anchor, build_directive attaches no identity vision
        ref and the direct-render path sends the typed words as the scene."""
        opts = {"prompt_enhance": False, "character": "hero"}
        with identity_anchor(), \
             self._patched({"id": "job962", "error": None, "seed": 42}) as (llm, submit), \
             patch.object(server, "_local_llm_mmproj", return_value="mmproj.gguf"):
            directive, vision = server.build_directive(dict(opts), local=True)
            self.assertEqual(vision, [])
            # what chat() builds when build_directive attaches nothing
            user_msg = {"role": "user", "content": [
                {"type": "text", "text": PROMPT + directive}]}
            await server._kimi_reply("chat962-direct", user_msg, [], opts=opts)

        llm.assert_not_awaited()
        submit.assert_awaited_once()
        self.assertEqual(submit.await_args.args[2], "identity_edit")
        self.assertEqual(submit.await_args.args[3], PROMPT)
        self.assertTrue(submit.await_args.kwargs["verbatim"])

    async def test_an_accept_turn_queues_the_users_words_not_the_placeholder(self):
        """The reproduction fixture, chat 7d77102e's convo shape: the last
        prompt turn is list content with the image part already substituted,
        the user answers the pending scene with "go" - today the queued scene
        opens with "[reference image] ". It must be the user's words exactly."""
        convo = [substituted_turn(PROMPT),
                 # the pending scene the "go" accepts (the local writer prints
                 # scenes as chat; >= 30 words, no question mark)
                 {"role": "assistant", "content": "Here is the shot: " + PROMPT}]
        with identity_anchor(), \
             self._patched({"id": "job963", "error": None, "seed": 43}) as (llm, submit):
            await server._kimi_reply(
                "chat962-accept", {"role": "user", "content": "go"}, convo,
                opts={"prompt_enhance": False, "character": "hero"})

        llm.assert_not_awaited()
        submit.assert_awaited_once()
        scene = submit.await_args.args[3]
        self.assertEqual(scene, PROMPT)
        self.assertNotIn(server.REF_IMAGE_PLACEHOLDER, scene)
        self.assertTrue(submit.await_args.kwargs["verbatim"])

    async def test_the_substitution_loop_uses_the_constant(self):
        convo = [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,AA=="}},
            {"type": "text", "text": "an earlier prompt with a photo attached."}]}]
        with identity_anchor(), \
             self._patched({"id": "job964", "error": None, "seed": 44}) as (llm, submit):
            await server._kimi_reply(
                "chat962-subst", {"role": "user", "content": PROMPT}, convo,
                opts={"prompt_enhance": False, "character": "hero"})

        submit.assert_awaited_once()
        self.assertEqual(convo[0]["content"][0],
                         {"type": "text", "text": server.REF_IMAGE_PLACEHOLDER})


if __name__ == "__main__":
    unittest.main()
