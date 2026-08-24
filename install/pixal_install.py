"""Pixal installer - the boring parts, in the right order, behind one page.

Not a wizard with a bitmap down the left edge. It serves a single local page on
127.0.0.1, opens it in the default browser, and does the work in a background
thread while the page watches. Same shape as Pixal itself, which is the point:
if this runs, the machine can run Pixal.

Stdlib only, and deliberately so - the interpreter that starts this may be a
freshly unzipped embeddable python with nothing installed in it at all.

What it actually does, in order:
  1. looks the machine over (Windows build, NVIDIA card, free disk, python)
  2. finds ComfyUI, or downloads and unpacks the portable build Pixal is
     developed against
  3. installs Pixal's four python dependencies into whichever interpreter is
     going to run the sidecar
  4. installs the node packs the chosen lanes need
  5. downloads the chosen weights to the exact paths server.py looks for
  6. writes config.json, drops a Desktop shortcut, and hands over a launch
     button

Every download resumes. Re-running after a crash, a closed lid or a dead
wifi costs only the bytes that were actually lost.
"""

import ctypes
import errno
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

PAYLOAD = "pixal-tree.zip"                # the committed tree, baked into the EXE


def _tree():
    """Where the Pixal tree lives, zipped-and-run or frozen.

    Unzipped, this file sits in <pixal>\\install, so the tree is simply the
    parent - the original case, unchanged.

    Frozen there is no tree beside the EXE, which is the whole difficulty with
    shipping one binary: every later step (install_pixal_to, requirements.txt,
    config.example.json) reads out of PIXAL. So the committed tree rides along
    inside the executable as pixal-tree.zip and is unpacked to a staging folder
    under LOCALAPPDATA; from there down, nothing else in this file can tell the
    difference. Staging is deliberately not %TEMP% - temporary_home() warns
    about folders people empty, and this one has to survive the run."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).absolute().parent.parent
    import zipfile
    stage = (Path(os.environ.get("LOCALAPPDATA") or Path.home())
             / "Pixal" / "_setup")
    shutil.rmtree(stage, ignore_errors=True)  # fresh each run; staleness is worse
    stage.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(Path(sys._MEIPASS) / PAYLOAD) as z:
        z.extractall(stage)
    return stage


PIXAL = _tree()                           # the Pixal folder this installer ships
HERE = PIXAL / "install"                  # catalog.json and _work live here
WORK = HERE / "_work"                     # archives, wheels, throwaway tools
CATALOG = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
UA = {"User-Agent": "pixal-installer/1.0"}
PORT = 8795
CREATE_NO_WINDOW = 0x08000000

HF = "https://huggingface.co/{repo}/resolve/main/{path}"
SEVENZR = "https://www.7-zip.org/a/7zr.exe"
GET_PIP = "https://bootstrap.pypa.io/get-pip.py"
LLAMA_RELEASES = "https://api.github.com/repos/JamePeng/llama-cpp-python/releases?per_page=15"

# --------------------------------------------------------------------------- #
# shared state: the worker writes, the page polls
# --------------------------------------------------------------------------- #

LOCK = threading.Lock()
STATE = {"phase": "idle", "steps": [], "log": [], "error": "", "done_note": ""}
CANCEL = threading.Event()

# The page polls /api/state on a timer, so every request that arrives is proof
# someone is still watching. When the proof stops AND bytes are moving, the
# engine pauses the run and leaves - an orphaned engine once kept downloading
# for many minutes after its wizard was killed. See ui_watchdog.
LAST_CLIENT = time.monotonic()
TRANSFERS = 0                    # downloads/unpacks in flight right now
WORKER_THREAD = None
UI_TIMEOUT = 600.0               # ten minutes of silence: generous on purpose
UI_POLL = 15.0                   # how often the watchdog re-checks


class Cancelled(Exception):
    pass


class DiskFull(Exception):
    """The drive ran out of room mid-write. Retrying cannot help - the answer
    is free space, not another attempt - so this skips the retry ladder."""
    pass


def log(line):
    with LOCK:
        STATE["log"].append(line)
        del STATE["log"][:-400]
    print(line, flush=True)
    _logfile(line)


_LOGFH = None


def _logfile(line):
    """Every run leaves a file behind.

    The ring buffer above dies with the window, which is exactly when you need
    it: a friend's install fails on their machine and the evidence is gone. One
    file per run, named by date, and the error note tells them to attach it."""
    global _LOGFH
    try:
        if _LOGFH is None:
            WORK.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%d-%H%M%S")
            _LOGFH = open(WORK / f"install-{stamp}.log", "a",
                          encoding="utf-8", errors="replace")
            _LOGFH.write(f"Pixal installer log - {stamp}\n")
        _LOGFH.write(line + "\n")
        _LOGFH.flush()
    except Exception:
        pass                                     # logging must never be fatal


def steps_add(sid, label, note=""):
    with LOCK:
        STATE["steps"].append({"id": sid, "label": label, "note": note,
                               "status": "wait", "detail": "", "pct": 0})


def step_set(sid, **kw):
    with LOCK:
        for s in STATE["steps"]:
            if s["id"] == sid:
                s.update(kw)
                return


def human(n):
    n = float(n or 0)
    for unit, size in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= size:
            return f"{n / size:.1f} {unit}"
    return f"{int(n)} B"


# --------------------------------------------------------------------------- #
# looking the machine over
# --------------------------------------------------------------------------- #

def run_out(cmd, timeout=25):
    """Run a command, return (rc, text). Never raises, never flashes a window."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW,
                           errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def gpus():
    rc, out = run_out(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                       "--format=csv,noheader,nounits"])
    if rc != 0:
        return []
    found = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[1].isdigit():
            found.append({"name": parts[0], "vram_mb": int(parts[1]),
                          "driver": parts[2] if len(parts) > 2 else ""})
    return found


def free_bytes(path):
    try:
        return shutil.disk_usage(str(path)).free
    except Exception:
        return 0


def disk_preflight(choices, lanes, have):
    """Refuse before the first byte moves when a destination drive cannot hold
    what the plan is about to write.

    An hour of downloading into a disk that fills at 97% is the worst way to
    learn this: the error lands mid-file, it reads as 'Pixal is broken', and
    the bytes already spent buy nothing. The arithmetic is approximate -
    weights at a 10% margin, the portable charged as archive + unpack -
    because the point is a plain-English refusal up front, not accounting."""
    need = {}

    def add(path, nbytes):
        probe = Path(path)
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent           # the chosen folder may not exist yet
        key = (probe.drive or str(probe)).rstrip("\\/").upper()
        prev = need.get(key)
        need[key] = (prev[0] + nbytes, probe) if prev else (nbytes, probe)

    weights = sum(f["bytes"] for f in pending_files(lanes, have))
    if weights:
        add(clean_path(choices["comfy"]["path"]) or "C:/", int(weights * 1.1))
    if choices["comfy"]["mode"] == "install":
        # The archive lands in WORK; the ~8 GB it unpacks to lands on the
        # chosen install drive - two different drives when Pixal was unzipped
        # to Downloads and the portable is headed for D:.
        add(WORK, CATALOG["comfyui"]["asset_bytes"])
        add(clean_path(choices["comfy"]["path"]) or "C:/", 8 * (1 << 30))
    for key, (nbytes, probe) in need.items():
        free = free_bytes(probe)
        if free < nbytes:
            raise RuntimeError(
                f"not enough room on {key} - this plan needs {human(nbytes)} "
                f"there and {human(free)} is free - free up "
                f"{human(nbytes - free)} on {key} (or pick folders on "
                f"another drive) and run the installer again")


SKIP_DIRS = {"windows", "$recycle.bin", "system volume information", "perflogs",
             "node_modules", "appdata", "programdata", ".git", "onedrive"}


class ScanResult(list):
    """The hit list, plus an honest account of how the search went.

    A search that says nothing about where it looked funnels people into the
    fresh-install lane whenever it misses - they cannot tell a miss from "no
    ComfyUI here". So the list carries its own diagnostics, and the page shows
    them under the choices."""
    def __init__(self, hits=(), info=None):
        super().__init__(hits)
        self.info = info or {}


def scan_for_comfy(roots, depth=2, deadline=None, clock=time.monotonic):
    """Any folder whose name mentions comfy, shallow, breadth-first, on a clock.

    A full walk of five fixed drives to find one install is minutes of disk for
    a question the user can answer by typing a path - the first version of this
    was still walking after two minutes. So: a hard deadline and two levels.

    Breadth-first is the part that matters. Depth-first spent the whole budget
    inside C:\\ and never reached X:\\ComfyUI_Pixal3D sitting at the top of
    another drive - a miss that ends with the friend installing a SECOND
    ComfyUI beside the one he already had. Every drive gets its top level
    looked at before any drive gets its second.

    The clock is a parameter so tests can hold time still and force the
    deadline deterministically."""
    t0 = clock()
    hits, seen = [], set()
    searched = []                                # roots whose top level was read
    queue = [(Path(r), 0) for r in roots]
    while queue:
        if CANCEL.is_set() or (deadline and clock() > deadline):
            break
        d, level = queue.pop(0)
        if level == 0:
            searched.append(str(d))
        key = str(d).lower().rstrip("\\/")
        if key in seen:
            continue
        seen.add(key)
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = e.name.lower()
            if name in SKIP_DIRS or name.startswith("."):
                continue
            if "comfy" in name and comfy_dir(Path(e.path)):
                hits.append(Path(e.path))
                continue                         # do not descend into a hit
            if level + 1 <= depth:
                queue.append((Path(e.path), level + 1))
    done = set(searched)
    info = {"searched": searched,
            "unfinished": [str(Path(r)) for r in roots
                           if str(Path(r)) not in done],
            "hits": [str(h) for h in hits],
            "seconds": round(clock() - t0, 1),
            "limit": round(deadline - t0, 1) if deadline else 0,
            # The question the page answers: did the clock run out with work
            # still queued, or did the search genuinely finish?
            "deadline_hit": bool(queue) and bool(deadline) and clock() > deadline}
    return ScanResult(hits, info)


def _scan_line(info):
    """The one engine-log line every probe leaves about the search."""
    roots = [s.rstrip("\\/") for s in info.get("searched", ())]
    scope = " ".join(roots[:8])
    if len(roots) > 8:
        scope += f" +{len(roots) - 8} more"
    hits = info.get("hits") or []
    what = f"hits: {'; '.join(hits)}" if hits else "no hits"
    late = ("deadline hit before "
            + " ".join(s.rstrip("\\/") for s in info.get("unfinished") or ["?"])
            + "; ") if info.get("deadline_hit") else ""
    return f"scan: {late}searched {scope or 'nothing'} in {info.get('seconds', 0)} s - {what}"


def clean_path(raw):
    """Explorer's "Copy as path" hands out a quoted string, and people paste it
    exactly as given. Quotes and trailing slashes off, everywhere a path arrives
    from the page."""
    return str(raw or "").strip().strip('"').rstrip("\\/")


def comfy_dir(root):
    """A user-supplied path -> the ComfyUI folder that owns models/.
    Same three shapes resolve_comfy_dir() in server.py accepts."""
    try:
        p = Path(str(root).strip().strip('"').rstrip("\\/"))
    except Exception:
        return None
    if p.name.lower() == "models" and p.is_dir():
        return p.parent
    for c in (p / "ComfyUI", p):
        if (c / "models").is_dir() and (c / "main.py").is_file():
            return c
    for c in (p / "ComfyUI", p):                 # models/ but no main.py: still usable
        if (c / "models").is_dir():
            return c
    return None


def comfy_version(cdir):
    try:
        raw = (Path(cdir) / "comfyui_version.py").read_text(encoding="utf-8")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', raw)
        return m.group(1) if m else ""
    except Exception:
        return ""


def portable_python(cdir):
    """python_embeded next to a portable ComfyUI, if that is the shape."""
    for cand in (Path(cdir).parent / "python_embeded" / "python.exe",
                 Path(cdir) / ".." / "python_embeded" / "python.exe"):
        if cand.is_file():
            return cand.resolve()
    return None


def install_clash(root):
    """The ComfyUI already living at a would-be fresh-install destination.

    comfy_dir(root) alone is not the whole story: a portable also unpacks to
    root\\ComfyUI_windows_portable, and a root\\ComfyUI\\ComfyUI happens when a
    portable was unzipped one level too far in. Unpacking the fresh portable
    over ANY of these paves a working ComfyUI, so all three count. Returns the
    ComfyUI dir found, or None when the destination is empty, missing, or
    holds only unrelated files - those stay valid places to install into."""
    root = Path(root)
    for cand in (root, root / "ComfyUI_windows_portable", root / "ComfyUI"):
        c = comfy_dir(cand)
        if c:
            return c
    return None


def system_python():
    """A real python (not this embeddable one, if that is what started us)."""
    if sys.version_info >= (3, 10) and (Path(sys.prefix) / "Lib" / "venv").is_dir():
        return Path(sys.executable)
    for cmd in (["py", "-3", "-c", "import sys;print(sys.executable)"],
                ["python", "-c", "import sys;print(sys.executable)"]):
        rc, out = run_out(cmd, timeout=15)
        exe = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ""
        if exe and Path(exe).is_file():
            return Path(exe)
    return None


# Kept when a destination already has them: a re-run is an upgrade, and an
# upgrade that overwrites the chat history, the characters or the access key in
# config.json is a fresh install wearing an upgrade's clothes.
KEEP_FILES = ("config.json", "history.jsonl", "input_ref_types.json",
              "_lora_titles.json", "lane.json", ".pixal_python")
KEEP_DIRS = ("characters", "chats", "logs", "briefs", "recipes", "output")
NEVER_COPY = {"_work", "runtime", ".venv", "__pycache__", ".git", "node_modules"}


def temporary_home(path):
    """Is this folder somewhere people empty? Downloads and %TEMP% are where an
    unzipped folder lands, not where an install should spend its life."""
    low = str(path).lower()
    return any(part in low for part in
               ("\\downloads", "\\temp\\", "\\tmp\\", "\\appdata\\local\\temp",
                "\\onedrive\\", "\\desktop\\"))


def suggest_home(comfy_root):
    """Where Pixal should live, if the person does not care to choose.

    Inside the ComfyUI portable at ComfyUI\\pixal_dm - the layout run.bat
    already knows by heart, and one tree to back up or move. Only when Pixal is
    somewhere temporary, though: a folder that is already settled is left where
    its owner put it."""
    if not temporary_home(PIXAL):
        return str(PIXAL)
    cdir = comfy_dir(comfy_root) if comfy_root else None
    if cdir:
        return str(Path(cdir) / "pixal_dm")
    return r"C:\Pixal"


def install_pixal_to(dest, sid):
    """Copy the unzipped folder to where Pixal will actually live.

    Copy, not move: this installer is running out of the source folder - on
    Windows a python.exe unpacked into install\\runtime cannot move itself out
    from under its own feet. ~5 MB either way, and leaving the original behind
    costs nothing but a line in the summary telling them it can go."""
    src = Path(PIXAL)
    dest = Path(str(dest).strip().strip('"').rstrip("\\/"))
    try:
        if dest.exists() and src.samefile(dest):
            step_set(sid, status="ok", detail="already there")
            return src, False
    except OSError:
        pass
    if str(dest).lower().startswith(str(src).lower() + os.sep):
        raise RuntimeError(f"{dest} is inside the folder being copied - "
                           "pick somewhere outside it")

    copied = kept = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in NEVER_COPY]
        rel = Path(root).relative_to(src)
        (dest / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            target = dest / rel / name
            protected = name in KEEP_FILES or (rel.parts and rel.parts[0] in KEEP_DIRS)
            if target.exists() and protected:
                kept += 1
                continue
            shutil.copy2(Path(root) / name, target)
            copied += 1
    log(f"Pixal -> {dest} ({copied} files"
        + (f", {kept} left as they were" if kept else "") + ")")
    step_set(sid, status="ok", detail=str(dest))
    return dest, True


def tidy(cdir, moves, sid):
    """Move misfiled models into the folders server.py's constants name.

    Rules, because this is somebody's existing ComfyUI and not a scratch dir:
      - only files the catalogue recognises, never a sweep of the folder
      - only within the same category (diffusion_models/unet count as one)
      - only within the same volume, where a move is a rename and cannot
        half-finish; anything across drives is reported and left alone
      - never over the top of an existing file
      - every move is written to a JSON trail beside the installer, so putting
        it all back is a readable list and not an act of memory
    """
    models = Path(cdir) / "models"
    done, skipped = [], []
    for mv in moves:
        src = models / mv["from"].replace("/", os.sep)
        dst = models / mv["to"].replace("/", os.sep)
        if not src.is_file():
            continue
        if dst.exists():
            skipped.append((mv["from"], "something is already at the destination"))
            continue
        if src.drive.lower() != dst.drive.lower():
            skipped.append((mv["from"], f"lives on {src.drive} - not moved across drives"))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(src, dst)
        except OSError as exc:
            skipped.append((mv["from"], str(exc)))
            continue
        done.append({"from": str(src), "to": str(dst)})
        log(f"  moved {mv['from']} -> {mv['to']}")
        step_set(sid, status="run", detail=f"{len(done)} moved")

    if done:
        trail = WORK / f"tidy-{int(time.time())}.json"
        trail.parent.mkdir(parents=True, exist_ok=True)
        trail.write_text(json.dumps(done, indent=1), encoding="utf-8")
        log(f"  undo list: {trail}")
    for name, why in skipped:
        log(f"  left alone: {name} - {why}")
    step_set(sid, status="ok" if done else "skip",
             detail=f"{len(done)} moved" + (f", {len(skipped)} left alone" if skipped else "")
                    if done or skipped else "nothing was misfiled")
    return done, skipped


def choose_python(cdir):
    """The interpreter that will run the sidecar, and how we got it.

    A .venv of its own is the right answer whenever the machine has a real
    python: Pixal's four pinned dependencies then cannot touch the numpy and
    Pillow that ComfyUI's torch is standing on. An embeddable python cannot
    create a venv and a portable ComfyUI does not ship one, so the fallback is
    to share ComfyUI's interpreter - carefully (see missing_deps)."""
    venv = PIXAL / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return venv, "venv"
    sys_py = system_python()
    if sys_py:
        rc, out = run_out([str(sys_py), "-m", "venv", str(PIXAL / ".venv")],
                          timeout=600)
        if venv.is_file():
            return venv, "venv"
        log(f"  could not create a .venv ({out.strip()[-200:]})")
    port = portable_python(cdir)
    if port:
        return port, "portable"
    if sys_py:
        return sys_py, "system"
    raise RuntimeError("no python to run Pixal on. Install Python 3.12 from "
                       "python.org and run this installer again.")


DEPS = (("aiohttp", "aiohttp"), ("numpy", "numpy"),
        ("PIL", "Pillow"), ("yaml", "PyYAML"))


def missing_deps(py):
    out = []
    for module, package in DEPS:
        rc, _ = run_out([str(py), "-c", f"import {module}"], timeout=90)
        if rc != 0:
            out.append(package)
    return out


DRIVER_MIN = 580          # torch cu130 (what the pinned portable ships) needs R580+


def driver_major(cards):
    for c in cards:
        m = re.match(r"\s*(\d+)", c.get("driver") or "")
        if m:
            return int(m.group(1))
    return 0


def gate(cards):
    """What the machine may do, decided once and read by both doors.

    Two hard stops, because both of them otherwise fail LATE - after a
    multi-gigabyte download - and in a way a first-time user reads as "Pixal is
    broken" rather than "this machine needs one thing first".

    Note nvidia-smi failing means no DRIVER responded; it does not prove there
    is no card. The copy has to say that, or we gaslight someone with a fresh
    Windows install and a perfectly good 4070."""
    if not cards:
        return {"gpu": False, "driver": True, "driver_major": 0,
                "driver_min": DRIVER_MIN,
                "why": "No NVIDIA driver responded. Pixal renders on NVIDIA "
                       "GPUs - if you have one, install its driver from "
                       "nvidia.com and run this again."}
    major = driver_major(cards)
    if major and major < DRIVER_MIN:
        return {"gpu": True, "driver": False, "driver_major": major,
                "driver_min": DRIVER_MIN,
                "why": f"Your NVIDIA driver is {major}.x. The ComfyUI Pixal "
                       f"installs needs {DRIVER_MIN} or newer (it ships CUDA 13 "
                       f"builds). Update at nvidia.com/drivers, then run this "
                       f"again."}
    return {"gpu": True, "driver": True, "driver_major": major,
            "driver_min": DRIVER_MIN, "why": ""}


def probe():
    """Everything the first screen shows. Cheap enough to run on page load."""
    known = []
    cfg = read_config()
    for cand in (cfg.get("comfy_root"), PIXAL.parent.parent, PIXAL.parent):
        if cand and comfy_dir(cand):
            known.append(str(Path(cand)))
    roots = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        d = Path(f"{letter}:\\")
        if d.exists():
            roots.append(d)
    home = Path.home()
    roots += [home, home / "Desktop", home / "Documents", home / "Downloads",
              Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs"))]
    roots = [r for r in roots if r.exists()]
    found = scan_for_comfy(roots, deadline=time.monotonic() + 8.0)
    known += [str(h) for h in found]
    scan_info = dict(found.info)
    log(_scan_line(scan_info))

    installs, seen = [], set()
    for raw in known:
        c = comfy_dir(raw)
        if not c or str(c).lower() in seen:
            continue
        seen.add(str(c).lower())
        # Pixal wants the portable ROOT (the folder with run_nvidia_gpu.bat),
        # because that launcher is how it starts ComfyUI for you.
        root = c.parent if (c.parent / "python_embeded").is_dir() else c
        installs.append({"root": str(root), "comfy": str(c),
                         "version": comfy_version(c),
                         "python": str(portable_python(c) or ""),
                         "packs": sorted(p.name for p in
                                         (c / "custom_nodes").glob("*")
                                         if p.is_dir() and not
                                         p.name.startswith("__"))[:40]})

    cards = gpus()
    return {
        "windows": f"{sys.getwindowsversion().major}.{sys.getwindowsversion().build}"
                   if os.name == "nt" else "not windows",
        "is_windows": os.name == "nt",
        "gate": gate(cards),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}."
                  f"{sys.version_info.micro}",
        "system_python": str(system_python() or ""),
        "gpus": cards,
        "vram_gb": round(max([c["vram_mb"] for c in cards], default=0) / 1024, 1),
        "installs": installs,
        # What the search above actually did - the page shows this under the
        # choices so a miss never silently reads as "you have no ComfyUI".
        "scan": scan_info,
        "pixal": str(PIXAL),
        # True when Pixal is running from somewhere people empty out - the
        # unzipped-into-Downloads case the page needs to talk them out of.
        "pixal_temporary": temporary_home(PIXAL),
        "free": {str(d): free_bytes(d) for d in
                 (Path(f"{c}:\\") for c in "CDEFGHIJKLMNOPQRSTUVWXYZ")
                 if d.exists()},
        "target_drive": (installs[0]["comfy"][:3] if installs
                         else str(PIXAL.drive + "\\")),
        "catalog": CATALOG,
        "pin": CATALOG["comfyui"]["pin"],
    }


MODEL_EXT = {".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".sft", ".bin"}
# ComfyUI reads both, and its catalog reports either as a diffusion model, so a
# file in one is not misplaced merely for not being in the other.
SAME_CATEGORY = {"diffusion_models": "diffusion_models", "unet": "diffusion_models"}


def inventory(cdir, extra_roots=()):
    """Every model file under a ComfyUI, as (lowercased forward-slash rel) ->
    absolute path. One walk, reused by every question below."""
    found = {}
    roots = [Path(cdir) / "models"] + [Path(r) for r in extra_roots]
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in files:
                if Path(name).suffix.lower() not in MODEL_EXT:
                    continue
                full = Path(dirpath) / name
                rel = full.relative_to(root).as_posix().lower()
                found.setdefault(rel, full)
    return found


def extra_model_roots(cdir):
    """ComfyUI's extra_model_paths.yaml, read with a regex rather than a YAML
    parser - this installer has no third-party imports by design, and all we
    need is the base_path lines. An older install very often keeps its models
    on another drive through exactly this file."""
    roots = []
    cfg = Path(cdir) / "extra_model_paths.yaml"
    if not cfg.is_file():
        return roots
    try:
        for m in re.finditer(r"^\s*base_path:\s*(.+?)\s*$",
                             cfg.read_text(encoding="utf-8", errors="replace"),
                             re.M):
            p = Path(m.group(1).strip().strip('"').strip("'"))
            if p.is_dir():
                roots.append(p)
    except Exception:
        pass
    return roots


def _satisfied(rule, files):
    """Is this catalogue entry already installed somewhere Pixal will look?"""
    for want in (rule or {}).get("paths", ()):
        if want.lower() in files:
            return files[want.lower()], want.lower()
    pattern = (rule or {}).get("any_path")
    if pattern:
        rx = re.compile(pattern, re.I)
        for rel, full in files.items():
            if rx.match(rel):
                return full, rel
    return None, ""


def _strays(entry, files):
    """The same model sitting where Pixal will NOT look. Only ever moved within
    its own category: a checkpoint that happens to share a name with a
    diffusion model is somebody else's file, not a misfiled one."""
    pattern = entry.get("stray")
    if not pattern:
        pattern = "^" + re.escape(Path(entry["dest"]).name) + "$"
    rx = re.compile(pattern, re.I)
    want_cat = entry["dest"].split("/")[0].lower()
    out = []
    for rel, full in files.items():
        parts = rel.split("/")
        if len(parts) < 2:
            continue                    # loose in models\ root; ComfyUI ignores it too
        cat = parts[0]
        if SAME_CATEGORY.get(cat, cat) != SAME_CATEGORY.get(want_cat, want_cat):
            continue
        if rx.match(parts[-1]):
            out.append((rel, full))
    return out


def survey(cdir):
    """What this ComfyUI already has, per lane, and what is merely misfiled.

    Three states per file, and they are not the same question:
      have    - installed where server.py's constants actually look
      stray   - the file is here, in a folder Pixal does not read
      missing - not on this machine
    """
    out = {"lanes": {}, "moves": [], "manual": [], "scanned": 0}
    if not cdir:
        return out
    files = inventory(cdir, extra_model_roots(cdir))
    out["scanned"] = len(files)

    for lane in CATALOG["lanes"]:
        rows, moves = [], []
        for f in lane["files"]:
            full, at = _satisfied(f.get("satisfied_by"), files)
            row = {"dest": f["dest"], "name": Path(f["dest"]).name,
                   "bytes": f["bytes"], "repo": f["repo"],
                   "page": f"https://huggingface.co/{f['repo']}"}
            if full:
                # `at` is lowercased for comparison; `full` keeps the real case,
                # which is what goes into config.json.
                row.update(state="have", at=at, full=str(full),
                           exact=at == f["dest"].lower())
            else:
                stray = _strays(f, files)
                if stray:
                    row.update(state="stray", at=stray[0][0])
                    moves.append({"from": stray[0][0], "to": f["dest"],
                                  "name": Path(stray[0][0]).name})
                else:
                    row.update(state="missing", at="")
            rows.append(row)
        out["lanes"][lane["id"]] = {
            "files": rows,
            "have": sum(1 for r in rows if r["state"] == "have"),
            "stray": sum(1 for r in rows if r["state"] == "stray"),
            "of": len(rows),
            "missing_bytes": sum(r["bytes"] for r in rows if r["state"] == "missing"),
            # What it costs to skip the tidy: a misfiled file has to be
            # downloaded again, because server.py will not read the copy that
            # is already sitting there.
            "stray_bytes": sum(r["bytes"] for r in rows if r["state"] == "stray"),
        }
        out["moves"] += moves

    for group in CATALOG.get("manual", []):
        for f in group["files"]:
            full, at = _satisfied({"paths": [f["dest"].lower()]}, files)
            row = {"dest": f["dest"], "name": Path(f["dest"]).name,
                   "search": "https://civitai.com/search/models?query="
                             + f.get("search", Path(f["dest"]).stem).replace(" ", "+")}
            if full:
                row["state"] = "have"
            else:
                stray = _strays(f, files)
                if stray:
                    row.update(state="stray", at=stray[0][0])
                    out["moves"].append({"from": stray[0][0], "to": f["dest"],
                                         "name": Path(stray[0][0]).name})
                else:
                    row["state"] = "missing"
            out["manual"].append(row)
    return out


# --------------------------------------------------------------------------- #
# config.json
# --------------------------------------------------------------------------- #

def read_config():
    try:
        return json.loads((PIXAL / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_config(patch):
    """Merge, never overwrite: on a machine that already had Pixal this must not
    wipe an API key or an access key."""
    cfg = read_config()
    if not cfg:
        try:
            cfg = json.loads((PIXAL / "config.example.json")
                             .read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    for k, v in patch.items():
        if isinstance(v, dict):
            cfg[k] = {**(cfg.get(k) or {}), **v}
        else:
            cfg[k] = v
    (PIXAL / "config.json").write_text(json.dumps(cfg, indent=2) + "\n",
                                       encoding="utf-8")
    return cfg


# --------------------------------------------------------------------------- #
# downloading
# --------------------------------------------------------------------------- #

def download(url, dest, expect=0, sid=None, label=""):
    """Resumable GET. The .part file is the resume point; a finished file of the
    right size is left alone, which is what makes re-running this cheap."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and expect and dest.stat().st_size >= expect * 0.999:
        step_set(sid, status="ok", pct=100, detail="already downloaded")
        log(f"  have {dest.name}")
        return dest

    part = dest.with_name(dest.name + ".part")
    last_err = None
    with _transfer():                        # the watchdog may pause orphans
        for attempt in range(6):
            if CANCEL.is_set():
                raise Cancelled()
            have = part.stat().st_size if part.is_file() else 0
            try:
                _stream(url, part, have, expect, sid, label)
                part.replace(dest)
                step_set(sid, status="ok", pct=100,
                         detail=human(dest.stat().st_size))
                return dest
            except Cancelled:
                raise
            except Exception as exc:
                if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                    raise DiskFull(
                        f"disk full on {dest.drive or dest} - free up space and "
                        f"run the installer again") from exc
                last_err = exc
                log(f"  {dest.name}: {type(exc).__name__}: {exc} "
                    f"- retry {attempt + 1}/5")
                step_set(sid, detail=f"reconnecting ({attempt + 1}/5)")
                for _ in range(4 * (attempt + 1)):
                    if CANCEL.is_set():
                        raise Cancelled()
                    time.sleep(1)
    raise RuntimeError(f"{dest.name}: gave up after 6 tries ({last_err})")


def _stream(url, part, have, expect, sid, label):
    headers = dict(UA)
    if have:
        headers["Range"] = f"bytes={have}-"
    with urlopen(Request(url, headers=headers), timeout=60) as r:
        mode = "ab"
        if have and r.status != 206:            # server ignored the range
            have, mode = 0, "wb"
        total = int(r.headers.get("Content-Length") or 0)
        total = total + have if r.status == 206 else total
        total = total or expect
        got, t0, started, tick = have, time.time(), have, 0.0
        with open(part, mode) as f:
            while True:
                if CANCEL.is_set():
                    raise Cancelled()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                now = time.time()
                if now - tick > 0.3:
                    tick = now
                    rate = (got - started) / max(now - t0, 0.001)
                    step_set(sid, status="run",
                             pct=round(100 * got / total, 1) if total else 0,
                             detail=f"{human(got)} of {human(total)} · "
                                    f"{human(rate)}/s")
        if total and got < total * 0.999:
            raise IOError(f"short read: {got} of {total}")


# --------------------------------------------------------------------------- #
# unpacking the ComfyUI portable
# --------------------------------------------------------------------------- #

def seven_zip():
    """7z.exe if the machine has one, otherwise 7-Zip's own 600KB standalone
    extractor. Windows' bundled tar can sometimes read .7z and sometimes cannot,
    and 'sometimes' is not a thing to hand a friend at 9pm."""
    for cand in (shutil.which("7z"), shutil.which("7za"),
                 r"C:\Program Files\7-Zip\7z.exe",
                 r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if cand and Path(cand).is_file():
            return str(cand)
    local = WORK / "7zr.exe"
    if not local.is_file():
        log("  fetching 7zr.exe (600 KB) to unpack the portable")
        download(SEVENZR, local, 602112, sid=None, label="7zr")
    return str(local)


def flatten_portable(root):
    """The archive carries its own ComfyUI_windows_portable\\ folder inside it.
    The user already said where ComfyUI goes, so lift its contents up one level
    rather than handing them C:\\ComfyUI\\ComfyUI_windows_portable\\ComfyUI.
    Same volume, so every move is a rename - not 9 GB of copying."""
    inner = Path(root) / "ComfyUI_windows_portable"
    if inner.is_dir():
        for child in list(inner.iterdir()):
            dst = Path(root) / child.name
            if not dst.exists():
                shutil.move(str(child), str(dst))
        if not any(inner.iterdir()):
            inner.rmdir()
    return Path(root) if (Path(root) / "ComfyUI").is_dir() else inner


def extract_7z(archive, dest, sid):
    exe = seven_zip()
    dest.mkdir(parents=True, exist_ok=True)
    with _transfer():                        # unpacking counts as bytes moving
        proc = subprocess.Popen([exe, "x", "-y", "-bsp1", f"-o{dest}",
                                 str(archive)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace",
                                creationflags=CREATE_NO_WINDOW)
        pat = re.compile(r"(\d{1,3})%")
        for line in proc.stdout:
            if CANCEL.is_set():
                proc.kill()
                raise Cancelled()
            m = pat.search(line)
            if m:
                step_set(sid, status="run", pct=int(m.group(1)),
                         detail=f"unpacking · {m.group(1)}%")
        if proc.wait() != 0:
            raise RuntimeError(f"7-Zip failed on {archive.name}")


# --------------------------------------------------------------------------- #
# pip, node packs, the local brain
# --------------------------------------------------------------------------- #

def pip(py, args, sid, what):
    """pip inside another interpreter, streamed to the log."""
    cmd = [str(py), "-m", "pip", "install", "--no-warn-script-location", *args]
    log(f"  pip: {' '.join(args)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace",
                            creationflags=CREATE_NO_WINDOW)
    tail = []
    for line in proc.stdout:
        line = line.rstrip()
        tail.append(line)
        del tail[:-3]
        if line:
            step_set(sid, status="run", detail=line[-90:])
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"{what} failed:\n" + "\n".join(tail))


def ensure_pip(py, sid):
    rc, _ = run_out([str(py), "-m", "pip", "--version"], timeout=60)
    if rc == 0:
        return
    log("  that interpreter has no pip - bootstrapping it")
    script = WORK / "get-pip.py"
    download(GET_PIP, script, 0, sid=sid, label="get-pip")
    rc, out = run_out([str(py), str(script), "--no-warn-script-location"],
                      timeout=600)
    if rc != 0:
        raise RuntimeError("could not install pip into " + str(py) + "\n" + out[-800:])


def install_pack(name, cdir, py, sid):
    """Node packs by zipball, because a fresh Windows laptop has no git."""
    spec = CATALOG["packs"][name]
    target = Path(cdir) / "custom_nodes" / name
    if target.is_dir():
        step_set(sid, status="ok", detail="already installed")
        return
    zip_url = (f"https://codeload.github.com/{spec['repo']}/zip/refs/heads/"
               f"{spec['branch']}")
    blob = WORK / f"{name}.zip"
    download(zip_url, blob, 0, sid=sid, label=name)
    step_set(sid, status="run", detail="unpacking")
    import zipfile
    tmp = WORK / f"{name}_x"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(blob) as z:
        z.extractall(tmp)
    inner = next(p for p in tmp.iterdir() if p.is_dir())
    shutil.move(str(inner), str(target))
    shutil.rmtree(tmp, ignore_errors=True)
    req = target / "requirements.txt"
    if req.is_file():
        step_set(sid, status="run", detail="installing its requirements")
        pip(py, ["-r", str(req)], sid, f"{name} requirements")
    step_set(sid, status="ok", detail="installed")


def llama_wheel_url(py):
    """A prebuilt CUDA wheel for llama-cpp-python matching this interpreter.

    PyPI ships source only on Windows and abetlen's index stopped at 0.2.66, so
    a `pip install llama-cpp-python` here means a two-hour CMake build that ends
    in a compiler error. JamePeng publishes the Windows CUDA builds Pixal's own
    local brain runs on; match the python tag, then the CUDA the installed torch
    was built for."""
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    rc, out = run_out([str(py), "-c",
                       "import sys;print('cp%d%d' % sys.version_info[:2]);"
                       "import torch;print(torch.version.cuda or '')"], timeout=120)
    cuda = ""
    if rc == 0:
        lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
        if lines:
            tag = lines[0]
        if len(lines) > 1:
            cuda = "cu" + lines[1].replace(".", "")
    try:
        rels = json.load(urlopen(Request(LLAMA_RELEASES, headers=UA), timeout=30))
    except Exception as exc:
        log(f"  could not read the wheel index: {exc}")
        return None, tag
    wheels = [a["browser_download_url"] for r in rels for a in r.get("assets", [])
              if a["name"].endswith(".whl") and f"{tag}-{tag}-win_amd64" in a["name"]]
    for want in ([cuda] if cuda else []) + ["cu130", "cu129", "cu128", "cu126", "cu124"]:
        for w in wheels:
            if want and want in w:
                return w, tag
    return (wheels[0] if wheels else None), tag


# --------------------------------------------------------------------------- #
# the shortcut
# --------------------------------------------------------------------------- #

def _shortcut_vbs():
    """The VBScript that writes Pixal.lnk.

    The Desktop path is resolved by the script itself, not by Python:
    OneDrive's Known-Folder-Move (the consumer Win11 default) redirects the
    real Desktop, and %USERPROFILE%\\Desktop is then a leftover folder nobody
    sees. SpecialFolders follows the redirect.

    Targets Pixal.exe, not pixal.vbs. Windows will not PIN a shortcut whose
    target is a script: the .lnk opens Pixal fine from the Desktop, and
    dragging it to the taskbar silently does nothing (Jesse, 2026-08-24:
    "it makes a desktop icon but I can't drag it to my task bar").
    Pixal.exe exists for exactly this reason - see pixal_launch.py, which
    is about owning the window identity - and with no arguments it hands
    straight to pixal.vbs, so the boot discipline is untouched. This runs
    AFTER Inno's own [Icons] entry, which already pointed at the exe, so
    the setup engine had been replacing a pinnable shortcut with an
    unpinnable one."""
    # New art gets a new filename: Windows caches shortcut icons by path, so
    # repainting pixal.ico in place leaves the old picture on the Desktop.
    icon = next((p for p in (PIXAL / "web" / "icons" / "pixal-block.ico",
                             PIXAL / "web" / "icons" / "pixal-p.ico",
                             PIXAL / "web" / "icons" / "pixal.ico") if p.is_file()), None)
    # The .vbs is the fallback for a from-source tree that never built the
    # launcher - unpinnable, but it still opens Pixal, which beats no icon.
    target = PIXAL / "Pixal.exe"
    if not target.is_file():
        target = PIXAL / "pixal.vbs"
    return (
        'Set s = CreateObject("WScript.Shell")\n'
        'desk = s.SpecialFolders("Desktop")\n'
        'If desk = "" Then WScript.Quit 1\n'
        'Set l = s.CreateShortcut(desk & "\\Pixal.lnk")\n'
        f'l.TargetPath = "{target}"\n'
        f'l.WorkingDirectory = "{PIXAL}"\n'
        + (f'l.IconLocation = "{icon}"\n' if icon else "") +
        'l.Description = "Pixal"\n'
        'l.Save\n'
        'WScript.Echo desk & "\\Pixal.lnk"\n')


# The AppUserModelID every Pixal shortcut must carry. pixal.vbs opens the
# studio as `chrome --app=http://127.0.0.1:8190`, and Chrome stamps that
# window with the AUMID "Chrome.127.0.0.1_/" (host + "_" + path, no port).
# The taskbar folds a running window into a pinned shortcut only when the
# two ids match - this string is the whole contract, and it is machine-
# independent by construction. It is deliberately NOT "Chrome._crx_<id>":
# that is an installed PWA's window identity, and a shortcut pinned to it
# matches nothing on a machine without the PWA - i.e. every fresh install
# (the two-button bug Jesse hit four times on 2026-08-24).
SHORTCUT_AUMID = "Chrome.127.0.0.1_/"
# Kept in sync with pixal.iss's [Icons] AppUserModelID - Inno stamps its own
# shortcuts, this stamps the desktop shortcut the engine writes over them.


def _stamp_ps1():
    """The PowerShell that writes SHORTCUT_AUMID into a .lnk's property store.

    WScript.Shell can create a shortcut but cannot reach
    System.AppUserModel.ID - that lives in the link's IPropertyStore, which
    only COM sees. Same shape as mklink.vbs: a generated script run once,
    from WORK, with the path passed in so no quoting is ever interpolated.
    """
    return r'''
param([Parameter(Mandatory=$true)][string]$LnkPath, [Parameter(Mandatory=$true)][string]$Aumid)
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class LnkStamp {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046"), ClassInterface(ClassInterfaceType.None)]
    public class CShellLink {}
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPropertyStore {
        int GetCount(out uint c);
        int GetAt(uint i, out PROPERTYKEY k);
        int GetValue(ref PROPERTYKEY k, out PROPVARIANT v);
        int SetValue(ref PROPERTYKEY k, ref PROPVARIANT v);
        int Commit();
    }
    [StructLayout(LayoutKind.Sequential, Pack=4)]
    public struct PROPERTYKEY { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Sequential, Size=24)]
    public struct PROPVARIANT {
        public ushort vt;
        public ushort w1; public ushort w2; public ushort w3;
        public IntPtr p;
        public IntPtr p2;
    }
    [ComImport, Guid("0000010B-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPersistFile {
        int GetClassID(out Guid g);
        int IsDirty();
        int Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint m);
        int Save([MarshalAs(UnmanagedType.LPWStr)] string f, bool remember);
        int SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f);
        int GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f);
    }
    [DllImport("ole32.dll")] public static extern void CoTaskMemFree(IntPtr p);
    public static int Stamp(string path, string aumid) {
        var pf = (IPersistFile)new CShellLink();
        int hr = pf.Load(path, 2);   // STGM_READWRITE: the Save below rewrites the file
        if (hr != 0) return hr;
        var ps = (IPropertyStore)pf;
        var k = new PROPERTYKEY { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
        var v = new PROPVARIANT();
        v.vt = 31;
        v.p = Marshal.StringToCoTaskMemUni(aumid);
        try {
            hr = ps.SetValue(ref k, ref v);
            if (hr != 0) return hr;
            hr = ps.Commit();
            if (hr != 0) return hr;
        } finally {
            CoTaskMemFree(v.p);
        }
        return pf.Save(path, true);
    }
}
"@
$hr = [LnkStamp]::Stamp($LnkPath, $Aumid)
if ($hr -ne 0) { Write-Error "stamp hr=$hr"; exit 1 }
'''


def _stamp_shortcut_aumid(lnk):
    """Pin the shortcut and the future window to the same AppUserModelID.

    Best effort: a shortcut without the stamp still opens Pixal, it just
    cannot fold into its pinned taskbar button - so a failure is logged,
    never fatal."""
    ps1 = WORK / "stamp-aumid.ps1"
    ps1.write_text(_stamp_ps1(), encoding="utf-16")
    rc, out = run_out(["powershell", "-NoProfile", "-ExecutionPolicy",
                       "Bypass", "-File", str(ps1),
                       "-LnkPath", lnk, "-Aumid", SHORTCUT_AUMID],
                      timeout=60)
    if rc != 0:
        print(f"WARNING: AppUserModelID stamp failed for {lnk}: {out}")


def desktop_shortcut():
    vbs = WORK / "mklink.vbs"
    # UTF-16, BOM and all: WScript parses BOM-less UTF-8 as ANSI, so an
    # install path with non-ASCII characters (Müller, 翔太) mojibakes into a
    # shortcut that points nowhere.
    vbs.write_text(_shortcut_vbs(), encoding="utf-16")
    # cscript, not wscript: under wscript.exe WScript.Echo is a message box,
    # and the run would hang on a dialog nobody can see. The script's last
    # line echoes the .lnk it wrote, which is how the caller learns where the
    # Desktop actually is.
    rc, out = run_out(["cscript", "//nologo", str(vbs)], timeout=30)
    if rc != 0:
        return ""
    line = next((ln.strip() for ln in reversed(out.splitlines()) if ln.strip()),
                "")
    # A path the console codepage cannot represent comes back mangled ('?' or
    # control characters); say where the shortcut is rather than show mojibake.
    if (line.lower().endswith(".lnk") and "?" not in line
            and "\ufffd" not in line
            and not any(ord(c) < 32 for c in line)):
        _stamp_shortcut_aumid(line)
        return line
    return "Desktop"


# --------------------------------------------------------------------------- #
# the worker
# --------------------------------------------------------------------------- #

def already_here(choices):
    """Which catalogued files this machine can already use, so the plan does not
    offer to download 12 GB of something that is sitting right there.

    A misfiled file counts only when the tidy step is going to run - until it
    moves, server.py genuinely cannot see it, and pretending otherwise ships an
    install that says 'done' and then cannot render."""
    if choices["comfy"]["mode"] == "install":
        return set(), None                       # a fresh ComfyUI has nothing
    cdir = comfy_dir(clean_path(choices["comfy"]["path"]))
    if not cdir:
        return set(), None
    found = survey(cdir)
    keep = {"have", "stray"} if choices.get("tidy") else {"have"}
    have = {row["dest"] for info in found["lanes"].values()
            for row in info["files"] if row["state"] in keep}
    return have, found


def build_plan(choices):
    """The whole plan up front, so the page can show what it is in for before
    the first byte moves."""
    with LOCK:
        STATE["steps"] = []
    lanes = [l for l in CATALOG["lanes"] if l["id"] in choices["lanes"]]
    have, found = already_here(choices)

    if choices["comfy"]["mode"] == "install":
        steps_add("comfy_get", "Download ComfyUI portable",
                  human(CATALOG["comfyui"]["asset_bytes"]))
        steps_add("comfy_x", "Unpack ComfyUI")
    elif choices["comfy"].get("update"):
        steps_add("comfy_up", "Update ComfyUI", CATALOG["comfyui"]["pin"])

    if choices.get("tidy"):
        steps_add("tidy", "Tidy the model folders", "move misfiled models into place")
    steps_add("home", "Put Pixal where it will live", choices.get("home") or "")
    steps_add("deps", "Install Pixal's python dependencies")

    packs = []
    for lane in lanes:
        for p in lane["packs"]:
            if p not in packs:
                packs.append(p)
    # Manual-group packs too. The Krea 2 files sit behind a Civitai login so we
    # can only point at them - but every recipe that uses them queues
    # ClownsharKSampler_Beta, so without RES4LYF the friend who dutifully
    # hand-downloads the models still cannot render realism, realism_ii,
    # face_mint or identity_edit. It is 9 MB and needs no login; there is no
    # reason to make that a second manual step.
    for group in CATALOG.get("manual", []):
        for p in group.get("packs", []):
            if p not in packs and p in CATALOG["packs"]:
                packs.append(p)
    for p in packs:
        steps_add("pack:" + p, f"Node pack · {p}", CATALOG["packs"][p]["why"])

    seen = set()
    for lane in lanes:
        for f in lane["files"]:
            if f["dest"] in seen or f["dest"] in have:
                continue
            seen.add(f["dest"])
            steps_add("dl:" + f["dest"], Path(f["dest"]).name, human(f["bytes"]))
    if not seen and lanes:
        steps_add("nodl", "Weights", "already on this machine - nothing to download")

    if any(l.get("brain") for l in lanes):
        steps_add("llama", "Install the local brain runtime", "llama-cpp-python")

    steps_add("config", "Write config.json")
    steps_add("shortcut", "Desktop shortcut")
    return lanes, packs, have, found


def pending_files(lanes, have):
    """The weights rows this machine still needs, in plan order, de-duplicated
    across lanes - the same set build_plan writes steps for."""
    seen = set()
    for lane in lanes:
        for f in lane["files"]:
            if f["dest"] in seen or f["dest"] in have:
                continue
            seen.add(f["dest"])
            yield f


def fetch_weights(lanes, have, models):
    """Download every missing row; a row that fails is marked and logged, and
    the rest still get their turn.

    Weights are the one stage where no later row depends on an earlier one, so
    a 429 at hour two must not abort the run the way a failed ComfyUI portable
    or node pack must. The row is marked fail with the reason, the run goes
    on, and the end of the run says how many never landed - re-running resumes
    at exactly those files. DiskFull and Cancelled still stop everything:
    continuing cannot help either."""
    models = Path(models)
    planned = list(pending_files(lanes, have))
    failed = []
    for f in planned:
        sid = "dl:" + f["dest"]
        step_set(sid, status="run")
        try:
            download(HF.format(repo=f["repo"], path=f["path"]),
                     models / f["dest"].replace("/", os.sep),
                     f["bytes"], sid=sid, label=Path(f["dest"]).name)
        except (Cancelled, DiskFull):
            raise
        except Exception as exc:
            failed.append((f, exc))
            step_set(sid, status="fail", detail=str(exc))
            log(f"  {Path(f['dest']).name}: FAILED ({exc}) - "
                f"continuing with the rest")
    return planned, failed


def finish_partial(note, planned, failed):
    """The run reached the end with holes in it. The honest terminal state is
    error, not 'Installed': the page shows the error with its resume note, and
    the headless progress file hands both error and note to Inno."""
    msg = (f"{len(failed)} of {len(planned)} downloads did not land — "
           f"run the installer again; it resumes where it stopped.")
    note.append(msg)
    with LOCK:
        STATE["done_note"] = " ".join(note)
        STATE["phase"] = "error"
        STATE["error"] = msg
    log(msg)


def worker(choices):
    global PIXAL
    source = PIXAL
    try:
        lanes, packs, have, found = build_plan(choices)
        WORK.mkdir(parents=True, exist_ok=True)
        disk_preflight(choices, lanes, have)

        # 1 - ComfyUI ------------------------------------------------------- #
        mode = choices["comfy"]["mode"]
        if mode == "install":
            root = Path(clean_path(choices["comfy"]["path"]))
            # The one check no page can be trusted with, so it lives in the
            # engine, before the first byte moves: never unpack the fresh
            # portable over a ComfyUI that is already there. The page can be
            # stale or bypassed, and the Inno wizard once misread a portable
            # root (its ComfyUI lives one level down) as a fresh target -
            # only a kill mid-download saved that install.
            clash = install_clash(root)
            if clash:
                msg = (f"there is already a ComfyUI at {clash} - choose "
                       f"\"Use\" for it instead of installing over it")
                step_set("comfy_get", status="fail", detail=msg)
                with LOCK:
                    STATE["phase"] = "error"
                    STATE["error"] = msg
                log(f"refused: {msg}")
                return
            tag = CATALOG["comfyui"]["pin"]
            asset = CATALOG["comfyui"]["asset"]
            url = CATALOG["comfyui"]["url"].format(tag=tag, asset=asset)
            log(f"ComfyUI {tag} -> {root}")
            blob = WORK / asset
            download(url, blob, CATALOG["comfyui"]["asset_bytes"],
                     sid="comfy_get", label="ComfyUI portable")
            step_set("comfy_x", status="run", detail="unpacking")
            extract_7z(blob, root, "comfy_x")
            comfy_root = flatten_portable(root)
            cdir = comfy_dir(comfy_root)
            if not cdir:
                raise RuntimeError(f"unpacked, but no models folder under {comfy_root}")
            step_set("comfy_x", status="ok", pct=100, detail=str(comfy_root))
            try:
                blob.unlink()                    # 2 GB of archive, already spent
            except OSError:
                pass
        else:
            comfy_root = Path(clean_path(choices["comfy"]["path"]))
            cdir = comfy_dir(comfy_root)
            if not cdir:
                raise RuntimeError(f"no ComfyUI models folder under {comfy_root}")
            log(f"using the ComfyUI already at {cdir} "
                f"(version {comfy_version(cdir) or 'unknown'})")
            if choices["comfy"].get("update"):
                update_comfy(cdir)

        # 1b - the model folders -------------------------------------------- #
        if choices.get("tidy"):
            step_set("tidy", status="run")
            # Recomputed here rather than trusting the page: this moves files
            # around somebody's ComfyUI, and the list of what moves is decided
            # by what is on disk at the moment it happens.
            tidy(cdir, survey(cdir)["moves"], "tidy")
            found = survey(cdir)

        # 2 - Pixal itself --------------------------------------------------- #
        # After ComfyUI, never before: the default home is inside the portable
        # (ComfyUI\pixal_dm), and a folder sitting there first would block the
        # unpacked archive's own ComfyUI\ from being moved into place.
        step_set("home", status="run")
        PIXAL, moved = install_pixal_to(choices.get("home") or PIXAL, "home")

        # 3 - Pixal's own dependencies -------------------------------------- #
        step_set("deps", status="run")
        py, kind = choose_python(cdir)
        log(f"Pixal will run on {py}")
        ensure_pip(py, "deps")
        if kind == "venv":
            pip(py, ["-r", str(PIXAL / "requirements.txt")], "deps",
                "Pixal requirements")
        else:
            # Pixal is about to share ComfyUI's interpreter, and
            # requirements.txt pins exact versions. Handing pip that file here
            # can DOWNGRADE the numpy or Pillow torch is running on - breaking
            # the ComfyUI we came to set up. So: only what is genuinely missing,
            # and let pip pick a version that fits what is already installed.
            missing = missing_deps(py)
            if missing:
                log(f"  sharing ComfyUI's python - adding only {', '.join(missing)}")
                pip(py, missing, "deps", "Pixal requirements")
        step_set("deps", status="ok", detail=str(py))

        # 3 - node packs ---------------------------------------------------- #
        # Pack requirements belong to ComfyUI's interpreter, NOT Pixal's. A pack
        # lives in ComfyUI's custom_nodes and is imported by ComfyUI's python -
        # so gguf/sentencepiece installed into Pixal's .venv are invisible to it
        # and the lane dies at import with the model already downloaded. Same
        # reasoning as the llama wheel below. pip is never handed --upgrade, so
        # a '>=' that torch already satisfies is left alone.
        pack_py = portable_python(cdir) or py
        if pack_py != py:
            log(f"node packs will use ComfyUI's python: {pack_py}")
        for p in packs:
            sid = "pack:" + p
            step_set(sid, status="run")
            install_pack(p, cdir, pack_py, sid)

        # 4 - weights ------------------------------------------------------- #
        models = Path(cdir) / "models"
        planned, failed = fetch_weights(lanes, have, models)
        if have:
            log(f"skipped {len(have)} file(s) this machine already has")
            step_set("nodl", status="ok", detail=f"{len(have)} already here")

        # 5 - the local brain ----------------------------------------------- #
        brain_gguf, brain_ready = "", False
        brain_lane = next((l for l in lanes if l.get("brain")), None)
        if brain_lane:
            # If this machine already had the brain gguf somewhere of its own,
            # config points at THAT file rather than at a path we never wrote.
            row = next((r for r in (found or {}).get("lanes", {})
                        .get("brain", {}).get("files", []) if r.get("full")), None)
            brain_gguf = row["full"] if row else str(
                models / brain_lane["files"][0]["dest"].replace("/", os.sep))
            step_set("llama", status="run", detail="finding a matching wheel")
            # Into ComfyUI's interpreter on purpose, not Pixal's .venv:
            # ggml-cuda.dll needs the CUDA runtime at load time or llama.cpp
            # silently falls back to CPU, and torch's lib folder is where those
            # DLLs live. server.py's resolve_local_llm_python looks here too.
            brain_py = portable_python(cdir) or py
            rc, _ = run_out([str(brain_py), "-c", "import llama_cpp"], timeout=120)
            if rc == 0:
                brain_ready = True
                step_set("llama", status="ok", detail="already installed")
            else:
                url, tag = llama_wheel_url(brain_py)
                try:
                    ensure_pip(brain_py, "llama")
                    if url:
                        log(f"  wheel: {url.rsplit('/', 1)[-1]}")
                        pip(brain_py, [url], "llama", "llama-cpp-python")
                    else:
                        pip(brain_py, ["llama-cpp-python"], "llama",
                            "llama-cpp-python")
                    rc, _ = run_out([str(brain_py), "-c", "import llama_cpp"],
                                    timeout=180)
                    brain_ready = rc == 0
                except Exception as exc:
                    log(f"  local brain runtime did not install: {exc}")
                if brain_ready:
                    step_set("llama", status="ok", detail="ready")
                else:
                    # Not fatal, and not silent: the model is on disk, chat just
                    # needs an API key until a wheel exists for this machine.
                    step_set("llama", status="skip",
                             detail="no wheel for this python - chat can use an "
                                    "API key instead")

        # 6 - config -------------------------------------------------------- #
        step_set("config", status="run")
        patch = {"comfy_root": str(comfy_root), "setup_done": True}
        if not read_config().get("comfy_url"):
            patch["comfy_url"] = "http://127.0.0.1:8188"
        # A catalogue entry can name a config key (edit.model). When the file
        # this machine already has is a different build of the same model - a
        # Q4 where the catalogue lists a Q6 - point the setting at what is
        # actually installed instead of at a filename that is not there.
        for lane in lanes:
            for f in lane["files"]:
                key = f.get("config")
                row = next((r for r in (found or {}).get("lanes", {})
                            .get(lane["id"], {}).get("files", [])
                            if r["dest"] == f["dest"] and r.get("full")), None)
                if not key or not row:
                    continue
                rel = Path(row["full"]).relative_to(models)
                value = str(Path(*rel.parts[1:]))     # drop the category folder
                section, _, field = key.partition(".")
                patch.setdefault(section, {})[field] = value
                log(f"  config {key} -> {value}")
        if brain_ready and brain_gguf:
            patch["llm"] = {"base_url": "http://127.0.0.1:8191/v1",
                            "api_key": "", "model": "local",
                            "local_model": brain_gguf, "local_keep": True}
        elif brain_gguf:
            patch["llm"] = {"local_model": brain_gguf}
        write_config(patch)
        # pixal.vbs starts run.bat with a bare environment, and an embeddable
        # python cannot make a .venv - so the interpreter choice lives on disk.
        if not (PIXAL / ".venv" / "Scripts" / "python.exe").is_file():
            (PIXAL / ".pixal_python").write_text(str(py) + "\n", encoding="utf-8")
        step_set("config", status="ok", detail=str(PIXAL / "config.json"))

        # 7 - shortcut ------------------------------------------------------ #
        step_set("shortcut", status="run")
        lnk = desktop_shortcut()
        step_set("shortcut", status="ok" if lnk else "skip",
                 detail=lnk or "could not write to the Desktop")

        note = [f"Pixal lives at {PIXAL}. Its shortcut and config point there, "
                f"so {source} is only the copy you unzipped — delete it whenever "
                f"you like." if moved else f"Pixal lives at {PIXAL}."]
        if brain_lane and not brain_ready:
            note.append("The chat brain's model is downloaded but its runtime is "
                        "not installed - open Settings and paste an API key, or "
                        "install llama-cpp-python by hand later.")
        if any(l["id"] == "qwen_edit" for l in lanes):
            note.append("Editing needs ComfyUI restarted once so it loads the "
                        "GGUF node pack. Pixal's own restart button does that.")
        if failed:
            finish_partial(note, planned, failed)
            return
        with LOCK:
            STATE["done_note"] = " ".join(note)
            STATE["phase"] = "done"
        log("done.")
    except Cancelled:
        with LOCK:
            STATE["phase"] = "idle"
            STATE["error"] = ""
        log("cancelled. Nothing half-downloaded was thrown away - "
            "run it again and it picks up where it stopped.")
    except Exception as exc:
        with LOCK:
            STATE["phase"] = "error"
            STATE["error"] = f"{type(exc).__name__}: {exc}"
        log(f"FAILED: {type(exc).__name__}: {exc}")


def update_comfy(cdir):
    """Move an existing checkout onto the version Pixal is developed against.
    Only ever a checkout of a tag, and never over local edits."""
    sid = "comfy_up"
    tag = CATALOG["comfyui"]["pin"]
    step_set(sid, status="run", detail="checking")
    have = comfy_version(cdir)
    if have and have.lstrip("v") == tag.lstrip("v"):
        step_set(sid, status="ok", detail=f"already {have}")
        return
    if not shutil.which("git") or not (Path(cdir) / ".git").is_dir():
        step_set(sid, status="skip",
                 detail="not a git checkout - left alone at " + (have or "unknown"))
        return
    rc, out = run_out(["git", "-C", str(cdir), "status", "--porcelain"], timeout=120)
    if rc == 0 and out.strip():
        step_set(sid, status="skip", detail="local changes - left alone")
        log("  ComfyUI has uncommitted changes; not touching it")
        return
    step_set(sid, status="run", detail="fetching")
    run_out(["git", "-C", str(cdir), "fetch", "--tags", "origin"], timeout=900)
    rc, out = run_out(["git", "-C", str(cdir), "checkout", tag], timeout=600)
    if rc != 0:
        step_set(sid, status="skip", detail="checkout failed - left as it was")
        log("  git checkout said: " + out[-400:])
        return
    step_set(sid, status="ok", detail=f"{have or '?'} -> {tag}")


# --------------------------------------------------------------------------- #
# the page
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# the last-client watchdog: never an orphan with a download in flight
# --------------------------------------------------------------------------- #

def note_client(now=None):
    """Every HTTP request from the page is proof someone is still watching."""
    global LAST_CLIENT
    with LOCK:
        LAST_CLIENT = now if now is not None else time.monotonic()


class _transfer:
    """One download or unpack in flight. The watchdog only ever pauses a run
    while bytes are moving - an idle engine whose page went away is harmless
    and is left alone."""
    def __enter__(self):
        global TRANSFERS
        with LOCK:
            TRANSFERS += 1

    def __exit__(self, *exc):
        global TRANSFERS
        with LOCK:
            TRANSFERS -= 1
        return False


def _pid_alive(pid):
    """Is this process still running? The headless engine's client is the
    wizard that spawned it - this is how it knows the wizard is gone."""
    if os.name == "nt":
        # OpenProcess succeeding is not enough: it also opens terminated
        # processes for as long as anyone holds a handle to them. Ask the
        # handle whether the process is STILL_ACTIVE (259) instead.
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong(0)
            if ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == 259
            return True
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _parent_alive():
    # A re-used PID can keep this true for a process that is not the wizard;
    # the cost of that is one extra UI_TIMEOUT of orphan work, never a false
    # pause - so the cheap check is the right check.
    return _pid_alive(os.getppid())


def _pause_for_resume(exit_=None):
    """Stop mid-run the way resume can pick up. The .part files on disk ARE
    the checkpoint, so nothing is deleted: the in-flight step is marked, the
    worker is asked to unwind so file buffers flush, and the process leaves."""
    log(f"no ui for {int(UI_TIMEOUT // 60)} minutes - pausing; "
        f"rerun setup to resume")
    with LOCK:
        running = [s["id"] for s in STATE["steps"] if s["status"] == "run"]
    for sid in running:
        step_set(sid, detail="paused - rerun setup to resume")
    CANCEL.set()
    t = WORKER_THREAD
    if t and t.is_alive() and t is not threading.current_thread():
        t.join(timeout=90)                   # one socket timeout; then leave
    (exit_ or os._exit)(0)


def ui_watchdog(client_alive=None, now=time.monotonic, sleep=time.sleep,
                pause=None):
    """Pause and exit when the UI is gone and bytes are moving.

    The page polls /api/state while anyone is looking at it; in a headless
    Inno run the client is the wizard process itself, and client_alive probes
    it. UI_TIMEOUT of silence plus a transfer in flight means orphan:
    checkpoint, say so, and leave - rerunning setup resumes from the .part
    files. The window is deliberately generous: a laptop lid-close then costs
    a retry, never a corrupted download."""
    while True:
        sleep(UI_POLL)
        if client_alive is not None and client_alive():
            note_client(now())
        with LOCK:
            busy = TRANSFERS > 0
            idle = now() - LAST_CLIENT
        if busy and idle >= UI_TIMEOUT:
            (pause or _pause_for_resume)()
            return


class Server(ThreadingHTTPServer):
    """A dropped connection is not an error worth printing.

    The console is the only thing a first-time user sees behind the browser, so
    a stack trace every time the page reloads reads as a broken install. Real
    faults still surface - they come through the log, not through socketserver."""
    daemon_threads = True

    def handle_error(self, request, addr):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError,
                            BrokenPipeError)):
            return
        super().handle_error(request, addr)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # The page polls /api/state on a timer, so a reload or a closed tab
            # routinely drops a response mid-write. http.server's default is to
            # print a full traceback per occurrence, which fills the console
            # with red during a normal install and reads as "it broke".
            pass

    def do_GET(self):
        note_client()
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send((HERE / "ui.html").read_text(encoding="utf-8"),
                              "text/html; charset=utf-8")
        if path == "/api/probe":
            return self._send(probe())
        if path == "/api/state":
            with LOCK:
                return self._send(dict(STATE))
        self._send({"error": "no"}, code=404)

    def do_POST(self):
        global WORKER_THREAD
        note_client()
        path = self.path.split("?")[0]
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}

        if path == "/api/validate":
            raw = clean_path(body.get("path"))
            c = comfy_dir(raw)
            return self._send({"ok": bool(c), "comfy": str(c or ""),
                               "version": comfy_version(c) if c else "",
                               "free": free_bytes(c or raw or "C:\\")})
        if path == "/api/survey":
            c = comfy_dir(clean_path(body.get("path")))
            return self._send(survey(c) if c else {"lanes": {}, "moves": [],
                                                   "manual": [], "scanned": 0})
        if path == "/api/pick":
            return self._send({"path": folder_dialog(body.get("title", ""))})
        if path == "/api/start":
            with LOCK:
                if STATE["phase"] == "running":
                    return self._send({"ok": False, "error": "already running"})
                STATE.update(phase="running", log=[], error="", done_note="")
            CANCEL.clear()
            WORKER_THREAD = threading.Thread(target=worker, args=(body,),
                                             daemon=True)
            WORKER_THREAD.start()
            return self._send({"ok": True})
        if path == "/api/cancel":
            CANCEL.set()
            return self._send({"ok": True})
        if path == "/api/launch":
            subprocess.Popen(["wscript", "//nologo", str(PIXAL / "pixal.vbs")],
                             cwd=str(PIXAL))
            return self._send({"ok": True})
        if path == "/api/quit":
            self._send({"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.4),
                                             os._exit(0)), daemon=True).start()
            return
        self._send({"error": "no"}, code=404)


def folder_dialog(title):
    """The native folder picker, borrowed from PowerShell. A browser cannot hand
    a page a real path, and typing one is where people mistype."""
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
          f"$d.Description='{title}';"
          "$d.ShowNewFolderButton=$true;"
          "if($d.ShowDialog() -eq 'OK'){$d.SelectedPath}")
    rc, out = run_out(["powershell", "-NoProfile", "-STA", "-Command", ps],
                      timeout=600)
    return out.strip().splitlines()[-1].strip() if rc == 0 and out.strip() else ""


def progress_line():
    """One flat snapshot of the run, for a caller that is not a browser.

    Deliberately key=value text and not JSON: the reader is Inno Setup's Pascal
    scripting, where parsing JSON is an afternoon and reading a line is a
    function call. Percent is per-step-count rather than per-byte because the
    steps are wildly uneven and a bar that sits at 3% for twenty minutes is
    worse than one that moves in visible jumps."""
    with LOCK:
        steps = list(STATE["steps"])
        phase, error, note = STATE["phase"], STATE["error"], STATE["done_note"]
    done = sum(1 for s in steps if s["status"] in ("ok", "skip"))
    running = next((s for s in steps if s["status"] == "run"), None)
    pct = int(done * 100 / len(steps)) if steps else 0
    if running:
        pct = min(99, pct + int(running.get("pct") or 0) / max(len(steps), 1))
    label = running["label"] if running else ("Finishing" if phase == "running"
                                              else phase)
    detail = (running or {}).get("detail", "") or ""
    return "\n".join([
        f"phase={phase}",
        f"pct={int(pct)}",
        f"step={label}",
        f"detail={detail[:120]}",
        f"error={(error or '')[:400].replace(chr(10), ' ')}",
        f"note={(note or '')[:400].replace(chr(10), ' ')}",
        "",
    ])


def probe_file(out_path):
    """probe(), flattened for Inno's wizard pages.

    Same key=value discipline as progress_line: the reader is Pascal script,
    and a scan that takes eight seconds should happen once, in the background,
    not twice in two languages."""
    p = probe()
    g = p["gate"]
    lines = [f"gpu={p['gpus'][0]['name'] if p['gpus'] else ''}",
             f"vram_gb={p['vram_gb']}",
             f"driver={g['driver_major']}",
             f"driver_min={g['driver_min']}",
             f"gate_gpu={1 if g['gpu'] else 0}",
             f"gate_driver={1 if g['driver'] else 0}",
             f"gate_why={g['why']}",
             f"comfy_count={len(p['installs'])}"]
    for i, inst in enumerate(p["installs"][:5]):
        lines.append(f"comfy{i}={inst['root']}")
        lines.append(f"comfy{i}_version={inst['version']}")
    for drive, free in p["free"].items():
        lines.append(f"free_{drive[0].upper()}={free}")
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


def headless(choices_path, progress_path):
    """Run an install with no server, no page and no browser.

    This is the path Inno Setup drives: it has already asked every question on
    its own wizard pages, so all that is left is the work. The engine below is
    the same one the browser flow uses - same plan, same downloads, same
    resume - it just reports through a file instead of a socket."""
    global WORKER_THREAD
    try:
        choices = json.loads(Path(choices_path).read_text(encoding="utf-8"))
    except Exception as exc:
        Path(progress_path).write_text(
            f"phase=error\npct=0\nstep=\ndetail=\n"
            f"error=could not read {choices_path}: {exc}\nnote=\n",
            encoding="utf-8")
        return 2

    out = Path(progress_path)
    stop = threading.Event()

    def flush():
        try:
            tmp = out.with_suffix(".tmp")
            tmp.write_text(progress_line(), encoding="utf-8")
            os.replace(tmp, out)                 # atomic; the reader polls it
        except Exception:
            pass

    def pump():
        while not stop.wait(0.4):
            flush()

    with LOCK:
        STATE.update(phase="running", log=[], error="", done_note="")
    flush()
    threading.Thread(target=pump, daemon=True).start()
    # No page ever polls here - the client is the wizard process itself. While
    # it lives the heartbeat stays fresh; when it dies the countdown starts.
    WORKER_THREAD = threading.current_thread()
    threading.Thread(target=ui_watchdog,
                     kwargs={"client_alive": _parent_alive},
                     daemon=True).start()
    try:
        worker(choices)
    finally:
        stop.set()
        flush()
    with LOCK:
        return 0 if STATE["phase"] == "done" else 1


def alert(text, title="Pixal Setup"):
    """The only way to say anything when there is no console and no window."""
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:
        print(text)


def open_window(url):
    """A real window, or False if this machine cannot give us one.

    An address bar and a console are the two things that make an installer feel
    like somebody's script instead of a product, so the window is the point -
    but it is chrome, not function. WebView2 is inbox on Windows 11 and so this
    path is what virtually everyone gets; a debloated image or a stripped
    runtime falls back to the browser, which is exactly the installer that
    shipped before, unchanged. Never let the chrome decide whether Pixal can
    be installed."""
    try:
        import webview
    except Exception as exc:
        log(f"  no window toolkit ({type(exc).__name__}) - using the browser")
        return False
    try:
        webview.create_window("Pixal Setup", url,
                              width=1080, height=760,
                              min_size=(960, 680),
                              background_color="#faf9f5",
                              text_select=True)
        webview.start()                          # blocks until the user closes
        return True
    except Exception as exc:
        # WebView2 runtime missing, or a headless/locked-down session.
        log(f"  could not open a window ({type(exc).__name__}: {exc}) - "
            f"using the browser")
        return False


def main():
    if os.name != "nt":
        print("Pixal's installer is Windows-only.")
        return 1
    WORK.mkdir(parents=True, exist_ok=True)

    # Driven by Inno Setup: every question was already answered on its wizard
    # pages, so do the work and report through a file. No server, no browser.
    argv = sys.argv[1:]
    if argv and argv[0] == "--probe":
        if len(argv) < 2:
            print("usage: --probe <out.txt>")
            return 2
        return probe_file(argv[1])
    if argv and argv[0] == "--headless":
        if len(argv) < 3:
            print("usage: --headless <choices.json> <progress.txt>")
            return 2
        return headless(argv[1], argv[2])

    port = PORT
    for _ in range(20):                          # a stale installer holding it
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                break
        port += 1
    try:
        srv = Server(("127.0.0.1", port), Handler)
    except OSError as exc:
        alert(f"Could not start the installer on this machine.\n\n{exc}")
        return 1
    url = f"http://127.0.0.1:{port}/"
    log(f"Pixal installer -> {url}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # Browser flow: the page's own polling is the heartbeat, nothing to probe.
    threading.Thread(target=ui_watchdog, daemon=True).start()

    if open_window(url):
        return 0                                 # window closed; we are done

    # Fallback: the browser, and a console title for the window behind it.
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("Pixal installer")
    except Exception:
        pass
    if not webbrowser.open(url):
        alert(f"Pixal Setup is running, but no browser opened.\n\n"
              f"Open this address yourself:\n\n{url}")
    try:
        threading.Event().wait()                 # serve until the user quits
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
