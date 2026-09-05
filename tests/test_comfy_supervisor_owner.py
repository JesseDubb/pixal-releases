"""Drive the real server supervision adapters with a fake process runner only."""
import asyncio
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import server
from pixal.backends.comfy.supervisor import ComfySupervisor, ProcessRunner


@dataclass
class FakeProcess:
    pid: int
    returncode: object = None


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.process = FakeProcess(700)
        self.listener = None
        self.start_error = None

    def poll(self, process):
        self.calls.append(("poll", process.pid))
        return process.returncode

    def start(self, command, **kwargs):
        self.calls.append(("start", command, kwargs))
        if self.start_error:
            raise self.start_error
        return self.process

    def run_hidden(self, argv, **kwargs):
        self.calls.append(("run", argv, kwargs))
        line = f"TCP 127.0.0.1:8188 0.0.0.0:0 LISTENING {self.listener}" if self.listener else ""
        return SimpleNamespace(stdout=line)

    def terminate_group(self, pid):
        self.calls.append(("group", pid))


class SupervisorRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.runner = FakeRunner()
        self.owner = ComfySupervisor(runner=self.runner)
        self.stack.enter_context(patch.object(server, "COMFY_SUPERVISOR", self.owner))
        self.stack.enter_context(patch.object(server, "COMFY_BOOT", self.owner.boot))
        self.stack.enter_context(patch.object(server, "_COMFY_RUNNER", self.runner))
        self.reachable = self.stack.enter_context(patch.object(server, "comfy_reachable", AsyncMock(return_value=False)))
        self.find = self.stack.enter_context(patch.object(server, "find_comfy_launcher", return_value=Path("synthetic/run.bat")))
        self.stack.enter_context(patch.object(server, "comfy_launch_command", return_value=(["synthetic-command"], "synthetic", {})))
        self.stack.enter_context(patch.object(server, "_nt", return_value=True))
        self.clock = self.stack.enter_context(patch.object(server.time, "time", return_value=1000.0))
        self.sleep = self.stack.enter_context(patch.object(server.asyncio, "sleep", AsyncMock()))
        self.stack.enter_context(patch.object(server.HUB, "comfy_up", True))
        self.forget = self.stack.enter_context(patch.object(server.HUB, "forget_residency"))
        self.stack.enter_context(patch.object(server, "load_config", return_value={"synthetic": True}))
        self.saved = self.stack.enter_context(patch.object(server, "save_config"))
        self.stack.enter_context(patch.object(server, "comfy_last_error", return_value="synthetic boot error"))
        self.stack.enter_context(patch.object(server, "COMFY", "http://127.0.0.1:8188"))
        async def inline(function, *args):
            return function(*args)
        self.stack.enter_context(patch.object(server.asyncio, "to_thread", inline))
        # Even an accidental fall-through cannot start/stop/query an OS process,
        # contact an endpoint or write configuration during these tests.
        for target in ("subprocess.Popen", "subprocess.run", "os.kill", "os.killpg", "os.getpgid",
                       "socket.socket.connect", "socket.socket.connect_ex", "aiohttp.ClientSession",
                       "pathlib.Path.write_text", "pathlib.Path.write_bytes"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("real I/O forbidden"), create=True))

    def actions(self, kind):
        return [call for call in self.runner.calls if call[0] == kind]

    async def test_reachable_and_in_flight_never_spawn_a_rival(self):
        self.reachable.return_value = True
        self.owner.boot["stalled_since"] = 900
        await server.ensure_comfy_running()
        self.assertEqual((self.owner.desired, self.owner.observed), ("running", "reachable"))
        self.assertIsNone(self.owner.boot["stalled_since"])
        self.assertEqual(self.runner.calls, [])
        self.find.assert_not_called()
        self.reachable.return_value = False
        self.owner.boot.update(proc=FakeProcess(9), at=123)
        await server.ensure_comfy_running()
        self.assertEqual(self.owner.observed, "booting")
        self.assertEqual(self.runner.calls, [("poll", 9)])

    async def test_occupied_port_reports_a_stall_without_killing_or_starting(self):
        self.owner.boot["proc"] = FakeProcess(9)
        self.runner.listener = 99
        await server.ensure_comfy_running()
        self.assertEqual(self.owner.observed, "stalled")
        self.assertEqual(self.owner.boot["stalled_since"], 1000)
        self.assertEqual(self.actions("start"), [])
        self.assertTrue(all(call[1][0] == "netstat" for call in self.actions("run")))
        self.find.assert_not_called()

    async def test_stale_console_tree_is_reaped_before_one_successful_boot(self):
        self.owner.boot["proc"] = FakeProcess(9)
        self.reachable.side_effect = [False, True]
        self.clock.side_effect = [1000, 1012]
        await server.ensure_comfy_running()
        self.assertEqual([call[1][0] for call in self.actions("run")], ["netstat", "taskkill"])
        self.assertEqual(self.actions("run")[1][1], ["taskkill", "/PID", "9", "/T", "/F"])
        self.assertEqual(len(self.actions("start")), 1)
        self.assertEqual(self.owner.observed, "reachable")
        self.assertIsNone(self.owner.boot["at"])
        self.saved.assert_called_once_with({"synthetic": True, "comfy_boot_seconds": 12.0})
        self.forget.assert_called_once_with("comfy restarting")

    async def test_missing_launcher_and_spawn_failure_keep_error_payloads(self):
        self.find.return_value = None
        await server.ensure_comfy_running()
        self.assertEqual(self.owner.boot["error"], "no ComfyUI launcher (.bat) found beside the ComfyUI folder - start it yourself")
        self.assertEqual(self.runner.calls, [])
        self.find.return_value = Path("run.bat")
        self.runner.start_error = OSError("synthetic denial")
        await server.ensure_comfy_running()
        self.assertEqual(self.owner.boot["error"], "could not start run.bat: synthetic denial")
        self.assertIsNone(self.owner.boot["at"])
        self.saved.assert_not_called()

    async def test_exited_and_timed_out_boots_do_not_invent_success(self):
        self.runner.process.returncode = 1
        await server.ensure_comfy_running()
        self.assertEqual(self.owner.observed, "exited")
        self.assertEqual(self.owner.boot["error"], "ComfyUI exited during boot - synthetic boot error")
        self.owner.boot.update(proc=None, at=None)
        self.runner.process.returncode = None
        self.sleep.reset_mock()
        await server.ensure_comfy_running()
        self.assertEqual(self.sleep.await_count, 180)
        self.assertEqual(self.owner.observed, "unreachable")
        self.assertEqual(self.owner.boot["error"], "ComfyUI did not come up within 6 minutes - synthetic boot error")
        self.saved.assert_not_called()

    async def test_replaced_attempt_does_not_overwrite_the_new_owners_report(self):
        replacement = FakeProcess(800)
        async def replace(_seconds):
            self.owner.boot.update(proc=replacement, error="replacement report")
        self.sleep.side_effect = replace
        await server.ensure_comfy_running()
        self.assertIs(self.owner.boot["proc"], replacement)
        self.assertEqual(self.owner.boot["error"], "replacement report")
        self.reachable.assert_awaited_once()
        self.saved.assert_not_called()

    async def test_boot_stamp_reset_uses_the_original_attempt_stamp(self):
        async def clear(_seconds):
            self.owner.boot["at"] = None
        self.sleep.side_effect = clear
        self.reachable.side_effect = [False, True]
        self.clock.side_effect = [1000, 1004]
        await server.ensure_comfy_running()
        self.saved.assert_called_once_with({"synthetic": True, "comfy_boot_seconds": 4.0})

    async def test_stop_targets_tracked_child_and_local_listener_only(self):
        self.owner.boot["proc"] = FakeProcess(10)
        self.runner.listener = 20
        self.assertEqual(server.stop_comfy(7), [10, 20])
        self.assertEqual(self.owner.desired, "stopped")
        self.assertIsNone(self.owner.boot["proc"])
        kills = [c for c in self.actions("run") if c[1][0] == "taskkill"]
        self.assertEqual([c[1][2] for c in kills], ["10", "20"])
        self.assertTrue(all(c[2]["timeout"] == 7 for c in kills))
        self.runner.calls.clear()
        with patch.object(server, "COMFY", "http://synthetic.invalid:8188"):
            self.assertEqual(server.stop_comfy(), [])
        self.assertEqual(self.runner.calls, [])

    async def test_resource_inventory_polls_the_supervisors_runner(self):
        self.owner.boot["proc"] = FakeProcess(10)
        self.runner.listener = 20
        self.assertEqual(server._comfy_local_pids(), [10, 20])
        self.assertEqual(self.actions("poll"), [("poll", 10)])

    async def test_closed_window_poll_and_posix_group_kill_use_only_runner(self):
        self.owner.boot["proc"] = FakeProcess(9, 0)
        self.assertTrue(server.comfy_closed_by_user())
        self.owner.boot["at"] = 1000
        self.assertFalse(server.comfy_closed_by_user())
        with patch.object(server, "_nt", return_value=False):
            server._taskkill(9)
        self.assertEqual(self.actions("group"), [("group", 9)])

    async def test_kick_joins_then_cancel_releases_and_retry_creates_a_new_task(self):
        async def wait_forever():
            await asyncio.Event().wait()
        with patch.object(server, "ensure_comfy_running", wait_forever):
            first = server.kick_comfy_boot()
            self.assertIs(server.kick_comfy_boot(), first)
            await server.cancel_comfy_boot()
            self.assertTrue(first.cancelled())
            self.assertIsNone(self.owner.boot["task"])
            second = server.kick_comfy_boot()
            self.assertIsNot(first, second)
            await server.cancel_comfy_boot()
        self.assertEqual(self.runner.calls, [])

    async def test_two_supervisors_share_no_desired_observed_or_boot_state(self):
        other = ComfySupervisor(runner=FakeRunner())
        self.reachable.return_value = True
        await server.ensure_comfy_running()
        self.owner.boot["error"] = "synthetic"
        self.assertEqual((other.desired, other.observed), ("unspecified", "unobserved"))
        self.assertIsNone(other.boot["error"])


class RunnerPrimitiveTests(unittest.TestCase):
    def test_platform_spawn_and_kill_arguments_are_sent_only_to_injected_primitives(self):
        run, popen, getpgid, killpg = Mock(), Mock(), Mock(return_value=77), Mock()
        runner = ProcessRunner(run=run, popen=popen, getpgid=getpgid, killpg=killpg,
                               startup_info=lambda: SimpleNamespace(dwFlags=0),
                               show_window_flag=lambda: 1, no_window_flag=lambda: 8)
        runner.start(["synthetic"], cwd="synthetic", env={}, windows=True)
        self.assertEqual(popen.call_args.kwargs["creationflags"], 0x10)
        self.assertEqual(popen.call_args.kwargs["startupinfo"].wShowWindow, 1)
        runner.start(["synthetic"], cwd="synthetic", env={}, windows=False)
        self.assertEqual(popen.call_args.kwargs, {"cwd": "synthetic", "env": {}, "start_new_session": True})
        runner.run_hidden(["synthetic"], timeout=9)
        run.assert_called_once_with(["synthetic"], timeout=9, creationflags=8)
        runner.terminate_group(12)
        getpgid.assert_called_once_with(12)
        killpg.assert_called_once_with(77, server.signal.SIGTERM)
