"""The DLSS 5 runtime seat - /api/dlss5/dll (2026-09-01).

Pixal can neither bundle the NR runtime nor download it from anywhere:
NVIDIA has not released DLSS 5, and the one public build is extracted
from a game's early-access files (briefs/QUEUE.md addendum 2026-09-01).
What the app CAN do is take the USER'S OWN copy and do the annoying
part - stream it into the node pack's runtime folder, sha-256 it on the
way, and tell the truth about what arrived:

  fingerprint - name, size and sha of the known 310.8.0.0 build are
                pinned constants; the sha decides VERIFIED vs
                unrecognized, never accept vs refuse, because a future
                official build must not be turned away for failing to
                match a game's.
  endpoint    - refuses when the node pack is absent (a DLL with no
                bridge is a file, not a feature), refuses a wrong
                filename and an implausibly small file, streams through
                a .part so a dropped upload never leaves a half-written
                runtime, and cleans the .part on every exit.
  settings    - the still slot carries dlss5_node and dlss5_dll
                separately, so the row can offer the RIGHT fix.
  row         - Settings' DLSS row offers Add DLL only when the pack is
                there and the DLL is not.

Same sanctioned simulation as every sibling file: fake multipart
requests, stubbed config, no server, no ComfyUI, no GPU.
"""

import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_dlss5_dll", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

SRC = (ROOT / "server.py").read_text(encoding="utf-8")
UI = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx") \
    .read_text(encoding="utf-8")


class Fingerprint(unittest.TestCase):
    """The known-good build's identity, pinned so a drive-by edit shows."""

    def test_the_constants_are_the_310_8_build(self):
        self.assertEqual(server.DLSS5_DLL_NAME, "nvngx_dlssnr.dll")
        self.assertEqual(server.DLSS5_DLL_SIZE, 165_840_496)
        self.assertEqual(server.DLSS5_DLL_SHA256,
                         "e16bcf15e16e13f527491cdf7845b2fe"
                         "6521a738d8f7c9c721866a8496e1fc8e")
        self.assertEqual(server.DLSS5_DLL_VERSION, "310.8.0.0")
        self.assertLess(server.DLSS5_DLL_MIN_BYTES, server.DLSS5_DLL_SIZE)
        self.assertLess(server.DLSS5_DLL_SIZE, server.DLSS5_DLL_MAX_BYTES)

    def test_the_verdict_names_and_sizes_before_it_veresigns(self):
        err, _ = server.dlss5_dll_verdict("nvngx_dlss.dll", 10, "x")
        self.assertIn("named nvngx_dlssnr.dll", err)
        err, _ = server.dlss5_dll_verdict("nvngx_dlssnr.dll", 1_000_000, "x")
        self.assertIn("MB", err)

    def test_the_sha_decides_verified_never_refusal(self):
        # exact build: verified
        err, verified = server.dlss5_dll_verdict(
            "NVNGX_DLSSNR.DLL", server.DLSS5_DLL_SIZE, server.DLSS5_DLL_SHA256)
        self.assertIsNone(err)
        self.assertTrue(verified)
        # plausible but unknown build: seated, not verified, not refused
        err, verified = server.dlss5_dll_verdict(
            "nvngx_dlssnr.dll", 200_000_000, "f" * 64)
        self.assertIsNone(err)
        self.assertFalse(verified)


class _Field:
    def __init__(self, name, filename, data):
        self.name = name
        self.filename = filename
        self._chunks = [data[i:i + 4096] for i in range(0, len(data), 4096)]

    async def read_chunk(self, _n=None):
        return self._chunks.pop(0) if self._chunks else b""

    async def release(self):
        pass


class _Reader:
    def __init__(self, fields):
        self._fields = list(fields)

    async def next(self):
        return self._fields.pop(0) if self._fields else None


class _Request:
    def __init__(self, fields):
        self._fields = fields

    async def multipart(self):
        return _Reader(self._fields)


def _seat(root, fields):
    with patch.object(server, "CDIR", root):
        response = asyncio.run(server.dlss5_dll(_Request(fields)))
    return response.status, json.loads(response.text)


def _node_dir(root):
    d = root / "custom_nodes" / "ComfyUI-DLSS5-NR"
    d.mkdir(parents=True)
    return d


class Endpoint(unittest.TestCase):

    def test_no_node_pack_is_a_400_that_says_so(self):
        with TemporaryDirectory() as td:
            status, out = _seat(Path(td),
                                [_Field("dll", "nvngx_dlssnr.dll", b"x")])
            self.assertEqual(status, 400)
            self.assertIn("node pack", out["error"])

    def test_a_wrong_filename_is_refused_and_nothing_is_written(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _node_dir(root)
            status, out = _seat(root, [_Field("dll", "nvngx_dlss.dll",
                                              b"y" * 100)])
            self.assertEqual(status, 400)
            self.assertIn("nvngx_dlssnr.dll", out["error"])
            runtime = root / "custom_nodes" / "ComfyUI-DLSS5-NR" / "runtime"
            self.assertEqual(sorted(p.name for p in runtime.glob("*")), [],
                             "a refused upload left a file behind")

    def test_the_known_build_seats_verified(self):
        data = b"K" * 4097          # spans chunks, so the stream hash is real
        import hashlib
        sha = hashlib.sha256(data).hexdigest()
        with TemporaryDirectory() as td:
            root = Path(td)
            _node_dir(root)
            with patch.object(server, "DLSS5_DLL_MIN_BYTES", 10), \
                 patch.object(server, "DLSS5_DLL_SIZE", len(data)), \
                 patch.object(server, "DLSS5_DLL_SHA256", sha):
                status, out = _seat(root, [_Field("meta", None, b""),
                                           _Field("dll", "nvngx_dlssnr.dll",
                                                  data)])
            self.assertEqual(status, 200)
            self.assertEqual(out, {"ok": True, "verified": True,
                                   "size": len(data), "sha256": sha,
                                   "version": server.DLSS5_DLL_VERSION})
            dest = (root / "custom_nodes" / "ComfyUI-DLSS5-NR" / "runtime"
                    / "nvngx_dlssnr.dll")
            self.assertEqual(dest.read_bytes(), data)
            self.assertFalse(dest.with_name(dest.name + ".part").exists(),
                             "the staging .part outlived the seat")

    def test_an_unknown_build_seats_unverified_with_no_version_claim(self):
        data = b"U" * 5000
        with TemporaryDirectory() as td:
            root = Path(td)
            _node_dir(root)
            with patch.object(server, "DLSS5_DLL_MIN_BYTES", 10):
                status, out = _seat(root, [_Field("dll", "nvngx_dlssnr.dll",
                                                  data)])
            self.assertEqual(status, 200)
            self.assertIs(out["verified"], False)
            self.assertIsNone(out["version"],
                              "an unrecognized build must not wear 310.8.0.0")

    def test_an_oversize_stream_is_cut_and_cleaned(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _node_dir(root)
            with patch.object(server, "DLSS5_DLL_MAX_BYTES", 4096):
                status, out = _seat(root, [_Field("dll", "nvngx_dlssnr.dll",
                                                  b"z" * 10_000)])
            self.assertEqual(status, 413)
            runtime = root / "custom_nodes" / "ComfyUI-DLSS5-NR" / "runtime"
            self.assertEqual(sorted(p.name for p in runtime.glob("*")), [])

    def test_the_route_is_registered(self):
        self.assertIn('app.router.add_post("/api/dlss5/dll", dlss5_dll)', SRC)


class SettingsFlags(unittest.TestCase):
    """The still slot says WHICH half is missing - one flag cannot."""

    def get_still(self, root):
        cfg = {"llm": {"base_url": "", "model": ""}, "critic": {"model": ""},
               "upscale": {}, "edit": {}, "vae": {}, "pid": {},
               "video": {"default_engine": "", "default_model": ""},
               "still": {}, "extra_model_roots": [], "comfy_editor": False,
               "comfy_console": "tui", "explicit": "auto",
               "vram_profile": "auto"}
        patches = [patch.object(server, "load_config", return_value=cfg),
                   patch.object(server, "model_catalog", return_value=[]),
                   patch.object(server, "_video_asset",
                                side_effect=lambda _k, rel: rel),
                   patch.object(server, "refresh_comfy_nodes", AsyncMock()),
                   patch.dict(server._COMFY_NODES, {"names": frozenset()}),
                   patch.object(server, "CDIR", root)]
        for p in patches:
            p.start()
        try:
            class _R:
                async def json(self):
                    return {}
            response = asyncio.run(server.settings_get(_R()))
        finally:
            for p in patches:
                p.stop()
        return json.loads(response.text)["still"]

    def test_node_and_dll_report_separately(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            still = self.get_still(root)
            self.assertIs(still["dlss5_node"], False)
            self.assertIs(still["dlss5_dll"], False)
            runtime = _node_dir(root) / "runtime"
            still = self.get_still(root)
            self.assertIs(still["dlss5_node"], True)
            self.assertIs(still["dlss5_dll"], False)
            runtime.mkdir()
            (runtime / "nvngx_dlssnr.dll").write_bytes(b"dll")
            still = self.get_still(root)
            self.assertIs(still["dlss5_dll"], True)


class SettingsRow(unittest.TestCase):
    """The row offers the RIGHT fix, in the panel's own words."""

    def test_the_row_offers_add_dll_only_when_the_pack_is_there(self):
        self.assertIn("!stillCfg.dlss5_available && stillCfg.dlss5_node", UI)
        self.assertIn(">Add DLL<", UI.replace("\n", "").replace(" ", "")
                      .replace('{dllBusy?"Checking…":"AddDLL"}', ">Add DLL<"),
                      "the Add DLL affordance is gone")

    def test_the_hints_split_by_missing_half(self):
        self.assertIn('"Bring your own nvngx_dlssnr.dll · 158 MB"', UI)
        self.assertIn('"Install the ComfyUI-DLSS5-NR node pack"', UI)

    def test_the_picker_posts_to_the_seat_endpoint(self):
        self.assertIn('fetch("/api/dlss5/dll"', UI)
        self.assertIn('accept=".dll"', UI)

    def test_the_toast_says_verified_or_tells_the_truth(self):
        self.assertIn("DLSS 5 runtime verified", UI)
        self.assertIn("unrecognized build, may not run", UI)


if __name__ == "__main__":
    unittest.main()
