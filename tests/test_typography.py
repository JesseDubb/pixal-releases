"""The typeface has to actually load — pinned, because for the app's entire
life it did not.

`FONT` named 'Geist' from day one and nothing ever loaded it: no @font-face,
no link, nothing vendored under web/. The stack fell through -apple-system and
BlinkMacSystemFont (neither resolves on Windows) to bare sans-serif, and CDP's
CSS.getPlatformFontsForNode reported ArialMT for every string in Pixal. Jesse
caught it by eye on 2026-09-04: "what font is that text? … looks like ARIAL".

It broke the weight ladder with it. Arial has regular and bold and nothing
between, so W.label 300 and W.body 400 both drew regular while W.nav 500 and
W.heading 600 both drew BOLD - every "one step heavier" for the life of the
app was full bold, and W.emphasis 550 could not render at all.

Static, in this repo's house style (there is no JS runtime here): the four
things that have to be true together. Any one of them missing puts the app
back on Arial silently, which is the whole point - nothing errors, nothing
logs, it just renders in the wrong face until someone notices by eye.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "web" / "fonts"
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
TOKENS = (ROOT / "web" / "src" / "lib" / "design-tokens.js").read_text(
    encoding="utf-8")
SW = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")

FAMILIES = ("geist", "syne")


class TheFilesAreVendored(unittest.TestCase):
    """Self-hosted, not a CDN link: a local studio must not need
    fonts.googleapis.com to draw its own settings panel, and a font request
    leaks that the user opened Pixal."""

    def test_both_faces_ship_inside_web(self):
        for fam in FAMILIES:
            f = FONT_DIR / f"{fam}-variable-latin.woff2"
            self.assertTrue(f.is_file(), f"{f} is missing - the app is on Arial")
            self.assertEqual(f.read_bytes()[:4], b"wOF2",
                             f"{f.name} is not a woff2")
            self.assertGreater(f.stat().st_size, 8000, f"{f.name} is a stub")

    def test_nothing_fetches_a_font_over_the_network(self):
        """A URL, not a mention: the comment above the @font-face names the
        CDN as the thing we are NOT doing, and a bare substring check reads
        that as the offence it is warning about."""
        for host in ("fonts.googleapis.com", "fonts.gstatic.com"):
            self.assertNotRegex(
                INDEX, r'(?:href|src)\s*=\s*["\'][^"\']*%s' % re.escape(host),
                "a CDN font is a network dependency in a local app")
            self.assertNotRegex(
                INDEX, r'url\(\s*["\']?[^)]*%s' % re.escape(host),
                "a CDN font is a network dependency in a local app")

    def test_bundled_fonts_are_covered_by_the_shipped_notice(self):
        notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for fam in FAMILIES:
            self.assertIn(f"{fam}-variable-latin.woff2", notice)
        self.assertIn("SIL Open Font License, Version 1.1", notice)
        self.assertIn("PERMISSION & CONDITIONS", notice)


class TheFacesAreDeclared(unittest.TestCase):

    def test_index_declares_both_at_font_face(self):
        for fam, family in zip(FAMILIES, ("Geist", "Syne")):
            block = re.search(r"@font-face\s*\{[^}]*?font-family:\s*'%s'[^}]*?\}"
                              % family, INDEX, re.S)
            self.assertIsNotNone(block, f"{family} has no @font-face")
            self.assertIn(f"/fonts/{fam}-variable-latin.woff2", block.group(0))

    def test_the_faces_are_variable_not_a_single_cut(self):
        """site/ vendored static 400 and 600 only; under those a request for
        500 or 550 snaps or synthesises. W has five steps and needs a face
        that can render five."""
        for family, lo, hi in (("Geist", 100, 900), ("Syne", 400, 800)):
            block = re.search(r"@font-face\s*\{[^}]*?font-family:\s*'%s'[^}]*?\}"
                              % family, INDEX, re.S).group(0)
            self.assertRegex(block, r"font-weight:\s*%d\s+%d" % (lo, hi),
                             f"{family} is not declared as a variable range")

    def test_the_body_face_is_preloaded(self):
        self.assertRegex(
            INDEX,
            r'rel="preload"[^>]*/fonts/geist-variable-latin\.woff2[^>]*as="font"')


class TheyReachTheBrowser(unittest.TestCase):
    """Declared is not served. The @font-face 404'd silently on the first
    attempt at this fix, and the page went right on rendering in Arial."""

    def test_the_sidecar_serves_the_fonts_directory(self):
        from pixal.http.routes import ROUTES, RouteSpec
        self.assertIn(RouteSpec("STATIC", "/fonts", "fonts"), ROUTES)
        # Actual HTTP delivery is covered by test_application_factory.py.

    def test_the_service_worker_precaches_both(self):
        for fam in FAMILIES:
            self.assertIn(f'"/fonts/{fam}-variable-latin.woff2"', SW,
                          "an offline Pixal would fall back to Arial")


class TheWeightLadderNeedsThem(unittest.TestCase):

    def test_the_half_step_exists(self):
        """550: ink on full chartreuse reads thin at 500 and bold at 600.
        Jesse, 2026-09-04: "I dont want bold I just wanted slightly thicker …
        like split the difference"."""
        self.assertRegex(TOKENS, r"emphasis:\s*550")

    def test_the_ladder_is_five_steps_a_static_cut_could_not_render(self):
        weights = {int(m) for m in re.findall(r"^\s*\w+:\s*(\d{3}),",
                                              _w_block(), re.M)}
        self.assertEqual(weights, {300, 400, 500, 550, 600})

    def test_one_family_for_the_ui(self):
        self.assertIn("'Geist'", TOKENS)
        self.assertIn("'Syne'", TOKENS)


def _w_block():
    m = re.search(r"export const W = \{(.*?)\};", TOKENS, re.S)
    return m.group(1) if m else ""


if __name__ == "__main__":
    unittest.main()
