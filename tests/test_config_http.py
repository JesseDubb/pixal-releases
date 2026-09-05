"""The real settings write handler against temporary storage, never a GPU."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

import server


class ConfigurationHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def _post(self, path, body):
        hooks = {name: AsyncMock() for name in ("on_start", "on_shutdown", "on_cleanup")}
        with patch.multiple(server, **hooks), patch.object(server, "CONFIG", path):
            async with TestClient(TestServer(server.create_app())) as client:
                response = await client.post("/api/settings", json=body)
                return response.status, await response.json()

    async def test_valid_save_and_invalid_value_use_existing_wire_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            code, body = await self._post(path, {"still": {"film_grain": True}})
            self.assertEqual((code, body), (200, {"ok": True}))
            self.assertTrue(json.loads(path.read_text())["still"]["film_grain"])
            original = path.read_bytes()
            code, body = await self._post(path, {"still": {"film_grain": "not a bool"}})
            self.assertEqual(code, 400)
            self.assertFalse(body["ok"])
            self.assertEqual(path.read_bytes(), original)

    async def test_corrupt_file_is_a_named_conflict_and_remains_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{incomplete", encoding="utf-8")
            code, body = await self._post(path, {"still": {"film_grain": True}})
            self.assertEqual(code, 409)
            self.assertFalse(body["ok"])
            self.assertIn("unreadable", body["error"])
            self.assertEqual(path.read_text(), "{incomplete")

    async def test_disk_failure_is_not_reported_as_a_successful_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            with patch("pixal.config.store.os.replace", side_effect=OSError("synthetic disk failure")):
                code, body = await self._post(path, {"still": {"film_grain": True}})
            self.assertEqual(code, 500)
            self.assertFalse(body["ok"])
            self.assertFalse(path.exists())

    async def test_rejected_change_does_not_retarget_engine_or_publish_brain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            with patch.object(server, "apply_comfy_url") as retarget, \
                    patch.object(server.HUB, "broadcast") as publish:
                code, _ = await self._post(path, {"comfy_url": "http://synthetic.invalid:8188",
                                                 "llm": {"model": "not committed"},
                                                 "vram_profile": "invalid"})
            self.assertEqual(code, 400)
            retarget.assert_not_called()
            publish.assert_not_called()
            self.assertFalse(path.exists())

    async def test_failed_commit_does_not_retarget_engine_or_publish_brain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            with patch("pixal.config.store.os.replace", side_effect=OSError("synthetic disk failure")), \
                    patch.object(server, "apply_comfy_url") as retarget, \
                    patch.object(server.HUB, "broadcast") as publish:
                code, _ = await self._post(path, {"comfy_url": "http://synthetic.invalid:8188",
                                                 "llm": {"model": "not committed"}})
            self.assertEqual(code, 500)
            retarget.assert_not_called()
            publish.assert_not_called()

    async def test_unrelated_save_keeps_catalog_and_metadata_warm(self):
        stamp = time.time()
        catalog = {"at": stamp, "data": []}
        metadata = {("loras", "synthetic"): {"family": "example"}}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(server, "_CATALOG", catalog), \
                patch.object(server, "_SIDECAR_META", metadata):
            code, body = await self._post(Path(tmp) / "config.json", {
                "still": {"film_grain": True}, "comfy_console": "plain"})
        self.assertEqual((code, body), (200, {"ok": True}))
        self.assertEqual(catalog["at"], stamp)
        self.assertEqual(metadata[("loras", "synthetic")], {"family": "example"})

    async def test_changed_roots_invalidate_only_after_successful_save(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.json"
                catalog, metadata = {"at": 123, "data": []}, {"synthetic": {}}
                with patch.object(server, "_CATALOG", catalog), \
                        patch.object(server, "_SIDECAR_META", metadata):
                    if fail:
                        with patch("pixal.config.store.os.replace", side_effect=OSError("disk full")):
                            code, _ = await self._post(path, {"extra_model_roots": ["synthetic"]})
                    else:
                        code, _ = await self._post(path, {"extra_model_roots": ["synthetic"]})
                self.assertEqual(code, 500 if fail else 200)
                self.assertEqual(catalog["at"], 123 if fail else 0)
                self.assertEqual(metadata, {"synthetic": {}} if fail else {})

    async def test_unchanged_roots_do_not_force_a_scan(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(server, "_CATALOG", {"at": 123, "data": []}):
            code, _ = await self._post(Path(tmp) / "config.json", {"extra_model_roots": []})
            self.assertEqual(code, 200)
            self.assertEqual(server._CATALOG["at"], 123)

    async def test_video_engine_and_model_share_one_request_local_catalog(self):
        engines = [{"id": "h3", "models": [{"id": "fl2va"}]}]
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(server, "video_engine_options", return_value=engines) as options:
            for _ in range(2):
                code, _ = await self._post(Path(tmp) / "config.json", {
                    "video": {"default_engine": "h3", "default_model": "fl2va"}})
                self.assertEqual(code, 200)
            self.assertEqual(options.call_count, 2, "one resolution per request, not per field")

    async def test_changed_engine_invalidates_catalog_and_closes_old_bridge(self):
        from types import SimpleNamespace
        ws = SimpleNamespace(closed=False, close=AsyncMock())

        def retarget(url):
            server.COMFY = url

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(server, "COMFY", "http://old.invalid:8188"), \
                patch.object(server, "apply_comfy_url", side_effect=retarget), \
                patch.object(server, "_CATALOG", {"at": 123, "data": []}), \
                patch.object(server, "_SIDECAR_META", {"synthetic": {}}), \
                patch.object(server, "_LM", {"at": 123}), \
                patch.object(server.HUB, "_ws", ws, create=True):
            code, _ = await self._post(Path(tmp) / "config.json", {
                "comfy_url": "http://new.invalid:8188"})
            self.assertEqual(code, 200)
            self.assertEqual(server._CATALOG["at"], 0)
            self.assertEqual(server._SIDECAR_META, {})
            self.assertEqual(server._LM["at"], 0)
            ws.close.assert_awaited_once()
