"""The chat brain hands the card back when nobody is talking to it.

local_keep used to mean "resident until something else evicts it". On
2026-08-22 a brain spawned at 02:10 was still holding 8.4 GB at 04:50 with
nothing having asked it anything for hours - the process that spawned it had
exited and nothing owned it any more. These tests pin the two halves of the
fix: the reaper only ever reaps its own idle process, and changing where the
brain runs evicts the one already running under the old answer.
"""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

import server


def _cfg(**llm):
    base = {"local_keep": True, "local_model": "brain.gguf", "local_gpu_layers": -1}
    base.update(llm)
    return {"llm": base}


class ReaperDecision(unittest.TestCase):
    """One tick of brain_idle_reaper, driven by hand."""

    def _tick(self, cfg, state, last_used, freed=True):
        """Run exactly one loop body and report whether it evicted."""
        free = AsyncMock(return_value=freed)
        # sleep returns immediately the first time, then aborts the loop, so
        # the test never depends on real time passing.
        calls = {"n": 0}

        async def one_sleep(_s):
            calls["n"] += 1
            if calls["n"] > 1:
                raise asyncio.CancelledError

        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "_llm_state", return_value=state), \
             patch.object(server, "free_brain_vram", free), \
             patch.object(server.asyncio, "sleep", one_sleep), \
             patch.object(server, "LLM_LAST_USED", last_used):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(server.brain_idle_reaper())
        return free

    def test_evicts_a_brain_nobody_has_used(self):
        free = self._tick(_cfg(), {"pid": 4242}, time.time() - 3600)
        free.assert_awaited_once()

    def test_leaves_a_brain_that_was_just_used(self):
        free = self._tick(_cfg(), {"pid": 4242}, time.time() - 5)
        free.assert_not_awaited()

    def test_leaves_a_server_it_did_not_spawn(self):
        """No pidfile means run_llm.bat started it. Never our business."""
        free = self._tick(_cfg(), {}, time.time() - 3600)
        free.assert_not_awaited()

    def test_stays_out_of_the_way_when_keep_is_off(self):
        """local_keep off already drops the brain every turn."""
        free = self._tick(_cfg(local_keep=False), {"pid": 4242}, time.time() - 3600)
        free.assert_not_awaited()

    def test_zero_minutes_means_keep_it_forever(self):
        free = self._tick(_cfg(local_idle_minutes=0), {"pid": 4242}, time.time() - 86400)
        free.assert_not_awaited()

    def test_honours_a_custom_idle_window(self):
        cfg = _cfg(local_idle_minutes=1)
        self._tick(cfg, {"pid": 4242}, time.time() - 30).assert_not_awaited()
        self._tick(cfg, {"pid": 4242}, time.time() - 90).assert_awaited_once()

    def test_an_adopted_orphan_counts_as_idle_since_boot(self):
        """LLM_LAST_USED is 0 for a brain this process never used - a survivor
        of a sidecar restart. Those are exactly the ones worth reaping."""
        with patch.object(server, "_PROCESS_START", time.time() - 7200):
            free = self._tick(_cfg(), {"pid": 4242}, 0.0)
        free.assert_awaited_once()

    def test_a_failed_kill_is_not_fatal(self):
        """taskkill can lose the race with a process that already died."""
        free = self._tick(_cfg(), {"pid": 4242}, time.time() - 3600, freed=False)
        free.assert_awaited_once()


class PlacementChangeEvicts(unittest.IsolatedAsyncioTestCase):
    """Saving 'chat brain: CPU' has to move the brain that is already running."""

    async def _save(self, before, patch_body):
        saved = {}
        req = AsyncMock()
        req.json = AsyncMock(return_value={"llm": patch_body})
        free = AsyncMock(return_value=True)
        cfg = {"llm": dict(before), "critic": {}, "upscale": {}, "video": {}}

        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "save_config", saved.setdefault.__get__(saved)
                          if False else (lambda c: saved.update(c))), \
             patch.object(server, "free_brain_vram", free):
            await server.settings_post(req)
        return free

    async def test_moving_the_brain_to_cpu_evicts_the_gpu_one(self):
        free = await self._save({"local_gpu_layers": -1, "local_model": "b.gguf"},
                                {"local_gpu_layers": 0})
        free.assert_awaited_once()

    async def test_a_different_model_evicts_too(self):
        free = await self._save({"local_gpu_layers": -1, "local_model": "b.gguf"},
                                {"local_model": "other.gguf"})
        free.assert_awaited_once()

    async def test_saving_the_same_placement_leaves_it_alone(self):
        """Settings gets saved for a hundred unrelated reasons. Reloading a
        multi-GB GGUF because someone changed the theme would be its own bug."""
        free = await self._save({"local_gpu_layers": -1, "local_model": "b.gguf"},
                                {"local_gpu_layers": -1})
        free.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
