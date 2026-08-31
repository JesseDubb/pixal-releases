"""9.61: the local writer's history filter must treat a queued prose scene as a
render. Chat 71979bcf: from turn 9 on every render was the local brain printing
the scene as prose (no tool_calls), the server queueing it and appending the
receipt as a user turn. local_history_view only recognised generate CHAINS, so
seven prose scenes stayed in context and out-voted every new ask.

2026-08-31: the same thing again, one step earlier. That fix keyed on the
queue RECEIPT, so it only ever saw a prose scene the user had accepted. The
writer prints a scene as chat on roughly one ask in six and most of those are
never accepted, so they accumulated untouched: six asks through /api/chat left
seven copies in context, the writer reproduced its own wardrobe verbatim in
three unrelated scenes ("a cropped black crop top with high-waisted denim
shorts, paired with ankle boots"), and captions went from ~70 words in
isolation to ~150 in the product - long enough that the appended framing
clause stopped being obeyed and three renders in a row came back full length.
An unqueued prose scene is now dropped the same way, except the newest, which
is what a bare "render it" accepts.
"""
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_SPEC = spec_from_file_location(
    "pixal_writer_history_leak_tests",
    Path(__file__).resolve().parents[1] / "server.py")
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


def queued_scene_receipt(job_id, template="realism"):
    """The exact string the server appends after queueing a prose scene."""
    return (f"[SYSTEM: the server queued that scene as job "
            f"{job_id} ({template}) - no reply needed.]")


def prose_scene(setting):
    """A local-brain assistant turn that printed the scene instead of calling
    generate (>= 30 words, no question - the shape the server queues)."""
    return {"role": "assistant", "content":
            f"A young woman in {setting}, wearing a black Louis Vuitton "
            f"full-body suit that hugs her hourglass figure, her face bare "
            f"with no makeup, no contouring, photographed on a phone camera."}


def chat_71979bcf():
    """Three queued prose scenes - each carrying the turn-4 wardrobe into a
    setting that never asked for it - then a fresh ask."""
    return [
        {"role": "user", "content": "put her at a rooftop party at golden hour"},
        prose_scene("a rooftop party at golden hour"),
        {"role": "user", "content": queued_scene_receipt("1a2b3c4d")},
        {"role": "user", "content": "now a laundromat at night"},
        prose_scene("an all-night laundromat"),
        {"role": "user", "content": queued_scene_receipt("5e6f7a8b")},
        {"role": "user", "content": "a farmers market on sunday morning"},
        prose_scene("a farmers market on a sunday morning"),
        {"role": "user", "content": queued_scene_receipt("9c0d1e2f")},
        {"role": "user", "content": "a quiet diner, counter seat, coffee"},
    ]


def unaccepted_chat():
    """2026-08-31's real shape: the writer answered four asks with prose and
    the user never said go, so not one of them has a receipt."""
    return [
        {"role": "user", "content": "render her on a night bus, half asleep"},
        prose_scene("the top deck of a night bus"),
        {"role": "user", "content": "make me one in a chip shop at 2am"},
        prose_scene("a chip shop at two in the morning"),
        {"role": "user", "content": "shoot her on a front step at dawn"},
        prose_scene("a front step at dawn"),
        {"role": "user", "content": "render her in a laundrette, eating a banana"},
    ]


class UnqueuedProseTests(unittest.TestCase):
    """A scene the user never accepted is still a scene."""

    def test_a_fresh_ask_drops_every_unaccepted_scene(self):
        """Not "all but the newest" - all of them. Keeping the last one was
        measured and changed nothing: the writer reproduced the survivor word
        for word, 148 words and the same wardrobe, in a scene that had asked
        for neither. One copy of its own prose is enough."""
        messages = unaccepted_chat()
        original = json.loads(json.dumps(messages))

        view = server.local_history_view(messages, 6, preserve_latest_render=False)
        encoded = json.dumps(view)

        # Every ask is conversation and stays.
        for ask in ("night bus, half asleep", "chip shop at 2am",
                    "front step at dawn", "laundrette, eating a banana"):
            self.assertIn(ask, encoded)
        # No prior scene text at all.
        self.assertNotIn("Louis Vuitton", encoded)
        self.assertNotIn("hourglass", encoded)
        # The persisted conversation is never mutated.
        self.assertEqual(messages, original)

    def test_the_pending_scene_survives_the_turn_that_accepts_it(self):
        """_pending_scene reads the unfiltered convo to decide a bare "render
        it" has something to accept. On that turn - and only that turn - the
        writer must still be able to see it, or the server offers to render
        something the writer cannot read."""
        messages = unaccepted_chat()[:-1]          # ends on the prose scene
        self.assertTrue(server._pending_scene(messages))
        accepting = server.local_history_view(
            messages, len(messages), preserve_pending_scene=True)
        self.assertIn("a front step at dawn, wearing", json.dumps(accepting))
        # ...and not on a turn that is asking for something new.
        fresh = server.local_history_view(
            messages, len(messages), preserve_pending_scene=False)
        self.assertNotIn("Louis Vuitton", json.dumps(fresh))

    def test_only_an_accept_or_an_edit_keeps_the_draft(self):
        """The crux, and the thing that made the first two attempts useless.

        render_intent asks "does the user want a picture", and answers yes for
        a brand new ask - correctly, or the tool would not be offered. Reusing
        that test to decide whether the WRITER sees its last draft keeps the
        draft in front of it on every single turn, and it then reproduces the
        draft verbatim. The narrower question is whether this turn accepts the
        draft or edits it, which is what local_iteration already answers.
        """
        accepts_or_edits = ("render it", "go", "show me", "yes",
                            "make her jacket red", "make it an 80s slasher",
                            "now a laundromat at night")
        new_shots = ("render her in a chip shop at 2am, eating chips",
                     "shoot her on a front step at dawn with a coffee",
                     "render her sat on the kerb outside a house party")
        for utext in accepts_or_edits:
            with self.subTest(utext=utext):
                self.assertTrue(
                    server._AFFIRMATIVE.match(utext.strip()) or
                    server._LOCAL_ITERATION_RE.search(utext) or
                    server._REFERS_BACK_RE.search(utext))
        for utext in new_shots:
            with self.subTest(utext=utext):
                self.assertFalse(server._AFFIRMATIVE.match(utext.strip()))
                self.assertFalse(server._LOCAL_ITERATION_RE.search(utext))
                self.assertFalse(server._REFERS_BACK_RE.search(utext))
                # ...while still plainly being a render request, which is why
                # render_intent's own test cannot be reused here.
                self.assertTrue(server.substantive_redirect(utext))

    def test_short_replies_are_conversation_and_stay(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "What are we making?"},
            {"role": "user", "content": "something on a night bus"},
        ]
        view = server.local_history_view(messages, 2, preserve_latest_render=False)
        self.assertIn("What are we making?", json.dumps(view))

    def test_the_word_threshold_is_the_one_pending_scene_uses(self):
        # Two readings of "is this a scene" that disagree would let a scene be
        # offered for acceptance and then hidden from the writer, or kept in
        # context forever while nothing could accept it.
        self.assertEqual(server._PROSE_SCENE_WORDS, 30)
        short = {"role": "assistant", "content": " ".join(["word"] * 29)}
        long = {"role": "assistant", "content": " ".join(["word"] * 30)}
        self.assertFalse(server._pending_scene([short]))
        self.assertTrue(server._pending_scene([long]))

    def test_a_queued_scene_and_an_unaccepted_one_both_go(self):
        messages = [
            {"role": "user", "content": "put her at a rooftop party"},
            prose_scene("a rooftop party at golden hour"),
            {"role": "user", "content": queued_scene_receipt("1a2b3c4d")},
            {"role": "user", "content": "now a laundromat at night"},
            prose_scene("an all-night laundromat"),
            {"role": "user", "content": "a quiet diner, counter seat, coffee"},
        ]
        fresh = json.dumps(server.local_history_view(messages, 5))
        self.assertNotIn("Louis Vuitton", fresh)
        self.assertNotIn("queued that scene", fresh)
        # On the turn that accepts it, the unqueued one - and only it - stays.
        accepting = json.dumps(server.local_history_view(
            messages, 5, preserve_pending_scene=True))
        self.assertEqual(accepting.count("Louis Vuitton"), 1)
        self.assertIn("an all-night laundromat", accepting)
        self.assertNotIn("rooftop party at golden hour, wearing", accepting)


    def test_an_older_draft_goes_when_a_newer_scene_was_accepted(self):
        """The survivor is the PENDING scene, not merely the newest unqueued
        one. Once a later scene has been queued, the earlier draft is what the
        rule exists to remove."""
        messages = [
            {"role": "user", "content": "put her at a rooftop party"},
            prose_scene("a rooftop party at golden hour"),
            {"role": "user", "content": "now a laundromat at night"},
            prose_scene("an all-night laundromat"),
            {"role": "user", "content": queued_scene_receipt("5e6f7a8b")},
            {"role": "user", "content": "a quiet diner, counter seat, coffee"},
        ]
        # Even asked to preserve the pending draft, there is none to preserve:
        # a later scene was queued, so the rooftop draft is just an old draft.
        encoded = json.dumps(server.local_history_view(
            messages, 5, preserve_pending_scene=True))
        self.assertNotIn("Louis Vuitton", encoded)
        self.assertNotIn("queued that scene", encoded)
        self.assertIn("put her at a rooftop party", encoded)
        self.assertIn("a quiet diner", encoded)


class ProseSceneRenderTests(unittest.TestCase):
    def test_fresh_ask_drops_every_prose_scene_and_receipt(self):
        messages = chat_71979bcf()
        original = json.loads(json.dumps(messages))

        view = server.local_history_view(messages, 9, preserve_latest_render=False)
        encoded = json.dumps(view)

        # The user's asks are conversation and stay.
        self.assertIn("rooftop party at golden hour", encoded)
        self.assertIn("now a laundromat at night", encoded)
        self.assertIn("a farmers market on sunday morning", encoded)
        self.assertIn("a quiet diner", encoded)
        # No prior scene text at all: not the wardrobe, not the receipts.
        self.assertNotIn("Louis Vuitton", encoded)
        self.assertNotIn("hourglass", encoded)
        self.assertNotIn("queued that scene", encoded)
        self.assertNotIn("1a2b3c4d", encoded)
        self.assertNotIn("5e6f7a8b", encoded)
        self.assertNotIn("9c0d1e2f", encoded)
        # The persisted conversation is never mutated.
        self.assertEqual(messages, original)

    def test_iteration_keeps_exactly_the_newest_prose_render(self):
        messages = chat_71979bcf()

        view = server.local_history_view(messages, 9, preserve_latest_render=True)
        encoded = json.dumps(view)

        # Exactly one prior render survives: the newest prose scene, with its
        # receipt (the receipt is what tells the brain a render happened).
        self.assertEqual(encoded.count("hourglass"), 1)
        self.assertIn("farmers market on a sunday morning", encoded)
        self.assertIn(queued_scene_receipt("9c0d1e2f"), encoded)
        self.assertNotIn("rooftop party at golden hour, wearing", encoded)
        self.assertNotIn("all-night laundromat", encoded)
        self.assertNotIn("1a2b3c4d", encoded)
        self.assertNotIn("5e6f7a8b", encoded)
        # All three asks stay - they are conversation.
        self.assertIn("rooftop party at golden hour", encoded)
        self.assertIn("now a laundromat at night", encoded)
        self.assertIn("a farmers market on sunday morning", encoded)

    def test_iteration_drops_older_prose_render_when_tool_chain_is_newest(self):
        """A prose render counts as 'the latest render' the same way a tool
        render does: when a tool chain is newer, the prose pair goes too."""
        messages = [
            {"role": "user", "content": "a rooftop party at golden hour"},
            prose_scene("a rooftop party at golden hour"),
            {"role": "user", "content": queued_scene_receipt("1a2b3c4d")},
            {"role": "user", "content": "same idea, but in a kitchen"},
            generate_call("e5f60718", "A person at the kitchen counter."),
            generate_receipt("e5f60718", "A person at the kitchen counter."),
            {"role": "assistant", "content": "Rendered: kitchen portrait."},
            {"role": "user", "content": "again, make it moodier"},
        ]

        view = server.local_history_view(messages, 7, preserve_latest_render=True)
        encoded = json.dumps(view)

        self.assertNotIn("hourglass", encoded)
        self.assertNotIn("1a2b3c4d", encoded)
        self.assertIn("e5f60718", encoded)
        self.assertIn("kitchen counter", encoded)

    def test_tool_only_fixture_output_byte_identical_to_pre_change(self):
        """Snapshot of the pre-change function on a mixed fixture of ordinary
        chat and generate chains only (captured 2026-08-27, before the edit):
        the tool path must not move by a byte."""
        fixture = [
            {"role": "user", "content": "What can you do?"},
            {"role": "assistant", "content": "I can help direct a shot."},
            {"role": "user", "content": [{"type": "text", "text":
                "Make a portrait.\n\n[COMPOSER: old model settings.]\n"
                "[CHARACTER: Old look. Never move them.]"}]},
            generate_call("a1b2c3d4", "A person standing among desert dunes."),
            generate_receipt("a1b2c3d4", "A person standing among desert dunes."),
            {"role": "assistant", "content": "Rendered: the person in desert sand."},
            {"role": "user", "content":
                "Now put her in a kitchen.\n[PRIOR RENDER #a1b2c3d4 - the desert shot]"},
            generate_call("e5f60718", "A person at the kitchen counter."),
            generate_receipt("e5f60718", "A person at the kitchen counter."),
            {"role": "assistant", "content": "Rendered: kitchen portrait."},
            {"role": "user", "content": "thanks!"},
            {"role": "assistant", "content": "Anytime."},
            {"role": "user", "content": "A new portrait in a music studio."},
        ]

        fresh = server.local_history_view(fixture, 12, preserve_latest_render=False)
        iteration = server.local_history_view(fixture, 12, preserve_latest_render=True)

        self.assertEqual(json.loads(SNAPSHOT)["fresh"], fresh)
        self.assertEqual(json.loads(SNAPSHOT)["iteration"], iteration)


class QueuedSceneReceiptTests(unittest.TestCase):
    def test_receipt_regex_matches_the_exact_appended_string(self):
        """The filter's matcher and the appender's string share one source;
        format a receipt through the same code path and assert the match."""
        receipt = server._QUEUED_SCENE_RECEIPT_FMT.format(
            job_id="a1b2c3d4", template="realism")
        self.assertEqual(
            receipt,
            "[SYSTEM: the server queued that scene as job "
            "a1b2c3d4 (realism) - no reply needed.]")
        self.assertTrue(server._QUEUED_SCENE_RECEIPT_RE.fullmatch(receipt))
        self.assertTrue(server._QUEUED_SCENE_RECEIPT_RE.fullmatch(
            queued_scene_receipt("0f1e2d3c", "phone_photo")))

    def test_receipt_regex_rejects_ordinary_user_text(self):
        self.assertIsNone(server._QUEUED_SCENE_RECEIPT_RE.fullmatch(
            "the server queued that scene, I think"))
        self.assertIsNone(server._QUEUED_SCENE_RECEIPT_RE.fullmatch(
            "[SYSTEM: the server queued that scene as job "
            "a1b2c3d4 (realism) - no reply needed.] trailing words"))
        # The enhance-off "prompt" variant is a different string, out of scope.
        self.assertIsNone(server._QUEUED_SCENE_RECEIPT_RE.fullmatch(
            "[SYSTEM: the server queued that prompt as job "
            "a1b2c3d4 (realism) - no reply needed.]"))


SNAPSHOT = r"""
{
  "fresh": [
    {"role": "user", "content": "What can you do?"},
    {"role": "assistant", "content": "I can help direct a shot."},
    {"role": "user", "content": [{"type": "text", "text": "Make a portrait."}]},
    {"role": "user", "content": "Now put her in a kitchen."},
    {"role": "user", "content": "thanks!"},
    {"role": "assistant", "content": "Anytime."},
    {"role": "user", "content": "A new portrait in a music studio."}
  ],
  "iteration": [
    {"role": "user", "content": "What can you do?"},
    {"role": "assistant", "content": "I can help direct a shot."},
    {"role": "user", "content": [{"type": "text", "text": "Make a portrait."}]},
    {"role": "user", "content": "Now put her in a kitchen.\n[PRIOR RENDER #a1b2c3d4 - the desert shot]"},
    {"role": "assistant", "content": null,
     "tool_calls": [{"id": "e5f60718", "type": "function",
                     "function": {"name": "generate",
                                  "arguments": "{\"template\": \"realism\", \"scene\": \"A person at the kitchen counter.\"}"}}]},
    {"role": "tool", "tool_call_id": "e5f60718",
     "content": "{\"queued\": \"e5f60718\", \"scene\": \"A person at the kitchen counter.\"}"},
    {"role": "assistant", "content": "Rendered: kitchen portrait."},
    {"role": "user", "content": "thanks!"},
    {"role": "assistant", "content": "Anytime."},
    {"role": "user", "content": "A new portrait in a music studio."}
  ]
}
"""


if __name__ == "__main__":
    unittest.main()
