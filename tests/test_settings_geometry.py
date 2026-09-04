"""Opt-in browser verification of the rendered Settings workspace.

Checks minimum row height, bounded and centered controls, card/group gaps,
a stable frame across tabs and real Escape dismissal. The audit blocks
non-read HTTP methods and never visits the API/Local source tabs.

Set PIXAL_BROWSER_AUDIT=1 only after authorizing this browser workflow.
Chrome, a running Pixal and a current web build are also required.
"""

import json
import os
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
URL = os.environ.get("PIXAL_URL", "http://127.0.0.1:8190/")


def _pixal_up():
    # There is no /api/health; any HTTP answer at all, 404 included, is "up".
    try:
        urllib.request.urlopen(URL + "api/status", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:                       # noqa: BLE001
        return False


class SettingsGeometry(unittest.TestCase):

    def test_the_rendered_panel_is_on_the_ladder(self):
        if os.environ.get("PIXAL_BROWSER_AUDIT") != "1":
            self.skipTest("Browser QA is opt-in: set PIXAL_BROWSER_AUDIT=1 after authorizing the browser audit")
        if not CHROME.exists():
            self.skipTest("Chrome is not at %s" % CHROME)
        if not _pixal_up():
            self.skipTest("Pixal is not answering on %s - start it (pixal.vbs) and build web\\build.bat" % URL)
        run = subprocess.run([sys.executable, str(ROOT / "tools" / "audit_rows.py"),
                              "--url", URL, "--json"],
                             capture_output=True, text=True, timeout=240, cwd=str(ROOT))
        try:
            report = json.loads(run.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            self.fail("audit_rows.py produced no report:\n%s\n%s" % (run.stdout, run.stderr))
        if "error" in report:
            self.fail("audit_rows.py could not measure: %s" % report["error"])
        self.assertGreater(report["measured"], 0,
                           "no rows found - the served bundle predates the landmarks; run web\\build.bat")
        self.assertEqual(report["violations"], [],
                         "the rendered panel is off the ladder:\n  " + "\n  ".join(report["violations"]))


if __name__ == "__main__":
    unittest.main()
