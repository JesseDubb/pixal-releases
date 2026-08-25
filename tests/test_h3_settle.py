"""Brief 9.37 - a settle beat before the first word.

H3 briefs kept opening with speech already in progress (ledger 3458c98e,
d400350d): the still was prompted "mid-sentence expression", so frame zero
has an open mouth and the director narrated a word mid-flight. The rule now
lives in the two directors' closing contracts; the detector and repair below
are the deterministic floor behind it. Same sanctioned simulation as 9.9:
fixed brief strings and a stubbed brain - no generation, no ComfyUI, no GPU.

Also in this brief (the Reddit addendum): the appended audio contract
carried a second, contradictory non_diegetic_music field with the wrong
token ("none." - the guide's token is N/A). The contract drops its own
field; the assembler guarantees exactly one, N/A unless the director wrote
music; and a brief with dialogue that never says the mouth stays shut gets
an after-line silence clause deterministically (unspoken seconds come back
as gibberish otherwise).
"""
import asyncio
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from PIL import Image


_SPEC = spec_from_file_location(
    "pixal_server_h3_settle", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def all_video_assets(_kind, _rel):
    return _rel


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def brief_with_desc(desc, sound="The hum of the coolers.", trailing_fields=True):
    """An assembled H3 prompt carrying `desc` as its description field."""
    body = f"integrated_multimodal_description: [Shot 1] {desc}"
    if trailing_fields:
        body += (f"\n\noverall_soundscape: {sound}\n\n"
                 "non_diegetic_music: N/A")
    return server.H3_I2VA_HEADER + "\n\n" + body


def llm_reply(text):
    return (200, {"choices": [{"message": {"content": text}}]})


# The two ledger briefs Jesse flagged (2026-08-25): H3 fl2va, 5s, source
# still 6b2f3036 ("mid-sentence expression, eyes on the lens"). Both open
# with speech already in progress.
LEDGER_FINISHES_A_WORD = (
    "For the target video, at 0.00 seconds into the target video, <Picture 1> (from "
    "[Shot 1]) is fully referenced.\n\nintegrated_multimodal_description: [Shot 1] "
    "Live-action, natural real-time motion — the woman exhales softly through her "
    "nose, lips rounding slightly as she finishes a word, then pivots her head just "
    "enough to glance right at the zipper pull where a loose strand of hair catches "
    "in her jacket’s collar before snapping back into place with a faint tug from "
    "her own movement; her left hand tightens on the phone strap while the camera "
    "holds locked and level, catching the glint of her gold hoop as sunlight shifts "
    "across her cheekbone; [0-3s] she pulls the zipper pull free with a slight jerk "
    "of her right thumb — hair flies loose for half a second before settling back "
    "— then immediately turns her gaze forward again, mouth closing mid-sentence,"
    " eyes locking on camera as if catching herself in motion. [3-5s] She lets out "
    "an almost imperceptible breath and says to the unseen listener: (S1) says: <d>[English] "
    "I finally found one I actually love.</d>, her lips parting again just enough "
    "for the word “love” before she snaps back into focus, eyes sharp but relaxed "
    "— the camera stays steady as she adjusts her jacket’s collar with a quick flick "
    "of her wrist.\n\noverall_soundscape: Soft ambient kitchen hums from behind, low "
    "murmur of distant city traffic outside the window, and the faint clink of a "
    "glass on a countertop to the left — no music. A single breath escapes through "
    "lips just before she speaks, then the sound of fabric shifting as her hand pulls "
    "at the zipper.\n\nnon_diegetic_music: N/A"
)

LEDGER_MID_SENTENCE = (
    "For the target video, at 0.00 seconds into the target video, <Picture 1> (from "
    "[Shot 1]) is fully referenced.\n\nintegrated_multimodal_description: [Shot 1] "
    "Live-action, natural real-time motion — the woman tucks her wavy dark hair behind "
    "her right ear with a quick, loose finger flick, then holds the phone steady "
    "at arm’s length as she speaks to it, lips parting mid-sentence. Her left hand "
    "remains bent and out of frame, sleeve slightly wrinkled from earlier movement;"
    " the silver phone case glints against the black bomber jacket as soft daylight "
    "slants across her cheek and shoulder. She says: (S1) says: <d>[English] Finally "
    "found a jacket I actually love.</d> — the phrase emerges in clipped, confident "
    "delivery with no pause, eyes locked on lens, mouth opening mid-word as she begins "
    "to speak; after the line, she closes lips fully, head tilting just slightly "
    "toward her right shoulder before settling. Camera holds locked and level, framing "
    "shoulders wide and face centered.\n\noverall_soundscape: Room tone hums — low "
    "ambient chatter from distant apartment neighbors, faint clink of a glass on "
    "a countertop to her left, and the quiet rustle of air as she exhales through "
    "her nose after speaking; no music plays. \n\nnon_diegetic_music: N/A"
)

SETTLE_SHE = "lips closed, she settles for a beat"
SILENCE_SHE = ("After the line, her lips close and she only listens; "
               "no further speech.")


class SpeechInProgressDetectionTests(unittest.TestCase):
    """The truth table: pure, description field only, the offending clause or
    None - the soundscape may legitimately say 'a breath before she speaks'."""

    def test_each_speech_in_progress_phrase_is_detected(self):
        cases = {
            "she turns to the lens, lips parting mid-sentence, and waves.":
                "lips parting mid-sentence",
            "her mouth opening mid-word, eyes wide.":
                "her mouth opening mid-word",
            "she exhales, finishing a word, then turns.":
                "finishing a word",
            "she nods as she finishes a word.":
                "she nods as she finishes a word",
            "the woman smiles as she begins to speak.":
                "the woman smiles as she begins to speak",
            "he glances up as he begins to speak.":
                "he glances up as he begins to speak",
            "they look over as they begin to speak.":
                "they look over as they begin to speak",
            "she answers with no pause, still smiling.":
                "she answers with no pause",
            "she is already speaking, hands busy.":
                "she is already speaking",
            "he continues speaking, leaning in.":
                "he continues speaking",
        }
        for desc, clause in cases.items():
            with self.subTest(clause=clause):
                brief = brief_with_desc(
                    "Live-action, natural real-time motion — " + desc)
                self.assertEqual(server.h3_speech_in_progress(brief), clause)

    def test_the_two_ledger_briefs_are_detected(self):
        self.assertEqual(server.h3_speech_in_progress(LEDGER_FINISHES_A_WORD),
                         "lips rounding slightly as she finishes a word")
        self.assertEqual(server.h3_speech_in_progress(LEDGER_MID_SENTENCE),
                         "lips parting mid-sentence")

    def test_the_soundscape_is_exempt(self):
        brief = brief_with_desc(
            "Live-action, natural real-time motion — she waves at the lens.",
            sound="Room tone, a breath before she speaks, then lips parting "
                  "mid-sentence.")
        self.assertIsNone(server.h3_speech_in_progress(brief))

    def test_a_says_cue_inside_the_first_sentence_is_detected(self):
        brief = brief_with_desc(
            "Live-action, natural real-time motion — She turns to the lens "
            "and (S1) says: <d>[English] Hi.</d> Her lips close and she waves.")
        self.assertEqual(server.h3_speech_in_progress(brief), "(S1) says:")

    def test_a_says_cue_after_the_first_sentence_is_clean(self):
        brief = brief_with_desc(
            "Live-action, natural real-time motion — She turns to the lens. "
            "(S1) says: <d>[English] Hi.</d> Her lips close and she waves.")
        self.assertIsNone(server.h3_speech_in_progress(brief))

    def test_a_clean_brief_is_silent(self):
        brief = brief_with_desc(
            "Live-action, natural real-time motion — she crosses the room "
            "and sits. The camera holds locked and level.")
        self.assertIsNone(server.h3_speech_in_progress(brief))

    def test_a_brief_without_a_description_field_is_silent(self):
        self.assertIsNone(server.h3_speech_in_progress("just some prose"))
        self.assertIsNone(server.h3_speech_in_progress(""))
        self.assertIsNone(server.h3_speech_in_progress(None))


class AfterLineSilenceTests(unittest.TestCase):
    """Dialogue with no stated mouth-shut for the rest of the clip: H3 fills
    the unspoken seconds with mouth noise, so the detector returns the
    sentinel and the repair appends the clause deterministically."""

    def test_dialogue_without_an_after_line_silence_clause_is_flagged(self):
        brief = brief_with_desc(
            "Live-action, natural real-time motion — she waves. "
            "(S1) says: <d>[English] Hi.</d> She grins and waves again.")
        self.assertEqual(server.h3_speech_in_progress(brief),
                         server.H3_NO_AFTER_LINE_SILENCE)

    def test_a_field_ending_on_the_tag_is_flagged_standalone(self):
        # in animate the hanging-line repair gets there first; standalone the
        # settle repair backstops the same slot
        brief = brief_with_desc(
            "Live-action, natural real-time motion — she waves. "
            "(S1) says: <d>[English] Hi.</d>")
        self.assertEqual(server.h3_speech_in_progress(brief),
                         server.H3_NO_AFTER_LINE_SILENCE)

    def test_a_stated_mouth_shut_satisfies_the_check(self):
        for beat in ("Her lips close and she turns away.",
                     "She closes lips fully, settling.",
                     "She says nothing more, watching him.",
                     "Their lips close and the speaking motion stops."):
            with self.subTest(beat=beat):
                brief = brief_with_desc(
                    "Live-action, natural real-time motion — she waves. "
                    f"(S1) says: <d>[English] Hi.</d> {beat}")
                self.assertIsNone(server.h3_speech_in_progress(brief))

    def test_no_dialogue_means_no_silence_check(self):
        brief = brief_with_desc(
            "Live-action, natural real-time motion — she waves at the lens.")
        self.assertIsNone(server.h3_speech_in_progress(brief))

    def test_the_append_never_reaches_the_brain(self):
        brief = brief_with_desc(
            "Live-action, natural real-time motion — she waves. "
            "(S1) says: <d>[English] Hi.</d> She grins and waves again.")
        stub = AsyncMock(return_value=llm_reply("anything"))
        with patch.object(server, "llm_call", stub):
            out = asyncio.run(server.repair_h3_speech_in_progress(brief, "cid9"))
        self.assertIn("She grins and waves again. " + SILENCE_SHE, out)
        self.assertIsNone(server.h3_speech_in_progress(out))
        stub.assert_not_awaited()

    def test_the_append_follows_the_briefs_own_pronoun(self):
        for desc, clause in (
                ("he waves. (S1) says: <d>[English] Hi.</d> He grins.",
                 "After the line, his lips close and he only listens; "
                 "no further speech."),
                ("the clerk waves. (S1) says: <d>[English] Hi.</d> "
                 "The clerk grins.",
                 "After the line, their lips close and they only listen; "
                 "no further speech.")):
            with self.subTest(clause=clause):
                brief = brief_with_desc(
                    "Live-action, natural real-time motion — " + desc)
                stub = AsyncMock()
                with patch.object(server, "llm_call", stub):
                    out = asyncio.run(
                        server.repair_h3_speech_in_progress(brief, "cid9"))
                self.assertIn(clause, out)
                stub.assert_not_awaited()


class SettleRepairTests(unittest.TestCase):
    """One brain call to rewrite ONLY the opening; the detector re-runs on
    the reply; any failure falls back to the deterministic rewrite. Never a
    retry."""

    FLAGGED = brief_with_desc(
        "Live-action, natural real-time motion — she is already speaking, "
        "hands busy. (S1) says: <d>[English] Hi there.</d> Her lips close "
        "and she turns away.")

    def repair(self, brief, stub):
        with patch.object(server, "llm_call", stub):
            return asyncio.run(server.repair_h3_speech_in_progress(brief, "cid9"))

    def test_a_clean_brief_never_calls_the_brain(self):
        clean = brief_with_desc(
            "Live-action, natural real-time motion — she crosses the room.")
        stub = AsyncMock(return_value=llm_reply("anything"))
        self.assertEqual(self.repair(clean, stub), clean)
        stub.assert_not_awaited()

    def test_an_accepted_rewrite_is_the_brains_text(self):
        rewritten = brief_with_desc(
            "Live-action, natural real-time motion — lips closed, she takes "
            "a breath and finds the lens. (S1) says: <d>[English] Hi there."
            "</d> Her lips close and she turns away.")
        stub = AsyncMock(return_value=llm_reply(rewritten))
        self.assertEqual(self.repair(self.FLAGGED, stub), rewritten)
        stub.assert_awaited_once()

    def test_a_still_flagged_reply_falls_back(self):
        stub = AsyncMock(return_value=llm_reply(self.FLAGGED))
        out = self.repair(self.FLAGGED, stub)
        self.assertIn(SETTLE_SHE, out)
        self.assertIsNone(server.h3_speech_in_progress(out))
        stub.assert_awaited_once()

    def test_a_reply_that_mangles_the_trailing_fields_falls_back(self):
        mangled = self.FLAGGED.replace("The hum of the coolers.",
                                       "A completely different soundscape.")
        rewritten = brief_with_desc(
            "Live-action, natural real-time motion — lips closed, she takes "
            "a breath. (S1) says: <d>[English] Hi there.</d> Her lips close "
            "and she turns away.", sound="A completely different soundscape.")
        self.assertEqual(mangled.split("overall_soundscape:")[-1],
                         rewritten.split("overall_soundscape:")[-1])
        stub = AsyncMock(return_value=llm_reply(rewritten))
        out = self.repair(self.FLAGGED, stub)
        self.assertIn(SETTLE_SHE, out)
        self.assertIn("The hum of the coolers.", out)

    def test_any_brain_failure_falls_back_without_retrying(self):
        for bad in (RuntimeError("brain fell over"), None,
                    (0, {"error": "no local brain"})):
            with self.subTest(bad=bad):
                stub = AsyncMock(return_value=bad) if not isinstance(bad, Exception) \
                    else AsyncMock(side_effect=bad)
                out = self.repair(self.FLAGGED, stub)
                self.assertIn(SETTLE_SHE, out)
                self.assertIsNone(server.h3_speech_in_progress(out))
                stub.assert_awaited_once()        # never a retry

    def test_a_stalled_brain_falls_back_at_the_budget(self):
        async def slow(_messages, timeout=None, cid=None):
            await asyncio.sleep(30)
            return llm_reply("irrelevant")
        with patch.object(server, "H3_SETTLE_TIMEOUT", 0.05):
            out = self.repair(self.FLAGGED, slow)
        self.assertIn(SETTLE_SHE, out)

    def test_the_fallback_replaces_only_the_offending_clause(self):
        stub = AsyncMock(return_value=(0, {"error": "down"}))
        out = self.repair(self.FLAGGED, stub)
        expected = self.FLAGGED.replace("she is already speaking", SETTLE_SHE)
        self.assertEqual(out, expected)

    def test_the_fallback_is_byte_deterministic(self):
        first = self.repair(self.FLAGGED, AsyncMock(return_value=None))
        second = self.repair(self.FLAGGED, AsyncMock(return_value=None))
        self.assertEqual(first, second)

    def test_the_fallback_says_case_joins_the_preamble_sentence(self):
        # 9.40: after the style preamble's em dash the clause joins the
        # sentence - lowercase, ", then ", the prose's first letter untouched
        brief = brief_with_desc(
            "Live-action, natural real-time motion — She turns to the lens "
            "and (S1) says: <d>[English] Hi.</d> Her lips close and she waves.")
        stub = AsyncMock(return_value=(0, {"error": "down"}))
        out = self.repair(brief, stub)
        expected = brief.replace(
            "motion — She turns",
            "motion — lips closed, she settles for a beat, then She turns")
        self.assertEqual(out, expected)
        self.assertIsNone(server.h3_speech_in_progress(out))

    def test_the_fallback_uses_the_briefs_own_pronoun(self):
        brief = brief_with_desc(
            "Live-action, natural real-time motion — they are already "
            "speaking, grinning at each other.")
        stub = AsyncMock(return_value=(0, {"error": "down"}))
        out = self.repair(brief, stub)
        self.assertIn("lips closed, they settle for a beat", out)

    def test_an_opening_offense_and_a_missing_silence_are_both_repaired(self):
        brief = brief_with_desc(
            "Live-action, natural real-time motion — she is already "
            "speaking, hands busy. (S1) says: <d>[English] Hi there.</d> "
            "She grins and waves.")
        stub = AsyncMock(return_value=(0, {"error": "down"}))
        out = self.repair(brief, stub)
        self.assertIn(SETTLE_SHE, out)
        self.assertIn(SILENCE_SHE, out)
        self.assertIsNone(server.h3_speech_in_progress(out))


class LedgerFallbackTests(unittest.TestCase):
    """The deterministic fallback on the two ledger briefs, pinned byte for
    byte: exactly the flagged clauses are replaced, nothing else moves."""

    def repair_down(self, brief):
        stub = AsyncMock(return_value=(0, {"error": "no local brain"}))
        with patch.object(server, "llm_call", stub):
            return asyncio.run(server.repair_h3_speech_in_progress(brief, "cid9"))

    def test_finishes_a_word_ledger_brief(self):
        out = self.repair_down(LEDGER_FINISHES_A_WORD)
        expected = (LEDGER_FINISHES_A_WORD
                    .replace("lips rounding slightly as she finishes a word",
                             SETTLE_SHE)
                    .replace("mouth closing mid-sentence", SETTLE_SHE)
                    .replace("quick flick of her wrist.\n\noverall_soundscape:",
                             "quick flick of her wrist. " + SILENCE_SHE
                             + "\n\noverall_soundscape:"))
        self.assertEqual(out, expected)
        self.assertIsNone(server.h3_speech_in_progress(out))

    def test_mid_sentence_ledger_brief(self):
        out = self.repair_down(LEDGER_MID_SENTENCE)
        expected = (LEDGER_MID_SENTENCE
                    .replace("lips parting mid-sentence", SETTLE_SHE)
                    .replace("confident delivery with no pause", SETTLE_SHE)
                    .replace("mouth opening mid-word as she begins to speak",
                             SETTLE_SHE))
        self.assertEqual(out, expected)
        self.assertIsNone(server.h3_speech_in_progress(out))
        # this brief already closes the line ("she closes lips fully"), so
        # no silence clause is appended
        self.assertNotIn("After the line", out)


class SettleJoinRuleTests(unittest.TestCase):
    """9.40: the says-case insertion joins the sentence it lands in. After
    the style preamble's em dash (or a , ; :) the clause goes in lowercase
    with ", then " and the prose's first letter is never touched; only a
    true sentence start (field start, after . ! ?, or right after the
    [Shot 1] marker with no preamble) gets the capitalised sentence form."""

    # The elevator brief from the 9.40 brief file, reconstructed pre-repair:
    # the live 09:45 defect was the floor prepending "Lips closed, he
    # settles for a beat. " ahead of this exact prose.
    ELEVATOR = brief_with_desc(
        "Live-action, natural real-time motion — the man with dark curly "
        "hair tilts his head slightly and releases a breath as he speaks to "
        "the camera, (S1) says: <d>[English] You have to see this place.</d> "
        "His eyes hold the lens; his lips close once the line lands.")

    def test_the_elevator_brief_joins_after_the_em_dash(self):
        out = server._h3_deterministic_settle(self.ELEVATOR)
        expected = self.ELEVATOR.replace(
            "motion — the man",
            "motion — lips closed, he settles for a beat, then the man")
        self.assertEqual(out, expected)
        self.assertEqual(out.count("settles for a beat"), 1)
        self.assertIsNone(server.h3_speech_in_progress(out))

    def test_a_comma_semicolon_or_colon_connector_joins_the_same_way(self):
        for connector in (",", ";", ":"):
            with self.subTest(connector=connector):
                brief = brief_with_desc(
                    f"Live-action, natural real-time motion{connector} she "
                    "turns to the lens and (S1) says: <d>[English] Hi.</d> "
                    "Her lips close and she waves.")
                out = server._h3_deterministic_settle(brief)
                expected = brief.replace(
                    f"motion{connector} she",
                    f"motion{connector} lips closed, she settles for a "
                    "beat, then she")
                self.assertEqual(out, expected)

    def test_field_start_keeps_the_capitalised_sentence_form(self):
        body = ("integrated_multimodal_description:she turns to the lens "
                "and (S1) says: <d>[English] Hi.</d> Her lips close and she "
                "waves.\n\noverall_soundscape: The hum of the coolers.\n\n"
                "non_diegetic_music: N/A")
        brief = server.H3_I2VA_HEADER + "\n\n" + body
        out = server._h3_deterministic_settle(brief)
        expected = brief.replace(
            "description:she turns",
            "description:Lips closed, she settles for a beat. she turns")
        self.assertEqual(out, expected)

    def test_the_shot_marker_without_a_preamble_keeps_the_sentence_form(self):
        brief = brief_with_desc(
            "She turns to the lens and (S1) says: <d>[English] Hi.</d> "
            "Her lips close and she waves.")
        out = server._h3_deterministic_settle(brief)
        expected = brief.replace(
            "[Shot 1] She turns",
            "[Shot 1] Lips closed, she settles for a beat. She turns")
        self.assertEqual(out, expected)

    def test_a_full_stop_keeps_the_capitalised_sentence_form(self):
        brief = brief_with_desc(
            "Live-action, natural real-time motion. She turns to the lens "
            "and (S1) says: <d>[English] Hi.</d> Her lips close and she "
            "waves.")
        out = server._h3_deterministic_settle(brief)
        expected = brief.replace(
            "motion. She turns",
            "motion. Lips closed, she settles for a beat. She turns")
        self.assertEqual(out, expected)

    def test_the_prose_first_letter_is_never_changed(self):
        # the join case: lowercase prose stays lowercase, uppercase stays
        # uppercase - the clause joins, it never edits the prose
        for first in ("she", "She"):
            with self.subTest(first=first):
                brief = brief_with_desc(
                    "Live-action, natural real-time motion — " + first +
                    " turns to the lens and (S1) says: <d>[English] Hi.</d> "
                    "Her lips close and she waves.")
                out = server._h3_deterministic_settle(brief)
                self.assertIn("for a beat, then " + first + " turns", out)
        # the sentence case: same contract on the other branch
        brief = brief_with_desc(
            "she turns to the lens and (S1) says: <d>[English] Hi.</d> "
            "Her lips close and she waves.")
        out = server._h3_deterministic_settle(brief)
        self.assertIn("for a beat. she turns", out)


class SettlePresentTests(unittest.TestCase):
    """9.40: a settle clause in the first prose sentence satisfies the
    opening - a (S1) says: cue there no longer flags. Every recognized
    shape is pinned; a "phrase" offense beside a settle still fires."""

    def opening_with_settle(self, shape):
        return brief_with_desc(
            "Live-action, natural real-time motion — " + shape +
            ", then (S1) says: <d>[English] Hi.</d> Her lips close and she "
            "turns away.")

    def test_each_settle_shape_suppresses_the_says_hit(self):
        shapes = (
            "lips closed, she settles for a beat",   # the floor's own clause
            "lips closed, he settles for a beat",
            "lips closed, they settle for a beat",
            "Lips closed, she settles for a beat",   # case-insensitive
            "mouth closed, she waits",
            "she settles for a beat",
            "she settles for a moment",
            "a beat before she speaks",
            "after a beat, she speaks",
            "she holds still for a beat",
            "she takes a breath before speaking",
        )
        for shape in shapes:
            with self.subTest(shape=shape):
                self.assertIsNone(
                    server.h3_speech_in_progress(
                        self.opening_with_settle(shape)))

    def test_a_spoken_settle_shape_does_not_count(self):
        # dialogue is masked: a settle shape inside the line is the line's
        brief = brief_with_desc(
            "Live-action, natural real-time motion — She turns and "
            "(S1) says: <d>[English] Lips closed, I settle for a beat.</d> "
            "Her lips close and she waves.")
        self.assertEqual(server.h3_speech_in_progress(brief), "(S1) says:")

    def test_a_phrase_offense_beside_a_settle_still_fires(self):
        # an explicit in-progress clause beside a settle clause is a
        # contradiction, not a settle - the phrase replacement resolves it
        brief = brief_with_desc(
            "Live-action, natural real-time motion — lips closed, she "
            "settles for a beat, finishing a word, then (S1) says: "
            "<d>[English] Hi.</d> Her lips close and she turns away.")
        self.assertEqual(server.h3_speech_in_progress(brief),
                         "finishing a word")


class SettleNeverDoublesTests(unittest.TestCase):
    """9.40: the floor is a no-op on an opening that already settles, the
    repair output never carries a second beat, and the deterministic floor
    is reached only when the brain's reply was rejected."""

    # The 9.37 findings defect-1 case, reconstructed pre-repair: the draft
    # already carries a settle clause in the first sentence AND the cue -
    # the 9.37 detector flagged the cue and the floor prepended a second
    # beat (live 07:12 clip, ledger 7cadcb3a).
    DOUBLED = brief_with_desc(
        "Live-action, natural real-time motion — the woman holds the phone "
        "steady at arm’s length, lips closed, she settles for a beat, eyes "
        "locked on the lens; a breath escapes, then she says: (S1) says: "
        "<d>[English] I finally found one I actually love.</d> Her lips "
        "close and she turns away.")

    def repair(self, brief, stub):
        with patch.object(server, "llm_call", stub):
            return asyncio.run(server.repair_h3_speech_in_progress(brief, "cid9"))

    def test_an_opening_that_already_settles_is_left_alone(self):
        self.assertIsNone(server.h3_speech_in_progress(self.DOUBLED))
        stub = AsyncMock(return_value=llm_reply("anything"))
        out = self.repair(self.DOUBLED, stub)
        self.assertEqual(out, self.DOUBLED)
        self.assertEqual(out.count("settles for a beat"), 1)
        stub.assert_not_awaited()

    def test_the_floor_is_a_no_op_on_an_existing_settle(self):
        self.assertEqual(server._h3_deterministic_settle(self.DOUBLED),
                         self.DOUBLED)

    def test_the_floor_is_idempotent_on_the_flagged_briefs(self):
        for brief in (SettleJoinRuleTests.ELEVATOR,
                      LEDGER_FINISHES_A_WORD, LEDGER_MID_SENTENCE):
            with self.subTest(brief=brief[:60]):
                once = server._h3_deterministic_settle(brief)
                twice = server._h3_deterministic_settle(once)
                self.assertEqual(once, twice)

    def test_a_reply_with_its_own_settle_is_accepted_not_floored(self):
        # 9.37 rejected this reply (the cue still sat in the first sentence)
        # and the floor prepended a second beat; 9.40 takes the reply as is
        flagged = brief_with_desc(
            "Live-action, natural real-time motion — she is already "
            "speaking, hands busy. (S1) says: <d>[English] Hi there.</d> "
            "Her lips close and she turns away.")
        reply = brief_with_desc(
            "Live-action, natural real-time motion — lips closed, she "
            "settles for a beat, then she says: (S1) says: <d>[English] Hi "
            "there.</d> Her lips close and she turns away.")
        stub = AsyncMock(return_value=llm_reply(reply))
        out = self.repair(flagged, stub)
        self.assertEqual(out, reply)
        self.assertEqual(out.count("settles for a beat"), 1)
        stub.assert_awaited_once()


class MusicFieldGuaranteeTests(unittest.TestCase):
    """Reddit item 1: the shipped prompt carried TWO non_diegetic_music
    fields - the director's N/A and the appended contract's 'none.', the
    wrong token. The contract drops its own; the assembler guarantees
    exactly one, N/A unless the director wrote music."""

    def test_the_audio_contract_carries_no_music_field(self):
        self.assertNotIn("non_diegetic_music", server.H3_AUDIO_PROMPT)
        # the two speech rules stay
        self.assertIn("do not invent speech", server.H3_AUDIO_PROMPT)
        self.assertIn("BEGIN and FINISH inside the clip", server.H3_AUDIO_PROMPT)

    def test_a_directed_brief_without_music_gains_na(self):
        out = server.assemble_h3_prompt("She crosses the room and sits.")
        self.assertEqual(out.count("non_diegetic_music:"), 1)
        self.assertTrue(out.endswith("non_diegetic_music: N/A"))

    def test_a_directed_brief_keeps_the_directors_music(self):
        brief = ("integrated_multimodal_description: [Shot 1] She dances.\n\n"
                 "overall_soundscape: A club system.\n\n"
                 "non_diegetic_music: Sparse piano at a slow tempo.")
        out = server.assemble_h3_prompt(brief)
        self.assertEqual(out.count("non_diegetic_music:"), 1)
        self.assertIn("Sparse piano at a slow tempo.", out)
        self.assertNotIn("non_diegetic_music: N/A", out)

    def test_a_duplicated_music_field_keeps_the_first(self):
        brief = ("integrated_multimodal_description: [Shot 1] She dances.\n\n"
                 "overall_soundscape: A club system.\n\n"
                 "non_diegetic_music: Sparse piano.\n\n"
                 "non_diegetic_music: none.")
        out = server.assemble_h3_prompt(brief)
        self.assertEqual(out.count("non_diegetic_music:"), 1)
        self.assertIn("Sparse piano.", out)
        self.assertNotIn("none.", out)

    def test_a_user_script_gains_the_no_score_switch(self):
        # the constant used to carry it for scripts too - with the wrong
        # token; the assembler now guarantees it with the guide's one
        out = server.assemble_h3_prompt("[Shot 1] my own words",
                                        user_script=True)
        self.assertEqual(out.count("non_diegetic_music:"), 1)
        self.assertTrue(out.endswith("non_diegetic_music: N/A"))
        self.assertIn("[Shot 1] my own words", out)

    def test_a_user_script_keeps_its_own_music_field(self):
        script = ("[Shot 1] my own words\n\n"
                  "non_diegetic_music: the score I asked for")
        out = server.assemble_h3_prompt(script, user_script=True)
        self.assertEqual(out.count("non_diegetic_music:"), 1)
        self.assertIn("the score I asked for", out)

    def test_the_i2v_builder_backstops_the_field_for_rerolls(self):
        # rerolls bypass assembly, so the guarantee rides the append site
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                _graph, brief, _info = server.build_h3_i2v(
                    "She turns toward the window.", 987, "prepared.png",
                    seconds=5, width=768, height=1344, model="fl2va",
                    sparse=False)
        self.assertEqual(brief.count("non_diegetic_music:"), 1)
        self.assertTrue(brief.endswith("non_diegetic_music: N/A"))

    def test_every_multishot_shot_carries_exactly_one_music_field(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "_video_asset", side_effect=all_video_assets):
                graph, _brief, _info = server.build_h3_multishot(
                    "One.\n---\nTwo.", 987, "prepared.png",
                    width=768, height=1344, model="fl2va")
        for shot in server.split_shot_script(graph["6"]["inputs"]["script"]):
            self.assertEqual(shot.count("non_diegetic_music:"), 1)
            self.assertIn("non_diegetic_music: N/A", shot)


class SpeechInProgressLintTests(unittest.TestCase):
    """The lint gains the speech-in-progress finding so evidence files and
    tests can count it."""

    def test_an_in_progress_opening_is_a_lint_finding(self):
        warnings = server.h3_brief_lint(LEDGER_MID_SENTENCE, 5)
        self.assertTrue(any("speech-in-progress" in w for w in warnings))

    def test_a_clean_brief_carries_no_such_finding(self):
        warnings = server.h3_brief_lint(brief_with_desc(
            "Live-action, natural real-time motion — she crosses the room."), 5)
        self.assertFalse(any("speech-in-progress" in w for w in warnings))

    def test_a_missing_silence_alone_is_not_the_opening_finding(self):
        # the silence gap is appended deterministically before the builders
        # lint; the finding counts the OPENING defect only
        brief = brief_with_desc(
            "Live-action, natural real-time motion — she waves. "
            "(S1) says: <d>[English] Hi.</d> She grins and waves again.")
        warnings = server.h3_brief_lint(brief, 5)
        self.assertFalse(any("speech-in-progress" in w for w in warnings))


class AnimateSettleWiringTests(unittest.TestCase):
    """The repair runs in animate() right after repair_h3_hanging_dialogue,
    on both lanes, and never on a user's verbatim script."""

    def run_animate(self, root, body, director, hang, settle):
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
                          return_value=("h3", body["model"], body["seconds"], None)), \
             patch.object(server, "prepare_h3_frame",
                          return_value=("prepared.png", 1344, 768)), \
             patch.object(server, "_video_asset", side_effect=all_video_assets), \
             patch.object(server, "direct_motion", director), \
             patch.object(server, "repair_h3_hanging_dialogue", hang), \
             patch.object(server, "repair_h3_speech_in_progress", settle), \
             patch.object(server.HUB, "ledger_read", return_value=[entry]), \
             patch.object(server.HUB, "broadcast"), \
             patch.object(server.HUB, "submit", submit):
            return asyncio.run(run()), submit

    def recording_repairs(self):
        order = []

        async def hang(brief, cid=None):
            order.append("hang")
            return brief

        async def settle(brief, cid=None):
            order.append("settle")
            return brief

        return order, AsyncMock(side_effect=hang), AsyncMock(side_effect=settle)

    def test_the_settle_repair_runs_after_the_hanging_repair_on_fl2va(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "output" / "still.png").write_bytes(b"still")
            order, hang, settle = self.recording_repairs()
            director = AsyncMock(return_value=("She browses the stalls.", True))
            response, submit = self.run_animate(
                root, {"id": "abc123", "cid": "cid1", "engine": "h3",
                       "model": "fl2va", "seconds": 5}, director, hang, settle)
            self.assertEqual(response.status, 200)
            self.assertEqual(order, ["hang", "settle"])
            hang.assert_awaited_once()
            settle.assert_awaited_once()

    def test_the_settle_repair_never_runs_on_a_script(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "output" / "still.png").write_bytes(b"still")
            order, hang, settle = self.recording_repairs()
            director = AsyncMock(return_value=("unreached", True))
            response, submit = self.run_animate(
                root, {"id": "abc123", "cid": "cid1", "engine": "h3",
                       "model": "fl2va", "seconds": 5,
                       "script": "[Shot 1] my own words"}, director, hang, settle)
            self.assertEqual(response.status, 200)
            self.assertEqual(order, ["hang"])
            settle.assert_not_awaited()

    def test_the_settle_repair_runs_on_the_ref2va_lane(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "input").mkdir()
            Image.new("RGB", (1920, 1080), (9, 9, 9)).save(root / "output" / "still.png")
            order, hang, settle = self.recording_repairs()
            director = AsyncMock(return_value=("She browses the stalls.", True))
            response, submit = self.run_animate(
                root, {"id": "abc123", "cid": "cid1", "engine": "h3",
                       "model": "ref2va", "seconds": 5}, director, hang, settle)
            self.assertEqual(response.status, 200)
            self.assertEqual(order, ["hang", "settle"])

    def test_the_settle_repair_never_runs_on_a_ref2va_script(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            (root / "input").mkdir()
            Image.new("RGB", (1920, 1080), (9, 9, 9)).save(root / "output" / "still.png")
            order, hang, settle = self.recording_repairs()
            director = AsyncMock(return_value=("unreached", True))
            response, submit = self.run_animate(
                root, {"id": "abc123", "cid": "cid1", "engine": "h3",
                       "model": "ref2va", "seconds": 5,
                       "script": "[Shot 1] my own words"}, director, hang, settle)
            self.assertEqual(response.status, 200)
            self.assertEqual(order, ["hang"])
            settle.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()



class OpeningBeatIsNotAfterLineSilence(unittest.TestCase):
    """Clip 222e0326 (2026-08-25): the director wrote the settle AFTER the
    cue - "mouth closed at first ... before she begins to speak" - and the
    silence check took it for the after-line clause. Seven words shipped for
    five seconds with nothing claiming the rest, and H3 fills unclaimed air
    with a second take."""

    E = ("integrated_multimodal_description: [Shot 1] Live-action, natural "
         "real-time motion \u2014 the camera steadies as (S1) says: <d>[English] "
         "Finally found a jacket I actually love.</d>, mouth closed at first "
         "\u2014 a moment\u2019s settle, breath held just behind the words \u2014 "
         "before she begins to speak; her gaze snaps toward the sofa.\n\n"
         "overall_soundscape: room tone.")

    def test_the_opening_settle_after_the_cue_does_not_count(self):
        self.assertEqual(server.h3_speech_in_progress(self.E),
                         server.H3_NO_AFTER_LINE_SILENCE)

    def test_a_real_after_line_clause_still_passes(self):
        for tail in ("Lips close softly, speaking motion stops.",
                     "After the line, her lips close and she only listens; "
                     "no further speech.",
                     "She says nothing more."):
            with self.subTest(tail=tail):
                body = self.E.replace("her gaze snaps toward the sofa.",
                                      "her gaze snaps toward the sofa. " + tail)
                self.assertIsNone(server.h3_speech_in_progress(body))

    def test_the_repair_appends_the_clause_it_found_missing(self):
        # no brain in tests: the deterministic fallback is what lands
        with patch.object(server, "llm_call",
                          AsyncMock(side_effect=RuntimeError("no brain"))):
            out = asyncio.run(server.repair_h3_speech_in_progress(self.E, "cid"))
        self.assertIsNone(server.h3_speech_in_progress(out))
        self.assertIn("no further speech", out)
