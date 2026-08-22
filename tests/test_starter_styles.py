import json
import unittest
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

_SPEC = spec_from_file_location("pixal_server", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

STARTER_DIR = ROOT / "templates" / "styles"


def starter_files():
    return sorted(STARTER_DIR.glob("*.json"))


def installer_models():
    """Every diffusion model the installer can lay down, as Pixal rel paths.

    Read out of install/catalog.json rather than restated here, so a lane
    rename or a new shipped checkpoint moves this test's idea of "a machine
    that has never seen a Civitai login" with it.
    """
    catalog = json.loads((ROOT / "install" / "catalog.json")
                         .read_text(encoding="utf-8"))
    out = set()
    for lane in catalog.get("lanes", []):
        for f in lane.get("files", []):
            dest = str(f.get("dest") or "").replace("/", "\\")
            if dest.lower().startswith("diffusion_models\\"):
                out.add(dest.split("\\", 1)[1])
    return out


@contextmanager
def fresh_install_catalog():
    """The model shelf of a brand-new install: exactly what the installer
    ships, resolved and profiled the way the live server does it."""
    entries = {}
    for rel in installer_models():
        profile = server.model_profile(rel)
        entries[rel.lower()] = {"rel": rel, "kind": "diffusion_models",
                                **profile}

    def resolve(nm):
        low = str(nm).strip().replace("/", "\\").lower()
        if low in entries:
            return entries[low]
        hits = [e for key, e in entries.items()
                if key.rsplit("\\", 1)[-1] == low.rsplit("\\", 1)[-1]]
        return hits[0] if len(hits) == 1 else None

    with ExitStack() as stack:
        stack.enter_context(patch.object(server, "resolve_model_entry",
                                         side_effect=resolve))
        stack.enter_context(patch.object(server, "_catalog_has",
                                         return_value=True))
        stack.enter_context(patch.object(server, "_catalog_resolve",
                                         side_effect=lambda kind, rel: rel))
        stack.enter_context(patch.object(server, "resolve_lora",
                                         side_effect=lambda name: name))
        yield


class ShippedStarterSetTests(unittest.TestCase):
    def test_the_set_ships_and_every_file_validates(self):
        """An empty picker is the bug this set exists to fix, so the directory
        must not be empty, and every file in it has to survive the same
        validator a stranger's hand-written file faces."""
        files = starter_files()
        self.assertGreaterEqual(len(files), 3,
                                "the starter set is empty - the picker ships bare")
        ids = []
        for path in files:
            with self.subTest(file=path.name):
                record = server.validate_saved_style(
                    json.loads(path.read_text(encoding="utf-8")),
                    default_id=path.stem)
                self.assertEqual(record["id"], path.stem)
                ids.append(record["id"])
        self.assertEqual(len(ids), len(set(ids)), "duplicate starter style ids")

    def test_every_starter_runs_on_a_fresh_install(self):
        """The whole point: no starter may need a checkpoint the installer did
        not lay down. check_style_runnable is the save-time gate the app
        itself uses, run here against a fresh machine's shelf."""
        shipped = installer_models()
        self.assertIn("ZiT\\z_image_turbo_bf16.safetensors", shipped)
        self.assertIn("Anima\\anima-base-v1.0.safetensors", shipped)
        for path in starter_files():
            with self.subTest(file=path.name):
                record = server.validate_saved_style(
                    json.loads(path.read_text(encoding="utf-8")))
                self.assertIn(record["model"], shipped,
                              f"{record['name']} needs a model no lane installs")
                with fresh_install_catalog():
                    self.assertIs(server.check_style_runnable(record), record)
                    self.assertEqual(server.style_missing(record), [])

    def test_no_starter_tunes_a_seat_that_does_not_exist(self):
        """Z-Image Turbo runs the Amazing v4 sigma schedule - the KSampler is
        deleted from its graph - so a steps box on it would be a lie that
        fails at queue time. Starter tuning must stay empty where there is no
        seat, and legal where there is one."""
        for path in starter_files():
            with self.subTest(file=path.name):
                record = server.validate_saved_style(
                    json.loads(path.read_text(encoding="utf-8")))
                with fresh_install_catalog():
                    seat = server.sampler_seat(record["base"], record["model"])
                    if seat is None:
                        self.assertEqual(record["tuning"], {})
                    else:
                        for key in record["tuning"]:
                            self.assertIn(key, server.seat_tuning_keys(seat))


class StarterSeedingTests(unittest.TestCase):
    def seed_into(self, root):
        with patch.object(server, "RECIPE_DIR", root):
            server.seed_starter_styles()

    def test_an_empty_recipes_dir_gets_the_set_once(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self.seed_into(root)
            seeded = sorted(p.name for p in root.glob("*.json"))
            self.assertEqual(seeded, [p.name for p in starter_files()])
            self.assertTrue((root / ".starter_seeded").is_file())
            # ...and the seeded copies load as ordinary styles, no problems.
            with patch.object(server, "RECIPE_DIR", root):
                styles, problems = server.load_saved_styles()
            self.assertEqual(problems, [])
            self.assertEqual(sorted(styles), [p.stem for p in starter_files()])

    def test_a_deleted_starter_is_never_resurrected(self):
        """The marker, not the folder's emptiness, is the memory. Delete one
        starter (or all of them) and a later boot must leave them gone."""
        with TemporaryDirectory() as td:
            root = Path(td)
            self.seed_into(root)
            for p in root.glob("*.json"):
                p.unlink()
            self.seed_into(root)
            self.assertEqual(list(root.glob("*.json")), [])

    def test_an_existing_users_styles_are_never_touched(self):
        """Upgrades land on folders that already have styles: no merging, no
        clobbering - but the marker still goes down so a later clean-out does
        not trigger a seed."""
        with TemporaryDirectory() as td:
            root = Path(td)
            mine = root / "my_own_style.json"
            mine.write_text(
                '{"schema_version": 1, "name": "Mine", "base": "realism",'
                ' "model": "Krea 2\\\\m.safetensors"}', encoding="utf-8")
            before = mine.read_bytes()
            self.seed_into(root)
            self.assertEqual([p.name for p in root.glob("*.json")],
                             ["my_own_style.json"])
            self.assertEqual(mine.read_bytes(), before)
            self.assertTrue((root / ".starter_seeded").is_file())

    def test_seeding_survives_a_readonly_recipes_dir(self):
        """A courtesy must never be a boot blocker: the failure is a printed
        note, not a traceback."""
        with TemporaryDirectory() as td:
            with patch.object(server, "RECIPE_DIR", Path(td) / "gone"), \
                 patch.object(server.RECIPE_DIR.__class__, "mkdir",
                              side_effect=OSError("read-only")):
                server.seed_starter_styles()  # must not raise


if __name__ == "__main__":
    unittest.main()
