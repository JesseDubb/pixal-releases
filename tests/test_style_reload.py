"""9.92: a recipe dropped into recipes/ appears without a restart.

Every read of the styles table goes through refresh_saved_styles(), which
re-parses only when the directory's per-file signature (name, mtime_ns, size)
moved. These tests run entirely against a TemporaryDirectory patched in as
RECIPE_DIR - the sanctioned simulation; the real recipes/ is never touched.
Each test also restores the module globals it mutates, in place, so no state
leaks into the other suites that hold those objects via patch.dict.
"""
import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


_SPEC = spec_from_file_location("pixal_server", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def recipe(name, **over):
    base = {"schema_version": 1, "name": name, "base": "realism",
            "model": "Krea 2\\m.safetensors"}
    base.update(over)
    return base


class StyleReloadTests(unittest.TestCase):
    def setUp(self):
        # Snapshot the live table and the signature; restore all three on the
        # way out so a refresh against a temp dir can never leak into a suite
        # that patch.dicts SAVED_STYLES and expects the real directory's cache.
        sig = server._STYLES_DIR_SIG
        styles = dict(server.SAVED_STYLES)
        problems = list(server.STYLE_PROBLEMS)

        def restore():
            server._STYLES_DIR_SIG = sig
            server.SAVED_STYLES.clear()
            server.SAVED_STYLES.update(styles)
            server.STYLE_PROBLEMS[:] = problems

        self.addCleanup(restore)
        self.td = TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        patcher = patch.object(server, "RECIPE_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, filename, record):
        (self.root / filename).write_text(json.dumps(record), encoding="utf-8")

    def refresh(self, **kw):
        return server.refresh_saved_styles(**kw)

    def test_a_dropped_file_appears_without_a_restart(self):
        self.refresh()
        self.assertEqual(dict(server.SAVED_STYLES), {})   # the "running" app
        self.write("night_market.json", recipe("Night Market"))
        # The reader path itself refreshes: no rescan, no restart.
        found = server.saved_style("night_market")
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Night Market")
        self.assertIn("night_market", server.SAVED_STYLES)

    def test_a_deleted_file_disappears_and_nothing_raises(self):
        self.write("one.json", recipe("One"))
        self.write("two.json", recipe("Two"))
        self.refresh()
        self.assertEqual(sorted(server.SAVED_STYLES), ["one", "two"])
        (self.root / "one.json").unlink()
        self.refresh()
        self.assertEqual(list(server.SAVED_STYLES), ["two"])
        self.assertIsNone(server.saved_style("one"))
        self.assertEqual(list(server.STYLE_PROBLEMS), [])

    def test_an_edited_file_rereads(self):
        self.write("portrait.json", recipe("Alpha", mp=1.0))
        self.refresh()
        self.assertEqual(server.saved_style("portrait")["name"], "Alpha")
        self.write("portrait.json", recipe("Beta Name", mp=2.0))
        self.refresh()
        again = server.saved_style("portrait")
        self.assertEqual(again["name"], "Beta Name")
        self.assertEqual(again["mp"], 2.0)

    def test_a_malformed_file_is_reported_not_swallowed(self):
        # In-place mutation is the contract: readers and patch.dict hold these
        # objects, so a rebind would strand them on the stale snapshot.
        styles_id, problems_id = id(server.SAVED_STYLES), id(server.STYLE_PROBLEMS)
        (self.root / "broken.json").write_text("{not json", encoding="utf-8")
        self.write("wrong.json", {"schema_version": 1, "name": "No Base"})
        self.write("good.json", recipe("Good"))
        self.refresh()
        self.assertEqual(list(server.SAVED_STYLES), ["good"])
        problems = list(server.STYLE_PROBLEMS)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("broken.json" in p and "JSON" in p for p in problems))
        self.assertTrue(any("wrong.json" in p and "base recipe" in p for p in problems))
        self.assertEqual(id(server.SAVED_STYLES), styles_id)
        self.assertEqual(id(server.STYLE_PROBLEMS), problems_id)

    def test_an_unchanged_directory_costs_stats_not_parses(self):
        self.write("one.json", recipe("One"))
        self.write("two.json", recipe("Two"))
        with patch.object(server, "load_saved_styles",
                          wraps=server.load_saved_styles) as spy:
            self.refresh()
            self.assertEqual(spy.call_count, 1)        # first read parses
            self.refresh()
            self.refresh()
            server.saved_style("one")
            self.assertEqual(spy.call_count, 1)        # unchanged: stats only
            self.write("three.json", recipe("Three"))  # prove the spy is live:
            self.refresh()                             # a real change re-parses
            self.assertEqual(spy.call_count, 2)

    def test_boot_with_no_recipes_dir_and_an_empty_one(self):
        missing = self.root / "gone"
        with patch.object(server, "RECIPE_DIR", missing):
            server.refresh_saved_styles(force=True)    # the boot read, dir absent
            self.assertEqual(dict(server.SAVED_STYLES), {})
            self.assertEqual(list(server.STYLE_PROBLEMS), [])
            missing.mkdir()
            server.refresh_saved_styles()              # an empty dir reports zero
            self.assertEqual(dict(server.SAVED_STYLES), {})
            self.assertEqual(list(server.STYLE_PROBLEMS), [])

    def test_options_lists_the_drop_and_names_the_problem(self):
        self.write("dropped.json", recipe("Dropped"))
        (self.root / "broken.json").write_text("{not json", encoding="utf-8")
        with TemporaryDirectory() as cd:
            cdir = Path(cd)
            (cdir / "input").mkdir()
            with patch.object(server, "CDIR", cdir), \
                 patch.object(server, "model_catalog", return_value=[]), \
                 patch.object(server, "model_roots", return_value=[]), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "lm_enrich"), \
                 patch.object(server, "_LORA_TITLE_CACHE", cdir / "titles.json"):
                options = server.Hub().options()
        self.assertIn("dropped", [s["id"] for s in options["saved_styles"]])
        self.assertTrue(any("broken.json" in p for p in options["style_problems"]))

    def test_rescan_also_recovers_styles(self):
        self.refresh()
        self.assertEqual(list(server.STYLE_PROBLEMS), [])
        (self.root / "late.json").write_text("{not json", encoding="utf-8")

        async def warmup():                 # the model half is not under test
            return None

        async def drive():
            with patch.object(server, "warmup_catalog", warmup):
                resp = await server.settings_rescan(None)
                await asyncio.sleep(0)      # let the scheduled stub finish
                return resp

        # patch.dict contains the rescan's catalog-cache mutations so no later
        # test pays a real model-root re-walk.
        with patch.dict(server._CATALOG), patch.dict(server._SIDECAR_META):
            asyncio.run(drive())
        self.assertTrue(any("late.json" in p for p in server.STYLE_PROBLEMS))


if __name__ == "__main__":
    unittest.main()
