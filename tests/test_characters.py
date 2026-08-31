import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web


_SPEC = spec_from_file_location(
    "pixal_server_characters", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def request_for(character_id):
    return SimpleNamespace(match_info={"character_id": character_id})


def payload(response):
    return json.loads(response.text)


class CharacterDeleteTests(unittest.TestCase):
    def test_delete_removes_only_anchor_record_and_preserves_source_image(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            anchors = root / "characters"
            inputs = root / "comfy" / "input"
            anchors.mkdir(parents=True)
            inputs.mkdir(parents=True)
            source = inputs / "source.png"
            source.write_bytes(b"source pixels")
            anchor = {"id": "test_anchor", "name": "Test Anchor",
                      "identity_ref": source.name}
            record = anchors / "test_anchor.json"
            record.write_text(json.dumps(anchor), encoding="utf-8")

            with patch.object(server, "CHAR_DIR", anchors), \
                 patch.object(server, "CHARACTERS", {"test_anchor": anchor}):
                response = asyncio.run(server.characters_delete(request_for("test_anchor")))
                self.assertNotIn("test_anchor", server.CHARACTERS)

            self.assertEqual(response.status, 200)
            self.assertTrue(payload(response)["source_image_preserved"])
            self.assertFalse(record.exists())
            self.assertEqual(source.read_bytes(), b"source pixels")

    def test_invalid_or_unknown_id_cannot_address_anchor_files(self):
        with TemporaryDirectory() as td:
            anchors = Path(td) / "characters"
            anchors.mkdir()
            record = anchors / "safe_anchor.json"
            record.write_text("{}", encoding="utf-8")
            characters = {"safe_anchor": {"id": "safe_anchor", "name": "Safe Anchor"}}

            with patch.object(server, "CHAR_DIR", anchors), \
                 patch.object(server, "CHARACTERS", characters):
                invalid = asyncio.run(server.characters_delete(request_for("../safe_anchor")))
                missing = asyncio.run(server.characters_delete(request_for("unknown_anchor")))

            self.assertEqual(invalid.status, 400)
            self.assertEqual(missing.status, 404)
            self.assertTrue(record.exists())
            self.assertIn("safe_anchor", characters)

    def test_delete_failure_is_actionable_and_keeps_runtime_anchor(self):
        with TemporaryDirectory() as td:
            anchors = Path(td) / "characters"
            anchors.mkdir()
            record = anchors / "test_anchor.json"
            record.write_text("{}", encoding="utf-8")
            characters = {"test_anchor": {"id": "test_anchor", "name": "Test Anchor"}}

            with patch.object(server, "CHAR_DIR", anchors), \
                 patch.object(server, "CHARACTERS", characters), \
                 patch.object(Path, "unlink", side_effect=PermissionError("blocked")):
                response = asyncio.run(server.characters_delete(request_for("test_anchor")))

            self.assertEqual(response.status, 500)
            self.assertIn("could not delete", payload(response)["error"])
            self.assertTrue(record.exists())
            self.assertIn("test_anchor", characters)

    def test_access_gate_rejects_unauthenticated_remote_delete(self):
        # transport=None: no socket to vouch for it, so it is remote by
        # definition. host= is left set deliberately - it must no longer matter.
        request = SimpleNamespace(
            method="DELETE", host="public.example", headers={}, query={},
            cookies={}, transport=None)
        handler = AsyncMock(return_value=web.Response(status=204))
        with patch.object(server, "ACCESS_KEY", "test-access-key"):
            response = asyncio.run(server.access_gate(request, handler))

        self.assertEqual(response.status, 403)
        handler.assert_not_awaited()

    def test_access_gate_allows_authenticated_remote_delete(self):
        request = SimpleNamespace(
            method="DELETE", host="public.example", headers={},
            query={"key": "test-access-key"}, cookies={}, transport=None)
        handler = AsyncMock(return_value=web.Response(status=204))
        with patch.object(server, "ACCESS_KEY", "test-access-key"):
            response = asyncio.run(server.access_gate(request, handler))

        self.assertEqual(response.status, 204)
        handler.assert_awaited_once_with(request)


class CharacterEditingTests(unittest.TestCase):
    """The form could only ever CREATE, so fixing a typo meant delete-and-retype.
    The save route always handled updates; nothing exposed the record to edit."""

    ANCHOR = {"id": "mia", "name": "Mia", "age": 24, "race": "Korean",
              "sex": "female", "style": "short black bob",
              "notes": "barista by day", "wardrobe_lock": "She stays in the jacket.",
              "identity_ref": "mia.png"}

    def test_the_whole_record_comes_back_for_editing(self):
        # /api/options carries only id/name/age/race/sex/has_ref - style, notes,
        # wardrobe_lock and identity_ref have no other way to reach the form.
        with patch.object(server, "CHARACTERS", {"mia": self.ANCHOR}):
            response = asyncio.run(server.characters_get_one(request_for("mia")))
        body = payload(response)
        self.assertEqual(response.status, 200)
        self.assertEqual(body["character"], self.ANCHOR)

    def test_a_hostile_or_unknown_id_gets_nothing(self):
        with patch.object(server, "CHARACTERS", {"mia": self.ANCHOR}):
            for bad, status in (("../secrets", 400), ("Mia", 400), ("ghost", 404)):
                with self.subTest(id=bad):
                    self.assertEqual(
                        asyncio.run(server.characters_get_one(request_for(bad))).status,
                        status)

    def test_the_preview_is_the_builders_own_sentence(self):
        # Rendered through character_subject/wardrobe_lock_for rather than
        # reimplemented in JS, so the form cannot drift from the render.
        draft = {"name": "Mia", "age": 24, "race": "Korean", "sex": "female",
                 "style": "short black bob"}
        request = SimpleNamespace(json=AsyncMock(return_value={"character": draft}))
        body = payload(asyncio.run(server.characters_preview(request)))
        self.assertEqual(body["subject"], server.character_subject(draft))
        self.assertEqual(body["wardrobe"], server.wardrobe_lock_for(draft))
        self.assertIn("24-year-old", body["subject"])
        self.assertIn("Korean", body["subject"])

    def test_a_custom_wardrobe_lock_shows_instead_of_the_generic_one(self):
        draft = {"name": "Mia", "sex": "female",
                 "wardrobe_lock": "She stays in the jacket."}
        request = SimpleNamespace(json=AsyncMock(return_value={"character": draft}))
        body = payload(asyncio.run(server.characters_preview(request)))
        self.assertEqual(body["wardrobe"], "She stays in the jacket.")

    def test_an_empty_draft_still_previews(self):
        # The form previews from the first keystroke; a half-filled draft must
        # not 500 the panel.
        request = SimpleNamespace(json=AsyncMock(return_value={"character": {}}))
        response = asyncio.run(server.characters_preview(request))
        self.assertEqual(response.status, 200)
        self.assertTrue(payload(response)["subject"])


class NeutralWardrobeMigrationTests(unittest.TestCase):
    """9.81: the neutral-wardrobe lane is deleted. Cards written by it load
    and re-save without its two fields, and an identity_ref that names a
    generated neutral frame is never reverted to the original upload."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "input").mkdir()
        for name in ("zara_upload.png", "pixal_neutral_zara.png"):
            (root / "input" / name).write_bytes(b"png")
        self.chars = root / "characters"
        patches = [patch.object(server, "CDIR", root),
                   patch.object(server, "CHAR_DIR", self.chars),
                   patch.object(server, "CHARACTERS", {})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def post(self, character):
        request = SimpleNamespace(
            json=AsyncMock(return_value={"character": character}))
        return asyncio.run(server.characters_post(request))

    def stored(self):
        return json.loads((self.chars / "zara.json").read_text(encoding="utf-8"))

    def test_a_card_saved_with_the_old_fields_re_saves_without_them(self):
        # The old-client shape: both dead fields arrive in the posted body.
        response = self.post({"id": "zara", "name": "Zara", "sex": "female",
                              "identity_ref": "zara_upload.png",
                              "neutral_wardrobe": True,
                              "identity_ref_original": "zara_upload.png"})
        self.assertEqual(response.status, 200)
        card = self.stored()
        self.assertNotIn("neutral_wardrobe", card)
        self.assertNotIn("identity_ref_original", card)

    def test_load_ignores_the_old_fields(self):
        self.chars.mkdir()
        (self.chars / "zara.json").write_text(json.dumps(
            {"id": "zara", "name": "Zara",
             "identity_ref": "pixal_neutral_zara.png",
             "neutral_wardrobe": True,
             "identity_ref_original": "zara_upload.png"}), encoding="utf-8")
        card = server.load_characters()["zara"]
        self.assertNotIn("neutral_wardrobe", card)
        self.assertNotIn("identity_ref_original", card)
        self.assertEqual(card["identity_ref"], "pixal_neutral_zara.png")

    def test_a_generated_neutral_identity_ref_is_kept(self):
        # The one rewrite the migration must not do: an identity_ref naming a
        # generated neutral frame is what every past render of the character
        # used - reverting to the upload would change how they look.
        response = self.post({"id": "zara", "name": "Zara", "sex": "female",
                              "identity_ref": "pixal_neutral_zara.png",
                              "neutral_wardrobe": False,
                              "identity_ref_original": "zara_upload.png"})
        self.assertEqual(response.status, 200)
        card = self.stored()
        self.assertEqual(card["identity_ref"], "pixal_neutral_zara.png")
        self.assertNotIn("identity_ref_original", card)


if __name__ == "__main__":
    unittest.main()
