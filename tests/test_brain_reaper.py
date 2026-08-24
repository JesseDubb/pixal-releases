"""The chat brain hands the card back when nobody is talking to it.

local_keep used to mean "resident until something else evicts it". On
2026-08-22 a brain spawned at 02:10 was still holding 8.4 GB at 04:50 with
nothing having asked it anything for hours - the process that spawned it had
exited and nothing owned it any more. These tests pin the two halves of the
fix: the reaper only ever reaps its own idle process, and changing where the
brain runs evicts the one already running under the old answer.
"""
import asyncio
import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
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


class EvictionKeepsOwnership(unittest.IsolatedAsyncioTestCase):
    """The butler evicts the brain before every render. What it must NOT do is
    disown one that survived the kill.

    Seen live 2026-08-23: taskkill did not land, the pidfile came off anyway,
    and from then on _llm_state() read empty. _ensure_local_llm's "up and not
    st" shortcut read the still-listening server as externally started and
    never respawned it, so llm_call's vision gate - bool(state["mmproj"]) -
    was False forever and _delocalize flattened every attached image to the
    literal string "[attached image]". Chat looked healthy; every LOOK went
    blind, and the H3 first-frame read reported "no live projector" against a
    projector that was loaded, warmed and answering.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.state = Path(self.tmp.name) / ".local_llm.json"
        self.state.write_text(json.dumps(
            {"pid": 4242, "model": "b.gguf", "mmproj": "b.mmproj-f16.gguf",
             "gpu_layers": -1}), encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)

    async def _evict(self, killed, port_open):
        with patch.object(server, "LLM_STATE", self.state), \
             patch.object(server, "_llm_kill", return_value=killed), \
             patch.object(server, "local_llm_port_open",
                          AsyncMock(return_value=port_open)), \
             patch.object(server.asyncio, "sleep", AsyncMock()):
            return await server.free_brain_vram()

    async def test_a_kill_that_did_not_land_keeps_the_pidfile(self):
        """The regression. Still listening = still ours = still sighted."""
        self.assertFalse(await self._evict(killed=False, port_open=True))
        self.assertTrue(self.state.exists())
        kept = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(kept["mmproj"], "b.mmproj-f16.gguf")   # still sighted

    async def test_a_brain_that_actually_died_is_disowned(self):
        self.assertTrue(await self._evict(killed=True, port_open=False))
        self.assertFalse(self.state.exists())

    async def test_a_stale_pidfile_is_still_cleaned_up(self):
        """Nothing there to kill AND nothing listening - the file is junk."""
        self.assertFalse(await self._evict(killed=False, port_open=False))
        self.assertFalse(self.state.exists())

    async def test_a_slow_exit_is_not_disowned_either(self):
        """Killed, but the socket has not closed yet. Keeping the pidfile is
        the safe side: if it really is dying, the next call finds the port
        shut, falls past the reuse check and respawns anyway."""
        self.assertTrue(await self._evict(killed=True, port_open=True))
        self.assertTrue(self.state.exists())

    async def test_no_pid_never_shells_out(self):
        self.state.write_text("{}", encoding="utf-8")
        with patch.object(server, "LLM_STATE", self.state), \
             patch.object(server, "_llm_kill") as kill:
            self.assertFalse(await server.free_brain_vram())
        kill.assert_not_called()

class ReleaseKeepsOwnership(unittest.TestCase):
    """The same ownership rule on the per-turn path.

    release_local_llm runs at the END OF EVERY TURN when local_keep is off,
    so a kill that does not land strands the brain here far sooner than the
    butler ever would - and a disowned brain is a brain whose vision gate is
    off for good (see EvictionKeepsOwnership above)."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.state = Path(self.tmp.name) / ".local_llm.json"
        self.state.write_text(json.dumps(
            {"pid": 4242, "model": "b.gguf", "mmproj": "b.mmproj-f16.gguf"}),
            encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)

    def _release(self, keep, killed=True):
        with patch.object(server, "LLM_STATE", self.state), \
             patch.object(server, "load_config", return_value=_cfg(local_keep=keep)), \
             patch.object(server, "_llm_kill", return_value=killed) as kill:
            server.release_local_llm()
        return kill

    def test_a_released_brain_that_died_is_disowned(self):
        self._release(keep=False, killed=True)
        self.assertFalse(self.state.exists())

    def test_a_release_that_did_not_land_keeps_the_pidfile(self):
        """The regression: still alive, so still ours, so still sighted."""
        self._release(keep=False, killed=False)
        self.assertTrue(self.state.exists())
        kept = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(kept["mmproj"], "b.mmproj-f16.gguf")

    def test_keep_on_never_touches_the_brain(self):
        kill = self._release(keep=True)
        kill.assert_not_called()
        self.assertTrue(self.state.exists())

if __name__ == "__main__":
    unittest.main()
