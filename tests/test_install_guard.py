"""Brief 8.6 — the installer must never miss, and never pave over, a real
ComfyUI.

Simulations only: temp-dir disk layouts, stubbed clocks, a stubbed
download(). No network, no ComfyUI HTTP, and the real config.json and the
real install/_work are never read or written — pi.log is captured in a list
and pi.WORK is pointed into the temp dir for every test.
"""

import copy
import itertools
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True          # keep install/__pycache__ out of the repo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "install"))
import pixal_install as pi


def portable_layout(root):
    """Jesse's shape: a portable ROOT - ComfyUI\\ one level down, python_embeded
    beside it, run bats on top."""
    root = Path(root)
    (root / "ComfyUI" / "models").mkdir(parents=True)
    (root / "ComfyUI" / "main.py").write_text("# comfy", encoding="utf-8")
    (root / "python_embeded").mkdir()
    (root / "python_embeded" / "python.exe").write_text("x", encoding="utf-8")
    (root / "run_nvidia_gpu.bat").write_text("rem", encoding="utf-8")
    return root


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.loglines = []
        self._saved = {k: getattr(pi, k, None) for k in
                       ("log", "WORK", "TRANSFERS", "LAST_CLIENT", "WORKER_THREAD")}
        self._state = copy.deepcopy(pi.STATE)
        pi.log = self.loglines.append
        pi.WORK = Path(self.tmp.name) / "_work"
        pi.TRANSFERS = 0
        pi.LAST_CLIENT = 0.0
        pi.WORKER_THREAD = None
        pi.CANCEL.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._saved.items():
            setattr(pi, k, v)
        pi.STATE.clear()
        pi.STATE.update(copy.deepcopy(self._state))
        pi.CANCEL.clear()


class InstallClashTests(_Base):
    """Task 1 - the engine refuses to unpack the fresh portable over a ComfyUI
    that is already there, no matter what any page or wizard claimed."""

    def test_a_portable_root_resolves_as_a_clash(self):
        root = portable_layout(Path(self.tmp.name) / "ComfyUI_Pixal3D")
        self.assertEqual(pi.install_clash(root), root / "ComfyUI")

    def test_a_windows_portable_subfolder_resolves_as_a_clash(self):
        root = Path(self.tmp.name) / "target"
        inner = root / "ComfyUI_windows_portable"
        (inner / "ComfyUI" / "models").mkdir(parents=True)
        (inner / "ComfyUI" / "main.py").write_text("# comfy", encoding="utf-8")
        self.assertEqual(pi.install_clash(root), inner / "ComfyUI")

    def test_a_double_nested_comfyui_resolves_as_a_clash(self):
        root = Path(self.tmp.name) / "target"
        (root / "ComfyUI" / "ComfyUI" / "models").mkdir(parents=True)
        self.assertEqual(pi.install_clash(root), root / "ComfyUI" / "ComfyUI")

    def test_an_empty_folder_is_a_valid_destination(self):
        root = Path(self.tmp.name) / "empty"
        root.mkdir()
        self.assertIsNone(pi.install_clash(root))

    def test_a_missing_folder_is_a_valid_destination(self):
        self.assertIsNone(pi.install_clash(Path(self.tmp.name) / "nothere"))

    def test_a_folder_of_unrelated_files_is_a_valid_destination(self):
        root = Path(self.tmp.name) / "photos"
        (root / "ComfyUI").mkdir(parents=True)   # the name alone proves nothing
        (root / "ComfyUI" / "main.py").write_text("# not enough", encoding="utf-8")
        (root / "holiday.jpg").write_text("x", encoding="utf-8")
        self.assertIsNone(pi.install_clash(root))

    def _choices(self, root):
        return {"lanes": [], "tidy": False,
                "comfy": {"mode": "install", "path": str(root)},
                "home": str(Path(self.tmp.name) / "home")}

    def test_worker_refuses_to_pave_an_existing_comfyui(self):
        root = portable_layout(Path(self.tmp.name) / "ComfyUI_Pixal3D")
        downloads = []

        def fake_download(*a, **k):
            downloads.append((a, k))
            raise RuntimeError("network in a test")

        with mock.patch.object(pi, "download", fake_download), \
             mock.patch.object(pi, "extract_7z",
                               side_effect=AssertionError("unpack reached")):
            pi.worker(self._choices(root))
        self.assertEqual(pi.STATE["phase"], "error")
        err = pi.STATE["error"]
        self.assertIn("there is already a ComfyUI at", err)
        self.assertIn(str(root / "ComfyUI"), err)
        self.assertIn('"Use"', err)
        self.assertEqual(downloads, [])          # not one byte was fetched
        step = next(s for s in pi.STATE["steps"] if s["id"] == "comfy_get")
        self.assertEqual(step["status"], "fail")
        self.assertIn("already a ComfyUI", step["detail"])

    def test_worker_still_installs_into_an_empty_folder(self):
        # The guard is a refusal, not a veto on installing: an empty
        # destination must still reach the download step.
        root = Path(self.tmp.name) / "fresh"
        root.mkdir()
        downloads = []

        def fake_download(*a, **k):
            downloads.append((a, k))
            raise RuntimeError("network in a test")

        with mock.patch.object(pi, "download", fake_download):
            pi.worker(self._choices(root))
        self.assertEqual(len(downloads), 1)      # the guard let it through
        self.assertNotIn("already a ComfyUI", pi.STATE["error"])


class ScanDiagnosticsTests(_Base):
    """Task 3 - the scan stops being a black box: what it searched, how long
    it took, whether the deadline cut it short, and what it found."""

    def _crowded_roots(self, n=4, siblings=250):
        roots = []
        for i in range(n):
            r = Path(self.tmp.name) / f"drive{i}"
            for j in range(siblings):
                (r / f"dir{j:03d}" / "nested").mkdir(parents=True)
            roots.append(r)
        return roots

    def test_a_comfy_on_the_last_root_survives_crowded_earlier_roots(self):
        # Jesse's layout: a root-level ComfyUI_Pixal3D (name mentions comfy,
        # ComfyUI\\models one level down) on the LAST root, with hundreds of
        # sibling dirs on every earlier root. Breadth-first must still reach it.
        roots = self._crowded_roots()
        last = Path(self.tmp.name) / "drive_last"
        hit = portable_layout(last / "ComfyUI_Pixal3D")
        roots.append(last)
        res = pi.scan_for_comfy(roots, deadline=time.monotonic() + 30)
        self.assertEqual(res, [hit])
        self.assertFalse(res.info["deadline_hit"])
        self.assertEqual(res.info["searched"], [str(r) for r in roots])
        self.assertEqual(res.info["unfinished"], [])
        self.assertIn(str(hit), res.info["hits"])
        self.assertGreaterEqual(res.info["seconds"], 0)

    def test_a_deadline_forces_a_partial_scan_and_says_so(self):
        roots = self._crowded_roots(n=3, siblings=40)
        last = Path(self.tmp.name) / "drive_last"
        portable_layout(last / "ComfyUI_Pixal3D")   # sits where the scan dies
        roots.append(last)
        clock = itertools.chain([100.0, 100.0], itertools.repeat(9999.0))
        res = pi.scan_for_comfy(roots, deadline=105.0, clock=lambda: next(clock))
        self.assertEqual(res, [])
        self.assertTrue(res.info["deadline_hit"])
        self.assertEqual(res.info["searched"], [str(roots[0])])
        self.assertIn(str(last), res.info["unfinished"])
        self.assertEqual(res.info["limit"], 5.0)

    def test_scan_line_reports_scope_time_and_outcome(self):
        info = {"searched": ["C:\\", "D:\\", "X:\\"], "unfinished": [],
                "hits": ["X:\\ComfyUI_Pixal3D"], "seconds": 3.2, "limit": 8.0,
                "deadline_hit": False}
        line = pi._scan_line(info)
        self.assertNotIn("\n", line)
        self.assertIn("scan:", line)
        self.assertIn("3.2", line)
        self.assertIn("X:\\ComfyUI_Pixal3D", line)
        late = pi._scan_line({**info, "hits": [], "deadline_hit": True,
                              "unfinished": ["N:\\"], "seconds": 8.0})
        self.assertIn("deadline", late)
        self.assertIn("N:", late)
        self.assertIn("no hits", late)

    def test_probe_returns_scan_diagnostics_and_logs_one_line(self):
        hit = portable_layout(Path(self.tmp.name) / "found" / "ComfyUI_Pixal3D")
        canned = pi.ScanResult([hit], {"searched": ["C:\\", "X:\\"],
                                       "unfinished": [], "hits": [str(hit)],
                                       "seconds": 1.5, "limit": 8.0,
                                       "deadline_hit": False})
        with mock.patch.object(pi, "scan_for_comfy", return_value=canned), \
             mock.patch.object(pi, "read_config", return_value={}), \
             mock.patch.object(pi, "gpus", return_value=[]), \
             mock.patch.object(pi, "system_python", return_value=None):
            p = pi.probe()
        self.assertEqual(p["scan"]["hits"], [str(hit)])
        self.assertFalse(p["scan"]["deadline_hit"])
        self.assertEqual(p["installs"][0]["comfy"], str(pi.comfy_dir(hit)))
        lines = [l for l in self.loglines if l.startswith("scan:")]
        self.assertEqual(len(lines), 1)
        self.assertIn(str(hit), lines[0])


class WatchdogTests(_Base):
    """Task 4 - the engine must not outlive its UI as an orphan. Stubbed
    clock throughout; no real sleeping, no network."""

    class _Stop(Exception):
        pass

    def _run_watchdog(self, *, transfers, client_alive, poll=False, cycles=300):
        box = {"t": 1000.0}
        pi.LAST_CLIENT = box["t"]
        pi.TRANSFERS = transfers
        pi.STATE["phase"] = "running"
        fired = []
        ticks = {"n": 0}

        def sleep(s):
            box["t"] += s
            if poll:
                pi.note_client(now=box["t"])   # the page's /api/state poll
            ticks["n"] += 1
            if ticks["n"] > cycles:
                raise self._Stop()

        try:
            pi.ui_watchdog(client_alive=client_alive, now=lambda: box["t"],
                           sleep=sleep, pause=lambda: fired.append(box["t"]))
        except self._Stop:
            pass
        return fired

    def test_no_ui_for_ten_minutes_with_a_download_pauses_and_exits(self):
        pi.STATE["steps"] = [{"id": "comfy_get", "label": "Download", "note": "",
                              "status": "run", "detail": "1.0 GB of 2.1 GB",
                              "pct": 40}]
        exits = []
        box = {"t": 1000.0}
        pi.LAST_CLIENT = box["t"]
        pi.TRANSFERS = 1

        def sleep(s):
            box["t"] += s

        pi.ui_watchdog(client_alive=lambda: False, now=lambda: box["t"],
                       sleep=sleep,
                       pause=lambda: pi._pause_for_resume(exit_=exits.append))
        self.assertEqual(exits, [0])
        self.assertTrue(pi.CANCEL.is_set())
        self.assertIn("no ui for 10 minutes - pausing; rerun setup to resume",
                      self.loglines)
        self.assertEqual(pi.STATE["steps"][0]["detail"],
                         "paused - rerun setup to resume")
        waited = box["t"] - 1000.0
        self.assertGreaterEqual(waited, pi.UI_TIMEOUT)      # the full window
        self.assertLess(waited, pi.UI_TIMEOUT + pi.UI_POLL + 1)   # then prompt

    def test_a_live_wizard_keeps_a_long_download_alive(self):
        # The Inno flow: no HTTP ever arrives, but the wizard process lives -
        # a 12 GB download on a slow line must not be paused at ten minutes.
        self.assertEqual(self._run_watchdog(transfers=1,
                                            client_alive=lambda: True), [])

    def test_a_polling_page_keeps_the_heartbeat_fresh(self):
        self.assertEqual(self._run_watchdog(transfers=1, client_alive=None,
                                            poll=True), [])

    def test_no_transfer_means_no_pause_even_with_no_ui(self):
        self.assertEqual(self._run_watchdog(transfers=0,
                                            client_alive=lambda: False), [])

    def test_an_http_request_from_the_page_refreshes_the_heartbeat(self):
        pi.LAST_CLIENT = 0.0
        srv = pi.Server(("127.0.0.1", 0), pi.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/state", timeout=5) as r:
                self.assertEqual(r.status, 200)
                r.read()
            self.assertGreater(pi.LAST_CLIENT, 0.0)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_pid_alive_tells_living_from_dead(self):
        self.assertTrue(pi._pid_alive(os.getpid()))
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        pid = p.pid
        p.wait()
        # Popen's still-open handle is load-bearing: it pins the PID against
        # reuse, so "dead" cannot be a recycled stranger. _pid_alive reads the
        # exit code, so the held handle no longer makes the corpse look alive.
        self.assertFalse(pi._pid_alive(pid))

    def test_the_transfer_counter_balances(self):
        self.assertEqual(pi.TRANSFERS, 0)
        with pi._transfer():
            self.assertEqual(pi.TRANSFERS, 1)
            with pi._transfer():
                self.assertEqual(pi.TRANSFERS, 2)
        self.assertEqual(pi.TRANSFERS, 0)


if __name__ == "__main__":
    unittest.main()
