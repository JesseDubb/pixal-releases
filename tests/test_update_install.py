"""Brief 9.24b -- a clicked update is downloaded, verified, and handed off.

No test in this module reaches the network, starts an installer, or raises a
real process signal.  The aiohttp fetch, Popen seam, and SIGINT call are all
replaced at the boundary; file work is confined to a temporary directory.
"""

import asyncio
import hashlib
import json
import shutil
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server


ROOT = Path(__file__).resolve().parent.parent
MENU_SRC = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(
    encoding="utf-8")
SERVER_SRC = (ROOT / "server.py").read_text(encoding="utf-8")

NEWER = "9.9.9z"
ASSET_NAME = f"Pixal-Setup-{NEWER}-win-x64.exe"
ASSET_URL = ("https://github.com/JesseDubb/pixal-releases/releases/download/"
             f"v{NEWER}/{ASSET_NAME}")
_DEFAULT_SHA = object()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _check(sha="a" * 64, url=ASSET_URL, *, ok=True, update=True):
    return {
        "ok": ok,
        "running": server.PIXAL_VERSION,
        "latest": NEWER,
        "update": update,
        "url": f"https://example.invalid/releases/tag/v{NEWER}",
        "sha256": sha,
        "download_url": url,
    }


class _UrlResp:
    def __init__(self, payload, status=200):
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeContent:
    def __init__(self, chunks):
        self.chunks = chunks

    def iter_chunked(self, _size):
        async def generate():
            for chunk in self.chunks:
                yield chunk
        return generate()


class _BlockingContent:
    """Yield once, then block so the cancel route can interrupt the read."""

    def __init__(self, started):
        self.started = started

    def iter_chunked(self, _size):
        async def generate():
            yield b"first chunk"
            self.started.set()
            await asyncio.Event().wait()
        return generate()


class _FakeResponse:
    def __init__(self, chunks=(), *, length=None, content=None, status=200):
        self.status = status
        self.headers = {} if length is None else {"Content-Length": str(length)}
        self.content = content or _FakeContent(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, _url, timeout=None):
        return self.response


class UpdateInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pixal-update-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.events = []
        broadcaster = mock.patch.object(
            server.HUB, "broadcast", side_effect=lambda **event: self.events.append(event))
        broadcaster.start()
        self.addCleanup(broadcaster.stop)
        if hasattr(server, "UPDATE_FETCH"):
            server.UPDATE_FETCH.update(
                task=None, cancel=None, path=None, version=None, sha256=None)

    def _body(self, response):
        return json.loads(response.text)

    def _session(self, response):
        return mock.patch.object(
            server.aiohttp, "ClientSession",
            side_effect=lambda *args, **kwargs: _FakeSession(response))

    def _seed_ready(self, payload=b"verified installer", sha=_DEFAULT_SHA):
        path = self.tmp / ASSET_NAME
        path.write_bytes(payload)
        server.UPDATE_FETCH.update(
            path=path, version=NEWER,
            sha256=_sha(payload) if sha is _DEFAULT_SHA else sha)
        return path

    def _launch_patches(self, *, busy=False):
        return (
            mock.patch.object(server, "_nt", return_value=True),
            mock.patch.object(server, "studio_busy", return_value=busy),
        )

    # The release endpoint is also the downloader's authority.  Select the
    # exact versioned installer asset, never a source archive or an exe for a
    # different version.
    def test_release_check_names_the_exact_installer_asset(self):
        payload = {
            "tag_name": f"v{NEWER}",
            "html_url": f"https://example.invalid/tag/v{NEWER}",
            "body": f"If you want to check it: sha256 `{'b' * 64}`",
            "assets": [
                {"name": "pixal-source.zip", "browser_download_url": "https://bad/zip"},
                {"name": "Pixal-Setup-1.0.0b-win-x64.exe",
                 "browser_download_url": "https://bad/old.exe"},
                {"name": ASSET_NAME, "browser_download_url": ASSET_URL},
            ],
        }
        with mock.patch.object(server.urllib.request, "urlopen",
                               return_value=_UrlResp(payload)):
            release = server._fetch_latest_release()
        self.assertEqual(release["download_url"], ASSET_URL)

    def test_release_check_does_not_guess_an_unlabelled_hash(self):
        unrelated = "c" * 64
        payload = {
            "tag_name": f"v{NEWER}",
            "html_url": f"https://example.invalid/tag/v{NEWER}",
            "body": f"unrelated source identifier `{unrelated}`",
            "assets": [{"name": ASSET_NAME, "browser_download_url": ASSET_URL}],
        }
        with mock.patch.object(server.urllib.request, "urlopen",
                               return_value=_UrlResp(payload)):
            release = server._fetch_latest_release()
        self.assertIsNone(release["sha256"])

    def test_success_replaces_part_and_marks_verified_file_ready(self):
        payload = b"installer bytes" * 100
        response = _FakeResponse([payload], length=len(payload))
        with self._session(response):
            asyncio.run(server._update_fetch_run(
                _check(_sha(payload)), asyncio.Event(), dest_dir=self.tmp))
        path = self.tmp / ASSET_NAME
        self.assertEqual(path.read_bytes(), payload)
        self.assertFalse(path.with_name(path.name + ".part").exists())
        self.assertEqual(server.UPDATE_FETCH["path"], path)
        self.assertEqual(server.UPDATE_FETCH["sha256"], _sha(payload))
        self.assertTrue(any(event.get("done") for event in self.events))

    def test_truncated_download_refuses_and_removes_part(self):
        response = _FakeResponse([b"short"], length=100)
        with self._session(response):
            asyncio.run(server._update_fetch_run(
                _check(_sha(b"short")), asyncio.Event(), dest_dir=self.tmp))
        path = self.tmp / ASSET_NAME
        self.assertFalse(path.exists())
        self.assertFalse(path.with_name(path.name + ".part").exists())
        self.assertIsNone(server.UPDATE_FETCH["path"])
        errors = [event.get("error") for event in self.events if event.get("error")]
        self.assertTrue(any("truncated" in error for error in errors), errors)

    def test_download_hash_mismatch_removes_part_and_never_marks_ready(self):
        payload = b"what the server returned"
        response = _FakeResponse([payload], length=len(payload))
        with self._session(response):
            asyncio.run(server._update_fetch_run(
                _check(_sha(b"what release notes promised")),
                asyncio.Event(), dest_dir=self.tmp))
        path = self.tmp / ASSET_NAME
        self.assertFalse(path.exists())
        self.assertFalse(path.with_name(path.name + ".part").exists())
        self.assertIsNone(server.UPDATE_FETCH["path"])
        self.assertTrue(any("sha256" in (event.get("error") or "")
                            for event in self.events))

    def test_second_download_is_a_409(self):
        async def run():
            sleeper = asyncio.create_task(asyncio.sleep(30))
            server.UPDATE_FETCH["task"] = sleeper
            try:
                with mock.patch.object(server, "_nt", return_value=True):
                    return await server.update_download_post(None)
            finally:
                sleeper.cancel()
                try:
                    await sleeper
                except asyncio.CancelledError:
                    pass

        response = asyncio.run(run())
        self.assertEqual(response.status, 409)
        self.assertFalse(self._body(response)["ok"])

    def test_download_refuses_an_unknown_or_unparseable_hash(self):
        for bad_hash in (None, "not-a-sha256", "a" * 63):
            with self.subTest(sha256=bad_hash), \
                    mock.patch.object(server, "_nt", return_value=True), \
                    mock.patch.object(server, "update_check",
                                      return_value=_check(bad_hash)):
                response = asyncio.run(server.update_download_post(None))
            self.assertEqual(response.status, 400)
            self.assertFalse(self._body(response)["ok"])
            self.assertIsNone(server.UPDATE_FETCH["task"])

    def test_download_is_windows_only(self):
        with mock.patch.object(server, "_nt", return_value=False), \
                mock.patch.object(server, "update_check",
                                  side_effect=AssertionError("network reached")):
            response = asyncio.run(server.update_download_post(None))
        self.assertEqual(response.status, 400)
        self.assertFalse(self._body(response)["ok"])

    def test_cancel_mid_download_removes_part_and_all_transient_state(self):
        async def run():
            started = asyncio.Event()
            response = _FakeResponse(
                length=100, content=_BlockingContent(started))
            with self._session(response), \
                    mock.patch.object(server, "_nt", return_value=True), \
                    mock.patch.object(server, "update_check",
                                      return_value=_check(_sha(b"unused"))), \
                    mock.patch.object(server, "UPDATE_DIR", self.tmp):
                accepted = await server.update_download_post(None)
                self.assertTrue(self._body(accepted)["ok"])
                await asyncio.wait_for(started.wait(), timeout=1)
                cancelled = await server.update_cancel_post(None)
                return cancelled

        response = asyncio.run(run())
        path = self.tmp / ASSET_NAME
        self.assertTrue(self._body(response)["ok"])
        self.assertFalse(path.exists())
        self.assertFalse(path.with_name(path.name + ".part").exists())
        for key in ("task", "cancel", "path", "version", "sha256"):
            self.assertIsNone(server.UPDATE_FETCH[key], key)
        self.assertTrue(any(event.get("cancelled") for event in self.events))
        self.assertFalse(any(event.get("error") for event in self.events))

    def test_cancel_discards_a_ready_installer_and_is_idempotent(self):
        path = self._seed_ready()
        first = asyncio.run(server.update_cancel_post(None))
        second = asyncio.run(server.update_cancel_post(None))
        self.assertTrue(self._body(first)["ok"])
        self.assertTrue(self._body(second)["ok"])
        self.assertFalse(path.exists())
        self.assertIsNone(server.UPDATE_FETCH["path"])

    def test_update_refuses_while_studio_is_busy(self):
        path = self._seed_ready()
        nt, busy = self._launch_patches(busy=True)
        with nt, busy, mock.patch.object(server, "_update_spawn") as spawn:
            response = asyncio.run(server.update_launch_post(None))
        self.assertEqual(response.status, 409)
        self.assertFalse(self._body(response)["ok"])
        spawn.assert_not_called()
        self.assertTrue(path.exists())

    def test_launch_refuses_when_nothing_is_ready(self):
        nt, busy = self._launch_patches()
        with nt, busy, mock.patch.object(server, "_update_spawn") as spawn:
            response = asyncio.run(server.update_launch_post(None))
        self.assertEqual(response.status, 400)
        spawn.assert_not_called()

    def test_hash_mismatch_deletes_file_and_launches_nothing(self):
        path = self._seed_ready(payload=b"bytes on disk",
                                sha=_sha(b"bytes promised"))
        nt, busy = self._launch_patches()
        with nt, busy, mock.patch.object(server, "_update_spawn") as spawn, \
                mock.patch.object(server.signal, "raise_signal") as raised:
            response = asyncio.run(server.update_launch_post(None))
        self.assertEqual(response.status, 400)
        self.assertFalse(path.exists())
        self.assertIsNone(server.UPDATE_FETCH["path"])
        spawn.assert_not_called()
        raised.assert_not_called()

    def test_unknown_or_unparseable_ready_hash_is_deleted_not_run_anyway(self):
        for bad_hash in (None, "unknown", "f" * 63):
            with self.subTest(sha256=bad_hash):
                path = self._seed_ready(sha=bad_hash)
                nt, busy = self._launch_patches()
                with nt, busy, mock.patch.object(server, "_update_spawn") as spawn:
                    response = asyncio.run(server.update_launch_post(None))
                self.assertEqual(response.status, 400)
                self.assertFalse(path.exists())
                spawn.assert_not_called()

    def test_launch_is_windows_only(self):
        self._seed_ready()
        with mock.patch.object(server, "_nt", return_value=False), \
                mock.patch.object(server, "_update_spawn") as spawn:
            response = asyncio.run(server.update_launch_post(None))
        self.assertEqual(response.status, 400)
        spawn.assert_not_called()

    def test_spawn_precedes_delayed_exit_and_response_returns_first(self):
        path = self._seed_ready()
        calls = []

        async def run():
            loop = asyncio.get_running_loop()
            scheduled = []
            nt, busy = self._launch_patches()
            with nt, busy, \
                    mock.patch.object(server, "_update_spawn",
                                      side_effect=lambda exe: calls.append(("spawn", exe))), \
                    mock.patch.object(server.signal, "raise_signal",
                                      side_effect=lambda sig: calls.append(("signal", sig))), \
                    mock.patch.object(loop, "call_later",
                                      side_effect=lambda delay, fn, *args:
                                      scheduled.append((delay, fn, args))):
                response = await server.update_launch_post(None)
            self.assertEqual([kind for kind, _value in calls], ["spawn"])
            self.assertTrue(self._body(response)["ok"])
            self.assertEqual(len(scheduled), 1)
            delay, fn, args = scheduled[0]
            self.assertEqual(delay, 0.75)
            fn(*args)
            return response

        response = asyncio.run(run())
        self.assertTrue(self._body(response)["ok"])
        self.assertEqual(calls, [("spawn", path), ("signal", signal.SIGINT)])

    def test_keep_comfy_sentinel_is_not_written_on_update_path(self):
        self._seed_ready()
        sentinel = self.tmp / ".pixal_keep_comfy"
        nt, busy = self._launch_patches()
        with nt, busy, mock.patch.object(server, "KEEP_COMFY", sentinel), \
                mock.patch.object(server, "_update_spawn"), \
                mock.patch.object(server.signal, "raise_signal"):
            asyncio.run(server.update_launch_post(None))
        self.assertFalse(sentinel.exists())

    def test_installer_is_launched_visibly_without_silent_flags(self):
        path = self.tmp / ASSET_NAME
        path.write_bytes(b"MZ")
        with mock.patch.object(server.subprocess, "Popen") as popen:
            server._update_spawn(path)
        popen.assert_called_once()
        argv = popen.call_args.args[0]
        self.assertEqual(argv, [str(path)])
        self.assertFalse(any("silent" in str(arg).lower() for arg in argv))

    def test_update_routes_are_registered(self):
        for route in ("/api/update/download", "/api/update/cancel",
                      "/api/update/launch"):
            self.assertIn(f'"{route}"', SERVER_SRC)

    def test_about_tab_is_advisory_only(self):
        """The About slot names the release and links to it - nothing more.

        Removed 2026-09-04: the in-app download-and-run-the-installer control.
        Handing the user a wizard meant killing the sidecar AND ComfyUI before
        the install had started, so a cancelled or failed wizard left a dead
        studio with no way back. Until an update can install itself and bring
        Pixal back on its own, the panel does not offer to try.
        """
        self.assertIn("/api/update-check", MENU_SRC)
        self.assertIn("Get Pixal ", MENU_SRC)          # the release link
        for gone in ("/api/update/download", "/api/update/cancel",
                     "/api/update/launch", "update_fetch", "AboutUpdate",
                     "px-about-update"):
            self.assertNotIn(gone, MENU_SRC)


if __name__ == "__main__":
    unittest.main()
