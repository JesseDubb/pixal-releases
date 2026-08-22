"""Brief 9.9 - the H3 trained slots stop carrying constants.

Two slots in H3's trained prompt format were being filled with a constant
instead of the truth: the beat after a closing </d> (nothing shipped, 77% of
measured briefs) and the style declaration (live-action even for Anima/anime
sources, 92%). These tests run the sanctioned simulation: fixed brief strings
through the repair/lint functions and a stubbed brain. No generation, no
ComfyUI, no GPU - a render may be live on the card.
"""
import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock, patch


_SPEC = spec_from_file_location(
    "pixal_server_h3_slots", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def brief_with_desc(desc, trailing_fields=True):
    """An assembled H3 prompt carrying `desc` as its description field."""
    body = f"integrated_multimodal_description: [Shot 1] {desc}"
    if trailing_fields:
        body += ("\n\noverall_soundscape: The hum of the coolers.\n\n"
                 "non_diegetic_music: N/A")
    return server.H3_I2VA_HEADER + "\n\n" + body


HANGING = brief_with_desc(
    "Live-action, natural real-time motion — the clerk looks up from the "
    "register. (S1) says: <d>[English] Do not watch</d>")
CLOSED = brief_with_desc(
    "Live-action, natural real-time motion — the clerk looks up from the "
    "register. (S1) says: <d>[English] Do not watch</d> Her lips close and "
    "she turns back to the shelf.")


def llm_reply(text):
    return (200, {"choices": [{"message": {"content": text}}]})


class HangingDialogueDetectionTests(unittest.TestCase):
    """Accept 2: detection is a pure function over a brief string."""

    def test_a_tag_that_ends_the_field_is_detected(self):
        self.assertTrue(server.h3_hanging_dialogue(HANGING))

    def test_a_tag_that_ends_the_whole_brief_is_detected(self):
        self.assertTrue(server.h3_hanging_dialogue(
            brief_with_desc("(S1) says: <d>[English] Stay back</d>",
                            trailing_fields=False)))

    def test_an_action_beat_after_the_tag_is_not_touched(self):
        # the closer already shipped; appending a second one would double it
        self.assertFalse(server.h3_hanging_dialogue(CLOSED))

    def test_only_the_last_of_several_lines_can_hang(self):
        two_lines = brief_with_desc(
            "Live-action, natural real-time motion — (S1) says: "
            "<d>[English] Stay back</d> She edges toward the door, and his "
            "mouth shuts. (S2) says: <d>[English] I mean it</d>")
        self.assertTrue(server.h3_hanging_dialogue(two_lines))
        both_closed = brief_with_desc(
            "Live-action, natural real-time motion — (S1) says: "
            "<d>[English] Stay back</d> Her lips press shut. (S2) says: "
            "<d>[English] I mean it</d> He exhales and lowers the flashlight.")
        # fixed during implementation: this asserted two_lines a second time,
        # so the both-closed case was never actually checked
        self.assertFalse(server.h3_hanging_dialogue(both_closed))

    def test_a_brief_without_dialogue_is_not_detected(self):
        self.assertFalse(server.h3_hanging_dialogue(brief_with_desc(
            "Live-action, natural real-time motion — she crosses the room.")))


class ClosingBeatValidatorTests(unittest.TestCase):
    """Accept 3: the deterministic gate the brain's one clause must pass."""

    def test_a_plain_one_clause_beat_is_accepted(self):
        self.assertTrue(server.h3_closing_beat_ok(
            "Her lips close as she turns back to the shelf."))
        self.assertTrue(server.h3_closing_beat_ok(
            "His mouth shuts"))                    # no terminal period needed

    def test_empty_is_rejected(self):
        self.assertFalse(server.h3_closing_beat_ok(""))
        self.assertFalse(server.h3_closing_beat_ok("   \n  "))
        self.assertFalse(server.h3_closing_beat_ok(None))

    def test_over_the_word_cap_is_rejected(self):
        fourteen = " ".join(["word"] * 14)
        fifteen = " ".join(["word"] * 15)
        self.assertTrue(server.h3_closing_beat_ok(fourteen))
        self.assertFalse(server.h3_closing_beat_ok(fifteen))

    def test_tags_brackets_and_quotes_are_rejected(self):
        for bad in ("Her lips close <d>", "</d> she stops",
                    "She says [English] nothing", "a ] bracket",
                    'She whispers "done"', "She whispers “done”",
                    "She whispers done”"):
            with self.subTest(bad=bad):
                self.assertFalse(server.h3_closing_beat_ok(bad))

    def test_a_speaker_cue_is_rejected(self):
        self.assertFalse(server.h3_closing_beat_ok("(S1) stops talking"))
        self.assertFalse(server.h3_closing_beat_ok("(S2)'s mouth shuts"))

    def test_more_than_one_sentence_is_rejected(self):
        self.assertFalse(server.h3_closing_beat_ok(
            "Her lips close. She turns away."))
        self.assertFalse(server.h3_closing_beat_ok(
            "Her lips close.\nShe turns away"))
        self.assertFalse(server.h3_closing_beat_ok("Is she done?"))
        self.assertFalse(server.h3_closing_beat_ok("Finally!"))
        # a non-terminal period is a second sentence trying to hide
        self.assertFalse(server.h3_closing_beat_ok("Dr. Reyes stops talking"))


class ClosingBeatRepairTests(unittest.TestCase):
    """Accept 3: one async wrapper around one brain call, fallback on any
    failure, never a retry. The brain returns ONLY the beat - a whole-brief
    echo is just another failed validation."""

    def repair(self, brief, stub):
        with patch.object(server, "llm_call", stub):
            return asyncio.run(server.repair_h3_hanging_dialogue(brief, "cid9"))

    def test_an_accepted_beat_is_appended_where_the_field_ends(self):
        beat = "Her lips close as she turns back to the shelf."
        stub = AsyncMock(return_value=llm_reply(beat))
        out = self.repair(HANGING, stub)
        self.assertIn(f"</d> {beat}", out)
        # the beat lands inside the description field, before the next header
        self.assertLess(out.index(f"</d> {beat}"), out.index("overall_soundscape:"))
        stub.assert_awaited_once()

    def test_the_append_is_byte_deterministic(self):
        # Accept 3b: same brief + same beat -> byte-identical output, and the
        # input is reconstructible from the output by removing one clause.
        beat = "Her lips close as she turns back to the shelf."
        stub = AsyncMock(return_value=llm_reply(beat))
        first = self.repair(HANGING, AsyncMock(return_value=llm_reply(beat)))
        second = self.repair(HANGING, AsyncMock(return_value=llm_reply(beat)))
        self.assertEqual(first, second)
        i = first.index(f"</d> {beat}")
        reconstructed = first[:i + 4] + first[i + 4 + len(" " + beat):]
        self.assertEqual(reconstructed, HANGING)

    def test_a_whole_brief_echo_is_rejected(self):
        # asked for hundreds of tokens a small brain paraphrases; the contract
        # is one clause, so an echo fails validation and the closer falls back
        stub = AsyncMock(return_value=llm_reply(HANGING))
        out = self.repair(HANGING, stub)
        self.assertIn(f"</d> {server.H3_NEUTRAL_CLOSER}", out)
        stub.assert_awaited_once()

    def test_rejected_replies_fall_back_to_the_neutral_closer(self):
        bad_replies = [
            "",                                   # empty
            " ".join(["word"] * 20),              # over the cap
            "Her lips close <d>[English]",        # tag syntax
            'She says "done"',                    # a quote character
            "(S1) stops talking",                 # a speaker cue
            "Her lips close. She turns away.",    # two sentences
        ]
        for bad in bad_replies:
            with self.subTest(bad=bad):
                stub = AsyncMock(return_value=llm_reply(bad))
                out = self.repair(HANGING, stub)
                self.assertIn(f"</d> {server.H3_NEUTRAL_CLOSER}", out)
                stub.assert_awaited_once()        # never a retry

    def test_a_brain_exception_falls_back_without_retrying(self):
        stub = AsyncMock(side_effect=RuntimeError("brain fell over"))
        out = self.repair(HANGING, stub)
        self.assertIn(f"</d> {server.H3_NEUTRAL_CLOSER}", out)
        stub.assert_awaited_once()

    def test_a_stalled_brain_falls_back_at_the_budget(self):
        async def slow(_messages, timeout=None, cid=None):
            await asyncio.sleep(30)
            return llm_reply("Her lips close.")
        with patch.object(server, "H3_CLOSER_TIMEOUT", 0.05):
            out = self.repair(HANGING, slow)
        self.assertIn(f"</d> {server.H3_NEUTRAL_CLOSER}", out)

    def test_an_unavailable_brain_falls_back(self):
        # llm_call's own contract for a brain that is not there
        stub = AsyncMock(return_value=(0, {"error": "no local brain"}))
        out = self.repair(HANGING, stub)
        self.assertIn(f"</d> {server.H3_NEUTRAL_CLOSER}", out)
        stub.assert_awaited_once()

    def test_a_brain_returning_nothing_falls_back(self):
        stub = AsyncMock(return_value=None)
        out = self.repair(HANGING, stub)
        self.assertIn(f"</d> {server.H3_NEUTRAL_CLOSER}", out)
        stub.assert_awaited_once()

    def test_a_closed_line_never_calls_the_brain(self):
        stub = AsyncMock(return_value=llm_reply("Her lips close."))
        out = self.repair(CLOSED, stub)
        self.assertEqual(out, CLOSED)
        stub.assert_not_awaited()


class LanguageTokenTests(unittest.TestCase):
    """Accept 4: the language token map is closed - the two tokens history
    has ever produced, and everything else passes through."""

    def test_en_normalizes_to_english(self):
        out = server.repair_h3_dialogue_tags("(S1) says: <d>[EN] Whoa</d>")
        self.assertIn("<d>[English] Whoa</d>", out)

    def test_an_already_correct_tag_is_untouched(self):
        body = "(S1) says: <d>[English] Whoa</d> She grins."
        self.assertEqual(server.repair_h3_dialogue_tags(body), body)

    def test_an_unknown_code_passes_through(self):
        body = "(S1) says: <d>[Klingon] Qapla’</d>"
        self.assertEqual(server.repair_h3_dialogue_tags(body), body)


class InTagProseTests(unittest.TestCase):
    """Accept 5: delivery prose stranded INSIDE the tag relocates before it;
    the signature is closed and ambiguous cases are left alone."""

    def test_delivery_prose_moves_before_the_tag_and_survives(self):
        # the real shipped instance, history.jsonl b63b6345
        out = server.repair_h3_dialogue_tags(
            "(S1) says: <d>[English] Do not watch,” she mutters, eyes "
            "flicking to the label.</d>")
        self.assertIn(
            "she mutters, eyes flicking to the label. "
            "<d>[English] Do not watch</d>", out)
        self.assertNotIn("”", out)            # the orphan quote is dropped

    def test_the_straight_quote_comma_after_variant_relocates(self):
        out = server.repair_h3_dialogue_tags(
            "(S1) says: <d>[English] Do not watch\", she mutters.</d>")
        self.assertIn("she mutters. <d>[English] Do not watch</d>", out)

    def test_legitimate_quoted_dialogue_survives_untouched(self):
        # balanced quotes inside the tag - history.jsonl 9d61e3ee's shape
        for body in (
                "(S1) says: <d>[English] “Whoa, I’m doing this for the "
                "camera... again.”</d> She grins.",
                "(S1) says: <d>[English] He called it “the usual place” and "
                "smiled</d>"):
            with self.subTest(body=body):
                self.assertEqual(server.repair_h3_dialogue_tags(body), body)

    def test_an_orphan_quote_without_the_full_signature_is_left_alone(self):
        # no comma beside the quote, and a verb off the closed list: both
        # ambiguous, both untouched
        for body in (
                "(S1) says: <d>[English] Do not watch” she mutters</d>",
                "(S1) says: <d>[English] Do not watch,” she giggles</d>"):
            with self.subTest(body=body):
                self.assertEqual(server.repair_h3_dialogue_tags(body), body)


class StyleDeclarationTests(unittest.TestCase):
    """Accept 6: the style slot comes from the source still's provenance.
    The map is closed and keyed on the recipe id: anima (family anima) and
    anime (Z-Image's clear anime, family zimage beside photoreal recipes)."""

    LIVE = ("Live-action, natural real-time motion — the clerk looks up "
            "from the register.")

    def splice(self, entry, desc=None):
        prompt = brief_with_desc(desc or self.LIVE)
        return server.h3_style_splice(prompt, server.h3_style_for_entry(entry))

    def test_an_anima_source_declares_2d_animated(self):
        out = self.splice({"template": "anima",
                           "info": {"model_family": "anima"}})
        self.assertIn("2D-animated, natural real-time motion", out)
        self.assertNotIn("Live-action", out)

    def test_an_anime_source_declares_2d_animated(self):
        # family alone would miss this: anime sits inside zimage beside two
        # photoreal recipes, so the recipe id is the key
        out = self.splice({"template": "anime",
                           "info": {"model_family": "zimage"}})
        self.assertIn("2D-animated, natural real-time motion", out)

    def test_a_realism_source_keeps_live_action(self):
        out = self.splice({"template": "realism",
                           "info": {"model_family": "krea2"}})
        self.assertIn("Live-action, natural real-time motion", out)

    def test_unknown_provenance_keeps_live_action(self):
        for entry in ({"template": "upscale_image", "info": {}},
                      {"template": "zimage", "info": {"model_family": "zimage"}},
                      {"id": "x"}, None):
            with self.subTest(entry=entry):
                self.assertIn("Live-action, natural real-time motion",
                              self.splice(entry))

    def test_a_missing_model_family_falls_back_to_the_recipe(self):
        # entries written before model_family was recorded: history has one
        # anime render exactly like this (47ada62b)
        out = self.splice({"template": "anime", "info": {}})
        self.assertIn("2D-animated, natural real-time motion", out)

    def test_the_tempo_clause_is_byte_identical_in_every_case(self):
        for entry in ({"template": "anime", "info": {"model_family": "zimage"}},
                      {"template": "realism", "info": {"model_family": "krea2"}},
                      None):
            with self.subTest(entry=entry):
                out = self.splice(entry)
                self.assertIn("natural real-time motion", out)
                # the only allowed change is the opening style token itself
                self.assertEqual(out.replace("2D-animated", "Live-action", 1),
                                 brief_with_desc(self.LIVE))

    def test_the_lowercase_anchor_splices_too(self):
        # the OUTPUT FORMAT's own example is lowercase; sentence-initial
        # history capitalizes it. Both are the same slot.
        out = self.splice({"template": "anima",
                           "info": {"model_family": "anima"}},
                          desc=("live-action, natural real-time motion — "
                                "she looks up."))
        self.assertIn("live-action", brief_with_desc(
            "live-action, natural real-time motion — she looks up."))
        self.assertTrue(out.startswith(
            server.H3_I2VA_HEADER + "\n\nintegrated_multimodal_description: "
            "[Shot 1] 2D-animated, natural real-time motion"))

    def test_a_live_action_mention_off_the_opening_slot_is_not_spliced(self):
        desc = ("The tape plays on. A caption reads live-action, natural "
                "real-time motion as she watches.")
        out = self.splice({"template": "anima",
                           "info": {"model_family": "anima"}}, desc=desc)
        self.assertEqual(out, brief_with_desc(desc))


if __name__ == "__main__":
    unittest.main()
