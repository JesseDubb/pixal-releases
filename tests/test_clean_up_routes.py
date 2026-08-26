"""Brief 9.46 — Clean up routes: measured frees, honest refusals.

/api/ram/free reports the RAM it actually handed back, and its ComfyUI call
is the node-cache reset ONLY - unload_models stays False, so the lane
weights never leave the card behind a RAM button (the full-reload cost the
comfy-free-flags note warns about is the price this button exists to pay
deliberately, never by accident). /api/desktop/reset is localhost-only (an
admin prompt on someone else's machine is never right), refuses mid-render,
and says "cancelled" when the user declines UAC. /api/comfy/free now
reports what the card handed back once the driver settles.

LIVE-MACHINE RULE: no ComfyUI, no GPU, no UAC - sessions, counters, pids,
clocks and subprocesses are all injected.
"""

import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientError


_SPEC = spec_from_file_location(
    "pixal_server_clean_up", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

GB = 2**30


class _Post:
    """aiohttp's _RequestContextManager shape: awaitable AND an async context
    manager (comfy_free does `async with s.post(...)`, ram_free awaits it)."""

    def __init__(self, status=200, exc=None):
        self.status = status
        self.exc = exc

    async def __aenter__(self):
        if self.exc:
            raise self.exc
        return self

    async def __aexit__(self, *_args):
        return None

    def __await__(self):
        async def _done():
            if self.exc:
                raise self.exc
            return self
        return _done().__await__()


class _Session:
    """Just enough aiohttp session: records posts, answers 200 to everything."""

    def __init__(self):
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def post(self, url, *, json, timeout):
        self.posts.append((url, json))
        return _Post()


def _req(peer=("127.0.0.1", 5000), headers=None):
    """A request double good enough for _is_local_peer: socket peer + headers."""
    transport = SimpleNamespace(
        get_extra_info=lambda name: peer if name == "peername" else None)
    return SimpleNamespace(transport=transport, headers=headers or {})


def _ps(stdout):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=0)


class RamFreeTests(unittest.IsolatedAsyncioTestCase):

    async def test_it_reports_what_came_back(self):
        session = _Session()
        with patch.object(server, "ram_free_bytes",
                          side_effect=[20 * GB, 23 * GB]), \
             patch.object(server.aiohttp, "ClientSession", return_value=session), \
             patch.object(server, "_nt", return_value=True), \
             patch.object(server, "_comfy_local_pids", return_value=[111]), \
             patch.object(server, "_trim_working_sets", Mock()):
            resp = await server.ram_free(None)
        body = json.loads(resp.text)
        self.assertTrue(body["ok"])
        self.assertEqual(body["freed_gb"], 3.0)

    async def test_the_comfy_call_resets_the_node_cache_only(self):
        """free_memory WITHOUT unload_models: the weights stay on the card
        (that is Free VRAM's job); what goes is the node-output CacheSet -
        the reload cost this button exists to pay on purpose."""
        session = _Session()
        with patch.object(server, "ram_free_bytes", return_value=20 * GB), \
             patch.object(server.aiohttp, "ClientSession", return_value=session), \
             patch.object(server, "_nt", return_value=False):
            resp = await server.ram_free(None)
        self.assertEqual(len(session.posts), 1)
        self.assertEqual(session.posts[0][1],
                         {"unload_models": False, "free_memory": True})
        self.assertTrue(json.loads(resp.text)["ok"])

    async def test_a_down_comfyui_still_hands_pixals_ram_back(self):
        """The node-cache reset is half the button; a dead ComfyUI must not
        keep Pixal's own heap and working set hostage."""
        class _Dead:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def post(self, url, *, json, timeout):
                return _Post(exc=ClientError("connection refused"))

        with patch.object(server, "ram_free_bytes",
                          side_effect=[20 * GB, 21 * GB]), \
             patch.object(server.aiohttp, "ClientSession", return_value=_Dead()), \
             patch.object(server, "_nt", return_value=False):
            resp = await server.ram_free(None)
        body = json.loads(resp.text)
        self.assertTrue(body["ok"])
        self.assertEqual(body["freed_gb"], 1.0)
        self.assertIn("comfy node cache kept", body["note"])

    async def test_an_unmeasurable_machine_says_so(self):
        """No number is never a fake number: the toast falls back to plain
        words instead of reporting 0.0 GB it cannot know."""
        with patch.object(server, "ram_free_bytes", return_value=None), \
             patch.object(server.aiohttp, "ClientSession",
                          return_value=_Session()), \
             patch.object(server, "_nt", return_value=False):
            resp = await server.ram_free(None)
        self.assertIsNone(json.loads(resp.text)["freed_gb"])

    async def test_pixal_and_the_comfy_pids_get_trimmed(self):
        trim = Mock()
        with patch.object(server, "ram_free_bytes", return_value=20 * GB), \
             patch.object(server.aiohttp, "ClientSession",
                          return_value=_Session()), \
             patch.object(server, "_nt", return_value=True), \
             patch.object(server, "_comfy_local_pids", return_value=[111, 222]), \
             patch.object(server, "_trim_working_sets", trim):
            await server.ram_free(None)
        (pids,), _ = trim.call_args
        import os
        self.assertEqual(pids, [os.getpid(), 111, 222])

    async def test_the_trim_is_windows_only(self):
        trim = Mock()
        with patch.object(server, "ram_free_bytes", return_value=20 * GB), \
             patch.object(server.aiohttp, "ClientSession",
                          return_value=_Session()), \
             patch.object(server, "_nt", return_value=False), \
             patch.object(server, "_trim_working_sets", trim):
            await server.ram_free(None)
        trim.assert_not_called()


class DesktopResetTests(unittest.IsolatedAsyncioTestCase):

    async def test_off_localhost_is_refused(self):
        """A keyed remote client passes the access gate - and still must
        never get an admin prompt on a machine that is not theirs."""
        resp = await server.desktop_reset(_req(peer=("192.168.1.50", 8080)))
        self.assertEqual(resp.status, 403)
        self.assertFalse(json.loads(resp.text)["ok"])

    async def test_a_proxied_localhost_is_refused(self):
        """The proxy headers mean the socket belongs to the relay, not the
        visitor - loopback proves nothing then (_is_local_peer's rule)."""
        resp = await server.desktop_reset(
            _req(headers={"X-Forwarded-For": "10.0.0.2"}))
        self.assertEqual(resp.status, 403)

    async def test_mid_render_is_refused_409(self):
        with patch.object(server, "studio_busy", return_value=True):
            resp = await server.desktop_reset(_req())
        self.assertEqual(resp.status, 409)

    async def test_a_declined_uac_says_cancelled(self):
        with patch.object(server, "studio_busy", return_value=False), \
             patch.object(server, "_nt", return_value=True), \
             patch.object(server, "_dwm_dedicated_bytes", return_value=1 * GB), \
             patch.object(server, "_powershell",
                          return_value=_ps("PX_RESET_CANCELLED")):
            resp = await server.desktop_reset(_req())
        body = json.loads(resp.text)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "cancelled")

    async def test_it_reports_what_dwm_dropped(self):
        with patch.object(server, "studio_busy", return_value=False), \
             patch.object(server, "_nt", return_value=True), \
             patch.object(server, "_dwm_dedicated_bytes",
                          side_effect=[int(2.5 * GB), int(0.8 * GB)]), \
             patch.object(server, "_powershell",
                          return_value=_ps("PX_RESET_OK")) as ps:
            resp = await server.desktop_reset(_req())
        body = json.loads(resp.text)
        self.assertTrue(body["ok"])
        self.assertAlmostEqual(body["freed_gb"], 1.7, places=1)
        # the bat runs elevated on the user's own desktop, never bare
        self.assertIn("reset_shell_vram.bat", ps.call_args[0][0])
        self.assertIn("-Verb RunAs", ps.call_args[0][0])

    async def test_a_negative_delta_never_reads_as_negative_back(self):
        """Live 2026-08-25: a fresh dwm recomposing the desktop read a touch
        higher than the trimmed baseline and the toast said "-0.0 GB back".
        Nothing came back is 0.0, never negative."""
        with patch.object(server, "studio_busy", return_value=False), \
             patch.object(server, "_nt", return_value=True), \
             patch.object(server, "_dwm_dedicated_bytes",
                          side_effect=[int(0.64 * GB), int(0.65 * GB)]), \
             patch.object(server, "_powershell",
                          return_value=_ps("PX_RESET_OK")):
            resp = await server.desktop_reset(_req())
        body = json.loads(resp.text)
        self.assertTrue(body["ok"])
        self.assertEqual(body["freed_gb"], 0.0)

    async def test_a_failed_elevation_surfaces_the_error(self):
        with patch.object(server, "studio_busy", return_value=False), \
             patch.object(server, "_nt", return_value=True), \
             patch.object(server, "_dwm_dedicated_bytes", return_value=1 * GB), \
             patch.object(server, "_powershell",
                          return_value=_ps("PX_RESET_ERROR access denied")):
            resp = await server.desktop_reset(_req())
        body = json.loads(resp.text)
        self.assertFalse(body["ok"])
        self.assertIn("access denied", body["error"])

    async def test_posix_gets_an_honest_refusal(self):
        with patch.object(server, "studio_busy", return_value=False), \
             patch.object(server, "_nt", return_value=False):
            resp = await server.desktop_reset(_req())
        self.assertEqual(resp.status, 400)
        self.assertIn("Windows-only", json.loads(resp.text)["error"])


class ComfyFreeFreedTests(unittest.IsolatedAsyncioTestCase):

    async def test_it_reports_what_the_card_handed_back(self):
        """5 GB free before, 8 once the pool settles: the toast reads 3.0 -
        and the settled read, not the one right after the POST, is what
        cudaMallocAsync is given time to finish."""
        hub = Mock()
        with patch.object(server, "gpu_free_bytes",
                          side_effect=[5 * GB] + [8 * GB] * 10), \
             patch.object(server, "VRAM_RECLAIM_POLL", 0.001), \
             patch.object(server, "VRAM_RECLAIM_DEADLINE", 0.005), \
             patch.object(server.aiohttp, "ClientSession",
                          return_value=_Session()), \
             patch.object(server, "HUB", hub):
            resp = await server.comfy_free(SimpleNamespace(can_read_body=False))
        body = json.loads(resp.text)
        self.assertTrue(body["ok"])
        self.assertEqual(body["freed_gb"], 3.0)
        hub.forget_residency.assert_called_once_with("settings freed vram")

    async def test_an_unreadable_card_reports_no_number(self):
        with patch.object(server, "gpu_free_bytes", return_value=None), \
             patch.object(server.aiohttp, "ClientSession",
                          return_value=_Session()), \
             patch.object(server, "HUB", Mock()):
            resp = await server.comfy_free(SimpleNamespace(can_read_body=False))
        body = json.loads(resp.text)
        self.assertTrue(body["ok"])
        self.assertIsNone(body["freed_gb"])

    async def test_a_dead_comfyui_is_still_a_502(self):
        class _Dead:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def post(self, url, *, json, timeout):
                return _Post(exc=ClientError("connection refused"))

        with patch.object(server, "gpu_free_bytes", return_value=5 * GB), \
             patch.object(server.aiohttp, "ClientSession", return_value=_Dead()):
            resp = await server.comfy_free(SimpleNamespace(can_read_body=False))
        self.assertEqual(resp.status, 502)


if __name__ == "__main__":
    unittest.main()
