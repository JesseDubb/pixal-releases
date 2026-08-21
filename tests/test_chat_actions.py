"""Chat-driven render actions: the tool surface the API brain sees, target
resolution for pointing language, and receipt hygiene (no brief echo)."""
import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

_SPEC = spec_from_file_location("pixal_server", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def _names(tools):
    return {t["function"]["name"] for t in tools}


class ToolSurface(unittest.TestCase):
    def test_api_brain_gets_render_actions(self):
        self.assertEqual(_names(server.TOOLS),
                         {"generate", "list_models", "animate", "review", "upscale"})

    def test_local_brain_contract_is_frozen(self):
        # the split-brain contract: the local writer gets ONE tool, ever
        self.assertEqual(_names(server.TOOLS_LOCAL), {"generate"})

    def test_system_prompt_teaches_actions(self):
        self.assertIn("ACTIONS ON AN EXISTING RENDER", server.SYSTEM)
        self.assertNotIn("ACTIONS ON AN EXISTING RENDER", server.SYSTEM_LOCAL)


class ResolveActionEntry(unittest.TestCase):
    def test_explicit_prefix_resolves_to_full_id(self):
        with patch.object(server.HUB, "ledger_read",
                          return_value=[{"id": "9a189484"}]):
            self.assertEqual(server.resolve_action_entry("#9a18"), "9a189484")

    def test_omitted_id_falls_back_to_this_chats_newest_receipt(self):
        convo = [{"role": "tool",
                  "content": '{"queued": "9a189484", "template": "realism"}'}]
        with patch.object(server.HUB, "ledger_read",
                          return_value=[{"id": "9a189484"}]):
            self.assertEqual(server.resolve_action_entry(None, convo), "9a189484")

    def test_prose_receipt_also_counts(self):
        convo = [{"role": "user",
                  "content": "[SYSTEM: the server queued that scene as job "
                             "9a189484 (realism) - no reply needed.]"}]
        with patch.object(server.HUB, "ledger_read",
                          return_value=[{"id": "9a189484"}]):
            self.assertEqual(server.resolve_action_entry("", convo), "9a189484")

    def test_no_render_anywhere_is_none(self):
        with patch.object(server.HUB, "ledger_read", return_value=[]):
            self.assertIsNone(server.resolve_action_entry(None, []))

    def test_unknown_id_is_none_not_a_guess(self):
        with patch.object(server.HUB, "ledger_read",
                          return_value=[{"id": "9a189484"}]):
            self.assertIsNone(server.resolve_action_entry("#deadbeef"))


class ActionRoutes(unittest.TestCase):
    def test_route_call_returns_payload_and_status(self):
        # proves the tool loop's direct-call seam against a verified route
        with patch.object(server.HUB, "ledger_read", return_value=[]):
            payload, status = asyncio.run(
                server._call_action_route(server.upscale, {"id": "nope"}))
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])
        self.assertIn("no such generation", payload["error"])


class Receipts(unittest.TestCase):
    def test_animate_receipt_never_echoes_the_brief(self):
        receipt = server._action_receipt(
            "animate", "9a189484",
            {"ok": True, "engine": "h3", "seconds": 5, "motion": "SECRET-BRIEF"})
        self.assertNotIn("SECRET-BRIEF", json.dumps(receipt))
        self.assertIn("NOT finished", receipt["status"])
        self.assertEqual(receipt["engine"], "h3")

    def test_review_receipt_forbids_invented_critique(self):
        receipt = server._action_receipt("review", "9a189484", {"ok": True})
        self.assertIn("Do not write a critique", receipt["status"])

    def test_error_payloads_pass_through_honestly(self):
        receipt = server._action_receipt("review", "9a189484",
                                         {"ok": False, "error": "no still to review"})
        self.assertEqual(receipt, {"error": "no still to review"})


if __name__ == "__main__":
    unittest.main()
