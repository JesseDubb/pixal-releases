"""The idle reaper must not kill a brain that is mid-answer.

LLM_LAST_USED is stamped when a call STARTS (_ensure_local_llm), and llm_call's
own ceiling is 180s - while Settings accepts a local_idle_minutes of 1 or 2, or
a fraction. So a user who sets an aggressive idle window and then asks for
something slow (a 12B writing a long brief on a busy card) had the brain killed
out from under the turn, which surfaces as a connection error with no cause a
user could reason about.

Idle now means "no call in flight AND nothing recent", and the stamp is
refreshed when a call ENDS as well as when it begins.
"""
import asyncio
import time
import unittest
from unittest.mock import patch

import server


def reap_once():
    """Exactly one pass of the reaper loop.

    The loop sleeps BEFORE its body, so the first sleep has to return for the
    body to run at all; cancelling on the second is what bounds it to one pass.
    """
    calls = {"n": 0}

    async def bounded(_s):
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError

    with patch.object(server.asyncio, "sleep", bounded):
        with self_suppress():
            asyncio.run(server.brain_idle_reaper())


class _Suppress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is asyncio.CancelledError


def self_suppress():
    return _Suppress()


class ReaperInFlight(unittest.TestCase):

    def setUp(self):
        self.freed = []
        self._flight = server.LLM_IN_FLIGHT
        self._used = server.LLM_LAST_USED

    def tearDown(self):
        server.LLM_IN_FLIGHT = self._flight
        server.LLM_LAST_USED = self._used

    def run_reaper(self, in_flight, idle_for, minutes=1):
        server.LLM_IN_FLIGHT = in_flight
        server.LLM_LAST_USED = time.time() - idle_for

        async def fake_free():
            self.freed.append(True)
            return True

        cfg = {"llm": {"local_keep": True, "local_idle_minutes": minutes}}
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "_llm_state", return_value={"pid": 1234}), \
             patch.object(server, "free_brain_vram", fake_free):
            reap_once()
        return bool(self.freed)

    def test_a_call_in_flight_is_never_reaped(self):
        """Even long past the idle window: in flight is the opposite of idle."""
        self.assertFalse(self.run_reaper(in_flight=1, idle_for=10_000))

    def test_several_calls_in_flight_are_never_reaped(self):
        self.assertFalse(self.run_reaper(in_flight=3, idle_for=10_000))

    def test_a_genuinely_idle_brain_is_still_reaped(self):
        """The guard must not disable the reaper - that is the whole feature."""
        self.assertTrue(self.run_reaper(in_flight=0, idle_for=10_000))

    def test_a_recently_used_brain_is_left_alone(self):
        self.assertFalse(self.run_reaper(in_flight=0, idle_for=1))

    def test_zero_minutes_still_means_never(self):
        self.assertFalse(self.run_reaper(in_flight=0, idle_for=10_000, minutes=0))

    def test_the_counter_is_released_when_a_call_raises(self):
        """A stranded count would disable the reaper for the life of the
        process - the exact failure it exists to prevent - so the decrement
        lives in `finally`."""
        before = server.LLM_IN_FLIGHT

        async def boom(*a, **k):
            return None

        async def drive():
            with patch.object(server, "ensure_local_llm", boom), \
                 patch.object(server, "load_config", return_value={
                     "llm": {"model": "m", "base_url": "http://x/v1",
                             "api_key": "k", "local_model": ""}}), \
                 patch.object(server.aiohttp, "ClientSession",
                              side_effect=RuntimeError("network is down")):
                with self.assertRaises(RuntimeError):
                    await server.llm_call([{"role": "user", "content": "hi"}])

        asyncio.run(drive())
        self.assertEqual(server.LLM_IN_FLIGHT, before)


if __name__ == "__main__":
    unittest.main()
