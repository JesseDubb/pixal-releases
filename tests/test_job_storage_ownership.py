"""Publisher wire behavior and per-app event/ledger isolation without engines."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import server
from pixal.jobs.events import EventPublisher, EVENTS_KEY
from pixal.storage.ledger import Ledger, LEDGER_KEY
from pixal.lifecycle import TASKS_KEY

NAME = web.AppKey("synthetic.name", str)


class PublisherTests(unittest.TestCase):
    def test_record_lane_fanout_order_and_full_subscriber_eviction(self):
        publisher = EventPublisher(clock=lambda: 123.5)
        live, full = asyncio.Queue(), asyncio.Queue(maxsize=1)
        full.put_nowait("already full")
        publisher.subs.update((live, full))
        def lane(event):
            self.assertIs(publisher.event_log[-1], event)
            self.assertTrue(live.empty())
        publisher.broadcast(after_record=lane, type="text", text="synthetic")
        self.assertEqual(live.get_nowait(), {"type": "text", "text": "synthetic", "ts": 123.5, "seq": 1})
        self.assertEqual(publisher.subs, {live})
        for _ in range(4001):
            publisher.broadcast(after_record=lambda event: None, type="progress")
        self.assertEqual(len(publisher.event_log), 4000)
        self.assertEqual(publisher.event_log[0]["seq"], 3)

    def test_hub_keeps_lane_side_effects_and_current_lane_patch(self):
        hub = server.Hub.__new__(server.Hub)
        hub.lane_add = Mock()
        for event in ({"type": "text", "text": "words"}, {"type": "job", "job_id": "j"},
                      {"type": "review", "text": "review", "fix": "fix", "parent": "p"},
                      {"type": "error", "message": "failure"},
                      {"type": "error", "message": "job failure", "job_id": "j"},
                      {"type": "text", "text": "   "}, {"type": "progress"}):
            hub.broadcast(**event)
        self.assertEqual([c.args[0] for c in hub.lane_add.call_args_list], [
            {"role": "assistant", "text": "words"}, {"role": "job", "job_id": "j"},
            {"role": "review", "text": "review", "fix": "fix", "parent": "p"},
            {"role": "error", "text": "failure"}])
        self.assertEqual(hub.event_seq, 7)


class LedgerTests(unittest.TestCase):
    def test_crlf_unicode_own_append_tail_double_append_delete_and_external_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            first = {"id": "one", "scene": "caf\u00e9"}
            path.write_bytes((json.dumps(first, ensure_ascii=False) + "\r\nnot-json\r\n").encode("utf-8"))
            ledger = Ledger(path)
            self.assertEqual(ledger.ledger_read(), [first])
            self.assertIs(ledger.ledger_read(), ledger.ledger_read())
            ledger.ledger_append({"id": "two"})
            with patch("pixal.storage.ledger.json.loads", wraps=json.loads) as parse:
                self.assertEqual([e["id"] for e in ledger.ledger_read()], ["two", "one"])
                self.assertEqual(parse.call_count, 1, "only the own-append tail is decoded")
            ledger.ledger_append({"id": "three"})
            ledger.ledger_append({"id": "four"})
            with patch("pixal.storage.ledger.json.loads", wraps=json.loads) as parse:
                self.assertEqual([e["id"] for e in ledger.ledger_read()], ["four", "three", "two", "one"])
                self.assertEqual(parse.call_count, 5, "double append disarms tail parsing, including malformed row")
            self.assertEqual(ledger.ledger_delete("two"), {"id": "two"})
            self.assertEqual([e["id"] for e in ledger.ledger_read()], ["four", "three", "one"])
            self.assertEqual([json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()], ["one", "three", "four"])
            path.write_text('{"id":"outside-longer-row"}\n', encoding="utf-8")
            self.assertEqual(ledger.ledger_read(), [{"id": "outside-longer-row"}])
            self.assertIsNone(ledger.ledger_delete("absent"))

    def test_legacy_delete_uses_patched_read_and_path_switch_resets_cache(self):
        hub = server.Hub.__new__(server.Hub)
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "first.jsonl", Path(tmp) / "second.jsonl"
            with patch.object(server, "LEDGER", first):
                hub.ledger_append({"id": "first"})
                self.assertEqual(hub.ledger_read(), [{"id": "first"}])
                with patch.object(hub, "ledger_read", return_value=[{"id": "patched"}]) as read:
                    self.assertEqual(hub.ledger_delete("patched"), {"id": "patched"})
                    read.assert_called_once()
            with patch.object(server, "LEDGER", second):
                self.assertEqual(hub.ledger_read(), [])


class AppOwnerIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_server_apps_isolate_requests_startup_tasks_sse_and_ledger_caches(self):
        async def background(name):
            await asyncio.sleep(0)
            server.HUB.broadcast(type="synthetic", name=name)
            server.HUB.ledger_append({"id": name})
        async def started(app):
            await app[TASKS_KEY].start("synthetic", background(app[NAME] + "-startup"))
        async def publish(request):
            await asyncio.create_task(background(request.app[NAME] + "-request"))
            return web.json_response(server.HUB.ledger_read())
        async def next_event(response):
            while True:
                line = await asyncio.wait_for(response.content.readline(), timeout=2)
                if line.startswith(b"data: "):
                    return json.loads(line[6:])
                if not line:
                    return None
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(server, "on_start", started), \
                patch.object(server, "on_cleanup", AsyncMock()), \
                patch.object(server, "brain_badge", return_value={"label": "synthetic"}):
            clients, apps, streams = [], [], []
            try:
                for name in ("first", "second"):
                    with patch.object(server, "LEDGER", Path(tmp) / f"{name}.jsonl"):
                        app = server.create_app()
                    app[NAME] = name
                    app.router.add_get("/synthetic/publish", publish)
                    apps.append(app)
                    client = TestClient(TestServer(app))
                    clients.append(client)
                    await client.start_server()
                for app, client in zip(apps, clients):
                    stream = await client.get("/api/events")
                    streams.append(stream)
                    self.assertEqual((await next_event(stream))["type"], "status")
                    self.assertEqual((await next_event(stream))["type"], "brain")
                    self.assertEqual(len(app[EVENTS_KEY].subs), 1)
                    response = await client.get("/synthetic/publish")
                    self.assertEqual([row["id"] for row in await response.json()],
                                     [app[NAME] + "-request", app[NAME] + "-startup"])
                    self.assertEqual((await next_event(stream))["name"], app[NAME] + "-request")
                    response = await client.get("/api/poll?since=1")
                    payload = await response.json()
                    self.assertEqual(payload["seq"], 2)
                    self.assertEqual([event["name"] for event in payload["events"]], [app[NAME] + "-request"])
                a, b = apps
                self.assertIsNot(a[EVENTS_KEY].subs, b[EVENTS_KEY].subs)
                self.assertIsNot(a[EVENTS_KEY].event_log, b[EVENTS_KEY].event_log)
                self.assertIsNot(a[LEDGER_KEY]._ledger_cache, b[LEDGER_KEY]._ledger_cache)
                await clients[0].close()
                self.assertTrue(a[EVENTS_KEY].shutting_down.is_set())
                self.assertFalse(b[EVENTS_KEY].shutting_down.is_set())
                self.assertEqual(len(b[EVENTS_KEY].subs), 1)
                await clients[1].get("/synthetic/publish")
                self.assertEqual((await next_event(streams[1]))["seq"], 3)
            finally:
                for stream in streams:
                    stream.close()
                for client in clients:
                    await client.close()

    async def test_same_ledger_file_does_not_share_cache_or_append_marker(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, "LEDGER", Path(tmp) / "history.jsonl"):
            first, second = server.create_app(), server.create_app()
            a, b = first[LEDGER_KEY], second[LEDGER_KEY]
            a.ledger_append({"id": "one"})
            rows_a, rows_b = a.ledger_read(), b.ledger_read()
            self.assertEqual(rows_a, rows_b)
            self.assertIsNot(rows_a, rows_b)
            self.assertIsNot(rows_a[0], rows_b[0])
            a.ledger_append({"id": "two"})
            self.assertIsNotNone(a._ledger_append_from)
            self.assertIsNone(getattr(b, "_ledger_append_from", None))
            self.assertEqual(rows_b, [{"id": "one"}])
