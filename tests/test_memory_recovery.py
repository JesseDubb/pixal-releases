"""Memory failure cases use synthetic graphs/readings, never the live engine."""
import asyncio
import copy
import time
import unittest
from unittest.mock import AsyncMock, patch

from pixal.memory import (
    GIB, HostMemory, MemoryPressureError, memory_failure_kind,
    shrink_still_spec, still_canvas,
)
from test_identity_build import server, assets, identity_anchor, KREA


def latent(w=1152, h=2048, batch=1):
    return {"30:5": {"class_type": "EmptyLatentImage", "inputs": {
        "width": w, "height": h, "batch_size": batch}}}


class MemoryPolicyTests(unittest.TestCase):
    def test_gpu_error_dialects(self):
        for error in (
            "Allocation on device 0 would exceed allowed memory. (out of memory)",
            "CUDA out of memory", "torch.OutOfMemoryError", "out of memory",
            "CUBLAS_STATUS_ALLOC_FAILED", "cudaErrorMemoryAllocation",
        ):
            with self.subTest(error=error):
                self.assertEqual(memory_failure_kind(error), "gpu")

    def test_host_error_dialects(self):
        for error in (
            "DefaultCPUAllocator: not enough memory", "MemoryError",
            "[WinError 1455] The paging file is too small", "std::bad_alloc",
            "numpy._core._exceptions._ArrayMemoryError: Unable to allocate",
        ):
            with self.subTest(error=error):
                self.assertEqual(memory_failure_kind(error), "ram")

    def test_non_memory_failures_are_not_retried(self):
        for error in (None, "stopped", "invalid model", "CUDA invalid argument"):
            self.assertIsNone(memory_failure_kind(error))

    def test_commit_pressure_matters_even_with_plenty_of_physical_ram(self):
        self.assertIn("commit", HostMemory(30 * GIB, GIB).critical_reason())
        self.assertIn("physical", HostMemory(GIB // 2, 100 * GIB).critical_reason())
        self.assertIsNone(HostMemory(8 * GIB, 20 * GIB).critical_reason())

    def test_only_sampling_canvas_counts(self):
        graph = latent()
        graph["composite"] = {"class_type": "ImageScale", "inputs": {"width": 8000, "height": 8000}}
        self.assertEqual(still_canvas(graph)["width"], 1152)
        graph["30:5"]["inputs"]["width"] = ["size", 0]
        self.assertIsNone(still_canvas(graph))

    def test_ambiguous_and_video_canvases_are_not_generically_shrunk(self):
        graph = latent()
        graph["other"] = copy.deepcopy(graph["30:5"])
        self.assertIsNone(still_canvas(graph))
        graph = latent()
        graph["30:5"].update(class_type="EmptyHunyuanLatentVideo")
        graph["30:5"]["inputs"]["length"] = 121
        self.assertIsNone(still_canvas(graph))

    def test_overrides_cannot_restore_the_failed_canvas(self):
        graph = latent()
        graph["scheduler"] = {"class_type": "Flux2Scheduler", "inputs": {
            "width": 1152, "height": 2048}}
        spec = {"aspect": "9:16 (Portrait Widescreen)", "mp": 2.36,
                "overrides": [{"node": "30:5", "input": "width", "value": 1152}],
                "character": "hero", "lora_plan": {"entries": []}}
        original = copy.deepcopy(spec)
        smaller, _ = shrink_still_spec(spec, still_canvas(graph), {"mp", "overrides"})
        for override in smaller["overrides"]:
            graph[override["node"]]["inputs"][override["input"]] = override["value"]
        canvas = still_canvas(graph)
        self.assertLessEqual(canvas["width"] * canvas["height"], 1152 * 2048 / 2)
        self.assertEqual(graph["scheduler"]["inputs"]["width"], canvas["width"])
        self.assertEqual(spec, original)
        self.assertEqual(smaller["character"], "hero")

    def test_batch_reduces_before_resolution(self):
        plan, note = shrink_still_spec({}, still_canvas(latent(batch=4)), {"overrides"})
        self.assertEqual(plan["overrides"], [{"node": "30:5", "input": "batch_size", "value": 2}])
        self.assertIn("batch", note)

    def test_minimum_canvas_is_terminal(self):
        self.assertIsNone(shrink_still_spec({}, still_canvas(latent(512, 512)), {"overrides"}))

    def test_fixed_decoder_presets_are_not_replaced_by_arbitrary_dimensions(self):
        canvas = {**still_canvas(latent()), "resizable": False}
        self.assertIsNone(shrink_still_spec({}, canvas, {"overrides"}))


class IdentityRecoveryTests(unittest.TestCase):
    def test_actual_identity_graph_rebuilds_smaller_even_with_old_overrides(self):
        with assets(KREA), identity_anchor(), patch.object(
                server, "resolve_recipe_lora_stack", return_value=([], [])):
            spec = {"character": "hero", "pid": False, "mp": 2,
                    "aspect": "2:3 (Portrait Photo)", "overrides": [
                        {"node": "30:5", "input": "width", "value": 1152},
                        {"node": "30:5", "input": "height", "value": 1728}]}
            graph, _, info = server.build_zara_edit("a quiet portrait", 7, **spec)
            self.assertEqual(info["canvas_mp"], 1152 * 1728 / 1e6)
            job = {"template": "identity_edit", "spec": spec, "info": info,
                   "error": "CUDA out of memory", "_memory_canvas": still_canvas(graph)}
            hub = server.Hub.__new__(server.Hub)
            retry, note = hub.oom_retry_plan(job)
            smaller, _, smaller_info = server.build_zara_edit("a quiet portrait", 7, **retry)
            self.assertLess(smaller_info["canvas_mp"], info["canvas_mp"] * .51)
            self.assertEqual(smaller["30:51"]["inputs"]["seed"], 7)
            self.assertEqual(smaller["ed:img"]["inputs"]["image"], graph["ed:img"]["inputs"]["image"])
            self.assertIn("instead of", note)
            self.assertIsNone(hub.oom_retry_plan({**job, "_oom_retry": True}))
            self.assertIsNotNone(hub.oom_retry_plan({**job, "template": "zara_edit"}))

    def test_source_edit_retry_overrides_the_old_ceiling(self):
        hub = server.Hub.__new__(server.Hub)
        for template, node in (("qwen_edit", "qe:scale"), ("klein_edit", "ke:scale")):
            job = {"template": template, "error": "CUDA out of memory",
                   "info": {"canvas_mp": 1.0}, "spec": {"megapixels": 8,
                   "overrides": [{"node": node, "input": "megapixels", "value": 8}]}}
            retry, _ = hub.oom_retry_plan(job)
            self.assertEqual(retry["overrides"][-1]["value"], .5)


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    def hub(self):
        hub = server.Hub.__new__(server.Hub)
        hub.jobs, hub.queue_remaining = {}, 0
        hub.broadcast = lambda **kw: None
        return hub

    async def test_concurrent_preflights_serialize_without_deadlocking(self):
        hub = self.hub()
        first = {"id": "a", "cid": "c", "started": time.time()}
        second = {"id": "b", "cid": "c", "started": time.time(), "_draining": True}
        hub.jobs = {"a": first, "b": second}
        lock = await hub.acquire_memory_turn(first)
        waiting = asyncio.create_task(hub.acquire_memory_turn(second))
        await asyncio.sleep(0)
        self.assertFalse(waiting.done())
        lock.release()
        await asyncio.sleep(0)
        self.assertFalse(waiting.done(), "enqueue alone must not allow flushing the running job")
        first["finalized"] = True
        second_lock = await asyncio.wait_for(waiting, 2)
        second_lock.release()
        self.assertFalse(second.get("_draining"))

    async def test_stopped_waiter_never_gets_admitted(self):
        hub = self.hub()
        hub.queue_remaining = 1
        job = {"id": "a", "cid": "c", "finalized": True}
        self.assertIsNone(await hub.acquire_memory_turn(job))
        self.assertFalse(hub._memory_lock.locked())

    async def test_cancellation_releases_the_admission_lock(self):
        hub = self.hub()
        hub.queue_remaining = 1
        job = {"id": "a", "cid": "c"}
        waiting = asyncio.create_task(hub.acquire_memory_turn(job))
        await asyncio.sleep(0)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertFalse(hub._memory_lock.locked())
        self.assertFalse(job.get("_draining"))

    async def test_busy_timeout_does_not_bypass_the_butler(self):
        hub = self.hub()
        hub.queue_remaining = 1
        with patch.object(server, "JOB_INFLIGHT_SECONDS", 0):
            with self.assertRaises(MemoryPressureError):
                await hub.acquire_memory_turn({"id": "a", "cid": "c"})
        self.assertFalse(hub._memory_lock.locked())

    async def test_host_cleanup_rechecks_commit_before_admission(self):
        hub = self.hub()
        hub.reclaim_vram = AsyncMock()
        low, healthy = HostMemory(20 * GIB, GIB), HostMemory(20 * GIB, 30 * GIB)
        with patch.object(server, "host_memory_status", side_effect=[low, healthy]), \
                patch.object(server, "free_brain_vram", AsyncMock()) as brain:
            await hub.ensure_host_memory({"cid": "c"})
        brain.assert_awaited_once()
        hub.reclaim_vram.assert_awaited_once()

    async def test_host_failure_is_not_swallowed_or_mislabeled_vram(self):
        hub = self.hub()
        hub.reclaim_vram = AsyncMock()
        with patch.object(server, "host_memory_status", return_value=HostMemory(20 * GIB, 0)), \
                patch.object(server, "free_brain_vram", AsyncMock()):
            with self.assertRaisesRegex(MemoryPressureError, "commit"):
                await hub.ensure_host_memory({"cid": "c"})

    async def test_missing_host_telemetry_does_not_unload_anything(self):
        hub = self.hub()
        hub.reclaim_vram = AsyncMock()
        with patch.object(server, "host_memory_status", return_value=None):
            await hub.ensure_host_memory({"cid": "c"})
        hub.reclaim_vram.assert_not_awaited()

    async def test_reclaim_reports_latest_headroom_not_an_old_high_water_mark(self):
        hub = self.hub()
        hub.flush_comfy_cache = AsyncMock()
        with patch.object(server, "gpu_free_bytes", side_effect=[30 * GIB, 20 * GIB, 10 * GIB]), \
                patch.object(server.asyncio, "sleep", AsyncMock()):
            self.assertEqual(await hub.reclaim_vram("test"), 10 * GIB)

    async def test_reclaim_does_not_present_stale_telemetry_as_current(self):
        hub = self.hub()
        hub.flush_comfy_cache = AsyncMock()
        with patch.object(server, "gpu_free_bytes", side_effect=[30 * GIB, None]), \
                patch.object(server.asyncio, "sleep", AsyncMock()):
            self.assertIsNone(await hub.reclaim_vram("test"))


class CalibrationTests(unittest.TestCase):
    def entry(self, **info):
        return {"template": "identity_edit", "info": info,
                "vram": {"peak": 20 * GIB, "start": 12 * GIB}}

    def test_legacy_plain_identity_size_can_be_used_but_pid_output_cannot(self):
        old = [self.entry(size="1024x1024")] * 3
        self.assertEqual(server.ledger_activation_estimate(old, "identity_edit", 1), 8 * GIB)
        old = [self.entry(size="1024x1024 (PiD 4×)")] * 3
        self.assertIsNone(server.ledger_activation_estimate(old, "identity_edit", 1))

    def test_different_models_and_batches_do_not_calibrate_each_other(self):
        rows = [self.entry(canvas_mp=1, model="large", memory_batch=1)] * 3
        self.assertIsNone(server.ledger_activation_estimate(rows, "identity_edit", 1,
                                                           context={"model": "small"}))
        self.assertIsNone(server.ledger_activation_estimate(rows, "identity_edit", 1,
                                                           context={"memory_batch": 4}))

    def test_old_history_scan_is_bounded(self):
        rows = [{}] * 256 + [self.entry(canvas_mp=1)] * 3
        self.assertIsNone(server.ledger_activation_estimate(rows, "identity_edit", 1))

    def test_larger_batches_cost_more_even_at_the_same_resolution(self):
        small = server.graph_activation_bytes("identity_edit", {}, {"canvas_mp": 1, "memory_batch": 1})
        large = server.graph_activation_bytes("identity_edit", {}, {"canvas_mp": 1, "memory_batch": 4})
        self.assertGreater(large, small)
