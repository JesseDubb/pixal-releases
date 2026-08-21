"""The POSIX half of the platform seam (brief 8.8, Linux phase 1).

Every test runs on BOTH host platforms: the platform seam is patched
(server._nt, or the absence of subprocess.CREATE_NO_WINDOW - the real POSIX
condition for the getattr pattern), filesystems are tmp dirs, and every
spawn is stubbed. What is proven:

- POSIX launcher discovery: run*.sh first (cpu/test skipped), then main.py;
  a .bat is never a POSIX candidate.
- nt discovery and the raw .bat command are unchanged under the nt seam.
- The ComfyUI boot spawn uses console plumbing on nt and start_new_session
  on POSIX, never mixing the two.
- The brain spawn builds identical argv on both platforms; creationflags is
  0 where CREATE_NO_WINDOW does not exist.
- The sidecar restart lane refuses politely on POSIX instead of spawning
  wscript.exe, and still spawns it on nt.
- _llm_kill/_taskkill keep their "was there a process" semantics via signals.
- resolve_local_llm_python probes the POSIX interpreter twins in order and
  never consults them on nt.
"""
import asyncio
import json
import signal
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


_SPEC = spec_from_file_location(
    "pixal_server_linux_lane", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def _comfy_layout(td, scripts=(), bats=(), main_py=False):
    """A tmp-dir ComfyUI shape: launchers BESIDE the checkout, main.py inside."""
    base = Path(td)
    comfy = base / "ComfyUI"
    comfy.mkdir()
    for name in list(scripts) + list(bats):
        (base / name).write_text("# launcher\n", encoding="utf-8")
    if main_py:
        (comfy / "main.py").write_text("# comfy\n", encoding="utf-8")
    return comfy


def _started(patches):
    started = []
    for p in patches:
        started.append(p.start())
    return started


class PosixLauncherDiscoveryTests(unittest.TestCase):
    def test_run_sh_wins_over_main_py_and_cpu_and_test_are_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            comfy = _comfy_layout(
                td, main_py=True,
                scripts=("run_cpu.sh", "run_test_fp32.sh", "run_nvidia_gpu.sh"))
            with patch.object(server, "_nt", lambda: False):
                self.assertEqual(server.find_comfy_launcher(comfy).name,
                                 "run_nvidia_gpu.sh")

    def test_main_py_is_the_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            comfy = _comfy_layout(td, main_py=True)
            with patch.object(server, "_nt", lambda: False):
                self.assertEqual(server.find_comfy_launcher(comfy),
                                 comfy / "main.py")

    def test_a_bat_is_never_a_posix_candidate(self):
        """A Windows launcher on a Linux box is not bootable; saying so (None)
        is the honest answer, not spawning it through something."""
        with tempfile.TemporaryDirectory() as td:
            comfy = _comfy_layout(
                td, bats=("run_nvidia_gpu_fast_fp16_accumulation.bat",))
            with patch.object(server, "_nt", lambda: False):
                self.assertIsNone(server.find_comfy_launcher(comfy))

    def test_nothing_bootable_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            comfy = _comfy_layout(td, scripts=("run_cpu.sh",))
            with patch.object(server, "_nt", lambda: False):
                self.assertIsNone(server.find_comfy_launcher(comfy))


class NtLauncherDiscoveryTests(unittest.TestCase):
    """The existing .bat cascade re-run under the pinned nt seam, so the nt
    contract is exercised on every host, not just Windows ones."""

    def test_the_tuned_bat_still_wins_and_cpu_and_test_are_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            comfy = _comfy_layout(
                td, bats=("run_cpu.bat", "run_nvidia_gpu.bat",
                          "run_TEST_fp32vae.bat",
                          "run_nvidia_gpu_fast_fp16_accumulation.bat"))
            with patch.object(server, "_nt", lambda: True):
                self.assertEqual(server.find_comfy_launcher(comfy).name,
                                 "run_nvidia_gpu_fast_fp16_accumulation.bat")
                (comfy.parent / "run_nvidia_gpu_fast_fp16_accumulation.bat").unlink()
                self.assertEqual(server.find_comfy_launcher(comfy).name,
                                 "run_nvidia_gpu.bat")
                (comfy.parent / "run_nvidia_gpu.bat").unlink()
                self.assertIsNone(server.find_comfy_launcher(comfy))

    def test_posix_shapes_do_not_leak_into_nt_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            comfy = _comfy_layout(td, scripts=("run_nvidia_gpu.sh",), main_py=True)
            with patch.object(server, "_nt", lambda: True):
                self.assertIsNone(server.find_comfy_launcher(comfy))


class LaunchCommandPlatformTests(unittest.TestCase):
    PLAIN = {"comfy_console": "plain", "comfy_editor": False,
             "comfy_boot_seconds": 0.0}

    def _cmd(self, launcher, cfg=None, nt=False):
        # comfy_console "plain" keeps the win32-only TUI branch out of the
        # way on every host, so the seam under test is the only fork.
        with patch.object(server, "load_config",
                          return_value={**self.PLAIN, **(cfg or {})}), \
                patch.object(server, "_nt", lambda: nt):
            return server.comfy_launch_command(launcher)

    def test_posix_shell_launcher_goes_through_bash(self):
        """bash, never ./run.sh: a fresh clone may not carry the +x bit."""
        with tempfile.TemporaryDirectory() as td:
            sh = Path(td) / "run_nvidia_gpu.sh"
            sh.write_text("#\n", encoding="utf-8")
            cmd, cwd, env = self._cmd(sh)
            self.assertEqual(cmd, ["bash", str(sh)])
            self.assertEqual(cwd, str(sh.parent))
            self.assertNotIn("BROWSER", env)

    def test_posix_main_py_uses_the_probed_python_and_honors_the_editor_flag(self):
        with tempfile.TemporaryDirectory() as td:
            comfy = _comfy_layout(td, main_py=True)
            venv_py = comfy / ".venv" / "bin" / "python"
            venv_py.parent.mkdir(parents=True)
            venv_py.touch()
            cmd, cwd, _ = self._cmd(comfy / "main.py")
            self.assertEqual(cmd, [str(venv_py), str(comfy / "main.py"),
                                   "--disable-auto-launch"])
            self.assertEqual(cwd, str(comfy))
            cmd, _, _ = self._cmd(comfy / "main.py", cfg={"comfy_editor": True})
            self.assertEqual(cmd, [str(venv_py), str(comfy / "main.py")])

    def test_posix_main_py_falls_back_to_the_system_python3(self):
        with tempfile.TemporaryDirectory() as td:
            comfy = _comfy_layout(td, main_py=True)
            system = Path(td) / "usr" / "bin" / "python3"
            system.parent.mkdir(parents=True)
            system.touch()
            with patch.object(server, "HERE", Path(td) / "no-such-pixal"), \
                    patch.object(server.sys, "executable", "/nonexistent/python"), \
                    patch.object(server.shutil, "which", return_value=str(system)):
                cmd, _, _ = self._cmd(comfy / "main.py")
            self.assertEqual(cmd[0], str(system))

    def test_posix_main_py_without_any_probe_hit_uses_the_running_python(self):
        with tempfile.TemporaryDirectory() as td:
            comfy = _comfy_layout(td, main_py=True)
            with patch.object(server, "HERE", Path(td) / "no-such-pixal"), \
                    patch.object(server.sys, "executable", "/current/python"), \
                    patch.object(server.shutil, "which", return_value=None):
                cmd, _, _ = self._cmd(comfy / "main.py")
            self.assertEqual(cmd[0], "/current/python")

    def test_nt_raw_launcher_is_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            bat = Path(td) / "run_nvidia_gpu.bat"
            bat.write_text("rem\n", encoding="utf-8")
            cmd, cwd, env = self._cmd(bat, nt=True)
            self.assertEqual(cmd, ["cmd.exe", "/c", str(bat)])
            self.assertEqual(cwd, str(bat.parent))
            self.assertTrue(env["BROWSER"].lower().endswith("rundll32.exe"))


class _FakeStartupInfo:
    def __init__(self):
        self.dwFlags = 0
        self.wShowWindow = 0


class ComfyBootSpawnTests(unittest.IsolatedAsyncioTestCase):
    """The spawn site in ensure_comfy_running: console plumbing is an nt
    concept; POSIX gets a process group _taskkill can take down as one tree."""

    def setUp(self):
        self._boot = dict(server.COMFY_BOOT)
        server.COMFY_BOOT.update(at=None, launcher=None, error=None,
                                 task=None, proc=None, stalled_since=None)

    def tearDown(self):
        server.COMFY_BOOT.clear()
        server.COMFY_BOOT.update(self._boot)

    async def _boot_once(self, nt):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        comfy = _comfy_layout(
            td.name,
            scripts=() if nt else ("run_nvidia_gpu.sh",),
            bats=("run_nvidia_gpu.bat",) if nt else ())
        proc = Mock(pid=777)
        proc.poll.return_value = None
        patches = [
            patch.object(server, "_nt", lambda: nt),
            patch.object(server, "CDIR", comfy),
            patch.object(server, "comfy_reachable",
                         AsyncMock(side_effect=[False, True])),
            patch.object(server, "load_config",
                         return_value={"comfy_console": "plain"}),
            patch.object(server, "save_config"),
            patch.object(server.HUB, "comfy_up", True),
            patch.object(server.HUB, "forget_residency"),
            patch.object(server.asyncio, "sleep", AsyncMock()),
            patch.object(server.subprocess, "Popen", return_value=proc),
        ]
        if nt:
            # subprocess.STARTUPINFO does not exist on POSIX hosts; a fake
            # keeps the nt spawn provable on the ubuntu CI leg too.
            patches += [
                patch.object(server.subprocess, "STARTUPINFO",
                             _FakeStartupInfo, create=True),
                patch.object(server.subprocess, "STARTF_USESHOWWINDOW", 1,
                             create=True),
            ]
        _started(patches)
        for p in patches:
            self.addCleanup(p.stop)
        await server.ensure_comfy_running()
        launcher = comfy.parent / ("run_nvidia_gpu.bat" if nt
                                   else "run_nvidia_gpu.sh")
        return server.subprocess.Popen, launcher

    async def test_posix_boot_spawns_bash_in_a_new_session(self):
        popen, launcher = await self._boot_once(nt=False)
        self.assertEqual(popen.call_args.args[0], ["bash", str(launcher)])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(launcher.parent))
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertNotIn("creationflags", popen.call_args.kwargs)
        self.assertNotIn("startupinfo", popen.call_args.kwargs)

    async def test_nt_boot_keeps_its_console_window_plumbing(self):
        popen, launcher = await self._boot_once(nt=True)
        self.assertEqual(popen.call_args.args[0],
                         ["cmd.exe", "/c", str(launcher)])
        self.assertEqual(popen.call_args.kwargs["creationflags"], 0x00000010)
        show = popen.call_args.kwargs["startupinfo"]
        self.assertIsInstance(show, _FakeStartupInfo)
        self.assertEqual(show.wShowWindow, 1)
        self.assertNotIn("start_new_session", popen.call_args.kwargs)


class BrainSpawnPlatformTests(unittest.IsolatedAsyncioTestCase):
    async def _spawn(self, root, extra_patches=()):
        config = {"llm": {"base_url": server.LOCAL_LLM_URL,
                          "local_model": str(root / "brain.gguf"),
                          "local_keep": True},
                  "comfy_root": ""}
        proc = Mock(pid=4321)
        proc.poll.return_value = None
        patches = [
            patch.object(server, "load_config", return_value=config),
            patch.object(server, "local_llm_port_open",
                         AsyncMock(return_value=False)),
            patch.object(server, "local_llm_up", AsyncMock(return_value=True)),
            patch.object(server, "resolve_local_llm_python",
                         return_value=(str(root / "python_embeded" / "python.exe"),
                                       None)),
            patch.object(server, "LLM_STATE", root / "llm-state.json"),
            patch.object(server, "LLM_LOG", root / "llama.log"),
            patch.object(server.subprocess, "Popen", return_value=proc),
            *extra_patches,
        ]
        _started(patches)
        for p in patches:
            self.addCleanup(p.stop)
        self.assertIsNone(await server._ensure_local_llm())
        call = server.subprocess.Popen.call_args
        call.kwargs["stdout"].close()
        return call.args[0], call.kwargs

    async def test_identical_argv_and_creationflags_zero_without_the_flag(self):
        """POSIX lacks subprocess.CREATE_NO_WINDOW - that absence is the real
        condition, so patching it to 0 simulates the POSIX host exactly for
        the getattr pattern, on any CI leg."""
        # Read before the POSIX patch below lands: the expectation is the
        # flag this host natively has (0x08000000 on Windows, absent on POSIX).
        nt_flag = getattr(server.subprocess, "CREATE_NO_WINDOW", 0)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            selected = root / "python_embeded" / "python.exe"
            selected.parent.mkdir()
            selected.touch()
            (root / "brain.gguf").touch()
            argv_nt, kwargs_nt = await self._spawn(root)
            argv_posix, kwargs_posix = await self._spawn(root, extra_patches=[
                patch.object(server.subprocess, "CREATE_NO_WINDOW", 0,
                             create=True)])
        self.assertEqual(argv_nt, argv_posix)
        self.assertEqual(argv_posix[1], str(server.HERE / "pixal_brain_server.py"))
        self.assertIn(str(server.LOCAL_LLM_PORT), argv_posix)
        self.assertEqual(kwargs_posix["creationflags"], 0)
        self.assertEqual(kwargs_nt["creationflags"], nt_flag)


class RestartLaneTests(unittest.IsolatedAsyncioTestCase):
    def _patches(self, td, nt):
        return [
            patch.object(server, "_nt", lambda: nt),
            patch.object(server, "studio_busy", return_value=False),
            patch.object(server, "KEEP_COMFY", Path(td) / "keep-comfy"),
            patch.object(server.subprocess, "Popen"),
        ]

    async def test_posix_returns_the_shell_error_and_spawns_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            patches = self._patches(td, nt=False)
            _started(patches)
            for p in patches:
                self.addCleanup(p.stop)
            resp = await server.restart_sidecar(Mock())
            body = json.loads(resp.text)
            self.assertFalse(body["ok"])
            self.assertEqual(resp.status, 400)
            self.assertIn("shell", body["error"])
            server.subprocess.Popen.assert_not_called()
            self.assertFalse((Path(td) / "keep-comfy").exists())

    async def test_nt_still_spawns_the_vbs_detached(self):
        with tempfile.TemporaryDirectory() as td:
            loop = asyncio.get_running_loop()
            patches = self._patches(td, nt=True)
            patches.append(patch.object(loop, "call_later"))
            started = _started(patches)
            for p in patches:
                self.addCleanup(p.stop)
            resp = await server.restart_sidecar(Mock())
            body = json.loads(resp.text)
            self.assertTrue(body["ok"])
            argv = server.subprocess.Popen.call_args.args[0]
            self.assertEqual(argv[0], "wscript.exe")
            self.assertTrue(argv[1].endswith("pixal.vbs"))
            self.assertEqual(argv[2], "restart")
            self.assertEqual((Path(td) / "keep-comfy").read_text(encoding="utf-8"),
                             "restart")
            started[-1].assert_called_once()


class LlmKillTests(unittest.TestCase):
    def test_posix_signals_and_reports_like_taskkill(self):
        with patch.object(server, "_nt", lambda: False), \
                patch.object(server.os, "kill", create=True) as kill, \
                patch.object(server.subprocess, "run") as run:
            self.assertTrue(server._llm_kill(123))
            kill.assert_called_once_with(123, signal.SIGTERM)
            run.assert_not_called()

    def test_posix_missing_or_foreign_process_is_false(self):
        """ESRCH is "nothing there" and EPERM is taskkill's ACCESS DENIED:
        both are the False callers use to spot a stale pidfile."""
        for exc in (ProcessLookupError, PermissionError):
            with self.subTest(exc=exc), \
                    patch.object(server, "_nt", lambda: False), \
                    patch.object(server.os, "kill", side_effect=exc, create=True):
                self.assertFalse(server._llm_kill(123))

    def test_posix_an_empty_pid_never_reaches_the_os(self):
        with patch.object(server, "_nt", lambda: False), \
                patch.object(server.os, "kill", create=True) as kill:
            self.assertFalse(server._llm_kill(None))
            kill.assert_not_called()

    def test_nt_taskkill_semantics_unchanged(self):
        for code, want in ((0, True), (1, False)):
            with self.subTest(code=code), \
                    patch.object(server, "_nt", lambda: True), \
                    patch.object(server.subprocess, "run",
                                 return_value=SimpleNamespace(returncode=code)) as run:
                self.assertEqual(server._llm_kill(123), want)
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "123", "/F"])


class TaskkillTests(unittest.TestCase):
    def test_posix_takes_the_whole_process_group(self):
        with patch.object(server, "_nt", lambda: False), \
                patch.object(server.os, "getpgid", return_value=4242, create=True), \
                patch.object(server.os, "killpg", create=True) as killpg, \
                patch.object(server.subprocess, "run") as run:
            server._taskkill(99)
        killpg.assert_called_once_with(4242, signal.SIGTERM)
        run.assert_not_called()

    def test_posix_a_dead_group_is_not_an_error(self):
        with patch.object(server, "_nt", lambda: False), \
                patch.object(server.os, "getpgid", return_value=4242, create=True), \
                patch.object(server.os, "killpg",
                             side_effect=ProcessLookupError, create=True):
            server._taskkill(99)     # a corpse is the goal anyway - no raise

    def test_nt_still_tree_kills(self):
        with patch.object(server, "_nt", lambda: True), \
                patch.object(server.subprocess, "run") as run:
            server._taskkill(99)
        self.assertEqual(run.call_args.args[0],
                         ["taskkill", "/PID", "99", "/T", "/F"])
        self.assertEqual(run.call_args.kwargs["creationflags"],
                         getattr(server.subprocess, "CREATE_NO_WINDOW", 0))


class PosixPythonCandidateTests(unittest.TestCase):
    def test_candidate_order_is_most_local_first(self):
        comfy = Path("/fake/ComfyUI")
        with patch.object(server.sys, "executable", "/current/python"), \
                patch.object(server.shutil, "which",
                             return_value="/usr/bin/python3"):
            cands = server._posix_python_candidates(comfy)
        self.assertEqual(cands, [
            comfy / ".venv" / "bin" / "python",
            comfy / "venv" / "bin" / "python",
            Path("/fake/.venv/bin/python"),
            server.HERE / ".venv" / "bin" / "python",
            Path("/current/python"),
            Path("/usr/bin/python3"),
        ])

    def test_no_comfy_dir_and_no_system_python3(self):
        with patch.object(server.sys, "executable", "/current/python"), \
                patch.object(server.shutil, "which", return_value=None):
            cands = server._posix_python_candidates(None)
        self.assertEqual(cands, [server.HERE / ".venv" / "bin" / "python",
                                 Path("/current/python")])

    def test_duplicates_are_probed_once(self):
        with patch.object(server.sys, "executable", "/same/python"), \
                patch.object(server.shutil, "which", return_value="/same/python"):
            cands = server._posix_python_candidates(None)
        self.assertEqual(cands.count(Path("/same/python")), 1)


class PosixLlmPythonResolverTests(unittest.TestCase):
    def _layout(self, td):
        root = Path(td)
        comfy = root / "ComfyUI"
        (comfy / "models").mkdir(parents=True)
        inside = comfy / ".venv" / "bin" / "python"
        inside.parent.mkdir(parents=True)
        inside.touch()
        beside = root / ".venv" / "bin" / "python"
        beside.parent.mkdir(parents=True)
        beside.touch()
        return comfy, inside, beside

    def _resolve(self, td, has_server, nt=False, extra=()):
        patches = [
            patch.object(server, "_nt", lambda: nt),
            patch.dict(server.os.environ, {}, clear=True),
            patch.object(server.sys, "executable", "/nonexistent/python"),
            # HERE is pinned into the void so the repo's own .venv (present
            # or not) can never make a probe order host-dependent.
            patch.object(server, "HERE", Path(td) / "no-such-pixal"),
            patch.object(server, "_llm_python_has_server",
                         side_effect=has_server),
            *extra,
        ]
        _started(patches)
        for p in patches:
            self.addCleanup(p.stop)
        return server.resolve_local_llm_python({"comfy_root": str(td)})

    def test_the_checkouts_own_venv_wins(self):
        with tempfile.TemporaryDirectory() as td:
            _, inside, _ = self._layout(td)
            selected, error = self._resolve(td, lambda p: True)
            self.assertEqual(selected, str(inside))
            self.assertIsNone(error)

    def test_probe_order_is_checkout_venv_then_beside_then_system(self):
        with tempfile.TemporaryDirectory() as td:
            _, inside, beside = self._layout(td)
            system = Path(td) / "system" / "python3"
            system.parent.mkdir()
            system.touch()
            seen = []

            def has_server(p):
                seen.append(str(p))
                return str(p) == str(system)

            selected, _ = self._resolve(
                td, has_server,
                extra=[patch.object(server.shutil, "which",
                                    return_value=str(system))])
            self.assertEqual(selected, str(system))
            self.assertEqual(seen, [str(inside), str(beside), str(system)])

    def test_every_miss_returns_the_actionable_error(self):
        with tempfile.TemporaryDirectory() as td:
            self._layout(td)
            selected, error = self._resolve(td, lambda p: False)
            self.assertIsNone(selected)
            self.assertIn("PIXAL_LLM_PYTHON", error)

    def test_nt_never_consults_the_posix_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            self._layout(td)
            selected, error = self._resolve(
                td, lambda p: False, nt=True,
                extra=[patch.object(server, "_posix_python_candidates",
                                    side_effect=AssertionError("posix probe on nt"))])
            self.assertIsNone(selected)
            self.assertIn("PIXAL_LLM_PYTHON", error)

    def test_nt_portable_probe_still_wins(self):
        with tempfile.TemporaryDirectory() as td:
            comfy, _, _ = self._layout(td)
            portable = comfy.parent / "python_embeded" / "python.exe"
            portable.parent.mkdir()
            portable.touch()
            selected, _ = self._resolve(
                td, lambda p: True, nt=True,
                extra=[patch.object(server, "_posix_python_candidates",
                                    side_effect=AssertionError("posix probe on nt"))])
            self.assertEqual(selected, str(portable))


if __name__ == "__main__":
    unittest.main()
