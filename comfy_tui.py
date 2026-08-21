"""The ComfyUI console, rewritten as something worth looking at.

Pixal starts ComfyUI through its own launcher .bat (the flags in that file are
load-bearing - see ensure_comfy_running) and that .bat used to get a raw console
window. Two things were wrong with it. It scrolled roughly 1700 lines of node
pack chatter, so the one line that mattered - the import that failed, the module
that is missing - went past too fast to read and was gone forever the moment the
window closed. And it told you nothing about how far along the boot was: 30-60
seconds of silence, then either a studio or nothing.

So this wraps the launcher instead of replacing it. Same .bat, same flags, same
environment; the output goes through a pipe, and this process draws it:

  - the boot as a phase list with real per-phase times, calibrated against the
    last good boot on THIS machine (logs/comfy-boot-profile.json)
  - a card meter, because a starved GPU is the thing that goes wrong here
  - the sampler's own progress once ComfyUI is up, so the window keeps earning
    its space instead of just proving something is on the card
  - every line, ANSI stripped and stamped with seconds-since-launch, in
    logs/comfy.log - which is what makes "where did it hang" answerable
  - errors ONLY, with the traceback attached and the boot phase they happened
    in, in logs/comfy-errors.log. That file is the whole point: it outlives the
    window.

Three contracts this must not break, all of them paid for:

  1. The window is the VRAM indicator. Open means something is still on the
     card, and closing it takes ComfyUI down with it. A pipe means the child is
     no longer attached to this console, so a Windows job object carries that
     contract instead: everything spawned under here dies when this exits.
  2. The pipe must never fill. 64KB of unread output blocks ComfyUI mid-render,
     which would be a far worse bug than the one this fixes - so the reader
     thread is unconditional and the renderer is wrapped in a net that degrades
     to plain printing rather than taking the drain down with it.
  3. Nothing here may be required. Settings -> "when ComfyUI boots" -> plain
     console puts the old raw window back, and this file is never imported by
     the sidecar - it is only ever spawned.

Windows only, stdlib only: it has to run on the ComfyUI portable's embeddable
python, which has neither a venv nor pip.
"""
import argparse
import codecs
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue

WINDOWS = os.name == "nt"
if WINDOWS:
    import msvcrt

# ------------------------------------------------------------------ the paint

# Straight off the studio's design tokens, so the console reads as the same
# product as the app: neutral charcoal, one electric chartreuse signal.
ACCENT = (214, 243, 47)
OK = (123, 180, 149)
WARN = (251, 191, 36)
# The app's error token (#8A3040) is a deep wine that all but disappears on a
# black console. This is that hue dragged up into legibility - the only place
# the console deliberately parts company with the tokens.
BAD = (224, 87, 107)
DIM = (118, 126, 134)
TEXT = (234, 237, 239)
MUTE = (150, 158, 166)

USE_COLOR = True


def rgb(text, color, bold=False):
    if not USE_COLOR:
        return text
    r, g, b = color
    return f"\x1b[{1 if bold else 0};38;2;{r};{g};{b}m{text}\x1b[0m"


# ANSI Shadow. 35 columns wide, 6 rows - it fits an 80-column console with room
# to spare, and drops to the one-line mark below that.
BANNER = (
    r"██████╗ ██╗██╗  ██╗ █████╗ ██╗     ",
    r"██╔══██╗██║╚██╗██╔╝██╔══██╗██║     ",
    r"██████╔╝██║ ╚███╔╝ ███████║██║     ",
    r"██╔═══╝ ██║ ██╔██╗ ██╔══██║██║     ",
    r"██║     ██║██╔╝ ██╗██║  ██║███████╗",
    r"╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝",
)
# Deliberately the oldest spinner there is. Braille reads better and Cascadia
# Mono has it, but a console opened with Consolas draws those as tofu, and this
# window has to look right in whatever terminal the machine hands it.
SPINNER = "|/-\\"

# ------------------------------------------------------------------ the boot

# The same five markers, in the same order, mapped to the same words the sidecar
# reports to the web overlay (server.py _BOOT_PHASES). One boot, two windows,
# one vocabulary - a console that said "importing nodes" while the app said
# "loading node packs" would read as two different machines. test_comfy_tui
# asserts the pairing so a rename on either side cannot drift silently.
PHASES = (("** ComfyUI startup time", "waking Python"),
          ("Prestartup times", "prestart hooks"),
          ("Total VRAM", "loading node packs"),
          ("Import times for custom nodes", "final checks"),
          ("Starting server", "starting the web server"))

# What a cold boot spends its time on before this machine has told us otherwise.
# Node packs dominate so completely that a bar weighted evenly across five
# phases would sit at 40% for half a minute and then jump. Replaced wholesale by
# the measured profile after the first good boot.
FALLBACK_WEIGHTS = (0.04, 0.03, 0.74, 0.11, 0.08)
FALLBACK_EXPECT = 45.0

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*(?:\x07|\x1b\\)")
_LEVEL = re.compile(r"^\[(INFO|DEBUG|WARNING|ERROR|CRITICAL)\]\s?")
# tqdm, as ComfyUI's sampler emits it:  " 30%|███       | 3/10 [02:01<04:22, 37.53s/it]"
_TQDM = re.compile(r"^\s*(\d+)%\|[^|]*\|\s*(\d+)/(\d+)\s*\[([^<]*)<([^,]*),\s*([^\]]*)\]")
_IMPORT_TIME = re.compile(r"^\s*\d+\.\d+ seconds(?: \(IMPORT FAILED\))?:")

# A line that is worth waking someone for. Everything else lives in comfy.log.
_ERROR_MARKS = ("Traceback (most recent call last):", "IMPORT FAILED",
                "ModuleNotFoundError", "ImportError:", "Cannot import",
                "CUDA out of memory", "OutOfMemoryError",
                "is not recognized as an internal or external command",
                "The system cannot find the path specified",
                "Access is denied.")
# Python's warning machinery writes to stderr in two lines - the location and
# the offending source - and a node pack that imports a deprecated API is not a
# problem the user has. They stay in comfy.log; they do not get counted as
# warnings on screen either, or the counter would read 200 on a healthy boot.
_NOISE = ("FutureWarning", "DeprecationWarning", "UserWarning",
          "warnings.warn", "TracerWarning")


def strip_ansi(text):
    return _ANSI.sub("", text).replace("\x00", "")


def fmt_secs(seconds):
    """Durations the way a person says them: 0.4s, 12.8s, 1m 04s."""
    seconds = max(0.0, float(seconds))
    if seconds < 100:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"


def bar(fraction, width, color=ACCENT):
    fraction = min(1.0, max(0.0, fraction))
    filled = int(round(fraction * width))
    return rgb("█" * filled, color) + rgb("░" * (width - filled), DIM)


def clip(text, width):
    """Trim to a column budget, ellipsis included, never mid-escape.

    Only ever called on plain text - colour is added after, so the count is the
    count."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[:max(0, width - 1)] + "…"


def clip_left(text, width):
    """Trim a path from the FRONT. Which drive it is on is never the question;
    which file it is always is."""
    if width <= 0 or len(text) <= width:
        return text if width > 0 else ""
    return "…" + text[-(width - 1):]


# ------------------------------------------------------------- windows plumbing

_JOB = None


def own_the_tree():
    """Make every process started under here die when this one does.

    The raw console had this for free: closing a console window kills what is
    attached to it, which is why an open ComfyUI window has always meant "still
    on the card". The launcher runs on a pipe now with no console of its own, so
    without this an X on the title bar would leave ComfyUI resident, holding
    VRAM, owning a port nothing is pointing at - the exact ghost backend the
    sidecar's whole lifecycle layer exists to prevent.

    A job object with KILL_ON_JOB_CLOSE assigned to OURSELVES is the version of
    that contract with no race in it: children inherit job membership at
    creation, so there is no window between spawn and assignment for a grandchild
    to escape through. Returns whether it took - the caller keeps a taskkill
    fallback for the machine where it does not.
    """
    global _JOB
    if not WINDOWS:
        return False

    class _IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in
                    ("ReadOperationCount", "WriteOperationCount",
                     "OtherOperationCount", "ReadTransferCount",
                     "WriteTransferCount", "OtherTransferCount")]

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", ctypes.c_ulong),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_ulong),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_ulong),
                    ("SchedulingClass", ctypes.c_ulong)]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _IO),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000   # KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info),
                                           ctypes.sizeof(info)):
            return False
        if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
            return False
    except (OSError, AttributeError):
        return False
    _JOB = job                      # held open on purpose: closing it kills us
    return True


def console_setup(title):
    """UTF-8, virtual terminal, a title, and a window big enough to draw in."""
    global USE_COLOR
    if not sys.stdout.isatty():
        USE_COLOR = False
        return False
    if not WINDOWS:
        return True
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.SetConsoleTitleW(title)
        k32.SetConsoleOutputCP(65001)
        handle = k32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING. Without it every escape in
            # this file would print as literal gibberish, so a console that
            # refuses gets a plain-text render instead.
            if not k32.SetConsoleMode(handle, mode.value | 0x0004):
                USE_COLOR = False
    except (OSError, AttributeError):
        USE_COLOR = False
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    _resize(96, 36)
    return True


def _resize(cols, rows):
    """Ask for a window the dashboard fits in. Best effort, and asked twice.

    The two console hosts on this platform take different instructions: legacy
    conhost resizes for `mode con:` and ignores the escape, Windows Terminal
    does the exact opposite. A host that refuses both just draws narrower -
    compose() lays out to whatever it is actually given."""
    try:
        sys.stdout.write(f"\x1b[8;{rows};{cols}t")
        sys.stdout.flush()
    except (OSError, ValueError):
        pass
    try:
        subprocess.run(["mode", "con:", f"cols={cols}", f"lines={rows}"],
                       shell=True, capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def open_in_editor(path):
    try:
        os.startfile(str(path))                          # noqa: S606 - Windows
        return True
    except (OSError, AttributeError):
        return False


# ------------------------------------------------------------------ the reader

def pump(stream, sink):
    """Drain the child's merged output into `sink`, one record per line.

    Splits on \\r as well as \\n because tqdm redraws a sampler bar by carriage
    return - treating those as one enormous line would mean the bar only ever
    appeared after the render finished. Reads at the file-descriptor level so a
    partial line is never held hostage by a buffer that has not filled.
    """
    fd = stream.fileno()
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    tail = ""
    while True:
        try:
            chunk = os.read(fd, 16384)
        except OSError:
            break
        if not chunk:
            break
        tail += decoder.decode(chunk)
        *records, tail = re.split(r"\r\n|\n|\r", tail)
        for record in records:
            sink(record)
    if tail:
        sink(tail)
    sink(None)                                           # end of stream


# ------------------------------------------------------------------- the state

class Boot:
    """Everything the screen knows, assembled one log line at a time."""

    def __init__(self, launcher, expect, profile):
        self.launcher = launcher
        self.t0 = time.monotonic()
        self.expect = expect if expect > 1 else FALLBACK_EXPECT
        self.profile = profile or {}
        self.phase = 0                    # index into PHASES, -1 once up
        self.phase_at = [self.t0] + [None] * (len(PHASES) - 1)
        self.done_at = None
        self.died_at = None
        self.exit_code = None
        self.facts = {}
        self.packs = 0
        self.errors = 0
        self.warnings = 0
        self.last_error = ""
        self.line = ""
        self.tail = deque(maxlen=12)
        self.sampling = None              # (percent, done, total, eta, rate)
        self.sampling_at = 0.0
        self.renders = 0
        self.last_render = ""
        self.port_ok = None
        self.gpu = None                   # (used_mb, total_mb, util, temp)
        self._held = None                 # the sampler bar's newest frame

    # -- boot geometry ----------------------------------------------------

    @property
    def elapsed(self):
        return time.monotonic() - self.t0

    @property
    def up(self):
        return self.done_at is not None

    def weights(self):
        """Per-phase share of the boot, measured on this machine when possible.

        The profile stores the last good boot's phase DURATIONS, so a machine
        that spends 40 seconds on node packs and two on everything else gets a
        bar that spends its time where the boot does.
        """
        measured = [float(self.profile.get(name) or 0.0) for _, name in PHASES]
        total = sum(measured)
        if total <= 0:
            return FALLBACK_WEIGHTS
        return tuple(m / total for m in measured)

    def progress(self):
        """How far along, blending the phase we are in with the clock.

        Elapsed alone is a guess that a cold pack cache makes a lie; the phase
        alone steps in five jumps. Together the bar advances continuously and
        still snaps to the truth every time a marker lands. It holds short of
        full until ComfyUI actually answers - the last sliver is never ours."""
        if self.up:
            return 1.0
        weights = self.weights()
        base = sum(weights[:self.phase])
        started = self.phase_at[self.phase] or self.t0
        budget = float(self.profile.get(PHASES[self.phase][1]) or
                       (weights[self.phase] * self.expect)) or 1.0
        within = min(1.0, (time.monotonic() - started) / budget)
        return min(0.97, base + within * weights[self.phase])

    def phase_seconds(self, index):
        """Wall time in a phase: measured if it is behind us, live if we are
        in it, None if it has not happened."""
        start = self.phase_at[index]
        if start is None:
            return None
        if index < self.phase:
            nxt = self.phase_at[index + 1] or start
            return nxt - start
        end = self.done_at if (self.up and index == self.phase) else time.monotonic()
        return end - start

    def record_profile(self, path):
        """Bank this boot's shape for the next one's meter."""
        phases = {}
        for i, (_, name) in enumerate(PHASES):
            seconds = self.phase_seconds(i)
            if seconds and seconds > 0:
                phases[name] = round(seconds, 2)
        try:
            path.write_text(json.dumps({"total": round(self.done_at - self.t0, 2),
                                        "phases": phases}, indent=1),
                            encoding="utf-8")
        except OSError:
            pass

    # -- reading the stream ----------------------------------------------

    def feed(self, raw, errlog):
        """One line of ComfyUI's output, turned into screen state.

        Returns the lines to write to comfy.log - usually one, none for a
        sampler frame that a newer one will replace, two when a held frame is
        finally overtaken. That is how a 400-frame progress bar contributes a
        single line to the transcript while still driving a live meter.
        """
        text = strip_ansi(raw).rstrip()
        if not text.strip():
            return []
        level_match = _LEVEL.match(text)
        level = level_match.group(1) if level_match else ""
        body = text[level_match.end():] if level_match else text

        held = errlog.feed(body, level, self.phase_name(), self.elapsed)
        if held == "error":
            self.errors += 1
            self.last_error = errlog.headline
        elif held == "warning":
            self.warnings += 1

        sample = _TQDM.match(body)
        if sample:
            self.sampling = (int(sample.group(1)), int(sample.group(2)),
                             int(sample.group(3)), sample.group(5).strip(),
                             sample.group(6).strip())
            self.sampling_at = time.monotonic()
            # Held, not written: only the last frame of a bar is a record, and
            # which one that is is not known until something else speaks.
            self._held = text
            return []

        self._advance(body)
        self._collect(body)
        self.line = body
        if not _IMPORT_TIME.match(body):
            self.tail.append((level, body))
        return self.flush_bar() + [text]

    def flush_bar(self):
        held, self._held = self._held, None
        return [held] if held else []

    def phase_name(self):
        return "ready" if self.up else PHASES[self.phase][1]

    def _advance(self, body):
        for i in range(len(PHASES) - 1, self.phase, -1):
            if PHASES[i][0] in body:
                # Backfill: a phase whose marker we never saw still ended when
                # the next one started, so the list never shows a gap.
                for j in range(self.phase + 1, i + 1):
                    if self.phase_at[j] is None:
                        self.phase_at[j] = time.monotonic()
                self.phase = i
                return

    def _collect(self, body):
        """Facts worth putting in the header, harvested as they scroll past."""
        take = (("Total VRAM", r"Total VRAM (\d+) MB, total RAM (\d+) MB", "ram"),
                ("Device:", r"Device: \S+ (.+?) :", "gpu"),
                ("ComfyUI version:", r"ComfyUI version: (\S+)", "comfy"),
                ("pytorch version:", r"pytorch version: (\S+)", "torch"),
                (" attention", r"Using (\S+) attention", "attention"),
                ("Set vram state", r"Set vram state to: (\S+)", "vram_state"),
                ("To see the GUI", r"To see the GUI go to: (\S+)", "url"))
        for marker, pattern, key in take:
            if marker in body and key not in self.facts:
                hit = re.search(pattern, body)
                if hit:
                    self.facts[key] = hit.group(1) if key != "ram" else \
                        (int(hit.group(1)), int(hit.group(2)))
                    # ComfyUI prints its address once it has BOUND the port, so
                    # that line is the boot finishing. Waiting on the health
                    # poll instead left the console spinning "starting the web
                    # server" at a ComfyUI that had plainly already started.
                    if key == "url":
                        self.mark_up()
        if _IMPORT_TIME.match(body) and self.phase >= 3:
            self.packs += 1
        if "Prompt executed in" in body:
            self.renders += 1
            self.sampling = None
            hit = re.search(r"Prompt executed in ([\d.]+) seconds", body)
            self.last_render = f"{float(hit.group(1)):.1f}s" if hit else ""
        elif "got prompt" in body:
            self.sampling = None

    def mark_up(self):
        if self.done_at is None:
            self.done_at = time.monotonic()


# --------------------------------------------------------------- the error log

class ErrorLog:
    """Errors only, with their tracebacks, outliving the window they scrolled in.

    Everything is in comfy.log; nobody reads 1700 lines. This file is the one a
    person opens, so what lands in it has to be worth the trip: an error keeps
    the traceback that explains it and the boot phase it happened in, and a
    known-benign one is quietly counted instead of shouted.
    """

    def __init__(self, path, oneline, launcher):
        self.path = path
        self.oneline = oneline
        self.launcher = launcher
        self.headline = ""
        self.count = 0
        self._fh = None
        self._trace = None
        self._folded = False
        self._pending = None
        self._context = ""
        # A stale one-liner would let the sidecar report the LAST boot's failure
        # over a boot that is doing fine, so it starts every run gone.
        try:
            self.oneline.unlink()
        except OSError:
            pass

    def _open(self):
        """Opened on the first error, never before: a clean boot must not leave
        a header behind saying it had something to say."""
        if self._fh is None:
            try:
                if self.path.exists() and self.path.stat().st_size > 2_000_000:
                    self.path.replace(self.path.with_suffix(".prev.log"))
                self._fh = open(self.path, "a", encoding="utf-8", errors="replace")
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._fh.write(f"\n{'=' * 78}\n{stamp}  ComfyUI via "
                               f"{self.launcher}\n{'=' * 78}\n")
            except OSError:
                self._fh = False
        return self._fh or None

    def write(self, phase, elapsed, lines, headline=None):
        # The LAST line is the headline in both shapes: a traceback ends on the
        # exception, and a bare error line is preceded by its context, so
        # taking the first would report the innocent line above the problem.
        self.count += 1
        self.headline = clip(headline or lines[-1], 300)
        handle = self._open()
        if handle:
            stamp = datetime.now().strftime("%H:%M:%S")
            try:
                handle.write(f"\n[{stamp}] {fmt_secs(elapsed)} in, during "
                             f"\"{phase}\"\n")
                handle.write("".join(f"  {line}\n" for line in lines))
                handle.flush()
            except OSError:
                pass
        try:
            self.oneline.write_text(self.headline, encoding="utf-8")
        except OSError:
            pass

    def feed(self, body, level, phase, elapsed):
        """Classify one line. Returns "error", "warning" or "" .

        Tracebacks are captured whole - a bare "ModuleNotFoundError" with no
        frames above it names the symptom and hides which pack caused it, which
        is precisely the question being asked."""
        if self._trace is not None:
            return self._continue_trace(body, phase, elapsed)
        if body.startswith("Traceback (most recent call last):"):
            # ComfyUI announces a failure and THEN prints the stack for it
            # ("!!! Exception during processing !!!" on one line, the traceback
            # on the next). Those are one incident: folding the announcement in
            # keeps the count honest and puts the headline above its own stack.
            pending, self._pending = self._pending, None
            self._folded = pending is not None
            head = pending[0] if pending else ([self._context] if self._context else [])
            self._trace = head + [body]
            return ""
        if self._pending is not None and body.startswith((" ", "\t")):
            # An indented line belongs to the error above it - bitsandbytes puts
            # a hint between its complaint and the stack that proves it, and
            # letting that split the two made one failure look like two.
            self._pending[0].append(body)
            return ""
        self.flush()
        if any(n in body for n in _NOISE):
            return ""
        if level in ("ERROR", "CRITICAL") or any(m in body for m in _ERROR_MARKS):
            # Held open until the next unrelated line, in case what follows is
            # its own traceback. `body` is kept as the headline because the
            # continuation lines under it are hints, not the fault.
            self._pending = ([self._context, body] if self._context else [body],
                             phase, elapsed, body)
            return "error"
        self._context = body
        return "warning" if level == "WARNING" else ""

    def close(self):
        self.flush()
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
        self._fh = False

    def flush(self):
        """Commit an error that turned out to have no traceback under it."""
        if self._pending is not None:
            lines, phase, elapsed, head = self._pending
            self._pending = None
            self.write(phase, elapsed, lines, headline=head)

    def _continue_trace(self, body, phase, elapsed):
        """Keep swallowing frames until the exception line closes the block."""
        block = self._trace
        if len(block) > 200:                             # a runaway recursion
            self._trace = None
            return self._finish(block, phase, elapsed)
        if not body.strip() or body.startswith((" ", "\t")):
            block.append(body)
            return ""
        if body.startswith(("Call stack:", "During handling", "The above exception")):
            block.append(body)
            return ""
        block.append(body)                               # the exception itself
        self._trace = None
        return self._finish(block, phase, elapsed)

    def _finish(self, block, phase, elapsed):
        folded, self._folded = self._folded, False
        # A stack under an explicit [ERROR] line is never noise, whatever it
        # says - the benign filter only gets to judge unannounced ones.
        if not folded and self._benign(block):
            return "warning"
        self.write(phase, elapsed, block)
        return "" if folded else "error"      # folded ones were counted already

    @staticmethod
    def _benign(block):
        """ComfyUI's own log handler throws UnicodeEncodeError whenever a node
        prints an emoji into a cp1252 console - a full traceback, several times
        a boot, about nothing. This launcher hands the child PYTHONIOENCODING
        =utf-8 so it should not recur at all; when it does, it is noise with a
        stack trace and does not belong in the file people open at 2am."""
        text = "\n".join(block)
        return "UnicodeEncodeError" in text and ("app\\logger.py" in text
                                                 or "logging" in text)


# ------------------------------------------------------------------- telemetry

class Telemetry(threading.Thread):
    """The card, and whether the port answers. Both off the render loop.

    The card is here because on this machine a boot that goes wrong goes wrong
    at the VRAM line: a model streaming from system memory pins the GPU at 100%
    with the card nearly empty, and no amount of log reading says so as fast as
    a meter does. The port is here because a ComfyUI that owns 8188 and is not
    answering is the normal shape of a large model load - saying so is much
    kinder than a window that has apparently stopped.
    """

    daemon = True

    def __init__(self, state, url):
        super().__init__(name="pixal-telemetry")
        self.state = state
        self.url = url.rstrip("/")
        self.stop = threading.Event()

    def run(self):
        import urllib.request
        misses = 0
        while not self.stop.wait(2.0):
            # On a machine with no nvidia-smi this would otherwise spawn a
            # process every two seconds for the rest of the session, to be told
            # the same thing every time.
            if misses < 3:
                self.state.gpu = self._card()
                misses = 0 if self.state.gpu else misses + 1
            try:
                with urllib.request.urlopen(f"{self.url}/system_stats",
                                            timeout=3) as response:
                    self.state.port_ok = response.status == 200
            except Exception:                            # any failure is "no"
                self.state.port_ok = False
            if self.state.port_ok and not self.state.up:
                self.state.mark_up()

    @staticmethod
    def _card():
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total,"
                 "utilization.gpu,temperature.gpu",
                 "--format=csv,noheader,nounits"], capture_output=True,
                text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if out.returncode != 0:
                return None
            return tuple(int(v.strip()) for v in
                         out.stdout.strip().splitlines()[0].split(","))
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return None


# -------------------------------------------------------------------- the draw

class Screen:
    """A diffing full-screen renderer: only the lines that changed are written.

    Redrawing everything at 10fps flickered and made the window feel busy while
    a boot was doing nothing. Comparing against the last frame means an idle
    ComfyUI costs one clock line a second.
    """

    def __init__(self):
        self.previous = []
        self.size = None

    def reset(self):
        self.previous = []
        sys.stdout.write("\x1b[2J\x1b[H")

    def paint(self, lines, width, height):
        # A window dragged narrower leaves the tails of the old frame behind on
        # every line the new one happens not to change, so a resize is a repaint
        # from scratch rather than a diff against a frame of a different shape.
        if self.size != (width, height):
            self.size = (width, height)
            self.reset()
        out = []
        lines = lines[:height - 1]
        for i, line in enumerate(lines):
            if i < len(self.previous) and self.previous[i] == line:
                continue
            out.append(f"\x1b[{i + 1};1H\x1b[K{line}")
        for i in range(len(lines), len(self.previous)):
            out.append(f"\x1b[{i + 1};1H\x1b[K")
        if out:
            sys.stdout.write("".join(out))
            sys.stdout.flush()
        self.previous = lines


def compose(state, width, height, paths, confirm_quit):
    """The whole window, as a list of already-coloured lines."""
    inner = min(max(width, 24), 110) - 4
    pad = "  "
    L = []
    spin = SPINNER[int(time.monotonic() * 10) % len(SPINNER)]

    # -- header --------------------------------------------------------
    if height >= 26 and width >= 74:
        L.append("")
        for i, row in enumerate(BANNER):
            side = ""
            if i == 1:
                side = rgb("e n g i n e   r o o m", MUTE)
            elif i == 3:
                side = rgb(clip(state.launcher, max(0, inner - 42)), DIM)
            L.append(pad + rgb(row, ACCENT) + ("   " + side if side else ""))
    else:
        L.append("")
        L.append(pad + rgb("P I X A L", ACCENT, bold=True) + rgb("   engine room", DIM))
    L.append("")

    facts = []
    if state.facts.get("comfy"):
        facts.append("ComfyUI " + state.facts["comfy"])
    if state.facts.get("gpu"):
        facts.append(state.facts["gpu"])
    if state.facts.get("torch"):
        facts.append("torch " + state.facts["torch"])
    if state.facts.get("attention"):
        facts.append(state.facts["attention"] + " attention")
    if state.packs:
        facts.append(f"{state.packs} node packs")
    L.append(pad + rgb(clip(" · ".join(facts) or "starting the launcher…", inner), DIM))
    L.append("")

    # -- the box: phases while booting, vitals once up ------------------
    # Deliberately narrower than the window. A five-row table stretched across
    # 96 columns is a row of labels with a lonely number at the far edge; at 64
    # it reads as one object, and the log river below gets the full width.
    panel = min(inner, 64)
    title = "stopped" if state.died_at else ("running" if state.up else "boot")
    L.append(pad + rgb("╭─ " + title + " " + "─" * (panel - len(title) - 5) + "╮", DIM))

    def row(text, right=""):
        """One line inside the box, optionally with a right-aligned column."""
        text = clip_ansi(text, panel - 4 - _plain_len(right))
        gap = max(1, panel - 3 - _plain_len(text) - _plain_len(right))
        L.append(pad + rgb("│", DIM) + " " + text + " " * gap + right +
                 rgb("│", DIM))

    if state.died_at:
        row(rgb(f"ComfyUI exited with code {state.exit_code}", BAD),
            rgb("after " + fmt_secs(state.died_at - state.t0), DIM))
        row("")
        row(rgb(clip(state.last_error or "nothing in the output said why - the "
                     "full log has everything", panel - 5), TEXT))
    elif state.up:
        # Three states, not two. Before the first health poll lands there is no
        # verdict to report, and printing the amber one read as a warning about
        # a ComfyUI that had just this second finished starting.
        port, tint = (("checking", MUTE) if state.port_ok is None else
                      ("answering", OK) if state.port_ok else
                      ("busy - big model load", WARN))
        row(rgb("up " + fmt_secs(time.monotonic() - state.done_at), TEXT) +
            rgb("  ·  ", DIM) + rgb("port " + port, tint),
            rgb(f"{state.renders} renders", MUTE))
        row("")
        if state.sampling and time.monotonic() - state.sampling_at < 20:
            pct, done, total, eta, rate = state.sampling
            pace = f"{rate}  eta {eta}"
            row(rgb(spin + " sampling  ", ACCENT) +
                bar(pct / 100, max(10, panel - 26 - len(pace))) +
                rgb(f"  {done}/{total}", TEXT), rgb(pace, DIM))
        elif state.last_render:
            row(rgb("idle", DIM), rgb("last render " + state.last_render, MUTE))
        else:
            row(rgb("idle - waiting for the studio to ask for something", DIM))
    else:
        for i, (_, name) in enumerate(PHASES):
            seconds = state.phase_seconds(i)
            if i < state.phase:
                mark, color = rgb("✓", OK), MUTE
            elif i == state.phase:
                mark, color = rgb(spin, ACCENT), TEXT
            else:
                mark, color = rgb("·", DIM), DIM
            clock = fmt_secs(seconds) if seconds is not None else ""
            row(mark + "  " + rgb(name, color), rgb(clock, color))
    L.append(pad + rgb("╰" + "─" * (panel - 2) + "╯", DIM))
    L.append("")

    # -- meters --------------------------------------------------------
    meter = max(16, panel - 32)
    if not state.up and not state.died_at:
        L.append(pad + rgb("boot  ", MUTE) + bar(state.progress(), meter) +
                 rgb(f"  {int(state.progress() * 100):>3}%", TEXT) +
                 rgb(f"  {fmt_secs(state.elapsed)} of ~{fmt_secs(state.expect)}", DIM))
    if state.gpu:
        used, total, util, temp = state.gpu
        share = used / total if total else 0
        # Amber at 85%, red past 96%: on Windows the card never OOMs, it pages,
        # and a full one takes the whole desktop down with it. The colour is the
        # early warning the driver refuses to give.
        color = BAD if share > 0.96 else (WARN if share > 0.85 else ACCENT)
        L.append(pad + rgb("vram  ", MUTE) + bar(share, meter, color) +
                 rgb(f"  {used / 1024:>4.1f}", TEXT) +
                 rgb(f"/{total / 1024:.1f} GB  {util:>3}%  {temp}°C", DIM))
    L.append("")

    # -- what it is saying ---------------------------------------------
    # Kept on screen after a crash too: the box names the error, these are the
    # six lines around it, and that context is usually the actual answer.
    room = height - len(L) - 4
    if room >= 2:
        for level, text in list(state.tail)[-min(room, state.tail.maxlen):]:
            color = BAD if level in ("ERROR", "CRITICAL") else (
                WARN if level == "WARNING" else DIM)
            L.append(pad + rgb("  " + clip(text, inner - 2), color))
        L.append("")

    # -- footer --------------------------------------------------------
    tally = []
    if state.errors:
        tally.append(rgb(f"{state.errors} error" + ("s" if state.errors > 1 else ""), BAD))
    if state.warnings:
        tally.append(rgb(f"{state.warnings} warning" +
                         ("s" if state.warnings > 1 else ""), WARN))
    if not tally:
        tally.append(rgb("no errors", DIM))
    left = rgb("  ", DIM) + rgb(" · ", DIM).join(tally)
    # A death always writes an entry, whether or not anything on the way down
    # looked like an error - so point at the file that now has the answer.
    target = paths["errors"] if (state.errors or state.died_at) else paths["full"]
    right = rgb(clip_left(str(target), max(12, inner - 30)), DIM)
    keys = [("E", "error log"), ("L", "full log"), ("V", "raw output"),
            ("Q", "quit - stops ComfyUI")]
    foot = [pad + left
            + " " * max(1, inner - _plain_len(left) - _plain_len(right) - 1) + right,
            pad + "  " + (rgb("press Q again to stop ComfyUI, any other key to stay", WARN)
                          if confirm_quit else rgb("   ", DIM).join(
                              rgb(k, ACCENT) + rgb(" " + label, DIM)
                              for k, label in keys))]

    # The footer is pinned to the bottom and never sacrificed - where the error
    # log lives is the one thing on screen someone might need at 2am, so a
    # console too short to hold the rest loses the rest.
    body = height - 1 - len(foot)
    L = L[:body] + [""] * max(0, body - len(L))
    # The one guarantee the whole renderer rests on: nothing wraps. A single
    # line one column too wide pushes every line below it down by one and the
    # diffing painter then redraws the entire frame, forever, flickering.
    return [clip_ansi(line, width) for line in L + foot]


def _plain_len(text):
    return len(_ANSI.sub("", text))


def clip_ansi(text, budget):
    """Truncate to `budget` PRINTED columns, counting escapes as free.

    len() would charge 19 characters for a colour that occupies none of them,
    so every coloured line would be cut to a third of its width."""
    if budget <= 0:
        return ""
    out, seen, i = [], 0, 0
    while i < len(text):
        escape = _ANSI.match(text, i)
        if escape:
            out.append(escape.group(0))
            i = escape.end()
            continue
        if seen >= budget:
            return "".join(out) + ("\x1b[0m" if USE_COLOR else "")
        out.append(text[i])
        seen += 1
        i += 1
    return "".join(out)


# -------------------------------------------------------------------- the main

def spawn(launcher, editor):
    """Start the launcher on a pipe, with nothing that can block it.

    stdin is /dev/null on purpose. A crashed .bat parks on "Press any key to
    continue", and with a real console that console stays alive forever holding
    the door shut - the corpse the sidecar has to detect and taskkill. Reading
    EOF instead makes `pause` return immediately, so a crash is reported in the
    second it happens instead of at the end of a six minute grace period.
    """
    env = dict(os.environ)
    # A pipe is not a console, so python picks the ANSI code page for stdout and
    # every emoji a node pack prints becomes a UnicodeEncodeError traceback in
    # the middle of the boot. This costs nothing and deletes that whole genre.
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if not editor:
        # Same trick the sidecar uses: --windows-standalone-build implies
        # auto-launching the graph editor and portable launchers forward no
        # args, so the off switch is the BROWSER variable webbrowser honours.
        env["BROWSER"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                      "System32", "rundll32.exe")
    return subprocess.Popen(
        ["cmd.exe", "/c", str(launcher)], cwd=str(Path(launcher).parent),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, bufsize=0, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def kill(proc):
    if _JOB is not None:
        try:                                    # instant, and gets grandchildren
            ctypes.WinDLL("kernel32").TerminateJobObject(_JOB, 1)
            return
        except (OSError, AttributeError):
            pass
    if proc and proc.poll() is None:
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pixal's ComfyUI console")
    ap.add_argument("--launcher", required=True, help="the ComfyUI .bat to run")
    ap.add_argument("--log-dir", default=str(Path(__file__).absolute().parent / "logs"))
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--expect", type=float, default=0.0,
                    help="seconds the last cold boot took, for the meter")
    ap.add_argument("--editor", action="store_true",
                    help="let ComfyUI pop its graph editor in a browser tab")
    args = ap.parse_args(argv)

    launcher = Path(args.launcher)
    logs = Path(args.log_dir)
    try:
        logs.mkdir(parents=True, exist_ok=True)
    except OSError:
        logs = Path.cwd()
    paths = {"full": logs / "comfy.log", "errors": logs / "comfy-errors.log",
             "oneline": logs / "comfy-last-error.txt",
             "profile": logs / "comfy-boot-profile.json"}

    profile = {}
    try:
        profile = json.loads(paths["profile"].read_text(encoding="utf-8"))["phases"]
    except (OSError, ValueError, KeyError, TypeError):
        pass

    owned = own_the_tree()
    rich = console_setup("Pixal · ComfyUI")
    state = Boot(launcher.name, args.expect, profile)
    errlog = ErrorLog(paths["errors"], paths["oneline"], launcher.name)

    # This boot's transcript replaces the last one's, which is kept: a crash
    # loop otherwise overwrites the evidence with the failure that followed it.
    try:
        if paths["full"].exists():
            paths["full"].replace(logs / "comfy.prev.log")
        # Line buffered, because the whole point of this file is being readable
        # about a boot that has not finished - a hang leaves nothing in a block
        # buffer, and a hang is exactly when someone goes looking.
        full = open(paths["full"], "w", encoding="utf-8", errors="replace",
                    buffering=1)
        full.write(f"# ComfyUI via {launcher}\n"
                   f"# started {datetime.now():%Y-%m-%d %H:%M:%S} by Pixal\n"
                   f"# the number in brackets is seconds since launch\n\n")
    except OSError:
        full = None

    try:
        proc = spawn(launcher, args.editor)
    except OSError as exc:
        # This window is about to close on its own, so the only useful place to
        # say so is the file the sidecar reads.
        errlog.write("starting the launcher", 0.0,
                     [f"could not start {launcher}: {exc}"])
        errlog.close()
        print(f"could not start {launcher.name}: {exc}")
        return 2

    if not owned:
        _install_close_handler(proc)
    records = Queue()
    threading.Thread(target=pump, args=(proc.stdout, records.put),
                     name="pixal-comfy-reader", daemon=True).start()
    telemetry = Telemetry(state, args.url)
    telemetry.start()

    screen = Screen()
    if rich:
        sys.stdout.write("\x1b[?25l\x1b[2J")
    raw_mode = not rich
    confirm = 0.0
    ended = None
    profiled = False

    try:
        while True:
            # Draining first and unconditionally is the one rule here: a full
            # pipe blocks ComfyUI itself, so nothing below may ever come before
            # this, and the cap keeps a 400-line burst from starving the paint.
            for _ in range(4000):
                try:
                    record = records.get_nowait()
                except Empty:
                    break
                if record is None:
                    ended = ended or time.monotonic()
                    _log(full, state, state.flush_bar())
                    continue
                _log(full, state, state.feed(record, errlog))
                if raw_mode:
                    print(record[:2000])

            if state.up and not profiled:
                profiled = True           # ONCE. This loop runs ten times a
                state.record_profile(paths["profile"])   # second, forever.

            code = proc.poll()
            if code is not None and state.died_at is None and (
                    ended or time.monotonic() - state.t0 > 2):
                state.died_at = time.monotonic()
                state.exit_code = code
                _record_death(state, errlog, paths, code)

            key = _read_key()
            if key:
                if confirm and time.monotonic() - confirm < 6:
                    confirm = 0.0
                    if key == "q":
                        break
                elif key == "q":
                    confirm = time.monotonic()
                elif key == "e":
                    open_in_editor(paths["errors"] if paths["errors"].exists()
                                   else paths["full"])
                elif key == "l":
                    open_in_editor(paths["full"])
                elif key == "v" and rich:
                    raw_mode = not raw_mode
                    screen.reset()
                    if raw_mode:
                        print(rgb("  raw output - V returns to the meters\n", DIM))

            # A dead ComfyUI leaves the error on screen long enough to read,
            # then gets out of the way: the sidecar is watching this process and
            # will start a fresh one, and a window that refused to close would
            # stack a second console on every retry. The log is the record.
            if state.died_at and time.monotonic() - state.died_at > 12:
                break

            if rich and not raw_mode:
                size = shutil.get_terminal_size((100, 34))
                try:
                    screen.paint(compose(state, size.columns, size.lines, paths,
                                         bool(confirm and
                                              time.monotonic() - confirm < 6)),
                                 size.columns, size.lines)
                except Exception as exc:                 # never take the drain down
                    # Standing down is right - a full pipe blocks ComfyUI, and
                    # that is a far worse bug than a missing dashboard. But it
                    # scrolls away in seconds, so the reason goes in the file
                    # too: the first time this fired it hid a one-line typo.
                    raw_mode = True
                    screen.reset()
                    errlog.write(state.phase_name(), state.elapsed, [
                        f"the console's meters stood down: {exc!r}",
                        "ComfyUI is unaffected - this is Pixal's own renderer, "
                        "and the raw output continues below"])
                    print(f"(the meters hit a snag and stood down: {exc})")
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        telemetry.stop.set()
        errlog.close()
        if rich:
            sys.stdout.write("\x1b[?25h\x1b[0m\n")
            sys.stdout.flush()
        if full:
            try:
                full.close()
            except OSError:
                pass
        kill(proc)
    return 0


def _record_death(state, errlog, paths, code):
    """A launcher that exits is the end of the story, so write the ending down.

    The last thing it said is usually the reason, and by the time anyone looks
    the window is gone - so this goes in the file even when nothing on the way
    down looked like an error."""
    errlog.flush()                       # whatever it said on the way down
    exit_line = (f"ComfyUI exited with code {code} after "
                 f"{fmt_secs(state.died_at - state.t0)}")
    tail = [text for _, text in list(state.tail)[-6:]]
    errlog.write(state.phase_name(), state.died_at - state.t0,
                 [exit_line] + tail,
                 # Its last words first. An error logged earlier in the boot is
                 # the fallback, not the headline: the bitsandbytes complaint
                 # every ComfyUI here prints would otherwise get blamed for a
                 # crash it had nothing to do with, forty seconds later.
                 headline=_telling(tail) or state.last_error or exit_line)
    state.last_error = errlog.headline


def _log(handle, state, lines):
    """Seconds-since-launch, then the line. The stamp is what makes the
    transcript answer "and then it sat there for ninety seconds doing what"."""
    for line in lines:
        if not handle:
            return
        try:
            handle.write(f"[{state.elapsed:8.2f}] {line}\n")
        except (OSError, ValueError):
            return


# What a .bat says after the thing that killed it. Never the reason.
_CHROME = ("Press any key to continue", "If you see this and ComfyUI did not",
           "The system cannot find the batch label")


def _telling(lines):
    """The last thing it said that was about the failure.

    An error-shaped line wins outright; otherwise the last real line, skipping
    the boilerplate a .bat prints on its way down."""
    real = [t for t in lines if t.strip() and not any(c in t for c in _CHROME)]
    for text in reversed(real):
        if any(m in text for m in _ERROR_MARKS) or re.match(
                r"^[A-Za-z_][\w.]*(Error|Exception)\b", text):
            return text
    return real[-1] if real else ""


def _install_close_handler(proc):
    """Fallback for the machine where the job object would not take: catch the
    window's X and take ComfyUI down by hand. Windows allows about five seconds
    here, so this cannot be the slow taskkill path if the job is available."""
    if not WINDOWS:
        return
    handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

    def handler(_event):
        kill(proc)
        return 0                                    # then let the close proceed

    _install_close_handler.ref = handler_type(handler)   # must outlive the call
    try:
        ctypes.WinDLL("kernel32").SetConsoleCtrlHandler(
            _install_close_handler.ref, True)
    except (OSError, AttributeError):
        pass


def _read_key():
    if not WINDOWS:
        return ""
    try:
        if not msvcrt.kbhit():
            return ""
        ch = msvcrt.getwch()
    except (OSError, ValueError):
        return ""
    if ch in ("\x00", "\xe0"):                      # a function/arrow key's tail
        try:
            msvcrt.getwch()
        except (OSError, ValueError):
            pass
        return ""
    return ch.lower()


if __name__ == "__main__":
    sys.exit(main())
