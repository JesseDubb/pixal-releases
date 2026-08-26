"""9.51 - the identity reference leaks its outfit into every scene; a new
reference is re-rendered in a plain grey tee by the Klein whole-frame lane
and the neutral frame becomes identity_ref (Jesse, 2026-08-25)."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "input").mkdir()
        (root / "output" / "pixal_dm").mkdir(parents=True)
        (root / "input" / "zara_ref.png").write_bytes(b"png")
        (root / "input" / "zara_ref2.png").write_bytes(b"png")
        self.chars = root / "characters"
        self.submitted = []
        self.said = []

        async def fake_submit(cid, src, template, scene, spec, count=1, parent=None,
                              flags=None, verbatim=False):
            self.submitted.append({"template": template, "scene": scene,
                                   "spec": spec, "flags": flags})
            return {"id": "job1", "error": None}

        patches = [
            mock.patch.object(server, "CDIR", root),
            mock.patch.object(server, "CHAR_DIR", self.chars),
            mock.patch.object(server, "CHARACTERS", {}),
            mock.patch.object(server.HUB, "submit", fake_submit),
            mock.patch.object(server.HUB, "broadcast",
                              lambda **kw: self.said.append(kw.get("text"))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def post(self, **ch):
        body = {"character": {"name": "Zara", "sex": "female", "neutral_wardrobe": True, **ch}}
        resp = asyncio.run(server.characters_post(_Req(body)))
        return json.loads(resp.body)

    def stored(self):
        return json.loads((self.chars / "zara.json").read_text(encoding="utf-8"))


class SaveQueuesTheNeutralEdit(_Base):

    def test_a_new_reference_with_the_toggle_on_queues_one_klein_edit(self):
        out = self.post(identity_ref="zara_ref.png")
        self.assertTrue(out["ok"])
        self.assertEqual(len(self.submitted), 1)
        job = self.submitted[0]
        self.assertEqual(job["template"], "klein_edit")
        self.assertEqual(job["spec"], {"image": "zara_ref.png"})
        self.assertEqual(job["flags"], {"_neutralize_for": "zara"})
        self.assertIn("plain grey crew-neck t-shirt", job["scene"])
        self.assertIn("her face", job["scene"])
        st = self.stored()
        self.assertEqual(st["identity_ref"], "zara_ref.png")       # until the edit lands
        self.assertEqual(st["identity_ref_original"], "zara_ref.png")
        self.assertTrue(st["neutral_wardrobe"])

    def test_the_default_is_off_and_queues_nothing(self):
        # Proof 2026-08-25: the neutral tee leaked into the scene like the
        # mesh shirt had - opt-in only.
        body = {"character": {"name": "Zara", "sex": "female", "identity_ref": "zara_ref.png"}}
        asyncio.run(server.characters_post(_Req(body)))
        self.assertEqual(self.submitted, [])
        self.assertFalse(self.stored()["neutral_wardrobe"])

    def test_the_toggle_off_saves_the_upload_and_queues_nothing(self):
        self.post(identity_ref="zara_ref.png", neutral_wardrobe=False)
        self.assertEqual(self.submitted, [])
        st = self.stored()
        self.assertEqual(st["identity_ref"], "zara_ref.png")
        self.assertNotIn("identity_ref_original", st)

    def test_the_pronoun_follows_sex(self):
        self.assertIn("his face", server.neutral_wardrobe_instruction("male"))
        self.assertIn("their face", server.neutral_wardrobe_instruction("other"))

    def test_resaving_an_already_neutral_character_does_not_requeue(self):
        self.post(identity_ref="zara_ref.png")
        server.CHARACTERS["zara"]["identity_ref"] = "pixal_neutral_zara.png"
        (Path(self.tmp.name) / "input" / "pixal_neutral_zara.png").write_bytes(b"png")
        self.submitted.clear()
        self.post(id="zara", identity_ref="pixal_neutral_zara.png")
        self.assertEqual(self.submitted, [])
        self.assertEqual(self.stored()["identity_ref_original"], "zara_ref.png")

    def test_turning_the_toggle_off_restores_the_upload(self):
        self.post(identity_ref="zara_ref.png")
        server.CHARACTERS["zara"]["identity_ref"] = "pixal_neutral_zara.png"
        (Path(self.tmp.name) / "input" / "pixal_neutral_zara.png").write_bytes(b"png")
        self.post(id="zara", identity_ref="pixal_neutral_zara.png", neutral_wardrobe=False)
        self.assertEqual(self.stored()["identity_ref"], "zara_ref.png")

    def test_a_refused_submit_keeps_the_upload_and_says_so(self):
        async def refusing(*a, **k):
            return {"id": None, "error": "no Klein build installed"}
        with mock.patch.object(server.HUB, "submit", refusing):
            out = self.post(identity_ref="zara_ref.png")
        self.assertTrue(out["ok"])
        self.assertIn("kept as uploaded", out["note"])
        self.assertEqual(self.stored()["identity_ref"], "zara_ref.png")


class TheNeutralFrameLands(_Base):

    def _job(self, **over):
        return {"cid": "c1", "images": [{"filename": "neutral_00001_.png",
                                          "subfolder": "pixal_dm", "type": "output"}],
                "_neutralize_for": "zara", **over}

    def test_finalize_swaps_identity_ref_to_the_staged_neutral_frame(self):
        self.post(identity_ref="zara_ref.png")
        (Path(self.tmp.name) / "output" / "pixal_dm" / "neutral_00001_.png").write_bytes(b"neutral")
        server.finish_reference_neutralise(self._job())
        st = self.stored()
        self.assertEqual(st["identity_ref"], "pixal_neutral_zara.png")
        self.assertEqual(st["identity_ref_original"], "zara_ref.png")
        self.assertEqual((Path(self.tmp.name) / "input" / "pixal_neutral_zara.png").read_bytes(),
                         b"neutral")
        self.assertTrue(any("neutralised" in (t or "") for t in self.said))

    def test_a_failed_edit_keeps_the_upload_and_says_so(self):
        self.post(identity_ref="zara_ref.png")
        server.finish_reference_neutralise(self._job(images=[], error="boom"))
        self.assertEqual(self.stored()["identity_ref"], "zara_ref.png")
        self.assertTrue(any("could not be neutralised" in (t or "") for t in self.said))


class FormCarriesTheToggle(unittest.TestCase):
    SRC = (Path(__file__).resolve().parents[1] / "web" / "src" / "components"
           / "CharacterForm.jsx").read_text(encoding="utf-8")

    def test_the_form_sends_and_prefills_neutral_wardrobe(self):
        self.assertIn("ch.neutral_wardrobe = neutral", self.SRC)
        self.assertIn("setNeutral(ch.neutral_wardrobe === true)", self.SRC)
        self.assertIn('label="neutral wardrobe"', self.SRC)


if __name__ == "__main__":
    unittest.main()
