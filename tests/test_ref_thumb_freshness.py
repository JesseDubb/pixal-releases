"""Brief 9.49 - the anchor preview must change when the reference does.

Jesse cropped Zara's reference, then uploaded his own crop, and the identity
anchor's hover preview in chat still showed the uncropped image an hour
later. Two layers pinned the stale pixels: the route answered
`Cache-Control: private, max-age=3600`, so the browser never revalidated
inside the hour (the ETag sat unused - the handler did not even honour
If-None-Match), and the Composer fetched the same bare
`/api/characters/<id>/ref-thumb` URL for every reference the anchor ever had.

The fix: the route now sends `private, no-cache` and answers 304 to a
matching If-None-Match (the mtime-size ETag makes an unchanged reference
cheap and a new one instant), and the anchor's URL carries `?v=<ref_rev>`
where ref_rev is the identity file's mtime_ns riding /api/options - a bare
number, never the private filename.

The route tests run the real handler against a temp ComfyUI input dir. The
Composer pin is static in the style of test_composer_canvas.py - this repo
has no JS test runner, so the contract asserts the structure of the source.
The freshness and 304 tests were proven RED against the pre-fix handler
(max-age, no If-None-Match path), the pin RED against the bare URL.
"""

import asyncio
import os
import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image


_SPEC = spec_from_file_location(
    "pixal_server_ref_thumb", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

ROOT = Path(__file__).resolve().parent.parent
COMPOSER = (ROOT / "web" / "src" / "components" / "Composer.jsx").read_text(encoding="utf-8")


def request_for(character_id, headers=None):
    return SimpleNamespace(match_info={"character_id": character_id},
                           headers=headers or {})


def write_image(path, color):
    with Image.new("RGB", (32, 32), color) as img:
        img.save(path, format="PNG")


def anchor_dir(td):
    """A temp ComfyUI root whose input/ holds one red reference image."""
    root = Path(td)
    inputs = root / "input"
    inputs.mkdir()
    ref = inputs / "ref.png"
    write_image(ref, (200, 30, 30))
    anchor = {"id": "zara", "name": "Zara", "identity_ref": ref.name}
    return root, ref, anchor


class RefThumbFreshnessTests(unittest.TestCase):
    def test_swapped_reference_serves_new_pixels_without_max_age(self):
        # Two different files behind the same id, consecutive requests: the
        # bodies must differ and neither response may carry a max-age.
        with TemporaryDirectory() as td:
            root, ref, anchor = anchor_dir(td)
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "CHARACTERS", {"zara": anchor}):
                first = asyncio.run(server.character_ref_thumb(request_for("zara")))
                write_image(ref, (30, 30, 200))
                stat = ref.stat()
                os.utime(ref, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
                second = asyncio.run(server.character_ref_thumb(request_for("zara")))

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertNotEqual(first.body, second.body)
        self.assertNotEqual(first.headers["ETag"], second.headers["ETag"])
        for response in (first, second):
            cache_control = response.headers.get("Cache-Control", "")
            self.assertNotIn("max-age", cache_control)
            self.assertIn("no-cache", cache_control)

    def test_matching_if_none_match_gets_304_and_mismatch_gets_pixels(self):
        with TemporaryDirectory() as td:
            root, ref, anchor = anchor_dir(td)
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "CHARACTERS", {"zara": anchor}):
                first = asyncio.run(server.character_ref_thumb(request_for("zara")))
                etag = first.headers["ETag"]
                repeat = asyncio.run(server.character_ref_thumb(
                    request_for("zara", headers={"If-None-Match": etag})))
                stale = asyncio.run(server.character_ref_thumb(
                    request_for("zara", headers={"If-None-Match": '"0-0"'})))

        self.assertEqual(repeat.status, 304)
        self.assertFalse(repeat.body)
        self.assertEqual(repeat.headers.get("ETag"), etag)
        self.assertIn("no-cache", repeat.headers.get("Cache-Control", ""))
        self.assertEqual(stale.status, 200)
        self.assertEqual(stale.body, first.body)


class IdentityRevTests(unittest.TestCase):
    def test_rev_is_the_identity_files_mtime_never_its_name(self):
        with TemporaryDirectory() as td:
            root, ref, anchor = anchor_dir(td)
            with patch.object(server, "CDIR", root):
                rev = server.character_identity_rev(anchor)
                self.assertEqual(rev, ref.stat().st_mtime_ns)
                self.assertNotIn(ref.name, str(rev))
                ref.unlink()
                self.assertIsNone(server.character_identity_rev(anchor))

    def test_rev_is_none_without_a_usable_reference(self):
        self.assertIsNone(server.character_identity_rev({"id": "x", "name": "X"}))
        self.assertIsNone(server.character_identity_rev(None))

    def test_options_payload_carries_ref_rev_per_character(self):
        # HUB.options needs the whole catalog, so this pins the payload shape
        # at its source: one lookup per character, beside has_ref.
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('"ref_rev": character_identity_rev(c)', src)


class ComposerUrlPinTests(unittest.TestCase):
    def test_anchor_thumb_url_carries_the_revision(self):
        match = re.search(r"image=\{`(/api/characters/[^`]*ref-thumb[^`]*)`\}", COMPOSER)
        self.assertIsNotNone(match, "the anchor AttachmentIcon lost its ref-thumb URL")
        self.assertIn("/ref-thumb?v=${", match.group(1))
        self.assertIn("ref_rev", match.group(1))


if __name__ == "__main__":
    unittest.main()
