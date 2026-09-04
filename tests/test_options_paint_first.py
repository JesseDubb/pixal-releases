"""The app paints on open: /api/options never blocks on a cache it already
holds, and the client seeds its catalog from the last one it saw."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
STORE = (ROOT / "web" / "src" / "store.js").read_text(encoding="utf-8")


class TheServerServesWhatItHas(unittest.TestCase):
    def handler(self):
        m = re.search(r"async def options\(_req\):([\s\S]{0,1200}?)\n\n", SERVER)
        self.assertIsNotNone(m)
        return m.group(1)

    def test_only_an_empty_cache_waits_on_comfy(self):
        body = self.handler()
        self.assertIn('if _COMFY_NODES["names"] is None:', body)
        self.assertIn("await refresh_comfy_nodes()", body)
        self.assertIn("_spawn_refresh(refresh_comfy_nodes)", body)
        self.assertIn("_spawn_refresh(refresh_lm_cache)", body)

    def test_one_refresh_in_flight_per_cache(self):
        m = re.search(r"def _spawn_refresh\(fn\):([\s\S]+?)\n\n", SERVER)
        self.assertIsNotNone(m)
        self.assertIn("not task.done()", m.group(1))
        self.assertIn("asyncio.ensure_future(fn())", m.group(1))


class TheClientPaintsFromTheLastCatalog(unittest.TestCase):
    def test_state_seeds_from_the_cache(self):
        self.assertIn("options: loadCachedOptions(),", STORE)
        self.assertRegex(STORE, r"Array\.isArray\(o\.recipes\) && Array\.isArray\(o\.models\)")

    def test_a_fresh_catalog_refills_the_cache(self):
        body = re.search(r"async loadOptions\(\) \{([\s\S]+?)\n  \},", STORE).group(1)
        self.assertIn("state.options = await transport.options();", body)
        self.assertIn("localStorage.setItem(OPTIONS_KEY, JSON.stringify(state.options))", body)


if __name__ == "__main__":
    unittest.main()
