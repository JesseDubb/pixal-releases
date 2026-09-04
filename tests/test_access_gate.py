"""The gate, and the passthrough behind it.

Both were rewritten on 2026-08-14 after a review found them open. The bugs were
not subtle and neither is the test for them: locality used to be read off the
client-supplied Host header, so `-H "Host: localhost"` walked past the gate on
every route; and /api/comfy/{tail} proxied every GET on a ComfyUI carrying ~50
node packs, several of which will read arbitrary files for you.

Every test below is a request that USED to be let through.
"""
import asyncio
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web


_SPEC = spec_from_file_location(
    "pixal_server_gate", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

KEY = "test-access-key"


def request(peer=None, headers=None, query=None, cookies=None, host="pixal.local"):
    """A fake request. `peer` is the TCP peername tuple - None means we could not
    see a socket at all, which must never be treated as local."""
    transport = SimpleNamespace(get_extra_info=lambda _k: peer) if peer else None
    return SimpleNamespace(method="GET", host=host, headers=headers or {},
                           query=query or {}, cookies=cookies or {},
                           transport=transport)


def run_gate(req):
    handler = AsyncMock(return_value=web.Response(status=204))
    with patch.object(server, "ACCESS_KEY", KEY):
        return asyncio.run(server.access_gate(req, handler)), handler


class HostHeaderSpoofTests(unittest.TestCase):
    """The live bug: request.host is the HOST HEADER, not the connection."""

    def test_a_spoofed_host_header_no_longer_passes(self):
        for host in ("localhost", "127.0.0.1", "localhost:8190", "[::1]"):
            with self.subTest(host=host):
                response, handler = run_gate(request(peer=("192.168.50.20", 51000),
                                                     host=host))
                self.assertEqual(response.status, 403)
                handler.assert_not_awaited()

    def test_a_tailscale_login_header_no_longer_passes(self):
        # Only `tailscale serve` strips these. lan_access is a bare 0.0.0.0
        # bind with nothing in front of it, so the header was caller-supplied.
        response, handler = run_gate(request(
            peer=("192.168.50.20", 51000),
            headers={"Tailscale-User-Login": "attacker@example.com"}))
        self.assertEqual(response.status, 403)
        handler.assert_not_awaited()

    def test_a_missing_transport_is_not_local(self):
        response, _ = run_gate(request(peer=None, host="localhost"))
        self.assertEqual(response.status, 403)


class LocalPeerTests(unittest.TestCase):
    def test_a_real_loopback_peer_passes_free(self):
        for addr in ("127.0.0.1", "::1", "127.0.0.53"):
            with self.subTest(addr=addr):
                response, handler = run_gate(request(peer=(addr, 51000),
                                                     host="whatever.example"))
                self.assertEqual(response.status, 204)
                handler.assert_awaited_once()

    def test_a_loopback_peer_carrying_proxy_headers_still_needs_the_key(self):
        # This is the one that makes putting a tunnel in front of Pixal safe
        # later: the proxy connects from 127.0.0.1 on behalf of the whole
        # internet, so loopback stops meaning "this machine".
        for header in ("X-Forwarded-For", "Tailscale-User-Login",
                       "CF-Connecting-IP", "Forwarded"):
            with self.subTest(header=header):
                response, handler = run_gate(request(
                    peer=("127.0.0.1", 51000), headers={header: "203.0.113.9"}))
                self.assertEqual(response.status, 403)
                handler.assert_not_awaited()

    def test_header_matching_is_case_insensitive(self):
        response, _ = run_gate(request(peer=("127.0.0.1", 51000),
                                       headers={"x-fOrWaRdEd-FoR": "203.0.113.9"}))
        self.assertEqual(response.status, 403)


class KeyedAccessTests(unittest.TestCase):
    def test_the_right_key_in_the_query_passes_and_sets_a_cookie(self):
        response, handler = run_gate(request(peer=("192.168.50.20", 51000),
                                             query={"key": KEY}))
        self.assertEqual(response.status, 204)
        handler.assert_awaited_once()
        self.assertIn("pixal_key", response.cookies)
        self.assertIn("HttpOnly", str(response.cookies["pixal_key"]))

    def test_the_cookie_alone_passes_without_re_setting_it(self):
        response, handler = run_gate(request(peer=("192.168.50.20", 51000),
                                             cookies={"pixal_key": KEY}))
        self.assertEqual(response.status, 204)
        handler.assert_awaited_once()
        self.assertNotIn("pixal_key", response.cookies)

    def test_a_wrong_or_empty_key_gets_403_with_no_hints(self):
        for query, cookies in (({"key": "wrong"}, {}), ({"key": ""}, {}),
                               ({}, {"pixal_key": "wrong"}), ({}, {})):
            with self.subTest(query=query, cookies=cookies):
                response, handler = run_gate(request(peer=("192.168.50.20", 51000),
                                                     query=query, cookies=cookies))
                self.assertEqual(response.status, 403)
                self.assertEqual(response.text, "Pixal: key required")
                handler.assert_not_awaited()

    def test_an_unset_access_key_does_not_open_the_gate(self):
        # ACCESS_KEY is minted at boot and never empty, but an empty one must
        # fail closed rather than match an empty query string.
        req = request(peer=("192.168.50.20", 51000), query={"key": ""})
        handler = AsyncMock(return_value=web.Response(status=204))
        with patch.object(server, "ACCESS_KEY", ""):
            response = asyncio.run(server.access_gate(req, handler))
        self.assertEqual(response.status, 403)
        handler.assert_not_awaited()


class ComfyPassthroughTests(unittest.TestCase):
    """It exists to serve lora-manager preview thumbs. Nothing else."""

    def comfy_get(self, tail, query=None):
        req = SimpleNamespace(match_info={"tail": tail}, query=query or {},
                              query_string="&".join(f"{k}={v}" for k, v in
                                                    (query or {}).items()))
        return asyncio.run(server.comfy_asset(req))

    def test_the_routes_that_made_this_a_file_reader_are_refused(self):
        for tail in ("getpath", "easyuse/reboot",
                     "deno/advanced/external-image-view", "view",
                     "api/lm/loras/list", "system_stats", "prompt"):
            with self.subTest(tail=tail):
                self.assertEqual(self.comfy_get(tail).status, 404)

    def test_a_preview_outside_the_model_roots_is_refused(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "models"
            (root / "loras").mkdir(parents=True)
            with patch.object(server, "model_roots", lambda *a, **k: [root]):
                for path in (r"C:\Users\Example\.aws\credentials",
                             str(root / ".." / ".." / "secret.png"),
                             str(Path(td) / "outside.jpeg"), ""):
                    with self.subTest(path=path):
                        self.assertEqual(
                            self.comfy_get("api/lm/previews",
                                           {"path": path}).status, 404)

    def test_a_preview_beside_a_model_is_allowed_through(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "models"
            loras = root / "loras"
            loras.mkdir(parents=True)
            preview = loras / "thing.jpeg"
            preview.write_bytes(b"jpeg")
            with patch.object(server, "model_roots", lambda *a, **k: [root]):
                self.assertTrue(server._preview_path_ok(str(preview)))
                # percent-encoded, the way lora-manager actually sends it
                self.assertTrue(server._preview_path_ok(
                    str(preview).replace("\\", "%5C").replace(" ", "%20")))


if __name__ == "__main__":
    unittest.main()
