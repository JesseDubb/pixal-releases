"""9.61: the local writer's history filter must treat a queued prose scene as a
render. Chat 71979bcf: from turn 9 on every render was the local brain printing
the scene as prose (no tool_calls), the server queueing it and appending the
receipt as a user turn. local_history_view only recognised generate CHAINS, so
seven prose scenes stayed in context and out-voted every new ask.
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
