"""Exercise the real route factory over loopback, with no live engines."""
import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from pixal.app import LifecycleHooks, PATHS_KEY, create_app
from pixal.http.routes import HANDLER_NAMES, ROUTES
from pixal.paths import RuntimePaths

ROOT = Path(__file__).resolve().parents[1]


class ApplicationFactoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_handler_fails_at_construction(self):
        with self.assertRaisesRegex(ValueError, "Missing HTTP handlers"):
            create_app(paths=RuntimePaths.discover(ROOT), handlers={}, client_max_size=1024)

    async def test_independent_http_apps_and_hooks_do_not_share_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clients, observed = [], []
            try:
                for name in ("first", "second"):
                    calls = []
                    observed.append(calls)

                    async def handler(request, calls=calls, name=name):
                        calls.append(request.path)
                        return web.json_response({"app": name, "requests": len(calls)})

                    async def started(app, calls=calls):
                        calls.append("start")

                    async def closed(app, calls=calls):
                        calls.append("cleanup")

                    paths = RuntimePaths(ROOT, root / name, root / "engine")
                    app = create_app(paths=paths, handlers=dict.fromkeys(HANDLER_NAMES, handler),
                                     client_max_size=1024,
                                     lifecycle=LifecycleHooks(startup=(started,), cleanup=(closed,)))
                    self.assertIs(app[PATHS_KEY], paths)
                    self.assertFalse(paths.data_root.exists())
                    self.assertEqual(calls, [])
                    client = TestClient(TestServer(app))
                    clients.append(client)
                    await client.start_server()
                for name, client in zip(("first", "second"), clients):
                    response = await client.get("/api/status")
                    self.assertEqual(await response.json(), {"app": name, "requests": 2})
                self.assertEqual(observed, [["start", "/api/status"], ["start", "/api/status"]])
            finally:
                for client in clients:
                    await client.close()
            self.assertEqual([calls[-1] for calls in observed], ["cleanup", "cleanup"])

    async def test_legacy_adapter_serves_assets_and_setup_without_live_startup(self):
        import server
        hooks = {name: AsyncMock() for name in ("on_start", "on_shutdown", "on_cleanup")}
        with patch.multiple(server, **hooks):
            app = server.create_app()
        async with TestClient(TestServer(app)) as client:
            for url, prefix in (("/fonts/geist-variable-latin.woff2", b"wOF2"),
                                ("/fonts/syne-variable-latin.woff2", b"wOF2"),
                                ("/app.js", None)):
                response = await client.get(url)
                self.assertEqual(response.status, 200)
                data = await response.read()
                if prefix:
                    self.assertEqual(data[:4], prefix)
                else:
                    self.assertEqual(data, (ROOT / "web/app.js").read_bytes())
            response = await client.get("/api/setup")
            self.assertEqual(response.status, 200)
            self.assertTrue((await response.json())["needs_setup"])
            self.assertFalse(server.CONFIG.exists())
        for hook in hooks.values():
            hook.assert_awaited_once()

    async def test_wire_route_order_matches_frozen_contract(self):
        import server
        expected = json.loads((ROOT / "tests/fixtures/architecture_1_3_1b.json").read_text())
        app = server.create_app()
        actual = []
        for resource in app.router.resources():
            info = resource.get_info()
            if "directory" in info:
                actual.append({"method": "STATIC", "path": info["prefix"]})
            else:
                for route in resource:
                    if route.method != "HEAD":
                        actual.append({"method": route.method, "path": info.get("path", info.get("formatter"))})
        canonical = [{**route, "path": re.sub(r"\{(\w+):[^}]+\}", r"{\1}", route["path"])}
                     for route in expected["routes"]]
        self.assertEqual(actual, canonical)
        actual_handlers = [route.handler for route in app.router.routes()
                           if route.method != "HEAD" and "directory" not in route.resource.get_info()]
        expected_handlers = [getattr(server, spec.handler) for spec in ROUTES
                             if spec.method != "STATIC" and spec.handler != "_bundle"]
        self.assertEqual(actual_handlers[:-1], expected_handlers)

    async def test_dynamic_comfy_proxy_keeps_nested_paths(self):
        async def handler(request):
            return web.json_response(dict(request.match_info))
        app = create_app(paths=RuntimePaths.discover(ROOT),
                         handlers=dict.fromkeys(HANDLER_NAMES, handler), client_max_size=1024)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/api/comfy/a/nested/asset.js")
            self.assertEqual(await response.json(), {"tail": "a/nested/asset.js"})
