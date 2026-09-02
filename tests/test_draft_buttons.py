"""Inline draft actions - Generate / Something else (Jesse, 2026-09-01:
"inline buttons after the system asks you something").

When the writer drafts a scene and invites a "go", the lane offers the
two answers that turn actually has: fire it, or ask for a different
take. The contract:

  server - kimi_reply's turn wrapper broadcasts type="draft" with
           pending=bool(_pending_scene(convo)) at EVERY turn end, success
           and failure alike - the same probe 10.4's accept backstop
           reads, so the buttons can never be armed when an accept would
           not fire. The broadcast is guarded: a broken probe must never
           keep _turn_end from running.
  store  - a "draft" event sets draftPending; a fired job or the user's
           own next message clears it optimistically (the server's next
           turn-end broadcast is the honest correction either way).
  lane   - the strip renders only while a draft is pending and nothing is
           generating. Generate sends the accept "go"; Something else
           sends a plain redirect. Both are ordinary chat turns, visible
           in the lane, so the transcript stays honest.
"""

import asyncio
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_draft_buttons", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

STORE = (ROOT / "web" / "src" / "store.js").read_text(encoding="utf-8")
CHAT = (ROOT / "web" / "src" / "components" / "Chat.jsx").read_text(encoding="utf-8")


class TurnEndBroadcast(unittest.TestCase):

    def _run(self, inner, pending):
        events = []
        with patch.object(server, "_kimi_reply", inner), \
             patch.object(server, "_pending_scene",
                          return_value="a drafted scene" if pending else None), \
             patch.object(server.HUB, "broadcast",
                          side_effect=lambda **kw: events.append(kw)), \
             patch.object(server, "_turn_start"), \
             patch.object(server, "_turn_end"):
            asyncio.run(server.kimi_reply("c1", "hey", []))
        return [e for e in events if e.get("type") == "draft"]

    def test_a_pending_draft_broadcasts_true_at_turn_end(self):
        drafts = self._run(AsyncMock(), pending=True)
        self.assertEqual(drafts, [{"type": "draft", "cid": "c1",
                                   "pending": True}])

    def test_no_draft_broadcasts_false_so_stale_buttons_retire(self):
        drafts = self._run(AsyncMock(), pending=False)
        self.assertEqual(drafts, [{"type": "draft", "cid": "c1",
                                   "pending": False}])

    def test_a_failed_turn_still_reports_the_draft_state(self):
        drafts = self._run(AsyncMock(side_effect=ValueError("boom")),
                           pending=True)
        self.assertEqual(drafts, [{"type": "draft", "cid": "c1",
                                   "pending": True}])

    def test_a_broken_probe_never_blocks_turn_end(self):
        ended = []
        with patch.object(server, "_kimi_reply", AsyncMock()), \
             patch.object(server, "_pending_scene",
                          side_effect=RuntimeError("probe broke")), \
             patch.object(server.HUB, "broadcast"), \
             patch.object(server, "_turn_start"), \
             patch.object(server, "_turn_end",
                          side_effect=lambda: ended.append(True)):
            asyncio.run(server.kimi_reply("c1", "hey", []))
        self.assertEqual(ended, [True])


class StoreContract(unittest.TestCase):

    def test_the_draft_event_sets_the_flag(self):
        self.assertIn('case "draft":', STORE)
        self.assertIn("state.draftPending = !!d.pending;", STORE)

    def test_the_lane_can_read_the_flag(self):
        # The lane reads the store through api's getters. The flag shipped
        # without one: store.draftPending read undefined forever while the
        # server broadcast pending=true (2026-09-01, seq 690), and Jesse had
        # to type "go!" by hand.
        self.assertIn("get draftPending() { return state.draftPending; }", STORE)

    def test_a_fired_job_and_a_sent_message_both_clear_it(self):
        # the offer is spent the moment a render fires or the user speaks;
        # the server's turn-end broadcast is the honest correction
        self.assertEqual(STORE.count("state.draftPending = false;"), 2,
                         "the optimistic clears drifted")


class LaneStrip(unittest.TestCase):

    def test_the_strip_gates_on_pending_and_not_generating(self):
        self.assertIn("store.draftPending && !generating", CHAT)

    def test_generate_sends_the_accept_the_backstop_fires(self):
        self.assertIn('send("go")', CHAT)

    def test_something_else_is_a_plain_visible_redirect(self):
        self.assertIn('send("Something else — pitch a different take.")', CHAT)

    def test_the_labels_are_ctas_in_sentence_case(self):
        self.assertIn("Generate", CHAT)
        self.assertIn("Something else", CHAT)


if __name__ == "__main__":
    unittest.main()
