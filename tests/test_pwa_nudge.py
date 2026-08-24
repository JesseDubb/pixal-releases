"""The install nudge's server half: status.pwa says whether the window can
carry Pixal's own taskbar identity (config names a Chrome PWA id AND that app
is really installed - the same _crx_ check pixal.vbs makes). False is what
the web nudge keys on; non-Windows always True (a Windows-taskbar story)."""
import unittest
from unittest import mock

import server


class PwaInstalled(unittest.TestCase):
    def test_posix_never_nudges(self):
        with mock.patch.object(server, "_nt", return_value=False):
            self.assertTrue(server.pwa_installed())

    def test_no_id_means_not_installed(self):
        with mock.patch.object(server, "_nt", return_value=True), \
             mock.patch.object(server, "load_config",
                               return_value={"chrome_app_id": ""}):
            self.assertFalse(server.pwa_installed())

    def test_id_without_crx_folder_is_not_installed(self):
        with mock.patch.object(server, "_nt", return_value=True), \
             mock.patch.object(server, "load_config",
                               return_value={"chrome_app_id": "a" * 32}), \
             mock.patch.dict(server.os.environ,
                             {"LOCALAPPDATA": r"C:\nonexistent\pixal-test"}):
            self.assertFalse(server.pwa_installed())

    def test_id_with_crx_folder_is_installed(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            app_id = "b" * 32
            (Path(tmp) / "Google" / "Chrome" / "User Data" / "Default"
             / "Web Applications" / f"_crx_{app_id}").mkdir(parents=True)
            with mock.patch.object(server, "_nt", return_value=True), \
                 mock.patch.object(server, "load_config",
                                   return_value={"chrome_app_id": app_id}), \
                 mock.patch.dict(server.os.environ, {"LOCALAPPDATA": tmp}):
                self.assertTrue(server.pwa_installed())


class ChromeAppIdDiscovery(unittest.TestCase):
    """Nothing ever wrote chrome_app_id, so installing the PWA connected it to
    nothing and pixal.vbs kept using `chrome --app=` - a window Windows
    attributes to Chrome. Find the id on disk and record it."""

    def _profile(self, tmp, apps):
        from pathlib import Path
        root = (Path(tmp) / "Google" / "Chrome" / "User Data" / "Default"
                / "Web Applications")
        for app_id, icon in apps:
            d = root / f"_crx_{app_id}"
            d.mkdir(parents=True)
            (d / icon).write_bytes(b"icon")
        return tmp

    def test_the_pixal_app_is_found_by_its_icon(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._profile(tmp, [("a" * 32, "Grok.ico"),
                                ("b" * 32, "Pixal.ico"),
                                ("c" * 32, "ComfyUI.ico")])
            with mock.patch.dict(server.os.environ, {"LOCALAPPDATA": tmp}):
                self.assertEqual(server.discover_chrome_app_id(), "b" * 32)

    def test_other_peoples_apps_are_not_pixal(self):
        # Desklight is the pre-rename app and is really on this machine.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._profile(tmp, [("d" * 32, "Desklight.ico")])
            with mock.patch.dict(server.os.environ, {"LOCALAPPDATA": tmp}):
                self.assertEqual(server.discover_chrome_app_id(), "")

    def test_no_chrome_at_all_is_quiet(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(server.os.environ, {"LOCALAPPDATA": tmp}):
                self.assertEqual(server.discover_chrome_app_id(), "")

    def test_a_found_id_is_written_to_config_once(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._profile(tmp, [("e" * 32, "Pixal.ico")])
            cfg, saves = {"chrome_app_id": ""}, []
            with mock.patch.dict(server.os.environ, {"LOCALAPPDATA": tmp}),                  mock.patch.object(server, "load_config", lambda: cfg),                  mock.patch.object(server, "save_config", saves.append):
                server._PWA_SCAN.update(at=0.0, id="")
                self.assertEqual(server.adopt_chrome_app_id(now=1000.0), "e" * 32)
                self.assertEqual(len(saves), 1)
                self.assertEqual(saves[0]["chrome_app_id"], "e" * 32)
                # Same answer a second later: no second write.
                server.adopt_chrome_app_id(now=1001.0)
                self.assertEqual(len(saves), 1)

    def test_a_configured_id_whose_app_is_gone_gets_replaced(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._profile(tmp, [("f" * 32, "Pixal.ico")])
            cfg, saves = {"chrome_app_id": "9" * 32}, []
            with mock.patch.dict(server.os.environ, {"LOCALAPPDATA": tmp}),                  mock.patch.object(server, "load_config", lambda: cfg),                  mock.patch.object(server, "save_config", saves.append):
                server._PWA_SCAN.update(at=0.0, id="")
                self.assertEqual(server.adopt_chrome_app_id(now=2000.0), "f" * 32)
                self.assertEqual(saves[0]["chrome_app_id"], "f" * 32)


if __name__ == "__main__":
    unittest.main()
