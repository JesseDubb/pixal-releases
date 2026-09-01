"""Brief 9.34 - the warm-path trim never wipes ComfyUI's node-output cache.

/free has no pure-trim verb: free_memory resets the whole node-output
CacheSet (execution.py:672, via main.py:409) and unload_models drops every
weight (main.py:404). The old trim sent free_memory anyway, so a same-stack
rerun came back 0/26 nodes skipped - the reload the trim exists to avoid.
The trim now sends NO request and lets the worker's own post-prompt GC hand
the pool back (main.py:374, inside the 10s gc_collect_interval);
reclaim_vram waits that out on VRAM_TRIM_DEADLINE. The full flush keeps
both flags and the 8s deadline.

LIVE-MACHINE RULE: no ComfyUI, no GPU - the session, the clock and the card
are all injected.
"""

import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


_SPEC = spec_from_file_location("pixal_server_cache_trim",
                                Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


class _Session:
    """Just enough aiohttp session: records posts, answers 200 to nothing."""

    def __init__(self):
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, json, timeout):
        self.posts.append((url, json))


class _Hub:
    """Residency state plus the two real methods under test, nothing else."""

    def __init__(self):
        self.resident_heavies = {"Krea 2\\m.safetensors": 12 * 2**30}
        self.critic_hot = True

    flush_comfy_cache = server.Hub.flush_comfy_cache
    reclaim_vram = server.Hub.reclaim_vram
    note_node_cache_flush = server.Hub.note_node_cache_flush


class TrimSendsNoRequest(unittest.IsolatedAsyncioTestCase):
    async def test_the_trim_sends_no_request_and_returns_true(self):
        """There is no trim verb in /free, so the correct request is no
        request: post must never fire, and the residency books must stay -
        nothing was evicted, nothing may be forgotten."""
        hub = _Hub()
        session = _Session()
        with patch.object(server.aiohttp, "ClientSession",
                          Mock(return_value=session)) as ctor:
            ok = await hub.flush_comfy_cache("stack already resident",
                                             unload=False)
        self.assertTrue(ok)
        ctor.assert_not_called()              # no session, so no /free at all
        self.assertEqual(session.posts, [])
        self.assertEqual(hub.resident_heavies,
                         {"Krea 2\\m.safetensors": 12 * 2**30})
        self.assertTrue(hub.critic_hot)

    async def test_the_flush_posts_the_full_payload(self):
        """The full flush is the one place both flags belong: before video
        the reload IS the bill, and the wipe also drops the previous
        prompt's decoded frames from host RAM."""
        hub = _Hub()
        session = _Session()
        with patch.object(server.aiohttp, "ClientSession",
                          return_value=session):
            ok = await hub.flush_comfy_cache("making room for h3_i2v",
                                             unload=True)
        self.assertTrue(ok)
        self.assertEqual(len(session.posts), 1)
        url, payload = session.posts[0]
        self.assertTrue(url.endswith("/free"))
        self.assertEqual(payload, {"unload_models": True, "free_memory": True})
        self.assertEqual(hub.resident_heavies, {})
        self.assertFalse(hub.critic_hot)


class ReclaimDeadlines(unittest.IsolatedAsyncioTestCase):
    async def _polls_to_the_deadline(self, unload):
        """An unreachable target on a frozen card leaves the deadline as the
        only exit, so the sleep count IS the deadline in VRAM_RECLAIM_POLL
        ticks - the harness the butler tests already use (mocked sleep,
        injected gpu_free_bytes)."""
        hub = _Hub()
        sleep = AsyncMock()
        with patch.object(server.aiohttp, "ClientSession",
                          return_value=_Session()), \
             patch.object(server.asyncio, "sleep", sleep), \
             patch.object(server, "gpu_free_bytes", return_value=2**30):
            await hub.reclaim_vram("counting polls", target=2**40,
                                   unload=unload)
        return sleep.await_count

    async def test_the_trim_waits_out_comfys_own_gc_clock(self):
        """12s: the worker's 10s gc_collect_interval plus slack."""
        self.assertEqual(server.VRAM_TRIM_DEADLINE, 12.0)
        self.assertGreater(server.VRAM_TRIM_DEADLINE,
                           server.VRAM_RECLAIM_DEADLINE)
        polls = await self._polls_to_the_deadline(unload=False)
        self.assertEqual(
            polls, round(server.VRAM_TRIM_DEADLINE / server.VRAM_RECLAIM_POLL))

    async def test_the_flush_keeps_the_reclaim_deadline(self):
        """8s, unchanged: /free's async pool trim is what this poll waits
        on, and that clock is the driver's, not ComfyUI's."""
        self.assertEqual(server.VRAM_RECLAIM_DEADLINE, 8.0)
        polls = await self._polls_to_the_deadline(unload=True)
        self.assertEqual(
            polls,
            round(server.VRAM_RECLAIM_DEADLINE / server.VRAM_RECLAIM_POLL))


if __name__ == "__main__":
    unittest.main()
