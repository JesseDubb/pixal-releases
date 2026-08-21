"""The ComfyUI console: what it reads, what it writes down, what it draws.

Two things here are load-bearing beyond looking nice. The errors log is the only
record of a failed boot that outlives the window, so what lands in it has to be
the actual fault and not the innocent line above it. And the renderer must never
emit a line wider than the console: one column too many wraps, every line below
shifts by one, and the diffing painter then redraws the whole frame forever.
"""
import shutil
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = spec_from_file_location("pixal_comfy_tui", ROOT / "comfy_tui.py")
tui = module_from_spec(_SPEC)
_SPEC.loader.exec_module(tui)
tui.USE_COLOR = False


class Case(unittest.TestCase):
    """A scratch log home per test. The handle has to be closed explicitly or
    Windows refuses to delete the directory out from under it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.errors = self.tmp / "comfy-errors.log"
        self.headline_file = self.tmp / "comfy-last-error.txt"

    def errlog(self):
        log = tui.ErrorLog(self.errors, self.headline_file, "run.bat")
        self.addCleanup(log.close)
        return log

    def booting(self, expect=30.0, profile=None):
        return tui.Boot("run.bat", expect, profile or {}), self.errlog()

    @staticmethod
    def feed(state, log, *lines):
        for line in lines:
            state.feed(line, log)


class PhaseTests(Case):
    def test_the_console_and_the_app_name_the_same_phases(self):
        """One boot, two windows. A rename on either side that left the console
        saying "importing nodes" while the overlay said "loading node packs"
        would read as two different machines, so the pairing is asserted."""
        spec = spec_from_file_location("pixal_server_phases", ROOT / "server.py")
        server = module_from_spec(spec)
        spec.loader.exec_module(server)
        # server keeps them latest-first, because it matches against a log tail.
        self.assertEqual(list(tui.PHASES), list(reversed(server._BOOT_PHASES)))

    def test_a_real_boot_walks_the_phases_in_order(self):
        state, log = self.booting()
        self.assertEqual(state.phase_name(), "waking Python")
        self.feed(state, log, "** ComfyUI startup time: 2026-08-10 09:12:38",
                  "Prestartup times for custom nodes:")
        self.assertEqual(state.phase_name(), "prestart hooks")
        self.feed(state, log, "[INFO] Total VRAM 32607 MB, total RAM 65292 MB")
        self.assertEqual(state.phase_name(), "loading node packs")
        self.feed(state, log, "[INFO] Import times for custom nodes:",
                  "[INFO] Starting server")
        self.assertEqual(state.phase_name(), "starting the web server")

    def test_a_missed_marker_does_not_leave_a_phase_open_forever(self):
        """Backfill. ComfyUI's prestartup line can be missing entirely, and
        without this the list would show it spinning for the whole boot."""
        state, log = self.booting()
        self.feed(state, log, "[INFO] Import times for custom nodes:")
        self.assertEqual(state.phase_name(), "final checks")
        self.assertTrue(all(state.phase_seconds(i) is not None for i in range(4)))

    def test_the_meter_never_claims_done_before_comfyui_answers(self):
        state, log = self.booting()
        state.t0 -= 600                                  # wildly overdue
        self.assertLess(state.progress(), 1.0)
        self.feed(state, log, "[INFO] Starting server")
        self.assertLess(state.progress(), 1.0)
        state.mark_up()
        self.assertEqual(state.progress(), 1.0)

    def test_a_measured_profile_moves_the_bar_where_the_time_goes(self):
        """Node packs are most of a cold boot on this machine. Weighted evenly
        the bar would sit at 40% for half a minute and then jump."""
        state, _ = self.booting(50.0, {"waking Python": 1.0,
                                       "prestart hooks": 1.0,
                                       "loading node packs": 45.0,
                                       "final checks": 2.0,
                                       "starting the web server": 1.0})
        self.assertLess(state.weights()[0], 0.05)
        self.assertGreater(state.weights()[2], 0.8)


class TranscriptTests(Case):
    def test_a_sampler_bar_costs_the_transcript_one_line(self):
        """400 carriage-return frames per render is a live meter, not a record -
        but the LAST frame is, and which one that is is only known when
        something else speaks."""
        state, log = self.booting()
        frames = [f" {p}%|##  | {p // 10}/10 [00:0{p // 10}<00:05,  1.2s/it]"
                  for p in (10, 20, 30)]
        self.assertEqual([state.feed(f, log) for f in frames], [[], [], []])
        self.assertEqual(state.sampling[1:3], (3, 10))
        written = state.feed("[INFO] Prompt executed in 8.31 seconds", log)
        self.assertEqual(len(written), 2)
        self.assertIn("30%", written[0])
        self.assertIn("Prompt executed", written[1])
        self.assertEqual(state.last_render, "8.3s")

    def test_the_last_frame_survives_a_launcher_that_stops_mid_bar(self):
        state, log = self.booting()
        state.feed(" 40%|#### | 4/10 [00:04<00:06,  1.2s/it]", log)
        self.assertEqual(len(state.flush_bar()), 1)
        self.assertEqual(state.flush_bar(), [])

    def test_colour_codes_never_reach_the_log(self):
        state, log = self.booting()
        written = state.feed("\x1b[32m[INFO]\x1b[0m Using sage attention", log)
        self.assertEqual(written, ["[INFO] Using sage attention"])
        self.assertEqual(state.facts.get("attention"), "sage")

    def test_the_header_facts_come_off_a_real_banner(self):
        state, log = self.booting()
        self.feed(state, log,
                  "[INFO] Total VRAM 32607 MB, total RAM 65292 MB",
                  "[INFO] Device: cuda:0 NVIDIA GeForce RTX 5090 : cudaMallocAsync",
                  "[INFO] pytorch version: 2.10.0+cu130",
                  "[INFO] ComfyUI version: 0.30.1",
                  "[INFO] Import times for custom nodes:",
                  "[INFO]    0.0 seconds: X:\\ComfyUI\\custom_nodes\\rgthree-comfy",
                  "[INFO]    1.4 seconds: X:\\ComfyUI\\custom_nodes\\was-node-suite")
        self.assertEqual(state.facts["gpu"], "NVIDIA GeForce RTX 5090")
        self.assertEqual(state.facts["comfy"], "0.30.1")
        self.assertEqual(state.facts["ram"], (32607, 65292))
        self.assertEqual(state.packs, 2)

    def test_the_prestartup_list_is_not_counted_as_node_packs(self):
        """It has the same "0.0 seconds:" shape and three entries."""
        state, log = self.booting()
        self.feed(state, log, "Prestartup times for custom nodes:",
                  "[INFO]    0.0 seconds: X:\\ComfyUI\\custom_nodes\\rgthree-comfy")
        self.assertEqual(state.packs, 0)


class ErrorLogTests(Case):
    def test_a_clean_boot_leaves_no_file_to_open(self):
        """The header is written on the first error, never before: a file that
        exists is a file someone will open looking for a problem."""
        log = self.errlog()
        log.feed("[INFO] Starting server", "INFO", "boot", 1.0)
        log.flush()
        self.assertFalse(self.errors.exists())
        self.assertFalse(self.headline_file.exists())

    def test_an_announcement_and_its_traceback_are_one_error(self):
        """ComfyUI names the failure on one line and prints the stack on the
        next. Counting those separately doubles every error on screen."""
        log = self.errlog()
        verdicts = [
            log.feed("!!! Exception during processing !!! no PulID", "ERROR", "boot", 1.0),
            log.feed("Traceback (most recent call last):", "ERROR", "boot", 1.0),
            log.feed('  File "execution.py", line 545, in execute', "", "boot", 1.0),
            log.feed("Exception: To use pulIDApply, install ComfyUI_PulID", "", "boot", 1.0),
        ]
        self.assertEqual(verdicts, ["error", "", "", ""])
        self.assertEqual(log.count, 1)
        self.assertEqual(log.headline,
                         "Exception: To use pulIDApply, install ComfyUI_PulID")

    def test_a_hint_between_the_error_and_its_stack_does_not_split_them(self):
        """bitsandbytes puts an indented suggestion between its complaint and
        the traceback that proves it - which read as two separate failures."""
        log = self.errlog()
        log.feed("bitsandbytes library load error: no CUDA binary", "ERROR", "packs", 1.0)
        log.feed(" If you are using Intel CPU/XPU, install ipex", "", "packs", 1.0)
        log.feed("Traceback (most recent call last):", "", "packs", 1.0)
        log.feed('  File "cextension.py", line 318, in <module>', "", "packs", 1.0)
        log.feed("RuntimeError: Configured CUDA binary not found", "", "packs", 1.0)
        self.assertEqual(log.count, 1)
        self.assertEqual(log.headline, "RuntimeError: Configured CUDA binary not found")
        body = self.errors.read_text(encoding="utf-8")
        self.assertIn("If you are using Intel CPU/XPU", body)     # the hint kept
        self.assertIn('during "packs"', body)                     # and the phase

    def test_the_headline_is_the_fault_not_the_line_above_it(self):
        """One line of context is worth keeping and worth never reporting: the
        first version of this named the healthy pack that printed just before
        the failure, on screen and in the sidecar's own error message."""
        log = self.errlog()
        log.feed("[QwenVL] Found 4 local GGUF vision models", "INFO", "packs", 1.0)
        log.feed("dzNodes: LayerStyle -> Cannot import name 'guidedFilter'", "", "packs", 1.0)
        log.flush()
        self.assertTrue(log.headline.startswith("dzNodes"))
        self.assertIn("[QwenVL] Found 4", self.errors.read_text(encoding="utf-8"))
        self.assertEqual(self.headline_file.read_text(encoding="utf-8"), log.headline)

    def test_comfyuis_own_console_encoding_traceback_is_not_an_error(self):
        """A node prints an emoji, ComfyUI's log handler cannot encode it into a
        cp1252 console, and out comes a full traceback about nothing. The
        launcher hands the child utf-8 so it should not recur - when it does, it
        is not what someone opening this file at 2am is looking for."""
        log = self.errlog()
        log.feed("--- Logging error ---", "", "packs", 1.0)
        log.feed("Traceback (most recent call last):", "", "packs", 1.0)
        log.feed('  File "logging\\__init__.py", line 1163, in emit', "", "packs", 1.0)
        verdict = log.feed("UnicodeEncodeError: 'charmap' codec can't encode",
                           "", "packs", 1.0)
        self.assertEqual(verdict, "warning")
        self.assertEqual(log.count, 0)

    def test_deprecation_noise_is_not_a_warning_anyone_asked_for(self):
        log = self.errlog()
        self.assertEqual(log.feed("timm/layers.py:49: FutureWarning: use timm.layers",
                                  "", "packs", 1.0), "")

    def test_a_stale_headline_cannot_outlive_the_boot_that_wrote_it(self):
        """The sidecar reports this file as the reason THIS boot failed."""
        self.headline_file.write_text("yesterday's disaster", encoding="utf-8")
        self.errlog()
        self.assertFalse(self.headline_file.exists())

    def test_errors_are_counted_once_on_screen_and_written_once_on_disk(self):
        state, log = self.booting()
        self.feed(state, log,
                  "[ERROR] !!! Exception during processing !!! no PulID",
                  "[ERROR] Traceback (most recent call last):",
                  '  File "execution.py", line 545, in execute',
                  "Exception: install ComfyUI_PulID",
                  "[INFO] Starting server")
        self.assertEqual((state.errors, log.count), (1, 1))


class LastWordsTests(unittest.TestCase):
    def test_press_any_key_is_not_a_cause_of_death(self):
        self.assertEqual(tui._telling([
            "ModuleNotFoundError: No module named 'cv2'",
            "",
            "If you see this and ComfyUI did not start try updating your Nvidia Drivers",
            "Press any key to continue . . .",
        ]), "ModuleNotFoundError: No module named 'cv2'")

    def test_with_nothing_error_shaped_the_last_real_line_wins(self):
        self.assertEqual(tui._telling(["loading models", "boom",
                                       "Press any key to continue . . ."]), "boom")

    def test_a_silent_exit_says_so_rather_than_inventing_a_reason(self):
        self.assertEqual(tui._telling(["Press any key to continue . . ."]), "")


class RenderTests(Case):
    """Nothing may wrap. One line a column too wide pushes every line below it
    down by one, and the diffing painter then redraws the entire frame."""

    SIZES = ((96, 36), (80, 30), (120, 50), (64, 24), (40, 20), (24, 12))
    PATHS = {"full": Path("C:\\a\\very\\long\\path\\to\\logs\\comfy.log"),
             "errors": Path("C:\\a\\very\\long\\path\\to\\logs\\comfy-errors.log")}

    def states(self):
        booting, log = self.booting(31.4)
        self.feed(booting, log, "[INFO] Total VRAM 32607 MB, total RAM 65292 MB",
                  "[INFO] Device: cuda:0 NVIDIA GeForce RTX 5090 : cudaMallocAsync",
                  "[INFO] ComfyUI version: 0.30.1", "[INFO] Using sage attention")
        booting.gpu = (21804, 32607, 99, 61)

        up, _ = self.booting(31.4)
        up.mark_up()
        up.port_ok = True
        up.gpu = (2048, 32607, 4, 38)
        up.sampling = (60, 6, 10, "2m 58s", "44.34s/it")
        up.sampling_at = tui.time.monotonic()

        dead, _ = self.booting(31.4)
        dead.died_at = dead.t0 + 4
        dead.exit_code = 1
        dead.last_error = "ModuleNotFoundError: No module named 'cv2' " * 6
        return {"booting": booting, "up": up, "dead": dead}

    def test_no_line_is_ever_wider_than_the_console(self):
        for name, state in self.states().items():
            state.tail.append(("ERROR", "x" * 400))
            state.errors, state.warnings = 3, 17
            for width, height in self.SIZES:
                for confirm in (False, True):
                    frame = tui.compose(state, width, height, self.PATHS, confirm)
                    self.assertEqual(len(frame), height - 1,
                                     f"{name} {width}x{height}")
                    for line in frame:
                        self.assertLessEqual(tui._plain_len(line), width,
                                             f"{name} {width}x{height}: {line!r}")

    def test_the_way_out_is_never_the_thing_that_gets_cut(self):
        """On a console too short for the dashboard, the log path and the keys
        are what a person actually needs."""
        frame = tui.compose(self.states()["dead"], 60, 14, self.PATHS, False)
        self.assertIn("comfy-errors.log", frame[-2])
        self.assertIn("error log", frame[-1])

    def test_the_box_draws_square(self):
        frame = tui.compose(self.states()["booting"], 96, 36, self.PATHS, False)
        box = [ln for ln in frame if ln.strip() and ln.strip()[0] in "╭│╰"]
        self.assertEqual(len(box), 7)                    # top, five phases, bottom
        self.assertEqual(len({len(ln) for ln in box}), 1, box)

    def test_the_painter_actually_paints(self):
        """compose() being right is half of it. The painter is wrapped in a net
        that degrades to raw printing rather than stalling the pipe drain - so a
        typo in here does not crash, it just silently costs the whole dashboard,
        which is exactly how it shipped broken once."""
        screen = tui.Screen()
        written = []
        real, sys_module = tui.sys.stdout, tui.sys
        try:
            sys_module.stdout = type("Sink", (), {
                "write": lambda _s, t: written.append(t), "flush": lambda _s: None,
            })()
            state = self.states()["booting"]
            for size in ((96, 36), (96, 36), (70, 24)):
                screen.paint(tui.compose(state, size[0], size[1], self.PATHS, False),
                             *size)
        finally:
            sys_module.stdout = real
        painted = "".join(written)
        self.assertIn("waking Python", painted)
        self.assertIn("error log", painted)               # the footer, every frame
        # First frame and the resize each clear; the repeated frame writes
        # nothing at all, which is the whole point of diffing.
        self.assertEqual(painted.count("\x1b[2J"), 2)

    def test_clipping_pays_for_printed_columns_not_escape_codes(self):
        tui.USE_COLOR = True
        try:
            painted = tui.rgb("hello world", tui.ACCENT)
            self.assertGreater(len(painted), 11)         # escapes cost bytes...
            self.assertEqual(tui._plain_len(tui.clip_ansi(painted, 5)), 5)
        finally:
            tui.USE_COLOR = False


if __name__ == "__main__":
    unittest.main()
