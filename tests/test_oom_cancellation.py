"""Stop owns pending OOM recovery, including its handoff into a new job.

All engine operations are fake. These tests must never interrupt the studio.
"""
import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from test_identity_build import server


class Response:
    status = 200

    def __init__(self, payload=None, barrier=None):
        self.payload, self.barrier = payload, barrier

    async def json(self):
        if self.barrier:
            await self.barrier.wait()
        return self.payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def __await__(self):
        async def ready():
            return self
        return ready().__await__()


class Session:
    def __init__(self, running=(), prompt_barrier=None):
        self.running, self.posts = list(running), []
        self.prompt_barrier = prompt_barrier
        self.prompt_started = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, json=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        self.posts.append((endpoint, json))
        if endpoint == "prompt":
            self.running = ["late-prompt"]
            self.prompt_started.set()
            return Response({"prompt_id": "late-prompt"}, self.prompt_barrier)
        if endpoint == "interrupt":
            self.running = []
        return Response({})

    def get(self, url, **kwargs):
        return Response({"queue_running": [[0, pid, {}] for pid in self.running],
                         "queue_pending": []})


class RecoveryCancellationTests(unittest.IsolatedAsyncioTestCase):
    def make_hub(self):
        hub = server.Hub.__new__(server.Hub)
        job = {"id": "failed", "cid": "test", "template": "identity_edit",
               "scene": "synthetic portrait", "seed": 7, "count": 1,
               "started": time.time(), "images": [], "prompt_ids": [],
               "finalized": True, "error": "CUDA out of memory", "_oom_pending": True}
        hub.jobs, hub.queue_remaining = {job["id"]: job}, 0
        hub.by_prompt, hub.client_id = {}, "test-client"
        hub.prev_job_free_min = None
        hub.broadcast, hub.forget_residency = Mock(), Mock()
        hub.finalize = Mock(side_effect=lambda j: j.update(finalized=True))
        hub.cancel_siblings, hub.reclaim_vram = AsyncMock(), AsyncMock(return_value=30 * 2**30)
        hub.oom_retry_plan = lambda j: ({"mp": 1}, "at 1MP")
        hub.submit = AsyncMock()
        self.addCleanup(patch.stopall)
        patch.object(server, "HUB", hub).start()
        self.brain = patch.object(server, "free_brain_vram", AsyncMock(return_value=False)).start()
        self.session = Session()
        patch.object(server.aiohttp, "ClientSession", return_value=self.session).start()
        return hub, job

    async def stop(self, job_id="failed"):
        body = {} if job_id is None else {"job_id": job_id}
        response = await server.stop(SimpleNamespace(json=AsyncMock(return_value=body)))
        return json.loads(response.text)

    async def test_stop_before_recovery_starts_prevents_all_work(self):
        hub, job = self.make_hub()
        task = asyncio.create_task(hub.retry_after_oom(job))
        self.assertEqual((await self.stop())["stopped"], 1)
        await task
        hub.cancel_siblings.assert_not_awaited()
        hub.reclaim_vram.assert_not_awaited()
        self.brain.assert_not_awaited()
        hub.submit.assert_not_awaited()
        self.assertFalse(job["_oom_pending"])
        self.assertEqual(self.session.posts, [])

    async def test_stop_while_recovery_waits_for_other_render(self):
        hub, job = self.make_hub()
        hub.queue_remaining = 1
        task = asyncio.create_task(hub.retry_after_oom(job))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertEqual((await self.stop())["stopped"], 1)
        await asyncio.wait_for(task, 2)
        self.assertFalse(hub._memory_lock.locked())
        hub.reclaim_vram.assert_not_awaited()
        hub.submit.assert_not_awaited()
        self.assertEqual(self.session.posts, [], "Stop must not interrupt the other render")

    async def test_stop_while_recovery_waits_for_admission_lock(self):
        hub, job = self.make_hub()
        hub._memory_lock = asyncio.Lock()
        await hub._memory_lock.acquire()
        task = asyncio.create_task(hub.retry_after_oom(job))
        await asyncio.sleep(0)
        await self.stop()
        self.assertTrue(hub._memory_lock.locked(), "Stop must not release another owner's lock")
        hub._memory_lock.release()
        await asyncio.wait_for(task, 2)
        hub.reclaim_vram.assert_not_awaited()
        hub.submit.assert_not_awaited()

    async def test_stop_during_cleanup_prevents_brain_rest_and_retry(self):
        hub, job = self.make_hub()
        entered, release = asyncio.Event(), asyncio.Event()

        async def cleanup(*args, **kwargs):
            entered.set()
            await release.wait()
        hub.reclaim_vram = AsyncMock(side_effect=cleanup)
        task = asyncio.create_task(hub.retry_after_oom(job))
        await asyncio.wait_for(entered.wait(), 2)
        await self.stop()
        release.set()
        await task
        self.brain.assert_not_awaited()
        hub.submit.assert_not_awaited()
        self.assertFalse(hub._memory_lock.locked())

    async def test_stop_during_brain_rest_prevents_retry(self):
        hub, job = self.make_hub()
        entered, release = asyncio.Event(), asyncio.Event()

        async def rest():
            entered.set()
            await release.wait()
            return True
        self.brain.side_effect = rest
        task = asyncio.create_task(hub.retry_after_oom(job))
        await asyncio.wait_for(entered.wait(), 2)
        await self.stop()
        release.set()
        await task
        hub.submit.assert_not_awaited()
        self.assertEqual(job["error"], "stopped")

    async def test_stop_all_cancels_pending_recovery_without_orphan_interrupt(self):
        hub, job = self.make_hub()
        self.assertEqual((await self.stop(None))["stopped"], 1)
        await hub.retry_after_oom(job)
        hub.submit.assert_not_awaited()
        self.assertEqual(self.session.posts, [])

    async def test_completed_job_without_recovery_remains_a_noop(self):
        hub, job = self.make_hub()
        job["_oom_pending"] = False
        self.session.running = ["unrelated"]
        self.assertEqual((await self.stop())["stopped"], 0)
        self.assertEqual(self.session.posts, [])

    async def test_original_stop_reaches_retry_child_after_handoff(self):
        hub, job = self.make_hub()
        job["_oom_pending"] = False
        child = {"id": "child", "cid": "test", "prompt_ids": ["child-prompt"],
                 "_oom_retry_of": "failed", "finalized": False}
        hub.jobs["child"] = child
        self.session.running = ["unrelated"]
        self.assertEqual((await self.stop())["stopped"], 1)
        self.assertTrue(child["finalized"])
        self.assertIn(("queue", {"delete": ["child-prompt"]}), self.session.posts)
        self.assertFalse(any(endpoint == "interrupt" for endpoint, _ in self.session.posts))

    async def test_retry_child_stop_also_cancels_its_pending_origin(self):
        hub, job = self.make_hub()
        hub.jobs["child"] = {"id": "child", "cid": "test", "prompt_ids": [],
                             "_oom_retry_of": "failed", "finalized": False}
        self.assertEqual((await self.stop("child"))["stopped"], 1)
        self.assertTrue(job["_oom_cancelled"])

    async def test_finalize_registers_pending_recovery_before_scheduling(self):
        hub, job = self.make_hub()
        job.pop("finalized")
        job.pop("_oom_pending")
        server.Hub.finalize(hub, job)
        self.assertTrue(job["_oom_pending"])
        await self.stop()
        await asyncio.sleep(0)
        hub.submit.assert_not_awaited()
        hub.reclaim_vram.assert_not_awaited()

    async def test_successful_recovery_still_submits_exactly_once(self):
        hub, job = self.make_hub()
        await hub.retry_after_oom(job)
        hub.submit.assert_awaited_once()
        self.assertEqual(hub.submit.call_args.kwargs["flags"], {
            "_oom_retry": True, "_oom_retry_of": "failed"})
        self.assertFalse(job["_oom_pending"])
        self.assertFalse(hub._memory_lock.locked())

    async def test_cancelled_origin_cannot_create_a_retry_card(self):
        hub, job = self.make_hub()
        job["_oom_cancelled"] = True
        child = await server.Hub.submit(hub, "test", "reroll", "identity_edit",
                                      "A quiet portrait.", {"seed": 7},
                                      flags={"_oom_retry": True, "_oom_retry_of": "failed"})
        self.assertEqual(child["error"], "stopped")
        self.assertTrue(child["finalized"])
        self.assertEqual(self.session.posts, [])
        self.assertFalse(any(c.kwargs.get("type") == "job" for c in hub.broadcast.call_args_list))

    async def test_stop_while_prompt_ack_is_pending_cancels_late_receipt(self):
        hub, job = self.make_hub()
        release = asyncio.Event()
        self.session.prompt_barrier = release
        hub.ensure_host_memory, hub.ensure_vram, hub.watch = AsyncMock(), AsyncMock(), AsyncMock()
        graph = {"latent": {"class_type": "EmptyLatentImage", "inputs": {
            "width": 512, "height": 512, "batch_size": 1}}}
        with patch.dict(server.BUILDERS, {"identity_edit": lambda *a, **k: (graph, "test", {})}), \
                patch.object(server, "validate_job_model_info"), \
                patch.object(server, "apply_special_decoder"):
            task = asyncio.create_task(server.Hub.submit(
                hub, "test", "reroll", "identity_edit", "A quiet portrait.", {"seed": 7},
                flags={"_oom_retry": True, "_oom_retry_of": "failed"}))
            await asyncio.wait_for(self.session.prompt_started.wait(), 2)
            await self.stop()
            release.set()
            child = await task
        self.assertEqual(child["error"], "stopped")
        self.assertIn(("queue", {"delete": ["late-prompt"]}), self.session.posts)
        self.assertIn(("interrupt", None), self.session.posts)
        self.assertFalse(hub._memory_lock.locked())
        hub.watch.assert_not_awaited()
