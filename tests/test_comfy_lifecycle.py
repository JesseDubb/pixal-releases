"""ComfyUI process lifecycle: never leave a backend behind, never start a rival.

The failure this guards against is a ghost: a ComfyUI that is running, holding
VRAM, and owns no port - so every check that looks the process up by port 8188
walks straight past it. Two of those stacked on one card is a starved GPU with
nothing on screen to explain it.
"""
import asyncio
import tempfile
import time
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


_SPEC = spec_from_file_location(
    "pixal_server_lifecycle", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


class StopComfyTests(unittest.TestCase):
    def setUp(self):
        server.COMFY_BOOT["proc"] = None

    def tearDown(self):
        server.COMFY_BOOT["proc"] = None

    def test_kills_the_child_that_never_bound_the_port(self):
        """The ghost case. It holds VRAM and owns no port, so a listener lookup
        alone can never find it - only the handle we kept at spawn can."""
        server.COMFY_BOOT["proc"] = SimpleNamespace(pid=4242, poll=lambda: None)
        with patch.object(server, "_taskkill") as kill, \
                patch.object(server, "comfy_listener_pid", return_value=None):
            self.assertEqual(server.stop_comfy(), [4242])
        kill.assert_called_once_with(4242, 20)
        self.assertIsNone(server.COMFY_BOOT["proc"])

    def test_kills_a_port_owner_we_did_not_spawn(self):
        """A ComfyUI that outlived the sidecar that started it."""
        with patch.object(server, "_taskkill") as kill, \
                patch.object(server, "comfy_listener_pid", return_value=999):
            self.assertEqual(server.stop_comfy(), [999])
        kill.assert_called_once_with(999, 20)

    def test_the_same_process_is_not_killed_twice(self):
        server.COMFY_BOOT["proc"] = SimpleNamespace(pid=555, poll=lambda: None)
        with patch.object(server, "_taskkill") as kill, \
                patch.object(server, "comfy_listener_pid", return_value=555):
            self.assertEqual(server.stop_comfy(), [555])
        self.assertEqual(kill.call_count, 1)

    def test_a_child_that_already_exited_is_cleared_without_a_kill(self):
        server.COMFY_BOOT["proc"] = SimpleNamespace(pid=77, poll=lambda: 0)
        with patch.object(server, "_taskkill") as kill, \
                patch.object(server, "comfy_listener_pid", return_value=None):
            self.assertEqual(server.stop_comfy(), [])
        kill.assert_not_called()
        self.assertIsNone(server.COMFY_BOOT["proc"])

    def test_remote_compute_is_never_stopped(self):
        """Settings -> Compute can borrow another rig. Killing that box's
        ComfyUI would end a session that is not ours to end."""
        with patch.object(server, "COMFY", "http://192.168.1.50:8188"), \
                patch.object(server, "_taskkill") as kill, \
                patch.object(server, "comfy_listener_pid", return_value=999):
            self.assertEqual(server.stop_comfy(), [])
        kill.assert_not_called()

    def test_localhost_spellings_all_count_as_ours(self):
        for url in ("http://127.0.0.1:8188", "http://localhost:8188"):
            with patch.object(server, "COMFY", url):
                self.assertTrue(server.comfy_is_local(), url)
        with patch.object(server, "COMFY", "http://10.0.0.7:8188"):
            self.assertFalse(server.comfy_is_local())


class NoRivalBackendTests(unittest.TestCase):
    def setUp(self):
        server.COMFY_BOOT["proc"] = None
        server.COMFY_BOOT["at"] = None

    def tearDown(self):
        server.COMFY_BOOT["proc"] = None
        server.COMFY_BOOT["at"] = None

    def test_a_live_child_stops_a_second_launcher(self):
        """Two launchers racing for one port is how a ghost is born: one wins
        the bind and the loser stays resident with no port to find it by.

        The handle alone no longer means "hands off" - a crashed .bat parks on
        "Press any key" and keeps cmd.exe alive forever, which wedged the studio
        shut. What holds the door is a boot still IN FLIGHT: COMFY_BOOT["at"]
        set, a watcher counting down. That is the only window a rival could
        actually race in."""
        server.COMFY_BOOT["proc"] = SimpleNamespace(pid=1, poll=lambda: None)
        server.COMFY_BOOT["at"] = 1234.0
        with patch.object(server, "comfy_reachable", AsyncMock(return_value=False)), \
                patch.object(server, "find_comfy_launcher") as find, \
                patch.object(server, "_taskkill") as kill, \
                patch.object(server.subprocess, "Popen") as popen:
            asyncio.run(server.ensure_comfy_running())
        popen.assert_not_called()
        find.assert_not_called()
        kill.assert_not_called()                 # never shoot a boot in flight
        self.assertIsNotNone(server.COMFY_BOOT["proc"])

    def test_a_stranded_console_is_killed_with_its_tree(self):
        """The corpse case: cmd.exe alive, no boot in flight. It gets closed and
        a fresh one started - but with a TREE kill, because the handle is the
        console and ComfyUI's python hangs off it. Terminating the console alone
        would strand that python with no port and then boot a rival beside it,
        which is the ghost this whole file exists to prevent."""
        server.COMFY_BOOT["proc"] = SimpleNamespace(pid=1, poll=lambda: None)
        with patch.object(server, "comfy_reachable", AsyncMock(return_value=False)), \
                patch.object(server, "comfy_listener_pid", return_value=None), \
                patch.object(server, "find_comfy_launcher", return_value=None) as find, \
                patch.object(server, "_taskkill") as kill:
            asyncio.run(server.ensure_comfy_running())
        kill.assert_called_once_with(1)
        self.assertIsNone(server.COMFY_BOOT["proc"])
        find.assert_called_once()                # and the door is open again

    def test_a_busy_comfy_is_not_mistaken_for_a_corpse(self):
        """Loading the 8B VL critic or the H3 stack holds ComfyUI's event loop
        past comfy_reachable's timeout, so the bridge drops and comfy_up goes
        false - and the boot meter re-enters this every 4s for as long as that
        lasts. Killing there costs the render in flight. The port tells the two
        apart: a .bat parked on "Press any key" has no python on the socket, a
        busy one does. Having found a listener we must also NOT fall through to
        the relaunch, or we boot a rival onto the same card."""
        server.COMFY_BOOT["proc"] = SimpleNamespace(pid=1, poll=lambda: None)
        with patch.object(server, "comfy_reachable", AsyncMock(return_value=False)), \
                patch.object(server, "comfy_listener_pid", return_value=4242), \
                patch.object(server, "find_comfy_launcher") as find, \
                patch.object(server, "_taskkill") as kill:
            asyncio.run(server.ensure_comfy_running())
        kill.assert_not_called()                 # it is working, not dead
        find.assert_not_called()                 # and no rival beside it
        self.assertIsNotNone(server.COMFY_BOOT["proc"])

    def test_a_dead_child_does_not_block_a_relaunch(self):
        """The guard must not wedge the door shut after a crash."""
        server.COMFY_BOOT["proc"] = SimpleNamespace(pid=1, poll=lambda: 1)
        with patch.object(server, "comfy_reachable", AsyncMock(return_value=False)), \
                patch.object(server, "find_comfy_launcher", return_value=None) as find:
            asyncio.run(server.ensure_comfy_running())
        find.assert_called_once()

    def test_a_reachable_comfy_is_never_relaunched(self):
        with patch.object(server, "comfy_reachable", AsyncMock(return_value=True)), \
                patch.object(server, "find_comfy_launcher") as find:
            asyncio.run(server.ensure_comfy_running())
        find.assert_not_called()


class LostBootReleasesTheDoorTests(unittest.TestCase):
    """A boot whose ComfyUI is stopped under it must let go, not hold the door.

    2026-09-04: /api/comfy/restart stopped ComfyUI and started nothing. The
    watcher re-read COMFY_BOOT["proc"] every tick, stop_comfy() had nulled that
    field, so it never noticed its own child was dead and rode out a grace
    worth up to 15 minutes of wall clock - while kick_comfy_boot's
    one-at-a-time guard handed that same lost task to the retry button, the
    page reload and the status poll alike. The screen said "waiting for
    ComfyUI" with no meter and no button that did anything.
    """

    def setUp(self):
        server.COMFY_BOOT.update(proc=None, at=None, task=None, error=None)

    def tearDown(self):
        server.COMFY_BOOT.update(proc=None, at=None, task=None, error=None)

    def test_the_watcher_returns_once_its_console_is_no_longer_ours(self):
        launched = SimpleNamespace(pid=7, poll=lambda: None)

        async def drive():
            # Reachable never, so the only way out is the ownership check.
            with patch.object(server, "comfy_reachable",
                              AsyncMock(return_value=False)), \
                    patch.object(server, "find_comfy_launcher",
                                 return_value=Path("run.bat")), \
                    patch.object(server, "comfy_launch_command",
                                 return_value=(["x"], ".", {})), \
                    patch.object(server.subprocess, "Popen",
                                 return_value=launched), \
                    patch.object(server, "_nt", return_value=False):
                task = asyncio.create_task(server.ensure_comfy_running())
                await asyncio.sleep(0)           # let it reach its watch loop
                self.assertIs(server.COMFY_BOOT["proc"], launched)
                server.COMFY_BOOT["proc"] = None            # stop_comfy() ran
                await asyncio.wait_for(task, timeout=10)

        asyncio.run(drive())
        # It let go quietly: the next owner writes the error and the meter.
        self.assertIsNone(server.COMFY_BOOT["error"])

    def test_cancel_clears_the_slot_so_the_next_kick_actually_starts(self):
        async def drive():
            forever = asyncio.create_task(asyncio.sleep(3600))
            server.COMFY_BOOT["task"] = forever
            await server.cancel_comfy_boot()
            self.assertIsNone(server.COMFY_BOOT["task"])
            self.assertTrue(forever.cancelled())

        asyncio.run(drive())

    def test_cancel_is_a_no_op_when_nothing_is_in_flight(self):
        async def drive():
            await server.cancel_comfy_boot()             # task is None
            done = asyncio.create_task(asyncio.sleep(0))
            await done
            server.COMFY_BOOT["task"] = done
            await server.cancel_comfy_boot()             # task is done
            self.assertIs(server.COMFY_BOOT["task"], done)

        asyncio.run(drive())

    def test_restart_cancels_the_attempt_before_it_stops_anything(self):
        """Order is the whole fix: cancel, THEN stop. The other way round lets
        the dying watcher hand COMFY_BOOT a proc we have already killed."""
        order = []

        async def cancel():
            order.append("cancel")

        with patch.object(server, "cancel_comfy_boot", cancel), \
                patch.object(server, "stop_comfy",
                             lambda: order.append("stop") or []), \
                patch.object(server, "kick_comfy_boot",
                             lambda: order.append("kick")):
            asyncio.run(server.restart_comfy(None))
        self.assertEqual(order, ["cancel", "stop", "kick"])


class ClosedByUserTests(unittest.TestCase):
    """/api/status polls every second and used to restart ComfyUI whenever it
    found it down, which made the console window impossible to close - it came
    straight back every time. A close now stays closed; a CRASH still relaunches,
    and the two are told apart by what the .bat leaves behind."""

    def setUp(self):
        server.COMFY_BOOT["proc"] = None
        server.COMFY_BOOT["at"] = None

    def tearDown(self):
        server.COMFY_BOOT["proc"] = None
        server.COMFY_BOOT["at"] = None

    def test_a_closed_console_reads_as_closed(self):
        server.COMFY_BOOT["proc"] = SimpleNamespace(pid=1, poll=lambda: 0)
        self.assertTrue(server.comfy_closed_by_user())

    def test_a_crash_parks_the_bat_alive_and_still_relaunches(self):
        """A crashed ComfyUI leaves cmd.exe sitting on "Press any key", so the
        handle reports no exit code - that is a corpse to clear, not a choice."""
        server.COMFY_BOOT["proc"] = SimpleNamespace(pid=1, poll=lambda: None)
        self.assertFalse(server.comfy_closed_by_user())

    def test_a_boot_in_flight_is_never_a_close(self):
        server.COMFY_BOOT["proc"] = SimpleNamespace(pid=1, poll=lambda: 0)
        server.COMFY_BOOT["at"] = 1234.0
        self.assertFalse(server.comfy_closed_by_user())

    def test_a_comfy_we_never_started_is_not_ours_to_reopen(self):
        """Adopted or hand-started ComfyUI leaves proc as None. Closing THAT is
        not something Pixal should claim to have noticed."""
        self.assertFalse(server.comfy_closed_by_user())


class LaunchCommandTests(unittest.TestCase):
    """Which console the launcher gets. Both paths run the SAME .bat - its
    --fast fp16_accumulation, --use-sage-attention and vcvars call are
    load-bearing, and bypassing them is measurable as a slower machine."""

    LAUNCHER = Path("X:/ComfyUI_Pixal3D/run_nvidia_gpu.bat")

    def _cmd(self, **cfg):
        base = {"comfy_console": "tui", "comfy_editor": False,
                "comfy_boot_seconds": 31.4}
        with patch.object(server, "load_config", return_value={**base, **cfg}), \
                patch.object(server.sys, "platform", "win32"):
            return server.comfy_launch_command(self.LAUNCHER)

    def test_the_wrapper_is_handed_the_launcher_and_this_machines_boot_time(self):
        cmd, cwd, _ = self._cmd()
        self.assertIn(str(server.COMFY_TUI), cmd)
        self.assertIn(str(self.LAUNCHER), cmd)
        self.assertIn("31.4", cmd)               # so the meter is calibrated
        self.assertEqual(cwd, str(server.HERE))
        self.assertNotIn("--editor", cmd)

    def test_plain_puts_the_raw_launcher_back(self):
        """The escape hatch has to be a real one: no wrapper in the command at
        all, and the graph-editor suppression the wrapper would have done."""
        cmd, cwd, env = self._cmd(comfy_console="plain")
        self.assertEqual(cmd[:2], ["cmd.exe", "/c"])
        self.assertEqual(cmd[2], str(self.LAUNCHER))
        self.assertEqual(cwd, str(self.LAUNCHER.parent))
        self.assertTrue(env["BROWSER"].lower().endswith("rundll32.exe"))

    def test_the_editor_setting_reaches_both_consoles(self):
        self.assertIn("--editor", self._cmd(comfy_editor=True)[0])
        # the wrapper owns the BROWSER trick for itself, from that flag
        self.assertNotIn("BROWSER", self._cmd()[2])
        self.assertNotIn("BROWSER", self._cmd(comfy_console="plain",
                                              comfy_editor=True)[2])

    def test_a_windowless_interpreter_is_never_the_one_that_draws(self):
        """pythonw.exe has no stdout to draw on: a sidecar started under it
        would open a console window that stayed blank for the whole boot."""
        with patch.object(server.sys, "executable", str(server.HERE / "pythonw.exe")):
            self.assertTrue(server._console_python().endswith("pythonw.exe"))
        real = Path(server.sys.executable)
        if real.name.lower() == "python.exe":       # the normal case, verified
            with patch.object(server.sys, "executable",
                              str(real.with_name("pythonw.exe"))):
                self.assertEqual(server._console_python(), str(real))


class LastErrorTests(unittest.TestCase):
    """The overlay used to say "its console window has the error" about a
    window that had already closed. Now it says the error."""

    def tearDown(self):
        server.COMFY_BOOT["at"] = None

    def test_a_headline_from_this_boot_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = Path(tmp) / "comfy-last-error.txt"
            line.write_text("ModuleNotFoundError: No module named 'cv2'",
                            encoding="utf-8")
            server.COMFY_BOOT["at"] = 0.0
            with patch.object(server, "COMFY_ERROR_LINE", line):
                self.assertIn("cv2", server.comfy_last_error())

    def test_a_headline_older_than_the_boot_is_not_blamed_on_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = Path(tmp) / "comfy-last-error.txt"
            line.write_text("yesterday's disaster", encoding="utf-8")
            server.COMFY_BOOT["at"] = time.time() + 60
            with patch.object(server, "COMFY_ERROR_LINE", line):
                self.assertEqual(server.comfy_last_error(), "")

    def test_no_file_at_all_is_not_an_error_message(self):
        with patch.object(server, "COMFY_ERROR_LINE", Path("nope/never.txt")):
            self.assertEqual(server.comfy_last_error(), "")


class ShutdownGateTests(unittest.TestCase):
    def tearDown(self):
        server.HUB.queue_remaining = 0
        server._LLM_TURNS["n"] = 0
        server.COMFY_BOOT["at"] = None

    def test_a_running_render_holds_the_door_open(self):
        """Closing the window must never end a render that is mid-sample."""
        server.HUB.queue_remaining = 1
        self.assertTrue(server.studio_busy())

    def test_a_live_chat_turn_holds_the_door_open(self):
        server._LLM_TURNS["n"] = 1
        self.assertTrue(server.studio_busy())

    def test_a_boot_in_progress_holds_the_door_open(self):
        server.COMFY_BOOT["at"] = 1.0
        self.assertTrue(server.studio_busy())

    def test_an_idle_studio_is_not_busy(self):
        self.assertFalse(server.studio_busy())


if __name__ == "__main__":
    unittest.main()
