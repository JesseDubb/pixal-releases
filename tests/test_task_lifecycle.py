import asyncio
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from pixal.app import LifecycleHooks, create_app
from pixal.http.routes import HANDLER_NAMES
from pixal.lifecycle import TASKS_KEY, TaskOwner
from pixal.paths import RuntimePaths

ROOT = Path(__file__).resolve().parents[1]


class TaskLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_active_name_is_rejected(self):
        owner = TaskOwner()
        owner.start("same", asyncio.sleep(60))
        with self.assertRaises(RuntimeError):
            owner.start("same", asyncio.sleep(60))
        await owner.close()

    async def test_shutdown_deadline_reports_a_cancellation_resistant_task(self):
        owner = TaskOwner()
        entered, release = asyncio.Event(), asyncio.Event()
        async def stubborn():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
        task = owner.start("stubborn", stubborn())
        await entered.wait()
        try:
            with self.assertLogs("pixal.lifecycle", level="ERROR"):
                self.assertEqual(await owner.close(timeout=0.01), ("pixal:stubborn",))
        finally:
            release.set()
            await task

    async def test_close_awaits_finalizers_and_rejects_new_work(self):
        owner = TaskOwner()
        entered, finished = asyncio.Event(), asyncio.Event()

        async def worker():
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                finished.set()

        task = owner.start("test", worker())
        await entered.wait()
        self.assertEqual(await owner.close(), ())
        self.assertTrue(task.cancelled())
        self.assertTrue(finished.is_set())
        with self.assertRaises(RuntimeError):
            owner.start("late", worker())
        self.assertEqual(await owner.close(), ())

    async def test_failure_is_logged_without_cancelling_unrelated_task(self):
        owner = TaskOwner()
        staying = owner.start("staying", asyncio.sleep(60))

        async def fail():
            raise ValueError("synthetic failure")

        with self.assertLogs("pixal.lifecycle", level="ERROR") as logs:
            failed = owner.start("failing", fail())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        self.assertTrue(failed.done())
        self.assertIn("synthetic failure", "\n".join(logs.output))
        self.assertFalse(staying.done())
        await owner.close()

    async def test_application_cleanup_owns_startup_tasks(self):
        finished = asyncio.Event()
        entered = asyncio.Event()

        async def worker():
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                finished.set()

        async def startup(app):
            app[TASKS_KEY].start("test", worker())
            await entered.wait()

        async def handler(request):
            return web.json_response({"ok": True})

        app = create_app(paths=RuntimePaths.discover(ROOT),
                         handlers=dict.fromkeys(HANDLER_NAMES, handler), client_max_size=1024,
                         lifecycle=LifecycleHooks(startup=(startup,)))
        async with TestClient(TestServer(app)) as client:
            self.assertEqual((await client.get("/api/status")).status, 200)
        self.assertTrue(finished.is_set())
