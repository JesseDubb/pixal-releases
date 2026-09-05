"""ComfyUI process ownership with explicit inputs and an injected process runner.

Construction and import do nothing. Tests provide a fake runner; only the
composition root supplies real OS functions. Desired/observed state supplements
the legacy boot dictionary without changing its wire projection.
"""
import asyncio
import os.path
from pathlib import Path
import signal
import subprocess
import urllib.parse

COMFY_LAUNCHER_PREFERENCE = ("run_nvidia_gpu_fast_fp16_accumulation.bat",
                            "run_nvidia_gpu.bat")


class ProcessRunner:
    """The sole process-action boundary; every OS primitive is injected."""
    def __init__(self, *, run, popen, getpgid, killpg, startup_info,
                 show_window_flag, no_window_flag):
        self.run = run
        self.popen = popen
        self.getpgid = getpgid
        self.killpg = killpg
        self.startup_info = startup_info
        self.show_window_flag = show_window_flag
        self.no_window_flag = no_window_flag

    def poll(self, process):
        return process.poll()

    def run_hidden(self, argv, **kwargs):
        return self.run(argv, creationflags=self.no_window_flag(), **kwargs)

    def terminate_group(self, pid):
        self.killpg(self.getpgid(pid), signal.SIGTERM)

    def start(self, command, *, cwd, env, windows):
        if windows:
            # Preserve the desktop's explicit visible ComfyUI console contract.
            show = self.startup_info()
            show.dwFlags |= self.show_window_flag()
            show.wShowWindow = 1
            return self.popen(command, cwd=cwd, creationflags=0x00000010,
                              startupinfo=show, env=env)
        return self.popen(command, cwd=cwd, env=env, start_new_session=True)


class ComfySupervisor:
    def __init__(self, *, runner):
        self.runner = runner
        self.boot = {"at": None, "launcher": None, "error": None, "task": None,
                     "proc": None, "stalled_since": None}
        self.desired = "unspecified"
        self.observed = "unobserved"

    def tracked_pid(self):
        process = self.boot.get("proc")
        if process is not None and self.runner.poll(process) is None:
            return process.pid
        return None

    def reset_boot_report(self):
        self.boot.update(at=None, error=None)

    def cancel_watch(self):
        if self.boot.get("task"):
            self.boot["task"].cancel()

    def find_comfy_launcher(self, root=None, *, comfy_root, is_windows, preference=COMFY_LAUNCHER_PREFERENCE):
        """The launcher the user actually starts ComfyUI with - it sits BESIDE the
        ComfyUI folder, not inside it. CPU and A/B test launchers are skipped.

        nt: the tuned .bat - its flags are measured, and bypassing them is slower.
        POSIX: a run*.sh beside the checkout wins (invoked through bash, so the
        executable bit does not matter), else the checkout's own main.py. A .bat
        is not bootable there, so it is never a POSIX candidate."""
        base = Path(root or comfy_root).parent
        if not is_windows():
            for candidate in sorted(base.glob("run*.sh")):
                low = candidate.name.lower()
                if "cpu" not in low and "test" not in low:
                    return candidate
            main_py = Path(root or comfy_root) / "main.py"
            return main_py if main_py.is_file() else None
        for name in preference:
            candidate = base / name
            if candidate.is_file():
                return candidate
        for candidate in sorted(base.glob("run*.bat")):
            low = candidate.name.lower()
            if "cpu" not in low and "test" not in low:
                return candidate
        return None

    def comfy_launch_command(self, launcher, *, cfg, environment, tui, logs, url,
                                 here, platform, is_windows, console_python,
                                 python_candidates, executable):
        """(argv, cwd, env) for the ComfyUI console - wrapped, or raw.

        Both nt paths run the same .bat: its --fast fp16_accumulation,
        --use-sage-attention and vcvars call are load-bearing, and bypassing them is
        measurable as a slower machine. The only question is who owns the window.
        POSIX has no window to own and no tuned .bat: a run*.sh goes through bash,
        a bare checkout through its own main.py with the best local python.
        """
        env = dict(environment)
        editor = bool(cfg.get("comfy_editor"))
        if cfg.get("comfy_console") != "plain" and tui.is_file() \
                and platform == "win32":
            cmd = [console_python(), str(tui), "--launcher", str(launcher),
                   "--log-dir", str(logs), "--url", url,
                   "--expect", str(cfg.get("comfy_boot_seconds") or 0.0)]
            if editor:
                cmd.append("--editor")
            # here, not the launcher's folder: the wrapper cd's the .bat itself, and
            # running from Pixal's root keeps its logs where Pixal's logs live.
            return cmd, str(here), env
        if not is_windows():
            if launcher.suffix == ".sh":
                # bash, never ./run.sh: a fresh clone may not carry the +x bit.
                return ["bash", str(launcher)], str(launcher.parent), env
            # The checkout's own main.py. Args actually forward here, so the
            # comfy_editor contract keeps its shape: --disable-auto-launch is the
            # direct form of the rundll32 trick the nt raw path is forced into.
            python = next((str(p) for p in python_candidates(launcher.parent)
                           if p.is_file()), executable)
            cmd = [python, str(launcher)]
            if not editor:
                cmd.append("--disable-auto-launch")
            return cmd, str(launcher.parent), env
        if not editor:
            # ComfyUI's --windows-standalone-build implies auto-launching its graph
            # editor, and portable launchers forward no args, so --disable-auto-launch
            # can't be passed. The polite off-switch is the BROWSER env var Python's
            # webbrowser honors: rundll32 with a URL argument exits silently, no
            # window. Settings > comfy_editor turns the popup back on for the next
            # ComfyUI boot. (The wrapper does this for itself, from --editor.)
            env["BROWSER"] = os.path.join(environment.get("SystemRoot", r"C:\Windows"),
                                          "System32", "rundll32.exe")
        return ["cmd.exe", "/c", str(launcher)], str(launcher.parent), env

    async def ensure_comfy_running(self, *, reachable, listener_pid, taskkill,
                                       find_launcher, launch_command, is_windows,
                                       forget_residency, comfy_up, read_config,
                                       save_config, last_error, clock, sleep, to_thread):
        """Bring ComfyUI up through its own launcher when it isn't already.

        So one click on Pixal is the whole studio: the sidecar starts, notices
        ComfyUI is down, and boots it in its own console while the UI shows a meter.
        """
        self.desired = "running"
        if await reachable():
            self.observed = "reachable"
            self.boot["stalled_since"] = None      # it answered - no stall to report
            return
        # A boot still IN FLIGHT is not a reason to start a second one: two
        # launchers race for port 8188, one wins the bind and the loser runs on with
        # no port, which is precisely a ghost backend. self.boot["at"] is what "in
        # flight" means - every exit path in the watcher below clears it.
        #
        # A live child with NO boot in flight is a different animal, and conflating
        # the two is what wedged the studio (2026-08-13). When ComfyUI crashes its
        # .bat parks on "Press any key to continue", so cmd.exe stays alive forever
        # and every later attempt returned right here, instantly: no boot, no error,
        # nothing running, for the rest of the sidecar's life. That console is a
        # corpse holding the door open - close it and start a fresh one.
        self.observed = "unreachable"
        live = self.boot.get("proc")
        if live is not None and self.runner.poll(live) is None:
            if self.boot.get("at"):
                self.observed = "booting"
                return
            # A BUSY ComfyUI is not a corpse. Loading the 8B VL critic or the H3
            # stack holds its event loop long past reachable's timeout, the
            # bridge websocket drops, and /api/status re-enters here every 4s for as
            # long as comfy_up is false - so without this check a big model load
            # gets its whole tree taskkill'd mid-render (2026-08-14). The port is
            # the discriminator: a .bat parked on "Press any key" has no python left
            # holding the socket, while a stalled one is still bound. A boot that
            # timed out never bound it either, so it is still correctly reaped.
            if await to_thread(listener_pid) is not None:
                # Never kill a process that still owns the port. But do not leave the
                # user staring at a meterless "waiting for ComfyUI" either: record
                # when the stall began so comfy_boot_state can offer a way out.
                self.observed = "stalled"
                if self.boot["stalled_since"] is None:
                    self.boot["stalled_since"] = clock()
                return
            # A TREE kill, not Popen.kill(): the handle we hold is cmd.exe, and
            # ComfyUI's python sits UNDER it. Terminating the console alone leaves
            # that python resident - holding VRAM, owning no port, unreachable by
            # any later lookup - and then this function boots a rival onto the same
            # card. That is the ghost backend, manufactured by the very code meant
            # to prevent it. (The corpse case has no python left to reap; the
            # timed-out-boot case very much does.)
            try:
                # off the loop: taskkill blocks up to 20s, and this path now runs
                # on the same 4s poll that drives the boot meter
                await to_thread(taskkill, live.pid)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"[pixal] could not close the stale ComfyUI console: {exc}",
                      flush=True)
            self.boot["proc"] = None
        launcher = find_launcher()
        if not launcher:
            shape = ".bat" if is_windows() else "run*.sh or main.py"
            self.boot["error"] = (f"no ComfyUI launcher ({shape}) found beside the "
                                   "ComfyUI folder - start it yourself")
            print("[pixal] " + self.boot["error"], flush=True)
            return
        self.boot.update(at=clock(), launcher=str(launcher), error=None)
        # A fresh ComfyUI holds nothing. The log has 25+ of these in one session and
        # the butler credited every one of them with the dead process's residency.
        forget_residency("comfy restarting")
        print(f"[pixal] starting ComfyUI via {launcher.name}", flush=True)
        try:
            cmd, cwd, env = launch_command(launcher)
            self.boot["proc"] = self.runner.start(cmd, cwd=cwd, env=env, windows=is_windows())
            self.observed = "booting"
        except OSError as exc:
            self.boot.update(at=None, error=f"could not start {launcher.name}: {exc}")
            print("[pixal] " + self.boot["error"], flush=True)
            return
        # Snapshot the boot stamp: another path (an adopt, a reset, a rival boot)
        # can clear self.boot["at"] while this watcher sleeps, and the first
        # reachable poll then subtracted None and took the whole task down
        # (sidecar.log, 2026-08-26, mid H3 2x clip).
        started = self.boot["at"]
        # Our OWN handle on the console we just opened. Re-reading self.boot["proc"]
        # every tick looked equivalent and was not: stop_comfy() nulls that field,
        # so the moment anything stopped ComfyUI this watcher went blind to the
        # death of the very child it had launched. It then polled a dead port for
        # the rest of its grace - up to 15 minutes of wall clock, because each tick
        # is a 2s sleep plus a 3s probe timeout - while kick_comfy_boot's
        # one-attempt-at-a-time guard handed that same lost task back to every
        # later caller. Retry, reload and /api/comfy/restart all became no-ops
        # behind a meterless "waiting for ComfyUI" (2026-09-04).
        mine = self.boot.get("proc")
        for _ in range(180):                                    # 6 minutes of grace
            await sleep(2)
            # Someone stopped or replaced this boot: it is no longer ours to report
            # on, and whoever owns self.boot now owns its error and its meter too.
            if self.boot.get("proc") is not mine:
                return
            if await reachable(timeout=3):
                self.observed = "reachable"
                stamp = self.boot["at"] or started
                took = round(clock() - stamp, 1) if stamp else None
                print(f"[pixal] ComfyUI up in {took}s" if took is not None
                      else "[pixal] ComfyUI up", flush=True)
                if took is not None:
                    cfg = read_config()                # calibrate the next boot meter
                    cfg["comfy_boot_seconds"] = took
                    save_config(cfg)
                # Hold the boot state until the hub's own watcher agrees. Clearing it
                # the moment the port answers blinks the UI through a frame that says
                # "waiting for ComfyUI" with no meter, right at the finish line.
                for _ in range(20):
                    if comfy_up():
                        break
                    await sleep(1)
                self.boot["at"] = None
                return
            # A launcher that has already exited is never going to answer, so a
            # crashed boot reports in seconds instead of riding out the grace.
            # (A .bat parked on `pause` after a crash keeps cmd.exe alive; that
            # shape still takes the timeout - poll() catches the clean exits.)
            proc = mine
            if proc is not None and self.runner.poll(proc) is not None:
                self.observed = "exited"
                # "its console window has the error" was true and useless: by the
                # time anyone reads this the window is gone. The wrapper leaves the
                # reason on disk, so say the reason.
                why = last_error()
                self.boot.update(at=None, error=(
                    f"ComfyUI exited during boot - {why}" if why else
                    "ComfyUI exited during boot - the output is in logs\\comfy.log"))
                print("[pixal] " + self.boot["error"], flush=True)
                return
        self.observed = "unreachable"
        why = last_error()
        self.boot.update(at=None, error=("ComfyUI did not come up within 6 minutes"
                                          + (f" - {why}" if why else "")))
        print("[pixal] " + self.boot["error"], flush=True)

    def comfy_listener_pid(self, port=None, *, url):
        """The pid listening on ComfyUI's port, whoever started it.

        We only know our own child's pid when WE launched it, and the common case
        is a ComfyUI the user started. The port is the one handle that identifies
        it either way.
        """
        port = int(port or urllib.parse.urlparse(url).port or 8188)
        try:
            # getattr, not a bare 0x08000000: creationflags raises ValueError - which
            # the except below does NOT catch - on any non-Windows platform, and the
            # Linux half of CI reaches this the moment a test exercises the caller.
            out = self.runner.run_hidden(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                                 text=True, timeout=15).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3].upper() == "LISTENING" \
                    and parts[1].rsplit(":", 1)[-1] == str(port):
                try:
                    return int(parts[4])
                except ValueError:
                    continue
        return None

    def _taskkill(self, pid, timeout=20, *, is_windows):
        """Kill a process and everything under it.

        /T because ComfyUI's launcher .bat sits between us and python: killing
        either one on its own leaves the other running. POSIX gets the same reach
        from the process group: the launcher is spawned with start_new_session, so
        one killpg takes launcher and python down together."""
        if is_windows():
            self.runner.run_hidden(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=timeout)
            return
        try:
            self.runner.terminate_group(pid)
        except (ProcessLookupError, PermissionError):
            pass

    def stop_comfy(self, timeout=20, *, is_local, listener_pid, taskkill):
        """Stop every ComfyUI this sidecar is responsible for; return the pids killed.

        Two handles, because either one alone leaves something behind. The tracked
        child catches a ComfyUI that never bound the port - the ghost case, which by
        definition no port lookup can find. The port owner catches one that outlived
        the sidecar that spawned it. Remote compute is never touched; that is
        someone else's box and someone else's session.
        """
        self.desired = "stopped"
        self.observed = "unobserved"  # kill dispatch is not an observed exit
        stopped = []
        proc = self.boot.get("proc")
        if proc is not None:
            if self.runner.poll(proc) is None:
                taskkill(proc.pid, timeout)
                stopped.append(proc.pid)
            self.boot["proc"] = None
        if is_local():
            pid = listener_pid()
            if pid and pid not in stopped:
                taskkill(pid, timeout)
                stopped.append(pid)
        return stopped

    def comfy_closed_by_user(self):
        """Did the ComfyUI WE started go away because someone shut its window?

        Told apart from a crash by what is left behind. When ComfyUI crashes, its
        .bat parks on "Press any key to continue" and the cmd.exe we spawned stays
        alive holding that console - a corpse, which ensure_comfy_running is
        already built to clear away and replace. When someone closes the window,
        the whole process tree goes with it and our handle reports an exit code.

        Only ever true for a console this process launched: a ComfyUI the user
        started by hand was never ours to restart, and an adopted one leaves
        self.boot["proc"] as None, so neither is mistaken for a close.
        """
        proc = self.boot.get("proc")
        return bool(proc is not None and self.runner.poll(proc) is not None
                    and not self.boot.get("at"))

    async def cancel_comfy_boot(self):
        """Stop an attempt in flight and wait for it to actually let go.

        An explicit "start it again" must not join a boot that is already lost.
        Cancelling BEFORE stop_comfy matters: the other order lets the cancelled
        watcher hand self.boot a proc we have already killed.
        """
        task = self.boot.get("task")
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if self.boot.get("task") is task:
            self.boot["task"] = None

    def kick_comfy_boot(self, *, ensure_running, create_task):
        """Start ComfyUI on demand, at most one attempt in flight.

        Re-entrant on purpose: if a previous attempt finished - including one that
        failed, or one whose ComfyUI has since died - reloading the page tries
        again, which makes the overlay's retry button mean something.

        Every caller here is an INTENT to have ComfyUI running - opening the app,
        the overlay's start button - and each of them starts a boot, which replaces
        self.boot["proc"] and so clears the closed-by-user reading on its own.
        Nothing has to be un-latched. status()'s poll is the one caller that asks
        first, because it speaks for nobody.
        """
        self.desired = "running"
        task = self.boot.get("task")
        if task is not None and not task.done():
            return task
        task = create_task(ensure_running())
        self.boot["task"] = task
        return task

