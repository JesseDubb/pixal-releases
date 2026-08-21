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


if __name__ == "__main__":
    unittest.main()
