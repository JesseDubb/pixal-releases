"""Brief 9.38 - dialogue tags vs quotes, and a same-seed A/B switch.

The opening blip (MiniMaxAI/MiniMax-H3 discussion #76): a ~0.5 s blip of
unintelligible speech at the very start of some H3 clips, seed-dependent.
The community workaround writes the spoken line in plain quotes instead of
the trained <d>[Lang] ...</d> tags - and repair_h3_dialogue_tags normalised
every line INTO tags, so the workaround was unreachable. video.h3_dialogue_tags
("tags" | "quotes") makes it a standing choice, surfaced in Settings ->
Video; /api/animate gains an optional seed (validated like held_seed) so the
A/B runs same-seed. The measured A/B (2026-08-25: the d400350d brief, 6 seeds
x both formats, then a merged settle-beat opening on 2 seeds) went to quotes
- the same opening still blipped under tags - so quotes is the default, the
spelling is `(S1) says "..."` (no colon, the #76 shape), and it is applied
LAST by h3_spell_dialogue so every tag-keyed repair upstream keeps working.

Also pinned here: the 9.37 live-clip defect - `she says: "line" (S1) says:
<d>[Lang] line</d>` shipped the spoken words TWICE. A quoted line beside the
tag is REPLACED by the chosen form, never left beside it - and the prose
"says" left in front of the cue goes too, because the A/B's quotes arm read
"She says: (S1) says" aloud as "I says".

Same sanctioned simulation as 9.9/9.37: fixed strings and stubbed handlers -
no generation, no ComfyUI, no GPU.
"""
import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch


_SPEC = spec_from_file_location(
    "pixal_server_h3_dialogue_tags",
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


class DialogueTagsSwitchTests(unittest.TestCase):
    """video.h3_dialogue_tags round-trips through /api/settings like the
    other video defaults (same harness as VideoUpscale2xDefaultTests)."""

    def _full_cfg(self, video):
        return {"llm": {"base_url": "", "model": ""},
                "critic": {"model": ""}, "upscale": {}, "edit": {}, "vae": {},
                "pid": {}, "video": video, "extra_model_roots": [],
                "comfy_editor": False, "comfy_console": "tui",
                "explicit": "auto", "vram_profile": "auto"}

    def test_settings_post_rejects_an_unknown_format(self):
        for bad in ("angle brackets", "", True, 1, None, ["tags"]):
            with self.subTest(bad=bad):
                saved = []
                with patch.object(server, "load_config",
                                  return_value=self._full_cfg(
                                      {"default_engine": "",
                                       "default_model": ""})), \
                     patch.object(server, "model_catalog", return_value=[]), \
                     patch.object(server, "save_config",
                                  side_effect=lambda cfg: saved.append(cfg)):
                    response = asyncio.run(server.settings_post(
                        FakeRequest({"video": {"h3_dialogue_tags": bad}})))
                self.assertEqual(response.status, 400)
                self.assertEqual(
                    json.loads(response.text),
                    {"ok": False, "error": f"not one of tags|quotes: {bad}"})
                self.assertEqual(saved, [])  # a rejected write never touches config

    def test_settings_round_trip_exposes_the_format(self):
        cfg = self._full_cfg({"default_engine": "", "default_model": ""})
        saved = []
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "_video_asset", side_effect=all_video_assets), \
             patch.object(server, "h3_upscale_available", return_value=True), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()), \
             patch.object(server, "save_config",
                          side_effect=lambda c: saved.append(c)):
            post = asyncio.run(server.settings_post(
                FakeRequest({"video": {"h3_dialogue_tags": "quotes"}})))
            self.assertEqual(post.status, 200)
            self.assertEqual(json.loads(post.text), {"ok": True})
            response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        video = json.loads(response.text)["video"]
        self.assertEqual(video["h3_dialogue_tags"], "quotes")
        self.assertEqual(saved[0]["video"]["h3_dialogue_tags"], "quotes")

    def test_settings_get_defaults_to_quotes(self):
        # an old config predating the key still publishes the trained form
        cfg = self._full_cfg({"default_engine": "", "default_model": ""})
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "_video_asset", side_effect=all_video_assets), \
             patch.object(server, "h3_upscale_available", return_value=True), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()):
            response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text)["video"]["h3_dialogue_tags"],
                         "quotes")

    def test_load_config_carries_the_default(self):
        # a fresh install: no config.json at all
        with TemporaryDirectory() as td, \
             patch.object(server, "CONFIG", Path(td) / "config.json"):
            self.assertEqual(
                server.load_config()["video"].get("h3_dialogue_tags", "tags"),
                "quotes")


class QuotesModeTests(unittest.TestCase):
    """The normaliser emits the trained <d>[Lang] ...</d> in tags mode and
    plain quotes in quotes mode - on the SAME input."""

    def test_tags_mode_wraps_a_plain_quote(self):
        out = server.repair_h3_dialogue_tags(
            "(S1) says: “Gotcha,” — lips part mid-sentence.")
        self.assertIn("says: <d>[English] Gotcha</d>", out)

    def test_quotes_mode_emits_plain_quotes_on_the_same_input(self):
        out = server.repair_h3_dialogue_tags(
            "(S1) says: “Gotcha,” — lips part mid-sentence.",
            dialogue_tags="quotes")
        self.assertIn("(S1) says \"Gotcha\"", out)
        self.assertNotIn("<d>", out)
        self.assertNotIn("[English]", out)
        self.assertIn("lips part mid-sentence", out)   # prose survives

    def test_quotes_mode_converts_a_proper_tag_and_drops_the_language(self):
        out = server.repair_h3_dialogue_tags(
            "(S1) says: <d>[English] Whoa</d> She grins.",
            dialogue_tags="quotes")
        self.assertEqual(out, "(S1) says \"Whoa\" She grins.")

    def test_the_normaliser_is_canonical_whatever_the_switch_says(self):
        # the tag-keyed repairs downstream (9.9, 9.37) must still see </d>
        body = "(S1) says: <d>[English] Whoa</d>"
        with patch.object(server, "load_config",
                          return_value={"video": {"h3_dialogue_tags": "quotes"}}):
            self.assertEqual(server.repair_h3_dialogue_tags(body), body)

    def test_the_switch_is_read_from_config_by_the_spelling_pass(self):
        body = "(S1) says: <d>[English] Whoa</d>"
        with patch.object(server, "load_config",
                          return_value={"video": {"h3_dialogue_tags": "quotes"}}):
            self.assertEqual(server.h3_spell_dialogue(body),
                             "(S1) says \"Whoa\"")
        with patch.object(server, "load_config",
                          return_value={"video": {"h3_dialogue_tags": "tags"}}):
            self.assertEqual(server.h3_spell_dialogue(body), body)

    def test_an_unknown_or_missing_config_value_is_quotes(self):
        body = "(S1) says: <d>[English] Whoa</d>"
        for video in ({}, {"h3_dialogue_tags": "angle brackets"}):
            with self.subTest(video=video):
                with patch.object(server, "load_config",
                                  return_value={"video": video}):
                    self.assertEqual(server.h3_spell_dialogue(body),
                                     "(S1) says \"Whoa\"")

    def test_assemble_h3_prompt_keeps_the_canonical_tags_for_the_repairs(self):
        # the assemblers never spell quotes: 9.9's closer and 9.37's settle
        # beat read </d>, so the spelling waits for h3_spell_dialogue, last
        brief = ("[Shot 1] She turns to the lens. "
                 "(S1) says: <d>[English] Finally found one I love.</d> "
                 "She grins.")
        with patch.object(server, "load_config",
                          return_value={"video": {"h3_dialogue_tags": "quotes"}}):
            out = server.assemble_h3_prompt(brief)
        self.assertIn("(S1) says: <d>[English] Finally found one I love.</d>",
                      out)

    def test_h3_spell_dialogue_writes_the_76_form_and_is_idempotent(self):
        text = ("lips closed, she settles for a beat, then (S1) says: "
                "<d>[English] Finally found one I love.</d> After the line, "
                "her lips close.")
        want = ("lips closed, she settles for a beat, then (S1) says "
                "\"Finally found one I love.\" After the line, her lips close.")
        out = server.h3_spell_dialogue(text, "quotes")
        self.assertEqual(out, want)
        self.assertEqual(server.h3_spell_dialogue(out, "quotes"), want)
        self.assertEqual(server.h3_spell_dialogue(text, "tags"), text)
        # a bare tag with no cue still loses its syntax
        self.assertEqual(server.h3_spell_dialogue("<d>[English] Hi.</d>",
                                                  "quotes"), "\"Hi.\"")
        self.assertNotIn("<d>", out)


class DoubledLineTests(unittest.TestCase):
    """The 9.37 live-clip defect: `she says: "line" (S1) says: <d>line</d>`
    shipped the line twice. The quoted copy is replaced by the chosen form,
    in either mode; a mismatched pair is a real quote and survives."""

    DOUBLED = ("a breath escapes her, then she says: "
               "“I finally found one I actually love” "
               "(S1) says: <d>[English] I finally found one I actually love.</d>")

    def test_tags_mode_collapses_the_quoted_copy(self):
        out = server.repair_h3_dialogue_tags(self.DOUBLED)
        self.assertEqual(out.count("I finally found one I actually love"), 1)
        self.assertIn(
            "a breath escapes her, then (S1) says: <d>[English] "
            "I finally found one I actually love.</d>", out)
        self.assertNotIn("“I finally", out)
        self.assertNotIn("she says", out)

    def test_the_line_quoted_elsewhere_in_the_prose_dissolves(self):
        # seed 4004, 2026-08-25: the director narrated the line in the action
        # prose three sentences before the cue - two spoken copies again
        body = ("She leans forward slightly, mouth opens fully to say "
                "\u201cFinally found a jacket I actually love.\u201d \u2014 [0-3s] "
                "her gaze locks with the lens, lips parting for \u201clove\u201d "
                "\u2014 [3-5s] eyes blink once as \u201cactually\u201d emerges. "
                "(S1) says: <d>[English] Finally found a jacket I actually love.</d> "
                "Lips close softly.")
        out = server.repair_h3_dialogue_tags(body)
        self.assertEqual(out.count("Finally found a jacket I actually love"), 1)
        self.assertIn("(S1) says: <d>[English] Finally found a jacket I actually love.</d>",
                      out)
        self.assertNotIn("to say", out)
        # single quoted words are delivery prose and survive
        self.assertIn("lips parting for \u201clove\u201d", out)
        self.assertIn("as \u201cactually\u201d emerges", out)
        # and quotes mode ships one spoken copy in the #76 form
        self.assertEqual(
            server.repair_h3_dialogue_tags(body, dialogue_tags="quotes")
                  .count("Finally found a jacket I actually love"), 1)

    def test_a_line_quoted_inside_its_own_tag_is_untouched(self):
        body = "(S1) says: <d>[English] \u201cHi there.\u201d</d> She waves."
        self.assertEqual(server.repair_h3_dialogue_tags(body), body)
        other = ("she recalls him saying \u201csomething else\u201d and grins. "
                 "(S1) says: <d>[English] Hi there.</d>")
        self.assertEqual(server.repair_h3_dialogue_tags(other), other)

    def test_a_prose_says_in_front_of_the_cue_is_dropped(self):
        # the A/B's quotes arm read "She says: (S1) says" aloud as "I says"
        self.assertEqual(
            server.repair_h3_dialogue_tags(
                "She says: (S1) says: <d>[English] Hi.</d>"),
            "(S1) says: <d>[English] Hi.</d>")
        self.assertEqual(
            server.repair_h3_dialogue_tags(
                "a breath, then she says (S1) says: <d>[English] Hi.</d>",
                dialogue_tags="quotes"),
            "a breath, then (S1) says \"Hi.\"")
        # a real quotation in between is not a doubled cue
        body = "she says: “different words entirely” (S1) says: <d>[English] Hi.</d>"
        self.assertEqual(server.repair_h3_dialogue_tags(body), body)

    def test_quotes_mode_collapses_to_one_quoted_line(self):
        out = server.repair_h3_dialogue_tags(self.DOUBLED,
                                             dialogue_tags="quotes")
        self.assertEqual(out.count("I finally found one I actually love"), 1)
        self.assertNotIn("<d>", out)

    def test_the_cued_twin_collapses_too(self):
        # the untagged-cue wrap turns `(S1) says: "line" (S1) says: <d>line</d>`
        # into two adjacent identical cue+tag blocks - still one spoken copy
        out = server.repair_h3_dialogue_tags(
            "(S1) says: “Hi.” (S1) says: <d>[English] Hi.</d>")
        self.assertEqual(out.count("Hi."), 1)

    def test_a_mismatched_pair_is_a_real_quote_and_survives(self):
        body = ("she says: “different words entirely” "
                "(S1) says: <d>[English] Hello there.</d>")
        self.assertEqual(server.repair_h3_dialogue_tags(body), body)
        self.assertEqual(
            server.repair_h3_dialogue_tags(body, dialogue_tags="quotes"),
            "she says: “different words entirely” (S1) says \"Hello there.\"")


class AnimateSeedTests(unittest.TestCase):
    """The optional seed on /api/animate: honoured when valid (the builders
    receive it through submit's args), rejected like held_seed when not."""

    def run_animate(self, root, body):
        entry = {"id": "abc123", "scene": "the subject at a workbench",
                 "images": [{"filename": "still.png", "subfolder": "",
                             "media": "image"}]}
        submit = AsyncMock(return_value={"id": "videojob", "error": None})

        async def run():
            response = await server.animate(FakeRequest(body))
            await asyncio.sleep(0)
            return response

        with patch.object(server, "CDIR", root), \
             patch.object(server, "validate_video_selection",
                          return_value=("h3", body["model"], body["seconds"],
                                        None)), \
             patch.object(server, "prepare_h3_frame",
                          return_value=("prepared.png", 1344, 768)), \
             patch.object(server, "_video_asset", side_effect=all_video_assets), \
             patch.object(server, "direct_motion",
                          AsyncMock(return_value=("She browses the stalls.",
                                                  True))), \
             patch.object(server, "repair_h3_hanging_dialogue",
                          AsyncMock(side_effect=lambda m, cid=None: m)), \
             patch.object(server, "repair_h3_speech_in_progress",
                          AsyncMock(side_effect=lambda m, cid=None: m)), \
             patch.object(server.HUB, "ledger_read", return_value=[entry]), \
             patch.object(server.HUB, "broadcast"), \
             patch.object(server.HUB, "submit", submit):
            return asyncio.run(run()), submit

    def _body(self, **kw):
        body = {"id": "abc123", "cid": "cid1", "engine": "h3",
                "model": "fl2va", "seconds": 5}
        body.update(kw)
        return body

    def test_a_valid_seed_reaches_the_builders(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "output" / "still.png").write_bytes(b"still")
            response, submit = self.run_animate(root, self._body(seed=424242))
            self.assertEqual(response.status, 200)
            self.assertEqual(submit.await_args.args[4]["seed"], 424242)

    def test_a_string_seed_is_taken_like_held_seed(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "output" / "still.png").write_bytes(b"still")
            response, submit = self.run_animate(root, self._body(seed="424242"))
            self.assertEqual(response.status, 200)
            self.assertEqual(submit.await_args.args[4]["seed"], 424242)

    def test_the_standing_format_is_spelled_last_scripts_included(self):
        # a verbatim script keeps its words; only the syntax follows the
        # switch, and after every tag-keyed repair
        script = ("she settles for a beat, then (S1) says: <d>[English] Hi.</d> "
                  "Her lips close.")
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "output" / "still.png").write_bytes(b"still")
            with patch.object(server, "h3_dialogue_tags_mode",
                              return_value="quotes"):
                response, submit = self.run_animate(
                    root, self._body(script=script))
            self.assertEqual(response.status, 200)
            motion = submit.await_args.args[3]
            self.assertIn("then (S1) says \"Hi.\" Her lips close.", motion)
            self.assertNotIn("<d>", motion)
            with patch.object(server, "h3_dialogue_tags_mode",
                              return_value="tags"):
                response, submit = self.run_animate(
                    root, self._body(script=script))
            self.assertIn("(S1) says: <d>[English] Hi.</d>",
                          submit.await_args.args[3])

    def test_an_invalid_seed_is_a_400_never_a_silent_reroll(self):
        for bad in ("banana", 0, -7, 2 ** 62, 12.5):
            with self.subTest(bad=bad):
                with TemporaryDirectory() as td:
                    root = Path(td)
                    (root / "output").mkdir()
                    (root / "output" / "still.png").write_bytes(b"still")
                    response, submit = self.run_animate(root, self._body(seed=bad))
                    self.assertEqual(response.status, 400)
                    self.assertIn("not a seed", json.loads(response.text)["error"])
                    submit.assert_not_awaited()

    def test_no_seed_draws_its_own_as_today(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "output" / "still.png").write_bytes(b"still")
            response, submit = self.run_animate(root, self._body())
            self.assertEqual(response.status, 200)
            self.assertNotIn("seed", submit.await_args.args[4])


if __name__ == "__main__":
    unittest.main()
