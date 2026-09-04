"""The sampler card must never vanish, and must not pay its fetch twice.

Jesse, 2026-09-03: "the sampler panel sometimes takes awhile to populate -
can you have a skeleton always there ... I've minimized it before and felt
like it was gone. It is a very important panel" and "why does it have to
load multiple times - feels a little clunky".

Both were one line: `if (!seat?.tunable) return null;` on a seat that starts
null and is refetched from scratch on every mount. While the fetch was in
flight - every composer open, every recipe change - the card rendered
NOTHING, indistinguishable from not having a sampler panel at all. And
because the seat lived in component state, minimizing and reopening the
composer paid the network round-trip again each time.

The fix keeps the seat in a module-level cache keyed (recipe, model),
painted immediately on mount and revalidated behind (stale-while-revalidate),
and renders a skeleton shell at the card's real geometry until a LOADED
answer arrives. Only a loaded `tunable: false` may hide the card.

Static, in the style of test_number_field.py - this repo has no JS runner.
Proven RED against the pre-fix tree (8d55393): the optional-chained early
return existed, no seatCache, no skeleton import.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSER = (ROOT / "web" / "src" / "components" / "Composer.jsx").read_text(encoding="utf-8")


class CardNeverVanishes(unittest.TestCase):
    def test_the_vanish_shape_is_gone(self):
        """`!seat?.tunable` hid three states behind one null - loading, failed
        and genuinely-not-tunable all rendered nothing."""
        self.assertNotIn("if (!seat?.tunable) return null;", COMPOSER)

    def test_loading_renders_a_skeleton_not_null(self):
        """An unknown seat draws the shell: header, ghost summary line,
        working chevron - so the panel holds its place while it loads."""
        self.assertIn('import { Bar, PickerGhost, SegGhost, SkeletonStyle } '
                      'from "./Skeleton.jsx";', COMPOSER)
        loading = re.search(r"if \(!seat\) return \((.*?)\n  \);", COMPOSER, re.S)
        self.assertIsNotNone(loading, "the loading branch must return the shell")
        for token in ("<SkeletonStyle />", "<Bar ", "<PickerGhost />",
                      "<AccordionChevron open={open} />"):
            with self.subTest(token=token):
                self.assertIn(token, loading.group(1))

    def test_only_a_loaded_seat_may_hide_the_card(self):
        """`tunable: false` is the server's own answer for this pairing - the
        one honest null. It must be read off a LOADED seat, after the
        skeleton branch, never through optional chaining that also swallows
        the still-loading state."""
        skeleton = COMPOSER.index("if (!seat) return (")
        hidden = COMPOSER.index("if (!seat.tunable) return null;")
        self.assertLess(skeleton, hidden)


class SeatLoadsOnce(unittest.TestCase):
    def test_the_cache_outlives_the_mount(self):
        """Module-level, keyed (recipe, model): reopening the composer paints
        the last seat immediately instead of paying the fetch again."""
        self.assertIn("const seatCache = new Map();", COMPOSER)
        self.assertIn('const seatKey = (recipeId, model) => '
                      'recipeId + "|" + (model || "");', COMPOSER)

    def test_only_an_ok_answer_writes_the_cache(self):
        """An error answer or a dead fetch keeps whatever is showing - the
        stale seat, or the skeleton. Nothing may write null over a seat."""
        self.assertIn("if (!d?.ok) return;", COMPOSER)
        self.assertIn("seatCache.set(key, d);", COMPOSER)
        self.assertNotIn("setSeat(", COMPOSER)

    def test_the_star_updates_the_cache_it_reads_from(self):
        """The shelf answer lands where the next mount will look, not in
        component state that dies with the card."""
        self.assertIn("seatCache.set(key, { ...cur, combos: d.combos || [] });", COMPOSER)


if __name__ == "__main__":
    unittest.main()
