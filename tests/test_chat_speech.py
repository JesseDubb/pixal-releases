"""The chat lane speaks English, not ids.

Two leaks Jesse caught on 2026-08-24, one after the other:

  "I also caught the chat saying realism for a anime shot again"
  "please make sure it can't leak indentity_edit in chat as well ...
   no underscored names like that"

Both had already been "fixed" by instruction - 7fffc7c told the writer to call
an anime ask an anime shot, and the composer directive has always said not to
name files. An instruction a small model can drop is not a fix, so these are
the deterministic guarantees behind them.
"""

import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_SPEC = spec_from_file_location("pixal_server", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


# A character forces effective_recipe to identity_edit - a Krea 2 photo graph -
# without needing a model catalog on disk, so the style direction is live.
ANIME = {"character": "Mia", "style": "anime"}
FANTASY = {"character": "Mia", "style": "fantasy"}


class SpokenStyleRepair(unittest.TestCase):
    def test_the_setup_actually_directs(self):
        """If the directive stops firing these tests prove nothing."""
        self.assertEqual(server.effective_recipe(ANIME), "identity_edit")
        self.assertTrue(server.style_directive(ANIME))

    def test_realism_shot_becomes_the_look_that_was_asked_for(self):
        self.assertEqual(
            server.chat_speech("Rendering now - it's a realism shot.", ANIME),
            "Rendering now - it's an anime shot.")

    def test_the_article_follows_the_word(self):
        """"a realism" -> "an anime": leaving "a anime" is the same bug wearing
        a different hat."""
        self.assertIn("an anime", server.chat_speech("a realism shot", ANIME))
        self.assertIn("a fantasy", server.chat_speech("a realism shot", FANTASY))
        self.assertNotIn("a anime", server.chat_speech("a realism shot", ANIME))

    def test_capitalisation_survives(self):
        self.assertEqual(server.chat_speech("A photorealistic shot lands soon.", ANIME),
                         "An anime shot lands soon.")
        self.assertEqual(server.chat_speech("Realism it is.", ANIME), "Anime it is.")

    def test_untouched_when_the_graph_draws_its_own_style(self):
        """No direction in force means "realism" is the true word. Anima and the
        Z-Image anime profile land here too - style_directive returns "" for
        them, and their recipe name is already honest."""
        self.assertEqual(server.chat_speech("it's a realism shot", {"style": "realism"}),
                         "it's a realism shot")
        self.assertEqual(server.chat_speech("it's a realism shot", {}),
                         "it's a realism shot")

    def test_no_opts_is_safe(self):
        self.assertEqual(server.chat_speech("all good", None), "all good")
        self.assertEqual(server.chat_speech("", ANIME), "")


class NoCodeWordsInChat(unittest.TestCase):
    def test_underscored_ids_are_spoken_as_their_labels(self):
        self.assertEqual(
            server.plain_render_words("running identity_edit now"),
            "running Identity Edit now")
        self.assertEqual(
            server.plain_render_words("queued klein_inpaint, then qwen_edit"),
            "queued Klein Inpaint, then Qwen Image Edit")

    def test_action_and_video_ids_too(self):
        self.assertEqual(server.plain_render_words("h3_i2v then upscale_video"),
                         "MiniMax H3 then Upscale")
        self.assertEqual(server.plain_render_words("ltx25_i2v"), "LTX 2.5")

    def test_pre_rename_ledger_id(self):
        self.assertEqual(server.plain_render_words("zara_edit"), "Identity Edit")

    def test_the_underscore_is_a_word_character(self):
        """realism_ii must not be half-matched as realism plus debris."""
        self.assertEqual(server.plain_render_words("realism_ii"), "Realism II")

    def test_ordinary_words_are_left_alone(self):
        """"realism" and "anime" are English. Only ids that READ as code go."""
        for line in ("a realism shot", "an anime shot", "painterly fantasy work"):
            self.assertEqual(server.plain_render_words(line), line)

    def test_every_public_recipe_id_is_covered(self):
        """A new recipe with an underscored id cannot ship unspeakable."""
        for rid in server.PUBLIC_RECIPE_IDS:
            if "_" not in rid:
                continue
            spoken = server.plain_render_words(f"ran {rid} on it")
            self.assertNotIn(rid, spoken, f"{rid} leaks into chat verbatim")
            self.assertIn(server.RECIPE_SPECS[rid]["label"], spoken)


class RenderNoteSpeaksEnglish(unittest.TestCase):
    """The waiting line is the one every render shows, and it fell back to the
    raw id for any recipe without a hand-written note - "rendering
    klein_inpaint - this takes a moment", plus face_mint and anima."""

    def test_no_recipe_announces_its_id(self):
        for rid in server.PUBLIC_RECIPE_IDS:
            with self.subTest(recipe=rid):
                note = server.render_note(rid, {})
                if "_" in rid or rid == "zimage":
                    self.assertNotIn(rid, note)
                self.assertTrue(note.strip())


if __name__ == "__main__":
    unittest.main()
