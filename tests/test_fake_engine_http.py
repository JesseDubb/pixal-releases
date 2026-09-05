"""Real HTTP handlers talking only to an ephemeral, in-process fake ComfyUI."""
import asyncio
import collections
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import server


class FakeEngineHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_compatibility_probe_and_cached_failure_use_fake_engine(self):
        requests = []
        broken = False

        async def fake_engine(request):
            requests.append((request.method, request.path))
            if request.path == "/object_info":
                if broken:
                    return web.Response(text="not JSON", status=503)
                return web.json_response({"KSampler": {"python_module": "nodes", "input": {"required": {
                    "sampler_name": [["euler"], {}], "scheduler": ["COMBO", {"options": ["simple"]}]
                }}}})
            if request.path == "/system_stats":
                return web.json_response({"system": {"comfyui_version": "synthetic-test-engine"}})
            return web.json_response({"ok": True})

        fake = web.Application()
        fake.router.add_get("/{tail:.*}", fake_engine)
        async with TestServer(fake) as engine:
            url = str(engine.make_url("/")).rstrip("/")
            hooks = {name: AsyncMock() for name in ("on_start", "on_shutdown", "on_cleanup")}
            with patch.multiple(server, **hooks), patch.object(server, "COMFY", url), \
                    patch.dict(server._COMFY_NODES, {"names": None, "modules": {}, "enums": {}, "at": 0}), \
                    patch.object(server.HUB, "comfy_up", True):
                async with TestClient(TestServer(server.create_app())) as client:
                    response = await client.get("/api/comfy/compat")
                    self.assertEqual(response.status, 200)
                    payload = await response.json()
                    self.assertEqual(payload["version"], "synthetic-test-engine")
                    self.assertTrue(payload["connected"])
                    self.assertTrue(payload["probed"])
                    self.assertEqual(server._COMFY_NODES["enums"]["KSampler"],
                                     {"sampler_name": ["euler"], "scheduler": ["simple"]})
                    await client.get("/api/comfy/compat")
                    self.assertEqual(requests.count(("GET", "/object_info")), 1)
                    broken = True
                    self.assertEqual(await server.refresh_comfy_nodes(ttl=0), frozenset({"KSampler"}))
            self.assertTrue(all(method == "GET" for method, _ in requests))
            self.assertNotIn(("POST", "/prompt"), requests)

    async def test_sse_poll_replay_resync_and_shutdown_keep_existing_contract(self):
        hub = SimpleNamespace(subs=set(), convo=[], comfy_up=True, gpu={}, scan={}, last_poll=0,
                              event_seq=42, event_log=collections.deque([
                                  {"type": "progress", "seq": 41, "value": 1},
                                  {"type": "progress", "seq": 42, "value": 2}]))
        shutdown = asyncio.Event()
        with patch.object(server, "HUB", hub), patch.object(server, "SHUTTING_DOWN", shutdown), \
                patch.object(server, "brain_badge", return_value={"label": "synthetic"}), \
                patch.object(server, "on_start", AsyncMock()), \
                patch.object(server, "on_cleanup", AsyncMock()):
            async with TestClient(TestServer(server.create_app())) as client:
                response = await client.get("/api/poll?since=41")
                self.assertEqual(await response.json(), {"seq": 42, "resync": False,
                                                         "events": [hub.event_log[-1]]})
                for cursor, resync in ((0, False), (1, True), (100, True)):
                    response = await client.get(f"/api/poll?since={cursor}")
                    payload = await response.json()
                    self.assertEqual(payload, {"seq": 42, "resync": resync, "events": [
                        {"type": "status", "comfy": True}, {"type": "brain", "label": "synthetic"}]})
                response = await client.get("/api/events")
                self.assertEqual(response.content_type, "text/event-stream")
                self.assertEqual(response.headers["X-Accel-Buffering"], "no")
                events = []
                while len(events) < 2:
                    line = await asyncio.wait_for(response.content.readline(), timeout=2)
                    if line.startswith(b"data: "):
                        events.append(json.loads(line[6:]))
                self.assertEqual(events, [{"type": "status", "comfy": True},
                                          {"type": "brain", "label": "synthetic"}])
                response.close()
            self.assertTrue(shutdown.is_set())
            self.assertEqual(hub.subs, set())
