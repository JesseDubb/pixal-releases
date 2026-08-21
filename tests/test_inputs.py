import asyncio
import json
import os
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image


_SPEC = spec_from_file_location(
    "pixal_server_inputs", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


class FakeField:
    def __init__(self, data, filename="reference.png", name="image"):
        self._data = data
        self.filename = filename
        self.name = name
        self.headers = {"Content-Type": "image/png"}

    async def read(self):
        return self._data

    async def text(self):
        return self._data.decode() if isinstance(self._data, bytes) else str(self._data)

    async def release(self):
        return None


class FakeReader:
    def __init__(self, fields):
        self.fields = list(fields if isinstance(fields, (list, tuple)) else [fields])

    async def next(self):
        return self.fields.pop(0) if self.fields else None


class FakeRequest:
    def __init__(self, field):
        self.reader = FakeReader(field)

    async def multipart(self):
        return self.reader


class FakeResponse:
    def __init__(self, body, status=200, text=""):
        self.body = body
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self, **_kwargs):
        return self.body

    async def text(self):
        return self._text


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.form = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def post(self, _url, *, data, timeout):
        self.form = data
        self.timeout = timeout
        return self.response


class InputLibraryTests(unittest.TestCase):
    def test_nested_input_names_are_safe_and_traversal_is_rejected(self):
        with TemporaryDirectory() as td, patch.object(server, "CDIR", Path(td)):
            self.assertEqual(server.input_ref_name(r"portraits\summer\face + 1%.jpg"),
                             "portraits/summer/face + 1%.jpg")
            self.assertEqual(server.input_ref_name("input/face.png"), "face.png")
            for unsafe in ("", ".", "..", "../face.png", "portraits/../face.png",
                           "/absolute.png", "C:/outside.png", "folder//face.png"):
                with self.subTest(unsafe=unsafe):
                    self.assertEqual(server.input_ref_name(unsafe), "")

    def test_catalog_is_recursive_complete_and_newest_first(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            inputs = root / "input"
            nested = inputs / "portraits" / "summer"
            nested.mkdir(parents=True)
            oldest = inputs / "old.png"
            middle = inputs / "camera.jfif"
            newest = nested / "face + 1%.jpg"
            ignored = inputs / "notes.txt"
            for path in (oldest, middle, newest, ignored):
                path.write_bytes(b"test")
            os.utime(oldest, (10, 10))
            os.utime(middle, (20, 20))
            os.utime(newest, (30, 30))

            with patch.object(server, "CDIR", root), \
                 patch.object(server, "INPUT_REF_TYPES", {
                     "portraits/summer/face + 1%.jpg": "identity",
                     "camera.jfif": "style",
                 }):
                catalog = server.input_image_catalog()

        self.assertEqual([item["name"] for item in catalog], [
            "portraits/summer/face + 1%.jpg", "camera.jfif", "old.png",
        ])
        self.assertEqual(catalog[0]["filename"], "face + 1%.jpg")
        self.assertEqual(catalog[0]["subfolder"], "portraits/summer")
        self.assertEqual(catalog[0]["kind"], "identity")
        self.assertEqual(catalog[1]["kind"], "style")
        self.assertNotIn("kind", catalog[2])
        self.assertTrue(all(item["type"] == "input" for item in catalog))

    def test_thumbnail_is_bounded_webp_and_rejects_escape(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            inputs = root / "input" / "portraits"
            inputs.mkdir(parents=True)
            source = inputs / "large.png"
            Image.new("RGB", (600, 300), "#c8d13a").save(source)
            request = SimpleNamespace(
                rel_url=SimpleNamespace(query={"name": "portraits/large.png"}))
            bad_request = SimpleNamespace(
                rel_url=SimpleNamespace(query={"name": "../large.png"}))

            server._input_thumbnail_bytes.cache_clear()
            with patch.object(server, "CDIR", root):
                response = asyncio.run(server.input_thumbnail(request))
                bad_response = asyncio.run(server.input_thumbnail(bad_request))

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "image/webp")
        self.assertEqual(response.body[:4], b"RIFF")
        self.assertEqual(response.body[8:12], b"WEBP")
        self.assertEqual(bad_response.status, 400)

    def test_upload_request_limit_allows_the_handler_to_enforce_40_mb(self):
        self.assertEqual(server.MAX_UPLOAD_BYTES, 40_000_000)
        self.assertGreater(server.UPLOAD_CLIENT_MAX_BYTES, server.MAX_UPLOAD_BYTES)

    def test_camera_sized_upload_is_normalized_and_never_requests_overwrite(self):
        upstream = FakeResponse({"name": "face (1).png", "subfolder": "portraits",
                                 "type": "input"})
        session = FakeSession(upstream)
        request = FakeRequest([
            FakeField(b"x" * 1_200_000, "face.png"),
            FakeField(b"identity", filename=None, name="kind"),
        ])

        with TemporaryDirectory() as td, \
             patch.object(server, "INPUT_REF_TYPES_FILE", Path(td) / "types.json"), \
             patch.object(server, "INPUT_REF_TYPES", {}), \
             patch.object(server.aiohttp, "ClientSession", return_value=session):
            response = asyncio.run(server.upload(request))
            saved = server.load_input_ref_types()

        body = json.loads(response.text)
        self.assertEqual(response.status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["name"], "portraits/face (1).png")
        self.assertEqual(body["filename"], "face (1).png")
        self.assertEqual(body["subfolder"], "portraits")
        self.assertEqual(body["kind"], "identity")
        self.assertEqual(saved, {"portraits/face (1).png": "identity"})
        field_names = [metadata.get("name") for metadata, _headers, _value
                       in session.form._fields]
        self.assertEqual(field_names, ["image"])

    def test_upload_sends_the_filename_unquoted(self):
        """aiohttp's default percent-encodes the multipart filename and ComfyUI
        stores that literally, so 'face 1.png' used to land as 'face%201.png'."""
        upstream = FakeResponse({"name": "face 1.png", "subfolder": "", "type": "input"})
        session = FakeSession(upstream)
        request = FakeRequest([FakeField(b"x" * 32, "face 1.png")])

        with TemporaryDirectory() as td, \
             patch.object(server, "INPUT_REF_TYPES_FILE", Path(td) / "types.json"), \
             patch.object(server, "INPUT_REF_TYPES", {}), \
             patch.object(server.aiohttp, "ClientSession", return_value=session):
            response = asyncio.run(server.upload(request))

        self.assertEqual(response.status, 200)
        disposition = "".join(
            part[0].headers.get("Content-Disposition", "")
            for part in session.form()._parts)
        self.assertIn('filename="face 1.png"', disposition)
        self.assertNotIn("face%201.png", disposition)


class PercentEncodedInputMigrationTests(unittest.TestCase):
    def test_legacy_names_are_decoded_and_every_reference_follows(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            inputs = root / "input"
            inputs.mkdir()
            (inputs / "Screenshot%202026.png").write_bytes(b"a")
            (inputs / "plain.png").write_bytes(b"b")
            chars = root / "characters"
            chars.mkdir()
            character = {"id": "zara", "name": "Zara",
                         "identity_ref": "Screenshot%202026.png"}
            (chars / "zara.json").write_text(json.dumps(character), encoding="utf-8")
            ledger = root / "history.jsonl"
            ledger.write_text(
                json.dumps({"id": "1", "spec": {"ref": "Screenshot%202026.png"}}) + "\n" +
                json.dumps({"id": "2", "spec": {"ref": "plain.png"}}) + "\n",
                encoding="utf-8")
            types_file = root / "input_ref_types.json"
            ref_types = {"Screenshot%202026.png": "identity", "plain.png": "style"}

            with patch.object(server, "CDIR", root), \
                 patch.object(server, "CHAR_DIR", chars), \
                 patch.object(server, "LEDGER", ledger), \
                 patch.object(server, "INPUT_REF_TYPES_FILE", types_file), \
                 patch.object(server, "INPUT_REF_TYPES", ref_types), \
                 patch.object(server, "CHARACTERS", {"zara": character}):
                renames = server.migrate_percent_encoded_inputs()
                # A second pass must be a no-op.
                self.assertEqual(server.migrate_percent_encoded_inputs(), {})
                saved_types = server.load_input_ref_types()

            self.assertEqual(renames, {"Screenshot%202026.png": "Screenshot 2026.png"})
            self.assertTrue((inputs / "Screenshot 2026.png").is_file())
            self.assertFalse((inputs / "Screenshot%202026.png").exists())
            self.assertEqual(saved_types,
                             {"Screenshot 2026.png": "identity", "plain.png": "style"})
            saved_character = json.loads((chars / "zara.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_character["identity_ref"], "Screenshot 2026.png")
            entries = [json.loads(line) for line
                       in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual([e["spec"]["ref"] for e in entries],
                             ["Screenshot 2026.png", "plain.png"])

    def test_a_taken_decoded_name_is_left_alone(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            inputs = root / "input"
            inputs.mkdir()
            (inputs / "face%20a.png").write_bytes(b"encoded")
            (inputs / "face a.png").write_bytes(b"already there")

            with patch.object(server, "CDIR", root), \
                 patch.object(server, "INPUT_REF_TYPES", {}), \
                 patch.object(server, "CHARACTERS", {}), \
                 patch.object(server, "LEDGER", root / "missing.jsonl"):
                self.assertEqual(server.migrate_percent_encoded_inputs(), {})

            self.assertEqual((inputs / "face%20a.png").read_bytes(), b"encoded")
            self.assertEqual((inputs / "face a.png").read_bytes(), b"already there")


if __name__ == "__main__":
    unittest.main()
