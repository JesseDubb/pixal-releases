"""Settings must not re-load on a remount.

Jesse, 2026-09-03: "I feel like settings sometimes loads and has to load
again". The panel has two mount sites in Chat.jsx - docked in the rail, and
floating over narrow layouts - so a dock swap or a window crossing the
wide/narrow breakpoint unmounts one and mounts the other. Every remount
started from cfg = null: the full skeleton, and the /api/settings fetch
paid again.

The fix is the sampler card's cure (test_sampler_card_skeleton.py): a
module-level stale-while-revalidate cache. The last payload seeds the panel
BEFORE first paint via useLayoutEffect, the mount fetch revalidates behind
it, and every successful save quietly refreshes the cached copy so the next
mount cannot flash pre-save values.

Static, in the style of test_number_field.py - this repo has no JS runner.
Proven RED against the pre-fix tree (1ec0802): no settingsCache, the whole
setter block lived inline in the mount fetch's .then.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")


class SettingsLoadsOnce(unittest.TestCase):
    def test_the_cache_outlives_the_mount(self):
        """Module-level - it must survive the panel moving between its docked
        and floating mount sites."""
        self.assertIn("let settingsCache = null;", SETTINGS)

    def test_a_remount_seeds_before_first_paint(self):
        """useLayoutEffect, not useEffect: the seeded values must be there on
        the first frame, or the remount still flashes the skeleton it was
        supposed to kill."""
        self.assertIn("useLayoutEffect(() => { if (settingsCache) "
                      "applySettings(settingsCache); }, []);", SETTINGS)

    def test_the_wire_and_the_cache_apply_the_same_way(self):
        """One applySettings for both sources - a second copy of a 25-setter
        block would drift the moment a field is added to one of them."""
        self.assertEqual(SETTINGS.count("const applySettings = (d) => {"), 1)
        self.assertIn("settingsCache = d;\n      applySettings(d);", SETTINGS)

    def test_a_successful_save_refreshes_the_cache(self):
        """POST /api/settings answers ok/error, never the payload. Without
        this, the next mount seeds pre-save values and 'corrects' them a
        beat later - trading a skeleton flash for a wrong-number flash."""
        self.assertIn("if (d.ok) fetch(\"/api/settings\")", SETTINGS)
        self.assertIn("{ settingsCache = d2; }", SETTINGS)


if __name__ == "__main__":
    unittest.main()
