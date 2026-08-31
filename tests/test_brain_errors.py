"""A provider failure reaches the chat as prose, and a busy one is waited out.

The bug this pins, Jesse 2026-08-31 mid-render: Moonshot returned a capacity
error and the chat lane printed `data.get('error', data)`, so the bubble read

    kimi-k3: {'message': 'The engine is currently overloaded, please try again
    later', 'type': 'engine_overloaded_error'}

- a Python repr of another service's JSON. Two things were wrong with it. The
shape (a dict where a sentence belongs) and the behaviour: an overloaded
provider is the one brain failure the user can do nothing about and that fixes
itself on its own, so it should never have reached them at all.
"""
import asyncio
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch


_SPEC = spec_from_file_location(
    "pixal_server_brain_errors", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

OVERLOADED = {"error": {"message": "The engine is currently overloaded, "
                                   "please try again later",
                        "type": "engine_overloaded_error"}}
BAD_KEY = {"error": {"message": "Invalid Authentication",
                     "type": "invalid_authentication_error"}}
OK = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}


class ErrorTextTests(unittest.TestCase):
    """llm_error turns a provider payload into one sentence."""

    def setUp(self):
        p = patch.object(server, "brain_name", lambda: "kimi-k3")
        p.start()
        self.addCleanup(p.stop)

    def test_the_dict_never_reaches_the_user(self):
        text, _ = server.llm_error(429, OVERLOADED)
        self.assertNotIn("{", text)
        self.assertNotIn("'type'", text)
        self.assertNotIn("engine_overloaded_error", text)

    def test_it_carries_the_providers_own_sentence(self):
        text, _ = server.llm_error(429, OVERLOADED)
        self.assertIn("kimi-k3", text)
        self.assertIn("currently overloaded", text)

    def test_a_capacity_failure_is_transient(self):
        self.assertTrue(server.llm_error(200, OVERLOADED)[1])

    def test_a_bad_key_is_not_transient(self):
        text, transient = server.llm_error(401, BAD_KEY)
        self.assertFalse(transient)
        self.assertIn("could not answer", text)
        self.assertIn("Invalid Authentication", text)

    def test_status_alone_can_mark_it_transient(self):
        # A provider that sends no error body at all still gets waited out
        # when the status says capacity - 503 with an empty payload.
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.assertTrue(server.llm_error(status, {})[1])

    def test_a_400_is_terminal(self):
        self.assertFalse(server.llm_error(400, {})[1])

    def test_a_plain_string_error_is_handled(self):
        # ensure_local_llm returns {"error": "<prose>"}, not the OpenAI shape.
        text, transient = server.llm_error(0, {"error": "the brain would not start"})
        self.assertFalse(transient)
        self.assertIn("the brain would not start", text)

    def test_an_empty_payload_still_says_something(self):
        text, _ = server.llm_error(503, {})
        self.assertIn("503", text)
        self.assertTrue(text.strip())


class PatientCallTests(unittest.TestCase):
    """llm_call_patient waits out a blip and gives up on a real failure."""

    def setUp(self):
        p = patch.object(server, "brain_name", lambda: "kimi-k3")
        p.start()
        self.addCleanup(p.stop)
        # No real sleeping in the suite; the schedule is asserted instead.
        self.slept = []

        async def _sleep(secs):
            self.slept.append(secs)

        s = patch.object(server.asyncio, "sleep", _sleep)
        s.start()
        self.addCleanup(s.stop)

    def _run(self, replies):
        calls = []

        async def fake(messages, timeout=180, tools=None, cid=None):
            calls.append(messages)
            return replies[min(len(calls) - 1, len(replies) - 1)]

        with patch.object(server, "llm_call", fake):
            out = asyncio.run(server.llm_call_patient([{"role": "user",
                                                       "content": "hi"}]))
        return out, calls

    def test_a_busy_provider_is_retried_and_succeeds(self):
        (status, data), calls = self._run([(429, OVERLOADED), (200, OK)])
        self.assertEqual(status, 200)
        self.assertIn("choices", data)
        self.assertEqual(len(calls), 2)

    def test_it_gives_up_after_the_budget_and_returns_the_failure(self):
        (_status, data), calls = self._run([(429, OVERLOADED)])
        self.assertNotIn("choices", data)
        self.assertEqual(len(calls), server.LLM_BUSY_RETRIES + 1)

    def test_the_backoff_grows(self):
        self._run([(429, OVERLOADED)])
        self.assertEqual(self.slept, [server.LLM_BUSY_BACKOFF,
                                      server.LLM_BUSY_BACKOFF * 2])

    def test_a_terminal_failure_is_not_retried(self):
        (_status, _data), calls = self._run([(401, BAD_KEY)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.slept, [])

    def test_a_first_try_success_costs_nothing(self):
        (status, _data), calls = self._run([(200, OK)])
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.slept, [])


class ChatLaneTests(unittest.TestCase):
    """The lane that Jesse actually saw."""

    def test_the_chat_lane_calls_the_patient_wrapper(self):
        src = (Path(__file__).resolve().parents[1] / "server.py") \
            .read_text(encoding="utf-8")
        self.assertIn("await llm_call_patient(", src)

    def test_the_raw_dict_format_is_gone(self):
        src = (Path(__file__).resolve().parents[1] / "server.py") \
            .read_text(encoding="utf-8")
        self.assertNotIn("data.get('error', data)", src)
        self.assertIn("message=llm_error(status, data)[0]", src)


if __name__ == "__main__":
    unittest.main()
