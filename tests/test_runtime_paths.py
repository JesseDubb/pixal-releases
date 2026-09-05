import dataclasses
import tempfile
import unittest
from pathlib import Path

from pixal.paths import RuntimePaths, resolve_comfy_dir


class RuntimePathTests(unittest.TestCase):
    def test_legacy_adapter_uses_temporary_data_but_real_assets(self):
        import server
        self.assertNotEqual(server.DATA_DIR, server.HERE)
        self.assertEqual(server.CONFIG, server.DATA_DIR / "config.json")
        self.assertEqual(server.CHATS_DIR, server.DATA_DIR / "chats")
        self.assertNotEqual(server.CDIR, server.HERE)
        self.assertTrue((server.HERE / "web/index.html").is_file())

    def test_standalone_default_does_not_move_user_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Pixal"
            paths = RuntimePaths.discover(app)
            self.assertEqual(paths.app_root, app)
            self.assertEqual(paths.data_root, app)
            self.assertEqual(paths.comfy_root, app)
            self.assertFalse(app.exists())

    def test_nested_install_keeps_neighboring_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "models").mkdir()
            paths = RuntimePaths.discover(root / "Pixal")
            self.assertEqual(paths.comfy_root, root)
            self.assertEqual(paths.data_root, root / "Pixal")

    def test_explicit_paths_are_separate_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_environment(root / "app", {
                "PIXAL_DATA_DIR": str(root / "data"), "PIXAL_COMFY_DIR": str(root / "engine")})
            self.assertEqual(paths.config_file, root / "data/config.json")
            self.assertEqual(paths.chats_dir, root / "data/chats")
            self.assertEqual(paths.web_dir, root / "app/web")
            self.assertEqual(paths.comfy_root, root / "engine")
            self.assertEqual(list(root.iterdir()), [])
            with self.assertRaises(dataclasses.FrozenInstanceError):
                paths.data_root = root

    def test_relative_environment_roots_fail_loudly(self):
        for variable in ("PIXAL_DATA_DIR", "PIXAL_COMFY_DIR"):
            with self.subTest(variable=variable), self.assertRaises(ValueError):
                RuntimePaths.from_environment(Path.cwd(), {variable: "relative"})

    def test_portable_bare_and_models_picker_paths_still_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = root / "ComfyUI"
            (engine / "models").mkdir(parents=True)
            for value in (root, engine, engine / "models", f'"{engine}"'):
                with self.subTest(value=value):
                    self.assertEqual(resolve_comfy_dir(value), engine)
            self.assertIsNone(resolve_comfy_dir(root / "missing"))
