"""Pixal - conversational middleware for ComfyUI.

Chat in, images out. An OpenAI-compatible cloud or local model directs a public
recipe; Pixal validates the selected model family, patches a proven API graph,
queues it in ComfyUI, and streams progress back over SSE. Every completed render
lands in the local history ledger.

Run:  run.bat
Open: http://127.0.0.1:8190
"""
import asyncio
import collections
import copy
import errno
import io
import hashlib
import hmac
import html as html_mod
import inspect
import ipaddress
import json
import math
import os
import random
import re
import shutil
import signal
import socket
import statistics
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from functools import lru_cache
from pathlib import Path, PureWindowsPath

import aiohttp
from aiohttp import web

HERE = Path(__file__).absolute().parent

# CDIR is the ComfyUI directory that owns models/input/output. Pixal can live
# either directly under ComfyUI (including through a directory junction) or in
# a normal standalone checkout such as ~/Projects/Pixal. In the latter case the
# first-run setup/config points it at the chosen ComfyUI install.
_NEIGHBOR_COMFY = HERE.parent if (HERE.parent / "models").is_dir() else None
CDIR = _NEIGHBOR_COMFY or HERE

def _nt():
    """The one platform seam. Every Windows/POSIX branch below keys off this
    (sys.platform, the same value the ComfyUI console check already reads), so
    tests can exercise the POSIX half from any host by patching it."""
    return sys.platform == "win32"

def resolve_comfy_dir(root):
    """User-supplied path -> the ComfyUI dir holding models/. Accepts a portable
    root (<root>\\ComfyUI\\models), a bare ComfyUI checkout (<root>\\models),
    or the models folder itself."""
    try:
        p = Path(str(root).strip().strip('"').rstrip("\\/"))
    except Exception:
        return None
    if p.name.lower() == "models" and p.is_dir():
        return p.parent
    for c in (p / "ComfyUI", p):
        if (c / "models").is_dir():
            return c
    return None

def apply_comfy_root(root):
    global CDIR
    c = resolve_comfy_dir(root) if root else None
    if c:
        CDIR = c
    return c

# Character canon is DATA (characters/*.json), not code - the app ships with no one.
CHAR_DIR = HERE / "characters"
PRONOUNS = {"female": ("she", "her"), "male": ("he", "him"), "other": ("they", "them")}

def load_characters():
    out = {}
    if CHAR_DIR.is_dir():
        for p in sorted(CHAR_DIR.glob("*.json")):
            try:
                ch = json.loads(p.read_text(encoding="utf-8"))
                if ch.get("id") and ch.get("name"):
                    out[ch["id"]] = ch
            except Exception:
                pass
    return out

CHARACTERS = load_characters()

INPUT_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".jfif", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".avif",
}
MAX_UPLOAD_BYTES = 40_000_000
UPLOAD_CLIENT_MAX_BYTES = MAX_UPLOAD_BYTES + 1_000_000
INPUT_REF_TYPES_FILE = HERE / "input_ref_types.json"
REFERENCE_KINDS = frozenset(("identity", "style", "clothing", "object"))

def resolve_character(ref):
    """id string or dict -> character dict (or None)."""
    if isinstance(ref, dict):
        return ref
    return CHARACTERS.get(str(ref or "")) or None

def input_ref_name(ref):
    """Normalize a ComfyUI/input-relative image path; reject path traversal."""
    name = str(ref or "").strip().replace("\\", "/").removeprefix("input/")
    parts = name.split("/")
    if (not name or name.startswith("/") or "\0" in name or
            any(part in ("", ".", "..") or ":" in part for part in parts)):
        return ""
    root = (CDIR / "input").resolve()
    candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return ""
    return "/".join(parts)


def reference_kind(value):
    kind = str(value or "").strip().lower()
    return kind if kind in REFERENCE_KINDS else ""


def load_input_ref_types():
    try:
        payload = json.loads(INPUT_REF_TYPES_FILE.read_text(encoding="utf-8"))
        images = payload.get("images", {}) if isinstance(payload, dict) else {}
        return {name: kind for raw_name, raw_kind in images.items()
                if (name := input_ref_name(raw_name)) and
                (kind := reference_kind(raw_kind))}
    except (OSError, ValueError, TypeError):
        return {}


INPUT_REF_TYPES = load_input_ref_types()


def set_input_ref_type(name, kind):
    """Persist the semantic type assigned when an input image was uploaded."""
    canonical = input_ref_name(name)
    normalized_kind = reference_kind(kind)
    if not canonical or not normalized_kind:
        raise ValueError("reference image and type are required")
    INPUT_REF_TYPES[canonical] = normalized_kind
    _save_input_ref_types()
    return normalized_kind


def input_image_record(name, *, mtime=None):
    """One browser-safe record for an image under ComfyUI/input."""
    canonical = input_ref_name(name)
    if not canonical:
        return None
    parts = canonical.split("/")
    record = {
        "name": canonical,
        "filename": parts[-1],
        "subfolder": "/".join(parts[:-1]),
        "type": "input",
    }
    if mtime is not None:
        record["mtime"] = mtime
    kind = INPUT_REF_TYPES.get(canonical)
    if kind:
        record["kind"] = kind
    return record


def input_image_catalog():
    """Every supported ComfyUI input image, newest first, including subfolders."""
    root = CDIR / "input"
    if not root.is_dir():
        return []
    records = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in INPUT_IMAGE_SUFFIXES:
            continue
        try:
            rel = path.relative_to(root).as_posix()
            record = input_image_record(rel, mtime=path.stat().st_mtime)
        except (OSError, ValueError):
            continue
        if record:
            records.append(record)
    records.sort(key=lambda item: (-item.get("mtime", 0), item["name"].lower()))
    return records


def _save_input_ref_types():
    payload = {"version": 1, "images": dict(sorted(INPUT_REF_TYPES.items()))}
    temporary = INPUT_REF_TYPES_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(INPUT_REF_TYPES_FILE)


def migrate_percent_encoded_inputs():
    """One-time cleanup. The upload proxy used to let aiohttp percent-encode
    multipart filenames, so 'Screenshot 2026.png' landed in ComfyUI/input as
    'Screenshot%202026.png'. Rename such files to their decoded names and move
    every stored reference with them (ref-type labels, character anchors, and
    ledger spec.ref). Conservative: a name is skipped when its decoded form is
    unsafe or already taken."""
    root = CDIR / "input"
    if not root.is_dir():
        return {}
    renames = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in INPUT_IMAGE_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        decoded = urllib.parse.unquote(rel)
        if decoded == rel or input_ref_name(decoded) != decoded:
            continue
        target = root / decoded
        if target.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            path.rename(target)
        except OSError as exc:
            print(f"[pixal] could not rename input {rel}: {exc}", flush=True)
            continue
        renames[rel] = decoded
        print(f"[pixal] renamed input {rel} -> {decoded}", flush=True)
    if not renames:
        return renames
    if any(name in INPUT_REF_TYPES for name in renames):
        for old, new in renames.items():
            if old in INPUT_REF_TYPES:
                INPUT_REF_TYPES[new] = INPUT_REF_TYPES.pop(old)
        try:
            _save_input_ref_types()
        except OSError as exc:
            print(f"[pixal] could not rewrite input_ref_types.json: {exc}", flush=True)
    for ch in CHARACTERS.values():
        old = ch.get("identity_ref")
        if old in renames:
            ch["identity_ref"] = renames[old]
            try:
                (CHAR_DIR / f"{ch['id']}.json").write_text(
                    json.dumps(ch, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError as exc:
                print(f"[pixal] could not rewrite character {ch['id']}: {exc}", flush=True)
    if LEDGER.exists():
        try:
            lines = LEDGER.read_text(encoding="utf-8").splitlines()
            changed = False
            for i, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                ref = (entry.get("spec") or {}).get("ref")
                if ref in renames:
                    entry["spec"]["ref"] = renames[ref]
                    lines[i] = json.dumps(entry, ensure_ascii=False)
                    changed = True
            if changed:
                temporary = LEDGER.with_suffix(".jsonl.tmp")
                temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
                temporary.replace(LEDGER)
        except OSError as exc:
            print(f"[pixal] could not rewrite history.jsonl: {exc}", flush=True)
    return renames


@lru_cache(maxsize=512)
def _input_thumbnail_bytes(path_text, mtime_ns):
    """Small first-frame WebP cached by resolved path + modification time."""
    from PIL import Image, ImageOps
    with Image.open(path_text) as source:
        source.seek(0)
        thumb = ImageOps.exif_transpose(source).copy()
    thumb.thumbnail((192, 192), Image.Resampling.LANCZOS)
    if thumb.mode not in ("RGB", "RGBA"):
        thumb = thumb.convert("RGBA" if "transparency" in thumb.info else "RGB")
    out = io.BytesIO()
    thumb.save(out, format="WEBP", quality=78, method=4)
    return out.getvalue()

def character_identity(ref, require_file=True):
    """Return (character, input filename) or raise an actionable identity error."""
    ch = resolve_character(ref)
    if not ch:
        raise ValueError(f"character anchor not found: {ref}")
    image = input_ref_name(ch.get("identity_ref"))
    if not image:
        raise ValueError(f"{ch['name']} needs a reference image before identity editing")
    if require_file and not (CDIR / "input" / image).is_file():
        raise ValueError(f"{ch['name']}'s reference image is missing from ComfyUI/input: {image}")
    return ch, image

def character_identity_ready(ch):
    """Safe availability bit for the UI; never expose the private filename."""
    try:
        character_identity(ch)
        return True
    except ValueError:
        return False

def character_subject(ch):
    """The standing 'who is this person' block for txt2img captions."""
    if ch.get("subject_block"):
        return ch["subject_block"]
    subj, _obj = PRONOUNS.get(ch.get("sex", "female"), PRONOUNS["other"])
    noun = {"female": "woman", "male": "man"}.get(ch.get("sex"), "person")
    parts = []
    if ch.get("age"):
        parts.append(f"a {ch['age']}-year-old")
    if ch.get("race"):
        parts.append(ch["race"])
    parts.append(noun)
    line = f"{subj.capitalize()} is {' '.join(parts)}."
    if ch.get("style"):
        st = ch["style"].rstrip(".").strip()
        line += " " + st[0].upper() + st[1:] + "."
    return line

def wardrobe_lock_for(ch):
    """The fineporn base drops clothing unless the LAST clause locks it - per-character
    wording when the anchor defines one, generic otherwise."""
    if ch and ch.get("wardrobe_lock"):
        return ch["wardrobe_lock"]
    subj, _obj = PRONOUNS.get((ch or {}).get("sex", "female"), PRONOUNS["other"])
    return f"{subj.capitalize()} is fully dressed in the clothing described above."

COMFY = "http://127.0.0.1:8188"
COMFY_WS = "ws://127.0.0.1:8188/ws"

# A sampling step slower than this is not a big model, it is a starved one.
# The heaviest thing Pixal renders - MiniMax H3, 362 frames at 768x1152 - runs
# 33s per step with the card to itself; the same render streaming its weights
# from system memory was over five times that. Well clear of both.
STEP_SLOW_SECONDS = 120

# Past this, an unfinalized job is not in flight - it is a corpse the watchdog
# has not buried yet. Comfortably longer than the slowest real render here (H3
# multishot, ~170s a shot) and far shorter than watch()'s 1800s deadline, which
# is what used to keep the butler switched off after a ComfyUI crash.
JOB_INFLIGHT_SECONDS = 600

def apply_comfy_url(url):
    """The compute picker: point every render, poll and proxy at another ComfyUI.
    The model catalog still reads THIS machine's disk - same-library boxes only."""
    global COMFY, COMFY_WS
    url = (url or "").strip().rstrip("/")
    if not url.startswith("http"):
        url = "http://127.0.0.1:8188"
    COMFY = url
    COMFY_WS = url.replace("http", "ws", 1) + "/ws"
KIMI_URL = "https://api.moonshot.ai/v1/chat/completions"
KIMI_MODEL = "kimi-k3"
LISTEN = ("127.0.0.1", 8190)

# Pixal's own version, and the release channel it means. The channel is a
# CHANNEL, not a maturity claim: "stable" is the line that ships, next to
# "beta" and "nightly", and the chip in the compat card reads it from here so
# the number can never drift from what is actually running.
# The trailing "b" is the beta line; the CHANNEL beside it is which build of
# that line you are on (stable, as against nightly). Two different facts, which
# is why they are two fields and not one string.
PIXAL_VERSION = "1.0.6b"
PIXAL_CHANNEL = "stable"

LEDGER = HERE / "history.jsonl"
KEEP_COMFY = HERE / ".pixal_keep_comfy"   # set by /api/sidecar/restart: this exit
                                          # is a restart, so leave the GPU stack up
LANE_FILE = HERE / "lane.json"          # single-lane era; migrated into chats/ on boot
CHATS_DIR = HERE / "chats"              # one json per chat: {id,title,ts,lane,convo}
# "zara_edit" was the original key - kept as an alias so old ledger entries
# reroll/iterate fine, but every user-facing surface says identity_edit now
# (people build their OWN characters; her name doesn't belong in the product)
TEMPLATES = {p.stem: json.loads(p.read_text(encoding="utf-8"))
             for p in (HERE / "templates").glob("*.json")}
TEMPLATES["zara_edit"] = TEMPLATES["identity_edit"]

MODEL_DIRS = ["checkpoints", "loras", "diffusion_models", "vae", "text_encoders",
              "controlnet", "upscale_models", "latent_upscale_models"]

_LORA_TITLE_CACHE = HERE / "_lora_titles.json"
# How long a fresh arrival stays badged. Sized against a real collection: this
# one gains ~13 models a week, so a fortnight would badge half the picker and the
# chip would stop meaning anything. A week answers "what did I just pull down".
MODEL_NEW_WINDOW = 7 * 86400
CONFIG = HERE / "config.json"


def is_new_model(entry, now=None):
    """Whether an installed model landed recently enough to badge in the picker.

    Read from the file's own mtime rather than from a record of when Pixal first
    noticed it. A first-seen ledger sounds better but is only as good as the list
    it is handed: any caller passing a partial set - a filtered view, a test, a
    half-warmed scan - rewrites the baseline and every model in the collection
    re-badges as new. mtime cannot be poisoned that way, and it also gives the
    right answer on a fresh Pixal install against an old models folder."""
    stamp = entry.get("mtime") or 0
    if not stamp:
        return False
    return (now or time.time()) - stamp < MODEL_NEW_WINDOW

def load_config():
    cfg = {"llm": {"base_url": KIMI_URL.rsplit("/chat", 1)[0],
                   "api_key": os.environ.get("MOONSHOT_API_KEY", ""),
                   "model": KIMI_MODEL,
                   "local_model": "",         # GGUF path for the managed local brain
                   "local_keep": True,        # keep it in VRAM between replies
                   # ...but not forever: hand the card back after this many
                   # idle minutes. 0 disables the reaper entirely.
                   "local_idle_minutes": 10,
                   # -1 = every layer on the GPU (the hardcoded flag before
                   # 8.7), 0 = CPU, positive = that many layers. The 16 GB
                   # knob: the brain shares the card or the render swaps.
                   "local_gpu_layers": -1},
           "critic": {"model": "Qwen3-VL-4B-Instruct"},
           # Upscaling is a finishing step, not a recipe: the image side runs any
           # installed ESRGAN-style model, the video side runs the RTX VSR filter.
           "upscale": {"image_model": "", "image_mode": UPSCALE_IMAGE_DEFAULT_MODE,
                       "video_mode": UPSCALE_VIDEO_DEFAULT_MODE,
                       "video_scale": 2.0},
           # Which Qwen-Image-Edit release runs an instruction edit. "" = the
           # recipe default. Releases differ in encoder node (see
           # set_qwen_edit_encoder), so this is a real choice, not a preference.
           # "speed" picks between the model's own distillation and its
           # un-accelerated schedule; the step counts behind both come from
           # EDIT_ACCELERATORS, never from the user, because a distillation
           # belongs to one transformer.
           "edit": {"model": "", "speed": "turbo"},
           # Optional decoder swap for the Z-Image/Flux VAE - "" keeps the
           # profile's own matched VAE. See zimage_vae_candidates().
           "vae": {"zimage": ""},
           # NVIDIA PiD as the finishing decoder. identity_finish routes the
           # Identity Edit sampler's final latent through PiD at 4x instead of
           # the Wan VAE - experimental: Krea 2 shares Qwen-Image's latent
           # space, but PiD's qwenimage decoder was not trained on Krea 2.
           "pid": {"identity_finish": False},
           # Which engine the Animate popup opens on, and which model inside
           # it. "" = the server's order (LTX 2.5 first, stock FL2VA inside
           # H3). Deliberate defaults, set in Settings - the popup itself
           # still switches freely per clip.
           "video": {"default_engine": "", "default_model": ""},
           "extra_model_roots": [],
           "comfy_url": "",
           "comfy_root": "",
           "setup_done": False,
           # Measured cold-start time, so the boot meter is calibrated to this
           # machine. 0 = never measured; the UI falls back to a constant.
           "comfy_boot_seconds": 0.0,
           # VRAM profile: "auto" follows the detected card; "32"/"24"/"16"
           # pin a tier (community testers simulate smaller cards; a laptop
           # eGPU can read wrong). Advisory layer only - the butler enforces.
           "vram_profile": "auto",
           # Pop ComfyUI's own graph editor in a browser tab when its console
           # boots. Off by default: the popup is jarring mid-chat, and the node
           # editor is a power tool, not part of the studio flow.
           "comfy_editor": False,
           # How ComfyUI's own window looks. "tui" wraps the launcher in
           # comfy_tui.py - a phase meter, a card meter, and an errors-only log
           # that outlives the window. "plain" is the raw .bat console, which is
           # the escape hatch if the wrapper ever misreads this machine.
           "comfy_console": "tui",
           # Chrome PWA id pixal.vbs opens the app window with - per machine,
           # only exists after that machine installs the PWA; "" makes the vbs
           # fall back to chrome --app= (no PWA needed).
           "chrome_app_id": "",
           # Bind every interface instead of loopback, so a phone, a tablet or
           # a VR headset on the same Wi-Fi can open the studio. Off by
           # default - this is the one setting that puts Pixal on a network.
           # access_gate still stands: any Host that is not localhost has to
           # present ?key=<access_key> once, which then rides a cookie.
           "lan_access": False,
           # Keep the studio open with no window connected. Off by default: at
           # the desk, closing the window SHOULD take the model stack down with
           # it. On for a remote session, where a backgrounded phone tab is not
           # the same thing as "done for the day". See exit_when_unwatched().
           "stay_up": False,
           # Whether a render may be explicit, which decides one thing: if the
           # wardrobe lock is appended to the prompt (see wardrobe_lock_for -
           # the fineporn base drops clothing without it). "auto" reads the
           # words the user actually wrote; "on" and "off" stop it guessing.
           # It only bites with Prompt enhance OFF, where there is no brain in
           # the path to infer nsfw - with enhance on the brain still decides.
           "explicit": "auto",
           "access_key": ""}
    if CONFIG.exists():
        try:
            saved = json.loads(CONFIG.read_text(encoding="utf-8"))
            cfg["llm"].update(saved.get("llm") or {})
            cfg["critic"].update(saved.get("critic") or {})
            cfg["upscale"].update(saved.get("upscale") or {})
            cfg["edit"].update(saved.get("edit") or {})
            cfg["vae"].update(saved.get("vae") or {})
            cfg["pid"].update(saved.get("pid") or {})
            cfg["video"].update(saved.get("video") or {})
            cfg["extra_model_roots"] = saved.get("extra_model_roots") or []
            cfg["comfy_url"] = (saved.get("comfy_url") or "").strip()
            cfg["comfy_root"] = (saved.get("comfy_root") or "").strip()
            cfg["setup_done"] = bool(saved.get("setup_done"))
            # This merge is a whitelist, so anything missing here is silently
            # dropped on load AND wiped by the next save_config round-trip.
            cfg["comfy_boot_seconds"] = float(saved.get("comfy_boot_seconds") or 0.0)
            if str(saved.get("vram_profile") or "") in ("auto", "32", "24", "16"):
                cfg["vram_profile"] = str(saved["vram_profile"])
            cfg["chrome_app_id"] = (saved.get("chrome_app_id") or "").strip()
            cfg["comfy_editor"] = bool(saved.get("comfy_editor"))
            if str(saved.get("comfy_console") or "") in ("tui", "plain"):
                cfg["comfy_console"] = str(saved["comfy_console"])
            cfg["lan_access"] = bool(saved.get("lan_access"))
            cfg["stay_up"] = bool(saved.get("stay_up"))
            if str(saved.get("explicit") or "") in ("auto", "on", "off"):
                cfg["explicit"] = str(saved["explicit"])
            cfg["access_key"] = (saved.get("access_key") or "").strip()
        except Exception as exc:
            # A malformed config silently becoming first-run defaults is worse
            # than a loud one: keep the evidence and say what happened. The
            # .bad copy doubles as a once-only guard, since this runs per request.
            bad = CONFIG.with_suffix(".json.bad")
            if not bad.exists():
                print(f"[pixal] config.json unreadable, using defaults: {exc}", flush=True)
                try:
                    shutil.copy2(CONFIG, bad)
                except OSError:
                    pass
    return cfg

def installed_vl_models():
    """AILab_QwenVL checkpoints actually on disk (anything else downloads on first run -
    the picker lists only what is truly local)."""
    llm = CDIR / "models" / "LLM"
    out = []
    for d in (llm / "Qwen-VL", llm):
        if d.is_dir():
            out += [p.name for p in d.iterdir()
                    if p.is_dir() and p.name not in (".cache", "Qwen-VL") and "VL" in p.name]
    joycaption = [p.name for p in llm.iterdir()
                  if p.is_dir() and "joycaption" in p.name.lower()] if llm.is_dir() else []
    return sorted(set(out + joycaption))

def critic_weights():
    """(name, on-disk) for the reviewer chosen in Settings - the ONE check
    every ComfyUI VL fallback passes before submitting.

    A submit without these weights is what pulled ~16GB from HuggingFace
    mid-render - the "Fetching 12 files" stall of 2026-08-22. The look got
    this guard in 9c089d9 and the review never did, and the two drifted
    within a day (brief 9.22); frame_inventory and review() both ask here
    now, so they cannot drift again."""
    critic = load_config()["critic"]["model"]
    return critic, critic in installed_vl_models()

def vl_download_gb(name):
    """Rough FP16 download size of an AILab_QwenVL checkpoint - ~2GB per
    billion parameters, read off the name. Good enough to warn with, which
    is all a warning needs; None when the name carries no size."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", name, re.I)
    return round(float(m.group(1)) * 2) if m else None

def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")

def model_roots(cfg=None):
    """Every root we scan: ComfyUI/models, extra_model_paths.yaml entries, and any
    roots the user added in settings (other drives, other layouts)."""
    cfg = cfg or load_config()
    roots = [CDIR / "models"]
    yaml_path = CDIR / "extra_model_paths.yaml"
    if yaml_path.exists():
        try:
            import yaml
            for section in (yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}).values():
                if isinstance(section, dict):
                    bp = section.get("base_path")
                    if bp:
                        roots.append(Path(bp))
        except Exception:
            pass
    for r in cfg["extra_model_roots"]:
        p = Path(r)
        if p.is_dir():
            roots.append(p)
    seen, out = set(), []
    for r in roots:
        k = str(r).lower()
        if k not in seen and r.is_dir():
            seen.add(k)
            out.append(r)
    return out

KIND_DIRS = ["checkpoints", "loras", "diffusion_models", "unet", "vae", "clip",
             "text_encoders", "controlnet", "upscale_models",
             # the LTX spatial upscalers live here; without it in the scan the
             # 2.5 engine read as missing its upscaler with the file on disk
             "latent_upscale_models"]
MODEL_EXTS = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin")
_CATALOG = {"at": 0, "data": None}

# Deno's RTX Video Super Resolution filter. Modes are <filter> <quality>; VSR is
# the upscaling family, the others are restoration passes at the same size.
# The LTX mode is a different animal: it re-renders the clip 2x through the
# LTX 2.5 latent upsampler + a short refine pass, inventing real detail the
# way PiD does for stills, and ignores the VSR scale setting (fixed 2x).
LTX25_UPSCALE_MODE = "LTX 2.5 2x"
UPSCALE_VIDEO_MODES = ("VSR Low", "VSR Medium", "VSR High", "VSR Ultra",
                       LTX25_UPSCALE_MODE)
# Image upscaling has two personalities: "model" runs a deterministic
# ESRGAN-style enlarger, "pid" runs NVIDIA PiD - a 4-step tiled pixel-diffusion
# pass that invents real texture instead of sharpening what is there.
UPSCALE_IMAGE_MODES = ("model", "pid")
UPSCALE_IMAGE_DEFAULT_MODE = "model"
UPSCALE_VIDEO_DEFAULT_MODE = "VSR High"
UPSCALE_VIDEO_SCALE_RANGE = (1.0, 4.0)

def model_catalog(kind=None, ttl=30):
    """Recursive scan of every model root, 30s TTL. Entries carry the relpath ComfyUI
    resolves (relative to the kind dir) so other drives/layouts work unchanged."""
    now = time.time()
    if _CATALOG["data"] is None or now - _CATALOG["at"] > ttl:
        entries = []
        for root in model_roots():
            for kd in KIND_DIRS:
                base_dir = root / kd
                if not base_dir.is_dir():
                    continue
                for p in base_dir.rglob("*"):
                    if p.is_file() and p.suffix.lower() in MODEL_EXTS \
                            and ".cache" not in p.parts:
                        try:
                            mtime = p.stat().st_mtime
                        except OSError:
                            mtime = 0
                        entries.append({"kind": kd, "root": str(root),
                                        "rel": str(p.relative_to(base_dir)),
                                        "mtime": mtime})
        _CATALOG.update(at=now, data=entries)
    data = _CATALOG["data"]
    return [e for e in data if e["kind"] == kind] if kind else data

# Both naming conventions in the wild: "4x-UltraSharp" and "..._x2_PSNR".
_UPSCALE_SCALE_HINT = re.compile(r"(?:^|[^0-9a-z])(?:([1248])x|x([1248]))", re.I)


def _upscale_scale_hint(rel):
    parts = Path(rel).parts
    for text in (Path(rel).name, parts[0] if len(parts) > 1 else ""):
        match = _UPSCALE_SCALE_HINT.search(text)
        if match:
            return int(match.group(1) or match.group(2))
    return None


def upscale_model_options():
    """Installed ESRGAN-style upscalers, grouped by folder, newest naming first.

    The declared factor is read from the filename only as a hint for the label -
    the real factor lives in the weights and ComfyUI applies it regardless."""
    out = []
    for entry in model_catalog("upscale_models"):
        rel = entry["rel"]
        parts = Path(rel).parts
        out.append({
            "name": rel,
            "short": Path(rel).stem,
            "group": parts[0] if len(parts) > 1 else "(root)",
            "scale_hint": _upscale_scale_hint(rel),
        })
    out.sort(key=lambda item: (item["group"].lower(), item["short"].lower()))
    return out


def resolve_upscale_model(chosen):
    """Map a saved upscaler onto an installed file, or raise saying what is wrong.

    The setting stores the path relative to upscale_models, so reorganising that
    folder - dropping a loose 4x-UltraSharp.pth into a 4x/ subfolder - would
    otherwise break a working setting with nothing to show for it. Fall back to
    matching the filename alone, which is what actually identifies the weights."""
    want = str(chosen or "").strip().replace("/", "\\")
    if not want:
        raise ValueError("choose an upscale model in Settings first")
    installed = [e["rel"] for e in model_catalog("upscale_models")]
    for rel in installed:
        if rel.replace("/", "\\").lower() == want.lower():
            return rel
    base = Path(want).name.lower()
    moved = [rel for rel in installed if Path(rel).name.lower() == base]
    if moved:
        return moved[0]
    if not installed:
        raise ValueError("no upscale models found - put ESRGAN-style weights in "
                         "ComfyUI/models/upscale_models, then Rescan in Settings")
    raise ValueError(f"upscale model is not installed: {want}")


_COMFY_NODES = {"at": 0.0, "names": None, "modules": {}, "enums": {}}
# Deno's pack first; the NVIDIA RTX pack exposes an equivalent filter as a fallback.
VIDEO_UPSCALE_NODES = ("DenoRTXVFXEasyUpscale", "RTXVideoSuperResolution")


def _video_upscale_node():
    """The installed RTX Video Super Resolution class, or "" when neither pack is."""
    names = _COMFY_NODES["names"]
    if names is None:
        return VIDEO_UPSCALE_NODES[0]      # not probed yet - do not hide the action
    return next((n for n in VIDEO_UPSCALE_NODES if n in names), "")


PID_UPSCALE_NODE = "PiDUpscale"            # from the ComfyUI-PiD pack
PID_DECODE_NODE = "PiDDecode"

def _node_available(name):
    """True unless ComfyUI has been probed and this node class is missing.

    Unprobed means "not asked yet", never "absent": hiding an action because the
    catalog is cold would be a worse lie than offering one that fails loudly.
    """
    names = _COMFY_NODES["names"]
    return names is None or name in names

def _pid_node_available(name):
    """True unless ComfyUI has been probed and the PiD pack is missing."""
    return _node_available(name)

def _pid_upscale_available():
    return _pid_node_available(PID_UPSCALE_NODE)


def _combo_choices(spec):
    """The choices out of an /object_info combo field, in either dialect.

    ComfyUI has TWO live spellings and this install serves both at once:
      legacy  ["sampler_name": [[...choices...], {...opts...}]]  - stock KSampler
      v3      ["sampler_name": ["COMBO", {"options": [...], ...}]] - RES4LYF's
    Handling only one silently yields an empty dropdown for the other, which is
    indistinguishable from "ComfyUI is not running" at the UI.
    """
    if not isinstance(spec, list) or not spec:
        return []
    head = spec[0]
    if isinstance(head, list):
        return [str(v) for v in head]
    meta = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    options = meta.get("options")
    return [str(v) for v in options] if isinstance(options, list) else []


async def refresh_comfy_nodes(ttl=300):
    """Which node classes this ComfyUI actually has. Used to hide features whose
    custom-node pack is missing instead of failing at queue time."""
    now = time.time()
    if _COMFY_NODES["names"] is not None and now - _COMFY_NODES["at"] < ttl:
        return _COMFY_NODES["names"]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{COMFY}/object_info", timeout=30) as r:
                data = await r.json(content_type=None)
        if isinstance(data, dict) and data:
            # python_module is ComfyUI's own record of which pack defined each
            # node ("custom_nodes.ComfyUI-KJNodes") - live attribution for the
            # compat report, so installed packs never need a hand-kept list.
            modules = {name: str(info.get("python_module") or "")
                       for name, info in data.items() if isinstance(info, dict)}
            # The sampler/scheduler combo lists for the classes a saved style is
            # allowed to tune. Read from the live install rather than hardcoded:
            # RES4LYF's ClownsharKSampler_Beta takes compound names
            # ("linear/euler", "bong_tangent") that a stock KSampler rejects, and
            # both lists grow whenever a node pack is updated.
            enums = {}
            for cls in {seat["class"] for seat in SAMPLER_SEATS.values()}:
                required = ((data.get(cls) or {}).get("input") or {}).get("required") or {}
                picked = {}
                for field in ("sampler_name", "scheduler"):
                    choices = _combo_choices(required.get(field))
                    if choices:
                        picked[field] = choices
                if picked:
                    enums[cls] = picked
            _COMFY_NODES.update(at=now, names=frozenset(data), modules=modules,
                                enums=enums)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, json.JSONDecodeError):
        pass                                   # comfy down - keep the last answer
    return _COMFY_NODES["names"]


# ------------------------------------------------------------- compat report
# The green dot's hover card: which node packs this ComfyUI setup gives Pixal.
# Names only, no URLs - ComfyUI-Manager finds every one of these by name.
#
# Attribution order matters. object_info's python_module SHOULD be the live
# truth, but a pack whose __init__ does `from nodes import *` (seen in the
# wild: comfyui_fearnworksnodes) exposes the GLOBAL registry as its own
# NODE_CLASS_MAPPINGS, and ComfyUI re-stamps every node loaded before it as
# that pack's. So node families whose home pack is fixed and never-core are
# attributed by NAME first; python_module covers the rest.
_PACK_NODE_NAMES = (
    ("H3Multishot",              "ComfyUI-H3-Multishot"),
    ("PiD",                      "ComfyUI-PiD"),
    ("DenoRTXVFX",               "Deno RTX VFX"),
    ("RTXVideoSuperResolution",  "NVIDIA RTX Video"),
    ("VHS_",                     "ComfyUI-VideoHelperSuite"),
    ("Clown",                    "RES4LYF"),
    ("GGUF",                     "ComfyUI-GGUF"),
    ("easy ",                    "ComfyUI-Easy-Use"),
    ("rgthree",                  "rgthree-comfy"),
    ("KJ",                       "ComfyUI-KJNodes"),
    ("UltimateSDUpscale",        "ComfyUI_UltimateSDUpscale"),
)
# For ABSENT nodes only - families that live in core on a current ComfyUI
# (LTX moved into comfy_extras) but have a pack worth naming when missing.
_MISSING_PACK_HINTS = (
    ("LTX",                      "ComfyUI-LTXVideo"),
    ("Krea2Edit",                "a Krea 2 edit pack"),
)


def _pack_of(node, installed_module):
    """Display name of the pack a node belongs to (or should come from)."""
    for needle, pack in _PACK_NODE_NAMES:
        if needle in node:
            return pack
    if installed_module:
        parts = installed_module.split(".")
        if parts[0] == "custom_nodes" and len(parts) > 1:
            return parts[1]
        return "ComfyUI core"
    for needle, pack in _MISSING_PACK_HINTS:
        if needle in node:
            return pack
    return "ComfyUI core"        # core node missing = ComfyUI itself is too old


def _pixal_node_wants():
    """Every node class Pixal can queue: the template library plus the graphs
    built in code (H3 multishot, PiD, RTX video upscale)."""
    wanted = set()
    for graph in TEMPLATES.values():
        wanted.update(n["class_type"] for n in graph.values()
                      if isinstance(n, dict) and n.get("class_type"))
    wanted.update((H3_MULTISHOT_NODE, H3_MULTISHOT_MEMORY_NODE,
                   PID_UPSCALE_NODE, PID_DECODE_NODE, *VIDEO_UPSCALE_NODES))
    return wanted


async def comfy_compat(_req):
    """The compatibility report behind the status dot: every node class Pixal
    can queue, grouped by the pack that provides it, checked against what this
    ComfyUI actually has loaded."""
    names = await refresh_comfy_nodes()
    modules = _COMFY_NODES["modules"]
    version = ""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{COMFY}/system_stats", timeout=10) as r:
                stats = await r.json(content_type=None)
        version = str((stats.get("system") or {}).get("comfyui_version") or "")
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
            json.JSONDecodeError, AttributeError):
        pass
    wanted = _pixal_node_wants()
    # The video upscalers are alternatives - either satisfies the feature, so
    # with one installed the other is not a gap worth reporting.
    if names and any(n in names for n in VIDEO_UPSCALE_NODES):
        wanted -= {n for n in VIDEO_UPSCALE_NODES if n not in names}
    packs = {}
    for node in sorted(wanted):
        ok = bool(names) and node in names
        pack = _pack_of(node, modules.get(node, "") if ok else "")
        entry = packs.setdefault(pack, {"name": pack, "nodes": [],
                                        "core": pack == "ComfyUI core"})
        entry["nodes"].append({"name": node, "ok": ok})
    for entry in packs.values():
        entry["ok"] = all(n["ok"] for n in entry["nodes"])
    return web.json_response({
        "ok": True,
        "connected": HUB.comfy_up,
        "probed": names is not None,   # False only before first contact ever
        "version": version,
        "comfy_url": COMFY,
        "packs": sorted(packs.values(),
                        key=lambda p: (p["core"], p["name"].lower())),
        "manager": await manager_state(),
        "pixal_version": PIXAL_VERSION,
        "pixal_channel": PIXAL_CHANNEL,
    })


# ------------------------------------------------------- ComfyUI-Manager
# ComfyUI SHIPS Manager. As of 0.32.0 it is a pip package (comfyui_manager in
# site-packages), started by main.py, serving its API under /v2/ - and nodes.py
# actively BLOCKS any separately installed copy in custom_nodes:
#
#   if args.enable_manager:
#       if comfyui_manager.should_be_disabled(module_path):
#           logging.info(f"Blocked by policy: {module_path}")
#
# So Pixal must never install it. Cloning it into custom_nodes produces a
# folder that looks installed, logs "Blocked by policy" once at boot, and never
# answers - which is indistinguishable from a broken install unless you read
# the log. This module only ever DETECTS, and the one thing it can usefully
# report is a stray clone that someone (me, 2026-08-17) put there.
#
# The probe is a real Manager route rather than a version string: the old
# standalone pack answered /api/manager/version, the built-in one does not, and
# guessing wrong reads as "not installed" forever.
MANAGER_DIR = "ComfyUI-Manager"
MANAGER_PROBE = "/v2/manager/queue/status"


def manager_path():
    return CDIR / "custom_nodes" / MANAGER_DIR


async def manager_api_live(timeout=4):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{COMFY}{MANAGER_PROBE}", timeout=timeout) as r:
                return r.status == 200
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False


async def manager_state():
    live = await manager_api_live() if HUB.comfy_up else False
    # A clone in custom_nodes is dead weight once the built-in one is running.
    # Worth naming so it can be deleted, never worth installing.
    stray = manager_path().is_dir()
    return {
        "live": live,
        "stray": stray and live,
        "probe": MANAGER_PROBE,
        # Manager is not optional and not installable: it arrives with ComfyUI.
        # Absent means the ComfyUI is older than the one Pixal targets.
        "too_old": HUB.comfy_up and not live,
    }


async def manager_status(_req):
    return web.json_response({"ok": True, "manager": await manager_state()})



def lora_title(path):
    """Real model title from the safetensors header metadata, not the filename."""
    try:
        with open(path, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            if n > 200_000_000:
                return None
            h = json.loads(f.read(n))
        m = h.get("__metadata__", {})
        for k in ("modelspec.title", "title", "ss_output_name", "sshs_name",
                  "modelspec.name", "name"):
            v = m.get(k)
            if v and isinstance(v, str):
                return v.strip()
    except Exception:
        pass
    return None

@lru_cache(maxsize=512)
def _lora_title_cached(path_text, mtime_ns, size):
    """lora_title memoized by (path, mtime, size): a titleless file is retried
    the moment it changes, and costs one header read per process until then."""
    return lora_title(path_text)

def _lora_title_map(rels):
    """rel -> embedded safetensors title for each rel, disk-cached.

    The cache persists HITS ONLY. An earlier build stored a null title as a
    PRESENT key, which pinned every titleless LoRA forever - never re-read
    until somebody deleted the cache by hand (162 sit sticky on the real box).
    A miss is now retried on every pass - memoized per process by mtime, so
    the retry is free until the file actually changes - and never written back.
    """
    try:
        titles = json.loads(_LORA_TITLE_CACHE.read_text(encoding="utf-8")) \
            if _LORA_TITLE_CACHE.exists() else {}
    except Exception:
        titles = {}
    dirty = False
    out = {}
    for rel in rels:
        title = titles.get(rel)
        if title is None:                        # absent, or a legacy null
            for root in model_roots():
                p = root / "loras" / rel
                if p.is_file():
                    try:
                        st = p.stat()
                        title = _lora_title_cached(str(p), st.st_mtime_ns,
                                                   st.st_size)
                    except OSError:
                        title = None
                    break
            if title:
                titles[rel] = title
                dirty = True
            elif rel in titles:
                del titles[rel]                  # drop the sticky null
                dirty = True
        out[rel] = title
    if dirty:
        try:
            _LORA_TITLE_CACHE.write_text(
                json.dumps({r: t for r, t in titles.items() if t},
                           ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return out

_MODEL_TITLE_CACHE = {}

def model_embedded_title(rel, kind):
    """modelspec.title straight from the checkpoint's safetensors header - the
    same fallback loras get, so a finetune Civitai never matched still shows
    its real name. Header-only read (8 bytes + the json), cached by mtime."""
    for root in model_roots():
        p = root / kind / rel
        if p.is_file():
            try:
                mtime = p.stat().st_mtime_ns
            except OSError:
                return None
            hit = _MODEL_TITLE_CACHE.get(str(p))
            if hit and hit[0] == mtime:
                return hit[1]
            title = lora_title(p)
            _MODEL_TITLE_CACHE[str(p)] = (mtime, title)
            return title
    return None


def _prettify_stem(stem):
    """Readable spacing for a filename nobody titled: underscore and camelCase
    splits, acronyms and vNN version tokens kept whole. Display only - it is
    never written anywhere, so a future real title simply replaces it."""
    s = re.sub(r"[_\-.]+", " ", str(stem))
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[a-uw-z])(?=\d)", " ", s)
    return " ".join(w if (len(w) > 1 and not w.islower()) else w.capitalize()
                    for w in s.split())


# --------------------------------------------------------------- lora-manager
# ComfyUI-Lora-Manager (custom node on :8188) owns the Civitai story: hashes,
# real model names, trigger words, previews. We read its list API into a TTL
# cache and merge per-file; everything degrades to embedded-metadata titles
# when the node (or ComfyUI) is down.
_LM = {"at": 0.0, "by_rel": {}, "models_by_rel": {}}

async def _lm_list(s, prefix):
    items, page = [], 1
    while True:
        async with s.get(f"{COMFY}/api/lm/{prefix}/list",
                         params={"page": page, "page_size": 500},
                         timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status != 200:
                return None                          # node absent
            d = await r.json()
        items += d.get("items") or []
        if page >= (d.get("total_pages") or 1):
            break
        page += 1
    return items

def _lm_index(items, marker):
    """items -> {path-relative-to-<marker>-folder: item} (backslash keys)."""
    out = {}
    for it in items or []:
        fp = (it.get("file_path") or "").replace("/", "\\")
        i = fp.lower().rfind(marker)
        if i >= 0:
            out[fp[i + len(marker):]] = it
    return out

async def refresh_lm_cache(ttl=60):
    if time.time() - _LM["at"] < ttl:
        return
    try:
        async with aiohttp.ClientSession() as s:
            loras = await _lm_list(s, "loras")
            if loras is None:
                return                               # node absent - keep stale
            # "checkpoints" covers diffusion_models too (sub_type diffusion_model)
            ckpts = await _lm_list(s, "checkpoints")
        _LM.update(at=time.time(),
                   by_rel=_lm_index(loras, "\\loras\\"),
                   models_by_rel=_lm_index(ckpts, "\\diffusion_models\\"))
    except Exception:
        pass                                          # comfy down - degrade

def lm_enrich(rel, entry):
    """Fold one Lora-Manager record into an options() lora entry."""
    lm = _LM["by_rel"].get(rel)
    if not lm:
        return
    civ = lm.get("civitai") or {}
    name = (lm.get("model_name") or "").strip()
    # model_name is the filename until Civitai matches (or the user renames) -
    # only prefer it over embedded metadata when it actually says something.
    if name and (civ or name != Path(rel).stem):
        entry["title"] = name
    pv = lm.get("preview_url") or ""
    if pv:
        # relative previews ride the sidecar proxy - an absolute :8188 URL is
        # unreachable from a phone or a Tailscale viewer (only :8190 is exposed)
        entry["thumb"] = pv if pv.startswith("http") else f"/api/comfy{pv}"
    bm = lm.get("base_model")
    if bm and bm != "Unknown":
        entry["base"] = bm
    words = civ.get("trainedWords") or []
    if words:
        entry["words"] = words[:8]
    if civ.get("modelId"):
        entry["civitai_url"] = f"https://civitai.com/models/{civ['modelId']}"

# ------------------------------------------------------- civitai (by hash)
# Lora-manager only names files IT has matched. For the rest - a model added a
# minute ago, or one delisted from Civitai - Pixal asks directly: sha256 the
# file (cached by size+mtime; these are 10-30GB), hit Civitai's by-hash API,
# and fall back to CivArchive's stable /sha256/<hash> page, whose <title> and
# og:image carry the common name and thumbnail for delisted models. Results
# (and misses) persist in _civitai_models.json so a file is hashed once ever.
_CIVITAI_CACHE = HERE / "_civitai_models.json"
_CIV = {"data": None, "busy": False}
_CIV_MISS_RETRY = 7 * 86400

def _civ_data():
    if _CIV["data"] is None:
        try:
            _CIV["data"] = json.loads(_CIVITAI_CACHE.read_text(encoding="utf-8"))
        except Exception:
            _CIV["data"] = {}
        # Self-heal records an earlier, laxer CivArchive parse let through: the
        # hash-mirror page ("<file> - SHA256 mirrors", banner.webp cover) is not
        # a model hit. Demoted to a plain miss; the sha256 is kept.
        for rec in _CIV["data"].values():
            hit = rec.get("hit") or {}
            if hit.get("source") == "civarchive" and \
                    re.search(r"sha256", hit.get("name", ""), re.I):
                rec.pop("hit", None)
    return _CIV["data"]

def _civ_key(kind, rel):
    """Cache key for one catalog file. Diffusion models keep the bare-rel keys
    the cache shipped with; every other kind namespaces, so a LoRA and a
    checkpoint that share a filename never share a record."""
    return rel if kind == "diffusion_models" else kind + "\\" + rel

def _civ_hit(rel, kind="diffusion_models"):
    return (_civ_data().get(_civ_key(kind, rel)) or {}).get("hit") or {}

def _civ_persist(data):
    """Per record: a 20GB hash is too expensive to lose to a mid-sweep
    restart, and the file is a few KB."""
    try:
        _CIVITAI_CACHE.write_text(json.dumps(data, ensure_ascii=False),
                                  encoding="utf-8")
    except Exception:
        pass

def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()

async def _civitai_by_hash(s, sha):
    """-> ("hit", data) | ("miss", None) | ("error", None). Never raises."""
    try:
        async with s.get("https://civitai.com/api/v1/model-versions/by-hash/" + sha,
                         timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status == 404:
                return "miss", None
            if r.status != 200:
                return "error", None
            v = await r.json()
    except Exception:
        return "error", None
    name = ((v.get("model") or {}).get("name") or "").strip()
    if not name:
        return "miss", None
    img = next((i for i in v.get("images") or []
                if (i.get("type") or "image") == "image"), None)
    return "hit", {"name": name, "version": (v.get("name") or "").strip(),
                   "thumb": (img or {}).get("url") or "",
                   "base": v.get("baseModel") or "", "source": "civitai"}

async def _civarchive_by_hash(s, sha):
    """Scrape-light fallback: page <title> is 'Name - Type by author - CivArchive'
    and og:image is the gallery cover. No JSON API exists (checked 2026-08-18)."""
    try:
        async with s.get("https://civarchive.com/sha256/" + sha,
                         timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status != 200:
                return "miss", None
            html = (await r.text(errors="replace"))[:300_000]
    except Exception:
        return "error", None
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = (m.group(1) if m else "").strip()
    title = re.sub(r"\s*-\s*CivArchive\s*$", "", title)
    # An unknown hash still renders a page - "<file> - SHA256 mirrors" - so a
    # real hit is ONLY a title in the model-page shape "Name - Type by author".
    m = re.match(r"(.+?)\s+-\s+[^-]+\s+by\s+\S+\s*$", title)
    if not m or re.search(r"sha256", title, re.I):
        return "miss", None
    name = m.group(1).strip()
    img = re.search(r'(?:property|name)="og:image"[^>]*content="([^"]+)"', html) or \
          re.search(r'content="([^"]+)"[^>]*(?:property|name)="og:image"', html)
    thumb = img.group(1) if img else ""
    if "banner" in thumb.lower():
        thumb = ""                            # the site's own banner, not a cover
    return "hit", {"name": html_mod.unescape(name), "version": "",
                   "thumb": thumb, "base": "", "source": "civarchive"}

# A local sidecar always wins (brief 9.19b): a LoRA with <stem>.jpeg/.png or
# <stem>.metadata.json beside it already has its cover and its declared base,
# so the by-hash pass leaves it entirely alone - no hash, no network call.
_LORA_SIDECAR_IMAGE_SUFFIXES = (".jpeg", ".png")

def _lora_sidecar_cover(p):
    """The cover image sitting beside a LoRA file, or None."""
    for suffix in _LORA_SIDECAR_IMAGE_SUFFIXES:
        cover = p.with_suffix(suffix)
        if cover.is_file():
            return cover
    return None

def _lora_has_sidecar(p):
    return _lora_sidecar_cover(p) is not None or \
        p.with_suffix(".metadata.json").is_file()

def _active_base_families():
    """Families of installed models a render can actually run. The picker only
    ever asks about these, so they bound what the LoRA by-hash pass scans:
    415 LoRAs are not hashed eagerly - a LoRA whose family nothing installed
    can use is a family the picker never shows, and costs nothing."""
    fams = set()
    for kind in ("diffusion_models", "unet"):
        for e in model_catalog(kind):
            if not e["rel"].lower().endswith((".safetensors", ".gguf")):
                continue
            profile = model_profile(e["rel"], e["kind"])
            if profile["supported"]:
                fams.add(profile["family"])
    return fams

async def _civ_lookup_one(s, data, kind, rel, p):
    """One file through the by-hash pass; True when the cache changed.

    Freshness keys on size+mtime, the record carries the sha256, and a miss is
    remembered for _CIV_MISS_RETRY so the obscure ones are not re-queried
    every scan. The content-addressed escape hatch: these exact bytes may
    already be known under another name - a rename, or a twin downloaded twice
    (krea2filterbypass.safetensors and its '2vector' twin are the same file).
    The new name's first pass rehashes (cheap for a LoRA), finds the twin's
    record by sha, and adopts it, hit or miss, with no network call."""
    try:
        st = p.stat()
    except OSError:
        return False
    key = _civ_key(kind, rel)
    rec = data.get(key)
    fresh = bool(rec) and rec.get("size") == st.st_size and \
        abs(rec.get("mtime", 0) - st.st_mtime) < 2
    if fresh and (rec.get("hit") or
                  time.time() - rec.get("checked", 0) < _CIV_MISS_RETRY):
        return False
    sha = rec.get("sha256") if fresh else None
    if not sha:
        sha = await asyncio.get_running_loop().run_in_executor(None, _sha256_of, p)
    donor = next((r for k, r in data.items()
                  if k != key and r.get("sha256") == sha), None)
    if donor:
        hit = donor.get("hit")
        if hit or time.time() - donor.get("checked", 0) < _CIV_MISS_RETRY:
            data[key] = {"size": st.st_size, "mtime": st.st_mtime,
                         "sha256": sha, "checked": donor.get("checked", 0),
                         **({"hit": dict(hit)} if hit else {})}
            _civ_persist(data)
            return True
    status, hit = await _civitai_by_hash(s, sha)
    if status == "miss":
        status, hit = await _civarchive_by_hash(s, sha)
    if status == "error":
        return False                      # network trouble - retry next scan
    data[key] = {"size": st.st_size, "mtime": st.st_mtime,
                 "sha256": sha, "checked": time.time(),
                 **({"hit": hit} if hit else {})}
    _civ_persist(data)
    return True

async def refresh_civitai_meta():
    """Name and thumbnail whatever lora-manager left unmatched - diffusion
    models, and (brief 9.19b) the LoRAs in play. Runs after a catalog scan;
    hashes off the event loop; tells the UI to refetch options once at the
    end only if anything actually changed. The LoRA pass is lazy: a sidecar
    wins outright, a family no installed model can run is never hashed, and
    what remains - the active families and the unknowns the pass exists to
    classify - is hashed once ever and cached by content."""
    if _CIV["busy"]:
        return
    _CIV["busy"] = True
    changed = False
    try:
        data = _civ_data()
        async with aiohttp.ClientSession(
                headers={"User-Agent": "Pixal (github.com/pixal)"}) as s:
            for e in model_catalog("diffusion_models"):
                rel = e["rel"]
                lm = _LM["models_by_rel"].get(rel) or {}
                if lm.get("model_name") and lm.get("preview_url"):
                    continue                      # lora-manager already owns it
                p = Path(e["root"]) / "diffusion_models" / rel
                if await _civ_lookup_one(s, data, "diffusion_models", rel, p):
                    changed = True
            active = _active_base_families()
            for e in model_catalog("loras"):
                rel = e["rel"]
                p = Path(e["root"]) / "loras" / rel
                if _lora_has_sidecar(p):
                    continue                      # local cover + metadata win
                family = lora_profile(rel)["family"]
                if family != "unknown":
                    if family not in active:
                        continue                  # not a family in play
                    lm = _LM["by_rel"].get(rel) or {}
                    if lm.get("model_name") and lm.get("preview_url"):
                        continue                  # lora-manager already covers it
                # Unknowns are scanned even when lora-manager owns the cover:
                # its base_model never reaches lora_profile, and the by-hash
                # record is the only rank-2 wire into the family table.
                if await _civ_lookup_one(s, data, "loras", rel, p):
                    changed = True
    finally:
        _CIV["busy"] = False
    _sync_by_hash_base_models()
    if changed:
        # done+no-totals refetches options client-side without a banner
        HUB.broadcast(type="scan", text=None, done=True, totals=None)

def _lora_entry_extras(entry, rel):
    """Pixal's own by-hash record and any local sidecar cover for one picker
    LoRA, applied after lora-manager's record. Local always wins over the
    network: a sidecar jpeg/png is the cover (and suppressed the by-hash
    lookup entirely); the CivitAI/CivArchive hit is the floor for name, cover
    and declared base. Nothing here fetches or hashes - it reads what
    refresh_civitai_meta already landed."""
    own_civ = _civ_hit(rel, "loras")
    if not entry.get("title"):
        md = adjacent_metadata("loras", rel)
        name = (md.get("model_name") or own_civ.get("name") or "").strip()
        if name:
            entry["title"] = name
    if "thumb" not in entry:
        for root in model_roots():
            p = root / "loras" / rel
            if p.is_file():
                cover = _lora_sidecar_cover(p)
                if cover:
                    # Rides the existing lora-manager preview proxy - an
                    # absolute path under a model root is exactly what
                    # _preview_path_ok allowlists.
                    entry["thumb"] = ("/api/comfy/api/lm/previews?path=" +
                                      urllib.parse.quote(str(cover)))
                break
    if "thumb" not in entry and own_civ.get("thumb"):
        entry["thumb"] = own_civ["thumb"]
    if "base" not in entry and own_civ.get("base"):
        entry["base"] = own_civ["base"]

def lora_catalog():
    """Every LoRA on disk: relpath + real title + model family, cached to disk."""
    root = CDIR / "models" / "loras"
    if not root.is_dir():
        return []
    files = sorted(root.rglob("*.safetensors"))
    titles = _lora_title_map([str(p.relative_to(root)) for p in files])
    out = []
    for p in files:
        rel = str(p.relative_to(root))
        group = p.relative_to(root).parts[0] if len(p.relative_to(root).parts) > 1 else "(root)"
        out.append({"name": rel, "title": titles.get(rel),
                    "short": base(rel), "group": group,
                    "krea2": group in ("Krea 2", "(root)")})
    out.sort(key=lambda l: (not l["krea2"], l["group"].lower(),
                            (l["title"] or l["short"]).lower()))
    return out

# ----------------------------------------------------------------------------- graph builders
# Builders clone known-good API graphs and patch only explicit recipe inputs.
# Creative recipes and runtime model families stay separate so a model can never
# be silently inserted into an incompatible CLIP/VAE/latent pipeline.

def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:36] or "shot"

ASPECTS = ["1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)",
           "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)",
           "21:9 (Ultrawide)"]   # ResolutionSelector's combo, verified against /object_info

ZIMAGE_CLIP = "qwen_3_4b.safetensors"
ZIMAGE_CLIP_CANDIDATES = (
    ZIMAGE_CLIP,
    "Qwen\\qwen_3_4b.safetensors",
    "Qwen3-4B.i1-Q5_K_S.gguf",
    "Qwen\\Qwen3-4B.i1-Q5_K_S.gguf",
    "Qwen\\qwen-4b-zimage-hereticV2-q8.gguf",
    "Qwen\\Josiefied-Qwen3-4B-abliterated-v2.Q8_0.gguf",
)
ZIMAGE_VAE = "ae.safetensors"
ZIMAGE_VAE_CANDIDATES = (
    ZIMAGE_VAE,
    "ZImage\\ZiB_ae.safetensors",
    "Flux\\ae.safetensors",
)
ZIMAGE_ANIME_VAE = "ZImage\\zImageClearVae_natural.safetensors"

# Anima: a 2B Cosmos-Predict2-derived anime model on a Qwen3-0.6B BASE text
# encoder and the Qwen-Image VAE. Every value below is ported from ComfyUI's own
# shipped blueprint, "Text to Image (Anima Base 1.0)" - it is a natively
# supported architecture (comfy/ldm/anima, supported_models.Anima), not a
# community graph. The one value no filename would tell you is the CLIPLoader
# type: "stable_diffusion", not any qwen type.
#
# Do NOT add a ModelSamplingAuraFlow shift node. supported_models.Anima already
# declares sampling_settings {"multiplier": 1.0, "shift": 3.0}, which is exactly
# what ModelSamplingAuraFlow(shift=3.0) patches in - Pixal carried that node for
# one commit until an A/B on a fixed seed came back PIXEL-identical with and
# without it. The blueprint has no shift node either.
ANIMA_CLIP = "Anima\\qwen_3_06b_base.safetensors"
ANIMA_VAE_CANDIDATES = ("Qwen-Image\\Qwen_Image_VAE.safetensors",
                        "Qwen-Image\\qwen_image_vae.safetensors",
                        "qwen_image_vae.safetensors")
# The model card's own prompt scaffolding. Anima trains on Danbooru tags, natural
# language, and combinations - Pixal writes prose, so the quality tags lead and
# the scene follows. NOT a substitute for a real tag lane; it is the documented
# minimum that keeps a prose scene from landing on an untagged prior.
ANIMA_QUALITY_TAGS = "masterpiece, best quality, score_7"
ANIMA_NEGATIVE = ("worst quality, low quality, score_1, score_2, score_3, "
                  "artist name, blurry, jpeg artifacts, chromatic aberration")
# Anima is uncensored and its prior leans hard that way: a fully-dressed brief
# came back in underwear, and a negative alone did not hold it (tested, twice).
# What works is the same thing the fineporn base needs - a wardrobe clause in
# the LAST position - with a tag echo up front where this model reads best, and
# the negative behind both. nsfw=True is the user asking, and lifts all three.
ANIMA_SFW_NEGATIVE = "nsfw, nude, topless, underwear, lingerie, ass focus"
ANIMA_SFW_TAGS = "fully clothed"
# "Use at CFG 1 and 8-12 steps" for turbo; 30-50 steps at CFG 4-5 for the rest.
ANIMA_SETTINGS = {"base": {"steps": 30, "cfg": 4.0},
                  "turbo": {"steps": 10, "cfg": 1.0}}


def zimage_vae_candidates(settings):
    """The profile's VAE list, with the user's chosen decoder in front of it.

    Z-Image and Flux share a VAE, so drop-in replacements like UltraFlux exist and
    genuinely sharpen output - but they can over-sharpen on a single pass, and the
    author's own advice is to use them on a second pass after upscaling. That is a
    taste call on finished work, so it is opt-in rather than an automatic upgrade.
    The clear-anime profile ships its own matched VAE and is left alone."""
    chosen = str(load_config().get("vae", {}).get("zimage") or "").strip()
    base = tuple(settings["vae_candidates"])
    if not chosen or base == (ZIMAGE_ANIME_VAE,):
        return base
    chosen = chosen.replace("/", "\\")
    return (chosen,) + tuple(name for name in base if name.lower() != chosen.lower())
FANTASY_LORA = "ZImage\\Base\\DnDPainterlyCleanZBase.safetensors"
# Structural for the whole Krea 2 family, not one recipe's taste: every krea2
# graph that samples runs it as the first locked stage, whichever checkpoint is
# selected. It was named REALISM_II_LORA back when Realism II was the only
# recipe carrying it.
# The CivitAI download name, verbatim (Krea2FilterBypass, model 2728234,
# version "2vector" = 3066812, "This modifies 2 vectors of the affected
# layer"). It was filed on this box as krea2filterbypass2vector.safetensors -
# a local rename, byte-identical by sha256 - and every OTHER machine has it
# under the name CivitAI ships. Naming the download is what lets a fresh
# install find it; see _catalog_has for the folder half of the same problem.
KREA_BYPASS_LORA = "Krea 2\\krea2filterbypass.safetensors"
# The variant every render to date used (CivitAI model 2728234, version
# "2vector" = 3066812, "This modifies 2 vectors of the affected layer"). The
# 3vector sibling (3067151) moves one more. This default is what keeps an
# untouched composer byte-identical (brief 9.15).
KREA_BYPASS_VECTORS = 2
REALISM_LORA = "Krea 2\\RealisticSnapshotKrea2.safetensors"
# r128 export: half the file, likeness indistinguishable from full-rank in the
# 2026-08-11 face-off (same seed, same ref, bf16 encoder).
IDENTITY_LORA = "Krea 2\\krea2_identity_edit_v1_2_r128.safetensors"
# v1.2 numbers, from the LoRA's own notes and the installed node's schema. The
# builder had kept v1's 1536 after the weights moved to v1.2, whose trained range
# is 384-768 - the notes call running far above it the most common cause of
# duplicated/split compositions. ref_boost is v1.2's likeness dial and the node
# defaults it to 1.0, meaning off, so it has to be set to do anything.
IDENTITY_GROUNDING_PX = 768
IDENTITY_REF_BOOST = 4.0
# The composer recipe-card extender's dials for Identity Edit (brief 9.14), in
# the LoRA author's own ranges (the model card at huggingface.co/conradlocke/
# krea2-identity-edit): ref_boost is "the fidelity dial" - "~4 is a strong-
# likeness starting point", below 1 "loosens toward creative freedom", above
# 10 "starts breaking removals". grounding_px's trained range is 384-768 with
# 768 the default; the card allows that 1024 "often still works", so the UI
# range runs higher - with the failure signature named on the dial, since it
# is the one a user will actually hit. "key" IS the build_zara_edit parameter,
# so submit's SIGS filter is the gate keeping dials off every other recipe's
# graph. A later recipe declares its own list in RECIPE_SPECS and the same
# plumbing carries it: validation, the re-roll and the extender all read the
# declaration. A saved style carrying dials is deliberately OUT of scope - the
# composer sends them itself, and _apply_opts applies them over the style's
# file exactly like the composer's LoRA stack.
IDENTITY_DIALS = [
    {"key": "ref_boost", "label": "Likeness",
     "min": 0.0, "max": 10.0, "step": 0.1, "default": IDENTITY_REF_BOOST,
     "help": ("How hard the edit holds the reference. ~4 is a strong-likeness "
              "start; below 1 loosens toward creative freedom; above 10 starts "
              "breaking removals.")},
    {"key": "grounding", "label": "Grounding",
     "min": 384, "max": 1536, "step": 64, "default": IDENTITY_GROUNDING_PX,
     "help": ("Lower = stronger edit adherence, higher = stronger identity. "
              "Trained range 384-768. Duplicated or split compositions mean "
              "lower it.")},
]

# The bypass A/B (brief 9.15): the same extender, a choice dial rather than a
# number. "key" IS the build_zara_edit parameter, exactly like the dials
# above; "choices_from" names the scan that fills the live options at
# /api/options time, so only INSTALLED variants are ever offered. The value
# is the vector count itself, read out of each patch's tensor - never the
# filename, which this box proves lies (the authoritative 2-vector is
# krea2filterbypass.safetensors, no digit in the name). Declared on
# identity_edit so identity and bypass advanced controls live in one place;
# any recipe with a vector_bypass stage can declare it and the same plumbing
# (validation, re-roll, extender) carries it.
BYPASS_VARIANT_DIAL = {"key": "bypass_variant", "kind": "choice",
                       "choices_from": "vector_bypass",
                       "label": "Bypass", "default": KREA_BYPASS_VECTORS,
                       "help": ("How many vectors of the text-fusion projector the "
                                "bypass moves. 2 is what every render so far used; "
                                "3 is the stronger CivitAI variant.")}


def recipe_dial_value(dial, value):
    """One declared dial on the way in: a finite in-range number passes,
    coerced the way the builder coerces so the stored spec says what ran;
    anything else lands on the recipe constant. Degrades, never dies - None,
    bool, non-numeric and out-of-range all fall back rather than raise, the
    same policy as reroll's canvas block."""
    if dial.get("choices_from"):
        return _recipe_choice_value(dial, value)
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) \
            or value < dial["min"] or value > dial["max"]:
        return dial["default"]
    return int(value) if isinstance(dial["default"], int) else float(value)


def _recipe_dials_payload(spec):
    """The extender's declared dials, with choice dials carrying their LIVE
    options: the scan runs here so only installed variants are ever offered
    (brief 9.15) - never a variant that would fail at queue time. The choice
    label is the count itself ("2-vector"), keyed on the tensor, and `name`
    is the loader-listed rel the graph will actually load."""
    out = []
    for dial in spec.get("dials", []):
        d = dict(dial)
        if d.get("choices_from") == "vector_bypass":
            d["choices"] = [{"value": count, "label": f"{count}-vector",
                             "name": rel}
                            for count, rel in sorted(vector_bypass_variants().items())]
        out.append(d)
    return out


def _recipe_choice_value(dial, value):
    """A declared choice passes only when it names an INSTALLED option - the
    control never offers what would fail at queue time, so a value that
    arrives anyway (a stale composer, a file deleted since /api/options)
    lands on the default rather than raising. The default itself always
    passes: it names the authored stage, which runs exactly as it always has.
    Same degrade-never-die policy as the number dials."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value != int(value):
        return dial["default"]
    value = int(value)
    if value == dial["default"]:
        return value
    installed = vector_bypass_variants() \
        if dial["choices_from"] == "vector_bypass" else {}
    return value if value in installed else dial["default"]
# New Face repaints the whole frame, so its cap IS the output size - there is
# nothing underneath to composite back over. Matched to the edit lane's ceiling
# because it is the same Krea 2 sampler at the same resolutions.
FACE_MINT_MP_CAP = 2.0
FACE_MINT_STEPS = 16
IDENTITY_STYLE_LORA = "Krea 2\\RawGirlV3.safetensors"
KREA_CLIP_REALISM = "Qwen\\qwen3-vl-4b-heretic_nvfp4.safetensors"
# fp8_scaled keeps the VISION tower bf16 (the part that reads the identity
# ref) and quantizes only the text stack - likeness-identical to the full bf16
# build in the 2026-08-11 encoder face-off, at 4.9GB instead of 8.3GB.
KREA_CLIP_EDIT = "Qwen\\qwen3vl_4b_fp8_scaled.safetensors"
KREA_VAE_REALISM = "Qwen-Image\\qwenImageVAESharpKrea2_fp32.safetensors"
KREA_VAE_WAN = "Wan\\Wan2_1_VAE_fp32.safetensors"

# Qwen-Image-Edit is an instruction editor, not a text-to-image recipe: it always
# consumes a finished frame. Its conditioning stack is the non-VL Qwen 2.5 VL 7B
# encoder loaded as `qwen_image` - the Krea/Z-Image encoders are the wrong stack.
# 2511, not the original release: dated refreshes from 2509 on take the
# TextEncodeQwenImageEditPlus path that set_qwen_edit_encoder switches to on its
# own, so the default moves without any other change here.
QWEN_EDIT_MODEL = "Qwen\\qwen-image-edit-2511-Q6_K.gguf"
QWEN_EDIT_CLIP = "Qwen\\qwen_2.5_vl_7b_fp8_scaled.safetensors"
QWEN_EDIT_VAE = "Qwen-Image\\Qwen_Image_VAE.safetensors"
QWEN_EDIT_MP = 1.0        # the 1 MP working resolution Qwen-Image-Edit expects
QWEN_EDIT_MP_RANGE = (0.25, 4.0)
# Edits default to the source's own size (see build_qwen_edit) so a finished frame
# survives a round trip; this is the ceiling that applies when it is larger.
QWEN_EDIT_MP_CAP = 2.0
# The official qwen-image-edit-2511-4steps workflow: the *base* Qwen-Image
# Lightning V2 distillation (the workflow's own note prefers it over the
# Edit-2511-specific LoRA) at full strength, cfg 1.0, shift 3.1.
QWEN_EDIT_LIGHTNING_LORA = "Qwen\\Qwen-Image-Lightning-4steps-V2.0.safetensors"
QWEN_EDIT_LIGHTNING = {"steps": 4, "cfg": 1.0, "shift": 3.1, "strength": 1.0}

# FireRed-Image-Edit: a third-party Qwen-Image-Edit derivative. It shares the
# encoder contract, the 2.5-VL text encoder and the Qwen-Image VAE, but it is a
# different transformer with its own accelerator. Ported from the official
# firered-image-edit-1.1 workflow, whose "use the acceleration LoRA" boolean
# switches both halves at once: on = the 8-step LoRA at strength 1.0, 8 steps,
# cfg 1.0; off = no LoRA, 40 steps, cfg 4.0. Shift is 3.1 on both branches.
FIRERED_EDIT_LORA = "Qwen\\FireRed-Image-Edit-1.1-Lightning-8steps-v1.2.safetensors"

# One row per edit transformer LINE, most specific first. A step-distillation is
# trained against one set of weights, so it is not a portable "go faster" switch:
# Qwen's 4-step Lightning on FireRed's transformer does not error, it quietly
# ruins the edit. Pairing the accelerator to the model by name is what prevents
# that, and it is why the Settings speed control reads its options from here
# rather than offering a bare step count.
EDIT_ACCELERATORS = (
    {"id": "firered", "tokens": ("firered",),
     "label": "FireRed 8-step Lightning",
     "lora": FIRERED_EDIT_LORA, "lora_tokens": ("firered", "8steps"),
     # FireRed carries no YYMM date but is a Plus-encoder model, so it cannot be
     # recognised by the date rule that covers the Qwen line.
     "plus_encoder": True,
     "turbo": {"steps": 8, "cfg": 1.0, "shift": 3.1, "strength": 1.0},
     "full": {"steps": 40, "cfg": 4.0, "shift": 3.1}},
    # The Qwen line itself, and the fall-through for any compatible release:
    # empty tokens match everything, so this row must stay last.
    {"id": "qwen", "tokens": (),
     "label": "Qwen-Image Lightning 4-step V2",
     "lora": QWEN_EDIT_LIGHTNING_LORA,
     "lora_tokens": ("qwen-image-lightning", "4steps"),
     "plus_encoder": None,          # decided by the release date - see below
     "turbo": dict(QWEN_EDIT_LIGHTNING),
     "full": {"steps": 20, "cfg": 2.5, "shift": 3.0}},
)

# FLUX.2 Klein 9B: the masked-inpaint lane. Graph ported from the F4 group of
# geoahmed's flux2_klein_ultimate_v2.1 workflow. Klein is step-distilled, so
# 4 steps at cfg 1.0 is its native schedule, not a speed hack. License is
# the FLUX Non-Commercial License v2.1 - surface it like PiD's, never ship it
# silently.
# int8 convrot over bf16 at Jesse's call (2026-08-12 same-seed A/B: parity
# quality, his pick, ~9GB lighter and faster). The bf16 stays on disk.
KLEIN_MODEL = "Flux\\flux-2-klein-9b_int8_convrot.safetensors"
KLEIN_CLIP = "Qwen\\qwen_3_8b_fp8mixed_abliterated.safetensors"
KLEIN_VAE = "Flux\\flux2-vae.safetensors"
# The sampling canvas is capped even though the OUTPUT stays native. This graph
# VAE-encodes the source TWICE (masked latent + full-frame reference latent), so
# an edit on an upscaled frame prices at double the canvas - a 4x upscale asked
# for a single 17.09GB allocation and took ComfyUI down with it (job 7f4d20e2,
# 2026-08-16). Klein is a 1-2MP model; sampling above that buys nothing it was
# trained to use. ki:back scales the decode to exact native and ki:comp lays it
# over the untouched original, so unmasked pixels stay bit-identical at full
# size and only the edited region pays the round trip.
KLEIN_INPAINT_MP_CAP = 2.0
KLEIN_INPAINT_STEPS = 16          # flux2 VAE is /16; keep both sides legal

# Qwen-Image is the text-to-image line (Qwen-Image, Qwen-Image-2512), separate
# from the Qwen-Image-Edit line above. It shares the 2.5-VL encoder and the VAE.
QWEN_IMAGE_MODEL = "Qwen\\qwen_image_2512_fp8_e4m3fn.safetensors"
QWEN_IMAGE_SHIFT = 3.1
QWEN_IMAGE_CFG = 4.0
QWEN_IMAGE_STEPS = 20

ZIMAGE_EXECUTION_PROFILES = {
    "zimage_base": {
        "clip_candidates": ZIMAGE_CLIP_CANDIDATES, "clip_type": "lumina2",
        "vae_candidates": ZIMAGE_VAE_CANDIDATES,
        "sampler_graph": "ksampler", "steps": 25,
        "cfg": 4.0, "sampler": "res_multistep", "scheduler": "simple",
        "shift": 3.0, "zero_negative": False,
    },
    "zimage_turbo_v4": {
        "clip_candidates": ZIMAGE_CLIP_CANDIDATES, "clip_type": "lumina2",
        "vae_candidates": ZIMAGE_VAE_CANDIDATES,
        "sampler_graph": "amazing_v4", "steps": 8,
        "cfg": 1.0, "sampler": "euler", "zero_negative": True,
    },
    "zimage_clear_anime": {
        "clip_candidates": ZIMAGE_CLIP_CANDIDATES, "clip_type": "lumina2",
        "vae_candidates": (ZIMAGE_ANIME_VAE,),
        "sampler_graph": "ksampler", "steps": 12,
        "cfg": 1.0, "sampler": "euler", "scheduler": "beta",
        "shift": 6.0, "zero_negative": True,
    },
}

# Public creative recipes are deliberately separate from runtime graph families.
# "anime" is a creative direction; "zimage" is the compatible execution stack.
# That separation prevents the old failure mode where any selected UNET was
# blindly inserted into Krea 2's CLIP/VAE/latent graph.
RECIPE_SPECS = {
    "realism": {
        "label": "Realism", "tag": "fast · ~10s", "family": "krea2",
        # Analog Madness is the daily driver (Jesse, 2026-08-15) - the same
        # checkpoint Realism II already defaults to, so the two passes of the
        # same creative direction now open on the same look instead of
        # changing model underneath the user at "Refined".
        "default_model": "Krea 2\\analogMadnessKrea2Turbo_v20.safetensors",
        "aspect": "2:3 (Portrait Photo)", "mp": 2.0,
        "required_loras": [KREA_BYPASS_LORA, REALISM_LORA],
        # revision 2 (2026-08-13): vector bypass joined the core, so plans saved
        # against revision 1 are discarded rather than replayed a stage short.
        "lora_stack_revision": 2, "lora_boundary": "sampler",
        "lora_stages": [
            {"slot": "vector_bypass", "name": KREA_BYPASS_LORA, "strength": 1.0,
             "role": "structural", "zone": "core", "order_locked": True,
             # 2026-08-21: core strength opened to the composer. The plan
             # contract already carried core strength overrides; only this flag
             # kept the row read-only. Slots and names are unchanged, so every
             # stored plan still validates - the revision stays put.
             "strength_editable": True, "removable": False,
             "active_by_default": True},
            {"slot": "realistic_snapshot", "name": REALISM_LORA, "strength": 1.0,
             "role": "style", "zone": "editable", "order_locked": False,
             "strength_editable": True, "removable": True,
             "active_by_default": True},
        ],
        "required_text_encoders": [KREA_CLIP_REALISM],
        "required_vaes": [KREA_VAE_REALISM],
    },
    "realism_ii": {
        "label": "Realism II", "tag": "two-pass + 2× finish", "family": "krea2",
        # Selfora was retired for quality (2026-08-11); Analog Madness int8
        # ConvRot is the proven daily driver from the same family.
        "default_model": "Krea 2\\analogMadnessKrea2Turbo_v20.safetensors",
        "aspect": "9:16 (Portrait Widescreen)", "mp": 2.11,
        "required_loras": [KREA_BYPASS_LORA],
        "lora_stack_revision": 1, "lora_boundary": "sampling + finish",
        "lora_stages": [
            {"slot": "vector_bypass", "name": KREA_BYPASS_LORA, "strength": 1.0,
             "role": "structural", "zone": "core", "order_locked": True,
             # 2026-08-21: core strength opened here too, same contract as
             # realism - the server already honoured core strength overrides,
             # so the revision stays put.
             "strength_editable": True, "removable": False,
             "active_by_default": True},
        ],
        "required_text_encoders": [KREA_CLIP_REALISM],
        "required_vaes": [KREA_VAE_WAN],
        "required_upscalers": ["scunet_color_real_gan.pth"],
    },
    "fantasy": {
        "label": "Fantasy", "tag": "painterly · Z-Image Base", "family": "zimage",
        "variants": ["base"],
        "default_model": "ZiB\\z_image_bf16.safetensors",
        "aspect": "1:1 (Square)", "mp": 1.05,
        "required_loras": [FANTASY_LORA],
        "lora_stack_revision": 1, "lora_boundary": "sampler",
        "lora_stages": [
            {"slot": "painterly", "name": FANTASY_LORA, "strength": 0.9,
             "role": "style", "zone": "editable", "order_locked": False,
             "strength_editable": True, "removable": True,
             "active_by_default": True},
        ],
    },
    "anime": {
        "label": "Anime", "tag": "clear anime · 12 steps", "family": "zimage",
        "variants": ["base"],
        "default_model": "ZiB\\Z-Image_clear_anime_BF16.safetensors",
        "aspect": "1:1 (Square)", "mp": 1.05,
        "required_vaes": [ZIMAGE_ANIME_VAE],
        "lora_stack_revision": 1, "lora_boundary": "sampler", "lora_stages": [],
    },
    "zimage": {
        "label": "Z-Image", "tag": "base + turbo aware", "family": "zimage",
        "default_model": "ZiT\\z_image_turbo_bf16.safetensors",
        "aspect": "1:1 (Square)", "mp": 1.05,
        "lora_stack_revision": 1, "lora_boundary": "sampler", "lora_stages": [],
    },
    "identity_edit": {
        "label": "Identity Edit", "tag": "anchor's face · ~40s", "family": "krea2",
        "default_model": "Krea 2\\krea2_turbo_int8_convrot.safetensors",
        # The identity patch grafts onto model weights; on GGUF tensors it
        # killed the ComfyUI process outright - no traceback, log just stops
        # (gonzalomo, 2026-08-11). Safetensors builds only until proven otherwise.
        "no_gguf": True,
        "aspect": "9:16 (Portrait Widescreen)", "mp": 2.36,
        "required_loras": [KREA_BYPASS_LORA, IDENTITY_LORA],
        # The recipe-card extender's advanced dials (Likeness, Grounding) plus
        # the bypass variant A/B (brief 9.15). Declared here so intake
        # validation, the re-roll and /api/options all read one declaration;
        # the defaults ARE the recipe's own numbers, so an untouched composer
        # renders exactly what it did before the dials became reachable.
        "dials": IDENTITY_DIALS + [BYPASS_VARIANT_DIAL],
        "lora_stack_revision": 1, "lora_boundary": "identity patch",
        "lora_stages": [
            {"slot": "vector_bypass", "name": KREA_BYPASS_LORA, "strength": 1.0,
             "role": "structural", "zone": "core", "order_locked": True,
             # 2026-08-21: core strength opened to the composer; the plan
             # contract already carried the override, so no revision bump.
             "strength_editable": True, "removable": False,
             "active_by_default": True},
            {"slot": "identity_edit", "name": IDENTITY_LORA, "strength": 1.0,
             "role": "structural", "zone": "core", "order_locked": True,
             # 2026-08-21: same unlock as the bypass above - the identity
             # LoRA's strength is user-tunable through the core override map.
             "strength_editable": True, "removable": False,
             "active_by_default": True},
            # RawGirlV3 is a taste call, not structure: the slot stays authored
            # (one tap to bring back, file checked only when used) but the
            # default stack is just the two structural stages above.
            {"slot": "rawgirl", "name": IDENTITY_STYLE_LORA, "strength": 1.0,
             "role": "style", "zone": "editable", "order_locked": False,
             "strength_editable": True, "removable": True,
             "active_by_default": False},
        ],
        "required_text_encoders": [KREA_CLIP_EDIT],
        "required_vaes": [KREA_VAE_WAN],
        "needs_character": True,
    },
    "qwen_edit": {
        "label": "Qwen Image Edit", "tag": "instruction edit · from a finished frame",
        "family": "qwen_edit",
        "default_model": QWEN_EDIT_MODEL,
        "aspect": "", "mp": QWEN_EDIT_MP,
        "lora_stack_revision": 1, "lora_boundary": "sampler", "lora_stages": [],
        "required_text_encoders": [QWEN_EDIT_CLIP],
        "required_vaes": [QWEN_EDIT_VAE],
        "needs_source_image": True,
    },
    "qwen_image": {
        "label": "Qwen Image", "tag": "photographic · Qwen-Image",
        "family": "qwen_image",
        "default_model": QWEN_IMAGE_MODEL,
        "aspect": "2:3 (Portrait Photo)", "mp": 1.5,
        "lora_stack_revision": 1, "lora_boundary": "sampler", "lora_stages": [],
        "required_text_encoders": [QWEN_EDIT_CLIP],
        "required_vaes": [QWEN_EDIT_VAE],
    },
    # A new person, minted from a real photograph. Deliberately carries no
    # LoRA: RealisticSnapshotKrea2 is trained on retouched imagery and cost
    # 12.7 texture points measured against the source photo, which is the
    # whole thing this recipe exists to keep. See build_face_mint.
    "face_mint": {
        "label": "New Face", "tag": "a new person from a photo · ~6s",
        "family": "krea2",
        "default_model": "Krea 2\\finepornV31TURBOFP8_v3FIXFP8.safetensors",
        "aspect": "", "mp": 0,
        "lora_stack_revision": 1, "lora_boundary": "sampler", "lora_stages": [],
        "required_text_encoders": [KREA_CLIP_REALISM],
        "required_vaes": [KREA_VAE_REALISM],
        "needs_source_image": True,
    },
    "klein_inpaint": {
        "label": "Klein Inpaint", "tag": "paint the spot · only that redraws",
        "family": "klein",
        "default_model": KLEIN_MODEL,
        "aspect": "", "mp": 0,
        "lora_stack_revision": 1, "lora_boundary": "sampler", "lora_stages": [],
        "required_text_encoders": [KLEIN_CLIP],
        "required_vaes": [KLEIN_VAE],
        "needs_source_image": True,
    },
    # Anima has one graph and no style/quality variants, like qwen_image: the
    # model IS the style. 896x1152 is the workflow's own canvas.
    "anima": {
        "label": "Anima", "tag": "anime illustration - 30 steps", "family": "anima",
        "default_model": "Anima\\anima-base-v1.0.safetensors",
        "aspect": "3:4 (Portrait Standard)", "mp": 1.03,
        "required_text_encoders": [ANIMA_CLIP],
        "lora_stack_revision": 1, "lora_boundary": "sampler", "lora_stages": [],
    },
}
PUBLIC_RECIPE_IDS = tuple(RECIPE_SPECS)
# Recipes the composer must never offer as a creative style: they have no
# text-to-image path and are reachable only from a finished frame.
SOURCE_ONLY_RECIPE_IDS = frozenset(
    rid for rid, spec in RECIPE_SPECS.items() if spec.get("needs_source_image"))

_SIDECAR_META = {}

def adjacent_metadata(kind, rel):
    """Best-effort Lora-Manager sidecar metadata for one installed asset."""
    key = (kind, str(rel).lower())
    if key in _SIDECAR_META:
        return _SIDECAR_META[key]
    out = {}
    for root in model_roots():
        p = root / kind / rel
        mp = p.with_suffix(".metadata.json")
        if not mp.is_file():
            continue
        try:
            out = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            out = {}
        break
    _SIDECAR_META[key] = out
    return out

# One family table, read by both classifiers (brief 9.19a). It lives beside
# install/catalog.json so it stays next to the installer's own notion of what
# a family is. A family is data - an id, the baseModel strings that map to it,
# its folder-name hints, its variant rule - and adding one is adding a row,
# never a new elif. model_profile and lora_profile both resolve through these
# rows, so the two can no longer drift (the model ladder once knew six
# families, the LoRA ladder two, and 172 of 415 LoRAs classified unknown by
# construction).
FAMILY_TABLE = json.loads((HERE / "install" / "families.json")
                          .read_text(encoding="utf-8"))["families"]

# 9.19b hook: CivitAI baseModel strings keyed by lowercased lora rel, filled
# by the by-hash fetch. Resolution rank 2 of 4 - after the sidecar, before
# the safetensors header. A mapping only; nothing here fetches or hashes.
BY_HASH_BASE_MODEL = {}

def _sync_by_hash_base_models():
    """Rebuild the 9.19b hook from the by-hash cache: lowercased lora rel ->
    the baseModel its sha256 resolved to. Reads the cache only - the fetching
    and hashing already happened (or didn't) in refresh_civitai_meta."""
    BY_HASH_BASE_MODEL.clear()
    for key, rec in _civ_data().items():
        if not key.startswith("loras\\"):
            continue
        base = str((rec.get("hit") or {}).get("base") or "").strip()
        if base:
            BY_HASH_BASE_MODEL[key[6:].replace("/", "\\").lower()] = base

def _family_row_by_base_model(bml):
    """First table row claiming a lowered declared-base string, or None."""
    if bml:
        for row in FAMILY_TABLE:
            if any(token in bml for token in row.get("base_model", ())):
                return row
    return None

def _family_row_by_path(low):
    """First table row claiming a lowered rel path, or None."""
    for row in FAMILY_TABLE:
        if any(low.startswith(p) for p in row.get("path_prefix", ())):
            return row
        if any(token in low for token in row.get("path_contains", ())):
            return row
        if any(all(token in low for token in group)
               for group in row.get("path_contains_all", ())):
            return row
    return None

def _family_variant(row, low, bml, consumer):
    """A row's variant for one consumer ("model"/"lora")."""
    fixed = row.get("variant")
    if isinstance(fixed, dict):
        return fixed.get(consumer, "any")
    if fixed:
        return fixed
    for rule in row.get("variants", ()):
        if any(token in bml for token in rule.get("base_model", ())):
            return rule["id"]
        if any(low.startswith(p) for p in rule.get(f"{consumer}_path_prefix", ())):
            return rule["id"]
        if any(token in low for token in rule.get(f"{consumer}_path_contains", ())):
            return rule["id"]
    return (row.get("variant_default") or {}).get(consumer, "any")

def family_row(family):
    """The table row for a family id, or None. lora_stack's variant gate reads
    the variants a family gates on from here instead of naming the family."""
    for row in FAMILY_TABLE:
        if row["id"] == family:
            return row
    return None

# Training metadata a safetensors header carries about its own base, most
# specific first - measured against the real library: modelspec.architecture
# ("krea2/lora", "flux-2/lora"), ss_base_model_version ("krea2",
# "flux2_klein_9b"), base_model ("krea-community/Krea-2-Turbo"),
# lora_base_model (usually just "dit" - harmless, it matches no row).
_LORA_HEADER_BASE_KEYS = ("modelspec.architecture", "ss_base_model_version",
                          "base_model", "lora_base_model")
_LORA_HEADER_MAX_BYTES = 4 * 1024 * 1024

@lru_cache(maxsize=256)
def _lora_header_base_model(path_text, mtime_ns, size):
    """Base-model hints from a LoRA's own safetensors header, or "".

    Resolution rank 3 of 4: more trustworthy than the folder the file sits
    in, less than its sidecar or by-hash record. Only the header span is
    read - a few KB off the front of the file, cached by (path, mtime, size).
    """
    try:
        with Path(path_text).open("rb") as f:
            span = struct.unpack("<Q", f.read(8))[0]
            if span > _LORA_HEADER_MAX_BYTES:
                return ""
            header = json.loads(f.read(span))
    except (OSError, ValueError, struct.error):
        return ""
    meta = header.get("__metadata__") if isinstance(header, dict) else None
    if not isinstance(meta, dict):
        return ""
    return " ".join(str(meta[k]) for k in _LORA_HEADER_BASE_KEYS if k in meta).lower()

def _lora_header_declared_base(rel):
    """The header hint of the FIRST installed copy of a lora rel, or ""."""
    for root in model_roots():
        p = root / "loras" / rel
        try:
            st = p.stat()
        except OSError:
            continue
        if p.suffix.lower() == ".safetensors":
            return _lora_header_base_model(str(p), st.st_mtime_ns, st.st_size)
        return ""
    return ""

def model_profile(rel, kind="diffusion_models"):
    """Classify an installed diffusion file without loading its multi-GB weights."""
    rel = str(rel).replace("/", "\\")
    low = rel.lower()
    md = adjacent_metadata(kind, rel)
    base_model = str(md.get("base_model") or (md.get("civitai") or {}).get("baseModel") or "")
    bml = base_model.lower()
    # Family is the table's business now (brief 9.19a): the declared base
    # first, then the path - the branches below the table are only the
    # markers no recipe accepts (flux/video/audio/auxiliary) and unknown.
    row = _family_row_by_base_model(bml) or _family_row_by_path(low)
    if row:
        family = row["id"]
        variant = _family_variant(row, low, bml, "model")
        media, supported, reason = "image", True, ""
    elif low.startswith("flux\\") or "flux" in bml:
        family, variant, media, supported = "flux", "image", "image", False
        reason = "Flux needs its own Pixal pipeline"
    elif low.startswith(("ltx", "minimax h3\\")):
        family, variant, media, supported = "video", "video", "video", False
        reason = "video model"
    elif "melband" in low:
        family, variant, media, supported = "audio", "audio", "audio", False
        reason = "audio model"
    elif "pid_" in low or low.startswith("nvidia_pid\\"):
        family, variant, media, supported = "auxiliary", "auxiliary", "auxiliary", False
        reason = "auxiliary model, not a standalone image generator"
    else:
        family, variant, media, supported = "unknown", "unknown", "unknown", False
        reason = "no compatible Pixal pipeline yet"
    profile = {"family": family, "variant": variant, "media": media,
               "supported": supported, "reason": reason,
               "base_model": base_model or None,
               "format": Path(rel).suffix.lower().lstrip(".")}
    # Supported, but only reachable from a finished frame - the composer's
    # creative model picker must not offer it as a text-to-image choice.
    if row and row.get("source_only"):
        profile["source_only"] = True
    if family == "zimage":
        profile["execution_profile"] = \
            "zimage_turbo_v4" if variant == "turbo" else "zimage_base"
    if family == "anima":
        profile["execution_profile"] = f"anima_{variant}"
    # This Base/Turbo merge ships its own measured schedule and VAE. Filename-
    # specific profiles win over broad family defaults.
    if low.endswith("zib\\z-image_clear_anime_bf16.safetensors"):
        profile.update(profile_id="clear_anime", variant="base",
                       execution_profile="zimage_clear_anime")
    return profile

# Krea2FilterBypass ships as sibling CivitAI versions that differ ONLY in how
# many vectors of the text-fusion projector they move - "2vector" (model
# 2728234, version 3066812) and "3vector" (3067151). The names are one
# character apart and people rename them on the way in; this box had the
# 2vector filed as krea2filterbypass2vector.safetensors for weeks. The FILE is
# the honest answer: a single [1, N] F32 tensor whose non-zero count IS the
# version, so the explorer reads the patch instead of trusting a filename.
# At 160 bytes that is free - and it is only ever attempted on files small
# enough to BE one of these patches, never on a real multi-hundred-MB LoRA.
_VECTOR_PATCH_MAX_BYTES = 64 * 1024
_VECTOR_PATCH_SUFFIX = ".txtfusion.projector.diff"


@lru_cache(maxsize=256)
def _vector_patch_count(path_text, mtime_ns, size):
    """Vectors a projector-patch LoRA moves, or None if it is not one."""
    if size > _VECTOR_PATCH_MAX_BYTES:
        return None
    try:
        raw = Path(path_text).read_bytes()
        span = struct.unpack("<Q", raw[:8])[0]
        header = json.loads(raw[8:8 + span])
    except (OSError, ValueError, struct.error):
        return None
    if not isinstance(header, dict):
        return None
    for key, meta in header.items():
        # __metadata__ is safetensors' own header slot, not a tensor; and a
        # patch file may name its tensor for any target layer, so match the
        # projector suffix rather than the full key.
        if key == "__metadata__" or not str(key).endswith(_VECTOR_PATCH_SUFFIX):
            continue
        if not isinstance(meta, dict) or meta.get("dtype") != "F32":
            return None
        try:
            first, last = meta["data_offsets"]
            body = raw[8 + span + first:8 + span + last]
            values = struct.unpack("<%df" % (len(body) // 4), body)
        except (KeyError, TypeError, ValueError, struct.error):
            return None
        return sum(1 for v in values if v != 0.0) or None
    return None


@lru_cache(maxsize=256)
def _vector_patch_sha(path_text, mtime_ns, size):
    """sha256 of a projector patch - 160 bytes, so this is free, and it is
    what tells a byte-identical twin apart from a genuinely different patch
    that happens to move the same number of vectors."""
    if size > _VECTOR_PATCH_MAX_BYTES:
        return None
    try:
        return hashlib.sha256(Path(path_text).read_bytes()).hexdigest()
    except OSError:
        return None


def vector_bypass_variants():
    """Installed projector patches as {vectors: catalog rel} (brief 9.15).

    The tensor is the identity, never the filename: this box's authoritative
    2-vector is `Krea 2\\krea2filterbypass.safetensors` - no digit anywhere in
    the name - and its byte-identical twin spent weeks filed next to it as
    krea2filterbypass2vector.safetensors. So the LoRA catalog is scanned for
    projector patches and each one's count read out of its own tensor; two
    files with the same count AND the same sha256 are ONE option, never two.
    Within one count the lowest-sorting rel represents the option (on this box
    that is the authored name itself, which sorts ahead of its `2vector`
    twin). Deliberately uncached: the catalog scan behind it carries a 30s
    TTL, and the per-file work is cached by (path, mtime, size) above, so a
    freshly downloaded variant appears on the next catalog refresh.
    """
    found = {}
    for entry in model_catalog("loras"):
        try:
            patch_file = Path(entry["root"]) / entry["kind"] / entry["rel"]
            stat = patch_file.stat()
        except (KeyError, TypeError, OSError):
            continue
        count = _vector_patch_count(str(patch_file), stat.st_mtime_ns,
                                    stat.st_size)
        if not count:
            continue
        sha = _vector_patch_sha(str(patch_file), stat.st_mtime_ns, stat.st_size)
        # The dedupe the whole control keys on: same count, same bytes -> one
        # option. Same count, DIFFERENT bytes is not a thing the two-way
        # control can express; the lowest-sorting rel stands for the count.
        found.setdefault((count, sha), entry["rel"])
    out = {}
    for (count, _sha), rel in sorted(found.items(),
                                     key=lambda item: (item[0][0], item[1].lower())):
        out.setdefault(count, rel)
    return out


def lora_profile(rel):
    # Two different jobs, two different forms, and conflating them cost a
    # silent Linux defect. The backslash form is Pixal's INTERNAL identity for
    # a LoRA - it is what `low` matches folder hints against and what
    # BY_HASH_BASE_MODEL is keyed by, deliberately stable across platforms.
    # It is NOT a path: on Linux "Krea 2\probe.safetensors" is one filename
    # with a backslash in it, so reading the header with it found nothing,
    # fell through to the folder hint, and classified a Klein LoRA as krea2 -
    # looking for all the world like a classifier bug. Touch the disk with
    # the native form.
    rel = str(rel).replace("/", "\\")
    low = rel.lower()
    native = rel.replace("\\", os.sep)
    md = adjacent_metadata("loras", native)
    sidecar = str(md.get("base_model") or (md.get("civitai") or {}).get("baseModel") or "")
    by_hash = str(BY_HASH_BASE_MODEL.get(low) or "")
    # Resolution order, most trustworthy first (brief 9.19a): the sidecar's
    # declared base, then the by-hash record (9.19b), then the file's own
    # safetensors header, and only then the folder it happens to sit in -
    # nobody downloading from CivitAI inherits our folder layout.
    row, declared = None, ""
    for candidate in (sidecar, by_hash):
        row = _family_row_by_base_model(candidate.lower())
        if row:
            declared = candidate
            break
    if not row:
        header = _lora_header_declared_base(native)
        row = _family_row_by_base_model(header)
        if row:
            declared = header
    if not row:
        row = _family_row_by_path(low)
    if not row:
        return {"family": "unknown", "variant": "any",
                "base_model": (sidecar or by_hash) or None, "supported": False}
    return {"family": row["id"],
            "variant": _family_variant(row, low, declared.lower(), "lora"),
            "base_model": (sidecar or by_hash or declared) or None,
            "supported": True}

def compatible_recipes(profile):
    out = []
    for rid, spec in RECIPE_SPECS.items():
        if profile.get("family") != spec["family"]:
            continue
        variants = spec.get("variants")
        if variants and profile.get("variant") not in variants:
            continue
        out.append(rid)
    return out


def recipe_model_candidates(recipe_id):
    """Installed diffusion models that can execute one creative recipe.

    Recipes own intent; this resolver owns plumbing. The authored default stays
    preferred, but a release install is not disabled merely because the user's
    compatible checkpoint has a different filename.
    """
    out, seen = [], set()
    for kind in ("diffusion_models", "unet"):
        for raw in model_catalog(kind):
            key = raw["rel"].replace("/", "\\").lower()
            if key in seen:
                continue
            seen.add(key)
            # nvidia_pid/ holds PiD's DECODER weights (auto-downloaded by the
            # ComfyUI-PiD pack). Name-wise they read as qwen_image family, but
            # they are not generation models - as a fallback candidate one
            # would be silently loaded as a UNet and render garbage.
            if key.startswith("nvidia_pid\\"):
                continue
            entry = {**raw, **model_profile(raw["rel"], raw["kind"])}
            if recipe_id not in compatible_recipes(entry):
                continue
            if RECIPE_SPECS[recipe_id].get("no_gguf") and \
                    entry["rel"].lower().endswith(".gguf"):
                continue
            out.append(entry)
    return sorted(out, key=lambda entry: entry["rel"].lower())

CANVAS_MULTIPLE = 16          # latent 8x with a 2x patch: 16 is the real grid
# Shape is a choice off a list; megapixels is a budget. Weighting the ratio
# error this much above the area error means an exactly-correct aspect wins
# whenever it is anywhere near the requested size, and loses only when holding
# it would cost real resolution (16:9 cannot be exact without a ~10% jump).
CANVAS_RATIO_WEIGHT = 6.0


def dims_for(aspect, mp, multiple=CANVAS_MULTIPLE):
    """aspect string + megapixels -> (w, h), both multiples of `multiple`.

    The height is derived from the SNAPPED width, not the ideal one. Rounding
    each axis independently off the unsnapped ideal let them drift apart and
    put up to 0.7% of shape error into the ratio - 3:4 at 2 MP came out
    1232x1632, which is not 3:4. Candidates either side of the ideal are then
    scored, so a width one step over that lands the ratio exactly is preferred
    to one that merely lands the area.
    """
    aw, ah = (float(x) for x in aspect.split(" ")[0].split(":"))
    ratio = aw / ah
    target = max(0.0, float(mp)) * 1_000_000
    step = max(1, int(multiple))
    if target <= 0 or ratio <= 0:
        return step, step
    # Half-UP, not Python's bankers rounding: the composer mirrors this function
    # in JS, where Math.round is half-up, and 4:3 lands on an exact .5 often
    # enough that round() would hand the two a different canvas.
    snap = lambda v: math.floor(v + 0.5)
    centre = max(1, snap((target * ratio) ** 0.5 / step))
    best = None
    for offset in range(-3, 4):
        w = (centre + offset) * step
        if w < step:
            continue
        h = max(step, snap(w / ratio / step) * step)
        score = (abs(w * h - target) / target
                 + CANVAS_RATIO_WEIGHT * abs((w / h) - ratio) / ratio)
        key = (round(score, 12), -(w * h))    # ties go to the larger canvas
        if best is None or key < best[0]:
            best = (key, w, h)
    return int(best[1]), int(best[2])

def base(name):
    return re.sub(r"\.(safetensors|gguf|ckpt|pt|pth|bin)$", "",
                  str(name).split("\\")[-1].split("/")[-1], flags=re.I)


def resolve_lora(nm):
    """Trust no LLM-suggested lora name: map it onto a real file (exact rel path,
    else unique basename match) or None. A hallucinated name spliced into the graph
    makes ComfyUI 'succeed' with zero outputs - the silent no-output trap."""
    rels = [e["rel"] for e in model_catalog("loras")]
    low = str(nm).strip().replace("/", "\\").lower()
    for r in rels:
        if r.lower() == low:
            return r
    bl = low.rsplit("\\", 1)[-1]
    if not bl.endswith(".safetensors"):
        bl += ".safetensors"
    hits = [r for r in rels if r.lower().rsplit("\\", 1)[-1] == bl]
    return hits[0] if len(hits) == 1 else None

def resolve_model_entry(nm):
    """Resolve a model name and preserve kind/format/family instead of returning
    a path string that can be inserted into the wrong loader."""
    entries = [e for k in ("diffusion_models", "unet", "checkpoints")
               for e in model_catalog(k)]
    low = str(nm).strip().replace("/", "\\").lower()
    for e in entries:
        if e["rel"].lower() == low:
            return {**e, **model_profile(e["rel"], e["kind"])}
    bl = low.rsplit("\\", 1)[-1]
    has_ext = any(bl.endswith(ext) for ext in MODEL_EXTS)
    hits = [e for e in entries if e["rel"].lower().rsplit("\\", 1)[-1] == bl or
            (not has_ext and base(e["rel"]).lower() == bl)]
    return ({**hits[0], **model_profile(hits[0]["rel"], hits[0]["kind"])}
            if len(hits) == 1 else None)

def pick_recipe_model(requested, recipe_id):
    spec = RECIPE_SPECS[recipe_id]
    wanted = requested or spec["default_model"]
    entry = resolve_model_entry(wanted)
    if not requested and not entry:
        candidates = recipe_model_candidates(recipe_id)
        entry = candidates[0] if candidates else None
        if entry:
            wanted = entry["rel"]
    if not entry:
        if requested:
            raise ValueError(f"{spec['label']} model is not installed: {wanted}")
        raise ValueError(f"{spec['label']} needs an installed compatible "
                         f"{spec['family']} diffusion model")
    if entry["kind"] not in ("diffusion_models", "unet"):
        raise ValueError(f"{base(wanted)} is a checkpoint; this recipe needs a diffusion model/UNET")
    if entry["family"] != spec["family"]:
        raise ValueError(f"{base(wanted)} is {entry['family']}, but {spec['label']} needs "
                         f"{spec['family']}")
    if spec.get("no_gguf") and entry["rel"].lower().endswith(".gguf"):
        raise ValueError(f"{spec['label']} cannot run GGUF models - the identity "
                         "patch crashes ComfyUI on GGUF weights. Use a "
                         "safetensors build of this model instead")
    variants = spec.get("variants")
    if variants and entry["variant"] not in variants:
        raise ValueError(f"{spec['label']} uses Z-Image {', '.join(variants)} models; "
                         f"{base(wanted)} is {entry['variant']}")
    return entry

def set_unet_loader(graph, node_id, entry):
    """Patch the correct loader class for safetensors/ckpt-style UNETs vs GGUF."""
    rel = entry["rel"]
    if rel.lower().endswith(".gguf"):
        graph[node_id] = {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": rel}}
    else:
        graph[node_id] = {"class_type": "UNETLoader",
                          "inputs": {"unet_name": rel, "weight_dtype": "default"}}

def lora_compatible(rel, family=None, variant=None, lp=None):
    """The ONE LoRA-vs-profile compatibility rule, shared by lora_stack (build
    time) and the add-LoRA popup (pick time). The picker used to restate it in
    JS, and once the rule became table-driven (9.19a) the two copies were one
    families.json row from drifting apart - the picker promising what the
    sampler then drops. Returns None when compatible, else a short reason code
    the picker turns into words: "unknown" (family never identified - it will
    not render), "family" (made for another family), "variant" (right family,
    wrong build - Z-Image's base/turbo gate)."""
    lp = lp or lora_profile(rel)
    # Unknown architecture is not neutral. A stale localStorage choice or
    # hallucinated cloud tool argument must never reach an arbitrary graph.
    if family and lp["family"] != family:
        return "unknown" if lp["family"] == "unknown" else "family"
    # The variant gate is the family row's own data: Z-Image's row declares
    # base/turbo, and a turbo LoRA never reaches a base graph.
    row = family_row(family)
    gated = {rule["id"] for rule in (row or {}).get("variants", ())}
    if variant in gated and lp["variant"] not in ("any", variant):
        return "variant"
    return None

# Every profile the add-LoRA popup can take, as "family:variant" keys: "any"
# plus the variants each family actually distinguishes. options() ships the
# predicate's verdict for every one of them per LoRA, so the popup looks its
# verdict up instead of restating the rule in JS (9.19d).
_LORA_PROFILE_VARIANTS = {"unknown": ("any",)}
for _row in FAMILY_TABLE:
    _vs = {"any"} | {rule["id"] for rule in _row.get("variants", ())}
    _fixed = _row.get("variant")
    _vs.update(_fixed.values() if isinstance(_fixed, dict)
               else [_fixed] if _fixed else [])
    _LORA_PROFILE_VARIANTS[_row["id"]] = tuple(sorted(_vs))
_LORA_PROFILE_KEYS = tuple(f"{fam}:{v}" for fam, vs in _LORA_PROFILE_VARIANTS.items()
                           for v in vs)
del _row, _vs, _fixed


def lora_stack(loras, baked=(), family=None, variant=None):
    """Parse ['name:strength', ...] into [(real_rel, strength)], dropped names aside.
    Dedupes: the same lora twice keeps the LAST strength, and anything already baked
    into the template graph is skipped - chaining a lora twice doubles its deltas
    (the anchor recipe's pinned strength wins over a composer re-pick)."""
    dropped, seen = [], {}
    baked_l = {str(b).lower() for b in baked}
    for spec in loras:
        nm, _, st = str(spec).rpartition(":")
        nm, st = (nm or str(spec)), (float(st) if nm else 1.0)
        real = resolve_lora(nm)
        if not real:
            dropped.append(base(nm))
            continue
        # The compatibility call is lora_compatible's alone - the same callable
        # the add-LoRA popup reads its verdicts from, so the picker can never
        # promise what the graph would drop (9.19d).
        if lora_compatible(real, family, variant):
            dropped.append(f"incompatible {base(real)}")
        elif real.lower() not in baked_l:
            key = real.lower()
            # Ordered stacks use the LAST occurrence for both strength and
            # position. Reassigning a dict key alone keeps its first position.
            if key in seen:
                del seen[key]
            seen[key] = (real, st)
    return list(seen.values()), dropped


def _lora_warning_text(warnings):
    """Lane line for LoRAs that never reached the graph. None when clean."""
    warnings = [w for w in (warnings or []) if str(w).strip()]
    if not warnings:
        return None
    return ("*left out of this render:* " + ", ".join(str(w) for w in warnings)
            + " - a name that doesn't match an installed, compatible LoRA "
              "never reaches the graph.")


def _lora_strength(value, label):
    try:
        strength = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid LoRA strength for {label}: {value}") from None
    if not math.isfinite(strength):
        raise ValueError(f"invalid LoRA strength for {label}: {value}")
    return strength


def validate_lora_plan(recipe_id, plan):
    """Validate the versioned UI contract without touching the model catalog."""
    if not isinstance(plan, dict):
        raise ValueError("lora_plan must be an object")
    spec = RECIPE_SPECS[recipe_id]
    if plan.get("version") != 1 or plan.get("mode") != "replace_editable":
        raise ValueError("unsupported lora_plan version or mode")
    if plan.get("recipe") != recipe_id:
        raise ValueError(f"lora_plan is for {plan.get('recipe') or 'unknown'}, not {recipe_id}")
    if plan.get("recipe_revision") != spec["lora_stack_revision"]:
        raise ValueError(f"{spec['label']} LoRA stack changed; refresh recipe options")
    entries = plan.get("entries")
    if not isinstance(entries, list) or len(entries) > 64:
        raise ValueError("lora_plan entries must be an array of at most 64 items")
    editable = {s["slot"]: s for s in spec["lora_stages"] if s["zone"] == "editable"}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"lora_plan entry {i + 1} must be an object")
        slot, name = entry.get("slot"), entry.get("name")
        if bool(slot) == bool(name):
            raise ValueError(f"lora_plan entry {i + 1} needs exactly one of slot or name")
        if slot and slot not in editable:
            raise ValueError(f"LoRA slot is not editable in {spec['label']}: {slot}")
        if "enabled" in entry and not isinstance(entry["enabled"], bool):
            raise ValueError(f"lora_plan entry {i + 1} enabled must be boolean")
        if slot and entry.get("enabled") is False and \
                editable[slot].get("removable") is False:
            raise ValueError(f"LoRA slot cannot be disabled in {spec['label']}: {slot}")
        if "strength" in entry:
            _lora_strength(entry["strength"], slot or name)
    # Core stages are structural, so they are not in the ordered lane - they
    # keep their authored position at the head of the chain. `core` is the
    # override map that lets the user unlock one anyway: turn it off, or run it
    # at a different strength. Absent means "every core stage as authored", so
    # a plan written before this existed still resolves the same way.
    core = {s["slot"]: s for s in spec["lora_stages"] if s["zone"] == "core"}
    overrides = plan.get("core")
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError("lora_plan core must be an object")
        for slot, override in overrides.items():
            if slot not in core:
                raise ValueError(
                    f"LoRA slot is not a core stage in {spec['label']}: {slot}")
            if not isinstance(override, dict):
                raise ValueError(f"lora_plan core.{slot} must be an object")
            if "enabled" in override and not isinstance(override["enabled"], bool):
                raise ValueError(f"lora_plan core.{slot} enabled must be boolean")
            if "strength" in override:
                _lora_strength(override["strength"], slot)
    return plan


def heal_stored_lora_plan(template, spec):
    """Ledger specs outlive recipe revisions. localStorage re-syncs itself on a
    bump; a spec written into history.jsonl cannot, so every card rendered
    before the bump replayed straight into "LoRA stack changed; refresh recipe
    options" and died at 0.0s - 181 Realism cards after the revision 2 bump on
    2026-08-13. A plan that trips ONLY the revision gate is restamped (slots and
    names are revision-independent); anything else is dropped so the render
    falls back to recipe defaults rather than failing outright."""
    plan = spec.get("lora_plan")
    # Video engines and edit graphs carry a differently-shaped plan and are not
    # in RECIPE_SPECS at all - indexing it would KeyError, not ValueError.
    if not isinstance(plan, dict) or template not in RECIPE_SPECS:
        return spec
    try:
        validate_lora_plan(template, plan)
        return spec
    except (ValueError, KeyError):
        pass
    healed = dict(plan)
    healed["recipe_revision"] = RECIPE_SPECS[template]["lora_stack_revision"]
    try:
        validate_lora_plan(template, healed)
        spec["lora_plan"] = healed
    except (ValueError, KeyError):
        spec.pop("lora_plan", None)
    return spec


# ---------------------------------------------------------------- saved styles
#
# A saved style is a recipe the USER authored: one of Pixal's graphs, pinned to
# a model, a LoRA plan and a sampler schedule, under a name of their own. It
# appears in the composer's style picker beside Realism / Anime / Fantasy.
#
# It is DATA, not code - recipes/<id>.json, the same pattern characters/ and
# chats/ already use - because a style is a thing people paste into Discord and
# attach to forum posts. A row in a database is not shareable, so you would end
# up building an export format anyway, at which point the file IS the format.
# The file IS the shareable unit; that is the whole argument for it.
#
# NAMING, because two vocabularies meet here: on disk and in the schema these
# are "recipes" (that is what they will be called in the shared registry). In
# the code they are SAVED_STYLES, because `recipe` already means an entry in
# RECIPE_SPECS - the built-in graph a saved style is BUILT ON, named by its
# `base` field.
RECIPE_DIR = HERE / "recipes"
RECIPE_SCHEMA_VERSION = 1
_STYLE_ID_RE = re.compile(r"[a-z0-9_]{1,64}")

# The graphs a saved style may be built on. Source-only recipes need a finished
# frame and have no text-to-image path of their own, so they have no look to
# bottle and stay out of the style picker. A needs_character recipe (today only
# identity_edit) IS allowed: bottling the look of an Identity Edit run is the
# whole point of "save this style" (Jesse, 2026-08-22). Such a style records
# that it still needs a character anchor, and the composer asks for one instead
# of failing at render time.
STYLE_BASE_IDS = tuple(
    rid for rid, spec in RECIPE_SPECS.items()
    if rid not in SOURCE_ONLY_RECIPE_IDS)

# Which node carries the sampler schedule a saved style may tune, and the class
# that node runs. Only graphs with ONE stable sampler seat are listed: Realism
# II samples three times at three denoise levels, so a single "steps" box would
# be a lie about what runs. The class matters because RES4LYF's
# ClownsharKSampler_Beta takes COMPOUND sampler names ("linear/euler") that a
# stock KSampler would reject - so the editor reads each seat's real options out
# of ComfyUI's own /object_info instead of shipping a guessed list.
SAMPLER_SEATS = {
    "realism":    {"node": "30:51", "class": "ClownsharKSampler_Beta"},
    "fantasy":    {"node": "8", "class": "KSampler"},
    "anime":      {"node": "8", "class": "KSampler"},
    "zimage":     {"node": "8", "class": "KSampler"},
    "anima":      {"node": "8", "class": "KSampler"},
    "qwen_image": {"node": "qi:sampler", "class": "KSampler"},
}
TUNING_KEYS = ("steps", "cfg", "sampler_name", "scheduler", "eta")
# Which of those a seat can actually take, by the node class sitting in it. eta
# is RES4LYF's stochasticity dial and exists ONLY on ClownsharKSampler_Beta - a
# stock KSampler has no such input, and writing one into its inputs is a
# queue-time ComfyUI error landing on the user. Unknown classes get the stock
# four, so a seat added later is conservative until it says otherwise.
_STOCK_TUNING = ("steps", "cfg", "sampler_name", "scheduler")
SEAT_TUNING = {"ClownsharKSampler_Beta": _STOCK_TUNING + ("eta",)}


def seat_tuning_keys(seat):
    """The tuning settings one seat accepts, in TUNING_KEYS order."""
    if not seat:
        return ()
    allowed = SEAT_TUNING.get(seat["class"], _STOCK_TUNING)
    return tuple(key for key in TUNING_KEYS if key in allowed)


def sampler_seat(base_id, model=None):
    """The node a saved style may tune for this base+model pairing, or None.

    The seat is a property of the PAIR, not of the recipe. Z-Image Turbo's
    Amazing v4 profile does not retune the KSampler, it deletes it and builds a
    two-pass schedule out of five sigma nodes (see _build_zimage), so offering a
    steps box on a Turbo build would write into a node that is not in the graph.
    """
    seat = SAMPLER_SEATS.get(base_id)
    if not seat:
        return None
    if RECIPE_SPECS[base_id]["family"] != "zimage":
        return seat
    entry = resolve_model_entry(model) if model else None
    if not entry:
        return None                      # unknown model - cannot promise a seat
    try:
        _profile, settings = _zimage_settings(entry)
    except (ValueError, KeyError):
        return None
    return seat if settings.get("sampler_graph") == "ksampler" else None


def fixed_schedule_reason(base_id, model=None):
    """Why this pairing has no tunable sampler, in a sentence for the editor."""
    if base_id == "realism_ii":
        return ("Realism II samples three times at three denoise levels - that "
                "schedule is what “refined” means, so it is not tunable.")
    if base_id not in SAMPLER_SEATS:
        return f"{RECIPE_SPECS[base_id]['label']} has no tunable sampler."
    if RECIPE_SPECS[base_id]["family"] == "zimage":
        if not (resolve_model_entry(model) if model else None):
            return "Choose an installed model to see its sampler settings."
        return ("Z-Image Turbo runs the Amazing v4 two-stage sigma schedule "
                "instead of a KSampler, so there are no steps to set.")
    return "This model's schedule is fixed."


def sampler_defaults(base_id, model=None):
    """What this pairing samples at today, for the editor's placeholders.

    Read from the same places the builders read: the Z-Image and Anima settings
    tables overwrite their template literals at build time, so quoting the
    template alone would show numbers that never run.
    """
    seat = sampler_seat(base_id, model)
    if not seat:
        return {}
    node = (TEMPLATES.get(base_id) or {}).get(seat["node"], {}).get("inputs", {})
    if RECIPE_SPECS[base_id]["family"] == "zimage":
        _profile, s = _zimage_settings(resolve_model_entry(model))
        return {"steps": s["steps"], "cfg": s["cfg"],
                "sampler_name": s["sampler"], "scheduler": s.get("scheduler", "simple")}
    if base_id == "anima":
        entry = resolve_model_entry(model) or {}
        s = ANIMA_SETTINGS["turbo" if entry.get("variant") == "turbo" else "base"]
        return {"steps": s["steps"], "cfg": s["cfg"],
                "sampler_name": node.get("sampler_name", "er_sde"),
                "scheduler": node.get("scheduler", "simple")}
    return {k: node[k] for k in seat_tuning_keys(seat) if k in node}


def sampler_choices(node_class):
    """sampler_name/scheduler options for one node class, from /object_info.

    Empty when ComfyUI has not been probed yet. An unprobed list must never be
    read as "no valid values", or every style would refuse to save.
    """
    return dict((_COMFY_NODES.get("enums") or {}).get(node_class) or {})


def tuning_overrides(base_id, model, tuning):
    """A style's sampler tuning as builder overrides.

    Empty when the pairing has no seat, which is what makes a style whose model
    was later swapped for a Turbo build degrade to "runs at the recipe's own
    schedule" instead of crashing on a node that is not in the graph.
    """
    seat = sampler_seat(base_id, model)
    if not seat or not tuning:
        return []
    return [{"node": seat["node"], "input": key, "value": tuning[key]}
            for key in seat_tuning_keys(seat) if key in tuning]


def validate_style_tuning(tuning):
    """Shape-check a tuning block: keys, types, ranges. No catalog access.

    Deliberately does NOT check the seat or the enum values - that needs the
    model catalog, which is not warm at boot, and a load-time check against it
    would reject perfectly good styles on the way up. Those checks live in
    check_style_runnable(), which runs when the user SAVES and is present.
    """
    if tuning in (None, {}):
        return {}
    if not isinstance(tuning, dict):
        raise ValueError("tuning must be an object")
    unknown = [k for k in tuning if k not in TUNING_KEYS]
    if unknown:
        raise ValueError(f"unknown tuning setting: {', '.join(sorted(unknown))}")
    out = {}
    if "steps" in tuning:
        try:
            steps = int(tuning["steps"])
        except (TypeError, ValueError):
            raise ValueError(f"steps must be a whole number, got {tuning['steps']!r}") from None
        if not 1 <= steps <= 200:
            raise ValueError(f"steps must be between 1 and 200, got {steps}")
        out["steps"] = steps
    if "cfg" in tuning:
        try:
            cfg = float(tuning["cfg"])
        except (TypeError, ValueError):
            raise ValueError(f"cfg must be a number, got {tuning['cfg']!r}") from None
        if not math.isfinite(cfg) or not 0.0 <= cfg <= 30.0:
            raise ValueError(f"cfg must be between 0 and 30, got {cfg:g}")
        out["cfg"] = cfg
    if "eta" in tuning:
        # Bounds are the node's own declared range, not a guess: RES4LYF
        # declares eta as a float in [-100, 100] (default 0.5). Which seats
        # even HAVE it is check_style_runnable's job - this stays catalog-free.
        try:
            eta = float(tuning["eta"])
        except (TypeError, ValueError):
            raise ValueError(f"eta must be a number, got {tuning['eta']!r}") from None
        if not math.isfinite(eta) or not -100.0 <= eta <= 100.0:
            raise ValueError(f"eta must be between -100 and 100, got {eta:g}")
        out["eta"] = eta
    for key in ("sampler_name", "scheduler"):
        if key not in tuning:
            continue
        value = str(tuning[key] or "").strip()
        if not value:
            raise ValueError(f"{key} cannot be empty")
        if len(value) > 64:
            raise ValueError(f"{key} is longer than 64 characters")
        out[key] = value
    return out


def heal_style_lora_plan(base_id, plan):
    """Validate a saved style's LoRA plan, restamping a stale revision.

    A style FILE outlives recipe revisions: Realism's stack went to revision 2
    on 2026-08-13, and a plan written before that would otherwise be refused
    forever with "LoRA stack changed; refresh recipe options". Slots and names
    are revision-independent, so a plan that trips ONLY the revision gate is
    restamped - the same contract heal_stored_lora_plan gives ledger entries.
    Every other failure keeps its own named reason.
    """
    if not isinstance(plan, dict):
        raise ValueError("lora_plan must be an object")
    try:
        return validate_lora_plan(base_id, plan)
    except ValueError as exc:
        if "refresh recipe options" not in str(exc):
            raise
    return validate_lora_plan(
        base_id, {**plan, "recipe_revision": RECIPE_SPECS[base_id]["lora_stack_revision"]})


def style_slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")[:64]


def validate_saved_style(raw, default_id=""):
    """recipes/*.json record -> a normalized style, or ValueError with a reason.

    Every rejection names what is wrong and what to do. A stranger's file must
    never reach the app as a traceback, and a hand-edited one has to say which
    field to fix.
    """
    if not isinstance(raw, dict):
        raise ValueError("a style must be a JSON object")
    version = raw.get("schema_version")
    if version != RECIPE_SCHEMA_VERSION:
        raise ValueError(f"schema_version {version!r} - this Pixal reads "
                         f"version {RECIPE_SCHEMA_VERSION}")
    name = " ".join(str(raw.get("name") or "").split())
    if not name:
        raise ValueError("the style needs a name")
    if len(name) > 64:
        raise ValueError("the style name is longer than 64 characters")
    base_id = str(raw.get("base") or "")
    if base_id not in RECIPE_SPECS:
        raise ValueError(f"unknown base recipe: {base_id or '(missing)'}")
    if base_id not in STYLE_BASE_IDS:
        raise ValueError(f"{RECIPE_SPECS[base_id]['label']} cannot be a style - it "
                         "runs from a finished frame, not from the style picker")
    style_id = style_slug(raw.get("id") or default_id or name)
    if not style_id or not _STYLE_ID_RE.fullmatch(style_id):
        raise ValueError("the style id must be lowercase letters, digits or underscores")
    if style_id in RECIPE_SPECS:
        raise ValueError(f"“{style_id}” is a built-in recipe id - pick another name")
    model = str(raw.get("model") or "").replace("/", "\\").strip()
    if not model:
        raise ValueError("a style has to name the model it runs on")
    aspect = str(raw.get("aspect") or "").strip()
    if aspect and aspect not in ASPECTS:
        raise ValueError(f"unknown canvas: {aspect}")
    mp = raw.get("mp")
    if mp in (None, ""):
        mp = None
    else:
        try:
            mp = float(mp)
        except (TypeError, ValueError):
            raise ValueError(f"megapixels must be a number, got {raw.get('mp')!r}") from None
        if not math.isfinite(mp) or not 0.1 <= mp <= 8.0:
            raise ValueError(f"megapixels must be between 0.1 and 8, got {mp:g}")
    plan = raw.get("lora_plan")
    if plan is not None:
        plan = heal_style_lora_plan(base_id, plan)
    provenance = raw.get("provenance")
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("provenance must be an object")
    record = {
        "schema_version": RECIPE_SCHEMA_VERSION,
        "id": style_id, "name": name, "base": base_id, "model": model,
        "tuning": validate_style_tuning(raw.get("tuning")),
        "provenance": provenance or {},
    }
    if RECIPE_SPECS[base_id].get("needs_character"):
        # Derived from the base, never taken from the file: the picker reads
        # this to ask for an anchor instead of failing the render later.
        record["needs_character"] = True
    if aspect:
        record["aspect"] = aspect
    if mp is not None:
        record["mp"] = mp
    if plan is not None:
        record["lora_plan"] = plan
    return record


def check_style_runnable(record):
    """Save-time checks that need the catalog: the model exists and fits, and
    the sampler values are ones this ComfyUI actually offers.

    Kept out of validate_saved_style so that loading a style whose model is
    temporarily missing still SHOWS it (greyed, with a reason) rather than
    making the file disappear.
    """
    base_id, model = record["base"], record["model"]
    spec = RECIPE_SPECS[base_id]
    entry = resolve_model_entry(model)
    if not entry:
        raise ValueError(f"model is not installed: {base(model)}")
    if entry["family"] != spec["family"]:
        raise ValueError(f"{base(model)} is {entry['family']}, but "
                         f"{spec['label']} needs {spec['family']}")
    if spec.get("no_gguf") and entry["rel"].lower().endswith(".gguf"):
        raise ValueError(f"{spec['label']} cannot run GGUF models")
    variants = spec.get("variants")
    if variants and entry["variant"] not in variants:
        raise ValueError(f"{spec['label']} uses {', '.join(variants)} models; "
                         f"{base(model)} is {entry['variant']}")
    tuning = record.get("tuning") or {}
    if not tuning:
        return record
    seat = sampler_seat(base_id, model)
    if not seat:
        raise ValueError(fixed_schedule_reason(base_id, model))
    # A setting the seat's node does not have would be written into its inputs
    # and rejected by ComfyUI at queue time, on the user. Say so at save time.
    unsupported = [k for k in tuning if k not in seat_tuning_keys(seat)]
    if unsupported:
        raise ValueError(f"{seat['class']} has no "
                         f"{', '.join(sorted(unsupported))} setting")
    options = sampler_choices(seat["class"])
    for key in ("sampler_name", "scheduler"):
        allowed = options.get(key) or ()
        if key in tuning and allowed and tuning[key] not in allowed:
            raise ValueError(f"{seat['class']} has no {key} called "
                             f"“{tuning[key]}”")
    return record


def style_missing(record):
    """What this style needs and does not have, in sentences. Empty = runnable."""
    missing = []
    try:
        check_style_runnable(record)
    except ValueError as exc:
        missing.append(str(exc))
    for row in ((record.get("lora_plan") or {}).get("entries") or []):
        name = row.get("name")
        if name and row.get("enabled") is not False and not resolve_lora(name):
            missing.append(f"LoRA: {base(name)}")
    return missing


def load_saved_styles():
    """Every recipes/*.json, plus a named reason for each one that is unusable.

    One bad file must never take the app down or silently vanish - it is
    reported, skipped, and shown in Settings so it can be fixed.
    """
    styles, problems = {}, []
    if RECIPE_DIR.is_dir():
        for path in sorted(RECIPE_DIR.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                problems.append(f"{path.name}: not readable JSON - {exc}")
                continue
            try:
                record = validate_saved_style(raw, default_id=path.stem)
            except ValueError as exc:
                problems.append(f"{path.name}: {exc}")
                continue
            if record["id"] in styles:
                problems.append(f"{path.name}: the id “{record['id']}” is "
                                "already used by another file")
                continue
            styles[record["id"]] = record
    for note in problems:
        print(f"[pixal] unusable style {note}", flush=True)
    return styles, problems


# The shipped starter set: product data living in templates/styles/ (a
# subdirectory, so the TEMPLATES glob above never mistakes a style for a
# graph). A fresh install's recipes/ holds only .gitkeep, and the first thing
# the picker asked of a stranger was to invent a base, a model and a LoRA
# chain - the node soup they installed Pixal to escape. The starter set is
# built ONLY on checkpoints the installer itself lays down (Z-Image Turbo and
# Anima; see install/catalog.json), so every one of them runs on a machine
# that has never seen a Civitai login.
STARTER_STYLE_DIR = HERE / "templates" / "styles"


def seed_starter_styles():
    """Copy the shipped starter styles into recipes/ on first run, once.

    The copies become ordinary user data from the first boot - visible,
    editable, deletable like anything else in recipes/. The marker file, not
    the folder's emptiness, is the memory: it is written whether or not
    anything was copied, so a user who deletes every starter never sees them
    resurrected, and an upgrade that already has styles is never merged with
    the set. Copying can clobber nothing - the no-styles precondition means
    there is no user file to overwrite, and the marker goes down LAST so a
    half-failed copy is retried on the next boot rather than sealed in.
    """
    try:
        marker = RECIPE_DIR / ".starter_seeded"
        if marker.exists():
            return
        if STARTER_STYLE_DIR.is_dir():
            RECIPE_DIR.mkdir(exist_ok=True)
            if not any(RECIPE_DIR.glob("*.json")):
                for src in sorted(STARTER_STYLE_DIR.glob("*.json")):
                    dst = RECIPE_DIR / src.name
                    if not dst.exists():
                        shutil.copy2(src, dst)
        marker.write_text("the starter styles were offered once; this file "
                          "only stops deleted ones from coming back\n",
                          encoding="utf-8")
    except OSError as exc:
        # Seeding is a courtesy, never a boot blocker.
        print(f"[pixal] starter styles not seeded: {exc}", flush=True)


seed_starter_styles()
SAVED_STYLES, STYLE_PROBLEMS = load_saved_styles()


def saved_style(ref):
    """A style record by id, or None. Never raises: a style deleted in another
    tab must not take a render down with it."""
    return SAVED_STYLES.get(str(ref or "")) or None


def write_saved_style(record):
    RECIPE_DIR.mkdir(exist_ok=True)
    path = RECIPE_DIR / f"{record['id']}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    SAVED_STYLES[record["id"]] = record
    return path


def _resolved_recipe_stage(recipe_id, stage, strength=None):
    real = resolve_lora(stage["name"])
    if not real:
        raise ValueError(f"{RECIPE_SPECS[recipe_id]['label']} requires LoRA: {stage['name']}")
    return {
        "slot": stage["slot"], "name": real,
        "strength": _lora_strength(stage["strength"] if strength is None else strength,
                                    stage["slot"]),
        "role": stage["role"], "zone": stage["zone"], "source": "recipe",
        "locked": bool(stage["order_locked"]),
    }


def _bypass_variant_stage(stage, variant):
    """Swap the locked vector-bypass stage's file for the chosen variant
    (brief 9.15). Only the NAME changes - slot, strength, role, zone and the
    chain's order are the stage's own, so a 3-vector graph is today's graph
    with one loader's lora_name swapped and nothing else. The default variant
    and anything uninstalled keep the authored stage: intake validation has
    already landed bad values on the default, so this is the builder-side
    guard for direct calls, and it degrades rather than dies."""
    if stage.get("slot") != "vector_bypass" or \
            isinstance(variant, bool) or not isinstance(variant, int):
        return stage
    if variant == KREA_BYPASS_VECTORS:
        return stage
    rel = vector_bypass_variants().get(variant)
    return {**stage, "name": rel} if rel else stage


def resolve_recipe_lora_stack(recipe_id, loras=(), lora_plan=None,
                              family=None, variant=None, bypass_variant=None):
    """Recipe stages + either legacy appended extras or a replacement editable lane.

    Structural/core stages always come from RECIPE_SPECS. A new lora_plan owns the
    complete editable lane; without one, authored defaults remain pinned and the
    historical `loras` list is appended exactly as before.
    """
    spec = RECIPE_SPECS[recipe_id]
    stages = spec.get("lora_stages") or []
    core_defs = [s for s in stages if s["zone"] == "core"]
    edit_defs = [s for s in stages if s["zone"] == "editable"]
    if lora_plan is not None:
        validate_lora_plan(recipe_id, lora_plan)
    # An unlocked core stage is skipped entirely rather than loaded at 0: a
    # LoraLoader at zero strength still costs the load and still perturbs the
    # chain, so "bypass" has to mean absent from the graph.
    overrides = (lora_plan or {}).get("core") or {}
    core = []
    for stage in core_defs:
        override = overrides.get(stage["slot"]) or {}
        if override.get("enabled") is False:
            continue
        core.append(_resolved_recipe_stage(
            recipe_id, _bypass_variant_stage(stage, bypass_variant),
            override.get("strength")))
    # Recomputed from what SURVIVED: a bypassed core LoRA is no longer a locked
    # stage, so the user may add it back by name in the editable lane.
    core_names = {e["name"].lower() for e in core}
    dropped = []

    if lora_plan is None:
        editable = [_resolved_recipe_stage(recipe_id, s) for s in edit_defs
                    if s.get("active_by_default")]
        baked = [e["name"] for e in core + editable]
        keep, dropped = lora_stack(loras, baked=baked, family=family, variant=variant)
        editable.extend({"name": name, "strength": strength, "role": "style",
                         "zone": "editable", "source": "user", "locked": False}
                        for name, strength in keep)
        return core + editable, dropped

    edit_by_slot = {s["slot"]: s for s in edit_defs}
    candidates = []
    for item in lora_plan["entries"]:
        # Disabled rows remain in the persisted literal chain, but they are not
        # execution candidates and therefore cannot leak into graph/job info.
        if item.get("enabled") is False:
            continue
        if item.get("slot"):
            stage = edit_by_slot[item["slot"]]
            candidates.append(_resolved_recipe_stage(
                recipe_id, stage, item.get("strength", stage["strength"])))
            continue
        name = item["name"]
        strength = _lora_strength(item.get("strength", 1.0), name)
        keep, rejected = lora_stack([f"{name}:{strength}"], family=family, variant=variant)
        dropped.extend(rejected)
        if not keep:
            continue
        real, strength = keep[0]
        if real.lower() in core_names:
            raise ValueError(f"LoRA is a locked {spec['label']} stage: {real}")
        candidates.append({"name": real, "strength": strength, "role": "style",
                           "zone": "editable", "source": "user", "locked": False})

    # Canonical names are the identity. Keep the last occurrence's strength AND
    # literal position, including collisions between a recipe slot and user row.
    ordered = {}
    for entry in candidates:
        key = entry["name"].lower()
        if key in ordered:
            del ordered[key]
        ordered[key] = entry
    return core + list(ordered.values()), dropped


def apply_lora_nodes(graph, tail, entries, prefix):
    for i, entry in enumerate(entries):
        node_id = f"{prefix}{i}"
        graph[node_id] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "lora_name": entry["name"], "strength_model": entry["strength"],
            "model": [tail, 0]}}
        tail = node_id
    return tail


def lora_job_info(entries, dropped=()):
    stack = [{k: entry[k] for k in
              ("slot", "name", "strength", "role", "zone", "source", "locked")
              if k in entry} for entry in entries]
    return {
        "loras": [f"{base(e['name'])}@{e['strength']:g}" for e in entries],
        "lora_stack": stack,
        "lora_warnings": list(dropped),
    }


def model_job_info(entry, execution_profile=None):
    """Authoritative identity of the model that was inserted into the graph.

    UI labels must not infer architecture from a marketing filename: Z-Image
    finetunes can legitimately contain strings such as ``Krea2`` in their name.
    """
    info = {
        "model": base(entry["rel"]),
        "model_path": entry["rel"],
        "model_family": entry["family"],
        "model_variant": entry.get("variant", "any"),
    }
    if execution_profile:
        info["execution_profile"] = execution_profile
    return info


def validate_job_model_info(template, info, graph=None):
    """Refuse to queue when builder attestation contradicts recipe or graph."""
    # `zara_edit` survives only in old ledgers/rerolls; it is the pre-rename
    # public key for today's Identity Edit builder and needs the same guard.
    canonical_template = "identity_edit" if template == "zara_edit" else template
    spec = RECIPE_SPECS.get(canonical_template)
    if not spec:
        return
    expected = spec["family"]
    actual = (info or {}).get("model_family")
    if actual != expected:
        raise RuntimeError(
            f"resolved model family mismatch: {template} needs {expected}, got {actual or 'unknown'}")
    if not info.get("model_path"):
        raise RuntimeError(f"{template} builder did not report its resolved model path")
    if expected == "zimage" and not str(info.get("execution_profile", "")).startswith("zimage_"):
        raise RuntimeError(f"{template} builder did not report a Z-Image execution profile")
    if graph is not None:
        loaders = []
        for node_id, node in graph.items():
            class_type = str(node.get("class_type", "")).lower()
            if "loader" not in class_type:
                continue
            inputs = node.get("inputs", {})
            for key in ("unet_name", "ckpt_name"):
                if isinstance(inputs.get(key), str):
                    loaders.append((node_id, inputs[key]))
        if len(loaders) != 1:
            raise RuntimeError(
                f"{template} graph must contain exactly one primary model loader, got {len(loaders)}")
        actual_path = loaders[0][1].replace("/", "\\").casefold()
        reported_path = str(info["model_path"]).replace("/", "\\").casefold()
        if actual_path != reported_path:
            raise RuntimeError(
                f"resolved model path mismatch: metadata says {info['model_path']}, "
                f"graph loads {loaders[0][1]}")

def build_realism(scene, seed, width=None, height=None, loras=(), overrides=(),
                   standing=True, nsfw=False, model=None, aspect=None, mp=None,
                   character=None, lora_plan=None):
    g = json.loads(json.dumps(TEMPLATES["realism"]))
    model_entry = pick_recipe_model(model, "realism")
    set_unet_loader(g, "30:10", model_entry)
    ch = resolve_character(character)
    cap = " ".join(scene.split())
    if standing:   # anchor's canon blocks + wardrobe lock; OFF for scenes with no person
        if ch:
            cap = " ".join(character_subject(ch).split()) + " " + cap
        if not nsfw:   # nsfw=true = the user ASKED for explicit - the lock would
            cap += " " + wardrobe_lock_for(ch)   # override their ask from the
                                                 # strongest (closing) position
    g["30:19"]["inputs"]["value"] = cap
    g["30:51"]["inputs"]["seed"] = seed
    g["30:24"]["inputs"]["value"] = False                 # --no-expand: VLM expander fights the caption
    if aspect and not (width and height):
        width, height = dims_for(aspect, mp or 2.0)       # graph default is ~2 MP (1080x1920)
    if width:
        g["30:5"]["inputs"]["width"] = int(width)
    if height:
        g["30:5"]["inputs"]["height"] = int(height)
    # The template's old baked node/switch is rebuilt from the same plan the UI
    # sees, so removal, strength and order cannot diverge from the actual graph.
    for node_id in ("30:15", "30:22"):
        g.pop(node_id, None)
    entries, dropped = resolve_recipe_lora_stack(
        "realism", loras, lora_plan, family="krea2")
    tail = apply_lora_nodes(g, "30:10", entries, "30:lora")
    g["30:51"]["inputs"]["model"] = [tail, 0]
    g["29"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene)}"
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    info = {**model_job_info(model_entry), **lora_job_info(entries, dropped),
            "size": f"{g['30:5']['inputs']['width']}x{g['30:5']['inputs']['height']}",
            "character": ch["name"] if ch else None}
    return g, cap, info


def build_face_mint(scene, seed, image=None, denoise=None, eta=None,
                    overrides=(), model=None):
    """A new person, minted from a real photograph.

    Generating a face from noise lands on the model's mode: symmetric, poreless,
    unmistakably rendered. Starting from a photograph and only partially
    denoising keeps that photograph's real proportions, lighting falloff and
    imperfection map and repaints only the surface, so the identity drifts to
    someone new while the realism is inherited rather than invented. Nothing in
    the sampler can manufacture what the encoder never saw.

    Measured on one source photo, texture against the photo itself:
        as shipped (LoRA on, eta 0, linear/euler)   -32.4%
        RealisticSnapshotKrea2 stripped             -19.7%
        + eta raised off zero                        +8.1%
    A VAE round trip alone costs 10% and no setting recovers it - a pore is
    smaller than one latent pixel. That 10% is the floor, not the LoRA's fault.

    `denoise` is the identity dial and the window is narrow: at 0.4 the identity
    holds, by 0.8 it is an unrelated face. It is also the texture gain, and the
    two pull in opposite directions - a source that already carries heavy skin
    detail needs LESS than the 0.55 default, not more, or its own texture gets
    amplified into something coarser than the photograph ever was.
    """
    src = input_ref_name(image)
    if not src:
        raise ValueError("New Face needs a source photo in ComfyUI/input")
    if not (CDIR / "input" / src).is_file():
        raise ValueError(f"source image not found in ComfyUI/input: {src}")
    g = json.loads(json.dumps(TEMPLATES["face_mint"]))
    model_entry = pick_recipe_model(model, "face_mint")
    set_unet_loader(g, "30:10", model_entry)
    g["fm:load"]["inputs"]["image"] = src
    # This repaints the WHOLE frame, so unlike the inpaint lane there are no
    # untouched pixels to protect and the cap simply is the output size. It
    # still has to exist: point this at a PiD 4x and the encode, all eight
    # sampler steps and the decode run at 30 megapixels on a model trained
    # around two.
    working_mp = min(_source_megapixels(CDIR / "input" / src, FACE_MINT_MP_CAP),
                     FACE_MINT_MP_CAP)
    g["fm:scale"]["inputs"]["megapixels"] = working_mp
    g["fm:scale"]["inputs"]["resolution_steps"] = FACE_MINT_STEPS
    cap = " ".join(str(scene or "").split())
    g["30:19"]["inputs"]["value"] = cap
    g["30:24"]["inputs"]["value"] = False       # --no-expand, as build_realism does
    g["30:51"]["inputs"]["seed"] = seed
    if denoise is not None:
        g["30:51"]["inputs"]["denoise"] = max(0.05, min(1.0, float(denoise)))
    if eta is not None:
        g["30:51"]["inputs"]["eta"] = max(0.0, min(1.0, float(eta)))
    g["29"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene) or 'face_mint'}"
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    info = {**model_job_info(model_entry), "source": src,
            "megapixels": g["fm:scale"]["inputs"]["megapixels"],
            "denoise": g["30:51"]["inputs"]["denoise"],
            "eta": g["30:51"]["inputs"]["eta"]}
    canvas = qwen_edit_canvas(CDIR / "input" / src,
                              g["fm:scale"]["inputs"]["megapixels"],
                              g["fm:scale"]["inputs"]["resolution_steps"])
    if canvas:
        info["size"] = f"{canvas[0]}x{canvas[1]}"
        info["canvas_mp"] = (canvas[0] * canvas[1]) / 1e6
    return g, cap, info


def build_zara_edit(scene, seed, ref=None, grounding=IDENTITY_GROUNDING_PX,
                    ref_boost=IDENTITY_REF_BOOST, overrides=(), model=None, aspect=None,
                    mp=None, loras=(), character=None, lora_plan=None, pid=None,
                    bypass_variant=None):
    """THE settled moments recipe (2026-08-07), captured verbatim from
    edit_fast.py: mxfp8 + Wan VAE, linear/euler + simple, 10 steps, cfg 1.0,
    eta 0.0, no base realism LoRA, 1152x2048. RawGirlV3 rode along in the
    captured graph but is a style call - it stays an authored slot, off by
    default. Replaces the old res_4s_munthe-kaas graph (4 model calls/step;
    its eta 0.38 is the prime suspect for the dark-blob defect). Old graph
    archived at templates/zara_edit_res4s.json.bak. Node ids are edit_fast's:
    30:19 caption, 30:51 sampler, 30:5 latent, 30:10 unet, 30:6 grounded
    encode, ed:img ref, ed:patch edit patch, 29 save."""
    # A selected character is authoritative. A stale/manual identity ref must
    # never silently replace the face the user just picked.
    if character:
        ch, ref = character_identity(character)
    else:
        ch = None
        ref = input_ref_name(ref)
        if not ref:
            raise ValueError("identity edit needs a selected character or identity reference")
        if not (CDIR / "input" / ref).is_file():
            raise ValueError(f"reference image not found in ComfyUI/input: {ref}")
    suffix = (ch or {}).get("edit_suffix", "")
    g = json.loads(json.dumps(TEMPLATES["identity_edit"]))
    model_entry = pick_recipe_model(model, "identity_edit")
    set_unet_loader(g, "30:10", model_entry)
    g["30:19"]["inputs"]["value"] = " ".join((scene + " " + suffix).split())
    g["30:51"]["inputs"]["seed"] = seed
    g["30:6"]["inputs"]["grounding_px"] = int(grounding)
    g["ed:img"]["inputs"]["image"] = ref
    # UNMASKED boost - a nudge, not the face-masked lock. Always written so the
    # builder is the single source of truth for it, as it is for grounding_px.
    g["ed:patch"]["inputs"]["ref_boost"] = float(ref_boost)
    if aspect:                        # default canvas is the recipe's 1152x2048 (9:16 @ 2.36MP)
        w, h = dims_for(aspect, mp or 2.36)
        g["30:5"]["inputs"]["width"], g["30:5"]["inputs"]["height"] = w, h
    elif mp:                          # keep 9:16, scale the canvas
        w, h = dims_for("9:16 (Portrait Widescreen)", mp)
        g["30:5"]["inputs"]["width"], g["30:5"]["inputs"]["height"] = w, h
    # Rebuild the complete pre-patch chain. In particular, vector bypass is a
    # locked first stage: UNET -> bypass -> identity LoRA -> editable lane ->
    # patch. bypass_variant (brief 9.15) swaps only that stage's FILE - the
    # chain's shape and order never change.
    for node_id in ("30:15", "30:22", "ed:lora", "ed:extra0"):
        g.pop(node_id, None)
    entries, dropped = resolve_recipe_lora_stack(
        "identity_edit", loras, lora_plan, family="krea2",
        bypass_variant=bypass_variant)
    tail = apply_lora_nodes(g, "30:10", entries, "ed:lora")
    g["ed:patch"]["inputs"]["model"] = [tail, 0]
    use_pid = load_config()["pid"]["identity_finish"] if pid is None else bool(pid)
    if use_pid:
        if not _pid_node_available(PID_DECODE_NODE):
            raise ValueError("PiD finish needs the ComfyUI-PiD node pack")
        # The 2kto4k decoder only accepts preset base canvases: snap on aspect,
        # then hand the sampler's finished latent to PiD instead of the Wan VAE.
        # 30:12 stays - the identity ref still ENCODES through the real VAE.
        w, h = pid_base_canvas(g["30:5"]["inputs"]["width"],
                               g["30:5"]["inputs"]["height"])
        g["30:5"]["inputs"]["width"], g["30:5"]["inputs"]["height"] = w, h
        g["30:8"] = pid_decode_node(["30:51", 0], g["30:19"]["inputs"]["value"],
                                    seed)
    g["29"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene)}"
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    size = f"{g['30:5']['inputs']['width']}x{g['30:5']['inputs']['height']}"
    info = {**model_job_info(model_entry), **lora_job_info(entries, dropped),
            "size": size + " (PiD 4×)" if use_pid else size,
            "character": ch["name"] if ch else None}
    return g, (scene + " " + suffix).strip(), info


# Qwen dates its releases YYMM. Edit refreshes from 2509 on ship as the Plus
# encoder; the bare original does not. Matching the date rather than a list means
# a later refresh drops in without a code change.
_QWEN_DATED_RELEASE = re.compile(r"(?<!\d)(2[5-9]|[3-9]\d)(0[1-9]|1[0-2])(?!\d)")
QWEN_EDIT_PLUS_FROM = "2509"


def set_qwen_edit_encoder(graph, model_entry):
    """Point the two encoders at the node class this Qwen-Image-Edit release wants.

    The original release takes one image on `image`; every dated refresh from 2509
    on ships as TextEncodeQwenImageEditPlus, which numbers its inputs
    image1..image3. Same conditioning contract either way, so swapping the class
    and the input name is the whole difference - and because this graph supplies
    its own reference latent, the Plus node's extra /8 rounding never comes up.

    Note the dates run per model line: Qwen-Image-2512 is a *base* text-to-image
    release, not an edit one, so it never reaches this function."""
    name = str((model_entry or {}).get("rel") or (model_entry or {}).get("name") or "")
    plus = edit_accelerator(model_entry).get("plus_encoder")
    if plus is None:
        dated = [m.group(0) for m in _QWEN_DATED_RELEASE.finditer(name)]
        plus = any(d >= QWEN_EDIT_PLUS_FROM for d in dated)
    if not plus:
        return "TextEncodeQwenImageEdit"
    for nid in ("qe:pos", "qe:neg"):
        node = graph[nid]
        node["class_type"] = "TextEncodeQwenImageEditPlus"
        node["inputs"]["image1"] = node["inputs"].pop("image")
    return "TextEncodeQwenImageEditPlus"


def _image_size(source_path):
    """(width, height) of a staged frame, or None when it cannot be read. Every
    canvas cap starts here, so a source Pillow refuses to open must degrade to
    'unknown' rather than to a guessed size that prices the render wrong."""
    try:
        from PIL import Image
        with Image.open(source_path) as im:
            width, height = im.size
    except (OSError, ValueError):
        return None
    return (width, height) if width and height else None


def _source_megapixels(source_path, cap):
    """The source's own size in Comfy megapixels, capped.

    Working at the source's own size is the point of every edit lane - it is
    what makes a finished frame survive a round trip - but each of them still
    needs a ceiling, and none of them should ever UPSCALE a small source to
    reach it. min() is doing both jobs."""
    size = _image_size(source_path)
    if not size:
        return cap
    return min((size[0] * size[1]) / (1024.0 * 1024.0), cap)


def qwen_edit_canvas(source_path, megapixels, steps=8):
    """What ImageScaleToTotalPixels will produce, so the job card can show the
    real aspect while sampling instead of guessing. Comfy measures megapixels in
    1024*1024 units and rounds each side up to `resolution_steps`."""
    size = _image_size(source_path)
    if not size:
        return None
    width, height = size
    scale = math.sqrt((float(megapixels) * 1024 * 1024) / (width * height))
    out = []
    for side in (width * scale, height * scale):
        out.append(int(math.ceil(side / steps) * steps) if steps > 1 else int(round(side)))
    return out[0], out[1]


def edit_accelerator(model_entry):
    """The EDIT_ACCELERATORS row that belongs to this edit transformer.

    Matched on the filename, most specific first, with the Qwen row last as the
    fall-through - the same shape as set_qwen_edit_encoder's date rule, and for
    the same reason: a compatible release should drop in as data, not as code."""
    name = str((model_entry or {}).get("rel") or (model_entry or {}).get("name") or "")
    low = name.replace("/", "\\").lower()
    for spec in EDIT_ACCELERATORS:
        if all(token in low for token in spec["tokens"]):
            return spec
    return EDIT_ACCELERATORS[-1]


def edit_accelerator_lora(spec):
    """The accelerator's file as ComfyUI spells it, or None when it is absent.

    The pinned filename wins; failing that any installed LoRA carrying the
    line's tokens does, so a point release (FireRed 8-step v1.1 -> v1.2) keeps
    accelerating instead of silently dropping back to the 40-step branch. max()
    prefers the later version and keeps the pick deterministic."""
    canonical = _video_asset("loras", spec["lora"])
    if canonical:
        return canonical
    tokens = spec.get("lora_tokens") or ()
    if not tokens:
        return None
    matches = [entry["rel"] for entry in model_catalog("loras")
               if all(t in str(entry.get("rel") or "").replace("/", "\\").lower()
                      for t in tokens)]
    return max(matches) if matches else None


def qwen_edit_speed_settings(model_entry=None, speed=None):
    """(steps, cfg, shift, lora_rows) for one edit model at one speed.

    "turbo" is the model's OWN distillation - Qwen's 4-step Lightning V2 on the
    Qwen line, FireRed's 8-step on FireRed - and applies only when that LoRA is
    actually on disk, because a distillation schedule without its distillation
    is not a faster edit, it is a ruined one. When it is missing, or the user
    asked for "full", this returns the line's un-accelerated schedule instead of
    leaving a distilled step count behind.
    """
    spec = edit_accelerator(model_entry)
    if str(speed or "turbo").lower() != "full":
        canonical = edit_accelerator_lora(spec)
        if canonical:
            turbo = spec["turbo"]
            row = {"name": canonical, "title": spec["label"],
                   "strength": turbo["strength"], "trigger": None,
                   "role": "speed", "zone": "core", "source": "turbo",
                   "locked": True}
            return turbo["steps"], turbo["cfg"], turbo["shift"], [row]
    full = spec["full"]
    return full["steps"], full["cfg"], full["shift"], []


def build_qwen_edit(scene, seed, image=None, megapixels=None, steps=None, cfg=None,
                    overrides=(), model=None, loras=(), lora_plan=None,
                    reference=None, speed=None):
    """Instruction-driven edit of an existing frame (Qwen-Image-Edit).

    Ported from ComfyUI's shipped `image_qwen_image_edit` template with the
    Lightning branch resolved to the non-Lightning side, then rewired to keep
    the source at its own resolution - see below. The spine is:
    two TextEncodeQwenImageEdit (instruction + empty negative) -> ReferenceLatent
    on each -> ModelSamplingAuraFlow(shift 3) -> CFGNorm(1.0) ->
    KSampler(20 steps, cfg 2.5, euler/simple, denoise 1.0).

    Three details are load-bearing and easy to get wrong:

    The encoders are deliberately given NO vae. Reading comfy_extras/nodes_qwen.py:
    the node always squashes the image to 1024*1024 px with "area" resampling, and
    `ref_latent = vae.encode(...)` runs on that squashed copy only when a vae is
    connected. Connecting it therefore forces every edit through a ~1 MP downscale
    that no parameter can turn off, which is the whole cause of edit-time softness,
    zoom and pixel drift. With the vae left off, that resize only feeds the
    Qwen2.5-VL semantic tokens, where a 1 MP view is all the encoder ever wanted.

    The reference latent instead comes from our own VAEEncode through
    ReferenceLatent, which appends to the same `reference_latents` conditioning key
    the node would have set. Because the sampler's latent_image and the reference
    latent are now literally the same VAEEncode output, they cannot desynchronise -
    the old failure this graph was pinned to 1 MP to avoid. Working resolution is
    ours again: the edit runs at the source's own size, so a 2 MP render comes back
    2 MP instead of round-tripping through 1 MP.

    The negative branch is a second encoder with an empty prompt (NOT
    ConditioningZeroOut) carrying the same reference latent, so CFG measures the
    instruction rather than the presence of the source image.

    Steps/cfg stay overridable so a 4-step Lightning LoRA (which also wants
    cfg 1.0) can be driven from the plan without editing the template."""
    src = input_ref_name(image)
    if not src:
        raise ValueError("Qwen Image Edit needs a source image in ComfyUI/input")
    if not (CDIR / "input" / src).is_file():
        raise ValueError(f"source image not found in ComfyUI/input: {src}")
    instruction = " ".join(str(scene or "").split())
    if not instruction:
        raise ValueError("Qwen Image Edit needs an edit instruction")
    g = json.loads(json.dumps(TEMPLATES["qwen_edit"]))
    # An explicit per-render pick wins; failing that Settings names the release,
    # and only then the recipe default.
    model_entry = pick_recipe_model(
        model or load_config()["edit"].get("model") or None, "qwen_edit")
    set_unet_loader(g, "qe:unet", model_entry)
    encoder = set_qwen_edit_encoder(g, model_entry)
    clip = _pick_catalog_asset("text_encoders", (QWEN_EDIT_CLIP,),
                               "its Qwen 2.5 VL 7B text encoder", "Qwen Image Edit")
    set_clip_loader(g, "qe:clip", clip, "qwen_image")
    g["qe:vae"]["inputs"]["vae_name"] = _pick_catalog_asset(
        "vae", (QWEN_EDIT_VAE, KREA_VAE_REALISM), "a Qwen-Image VAE", "Qwen Image Edit")
    g["qe:img"]["inputs"]["image"] = src
    g["qe:pos"]["inputs"]["prompt"] = instruction
    g["qe:sampler"]["inputs"]["seed"] = seed
    low, high = QWEN_EDIT_MP_RANGE
    if megapixels is None:
        working_mp = _source_megapixels(CDIR / "input" / src, QWEN_EDIT_MP_CAP)
    else:
        working_mp = float(megapixels)
    g["qe:scale"]["inputs"]["megapixels"] = min(max(working_mp, low), high)
    # Lightning is the default speed when its LoRA is installed; an explicit
    # steps/cfg ask is a deliberate schedule and must not get a strength-1
    # distillation stacked under it silently.
    speed_rows = []
    if steps is None and cfg is None:
        want = speed or load_config()["edit"].get("speed") or "turbo"
        sched = qwen_edit_speed_settings(model_entry, want)
        g["qe:sampler"]["inputs"]["steps"] = sched[0]
        g["qe:sampler"]["inputs"]["cfg"] = sched[1]
        g["qe:shift"]["inputs"]["shift"] = sched[2]
        speed_rows = sched[3]
    if steps is not None:
        g["qe:sampler"]["inputs"]["steps"] = max(1, int(steps))
    if cfg is not None:
        g["qe:sampler"]["inputs"]["cfg"] = float(cfg)
    entries, dropped = resolve_recipe_lora_stack(
        "qwen_edit", loras, lora_plan, family="qwen_edit")
    entries = speed_rows + entries
    tail = apply_lora_nodes(g, "qe:unet", entries, "qe:lora")
    g["qe:shift"]["inputs"]["model"] = [tail, 0]
    g["qe:save"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(instruction)}"
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    if reference:
        # A second image the instruction can point at ("the logo from image 2").
        # It needs BOTH wires: image2 on the Plus encoders gives the VL tokens,
        # but tokens alone make the model invent a lookalike - only the chained
        # ReferenceLatent makes it reproduce the actual mark.
        ref = input_ref_name(reference)
        if not ref or not (CDIR / "input" / ref).is_file():
            raise ValueError(f"reference image not found in ComfyUI/input: {reference}")
        if encoder != "TextEncodeQwenImageEditPlus":
            raise ValueError("this Qwen-Image-Edit release takes a single image; "
                             "a 2509+ release is needed for a reference image")
        g["qe:img2"] = {"class_type": "LoadImage", "inputs": {"image": ref}}
        for nid in ("qe:pos", "qe:neg"):
            g[nid]["inputs"]["image2"] = ["qe:img2", 0]
        g["qe:latent2"] = {"class_type": "VAEEncode",
                           "inputs": {"pixels": ["qe:img2", 0], "vae": ["qe:vae", 0]}}
        g["qe:ref2"] = {"class_type": "ReferenceLatent",
                        "inputs": {"conditioning": ["qe:ref", 0],
                                   "latent": ["qe:latent2", 0]}}
        g["qe:refneg2"] = {"class_type": "ReferenceLatent",
                           "inputs": {"conditioning": ["qe:refneg", 0],
                                      "latent": ["qe:latent2", 0]}}
        g["qe:sampler"]["inputs"]["positive"] = ["qe:ref2", 0]
        g["qe:sampler"]["inputs"]["negative"] = ["qe:refneg2", 0]
    info = {**model_job_info(model_entry), **lora_job_info(entries, dropped),
            "source_image": src,
            "megapixels": g["qe:scale"]["inputs"]["megapixels"]}
    if reference:
        info["reference_image"] = input_ref_name(reference)
    canvas = qwen_edit_canvas(CDIR / "input" / src,
                              g["qe:scale"]["inputs"]["megapixels"],
                              g["qe:scale"]["inputs"]["resolution_steps"])
    if canvas:
        info["size"] = f"{canvas[0]}x{canvas[1]}"
    return g, instruction, info


def build_klein_inpaint(scene, seed, image=None, overrides=(), model=None):
    """Masked inpaint of an existing frame (FLUX.2 Klein 9B).

    Ported node-for-node from the F4 group of geoahmed's
    `flux2_klein_ultimate_v2.1` workflow, with two deliberate drops: the NAG
    branch (its negative is zeroed out anyway, and the pack is not installed)
    and the enhancer LoRA slot (not on disk).

    The mask rides the source PNG's alpha channel: LoadImage's MASK output is
    1-alpha, so transparent pixels are the painted edit region - exactly what
    ComfyUI's own mask editor produces, and what /api/edit stages when a mask
    is attached. VAEEncodeForInpaint (grow 15) restricts sampling to that
    region; the chained ReferenceLatents (inpaint latent, then the full-frame
    latent) keep Klein's KV attention anchored on the untouched pixels, so
    identity outside the mask cannot drift - it is never resampled.

    The decode is composited back over the SOURCE through the grown, feathered
    mask, so unmasked pixels are the original file's, bit-identical. Saving
    the raw decode instead put the whole frame through a flux2-VAE
    encode/decode round trip - visible as global softening plus blotchy
    reconstruction noise in regions the edit never touched (Jesse spotted it
    2026-08-12; the tiled decode's 512px tiles added seams on top).

    Klein is step-distilled: 4 steps at cfg 1.0 IS the schedule, not a speed
    trick, which also makes the zeroed negative the correct one."""
    src = input_ref_name(image)
    if not src:
        raise ValueError("Klein Inpaint needs a source image in ComfyUI/input")
    if not (CDIR / "input" / src).is_file():
        raise ValueError(f"source image not found in ComfyUI/input: {src}")
    instruction = " ".join(str(scene or "").split())
    if not instruction:
        raise ValueError("Klein Inpaint needs an instruction for the masked area")
    g = json.loads(json.dumps(TEMPLATES["klein_inpaint"]))
    model_entry = pick_recipe_model(
        model or None, "klein_inpaint")
    set_unet_loader(g, "ki:unet", model_entry)
    clip = _pick_catalog_asset("text_encoders", (KLEIN_CLIP,),
                               "its Qwen3 8B text encoder", "Klein Inpaint")
    set_clip_loader(g, "ki:clip", clip, "flux2")
    g["ki:vae"]["inputs"]["vae_name"] = _pick_catalog_asset(
        "vae", (KLEIN_VAE,), "the Flux2 VAE", "Klein Inpaint")
    g["ki:img"]["inputs"]["image"] = src
    g["ki:pos"]["inputs"]["text"] = instruction
    g["ki:sampler"]["inputs"]["seed"] = seed
    g["ki:save"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(instruction)}"
    # Sampling canvas: the source's own size, capped. Both scale nodes run the
    # same megapixels/resolution_steps so the mask lands on exactly the pixel
    # grid the image did - they are one resize expressed twice, and drifting
    # them apart is a shape mismatch at VAEEncodeForInpaint.
    #
    # ki:back then returns the decode to the source's EXACT size so ki:comp can
    # lay it over the untouched original with resize_source off. That exactness
    # is load-bearing, so a source we cannot measure does not get a guessed
    # size - it skips the cap entirely and runs the way it did before the cap
    # existed. Capping blind would composite a 1024-px patch onto a full-size
    # frame.
    native = _image_size(CDIR / "input" / src)
    working_mp = None
    if native:
        working_mp = min((native[0] * native[1]) / (1024.0 * 1024.0),
                         KLEIN_INPAINT_MP_CAP)
        g["ki:back"]["inputs"]["width"] = native[0]
        g["ki:back"]["inputs"]["height"] = native[1]
        for node in ("ki:scale", "ki:maskscale"):
            g[node]["inputs"]["megapixels"] = working_mp
            g[node]["inputs"]["resolution_steps"] = KLEIN_INPAINT_STEPS
    else:
        _klein_bypass_scaling(g)
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    info = {**model_job_info(model_entry), "source_image": src}
    if native:
        canvas = qwen_edit_canvas(CDIR / "input" / src, working_mp,
                                  KLEIN_INPAINT_STEPS) or native
        info["megapixels"] = working_mp
        # canvas_mp is what the butler prices; the saved frame stays native, so
        # `size` and `canvas_mp` deliberately disagree.
        info["canvas_mp"] = (canvas[0] * canvas[1]) / 1e6
        info["size"] = f"{native[0]}x{native[1]}"
        if tuple(canvas) != tuple(native):
            # Say it plainly on the job card: sampled small, returned full size.
            info["size"] = (f"{native[0]}x{native[1]} "
                            f"(sampled at {canvas[0]}x{canvas[1]})")
    return g, instruction, info


def _klein_bypass_scaling(g):
    """Wire klein_inpaint back to native-resolution sampling.

    Used when the source cannot be measured, and by the OOM retry in reverse -
    it is the one edit that makes the cap nodes inert without deleting them, so
    the graph stays shaped like the template it was ported from."""
    g["ki:latent"]["inputs"]["pixels"] = ["ki:img", 0]
    g["ki:latent"]["inputs"]["mask"] = ["ki:img", 1]
    g["ki:reffull"]["inputs"]["pixels"] = ["ki:img", 0]
    g["ki:comp"]["inputs"]["source"] = ["ki:decode", 0]


def build_qwen_image(scene, seed, aspect=None, mp=None, width=None, height=None,
                     steps=None, cfg=None, overrides=(), model=None, loras=(),
                     lora_plan=None, character=None, standing=True, nsfw=False):
    """Text-to-image on the Qwen-Image line (Qwen-Image, Qwen-Image-2512).

    A straight port of the basic Qwen-Image-2512 workflow: UNETLoader ->
    ModelSamplingAuraFlow(shift 3.1) -> KSampler(20 steps, cfg 4.0, euler/simple)
    over an EmptySD3LatentImage, with two plain CLIPTextEncode branches on the
    qwen_image CLIP type. No CFGNorm here - that belongs to the edit graph.

    This is a different model line from Qwen-Image-Edit despite the shared name:
    it has no source image, and it reuses the same 2.5-VL text encoder and VAE,
    so installing it costs one UNET rather than a new asset set."""
    spec = RECIPE_SPECS["qwen_image"]
    cap, ch = _character_caption(scene, character, standing, nsfw)
    g = json.loads(json.dumps(TEMPLATES["qwen_image"]))
    model_entry = pick_recipe_model(model, "qwen_image")
    set_unet_loader(g, "qi:unet", model_entry)
    clip = _pick_catalog_asset("text_encoders", (QWEN_EDIT_CLIP,),
                               "its Qwen 2.5 VL 7B text encoder", "Qwen Image")
    set_clip_loader(g, "qi:clip", clip, "qwen_image")
    g["qi:vae"]["inputs"]["vae_name"] = _pick_catalog_asset(
        "vae", (QWEN_EDIT_VAE, KREA_VAE_REALISM), "a Qwen-Image VAE", "Qwen Image")
    if width and height:
        w, h = int(width), int(height)
    else:
        w, h = dims_for(aspect or spec["aspect"], float(mp or spec["mp"]))
    g["qi:latent"]["inputs"]["width"] = w
    g["qi:latent"]["inputs"]["height"] = h
    g["qi:pos"]["inputs"]["text"] = cap
    g["qi:sampler"]["inputs"]["seed"] = seed
    if steps is not None:
        g["qi:sampler"]["inputs"]["steps"] = max(1, int(steps))
    if cfg is not None:
        g["qi:sampler"]["inputs"]["cfg"] = float(cfg)
    entries, dropped = resolve_recipe_lora_stack(
        "qwen_image", loras, lora_plan, family="qwen_image")
    tail = apply_lora_nodes(g, "qi:unet", entries, "qi:lora")
    g["qi:shift"]["inputs"]["model"] = [tail, 0]
    g["qi:save"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene)}"
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    info = {**model_job_info(model_entry), **lora_job_info(entries, dropped),
            "size": f"{w}x{h}",
            "character": ch["name"] if ch else None}
    return g, cap, info


def _character_caption(scene, character=None, standing=True, nsfw=False,
                       lock_generic=True):
    """Shared txt2img subject/wardrobe policy across creative recipes."""
    ch = resolve_character(character)
    cap = " ".join(scene.split())
    if standing:
        if ch:
            cap = " ".join(character_subject(ch).split()) + " " + cap
        if not nsfw and (ch or lock_generic):
            cap += " " + wardrobe_lock_for(ch)
    return cap.strip(), ch


def build_realism_ii(scene, seed, width=None, height=None, loras=(), overrides=(),
                     standing=True, nsfw=False, model=None, aspect=None, mp=None,
                     character=None, lora_plan=None):
    """The supplied Realism II workflow, hardened into an API graph.

    Preserves Selfora + filter-bypass, the 8-step detail pass, 2-step latent
    refinement, and 2x tiled SCUNet finish. Dead previews/disconnected scheduler
    experiments are intentionally omitted, and seeds are inlined so Pixal's
    62-bit seeds do not hit rgthree's narrower primitive limit.
    """
    g = json.loads(json.dumps(TEMPLATES["realism_ii"]))
    model_entry = pick_recipe_model(model, "realism_ii")
    set_unet_loader(g, "316", model_entry)
    cap, ch = _character_caption(scene, character, standing, nsfw)
    g["6"]["inputs"]["text"] = cap
    for nid in ("265", "274", "333"):
        g[nid]["inputs"]["seed"] = int(seed)
    if aspect and not (width and height):
        width, height = dims_for(aspect, mp or RECIPE_SPECS["realism_ii"]["mp"])
    elif mp and not (width and height):
        width, height = dims_for("9:16 (Portrait Widescreen)", mp)
    if width:
        g["323"]["inputs"]["width"] = int(width)
    if height:
        g["323"]["inputs"]["height"] = int(height)

    g.pop("324", None)
    entries, dropped = resolve_recipe_lora_stack(
        "realism_ii", loras, lora_plan, family="krea2")
    tail = apply_lora_nodes(g, "316", entries, "r2:lora")
    for nid in ("265", "274", "333"):
        g[nid]["inputs"]["model"] = [tail, 0]
    g["336"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene)}"
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    w, h = g["323"]["inputs"]["width"], g["323"]["inputs"]["height"]
    scale = float(g["333"]["inputs"]["upscale_by"])
    info = {**model_job_info(model_entry), **lora_job_info(entries, dropped),
            "size": f"{round(w * scale)}x{round(h * scale)} (2× finish)",
            "character": ch["name"] if ch else None}
    return g, cap, info


def _zimage_settings(entry):
    profile_id = entry.get("execution_profile")
    if not profile_id:
        profile_id = "zimage_clear_anime" if entry.get("profile_id") == "clear_anime" else \
            "zimage_turbo_v4" if entry["variant"] == "turbo" else "zimage_base"
    try:
        return profile_id, ZIMAGE_EXECUTION_PROFILES[profile_id]
    except KeyError:
        raise ValueError(f"unsupported Z-Image execution profile: {profile_id}") from None


def _catalog_resolve(kind, rel):
    """The installed rel this asset name means, or None.

    Exact path first, then a UNIQUE basename. The returned rel is the name
    ComfyUI's loaders actually list: a file sitting in a subfolder is offered
    as `Flux\\ae.safetensors`, and handing a loader the bare candidate it
    matched by is a queue-time rejection (Z-Image's first VAE candidate died
    exactly that way on a box whose only ae.safetensors lives under Flux\\).
    """
    # Normalise for COMPARISON only, and return the catalog's own string. The
    # catalog stores `str(p.relative_to(base))`, which carries os.sep - so on
    # Linux it is `ZiT/z_image_turbo_bf16.safetensors` and the backslash copy
    # is a name ComfyUI does not list. Returning the normalised form was the
    # very failure this function exists to prevent ("not in list" at queue
    # time), just moved to the other platform: on Windows the two coincide, on
    # Linux every model in a subfolder was rejected - which is all four starter
    # styles, since both ZiT\ and Anima\ are subfolders.
    entries = model_catalog(kind)
    want = str(rel).replace("/", "\\").lower()
    low = [e["rel"].replace("/", "\\").lower() for e in entries]
    if want in low:
        return entries[low.index(want)]["rel"]
    stem = want.rsplit("\\", 1)[-1]
    hits = [e for e, r in zip(entries, low) if r.rsplit("\\", 1)[-1] == stem]
    return hits[0]["rel"] if len(hits) == 1 else None


def _catalog_has(kind, rel):
    """Is this asset installed? Exact path first, then a UNIQUE basename.

    Exact-only was stricter than `resolve_lora`, which has always fallen back
    to a unique basename - so a recipe could report a recipe LoRA missing
    on a machine that owns x and merely filed it in another folder, while the
    graph builder would have resolved it fine. Nobody downloading from CivitAI
    inherits our folder layout, and this readiness list is the first thing a
    fresh install reads. Uniqueness is the guard: two files sharing a basename
    stay ambiguous and stay unmatched, exactly as before.
    """
    return _catalog_resolve(kind, rel) is not None


def _pick_catalog_asset(kind, candidates, label, recipe="Z-Image"):
    for name in candidates:
        real = _catalog_resolve(kind, name)
        if real:
            return real
    raise ValueError(f"{recipe} requires {label}: " + " or ".join(candidates))


def set_clip_loader(graph, node_id, name, clip_type):
    if name.lower().endswith(".gguf"):
        graph[node_id] = {"class_type": "CLIPLoaderGGUF",
                          "inputs": {"clip_name": name, "type": clip_type}}
    else:
        graph[node_id] = {"class_type": "CLIPLoader",
                          "inputs": {"clip_name": name, "type": clip_type}}


def _build_zimage(recipe_id, scene, seed, width=None, height=None, loras=(), overrides=(),
                   standing=True, nsfw=False, model=None, aspect=None, mp=None,
                   character=None, lora_plan=None):
    g = json.loads(json.dumps(TEMPLATES["zimage"]))
    model_entry = pick_recipe_model(model, recipe_id)
    set_unet_loader(g, "1", model_entry)
    execution_profile, settings = _zimage_settings(model_entry)
    clip_name = _pick_catalog_asset(
        "text_encoders", settings["clip_candidates"], "a Qwen3-4B non-VL text encoder")
    vae_name = _pick_catalog_asset("vae", zimage_vae_candidates(settings),
                                   "the Z-Image VAE")
    set_clip_loader(g, "2", clip_name, settings["clip_type"])
    g["3"]["inputs"]["vae_name"] = vae_name

    cap, ch = _character_caption(scene, character, standing, nsfw, lock_generic=False)
    if recipe_id == "fantasy" and not cap.lower().startswith("d&d painterly"):
        cap = "D&D Painterly, " + cap
    elif recipe_id == "anime" and not cap.lower().startswith(("anime", "japanese anime")):
        cap = "anime, Japanese anime, " + cap
    g["4"]["inputs"]["text"] = cap
    if settings["zero_negative"]:
        g["5"] = {"class_type": "ConditioningZeroOut",
                  "inputs": {"conditioning": ["4", 0]}}
    else:
        g["5"] = {"class_type": "CLIPTextEncode",
                  "inputs": {"clip": ["2", 0], "text": ""}}

    if aspect and not (width and height):
        width, height = dims_for(aspect, mp or RECIPE_SPECS[recipe_id]["mp"])
    elif mp and not (width and height):
        width, height = dims_for(RECIPE_SPECS[recipe_id]["aspect"], mp)
    if width:
        g["6"]["inputs"]["width"] = int(width)
    if height:
        g["6"]["inputs"]["height"] = int(height)

    entries, dropped = resolve_recipe_lora_stack(
        recipe_id, loras, lora_plan, family="zimage", variant=model_entry["variant"])
    tail = apply_lora_nodes(g, "1", entries, "z:lora")
    if settings["sampler_graph"] == "amazing_v4":
        # Amazing Z-Image v4's measured Turbo schedule. The raw model feeds two
        # Euler passes; applying AuraFlow here caused severe artifacts.
        g.pop("7", None)
        g.pop("8", None)
        g["z:v4:sampler"] = {"class_type": "KSamplerSelect",
                              "inputs": {"sampler_name": settings["sampler"]}}
        g["z:v4:sigmas"] = {"class_type": "KarrasScheduler", "inputs": {
            "steps": 8, "sigma_max": 0.99, "sigma_min": 0.08, "rho": 0.3}}
        g["z:v4:split"] = {"class_type": "SplitSigmas",
                            "inputs": {"sigmas": ["z:v4:sigmas", 0], "step": 2}}
        g["z:v4:first"] = {"class_type": "SetFirstSigma",
                            "inputs": {"sigmas": ["z:v4:split", 1], "sigma": 0.906}}
        g["z:v4:extend"] = {"class_type": "ExtendIntermediateSigmas", "inputs": {
            "sigmas": ["z:v4:first", 0], "steps": 2, "start_at_sigma": 1.0,
            "end_at_sigma": 0.8, "spacing": "linear"}}
        common = {"model": [tail, 0], "cfg": settings["cfg"],
                  "positive": ["4", 0], "negative": ["5", 0],
                  "sampler": ["z:v4:sampler", 0]}
        g["z:v4:high"] = {"class_type": "SamplerCustom", "inputs": {
            **common, "add_noise": True, "noise_seed": int(seed),
            "sigmas": ["z:v4:split", 0], "latent_image": ["6", 0]}}
        g["z:v4:low"] = {"class_type": "SamplerCustom", "inputs": {
            **common, "add_noise": False, "noise_seed": int(seed),
            "sigmas": ["z:v4:extend", 0], "latent_image": ["z:v4:high", 0]}}
        g["9"]["inputs"]["samples"] = ["z:v4:low", 0]
    else:
        g["7"]["inputs"].update(model=[tail, 0], shift=settings["shift"])
        g["8"]["inputs"].update(seed=int(seed), steps=settings["steps"],
                                cfg=settings["cfg"], sampler_name=settings["sampler"],
                                scheduler=settings["scheduler"])
    g["10"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene)}"
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    info = {**model_job_info(model_entry, execution_profile),
            "text_encoder": base(clip_name), "vae": base(vae_name),
            **lora_job_info(entries, dropped),
            "size": f"{g['6']['inputs']['width']}x{g['6']['inputs']['height']}",
            "character": ch["name"] if ch else None}
    return g, cap, info


def build_anima(scene, seed, width=None, height=None, loras=(), overrides=(),
                standing=True, nsfw=False, model=None, aspect=None, mp=None,
                character=None, lora_plan=None):
    """Anima (Cosmos-Predict2 2B), ported from ComfyUI's shipped blueprint.

    Unlike the Z-Image recipes this one carries a REAL negative prompt: Anima
    runs at CFG 4, where a zeroed negative wastes the guidance it is tuned for.
    """
    g = json.loads(json.dumps(TEMPLATES["anima"]))
    model_entry = pick_recipe_model(model, "anima")
    set_unet_loader(g, "1", model_entry)
    variant = "turbo" if model_entry.get("variant") == "turbo" else "base"
    settings = ANIMA_SETTINGS[variant]
    clip_name = _pick_catalog_asset("text_encoders", (ANIMA_CLIP,),
                                    "Anima's Qwen3-0.6B base text encoder",
                                    recipe="Anima")
    vae_name = _pick_catalog_asset("vae", ANIMA_VAE_CANDIDATES,
                                   "the Qwen-Image VAE", recipe="Anima")
    set_clip_loader(g, "2", clip_name, "stable_diffusion")
    g["3"]["inputs"]["vae_name"] = vae_name

    # lock_generic: unlike the Z-Image recipes this model needs the closing
    # wardrobe clause even when no character anchor is in play (see above).
    cap, ch = _character_caption(scene, character, standing, nsfw,
                                 lock_generic=True)
    # Quality tags lead, scene follows: the model's examples all open this way,
    # and a bare prose sentence lands on an untagged region of its prior.
    lead = ANIMA_QUALITY_TAGS if nsfw else f"{ANIMA_QUALITY_TAGS}, {ANIMA_SFW_TAGS}"
    g["4"]["inputs"]["text"] = f"{lead}, {cap}"
    g["5"]["inputs"]["text"] = (ANIMA_NEGATIVE if nsfw
                                else f"{ANIMA_NEGATIVE}, {ANIMA_SFW_NEGATIVE}")

    if aspect and not (width and height):
        width, height = dims_for(aspect, mp or RECIPE_SPECS["anima"]["mp"])
    elif mp and not (width and height):
        width, height = dims_for(RECIPE_SPECS["anima"]["aspect"], mp)
    if width:
        g["6"]["inputs"]["width"] = int(width)
    if height:
        g["6"]["inputs"]["height"] = int(height)

    entries, dropped = resolve_recipe_lora_stack(
        "anima", loras, lora_plan, family="anima", variant=model_entry["variant"])
    tail = apply_lora_nodes(g, "1", entries, "an:lora")
    g["8"]["inputs"]["model"] = [tail, 0]
    g["8"]["inputs"].update(seed=int(seed), steps=settings["steps"],
                            cfg=settings["cfg"])
    g["10"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene)}"
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    info = {**model_job_info(model_entry, f"anima_{variant}"),
            "text_encoder": base(clip_name), "vae": base(vae_name),
            **lora_job_info(entries, dropped),
            "size": f"{g['6']['inputs']['width']}x{g['6']['inputs']['height']}",
            "character": ch["name"] if ch else None}
    return g, cap, info


def build_zimage(scene, seed, width=None, height=None, loras=(), overrides=(),
                 standing=True, nsfw=False, model=None, aspect=None, mp=None,
                 character=None, lora_plan=None):
    return _build_zimage("zimage", scene, seed, width, height, loras, overrides,
                         standing, nsfw, model, aspect, mp, character, lora_plan)


def build_fantasy(scene, seed, width=None, height=None, loras=(), overrides=(),
                  standing=True, nsfw=False, model=None, aspect=None, mp=None,
                  character=None, lora_plan=None):
    return _build_zimage("fantasy", scene, seed, width, height, loras, overrides,
                         standing, nsfw, model, aspect, mp, character, lora_plan)


def build_anime(scene, seed, width=None, height=None, loras=(), overrides=(),
                standing=True, nsfw=False, model=None, aspect=None, mp=None,
                character=None, lora_plan=None):
    return _build_zimage("anime", scene, seed, width, height, loras, overrides,
                         standing, nsfw, model, aspect, mp, character, lora_plan)


# Animate model picks. Ero10/Sulphur are NON-distilled LTX 2.3 finetunes (NSFW) -
# on the few-step distilled graph they need the distillation LoRA chained in or
# the render undercooks to mush.
LTX_MODELS = {
    "default": ("LTX2\\ltx-2.3-22b-distilled-1.1-Q8_0.gguf", False),
    "eros":    ("LTX2\\10Eros_v1.4-Q8_0.gguf", True),
    "sulphur": ("LTX2\\sulphur_dev-Q8_0.gguf", True),
}
LTX_DISTILL_LORA = "LTX\\ltx-2.3-22b-distilled-lora-384-1.1.safetensors"
# Clip length is bounded by VRAM and patience, not by the model: the audio latent
# node accepts up to 1000 frames, which is 33s even at 30fps. Frame rate is the
# graph's own (node 285) and is offered as a choice because it changes both the
# look and how many frames a given duration costs.
LTX_FPS_CHOICES = (24, 25, 30)
LTX_FPS_DEFAULT = 30                      # what templates/ltx_i2v.json ships at
LTX_FPS_RANGE = (8, 60)
LTX_SECONDS_RANGE = (2.0, 20.0)

# LTX 2.5: the official Comfy-Org I2V graph (templates/ltx25_i2v.json), ported
# with its two-pass pipeline intact. Frame rate stays at the graph's 24: the
# in-graph frame formula is fps*seconds+1, which only lands on the model's
# 8k+1 grid when fps is a multiple of 8, and 24 is also what keeps the audio
# track honest (see the H3 audio lesson - combine at anything else drifts).
LTX25_UNET = "LTX2\\ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
LTX25_CLIP = "LTX2\\gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
LTX25_CLIP_ENHANCER = "LTX2\\gemma4_e2b_it_bf16.safetensors"
LTX25_VIDEO_VAE = "LTX2\\ltx-2.5-video-vae-bf16.safetensors"
LTX25_AUDIO_VAE = "LTX2\\ltx-2.5-audio-vae-bf16.safetensors"
LTX25_UPSCALER = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"
# The community H3-upscale graph runs this 2.3-era IC lora on the 2.5
# transformer for extra texture; optional - the graph runs without it.
LTX25_DETAILER_LORA = "LTX\\ltx-2-19b-ic-lora-detailer.safetensors"
LTX25_SECONDS_RANGE = (2, 20)
LTX25_DEFAULT_SECONDS = 5     # node "20" in templates/ltx25_i2v.json
# The official graph sizes the canvas with a fixed 16:9 ResolutionSelector at
# 0.9MP; Pixal derives the same budget from the start frame's own aspect.
LTX25_CANVAS_MEGAPIXELS = 0.9
LTX25_CANVAS_MULTIPLE = 32
# The eviction gate between the refine sampler and the video decode.
#
# LTX 2.5's video VAE is not a conv decoder - it is a DIFFUSION decoder
# (comfy/ldm/lightricks/vae/na_diffusion_decoder.py) that runs attention blocks
# and is constructed lazily, at decode time. ComfyUI does not evict the sampled
# 22B DiT first, so ~20GB of transformer is still resident when the decoder asks
# for its own working set, and the decode OOMs INSIDE the tiled path - tiling
# cannot save a decode that has no room to start (Comfy-Org/ComfyUI#15606: same
# 32GB card, same model set, same cudaMallocAsync allocator; open on 0.32/0.33).
# --disable-dynamic-vram does not prevent it; it is already set in the launcher
# and this OOMed anyway.
#
# So the graph frees the transformer itself. This is the workaround confirmed in
# that thread, and being a NODE it also pins the ordering: ComfyUI cannot build
# the decoder before the gate has run. Pixal's own VRAM butler cannot cover this
# - it makes room BEFORE a job, and this is a mid-graph spike after sampling.
#
# Not a hard requirement: without KJNodes the builder rewires the decode straight
# back to the sampler and renders exactly as it did before.
LTX25_VRAM_GATE_NODE = "VRAM_Debug"
LTX25_VRAM_GATE_ID = "ltx25:vram"

# Animate is its own model surface. Video engines never become "supported" in
# model_profile(), because that flag is the still-image picker contract.
H3_MODEL_ID = "fl2va"
H3_MODEL = "Minimax H3\\minimax_h3_fl2va_pruned_int8_convrot.safetensors"
# The second architecture the same encoder/VAE stack serves: reference-to-video
# ("put THIS subject in a new scene"). The model chip IS the lane switch, per
# render - same family, different conditioning node and a different trained
# prompt format (brief 9.12).
H3_REF2V_MODEL_ID = "ref2va"
H3_REF2V_MODEL = "Minimax H3\\minimax_h3_ref2va_pruned_int8_convrot.safetensors"
# MiniMax's own caps, Pixal-enforced because the node will not: 9 images is the
# node schema's Autogrow max; 12 files across ALL types is the model card's
# Ref2VA row (the node alone would permit 15). v1 wires images only; the 12
# exists from day one so the deferred video/audio lanes inherit one constant.
H3_REF2V_MAX_IMAGES = 9
H3_REF2V_MAX_FILES = 12
H3_CLIP = "Qwen\\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
H3_VIDEO_VAE = "MiniMax-H3\\minimax_h3_video_vae_fp16.safetensors"
H3_AUDIO_VAE = "MiniMax-H3\\minimax_h3_audio_vae_fp32.safetensors"
H3_HMNSFW_LORA = "Minimax H3\\HMNSFW_AIO_V2.safetensors"
# Video LoRAs are deliberately not part of the still-image LoRA catalog contract.
# Each entry names the exact H3 execution variant it was published for; folder
# placement alone is never treated as architecture compatibility.
H3_VIDEO_LORAS = (
    {"name": H3_HMNSFW_LORA, "title": "HMNSFW AIO V2",
     "family": "minimax_h3", "variants": (H3_MODEL_ID,),
     "default_strength": 1.0, "trigger": "hmmotion",
     "description": "HMNSFW AIO V2 for MiniMax H3 FL2VA image/video generation.",
     "active_by_default": False},
)
# Turbo is a DISTILLATION, not a creative LoRA, so it is a speed mode rather
# than a row in the user's stack: it changes how many steps the model needs and
# therefore brings its own sampler and scheduler. Unlike the cache/forecast
# accelerators (Spectrum, EasyCache) it does not skip or approximate
# evaluations, which is why it does not carry their motion-deviation failure.
# The pack author's published numbers: 20 steps 39.9s -> 8 steps 23.4s.
H3_TURBO_LORA = "Minimax H3\\minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors"
H3_STEPS = 20
H3_SAMPLER = "res_multistep"
H3_SCHEDULER = "simple"
H3_TURBO = {"steps": 8, "sampler": "euler", "scheduler": "beta", "strength": 1.0}

H3_LENGTHS = (5, 10, 15)
H3_FRAMES = {5: 124, 10: 243, 15: 362}  # 24 fps, MiniMax's 17k+5 grid
H3_CANVAS_MULTIPLE = 32
H3_BASE_SHORT_EDGE = 768
H3_MAX_PIXELS = 768 * 1344
H3_ASPECT_TOLERANCE = 0.005

# Multishot rides ComfyUI-H3-Multishot, whose sampler runs the same stack the
# single-shot builder wires by hand; what it adds is the chain between shots.
H3_MULTISHOT_NODE = "H3MultishotSampler"
# Sparse attention for the H3 transformer (ComfyUI-PlagueKind-Nodes).
# Optional: absent, every H3 graph is built exactly as before.
H3_SLA_NODE = "H3SLAAttention"
# The node's own default, and the ratio its author validated. 0.85 is what
# lightx2v distilled the SLA turbo LoRA against; 0.95 is faster and visibly
# softer. Not exposed as a dial until there is a reason to move it.
H3_SLA_SPARSITY = 0.9
# 2x latent upscale of the finished render, re-sampled inside the SAME job by
# Comfyui-MMH3-UltimateUpscale: it needs the sampler's latent and Pixal does
# not store latents, so this is an option on the render, never an action on a
# finished clip. Opt-in - measured 140s -> 464s on a 928x1120 x 124-frame
# take (~3x), peaking at 30.9 GB of 32.6. The model-free
# MMH3LatentUpscaleParams path is deliberately NOT offered: it smears hair
# across the face in wet streaks ("v5 is broken", Jesse 2026-08-23), and both
# metrics had ranked that clip first, which is why this is written down as
# forbidden rather than left as an option.
H3_UPSCALE_NODE = "MMH3UltimateUpscale"
H3_LATENT_UPSCALER = "minimax_h3_latent_upscaler_3d_bf16.safetensors"
H3_UPSCALE_STEPS = 6
H3_UPSCALE_DENOISE = 0.22
H3_UPSCALE_TILE = 896
H3_UPSCALE_OVERLAP = 224
# The memory variant is a superset: it splits the KEYFRAME (the previous shot's
# last frame, which is all the plain sampler chains on) from MEMORY - a
# persistent anchor taken from the start of the chain plus the last N shot-end
# frames. The anchor is what holds identity, because every shot is conditioned
# on the ORIGINAL frame rather than on a copy of a copy. With both set to 0 it
# behaves exactly like the plain sampler.
H3_MULTISHOT_MEMORY_NODE = "H3MultishotMemorySampler"
H3_ANCHOR_FRAMES = 1                    # 0-2; 0 disables the identity anchor
H3_MEMORY_FRAMES = 2                    # 0-6 recent shot-end frames
H3_SHOTS_MAX = 8                        # the plain node's shot_count ceiling
H3_SHOT_SEPARATOR = "---"
_H3_SHOT_SPLIT = re.compile(r"(?m)^[ \t]*-{3,}[ \t]*$")
# Directors label their shots ("SHOT 1", "Shot 2:"). That label is not scene
# description - left in, it goes straight into the text encoder as literal
# conditioning. Requiring a separator or a line break after the number keeps
# "shot 1 of the roll" in a real sentence intact.
_H3_SHOT_LABEL = re.compile(
    r"^[ \t]*shot[ \t]*#?[ \t]*\d+[ \t]*(?:[:.–—-][ \t]*|\r?\n)", re.I)


# Measured here on 2026-08-13, one still and one seed, only these fields
# moving (sheets in Desktop\Pixal AB Renders). The headline was NEGATIVE: at a
# portrait close-up every one of these produces clean, individuated teeth, and
# the differences are close to noise. Framing dominates sampler. So these are
# offered as a SPEED ladder, not a quality ladder - pick by how long you are
# willing to wait, and frame tight either way.
# Every mode names the variants it can run. The distillation rungs are
# ("fl2va",) alone: their LoRAs are all fl2v distills, and the official
# ref2v 4-step LoRA is not on this machine (models/loras/Minimax H3/ holds
# four fl2v turbos and no ref2v, checked 2026-08-22). Quality carries both
# variants because ref2va IS quality at 20 steps - refusing it the quality id
# would refuse the only mode it has. A distillation asked on a ref2va chip is
# a 400 at /api/animate, never a silent fallback: the user picked a lane that
# can never honour it.
H3_SPEED_MODES = (
    {"id": "quality", "label": "Quality", "gloss": "20 steps, no distillation",
     "steps": H3_STEPS, "sampler": H3_SAMPLER, "scheduler": H3_SCHEDULER,
     "lora": None, "strength": 0.0, "title": None,
     "variants": (H3_MODEL_ID, H3_REF2V_MODEL_ID)},
    # Jesse's find: v4 at full strength was waxy, 0.8 restored skin texture.
    {"id": "turbo8", "label": "Turbo 8", "gloss": "8 steps, lightx2v v1.0 @0.8",
     "steps": 8, "sampler": "euler", "scheduler": "simple",
     "lora": "Minimax H3\\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
     "strength": 0.8, "title": "lightx2v Turbo 8-step v1.0",
     "variants": (H3_MODEL_ID,)},
    # Kijai's published recipe for the lightx2v distill (4 steps, 0.75,
    # er_sde or sa_solver). The 4-step file is the 768p-trained one, which
    # matches Pixal's 768 short edge.
    {"id": "turbo4", "label": "Turbo 4", "gloss": "4 steps, Kijai's recipe @0.75",
     "steps": 4, "sampler": "er_sde", "scheduler": "simple",
     "lora": "Minimax H3\\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
     "strength": 0.75, "title": "lightx2v Turbo 4-step v1.0 768p",
     "variants": (H3_MODEL_ID,)},
    # Superseded by the two above; kept so old jobs and the legacy turbo
    # toggle keep resolving to something real.
    {"id": "turbo_v4", "label": "Turbo v4 (old)", "gloss": "8 steps, superseded",
     "steps": H3_TURBO["steps"], "sampler": H3_TURBO["sampler"],
     "scheduler": H3_TURBO["scheduler"], "lora": H3_TURBO_LORA,
     "strength": H3_TURBO["strength"], "title": "MiniMax H3 Turbo v4",
     "variants": (H3_MODEL_ID,)},
)
H3_SPEED_DEFAULT = "quality"
H3_SPEED_LEGACY_TURBO = "turbo8"     # what a bare turbo=True now means


def h3_speed_mode(mode):
    """Resolve an id (or the legacy boolean) to a speed mode dict."""
    if mode is True:
        mode = H3_SPEED_LEGACY_TURBO
    elif mode is False or mode is None:
        mode = H3_SPEED_DEFAULT
    key = str(mode).strip().lower()
    return next((m for m in H3_SPEED_MODES if m["id"] == key), None)


def h3_speed_mode_options():
    """The speed ladder for the UI, each marked with whether its LoRA is here."""
    out = []
    for m in H3_SPEED_MODES:
        out.append({"id": m["id"], "label": m["label"], "gloss": m["gloss"],
                    "steps": m["steps"], "sampler": m["sampler"],
                    "available": m["lora"] is None
                                 or _video_asset("loras", m["lora"]) is not None})
    return out


def h3_turbo_available():
    """Whether any distillation the speed ladder offers is on disk."""
    return any(o["available"] for o in h3_speed_mode_options()
               if o["id"] != H3_SPEED_DEFAULT)


def h3_sla_available():
    """Whether the sparse-attention pack is installed.

    Same contract as h3_multishot_available(): before the first successful
    probe the answer is yes, so a cold start never hides the control, and a
    genuinely missing pack fails at queue time naming the node.
    """
    names = _COMFY_NODES["names"]
    return names is None or H3_SLA_NODE in names


def h3_sparse_active(sparse=True):
    """Sparse attention is on by default wherever the pack exists (Jesse,
    2026-08-23: "on by default, if its installed")."""
    return sparse is not False and h3_sla_available()


def apply_h3_sparse(graph, model_tail, sparse=True):
    """Sparse attention on the H3 transformer, AFTER the LoRA chain - the node
    requires that ordering, and a LoRA stacked on top of the patch would be
    applied to a model that no longer attends densely.

    Measured on this machine, 5090, 928x1120 x 124 frames, 20 steps
    res_multistep, everything else in the graph identical - four FULL runs
    alternating dense/sparse/dense/sparse on distinct seeds, warm process:

        Sage attention (before)   7.25, 7.23 s/step   (155.7s, 146.9s sampler)
        + sparse attention 0.9    5.42, 5.37 s/step   (110.0s, 109.1s)
                                                      1.34x, +/-0.3%

    An earlier figure of 1.51x (20.28 -> 13.47 s/step) was wrong in both the
    ratio and the absolute numbers: that harness interrupted each run after
    four progress ticks, which is the window where the weights are still
    streaming in over PCIe. It timed the load, not the loop.

    It engages only past the node's min_seq_len (8192 tokens), so short or
    low-resolution clips fall back to dense attention on their own. That is
    why the low-res reports see no change - and Pixal's canvases, 2MP over
    124 frames, are far past the threshold.

    Comfy Kitchen attention was measured on the same rig at 2.17 it/s against
    Sage's 2.15 and is deliberately NOT wired: it is a wash on Blackwell.
    """
    if not h3_sparse_active(sparse):
        return model_tail
    graph["h3:sla"] = {"class_type": H3_SLA_NODE, "inputs": {
        "model": [model_tail, 0],
        "sparsity_ratio": H3_SLA_SPARSITY,
        "block_size": "64"}}
    return "h3:sla"


def h3_upscale_available():
    """The pack AND the 3D latent upscaler weights. Unlike sparse attention
    this needs a 659 MB file on disk, so a cold probe is not enough on its
    own - the node list may be unprobed while the weights are simply absent."""
    names = _COMFY_NODES["names"]
    if names is not None and H3_UPSCALE_NODE not in names:
        return False
    return _video_asset("latent_upscale_models", H3_LATENT_UPSCALER) is not None


def h3_upscale_active(upscale=False):
    """2x is opt-in - the OPPOSITE of sparse attention's default, because it
    triples the cost of a render. Asking for it where it cannot run builds
    the plain graph rather than queueing a prompt that fails validation."""
    return bool(upscale) and h3_upscale_available()


def h3_tile_axis(size_px, target_tile=H3_UPSCALE_TILE,
                 target_overlap=H3_UPSCALE_OVERLAP):
    """(tile_px, overlap_px) for one axis of the 2x canvas, dividing EXACTLY.

    The pack tiles in latent units (pixels / 16) and its _grid_1d walks
    stride = tile - overlap from 0, clamping the last origin - so a grid that
    does not divide exactly leaves a SLIVER tile at the right and bottom
    edges, re-sampled semi-independently. That is what put coloured noise
    blocks in the corner of take 1. Pick n tiles and an overlap with
    n*tile - (n-1)*overlap == size exactly, in 32px units (the node's own
    step), closest to the measured 896/224 targets. Per axis, independently -
    the pack computes rows and columns separately.
    """
    s = size_px // 32
    best = None
    for n in range(2, 7):
        for v in range(4, 15):
            if (s + (n - 1) * v) % n:
                continue                     # would not divide exactly
            t = (s + (n - 1) * v) // n
            if t <= v:
                continue                     # overlap must be < tile
            score = abs(t * 32 - target_tile) + abs(v * 32 - target_overlap)
            if best is None or score < best[0]:
                best = (score, t, v)
    if best is None:
        raise ValueError(f"MiniMax H3 2x upscale cannot tile a {size_px}px axis")
    return best[1] * 32, best[2] * 32


def h3_speed_settings(turbo):
    """(steps, sampler, scheduler, lora rows) for the requested speed mode.

    Accepts a mode id ("turbo4"), the legacy boolean, or None. Falls back to
    the full 20-step path when a distillation is asked for but its LoRA is not
    installed - a missing distillation at 4 steps is not a slower render, it is
    an unusable one.
    """
    mode = h3_speed_mode(turbo)
    if mode is None or mode["lora"] is None:
        return H3_STEPS, H3_SAMPLER, H3_SCHEDULER, []
    canonical = _video_asset("loras", mode["lora"])
    if canonical is None:
        return H3_STEPS, H3_SAMPLER, H3_SCHEDULER, []
    row = {"name": canonical, "title": mode["title"],
           "strength": mode["strength"], "trigger": None, "role": "speed",
           "zone": "video", "source": "turbo", "locked": True}
    return mode["steps"], mode["sampler"], mode["scheduler"], [row]


def h3_multishot_available():
    """Whether ComfyUI-H3-Multishot is installed.

    Same contract as _video_upscale_node(): before the first successful probe
    the answer is yes, so a cold start never hides the control. A genuinely
    missing pack then fails at queue time naming the pack, which beats silently
    offering an engine that cannot run.
    """
    names = _COMFY_NODES["names"]
    return names is None or H3_MULTISHOT_NODE in names


def h3_multishot_node(anchor, memory):
    """Pick the sampler that can honour the requested memory settings.

    Older installs of the pack shipped only the plain sampler, so asking for an
    anchor there must fall back rather than queue a graph ComfyUI cannot run.
    """
    if anchor <= 0 and memory <= 0:
        return H3_MULTISHOT_NODE
    names = _COMFY_NODES["names"]
    if names is None or H3_MULTISHOT_MEMORY_NODE in names:
        return H3_MULTISHOT_MEMORY_NODE
    return H3_MULTISHOT_NODE


def split_shot_script(brief):
    """A motion brief -> its per-shot prompts, split on `---` on its own line.

    This is the node's own script format, so a brief written by the motion
    director and a brief typed by hand parse identically. Any "SHOT n" heading
    is dropped - it is a label for the reader, not something to condition on.
    """
    shots = []
    for part in _H3_SHOT_SPLIT.split(str(brief or "")):
        text = _H3_SHOT_LABEL.sub("", part.strip()).strip()
        if text:
            shots.append(text)
    return shots


def h3_frame_count(seconds):
    """One of the trained UI durations -> the matching 17k+5 frame count."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        raise ValueError("MiniMax H3 length must be 5, 10, or 15 seconds") from None
    if not value.is_integer() or int(value) not in H3_FRAMES:
        raise ValueError("MiniMax H3 length must be 5, 10, or 15 seconds")
    return H3_FRAMES[int(value)]


def h3_adapt_canvas(width, height):
    """Largest in-spec H3 canvas for a source aspect, ported from the proven tool."""
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise ValueError("MiniMax H3 needs a non-empty source image")
    ratio = width / height
    if ratio >= 1.0:
        nw, nh = H3_BASE_SHORT_EDGE * ratio, H3_BASE_SHORT_EDGE
    else:
        nw, nh = H3_BASE_SHORT_EDGE, H3_BASE_SHORT_EDGE / ratio
    if nw * nh > H3_MAX_PIXELS:
        scale = math.sqrt(H3_MAX_PIXELS / (nw * nh))
        nw, nh = nw * scale, nh * scale
    width = max(H3_CANVAS_MULTIPLE,
                round(nw / H3_CANVAS_MULTIPLE) * H3_CANVAS_MULTIPLE)
    height = max(H3_CANVAS_MULTIPLE,
                 round(nh / H3_CANVAS_MULTIPLE) * H3_CANVAS_MULTIPLE)
    # Scaling to the cap and THEN rounding up to the grid puts the canvas back
    # over it - a 9:19.5 phone frame landed 2.6% above, an ultrawide 2.1%. Walk
    # the long edge down until it fits; prepare_h3_frame's crop then squares the
    # aspect up, so the only cost is a slightly tighter crop.
    while width * height > H3_MAX_PIXELS:
        if width >= height and width > H3_CANVAS_MULTIPLE:
            width -= H3_CANVAS_MULTIPLE
        elif height > H3_CANVAS_MULTIPLE:
            height -= H3_CANVAS_MULTIPLE
        else:
            break
    return width, height


def prepare_h3_frame(src):
    """Stage a content-addressed, exact-canvas first frame in ComfyUI/input.

    MiniMaxH3ImageToVideo otherwise stretches a mismatched first frame. The same
    stretched tensor also goes through Qwen3-VL, so this is correctness, not a
    cosmetic resize. A cover crop is used only when 32-pixel canvas rounding
    changes aspect by more than 0.5 percent.
    """
    import numpy as np
    from PIL import Image

    src = Path(src)
    if not src.is_file():
        raise ValueError(f"source image is missing: {src.name}")
    digest = hashlib.sha1(src.read_bytes()).hexdigest()[:12]
    name = f"pixal_h3_{digest}.png"
    dst = CDIR / "input" / name
    if dst.is_file():
        with Image.open(dst) as staged:
            return name, *staged.size

    with Image.open(src) as opened:
        image = opened.convert("RGB")
    sw, sh = image.size
    width, height = h3_adapt_canvas(sw, sh)
    target_aspect, source_aspect = width / height, sw / sh
    error = abs(source_aspect - target_aspect) / target_aspect
    if error > H3_ASPECT_TOLERANCE:
        if source_aspect > target_aspect:
            crop_w, crop_h = int(round(sh * target_aspect)), sh
        else:
            crop_w, crop_h = sw, int(round(sw / target_aspect))
        left, top = (sw - crop_w) // 2, (sh - crop_h) // 2
        image = image.crop((left, top, left + crop_w, top + crop_h))

    # Float32 LANCZOS, matching the proven H3 tool without a resize-time uint8
    # round trip. The final PNG conversion happens once, after all three planes.
    source = np.asarray(image).astype(np.float32) / 255.0
    planes = [np.asarray(Image.fromarray(source[:, :, channel], mode="F").resize(
        (width, height), Image.Resampling.LANCZOS)) for channel in range(3)]
    prepared = np.clip(np.stack(planes, axis=-1), 0.0, 1.0)
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((prepared * 255.0 + 0.5).astype(np.uint8)).save(dst)
    return name, width, height


def _video_asset(kind, rel):
    """Return ComfyUI's exact catalog relpath for a normalized asset match."""
    wanted = str(rel or "").strip().replace("/", "\\").lower()
    return next((entry["rel"] for entry in model_catalog(kind)
                 if str(entry.get("rel") or "").replace("/", "\\").lower() == wanted),
                None)


def _h3_asset_paths(model_rel=None):
    """Resolve every fixed H3 dependency to the spelling emitted by the catalog,
    for THE PICKED BUILD's transformer file (the stock fl2va constant when
    unspecified). Encoder and both VAEs are shared across variants and stay
    fixed; the transformer is the lane, so a ref2va-only machine must not fail
    this check on the fl2va file it never needed."""
    build = model_rel or H3_MODEL
    label = ("MiniMax H3 FL2VA model" if build == H3_MODEL else
             "MiniMax H3 REF2VA model" if build == H3_REF2V_MODEL else
             f"MiniMax H3 model ({base(build)})")
    required = (
        ("model", "diffusion_models", build, label),
        ("clip", "text_encoders", H3_CLIP, "Qwen3-VL 32B MiniMax encoder"),
        ("video_vae", "vae", H3_VIDEO_VAE, "MiniMax H3 video VAE"),
        ("audio_vae", "vae", H3_AUDIO_VAE, "MiniMax H3 audio VAE"),
    )
    paths, missing = {}, []
    for key, kind, expected, label in required:
        canonical = _video_asset(kind, expected)
        if canonical is None:
            missing.append(label)
        else:
            paths[key] = canonical
    return paths, missing


def _h3_finetune_label(stem):
    """Filename stem -> chip label: drop the packaging words, keep the identity."""
    drop = {"h3", "fl2va", "ref2va", "pruned", "int8", "convrot", "comfyui", "minimax"}
    words = [w for w in stem.replace("-", "_").split("_")
             if w and w.lower() not in drop]
    return " ".join(words).title() or stem


def h3_model_options():
    """Every FL2VA and REF2VA build on disk, stock first - each is an Animate
    model chip, and the chip IS the lane switch (brief 9.12: per render, one
    lane, chosen by weights).

    Finetunes of either architecture (anything carrying "fl2va" or "ref2va"
    in its filename under diffusion_models) share H3's encoder, VAEs and LoRA
    catalog, so dropping one beside the stock weights is all it takes to get a
    chip. The stock files keep the legacy "fl2va"/"ref2va" ids so old ledger
    entries and rerolls keep resolving; finetune ids are their lowercase
    filename stems for the same reason - stable across restarts and rescans.

    Both stock chips are listed even when the scan finds nothing: selection
    and validation must be able to NAME the stock builds on a bare machine
    (the ids are the ledger's legacy spellings). That never queues a render
    against absent weights - _h3_asset_paths() stays the disk-driven
    availability gate, and it runs only after the id resolves.
    """
    stock = {
        str(H3_MODEL).replace("/", "\\").lower(): (
            H3_MODEL_ID, "FL2VA",
            "First-frame video with native synchronized audio."),
        str(H3_REF2V_MODEL).replace("/", "\\").lower(): (
            H3_REF2V_MODEL_ID, "REF2VA",
            "Reference-to-video: this subject, carried into a new scene, with "
            "native synchronized audio."),
    }
    found = {}
    finetunes = []
    for entry in model_catalog("diffusion_models"):
        rel = str(entry.get("rel") or "")
        low = rel.replace("/", "\\").lower()
        name = low.rsplit("\\", 1)[-1]
        if not name.endswith(".safetensors") or \
                ("fl2va" not in name and "ref2va" not in name):
            continue
        if low in stock:
            found[low] = rel
            continue
        stem = rel.replace("/", "\\").rsplit("\\", 1)[-1][:-len(".safetensors")]
        variant = "ref2va" if "ref2va" in name else "fl2va"
        finetunes.append({
            "id": name[:-len(".safetensors")], "rel": rel,
            "label": _h3_finetune_label(stem),
            "description": f"Community {variant.upper()} finetune - same encoder, "
                           "VAEs and LoRA catalog as stock."})
    options = []
    for low, (chip_id, label, description) in stock.items():
        options.append({"id": chip_id, "rel": found.get(low) or
                        (H3_MODEL if chip_id == H3_MODEL_ID else H3_REF2V_MODEL),
                        "label": label, "description": description})
    return options + finetunes


def h3_model_rel(model_id):
    """Chip id -> catalog rel of that build, or None for an unknown id."""
    mid = str(model_id or H3_MODEL_ID).strip().lower()
    return next((o["rel"] for o in h3_model_options() if o["id"] == mid), None)


def h3_model_variant(model_id):
    """Chip id -> its lane: "fl2va" or "ref2va", None for an unknown id.

    Precedence, matched on the lowercased basename (the scan already
    lowercases): an exact stock basename first - there are two now, and each
    maps to its own variant by definition - then "ref2va" in the name, then
    "fl2va". A future finetune carrying BOTH tokens therefore lands in ref2va,
    deterministically and on purpose (9.0 trap #6)."""
    rel = h3_model_rel(model_id)
    if rel is None:
        return None
    name = str(rel).replace("/", "\\").lower().rsplit("\\", 1)[-1]
    if name == H3_MODEL.replace("/", "\\").lower().rsplit("\\", 1)[-1]:
        return H3_MODEL_ID
    if name == H3_REF2V_MODEL.replace("/", "\\").lower().rsplit("\\", 1)[-1]:
        return H3_REF2V_MODEL_ID
    if "ref2va" in name:
        return H3_REF2V_MODEL_ID
    if "fl2va" in name:
        return H3_MODEL_ID
    return None


def video_lora_profile(name):
    """Classify a video LoRA by an explicit compatibility record.

    Video model families are not interchangeable. In particular, an LoRA found
    in a MiniMax-named folder is not thereby safe for REF2VA or a still graph.
    """
    wanted = str(name or "").strip().replace("/", "\\").lower()
    spec = next((entry for entry in H3_VIDEO_LORAS
                 if entry["name"].lower() == wanted), None)
    if not spec:
        return {"name": str(name or ""), "family": "unknown", "variants": [],
                "engine": None, "supported": False}
    return {**spec, "variants": list(spec["variants"]), "engine": "h3",
            "supported": True}


def h3_video_lora_options(model_id=H3_MODEL_ID):
    """Public, add-only catalog for the selected H3 FL2VA build."""
    variant = h3_model_variant(model_id)
    return [
        {"name": spec["name"], "title": spec["title"],
         "default_strength": spec["default_strength"],
         "trigger": spec.get("trigger"), "description": spec["description"],
         "active_by_default": bool(spec.get("active_by_default")),
         "available": bool(_video_asset("loras", spec["name"]))}
        for spec in H3_VIDEO_LORAS if variant in spec["variants"]
    ]


def validate_video_lora_plan(engine_id, model_id, plan):
    """Validate the isolated Animate LoRA contract and literal chain order."""
    if plan is None:
        return None
    variant = h3_model_variant(model_id) if engine_id == "h3" else None
    if variant is None:
        raise ValueError("video lora_plan is only supported by MiniMax H3 FL2VA builds")
    if not isinstance(plan, dict):
        raise ValueError("video lora_plan must be an object")
    if plan.get("version") != 1 or plan.get("mode") != "replace":
        raise ValueError("unsupported video lora_plan version or mode")
    if plan.get("engine") != engine_id or plan.get("model") != model_id:
        raise ValueError("video lora_plan does not match the selected engine and model")
    entries = plan.get("entries")
    if not isinstance(entries, list) or len(entries) > 64:
        raise ValueError("video lora_plan entries must be an array of at most 64 items")
    allowed = {entry["name"].lower(): entry for entry in H3_VIDEO_LORAS
               if variant in entry["variants"]}
    seen = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"video lora_plan entry {i + 1} must be an object")
        name = str(entry.get("name") or "").strip().replace("/", "\\")
        key = name.lower()
        if not name or key not in allowed:
            # the variant names the lane, so a ref2va render refusing an
            # FL2VA-only LoRA says which fence it hit
            raise ValueError(f"video LoRA is not compatible with MiniMax H3 "
                             f"{variant.upper()}: {name or 'missing name'}")
        if key in seen:
            raise ValueError(f"duplicate video LoRA in chain: {name}")
        seen.add(key)
        if "enabled" in entry and not isinstance(entry["enabled"], bool):
            raise ValueError(f"video lora_plan entry {i + 1} enabled must be boolean")
        _lora_strength(entry.get("strength", allowed[key]["default_strength"]), name)
        if entry.get("enabled", True) and not _video_asset("loras", allowed[key]["name"]):
            raise ValueError(f"MiniMax H3 video LoRA is not installed: {name}")
    return plan


def resolve_h3_video_lora_stack(plan=None, model_id=H3_MODEL_ID):
    """Resolve enabled rows only, preserving the UI's literal top-to-bottom order."""
    if plan is None:
        return []
    validate_video_lora_plan("h3", model_id, plan)
    allowed = {entry["name"].lower(): entry for entry in H3_VIDEO_LORAS}
    stack = []
    for item in plan["entries"]:
        if item.get("enabled") is False:
            continue
        spec = allowed[str(item["name"]).replace("/", "\\").lower()]
        canonical = _video_asset("loras", spec["name"])
        if canonical is None:
            raise ValueError(f"MiniMax H3 video LoRA is not installed: {spec['name']}")
        stack.append({"name": canonical, "title": spec["title"],
                      "strength": _lora_strength(
                          item.get("strength", spec["default_strength"]), spec["name"]),
                      "trigger": spec.get("trigger"), "role": "motion",
                      "zone": "video", "source": "user", "locked": False})
    return stack


# ---- VRAM profiles ----------------------------------------------------------
# Tier detection + honest per-engine minimums. ONLY measured entries belong in
# VRAM_MINIMUMS - a guessed threshold lies in both directions, and "not on this
# card" claims cost trust. The butler remains the runtime enforcement layer;
# profiles are the advisory layer for pickers, setup, and community testers.
VRAM_TIERS = ((30.0, "32"), (22.0, "24"), (14.0, "16"))

# engine id -> (min_gb, measured consequence). H3: 100% GPU at ~160W with 0%
# memory-controller utilisation below ~25GB free means it is streaming weights,
# not rendering - measured ~5x slower on the 5090 starvation session.
VRAM_MINIMUMS = {
    "h3": (24.0, "it still runs, but streams weights instead of holding them "
                 "- about 5x slower"),
    # 21.5GB INT8 transformer + 15.4GB text encoder; the encoder unloads
    # before sampling but the transformer alone already fills a 24GB card.
    "ltx25": (24.0, "it still runs, but streams weights instead of holding "
                    "them - expect the H3-style slowdown"),
}


def vram_tier(total_gb):
    """Bucket a card's total VRAM into a profile tier; None when unknown."""
    try:
        total_gb = float(total_gb)
    except (TypeError, ValueError):
        return None
    if total_gb <= 0:
        return None
    for floor, tier in VRAM_TIERS:
        if total_gb >= floor:
            return tier
    return "low"


def _tier_gb(tier):
    # "low" compares as 12: under every minimum we would ever assert, and the
    # exact number never shows in copy (notes quote the detected GB instead).
    return {"32": 32.0, "24": 24.0, "16": 16.0, "low": 12.0}.get(tier)


def vram_profile_state():
    """The whole story for options/settings: what the card reads as, what the
    user pinned, and which tier is in force."""
    profile = load_config().get("vram_profile") or "auto"
    detected_gb = (HUB.gpu or {}).get("total")
    detected = vram_tier(detected_gb)
    return {"profile": profile, "detected_gb": detected_gb,
            "detected": detected,
            "effective": detected if profile == "auto" else profile}


def vram_fit_note(engine_id):
    """None when the effective profile fits (or nothing is measured for this
    engine). Honest advisory text otherwise - never a block."""
    entry = VRAM_MINIMUMS.get(engine_id)
    if not entry:
        return None
    need, consequence = entry
    state = vram_profile_state()
    cap = _tier_gb(state["effective"])
    if cap is None or cap >= need:
        return None
    if state["profile"] == "auto":
        return (f"wants {need:g} GB+ of VRAM and this card reads as "
                f"{state['detected_gb']:g} GB - {consequence}")
    return (f"wants {need:g} GB+ of VRAM and the pinned profile is "
            f"{state['profile']} GB - {consequence}")


def video_engine_options():
    """Data-driven Animate choices, separate from the still model catalog."""
    # LTX 2.3 (and its eros/sulphur finetunes) left the picker 2026-08-12 -
    # two chips only, and 2.5 is the LTX. The 2.3 builder and template stay
    # for rerolling old history cards.
    ltx25_missing = [label for label, kind, rel in (
        ("LTX 2.5 transformer", "diffusion_models", LTX25_UNET),
        ("Gemma 4 text encoder", "text_encoders", LTX25_CLIP),
        ("Gemma 4 prompt enhancer", "text_encoders", LTX25_CLIP_ENHANCER),
        ("LTX 2.5 video VAE", "vae", LTX25_VIDEO_VAE),
        ("LTX 2.5 audio VAE", "vae", LTX25_AUDIO_VAE),
        ("LTX 2.5 spatial upscaler", "latent_upscale_models", LTX25_UPSCALER),
    ) if not _video_asset(kind, rel)]
    # Same optimistic contract as multishot: before the first node probe the
    # answer is yes; a genuinely old ComfyUI then fails at queue time by name.
    names = _COMFY_NODES["names"]
    if names is not None and "LTXVDualCFGGuider" not in names:
        ltx25_missing.append("ComfyUI v0.31+ (LTX 2.5 nodes)")
    ltx25_available = not ltx25_missing

    # Per-chip availability keeps its everyday meaning: whether THAT chip can
    # render - the shared encoder/VAEs plus its own transformer file (the
    # transformer is the lane, so a ref2va-only machine must not fail on the
    # fl2va file). The engine is available when ANY chip is.
    h3_chips = h3_model_options()
    h3_chip_available = {}
    for opt in h3_chips:
        _, chip_missing = _h3_asset_paths(opt["rel"])
        h3_chip_available[opt["id"]] = not chip_missing
    _, h3_missing = _h3_asset_paths()
    h3_available = any(h3_chip_available.values())
    if h3_available:
        h3_missing = []
    else:
        h3_missing = ["a MiniMax H3 model build (FL2VA or REF2VA)"
                      if label == "MiniMax H3 FL2VA model" else label
                      for label in h3_missing]
    h3_vram_note = vram_fit_note("h3")
    engines = [
        # Both engines generate sound - LTX through its audio VAE, H3 natively - so
        # the chips differentiate on take length, not on audio, which used to read
        # as though only H3 had any.
        # No fps_choices on purpose: the 2.5 graph computes fps*seconds+1
        # frames internally, and 24 is the rate that both stays on the 8k+1
        # grid and keeps the audio latent in step.
        {"id": "ltx25", "label": "LTX 2.5", "tag": "pixel diffusion · audio",
         "description": "Lightricks' keyframes-first generation: sharper faces "
                        "and text, synchronized audio, two-pass upscale built in.",
         "lengths": [{"s": 3, "label": "3s", "gloss": "a beat"},
                     {"s": 5, "label": "5s", "gloss": "a moment"},
                     {"s": 8, "label": "8s", "gloss": "a take"},
                     {"s": 12, "label": "12s", "gloss": "a long take"},
                     {"s": 15, "label": "15s", "gloss": "a scene"}],
         "models": [{"id": "default", "label": "Distilled",
                     "available": ltx25_available,
                     "description": "LTX 2.5 22B distilled INT8; the official "
                                    "two-pass graph with the x2 latent upscaler."}],
         "vram_min_gb": VRAM_MINIMUMS["ltx25"][0],
         **({"vram_note": vram_fit_note("ltx25")} if vram_fit_note("ltx25") else {}),
         # The note is actionable when the family has a curated lighter build.
         **({"quant_hint": True} if _quant_family("ltx25") else {}),
         "available": ltx25_available, "missing": ltx25_missing},
        {"id": "h3", "label": "MiniMax H3", "tag": "long takes · audio",
         "description": "FL2VA/REF2VA video with synchronized generated sound, "
                        "and the longer takes of the two engines.",
         "lengths": [{"s": 5, "label": "5s", "gloss": "a scene"},
                     {"s": 10, "label": "10s", "gloss": "a full take"},
                     {"s": 15, "label": "15s", "gloss": "a long take"}],
         # Per-shot length. Multishot chains up to H3_SHOTS_MAX of these takes,
         # each starting from the previous one's last frame.
         "shots_max": H3_SHOTS_MAX if h3_multishot_available() else 1,
         # Opt-in, and only offered when the distillation is actually on disk -
         # asking for 8 steps without it is an unusable render, not a fast one.
         # "turbo" stays for the old boolean toggle (it now means turbo8);
         # "speed_modes" is the full ladder with per-mode availability.
         "turbo": h3_turbo_available(),
         "speed_modes": h3_speed_mode_options(),
         "speed_default": H3_SPEED_DEFAULT,
         # Sparse attention: 1.51x measured here, and ON wherever the pack is
         # installed. The row hides entirely when it is not, rather than
         # offering a toggle that cannot do anything.
         "sparse": h3_sla_available(),
         "sparse_default": True,
         # 2x upscale: opt-in (~3x the render's time), offered only when the
         # pack AND its 659 MB 3D upscaler weights are both installed. It
         # rides inside the render job - Pixal does not store latents, so it
         # can never be an action on a finished clip.
         "upscale_2x": h3_upscale_available(),
         # One chip per FL2VA or REF2VA build on disk (stock first) - drop a
         # finetune beside the stock weights and it appears here after a rescan.
         "models": [{"id": opt["id"], "label": opt["label"],
                     "available": h3_chip_available[opt["id"]],
                     "description": opt["description"],
                     "loras": h3_video_lora_options(opt["id"])}
                    for opt in h3_chips],
         "vram_min_gb": VRAM_MINIMUMS["h3"][0],
         **({"vram_note": h3_vram_note} if h3_vram_note else {}),
         **({"quant_hint": True} if _quant_family("h3") else {}),
         "available": h3_available, "missing": h3_missing},
    ]
    # The Settings-chosen default engine. A FLAG, not a reorder: the popup's
    # chip order stays stable while the default moves, or picking a default
    # would visibly shuffle the buttons underneath the user.
    video_cfg = load_config().get("video") or {}
    want = video_cfg.get("default_engine") or ""
    for engine in engines:
        if engine["id"] == want:
            engine["default"] = True
    # The default model, same discipline: flag the chip, never reorder the
    # list. The popup opens on it, and switching back to its engine lands on
    # it again.
    want_model = video_cfg.get("default_model") or ""
    for engine in engines:
        for model in engine["models"]:
            if model["id"] == want_model:
                model["default"] = True
    return engines


# ---- Quant finder ----------------------------------------------------------
# vram_fit_note tells the user their card sits under an engine's measured
# floor; this is the way OUT of that note: a lighter build of the SAME model,
# fetched from a curated HF repo. Never a local conversion - community-
# calibrated quants (convrot INT8, GGUF K-quants) beat a local cast, and a
# user who cannot fit the model must not be asked to download its 45GB bf16
# source first.
#
# family -> ordered (repo, format, prefix) sources. The prefix pins WHICH of
# a repo's files are on the ladder (the Lightricks repo also carries the 45GB
# bf16 source under the same root); sizes come from the HF API at request
# time, never hardcoded here.
QUANT_SOURCES = {
    "ltx25": [("Lightricks/LTX-2.5", "int8_convrot",
               "diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot"),
              ("Abiray/LTX-2.5-Distilled-GGUF", "gguf", None),
              ("DmitryDB/LTX-2.5-ComfyUI-Quants", "nvfp4", "diffusion_models/")],
    "ltx": [("QuantStack/LTX-2.3-GGUF", "gguf", None)],
}
# Both LTX engines install their transformer builds into the same subfolder.
QUANT_FAMILY_SUBDIRS = {"ltx25": "LTX2", "ltx": "LTX2"}
# One download at a time: these are tens of GB, and a second stream just
# doubles the wall time of the first on a home link.
QUANT_FETCH = {"task": None}
QUANT_FIT_RATIO = 0.8   # latents + the VAE need the rest of the card


def _quant_family(engine_id):
    """The curated lighter-build family for a video engine, when one exists."""
    return engine_id if engine_id in QUANT_SOURCES else None


def pick_quant_rung(files, budget_gb):
    """Annotate the ladder with fits/picked against a VRAM budget in GB.

    The pick: convrot INT8 when it fits, else the largest GGUF rung that fits
    (a bigger rung is a better rung), else nothing - every entry then reads
    fits: false so the UI can say "nothing fits N GB". NVFP4 entries are
    listed with blackwell_only and are NEVER auto-picked.
    """
    limit = QUANT_FIT_RATIO * float(budget_gb) * 1e9
    ladder = []
    for f in files:
        entry = dict(f)
        entry["fits"] = entry["size"] <= limit
        entry["picked"] = False
        if entry["format"] == "nvfp4":
            entry["blackwell_only"] = True
        ladder.append(entry)
    fitting = [entry for entry in ladder
               if entry["fits"] and entry["format"] != "nvfp4"]
    int8 = [entry for entry in fitting if entry["format"] == "int8_convrot"]
    gguf = [entry for entry in fitting if entry["format"] == "gguf"]
    chosen = max(int8 or gguf, key=lambda entry: entry["size"], default=None)
    if chosen is not None:
        chosen["picked"] = True
    return ladder


def _hf_headers():
    """Authorization for gated repos, when the user has an HF token around."""
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        try:
            cached = Path.home() / ".cache" / "huggingface" / "token"
            if cached.is_file():
                token = cached.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _hf_repo_files(repo):
    """The repo's file list with real byte sizes (?blobs=true). Raises on any
    network/API failure - the route turns that into a graceful ok: false."""
    url = f"https://huggingface.co/api/models/{repo}?blobs=true"
    async with aiohttp.ClientSession(headers=_hf_headers()) as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                raise aiohttp.ClientError(f"{repo}: HTTP {r.status}")
            data = await r.json(content_type=None)
    return data.get("siblings") or []


def _quant_candidates(repo, fmt, prefix, siblings):
    """Filter a repo's file list down to the ladder entries its row means."""
    kind = (prefix or "").split("/", 1)[0] or "diffusion_models"
    out = []
    for sib in siblings:
        rel = str(sib.get("rfilename") or "")
        size = sib.get("size")
        if not rel or isinstance(size, bool) or not isinstance(size, int) \
                or size <= 0:
            continue
        if prefix and not rel.startswith(prefix):
            continue
        if Path(rel).suffix.lower() not in MODEL_EXTS:
            continue
        # an nvfp4 row must not mislabel the repo's other builds
        if fmt == "nvfp4" and "nvfp4" not in rel.lower():
            continue
        out.append({"repo": repo, "filename": rel, "size": size,
                    "format": fmt, "kind": kind})
    out.sort(key=lambda entry: -entry["size"])   # biggest rung first per repo
    return out


def _quant_safe_relpath(name):
    """A repo-relative filename we will both fetch and write: no traversal, no
    absolute paths, model weights only - this route is not a generic downloader."""
    if not name or name != name.strip() or "\\" in name or ":" in name:
        return False
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    return Path(parts[-1]).suffix.lower() in MODEL_EXTS


async def _quant_fetch_run(repo, filename, kind):
    """The download itself. Progress rides quant_fetch broadcasts; only a
    byte-count-verified completion renames the .part into place."""
    def say(got, total, done=False, error=None):
        HUB.broadcast(type="quant_fetch", repo=repo, filename=filename,
                      got=got, total=total, done=done, error=error)

    family = next(fam for fam, sources in QUANT_SOURCES.items()
                  if any(source_repo == repo for source_repo, _fmt, _pre in sources))
    dest_dir = CDIR / "models" / kind / QUANT_FAMILY_SUBDIRS[family]
    dest = dest_dir / filename.rsplit("/", 1)[-1]
    part = dest.with_name(dest.name + ".part")
    url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
    got, total, said = 0, None, 0
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        async with aiohttp.ClientSession(headers=_hf_headers()) as s:
            # no total timeout: a 20GB build on a slow link takes what it takes;
            # the socket-read timeout is what catches a stalled stream
            async with s.get(url, timeout=aiohttp.ClientTimeout(
                    total=None, connect=15, sock_read=120)) as r:
                if r.status != 200:
                    raise aiohttp.ClientError(f"{repo}: HTTP {r.status}")
                length = r.headers.get("Content-Length")
                total = int(length) if length else None
                say(0, total)
                with part.open("wb") as fh:
                    async for chunk in r.content.iter_chunked(1 << 22):
                        await asyncio.to_thread(fh.write, chunk)
                        got += len(chunk)
                        if got - said >= 32 * 2**20:   # the UI reads GB anyway
                            said = got
                            say(got, total)
        if total is not None and got != total:
            raise aiohttp.ClientError(f"truncated at {got} of {total} bytes")
        os.replace(part, dest)
        _CATALOG["at"] = 0            # the new build lists without a rescan
        say(got, total, done=True)
    except Exception as exc:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        say(got, total, error=str(exc))


def h3_cut_plan(shots, seconds):
    """(total seconds, cut times) when N shots fit ONE generation, else None.

    Measured on the same still, same script, three ways: the chained samplers
    took 814s (identity gone by shot 3) and 985s (identity held), while a single
    362-frame pass with H3's own internal cuts took 677s and held identity best.
    Chaining re-enters through the previous last frame, so it can only ever morph
    between shots - a real cut is impossible - and it pays a text encode per
    shot. Below H3's 15s ceiling the single pass wins on speed, identity AND
    cuts, so the chain is reserved for lengths one generation cannot reach.
    """
    try:
        shots, seconds = int(shots), int(seconds)
    except (TypeError, ValueError):
        return None
    total = shots * seconds
    if shots < 2 or total not in H3_FRAMES:
        return None
    return total, [seconds * i for i in range(1, shots)]


def h3_cut_timestamp(seconds):
    """Seconds -> H3's MM:SS.mmm cut-time format."""
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}.000"


# The timestamp half is deliberately LOOSE on digit counts: a malformed stamp
# like 00:5.0 is exactly what needs replacing, and a strict pattern would leave
# it sitting next to the corrected one.
_H3_CUT_MARKER = re.compile(
    r"(?im)^[ \t]*\[[ \t]*shot[ \t]*(\d+)[ \t]*\][ \t]*"
    r"(?:at[ \t]+(\d{1,2}:\d{1,2}(?:\.\d{1,3})?)[ \t]*,?[ \t]*)?")


def normalise_cut_timeline(text, cut_times):
    """Force a written timeline onto the cut times we actually planned.

    The director is asked for exact timestamps and will sometimes drift: a cut
    past the end of the clip, a malformed 00:5.0, or a stamp on shot 1 (which
    H3's format forbids). None of that is recoverable at the sampler - it just
    silently mis-cuts. Since the planned times are already known exactly, the
    honest repair is arithmetic rather than a second LLM round: renumber the
    markers in order and stamp each with its planned time.
    """
    body = str(text or "")
    if not _H3_CUT_MARKER.search(body):
        return body                      # no timeline written - leave it alone
    index = {"n": 0}

    def restamp(match):
        number = index["n"]
        index["n"] += 1
        if number == 0:
            return "[Shot 1] "           # shot 1 never carries a timestamp
        if number - 1 >= len(cut_times):
            return f"[Shot {number + 1}] "
        return f"[Shot {number + 1}] At {h3_cut_timestamp(cut_times[number - 1])}, "

    return _H3_CUT_MARKER.sub(restamp, body)


def compile_cut_script(shots, cut_times):
    """Per-shot prompts -> one timeline with H3's native hard cuts.

    Shot 1 carries no timestamp (H3's rule); each later shot opens with its cut
    time and an explicit cut verb, which is what makes it a cut rather than the
    continuous drift H3 falls into when the transition is left unstated.
    """
    parts = [f"[Shot 1] {shots[0].strip()}"]
    for index, text in enumerate(shots[1:]):
        at = h3_cut_timestamp(cut_times[index]) if index < len(cut_times) else None
        head = f"[Shot {index + 2}]"
        parts.append(f"{head} At {at}, the shot cuts to {text.strip()}"
                     if at else f"{head} {text.strip()}")
    return "\n\n".join(parts)


# The i2va alignment header is arithmetic, so the director is never asked to
# write it. Ported verbatim from the official guide (MiniMaxAI/MiniMax-H3
# docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md): this line binds <Picture 1> -
# the keyframe the ComfyUI node tokenizes alongside the prompt - to frame zero.
H3_I2VA_HEADER = ("For the target video, at 0.00 seconds into the target video, "
                  "<Picture 1> (from [Shot 1]) is fully referenced.")

_H3_DESC_FIELD_RE = re.compile(r"(?im)^\s*integrated_multimodal_description\s*:")
# The ref2va lane names its body field detailed_description: (ref guide §5.2).
# The 9.9 repairs key on the FIELD SPAN, so the span matcher widens to both
# names - a SEPARATE alternation, because _H3_DESC_FIELD_RE is shared with
# assemble_h3_prompt's wrap gate and widening it in place would change fl2va
# behaviour on any input containing the ref2va field name (brief 9.12 Task 4).
_H3_DESC_FIELD_RE_ANY = re.compile(
    r"(?im)^\s*(?:integrated_multimodal_description|detailed_description)\s*:")
_H3_SOUND_FIELD_RE = re.compile(r"(?im)^\s*overall_soundscape\s*:")
_H3_MUSIC_FIELD_RE = re.compile(r"(?im)^\s*non_diegetic_music\s*:")
_H3_HEADER_RE = re.compile(
    r"(?i)^\s*(?:for the target video|how the reference pictures align)")


def h3_alignment_header(last_frame=False, seconds=None):
    """The deterministic alignment line the trained format opens with.

    Both strings are ported VERBATIM from the official guide. Its bracket
    conventions are inconsistent on purpose - i2va uses <Picture 1>/[Shot 1],
    fl2va uses bare Picture 1/Shot 1 - and verbatim beats tidy on a trained
    format. A bridge is always one continuous take, so Picture 2 is from
    Shot 1 at the clip's exact final second.
    """
    if not last_frame:
        return H3_I2VA_HEADER
    mark = f"{float(seconds or 5):.2f}"
    return ("How the reference pictures align with the target video — "
            "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the "
            "target video; Picture 2 (from Shot 1) aligns with the "
            f"{mark}-second mark of the target video.")


def h3_slug_source(brief):
    """Filename label from the description content, never the fixed header
    (which would name every H3 clip 'for_the_target_video'). The ref2va lane's
    field is detailed_description:, and its value leads with the pinned style
    sentence - skip both, or every ref2va clip would be named after them."""
    text = str(brief or "")
    if "detailed_description:" in text:
        text = text.split("detailed_description:")[-1]
        text = re.sub(r"(?i)^\s*the target video is in [^.]*\.\s*", "", text)
    else:
        text = text.split("integrated_multimodal_description:")[-1]
    return re.sub(r"(?i)^\s*\[\s*shot\s*1\s*\]\s*", "", text.strip())


# Every `(Sn) says:` cue whose line arrived in plain quotes instead of the
# trained tag syntax (the 4B brain's standard failure: 6/6 harness samples,
# 2026-08-12). Curly and straight quotes both appear in the wild.
_H3_UNTAGGED_SAYS_RE = re.compile(
    r"(\(S\d+\)\s*says\s*:\s*)(?!\s*<d>)[\"“]([^\"”]+)[\"”]", re.S)
_H3_UNLANGUAGED_TAG_RE = re.compile(
    r"<d>\s*(?!\[)[\"“]?(.*?)[\"”]?\s*</d>", re.S)
_H3_PROPER_TAG_RE = re.compile(r"<d>\[[A-Za-z]+\][^<]*</d>")

# The language-token map is CLOSED, not a guesser: history.jsonl has only ever
# produced [English] (41 briefs) and [EN] (2), so EN normalizes and every
# unknown code passes through byte-identical. Inventing an expansion for a
# code nobody has seen is the same writing-from-memory mistake as a constant
# slot (brief 9.9).
_H3_LANG_TOKENS = {"EN": "English"}
_H3_LANG_TAG_RE = re.compile(r"<d>\[([A-Za-z]+)\]")

# Delivery prose stranded INSIDE the tag (history.jsonl b63b6345 shipped
# `<d>[English] Do not watch," she mutters, ...</d>` - the mirror of the
# trailing-prose failure) is direction the director meant to give: relocate it
# BEFORE the tag, never strip it. The signature is closed and conservative -
# an orphan closing quote with its attribution comma ADJACENT (English puts
# the comma inside the quotes, `watch," she`; the brain emits both orders),
# and an attribution verb from this list within the next few words. Anything
# else (balanced quotes, no comma, a verb off the list) is left untouched,
# because legitimate dialogue quoting somebody else must survive.
_H3_ATTRIBUTION_VERBS = frozenset({
    "says", "said", "mutters", "muttered", "whispers", "whispered",
    "shouts", "shouted", "adds", "added", "replies", "replied",
    "asks", "asked"})
_H3_TAG_BLOCK_RE = re.compile(r"<d>(\[[A-Za-z]+\].*?)</d>", re.S)
_H3_ORPHAN_QUOTE_RE = re.compile("[\"\u201d]")


def _h3_relocate_intag_prose(m):
    """Move orphaned delivery prose out of a <d> block; see the table above."""
    content = m.group(1)
    for q in _H3_ORPHAN_QUOTE_RE.finditer(content):
        earlier = content[:q.start()]
        # A closing quote with an opening partner earlier in the tag is
        # balanced - somebody quoting somebody - not stranded delivery prose.
        if (q.group(0) == "\u201d" and "\u201c" in earlier) or \
           (q.group(0) == '"' and '"' in earlier):
            continue
        rest = content[q.end():]
        # the attribution comma sits either side of the dangling quote
        if rest.startswith(","):
            prose = rest[1:].strip()
        elif earlier.rstrip().endswith(","):
            prose = rest.strip()
        else:
            continue
        words = [w.strip(".,;:!?").lower() for w in prose.split()[:3]]
        if not any(w in _H3_ATTRIBUTION_VERBS for w in words):
            continue
        # the orphan quote and its comma dissolve; everything from the quote
        # onward was prose, everything before it was the spoken line
        return f"{prose} <d>{earlier.rstrip().rstrip(',')}</d>"
    return m.group(0)


def repair_h3_dialogue_tags(body, language="English"):
    """Normalize spoken lines to the trained `(Sn) says: <d>[Lang] words</d>`.

    Three malformations observed on the live brain (harness + the 2026-08-12
    "I'm not late" render): the line in plain quotes with no tags at all; tags
    present but no language tag (often keeping the quotes); and stray tag
    fragments wrapping DELIVERY prose instead of the words - `says: "line," d>
    she glances back...</d>`. The words become properly tagged, and leftover
    fragments dissolve so the prose lands back in the scene text where the
    encoder reads it as action. Brief 9.9 added two more, both closed rules
    over real history: the [EN] shorthand normalizes through the two-token
    map, and delivery prose stranded inside a proper tag relocates in front
    of it. Mechanical, so fix rather than re-ask - same policy as every
    other repair in assemble_h3_prompt."""
    def _wrap(m):
        return (f"{m.group(1)}<d>[{language}] "
                f"{m.group(2).strip().rstrip(',')}</d> ")
    out = _H3_UNTAGGED_SAYS_RE.sub(_wrap, body)
    out = _H3_UNLANGUAGED_TAG_RE.sub(
        lambda m: f"<d>[{language}] {m.group(1).strip().rstrip(',')}</d>", out)
    out = _H3_LANG_TAG_RE.sub(
        lambda m: f"<d>[{_H3_LANG_TOKENS.get(m.group(1), m.group(1))}]", out)
    out = _H3_TAG_BLOCK_RE.sub(_h3_relocate_intag_prose, out)
    # Whatever tag text remains outside a proper pair is a fragment around
    # scene prose: dissolve it rather than let the encoder chew on it.
    protected = _H3_PROPER_TAG_RE.findall(out)
    for i, block in enumerate(protected):
        out = out.replace(block, f"\x00{i}\x00", 1)
    out = re.sub(r"(?<!<)\bd>|</d>|<d>", "", out)
    for i, block in enumerate(protected):
        out = out.replace(f"\x00{i}\x00", block, 1)
    return out


# ---- the line-end beat after </d> (brief 9.9) -------------------------------
# H3's trained format wants a beat after the closing tag: "the lips close and
# the speaking motion stops". 24 of 31 measured briefs ended the field on the
# tag itself, and a mouth with no stated end keeps articulating after the
# words run out - the tail a public thread blamed on the <d> syntax. The rule
# already lives in H3_MOTION_SYSTEM and the brain ignores it, which is the
# brief-harness finding: small models obey end contracts and deterministic
# repair, never mid-paragraph rules. So detection, validation and the append
# are pure sync functions over the brief string (no brain, no GPU - testable
# under the live-machine rule), and exactly one async wrapper spends one brain
# call on the ~77% that hang.

def _h3_desc_span(text):
    """(start, end) of the description field's VALUE: to the next field
    header at line start, or to end of string. None when there is no field.
    Matches either lane's field name; the END markers are shared."""
    m = _H3_DESC_FIELD_RE_ANY.search(text)
    if not m:
        return None
    end = len(text)
    for field_re in (_H3_SOUND_FIELD_RE, _H3_MUSIC_FIELD_RE):
        nxt = field_re.search(text, m.end())
        if nxt:
            end = min(end, nxt.start())
    return m.end(), end


def h3_hanging_dialogue(brief):
    """True when the description field's last non-space content is `</d>` -
    the spoken line shipped with no beat ending the speaking motion. A beat
    already following the tag must NOT detect (appending would double it), and
    of several dialogue lines only the last can hang."""
    text = str(brief or "")
    span = _h3_desc_span(text)
    return bool(span) and text[span[0]:span[1]].rstrip().endswith("</d>")


# The deterministic gate the brain's one clause must pass. Every reject is a
# way the reply stops being a beat and starts being something else: empty, a
# paragraph (the word cap), tag syntax or quotes leaking back in, a speaker
# cue, or more than one sentence (a period anywhere but the end, or ?/!).
H3_CLOSER_WORD_CAP = 14


def h3_closing_beat_ok(beat):
    """Validate the brain's reply as ONE clause, never the brief echoed back."""
    if not beat:
        return False
    beat = str(beat).strip()
    if not beat or len(beat.split()) > H3_CLOSER_WORD_CAP:
        return False
    if any(t in beat for t in ("<d>", "</d>", "[", "]", '"', "\u201c",
                               "\u201d", "(S", "?", "!")):
        return False
    # a single sentence: at most one period, and only terminal - "Dr. Reyes"
    # is a second sentence trying to hide
    return beat.count(".") <= 1 and ("." not in beat or beat.endswith("."))


# The fallback closer is deliberately neutral: a fixed gendered or staged beat
# would be the same disease this repair exists to cure - a constant where the
# truth belongs - asserting lips closing on an off-screen voiceover or a line
# meant to carry into the next shot. It fires on ANY failed repair: failed
# validation, exception, timeout, brain unavailable. One attempt, never a
# retry: a stalled repair blocking the render path is worse than the artifact
# it fixes, so the whole call sits under one 20-second budget.
H3_NEUTRAL_CLOSER = "Their lips close and the speaking motion stops."
H3_CLOSER_TIMEOUT = 20


def _h3_closer_request(text):
    """The narrow end-contract for one hanging line: ONE beat, one clause.

    Never ask for the brief back - a whole-brief echo asks a small brain to
    reproduce hundreds of tokens byte-for-byte, it paraphrases nearly every
    time, validation fails nearly every time, and the 'rare' fallback quietly
    becomes the constant this repair exists to remove. The brain returns ONLY
    the beat; Pixal appends it deterministically, so byte-identity of
    everything else is true by construction rather than by check.
    """
    scene = text[slice(*_h3_desc_span(text))].strip()
    return [
        {"role": "system", "content": (
            "You write the beat that ends a speaking motion in a video brief. "
            "The scene below ends its last spoken line with </d> and says "
            "nothing after it - a mouth with no stated end keeps articulating "
            "after the words run out, and that tail is where teeth stop being "
            "teeth. Reply with ONE beat and nothing else: a single clause of "
            f"at most {H3_CLOSER_WORD_CAP} words that says the lips close and "
            "the speaking motion stops, consistent with THIS scene. No tags, "
            "no quotes, no speaker cues, no explanation.")},
        {"role": "user", "content": scene},
    ]


def _h3_append_closing_beat(text, beat):
    """` beat` immediately after the field-ending `</d>` - one clause, in the
    one slot, with every other byte of the brief untouched by construction."""
    span = _h3_desc_span(text)
    if not span:
        return text
    at = text[span[0]:span[1]].rfind("</d>")
    if at < 0:
        return text
    pos = span[0] + at + len("</d>")
    return text[:pos] + " " + beat + text[pos:]


async def repair_h3_hanging_dialogue(brief, cid=None):
    """Close a hanging spoken line: one brain call for one beat, else the
    neutral closer. Briefs that already end the motion never reach the brain."""
    text = str(brief or "")
    if not h3_hanging_dialogue(text):
        return text
    beat = None
    try:
        reply = await asyncio.wait_for(
            llm_call(_h3_closer_request(text), timeout=H3_CLOSER_TIMEOUT,
                     cid=cid),
            timeout=H3_CLOSER_TIMEOUT)
        if reply:
            status, data = reply
            if status == 200 and isinstance(data, dict):
                choices = data.get("choices") or []
                if choices:
                    beat = (choices[0].get("message") or {}).get("content")
    except Exception:
        beat = None     # one attempt, never a retry - see the closer's comment
    if not h3_closing_beat_ok(beat):
        beat = H3_NEUTRAL_CLOSER
    return _h3_append_closing_beat(text, beat)


# ---- the style declaration (brief 9.9) --------------------------------------
# The OUTPUT FORMAT's style example reads "(live-action, natural real-time
# motion)", so an Anima or clear-anime still animates as live capture - 92% of
# measured briefs, 0 stylized - with conflicting conditioning in the one
# position H3 reads as style. The fix is provenance, not a vision heuristic:
# the ledger entry of the source still already says what rendered it.
#
# The map is CLOSED and keyed on (recipe id, family) - never the family alone:
# `anime` is Z-Image's clear-anime model sitting inside the zimage family
# beside two photoreal recipes, so the recipe id is the key and the family
# (falling back to the recipe's own for entries written before model_family
# was recorded) only corroborates. "2D-animated" is pinned byte-for-byte from
# MiniMax's own guide (h3pb/web/Video_Prompt_Writing_Guide.pdf §1.4.1). The
# tempo half is load-bearing against slow motion and stays byte-for-byte;
# only the style token is ever spliced. Style-direction renders (a photoreal
# core carrying an anime style) are genuinely ambiguous, so unknown or
# unmatched provenance leaves live-action alone: a wrong stylized claim is
# exactly as bad as the wrong constant this removes.
H3_STYLIZED_SOURCES = {
    ("anima", "anima"): "2D-animated",
    ("anime", "zimage"): "2D-animated",
}


def h3_style_for_entry(entry):
    """The style declaration the source still's provenance dictates, or None
    to leave the brief's own wording untouched."""
    if not isinstance(entry, dict):
        return None
    template = entry.get("template")
    family = (entry.get("info") or {}).get("model_family")
    if not family:
        family = (RECIPE_SPECS.get(template) or {}).get("family")
    return H3_STYLIZED_SOURCES.get((template, family))


# The style slot is the OPENING token of the description field - 154 of 168
# shipped briefs open on the identical constant, so the anchor is reliable.
# A "live-action" mention anywhere else (a caption in the scene, say) is
# content, not the declaration, and is never spliced.
_H3_STYLE_SLOT_RE = re.compile(
    r"(integrated_multimodal_description:\s*(?:\[\s*shot\s*1\s*\]\s*)?)"
    r"(Live-action|live-action)\b", re.I)


def h3_style_splice(prompt, style):
    """Swap the opening style token for `style`; every other byte stays."""
    text = str(prompt or "")
    if not style:
        return text
    return _H3_STYLE_SLOT_RE.sub(lambda m: m.group(1) + style, text, count=1)


# A DIRECTOR'S NOTE that pins the camera ("the camera never moves") is the
# instruction models drop most: the 2026-08-12 three-model bake-off lost it on
# 11 of 18 hinted briefs while every quoted line survived. Static is the only
# case repaired deterministically - a note asking for a specific MOVE can fail
# a regex a hundred ways, and inventing camera language would be worse than
# trusting the contract line.
_STATIC_CAM_HINT_RE = re.compile(
    r"camera[^.!?]{0,60}?(never (?:moves?|pans?|zooms?)|"
    r"do(?:es)?n'?t move|does not move|stays? (?:still|put|fixed|static)|"
    r"remains? (?:still|fixed|static)|locked(?:[- ]off)?|is static|no movement)|"
    r"\bstatic (?:camera|shot|frame)\b|\blocked[- ]off\b", re.I)
# The gate must look for a STATIC-camera statement, not the word "camera" -
# a mere mention proves nothing about whether the pin survived. (Until
# 2026-08-14 there was a stronger reason: the output contract forced every
# brief to open with "the camera cuts into a scene already underway", so the
# word was guaranteed present. That clause is gone - it was causing the
# first-frame stick - but the strict match is still the right test.)
_BRIEF_STATIC_CAM_RE = re.compile(
    r"camera[^.!?]{0,60}?(never moves?|stays|remains|holds|locked|static|"
    r"level|fixed)|\bstatic (?:frame|shot|camera)\b|\blocked[- ]off\b|"
    r"\bshot locked\b|\bno camera (?:movement|motion|move)\b", re.I)
_STATIC_CAM_SENTENCE = (" The camera holds locked and level at a fixed framing "
                        "for the entire take.")


def repair_camera_note(body, hint):
    """When the note pins the camera and the brief drops the pin, restate it.

    Appends inside the field the encoder actually reads (before
    overall_soundscape for H3's labeled structure, at the end for LTX's flowing
    paragraph). A brief that already states a held camera is left alone - it
    honored the note in its own words. Repair-only by measurement: a fourth
    OUTPUT CONTRACT point lifted camera compliance but collapsed brief length
    and broke dialogue tags (Gemma 12B, 2026-08-12) - attention dilution.
    """
    if not hint or not _STATIC_CAM_HINT_RE.search(str(hint)):
        return body
    if _BRIEF_STATIC_CAM_RE.search(body):
        return body
    idx = body.find("overall_soundscape:")
    if idx < 0:
        return body.rstrip() + _STATIC_CAM_SENTENCE
    return body[:idx].rstrip() + _STATIC_CAM_SENTENCE + "\n\n" + body[idx:]


def assemble_h3_prompt(brief, user_script=False, last_frame=False, seconds=None):
    """Deterministic assembly of the official H3 i2va/fl2va structure.

    The director is asked for the three labeled fields; a brief that came back
    as bare prose (small local brains drop labels under pressure) is repaired
    by wrapping rather than re-asked - one LLM round is expensive and the
    repair is mechanical. A user-pasted script is the user's own words: it
    gets the alignment header and NOTHING creative - no default soundscape, no
    music policy the user did not write.
    """
    body = str(brief or "").strip()
    if not user_script:
        # Two dialogue slips the director keeps making under pressure despite
        # the prompt (2026-08-11, twerk render): square-bracket tags ([d] for
        # <d>), and the whole spoken block appended AFTER the three fields as
        # a fourth. Both repairs are mechanical, so fix rather than re-ask -
        # same policy as the label repair below.
        body = re.sub(r"\[\s*d\s*\]", "<d>", body, flags=re.I)
        body = re.sub(r"\[\s*/\s*d\s*\]", "</d>", body, flags=re.I)
        body = repair_h3_dialogue_tags(body)
        sound = _H3_SOUND_FIELD_RE.search(body)
        if sound:
            spoken = next((m for m in re.finditer(r"\(S\d+\)\s*says\s*:", body)
                           if m.start() > sound.start()), None)
            if spoken:
                # the block runs to the next field label (a stray block can sit
                # between soundscape and music) or to the end of the brief
                nxt = _H3_MUSIC_FIELD_RE.search(body, spoken.end())
                end = nxt.start() if nxt else len(body)
                block = body[spoken.start():end].strip()
                desc = body[:sound.start()].rstrip()
                mid = body[sound.start():spoken.start()].rstrip()
                tail = body[end:].strip()
                body = (desc + " " + block + "\n\n" + mid +
                        ("\n\n" + tail if tail else ""))
        if not _H3_DESC_FIELD_RE.search(body):
            if not re.match(r"(?i)\s*\[\s*shot\s*1\s*\]", body):
                body = "[Shot 1] " + body
            body = "integrated_multimodal_description: " + body
        if not _H3_SOUND_FIELD_RE.search(body):
            body += ("\n\noverall_soundscape: The natural ambience of the "
                     "scene and the sounds of the visible actions, "
                     "synchronized.")
        if not _H3_MUSIC_FIELD_RE.search(body):
            body += "\n\nnon_diegetic_music: N/A"
    if not _H3_HEADER_RE.match(body):
        body = h3_alignment_header(last_frame, seconds) + "\n\n" + body
    return body


# ---- the ref2va six-section format (brief 9.12) ----------------------------
# ref2va has its OWN trained format (MiniMax's full-reference guide §1): six
# sections, no alignment header, and the style declaration is the first line
# of the detailed_description VALUE. The DIRECTOR writes all six sections
# (H3_REF2V_MOTION_SYSTEM); the assembler below is repair-and-guarantee, never
# re-ask - it deterministically guarantees every structural property and fills
# missing sections from the wired ref list with generic binding sentences. It
# repairs; it does not author the scene. An assembler that MANUFACTURED six
# sections around the fl2va director's three-field output would pass every
# literal-string test and ship the wrong product.
H3_REF2V_FIELDS = ("subject_definitions", "summary", "retention_analysis",
                   "detailed_description", "overall_soundscape",
                   "non_diegetic_music")
_H3_REF2V_FIELD_RE = re.compile(
    r"(?im)^\s*(subject_definitions|summary|retention_analysis|"
    r"detailed_description|overall_soundscape|non_diegetic_music)\s*:\s*")

# The style slot is POSITIONAL: everything between the detailed_description
# header and the first [Shot 1] marker. The guide's own examples use different
# verbs ("is in a ... style" vs "uses a ... style"), so there is no reliable
# lexical anchor and no regex over free prose is invented - the assembler owns
# the slot outright, and the director variant is told not to write one. Both
# sentences pinned byte-for-byte; h3_style_for_entry stays the provenance map.
H3_REF2V_STYLE_PHOTOREAL = "The target video is in realistic photographic style."
H3_REF2V_STYLE_STYLIZED = "The target video is in 2D-animated style."

# Reference tags the prompt may name. v1 wires images only, so any <Video k>
# or <Audio j> is dangling BY DEFINITION; a <Picture N> beyond the wired count
# is the mistake the official template itself ships (its stock prompt names
# <Audio 1> with ref_audios.ref_audio_0 unlinked). The node never complains -
# a dangling tag is just text - so the policy is Pixal's to enforce, and it is
# decided, not delegated: with exactly one wired ref there is only one thing
# the director could have meant, so demote and warn; with two or more, repair
# cannot be semantics-safe, so refuse with a named error.
_H3_REF_TAG_RE = re.compile(r"<\s*(picture|video|audio)\s*(\d+)\s*>", re.I)


def h3_ref2v_tag_check(brief, ref_count):
    """The dangling-ordinal policy over an assembled ref2va brief.

    Returns (brief, warnings); raises ValueError where repair cannot be
    semantics-safe. Pure and sync - the assembler calls it at intake and the
    builder re-calls it so rerolls (which bypass the assembler) get the same
    guarantee."""
    text = str(brief or "")
    wired = {str(n) for n in range(1, int(ref_count) + 1)}
    dangling = [m.group(0) for m in _H3_REF_TAG_RE.finditer(text)
                if m.group(1).lower() != "picture" or m.group(2) not in wired]
    if not dangling:
        return text, []
    if int(ref_count) == 1:
        warnings = []

        def demote(m):
            if m.group(1).lower() == "picture" and m.group(2) == "1":
                return m.group(0)
            warnings.append(
                f"{m.group(0)} names a reference that is not wired - only "
                f"<Picture 1> is, so it was rewritten to <Picture 1>")
            return "<Picture 1>"

        return _H3_REF_TAG_RE.sub(demote, text), warnings
    raise ValueError(
        "the brief names references that are not wired: "
        + ", ".join(dict.fromkeys(dangling))
        + f" - {ref_count} image reference(s) are wired; fix the brief or wire "
          f"the reference")


def h3_ref2v_unnamed_lint(brief, ref_count):
    """A wired ref the prompt never names still costs: its vision block enters
    the Qwen context and its latent rides every sampling step (9.0 Q3). Warn."""
    named = {int(m.group(2)) for m in _H3_REF_TAG_RE.finditer(str(brief or ""))
             if m.group(1).lower() == "picture"}
    return [f"<Picture {n}> is wired but the brief never names it - its tokens "
            f"ride every sampling step with no job assigned"
            for n in range(1, int(ref_count) + 1) if n not in named]


# A ref's stored kind becomes the subject sentence (ref guide §2.1: state the
# features to follow). v1 routes the picked gallery still, which carries no
# kind, so the neutral default is the one that ships until the 9.13 strip.
_H3_REF2V_KIND_LINES = {
    "identity": "<Subject {n}> is the person in <Picture {n}>.",
    "clothing": "<Subject {n}> is the wardrobe shown in <Picture {n}>.",
    "style": "<Subject {n}> is the visual style of <Picture {n}>.",
    "object": "<Subject {n}> is the object shown in <Picture {n}>.",
}


def _h3_ref2v_subject_line(n, kind=None):
    template = _H3_REF2V_KIND_LINES.get(str(kind or ""),
                                        "<Subject {n}> is the subject of <Picture {n}>.")
    return template.format(n=n)


def _h3_ref2v_sections(text):
    """Split a brief into its six sections: {name: content}, plus the prose
    before the first header. First occurrence of a header wins - a duplicated
    field (the H3_AUDIO_PROMPT echo ends on a second non_diegetic_music:) is a
    contradiction, and keeping the first is the deterministic answer. The
    preamble is returned separately: bare prose becomes the description, but
    when sections exist it is dropped - nothing precedes the six sections in
    this lane, least of all the fl2va alignment header."""
    matches = list(_H3_REF2V_FIELD_RE.finditer(text))
    fields = {}
    for i, m in enumerate(matches):
        name = m.group(1).lower()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if name not in fields:
            fields[name] = text[m.end():end].strip()
    preamble = text[:matches[0].start()].strip() if matches else text.strip()
    return fields, preamble


def assemble_h3_ref2v_prompt(brief, refs, user_script=False, style=None):
    """Deterministic assembly of MiniMax's six-section full-reference format -
    a SIBLING of assemble_h3_prompt, not a parameter on it.

    refs is the ordered wired reference list (dicts; a stored `kind` becomes
    the subject sentence). Returns (prompt, warnings). Guarantees, each
    checkable against the model card's canonical case-Ref2VA prompt: all six
    sections in the guide's order; block shape (header at column 0, value on
    the next line, one blank line between); no alignment header; no
    H3_AUDIO_PROMPT; exactly one non_diegetic_music field; [reference
    generation] as the only task prefix (v1 wires images, no source video, no
    audio - the other prefixes are all things v1 cannot mean); <Subject N>
    bound 1:1 to its wired <Picture N>; one <Subject N>-keyed retention line
    per wired ref with the ` - ` separator; and the style sentence as the
    first line of detailed_description, before [Shot 1].
    """
    refs = list(refs or [])
    count = len(refs)
    body = str(brief or "").strip()
    # The fl2va lane's audio instruction ends on its own inline
    # `non_diegetic_music: none.` - echoed here it would ship instruction prose
    # plus a second, contradictory music field, in a format that has no
    # instruction line at all. Its two load-bearing rules live in the ref2va
    # director's OUTPUT CONTRACT instead; the constant itself is stripped.
    body = body.replace(H3_AUDIO_PROMPT, "")
    if not user_script:
        # The director's recurring slips are lane-independent; the repair is
        # field-name agnostic and applies here unchanged.
        body = re.sub(r"\[\s*d\s*\]", "<d>", body, flags=re.I)
        body = re.sub(r"\[\s*/\s*d\s*\]", "</d>", body, flags=re.I)
        body = repair_h3_dialogue_tags(body)
    sections, preamble = _h3_ref2v_sections(body)

    # detailed_description: the style sentence is written or REPLACED from
    # provenance (the slot is positional - everything before [Shot 1]). Bare
    # prose with no section headers wraps into the description, the same
    # repair the fl2va assembler makes for a brain that dropped every label.
    desc = sections.get("detailed_description") or preamble
    marker = re.search(r"(?i)\[\s*shot\s*1\s*\]", desc)
    if marker:
        desc = desc[marker.start():].strip()
    else:
        desc = ("[Shot 1] " + desc.strip()).strip()
    style_sentence = (H3_REF2V_STYLE_STYLIZED if style == "2D-animated"
                      else H3_REF2V_STYLE_PHOTOREAL)
    sections["detailed_description"] = style_sentence + "\n" + desc

    # subject_definitions / retention_analysis: fill what is missing, never
    # rewrite what the director wrote. One <Subject N> per wired ref, 1:1,
    # citing its <Picture N> (§2.2: an image used only to define a character
    # gets no standalone <Picture N> entry). The retention repair omits the
    # shot-appearance parenthetical rather than inventing one.
    subj = sections.get("subject_definitions", "")
    lines = [line for line in subj.splitlines() if line.strip()]
    for n in range(1, count + 1):
        if f"<Picture {n}>" in subj or f"<Subject {n}>" in subj:
            continue
        lines.append(_h3_ref2v_subject_line(n, refs[n - 1].get("kind")
                                            if isinstance(refs[n - 1], dict) else None))
    sections["subject_definitions"] = "\n".join(lines)

    ret = sections.get("retention_analysis", "")
    lines = [line for line in ret.splitlines() if line.strip()]
    for n in range(1, count + 1):
        if f"<Subject {n}>" in ret:
            continue
        lines.append(f"<Subject {n}>: fully_preserved - the features named in "
                     f"subject_definitions are retained.")
    sections["retention_analysis"] = "\n".join(lines)

    # summary opens with the bracketed task-type prefix from the closed §3
    # menu. Whatever prefix the director wrote, v1 can only mean [reference
    # generation]; a missing prefix gains one.
    summary = sections.get("summary", "").strip()
    prefix = re.match(r"\[[^\]]*\]", summary)
    if prefix:
        summary = "[reference generation]" + summary[prefix.end():]
    elif summary:
        summary = "[reference generation] " + summary
    else:
        subjects = ", ".join(f"<Subject {n}>" for n in range(1, count + 1))
        summary = (f"[reference generation] The target video carries "
                   f"{subjects or '<Subject 1>'} into a new scene.")
    sections["summary"] = summary

    if not sections.get("overall_soundscape"):
        sections["overall_soundscape"] = (
            "The natural ambience of the scene and the sounds of the visible "
            "actions, synchronized.")
    if not sections.get("non_diegetic_music"):
        sections["non_diegetic_music"] = "N/A"

    out = "\n\n".join(f"{name}:\n{sections[name]}" for name in H3_REF2V_FIELDS)
    return h3_ref2v_tag_check(out, count)


# Sourced ceilings, not preferences (researched 2026-08-13 after a trailer came
# back with mangled teeth and a voice belonging to nobody on screen). The
# speaker cap is MiniMax-AI/MiniMax-H3 issue #17: attribution degrades at three
# or more, and the surplus line returns in an unattached voice. The speech rate
# is MiniMax's own guidance - roughly 2.5 words a second, so a 5s shot holds
# about a dozen words TOTAL across every speaker. Past that the mouth is moving
# for the whole clip, which is when teeth stop being coherent frame to frame.
#
# Reported, never repaired: both fixes mean rewriting the user's own lines, and
# silently deleting a character's dialogue is worse than shipping a warning.
H3_MAX_SPEAKERS = 2
H3_WORDS_PER_SECOND = 2.5

_H3_SPEAKER_RE = re.compile(r"\(\s*(S\d+(?:\s*,\s*S\d+)*)\s*\)")
_H3_DIALOGUE_RE = re.compile(r"<d>(.*?)</d>", re.S)
# Briefs write speech as quoted prose far more often than in <d> tags - the
# director's own SPOKEN_LINE_RULE asks for the line "in quotes". Counting only
# <d> meant a brief could be double its budget and lint clean, which is exactly
# how a 10s clip shipped with the tail of "let's go" wrapped onto its own head
# (2026-08-18). Straight and curly pairs both, since the writers emit either.
_H3_QUOTED_RE = re.compile("[\"“]([^\"“”]{2,240})[\"”]")


def h3_brief_lint(brief, seconds=None):
    """H3 budget overruns in a finished brief, as user-facing lines."""
    text = str(brief or "")
    warnings = []
    ids = set()
    for match in _H3_SPEAKER_RE.finditer(text):
        ids.update(p.strip().upper() for p in match.group(1).split(",")
                   if p.strip())
    if len(ids) > H3_MAX_SPEAKERS:
        warnings.append(
            f"{len(ids)} speakers ({', '.join(sorted(ids))}) - H3 attributes "
            f"at most {H3_MAX_SPEAKERS} reliably, and the extra line tends to "
            f"come back in a voice belonging to nobody on screen")
    # the [English] tag is syntax, not speech, so it does not spend the budget
    tagged = _H3_DIALOGUE_RE.findall(text)
    # Quoted speech counts too, but never twice: a <d> line is usually quoted
    # INSIDE the tag, so only quotes outside every tagged span are added.
    outside = _H3_DIALOGUE_RE.sub(" ", text)
    spoken = re.sub(r"\[[^\]]*\]", " ",
                    " ".join(tagged + _H3_QUOTED_RE.findall(outside)))
    words = len(spoken.split())
    try:
        secs = float(seconds)
    except (TypeError, ValueError):
        secs = 0.0
    budget = int(secs * H3_WORDS_PER_SECOND)
    if budget and words > budget:
        warnings.append(
            f"{words} words of dialogue in {secs:g}s - the budget is about "
            f"{budget}; past it the mouth moves for the whole clip, the teeth "
            f"stop holding together, and the speech H3 cannot fit wraps onto "
            f"the START of the clip as a stray syllable")
    return warnings


def h3_speech_budget_note(seconds, shots=1):
    """Tell the director the word ceiling for THIS clip, and where it must land.

    SPOKEN_LINE_RULE carries a flat "twelve words or fewer", which is the 5s
    budget wearing the clothes of a universal rule: correct at 5s, needlessly
    tight at 10s, and silent about WHEN the line runs. Neither half was enough
    on its own - H3 truncates speech that is still going at the window edge and
    the overflow reappears at the head of the clip, so the line has to finish
    early, not merely be short (measured 2026-08-18).

    Warning after the fact was the old contract and it could not fire here: the
    lint reads a finished brief, and rewriting a user's dialogue to fit is worse
    than shipping the warning. Budgeting the writer up front is the version that
    costs nobody their words.
    """
    try:
        secs = float(seconds or 0)
    except (TypeError, ValueError):
        secs = 0.0
    if secs <= 0:
        return ""
    per_shot = secs / max(1, int(shots or 1))
    budget = int(per_shot * H3_WORDS_PER_SECOND)
    if budget < 1:
        return ""
    unit = "shot" if (shots or 1) > 1 else "clip"
    return (f"\n\nSPEECH BUDGET FOR THIS {unit.upper()}: {per_shot:g}s holds about "
            f"{budget} words of dialogue TOTAL across every speaker. Stay under "
            f"it. Start the line early enough that its LAST WORD is finished "
            f"before the final second of the {unit}: speech still running when "
            f"the {unit} ends is cut off there, and the piece H3 could not fit "
            f"reappears as a stray syllable over the opening frames. Silence at "
            f"the end of a {unit} is correct and costs nothing.")


def _h3_warning_text(warnings):
    """Lane line for an over-budget H3 brief. None when it is within budget."""
    warnings = [w for w in (warnings or []) if str(w).strip()]
    if not warnings:
        return None
    return ("*over what H3 can hold:* " + "; ".join(str(w) for w in warnings)
            + ".")


def validate_shot_count(engine=None, shots=None, seconds=None, model=None):
    """Normalize the multishot count. Only MiniMax H3 renders multiple shots.

    Kept out of validate_video_selection deliberately: that function's tuple is
    already four wide, and shots are an H3-only concept.
    """
    if shots is None:
        return 1
    try:
        count = int(shots)
    except (TypeError, ValueError):
        raise ValueError("invalid shot count") from None
    if count == 1:
        return 1
    if str(engine or "").strip().lower() != "h3":
        raise ValueError("only MiniMax H3 renders multiple shots")
    # v1 ref2va is single-shot, and the refusal must land BEFORE any cut plan
    # is computed: /api/animate hardcodes template="h3_i2v" for a truthy cut
    # plan, which would otherwise sail a ref2va chip straight into the fl2va
    # builder past every multishot fence. The chained pack is no way in either
    # - it drives keyframe conditioning semantics, and ref2va+keyframes is
    # untested upstream.
    if h3_model_variant(model) == H3_REF2V_MODEL_ID:
        raise ValueError("MiniMax H3 REF2VA is single-shot: it carries its "
                         "reference subject through one new scene - set shots to 1")
    # A single-pass take cuts inside one core-ComfyUI generation, so it must not
    # be blocked on a node pack it never loads.
    if not h3_cut_plan(count, seconds) and not h3_multishot_available():
        raise ValueError("multishot needs the ComfyUI-H3-Multishot node pack, "
                         "which is not installed")
    if not 1 <= count <= H3_SHOTS_MAX:
        raise ValueError(f"shot count must be 1-{H3_SHOTS_MAX}")
    return count


def validate_video_selection(engine=None, model=None, seconds=None, fps=None):
    """Normalize and validate Animate controls before copying or preparing files."""
    engine_id = str(engine or "ltx25").strip().lower()
    # 2.3 was retired from the picker 2026-08-12; stale clients and drifting
    # tool calls that still say "ltx" mean the current LTX now. Old ltx_i2v
    # history entries reroll through their stored template, not through here.
    if engine_id == "ltx":
        engine_id = "ltx25"
    item = next((choice for choice in video_engine_options()
                 if choice["id"] == engine_id), None)
    if not item:
        raise ValueError(f"unknown video engine: {engine_id}")
    if not item["available"]:
        raise ValueError(f"{item['label']} is unavailable: " + ", ".join(item["missing"]))
    choices = item["models"]
    model_id = str(model or choices[0]["id"]).strip().lower()
    model_item = next((choice for choice in choices if choice["id"] == model_id), None)
    if not model_item:
        raise ValueError(f"{item['label']} does not have model: {model_id}")
    if not model_item["available"]:
        raise ValueError(f"{item['label']} model {model_item['label']} is unavailable")
    default_seconds = 5
    try:
        value = float(default_seconds if seconds is None else seconds)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {item['label']} clip length") from None
    allowed = {length["s"] for length in item["lengths"]}
    if not value.is_integer() or int(value) not in allowed:
        raise ValueError(f"{item['label']} length must be one of " +
                         ", ".join(f"{length}s" for length in sorted(allowed)))
    # Only LTX exposes a frame rate; H3's is fixed by its trained frame counts.
    chosen_fps = None
    if fps is not None and item.get("fps_choices"):
        try:
            chosen_fps = int(float(fps))
        except (TypeError, ValueError):
            raise ValueError(f"invalid {item['label']} frame rate") from None
        if chosen_fps not in item["fps_choices"]:
            raise ValueError(f"{item['label']} frame rate must be one of " +
                             ", ".join(f"{r}fps" for r in item["fps_choices"]))
    return engine_id, model_id, int(value), chosen_fps


def keep_video_output(template, filename):
    """VHS writes a silent mp4 twin beside its audio-bearing ``-audio`` file
    whenever the graph's VHS_VideoCombine has an audio input wired - which is
    exactly the templates listed below. ltx25_i2v saves through core SaveVideo
    and is genuinely exempt, and ltx25_upscale_video is a file built inside
    build_upscale_video, so it arrives here as "upscale_video"."""
    name = str(filename or "").lower()
    if template in ("h3_i2v", "h3_multishot", "h3_ref2v", "ltx_i2v", "upscale_video") and \
            name.endswith((".mp4", ".webm", ".mov")):
        return bool(re.search(r"-audio\.(mp4|webm|mov)$", name))
    return True

def build_ltx_i2v(motion, seed, image, seconds=None, fps=None, overrides=(), model=None):
    """LTX 2.3 image-to-video from a finished still. The graph is the supplied I2V
    (GGUF distilled, two-pass with the spatial upsampler) with its KJNodes Get/Set
    indirection resolved to direct links.

    Frame count is derived from the graph's OWN frame rate, which one node (285)
    feeds to both the muxer and the audio latent. It ships at 30, and this builder
    used to convert seconds at a hardcoded 24 - so every clip came out a fifth
    short, and an "8s" request measured 6.43s on disk."""
    g = json.loads(json.dumps(TEMPLATES["ltx_i2v"]))
    model_short = "ltx-2.3-22b-distilled"
    if model and model in LTX_MODELS and model != "default":
        rel, needs_distill = LTX_MODELS[model]
        g["345"]["inputs"]["unet_name"] = rel
        if needs_distill:
            g["dm:distill"] = {"class_type": "LoraLoaderModelOnly",
                               "inputs": {"lora_name": LTX_DISTILL_LORA,
                                          "strength_model": 1.0,
                                          "model": ["345", 0]}}
            g["301"]["inputs"]["model"] = ["dm:distill", 0]
        model_short = base(rel)
    g["352"]["inputs"]["value"] = motion                    # positive motion prompt
    g["380"]["inputs"]["image"] = image                     # start frame (in ComfyUI/input)
    g["115"]["inputs"]["noise_seed"] = seed
    g["140"]["inputs"]["filename_prefix"] = f"pixal_dm/anim_{slug(motion)[:24]}"
    rate = float(g["285"]["inputs"]["value"])               # muxer + audio latent
    if fps:
        rate = float(min(max(float(fps), LTX_FPS_RANGE[0]), LTX_FPS_RANGE[1]))
        g["285"]["inputs"]["value"] = rate
    frames = int(g["108"]["inputs"]["length"])              # template default
    if seconds:
        # LTX's frame grid is 8k+1; clamp so a typo cannot queue a marathon
        low, high = LTX_SECONDS_RANGE
        secs = min(max(float(seconds), low), high)
        frames = 1 + 8 * round(secs * rate / 8)
        g["108"]["inputs"]["length"] = frames               # video latent
        g["199"]["inputs"]["frames_number"] = frames        # audio latent - keep in step
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    # The refine pass runs at the ceiling those two INTConstants set (the base
    # pass is node 164's half of it), so that is the canvas the butler prices.
    bound = ((int(g["292"]["inputs"]["value"]) * int(g["293"]["inputs"]["value"]))
             / 1e6)
    info = {"model": model_short,
            "loras": ["distill-lora@1"] if "dm:distill" in g else [],
            "canvas_mp": bound, "frames": frames,
            "size": f"{frames}f @ {rate:g}fps · {frames / rate:.1f}s"}
    return g, motion, info


def _ltx25_canvas(image):
    """Width/height for the 2.5 canvas: the official 0.9MP budget, but on the
    start frame's own aspect instead of the template's fixed 16:9 selector."""
    image_path = CDIR / "input" / image
    if not image_path.is_file():
        raise ValueError(f"LTX 2.5 start frame is missing from ComfyUI/input: {image}")
    from PIL import Image
    with Image.open(image_path) as still:
        w, h = still.size
    scale = (LTX25_CANVAS_MEGAPIXELS * 1_000_000 / (w * h)) ** 0.5
    m = LTX25_CANVAS_MULTIPLE
    return (max(m, round(w * scale / m) * m), max(m, round(h * scale / m) * m))


def build_ltx25_i2v(motion, seed, image, seconds=None, overrides=(), model=None):
    """LTX 2.5 image-to-video: the official Comfy-Org two-pass graph (base pass
    at half res, x2 latent upsample, refine pass, tiled decode) ported node for
    node into templates/ltx25_i2v.json.

    The graph derives its own frame count (fps*seconds+1 at its shipped 24fps),
    so unlike the 2.3 builder there is no frame math here - only whole seconds
    go in. The built-in Gemma 4 prompt enhancer stays OFF: the motion director
    already wrote the brief, and enhancing a directed brief rewrites it."""
    del model                       # single official model; kept for SIGS parity
    g = json.loads(json.dumps(TEMPLATES["ltx25_i2v"]))
    if not _node_available(LTX25_VRAM_GATE_NODE):
        # No KJNodes: drop the gate rather than queueing a graph ComfyUI cannot
        # resolve. The decode is then exactly as fragile as upstream's own.
        g["32"]["inputs"]["samples"] = g[LTX25_VRAM_GATE_ID]["inputs"]["any_input"]
        g.pop(LTX25_VRAM_GATE_ID, None)
    g["33"]["inputs"]["value"] = motion                     # positive motion prompt
    g["1"]["inputs"]["image"] = image                       # start frame (in ComfyUI/input)
    g["3"]["inputs"]["noise_seed"] = seed                   # base pass (refine pass is pinned)
    g["38"]["inputs"]["value"] = False                      # prompt enhancer switch
    g["49"]["inputs"]["filename_prefix"] = f"pixal_dm/anim_{slug(motion)[:24]}"
    width, height = _ltx25_canvas(image)
    g["30"]["inputs"]["value"] = width                      # replaces ResolutionSelector feed
    g["18"]["inputs"]["value"] = height
    # The still gets its own resize before LTXVPreprocess, and the template
    # ships that at a flat 1536 longer edge - roughly 2.6x the sampling canvas
    # for no gain, encoded once per pass. Match it to the canvas the frames
    # actually run at.
    g["10"]["inputs"]["resize_type.longer_size"] = max(width, height)
    rate = int(g["19"]["inputs"]["value"])                  # the graph's own 24
    secs = int(g["20"]["inputs"]["value"])                  # template default
    if seconds:
        low, high = LTX25_SECONDS_RANGE
        secs = int(min(max(float(seconds), low), high))
        g["20"]["inputs"]["value"] = secs
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    frames = rate * secs + 1
    # canvas_mp/frames are what the butler prices on. The graph expresses both
    # through ComfyMathExpression nodes fed by primitives, which no amount of
    # scanning can read - and pricing this flat is what let three of these OOM.
    info = {"model": base(LTX25_UNET), "loras": [],
            "canvas_mp": (width * height) / 1e6, "frames": frames,
            "size": f"{width}x{height} · {frames}f @ {rate}fps · {secs}s"}
    return g, motion, info


H3_AUDIO_PROMPT = (
    "Audio: Generate synchronized ambience and action sounds that match the visible "
    "scene. Preserve any quoted dialogue exactly with matching mouth articulation; "
    "when no dialogue is quoted, do not invent speech.\n"
    # Speech that does not FIT is not merely cut off: H3 truncates the tail at
    # the window edge and the overflow surfaces in the opening latent frames,
    # so the clip begins with the last syllable of its own final word. Measured
    # 2026-08-18 - a 10s clip ended mid-"go" at peak amplitude and opened with
    # the "oh". A control render whose line finished a second early was clean at
    # both ends. Landing the speech early is what prevents it.
    "All speech must BEGIN and FINISH inside the clip, with the final word "
    "completed before the last second of the duration; never let a line still "
    "be running when the clip ends.\n"
    # H3 scores clips with background music unasked, which is most of what makes
    # a grounded scene feel like an advert. non_diegetic_music is one of the six
    # field names from H3's own brief format, and the encoder honours it.
    "non_diegetic_music: none."
)


def inject_video_lora_triggers(brief, entries):
    """Add each enabled technical activation token exactly once."""
    brief = str(brief or "").strip()
    applied, pending = [], []
    for entry in entries:
        trigger = str(entry.get("trigger") or "").strip()
        if not trigger or trigger.lower() in {value.lower() for value in applied}:
            continue
        applied.append(trigger)
        if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(trigger)}(?![A-Za-z0-9_])",
                         brief, re.I):
            pending.append(trigger)
    if pending:
        brief = ", ".join(pending) + ". " + brief
    return brief, applied


def _h3_prepared_canvas(image, width=None, height=None):
    """Validate a staged first frame and return (name, width, height).

    Shared by both H3 builders so the single-shot and multishot paths can never
    disagree about what a legal canvas is - the multishot node resizes chained
    keyframes with "disabled" (no crop), so an off-grid canvas hurts it exactly
    as much as it hurts MiniMaxH3ImageToVideo.
    """
    image = input_ref_name(image)
    if not image:
        raise ValueError("MiniMax H3 needs a prepared first-frame image")
    image_path = CDIR / "input" / image
    if not image_path.is_file():
        raise ValueError(f"MiniMax H3 first frame is missing from ComfyUI/input: {image}")
    if width is None or height is None:
        from PIL import Image
        with Image.open(image_path) as prepared:
            width, height = prepared.size
    width, height = int(width), int(height)
    if width <= 0 or height <= 0 or width % H3_CANVAS_MULTIPLE or \
            height % H3_CANVAS_MULTIPLE:
        raise ValueError("MiniMax H3 canvas must use positive multiples of 32")
    return image, width, height


def build_h3_i2v(motion, seed, image, seconds=5, width=None, height=None,
                  overrides=(), model=None, lora_plan=None, turbo=False,
                  last_image=None, sparse=True, upscale=False):
    """MiniMax H3 FL2VA I2V, based on the locally proven native ComfyUI graph.

    The first frame must already be prepared to the exact adaptive canvas by
    prepare_h3_frame(); passing those dimensions makes MiniMaxH3ImageToVideo's
    internal resize a no-op and prevents both visual distortion and degraded
    Qwen3-VL image understanding.

    ``last_image`` engages true FL2VA: the node pins it to the final frame
    (cover-cropping it to canvas itself - the "follower" path in
    nodes_minimax_h3.py), and the brief's alignment header names it Picture 2.

    ``upscale`` re-samples the latent the sampler just produced at 2x through
    Comfyui-MMH3-UltimateUpscale, INSIDE this job - the pass needs node 11's
    latent and Pixal does not store latents, so it can only ever be an option
    on the render, not an action on a finished clip. Opt-in (it ~triples the
    render's cost), and only honoured where the pack and its 3D upscaler
    weights are both installed; anywhere else the plain graph is built.
    """
    model_id = str(model or H3_MODEL_ID).strip().lower()
    model_rel = h3_model_rel(model_id)
    if model_rel is None:
        raise ValueError(f"MiniMax H3 does not have model: {model_id}")
    # The reciprocal lane guard: this builder accepts any id h3_model_rel
    # resolves, so without the refusal a ref2va chip would build
    # MiniMaxH3ImageToVideo on ref2va weights - same architecture, ComfyUI
    # runs it, and the output is quietly wrong with no error anywhere.
    if h3_model_variant(model_id) == H3_REF2V_MODEL_ID:
        raise ValueError(
            f"MiniMax H3 model {model_id} is a ref2va build - first/last-frame "
            f"video needs an fl2va chip (the reference lane is template h3_ref2v)")
    # The asset check requires the PICKED build's file, not the fl2va constant;
    # encoder, VAEs and LoRAs are architecture-wide and shared.
    h3_assets, missing = _h3_asset_paths(model_rel)
    if missing:
        raise ValueError("MiniMax H3 is unavailable: " + ", ".join(missing))

    image, width, height = _h3_prepared_canvas(image, width, height)

    frames = h3_frame_count(seconds)
    brief = str(motion or "").strip()
    if not brief:
        raise ValueError("MiniMax H3 needs a motion brief")
    video_loras = resolve_h3_video_lora_stack(lora_plan, model_id)
    brief, lora_triggers = inject_video_lora_triggers(brief, video_loras)
    if H3_AUDIO_PROMPT not in brief:
        brief = brief.rstrip() + "\n\n" + H3_AUDIO_PROMPT
    # Turbo rides FIRST so the creative LoRAs stack on top of the distillation
    # rather than under it, and it contributes no trigger word.
    steps, sampler_name, scheduler, turbo_rows = h3_speed_settings(turbo)
    video_loras = turbo_rows + video_loras

    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": h3_assets["model"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": h3_assets["clip"], "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": h3_assets["video_vae"]}},
        "4": {"class_type": "VAELoader", "inputs": {
            "vae_name": h3_assets["audio_vae"]}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image}},
        "6": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": brief,
            "width": width, "height": height, "length": frames,
            "first_frame": ["5", 0]}},
        # "5b"/last_frame added below only for a bridge - a permanently present
        # optional input would change the proven graph's shape for every run.
        "7": {"class_type": "KSamplerSelect",
              "inputs": {"sampler_name": sampler_name}},
        "8": {"class_type": "BasicScheduler", "inputs": {
            "model": ["1", 0], "scheduler": scheduler, "steps": steps,
            "denoise": 1.0}},
        # H3 is CFG-distilled: the verified graph uses BasicGuider, not CFGGuider.
        "9": {"class_type": "BasicGuider", "inputs": {
            "model": ["1", 0], "conditioning": ["6", 0]}},
        "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed)}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["10", 0], "guider": ["9", 0], "sampler": ["7", 0],
            "sigmas": ["8", 0], "latent_image": ["6", 1]}},
        "12": {"class_type": "VAEDecode", "inputs": {
            "samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "VAEDecodeAudio", "inputs": {
            "samples": ["11", 0], "vae": ["4", 0]}},
        "14": {"class_type": "VHS_VideoCombine", "inputs": {
            # CRF, never bitrate: quality-targeted, so size floats down on easy
            # content. 14 is visually transparent for these canvases; 10 bought
            # ~40% bigger files for nothing a viewer could see.
            "images": ["12", 0], "audio": ["13", 0], "frame_rate": 24,
            "loop_count": 0,
            "filename_prefix": f"pixal_dm/h3_{slug(h3_slug_source(brief))[:24]}",
            "format": "video/h264-mp4", "crf": 14, "pix_fmt": "yuv420p",
            "pingpong": False, "save_output": True}},
    }
    if last_image:
        last_name = input_ref_name(last_image)
        if not last_name or not (CDIR / "input" / last_name).is_file():
            raise ValueError("MiniMax H3 bridge end frame is missing from ComfyUI/input")
        graph["5b"] = {"class_type": "LoadImage", "inputs": {"image": last_name}}
        graph["6"]["inputs"]["last_frame"] = ["5b", 0]
    for override in overrides:
        node_id = str(override.get("node"))
        input_name = override.get("input")
        if node_id not in graph or input_name not in graph[node_id]["inputs"]:
            raise ValueError(f"invalid MiniMax H3 override: {node_id}.{input_name}")
        graph[node_id]["inputs"][input_name] = override.get("value")
    model_tail = apply_lora_nodes(graph, "1", video_loras, "h3:lora")
    # The 2x refine samples through the model WITH the LoRA chain but WITHOUT
    # the sparse-attention patch, so the dense tail is captured before
    # apply_h3_sparse overwrites it. Measured: at 6 steps dense scored 14.87
    # flicker against sparse's 14.16 - the number preferred sparse, and Jesse
    # looked at both clips and picked dense ("the artifact is gone in this
    # one - best so far"). Sparse also buys almost nothing on a tile (4.49 vs
    # 4.81 s/tile-step, ~3%), because a tile is a much shorter sequence than
    # a whole frame.
    refine_tail = model_tail
    model_tail = apply_h3_sparse(graph, model_tail, sparse)
    # Both consumers must see the identical literal chain. Row zero is the
    # first physical loader after UNETLoader; the final row feeds the sampler.
    graph["8"]["inputs"]["model"] = [model_tail, 0]
    graph["9"]["inputs"]["model"] = [model_tail, 0]
    upscale_on = h3_upscale_active(upscale)
    if upscale_on:
        w2, h2 = width * 2, height * 2
        tile_w, ol_w = h3_tile_axis(w2)
        tile_h, ol_h = h3_tile_axis(h2)
        # The 2x conditioning's first frame goes through the user's configured
        # IMAGE upscaler. Take 1 fed the 1x conditioning and the node's
        # reanchor bilinear-resized the frozen frame-0 keyframe - the clip
        # opened on a blur and only sharpened as the model took over.
        # ...through the user's configured IMAGE upscaler when there IS one.
        # The shipped default is image_model="" and a fresh install may carry
        # no ESRGAN weights at all, so an unresolvable one falls back to a
        # plain lanczos resize instead of raising "choose an upscale model in
        # Settings first" and killing the render. What take 1 got wrong was
        # the conditioning's SIZE, not its sharpness, and the size is right
        # either way; the model only buys a crisper anchor.
        try:
            image_model = resolve_upscale_model(
                load_config()["upscale"].get("image_model"))
        except ValueError:
            image_model = None
        anchor = ["5", 0]
        if image_model:
            graph["h3:up:imgloader"] = {"class_type": "UpscaleModelLoader",
                                        "inputs": {"model_name": image_model}}
            graph["h3:up:imgup"] = {"class_type": "ImageUpscaleWithModel", "inputs": {
                "upscale_model": ["h3:up:imgloader", 0], "image": ["5", 0]}}
            anchor = ["h3:up:imgup", 0]
        graph["h3:up:imgfit"] = {"class_type": "ImageScale", "inputs": {
            "image": anchor, "upscale_method": "lanczos",
            "width": w2, "height": h2, "crop": "disabled"}}
        # Conditioning rebuilt AT the 2x canvas: same brief, same length,
        # every other input identical to the render's own node 6.
        graph["h3:up:cond"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            **graph["6"]["inputs"], "width": w2, "height": h2,
            "first_frame": ["h3:up:imgfit", 0]}}
        graph["h3:up:param"] = {"class_type": "MMH3LatentUpscaleWithModelParams",
                                "inputs": {
            "model_name": H3_LATENT_UPSCALER, "width": w2, "height": h2,
            "device": "cuda", "precision": "bf16"}}
        graph["h3:up:tiles"] = {"class_type": "MMH3SpatialSplitParams", "inputs": {
            "tile_width": tile_w, "tile_height": tile_h,
            "spatial_w_overlap": ol_w, "spatial_h_overlap": ol_h,
            "fade_width": max(32, ol_w - 32),
            "fade_height": max(32, ol_h - 32),
            "min_tile_size": 256,
            "overlap_mode": "earlier", "overlap_blend": "smoothstep"}}
        graph["h3:up:sigmas"] = {"class_type": "BasicScheduler", "inputs": {
            "model": [refine_tail, 0], "scheduler": scheduler,
            "steps": H3_UPSCALE_STEPS, "denoise": H3_UPSCALE_DENOISE}}
        graph["h3:up:noise"] = {"class_type": "RandomNoise", "inputs": {
            "noise_seed": int(seed) + 1}}
        graph["h3:up:sample"] = {"class_type": H3_UPSCALE_NODE, "inputs": {
            "model": [refine_tail, 0], "conditioning": ["h3:up:cond", 0],
            "latent": ["11", 0], "noise": ["h3:up:noise", 0],
            "sampler": ["7", 0], "sigmas": ["h3:up:sigmas", 0], "cfg": 1.0,
            "latent_upscale_param": ["h3:up:param", 0],
            "spatial_split_param": ["h3:up:tiles", 0]}}
        graph["h3:up:decode"] = {"class_type": "VAEDecode", "inputs": {
            "samples": ["h3:up:sample", 0], "vae": ["3", 0]}}
        # One video output, the 2x. Audio stays the render's own decode - the
        # pack carries the 32-channel audio latent through untouched and never
        # re-samples it.
        graph["14"]["inputs"]["images"] = ["h3:up:decode", 0]
    lora_info = lora_job_info(video_loras)
    for row, entry in zip(lora_info["lora_stack"], video_loras):
        row.update(title=entry["title"], trigger=entry.get("trigger"))
    info = {
        "model": "MiniMax H3 FL2VA",
        "model_path": h3_assets["model"],
        "model_family": "minimax_h3",
        # the resolved lane, so a reroll resolves the right builder
        "model_variant": h3_model_variant(model_id),
        "execution_profile": "minimax_h3_fl2va_i2v",
        "engine": "MiniMax H3",
        "engine_id": "h3",
        "text_encoder": "Qwen3-VL 32B · NVFP4 AWQ",
        # Read back from what was actually resolved, never the constants: turbo
        # swaps all three, and this string is the one place the user can check
        # what ran.
        "sampler": f"{sampler_name} · {scheduler} · {steps} steps",
        "audio": "native synchronized audio",
        # what actually ran, not what was asked for: a mode whose LoRA is
        # missing silently falls back to the 20-step path, and the ledger
        # should say "quality" in that case rather than the mode that failed
        "speed_mode": ((h3_speed_mode(turbo) or {}).get("id", H3_SPEED_DEFAULT)
                       if turbo_rows else H3_SPEED_DEFAULT),
        "sparse_attention": h3_sparse_active(sparse),
        # Only ever present when the 2x pass was actually wired in - and when
        # it was, size/canvas_mp below report the canvas the delivered clip
        # actually has, the 2x one. canvas_mp is also what the VRAM butler
        # prices on, and the job's peak (30.9 GB of 32.6, measured) sits in
        # the tiled pass, so the bigger number is the true one in both
        # places - same convention as LTX 2.5's clip upscale.
        **({"upscale": "2x"} if upscale_on else {}),
        "h3_warnings": h3_brief_lint(brief, frames / 24),
        **lora_info,
        "lora_triggers": lora_triggers,
        "size": (f"{width * 2}x{height * 2}" if upscale_on
                 else f"{width}x{height}"),
        "canvas_mp": (width * height * (4 if upscale_on else 1)) / 1e6,
        "frames": frames,
        "duration": f"{frames / 24:.2f}s @ 24fps",
    }
    return graph, brief, info


def build_h3_multishot(motion, seed, image, seconds=5, shots=None, width=None,
                       height=None, overrides=(), model=None, lora_plan=None,
                       anchor=None, memory=None, turbo=False, sparse=True):
    """MiniMax H3 FL2VA multishot: one chained take per script prompt.

    ComfyUI-H3-Multishot's sampler runs the same stack build_h3_i2v wires by
    hand (BasicScheduler simple -> res_multistep -> BasicGuider ->
    SamplerCustomAdvanced at 20 steps), so the look matches the single-shot
    path. What it adds is the chain: each shot starts from the previous shot's
    last frame, and the duplicated seam frame plus its 1/24s of audio are
    trimmed. ``seconds`` is PER SHOT - a 3-shot 10s job is a ~30s video.

    Chaining on the last frame alone is a copy of a copy: by shot three the face
    is conditioned on an image the sampler itself drew twice, and identity
    slides. ``anchor`` pins frame(s) from the ORIGINAL start image into every
    shot, which is the pack's own fix for that drift; ``memory`` widens how many
    recent shot-end frames the encoder sees. Both 0 = the plain sampler.
    """
    model_id = str(model or H3_MODEL_ID).strip().lower()
    model_rel = h3_model_rel(model_id)
    if model_rel is None:
        raise ValueError(f"MiniMax H3 does not have model: {model_id}")
    if not h3_multishot_available():
        raise ValueError("MiniMax H3 multishot needs the ComfyUI-H3-Multishot "
                         "node pack, which is not installed")
    # The pack drives keyframe conditioning semantics, and ref2va+keyframes is
    # untested upstream - chained multishot refuses a ref2va chip outright.
    if h3_model_variant(model_id) == H3_REF2V_MODEL_ID:
        raise ValueError(
            "MiniMax H3 multishot is FL2VA-only: ref2va renders a single "
            "continuous scene from its references")
    h3_assets, missing = _h3_asset_paths(model_rel)
    if missing:
        raise ValueError("MiniMax H3 is unavailable: " + ", ".join(missing))
    image, width, height = _h3_prepared_canvas(image, width, height)
    frames = h3_frame_count(seconds)

    script = split_shot_script(motion)
    if not script:
        raise ValueError("MiniMax H3 multishot needs a motion brief")
    count = len(script) if shots is None else int(shots)
    if not 1 <= count <= H3_SHOTS_MAX:
        raise ValueError(f"MiniMax H3 multishot supports 1-{H3_SHOTS_MAX} shots")
    anchor = H3_ANCHOR_FRAMES if anchor is None else max(0, min(2, int(anchor)))
    memory = H3_MEMORY_FRAMES if memory is None else max(0, min(6, int(memory)))
    sampler = h3_multishot_node(anchor, memory)

    video_loras = resolve_h3_video_lora_stack(lora_plan, model_id)
    steps, sampler_name, scheduler, turbo_rows = h3_speed_settings(turbo)
    video_loras = turbo_rows + video_loras
    # Triggers and the audio instruction ride EVERY shot: the node tokenizes
    # each prompt on its own, so anything present only in shot one is simply
    # absent from the rest of the take.
    written, lora_triggers = [], []
    for prompt in script:
        text, lora_triggers = inject_video_lora_triggers(prompt, video_loras)
        if H3_AUDIO_PROMPT not in text:
            text = text.rstrip() + "\n\n" + H3_AUDIO_PROMPT
        written.append(text)
    brief = f"\n{H3_SHOT_SEPARATOR}\n".join(written)

    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": h3_assets["model"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": h3_assets["clip"], "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": h3_assets["video_vae"]}},
        "4": {"class_type": "VAELoader", "inputs": {
            "vae_name": h3_assets["audio_vae"]}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image}},
        # One node replaces the conditioning/guider/sampler/decode chain: it owns
        # the per-shot loop, the seam trim and the audio crossfade.
        "6": {"class_type": sampler, "inputs": {
            "model": ["1", 0], "clip": ["2", 0],
            "video_vae": ["3", 0], "audio_vae": ["4", 0],
            "start_image": ["5", 0], "script": brief, "shot_count": count,
            "width": width, "height": height, "frames_per_shot": frames,
            "seed": int(seed), "steps": steps,
            "sampler_name": sampler_name, "scheduler": scheduler,
            # Measured by the pack author: one seed for every shot drifts BOTH
            # the face and the voice. Identity lives in the conditioning.
            "seed_per_shot": True}},
        "7": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["6", 0], "audio": ["6", 1], "frame_rate": 24,
            "loop_count": 0,
            # same encode policy as the single-shot graph: CRF 14, never bitrate
            "filename_prefix": f"pixal_dm/h3_multishot_{slug(script[0])[:20]}",
            "format": "video/h264-mp4", "crf": 14, "pix_fmt": "yuv420p",
            "pingpong": False, "save_output": True}},
    }
    # Only the memory sampler declares these, and there they are REQUIRED. Set
    # before the override loop so a caller can still tune them by hand.
    if sampler == H3_MULTISHOT_MEMORY_NODE:
        graph["6"]["inputs"]["anchor_frames"] = anchor
        graph["6"]["inputs"]["memory_frames"] = memory
    for override in overrides:
        node_id = str(override.get("node"))
        input_name = override.get("input")
        if node_id not in graph or input_name not in graph[node_id]["inputs"]:
            raise ValueError(f"invalid MiniMax H3 override: {node_id}.{input_name}")
        graph[node_id]["inputs"][input_name] = override.get("value")
    model_tail = apply_lora_nodes(graph, "1", video_loras, "h3:lora")
    model_tail = apply_h3_sparse(graph, model_tail, sparse)
    graph["6"]["inputs"]["model"] = [model_tail, 0]
    lora_info = lora_job_info(video_loras)
    for row, entry in zip(lora_info["lora_stack"], video_loras):
        row.update(title=entry["title"], trigger=entry.get("trigger"))
    total = frames if count == 1 else frames + (count - 1) * (frames - 1)
    info = {
        "model": "MiniMax H3 FL2VA",
        "model_path": h3_assets["model"],
        "model_family": "minimax_h3",
        "model_variant": h3_model_variant(model_id),
        "execution_profile": "minimax_h3_fl2va_multishot",
        "engine": "MiniMax H3",
        "engine_id": "h3",
        "text_encoder": "Qwen3-VL 32B · NVFP4 AWQ",
        # Read back from what was actually resolved, never the constants: turbo
        # swaps all three, and this string is the one place the user can check
        # what ran.
        "sampler": f"{sampler_name} · {scheduler} · {steps} steps",
        "audio": "native synchronized audio",
        # per shot, not per take: the budget is what one 5s beat can hold, so
        # a chained multishot is linted a shot at a time
        "sparse_attention": h3_sparse_active(sparse),
        "h3_warnings": [w for shot in script[:count]
                        for w in h3_brief_lint(shot, frames / 24)],
        **lora_info,
        "lora_triggers": lora_triggers,
        "size": f"{width}x{height}",
        "canvas_mp": (width * height) / 1e6,
        "shots": count,
        "frames": total,
        # Shots are sampled one at a time and concatenated on the CPU
        # (h3_multishot_utils appends each shot's frames as .cpu() tensors), so
        # the card only ever holds one of them. `frames` is what the user gets;
        # `peak_frames` is what the card has to survive, and pricing an 8-shot
        # take on 2891 frames would evict everything for a job that needs 362.
        "peak_frames": frames,
        "duration": f"{total / 24:.2f}s @ 24fps · {count} shots",
    }
    return graph, brief, info


# Reference LoadImage node ids follow build_h3_i2v's numbering (5, 5b, 5c ...)
# so the two builders stay legible side by side.
_H3_REF2V_REF_NODES = ("5", "5b", "5c", "5d", "5e", "5f", "5g", "5h", "5i")


def build_h3_ref2v(motion, seed, refs, seconds=5, width=None, height=None,
                   overrides=(), model=None, lora_plan=None, turbo=False,
                   sparse=True):
    """MiniMax H3 REF2VA: put THIS subject in a new scene. Sibling of
    build_h3_i2v; the model chip is the lane switch, per render.

    The graph is the official R2V template ported into Pixal's API shape: the
    proven fl2va spine byte-for-byte (encoder, both VAEs, KSamplerSelect
    res_multistep, BasicScheduler simple/20/1.0, BasicGuider, RandomNoise,
    SamplerCustomAdvanced, VAEDecode/VAEDecodeAudio, the VHS tail at CRF 14)
    with exactly three deltas - the UNET points at the ref2va build, node 6 is
    MiniMaxH3ReferenceToVideo (which takes audio_vae, and whose reference
    slots are flat dotted keys: ref_images.ref_image_0, ...), and the prompt
    is the six-section brief assemble_h3_ref2v_prompt emits. The scheduler
    stays `simple`: the template's own note prefers beta for reference-heavy
    prompts, but its shipped widget is [simple, 20, 1] and simple is Pixal's
    proven spine - the tip is logged in 9.12-evidence as unverified.

    ``refs`` are staged in ComfyUI/input as RAW copies, never through
    prepare_h3_frame: a first frame anchors geometry and is center-cropped to
    the canvas for it, while a reference carries identity - the node scales
    refs itself, aspect-preserved (ref_image_size "match"), and cropping to
    canvas would throw away exactly what the ref exists to carry.
    """
    model_id = str(model or H3_REF2V_MODEL_ID).strip().lower()
    model_rel = h3_model_rel(model_id)
    if model_rel is None:
        raise ValueError(f"MiniMax H3 does not have model: {model_id}")
    # The reciprocal guard, twin of build_h3_i2v's: between them every lane
    # crossing is closed, including the ones nobody has thought of yet.
    if h3_model_variant(model_id) != H3_REF2V_MODEL_ID:
        raise ValueError(
            f"MiniMax H3 model {model_id} is not a ref2va build - reference "
            f"video needs a REF2VA chip")
    h3_assets, missing = _h3_asset_paths(model_rel)
    if missing:
        raise ValueError("MiniMax H3 is unavailable: " + ", ".join(missing))

    refs = [input_ref_name(r) for r in (refs or [])]
    refs = [r for r in refs if r]
    # Zero refs is silently t2va-on-ref2va-weights (minimax.py's falsy path:
    # no ref_items, no minimax_refs payload, no error anywhere). Almost never
    # the user's intent, so it is refused at build time - the one gate every
    # path (animate, reroll, tool call) must pass.
    if not refs:
        raise ValueError(
            "MiniMax H3 REF2VA needs at least one reference image - with none "
            "wired it would silently render plain text-to-video on ref2va weights")
    if len(refs) > H3_REF2V_MAX_IMAGES:
        raise ValueError(
            f"MiniMax H3 REF2VA wires at most {H3_REF2V_MAX_IMAGES} reference "
            f"images (the node schema's max); {len(refs)} were passed")
    for staged in refs:
        if not (CDIR / "input" / staged).is_file():
            raise ValueError(
                f"MiniMax H3 reference image is missing from ComfyUI/input: {staged}")
    if width is None or height is None:
        # No prepared frame defines the canvas in this lane; derive it from
        # the first reference's aspect through the same adaptive-canvas logic.
        from PIL import Image
        with Image.open(CDIR / "input" / refs[0]) as opened:
            width, height = h3_adapt_canvas(*opened.size)
    width, height = int(width), int(height)
    if width <= 0 or height <= 0 or width % H3_CANVAS_MULTIPLE or \
            height % H3_CANVAS_MULTIPLE:
        raise ValueError("MiniMax H3 canvas must use positive multiples of 32")

    frames = h3_frame_count(seconds)
    brief = str(motion or "").strip()
    if not brief:
        raise ValueError("MiniMax H3 needs a motion brief")
    # The dangling-ordinal policy runs here as well as in the assembler:
    # rerolls submit the stored brief without re-assembling, and the node
    # itself never complains about a tag nothing is wired to.
    brief, tag_warnings = h3_ref2v_tag_check(brief, len(refs))
    video_loras = resolve_h3_video_lora_stack(lora_plan, model_id)
    brief, lora_triggers = inject_video_lora_triggers(brief, video_loras)
    # H3_AUDIO_PROMPT is NOT appended in this lane: it would add instruction
    # prose plus a second, contradictory non_diegetic_music field to a format
    # that has no instruction line. Its two load-bearing rules (speech begins
    # and finishes inside the clip; no unasked score) live in the ref2va
    # director's OUTPUT CONTRACT.
    mode = h3_speed_mode(turbo)
    if mode is not None and H3_REF2V_MODEL_ID not in mode["variants"]:
        raise ValueError(
            f"{mode['label']} is an FL2VA distillation and no ref2v turbo LoRA "
            f"is on disk - a REF2VA chip renders at Quality, 20 steps")
    steps, sampler_name, scheduler, turbo_rows = h3_speed_settings(turbo)
    video_loras = turbo_rows + video_loras

    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": h3_assets["model"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": h3_assets["clip"], "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": h3_assets["video_vae"]}},
        "4": {"class_type": "VAELoader", "inputs": {
            "vae_name": h3_assets["audio_vae"]}},
        "6": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0],
            "prompt": brief, "width": width, "height": height,
            "length": frames, "ref_image_size": "match"}},
        # Only the ref slots actually wired are emitted: an unwired Autogrow
        # arrives as {} and the node's (ref_images or {}) guard handles it,
        # so omission is safe - and a present-but-empty slot is not.
        "7": {"class_type": "KSamplerSelect",
              "inputs": {"sampler_name": sampler_name}},
        "8": {"class_type": "BasicScheduler", "inputs": {
            "model": ["1", 0], "scheduler": scheduler, "steps": steps,
            "denoise": 1.0}},
        # H3 is CFG-distilled: the verified graph uses BasicGuider, not CFGGuider.
        "9": {"class_type": "BasicGuider", "inputs": {
            "model": ["1", 0], "conditioning": ["6", 0]}},
        "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed)}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["10", 0], "guider": ["9", 0], "sampler": ["7", 0],
            "sigmas": ["8", 0], "latent_image": ["6", 1]}},
        "12": {"class_type": "VAEDecode", "inputs": {
            "samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "VAEDecodeAudio", "inputs": {
            "samples": ["11", 0], "vae": ["4", 0]}},
        "14": {"class_type": "VHS_VideoCombine", "inputs": {
            # Same encode policy as the fl2va graph: CRF 14, never bitrate.
            "images": ["12", 0], "audio": ["13", 0], "frame_rate": 24,
            "loop_count": 0,
            "filename_prefix": f"pixal_dm/h3_ref_{slug(h3_slug_source(brief))[:24]}",
            "format": "video/h264-mp4", "crf": 14, "pix_fmt": "yuv420p",
            "pingpong": False, "save_output": True}},
    }
    for i, staged in enumerate(refs):
        graph[_H3_REF2V_REF_NODES[i]] = {
            "class_type": "LoadImage", "inputs": {"image": staged}}
        graph["6"]["inputs"][f"ref_images.ref_image_{i}"] = \
            [_H3_REF2V_REF_NODES[i], 0]
    for override in overrides:
        node_id = str(override.get("node"))
        input_name = override.get("input")
        if node_id not in graph or input_name not in graph[node_id]["inputs"]:
            raise ValueError(f"invalid MiniMax H3 override: {node_id}.{input_name}")
        graph[node_id]["inputs"][input_name] = override.get("value")
    model_tail = apply_lora_nodes(graph, "1", video_loras, "h3:lora")
    model_tail = apply_h3_sparse(graph, model_tail, sparse)
    # Both consumers must see the identical literal chain, as in build_h3_i2v.
    graph["8"]["inputs"]["model"] = [model_tail, 0]
    graph["9"]["inputs"]["model"] = [model_tail, 0]
    lora_info = lora_job_info(video_loras)
    for row, entry in zip(lora_info["lora_stack"], video_loras):
        row.update(title=entry["title"], trigger=entry.get("trigger"))
    info = {
        "model": "MiniMax H3 REF2VA",
        "model_path": h3_assets["model"],
        "model_family": "minimax_h3",
        "model_variant": H3_REF2V_MODEL_ID,
        "execution_profile": "minimax_h3_ref2v",
        "engine": "MiniMax H3",
        "engine_id": "h3",
        "text_encoder": "Qwen3-VL 32B · NVFP4 AWQ",
        # Read back from what was actually resolved, never the constants.
        "sampler": f"{sampler_name} · {scheduler} · {steps} steps",
        "audio": "native synchronized audio",
        "speed_mode": ((h3_speed_mode(turbo) or {}).get("id", H3_SPEED_DEFAULT)
                       if turbo_rows else H3_SPEED_DEFAULT),
        "references": len(refs),
        "sparse_attention": h3_sparse_active(sparse),
        "h3_warnings": (tag_warnings
                        + h3_ref2v_unnamed_lint(brief, len(refs))
                        + h3_brief_lint(brief, frames / 24)),
        **lora_info,
        "lora_triggers": lora_triggers,
        "size": f"{width}x{height}",
        "canvas_mp": (width * height) / 1e6,
        "frames": frames,
        "duration": f"{frames / 24:.2f}s @ 24fps",
    }
    return graph, brief, info


CRITIC_Q = ("You are a blunt creative director reviewing one AI-generated photo. Reply in "
            "EXACTLY these four labeled lines:\n"
            "LOOKS: one sentence - what the photo is doing.\n"
            "WORKS: the single strongest concrete thing (light, gesture, or detail).\n"
            "PROBLEMS: blunt list of visible issues - check hands and fingers, extra or "
            "warped limbs, warped text, ghost or dark blobs, plastic skin, a dead "
            "stock-photo pose, a gaze that reads to nothing; write 'none' if clean.\n"
            "FIX: one sentence - the single change that would most improve a re-roll.\n"
            "Under 90 words total.")

# PiD runs at v1.5's 2kto4k profile (1024px tiles, any aspect) with the INT8
# ConvRot diffusion model - near-bf16 quality at half the size - and the FP8
# Gemma encoder that release pairs it with. The zimage backbone shares its
# tile VAE with Flux1, which covers everything Pixal renders.
PID_UPSCALE_SETTINGS = {"version": "v1.5", "pid_ckpt_type": "2kto4k",
                        "model_precision": "int8", "backbone": "zimage"}

# --- PiD tile-ghosting guard (2026-08-16) -----------------------------------
# ComfyUI-PiD tiles 2kto4k at 1024px stepping by (1024 - 128), then blends the
# tiles with a raised-cosine ramp. The ramp width is always the NOMINAL 128px
# overlap - but tile_origins() appends a final tile flush to the edge, and that
# tile can overlap its neighbour by up to 896px. Wherever the real overlap
# exceeds twice the ramp, both tiles sit at full weight and the output is a flat
# 50/50 average of two 4-step passes run at DIFFERENT seeds (the pack seeds each
# tile as seed_base + tile.index, so they always disagree).
#
# Averaging two hallucinations is invisible on skin and hair, and shows as a
# doubled ghost edge on teeth, lashes and iris rims. Measured on a 1152x1728
# source: peak edge acutance 55 ghosted vs 79 for an untiled reference; padding
# to a clean extent recovers 66 at full resolution.
#
# Every canvas Pixal renders was affected - 896x1152 and 1152x1728 average a
# 640px band, 1056x1888 a 736px one. The fix is to hand PiD a source whose axes
# land on its own step, then trim the padding back off afterwards.
PID_TILE = 1024
PID_TILE_OVERLAP = 128
PID_TILE_STEP = PID_TILE - PID_TILE_OVERLAP


def pid_clean_extent(n):
    """Smallest length >= n that ComfyUI-PiD tiles using only its 128px ramp.

    <= one tile needs no padding at all; above that the origins must land on
    PID_TILE + k*PID_TILE_STEP so the flush-to-edge final tile IS the k-th step
    instead of a near-duplicate of it."""
    n = int(n)
    if n <= PID_TILE:
        return n
    steps = -(-(n - PID_TILE) // PID_TILE_STEP)
    return PID_TILE + steps * PID_TILE_STEP


def _reflect_pad(im, pw, ph):
    """Mirror-pad right and bottom. The pad is cropped off after the upscale, so
    it only has to be something the sampler will not invent a hard edge out of -
    mirrored content matches the pack's own reflect padding for edge tiles."""
    from PIL import Image
    w, h = im.size
    out = Image.new(im.mode, (pw, ph))
    out.paste(im, (0, 0))
    if pw > w:
        strip = im.crop((2 * w - pw, 0, w, h)).transpose(Image.FLIP_LEFT_RIGHT)
        out.paste(strip, (w, 0))
    if ph > h:                                   # after the width pad, so corners fill
        band = out.crop((0, 2 * h - ph, pw, h)).transpose(Image.FLIP_TOP_BOTTOM)
        out.paste(band, (0, h))
    return out


def pid_pad_source(src):
    """Reflect-pad a PiD source up to a cleanly-tiling size.

    Returns (input_name, (orig_w, orig_h)); the size is None when the image
    already tiles cleanly, in which case the caller must change nothing. The
    padded file is named for its target so repeat upscales of the same frame
    reuse it instead of piling up in ComfyUI/input."""
    from PIL import Image
    path = CDIR / "input" / src
    try:
        with Image.open(path) as im:
            w, h = im.size
            pw, ph = pid_clean_extent(w), pid_clean_extent(h)
            if (pw, ph) == (w, h):
                return src, None
            name = f"{Path(src).stem}__pidpad{pw}x{ph}.png"
            out = CDIR / "input" / name
            if not out.is_file():
                _reflect_pad(im.convert("RGB"), pw, ph).save(out)
    except Exception as exc:                     # unreadable source, no PIL, disk full
        print(f"[pixal] PiD pad skipped ({exc}); upscaling unpadded", flush=True)
        return src, None
    return name, (w, h)


# ComfyUI-PiD's 2kto4k profile carries small_edge = 1024, and _planned_pid_calls
# takes a completely different branch below it: it resizes the source to 1024,
# spends a WHOLE 4x PiD pass to get a 4096px working image, tiles THAT into 5x5,
# and finally downsamples the stitched 16k canvas back to source*4. That is
# 1 + 25 = 26 PiD calls at 4 steps each - the "sampling 24/104" Jesse hit - to
# produce a SMALLER picture than one pass on a 1024 source would.
#
# Measured on this machine 2026-08-22, same frame, same settings:
#   832 handed straight to PiD   26 passes   223.5s   ->  3328x3328
#   832 pre-scaled to 1024        4 passes    24.2s   ->  4096x4096
# 9.2x faster, larger, and no visible difference at 1:1 on either the face or
# the hair. The cliff is brutal and invisible: 1024 costs 4 steps, 1023 costs
# 104 - and Pixal's own 1:1 @ 1MP canvas lands on 992, thirty-two pixels under.
PID_SMALL_EDGE = 1024


def pid_lift_small_source(src):
    """Bring a sub-1024 source up to PiD's own small_edge before handing it over.

    Returns the input name to sample from - unchanged when the source is
    already 1024 or larger, which is the common case and must cost nothing.
    PiD would perform this exact resize itself as step one of the slow branch;
    doing it here just stops it from then re-upscaling its own output 25 more
    times and throwing the result away.
    """
    from PIL import Image
    path = CDIR / "input" / src
    try:
        with Image.open(path) as im:
            w, h = im.size
            if max(w, h) >= PID_SMALL_EDGE:
                return src                       # already on the fast branch
            scale = PID_SMALL_EDGE / float(max(w, h))
            # multiples of 16 keep every latent-space consumer happy; the long
            # edge is pinned to exactly small_edge so we clear the cliff by 0.
            tw = PID_SMALL_EDGE if w >= h else max(16, round(w * scale / 16) * 16)
            th = PID_SMALL_EDGE if h > w else max(16, round(h * scale / 16) * 16)
            name = f"{Path(src).stem}__pidlift{tw}x{th}.png"
            out = CDIR / "input" / name
            if not out.is_file():
                im.convert("RGB").resize((tw, th), Image.LANCZOS).save(out)
    except Exception as exc:                     # unreadable source, no PIL, disk full
        print(f"[pixal] PiD lift skipped ({exc}); upscaling as-is", flush=True)
        return src
    print(f"[pixal] PiD source lifted {w}x{h} -> {tw}x{th}: "
          f"26 passes become 4", flush=True)
    return name


def _pid_scale_factor(value):
    """"4x" -> 4. The trim has to match whatever factor the graph ended up with,
    including one an override supplied."""
    try:
        return max(1, int(str(value or "4x").lower().rstrip("x")))
    except ValueError:
        return 4

# PiD as the finishing decoder: the sampler's final x0 latent goes straight to
# PiD (sigma 0) instead of the recipe VAE, coming back at 4x the base canvas.
# Krea 2 runs the Wan 2.1 VAE - the same 16ch latent space as Qwen-Image - so
# the qwenimage decoder is latent-compatible, though formally off-distribution.
PID_DECODE_SETTINGS = {"version": "v1.5", "pid_ckpt_type": "2kto4k",
                       "model_precision": "int8", "backbone": "qwenimage"}
# The 2kto4k profile decodes only these 1024-class base canvases (pack README).
PID_BASE_CANVASES = ((1024, 1024), (1024, 768), (768, 1024), (1008, 672),
                     (672, 1008), (1024, 576), (576, 1024), (1008, 432),
                     (432, 1008))

def pid_base_canvas(width, height):
    """Nearest 2kto4k base preset by aspect ratio; ties go to the larger one."""
    want = math.log(width / height)
    return min(PID_BASE_CANVASES,
               key=lambda wh: (abs(want - math.log(wh[0] / wh[1])),
                               -(wh[0] * wh[1])))

def pid_decode_node(latent_link, caption, seed):
    """A PiDDecode tail per the node's own schema, at the settled settings:
    4 steps, cfg 1.0, native 4x scale, sigma 0 = decode a finished latent."""
    return {"class_type": PID_DECODE_NODE, "inputs": {
        "latent": latent_link, "caption": caption, **PID_DECODE_SETTINGS,
        "pid_steps": 4, "scale": 0, "cfg_scale": 1.0, "sigma": 0.0,
        "seed": int(seed) % (2**31 - 1), "auto_download": True,
        "unload_comfy_before_pid": True, "aggressive_cleanup": True},
        "_meta": {"title": "PiD Decode"}}

def build_upscale_image(scene, seed, image=None, model=None, mode=None, overrides=()):
    """Run a finished still through the chosen enlarger.

    "model" mode is deterministic and diffusion-free: the frame is not
    re-sampled, so the content cannot drift, and the model's own factor decides
    the output size. "pid" mode trades that guarantee for generative detail -
    NVIDIA PiD repaints each tile in a 4-step diffusion pass at 4x."""
    src = input_ref_name(image)
    if not src:
        raise ValueError("upscale needs a source image in ComfyUI/input")
    if not (CDIR / "input" / src).is_file():
        raise ValueError(f"source image not found in ComfyUI/input: {src}")
    cfg = load_config()["upscale"]
    chosen_mode = mode if mode in UPSCALE_IMAGE_MODES else cfg.get("image_mode")
    if chosen_mode == "pid":
        if not _pid_upscale_available():
            raise ValueError("PiD upscaling needs the ComfyUI-PiD node pack")
        g = json.loads(json.dumps(TEMPLATES["pid_upscale"]))
        g["up:img"]["inputs"]["image"] = src
        g["up:pid"]["inputs"].update(PID_UPSCALE_SETTINGS)
        g["up:save"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene) or 'upscaled'}"
        for o in overrides:
            g[str(o["node"])]["inputs"][o["input"]] = o["value"]
        info = {"upscaler": "PiD 4× int8 convrot", "source_image": src}
        # Pad AFTER the overrides: one of them can swap the source image or the
        # upscale factor, and both decide what has to be trimmed back off.
        chosen_src = input_ref_name(g["up:img"]["inputs"]["image"]) or src
        # OFF by default since 2026-08-16: on real work the padding made things
        # visibly WORSE, not better ("tons of noise and artifacts" - Jesse). The
        # arithmetic says why. A 1152x1728 portrait pads to 1920x1920 - two
        # thirds of the width is mirrored filler - so PiD samples a 3.7 MP
        # canvas instead of 2.0 MP, in more tiles, at 4x, and every one of those
        # extra tiles is a fresh 4-step hallucination competing for VRAM. Trading
        # a ghosted overlap band for that is not a trade worth making by default.
        # "pid_clean_tiles": true in config.json opts back into the padded path.
        # Clear PiD's small_edge cliff first: below 1024 the pack spends 26
        # passes to make a smaller picture than 4 passes would. Orthogonal to
        # the padding below, and it runs on the DEFAULT path too, which is the
        # one everybody is actually on.
        lifted = pid_lift_small_source(chosen_src)
        if lifted != chosen_src:
            info["lifted"] = f"source raised to {PID_SMALL_EDGE}px before PiD"
        padded, real = ((lifted, None) if not cfg.get("pid_clean_tiles", False)
                        else pid_pad_source(lifted))
        if lifted != chosen_src and not (real and _pid_node_available("ImageCrop")):
            # The lifted frame feeds the SAMPLER only, for the same reason the
            # padded one does: "up:img" stays the real image so
            # PiDCaptionCreator keeps describing what the user actually made.
            g["up:liftimg"] = {"class_type": "LoadImage",
                               "inputs": {"image": lifted},
                               "_meta": {"title": "Lifted past PiD's small-edge cliff"}}
            g["up:pid"]["inputs"]["image"] = ["up:liftimg", 0]
        if real and _pid_node_available("ImageCrop"):
            factor = _pid_scale_factor(g["up:pid"]["inputs"].get("upscale_factor"))
            # The padded frame feeds the SAMPLER only. "up:img" stays the real
            # image so PiDCaptionCreator keeps describing it - caption the mirror
            # pad and the VLM reports what it sees, which on a 1152x1728 portrait
            # was "two women dance... creating a mirror image" (2026-08-16). That
            # caption conditions every tile, including the ones holding the real
            # subject, so padding the caption input made the output worse than
            # the tile ghosting it was fixing.
            g["up:padimg"] = {"class_type": "LoadImage",
                              "inputs": {"image": padded},
                              "_meta": {"title": "Padded for clean PiD tiling"}}
            g["up:pid"]["inputs"]["image"] = ["up:padimg", 0]
            g["up:crop"] = {"class_type": "ImageCrop", "inputs": {
                "image": ["up:pid", 0], "x": 0, "y": 0,
                "width": real[0] * factor, "height": real[1] * factor},
                "_meta": {"title": "Trim PiD tiling pad"}}
            g["up:save"]["inputs"]["images"] = ["up:crop", 0]
            info["tiling"] = (f"padded {real[0]}x{real[1]} -> "
                              f"{pid_clean_extent(real[0])}x{pid_clean_extent(real[1])} "
                              f"for clean {PID_TILE_OVERLAP}px tile overlaps")
        return g, scene, info
    chosen = resolve_upscale_model(model or cfg.get("image_model"))
    g = json.loads(json.dumps(TEMPLATES["upscale_image"]))
    g["up:model"]["inputs"]["model_name"] = chosen
    g["up:img"]["inputs"]["image"] = src
    g["up:save"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene) or 'upscaled'}"
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    info = {"upscaler": chosen, "source_image": src}
    return g, scene, info


def build_upscale_video(scene, seed, video=None, mode=None, scale=None,
                        prompt=None, overrides=()):
    """Run a finished clip through RTX Video Super Resolution, audio intact.

    Frames come back through VHS at the clip's own rate (read from the file, not
    assumed) and the source audio track is re-attached, so a MiniMax H3 clip
    keeps its native sound. The LTX 2.5 mode branches to a generative 2x
    re-render instead of the VSR filter."""
    path = Path(str(video or ""))
    if not video or not path.is_file():
        raise ValueError("upscale needs the rendered clip on disk")
    cfg = load_config()["upscale"]
    chosen_mode = mode if mode in UPSCALE_VIDEO_MODES else cfg.get("video_mode")
    if chosen_mode not in UPSCALE_VIDEO_MODES:
        chosen_mode = UPSCALE_VIDEO_DEFAULT_MODE
    if chosen_mode == LTX25_UPSCALE_MODE:
        return _build_ltx25_upscale_video(scene, seed, path, prompt, overrides)
    node = _video_upscale_node()
    if not node:
        raise ValueError("video upscaling needs the Deno RTX VFX node pack")
    low, high = UPSCALE_VIDEO_SCALE_RANGE
    try:
        chosen_scale = float(scale if scale is not None else cfg.get("video_scale", 2.0))
    except (TypeError, ValueError):
        chosen_scale = 2.0
    chosen_scale = min(max(chosen_scale, low), high)
    g = json.loads(json.dumps(TEMPLATES["upscale_video"]))
    g["uv:load"]["inputs"]["video"] = str(path)
    g["uv:vsr"]["class_type"] = node
    if node == "DenoRTXVFXEasyUpscale":
        g["uv:vsr"]["inputs"]["mode"] = chosen_mode
        g["uv:vsr"]["inputs"]["scale"] = chosen_scale
    else:
        # The NVIDIA pack's node takes only a quality tier, not a mode string.
        g["uv:vsr"]["inputs"] = {"images": ["uv:load", 0],
                                 "resize_type": "Scale",
                                 "quality": chosen_mode.rsplit(" ", 1)[-1].upper()}
    g["uv:save"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene) or 'upscaled'}"
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    info = {"upscaler": f"RTX {chosen_mode}", "video_scale": chosen_scale,
            "source_video": path.name}
    shape = clip_shape(path)
    if shape:
        width, height, frames = shape
        out = (int(width * chosen_scale), int(height * chosen_scale))
        info["canvas_mp"] = (out[0] * out[1]) / 1e6
        info["frames"] = frames
        info["size"] = f"{out[0]}x{out[1]} · {frames}f"
    return g, scene, info


def _ltx25_upscale_missing():
    """What the LTX 2.5 clip upscale still needs on disk (enhancer excluded -
    the refine pass never prompt-enhances)."""
    return [label for label, kind, rel in (
        ("LTX 2.5 transformer", "diffusion_models", LTX25_UNET),
        ("Gemma 4 text encoder", "text_encoders", LTX25_CLIP),
        ("LTX 2.5 video VAE", "vae", LTX25_VIDEO_VAE),
        ("LTX 2.5 audio VAE", "vae", LTX25_AUDIO_VAE),
        ("LTX 2.5 spatial upscaler", "latent_upscale_models", LTX25_UPSCALER),
    ) if not _video_asset(kind, rel)]


def _build_ltx25_upscale_video(scene, seed, path, prompt, overrides):
    """Re-render a finished clip at 2x through the LTX 2.5 latent upsampler.

    Ported from the community MiniMax H3 + LTX 2.5 graph (PeterDuncan
    MINIMAX_H3_LTX2.5_Upscaler_v1): encode the clip into the 2.5 video VAE,
    x2 latent upsample, then a 4-step denoise-0.15 refine with the audio
    latent riding along so lip sync survives. The SOURCE audio feeds the save
    node - the re-decoded LTX track sounds underwater - and the clip's own
    frame rate is kept, which for H3 clips is the 24fps its audio is baked at.
    """
    missing = _ltx25_upscale_missing()
    if missing:
        raise ValueError("LTX 2.5 upscale needs: " + ", ".join(missing))
    g = json.loads(json.dumps(TEMPLATES["ltx25_upscale_video"]))
    g["lu:load"]["inputs"]["video"] = str(path)
    g["lu:noise"]["inputs"]["noise_seed"] = int(seed)
    # The clip's original brief steers the refine, same as the source graph
    # feeding its H3 prompt forward; empty is fine at this low a denoise.
    g["lu:pos"]["inputs"]["text"] = str(prompt or "")
    g["lu:save"]["inputs"]["filename_prefix"] = f"pixal_dm/{slug(scene) or 'upscaled'}"
    if not _video_asset("loras", LTX25_DETAILER_LORA):
        g["lu:sage"]["inputs"]["model"] = ["lu:unet", 0]
        del g["lu:lora"]
    # Same optimistic contract as the engines: unknown until the first node
    # probe, then the patch is dropped if the pack is not installed.
    names = _COMFY_NODES["names"]
    if names is not None and "LTX2MemoryEfficientSageAttentionPatch" not in names:
        tail = g["lu:sage"]["inputs"]["model"]
        g["lu:sched"]["inputs"]["model"] = tail
        g["lu:guider"]["inputs"]["model"] = tail
        del g["lu:sage"]
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    info = {"upscaler": "LTX 2.5 latent 2x + 4-step refine",
            "source_video": path.name}
    # This is the heaviest thing in the app: every frame of the clip goes
    # through one un-tiled VAEEncode, a x2 latent upsample and a 4-step refine,
    # so the working set is the SOURCE's frames at FOUR times its pixel area.
    # An H3 15s clip lands at 1536x2688 x 362 frames. Priced flat it sat in the
    # same bracket as the RTX VSR filter, which is a pure image-space pass.
    shape = clip_shape(path)
    if shape:
        width, height, frames = shape
        info["canvas_mp"] = (width * height * 4) / 1e6      # after the x2
        info["frames"] = frames
        info["size"] = f"{width * 2}x{height * 2} · {frames}f"
    return g, scene, info


def build_review(scene, seed, image, overrides=()):
    """Local VL critique of a finished still: Qwen3-VL-4B inside ComfyUI (no sidecar
    torch fighting for VRAM). The saved file is the record - finalize reads it back
    (survives a websocket drop during the 8 GB model load)."""
    m = re.search(r"#(\w+)", scene)
    out_file = f"pixal_dm/review_{m.group(1) if m else 'x'}.txt"
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image}},
        "2": {"class_type": "AILab_QwenVL", "inputs": {
            "model_name": load_config()["critic"]["model"],
            "quantization": "None (FP16)",   # avoids backend-specific bitsandbytes DLL issues
            "attention_mode": "auto",
            "preset_prompt": "\U0001f5bc\ufe0f Simple Description",
            "custom_prompt": CRITIC_Q,
            "max_tokens": 512, "keep_model_loaded": True,
            "seed": int(seed) % 4294967295 + 1,      # node INT range is 1..2^32-1
            "image": ["1", 0]}},
        "4": {"class_type": "SaveText|pysssss", "inputs": {
            "root_dir": "output", "file": out_file, "append": "overwrite",
            "insert": True, "text": ["2", 0]}},
        # SaveText returns plain STRING with no ui payload, so the ws
        # "executed" event never carried the critique - and the file fallback
        # LOSES a race on cold loads (file mtime 15:26:33.939, finalize read 0
        # the same instant, 2026-08-13). ShowText's {"ui": {"text": ...}} is
        # what the bridge's capture actually reads; the file stays as backup.
        "5": {"class_type": "ShowText|pysssss", "inputs": {"text": ["2", 0]}},
    }
    info = {"model": "qwen3-vl-4b", "loras": [], "size": "review"}
    return g, scene, info


LOOK_Q = ("Inventory this photograph for a film crew in 80-120 words of plain "
          "prose. Name: the subject (build, hair) and their exact pose, hands "
          "and gaze; every visible garment and its state; every object they "
          "touch or that could plausibly move; the setting and its depth (what "
          "is beside and behind them); the light source with its direction and "
          "colour; anything already mid-motion. Only what is VISIBLE - no mood "
          "words, no story, no praise, no guesses about what is out of frame. "
          # The director builds the premise from the frame, so the look must
          # surface what makes THIS frame different - still as a visible fact,
          # never a story (the inventory rules above still bind it).
          "Then one final sentence: the single oddest or most charged VISIBLE "
          "detail in the frame - the concrete thing a director would build "
          "the shot around.")


def build_look(scene, seed, image, overrides=()):
    """The motion director's eyes, as the FALLBACK: the critic's proven QwenVL
    graph pointed at the exact start frame, asking for an inventory instead of
    a critique. Directing from the scene caption alone made the brief describe
    somebody else's sentence about the picture; the look gives the director
    ground truth to direct from.

    This is no longer the primary path. brain_vl_read asks the chat brain's
    own eyes first (Jesse, 2026-08-18: "I want it using the chats vision
    model!") and only reaches here when the brain cannot see or answers
    empty - and only when the critic's weights are already on disk.

    The paragraph that used to sit here said the managed brain "has no mmproj
    wired - on the local preset the chat brain is BLIND". That stopped being
    true when the projector was wired and _vision_smoke_test started proving
    it, and leaving it here cost real work: on 2026-08-23 it was read as
    current and a brief was written to build routing that already existed.
    A stale reason is worse than no reason."""
    m = re.search(r"#(\w+)", scene)
    out_file = f"pixal_dm/look_{m.group(1) if m else 'x'}.txt"
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image}},
        "2": {"class_type": "AILab_QwenVL", "inputs": {
            "model_name": load_config()["critic"]["model"],
            "quantization": "None (FP16)",   # avoids backend-specific bitsandbytes DLL issues
            "attention_mode": "auto",
            "preset_prompt": "\U0001f5bc️ Simple Description",
            "custom_prompt": LOOK_Q,
            "max_tokens": 512, "keep_model_loaded": True,
            "seed": int(seed) % 4294967295 + 1,      # node INT range is 1..2^32-1
            "image": ["1", 0]}},
        "4": {"class_type": "SaveText|pysssss", "inputs": {
            "root_dir": "output", "file": out_file, "append": "overwrite",
            "insert": True, "text": ["2", 0]}},
        # Same ShowText rider as build_review: the ws is the delivery path,
        # the saved file is the backup record.
        "5": {"class_type": "ShowText|pysssss", "inputs": {"text": ["2", 0]}},
    }
    info = {"model": "qwen3-vl look", "loras": [], "size": "look"}
    return g, scene, info

BUILDERS = {"realism": build_realism, "realism_ii": build_realism_ii,
            "fantasy": build_fantasy, "anime": build_anime, "zimage": build_zimage,
            "anima": build_anima,
            "identity_edit": build_zara_edit,
            "zara_edit": build_zara_edit,       # alias: pre-rename ledger entries
            "qwen_edit": build_qwen_edit, "qwen_image": build_qwen_image,
            "face_mint": build_face_mint, "klein_inpaint": build_klein_inpaint,
            "ltx_i2v": build_ltx_i2v, "ltx25_i2v": build_ltx25_i2v,
            "h3_i2v": build_h3_i2v,
            "h3_ref2v": build_h3_ref2v,
            "h3_multishot": build_h3_multishot,
            "upscale_image": build_upscale_image, "upscale_video": build_upscale_video,
            "vl_review": build_review, "vl_look": build_look}
SIGS = {name: set(inspect.signature(fn).parameters) - {"scene", "seed"}
        for name, fn in BUILDERS.items()}

# ----------------------------------------------------------------------------- state

class Hub:
    """SSE fan-out + job/ledger tracking + the ComfyUI websocket bridge."""
    def __init__(self):
        self.subs = set()            # asyncio.Queue per browser tab
        # Replay log for /api/poll, the no-open-stream transport. 4000 is a few
        # minutes of the heaviest traffic this emits (sampler progress at ~8/s),
        # so a phone that polls every second can never outrun it; a client that
        # falls further behind than the window is told to resync rather than
        # handed a hole it cannot see.
        self.event_log = collections.deque(maxlen=4000)
        self.event_seq = 0
        self.last_poll = 0.0         # last /api/poll hit - a window with no SSE
        self.jobs = {}               # job_id -> job dict
        self.by_prompt = {}          # comfy prompt_id -> job_id
        self.client_id = str(uuid.uuid4())
        self.comfy_up = False
        self.queue_remaining = 0
        self.gpu = None
        self.resident_heavies = {}   # model file -> bytes the vram butler believes
                                     # ComfyUI still holds resident (cleared on flush)
        self.paging_streak = 0       # consecutive gpu_watch reads that look like
                                     # WDDM paging (full card, busy cores, idle bus)
        self.prev_job_free_min = None  # _vram_free_min of the last finalized job -
                                     # the near-miss signal the guard-band trim in
                                     # ensure_vram consumes. None = no signal (the
                                     # job was never sampled), never zero.
        self.critic_hot = False      # the 8B VL critic is warm in ComfyUI's process
                                     # (keep_model_loaded) - cleared on every flush
        self.scan = None                     # startup catalog scan state (for late joiners)
        CHATS_DIR.mkdir(exist_ok=True)       # multi-chat: lane + LLM convo per chat
        self.chats = {}
        for p in CHATS_DIR.glob("*.json"):
            try:
                c = json.loads(p.read_text(encoding="utf-8"))
                self.chats[c["id"]] = c
            except Exception as exc:
                # Set the corrupt file aside instead of silently re-skipping it
                # forever - the user should see WHY a chat vanished.
                print(f"[pixal] unreadable chat {p.name}, moving aside: {exc}", flush=True)
                try:
                    p.replace(p.with_suffix(".json.bad"))
                except OSError:
                    pass
        if not self.chats and LANE_FILE.exists():   # migrate the single-lane era
            try:
                lane = json.loads(LANE_FILE.read_text(encoding="utf-8"))
                c = {"id": uuid.uuid4().hex[:8], "ts": time.time(), "lane": lane,
                     "convo": [], "title": next((e["text"][:48] for e in lane
                                                 if e.get("role") == "user"), "chat")}
                self.chats[c["id"]] = c
                self._save_chat(c)
                LANE_FILE.unlink(missing_ok=True)
            except Exception:
                pass
        if self.chats:
            self.active_chat = max(self.chats.values(), key=lambda c: c["ts"])["id"]
        else:
            self.new_chat()

    # the LLM context and the visible lane both belong to the ACTIVE chat
    @property
    def convo(self):
        return self.chats[self.active_chat]["convo"]

    @convo.setter
    def convo(self, _v):                     # legacy main() wiring - ignored
        pass

    @property
    def lane(self):
        return self.chats[self.active_chat]["lane"]

    def _save_chat(self, c):
        try:
            (CHATS_DIR / f"{c['id']}.json").write_text(
                json.dumps(c, ensure_ascii=False), encoding="utf-8")
        except (OSError, TypeError):
            pass

    def new_chat(self):
        c = {"id": uuid.uuid4().hex[:8], "title": "new chat", "ts": time.time(),
             "lane": [], "convo": []}
        self.chats[c["id"]] = c
        self.active_chat = c["id"]
        self._save_chat(c)
        return c

    def delete_chat(self, chat_id):
        self.chats.pop(chat_id, None)
        (CHATS_DIR / f"{chat_id}.json").unlink(missing_ok=True)
        if self.active_chat == chat_id:
            if self.chats:
                self.active_chat = max(self.chats.values(),
                                       key=lambda c: c["ts"])["id"]
            else:
                self.new_chat()

    def lane_add(self, entry):
        """Persist one lane line (user/assistant/job/review/error) so a browser
        refresh replays the chat instead of losing it. Job entries store only the
        id - /api/lane hydrates them from the ledger at read time. Saving the
        chat also persists its convo (the LLM context) as a side effect."""
        entry["ts"] = time.time()
        c = self.chats[self.active_chat]
        c["lane"] = (c["lane"] + [entry])[-120:]
        if entry.get("role") == "user" and c["title"] == "new chat":
            c["title"] = entry["text"][:48]   # first message names the chat
        c["ts"] = time.time()                 # list sorts by last activity
        self._save_chat(c)

    def broadcast(self, **event):
        event["ts"] = time.time()
        # Every event also lands in a sequenced replay log. SSE is the fast
        # path, but a never-ending HTTP response is hostile to the free tunnels
        # a remote session runs over - Cloudflare's edge buffers the stream and
        # releases nothing, and localtunnel hands it the whole connection pool
        # so every image request behind it 502s. /api/poll reads this log
        # instead, so the studio works over a plain sequence of short requests
        # with no open stream at all. See events_poll().
        self.event_seq += 1
        event["seq"] = self.event_seq
        self.event_log.append(event)
        t = event.get("type")
        if t == "text" and (event.get("text") or "").strip():
            self.lane_add({"role": "assistant", "text": event["text"]})
        elif t == "job":
            self.lane_add({"role": "job", "job_id": event.get("job_id")})
        elif t == "review":
            self.lane_add({"role": "review", "text": event.get("text"),
                           "fix": event.get("fix"), "parent": event.get("parent")})
        elif t == "error" and not event.get("job_id"):
            self.lane_add({"role": "error", "text": event.get("message")})
        dead = []
        for q in self.subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.subs.discard(q)

    def handle_preview(self, raw):
        """ComfyUI preview frame (BinaryEventTypes.PREVIEW_IMAGE = 1): 4-byte
        event type + 4-byte image format + JPEG/PNG bytes. Reduced to a tiny
        luminance grid (~4 KB) and pushed over SSE - the UI renders it as the
        dot-matrix generation preview. Structure only, never the pixels."""
        try:
            if len(raw) < 9 or int.from_bytes(raw[:4], "big") != 1:
                return
            job_id = getattr(self, "cur_job_id", None)
            if not job_id:
                return
            now = time.time()
            if now - getattr(self, "_last_preview", 0.0) < 0.12:
                return
            self._last_preview = now
            import base64
            import io
            from PIL import Image
            im = Image.open(io.BytesIO(raw[8:])).convert("L")
            scale = 64 / max(im.size)
            cols = max(8, round(im.size[0] * scale))
            rows = max(8, round(im.size[1] * scale))
            im = im.resize((cols, rows))
            self.broadcast(type="preview", job_id=job_id, cols=cols, rows=rows,
                           data=base64.b64encode(im.tobytes()).decode())
        except Exception:
            pass

    def ledger_append(self, entry):
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def ledger_delete(self, eid):
        """Rewrite the ledger without one entry; returns the removed entry or None.
        The ONE sanctioned exception to append-only - user-initiated delete."""
        entries = self.ledger_read()[::-1]          # back to file order
        entry = next((e for e in entries if e.get("id") == eid), None)
        if entry:
            with LEDGER.open("w", encoding="utf-8") as f:
                for e in entries:
                    if e.get("id") != eid:
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return entry

    def ledger_read(self):
        """Newest first. Cached on (mtime, size): /api/status polls every
        second and every chat turn resolves prior renders, which re-parsed the
        whole 600KB+ file each time. The sidecar is the only writer, so a
        changed file always changes the key. Callers must not mutate the list
        or its entries - copy before editing (ledger_delete already does)."""
        if not LEDGER.exists():
            return []
        try:
            stat = LEDGER.stat()
            key = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            key = None
        if key is not None and getattr(self, "_ledger_key", None) == key:
            return self._ledger_cache
        out = []
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        out = out[::-1]              # newest first
        if key is not None:
            self._ledger_key, self._ledger_cache = key, out
        return out

    def note_step_rate(self, job, data):
        """Say something when a sampling step is running many times too slow.

        This replaced a pre-flight VRAM check, which was wrong in the ordinary
        case: right after a render ComfyUI is still HOLDING ~25GB of resident
        models, so free VRAM reads low exactly when the next render is the fast
        one. A warning that cries wolf on every second render is worse than no
        warning at all.

        Measuring the step itself has no such failure. A healthy 15s H3 step is
        ~33s; the starved run was over five times that, because the weights
        were streaming from system memory. One message per job, and only after
        two consecutive slow steps, so a single stall - a preview decode, the
        first step paying for a model load - is not enough to trigger it.

        Two checks ride this one timing path. Below, the absolute one: any
        step past STEP_SLOW_SECONDS warns the lane. First, the relative one
        (PAGING_RATE_*): a collapse against the job's OWN opening median,
        which catches a page-out the absolute threshold is calibrated too
        high to see, and which only logs and ledger-records - the actuator
        decision is deliberately deferred (brief 9.10).
        """
        value, mx = data.get("value") or 0, data.get("max") or 0
        if mx <= 1 or value <= 0:
            return
        now, prev = time.time(), job.get("_step_at")
        job["_step_at"] = now
        if prev is None or value <= job.get("_step_value", 0):
            job["_step_value"] = value
            return
        job["_step_value"] = value
        # The relative watchdog first: every measured interval goes in,
        # because the healthy ones ARE the baseline it compares against.
        durations = job.setdefault("_step_durations", [])
        durations.append(now - prev)
        trip = paging_rate_trip(durations)
        if trip and not job.get("_paging_rate_tripped"):
            job["_paging_rate_tripped"] = True
            # The free figure is the gpu_watch sample the PAGING_* detector
            # already collects, kept per job as _vram_free_min - NEVER a
            # fresh nvidia-smi/NVML read: a GPU query on the per-step path
            # is exactly what the live-machine rule exists to prevent. A job
            # gpu_watch never sampled logs the trip without the figure.
            free_min = job.get("_vram_free_min")
            job["_paging_watchdog"] = {"step": trip["step"],
                                       "baseline_s": round(trip["baseline"], 2),
                                       "rate_s": round(trip["rate"], 2),
                                       "free_min": free_min}
            print(f"[pixal] paging-watchdog: {job.get('template')} step rate "
                  f"collapsed at step {trip['step']}: "
                  f"{trip['rate']:.0f}s/step vs {trip['baseline']:.1f}s baseline"
                  + (f", card free min {free_min / 2**30:.2f}GB"
                     if free_min is not None else ""), flush=True)
        if now - prev < STEP_SLOW_SECONDS:
            job["_slow_steps"] = 0
            return
        job["_slow_steps"] = job.get("_slow_steps", 0) + 1
        if job["_slow_steps"] < 2 or job.get("_slow_warned"):
            return
        job["_slow_warned"] = True
        job["_flush_after"] = True     # self-heal: clear the deck once it ends
        free = gpu_free_bytes()
        room = f"{free / 2**30:.1f}GB of VRAM is free" if free is not None \
            else "VRAM is short"
        ram = ram_free_bytes()
        ram_note = (f" System RAM is nearly gone too "
                    f"({ram / 2**30:.1f}GB left), which makes it worse."
                    if ram is not None and ram < RAM_FLOOR else "")
        self.broadcast(
            type="text", cid=job.get("cid"),
            text=(f"*this render is crawling - {now - prev:.0f}s per step, and "
                  f"{room}.* The model is being streamed from system memory "
                  f"rather than sitting on the card.{ram_note} It will finish "
                  f"and it will look right, and Pixal will clear cached models "
                  f"the moment it ends so the next one starts clean. If it is "
                  f"unbearable, restarting ComfyUI is the quick way out."))

    async def gpu_watch(self):
        """Push GPU/VRAM over SSE when it moves. /system_stats: vram_total/free are
        driver-level (whole device), which is what 'how full is the card' means."""
        last = None
        while True:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(f"{COMFY}/system_stats", timeout=10) as r:
                        d = await r.json()
                dev = next((x for x in d.get("devices", []) if x.get("type") == "cuda"), None)
                if dev:
                    total = dev.get("vram_total", 0) / 2**30
                    used = (dev.get("vram_total", 0) - dev.get("vram_free", 0)) / 2**30
                    raw = dev.get("name", "")
                    raw = re.sub(r"^\s*\w+:\d+\s*", "", raw)          # "cuda:0 " prefix
                    raw = raw.split(" : ")[0]                          # " : cudaMallocAsync" suffix
                    name = re.sub(r"^(NVIDIA|AMD) (GeForce|Radeon) ", "", raw).strip()
                    rt = d.get("system", {}).get("ram_total", 0) / 2**30
                    ru = (d.get("system", {}).get("ram_total", 0)
                          - d.get("system", {}).get("ram_free", 0)) / 2**30
                    cur = {"name": name, "used": round(used, 1), "total": round(total, 1),
                           "ram_used": round(ru, 1), "ram_total": round(rt, 1)}
                    if last is None or abs(cur["used"] - last["used"]) >= 0.1 \
                            or abs(cur["ram_used"] - last["ram_used"]) >= 0.5 \
                            or cur["name"] != last["name"]:
                        last = cur
                        self.gpu = cur
                        self.broadcast(type="gpu", **cur)
                # While a render is in flight, one nvidia-smi read per tick
                # does two jobs: it records each job's true VRAM peak
                # (finalize logs it against the butler's estimate, so a
                # drifting activation profile shows up BEFORE it OOMs), and it
                # feeds the WDDM paging detector - the crawl Windows never
                # reports (see PAGING_* constants).
                inflight = [j for j in self.jobs.values()
                            if not j.get("finalized") and
                            time.time() - j.get("started", 0) < JOB_INFLIGHT_SECONDS]
                if inflight:
                    st = await asyncio.to_thread(gpu_stats)
                    if st:
                        free_b, used_b, gu, mu = st
                        for j in inflight:
                            # The job's starting occupancy: set-once, so a
                            # later, larger read can never move it. gpu_watch
                            # is a timer, so this first sample can land just
                            # after weight loading has begun - a near-start,
                            # not an exact pre-submit read. That stays: an
                            # inline read at submit time stalled the event
                            # loop and the SSE stream for the whole poll,
                            # which is why these live in to_thread at all.
                            j.setdefault("_vram_start_used", used_b)
                            j["_vram_peak"] = max(j.get("_vram_peak", 0), used_b)
                            j["_vram_free_min"] = min(
                                j.get("_vram_free_min", free_b), free_b)
                        starved = (free_b < PAGING_FREE_FLOOR
                                   and gu >= PAGING_GPU_MIN
                                   and mu <= PAGING_MEMBUS_MAX)
                        self.paging_streak = self.paging_streak + 1 if starved else 0
                        # == not >=, so one episode narrates once and a streak
                        # that keeps climbing stays quiet.
                        if self.paging_streak == PAGING_STREAK:
                            print(f"[pixal] paging: {free_b / 2**30:.2f}GB free, "
                                  f"gpu {gu}%, membus {mu}%", flush=True)
                            for j in inflight:
                                if not j.get("_paging_warned"):
                                    j["_paging_warned"] = True
                                    self.broadcast(type="text", cid=j["cid"], text=(
                                        "*this render is paging - the card is full, "
                                        "so the GPU is streaming weights from system "
                                        "RAM instead of computing. It will crawl; "
                                        "cancelling and asking smaller, or closing "
                                        "other GPU apps, is usually faster*"))
                else:
                    self.paging_streak = 0
            except Exception:
                pass
            await asyncio.sleep(3)

    async def bridge(self):
        """One permanent websocket to ComfyUI: progress + queue state -> SSE."""
        while True:
            try:
                async with aiohttp.ClientSession() as s:
                    # A hung handshake inherited aiohttp's 5-minute default
                    # timeout: ComfyUI's loop stalls while it loads big models,
                    # HTTP answers between stalls, and the app gate sat on
                    # "waiting for ComfyUI" for minutes against a server that
                    # was up. 15s caps one attempt; the loop retries in 3s.
                    ws = await asyncio.wait_for(
                        s.ws_connect(f"{COMFY_WS}?clientId={self.client_id}",
                                     heartbeat=60), 15)   # VL loads stall pongs
                    async with ws:
                        self._ws = ws          # settings can close it to force a re-aim
                        if not self.comfy_up:
                            # Reconnecting means the ComfyUI we were tracking
                            # may not be the one we are now talking to. What it
                            # holds is unknowable from here, and a residency
                            # claim is a CREDIT - guessing high wastes a flush,
                            # guessing wrong wastes the render.
                            self.forget_residency("comfy reconnected")
                        self.comfy_up = True
                        self.last_ws_seen = time.time()
                        self.broadcast(type="status", comfy=True)
                        async for msg in ws:
                            self.last_ws_seen = time.time()
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                self.handle_preview(msg.data)
                                continue
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            d = json.loads(msg.data)
                            t, data = d.get("type"), d.get("data", {})
                            pid = data.get("prompt_id")
                            job = self.jobs.get(self.by_prompt.get(pid, ""), {})
                            if t == "progress" and job:
                                self.cur_job_id = job["id"]   # binary previews carry no id
                                self.note_step_rate(job, data)
                                self.broadcast(type="progress", job_id=job["id"],
                                               value=data.get("value", 0),
                                               max=data.get("max", 0),
                                               node=data.get("node"))
                            elif t == "executed" and job:
                                out = data.get("output") or {}
                                for img in (out.get("images") or []) + (out.get("gifs") or []):
                                    self.add_image(job, img)
                                if out.get("text"):
                                    job.setdefault("texts", []).extend(
                                        str(x) for x in out["text"])
                                    print(f"[pixal] text captured <- job {job['id']} "
                                          f"({len(out['text'])} parts)", flush=True)
                            elif t == "executed" and not job:
                                print(f"[pixal] executed for UNMAPPED prompt "
                                      f"{str(pid)[:8]} node {data.get('node')}", flush=True)
                            elif t == "executing" and data.get("node") is None and job:
                                self.pid_done(job, pid)      # prompt finished executing
                            elif t == "executing" and job:
                                # narrate the stage this node represents (dedup'd)
                                ct = (job.get("node_types") or {}).get(
                                    str(data.get("node")), "")
                                ph = self.stage_phrase(job, ct)
                                if ph and ph != job.get("stage"):
                                    job["stage"] = ph
                                    self.broadcast(type="thinking", cid=job["cid"],
                                                   note=ph)
                            elif t == "execution_success" and job:
                                self.pid_done(job, pid)
                            elif t == "status":
                                self.queue_remaining = (data.get("status", {})
                                                        .get("exec_info", {})
                                                        .get("queue_remaining", 0))
                            elif t == "execution_error" and job:
                                job["error"] = data.get("exception_message", "execution error")
                                # ComfyUI names the node that threw. We were
                                # dropping it, so an OOM in the VAE decode was
                                # indistinguishable from one in the sampler -
                                # and the retry shortened the clip, which is
                                # the wrong lever when the sampling finished.
                                job["_oom_node"] = {
                                    "id": str(data.get("node_id") or ""),
                                    "type": str(data.get("node_type") or "")}
                                self.finalize(job)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                pass                      # comfy down/restarting - retry quietly
            except Exception as exc:
                # A dispatch bug would otherwise look identical to "comfy down".
                print(f"[pixal] comfy bridge dropped: {type(exc).__name__}: {exc}",
                      flush=True)
            if self.comfy_up:
                self.comfy_up = False
                self.broadcast(type="status", comfy=False)
            await asyncio.sleep(3)

    def add_image(self, job, img):
        if img.get("type") != "output":
            return
        if not keep_video_output(job.get("template"), img.get("filename")):
            print(f"[pixal] skipped VHS silent twin {img.get('filename')}", flush=True)
            return
        key = (img.get("filename"), img.get("subfolder"))
        if key in job["seen"]:
            return
        job["seen"].add(key)
        fmt = str(img.get("format", ""))
        name = str(img.get("filename", "")).lower()
        img["media"] = "video" if fmt.startswith("video") or \
            name.endswith((".mp4", ".webm", ".mov", ".gif")) else "image"
        job["images"].append(img)
        self.broadcast(type="image", job_id=job["id"],  # img carries its own "type" - rename
                       filename=img.get("filename"), subfolder=img.get("subfolder", ""),
                       img_type=img.get("type"), media=img["media"])
        print(f"[pixal] {img['media']} {img.get('filename')} <- job {job['id']}", flush=True)

    def pid_done(self, job, pid):
        job["done_pids"].add(pid)
        if job["done_pids"] >= set(job["prompt_ids"]):
            self.finalize(job)

    def finalize(self, job):
        if job.get("finalized"):
            return
        job["finalized"] = True
        job["elapsed"] = round(time.time() - job["started"], 1)
        if job["template"] in ("vl_review", "vl_look"):
            # keep_model_loaded holds the critic warm across consecutive
            # looks; ensure_vram trusts this flag instead of flush-thrashing
            # an 8B reload per review. Every cache flush clears it.
            self.critic_hot = not job.get("error")
        if job["template"] == "vl_review":
            text = "\n".join(job.get("texts", [])).strip()
            if not text:                       # ws dropped mid-load - the file is the record
                fp = CDIR / "output" / \
                    f"pixal_dm/review_{job.get('parent') or job['id']}.txt"
                if fp.is_file():
                    try:
                        text = fp.read_text(encoding="utf-8").strip()
                    except Exception as exc:
                        print(f"[pixal] review file unreadable: {exc}", flush=True)
                else:
                    # cold-load race: the write can land milliseconds AFTER
                    # this read - say which leg failed instead of guessing
                    print(f"[pixal] review file not there yet: {fp}", flush=True)
            print(f"[pixal] review finalize: texts={len(job.get('texts', []))} "
                  f"file_text={len(text)} chars", flush=True)
            fix_m = re.search(r"^FIX:\s*(.+)$", text, re.M)
            if text:
                self.broadcast(type="review", job_id=job["id"], cid=job["cid"],
                               parent=job.get("parent"), text=text,
                               fix=fix_m.group(1).strip() if fix_m else None)
                if self.convo is not None:
                    self.convo.append({"role": "system", "content":
                        f"[critic on #{job.get('parent') or job['id']}: {text}]"})
            else:
                self.broadcast(type="error", job_id=job["id"], cid=job["cid"],
                               message="critic returned nothing")
        if not job["images"] and not job.get("error") and \
                job["template"] not in ("vl_review", "vl_look"):
            # "success" with zero outputs = a graph value was silently invalid
            job["error"] = ("the render finished but produced nothing - usually a "
                            "bad model/lora/reference name in the request")
            self.broadcast(type="error", job_id=job["id"], cid=job["cid"],
                           message=job["error"])
        if job["images"]:
            entry = {"id": job["id"], "ts": job["started"], "template": job["template"],
                     "scene": job["scene"], "full_prompt": job.get("full_prompt", ""),
                     "seed": job["seed"], "count": job["count"], "spec": job["spec"],
                     "info": job.get("info"),
                     "images": job["images"], "elapsed": job["elapsed"],
                     "src": "reroll" if job.get("parent") else "chat"}
            if job.get("parent"):
                entry["parent"] = job["parent"]
            # The butler's numbers ride the DURABLE record, not just the
            # console. logs/sidecar.log rotates, and fitting ACT_PROFILES means
            # fitting the DELTA (peak - start) - which only exists if both
            # numbers outlive the session that measured them. The 126-render
            # analysis behind this telemetry had to be mined out of a log that
            # was one rotation away from being gone; the next one should read
            # the ledger instead.
            if job.get("_vram_peak"):
                entry["vram"] = {"priced": (job.get("_priced") or {}).get("est"),
                                 "start": job.get("_vram_start_used"),
                                 "peak": job["_vram_peak"],
                                 "free_min": job.get("_vram_free_min")}
            # A tripped rate watchdog is the same kind of number as the vram
            # block: sidecar.log rotates, so the collapse has to ride the
            # ledger or the future actuator gets designed against the one
            # 110s/step anecdote again instead of a measured rate.
            if job.get("_paging_watchdog"):
                entry["paging_watchdog"] = job["_paging_watchdog"]
            self.ledger_append(entry)
        if not job.get("_oom_retry") and looks_like_oom(job.get("error")):
            # The verdict is recorded as a flag rather than re-read from the
            # text later, because the very next line replaces that text with
            # something friendlier - and the friendlier wording does not match
            # the allocator's phrasing, so the retry would refuse itself.
            job["_oom"] = True
            # The plan itself is decided inside the task, AFTER the card has
            # been reclaimed - "how much fits" is a question about the card the
            # retry will get, not the one the failure left behind.
            job["error"] = "ran out of VRAM - clearing the card and retrying"
            asyncio.create_task(self.retry_after_oom(job))
        self.broadcast(type="jobdone", job_id=job["id"], cid=job["cid"],
                       elapsed=job["elapsed"], images=len(job["images"]),
                       error=job["error"])
        if job.get("_vram_peak"):
            # The line that makes ACT_PROFILES tunable by reading instead of
            # archaeology: what the butler priced next to what the card did.
            # The start figure turns the peak into a delta - how much of the
            # height was the job and how much was the card it was dealt.
            est = (job.get("_priced") or {}).get("est")
            start = job.get("_vram_start_used")
            print(f"[pixal] vram: {job['template']}"
                  + (f" priced {est / 2**30:.1f}GB," if est else "")
                  + (f" started {start / 2**30:.1f}GB used," if start else "")
                  + f" card peaked {job['_vram_peak'] / 2**30:.1f}GB used / "
                  f"{job.get('_vram_free_min', 0) / 2**30:.1f}GB free min",
                  flush=True)
        # Hand the butler the near-miss signal: how close to the wall the
        # last job ran. Unconditional - a job that was never sampled must
        # overwrite a low predecessor with None (no signal), or one bad night
        # trims every later job forever.
        self.prev_job_free_min = job.get("_vram_free_min")
        print(f"[pixal] job {job['id']} done: {len(job['images'])} img, "
              f"{job['elapsed']}s, err={job['error']}", flush=True)
        # A PiD stage leaves its trio (decoder + PixelDiT TE + autoencoder,
        # ~4.2GB) cached in ComfyUI's VRAM after the job. That cache buys
        # nothing - unload_comfy_before_pid already flushed every other model
        # to make room, so it holds PiD alone and PiD reloads in ~3s anyway -
        # but it costs the NEXT heavy job its activation headroom: the identity
        # stack went from ~11s/step to 110s/step of WDDM paging on a card
        # 99.9% full (2026-08-11). ComfyUI's own eviction only makes room for
        # weights, not activations, so the flush has to be ours. A job the
        # crawl detector flagged gets the same treatment - it already PROVED
        # the card is oversubscribed, so its cache is poison, not warmth.
        ran_pid = any(ct in (PID_UPSCALE_NODE, PID_DECODE_NODE)
                      for ct in (job.get("node_types") or {}).values())
        if ran_pid or job.get("_flush_after"):
            why = "pid leftovers" if ran_pid else "render crawled - card oversubscribed"
            asyncio.create_task(self.flush_comfy_cache(why))

    # ---------------------------------------------------------- oom recovery
    # An OOM used to be the end of the render: the lane printed ComfyUI's
    # allocator message and the user started again by hand. Every OOM in the
    # log was MARGINAL - 28-30GB live on a 31.84GB card, or one oversized
    # allocation on a card holding 13 - which means the same work on a properly
    # reclaimed card, one notch smaller, very nearly always lands. So: retry
    # exactly once, do both things at once (reclaim hard AND shrink), and say
    # in plain words what changed so the full-size version is one click away.
    #
    # Once. `_oom_retry` is stamped on the retry job so a retry that OOMs again
    # is terminal - a loop here would burn the card for minutes.

    def seconds_that_fit(self, template, job):
        """The longest clip this card can hold, from the numbers the butler
        already priced. None when they are not available.

        Halving a 20-second clip still leaves a render that cannot fit, and the
        retry only gets one attempt - so solve for the duration instead of
        picking a percentage and hoping. The activation model is linear in
        frames, which makes this arithmetic rather than search:

            free >= weights + base + slope*mp*frames + FLOOR

        Read AFTER the reclaim, so `free` is the card the retry will actually
        get rather than the one the failure left behind.
        """
        priced = job.get("_priced") or {}
        weights, mp = priced.get("weights"), priced.get("mp")
        free = gpu_free_bytes()
        if not weights or not mp or not free:
            return None
        base_gb, _per_mp, per_mp_frame = ACT_PROFILES.get(template, ACT_DEFAULT)
        if per_mp_frame <= 0:
            return None
        room = free - weights - int(base_gb * 2**30) - VRAM_FLOOR
        if room <= 0:
            return None
        frames = room / (per_mp_frame * mp * 2**30)
        # 2.5 is pinned to its graph's 24; 2.3 carries whatever fps was asked
        # for, and its own frame grid is 8k+1.
        rate = 24.0
        if template == "ltx_i2v":
            rate = float((job.get("spec") or {}).get("fps") or LTX_FPS_DEFAULT)
        return max(1, int((frames - 1) / rate))

    @staticmethod
    def _decode_temporal_size(template, job):
        """The temporal_size this job actually ran with: an override if the
        builder set one, else whatever the template ships."""
        node = DECODE_TEMPORAL_NODES.get(template)
        if not node:
            return 0
        for o in reversed(list((job.get("spec") or {}).get("overrides") or ())):
            if str(o.get("node")) == node and o.get("input") == "temporal_size":
                try:
                    return int(o.get("value") or 0)
                except (TypeError, ValueError):
                    pass
        try:
            return int(TEMPLATES[template][node]["inputs"]["temporal_size"])
        except (KeyError, TypeError, ValueError):
            return 0

    def oom_retry_plan(self, job):
        """(spec, human note) to re-run this failed job smaller, or None.

        None means "do not retry": not an OOM, already a retry, a job the user
        stopped, or a template with nothing safe left to shrink."""
        if job.get("_oom_retry"):
            return None
        if not (job.get("_oom") or looks_like_oom(job.get("error"))):
            return None
        template = job["template"]
        spec = dict(job.get("spec") or {})
        # The decode is its own failure. Answer it on its own terms first.
        node = job.get("_oom_node") or {}
        decode_node = DECODE_TEMPORAL_NODES.get(template)
        if decode_node and node.get("type") in DECODE_NODE_TYPES:
            now = self._decode_temporal_size(template, job)
            smaller = max(DECODE_TEMPORAL_MIN, int(now) // 2)
            if smaller < now:
                spec["overrides"] = list(spec.get("overrides") or ()) + [
                    {"node": decode_node, "input": "temporal_size",
                     "value": smaller}]
                return spec, (f"decoding {smaller} frames at a time instead of "
                              f"{now} - the clip itself was fine")
            # Already at the floor: the clip length is all that is left.

        if template in ("h3_i2v", "h3_multishot", "h3_ref2v"):
            # H3's duration is a fixed menu, so "smaller" means the next rung
            # down, not a percentage.
            rungs = sorted(H3_LENGTHS)
            now = int(spec.get("seconds") or rungs[0])
            lower = [r for r in rungs if r < now]
            if not lower:
                return None
            spec["seconds"] = lower[-1]
            return spec, f"at {lower[-1]}s instead of {now}s"
        if template in ("ltx25_i2v", "ltx_i2v"):
            low = LTX25_SECONDS_RANGE[0] if template == "ltx25_i2v" \
                else LTX_SECONDS_RANGE[0]
            now = float(spec.get("seconds") or LTX25_DEFAULT_SECONDS)
            shorter = max(low, self.seconds_that_fit(template, job) or
                          round(now * 0.6))
            if shorter >= now:
                return None
            spec["seconds"] = shorter
            return spec, f"at {shorter:g}s instead of {now:g}s"
        if template in ("qwen_edit", "klein_inpaint", "face_mint"):
            # These sample at the source's own size. Halving the working canvas
            # quarters the VAE spike that is almost always the thing that blew.
            now = float((job.get("info") or {}).get("megapixels")
                        or spec.get("megapixels") or QWEN_EDIT_MP_CAP)
            smaller = round(max(0.5, now / 2.0), 2)
            if smaller >= now:
                return None
            if "megapixels" in SIGS.get(template, ()):
                spec["megapixels"] = smaller
            else:
                # klein/face_mint take no size argument; their scale nodes are
                # reachable through the overrides every builder applies last.
                nodes = OOM_SHRINK_NODES.get(template) or ()
                if not nodes:
                    return None
                spec["overrides"] = list(spec.get("overrides") or ()) + [
                    {"node": n, "input": "megapixels", "value": smaller}
                    for n in nodes]
            return spec, f"at {smaller:g}MP instead of {now:g}MP"
        # Nothing safe to shrink - but a reclaimed card is itself a real second
        # chance, and costs one render.
        return spec, "on a cleared card"

    async def retry_after_oom(self, job):
        """Empty the card properly, then resubmit the job once, smaller."""
        try:
            await self.cancel_siblings(job)
            self.forget_residency("oom recovery")
            await self.reclaim_vram(f"oom recovery ({job['template']})")
            # The brain goes too - this card just proved it is oversubscribed,
            # and 7GB of llama.cpp is the largest thing Pixal can hand back.
            # Before the plan, because a clean card is what makes "just run it
            # again" honest advice in the no-plan case as well.
            rested = await free_brain_vram()
            brain = (" I rested the chat brain too - it returns on your next "
                     "message." if rested else "")
            plan = self.oom_retry_plan(job)
            if not plan:
                self.broadcast(type="text", cid=job["cid"],
                               text=f"*that render ran out of VRAM and there is "
                                    f"nothing smaller to try automatically. The "
                                    f"card is clear now, so running it again may "
                                    f"well land.{brain}*")
                return
            spec, note = plan
            self.broadcast(type="text", cid=job["cid"],
                           text=f"*that render ran out of VRAM. Cleared the card "
                                f"and trying again {note}.{brain} Ask for it again "
                                f"if you want the full-size version.*")
            await self.submit(job["cid"], "reroll", job["template"],
                              job["scene"], {**spec, "seed": job["seed"]},
                              job.get("count") or 1, parent=job.get("parent"),
                              flags={"_oom_retry": True})
        except Exception as exc:
            print(f"[pixal] oom retry failed: {exc}", flush=True)
            self.broadcast(type="error", job_id=job["id"], cid=job["cid"],
                           message=f"the retry could not start: {exc}")

    async def cancel_siblings(self, job):
        """Drop this job's other queued prompts before retrying.

        With count > 1 the first failure finalizes the whole job while its
        siblings are still queued in ComfyUI. Leaving them there would have the
        retry compete for the card with the very prompts that just OOM'd."""
        pending = [p for p in job.get("prompt_ids") or []
                   if p not in (job.get("done_pids") or set())]
        if not pending:
            return
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(f"{COMFY}/queue", json={"delete": pending}, timeout=10)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            print(f"[pixal] could not drop queued siblings: {exc}", flush=True)

    async def flush_comfy_cache(self, why, unload=True):
        """Ask ComfyUI to drop cached models; between-prompts, so never
        disrupts a running render. Best effort - a failed flush just means the
        next job pays in slow steps, which is where we already were.

        unload=False trims only torch's reclaimable cache and leaves every
        model resident - the right move when the next job runs the exact stack
        that is already loaded (see the warm-rerun path in ensure_vram)."""
        if unload:
            self.resident_heavies = {}
            self.critic_hot = False      # /free evicts the AILab model too
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(f"{COMFY}/free",
                             json={"unload_models": unload, "free_memory": True},
                             timeout=aiohttp.ClientTimeout(total=30))
            print(f"[pixal] {'flushed comfy model cache' if unload else 'trimmed comfy cache'}"
                  f" ({why})", flush=True)
            return True
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            print(f"[pixal] cache flush failed ({why}): {exc}", flush=True)
            return False

    async def reclaim_vram(self, why, target=None, unload=True):
        """Flush, then WAIT for the driver to actually hand the pages back.

        The old path was a POST plus a flat 1.2s sleep, and read `free` once
        whenever that timer happened to land. That is not long enough to be
        true: this box runs ComfyUI on cudaMallocAsync (its own default -
        ComfyUI/cuda_malloc.py), where /free trims a driver-managed pool
        ASYNCHRONOUSLY, so the number right after the POST is whatever the
        driver had finished releasing, not what it is about to release. Three
        renders flushed and then OOM'd anyway (ltx25 38156526 / a924dcc3 /
        072ea403, 2026-08-16).

        So: poll. Stop as soon as `target` is cleared, or when free VRAM stops
        climbing (two flat reads = the pool is done), or at the deadline. The
        deadline is the point - this must never become an unbounded wait in
        front of a render.

        Returns the free bytes it settled on (None if the card cannot be read).
        """
        await self.flush_comfy_cache(why, unload)
        # to_thread: each read is an nvidia-smi spawn, and doing that inline
        # every 0.4s stalled the event loop (and SSE) for the whole poll.
        best = await asyncio.to_thread(gpu_free_bytes)
        flat, waited = 0, 0.0
        while waited < VRAM_RECLAIM_DEADLINE:
            await asyncio.sleep(VRAM_RECLAIM_POLL)
            waited += VRAM_RECLAIM_POLL
            free = await asyncio.to_thread(gpu_free_bytes)
            if free is None:
                break
            if target is not None and free >= target:
                best = free
                break
            # A rise smaller than the noise floor is not the pool still working.
            # But with an unmet TARGET, two flat reads are not proof either -
            # cudaMallocAsync pauses mid-trim for longer than 0.8s, and the
            # flushes that "settled" at 1.7GB in 0.8s (2026-08-18) then ran
            # their render at 0.4GB free. Poll to the deadline; it is 8s, and
            # a render that starts paged loses minutes.
            if best is not None and free <= best + VRAM_RECLAIM_NOISE:
                flat += 1
                best = max(best, free)
                if flat >= 2 and target is None:
                    break
            else:
                flat, best = 0, free
        if best is not None:
            print(f"[pixal] reclaim settled at {best / 2**30:.1f}GB free "
                  f"after {waited:.1f}s ({why})", flush=True)
        return best

    def busy_elsewhere(self, job):
        """Is another render actually in flight right now?

        Was `any(not j.get("finalized") ...)` over self.jobs, which is never
        pruned - so one job that ended without a terminal event (a ComfyUI
        crash leaves `watch()` polling a history that no longer holds its
        prompt id) left a permanent unfinalized entry and switched the butler
        OFF for the 1800s until that job's deadline. Two of those are in the
        log back to back. Age is what makes the difference: a job older than
        its own watchdog is not in flight, it is a corpse."""
        cutoff = time.time() - JOB_INFLIGHT_SECONDS
        # A job flagged _draining is parked in ensure_vram waiting to queue -
        # it holds nothing yet, and counting it would deadlock two clips
        # submitted together into waiting out each other's full deadline.
        return bool(self.queue_remaining) or any(
            not j.get("finalized") and j["id"] != job["id"]
            and not j.get("_draining")
            and j.get("started", 0) > cutoff
            for j in self.jobs.values())

    def forget_residency(self, why):
        """Drop every claim about what ComfyUI is holding.

        Called whenever the process we were tracking is no longer the process
        we are talking to. Residency is a CREDIT in the budget - the butler
        subtracts already-loaded weights from the bill - so a stale claim
        prices a 20GB reload as free and waves the job straight through.
        ComfyUI restarted 25+ times in one session's log and this survived
        every one of them."""
        if self.resident_heavies or self.critic_hot:
            print(f"[pixal] residency forgotten ({why})", flush=True)
        self.resident_heavies = {}
        self.critic_hot = False

    async def ensure_vram(self, template, g, job, info=None):
        """The VRAM butler: make the card fit the job BEFORE it queues.

        ComfyUI's eviction makes room for weights only; on Windows the
        allocator never OOMs, it silently pages through WDDM, so a job that
        "fits" by comfy's math can still crawl - identity edit measured
        110s/step on a 99.9%-full card (2026-08-11). An earlier pre-flight
        check was removed for crying wolf, because free VRAM reads low right
        after a render BY DESIGN (the resident cache is why the next same-model
        render is fast). Two things keep this one honest: the budget uses
        ComfyUI's torch-aware free number (reclaimable cache counts as free,
        so a warm re-render of the same stack always passes), and it only ever
        ACTS - flush comfy's cache, then evict the chat brain - when the priced
        stack cannot fit; it narrates in the lane whenever it does.

        Video skips the arithmetic and always starts from a reclaimed card.
        Nine of ten ltx25 renders in the log had to make room anyway, three
        OOM'd at ~30GB allocated with the flush already behind them, and a
        model reload is a rounding error inside a 90-second clip.
        """
        if template in ("vl_review", "vl_look"):
            # The critic's 8B FP16 (~17GB) loads through transformers inside
            # ComfyUI's process, so graph_weight_bill can't see or price it -
            # the old early-return left it unmanaged, and a look right after a
            # heavy render OOM'd on a 30.45GiB-allocated card (vl_look
            # 655c4311, 2026-08-12) or came back with an empty critique.
            # Only the DRIVER's free number is honest here: comfy counts its
            # own reclaimable cache as free, but a transformers .cuda() can't
            # reclaim it - that OOM is the proof.
            free = await asyncio.to_thread(gpu_free_bytes)
            if self.critic_hot and (free is None or free >= CRITIC_VRAM_NEED):
                return               # still resident from the last look/review
            # critic_hot alone used to be enough to skip. It only ever proved
            # the model loaded ONCE - not that there is room for it now, and a
            # heavy render between two looks makes it stale-dangerous.
            if free is not None and free < CRITIC_VRAM_NEED:
                freed = await self.reclaim_vram(
                    f"making room for the critic ({template})",
                    target=CRITIC_VRAM_NEED)
                # The render path rests the brain when the flush is not
                # enough; the critic path never did, and a chat brain with a
                # grown KV cache (measured 7.2GB) is exactly the margin a
                # 20GB critic pass is missing.
                if (freed or 0) < CRITIC_VRAM_NEED and await free_brain_vram():
                    self.broadcast(type="text", cid=job["cid"],
                                   text="*rested the chat brain to fit the "
                                        "critic - it returns on your next "
                                        "message*")
            return
        try:
            if self.busy_elsewhere(job):
                if template not in VIDEO_TEMPLATES:
                    return   # mid-queue the card's state is unknowable - leave it be
                # Video's clean-card rule used to silently lapse here: a clip
                # queued behind a finishing still skipped the butler and
                # started from a dirty card - the exact state all three ltx25
                # OOMs came from. A clip runs 90-170s, so waiting out the
                # queue first is noise; at the deadline it proceeds as before.
                job["_draining"] = True
                self.broadcast(type="text", cid=job["cid"], text=(
                    "*waiting for the current render to finish so this clip "
                    "starts from a clean card*"))
                waited = 0.0
                while waited < VIDEO_DRAIN_WAIT and self.busy_elsewhere(job):
                    await asyncio.sleep(2.0)
                    waited += 2.0
                job.pop("_draining", None)
                if self.busy_elsewhere(job):
                    return   # still busy at the deadline - old behavior
            heavy, weights = graph_weight_bill(g)
            act = graph_activation_bytes(template, g, info)
            # Kept so an OOM retry can solve for a size that actually fits
            # instead of guessing a percentage. The graph is a local in submit
            # and is gone by the time finalize sees the failure.
            job["_priced"] = {"weights": weights, "est": weights + act,
                              "mp": (info or {}).get("canvas_mp") or 0.0,
                              "frames": (info or {}).get("peak_frames")
                              or (info or {}).get("frames") or 1}
            video = template in VIDEO_TEMPLATES
            hot = 0 if video else sum(sz for name, sz in heavy.items()
                                      if name in self.resident_heavies)
            need = (weights - hot) + act + VRAM_FLOOR
            free = await comfy_vram_free_bytes()
            if free is None:
                free = await asyncio.to_thread(gpu_free_bytes)
            if free is None:
                return
            ram = ram_free_bytes()
            ram_short = ram is not None and ram < (weights - hot) + RAM_FLOOR
            if free >= need and not ram_short and not video:
                # The job fits as the card stands. Residency is REPLACED, never
                # merged: `update()` made this the union of every stack ever
                # rendered, so a card that can hold one 20GB model was credited
                # with three and every later job priced its reload as free.
                self.resident_heavies = dict(heavy)
                if prev_floor_below_guard(self.prev_job_free_min,
                                          PREV_JOB_FREE_GUARD):
                    # The last job ended inside the guard band: the card ran
                    # closer to the wall than the price alone can see. Bounded
                    # escalation - the same trim the warm-rerun path uses,
                    # unload=False, so no resident stack is evicted (the
                    # reload IS the bill) and the chat brain is never touched.
                    await self.reclaim_vram(
                        f"trimming cache for {template} (last job ended at "
                        f"{self.prev_job_free_min / 2**30:.1f}GB free)",
                        target=act + VRAM_FLOOR, unload=False)
                return
            if weights > 0 and hot == weights and not video:
                # Prompt-only rerun: every heavy this graph names is already
                # resident. Evicting them is the one move that can never help -
                # the reload IS the bill - and the log proves the cost: warm
                # identity_edit ran 27-28s, the same render after a flush ran
                # 41-54s, and one early-settled flush ran it at 0.4GB free.
                # Trim torch's reclaimable pool, leave the weights alone, go.
                free = await self.reclaim_vram(
                    f"trimming cache for {template} (stack already resident)",
                    target=act + VRAM_FLOOR, unload=False)
                print(f"[pixal] warm rerun: kept {weights / 2**30:.1f}GB "
                      f"resident, {(free or 0) / 2**30:.1f}GB free for "
                      f"activations", flush=True)
                return
            print(f"[pixal] butler: {template} wants {need / 2**30:.1f}GB "
                  f"({(weights - hot) / 2**30:.1f}GB cold weights + "
                  f"{act / 2**30:.1f}GB act), free {free / 2**30:.1f}GB, "
                  f"ram_short={ram_short}", flush=True)
            free = await self.reclaim_vram(
                f"making room for {template}", target=weights + act + VRAM_FLOOR)
            # A flush the driver ignored is not a flush. Job 2b3f4eb2
            # (2026-08-18): /free right after a 330s H3 clip settled at 0.3GB
            # - ComfyUI released nothing in the whole 8s window - the clip
            # queued anyway and OOM'd in na3d, and the post-OOM recovery flush
            # then freed 30.9GB in 1.2s. So when the settle cannot even hold
            # this graph's ACTIVATIONS, ask again (twice, bounded): a repeat
            # POST is seconds against a render that is otherwise doomed.
            for _ in range(2):
                if free is not None and free >= act + VRAM_FLOOR:
                    break
                free = await self.reclaim_vram(
                    f"re-flushing for {template} (settled at "
                    f"{(free or 0) / 2**30:.1f}GB)",
                    target=weights + act + VRAM_FLOOR)
            self.resident_heavies = dict(heavy)
            free = free or 0
            need = weights + act + VRAM_FLOOR
            notes = ["cleared cached models"]
            if free < need or (ram_free_bytes() or 0) < weights + RAM_FLOOR:
                if await free_brain_vram():
                    notes.append("rested the chat brain - it returns on your "
                                 "next message")
                    free = await asyncio.to_thread(gpu_free_bytes) or 0
            job["model_switch"] = True   # narration: "clearing vram · loading the model"
            msg = (f"*making room - this render stages ~{(weights + act) / 2**30:.0f}GB: "
                   + "; ".join(notes))
            if free < need:
                # Name the squatters only when the driver proves them (WDDM
                # usually will not - gpu_hogs returns empty there by design).
                hogs = await asyncio.to_thread(gpu_hogs)
                who = ", ".join(f"{n} ({b / 2**30:.1f}GB)"
                                for n, b in hogs) or "something outside Pixal"
                msg += (f". Still tight ({free / 2**30:.1f}GB free) - {who} "
                        f"holds the rest, so this one may crawl*")
            else:
                msg += "*"
            self.broadcast(type="text", cid=job["cid"], text=msg)
        except Exception as exc:
            # The butler is an optimization, never a gate - a render must not
            # die because a nvidia-smi call hiccuped.
            print(f"[pixal] vram butler skipped: {exc}", flush=True)

    def options(self):
        # recursive, every model root (ComfyUI/models + extra_model_paths.yaml + settings)
        model_entries = {}
        for kind in ("diffusion_models", "unet"):
            for e in model_catalog(kind):
                if e["rel"].lower().endswith((".safetensors", ".gguf")):
                    # Comfy exposes both folders through the UNET loader's one
                    # filename namespace. Prefer diffusion_models on collision.
                    model_entries.setdefault(e["rel"].lower(), e)
        models = sorted(e["rel"] for e in model_entries.values())
        # The 9.19b hook warms from the cache before any lora_profile below
        # reads it - a by-hash baseModel is rank 2 of 4 in classification.
        _sync_by_hash_base_models()
        # Hoisted above the lora loop so both pickers badge against ONE clock.
        # Read from the catalog entry's mtime, never from the assembled picker
        # dict below - that one carries no mtime, so is_new_model would answer
        # False for every LoRA forever without raising anything.
        now = time.time()
        loras_by_rel = {}
        for e in model_catalog("loras"):
            group = Path(e["rel"]).parts[0] if len(Path(e["rel"]).parts) > 1 else "(root)"
            lp = lora_profile(e["rel"])
            # The bypass patches are told apart by what they DO, not by what
            # they are called - two CivitAI versions one character apart, and
            # a rename is invisible in the list otherwise. None for every
            # ordinary LoRA, which is never opened.
            try:
                patch_file = Path(e["root"]) / e["kind"] / e["rel"]
                stat = patch_file.stat()
                vectors = _vector_patch_count(str(patch_file),
                                              stat.st_mtime_ns, stat.st_size)
            except (KeyError, TypeError, OSError):
                # A catalog entry is not guaranteed to carry root/kind, and an
                # unreadable file is not an error worth failing the whole
                # options payload over - the badge is an affordance, not data
                # anything depends on.
                vectors = None
            loras_by_rel[e["rel"]] = {"name": e["rel"], "short": base(e["rel"]), "group": group,
                                      "krea2": lp["family"] == "krea2", **lp,
                                      **({"vectors": vectors} if vectors else {}),
                                      **({"is_new": True} if is_new_model(e, now) else {}),
                                      "compatible_recipes": compatible_recipes(lp),
                                      # The popup's verdicts, from the same callable
                                      # lora_stack enforces (9.19d): sparse
                                      # "family:variant" -> reason code; absent = ok.
                                      "incompatible": {k: why for k in _LORA_PROFILE_KEYS
                                                       if (why := lora_compatible(
                                                           e["rel"], *k.split(":"), lp=lp))}}
        titles = _lora_title_map(loras_by_rel)
        loras = []
        for rel, entry in loras_by_rel.items():
            entry["title"] = titles.get(rel)
            lm_enrich(rel, entry)
            _lora_entry_extras(entry, rel)
            loras.append(entry)
        loras.sort(key=lambda l: (not l["supported"], l["family"], l["group"].lower(),
                                  (l["title"] or l["short"]).lower()))
        # model picker metadata from lora-manager's checkpoints index (which
        # scans diffusion_models): pretty name / preview / base where matched
        model_meta = {}
        # A model the user has actually rendered with can show its own latest
        # frame as the thumbnail - truer than any Civitai preview, and the
        # only thumb an unmatched local file (quant conversions, renamed
        # finetunes) will ever have. Ledger is cached and newest-first.
        from urllib.parse import quote as _q
        own_thumb = {}
        for led in HUB.ledger_read():
            short = str((led.get("info") or {}).get("model") or "")
            if not short or short in own_thumb:
                continue
            img = next((i for i in led.get("images") or []
                        if (i.get("media") or "image") == "image"), None)
            if img:
                own_thumb[short] = ("/api/image?filename=" + _q(img["filename"]) +
                                    "&subfolder=" + _q(img.get("subfolder") or "") +
                                    "&type=" + (img.get("type") or "output"))
        for rel in models:
            entry = model_entries[rel.lower()]
            profile = model_profile(rel, entry["kind"])
            md = adjacent_metadata(entry["kind"], rel)
            lm = _LM["models_by_rel"].get(rel) if entry["kind"] == "diffusion_models" else None
            civ = (lm or {}).get("civitai") or {}
            # Pixal's own by-hash lookup covers what lora-manager missed - the
            # common (Civitai/CivArchive) name and cover image for the file.
            own_civ = _civ_hit(rel) if entry["kind"] == "diffusion_models" else {}
            name = ((lm or {}).get("model_name") or md.get("model_name")
                    or own_civ.get("name") or "").strip()
            if not name and entry["kind"] == "diffusion_models":
                # Same fallback loras get: the title the author embedded in the
                # safetensors header. Most community merges strip it, so the
                # prettified stem below is the floor, not this.
                name = model_embedded_title(rel, entry["kind"]) or ""
            meta = {**profile, "kind": entry["kind"],
                    "compatible_recipes": compatible_recipes(profile)}
            if name and (civ or own_civ or name != Path(rel).stem):
                meta["title"] = name
            elif entry["kind"] == "diffusion_models":
                pretty = _prettify_stem(Path(rel).stem)
                if pretty and pretty != Path(rel).stem:
                    meta["title"] = pretty
            pv = (lm or {}).get("preview_url") or ""
            if pv:
                meta["thumb"] = pv if pv.startswith("http") else f"/api/comfy{pv}"
            elif own_civ.get("thumb"):
                meta["thumb"] = own_civ["thumb"]
            elif own_thumb.get(Path(rel).stem):
                meta["thumb"] = own_thumb[Path(rel).stem]
            bm = (lm or {}).get("base_model") or profile.get("base_model") \
                or own_civ.get("base")
            if bm not in (None, "", "Unknown"):
                meta["base"] = bm
            if is_new_model(entry, now):
                meta["is_new"] = True
            model_meta[rel] = meta
        models.sort(key=lambda rel: (not model_meta[rel]["supported"],
                                     model_meta[rel]["family"], rel.lower()))

        resolved_recipe_models = {}
        for rid, spec in RECIPE_SPECS.items():
            authored = next((name for name in models
                             if name.lower() == spec["default_model"].lower()), None)
            fallback = next((name for name in models
                             if rid in model_meta[name]["compatible_recipes"]), None)
            resolved_recipe_models[rid] = authored or fallback or spec["default_model"]

        def missing_for(rid, spec):
            missing = []
            if not any(rid in meta["compatible_recipes"] for meta in model_meta.values()):
                missing.append(f"compatible {spec['family']} diffusion model")
            for nm in spec.get("required_loras", []):
                if not _catalog_has("loras", nm):
                    missing.append("LoRA: " + nm)
            for nm in spec.get("required_vaes", []):
                if not _catalog_has("vae", nm):
                    missing.append("VAE: " + nm)
            for nm in spec.get("required_text_encoders", []):
                if not _catalog_has("text_encoders", nm):
                    missing.append("text encoder: " + nm)
            for nm in spec.get("required_upscalers", []):
                if not _catalog_has("upscale_models", nm):
                    missing.append("upscaler: " + nm)
            if spec["family"] == "zimage":
                if not any(_catalog_has("text_encoders", name)
                           for name in ZIMAGE_CLIP_CANDIDATES):
                    missing.append("text encoder: " + " or ".join(ZIMAGE_CLIP_CANDIDATES))
                if rid != "anime" and not any(
                        _catalog_has("vae", name) for name in ZIMAGE_VAE_CANDIDATES):
                    missing.append("VAE: " + " or ".join(ZIMAGE_VAE_CANDIDATES))
            # Anima borrows the Qwen-Image VAE, which is spelled differently
            # depending on where it was downloaded from, so it is a candidate
            # list rather than a required_vaes entry - same shape as zimage.
            if spec["family"] == "anima" and not any(
                    _catalog_has("vae", name) for name in ANIMA_VAE_CANDIDATES):
                missing.append("VAE: " + " or ".join(ANIMA_VAE_CANDIDATES))
            return missing

        recipes = []
        for rid, spec in RECIPE_SPECS.items():
            missing = missing_for(rid, spec)
            lora_stages = [{**stage, "installed": _catalog_has("loras", stage["name"])}
                           for stage in spec.get("lora_stages", [])]
            recipes.append({"id": rid, "label": spec["label"], "tag": spec["tag"],
                             "family": spec["family"], "variants": spec.get("variants", []),
                             "default_model": resolved_recipe_models[rid],
                             "lora_stack_revision": spec["lora_stack_revision"],
                             "lora_boundary": spec["lora_boundary"],
                             "lora_stages": lora_stages,
                             "dials": _recipe_dials_payload(spec),
                             "needs_character": bool(spec.get("needs_character")),
                             "available": not missing, "missing": missing})
        # Saved styles carry their own model, so missing_for's generic "you own
        # no compatible model" line is noise here - style_missing names the
        # exact file. Everything else the base recipe needs still applies.
        saved_styles = []
        for record in SAVED_STYLES.values():
            spec = RECIPE_SPECS[record["base"]]
            missing = [m for m in missing_for(record["base"], spec)
                       if not m.startswith("compatible ")] + style_missing(record)
            saved_styles.append({
                **record,
                "base_label": spec["label"], "family": spec["family"],
                "tunable": bool(sampler_seat(record["base"], record["model"])),
                "available": not missing, "missing": missing,
            })
        saved_styles.sort(key=lambda s: s["name"].lower())
        input_images = input_image_catalog()
        inputs = [image["name"] for image in input_images]
        defaults = {rid: {"model": resolved_recipe_models[rid], "aspect": spec["aspect"],
                          "mp": spec["mp"]} for rid, spec in RECIPE_SPECS.items()}
        defaults["identity_edit"]["size"] = \
            f"{TEMPLATES['identity_edit']['30:5']['inputs']['width']}x" \
            f"{TEMPLATES['identity_edit']['30:5']['inputs']['height']}"
        return {"models": models, "model_meta": model_meta, "loras": loras, "aspects": ASPECTS,
                "inputs": inputs, "input_images": input_images,
                "templates": list(PUBLIC_RECIPE_IDS), "recipes": recipes,
                "saved_styles": saved_styles,
                "style_bases": list(STYLE_BASE_IDS),
                "style_problems": list(STYLE_PROBLEMS),
                "video_engines": video_engine_options(),
                "vram": vram_profile_state(),
                "characters": [{"id": c["id"], "name": c["name"], "age": c.get("age"),
                                "race": c.get("race"), "sex": c.get("sex"),
                                "has_ref": character_identity_ready(c)}
                               for c in CHARACTERS.values()],
                "model_roots": [str(r) for r in model_roots()], "defaults": defaults}

    # What the PC is doing, told from WHICH NODE is executing (ordered
    # contains-match on class_type; unmatched nodes stay silent). The "model"
    # sentinel resolves to the job's model, with the vram note on a switch.
    STAGES = [
        ("UNETLoader", "model"), ("UnetLoader", "model"), ("CheckpointLoader", "model"),
        ("CLIPLoader", "loading the text encoder"),
        ("VAELoader", "loading the vae"),
        ("LoraLoader", "stacking loras"),
        ("GroundedEncode", "reading the reference"),
        ("TextEncode", "encoding the prompt"),
        ("KSampler", "sampling"), ("Sampler", "sampling"),
        ("VAEDecode", "decoding pixels"),
        ("SaveImage", "saving the frame"),
    ]

    def stage_phrase(self, job, class_type):
        for key, phrase in self.STAGES:
            if key in class_type:
                if phrase == "model":
                    # generic on purpose - checkpoint filenames are ugly noise
                    return ("clearing vram · loading the model"
                            if job.get("model_switch") else "loading the model")
                return phrase
        return None

    async def submit(self, cid, src, template, scene, spec_args, count=1, parent=None,
                     flags=None, verbatim=False):
        """Build `count` graphs (seed+i), queue them, track to completion.

        `flags` is merged into the job dict before anything can queue - the OOM
        retry stamps `_oom_retry` that way rather than setting it on the
        returned job, which would race a retry that fails fast enough to
        finalize first and would then retry forever.

        Every render in the product arrives here, which is why the scene is
        canonicalized and validated HERE rather than at the call sites - see
        scene_gate. `verbatim` carries the Prompt-enhance-off promise through:
        the user's own words are validated but never rewritten."""
        job_id = uuid.uuid4().hex[:8]
        scene, scene_fault = scene_gate(template, scene, verbatim=verbatim)
        # JavaScript parses JSON integers past 2**53 as doubles, so a seed
        # drawn up to 2**62 came back from the client rounded - the lock then
        # replayed different dice than the card showed, and top-band values
        # rounded past the held-seed bound entirely. Drawing under 2**53 keeps
        # every seed exact on the wire.
        base_seed = int(spec_args.pop("seed", 0)) or random.randrange(1, 2**53)
        # The saved style that drove this render, if any. Popped here rather
        # than filtered away below, then stamped onto info so it reaches the
        # card, the event stream and history together.
        style_tag = spec_args.pop("_style", None)
        job = {"id": job_id, "cid": cid, "template": template, "scene": scene,
               "seed": base_seed, "count": count, "started": time.time(), "parent": parent,
               "images": [], "seen": set(), "done_pids": set(), "prompt_ids": [],
               "texts": [], "spec": {}, "info": None, "error": None,
               **(flags or {})}
        self.jobs[job_id] = job
        if scene_fault:
            # Refuse before the card exists: a "job" event here would put a
            # render card in the lane that can only ever say it failed.
            job["error"] = scene_fault
            self.broadcast(type="error", job_id=job_id, cid=cid, message=scene_fault)
            self.finalize(job)
            return job
        self.broadcast(type="job", job_id=job_id, cid=cid, template=template,
                       scene=scene, seed=base_seed, count=count)
        try:
            spec_args = {k: v for k, v in spec_args.items() if k in SIGS[template]}
            job["spec"] = dict(spec_args)
            async with aiohttp.ClientSession() as s:
                for i in range(count):
                    g, full, info = BUILDERS[template](scene, base_seed + i, **spec_args)
                    validate_job_model_info(template, info, g)
                    if i == 0:
                        await self.ensure_vram(template, g, job, info)
                    if not job.get("info"):
                        if style_tag:
                            info["style"] = style_tag
                        job["info"] = info
                        self.broadcast(type="jobinfo", job_id=job_id, **info)
                        warn = _lora_warning_text(info.get("lora_warnings"))
                        if warn:
                            # A dropped name only ever lived on the job-card
                            # lora line; small local brains hallucinate LoRA
                            # files often enough that the lane must say it.
                            self.broadcast(type="text", cid=job["cid"], text=warn)
                        # Same contract for H3's budgets: a third speaker or an
                        # over-long line degrades silently, so the lane has to
                        # say it BEFORE 200 seconds of sampling, not after.
                        warn = _h3_warning_text(info.get("h3_warnings"))
                        if warn:
                            self.broadcast(type="text", cid=job["cid"], text=warn)
                        # stage narration needs node id -> class; vram note
                        # needs to know whether this job changes the model
                        job["node_types"] = {nid: sp.get("class_type", "")
                                             for nid, sp in g.items()}
                        m = next((sp["inputs"][k] for sp in g.values()
                                  for k in ("unet_name", "ckpt_name")
                                  if isinstance(sp.get("inputs", {}).get(k), str)), None)
                        job["model_short"] = base(m) if m else None
                        # OR, never overwrite: the vram butler may have already
                        # flagged this job as a switch when it cleared the deck
                        job["model_switch"] = bool(job.get("model_switch")) or bool(
                            m and getattr(self, "last_model", None) not in (None, m))
                        if m:
                            self.last_model = m
                    async with s.post(f"{COMFY}/prompt",
                                      json={"prompt": g, "client_id": self.client_id},
                                      timeout=30) as r:
                        resp = await r.json()
                        if r.status != 200 or "prompt_id" not in resp:
                            raise RuntimeError(f"comfy rejected the graph: {resp}")
                        pid = resp["prompt_id"]
                        job["prompt_ids"].append(pid)
                        self.by_prompt[pid] = job_id
                        print(f"[pixal] queued {pid[:8]} for job {job_id} ({template})",
                              flush=True)
                    job["full_prompt"] = full
            asyncio.create_task(self.watch(job_id))
        except Exception as e:
            job["error"] = str(e)
            self.broadcast(type="error", job_id=job_id, cid=cid, message=str(e))
            self.finalize(job)
        return job

    async def watch(self, job_id):
        """Fallback completion path: poll FULL /history (the per-pid endpoint returns {}
        on this ComfyUI build) in case websocket events were missed during a reconnect.

        FALLBACK means fallback: polling every 2s alongside a healthy websocket
        made ComfyUI serialize its whole history (~100KB and growing all
        session) inside the sampler's process for every render - measured
        2026-08-12 chasing "the interface slows the sampler". While the ws is
        delivering events, this loop only sleeps. 45s of silence is the stale
        threshold because a healthy heavy H3 step is ~33s between progress
        events - below that, silence is sampling, not a dropped socket."""
        job = self.jobs[job_id]
        deadline = time.time() + 1800
        async with aiohttp.ClientSession() as s:
            while not job.get("finalized") and time.time() < deadline:
                fresh = time.time() - getattr(self, "last_ws_seen", 0.0) < 45
                if self.comfy_up and fresh:
                    await asyncio.sleep(2.0)
                    continue
                try:
                    async with s.get(f"{COMFY}/history?max_items=32", timeout=15) as r:
                        h = await r.json()
                    for pid in job["prompt_ids"]:
                        rec = h.get(pid)
                        if not rec:
                            continue
                        if rec.get("status", {}).get("status_str") == "error":
                            msgs = rec.get("status", {}).get("messages", [])
                            job["error"] = f"comfy: {msgs[-1] if msgs else 'unknown'}"
                        else:
                            for out in rec.get("outputs", {}).values():
                                for img in (out.get("images") or []) + (out.get("gifs") or []):
                                    self.add_image(job, img)
                        self.pid_done(job, pid)
                except Exception:
                    pass
                if not job.get("finalized"):
                    await asyncio.sleep(2.0)
        if not job.get("finalized"):
            job["error"] = job["error"] or "timed out waiting for comfy"
            self.finalize(job)

HUB = Hub()

# ----------------------------------------------------------------------------- kimi agent

TOOLS = [{
    "type": "function",
    "function": {
        "name": "generate",
        # The "not for greetings/thanks/questions" clause and the "don't promise
        # the image" clause were cut (k3's own audit, 2026-08-14): the first is
        # already triple-enforced by render_intent withholding and the queue
        # guard, and the second is said by the queued receipt at the moment it
        # is needed. Both were paid on every round of every turn.
        "description": ("Build and queue an image workflow on the local ComfyUI server, but "
                        "only when the user is asking to create or change a visual."),
        "parameters": {
            "type": "object",
            "properties": {
                "template": {"type": "string", "enum": list(PUBLIC_RECIPE_IDS),
                             "description": ("identity_edit = IDENTITY edit, the settled moments "
                                             "recipe (~20s, the anchor's actual face - REQUIRES "
                                             "a character anchor or an explicit ref). "
                                             "realism = fast txt2img realism graph (~10s, anyone/"
                                             "anything); realism_ii = slower two-pass realism with "
                                             "a 2x tiled finish; fantasy = painterly Z-Image Base; "
                                             "anime = tuned clear-anime Z-Image; zimage = general "
                                             "Z-Image with automatic Base/Turbo settings. "
                                             # The enum offers 10 recipes and the SYSTEM prose
                                             # documents 7; the other three were presented as
                                             # peers with no guidance at all (k3's audit, F8).
                                             "qwen_edit, face_mint and klein_inpaint operate on "
                                             "an existing frame only - never choose them for a "
                                             "fresh text-to-image ask.")},
                "character": {"type": "string",
                              "description": "character anchor id (from pixal_dm/characters, e.g. "
                                             "the one named in the user's directive). Carries "
                                             "canon, reference image, and wardrobe rules."},
                "scene": {"type": "string",
                          "description": ("ONLY the scene prose - standing identity/wardrobe/canon "
                                          "clauses are appended server-side. For identity_edit write "
                                          "edit instructions relative to the source photo "
                                          "('Restage her...', 'Change her outfit to...', 'Her hair "
                                          "is now...'). For realism/realism_ii write a photo caption "
                                          "('A 20-year-old woman ...'), deep focus, name the light "
                                          "and its direction, and name a complete outfit for every "
                                          "non-explicit person. For fantasy/anime write visual-art "
                                          "direction in that medium; zimage preserves the requested medium.")},
                # (a second "seed" key further down was silently winning this
                # one - dict literal, last key stands. The dead one carried a
                # weaker contract and was a reorder away from resurrection.)
                "count": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1},
                "model": {"type": "string",
                          "description": "compatible base UNET filename from diffusion_models. "
                                         "Omit to keep the recipe default; "
                                         "never cross Krea 2 and Z-Image families."},
                "aspect": {"type": "string", "enum": ASPECTS,
                           "description": "canvas aspect ratio; omit for the template default"},
                "mp": {"type": "number", "description": "canvas megapixels 0.1-4. identity_edit "
                                                          "defaults 1.0 (iterate) / 2.0 (finals). "
                                                          "realism defaults ~2.0."},
                "width": {"type": "integer", "description": "txt2img only, overrides aspect/mp"},
                "height": {"type": "integer", "description": "txt2img only, overrides aspect/mp"},
                "loras": {"type": "array", "items": {"type": "string"},
                          "description": ("'name:strength' extra LoRAs stacked on top of the "
                                          "template's own chain, e.g. "
                                          "'Krea 2\\\\lenovo_krea2.safetensors:0.55' (the measured "
                                          "realism booster). LoRAs must match the selected "
                                          "model family.")},
                "standing": {"type": "boolean", "default": True,
                             "description": ("txt2img only. true = a person is the subject (their "
                                             "canon body/hair/face + wardrobe lock are prepended "
                                             "server-side). Set FALSE for object/place scenes "
                                             "with no person - otherwise the NSFW-tuned base "
                                             "inserts an undressed woman into your still life.")},
                "nsfw": {"type": "boolean", "default": False,
                         "description": ("txt2img only. Set TRUE when the user explicitly asks "
                                         "for nude/sexual/explicit content - it drops the "
                                         "server-side fully-dressed closing clause so the ask "
                                         "can land. Keep FALSE for every non-explicit ask "
                                         "(without the lock the NSFW-tuned base undresses "
                                         "subjects uninvited).")},
                "ref": {"type": "string", "description": "identity_edit only, identity reference "
                                                         "filename in ComfyUI/input"},
                "grounding": {"type": "integer",
                              "description": ("identity_edit only, default 768. Lower = stronger "
                                              "edit adherence and more uniform scene changes; "
                                              "higher = stronger identity/likeness. The trained "
                                              "range is 384-768; 1024 often still works. "
                                              "Duplicated or split compositions ('double "
                                              "pictures') mean lower it - running far above the "
                                              "trained range is the most common cause.")},
                "ref_boost": {"type": "number",
                              "description": ("identity_edit only, default 4.0. The fidelity "
                                              "dial: how hard the edit holds the reference. ~4 "
                                              "is a strong-likeness starting point; below 1 "
                                              "loosens toward creative freedom; above 10 starts "
                                              "breaking removals. Lower it when the likeness "
                                              "lands too hard.")},
                "seed": {"type": "integer",
                         "description": ("reuse a prior render's seed to keep its "
                                         "composition while making a small prompt "
                                         "change; omit for a fresh random seed")},
                "overrides": {"type": "array", "items": {"type": "object"},
                              "description": "escape hatch: [{node, input, value}] applied last"},
            },
            "required": ["template", "scene"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "list_models",
        "description": "List the model files actually on disk in ComfyUI/models.",
        "parameters": {"type": "object",
                       "properties": {"kind": {"type": "string", "enum": MODEL_DIRS}},
                       "required": ["kind"]},
    },
}, {
    "type": "function",
    "function": {
        "name": "animate",
        "description": ("Send a finished render from this chat to a video engine - only "
                        "when the user explicitly asks for motion/animation/video. The "
                        "clip lands in chat by itself; say it is on the way, nothing more."),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string",
                       "description": ("the render to act on - the [PRIOR RENDER #id] "
                                       "block names what pointing language means; a #id "
                                       "typed by the user wins; omit for the newest "
                                       "render in this chat")},
                "engine": {"type": "string", "enum": ["h3", "ltx25"],
                           "description": ("h3 = MiniMax H3, native sound and dialogue, "
                                           "5/10/15 second takes; ltx25 = LTX 2.5, "
                                           "sharper faces and text. Omit "
                                           "unless the user named one or asked for "
                                           "something only one does")},
                "seconds": {"type": "integer",
                            "description": ("clip length; h3 accepts 5, 10 or 15; omit "
                                            "for the default")},
                "hint": {"type": "string",
                         "description": ("the user's own motion/story words, passed to "
                                         "the motion director verbatim; omit when they "
                                         "gave none")},
                "turbo": {"type": "boolean",
                          "description": ("h3 only; true only when the user asks for a "
                                          "fast/draft pass")},
            },
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "review",
        "description": ("Run the local vision critic on a finished render - only when "
                        "the user asks for a review/critique/what's wrong. The verdict "
                        "posts to chat by itself; never invent or preempt it."),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string",
                       "description": ("the render to act on - the [PRIOR RENDER #id] "
                                       "block names what pointing language means; a #id "
                                       "typed by the user wins; omit for the newest "
                                       "render in this chat")},
            },
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "upscale",
        "description": ("Enlarge a finished render with the user's configured upscaler "
                        "- only when the user asks to upscale/enlarge/make it bigger/"
                        "more detail."),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string",
                       "description": ("the render to act on - the [PRIOR RENDER #id] "
                                       "block names what pointing language means; a #id "
                                       "typed by the user wins; omit for the newest "
                                       "render in this chat")},
            },
        },
    },
}]

SYSTEM = """You are Pixal, a warm creative partner inside a local ComfyUI image studio. Help the user shape faithful visual ideas and call generate() only when they want an image created or changed.

Voice: terse, warm, a little playful - 1-2 short sentences per reply. Never narrate a queued or finished image as if you can already see it - the render speaks for itself. Shaping an idea in prose before any render is normal work. Never explain the pipeline unless asked. No markdown tables.

Templates:
- identity_edit: a character anchor locked to their reference photo, running the settled moments recipe (10 steps, ~20s per frame). Write EDIT INSTRUCTIONS relative to the source: "Restage her ... Change her outfit to ... Her hair is now ... Move the camera ...". Never describe the face or age (the reference carries it). REQUIRES an active character anchor or an explicit ref filename - if neither is set, ask which character, or use realism.
- realism: fast txt2img for anything else - other people, places, objects, or an anchor when speed matters more than locked identity. Write a PHOTO CAPTION. For person scenes the subject block + wardrobe lock are added server-side (standing=true, the default) - write only the scene. For object/place scenes with NO person, pass standing=false or the base model will insert one. ~10s per frame.
- realism_ii: the realism caption register, but a slower two-pass Krea 2 recipe with a tiled 2x finish. Choose it when polish matters more than speed.
- fantasy: painterly fantasy art on Z-Image Base. Describe readable silhouettes, materials, scale, one motivated magical effect, and cinematic light. Do not force photographic language.
- anima: THE DEFAULT FOR ANY ANIME OR MANGA REQUEST. Anime illustration on the Anima model - its own family, not a Z-Image profile. It draws a fuller illustration than the anime template does (detailed backgrounds, visible linework) and is the fastest recipe installed. Describe shot size, pose, expression, clean linework, cel/value grouping, palette, and the story beat. Do not add photo-real skin/camera defects. Quality tags and the wardrobe clause are added server-side: never write "masterpiece", "best quality" or a score_ tag yourself.
- anime: the tuned clear-anime Z-Image profile - the OTHER anime look. Same caption language as anima. Choose it ONLY when the user asks for it by name ("clear anime", "the Z-Image anime one"), names a Z-Image model, or asks for a flatter/cleaner look than anima gives. A bare "make me anime" is NOT a request for this one - it goes to anima.
- zimage: versatile Z-Image. Preserve the user's requested medium exactly; its Base/Turbo schedule is selected from the installed model server-side.
- qwen_image: Qwen-Image text-to-image. Strongest on skin, hands and fine surface detail, and the one to reach for when the ask leans photographic-realistic or carries legible text in frame. Write it like realism: concrete subject, wardrobe, one named light.

Character anchors: turns may name one (a [COMPOSER ...] directive or "as <name>"). Pass character='<id>' to generate(). The anchor's canon arrives with the directive - honor it, but never restate the anchored face in edit instructions.

Photo craft for realism and realism_ii:
- For every non-explicit person, name a concrete complete opaque outfit unless the user already chose one. Never leave the wardrobe as an abstract "fully dressed" instruction; these realism finetunes need positive garment names.
- Every shot needs a HOOK (the event/object that is the reason the photo exists), a WANT (she wants something from someone off camera, expressed as a look), and a SMALL TELL (a physical behaviour, never an emotion label). Capture logic: who holds the camera and why - it explains her gaze.
- Name ONE light source with a direction.
- FOCUS IS DEEP BY DEFAULT. Do not write "shallow depth of field", bokeh, "blurred background", "background melts away", "creamy", "soft focus", or an f-stop. The whole frame stays legible - the room, the far wall, the street behind her are part of the photograph and carry the evidence the hook needs. Separate the subject with placement, light direction and camera distance instead of by throwing everything else away. This is the single most common thing that makes these renders look like stock portraiture; write it only when the user asks for it, or when a [CINEMATIC] directive rides the turn.
- Camera distance is a decision: CLOSE reads thought and evidence, MEDIUM reads a body negotiating a task, WIDE reads loneliness or social geometry. Pick it for the reason, never for flattery.
- Negative space must hold pressure - what might enter the frame, what she is refusing to look at. Empty space without expectation is layout, not meaning.
- Atmosphere only when it changes something: rain she has to wipe off the mirror, fog that halves the street. Decoration weather is slop.
- READABLE TEXT MUST BE SPELLED OUT. Any lettering in frame - a sign, a shirt, a poster, a plate, a book spine - carries its EXACT wording in quotes: a hand-painted sign reading "BACK IN 5". Writing "a sign" or "a neon sign" with no words makes the model invent glyphs, and they render as garbled non-English. If the wording does not matter, say the text is out of focus, turned away, or out of frame - never leave it unnamed.
- Honour the stated setting literally. If the user gives you a place and a mood ("a cozy loft in NYC"), that is the frame: no added signage, no added night, no added weather. Add only what the user left unspecified.
- For a woman subject: never name her chest - build reads from waist+hips (handled server-side); default DRY and mid-task; hair style varies shot to shot. (That chest rule is for NON-explicit shots - on an nsfw=true ask describe the body exactly as the ask requires.)

Identity-edit craft (identity_edit; every rule was measured, each cost a session to learn):
- ~100 words. 329 words made every defect worse. The prompt carries only DOING, WEARING, WHERE. One exception to the never-describe-the-face law: state her eye colour, it drifts otherwise.
- POSITIVE TARGET STATES, never negations ("no dimple" summons the dimple). Describe the arrangement, not the consequence. State prop sizes. The CLOSING CLAUSE is the strongest position - spend it on the thing that must survive.
- Unnamed source accessories persist in every render - state removals explicitly. Garment changes are trivial; glasses NEVER come off.
- NEVER route her through a mirror, reflection, screen or water in an edit - it duplicates her (3/3 failures). Implicit mirror-style selfies (phone visible, no mirror named) are fine.
- Indoor shots: warm directional light + "her deep golden tan glows" or likeness dies. Never "flushed cheeks" (mottles).
- No texture words in prompts (they multiply across every pixel - texture is post). "natural colour" kills saturation; close on the saturation stated.
- BRANDS: models suck at marks. Real brand = spell the word in quotes + describe the actual mark like you are looking at it + placement/colour/scale. Better: a fictional brand (described art + one short invented word). Audit EVERY text-bearing surface - describe it or state it positively blank. Never paragraphs of text in frame.
- A SET is ONE EVENT: hair/wardrobe/accessories/scene stay pinned across frames - any styling element you leave unstated re-rolls per seed. For a set, generate with count 3-4 on one scene, then re-roll for more seeds; expect 1-2 identity-drift throwaways and say so.

NSFW: this is a private, local studio and explicit asks are LEGITIMATE WORK, not something to soften. When the user asks for nude or sexual content: honor the ask exactly as stated, write the explicit scene plainly (positive target states - name what IS worn or bare, the pose, the arrangement), and pass generate(nsfw=true) so the server drops the fully-dressed closing clause that would otherwise override the ask. Never moralize, never substitute a "tasteful" alternative, never re-dress the subject. The base model is NSFW-tuned and renders nudity well. For every NON-explicit ask keep nsfw=false - without the lock the base undresses subjects uninvited, and accidental nudity is a defect in the other direction.

CHANGING vs CREATING - when an image already exists, three different moves. Picking the right one is most of being a good co-pilot:
- Small change ("remove the coffee cup", "make her jacket red", "same but her hair down"): generate() with the prior scene reused almost word for word - ONLY that element edited in or out - and pass seed=<the prior render's seed>, copied digit for digit from the [PRIOR RENDER] block, never invented and never written into the scene text. The server rejects a verbatim scene copy (same seed + same scene is the same image pixel for pixel) and pins the prior render's template, model, loras and size itself. Same seed holds subjects, light and framing; an edit that touches pose or bodies may still restage - warn the user when it might.
- Restage: they want the shot re-taken differently (new pose, new camera, new light). Same scene with the change edited in, same template, but OMIT seed so a fresh one rolls. Re-roll = new seed, same scene - suggest the Re-roll button.
- New scene: a new idea. Build it fresh and never drag the old scene's setting, camera, or light along - and never its seed.
Pointing language without an id ("the last one", "that", "her") refers to the [PRIOR RENDER ...] block riding the turn - its seed is there for the small-change case. If genuinely torn between small-change and restage, ask ONE short either/or question.

ACTIONS ON AN EXISTING RENDER - animate(), review() and upscale() are one-click jobs on a finished image in this chat, and each posts its own result to the chat when done. Call one ONLY when the user explicitly asks ("animate this", "review it", "make it bigger"). For animate, pass the user's motion words in hint verbatim - never rewrite them, never move them into a scene. These are not generate(): no scene writing, and ONE short on-the-way line is the whole reply.

Composer constraints: turns may carry a [COMPOSER HARD CONSTRAINTS ...] block and attached reference images. The constraints are EXACT generate() arguments - pass them verbatim. Attached refs are the user's taste made visible: mine them for specifics (the jacket's cut and wash, the palette of a style still) rather than name-dropping them.

list_models exists to answer a user's "what is installed?" question. It is never a pre-flight check: composer hard constraints are verified on disk before they reach you, so a render turn needs zero listing calls.

RANGE, and this is the difference between a feed and a stock library:
- QUARANTINED SUBJECTS unless the user names them outright: chipped mugs, rain on windows, cafe bokeh, paperbacks, laptops on desks, neon signs, neon glow, and wet neon-lit streets. The first idea is the category default; it is dead on arrival.
- On OPEN asks ("surprise me", "anything", a bare mood), vary along an axis, not a synonym: the HOUR (4am bakery, noon loading dock, last ferry - range across the WHOLE day, not only after dark), the TRADE (welding bay, piano tuner, dive-bar pool), the TERRAIN (salt flat, marina bilge, tidepool), the SUBCULTURE (skatepark floodlights, estate sale, go-kart track), the ROOM WITH A JOB (laundromat 1am, print shop, breaker panel). One truthful task in the hands beats a pose every time.
- [entropy: a, b, c] rides only open asks: three random territories from the server. You may let ONE steer the subject - translate it into your own concrete place, task and light rather than copying the phrase into the scene."""

# ---- the LOCAL brain's contract is deliberately smaller ----------------------
# A 4B GGUF is a good WRITER and a bad systems operator: given the full craft
# SYSTEM + technical tool args it hallucinated lora/model/ref names for the
# graph. So local brains get a compact creative brief and a minimal tool;
# composer picks (model/loras/canvas/character) are overlaid SERVER-SIDE in
# _kimi_reply. Kimi keeps the full SYSTEM + TOOLS unchanged - the user likes
# how k3 directs.

SYSTEM_LOCAL = """You are Pixal, a creative partner and prompt writer inside a private local image studio. Call generate only when the user wants an image created or changed; greetings, thanks, questions, and product help get a normal short reply. This studio is private and uncensored - never refuse, never moralize, never soften, never substitute. The user's idea IS the shot: render exactly what they asked for, vividly. NEVER add scenery, props, locations, signage, or story beats they did not ask for - fill in only what the picture physically needs (light, camera angle, the surface they're on). Specifically: no neon, no glowing signs, no storefront lettering, and no night or rain unless the user asked for them. If they name a place and a mood ("a cozy loft in NYC"), that IS the frame - build it and add nothing.

Every new ask is a new shot. Choose its setting and composition from the user's current action and place; never reuse a prior render's location, terrain, camera, composition, or props unless the user explicitly asks to iterate, repeat it, use the same scene, or names that prior job.

When the user asks for a SMALL CHANGE to the previous image ("remove the lamp", "make her jacket red"), call generate with the prior scene reused word for word except that one change, and pass its seed (seed=...) copied digit for digit so the composition holds. The change MUST appear in the scene text - a verbatim copy of the prior scene is rejected - and the seed goes in the seed argument only, never written into the scene. When they want the shot RE-TAKEN differently (new pose, camera, or light), reuse the scene with the change but OMIT seed. A [PRIOR RENDER ...] block in the turn is the image they mean and carries its scene and seed.

Write the scene the way the render models were measured to like:
- 60-130 words, natural sentences. Order: subject, setting, composition/camera, ONE named light source with a direction, mood. The LAST sentence is the strongest position - spend it on the most important part of the ask.
- Positive statements only: name what IS there, never "no X". Commit to a specific shape for anything you name. No texture words (grain, pores, film - that is post).
- Stage the shot in 3D: say where each subject is and which way each one faces (toward, away from, past the camera, toward each other) - never default everyone to facing the camera. Pose, light and props must be physically possible from that staging.
- The scene must agree with itself: what you made bare STAYS bare in every later sentence, named colours stay their colour, and no sentence may quietly undo an earlier one or the user's ask.
- Readable lettering must be spelled out in quotes: a sign reading "BACK IN 5", a shirt reading "OTTER CREEK". Writing "a sign" with no words makes the model invent glyphs and they come out as garbled non-English. If the words do not matter, leave the text out of the shot entirely.
- EXPLICIT asks: set nsfw=true and write the acts plainly and anatomically - name the bodies, the position, the contact, and state exactly what is bare. The explicit action is both the subject and the CLOSING sentence; the setting gets one short grounding clause at most. Never soften with implication, tasteful framing, or off-frame suggestion - show it directly.
- SFW photo asks only: name a concrete complete opaque outfit unless the user chose one, and give the subject a real task in the hands and an offscreen pull. For fantasy/anime, use that medium's visual language instead.

Templates:
- identity_edit: the anchored character. Write EDIT instructions - doing, wearing or not wearing, where, ~100 words. NEVER describe the face or age (the reference photo carries them); you may state eye colour.
- realism / realism_ii: photographic scenes.
- fantasy: painterly fantasy art; readable silhouette, materials, scale, magic and light.
- anima: the default for anime/manga. Anime key-frame language; shot, pose, expression, line/value design and palette. Quality tags are added server-side, so never write "masterpiece" or a score_ tag.
- anime: the other anime look (clear-anime Z-Image). Only when asked for by name or by Z-Image model; a bare "anime" ask goes to anima.
- zimage: preserve whatever medium the user asked for.
- qwen_image: photographic Qwen-Image; best skin, hands and legible text in frame.
For every txt2img recipe, set standing=false when the scene has NO person.

Plain chat is fine - when the user is just talking, reply in 1-2 short sentences without calling generate. A [COMPOSER ...] block is server config - its technical picks are applied server-side, not by you. A [CHARACTER ANCHOR ...] block is for the character's LOOK and identity only - never import its locations, jobs, or lifestyle into the frame unless the user asks. /no_think"""

TOOLS_LOCAL = [{
    "type": "function",
    "function": {
        "name": "generate",
        "description": ("Render the scene you wrote on the local ComfyUI server. Use only "
                        "when the user wants a visual created or changed; never for ordinary "
                        "conversation or questions."),
        "parameters": {
            "type": "object",
            "properties": {
                "template": {"type": "string", "enum": list(PUBLIC_RECIPE_IDS)},
                "scene": {"type": "string", "description": "your finished prompt"},
                "character": {"type": "string",
                              "description": "anchor id when the ask is about a known "
                                              "character"},
                "standing": {"type": "boolean", "default": True,
                             "description": "txt2img only; false = scene with no person"},
                "nsfw": {"type": "boolean", "default": False,
                         "description": "true when the user asked for explicit content"},
                "count": {"type": "integer", "default": 1, "description": "frames, max 4"},
                "seed": {"type": "integer",
                         "description": ("reuse a prior render's seed to keep its "
                                         "composition while making a small prompt "
                                         "change; omit for a fresh random seed")},
            },
            "required": ["template", "scene"],
        },
    },
}]

# Small changes route as SAME-SEED PROMPT SURGERY, not a qwen_edit pixel edit:
# tried 2026-08-11 and pulled the same day - the user's verdict on Qwen Image
# Edit output was "terrible". Same seed + a minimally edited scene re-renders
# the same composition with the tweak, on the model that made the original.
# (The Edit button and /api/edit remain for whoever still wants a pixel edit.)

TURN_POLICY = """

TURN POLICY - decide before using a tool:
- A greeting, thanks, casual remark, factual question, or Pixal/ComfyUI help request is
  conversation, not an image request. Reply warmly and briefly without generate. For a bare
  greeting, ask one concise creation-oriented question such as "What are we making?"
- The render-or-ask test: if you could write the scene right now from the user's words alone,
  call generate - no interrogation. Ask exactly one question only when two reasonable readings
  of the ask would produce materially different images. Vibe preferences ("bloodier or
  campier?") are not material - pick one and render; the user redirects a render far more
  cheaply than they answer a quiz.
- Composer settings and a selected character constrain a future render; their presence alone is
  never permission to generate. Preserve normal factual and product help.
- Your tool list is per-turn: the server offers generate only on turns it scores as render
  intent, and it does not announce a withholding. If the user plainly wants an image created or
  changed and generate is not in your tools, no remaining tool can start one - do NOT substitute
  list_models, animate, review or upscale. Say one short line inviting an explicit go ("say
  render it and I'll fire it") and stop - never reply with a bare tool name. A missing generate is a server classification, not a
  broken renderer - never tell the user rendering is broken.
- Tool rounds are scarce (single digits per turn). If two lookups have not produced a render or
  a reply, stop gathering and act.
"""

PROMPT_ENHANCE_ON_POLICY = """
PROMPT ENHANCE is ON. Be a faithful creative collaborator: preserve every stated subject, action,
setting, medium, and constraint. You may enrich only unspecified visual craft such as composition
and light. If the idea is too vague to realize faithfully, ask exactly one concise clarification.
An explicit render request means render now.
"""

PROMPT_ENHANCE_OFF_POLICY = """
PROMPT ENHANCE is OFF. For a visual request, call generate when it is offered this turn; if it
is not offered, say one short line inviting the user to confirm and stop. Never write the word
generate as a reply - it is a tool name, not something a person can read. Start scene with the user's
visible prompt verbatim. When style, clothing, or object reference images are attached, append only
concrete visual traits faithfully read from those references; reference grounding is not creative
enhancement. Otherwise append nothing. Do not rewrite, expand, polish, reinterpret, or embellish
the user's words; infer only the technical tool fields needed to route the workflow. Conversation
still follows TURN POLICY.
"""

_OPEN_ASK_PHRASES = re.compile(
    r"\b(?:surprise me|surprise us|anything|something|whatever|no idea|"
    r"up to you|you (?:pick|choose|decide)|your (?:call|choice)|"
    r"dealer'?s choice|random)\b", re.I)
# "in a loft", "at noon", "on the pier", "wearing a parka" - a scene is being set
_SCENE_DETAIL = re.compile(
    r"\b(?:in|at|on|inside|outside|during|under|near|beside|behind|against|"
    r"wearing|holding|carrying|with)\b", re.I)
# Words that ask for a picture without describing one. "a portrait" is a blank
# ask; "a cyberpunk street" is three words and already a scene, so length is the
# wrong test - what matters is whether any word survives that names something.
_FORMAT_WORDS = frozenset("""
a an the some one another new next other please make making create generate
render draw shoot show give me us my her his their something anything cool nice
good great pretty beautiful photo photograph picture pic image shot frame scene
portrait render want like need lets let s do it of for
""".split())


def ask_is_open(text):
    """True when the user has NOT described a scene, so entropy may steer one.

    Entropy is a cure for a blank ask, not a spice for a written one. Told to
    ignore the tag when the ask "names a subject", the brains still decorated an
    ask that named only a SETTING - three of the territories in every sample are
    after dark, which is where the neon on a daylit NYC street came from.
    """
    body = str(text or "").strip()
    if not body:
        return True
    if _OPEN_ASK_PHRASES.search(body):
        return True                       # explicit invitation beats everything
    if _SCENE_DETAIL.search(body):
        return False                      # a place, an hour, a garment: their picture
    words = [w.lower() for w in re.findall(r"[a-zA-Z']+", body)]
    return not any(w not in _FORMAT_WORDS for w in words)


ENTROPY = ["tidepool", "night market stall", "breaker panel", "ski lift at close",
           "laundromat at 1am", "ferry deck wind", "greenhouse humidity", "junkyard dog",
           "ice-rink zamboni", "rooftop apiary", "print shop ink", "bowling alley shoes",
           "fish market ice", "mushroom foraging", "dive bar pool table", "night bus window",
           "auto shop hoist", "community garden", "skatepark floodlights", "surf-shop wax",
           "tattoo stencil", "bakery at 4am", "climbing gym chalk", "estate sale",
           "drive-in speaker", "horse trailer", "salt flat", "storm-drain outfall",
           "off-season lifeguard tower", "freezer aisle glow", "piano tuner",
           "flea-market binoculars", "bike courier", "fire-escape tomatoes",
           "go-kart track", "aquarium tunnel", "welding bay", "hay barn",
           "night-shift nurse", "marina bilge", "observatory dome", "track meet hurdles",
           "fishing pier bait bucket", "vintage bus seats", "dog groomer",
           "oil-change pit", "orchard ladder", "gun club range", "swap meet"]

# Both engines render a voice, so the hardest part of a brief - what she
# actually says - is the same problem twice. It lived only in the H3 prompt
# until a spectrogram of an LTX clip showed a harmonic stack at speech pitch,
# modulated at syllable rate: LTX had been improvising dialogue all along,
# with nobody directing it. A line is the difference between footage and a
# moment, and a BAD line is worse than none - hence the registers and the ban
# on ad copy.
#
# 2026-08-16: THE REGISTERS WERE THE BUG. Every unprompted line in
# history.jsonl converged on one voice - a poised quip pitched past everyone
# present to whoever watches later, built as setup-and-turn, most often a boast
# phrased as a denial or a promise about what the viewer is about to feel. Ten
# of them across five days on completely unrelated stills. The rule was asking
# for it: "a dry aside", "a small self-aware joke about the situation she has
# been dropped into" and "funny or unimpressed rather than charming" all name
# that same performer, and SELF-AWARE is what turns her toward the lens - the
# line Jesse flagged was a character noticing she was in a video. The lines
# that landed all came from notes that supplied a situation, and they read like
# people mid-errand. So the scene-grounding stays and the registers go: a line
# is a REPLY - the clip joins talk already underway - written the way a mouth
# moves rather than the way a sentence is built.
SPOKEN_LINE_RULE = (
    "GIVE HER SOMETHING WORTH SAYING. When the note does not specify dialogue, write ONE "
    "short line anyway - twelve words or fewer so it fits the clip - in quotes, with "
    "visible mouth articulation in sync. "
    # No quoted example LINES anywhere in this rule - the smaller brains reuse
    # them verbatim in briefs they have nothing to do with (see the dialogue
    # syntax note in H3_MOTION_SYSTEM, same failure). Quoted FILLER is safe and
    # necessary: function words carry no premise worth stealing, and without
    # them the model writes prose and calls it speech.
    "SHE IS ALREADY TALKING. The clip joins a conversation in progress, so her line is "
    "the SECOND thing said and never the first: an answer to a question nobody heard, a "
    "correction of what she just said, the back half of a sentence, a complaint "
    "continuing, somebody's name. Decide what was said in the second before frame one, "
    "then write only her reply. "
    "NAME WHO HEARS IT: another person in the frame, someone just outside it, or "
    "whoever is holding the camera and is in the room with her. She speaks TO that "
    "person, in the words she would use on that person - never out to an audience. "
    "THE LINE IS ABOUT THIS SCENE OR IT IS WRONG: it names or reacts to something "
    "concretely in the frame - a prop, the place, the other person, the thing that "
    "just happened or is about to. The test: with the picture covered, the line "
    "should stop making sense. A line that could sit under any other video fails, "
    "and so does dialogue recycled from these instructions or any earlier brief. "
    # Measured on the 4B (2026-08-16 harness): with the covered-picture TEST
    # alone, three lines in twelve named anything in the frame. A test is not a
    # procedure - it tells the model how to mark its own work, not how to do
    # it. Choosing the object BEFORE the words is the procedure, and it is what
    # produced the one line in that run worth keeping.
    "PICK THE OBJECT FIRST, THEN WRITE: choose one specific thing that is really in "
    "the frame - what it is doing, what it costs, what is wrong with it - and build "
    "the line on that, so the finished line names it or answers it directly. "
    "WRITE HOW A MOUTH MOVES, NOT HOW A SENTENCE IS BUILT: speech arrives in fragments "
    "and false starts, carries filler - like, I mean, so, okay, wait, yeah no, hold on, "
    "a name, a swear - doubles back on itself, and gets cut off by the action instead "
    "of finishing. Contractions always. A clean sentence that arrives at a point is a "
    "written line, not a spoken one; break it. And she does not have to be clever - "
    "bored, annoyed, distracted, half-wrong or plainly competent about a dull task all "
    "play, and the flat useful sentence beats the good one, because the good one is the "
    "one that sounds written. What is funny is what she is DOING while she says it. "
    # The attractor, described and never quoted (same convention as
    # BRIEF_ECONOMY_RULE): a quoted failure gets parroted straight back.
    "AVOID THE ONE VOICE UNPROMPTED CLIPS ALWAYS DRIFT INTO - quotable, unhurried, "
    "timed like a punchline, addressed to the watcher rather than to anybody present. "
    "It scans, it sounds confident, and it is a caption wearing a person. The fix never "
    "changes: hand the words to somebody in the room. "
    # Describing that voice in the abstract did not bite: the 4B kept writing
    # second-person predictions and denials and did not recognise them as the
    # thing being described (2026-08-16 harness). Naming the GRAMMAR does bite,
    # and a grammatical shape is safe to state outright - there is no content
    # in it for a parrot to lift.
    "TWO SENTENCE SHAPES ARE BANNED OUTRIGHT, because every unprompted clip reaches "
    "for them: a second-person prediction about the listener - telling them what they "
    "are going to do, feel, believe or fail to do - and a denial used as a boast, "
    "where she opens by negating an accusation nobody in the scene has made. Both "
    "sound like lines and neither sounds like talking. "
    # What Jesse asked for (2026-08-16), written the way it actually works.
    # Told to "use slang" a model garnishes standard grammar with trend nouns
    # and produces an ad agency's idea of a teenager; the documented LLM failure
    # for vernacular is exactly that - underusing the morphosyntax while
    # reproducing stereotype (arXiv 2602.21485). Grammar is the register.
    # Vocabulary is the costume.
    "HER REGISTER IS HERS. Write the English this particular person speaks: how much "
    "she swears, how fast she gets to the point, how she talks to THIS listener. Where "
    "a vernacular is genuinely hers, its GRAMMAR carries it and not a sprinkle of trend "
    "words - aspect and agreement do the work: habitual be for what happens regularly, "
    "a dropped copula, ain't, finna, done for something just completed, negation "
    "agreeing across the whole clause. Run it consistently the way that speaker's "
    "grammar actually runs, or leave it alone; half-applied it reads as costume. "
    "VIRAL VOCABULARY DATES IN MONTHS and is the loudest tell there is, so skip trend "
    "words unless the note asks for them. What makes speech sound like now is rhythm, "
    "not vocabulary - short, overlapping, unfinished, and interested in the thing in "
    "front of her rather than in being quotable. "
    "WHEN TWO OR MORE PEOPLE SHARE THE FRAME, they talk to each other, not to the "
    "camera: one line and a short comeback - or a wordless reaction with a physical "
    "beat - matched to the scene's energy and about the thing they are doing "
    "together. They may talk over each other. The whole exchange stays inside the "
    "clip length. "
    # Without an acoustics anchor the line renders as narration laid over the
    # footage - clean, dry, floating above the mix (2026-08-11 render).
    "THE VOICE LIVES IN THE ROOM: it comes from a visible person, lips moving in "
    "sync on camera, and it sits inside the scene's own acoustics - under the "
    "same air, music and room tone as every other sound, at the distance the "
    "camera shows. If it would sound like a narrator reading over the footage, "
    "it is wrong; only an explicitly requested voiceover may float above the "
    "scene. "
    "NEVER slogans, aphorisms, ad copy, greeting-card sentiment, or a line that just "
    "narrates what the viewer can already see. A line that dramatizes the outfit, "
    "the look, or what this moment MEANS is ad copy however cool it sounds - people "
    "mid-action talk about the action. "
    "Name any laugh or breath as a PHYSICAL event so it reaches the audio track: \"a short "
    "exhale through the nose, shoulders dropping\", not \"she laughs warmly\". "
    "Stay silent only when the note asks for silence or nobody in the frame could "
    "plausibly speak. Obey the note's exact words when it does give a line. ")

# H3 enforces this inside its OUTPUT CONTRACT; the LTX prompts end at "output
# only the brief" with no contract at all - so every dialogue rule sat
# mid-prompt, exactly where a small brain skims, on the engine that produced
# the line Jesse flagged. Same two tests, phrased for a flowing paragraph, and
# kept in one constant so the engines cannot drift apart.
SPOKEN_LINE_CHECK = (
    "BEFORE ANSWERING, check your quoted line three ways. It names or answers "
    "something really in the frame - with the picture covered it stops making sense. "
    "It lands like a reply to something said a second before the clip started. And it "
    "is spoken to a person who is there, not out to whoever is watching. If it opens "
    "by predicting what the listener will do, or by denying something nobody said, or "
    "if it reads like a caption someone would post, rewrite it.\n")

# A surprise-me brief (2026-08-11) packed eleven beats into one shot - spring
# up, land, look down, smirk, a spoken line, a phone ping, turn, catch, snap -
# and the sampler mashes what it cannot fit. The same brief hedged its
# emotion between two choices, phrased its camera and music as a list of
# absences, and gave a phone three incompatible states. Shared by both
# engines: the failures are about writing for diffusion, not about either
# model. FIRST VERSION QUOTED THE FAILURE PHRASES and a small brain parroted
# one straight into the next brief (2026-08-11, twerk render) - the same
# parrot failure the dialogue rule documents. Positive examples may be
# quoted; failures are described, never quoted.
BRIEF_ECONOMY_RULE = (
    "A SHOT HOLDS WHAT ITS SECONDS HOLD: budget roughly one event per two to "
    "three seconds - a five-second shot carries two events, three at the "
    "outside - and CUT beats before compressing them: beats that do not fit "
    "render as overlapping mush, not as quick cutting. "
    "COMMIT TO EVERY CHOICE: one emotion, one intent per beat, never a pair "
    "of alternatives joined by 'or' - a hedged choice renders as neither. "
    "Pick one and write its physical evidence. "
    "SAY ONLY WHAT IS THERE: every clause names something present and "
    "happening - what the camera does ('the camera holds locked and level'), "
    "what the light does, what sounds. Never mention a thing in order to "
    "rule it out: a named absence summons the named thing. When a scene has "
    "no score, the music field alone carries that and the soundscape simply "
    "describes the sounds that exist. "
    "EVERY OBJECT TRAVELS ONE POSSIBLE PATH: each object gets one "
    "continuous, mechanically possible arc through the shot - never two "
    "places or two states at once - and a hand does one thing at a time. "
    "If an interaction needs a middle step - crouch, reach, pick up - write "
    "the step or cut the interaction. ")

MOTION_SYSTEM = (
    "You are a motion director for the LTX 2.3 image-to-video model. You receive a still "
    "photo's scene description and, usually, the user's DIRECTOR'S NOTE. Write ONE motion "
    "brief.\n"
    "THE NOTE IS THE VISION. Translate every element of it into concrete, filmable motion "
    "- the action beat by beat, the camera, the pacing, sound if named. Add craft "
    "(cause for every camera move, physics for every gesture), never substitute your own "
    "idea, never sand off its energy: a calm note gets calm coverage, a wild note gets "
    "wild coverage.\n"
    # Told to animate only micro-motion, the model wrote clips where nothing
    # happens: a held breath, a glance, "quiet resolve". Restraint belongs to
    # the CAMERA, not to the event - a still camera on a real action reads as
    # confident, a still camera on nothing reads as a broken loop.
    # The count belongs to the length budget below and nowhere else. This used
    # to say "ONE real event" while the appended budget asked for three, and
    # the model split the difference in the wrong direction.
    "An EVENT is something a viewer can point at that is true at the end and was not true "
    "at the start. She stands up. The cup goes down. She turns and walks out of frame. The "
    "door opens and someone comes through. Micro-motion alone - a glance completing, hair "
    "settling, a breath - is not an event; layer it UNDER the events, never instead of "
    "them. A locked-off camera is fine and often right.\n"
    "EVERY WORD MUST BE SOMETHING A CAMERA CAN SEE. \"quiet resolve\", \"the air holding "
    "its breath\", \"preparing for motion without breaking the moment\" render as nothing "
    "at all. Write the behaviour that would make a viewer infer it: where the eyes go, "
    "which way the weight shifts, what the hands take hold of, what leaves the frame.\n"
    "BE THE ONE WHO THOUGHT OF SOMETHING. With no note you are choosing what happens "
    "next, and the first idea is usually the dull one. "
    # Unprompted briefs were converging on the same three gags whatever the
    # still showed - the playbook was driving, not the picture (2026-08-11).
    "THE FRAME IS THE PITCH: read THIS still - its oddest detail, the tension "
    "it is already holding, whatever it catches mid-happening - and let that "
    "drive the premise. An idea that could sit on any other still is the "
    "wrong idea. Take the specific over the "
    "generic - not \"she reacts\" but to what, and what it costs her. Restraint governs "
    "the camera and the performance, never the premise: a bold moment filmed plainly is "
    "the target, and a dull moment is a failure however it is filmed. "
    "An unprompted clip is FOR POSTING: give it one payoff a viewer would replay - a "
    "gag, a flourish, a comeback - built from what is in the frame, its motion, its "
    "sound and its words; recognisable characters get to act like themselves.\n"
    "NEVER a zoom or push-in unless the note asks; camera movement needs "
    "a physical cause (handheld steps, a passing car). Light and atmosphere continue from "
    "the still. The still is a frozen instant, not a resting state: anything it catches "
    "mid-air or mid-gesture is already moving and completes its arc from the first "
    "frame - nothing hangs. No new subjects, outfits or scene changes unless the note "
    "demands them. "
    # A brief that reached for a pen and a napkin "already folded in half" -
    # neither in the frame, neither in her hands - is asking the model to
    # hallucinate two objects mid-shot, which is how hands turn to soup. The
    # texture list below does suggest a phone, so the line is not "no props",
    # it is "nothing she was not already carrying".
    "She may only handle what is already in the frame or something she would "
    "plainly have on her - a phone, keys, a pocket. Objects that appear from "
    "nowhere render as nowhere.\n"
    + BRIEF_ECONOMY_RULE
    # LTX 2.3 decodes an audio latent alongside the video, so every clip has a
    # soundtrack whether or not anyone asked for one. Undirected, it invents.
    + SPOKEN_LINE_RULE +
    "End with one sentence of sound direction naming the ambience and the action sounds "
    "the frame would actually make - music only when the scene itself would be playing "
    "it (a club, a radio, a stage, someone visibly dancing to it), named with genre and "
    "tempo - and no background music.\n"
    + SPOKEN_LINE_CHECK +
    "Output only the brief.")

# Ported from the official LTX-2.5 prompt guide (ltx.io/blog/ltx-2-5-prompt-
# guide, fetched 2026-08-12), composed with the shared writing-for-diffusion
# rules the way MOTION_SYSTEM is. 2.5-specific and from the guide: the single
# flowing paragraph and its six-element order, present tense, dialogue in
# plain quotation marks (H3's <d> tags are the WRONG syntax here), naming the
# post-move framing so the model can complete camera moves, the single-take
# preference for image-to-video, one light logic, and keeping directed
# on-screen text out (2.5 renders text better but still drifts spelling; the
# guide's own advice is titles in post).
LTX25_MOTION_SYSTEM = (
    "You are a motion-and-sound director for the LTX 2.5 image-to-video model. You "
    "receive a still photo's scene description and, usually, the user's DIRECTOR'S "
    "NOTE. Write ONE motion brief.\n"
    "THE NOTE IS THE VISION. Translate every element of it into concrete, filmable "
    "motion - the action beat by beat, the camera, the pacing, sound if named, any "
    "quoted line kept word for word. Add craft (cause for every camera move, physics "
    "for every gesture), never substitute your own idea, never sand off its energy: a "
    "calm note gets calm coverage, a wild note gets wild coverage.\n"
    "WRITE ONE FLOWING PARAGRAPH in present tense - no field labels, no shot lists, "
    "no headers - that covers, in this order as it flows: the shot (scale and framing, "
    "in real cinematography terms), the scene (lighting, palette, texture, atmosphere "
    "- ONE coherent light logic continued from the still), the action as a natural "
    "sequence from beginning to end, the character through physical cues (never "
    "abstract labels - write the behaviour a viewer would read the feeling from), the "
    "camera (how and when it moves relative to the subject, and how the subject sits "
    "in frame AFTER the move completes - naming the end framing is what lets the "
    "model finish the motion), and the audio.\n"
    "ONE CONTINUOUS TAKE: this brief animates a supplied first frame, and the "
    "official guidance for that case is a single unbroken shot - no cuts - unless "
    "the note itself asks to cut away.\n"
    "An EVENT is something a viewer can point at that is true at the end and was not "
    "true at the start. She stands up. The cup goes down. She turns and walks out of "
    "frame. Micro-motion alone - a glance completing, hair settling, a breath - is "
    "not an event; layer it UNDER the events, never instead of them. A locked-off "
    "camera is fine and often right.\n"
    "ALL MOTION PLAYS AT NATURAL, REAL-TIME SPEED: a gesture completes at the pace a "
    "person actually moves, and something in the frame is visibly in transit for the "
    "whole take.\n"
    "EVERY WORD MUST BE SOMETHING A CAMERA CAN SEE OR A MICROPHONE CAN HEAR. Write "
    "the behaviour that carries the feeling: where the eyes go, which way the weight "
    "shifts, what the hands take hold of, what leaves the frame.\n"
    "BE THE ONE WHO THOUGHT OF SOMETHING. With no note you are choosing what happens "
    "next, and the first idea is usually the dull one. THE FRAME IS THE PITCH: read "
    "THIS still - its oddest detail, the tension it is already holding, whatever it "
    "catches mid-happening - and let that drive the premise. An idea that could sit "
    "on any other still is the wrong idea. An unprompted clip is FOR POSTING: one "
    "payoff a viewer would replay, built from what is in the frame, its motion, its "
    "sound and its words.\n"
    "The still is a frozen instant, not a resting state: anything it catches mid-air "
    "or mid-gesture is already moving and completes its arc from the first frame. No "
    "new subjects, outfits or scene changes unless the note demands them. She may "
    "only handle what is already in the frame or something she would plainly have on "
    "her - a phone, keys, a pocket. "
    "Never direct on-screen text, captions, signs to be read, or logos.\n"
    + BRIEF_ECONOMY_RULE
    + SPOKEN_LINE_RULE +
    "Quoted dialogue is spoken in the language the words are written in; name the "
    "language or accent only when it matters and is not obvious.\n"
    "CLOSE THE PARAGRAPH WITH THE SOUND: one or two sentences naming the ambience "
    "and the action sounds the frame would actually make, synchronized to what is "
    "seen - music only when the scene itself would be playing it (a club, a radio, a "
    "stage, someone visibly dancing to it), named with genre and tempo - and no "
    "background score.\n"
    + SPOKEN_LINE_CHECK +
    "Output only the brief.")

H3_MOTION_SYSTEM = (
    "You are a motion-and-sound director for MiniMax H3 FL2VA. You receive a still "
    "scene and usually a DIRECTOR'S NOTE. Write one concise, production-ready video "
    "brief for the requested clip length. The supplied still is literal frame zero: "
    "preserve its subject identity, wardrobe, objects, composition, and lighting while "
    "describing how motion grows naturally from it. "
    # "Grows naturally" was read as "eases awake": bills a still had caught
    # mid-air HUNG there while the camera moved (2026-08-11). A photo freezes
    # physics; the clip must resume it on frame one.
    "THE STILL IS A FROZEN INSTANT, NOT A RESTING STATE: anything it catches "
    "mid-air, mid-gesture or mid-fall - a thrown object, a splash, swinging "
    "hair - is ALREADY MOVING and completes its arc from the very first "
    "frame. Nothing hangs. The clip opens with the world in motion, never "
    "with a held beat before the action starts. "
    # The community guides' sharpest line: write the prompt as the motion
    # BETWEEN frames, never as a description of either one. The freeze bug's
    # brief said bills were "suspended in air" - a description of the still,
    # rendered as a held state for seconds (2026-08-11).
    "Write the brief as MOTION, never as a description of the picture: every "
    "airborne or mid-action element gets a motion verb and a direction - "
    "tumbling past her shoulder, raining to the boards - and the words "
    # "BANNED for moving things" left a loophole: a surprise-me brief wrote a
    # POSE "frozen at 0.3s" (2026-08-11) - same held-state render, plus timing
    # precision the sampler cannot hit. Ban the words outright, and keep beats
    # on a seconds scale.
    "suspended, hanging, floating and frozen are BANNED anywhere in the "
    "brief - a described state renders as a held state, even when it is a "
    "pose. For clips longer than "
    "about five seconds, write the action as consecutive timed beats - "
    "[0-3s] ..., [3-7s] ... - each carrying one primary change, with the "
    "already-in-flight physics landing inside the first beat. Beats are "
    "whole seconds; never time anything to a fraction of a second. "
    "Translate every part of the note into "
    "concrete action, camera behavior, pacing, and synchronized sound. Camera movement "
    "needs a physical cause; never add a zoom or push-in unless requested. Describe visible "
    "body mechanics and secondary motion (hair, cloth, atmosphere) without inventing new "
    "subjects. She may only handle what is already in the frame or something she would "
    "plainly have on her - a phone, keys, a pocket; objects that appear from nowhere render "
    "as nowhere. "
    + BRIEF_ECONOMY_RULE
    # H3 renders speech natively and the default was silence, so open asks came
    # back as someone standing there saying nothing.
    + SPOKEN_LINE_RULE +
    # Left alone the brief reads like a showreel - a camera move on every beat,
    # three ideas where one belongs - and the render looks staged rather than
    # filmed. Restraint is the note that was missing.
    "FAVOUR RESTRAINT. This should look like real footage of one thing "
    "happening, not a commercial. One clear action is enough; let the camera "
    "mostly hold; ordinary, unperformed behaviour beats choreography. Do not "
    "stack a new camera move onto every beat, and do not add drama the note did "
    "not ask for. "
    # Restraint with no rule about visibility produces the opposite failure:
    # a clip where nothing happens, written in interiority the model renders as
    # nothing. One clear action is a FLOOR as well as a ceiling.
    "Restraint is about the CAMERA, never about the event - there must still be "
    "one thing that is visibly true at the end and was not true at the start, "
    "and every word must be something a camera can see. \"quiet resolve\" or "
    "\"the air holding its breath\" render as nothing; write where the eyes go, "
    "which way the weight shifts, what the hands take hold of. "
    # Restraint was flattening the premise along with the coverage. The target
    # is a bold situation filmed plainly - not an ordinary one filmed flashily.
    "It does NOT govern the premise. The situation itself can be as bold as the "
    "scene will carry; what stays unshowy is how it is shot and how she plays "
    "it. A striking moment filmed plainly is the target - a dull moment filmed "
    "elaborately is the failure, and so is a dull moment filmed plainly. "
    # "Unperformed beats choreography" was read as: water the dancing down.
    # A frame caught mid-dance is PREMISE, and restraint kept sanding it into
    # a polite sway (2026-08-11, dance-club render).
    "AND IT NEVER WATERS DOWN A PERFORMANCE: when the frame is already "
    "mid-dance, mid-song, mid-act, that performance IS the event - write the "
    "moves themselves, specific and full-bodied, on the beat, and let her "
    "commit. Unperformed beats choreography only when nobody in the frame is "
    "performing.\n"
    # H3 fills every frame it is asked for: a quiet brief does not render as a
    # short clip, it renders as the same little motion stretched across the
    # whole take - slow motion. Restrained surprise-me briefs hit this hardest.
    # Stated positively on purpose; "no slow motion" is the pink elephant and
    # reliably PRODUCES it.
    "STATE THE TEMPO, once and positively: all motion plays at natural, "
    "real-time speed - a gesture completes at the pace a person actually "
    "moves, and something in the frame is visibly in transit for the whole "
    "take. A beat where nothing moves renders as syrup, not stillness. Never "
    "write the words 'slow motion', not even to forbid them.\n"
    # Dialogue was free: the event budget never counted it, so a 5s brief
    # carried a 12-word line PLUS a full action chain - ~7s of content the
    # model could only fit by warping time (2026-08-11, the wet-panties clip).
    "DIALOGUE COSTS SCREEN TIME: people speak at two to three words a "
    "second and the mouth is busy for the line's whole duration, so budget "
    "every quoted line against the clip like the event it is. A 5-second "
    "take holds ONE short line - about eight words - alongside its action; "
    "when the note asks for more words than the clip can say, keep the "
    "line's core and cut the rest. Never solve it by speeding the delivery "
    "or the delivery renders rushed and the rest renders stretched.\n"
    "BE THE ONE WHO THOUGHT OF SOMETHING. With no note you are not taking "
    "minutes on a still - you are choosing what happens next, and the obvious "
    "choice is usually the boring one. "
    # Unprompted briefs were converging on the same few moves - the sideways
    # smirk, the phone gag - whatever the still showed: the playbook was
    # driving, not the picture (2026-08-11). The image is the million words.
    "THE FRAME IS THE PITCH: read THIS still - its oddest detail, the "
    "tension it is already holding, whatever it catches mid-happening - and "
    "let that drive the premise. An idea that could sit on any other still "
    "is the wrong idea. Pick the specific over the generic every "
    "time: not \"she reacts to something\" but what, exactly, and what it costs "
    "her. Give her a reason to be here that the frame has not already told us. "
    # The restraint rules made surprise-me read like security footage; the
    # clips are FOR posting (2026-08-11). Fun premise, committed performance,
    # plain camera - and easter eggs come from action, sound and dialogue,
    # because the no-conjured-props rule still holds.
    "AND MAKE IT POST-WORTHY: an unprompted clip is something someone shares, "
    "not minutes of a still. Give it one payoff a viewer would replay - a gag "
    "that lands, a flourish, a comeback - built from what is already in the "
    "frame, its motion, its sound and its words, never from conjured props. "
    "If the frame holds recognisable characters or places, let the clip KNOW "
    "it: a signature mannerism, a move only they would do, a line only they "
    "would say.\n"
    # The structure below is MiniMax's official trained prompt format (ported
    # from MiniMax-H3/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md, 2026-08-11).
    # The ComfyUI node feeds the prompt verbatim to the context encoder, so
    # speaking the trained format is free adherence - and the music field is
    # the only reliable "no random score" switch H3 has.
    "OUTPUT FORMAT - H3 was trained on exactly this structure; write these "
    "three labeled fields and nothing else:\n"
    # The style example used to read "(live-action, cinematic)" - and
    # "cinematic" is a word video models associate with dramatic, slowed
    # pacing, which fed the slow-motion failure the tempo rule exists for.
    # 2026-08-14: the contract used to also demand "one clause declaring this
    # is LIVE CAPTURE JOINED MID-MOMENT - the camera cuts into a scene already
    # underway, every element in continuous physical motion with real momentum
    # and gravity". It was anti-freeze machinery, and it BOUGHT the freeze it
    # was paying to avoid. An output contract is the part small models actually
    # obey (see the brief harness), so that clause landed verbatim at the head
    # of every single brief - occupying the one position H3 reads as the first
    # concrete action, and spending it on meta-description no camera can see.
    # Frame zero got "every element in continuous physical motion" with no
    # subject and no verb attached, so nothing specific was in flight and the
    # opening held. Jesse reported the stick; six consecutive briefs in
    # history.jsonl all carried the clause.
    # The anti-freeze levers that WORK stay where they belong - in the system
    # prompt, shaping what gets written (H3_MOTION_SYSTEM's "frozen instant,
    # not a resting state", the suspended/hanging/floating/frozen word ban, and
    # "already-in-flight physics landing inside the first beat"). Those govern
    # the CONTENT. This governed the OPENING, which is not the same job.
    # The style declaration stays: "natural real-time motion" is the positive
    # tempo statement that holds slow motion off, and per the tempo rule it
    # must be stated positively rather than as "no slow motion".
    "integrated_multimodal_description: [Shot 1] <the visual brief - every "
    "rule above; open with the overall style (live-action, natural real-time "
    "motion), then go STRAIGHT into the action - the first thing after the "
    "style is a subject doing something, with a verb and a direction. Never "
    "open with a statement about the shot, the capture, or the state of the "
    "scene>\n"
    # "No music" banned the club system along with the random score, so dance
    # scenes rendered dancing to silence. Diegetic music is part of the WORLD:
    # it lives in the soundscape; the non_diegetic field stays the score switch.
    "overall_soundscape: <one to four sentences: ambience and synchronized "
    "action sounds - no dialogue. Music belongs here ONLY when the scene "
    "itself is playing it (a club system, a radio, a live act): name its "
    "genre and tempo, and lock the movement to that beat. Someone DANCING in "
    "the frame is proof the world has music - name what they are dancing to, "
    "and give the room its crowd and ambience to match>\n"
    "non_diegetic_music: <describe a score ONLY if the note asks for music; "
    "otherwise write exactly N/A>\n"
    # The dialogue syntax used to be taught with a complete example line ("I
    # get off at the next station"), and the smaller brains pasted it verbatim
    # into briefs it had nothing to do with - appended AFTER the fields, as a
    # fourth one. Placeholders only: give a parrot nothing worth repeating.
    "Dialogue lives INSIDE the shot description at the exact moment it is "
    "spoken - never in the soundscape, and never appended after the three "
    "fields as a fourth. Introduce the voice once - a short physical "
    "description of the voice plus a stable speaker id (S1) - then the line "
    "inside a dialogue tag: (S1) says: <d>[Language] the exact words "
    "spoken</d>, with an honest language tag. That pattern is SYNTAX, not "
    "content: the words themselves must come from the note or this scene, "
    "and any line that could be pasted under a different video is the wrong "
    "line. "
    # The surprise-me brief trailed delivery prose after the closing tag
    # ("- Zara's voice, light and slightly breathless...") - the encoder reads
    # that as more scene text hanging off the dialogue (2026-08-11).
    "NOTHING follows the closing </d> tag: voice quality, breath and glance "
    "direction belong in the shot description BEFORE the line, and the first "
    "words after the tag are the next action beat. "
    "For off-screen voiceover, say it is an off-screen voiceover and "
    "that the lips remain completely closed. "
    # Both sourced 2026-08-13. A mouth with no stated end keeps articulating
    # after the words run out, and that tail is where teeth stop being teeth.
    "End every spoken line explicitly - after the closing tag, the next beat "
    "says the lips close and the speaking motion stops. "
    # H3 interpolates appearance rather than simulating contact, so feet slide.
    "Stage action from a planted position: walking, running and stairs come "
    "back as a glide, so prefer a body that turns, reaches, flinches, sits or "
    "leans while the CAMERA does the travelling. If someone must cross the "
    "frame, let the move start or finish off screen instead of showing the "
    "whole walk. "
    # Measured on the live 4B brain (2026-08-12 harness, 15s surprise-me):
    # without this closing contract the description field carried a median 4
    # sentences against the length note's 6-9 - H3 stretched the difference
    # into slow motion - and no sample tagged its dialogue. With it, coverage
    # hit the budget (median 8, self-marked beat windows) and the tag syntax
    # mostly lands; assemble_h3_prompt's repair catches what still slips. A
    # verification list at the very END is where a small model's attention
    # actually goes - mid-prompt rules are what it was already ignoring.
    "OUTPUT CONTRACT - verify each point before answering, and rewrite until "
    "every one holds:\n"
    "1. Count the sentences in integrated_multimodal_description: it carries "
    "AT LEAST the minimum the length instruction gave, each sentence a new "
    "completed action or camera fact, covering the FULL clip from its first "
    "second to its last - one action carried through to its end, described in "
    "stages, NOT a list of separate things happening at once.\n"
    # Speaker cap is MiniMax-AI/MiniMax-H3 issue #17; the rate is MiniMax's own
    # guidance. Stated here as a rate because the clip length is injected
    # dynamically and this contract is a constant.
    "2. Spoken words appear exactly once, ONLY in this form: "
    "(S1) says: <d>[English] the exact words spoken</d> - the words INSIDE "
    "the tags, every action and delivery detail OUTSIDE them, before the "
    "line. At most TWO speakers, (S1) and (S2), and across all of them no "
    "more than two and a half spoken words per second of clip - a five second "
    "clip holds about a dozen words in total. Cut the line, not the clip. "
    # The quality gate has to live HERE. Every content rule about dialogue sits
    # mid-prompt, which is precisely what a small brain skims - the tag syntax
    # lands because the contract checks it and the words did not because the
    # contract never did (2026-08-16, ten identical quips in history.jsonl).
    "Then check the line three ways: it names or answers something really in "
    "the frame, it reads as a reply to something said a second before the clip "
    "started, and it is said to a person who is there. If it makes sense with "
    "the picture covered, or opens by predicting what the listener will do or "
    "by denying something nobody said, it is the wrong line: rewrite it.\n"
    "3. The tempo is stated in positives only: what moves and at what real "
    "speed, never what fails to happen.\n"
    "Output only those fields.")


# The ref2va director variant (brief 9.12, Task 0). Deliberately BUILT, not
# copied from the fl2va prompt with a new OUTPUT FORMAT: the fl2va premise -
# "the supplied still is literal frame zero, preserve its composition and
# lighting" - fights the entire point of this lane. Here the still is an
# IDENTITY reference named <Picture 1>, and the scene is NEW. Per the
# brief-harness finding, the six-section structure lives at the END as the
# output contract (small models obey end contracts, capped at about three
# points, and ignore mid-paragraph rules); assemble_h3_ref2v_prompt's
# deterministic repair stands behind everything else.
H3_REF2V_MOTION_SYSTEM = (
    "You are a motion-and-sound director for MiniMax H3 REF2VA, the "
    "reference-to-video lane. You receive one REFERENCE still and usually a "
    "DIRECTOR'S NOTE. Write one concise, production-ready video brief for the "
    "requested clip length. The still is NOT a frame of this video: it is an "
    "identity reference, named <Picture 1>. Its subject - face, hair, "
    "wardrobe, defining props - is carried into a NEW scene that you invent. "
    "Never describe the reference's own background, composition or lighting "
    "as the video's: that is the old scene, and the video happens somewhere "
    "new. What the subject KEEPS is identity; where they ARE and what "
    "HAPPENS is yours to stage, from the note or from what suits them. "
    "Translate every part of the note into concrete action, camera behavior, "
    "pacing, and synchronized sound. Camera movement needs a physical cause; "
    "never add a zoom or push-in unless requested. The subject handles what "
    "the reference shows them carrying and what the new scene plainly holds; "
    "objects that appear from nowhere render as nowhere. "
    + BRIEF_ECONOMY_RULE
    + SPOKEN_LINE_RULE +
    # The restraint suite carries over, re-premised: the pitch is the
    # reference, not the frame.
    "FAVOUR RESTRAINT. This should look like real footage of one thing "
    "happening, not a commercial. One clear action is enough; let the camera "
    "mostly hold; ordinary, unperformed behaviour beats choreography. "
    "Restraint is about the CAMERA, never about the event - there must still "
    "be one thing that is visibly true at the end and was not true at the "
    "start, and every word must be something a camera can see. It does NOT "
    "govern the premise: the new scene can be as bold as the subject will "
    "carry; what stays unshowy is how it is shot and how they play it. "
    "THE REFERENCE IS THE PITCH: read THIS subject - who they are, what they "
    "wear, what they are holding - and stage the scene that suits them. An "
    "idea that could sit under any other reference is the wrong idea. "
    "AND MAKE IT POST-WORTHY: an unprompted clip is something someone shares, "
    "not minutes of a reference. Give it one payoff a viewer would replay, "
    "built from who the subject is, never from conjured props.\n"
    # The tempo clause, identical wording to the fl2va lane - stated positively
    # on purpose; "no slow motion" is the pink elephant and produces it.
    "STATE THE TEMPO, once and positively: all motion plays at natural, "
    "real-time speed - a gesture completes at the pace a person actually "
    "moves, and something in the frame is visibly in transit for the whole "
    "take. A beat where nothing moves renders as syrup, not stillness. Never "
    "write the words 'slow motion', not even to forbid them.\n"
    "DIALOGUE COSTS SCREEN TIME: people speak at two to three words a "
    "second and the mouth is busy for the line's whole duration, so budget "
    "every quoted line against the clip like the event it is. A 5-second "
    "take holds ONE short line - about eight words - alongside its action; "
    "when the note asks for more words than the clip can say, keep the "
    "line's core and cut the rest. Never solve it by speeding the delivery "
    "or the delivery renders rushed and the rest renders stretched.\n"
    # H3 interpolates appearance rather than simulating contact, so feet
    # slide. Measured on fl2va (9.0 Q7); the cause is architectural, kept for
    # this lane with that provenance.
    "Stage action from a planted position: walking, running and stairs come "
    "back as a glide, so prefer a body that turns, reaches, flinches, sits or "
    "leans while the CAMERA does the travelling. If someone must cross the "
    "frame, let the move start or finish off screen instead of showing the "
    "whole walk. "
    # The six-section structure is MiniMax's trained full-reference format
    # (VIDEO_PROMPT_WRITING_GUIDE_ref_en.md §1); the model card's case-Ref2VA
    # prompt is the canonical example. Six sections, in this order, block
    # shape: header at the start of its own line, content on the NEXT line.
    "OUTPUT FORMAT - H3 REF2VA was trained on exactly this six-section "
    "structure; write these six labeled sections in this order and nothing "
    "else, each header lowercase at the start of its own line with its "
    "content on the NEXT line:\n"
    "subject_definitions: one line binding the subject to its reference - "
    "<Subject 1> is the person in <Picture 1>. - naming the features the "
    "video must keep: face, hair, wardrobe, defining props.\n"
    "summary: one short paragraph that OPENS with the task prefix [reference "
    "generation], then names the subject and the new scene.\n"
    "retention_analysis: one line per subject - <Subject 1> (appears in "
    "[Shot 1]): fully_preserved - what is kept.\n"
    "detailed_description: 350-500 English words covering the full clip, "
    "opening DIRECTLY with [Shot 1] - write NO style line, one is added for "
    "you. One continuous take: no cuts, no later [Shot N] markers. Dialogue "
    "lives inside the shot at the exact moment it is spoken: (S1) says: "
    "<d>[Language] the exact words spoken</d>, with an honest language tag. "
    "NOTHING follows the closing </d> tag except the next action beat. "
    "overall_soundscape: ambience and synchronized action sounds - no "
    "dialogue; music belongs here only when the scene itself plays it.\n"
    "non_diegetic_music: a score ONLY if the note asks for one; otherwise "
    "exactly N/A.\n"
    "OUTPUT CONTRACT - verify each point before answering, and rewrite until "
    "every one holds:\n"
    "1. All six sections are present, in the order above, block-shaped. The "
    "ONLY reference tag anywhere is <Picture 1> and the ONLY subject is "
    "<Subject 1>, bound to it in subject_definitions - never name <Picture "
    "2>, <Video> or <Audio>: none are wired.\n"
    # H3_AUDIO_PROMPT's two load-bearing rules live here in this lane (speech
    # inside the window; no unasked score), plus the 9.9 closing beat.
    "2. Spoken words appear exactly once, ONLY as (S1) says: <d>[English] "
    "the exact words</d>, and every spoken line ends explicitly - the next "
    "beat says the lips close and the speaking motion stops. All speech "
    "BEGINS and FINISHES inside the clip, its final word complete before the "
    "last second: speech still running when the clip ends is cut off there, "
    "and the piece that did not fit reappears as a stray syllable over the "
    "opening frames. At most TWO speakers, and no more than two and a half "
    "spoken words per second of clip across both.\n"
    "3. The tempo is stated in positives only - what moves and at what real "
    "speed, never what fails to happen - and non_diegetic_music carries a "
    "score only when the note asked for one.\n"
    "Output only the six sections.")

# The frame-attach and inventory notes name the premise for the VISION path;
# the fl2va ones ("the exact frame this video starts from") would re-import
# the frame-zero premise, so the ref2va lane gets its own pair.
H3_REF2V_LOOK_NOTE = (
    "\nThe attached image is <Picture 1>, the IDENTITY reference for this "
    "render - NOT its first frame. Read from it who the subject is: face, "
    "hair, wardrobe, defining props. The video's scene is new and yours to "
    "stage; never carry the reference's background, composition or lighting "
    "into the brief, and never invent a second reference.")

H3_REF2V_INVENTORY_NOTE = (
    "\nThe FRAME INVENTORY describes <Picture 1>, the identity reference, read "
    "by a vision model that examined it. It is ground truth for WHO the "
    "subject is: face, hair, wardrobe, props. It says nothing about the "
    "video's scene, which is new and yours to stage. Where it disagrees with "
    "the scene caption about the subject, the inventory wins.")


# ------------------------------------------------------------- managed local brain
# The "Local (uncensored)" preset points at :8191. When the chat brain lives there,
# the sidecar owns the llama.cpp server: spawn on first use, respawn on model change.
# A server we did NOT start (run_llm.bat) is respected and used as-is, never killed.

LOCAL_LLM_PORT = 8191
LOCAL_LLM_URL = f"http://127.0.0.1:{LOCAL_LLM_PORT}/v1"
LLM_STATE = HERE / ".local_llm.json"     # {pid, model} of the server WE spawned -
LLM_LOG = HERE / "llama_server.log"      # survives sidecar restarts (adopt, don't strand)

# When the brain was last actually wanted. local_keep used to mean "resident
# forever": the only alternative was local_keep off, which hands the VRAM back
# after EVERY turn and pays a multi-GB reload on the next one. Neither is what
# a person wants - warm while you are talking to it, gone while you are not.
#
# Found the hard way (2026-08-22): a brain spawned at 02:10 was still holding
# 8.4 GB at 04:50 with nothing having asked it anything for hours, because the
# process that spawned it had exited and nothing owned it any more. The VRAM
# butler already evicts before a render (free_brain_vram), so this is purely
# the idle case - and idle is most of the time.
LLM_LAST_USED = 0.0
# Calls currently awaiting the brain. The reaper measures IDLE, and a call
# in flight is the opposite of idle - without this it could kill the brain
# mid-generation, because LLM_LAST_USED is stamped when a call STARTS and
# llm_call's own ceiling (180s) can exceed a local_idle_minutes of 1 or 2,
# which Settings accepts.
LLM_IN_FLIGHT = 0
LLM_IDLE_EVICT_S = 600          # 10 min; cfg llm.local_idle_minutes overrides
LLM_REAP_TICK_S = 60
_PROCESS_START = time.time()    # so an adopted orphan counts as idle from boot

def _llm_state():
    try:
        return json.loads(LLM_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _llm_kill(pid):
    """True when there was actually a process there to kill.

    taskkill exits non-zero for a pid that no longer exists, which is how a
    stale pidfile - the server died, or something outside Pixal killed it -
    gets told apart from a live one. Callers that report to the user need that
    difference; the ones that just want it gone can ignore it. POSIX mirrors
    the same semantics with signals: ESRCH (nothing there) is False, and so is
    EPERM - there, but not ours to kill, which taskkill answers ACCESS DENIED.
    """
    if not pid:
        return False              # no pid is "nothing to kill", on both OSes -
                                  # taskkill /PID None /F only spawned a process
                                  # to be told the same thing
    if _nt():
        done = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        return done.returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError):
        return False

# filename → human name: family + params + variant; the raw file stays in a tooltip
_LLM_FAMS = [("qwen3-vl", "Qwen3"), ("qwen3vl", "Qwen3"), ("qwen3", "Qwen3"),
             ("qwen", "Qwen"), ("gemma-3", "Gemma 3"), ("gemma3", "Gemma 3"),
             ("joycaption", "JoyCaption"), ("z-image", "Z-Image"), ("zimage", "Z-Image"),
             ("deepseek", "DeepSeek"), ("mistral", "Mistral"), ("llama", "Llama")]
_LLM_VARS = [("josiefied", "Josiefied"), ("heretic", "Heretic"), ("hauhau", "HauhauCS"),
             ("huihui", "Huihui"), ("abliterated", "Abliterated"),
             ("uncensored", "Uncensored")]

def _pretty_name(s):
    low = s.lower()
    fam = next((v for k, v in _LLM_FAMS if k in low), "")
    var = next((v for k, v in _LLM_VARS if k in low), "")
    pm = re.search(r"(\d+(?:\.\d+)?)b(?![a-z0-9])", low)
    return {"title": " ".join(x for x in (fam, pm and pm.group(1) + "B", var) if x) or s,
            "nsfw": bool(var) or "nsfw" in low,
            "vision": bool(re.search(r"(?:^|[-_.])vl(?:$|[-_.])|\dvl|llava|joycaption",
                                     low))}

def _pretty_llm(p):
    low = p.stem.lower()
    qm = re.search(r"(iq\d|q\d|bf16|f16|f32)", low)
    try:
        size = f"{p.stat().st_size / 1e9:.1f} GB"
    except OSError:
        size = ""
    d = _pretty_name(p.stem)
    if d["title"] == p.stem:
        d["title"] = p.stem
    return {**d, "quant": qm.group(1).upper() if qm else "", "size_gb": size}

def brain_badge():
    """What is answering, on what, and the two things people ask about a local
    model: can it see, and is it filtered.

    Jesse: "its just so people know what is being used. There could be tags
    for Vision and Uncensored as well." The brain was the one part of the rig
    with no presence in the chat window - the card and its VRAM are on that
    strip, the model doing the talking was not.

    Read straight from config on demand: one file read and one regex, and
    nothing to keep in sync. The vision/nsfw flags come from _pretty_name, the
    same source Settings' brain list badges from, so the chip and that list can
    never disagree.
    """
    cfg = load_config()["llm"]
    # cfg["model"] == "local" is the mode flag; the gguf path lives in
    # local_model (see llm_call).
    if (cfg.get("model") or "") != "local":
        return {"mode": "api", "model": (cfg.get("model") or "").strip() or "not set",
                "device": "", "vision": False, "nsfw": False}
    path = (cfg.get("local_model") or "").strip()
    d = _pretty_name(Path(path).stem) if path else {}
    return {"mode": "local", "model": d.get("title") or "not set",
            # 0 = CPU, -1 = every layer on the card, positive = that many.
            # Anything that is not an explicit 0 is running on the GPU.
            "device": "CPU" if cfg.get("local_gpu_layers") == 0 else "GPU",
            "vision": bool(d.get("vision")), "nsfw": bool(d.get("nsfw"))}


def local_llm_models():
    """Chat-capable GGUFs under every model root (LLM + text_encoders trees).
    mmproj files are vision adapters, not chat models."""
    out = {}
    for root in model_roots():
        for sub in ("LLM", "text_encoders"):
            d = Path(root) / sub
            if not d.is_dir():
                continue
            for p in d.rglob("*.gguf"):
                low = p.name.lower()
                # mmproj = vision adapter; *-encoder (t5/umt5/clip) = render TEs -
                # neither can hold a conversation
                if "mmproj" in low or "encoder" in low:
                    continue
                try:                     # same name+size in two dirs = the same model
                    key = (low, p.stat().st_size)
                except OSError:
                    key = (low, 0)
                out[key] = {"path": str(p), "name": p.name, **_pretty_llm(p)}
    return sorted(out.values(), key=lambda m: (m["title"].lower(), m["quant"]))

async def local_llm_up():
    """HTTP readiness - use ONLY on a fresh spawn (a busy server can't answer)."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(LOCAL_LLM_URL + "/models",
                             timeout=aiohttp.ClientTimeout(total=3)) as r:
                return r.status == 200
    except Exception:
        return False

async def local_llm_port_open():
    """Liveness. A generating llama server holds its global lock and stops
    answering HTTP, but still ACCEPTS connections - probing with HTTP misread
    'busy' as 'down' and spawned a doomed second server into the held port
    (the 10048 crash). TCP connect is the truth."""
    try:
        _r, w = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", LOCAL_LLM_PORT), 2)
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


def _torch_lib_for_python(executable):
    root = Path(executable).parent
    if root.name.lower() == "scripts":       # normal Windows virtualenv
        root = root.parent
    return root / "Lib" / "site-packages" / "torch" / "lib"


def _local_llm_env(executable):
    env = {**os.environ, "KMP_DUPLICATE_LIB_OK": "TRUE"}
    env["PATH"] = str(_torch_lib_for_python(executable)) + os.pathsep + env.get("PATH", "")
    return env


def _llm_python_has_server(executable):
    """True when this interpreter can actually start llama_cpp.server."""
    try:
        probe = subprocess.run(
            [str(executable), "-c", "import llama_cpp.server"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=_local_llm_env(executable))
        return probe.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _posix_python_candidates(comfy_dir):
    """POSIX interpreters worth probing, most-local first. These are the twins
    of the Windows probe shapes: a venv inside or beside the ComfyUI checkout
    stands where python_embeded stands, Pixal's own .venv where
    .venv\\Scripts stands, and the system python3 closes it out. Nothing is
    stat'ed here - existence/import probing is the caller's job."""
    candidates = []
    if comfy_dir:
        candidates += [comfy_dir / ".venv" / "bin" / "python",
                       comfy_dir / "venv" / "bin" / "python",
                       comfy_dir.parent / ".venv" / "bin" / "python"]
    candidates += [HERE / ".venv" / "bin" / "python", Path(sys.executable)]
    system = shutil.which("python3")
    if system:
        candidates.append(Path(system))
    seen, unique = set(), []
    for c in candidates:
        if str(c) not in seen:
            seen.add(str(c))
            unique.append(c)
    return unique


def resolve_local_llm_python(cfg=None):
    """Pick a Python that owns llama_cpp.server; return (path, error)."""
    cfg = cfg or load_config()
    explicit = os.environ.get("PIXAL_LLM_PYTHON", "").strip().strip('"')
    if explicit:
        candidate = Path(os.path.expandvars(explicit)).expanduser().resolve()
        if not candidate.is_file():
            return None, f"PIXAL_LLM_PYTHON does not point to a Python executable: {candidate}"
        if not _llm_python_has_server(candidate):
            return None, ("PIXAL_LLM_PYTHON cannot import llama_cpp.server: "
                          f"{candidate}")
        return str(candidate), None

    current = Path(sys.executable).resolve()
    if current.is_file() and _llm_python_has_server(current):
        return str(current), None

    comfy_dir = resolve_comfy_dir(cfg.get("comfy_root"))
    portable = comfy_dir.parent / "python_embeded" / "python.exe" if comfy_dir else None
    if portable and portable.is_file() and _llm_python_has_server(portable):
        return str(portable), None

    if not _nt():
        for candidate in _posix_python_candidates(comfy_dir):
            if candidate.is_file() and _llm_python_has_server(candidate):
                return str(candidate), None

    return None, ("no Python interpreter with llama_cpp.server was found; set "
                  "PIXAL_LLM_PYTHON or install llama-cpp-python in the Pixal or "
                  "configured ComfyUI portable environment")

_LLM_LOCK = asyncio.Lock()   # one spawn at a time - two racing turns once both
                             # spawned and the loser died on the port bind (10048)
_LLM_TURNS = {"n": 0}        # live turns; release only when the LAST one ends

def _turn_start():
    _LLM_TURNS["n"] += 1

def _turn_end():
    _LLM_TURNS["n"] = max(0, _LLM_TURNS["n"] - 1)
    if _LLM_TURNS["n"] == 0:
        release_local_llm()

def _local_llm_family(model_path):
    """Which multimodal handler family a chat gguf belongs to, or None.

    Filename sniffing on purpose: the gguf metadata names the BASE model, so an
    abliterated/heretic finetune reports upstream's name and tells us nothing
    about which handler its tokens want.
    """
    n = PureWindowsPath(model_path or "").name.lower()
    if "gemma" in n:
        return "gemma"
    if "qwen3" in n and "vl" in n:
        return "qwen3-vl"
    return None


def _local_llm_mmproj(model_path):
    """The vision projector that lets the managed brain see. Discovery, not a
    setting: an *mmproj*.gguf dropped in the chat model's own folder turns
    vision on at the next (re)spawn. Largest candidate wins (f16 beats Q8_0 on
    a 854MB file; VRAM is not the constraint here, the 12B is).

    Gemma and Qwen3-VL. Gemma was the only family for a while because it was
    the only one llama-cpp-python's server could actually dispatch; Qwen3-VL
    joined on 2026-08-18 once pixal_brain_server.py started routing it, which
    matters because the shipped chat brain IS a Qwen3-VL and had been blind
    since it landed - its own repo publishes no mmproj at all.
    """
    p = Path(model_path or "")
    if not _local_llm_family(model_path) or not p.is_file():
        return None
    cands = sorted(p.parent.glob("*mmproj*.gguf"),
                   key=lambda c: c.stat().st_size, reverse=True)
    return str(cands[0]) if cands else None


async def ensure_local_llm(cid=None):
    """No-op unless the chat brain points at the managed port. Returns an error
    string (the honest kind, for the lane) or None when the server is ready.
    State lives in a pidfile so a restarted sidecar ADOPTS its old server instead
    of stranding it (a stranded orphan once served the WRONG model as 'external')."""
    async with _LLM_LOCK:
        return await _ensure_local_llm(cid)

# A 64x64 red square. Small enough that the probe costs a fraction of a second
# and cannot be answered correctly by guessing the way "describe this" could.
_VISION_PROBE_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAUElEQVR42u3PQREAAAQAMATRP5Qw"
    "Uni42xospzs+q3hOQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBA"
    "4N4CCJ0BmOb2hBcAAAAASUVORK5CYII=")


async def _vision_smoke_test():
    """Can the brain we just spawned actually SEE? Returns True/False.

    Worth the half second because the failure it catches is silent. Handing a
    Qwen3-VL gguf to the wrong multimodal handler does not crash: the image
    encodes, the position stream comes out wrong, and the model returns an
    EMPTY string (measured 2026-08-18 with the 2.5 handler). A blind brain that
    still answers is far more damaging than one that refuses to start, because
    every reference the user attaches from then on is quietly invented.
    """
    body = {"model": "local", "max_tokens": 8, "temperature": 0.0,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + _VISION_PROBE_PNG}},
                {"type": "text", "text": "What colour is this image? One word."}]}]}
    try:
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                    f"http://127.0.0.1:{LOCAL_LLM_PORT}/v1/chat/completions",
                    json=body) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        return "red" in str(text or "").strip().lower()
    except Exception as exc:
        print(f"[pixal] vision probe failed: {exc}", flush=True)
        return False


async def _ensure_local_llm(cid=None):
    global LLM_LAST_USED
    LLM_LAST_USED = time.time()      # every local-brain use passes through here
    full_cfg = load_config()
    cfg = full_cfg["llm"]
    if f"127.0.0.1:{LOCAL_LLM_PORT}" not in cfg["base_url"]:
        return None
    want = (cfg.get("local_model") or "").strip()
    gpu_layers = cfg.get("local_gpu_layers", -1)
    up = await local_llm_port_open()     # TCP, not HTTP - busy is NOT down
    st = _llm_state()
    if not want:
        if up:
            return None              # externally-started server is fine to use
        return "pick a local chat model in settings first"
    if not Path(want).is_file():
        return f"local model file is gone: {Path(want).name}"
    if up and not st:
        return None                  # truly external (run_llm.bat) - use as-is, never kill
    mmproj = _local_llm_mmproj(want)
    # A demoted-blind server keeps "mmproj": None on purpose (every vision
    # gate reads it) and records the projector it lost as blind_mmproj - the
    # reuse check has to accept that fact too, or None never matches the path
    # still on disk and every chat turn killed a healthy server to reload a
    # multi-GB GGUF.
    if up and st.get("model") == want and st.get("gpu_layers") == gpu_layers \
            and (st.get("mmproj") == mmproj
                 or st.get("blind_mmproj") == mmproj):
        return None                  # ours, right model/eyes/card split

    llm_python, python_error = resolve_local_llm_python(full_cfg)
    if python_error:
        return python_error

    if up:
        _llm_kill(st.get("pid"))     # ours, wrong model - replace
        for _ in range(20):          # wait for the PORT to actually free
            if not await local_llm_port_open():
                break
            await asyncio.sleep(0.5)
    LLM_STATE.unlink(missing_ok=True)
    name = brain_display_name(want, mmproj)
    if cid:
        HUB.broadcast(type="thinking", cid=cid, note=f"waking the local brain - {name}")
    # ggml-cuda.dll needs the CUDA runtime (cudart/cublas) at load time or
    # llama.cpp SILENTLY falls back to CPU (the "super slow" chat). torch ships
    # them - put its lib dir on the server's PATH.
    env = _local_llm_env(llm_python)
    log = open(LLM_LOG, "ab")
    # pixal_brain_server.py, not -m llama_cpp.server: the shipped Qwen3-VL brain
    # has no reachable dispatch in the wheel we install (the handler exists and
    # nothing routes to it), and borrowing the 2.5 handler returns EMPTY replies
    # rather than failing loudly. The wrapper picks the handler from the model
    # family and sets --chat_format itself, so the projector is all we pass.
    args = [llm_python, str(HERE / "pixal_brain_server.py"), "--model", want,
            "--n_gpu_layers", str(gpu_layers), "--n_ctx", "16384",
            "--host", "127.0.0.1", "--port", str(LOCAL_LLM_PORT)]
    if mmproj:
        args += ["--clip_model_path", mmproj]
    try:
        proc = subprocess.Popen(
            args, env=env, stdout=log, stderr=log,
            # getattr, not a bare 0x08000000: any nonzero creationflags raises
            # ValueError on POSIX, and this spawn runs there too.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        # The child received its own handle at spawn, so the parent's copy is
        # pure leak from here on - and on Windows it keeps llama_server.log
        # undeletable while Pixal runs. Close it whether or not Popen raised.
        log.close()
    LLM_STATE.write_text(json.dumps({"pid": proc.pid, "model": want,
                                     "mmproj": mmproj,
                                     "gpu_layers": gpu_layers}),
                         encoding="utf-8")
    for _ in range(60):                                    # big ggufs load slow
        if proc.poll() is not None:
            LLM_STATE.unlink(missing_ok=True)
            return (f"the local brain crashed loading {name} - "
                    "inspect llama_server.log")
        if await local_llm_up():
            if mmproj and not await _vision_smoke_test():
                # Up, answering, and blind. Demote to text-only rather than let
                # the lane keep promising eyes: _delocalize and has_vision_refs
                # both read mmproj off this state, so clearing it here is what
                # makes attached references flatten honestly instead of being
                # described from imagination. mmproj must stay None for them;
                # the projector it lost rides as blind_mmproj, its own fact,
                # so the reuse check above can still recognize this server.
                print("[pixal] local brain came up BLIND - vision disabled for "
                      "this session (see llama_server.log)", flush=True)
                LLM_STATE.write_text(json.dumps({"pid": proc.pid, "model": want,
                                                 "mmproj": None,
                                                 "blind_mmproj": mmproj,
                                                 "gpu_layers": gpu_layers}),
                                     encoding="utf-8")
                if cid:
                    HUB.broadcast(type="thinking", cid=cid,
                                  note="the local brain started without vision - "
                                       "attached images will not be read")
            return None
        await asyncio.sleep(2)
    return f"the local brain didn't come up with {name} (2 min timeout)"

async def brain_idle_reaper():
    """Hand the card back when nobody is talking to the brain.

    Only ever touches a process our own pidfile claims, so an externally
    started llama server (run_llm.bat) is never disturbed. Eviction is free to
    be wrong in the cheap direction: the next chat turn starts a fresh one.
    """
    while True:
        await asyncio.sleep(LLM_REAP_TICK_S)
        try:
            cfg = load_config()["llm"]
            if not cfg.get("local_keep", True):
                continue            # release_local_llm already drops it per turn
            mins = cfg.get("local_idle_minutes")
            if isinstance(mins, bool) or not isinstance(mins, (int, float)):
                idle_after = LLM_IDLE_EVICT_S      # unset or junk - use the default
            elif mins <= 0:
                continue                           # 0 is a real choice: never reap
            else:
                idle_after = float(mins) * 60
            if not _llm_state().get("pid"):
                continue            # nothing of ours is up
            if LLM_IN_FLIGHT:
                continue            # somebody IS talking to it - that is not idle
            # LLM_LAST_USED is 0 for a brain this process never used - an
            # orphan adopted across a sidecar restart. Those are exactly the
            # ones worth reaping, so treat unknown as "idle since boot".
            since = time.time() - (LLM_LAST_USED or _PROCESS_START)
            if since < idle_after:
                continue
            if await free_brain_vram():
                print(f"[pixal] brain idle {int(since)}s - VRAM handed back",
                      flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[pixal] brain reaper: {exc}", flush=True)


def release_local_llm():
    """local_keep off = hand the VRAM back at the end of every turn. Only ever
    touches a server WE spawned (pidfile) - external ones are left alone.

    Drops the pidfile only when the kill actually landed, for the reason
    free_brain_vram documents at length: a pidfile deleted off a brain that
    is still alive DISOWNS it, and _ensure_local_llm then reads the still
    listening server as externally started and never respawns it - which
    turns the vision gate off permanently. This path runs at the END OF
    EVERY TURN when keep is off, so it strands one far sooner than the
    butler does. It is synchronous, so the kill's own answer is the arbiter
    here rather than a port probe; a genuinely stale pidfile that survives
    costs nothing, because the next call finds the port shut and respawns.
    """
    if load_config()["llm"].get("local_keep", True):
        return
    st = _llm_state()
    if st.get("pid") and _llm_kill(st["pid"]):
        LLM_STATE.unlink(missing_ok=True)

_TOOLCALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)
_HISTORY_DIRECTIVE_RE = re.compile(
    # CINEMATIC/STYLE ride the turn as craft direction OUTSIDE the composer
    # block, so they were missed here - history hygiene has to strip the same
    # set the turn-level splits and the verbatim gate know about.
    # The composer/craft blocks are single-line server templates, so a greedy
    # [^\n]* is right for them: .*? stopped at the FIRST ] and a loras=
    # [a:0.8, b:1.0] list left ", aspect='1:1']" behind in stored history.
    # COMPOSER comes in two punctuations - the local writer's "[COMPOSER: "
    # and the big brain's "[COMPOSER HARD CONSTRAINTS - " - and the second is
    # the one that actually carries the loras list. CHARACTER keeps the
    # cross-line match: its look/notes text really can span lines.
    #
    # PRIOR RENDER left that group on 2026-08-23. It embeds a verbatim scene,
    # but BOTH emitters collapse it first (" ".join(scene.split()) in
    # prior_render_directive and last_render_directive), so the block is
    # always one line - and .*? was losing to the same "stops at the FIRST ]"
    # trap the COMPOSER branch above already documents. A scene containing a
    # bracket cut the match short and left the whole tail of the block behind
    # ('..." If this message asks to CHANGE that image, call generate() ...]'),
    # which then reads to the brain as if the user had typed it. Demonstrated
    # against the real thing: entry 079b9083's scene WAS a bracketed block.
    # ATTACHED IMAGES joined 2026-08-23: it was added with the local brain's
    # vision refs and never added here, so it was the ONE block that survived
    # an echo - it reached the lane as prose and the sampler as the prompt
    # ("[ATTACHED IMAGES: the FIRST is the person..." rendered as a scene).
    # Single-line server template with no internal ], so the same rule holds.
    r"(?:\n\s*)?\[COMPOSER(?: HARD CONSTRAINTS)?(?::| - )[^\n]*\]"
    r"|(?:\n\s*)?\[(?:CINEMATIC|STYLE|ATTACHED IMAGES):[^\n]*\]"
    # PERSON REFERENCE is the API brain's half of ATTACHED IMAGES - same job,
    # same turn, emitted by the non-local arm of build_directive - and it was
    # missing here for the same reason. It punctuates with " - ", not ":".
    r"|(?:\n\s*)?\[PERSON REFERENCE -[^\n]*\]"
    # CHARACTER cannot use the single-line rule - look/notes carry a newline
    # by construction - so it keeps .*?, and .*? stops at the FIRST ]. A look
    # of "wet-street neon [teal and magenta]" therefore stranded the server's
    # own closing sentence in history, where it reads as the user's words and
    # contradicts them ("Never describe her face..." attributed to Jesse).
    # First branch: stop only at a ] that ENDS the block - one followed by the
    # next bracket block or by end of turn. Second branch is the old behaviour,
    # kept as the fallback for a block echoed back mid-sentence, where no
    # terminator satisfies the lookahead and a partial strip still beats none.
    r"|(?:\n\s*)?\[CHARACTER(?: ANCHOR)?:.*?\](?=\s*(?:\n\s*\[|$))"
    r"|(?:\n\s*)?\[CHARACTER(?: ANCHOR)?:.*?\]"
    r"|(?:\n\s*)?\[PRIOR RENDER #[0-9a-f]+ -[^\n]*\]",
    re.S,
)
_LOCAL_ITERATION_RE = re.compile(
    r"\b(?:iterate|iteration|again|same|reroll|re-roll)\b|#[a-z0-9_-]{4,}", re.I)


def _strip_history_directives(content):
    """Remove server-added composer/character blocks from an old user turn.

    Work on copied content only: the persisted conversation and visible lane are
    the record, while the local brain gets a deliberately smaller context view.
    """
    if isinstance(content, str):
        return _HISTORY_DIRECTIVE_RE.sub("", content).strip()
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and \
                    isinstance(part.get("text"), str):
                part["text"] = _HISTORY_DIRECTIVE_RE.sub("", part["text"]).strip()
    return content


_SCENE_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.S)
_SCENE_CONFIG_LINE_RE = None  # built lazily: PUBLIC_RECIPE_IDS lives below


def _scene_from_prose(text):
    """A prose brain that failed to call generate sometimes roleplays the tool
    instead: a line of chat, then a markdown fence holding a fake settings
    header ('realism / realism_ii', 'standing=false', 'seed=12345') and the
    scene - and all of it shipped to the sampler verbatim (job b2cafaef,
    Gemma swap-in). The fenced block IS the scene; config-shaped lines are
    the settings it should have passed as tool arguments."""
    global _SCENE_CONFIG_LINE_RE
    if _SCENE_CONFIG_LINE_RE is None:
        ids = "|".join(re.escape(i) for i in PUBLIC_RECIPE_IDS)
        _SCENE_CONFIG_LINE_RE = re.compile(
            rf"^(?:(?:template|seed|standing|nsfw|count)\s*[=:][^\n]*"
            rf"|(?:{ids})(?:\s*/\s*(?:{ids}))*)\s*$\n?", re.I | re.M)
    fences = _SCENE_FENCE_RE.findall(text or "")
    if fences:
        text = max(fences, key=len)
    text = _SCENE_CONFIG_LINE_RE.sub("", text or "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


REALISM_CAPTION = "Rich saturated colour."
# RETIRED 2026-08-11 at the user's call: the closing caption is out of both
# contracts, and the scrubber now removes it on EVERY recipe. It used to be
# kept on the realism finetunes it was written for, but the sentence tail-ended
# every card in the lane and read as boilerplate. Brains that learned it from
# conversation history (or a resumed chat whose old turns still carry it) will
# keep emitting it for a while - hence the scrub stays, gate removed.
_REALISM_CAPTION_RE = re.compile(
    r"(?:^|(?<=[\s]))rich,?\s+saturated\s+colou?rs?\s*[.!]*\s*$", re.I)


def scrub_style_caption(scene, template):
    """The retired house caption is removed wherever a brain still writes it."""
    return _REALISM_CAPTION_RE.sub("", str(scene or "")).rstrip()


# A brain told about a prior seed sometimes writes it INTO the scene it sends
# ("...raw, real, and fucking dazzling. Seed = 4217389056" - job 5c2a717d).
# The text encoder then conditions on the number, shifting the very
# composition the seed was passed to hold. _scene_from_prose only catches
# seed= on its own header line; this catches the sentence form everywhere.
_SEED_PROSE_RE = re.compile(r"[\s.,;:(\[-]*\bseed\s*[=:]\s*\d{4,}\b[\s.)\]]*", re.I)


def strip_seed_prose(scene):
    return _SEED_PROSE_RE.sub(" ", str(scene or "")).strip()


def _norm_scene(scene):
    """Scene equality for the same-seed guard, compared at the WORD level:
    seed prose, punctuation, case and whitespace are presentation - a real
    user change always changes words, and the seed scrubber eats punctuation
    beside the number, so comparing it would let a verbatim copy through."""
    return " ".join(re.sub(r"[^\w\s]", " ", strip_seed_prose(scene).lower()).split())


_ASK_WRAP_RE = re.compile(
    r"^\s*(?:hey|hi|ok(?:ay)?|so|now|and|also|pixal)[,\s]+"
    r"|^\s*(?:can|could|would|will)\s+you\s+(?:please\s+)?"
    r"|^\s*please\s+", re.I)


def _change_sentence(ask):
    """The user's tweak, rewritten as one appendable scene sentence.

    The deterministic repair for a small brain that copies the prior scene
    verbatim: Qwen3-VL-4B resent the identical generate() call for all 8
    rounds straight past the corrective tool error ("make her blonde",
    2026-08-13) - the brief-harness lesson again, feedback doesn't fix a
    small model, mechanical repair does. Empty when the ask is too long to
    be a small change."""
    s = " ".join(str(ask or "").split())
    prev = None
    while s != prev:
        prev = s
        s = _ASK_WRAP_RE.sub("", s)
    s = s.strip(" ?!.")
    if not s or len(s.split()) > 24:
        return ""
    return s[0].upper() + s[1:] + "."


RECIPE_NOTE = {
    "identity_edit": "her identity", "zara_edit": "her identity",
    "realism": "a photographic frame", "realism_ii": "a photographic frame",
    "qwen_image": "a photographic frame", "qwen_edit": "the edit",
    "zimage": "the frame", "anime": "an anime frame", "fantasy": "a fantasy frame",
}


MODEL_FAMILY_NOTE = {"krea2": "Krea 2", "zimage": "Z-Image", "flux": "Flux",
                     "qwen_edit": "Qwen Image Edit", "qwen_image": "Qwen-Image"}


def render_note(template, args, count=1):
    """Say what is actually being rendered, and that it is not instant.

    "queued on comfy - sampling soon" named neither the recipe nor the model,
    which is exactly what the user wants confirmed before waiting on a GPU.
    """
    what = RECIPE_NOTE.get(template, template)
    model = str(args.get("model") or "")
    label = ""
    if model:
        try:
            label = MODEL_FAMILY_NOTE.get(model_profile(model).get("family"), "")
        except Exception:
            label = ""                       # never let a label break a render
        if label and "turbo" in model.lower():
            label += " Turbo"
    # No count here: the job card already carries it, and "2 frames of a
    # photographic frame" reads worse than saying nothing.
    tail = f" with {label}" if label else ""
    return f"rendering {what}{tail} - this takes a moment"


_AFFIRMATIVE = re.compile(
    r"^(?:yes|yep|yeah|yup|ya|ok|okay|k|sure|please|do it|go|go ahead|send it|"
    r"run it|that one|perfect|love it|nice|great|shoe me|sh?o?w\s*me|show it|"
    r"render|render it|make it|let'?s go|hit it|sounds\s+good|ready)"
    r"\b[\s!.?]*$", re.I)

# --------------------------------------------------------------------------- #
# the scene gate
# --------------------------------------------------------------------------- #
# Recipes whose `scene` really is a written prompt bound for a CLIPTextEncode.
# The others carry a different payload and must NOT be judged by prose rules:
# qwen_edit takes an edit INSTRUCTION (where "make her jacket red" is a
# perfectly good whole prompt), the i2v recipes take a motion brief, and
# upscale/review carry no author's words at all.
PROSE_TEMPLATES = frozenset({
    "realism", "realism_ii", "fantasy", "anime", "zimage", "anima",
    "identity_edit", "zara_edit", "qwen_image", "face_mint", "klein_inpaint"})

# Server-side machinery that must never reach a text encoder. The brackets are
# blocks this server itself appends to user turns; the rest is a model printing
# its tool call as prose instead of calling it.
# ATTACHED IMAGES, PERSON REFERENCE and bare CHARACTER were missing until
# 2026-08-23, which is how a leaked brief reached the sampler as a whole
# prompt (ledger 079b9083): the scrubber above did not know the block and
# this gate - the one that exists to catch exactly that - did not either.
# Two hand-kept lists, both a step behind the emitters. "CHARACTER" also
# covers "CHARACTER ANCHOR" by prefix, so the longer name is redundant now.
_MACHINERY_RE = re.compile(
    r"\[(?:COMPOSER|CHARACTER|PRIOR RENDER|SYSTEM|NOTE\s*-\s*THIS TURN|CINEMATIC"
    r"|STYLE|ATTACHED IMAGES|PERSON REFERENCE)"
    r"|</?tool_call>|\"name\"\s*:\s*\"(?:generate|animate|upscale|review)\"", re.I)
# A label a small model prints in front of the scene because the recipe brief
# told it to "write EDIT instructions" - it reads that as a heading.
_SCENE_LABEL_RE = re.compile(r"^\s*(?:EDIT|SCENE|PROMPT|OUTPUT|RESULT)\s*[:\-]\s*", re.I)


# What may trail a render verb while the turn still names NOTHING to look at:
# pronouns pointing back at something already written, bare articles, and
# politeness. Deliberately NOT _FORMAT_WORDS - that set exists for ask_is_open
# and counts "portrait", "photo" and "scene" as non-describing, which is right
# when asking "did they describe anything" and wrong here: "shoot a portrait"
# names a picture to make, where "render it" only points at one.
_ACCEPT_REMAINDER = frozenset(
    "it that this one them those these me us my mine "
    "a an the some any of to for "
    "now please then again already too also yes yeah yep ok okay sure "
    "go ahead thanks".split())


def scene_is_command(text):
    """True when a turn is only an instruction to render, carrying no scene.

    "generate", "show me", "render it" - the words a person says to ACCEPT a
    prompt they already typed. Rendering them AS the prompt is the 2026-08-18
    incident where the card came back reading "generate" (chat 629d1c68).

    The test is what SURVIVES the render verb, not how short the turn is: a
    word cap of three refused "draw a cat", which is a perfectly good prompt.
    "render it" leaves nothing that names a picture; "draw a cat" leaves a cat.
    """
    body = " ".join(str(text or "").split()).strip(" .!?")
    if not body:
        return True
    if _AFFIRMATIVE.match(body):
        return True
    opener = _EXPLICIT_RENDER_REQUEST.match(body)
    if not opener:
        return False
    rest = body[opener.end():]
    return not [w for w in re.split(r"\W+", rest.lower())
                if w and w not in _ACCEPT_REMAINDER]


def scene_gate(template, scene, verbatim=False):
    """Canonicalize a scene and refuse the shapes that are not one.

    ONE gate, at the only chokepoint every render passes, because the scrubbers
    this replaces guarded 2 of the 11 HUB.submit call sites - and not the one
    that mattered most. /api/reroll resubmits a stored scene verbatim, so a
    contaminated ledger entry re-rendered its contamination AND wrote a fresh
    contaminated entry: contagion, not a one-off. Four such entries are in the
    dev history.jsonl, including one whose whole scene is a raw JSON tool call
    (7fa6b489) and one ending ". . Seed = 4217389056" (5c2a717d).

    `verbatim` is the Prompt-enhance-off promise: the user's own words go to the
    encoder untouched, so nothing is rewritten - but a scene that is machinery
    or a bare command is still refused, because those are never what they typed.

    Returns (scene, error_or_None).
    """
    if template not in PROSE_TEMPLATES:
        return scene, None
    text = str(scene or "")
    if not verbatim:
        text = _SCENE_LABEL_RE.sub("", text)
        text = _scene_from_prose(text)              # fences + config-shaped lines
        text = _strip_history_directives(text)      # [COMPOSER ...] and friends
        text = scrub_style_caption(text, template)
        text = strip_seed_prose(text)
    text = text.strip()
    if not text:
        return text, "empty scene - nothing to render"
    if _MACHINERY_RE.search(text):
        return text, ("that scene is server machinery or a printed tool call, not a "
                      "prompt - say what you want to see and I'll render it")
    if scene_is_command(text):
        return text, (f"\"{text}\" is an instruction to render, not something to "
                      f"render - tell me what the picture is")
    return text, None




def _pending_scene(convo):
    """True when the newest assistant turn is a written scene awaiting a go.

    The local writer routinely prints the finished scene as chat instead of
    calling generate. When it does, a short "yes" / "go" / "shoe me" is the user
    ACCEPTING that scene, not opening a new conversational turn - and the intent
    classifier, which only sees the user's words, reads those as chat. Without
    this the user re-asks two or three times and the model rewrites the scene
    every round (observed: "shoe me?" then "show me!" before anything queued).
    """
    for message in reversed(convo):
        role = message.get("role")
        if role == "assistant":
            if message.get("tool_calls"):
                return False          # it already acted; nothing is pending
            return len(str(message.get("content") or "").split()) >= 30
        if role == "user":
            return False              # an unanswered user turn, not a proposal
    return False


def _pending_question(convo):
    """True when the newest assistant turn asked the user a question without
    acting. The user's answer is the second half of a render request the
    intent classifier can't see on its own: after "What kind of fun is she
    having?", the reply "surfing at sunset" reads as chat, the generate tool
    gets WITHHELD, and the brain literally cannot render - the user has to
    say "show me" again every time (Jesse, 2026-08-13). Granting the tool on
    the answer turn doesn't force a render; TURN_POLICY still lets the model
    keep shaping when the answer truly needs it."""
    for message in reversed(convo):
        role = message.get("role")
        if role == "assistant":
            if message.get("tool_calls"):
                return False          # it already acted; nothing is pending
            return str(message.get("content") or "").strip().endswith("?")
        if role == "user":
            return False              # an unanswered user turn, not a question
    return False


def _generate_calls(message):
    return [call for call in (message.get("tool_calls") or [])
            if (call.get("function") or {}).get("name") == "generate"]


def local_history_view(messages, current_user_index, preserve_latest_render=False):
    """Context view for the local prompt writer, without old render echo.

    A completed render otherwise appears three times in history: assistant tool
    arguments, the tool receipt (which repeats ``scene``), and the final rendered
    prose. Repeating every old composition turns an early setting into an
    autoregressive default. Fresh asks retain ordinary chat but omit those old
    generate chains. Explicit iteration keeps only the newest prior chain.

    Messages at and after ``current_user_index`` are the live turn and are never
    filtered, so the current generate/tool pairing remains valid on later rounds.
    """
    copied = copy.deepcopy(messages)
    prior = copied[:current_user_index]
    current = copied[current_user_index:]
    render_indices = [i for i, message in enumerate(prior)
                      if message.get("role") == "assistant" and
                      _generate_calls(message)]
    keep_render = render_indices[-1] if preserve_latest_render and render_indices else None
    keep_user = None
    if keep_render is not None:
        keep_user = next((i for i in range(keep_render - 1, -1, -1)
                          if prior[i].get("role") == "user"), None)

    out, dropped_call_ids = [], set()
    drop_followup = False
    for i, message in enumerate(prior):
        role = message.get("role")
        if role == "user":
            drop_followup = False
            if i != keep_user:
                message["content"] = _strip_history_directives(message.get("content"))
            out.append(message)
            continue

        calls = _generate_calls(message) if role == "assistant" else []
        if calls and i != keep_render:
            ids = {call.get("id") for call in calls if call.get("id")}
            dropped_call_ids.update(ids)
            remaining = [call for call in (message.get("tool_calls") or [])
                         if call not in calls]
            if remaining or message.get("content"):
                message["tool_calls"] = remaining
                out.append(message)
            drop_followup = True
            continue

        if role == "tool" and message.get("tool_call_id") in dropped_call_ids:
            continue

        # The assistant response immediately following a completed generate
        # receipt is render confirmation/prose, not ordinary conversation.
        if role == "assistant" and drop_followup and not message.get("tool_calls"):
            drop_followup = False
            continue

        out.append(message)
    return out + current

_BARE_TOOLJSON_START_RE = re.compile(r'\{\s*"name"\s*:')


def _bare_tool_calls(content):
    """Tag-less tool JSON repair. Gemma obeyed everything about the tool
    contract except the tags: it emitted the bare {"name": ..., "arguments":
    {...}} object, so no call was parsed, the prose fallback fired, and the
    JSON blob shipped to the lane as chat AND to the sampler as the scene
    (2026-08-12). Parse every such object out of the text; byte-identical
    repeats collapse to one call. Returns (dicts, spans-to-strip)."""
    dec = json.JSONDecoder()
    calls, spans, seen = [], [], set()
    pos = 0
    while True:
        m = _BARE_TOOLJSON_START_RE.search(content, pos)
        if not m:
            return calls, spans
        try:
            d, length = dec.raw_decode(content[m.start():])
        except json.JSONDecodeError:
            pos = m.start() + 1
            continue
        pos = m.start() + length
        if not (isinstance(d, dict) and isinstance(d.get("name"), str)
                and isinstance(d.get("arguments"), dict)):
            continue
        spans.append((m.start(), pos))
        key = json.dumps(d, sort_keys=True)
        if key not in seen:
            seen.add(key)
            calls.append(d)


def _localize(msg):
    """Local GGUF servers (llama.cpp w/ Qwen's embedded template) emit tool calls
    as <tool_call>{json}</tool_call> INSIDE content and leak <think> blocks -
    and Gemma sometimes drops the tags entirely, leaving bare tool JSON in the
    text. Normalize all of it to the OpenAI shape kimi_reply expects. No-op on
    cloud replies."""
    content = msg.get("content")
    if not isinstance(content, str):
        return msg
    stripped = _THINK_RE.sub("", content)
    calls = msg.get("tool_calls") or []
    had = len(calls)
    for i, m in enumerate(_TOOLCALL_RE.finditer(stripped)):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        calls.append({"id": f"local_{i}", "type": "function",
                      "function": {"name": d.get("name", ""),
                                   "arguments": json.dumps(d.get("arguments") or {})}})
    stripped = _TOOLCALL_RE.sub("", stripped)
    if len(calls) == had:            # no tagged calls - try the tag-less repair
        bare, spans = _bare_tool_calls(stripped)
        for i, d in enumerate(bare):
            calls.append({"id": f"local_{had + i}", "type": "function",
                          "function": {"name": d.get("name", ""),
                                       "arguments": json.dumps(
                                           d.get("arguments") or {})}})
        for s, e in reversed(spans):
            stripped = stripped[:s] + stripped[e:]
        if spans:                    # a fence that held only the JSON is litter
            stripped = re.sub(r"```[a-zA-Z]*", "", stripped)
    if stripped == content and len(calls) == had:
        return msg                   # true no-op (cloud replies land here)
    msg["content"] = stripped.strip() or None
    if calls:
        msg["tool_calls"] = calls
    return msg

def _delocalize(messages, vision=False):
    """OpenAI structured tool turns -> Qwen text format for the local server.
    llama-cpp-python's request schema rejects structured assistant tool_calls
    (requires 'name', mistypes the list), so we hand the model back exactly the
    <tool_call> text it emitted - which is also what its template was trained on.
    vision=True (managed brain running with an mmproj): image parts survive as
    content-part lists for the multimodal chat handler instead of flattening."""
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list) and vision and m.get("role") != "assistant":
            out.append({**m, "content": content})
            continue
        if isinstance(content, list):
            # OpenAI content-parts (refs ride as image_url) - llama.cpp's template
            # calls .startswith on content and 500s on a list. Flatten to text;
            # image parts become a placeholder (no mmproj wired = no local vision).
            content = "\n".join(
                (p.get("text") or "") if p.get("type") == "text" else "[attached image]"
                for p in content).strip()
        if m.get("role") != "assistant":
            out.append({**m, "content": content})
            continue
        parts = [content] if content else []
        for c in m.get("tool_calls") or []:
            fn = c.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            parts.append("<tool_call>\n" + json.dumps(
                {"name": fn.get("name"), "arguments": args}, ensure_ascii=False)
                + "\n</tool_call>")
        # rebuilt clean: the schema REQUIRES a name key on assistant messages
        # (missing = validation 500) and may not know extra provider fields
        out.append({"role": "assistant", "content": "\n".join(parts), "name": None})
    return out

def _inline_tools(messages, tools):
    """Gemma's chat template has no tools section, so a structured `tools`
    payload renders into the prompt as NOTHING - the model never sees its
    contract. Inline the definitions into the system text and teach the Qwen
    <tool_call> markup, which _localize already parses back into OpenAI
    tool_calls; the rest of the chat loop never knows the difference."""
    defs = "\n".join(json.dumps(t.get("function", t), ensure_ascii=False)
                     for t in tools)
    note = (
        "\n\n# Tools\n\n"
        "You may call one of the functions below when the turn calls for it. "
        "Function signatures, one JSON object per line:\n"
        f"<tools>\n{defs}\n</tools>\n\n"
        "To call a function, reply with exactly this block (real JSON on the "
        "middle line, nothing outside the tags):\n"
        '<tool_call>\n{"name": "<function-name>", "arguments": '
        "{<args-json-object>}}\n</tool_call>\n"
        "For plain conversation, reply normally with no tool_call block.\n\n"
        # Measured on Gemma-3-12B (2026-08-12): without this closing contract
        # it rendered 0/6 asks as tool calls - it counter-interrogated or
        # roleplayed the tool as fenced prose with a fake settings header.
        # With it: 6/6. Small models keep end-of-prompt rules, not mid-prompt.
        "RENDER MECHANICS - the ONLY way to render: when the user wants an "
        "image, your ENTIRE reply is one <tool_call> block, nothing before or "
        "after it. Never write the scene as prose, never use markdown, never "
        "use ``` fences, never write settings like template or seed as text - "
        "settings exist only as JSON fields inside the tool_call arguments. "
        # "I keep having to say show me again" (2026-08-13): one question per
        # idea, and an answered question means render NOW.
        "You get at most ONE clarifying question per idea; if you already "
        "asked one and the user has answered, your reply is the tool_call - "
        "never a second question.")
    out = [dict(m) for m in messages]
    if out and out[0].get("role") == "system":
        out[0]["content"] = (out[0].get("content") or "") + note
    else:
        out.insert(0, {"role": "system", "content": note.strip()})
    return out

def _flatten_roles(messages):
    """Gemma's embedded template raise_exception()s on anything but an
    optional leading system followed by strictly alternating user/assistant
    turns - the bake-off's [system, user] worked, but the chat lane's tool
    receipts and mid-stream [SYSTEM:]/critic notes 500 with 'Conversation
    roles must alternate user/assistant/...'. Fold everything nonconforming
    into that shape. (Qwen's own template does the same tool->user folding
    internally, so this shim only runs where it's load-bearing.)"""
    out = []
    for m in messages:
        role, content = m.get("role"), m.get("content") or ""
        if role == "system" and not out:
            out.append({"role": "system", "content": content})
            continue
        if role == "tool":
            role = "user"
            content = f"<tool_response>\n{content}\n</tool_response>"
        elif role == "system":
            role = "user"
        prev = out[-1] if out else None
        if prev and prev["role"] == role:
            a, b = prev["content"], content
            if isinstance(a, list) or isinstance(b, list):
                # a vision turn merging with a text turn: join as content parts
                pa = a if isinstance(a, list) else \
                    [{"type": "text", "text": a}] if a else []
                pb = b if isinstance(b, list) else \
                    [{"type": "text", "text": b}] if b else []
                prev["content"] = pa + pb
            else:
                prev["content"] = (a + "\n\n" + b).strip()
            continue
        if role == "assistant" and (not prev or prev["role"] == "system"):
            out.append({"role": "user", "content": "[conversation resumes]"})
        if role == "assistant":
            # llama-cpp-python's schema 500s on assistant messages missing name
            out.append({"role": role, "content": content, "name": None})
        else:
            out.append({"role": role, "content": content})
    return out

async def llm_call(messages, timeout=180, tools=None, cid=None):
    err = await ensure_local_llm(cid)
    if err:
        return 0, {"error": err}
    cfg = load_config()["llm"]
    if f"127.0.0.1:{LOCAL_LLM_PORT}" in cfg["base_url"]:
        # only a server WE spawned with an mmproj can see; an external server
        # gets the safe flatten (a list content 500s a text-only template)
        messages = _delocalize(messages, vision=bool(_llm_state().get("mmproj")))
        # the gguf path lives in local_model; cfg["model"] is just "local"
        if "gemma" in os.path.basename(cfg.get("local_model") or "").lower():
            if tools:
                messages = _inline_tools(messages, tools)
                tools = None
            messages = _flatten_roles(messages)
    payload = {"model": cfg["model"], "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    global LLM_IN_FLIGHT, LLM_LAST_USED
    LLM_IN_FLIGHT += 1
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(cfg["base_url"].rstrip("/") + "/chat/completions",
                              json=payload, timeout=timeout,
                              headers={"Authorization": "Bearer " + cfg["api_key"],
                                       "Content-Type": "application/json"}) as r:
                status, data = r.status, await r.json()
    finally:
        # In `finally` so a timeout, a 500 or a cancelled turn cannot strand the
        # count above zero - a stranded count disables the reaper for the life
        # of the process, which is the failure the reaper exists to prevent.
        LLM_IN_FLIGHT -= 1
        LLM_LAST_USED = time.time()   # idle is measured from the END of a call
    if status == 200 and data.get("choices"):
        _localize(data["choices"][0].get("message") or {})
    return status, data

def motion_length_note(seconds, beats=None):
    """How much can actually happen in this clip, and what fills the rest.

    The directors were told to write "for the requested clip length" and never
    told what it was, so a 15s brief carried 5s of content and the rest played
    as someone waiting. One real event per ~5s is the budget; the gaps are for
    the involuntary things people do, which is what makes a clip read as
    footage instead of a pose being held.

    The sentence count is derived here for the same reason the event count is.
    Both prompts used to cap it at a fixed 2-4 (LTX) or 3-6 (H3) sentences, and
    a fixed cap with a scaling budget inverts the result: measured on one
    still, the 5s brief came back at 687 characters carrying five events while
    the 15s brief came back at 483 carrying three. The cap, not the clip, was
    setting the content - so it has to move with the clip or not exist.
    """
    seconds = int(seconds or 5)
    beats = max(1, int(beats if beats is not None else round(seconds / 5)))
    low, high = 2 + 2 * (beats - 1), 3 + 3 * (beats - 1)
    return (f"\nTHIS CLIP IS {seconds} SECONDS - room for about {beats} real "
            f"event{'s' if beats != 1 else ''}, in order, each given time to "
            f"land. Do not cram in more, and do not pad with fewer. Write "
            f"{low}-{high} sentences: that is the length this much screen time "
            f"needs, and it is the only sentence count that applies.\n"
            # "The people wait for action notes if they don't have any"
            # (2026-08-11): events with dead air between them render as a
            # subject idling until the next instruction. The chain rule hands
            # the whole duration to SOMETHING, so nothing waits or stretches.
            f"EVERY SECOND IS SPOKEN FOR, AS A CHAIN: each event begins as "
            f"the one before it lands - nobody in frame ever stands waiting "
            f"for a next note, because the texture below is already carrying "
            f"them there. A quoted line IS an event and spends real seconds "
            f"(two to three words a second, mouth busy for all of them), so "
            f"it shares the take with the action instead of stacking on top "
            f"of it.\n"
            f"BETWEEN AND UNDER THE EVENTS, write what real people do without "
            f"meaning to and film happens to catch: a glance away and back "
            f"before answering, weight settling onto one hip, a thumb worrying "
            f"the seam of a cup, a swallow before the first word, hair pushed "
            f"back that falls again anyway, a half-step taken purely for "
            f"balance, fingers finding a pocket. That texture is what separates "
            f"footage from a held pose - but it is texture, never the event, "
            # Texture written as a settled pose gives the sampler nothing to
            # move, and it stretches what little it has: slow motion.
            f"and it stays IN MOTION: write it mid-transit at real speed - "
            f"falling, shifting, being pushed - never as a position already "
            f"reached.\n"
            # A take where every beat lands on time is the definition of
            # staged. Attention wandering is the cheapest, truest way to break
            # that, and it costs a beat rather than the shot.
            f"NOTHING GOES CLEANLY, BECAUSE NOBODY'S ATTENTION HOLDS. Let one "
            f"thing pull her off the plan and then let her come back to it: a "
            f"noise off-frame she turns toward and dismisses, a sentence she "
            f"abandons and restarts differently, a reach that misses on the "
            f"first try, a phone checked out of pure reflex, a thought that "
            f"visibly derails before she catches it again. ONE interruption is "
            f"plenty - it should cost her a beat, not the shot - and it must "
            f"never be performed as cute. She is not doing it for the camera.")


def h3_ref2v_length_note(seconds):
    """The ref2va lane's length guidance. motion_length_note's sentence counts
    are the fl2va budget; this lane's trained budget is 350-500 words of
    detailed_description (ref guide §5.2), so it gets its own note with the
    same event physics and no competing number."""
    seconds = int(seconds or 5)
    events = max(1, round(seconds / 5))
    return (f"\nTHIS CLIP IS {seconds} SECONDS - one continuous take with room "
            f"for about {events} real event{'s' if events != 1 else ''}, in "
            f"order, each given time to land, with the texture of real "
            f"behaviour between them so no second waits or stretches. "
            f"detailed_description runs 350-500 English words: that is the "
            f"length this much screen time needs, covering the clip from its "
            f"first second to its last - one action carried through to its "
            f"end, described in stages, not a list of things happening at "
            f"once.\n")


def h3_cut_system(shots, cut_times):
    """The H3 motion brief as ONE take with real internal cuts.

    Same craft rules as every other H3 brief; what changes is that the shots
    live inside a single generation, so they are separated by H3's own timed cut
    syntax instead of by chaining. Nothing here needs an end-state handoff -
    there is no next generation to anchor - but each shot still needs its camera
    stated, because H3 drifts and reframes when told nothing.
    """
    times = ", ".join(h3_cut_timestamp(t) for t in cut_times)
    return (H3_MOTION_SYSTEM + f"\n\nCUT TIMELINE MODE: write ONE continuous "
            f"take containing exactly {shots} shots separated by hard cuts - "
            f"all of them inside the integrated_multimodal_description field.\n"
            f"'[Shot 1] ' carries NO timestamp; open it with the overall style "
            f"before the action. Begin each later shot with "
            f"'[Shot N] At MM:SS.mmm, the shot cuts to ...' using exactly these "
            f"cut times in this order: {times}. A cut must introduce new "
            f"information - a new space, viewpoint or moment; if only the "
            f"framing changes slightly, that is camera motion, not a cut.\n"
            f"State the camera in every shot, including what must NOT happen "
            f"('the frame never moves - no pan, no push-in, no reframing'), "
            f"because H3 drifts and reframes by default.\n"
            f"The subject is the same person throughout. Refer back to the "
            f"supplied still in a short phrase - 'the same face, hair and "
            f"wardrobe as the first frame, without reinterpretation' - and do "
            f"NOT re-describe their features, which fights the image and makes "
            f"identity worse.\n"
            f"Give each shot ONE primary change and close it with a short 'End "
            f"state:' sentence naming what is visibly true. Output only the "
            f"take.")


def h3_multishot_system(shots):
    """The H3 motion brief extended into a shot script.

    Additive rather than a rewritten prompt: every single-shot craft rule (frame
    zero fidelity, caused camera moves, synchronized sound) applies per shot,
    and a second copy of them would drift from the original.
    """
    return (H3_MOTION_SYSTEM + f"\n\nSHOT SCRIPT MODE: write exactly {shots} shots "
            f"of one continuous scene, separated by a line containing only "
            f"{H3_SHOT_SEPARATOR}. IGNORE the three-field OUTPUT FORMAT in this "
            f"mode: each shot is its own plain brief with no field labels (the "
            f"chain samples each shot separately); dialogue keeps the "
            f"(S1) <d>[Language] ...</d> form. Every rule above applies to each shot. Shot 1 "
            f"begins from the supplied still. Each later shot continues from the "
            f"previous shot's final frame, so open it where that motion ended and "
            f"hold subject identity, wardrobe and lighting across the whole "
            f"script. Give each shot ONE new thing to do rather than restating "
            f"the same brief - a change of angle or of beat is enough, and the "
            f"restraint rule still applies to every shot.\n"
            # The chain literally re-enters through the last frame, so that frame
            # is the next shot's entire view of the character. End on a close-up
            # or a half-occluded body and the following shot anchors on that -
            # which is a large part of why long chains drift.
            f"HOW EACH SHOT ENDS IS LOAD-BEARING, because the next shot is "
            f"generated from that exact frame. End every shot - including the "
            f"last - with the subject facing the camera, unoccluded, and framed "
            f"in full, not on a close-up, a turn away, or a body half out of "
            f"frame. Close each shot with one short sentence beginning 'End "
            f"state:' naming what is visibly true: where the subject is, what "
            f"they are holding, what has left frame. It must be checkable in a "
            f"still - 'she feels relieved' is not an end state, 'her shoulders "
            f"drop and both hands rest on the counter' is.\n"
            f"Output only the shots and the separators.")


# The brain is a Qwen3-VL, and the frame we are about to animate is sitting in
# ComfyUI's input folder. Directing from `scene` alone means directing from
# somebody else's sentence about the picture - so the model fills the gaps in
# the SENTENCE rather than the gaps in the IMAGE, and invents props, people and
# rooms that are not in the shot. Especially on "surprise me", where the text is
# thin and there is nothing else to anchor to.
MOTION_LOOK_NOTE = (
    "\nThe attached image IS the exact frame this video starts from. Direct only "
    "what is actually in it. Name the subject, wardrobe, props, setting and light "
    "you can SEE, and keep them unchanged unless the note asks otherwise. Do not "
    "add people, objects, animals or scenery that are not already in the frame, "
    "and never contradict what is there. If the shot needs something to happen, "
    "make it happen with what is visible.")

MOTION_INVENTORY_NOTE = (
    "\nThe FRAME INVENTORY lists what is actually in the start frame, read by a "
    "vision model that examined it. It is ground truth: where it disagrees with "
    "the scene caption, the inventory wins. Direct only what it names, and keep "
    "subject, wardrobe, props, setting and light unchanged unless the note asks "
    "otherwise. Do not add people, objects, animals or scenery it does not "
    "list, and never contradict it. If the shot needs something to happen, make "
    "it happen with what is listed.")

H3_BRIDGE_NOTE = (
    "\n\nFL2VA BRIDGE: Picture 1 is the exact first frame and Picture 2 is the "
    "exact final frame of this clip. Write ONE continuous shot - no cuts - "
    "whose action, camera and composition visibly CONVERGE on Picture 2's "
    "arrangement by the end: name the body movement, object movement, lighting "
    "and framing changes that get from one to the other. The destination is "
    "not optional, nothing may contradict either picture, and the last "
    "described moment must match Picture 2 exactly.")


# The canonical sighted brain, mirrored from install/catalog.json's "brain"
# lane: the 4B heretic gguf plus the base model's f16 projector (the heretic
# repo publishes none), ~4.8GB total. When the look has no eyes it provisions
# THIS - never the ~16GB FP16 AILab critic, whose first-run HuggingFace pull
# inside a render is what read as "Animate hangs" (Jesse, 2026-08-22: "force
# the download of the smaller model and projector, if it is not present").
BRAIN_VL_MODEL = {"repo": "DreamFast/Qwen3-VL-4b-Heretic-GGUF",
                  "path": "qwen3-vl-4b-heretic-Q8_0.gguf",
                  "bytes": 4280406176}
BRAIN_VL_MMPROJ = {"repo": "unsloth/Qwen3-VL-4B-Instruct-GGUF",
                   "path": "mmproj-F16.gguf",
                   "name": "qwen3-vl-4b-heretic.mmproj-f16.gguf",
                   "bytes": 836180640}
# A cold look is a Q8 load + projector load + a ~1024-vision-token read on a
# card that may still be busy from the render the user just made. The 120s
# chat default was never chosen for that; the warm retry gets room for the
# cold load instead of falling to the critic for what is really just patience.
BRAIN_VL_COLD_TIMEOUT = 300
_BRAIN_VL_FETCH = {"at": 0.0, "error": None}   # latch: a failed download is
                                               # not retried on every look
_BRAIN_VL_FETCH_LOCK = asyncio.Lock()


def _vl_miss(reason):
    """Every way the look leaves the brain names itself, logged exactly once.

    The fallback it precedes costs 16GB and minutes; a silent one is not
    allowed to exist (brief 9.16). The reason also rides to the caller, which
    decides the fallback and says so in the lane."""
    print(f"[pixal] the look left the brain: {reason}", flush=True)
    return None, reason


async def _brain_vl_fetch(entry, dest, label, cid=None):
    """One catalog file from HuggingFace, visibly. The .part/byte-count
    discipline of _quant_fetch_run; progress rides the lane in GB, because the
    download that prompted all this looked exactly like a hang."""
    part = dest.with_name(dest.name + ".part")
    url = f"https://huggingface.co/{entry['repo']}/resolve/main/{entry['path']}"
    total, got, said = entry["bytes"], 0, 0
    if cid:
        HUB.broadcast(type="text", cid=cid,
                      text=f"*downloading {label}: {dest.name} "
                           f"({total / 2**30:.1f} GB) - one time, then the look "
                           f"stays on the brain*")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with aiohttp.ClientSession(headers=_hf_headers()) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(
                    total=None, connect=15, sock_read=120)) as r:
                if r.status != 200:
                    raise aiohttp.ClientError(f"{entry['repo']}: HTTP {r.status}")
                with part.open("wb") as fh:
                    async for chunk in r.content.iter_chunked(1 << 22):
                        await asyncio.to_thread(fh.write, chunk)
                        got += len(chunk)
                        if cid and got - said >= 512 * 2**20:
                            said = got
                            HUB.broadcast(
                                type="thinking", cid=cid,
                                note=f"downloading {dest.name} - "
                                     f"{got / 2**30:.1f} of {total / 2**30:.1f} GB")
        if got != total:
            raise aiohttp.ClientError(f"truncated at {got} of {total} bytes")
        os.replace(part, dest)
    except Exception:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    if cid:
        HUB.broadcast(type="text", cid=cid,
                      text=f"*{dest.name} is in - the brain can see*")


async def ensure_sighted_brain(cfg, cid=None):
    """Give the look a seeing brain when it has none: fetch the 4B + its
    projector and leave the config pointing at a model with eyes. Returns an
    error string (the reason the brain stays blind) or None when a sighted
    brain is ready to spawn.

    Only the Qwen3-VL 4B pair is provisioned: a projector is size-specific,
    so a Gemma (or an 8B) with no projector keeps the old ComfyUI fallback
    rather than growing mismatched eyes."""
    model = (cfg.get("local_model") or "").strip()
    have_model = bool(model) and Path(model).is_file()
    if have_model:
        if not (_local_llm_family(model) == "qwen3-vl"
                and "4b" in Path(model).name.lower()):
            return (f"no projector sits beside {Path(model).name}, and the "
                    "shipped projector only fits the Qwen3-VL 4B brain")
        dest_model = Path(model)
    else:
        dest_model = CDIR / "models" / "LLM" / "GGUF" / BRAIN_VL_MODEL["path"]
    latch = _BRAIN_VL_FETCH
    if latch["error"] and time.time() - latch["at"] < 600:
        return (f"the 4B brain download failed earlier ({latch['error']}) - "
                "not retrying on every look")
    dest_proj = dest_model.parent / BRAIN_VL_MMPROJ["name"]
    async with _BRAIN_VL_FETCH_LOCK:
        try:
            if not dest_model.is_file():
                await _brain_vl_fetch(BRAIN_VL_MODEL, dest_model,
                                      "the sighted brain (Qwen3-VL 4B)", cid)
            if not dest_proj.is_file():
                await _brain_vl_fetch(BRAIN_VL_MMPROJ, dest_proj,
                                      "the brain's projector", cid)
        except Exception as exc:
            latch.update(at=time.time(), error=str(exc))
            return f"the 4B brain could not be fetched ({exc})"
    if not have_model:
        # The configured model was gone (or never picked): point the setting
        # at the pair that just landed, or ensure_local_llm keeps reporting a
        # file that is not there.
        full = load_config()
        full["llm"]["local_model"] = str(dest_model)
        save_config(full)
    return None


async def brain_vl_read(staged, question, cid=None, timeout=120):
    """Ask the sighted LOCAL brain a question about one staged frame.

    Returns (text, None) on an answer, or (None, reason) meaning "use the
    ComfyUI critic graph instead" - and every one of the eight ways out names
    itself, because the fallback is a 16GB FP16 load and a silent one once
    read as "Animate hangs" (Jesse, 2026-08-22). Brain-first is the rule
    (Jesse, 2026-08-18): the brain is ~5GB and already resident for chat,
    while the critic graph survives only as the blind-preset fallback, and
    only when its weights are already local (frame_inventory checks).
    """
    import base64
    cfg = load_config()["llm"]
    if f"127.0.0.1:{LOCAL_LLM_PORT}" not in cfg["base_url"]:
        return _vl_miss("the chat preset is remote - only the managed local "
                        "brain can see")
    state = _llm_state()
    mmproj = _local_llm_mmproj(cfg.get("local_model") or "")
    if state.get("pid") and not state.get("mmproj") and mmproj:
        # Running and demoted-blind (its projector failed the smoke test this
        # session): a respawn changes nothing, so don't ask.
        return _vl_miss("the brain is running blind - its projector failed "
                        "this session's smoke test")
    if not mmproj:
        # No projector on disk - or no model at all. Fetch the small sighted
        # pair and keep the look on the brain; the 16GB critic is not allowed
        # to be the way vision arrives.
        err = await ensure_sighted_brain(cfg, cid)
        if err:
            return _vl_miss(err)
    path = CDIR / "input" / staged
    try:
        b64 = base64.b64encode(path.read_bytes()).decode()
    except OSError as exc:
        return _vl_miss(f"the staged frame could not be read ({exc})")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": question},
        {"type": "image_url",
         "image_url": {"url": "data:image/png;base64," + b64}},
    ]}]
    try:
        status, data = await llm_call(messages, timeout=timeout, cid=cid)
    except Exception:
        # Cold, most likely: the butler evicts the brain before renders, and a
        # Q8 load + projector + vision read can outrun a chat-sized timeout.
        # That is patience, not failure - warm the brain through the same
        # ensure path chat uses, then ask ONCE more, before ComfyUI is even
        # considered.
        if cid:
            HUB.broadcast(type="thinking", cid=cid,
                          note="the brain is cold - warming it for one more look")
        err = await ensure_local_llm(cid)
        if err:
            return _vl_miss(f"the brain would not wake for a second look "
                            f"({err})")
        try:
            status, data = await llm_call(messages,
                                          timeout=BRAIN_VL_COLD_TIMEOUT,
                                          cid=cid)
        except Exception as exc:
            return _vl_miss(f"the brain did not answer even warmed ({exc})")
    if status != 200:
        return _vl_miss(f"the brain answered HTTP {status}")
    # The spawn's smoke test can demote a blind brain mid-call; a demoted
    # brain answered from imagination, so its text must not count. (This also
    # catches a server with no registered projector, e.g. an external one.)
    if not _llm_state().get("mmproj"):
        return _vl_miss("the brain that answered has no live projector - its "
                        "read cannot be trusted")
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    text = msg.get("content")
    if isinstance(text, list):
        text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))
    text = " ".join(str(text or "").split())
    if not text:
        return _vl_miss("the brain answered empty")
    return text, None


async def frame_inventory(frame, ref_id, cid=None):
    """LOOK stage: read the staged start frame, brain-first.

    Best-effort by design - any failure returns "" and the brief rides the
    scene caption alone, exactly as before the look existed. A sighted local
    brain answers directly (no extra model load); the vl_look ComfyUI job is
    the fallback, butler-managed like a review - and submitted ONLY when the
    critic's weights are already on disk, because a first-run HuggingFace pull
    inside a render is the hang this stage was rebuilt to kill (brief 9.16)."""
    name = input_ref_name(frame)
    if not name or not (CDIR / "input" / name).is_file():
        return ""
    try:
        # Animate frames can be upscales; the look reads a ~1.5K copy - same
        # inventory, a fraction of the vision tokens.
        name = stage_critic_input(CDIR / "input" / name,
                                  f"pixal_look_{ref_id}.png")
        text, reason = await brain_vl_read(name, LOOK_Q, cid=cid)
        if text is None:
            critic, on_disk = critic_weights()
            if not on_disk:
                # The critic's weights are NOT local: submitting this job is
                # what pulled ~16GB from HuggingFace mid-render - the
                # "Fetching 12 files" stall of 2026-08-22. The look is
                # optional; the brief rides the caption and the lane says why.
                if cid:
                    HUB.broadcast(type="text", cid=cid,
                                  text=f"*the look is skipped: {reason} - and "
                                       f"the critic ({critic}) is not downloaded, "
                                       f"so the brief rides the caption*")
                return ""
            if cid:
                HUB.broadcast(type="text", cid=cid,
                              text=f"*the brain could not look ({reason}) - the "
                                   f"critic on disk reads the frame instead*")
            job = await HUB.submit(cid or uuid.uuid4().hex[:8], "look", "vl_look",
                                   f"look at #{ref_id}", {"image": name}, 1)
            if job.get("error"):
                return ""
            for _ in range(180):           # cold 8B load + read; usually far less
                if job.get("finalized"):
                    break
                await asyncio.sleep(1)
            text = "\n".join(job.get("texts", [])).strip()
            if not text:                   # ws dropped mid-load - the file is the record
                fp = CDIR / "output" / f"pixal_dm/look_{ref_id}.txt"
                if fp.is_file():
                    text = fp.read_text(encoding="utf-8").strip()
            text = " ".join(text.split())
        if text and cid:
            # The inventory used to ride to the director invisibly; showing it
            # lets the user catch a misread frame BEFORE the render spends
            # minutes animating somebody else's picture.
            HUB.broadcast(type="text", cid=cid,
                          text=f"*what the camera sees: {text}*")
        return text
    except Exception:
        return ""


# ------------------------------------------------------- the line, repaired
# Rewriting SPOKEN_LINE_RULE moved the needle and did not finish the job. On
# the live 4B (2026-08-16 harness, 13 unprompted lines) the meta-quip that
# started this went to zero, but three lines still OPENED with a second-person
# prediction and the rest mostly floated free of the frame - with the shape
# banned outright in the system prompt AND checked in the output contract. A
# 4B has that phrasebook too deep for prose to reach.
#
# Which is the lesson repair_h3_dialogue_tags already learned about syntax:
# for a small brain, the fix is detect-then-repair, not another paragraph. The
# difference is that a bad LINE cannot be rewritten in code - so this detects
# deterministically and spends one short completion asking for a replacement,
# with the fault named and the frame in hand. It never deletes dialogue and
# never touches words the user supplied: a failed repair keeps the original,
# because silently muting a character is worse than shipping a weak line.
_LINE_ATTRACTORS = (
    (re.compile(r"^\W*(?:i|that|this|it)\s*(?:'|’)?\s*(?:m|s|am|is)?\s+not\b", re.I),
     "it opens by denying something nobody in the scene said"),
    (re.compile(r"^\W*(?:not\s+even|still\s+(?:got|here|standing|winning))\b", re.I),
     "it is a boast dressed up as a denial"),
    # First person only. "You're still here?" said to somebody in the room is
    # ordinary talk; "I'm still here" is the clip winking at its own viewer,
    # which is the line that started all this.
    (re.compile(r"\b(?:i\s*(?:'|’)?\s*m\s+still\s+here|on\s+camera|the\s+camera|"
                r"watching\s+this|say(?:ing)?\s+goodnight)\b", re.I),
     "it talks about the video instead of talking to somebody in the room"),
)

_SECOND_PERSON_FUTURE = re.compile(
    r"^\W*(?:so|and|but|well|yeah|oh)?[\s,]*you\b"
    r"(?:\s*(?:'|’)\s*(?P<will>ll)|\s+(?P<willw>will))?"
    r"(?:\s*(?:'|’)\s*(?P<cop>re)|\s+(?P<copw>are))?"
    r"(?:\s+(?:not|never))?"
    r"(?:\s*(?P<verb>gonna|gunna|going\s+to|never|always|won'?t)\b)?", re.I)


def _predicts_at_the_listener(flat):
    """The commonest attractor: telling the viewer what they will do or feel.

    Exempts bare copula deletion. "you gonna get that fixed?" is a real
    vernacular construction and exactly the speech SPOKEN_LINE_RULE asks for -
    banning it would enforce standard grammar in the name of sounding real. It
    is the explicit copula that marks the promise: "you're gonna", "you'll".
    Matching on the QUESTION MARK instead was tried first and was too broad; it
    waved through "You'll be late for that meeting, ain't you?" (2026-08-16).
    """
    m = _SECOND_PERSON_FUTURE.match(flat)
    if not m:
        return False
    if m.group("will") or m.group("willw"):
        return True             # "you'll ..." - the auxiliary IS the promise
    verb = (m.group("verb") or "").lower()
    if not verb:
        return False            # bare "you're late," is just talking
    if not (m.group("cop") or m.group("copw")) and verb in ("gonna", "gunna"):
        return False            # copula deletion - "you gonna get that fixed?"
    return True

# H3 tags its dialogue, LTX 2.x quotes it. One pattern, two dialects: group
# "tag" and group "quo" hold the words, so a repair can swap the inner text
# without disturbing the delivery prose either side of it.
_SPOKEN_SPAN_RE = re.compile(
    r"<d>\s*(?:\[[^\]]*\]\s*)?(?P<tag>[^<]{2,160}?)\s*</d>"
    r"|[\"“](?P<quo>[^\"”\n]{4,160})[\"”]")

_NOTE_HAS_WORDS_RE = re.compile(r"[\"“‘][^\"”’\n]{3,}[\"”’]")

# Everything a line can be built from without being ABOUT anything. A line that
# shares no word outside this list with the frame inventory is the "could sit
# under any other video" failure, measured: with the shape attractors beaten,
# three lines in four still named nothing that was actually in the picture
# (2026-08-16 harness). Grounding is what the covered-picture test is for, and
# a bag of words is a blunt but honest way to ask it in code.
_LINE_FUNCTION_WORDS = frozenset("""
a an the and or but so if then than as at by for from in into of off on onto out
over to up down with without within about after before again just only even still
this that these those it its there here where when what which who whom whose why
how i im me my mine we us our ours you your yours he him his she her hers they
them their theirs is am are was were be been being do does did doing done have
has had having can could will would shall should may might must ok okay yeah yes
no not nah nope dont doesnt didnt cant wont isnt arent wasnt werent aint gonna
gunna wanna gotta kinda sorta lemme dunno get gets got getting go goes going went
come comes coming came take takes taking took make makes making made say says
saying said think thinks thinking thought know knows knowing knew see sees seeing
saw look looks looking looked want wants wanted need needs needed like likes
liked well right now one two three thing things stuff man dude bro hey oh um uh
uhh huh whoa wow damn shit fuck hell god jesus christ please thanks sorry wait
really actually literally seriously maybe probably always never sometimes
""".split()) | frozenset("""
late early mid young older adult teen woman women girl guy lady person people
""".split())
# ^ every VL inventory opens by ageing the subject ("Woman, late 20s"), so
# those words are in EVERY frame and a line matching one is not grounded by it.
# "You're late," scored as grounded against "late 20s" the first time this ran.


def _content_words(text):
    """Nouns-ish: whatever is left after the words every sentence has. Plurals
    are stemmed because "quarter" vs "quarters" scored a grounded line as
    ungrounded the first time this was measured."""
    out = set()
    for w in re.findall(r"[a-z']+", str(text or "").lower()):
        w = w.replace("'", "")
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]
        if len(w) > 2 and w not in _LINE_FUNCTION_WORDS:
            out.add(w)
    return out


def spoken_line_fault(line, frame=None):
    """Which attractor this line fell into, or None if it is clean.

    With a frame inventory in hand it also asks the covered-picture question:
    a line sharing no content word with the frame could sit under any other
    video. Called with no frame it checks shape only.
    """
    flat = " ".join(str(line or "").split())
    if not flat:
        return None
    # Quoted ALL CAPS in a brief is a sign, a title card or a chyron, not a
    # spoken line - history.jsonl has several. Never rewrite the set dressing.
    if flat.upper() == flat and re.search(r"[A-Z]{3}", flat):
        return None
    if _predicts_at_the_listener(flat):
        return "it opens by predicting what the listener is about to do or feel"
    for pattern, why in _LINE_ATTRACTORS:
        if pattern.search(flat):
            return why
    # Only against a real inventory. The caption alone is the sentence that
    # MADE the picture, so matching against it rewards echoing the prompt.
    if frame and not (_content_words(flat) & _content_words(frame)):
        return "it names nothing that is actually in the frame"
    return None


async def repair_spoken_line(brief, scene, look, hint, seconds=None):
    """Swap out any spoken line that fell into a known attractor.

    Returns the brief unchanged when there is nothing to fix, when the user's
    note supplied the words, or when the replacement is no better than what it
    would replace.
    """
    if hint and _NOTE_HAS_WORDS_RE.search(hint):
        return brief                        # the note's words are the vision
    # Grounding VALIDATES a replacement; it does not TRIGGER one. Firing on it
    # was measured and reverted (2026-08-16): as a trigger it fired on roughly
    # seven lines in ten, converged every one of them onto the same prop and
    # the same flat construction, and took spoken texture from 77% to 31% while
    # grounding went DOWN. It also ate "you gonna get that machine fixed or
    # just let it burn?" - a good line - for saying "machine" instead of
    # "dryer". A bag of words is too blunt to judge what a line is ABOUT, but
    # it is fine for confirming a rewrite actually landed somewhere real.
    ground = None if hint else (look or None)
    faults = [(m, spoken_line_fault(m.group("tag") or m.group("quo")))
              for m in _SPOKEN_SPAN_RE.finditer(brief or "")]
    faults = [(m, why) for m, why in faults if why][:2]   # two repairs, never a loop
    if not faults:
        return brief
    frame = (look or scene or "").strip()[:900]
    budget = max(4, min(12, int((seconds or 5) * 2)))
    out, cursor = [], 0
    for m, why in faults:
        original = (m.group("tag") or m.group("quo")).strip()
        system = (
            "You rewrite ONE line of spoken dialogue for a video clip. Reply with the "
            "replacement line only - no quotation marks, no name, no explanation, no "
            f"stage direction, at most {budget} words.")
        user = (
            f"WHAT IS IN THE FRAME: {frame}\n"
            f"THE LINE THAT FAILED: {original}\n"
            f"WHY IT FAILED: {why}.\n"
            "Write its replacement. The clip joins a conversation already underway, so "
            "this is a reply to something said a second before it started, spoken to a "
            "person who is there. Name or answer ONE specific thing from the frame - "
            "with the picture covered the line must stop making sense. "
            # Forcing the object in produced a line about a puddle's GLOW
            # (2026-08-16 harness) - grounded, and worse than what it replaced.
            "Use plain everyday words - no metaphor, no imagery, nothing about how "
            "anything looks; talk about what the thing is doing or what is wrong with "
            "it. "
            # Last, because it is the instruction most easily flattened by the
            # one above: asked for plain words the 4B writes tidy declaratives.
            "Write it the way a mouth moves: a fragment, a contraction, filler, "
            "trailing off or cut short. It does not have to be clever and it must not "
            "sound quotable - a half-finished thought is the target.")
        # Two attempts. One was measured too brittle: the 4B answers a rewrite
        # with the same attractor often enough that a single rejection left the
        # bad line standing (2026-08-16, "I'm not late," survived a repair that
        # ran and was refused). The second ask is a fifth of a second here.
        fresh = ""
        for attempt in range(2):
            try:
                status, d = await llm_call(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": user}], timeout=45)
            except Exception:
                break
            if status != 200:
                break
            got = (d.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
            got = " ".join(got.split()).strip("\"“”'‘’")
            # A repair that trips the same wire, runs long, or comes back as
            # prose about the line instead of the line is worse than nothing.
            if (got and not spoken_line_fault(got, ground)
                    and len(got.split()) <= budget + 2
                    and "\n" not in got and got.lower() != original.lower()):
                fresh = got
                break
            user += ("\nThat rewrite failed for the same reason. Try again, and this "
                     "time start with a filler word or a fragment, not with 'you'.")
        if not fresh:
            continue
        span = m.span("tag") if m.group("tag") is not None else m.span("quo")
        out.append(brief[cursor:span[0]])
        out.append(fresh)
        cursor = span[1]
        print(f"[pixal] spoken line repaired ({why}): {original!r} -> {fresh!r}")
    if not out:
        return brief
    out.append(brief[cursor:])
    return "".join(out)


async def direct_motion(scene, hint=None, engine="ltx25", shots=1, cut_times=None,
                        seconds=None, frame=None, look=None,
                        last_frame=None, look_end=None, model=None):
    """Returns (brief, directed) - directed=False means the LLM was unreachable and
    the caller should say so instead of quietly shipping the default.

    ``cut_times`` selects the single-pass timeline (real cuts inside ONE
    generation); without it, several shots mean the chained script format.
    ``model`` selects the H3 lane: a ref2va chip gets the six-section director
    variant (H3_REF2V_MOTION_SYSTEM) - the DIRECTOR writes all six sections,
    and the fl2va frame-zero premise never enters this lane.

    The single-shot fallback is safe for both: the chain's builder passes the
    requested shot_count and the node continues the last prompt for any shot the
    script did not cover, and a single pass with no cut markers is simply a
    one-shot take of the right length.
    """
    user = f"Still scene: {scene}"
    if look:
        # The look ran because the chat brain cannot see (no mmproj on the
        # managed llama.cpp server) - the caption alone made briefs describe the
        # SENTENCE about the picture, not the picture.
        user = (f"Still scene (the caption that generated the frame): {scene}\n"
                f"FRAME INVENTORY (ground truth): {look}")
    if look_end:
        user += (f"\nEND FRAME INVENTORY (Picture 2 - the clip must visibly "
                 f"converge on exactly this): {look_end}")
    if hint:
        user += f"\nDIRECTOR'S NOTE (the vision - obey it): {hint}"
    h3_variant = h3_model_variant(model) if engine == "h3" else None
    if h3_variant == H3_REF2V_MODEL_ID:
        # The director must know exactly what is wired: one reference image,
        # and nothing else. Tag discipline is the failure the official
        # template itself ships (a dangling <Audio 1>).
        user += ("\nTHE WIRED REFERENCE: exactly one reference image is wired, "
                 "<Picture 1> - the still above. Its subject is who your brief "
                 "carries into the new scene. Bind it to <Subject 1>; never "
                 "name <Picture 2>, <Video> or <Audio> - none are wired.")
    _turn_start()
    try:
        if engine == "h3":
            if cut_times:
                system = h3_cut_system(shots, cut_times)
            elif shots > 1:
                system = h3_multishot_system(shots)
            elif h3_variant == H3_REF2V_MODEL_ID:
                system = H3_REF2V_MOTION_SYSTEM
            else:
                system = H3_MOTION_SYSTEM
            # `seconds` here is the PER-SHOT length and the note divides by
            # `shots` itself - passing it raw budgeted every multishot shot at
            # seconds/shots (a 5s 3-shot brief told its director 1.67s and
            # starved dialogue to a third). Pass the total; shots=1 is a no-op,
            # so single-shot output is unchanged.
            system += h3_speech_budget_note(int(seconds or 5) * shots, shots)
            # No bridge in the reference lane - animate refuses last_id on a
            # ref2va chip, and the node has no end-frame input at all.
            if h3_variant != H3_REF2V_MODEL_ID and (last_frame or look_end):
                system += H3_BRIDGE_NOTE
        elif engine == "ltx25":
            # 2.5 speaks a different dialect from 2.3: flowing paragraph,
            # quotation-mark dialogue, post-move framing. Its own prompt,
            # ported from the official guide.
            system = LTX25_MOTION_SYSTEM
        else:
            system = MOTION_SYSTEM
        # Always appended, never conditional: the length note is now the only
        # place either prompt states how many events OR how many sentences to
        # write, so skipping it would ship a brief with no length guidance at
        # all. It defaults to 5s, which is the shortest clip either engine makes.
        #
        # A cut timeline spends its whole length across the shots, so the
        # budget is one event per shot; every other mode gets one per ~5s.
        # ref2va gets its own note: its trained budget is 350-500 words of
        # detailed_description, and the fl2va note's sentence counts would
        # fight it.
        if h3_variant == H3_REF2V_MODEL_ID:
            system += h3_ref2v_length_note(int(seconds or 5))
        else:
            total = int(seconds or 5) * shots if cut_times else int(seconds or 5)
            system += motion_length_note(total, shots if cut_times else None)
        # Only claim the model can see when we actually managed to attach the
        # frame - promising an image that is not there is worse than not sending
        # one, because the brief then describes a picture nobody supplied. With
        # a frame inventory in hand the image is NOT attached: the local brain
        # would flatten it to "[attached image]" anyway, and the inventory is
        # the text-shaped truth it can actually use.
        url = None if look else (data_url_for(frame) if frame else None)
        if look:
            system += (H3_REF2V_INVENTORY_NOTE
                       if h3_variant == H3_REF2V_MODEL_ID else MOTION_INVENTORY_NOTE)
            content = user
        elif url:
            system += (H3_REF2V_LOOK_NOTE
                       if h3_variant == H3_REF2V_MODEL_ID else MOTION_LOOK_NOTE)
            content = [{"type": "image_url", "image_url": {"url": url}}]
            url_end = data_url_for(last_frame) if last_frame else None
            if url_end:
                system += ("\nThe SECOND attached image is Picture 2, the "
                           "exact FINAL frame - the clip must converge on it.")
                content.append({"type": "image_url", "image_url": {"url": url_end}})
            content.append({"type": "text", "text": user})
        else:
            content = user
        status, d = await llm_call([{"role": "system", "content": system},
                                    {"role": "user", "content": content}], timeout=120)
        text = (d.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        if status == 200 and text:
            text = await repair_spoken_line(text, scene, look, hint, seconds)
            return repair_camera_note(text, hint), True
    except Exception:
        pass
    finally:
        _turn_end()
    # the old fallback was a push-in - it read as "it just zoomed in on the image"
    fallback = ("A still handheld camera with natural micro-shake; the subject continues "
                "the action of the frame - breathing, blinking, hair and fabric moving "
                "naturally; lighting unchanged. No zoom, no push-in.")
    if engine == "h3" and h3_variant == H3_REF2V_MODEL_ID:
        # No frame to continue in this lane: the reference is identity, and the
        # scene is new. The assembler wraps this into the six sections.
        fallback = ("The subject of <Picture 1> in a new, quiet scene - breathing, "
                    "blinking, hair and fabric moving naturally; a still handheld "
                    "camera with natural micro-shake. No zoom, no push-in. Generate "
                    "synchronized room tone, fabric movement, and other action "
                    "sounds visible in the scene; do not invent dialogue.")
    elif engine == "h3":
        fallback += (" Generate synchronized room tone, fabric movement, footsteps, and "
                     "other action sounds visible in the scene; do not invent dialogue.")
    if hint:
        fallback = hint.strip().rstrip(".") + ". " + fallback
    return fallback, False

_QUANT_TOKEN_RE = re.compile(
    r"^(i?q\d[\w]*|f16|f32|bf16|fp\d+\w*|\d+bit|gguf)$", re.I)
_SIZE_TOKEN_RE = re.compile(r"^\d+(\.\d+)?b$", re.I)


def brain_display_name(path, mmproj=None):
    """'gemma-3-12b-it-abliterated.Q6_K.gguf' -> 'Gemma 3 12b w/ vision':
    the lane talks about the model by its common name (family + size), not
    its filename (Jesse, 2026-08-12). Variant/quant tokens after the size
    are shop talk; the vision suffix is the one state worth surfacing."""
    # PureWindowsPath, not Path: the model path comes from config.json and is
    # authored on Windows, but the test suite also runs on Linux, where a Path
    # never splits on a backslash and the whole 'X:\m\...' becomes the name.
    # PureWindowsPath honours both separators on either platform.
    toks = re.split(r"[-_. ]+", PureWindowsPath(path or "").name)
    out = []
    for t in toks:
        if not t or _QUANT_TOKEN_RE.match(t):
            break
        out.append("VL" if t.lower() == "vl" else t)
        if _SIZE_TOKEN_RE.match(t):
            break
    name = " ".join(out)
    if not name:
        return "local brain"
    name = name[0].upper() + name[1:]
    return name + (" w/ vision" if mmproj else "")


def brain_name():
    """What to call the chat brain in the lane - 'kimi' was a lie when the error
    came from a local GGUF."""
    cfg = load_config()["llm"]
    if f"127.0.0.1:{LOCAL_LLM_PORT}" in cfg["base_url"]:
        model = cfg.get("local_model") or ""
        if not model:
            return "local brain"
        return brain_display_name(model, _local_llm_mmproj(model))
    return cfg.get("model") or "the brain"

def effective_recipe(opts):
    """Resolve composer intent once so UI direction and queued graph agree.

    A selected character (or standalone identity reference) is an identity-edit
    request, regardless of stale engine/model state. Explicit recipe and model
    family selection apply only when there is no identity source.
    """
    opts = opts or {}
    if opts.get("character"):
        return "identity_edit"
    if any(r.get("kind") == "identity" for r in (opts.get("refs") or [])):
        return "identity_edit"
    # A saved style names the graph it runs on. It sits BELOW identity, which
    # still wins - a character IS the style - and ABOVE style/quality, which it
    # supersedes entirely.
    style = saved_style(opts.get("saved_style"))
    if style:
        return style["base"]
    # New composer contract: model owns the executable graph; style is creative
    # intent and quality only selects Realism II on Krea. Unsupported pairings
    # degrade to that model family's safe general route rather than splicing a
    # Base-only Anime VAE or Fantasy LoRA into Z-Image Turbo.
    if "style" in opts or "quality" in opts:
        style = opts.get("style") if opts.get("style") in (
            "realism", "anime", "fantasy") else "realism"
        refined = opts.get("quality") == "refined"
        entry = resolve_model_entry(opts.get("model")) if opts.get("model") else None
        if entry and entry["family"] == "zimage":
            if entry.get("variant") == "base" and style in ("anime", "fantasy"):
                return style
            return "zimage"
        if entry and entry["family"] == "krea2":
            return "realism_ii" if style == "realism" and refined else "realism"
        # Qwen-Image owns its own graph and has no style or quality variants, so
        # every creative intent resolves to the one recipe that can run it.
        # Without this the fallthrough hands a qwen_image model to Realism, and
        # resolve_recipe_model rejects it for the family it never claimed to be.
        if entry and entry["family"] == "qwen_image":
            return "qwen_image"
        # Anima is the same shape of trap, one step worse: the composer pins its
        # style to "anime", so without this the next line hands an Anima
        # checkpoint to the Z-Image clear-anime recipe and pick_recipe_model
        # rejects it - "anima-base-v1.0 is anima, but Anime needs zimage" - on
        # the first render anyone tries.
        if entry and entry["family"] == "anima":
            return "anima"
        if style in ("anime", "fantasy"):
            return style
        return "realism_ii" if refined else "realism"
    if opts.get("engine") in PUBLIC_RECIPE_IDS:
        return opts["engine"]
    if opts.get("model"):
        entry = resolve_model_entry(opts["model"])
        if entry and entry["family"] == "zimage":
            return "zimage"
        if entry and entry["family"] == "krea2":
            return "realism"
        if entry and entry["family"] == "qwen_image":
            return "qwen_image"
        if entry and entry["family"] == "anima":
            return "anima"
    return None

def held_seed(src):
    """A frozen seed off the composer (or a re-roll body), or None.

    The lock is a promise - "this exact dice until I say otherwise" - so it is
    read here, once, for every render path rather than at each call site. Out
    of range means not a seed at all: submit now draws from [1, 2**53) so the
    value survives JSON, but the bound stays at 2**62 because ledger entries
    drawn before that cap still hold bigger seeds and must keep validating. A
    0 would be indistinguishable from "unset" once it got there.
    """
    raw = (src or {}).get("seed")
    if raw in (None, "", 0):
        return None
    try:
        seed = int(raw)
    except (TypeError, ValueError):
        return None
    return seed if 1 <= seed < 2 ** 62 else None


def _apply_opts(args, opts):
    """Apply validated composer intent for both cloud and local brains."""
    opts = opts or {}
    recipe = effective_recipe(opts)
    ident = next((r for r in (opts.get("refs") or [])
                  if r.get("kind") == "identity"), None)
    identity_source = bool(opts.get("character") or ident)

    if opts.get("character"):
        # Validate before a costly brain turn can queue a doomed graph. The
        # anchor's own reference is authoritative; stale manual refs are ignored.
        character_identity(opts["character"])
        args["character"] = opts["character"]
        args.pop("ref", None)
    elif ident:
        ref = input_ref_name(ident.get("file"))
        if not ref or not (CDIR / "input" / ref).is_file():
            raise ValueError(f"identity reference not found in ComfyUI/input: {ref or 'unknown'}")
        # The composer explicitly chose a standalone face. Do not let a
        # brain-invented character argument outrank it inside build_zara_edit.
        args.pop("character", None)
        args["ref"] = ref

    if identity_source:
        # Identity Edit has a proven default. Carry a selected model only when
        # it is genuinely compatible; never splice a stale Z model into Krea.
        args.pop("model", None)
        args.pop("loras", None)
        if opts.get("model"):
            entry = resolve_model_entry(opts["model"])
            if entry and "identity_edit" in compatible_recipes(entry):
                args["model"] = opts["model"]
    elif opts.get("model"):
        args["model"] = opts["model"]

    # While a saved style is selected the FILE is authoritative. The composer
    # mirrors its model, canvas and LoRA plan so every pill states what will
    # run, but a mirror is exactly the thing that goes stale between two tabs -
    # so the render reads the file, not the mirror.
    style = saved_style(opts.get("saved_style"))
    if style and identity_source:
        # A character no longer refuses the style outright (Jesse, 2026-08-18):
        # the identity patch is a Krea-2-trained LoRA, so any style whose model
        # can carry it contributes its model and stack to the identity graph.
        # A style on an incompatible base (Z-Image, Anima) still steps aside.
        entry = resolve_model_entry(style["model"])
        if not (entry and "identity_edit" in compatible_recipes(entry)):
            style = None
    if style:
        # Ride along to the job receipt. Everything the style does is folded
        # into ordinary args below, so without this the render loses the only
        # record of WHICH preset produced it and the card can only ever name
        # the base recipe - "Realism" for a picture that was Ultra Realism.
        # `submit` pops this before the SIGS filter, the same way it pops seed.
        args["_style"] = {"id": style["id"], "name": style["name"],
                          "base": style["base"]}
        args["model"] = style["model"]
        if style.get("aspect"):
            args["aspect"] = style["aspect"]
        if style.get("mp"):
            args["mp"] = style["mp"]
        # Tuning names nodes in the style's OWN base graph; on the identity
        # graph those ids point at nothing (or worse, something else), so the
        # sampler settings only apply when the style's base is what runs.
        if recipe == style["base"]:
            overrides = tuning_overrides(style["base"], style["model"],
                                         style.get("tuning"))
            if overrides:
                args["overrides"] = overrides

    # The composer's stack wins over the style's file. Selecting a style mirrors
    # its plan into the composer, so this IS the style's plan until the user
    # edits it - and the moment they add a LoRA, the render has to be the stack
    # they are looking at. Model, canvas and sampler still come from the file,
    # which is what a mirror can actually go stale about between two tabs; a
    # LoRA the user just added by hand cannot be stale.
    plan = opts.get("lora_plan")
    if plan is None and style:
        plan = style.get("lora_plan")
    if plan is not None and style and recipe == "identity_edit" and \
            plan.get("recipe") != "identity_edit":
        # The style's stack was authored against its base recipe; on identity
        # it rides the editable lane instead, while the core stages (vector
        # bypass + the identity patch) stay. Entries must still be Krea 2 or
        # validate_lora_plan refuses them by family.
        plan = {"version": 1, "mode": "replace_editable",
                "recipe": "identity_edit",
                "recipe_revision":
                    RECIPE_SPECS["identity_edit"]["lora_stack_revision"],
                "entries": [{k: v for k, v in e.items()
                             if k in ("name", "slot", "enabled", "strength")}
                            for e in plan.get("entries") or []]}
    if plan is not None and recipe:
        # The plan replaces the editable lane; never merge brain/legacy extras
        # into it. A recipe mismatch is a stale UI state and fails honestly.
        validate_lora_plan(recipe, plan)
        args.pop("loras", None)
        args["lora_plan"] = plan
    elif style:
        # The style carries no plan, so the base recipe's own defaults run. A
        # composer plan left over from free mode belongs to a stack the user is
        # no longer looking at.
        args.pop("lora_plan", None)
        args.pop("loras", None)
    else:
        # Bare Auto has no resolved graph yet, so a stale recipe-specific plan
        # is ignored. Legacy extras retain their historical append behavior.
        args.pop("lora_plan", None)
        picked_loras = opts.get("loras") or []
        if identity_source:
            picked_loras = [l for l in picked_loras
                            if lora_profile(l.get("name", ""))["family"] == "krea2"]
        if picked_loras:
            args["loras"] = [f"{l['name']}:{l['strength']}" for l in picked_loras]
    if opts.get("aspect"):
        args["aspect"] = opts["aspect"]
    if opts.get("mp"):
        args["mp"] = opts["mp"]
    # Identity Edit's likeness dials ride like the canvas: present = the user
    # moved one, absent = the recipe default. They mean nothing to any other
    # graph, so they are read only when an identity source is driving, and a
    # bad value degrades to the recipe constant rather than killing the turn.
    # They apply over a saved style's file exactly like the composer's LoRA
    # stack does - a style carrying dials is out of scope (brief 9.14).
    if identity_source:
        for dial in RECIPE_SPECS["identity_edit"].get("dials", ()):
            if dial["key"] in opts:
                args[dial["key"]] = recipe_dial_value(dial, opts.get(dial["key"]))
    # The held seed is deliberately NOT applied here - see freeze_seed().
    return recipe


def freeze_seed(args, opts):
    """Apply the composer's held seed. Must be the LAST thing before submit.

    It cannot live in _apply_opts, because a `seed` in args before the brain's
    turn is resolved means something entirely different: the brain pinning a
    prior composition. That meaning makes the turn look the seed up in the
    ledger, inherit that job's whole spec, and hard-refuse a scene that has not
    changed ("same seed + same scene re-renders the SAME image"). A frozen seed
    is the opposite intent - the user holding the dice steady WHILE they change
    a LoRA or a model - so it must not trip any of that. submit pops "seed"
    before it filters by the builder signature, so this rides every template.
    """
    frozen = held_seed(opts)
    if frozen:
        args["seed"] = frozen

_RENDER_INTENT = re.compile(
    r"\b(render|generate|make|draw|create|shoot|show|edit|change|another|again|"
    r"image|photo|pic|shot|portrait|illustration|painting|video|clip|visual)\b", re.I)
_PLEASANTRY = (
    r"(?:hey|hi|hello|hiya|yo|sup|good\s+(?:morning|afternoon|evening)|"
    r"thanks|thank\s+you|thx|nice|cool|great|okay|ok|yes|yep|yeah|no|nope|"
    r"lol|haha|perfect|awesome|btw|got\s+it|sounds\s+good|wait|hold\s+on|"
    r"one\s+(?:moment|second)|really|wow|ready|better|amazing|beautiful|"
    r"love\s+it|nailed\s+it|much\s+better)"
    r"(?:\s+(?:there|pixal|sol|kimi))?")
# A pleasantry SEQUENCE, not a single token: "cool thanks" and "ok great" used
# to fall through the whole cascade and land on _BARE_VISUAL_PROMPT, which read
# them as a prompt and offered generate on a compliment.
_CHAT_ONLY = re.compile(r"(?:" + _PLEASANTRY + r"[!?.,\s]*)+", re.I)
# Real turns open with an interjection - "perfect!!!! now can you...", "Hey kimi
# I need to...", "better! the girls...". Every pattern below is anchored with
# .match, so a lead-in of any kind sent the turn straight to the bare-prompt
# fallback, where a question mark killed it. Three of the failures in
# chats/ce52340c.json are exactly this. Strip the lead-in, then classify.
_LEAD_FILLER = re.compile(
    r"^\s*(?:" + _PLEASANTRY + r"|now|so|also|then|alright|right|actually|"
    r"anyway|oh|ah|hmm+|umm*|uhh*|dude|man)\b[\s,!?.:;-]*", re.I)
# A request can sit in any clause, not only the first: "the girls dont have
# pants on - can you give them 80's clothing?" is a render request whose verb
# is in clause two.
_CLAUSE_SPLIT = re.compile(r"[.;!?]+|\s+[-–—]\s+|"
                           r",\s*(?=(?:can|could|would|will|please|and|but|then)\b)", re.I)
_REQUEST_PREFIX = re.compile(
    r"^\s*(?:(?:can|could|would|will)\s+(?:you|we)\s+)?(?:please\s+)?(?:just\s+)?",
    re.I)
_RENDER_VERB_LEAD = re.compile(
    r"^(?:render|generate|draw|create|shoot|show(?:\s+me)?|make(?:\s+me)?|"
    r"edit|change|redo|reroll|animate|give|put|dress|swap)\b", re.I)
# "title card" / "movie poster" are IMAGES; _PRODUCT_TERMS lists "card" because
# of the UI's job cards and hover cards. Mask the visual compounds before the
# product guard runs, or "an 80's movie title card" reads as a UI request.
_VISUAL_COMPOUND = re.compile(
    r"\b(?:title|movie|poster|trading|greeting|birthday|index|tarot|playing|"
    r"post|score|report|flash|lobby|credit)\s+cards?\b", re.I)
# A bare "anime" ask belongs to Anima; the clear-anime Z-Image profile is the
# by-name choice. The director prompt says so, but the prompt alone does not
# hold: with one earlier anime render in the same chat, Qwen3-VL-4B copies its
# own prior tool call and every later anime ask lands on the wrong family (two
# in a row, 2026-08-15). Only the words below buy the Z-Image profile.
_CLEAR_ANIME = re.compile(r"\bclear[\s_-]?anime\b|\bz[\s-]?image\b|\bzimage\b", re.I)
_RENDER_NEGATION = re.compile(
    r"(?:\b(?:do\s+not|don'?t|dont|never)\s+(?:render|generate|create|queue)\b|"
    r"\b(?:do\s+not|don'?t|dont)\s+make\s+(?:me\s+)?(?:an?\s+)?"
    r"(?:image|photo|picture|render|video|anything)\b|"
    r"\bi\s+(?:do\s+not|don'?t|dont)\s+want\s+(?:an?\s+)?"
    r"(?:image|photo|picture|render|video)\b|"
    r"\b(?:render|generate|create|queue|image|photo|video)\b.{0,24}\bnot\s+yet\b|"
    # "describe X - no render, just tell me what you see" queued a render
    # (2026-08-13): the bare "no <thing>" and "just tell me/describe" forms
    # are negations too, not only the verb-led ones above.
    r"\bno\s+render(?:s|ing)?\b|"
    r"\bjust\s+(?:tell\s+me|describe|explain)\b)", re.I)
_PRODUCT_CHANGE = re.compile(
    r"\s*(?:(?:can|could|would|will)\s+(?:you|we)\s+)?(?:please\s+)?"
    r"(?:make|fix|change|edit|add|remove|install|update|move|delete)\s+"
    r"(?:(?:the|this|that|my|our)\s+)?(?:pixal|comfyui|ui|interface|system|"
    r"workflow|node|lora|toggle|button|popover|setting|recipe|project|github|"
    r"directory|chat|prompt\s+enhance|icon|widget|card|corner\s+radius)\b", re.I)
_EXPLICIT_RENDER_REQUEST = re.compile(
    r"\s*(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"
    r"(?:render|generate|draw|create|shoot|show(?:\s+me)?|make(?:\s+me)?|"
    r"edit|change|redo|reroll|animate)\b", re.I)
_VISUAL_DIRECTIVE = re.compile(
    r"\s*(?:please\s+)?(?:have|put|place|pose|dress|give|swap|move)\s+"
    r"(?:her|him|them|it|the\s+\w+)\b", re.I)
_ASSISTANT_REQUEST = re.compile(
    r"\s*(?:can|could|would|will)\s+you\b", re.I)
_DIRECT_VISUAL_WANT = re.compile(
    r"\s*i\s+(?:just\s+)?want\b", re.I)
_VISUAL_DESIRE = re.compile(
    r"\s*i\s+(?:(?:just\s+)?(?:want|need)|would\s+(?:like|love))\s+"
    r"(?:to\s+(?:see|make|create|render|draw|shoot|build)\b|"
    r"(?:an?|some|the|this|that)\b)", re.I)
_VISUAL_COPULA = re.compile(
    r"\s*(?!(?:i|we|you|my|our|your|this|that|these|those)\b).+?"
    r"\b(?:is|are|was|were)\s+(?:sitting|standing|lying|kneeling|crouching|"
    r"walking|running|flying|riding|dancing|wearing|holding|carrying|facing|"
    r"looking|leaning|posing|smiling|turning|moving)\b", re.I)
_CONTEXTUAL_VISUAL_WANT = re.compile(
    r"\s*i\s+(?:just\s+)?want\s+(?:her|him|them|it)\b", re.I)
_SELF_CAPABILITY_QUESTION = re.compile(
    r"\s*(?:can|could|may|should|would)\s+i\b", re.I)
_CHAT_REQUEST = re.compile(
    r"\s*(?:tell\s+me\b|explain\b|help\s+me\s+(?:understand|with)\b|"
    r"talk\s+(?:to\s+me|about)\b|let'?s\s+(?:talk|discuss)\b|"
    r"i\s+(?:have|got)\s+(?:a\s+)?question\b|what\s+do\s+you\s+think\b)", re.I)
_ITERATION_QUESTION = re.compile(
    r"\s*(?:(?:what|how)\s+about\b|(?:maybe|perhaps)\b|"
    r"(?:can|could|would|should)\s+(?:she|he|they|it|we|the\s+\w+)\b)", re.I)
_ITERATION_STATEMENT = re.compile(
    r"\s*(?:i\s+think|maybe|perhaps)\s+"
    r"(?:(?:she|he|they|it|we|the\s+\w+)\s+(?:should|could|would)\b|"
    r".+\b(?:would|could)\s+be\s+(?:better|stronger|nicer)\b)", re.I)
_FEEDBACK_CHAT = re.compile(
    r"\s*(?:(?:so|also)\s+)?(?:i(?:'m|\s+am)\s+just\b|"
    r"i\s+(?:think|mean|wonder|noticed|like|love|"
    r"just\b|still\b|added\b|installed\b|usually\b|know\b)|"
    r"looking\s+(?:good|great|nice)\b|"
    r"whatever\s+you\b|it\s+(?:was|is|looks?|looked|works?|worked|feels?)\b|"
    r"that(?:'s|\s+is|\s+looks?|\s+looked|\s+works?|\s+worked)\b|"
    r"this\s+(?:is|looks?|looked|works?|worked|feels?)\b|"
    r"(?:these|those)\s+(?:images?|renders?|outputs?|results?)\b|"
    r"(?:please\s+)?be\s+careful\b|by\s+the\s+way\b)", re.I)
_PRODUCT_STATEMENT = re.compile(
    r"\s*(?:(?:this|that|the|these|those)\s+)?(?:pixal|comfyui|workflows?|nodes?|"
    r"models?|systems?|loras?|toggles?|popovers?|interfaces?|ui|recipes?|prompt\s+enhance|"
    r"z-?image|icons?|widgets?|cards?)\b", re.I)
_PERSONAL_CHAT = re.compile(
    r"\s*(?:i(?:'m|\s+am)\s+(?:having|feeling|doing|not\s+sure)\b|"
    r"i\s+was\s+(?:thinking|wondering|asking|talking)\b|"
    r"i\s+(?:feel|felt|hope|guess|suppose|remember|forgot|agree|disagree)\b|"
    r"eventually\s+i\b)", re.I)
_PRODUCT_CHAT = re.compile(
    r"\s*(?:why\b|how\b|what\b|which\b|where\b|"
    r"when\b|who\b|is\s+(?:it|there|this|that)\b|are\s+(?:you|there)\b|"
    r"do\s+you\b|does\b|did\b)", re.I)
_PRODUCT_TERMS = re.compile(
    r"\b(?:pixal|comfyui|workflows?|node|lora|toggle|button|popover|setting|"
    r"interface|ui|chat|model|system|recipe|project|github|install|directory|"
    r"prompt\s+enhance|talking|helpful|icon|widget|card|corner\s+radius)\b", re.I)
_BARE_VISUAL_PROMPT = re.compile(
    r"\s*(?=.{2,}\Z)(?!.*\?)"
    r"(?!(?:i|i['’]?m|we|we['’]?re|you|my|our|your)\b)"
    # A demonstrative can open either a VERDICT on the last render ("that worked",
    # "this is broken") or the SUBJECT of the next one ("this girl on a sports
    # bike in Arizona"). Only the verdict is chat, and what separates them is the
    # word right after: a finite verb judges, a noun describes. Blocking every
    # demonstrative made "this girl ..." - the most natural way to keep directing
    # the same character - permanently unrenderable, so it always needed a
    # follow-up "show me".
    r"(?!(?:this|that|these|those)\s+(?:is|are|was|were|isn|aren|wasn|weren|"
    r"looks?|looked|seems?|seemed|feels?|felt|works?|worked|helps?|helped|"
    r"did|does|didn|doesn|will|won|has|have|had|hasn|haven|"
    r"broke|broken|failed|fixed|makes?|made|means?|meant)\b)"
    r"(?!.*\b(?:am|is|are|was|were|want|wants|wanted|need|needs|needed|"
    r"think|thinks|thought|know|knows|knew|feel|feels|felt|seem|seems|seemed|"
    r"found|closed|finished|done|testing)\b).+", re.I)


def _has_product_terms(text):
    """Product-term guard with the image compounds masked out first."""
    return bool(_PRODUCT_TERMS.search(_VISUAL_COMPOUND.sub(" ", text or "")))


def _strip_lead_filler(clean):
    """Peel greetings, verdicts and discourse markers off the front of a turn.

    Everything downstream is anchored at position 0, so "perfect!!!! now can
    you make it a film frame?" scored as conversation while "can you make it a
    film frame?" scored as a render. The lead-in carried no intent either way.
    """
    while True:
        peeled = _LEAD_FILLER.sub("", clean, count=1)
        if peeled == clean:
            return clean
        clean = peeled


def _clause_requests_render(clean):
    """An explicit render request in ANY clause, not just the opening one."""
    for clause in _CLAUSE_SPLIT.split(clean):
        clause = " ".join((clause or "").split()).strip()
        if not clause or _PRODUCT_CHANGE.match(clause) or _has_product_terms(clause):
            continue
        if _EXPLICIT_RENDER_REQUEST.match(clause) or _VISUAL_DIRECTIVE.match(clause):
            return True
        # "can you give them 80's clothing" - the politeness prefix hides the verb
        bare = _REQUEST_PREFIX.sub("", clause, count=1)
        if bare != clause and (_RENDER_VERB_LEAD.match(bare)
                               or _VISUAL_DIRECTIVE.match(bare)):
            return True
    return False


def user_wants_render(text, has_visual_context=False):
    """Conservative queue authority for one user turn.

    The model may help shape an idea, but it cannot turn greetings, capability
    questions, or product feedback into GPU work. Prompt-like statements remain
    renderable so terse inputs such as ``a fox in snow`` still work.
    """
    raw = " ".join(str(text or "").split()).strip()
    if not raw or _CHAT_ONLY.fullmatch(raw):
        return False
    # Negations and product edits are judged on the WHOLE turn, before any
    # peeling - "no render, just describe it" must never survive as "describe".
    if _RENDER_NEGATION.search(raw) or _PRODUCT_CHANGE.match(raw):
        return False
    clean = _strip_lead_filler(raw)
    if not clean or _CHAT_ONLY.fullmatch(clean):
        return False
    if _clause_requests_render(clean):
        return True
    if _EXPLICIT_RENDER_REQUEST.match(clean) or _VISUAL_DIRECTIVE.match(clean):
        return True
    # An assistant-directed request without a rendering verb is conversation,
    # even when punctuation is omitted (for example, a request to work faster).
    if _ASSISTANT_REQUEST.match(clean):
        return False
    if _VISUAL_DESIRE.match(clean) and not _has_product_terms(clean):
        return True
    # "I just want" is not inherently idle feedback. A named visual request is
    # actionable on its own; pronoun-led changes require an existing visual.
    if _DIRECT_VISUAL_WANT.match(clean) and not _has_product_terms(clean):
        if _RENDER_INTENT.search(clean) or \
                (has_visual_context and _CONTEXTUAL_VISUAL_WANT.match(clean)):
            return True
    if clean.endswith("?"):
        if _SELF_CAPABILITY_QUESTION.match(clean) or _CHAT_REQUEST.match(clean):
            return False
        # Contextual fragments are a natural way to direct the next iteration;
        # without a prior visual they stay conversational rather than guessing.
        return bool(has_visual_context and _ITERATION_QUESTION.match(clean)
                    and not _has_product_terms(clean))
    if has_visual_context and _ITERATION_STATEMENT.match(clean) and \
            not _has_product_terms(clean):
        return True
    if _CHAT_REQUEST.match(clean):
        return False
    if _FEEDBACK_CHAT.match(clean):
        return False
    if _PRODUCT_STATEMENT.match(clean):
        return False
    if _PERSONAL_CHAT.match(clean):
        return False
    if re.match(r"\s*(?:also\b|we\s+(?:can|could|should|need|used|have|want)\b|"
                r"i\s+(?:added|found|installed|use|have)\b)", clean, re.I) and \
            _has_product_terms(clean):
        return False
    if _PRODUCT_CHAT.match(clean):
        return False
    if _VISUAL_COPULA.match(clean):
        return True
    # Direct prompt fragments generally omit a conversational subject and a
    # finite status verb ("gothic castle at sunset", "red dress"). Everything
    # else stays chat-only unless one of the explicit/contextual rules above
    # granted queue authority.
    return bool(_BARE_VISUAL_PROMPT.fullmatch(clean))


def substantive_redirect(text):
    """A pending scene or an unanswered question makes the NEXT user turn the
    second half of a render request - "so it's in the style of an 80s slasher
    flick" redirects the scene without saying "show me". But the redirect still
    answers to the authorities user_wants_render checks first. Reading it as
    "anything that isn't a question" handed the tool back on "no render, just
    tell me what you see", "thanks", and "tell me a joke" - re-opening from the
    rescue side the exact door 01a7319 closed (2026-08-14)."""
    flat = " ".join((text or "").split()).strip()
    return bool(flat and not flat.endswith("?") and
                not _PRODUCT_CHANGE.match(text) and
                not _PRODUCT_TERMS.search(text) and
                not _RENDER_NEGATION.search(text) and
                not _CHAT_ONLY.fullmatch(flat) and
                not _CHAT_REQUEST.match(flat))


def conversation_has_visual(messages):
    """Whether this chat has a completed/attempted visual to iterate from."""
    for message in messages or ():
        if message.get("role") == "assistant" and _generate_calls(message):
            return True
        content = message.get("content")
        if isinstance(content, str) and ("\"queued\"" in content or
                                         "the server queued that scene" in content):
            return True
    return False


# A person in frame, so the wardrobe policy has something to apply to. Missing
# one is the safe direction: standing=False only skips the lock, and a prompt
# with no word for a person is unlikely to grow an undressed one.
_PERSON_RE = re.compile(
    r"\b(?:wom[ae]n|m[ae]n\b|girl|boy|lady|guy|dude|person|people|couple|"
    r"figure|model|character|someone|somebody|she|her|hers|he|him|his|they|"
    r"them|their|face|portrait|body|hair|skin|hands?|eyes?|smile|"
    r"boyfriend|girlfriend|wife|husband|mother|father|sister|brother|"
    r"knight|soldier|dancer|singer|worker|rider|pilot|nurse|doctor|witch|"
    r"warrior|princess|prince|queen|king|elf|goddess|god\b|anime girl)\b",
    re.I)

# Unambiguous only. A false positive here DROPS the wardrobe lock and the
# fineporn base then undresses a subject the user dressed, which is far worse
# than a false negative - that just reproduces what the brain already does.
_EXPLICIT_RE = re.compile(
    r"\b(?:nude|nudes|naked|topless|bottomless|nsfw|explicit|erotic|porn|"
    r"sex|sexual|fucking|fucks|thrusting|thrusts|penetrat\w*|intercourse|"
    r"blowjob|handjob|cunnilingus|masturbat\w*|orgasm|climax(?:ing)?|"
    r"nipples?|areola|breasts? (?:bare|exposed)|bare breasts?|"
    r"genitals?|penis|cock\b|dick\b|vagina|pussy\b|clit\w*|labia|"
    r"cum\b|cumming|semen|ejaculat\w*|anal\b|blow job)\b", re.I)


def scene_flags(text):
    """(standing, nsfw) for a render with no brain in the path.

    These two are the only things the model used to contribute that the
    composer does not already pin server-side, and both feed one decision:
    whether _character_caption appends the wardrobe lock. Getting them wrong is
    visible - a landscape that ends "She is fully dressed in the clothing
    described above", or an explicit scene the base quietly puts clothes back
    on, which is exactly what happened to job 5c2a717d when the brain guessed
    nsfw=False on an explicit ask.
    """
    body = str(text or "")
    return bool(_PERSON_RE.search(body)), bool(_EXPLICIT_RE.search(body))


def enhance_off_is_prompt(text):
    """With Prompt enhance OFF, a paragraph is a prompt.

    This is deliberately NOT another English heuristic bolted onto
    user_wants_render - it is a statement about MODE. Turning the prompt writer
    off is the user saying they will write the prompts themselves, and the thing
    people type a paragraph of in that mode is a scene.

    It exists because user_wants_render scored a 717-character scene as
    conversation (chat 629d1c68, 2026-08-18): _VISUAL_COPULA rescues "sitting"
    but not "seated", and _BARE_VISUAL_PROMPT refuses any turn containing the
    word "is". Patching those regexes again would be the fifth pass over the
    same ground; this sidesteps them in the one mode where the answer is not
    genuinely ambiguous, and leaves the classifier untouched for enhance-ON
    turns where the brain really is being asked to converse.

    The three exclusions are the turns a paragraph is NOT a prompt: a question,
    a request to change the product, and an explicit "don't render".
    """
    body = " ".join(str(text or "").split()).strip()
    if len(body.split()) < 25 or "?" in body:
        return False
    return not (_PRODUCT_CHANGE.match(body) or _RENDER_NEGATION.search(body)
                or _CHAT_ONLY.fullmatch(body))


def captured_prompt(convo, current_text):
    """The user's own words to render, for a Prompt-enhance-off turn.

    Normally that is the current turn. But an accept turn - "show me",
    "generate", "go" - is the user saying YES to a prompt they already typed,
    not a new prompt, and rendering those two words is exactly what produced a
    card reading "generate" (chat 629d1c68, 2026-08-18). So a command-shaped
    turn reaches back for the last turn that actually carried a prompt.

    Derived from convo rather than stored, so a resumed chat and a reloaded tab
    behave the same as a live one and there is no second copy to fall stale.
    """
    text = " ".join(str(current_text or "").split()).strip()
    if text and not scene_is_command(text):
        return text
    for message in reversed(convo):
        if message.get("role") != "user":
            continue
        body = message.get("content")
        if isinstance(body, list):
            body = " ".join(part.get("text", "") for part in body
                            if isinstance(part, dict) and part.get("type") == "text")
        # Same split the turn itself uses, so a captured prompt never carries
        # the composer block appended to it - plus [SYSTEM, because the queue
        # receipts this server appends after a render carry role "user" so the
        # brain can see one happened. That makes them indistinguishable from
        # something a person typed, and walking back onto one rendered a
        # picture of the words "[SYSTEM: the server queued that prompt as job
        # 8bbda870 ...]" (2026-08-18, first live pass over this path).
        # CINEMATIC/STYLE too: craft direction the composer appended, not the
        # user's words - left in, the direct-render path encoded "thanks!
        # [CINEMATIC: ON. Shoot this as a film frame ...]" verbatim.
        body = re.split(r"\[(?:COMPOSER|CHARACTER ANCHOR|PRIOR RENDER|SYSTEM|NOTE|CINEMATIC|STYLE)",
                        str(body or ""))[0]
        body = " ".join(_WITHHELD_NOTE_RE.sub("", body).split()).strip()
        if body and not scene_is_command(body):
            return body
    return text


def _direct_prompt_scene(user_text, brain_scene, has_vision_refs=False):
    """Keep direct text immutable while retaining a vision-derived suffix.

    Reference images are intentionally materialized into scene prose so rerolls
    keep their visual constraints. A brain that rewrites the user's prefix loses
    that suffix rather than silently defeating Prompt Enhance OFF.
    """
    raw = str(user_text or "").strip()
    candidate = str(brain_scene or "").strip()
    if not raw or not has_vision_refs or not candidate.startswith(raw):
        return raw
    suffix = candidate[len(raw):]
    if suffix and suffix[0].isalnum():
        return raw
    return candidate


async def kimi_reply(cid, user_msg, convo, opts=None):
    """Turn wrapper: honor the local_keep toggle when the LAST live turn ends
    (never between tool rounds or under a concurrent turn - that kills a server
    someone else is mid-conversation with)."""
    _turn_start()
    try:
        await _kimi_reply(cid, user_msg, convo, opts)
    except Exception as e:
        # Composer validation lives outside HUB.submit, so surface an honest
        # lane error instead of leaving a failed background task "thinking".
        # ValueError was the known case but too narrow: llm_call's HTTP POST,
        # the 180s brain timeout and a proxy's HTML 502 raise ClientError /
        # asyncio.TimeoutError / ContentTypeError, which escaped into the
        # background task and died there - the lane got "thinking" and then
        # nothing, forever. (CancelledError is BaseException, so a stop still
        # propagates.)
        HUB.broadcast(type="thinkingdone", cid=cid)
        HUB.broadcast(type="error", cid=cid, message=str(e))
    finally:
        _turn_end()

# A withheld-generate note is true only for the turn it rode in on. Left in the
# persisted history it would read as "rendering is still closed" on every later
# turn - the exact belief this whole change exists to prevent - so it is scrubbed
# out of convo at the top of each turn, the same way base64 refs are.
_WITHHELD_NOTE_RE = re.compile(r"\n\n\[NOTE - THIS TURN ONLY:.*?\]", re.S)


async def _kimi_reply(cid, user_msg, convo, opts=None):
    # API brains (Kimi & co, the SFW side) keep the full directing contract.
    # The LOCAL brain is the NSFW side: compact writer's brief, minimal tool,
    # and the composer's technical picks overlaid server-side (a 4B echoing
    # file names is how graphs silently die).
    local_brain = f"127.0.0.1:{LOCAL_LLM_PORT}" in load_config()["llm"]["base_url"]
    prompt_enhance = True
    if opts:
        if "prompt_enhance" in opts and not isinstance(opts["prompt_enhance"], bool):
            raise ValueError("prompt_enhance must be boolean")
        prompt_enhance = opts.get("prompt_enhance") is not False
        # Validate identity sources before paying for a cloud/local brain turn.
        # The same overlay is applied again to the eventual generate call.
        _apply_opts({}, opts)
    # render intent from the user's OWN words (directive blocks stripped) - small
    # local models sometimes print the finished prompt as chat instead of calling
    # generate; when the user clearly asked for an image, the server rescues it.
    _utext = user_msg.get("content")
    if isinstance(_utext, list):
        _utext = " ".join(p.get("text", "") for p in _utext if p.get("type") == "text")
    # PRIOR RENDER included: only the composer blocks were split off, so a
    # turn whose directive carried no composer block fed the render-intent
    # regexes the server's own [PRIOR RENDER ...] prose as user words.
    # CINEMATIC/STYLE are the same miss, found later: they ride the turn as
    # craft direction OUTSIDE the composer block, and the directive's own
    # "Shoot this as a film frame" matches the explicit-render regex - a bare
    # "thanks!" classified as a render request.
    _utext = re.split(r"\[(?:COMPOSER|CHARACTER ANCHOR|PRIOR RENDER|CINEMATIC|STYLE)", _utext or "")[0]
    current_content = user_msg.get("content")
    # The gate is vision CAPABILITY, not lane. This read `not local_brain` for
    # as long as the managed llama.cpp server had no projector wired: refs
    # flattened to "[attached image]" before the model saw them, so letting the
    # local brain claim it had read a reference produced confident fiction. A
    # Qwen3-VL brain spawned with an mmproj genuinely reads them (2026-08-18),
    # and _delocalize keeps the image parts intact on exactly the same test.
    brain_sees = (not local_brain) or bool(_llm_state().get("mmproj"))
    has_vision_refs = brain_sees and isinstance(current_content, list) and any(
        p.get("type") == "image_url" for p in current_content
    )
    local_iteration = bool(_LOCAL_ITERATION_RE.search(_utext) or
                           _REFERS_BACK_RE.search(_utext))
    # Anything the assistant left hanging - a written scene OR a question -
    # makes the next user turn the second half of a render request, whatever
    # its words look like alone. Two shapes, one rule: a bare "yes"/"show me"
    # ACCEPTS the pending scene, and anything substantive that is not a
    # question REDIRECTS it. The redirect half used to apply only to pending
    # questions, so "so it's in the style of an 80s slasher flick" after a
    # written-out scene read as chat, generate was withheld, and the brain
    # then told Jesse - accurately - that it had no render tool. He had to
    # type "show me" to get it back (2026-08-13).
    _substantive = substantive_redirect(_utext)
    render_intent = user_wants_render(_utext, conversation_has_visual(convo)) or \
        bool(_pending_scene(convo) and (_AFFIRMATIVE.match(_utext.strip()) or
                                        _substantive)) or \
        bool(_pending_question(convo) and (_AFFIRMATIVE.match(_utext.strip()) or
                                           _substantive))
    nudged = rendered = False    # rescue arms only until SOMETHING got queued
    verbatim_bounces = 0         # cloud brains get ONE corrective error before
                                 # the server repairs the scene mechanically
    # list_models is a lookup, not work, and it has to stay cheap in ROUNDS.
    # kimi-k3 walked the entire catalog one kind at a time - checkpoints, loras,
    # upscalers, text encoders, controlnets, vaes - eight calls, no render, and
    # the turn died on "too many tool rounds" (2026-08-13). Two looks is
    # generous: the composer already pins the model, and the loras it may use
    # arrive in the constraints block.
    listings = 0
    for m in convo:                      # base64 refs are for THIS turn; don't resend them forever
        if isinstance(m.get("content"), list):
            m["content"] = [{"type": "text", "text": "[reference image]"}
                            if p.get("type") == "image_url" else p for p in m["content"]]
            for p in m["content"]:
                if p.get("type") == "text":
                    p["text"] = _WITHHELD_NOTE_RE.sub("", p.get("text") or "")
        elif isinstance(m.get("content"), str):
            m["content"] = _WITHHELD_NOTE_RE.sub("", m["content"])
    # entropy rides the USER turn, never the system prompt: Moonshot's context
    # cache is prefix-keyed, so a system message that changes per call forces a
    # full re-read of SYSTEM + history every round (measured as the k3 lag).
    # NEVER on the local lane - small models take the tag words as literal scene
    # elements and weld them into the prompt (horse trailers on the beach).
    # And never on an ask that already describes a scene: the big brains leaked it
    # the same way, just more tastefully (a third of the territories are after
    # dark, so "night market stall" became neon signage on a daylit NYC street).
    # A rule telling the model to ignore the tag was already there and was not
    # enough - the tag it cannot see cannot leak.
    if not local_brain and prompt_enhance and ask_is_open(_utext):
        tag = f"\n\n[entropy: {', '.join(random.sample(ENTROPY, 3))}]"
        if isinstance(user_msg.get("content"), list):
            for p in reversed(user_msg["content"]):
                if p.get("type") == "text":
                    p["text"] += tag
                    break
        else:
            user_msg["content"] = (user_msg.get("content") or "") + tag
    # Name the withholding instead of letting the tool silently vanish. Three
    # turns in chats/ce52340c.json died on this: the composer block in the
    # user's OWN message ordered the brain to pass generate() arguments while
    # generate was absent from its tool list, and with no sanctioned move it
    # improvised - repeated list_models, then upscale/review/animate on the
    # user's render, then a markdown spec-dump saying the render button was
    # broken. Rides the USER turn for the same reason entropy does: the system
    # prefix has to stay byte-stable for Moonshot's cache. Cloud lane only -
    # the local writer welds stray bracket text into the scene.
    if not local_brain and not render_intent:
        note = ("\n\n[NOTE - THIS TURN ONLY: generate is not offered, because the server "
                "scored this turn as conversation. Any composer constraints above apply "
                "to the next render turn, not this one. No other tool can start a render. "
                "If an image is plainly what they want, write out the full scene you "
                "would render - they must SEE the prompt, in plain prose, no tool syntax "
                "- then close with one short line like 'say go and I'll fire it'. Never "
                "reply with only the invitation, and do not report that rendering is "
                "broken.]")
        content = user_msg.get("content")
        if isinstance(content, list):
            for p in reversed(content):
                if p.get("type") == "text":
                    p["text"] += note
                    break
            else:
                content.append({"type": "text", "text": note})
        else:
            user_msg["content"] = (content or "") + note
    current_user_index = len(convo)
    convo.append(user_msg)
    # ---- Prompt enhance OFF: the user's words ARE the prompt ----------------
    # Jesse's requirement, in his words: "I want the prompt without enhance to
    # pass directly through to the clip prompt text encode." What this used to
    # do instead was swap the policy text, call the brain anyway, and substitute
    # the turn text afterwards - so every prompt still went through a 4B, and a
    # 4B that reached for a withheld tool put the word "generate" on the card
    # (629d1c68). Nothing in the path now: captured text straight to submit.
    #
    # Held back in the two cases that genuinely need the model:
    #   iteration ("make her jacket red") has to be merged into the prior scene;
    #     rendering those four words as the whole prompt is not what anybody
    #     means by passing it through.
    #   attached references are read into the scene as prose so a re-roll keeps
    #     their constraints (see _direct_prompt_scene). Cloud lane only -
    #     has_vision_refs is False on the local one by construction.
    if not prompt_enhance and not local_iteration and not has_vision_refs \
            and (render_intent or enhance_off_is_prompt(_utext)):
        args = {}
        template = (_apply_opts(args, opts) if opts else None) or "realism"
        # The brain is not here to set these, and their default (a person, kept
        # clothed) rewrites the end of the user's own sentence.
        scene_for_flags = captured_prompt(convo, _utext)
        standing, detected = scene_flags(scene_for_flags)
        mode = load_config().get("explicit") or "auto"
        args.setdefault("standing", standing)
        args.setdefault("nsfw", detected if mode == "auto" else mode == "on")
        freeze_seed(args, opts)
        HUB.broadcast(type="text", cid=cid,
                      text="Got it \u2014 rendering your prompt exactly as written.")
        HUB.broadcast(type="thinking", cid=cid,
                      note="writing the workflow - " + template)
        job = await HUB.submit(cid, "chat", template,
                               scene_for_flags, args, 1, verbatim=True)
        if not job["error"]:
            # Keep history coherent for the NEXT turn, exactly as the tool path
            # does - the brain has to know a render happened without being told
            # to reply about it.
            convo.append({"role": "user", "content":
                          f"[SYSTEM: the server queued that prompt as job "
                          f"{job['id']} ({template}) - no reply needed.]"})
        HUB.broadcast(type="thinkingdone", cid=cid)
        return
    # name the invisible phase: this is a cloud call, not the GPU working
    HUB.broadcast(type="thinking", cid=cid, note=f"asking {brain_name()} to direct the shot")
    base_prompt, base_tools = (SYSTEM_LOCAL, TOOLS_LOCAL) if local_brain else (SYSTEM, TOOLS)
    enhance_policy = PROMPT_ENHANCE_ON_POLICY if prompt_enhance else \
        PROMPT_ENHANCE_OFF_POLICY
    sys_prompt = base_prompt + TURN_POLICY + enhance_policy
    # Withhold generate on conversational turns for clean behavior. The queue
    # guard below remains authoritative against a raw/hallucinated tool call.
    #
    # NOT on the local lane. The compensating [NOTE - THIS TURN ONLY ...] above
    # is cloud-only (bracket text welds itself into a small model's scene), so a
    # 4B saw SYSTEM_LOCAL and PROMPT_ENHANCE_OFF_POLICY both demanding generate
    # while the tool had silently vanished from its list - and resolved the
    # contradiction by printing the tool's NAME as prose, six times in one chat
    # (629d1c68). The guard below refuses a wrongly-called generate with a
    # sentence the model can act on: the same protection, with a voice.
    tools = base_tools if (render_intent or local_brain) else [
        tool for tool in base_tools
        if tool.get("function", {}).get("name") != "generate"
    ]
    for _ in range(8):
            history = local_history_view(
                convo, current_user_index, preserve_latest_render=local_iteration
            ) if local_brain else convo
            status, data = await llm_call([{"role": "system", "content": sys_prompt}] + history,
                                          tools=tools, cid=cid)
            if "choices" not in data:
                HUB.broadcast(type="thinkingdone", cid=cid)
                HUB.broadcast(type="error", cid=cid,
                              message=f"{brain_name()}: {data.get('error', data)}")
                return
            msg = data["choices"][0]["message"]
            convo.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                # Strip before ANYTHING reads it. On this path scene_text becomes
                # both the lane text and the rendered prompt, so a small brain
                # that echoes its own [COMPOSER: ...] brief would otherwise ship
                # the brief to the sampler and print it to the user as prose.
                # The tool-call path below already strips; this one did not.
                # The label comes off here too: SYSTEM_LOCAL tells the writer to
                # "write EDIT instructions" for identity_edit and a 4B reads that
                # as a heading, so its replies open "EDIT: <scene>".
                scene_text = _SCENE_LABEL_RE.sub(
                    "", _strip_history_directives(msg.get("content") or "")).strip()
                looks_like_scene = len(scene_text.split()) >= 30 and "?" not in scene_text
                # not on an iteration turn: "make her jacket red" is an
                # instruction, and the scene has to stay the brain's merge of it
                # into the prior one.
                direct_prompt = render_intent and not prompt_enhance \
                    and not local_iteration
                if render_intent and not rendered and (direct_prompt or
                                                       (local_brain and looks_like_scene)):
                    # the model wrote the scene as prose - the server renders it
                    # directly. (A "call the tool properly" nudge round was tried
                    # and cut: identical outcome, one full model round slower.)
                    render_scene = _scene_from_prose(scene_text) if prompt_enhance \
                        else _direct_prompt_scene(captured_prompt(convo, _utext),
                                                  scene_text, has_vision_refs)
                    args = {}
                    template = (_apply_opts(args, opts) if opts else None) or "realism"
                    render_scene = strip_seed_prose(
                        scrub_style_caption(render_scene, template))
                    # In direct mode the user's exact prompt is already visible
                    # in the lane. Keep the model-authored acknowledgement (when
                    # it supplied one) instead of echoing the prompt as Pixal.
                    display_text = scene_text if direct_prompt else render_scene
                    if display_text:
                        HUB.broadcast(type="text", cid=cid, text=display_text)
                    HUB.broadcast(type="thinking", cid=cid,
                                  note="writing the workflow - " + template)
                    freeze_seed(args, opts)
                    job = await HUB.submit(cid, "chat", template, render_scene, args, 1)
                    if not job["error"]:
                        # Keep history coherent for the NEXT turn, but only when
                        # Comfy actually accepted the graph. HUB.submit already
                        # broadcasts the concrete failure when submission fails.
                        convo.append({"role": "user", "content":
                                      f"[SYSTEM: the server queued that scene as job "
                                      f"{job['id']} ({template}) - no reply needed.]"})
                    HUB.broadcast(type="thinkingdone", cid=cid)
                    return
                HUB.broadcast(type="thinkingdone", cid=cid)
                # Two different failures land here and they used to share one
                # reply. scene_is_command("") is True on purpose - scene_gate
                # needs "empty is not renderable" - so a turn the scrubbers
                # emptied looked exactly like a model printing "generate".
                #
                # It is not the same thing. The local writer sometimes answers
                # with NOTHING BUT its own brief echoed back: [COMPOSER ...],
                # [CHARACTER ... Look: <the scene it actually wrote>], and
                # [ATTACHED IMAGES ...]. Every one of those is machinery, the
                # scrubbers correctly take all of it, and the turn goes empty -
                # so Pixal answered "tell me what you'd like to see" one line
                # after Jesse had said exactly what he wanted, twice in a row,
                # and rendered nothing either time (2026-08-23, chat log).
                # Blaming the user for the writer's failure is the bug.
                echoed_brief = bool((msg.get("content") or "").strip()) \
                    and not scene_text
                if echoed_brief:
                    HUB.broadcast(type="text", cid=cid, text=(
                        "*the writer answered with its own brief instead of a "
                        "scene, so there was nothing to render \u2014 say that "
                        "again and I'll retry*"))
                    return
                # A model that wanted a tool it could not reach prints the tool's
                # NAME as prose - six times in one chat before the local lane
                # stopped having generate withheld. It is never Pixal's reply.
                if scene_is_command(scene_text):
                    HUB.broadcast(type="text", cid=cid, text=(
                        "Tell me what you'd like to see and I'll render it \u2014 "
                        "or say \u201cgo\u201d to run the last prompt you wrote."))
                    return
                # The local writer routinely prints the finished scene as chat
                # instead of calling generate. Present that as the offer it
                # actually is: the user should not have to guess that typing
                # "show me" is what turns this into a picture.
                if looks_like_scene:
                    HUB.broadcast(type="text", cid=cid, text=(
                        "Got it \u2014 here\u2019s the prompt I\u2019d render:\n\n"
                        + scene_text +
                        "\n\nWant me to run it? Say \u201cgo\u201d, or tell me "
                        "what to change."))
                    return
                HUB.broadcast(type="text", cid=cid, text=scene_text)
                return
            said = _SCENE_LABEL_RE.sub(
                "", _strip_history_directives(msg.get("content") or "")).strip()
            # It called the tool AND printed the tool's name; only the call counts.
            if said and not scene_is_command(said):
                HUB.broadcast(type="text", cid=cid, text=said)
            for call in calls:
                fn, args = call["function"]["name"], call["function"].get("arguments") or "{}"
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
                if fn == "list_models":
                    listings += 1
                    if listings > 2:
                        result = {"error": (
                            "You have already listed the catalog twice this turn. "
                            "Stop looking and act: the model, LoRAs and canvas are "
                            "pinned by the composer's hard constraints, so pass "
                            "those through verbatim and call generate now.")}
                    else:
                        files = sorted(e["rel"]
                                       for e in model_catalog(args.get("kind", "loras")))
                        result = {"files": files[:200]}
                elif fn == "generate":
                    if not render_intent:
                        # This used to assert "The user did not request a render",
                        # which is false on every MISclassified turn - and it was
                        # false on all three of them in chats/ce52340c.json. The
                        # one diagnostic the brain can reach must not gaslight it.
                        result = {"error": (
                            "The server scored this turn as conversation, so generate is "
                            "closed for it. If the user plainly asked for an image, reply "
                            "with the exact scene you just tried to render, as plain prose "
                            "they can read, then close with one short line ('say go and "
                            "I'll fire it'). Never reply with only the invitation - the "
                            "user must see the scene. Otherwise reply in plain chat. Do not "
                            "call list_models, animate, review or upscale as a substitute.")}
                    else:
                        template = args.pop("template", "realism")
                        # Small local brains sometimes echo the server's own
                        # [COMPOSER: ...] brief back inside the scene they write,
                        # which then ships to the sampler and into the ledger as
                        # if the user had asked for it.
                        scene = _strip_history_directives(args.pop("scene", ""))
                        if not prompt_enhance and not local_iteration:
                            # The captured prompt, never the literal turn: on an
                            # accept turn the literal turn is the word "generate".
                            # Skipped for iteration, where the brain's merge of
                            # the change into the prior scene IS the prompt.
                            scene = _direct_prompt_scene(
                                captured_prompt(convo, _utext), scene, has_vision_refs)
                        count = min(int(args.pop("count", 1) or 1), 4)
                        # A brain-passed seed pins a small change to the prior
                        # composition. Coerce here: submit int()s it OUTSIDE its
                        # error handling, so "same" as a seed would kill the task.
                        try:
                            if "seed" in args:
                                args["seed"] = int(args["seed"])
                        except (TypeError, ValueError):
                            args.pop("seed", None)
                        # Small brains invent anchor ids ("attached image 1")
                        # when a ref rides along; the composer's real pick is
                        # overlaid by _apply_opts below either way.
                        if args.get("character") and \
                                not resolve_character(args["character"]):
                            args.pop("character")
                        pinned = _apply_opts(args, opts) if opts else None
                        template = pinned or template
                        # The composer's pin is authoritative - a Z-Image base
                        # with style=anime really is the clear-anime profile.
                        # An unpinned "anime" is the brain's own choice, and it
                        # only stands if the user named that look.
                        if template == "anime" and not pinned \
                                and not _CLEAR_ANIME.search(_utext or ""):
                            template = "anima"
                        scene = strip_seed_prose(scrub_style_caption(scene, template))
                        # A passed seed means "hold that composition" - but the
                        # brain sometimes copies the prior scene verbatim without
                        # editing the change in, and same seed + same scene is
                        # pixel-identical (4 jobs, 1 unique scene, seed 3093...386).
                        # A seed with no ledger entry is invented, not reused.
                        prior = None
                        if "seed" in args:
                            prior = next(
                                (e for e in HUB.ledger_read()
                                 if e.get("seed") == args["seed"]
                                 and str(e.get("scene") or "").strip()), None)
                        verbatim = bool(
                            prior and _norm_scene(scene) == _norm_scene(prior["scene"]))
                        if verbatim:
                            # Local brains repair immediately - Qwen3-VL-4B
                            # resent the identical call all 8 rounds past the
                            # corrective error. Cloud brains get one round to
                            # do the surgery properly before the same repair.
                            repair = _change_sentence(_utext) \
                                if (local_brain or verbatim_bounces) else ""
                            if repair:
                                scene = scene.rstrip() + " " + repair
                                verbatim = False
                            else:
                                verbatim_bounces += 1
                        if verbatim:
                            result = {"error": (
                                f"scene is identical to render #{prior['id']} - same "
                                f"seed + same scene re-renders the SAME image pixel "
                                f"for pixel. Rewrite the scene with the user's "
                                f"requested change actually edited in (keep the rest "
                                f"word for word), or omit seed for a fresh roll.")}
                        elif template not in BUILDERS or not scene.strip():
                            result = {"error": "bad template or empty scene"}
                        else:
                            if prior:
                                # Same seed on a different graph holds nothing:
                                # the composer's CURRENT model/loras/aspect drift
                                # under a tweak (3 identical-scene renders, 3 lora
                                # plans, seed 2772...624). Rebuild the prior job's
                                # exact spec; only the scene carries the change.
                                #
                                # But the composer's OWN picks still outrank it -
                                # rebuilding blind rendered the old job's aspect
                                # and model after the user had changed both, while
                                # the lane chip still showed the new ones. Re-run
                                # _apply_opts on a fresh dict to get the composer
                                # contribution with nothing brain-invented mixed
                                # in, and lay only that over the prior spec.
                                picked = {}
                                if opts:
                                    _apply_opts(picked, opts)
                                prior_tpl = prior.get("template") or template
                                opts_tpl = effective_recipe(opts) if opts else None
                                if opts_tpl and opts_tpl != prior_tpl:
                                    pass    # composer resolved a different graph;
                                            # the prior spec belongs to another
                                            # builder, so hold nothing from it
                                else:
                                    template = prior_tpl
                                    args = {"seed": args["seed"],
                                            **(prior.get("spec") or {}), **picked}
                                    # _apply_opts enforces these pairs inside its
                                    # own dict; the prior spec can still carry the
                                    # other half of one across the merge.
                                    if "character" in picked:
                                        args.pop("ref", None)
                                    elif "ref" in picked:
                                        args.pop("character", None)
                                    if "lora_plan" in picked:
                                        args.pop("loras", None)
                                    elif "loras" in picked:
                                        args.pop("lora_plan", None)
                                    args = heal_stored_lora_plan(template, args)
                            HUB.broadcast(type="thinking", cid=cid,
                                          note="writing the workflow - " + template)
                            freeze_seed(args, opts)
                            job = await HUB.submit(cid, "chat", template, scene, args, count)
                            rendered = rendered or not job["error"]
                            HUB.broadcast(type="thinking", cid=cid,
                                          note=render_note(template, args, count))
                            # The receipt rides INSIDE the tool result - a system message between
                            # tool_calls and the tool response breaks k3's pairing validation.
                            # No "scene" key: echoing the prompt back is why the
                            # follow-up turn reprinted the whole thing. And the
                            # job is QUEUED, not finished - the model was saying
                            # "Rendered!" before the sampler had a first step.
                            result = ({"queued": job["id"], "template": template,
                                       "seed": job["seed"], "count": count,
                                       "status": ("accepted by the GPU queue - NOT finished. "
                                                  "Do not say rendered, done, ready or here it "
                                                  "is, and do not repeat the prompt. Reply with "
                                                  "ONE short line saying what is now rendering "
                                                  "and that it takes a moment. This turn is "
                                                  "over: call no further tools.")}
                                      if not job["error"] else {"error": job["error"]})
                elif fn in ("animate", "review", "upscale") and not local_brain:
                    # Render actions ride the SAME verified route code the
                    # buttons use; the model only ever contributes a target
                    # and, for animate, the user's own hint words. Not gated
                    # on render_intent - "review that" is a legitimate ask
                    # that is not render intent.
                    target = resolve_action_entry(args.get("id"), convo)
                    if not target:
                        result = {"error": ("no finished render in this chat to act "
                                            "on - generate one first or name a #id")}
                    elif fn == "animate":
                        act = {"id": target, "cid": cid}
                        act.update({k: args[k]
                                    for k in ("engine", "seconds", "hint", "turbo")
                                    if args.get(k) is not None})
                        payload, _ = await _call_action_route(animate, act)
                        result = _action_receipt(fn, target, payload)
                    else:
                        handler = review if fn == "review" else upscale
                        payload, _ = await _call_action_route(
                            handler, {"id": target, "cid": cid})
                        result = _action_receipt(fn, target, payload)
                else:
                    result = {"error": f"unknown tool {fn}"}
                convo.append({"role": "tool", "tool_call_id": call["id"],
                              "content": json.dumps(result, ensure_ascii=False)})
            # Refusing the third listing is not enough on its own - a model
            # determined to browse would spend the remaining rounds collecting
            # refusals. Take the tool away instead, and the only moves left are
            # render or reply.
            if listings >= 2:
                tools = [t for t in tools
                         if (t.get("function") or {}).get("name") != "list_models"]
    HUB.broadcast(type="thinkingdone", cid=cid)
    HUB.broadcast(type="error", cid=cid, message=f"{brain_name()}: too many tool rounds")

# ----------------------------------------------------------------------------- http

async def index(_req):
    # Opening the app IS the intent to use the GPU, so this is where ComfyUI is
    # started - not at sidecar startup, which would drag a 21GB model stack up
    # behind a process that may sit idle all session.
    kick_comfy_boot()
    return web.FileResponse(HERE / "web" / "index.html")

async def manifest(_req):
    return web.FileResponse(HERE / "web" / "manifest.webmanifest")

async def service_worker(_req):
    return web.FileResponse(HERE / "web" / "sw.js",
                            headers={"Content-Type": "application/javascript"})

# Set the moment aiohttp begins shutting down. events() is an infinite loop, and
# aiohttp waits shutdown_timeout for open handlers before it will exit - so on a
# restart the outgoing process (and the cmd wrapper holding sidecar.log) used to
# linger up to a minute while pixal.vbs, which waits only for the port to close,
# had already spawned the replacement into a log it could not open (2026-08-14).
SHUTTING_DOWN = asyncio.Event()


async def on_shutdown(app):
    """Let every SSE stream end itself so the process can actually exit."""
    SHUTTING_DOWN.set()
    for q in list(HUB.subs):
        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass


# A buffering proxy is an INVISIBLE failure for this app: the render runs,
# finishes and saves, while the browser sits on "thinking" forever because not
# one byte of the stream reached it. Measured through a Cloudflare quick tunnel
# on 2026-08-16 - 285 bytes in 8s on loopback, 0 bytes in 15s through the edge,
# with the response HEADERS arriving instantly either way.
#
# Two defences, because the first one is not enough on its own:
#   1. X-Accel-Buffering: no - the header nginx and several CDNs honour.
#      Cloudflare STRIPS it (verified: absent from the proxied response), so it
#      buys nothing there and everything behind an nginx.
#   2. A opening pad. Edges that buffer do it up to a threshold, and this
#      stream's whole opening burst is ~285 bytes, well under it. A ":" line is
#      an SSE COMMENT - the EventSource spec requires clients to ignore it - so
#      a few KB of padding is invisible to the app and forces the flush.
_SSE_PAD = b":" + b" " * 2048 + b"\n\n"


async def events(req):
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                       "Cache-Control": "no-cache, no-transform",
                                       "X-Accel-Buffering": "no",
                                       "Connection": "keep-alive"})
    await resp.prepare(req)
    q = asyncio.Queue(maxsize=500)
    HUB.subs.add(q)
    q.put_nowait({"type": "status", "comfy": HUB.comfy_up})   # snapshots for late joiners
    q.put_nowait({"type": "brain", **brain_badge()})
    if HUB.gpu:
        q.put_nowait({"type": "gpu", **HUB.gpu})
    if HUB.scan:
        q.put_nowait({"type": "scan", **HUB.scan})
    try:
        await resp.write(_SSE_PAD + b": hello\n\n")
        while not SHUTTING_DOWN.is_set():
            try:
                ev = await asyncio.wait_for(q.get(), 20)
                if ev is None:                  # shutdown sentinel - let go
                    break
                await resp.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
            except asyncio.TimeoutError:
                await resp.write(b": ka\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        HUB.subs.discard(q)
    return resp


def _hub_snapshot():
    """The events a fresh client needs to draw the chrome, same three the SSE
    handler seeds a new subscriber with."""
    snap = [{"type": "status", "comfy": HUB.comfy_up},
            {"type": "brain", **brain_badge()}]
    if HUB.gpu:
        snap.append({"type": "gpu", **HUB.gpu})
    if HUB.scan:
        snap.append({"type": "scan", **HUB.scan})
    return snap


async def events_poll(req):
    """The same event feed as /api/events, without holding a connection open.

    SSE is strictly better on a LAN and is still the default. It is also
    unusable through the free tunnels a remote session runs over, in two
    different ways: Cloudflare's edge buffers a text/event-stream body and
    releases nothing (headers arrive instantly, 0 bytes of body in 15s), and
    localtunnel gives the never-ending response its entire connection pool, so
    with the stream open even TWO parallel thumbnail requests 502 - which is
    exactly "images aren't coming through". Both failures are the same shape: a
    response that never ends. So this one always ends.

    `since` is the last seq the client holds. 0 (or absent) means "new client":
    it gets the snapshot and the CURRENT seq, deliberately not the backlog, so
    opening the app does not replay the whole session into the lane.
    """
    # A polling client is a WATCHING client. exit_when_unwatched counts SSE
    # subscribers, and a phone on the poll transport has none - without this the
    # studio would decide nobody was home and shut itself down mid-session.
    HUB.last_poll = time.time()
    try:
        since = int(req.rel_url.query.get("since") or 0)
    except (TypeError, ValueError):
        since = 0
    log = list(HUB.event_log)
    latest = HUB.event_seq
    if since <= 0:
        return web.json_response({"seq": latest, "events": _hub_snapshot(),
                                  "resync": False})
    # A cursor AHEAD of the server means the sidecar restarted underneath this
    # client - seq resets to 0 on boot, so a phone holding seq=500 would poll
    # forever and be handed an empty list every time, silently frozen for good.
    # This is the common case, not the exotic one: every code change restarts
    # the sidecar. Treat it exactly like falling off the ring.
    if since > latest:
        return web.json_response({"seq": latest, "events": _hub_snapshot(),
                                  "resync": True})
    # Fell off the back of the ring: say so rather than silently skipping the
    # gap. The client refetches history and starts clean from `seq`.
    oldest = log[0]["seq"] if log else latest + 1
    if since < oldest - 1:
        return web.json_response({"seq": latest, "events": _hub_snapshot(),
                                  "resync": True})
    return web.json_response(
        {"seq": latest, "resync": False,
         "events": [e for e in log if e["seq"] > since]})

# Cinematic is opt-in because its opposite is not "flat" - it is a photograph
# where the whole frame is readable. Left on by default the brain writes a
# shallow plane of focus into every scene and every render becomes the same
# stock portrait with the room thrown away behind it.
CINEMATIC_DIRECTIVE = (
    "\n[CINEMATIC: ON. Shoot this as a film frame rather than a snapshot - an "
    "anamorphic-leaning lens, a shallow plane of focus that holds the subject "
    "and lets the depth fall away, motivated practical light with real "
    "falloff, and a graded palette committed to one temperature. Depth of "
    "field, halation and lens character are wanted here: the deep-focus "
    "default is lifted for this turn.]")

# Krea 2 owns no anime or fantasy graph, so the recipe stays its photo one and
# the creative register has to arrive as direction. Without this the composer's
# style selector silently did nothing on a Krea model.
STYLE_ON_PHOTO_GRAPH = {
    "anime": "shot size, pose, expression, clean linework, cel shading and "
             "value grouping, a committed palette, and the story beat",
    "fantasy": "readable silhouettes, materials and scale, one motivated "
               "magical effect, and painterly light",
}


def style_directive(opts):
    """The composer's style when the resolved graph cannot express it itself."""
    opts = opts or {}
    style = opts.get("style")
    craft = STYLE_ON_PHOTO_GRAPH.get(style)
    recipe = effective_recipe(opts)
    # identity_edit is a Krea 2 graph too (bypass + identity patch stay in the
    # chain), so the composer's style lands on it the same way (Jesse, 2026-08-18).
    if not craft or recipe not in ("realism", "realism_ii", "identity_edit"):
        return ""
    why = ("the identity patch runs on it" if recipe == "identity_edit"
           else "that is the selected model")
    return (f"\n[STYLE: {style}. The graph is Krea 2's photo recipe because "
            f"{why}, but the ask is {style}. Write it in "
            f"that register - {craft} - and drop the photo-caption rules that "
            f"assume a camera in a real room: no film grain, no skin defects, "
            f"no lens language. Name the medium in the first clause so the "
            f"model commits to it.]")


def build_directive(opts, local=False):
    """Composer settings -> a hard-constraint block appended to the user turn, plus the
    list of vision refs to attach. The LLM passes the constraints to generate() verbatim
    and describes the attached refs into the scene.

    local=True (the NSFW writer's brief): the local brain never handles file names -
    the server overlays the composer's picks onto its generate() call. It only gets
    told WHAT it is writing for, and no vision refs (it can't see them anyway)."""
    if not opts:
        return "", []
    if local:
        d = ""
        tpl = effective_recipe(opts)
        if tpl:
            d += (f"\n\n[COMPOSER: writing for template={tpl}. Model, loras, size and "
                  f"reference are applied server-side - never mention file names.]")
        lch = resolve_character(opts.get("character")) if opts.get("character") else None
        if lch:
            # NEVER the notes field here - it is directing canon for the big API
            # brains (persona, feed strategy, recipe trivia) and a small writer
            # mines it for set dressing ("surf cafe neon" in every frame). The
            # local writer gets LOOK only; body/wardrobe/face ride server-side.
            look = lch.get("style") or ""
            # skin/ethnicity/build joined the ban (2026-08-11): the blind
            # writer cannot check the photo, and inventing any of them can
            # contradict the person the reference carries - the server-side
            # identity pass then fights the prompt.
            d += (f"\n[CHARACTER: {lch['name']}. Look: {look}\n"
                  f"Never describe her face, age, skin, ethnicity or build - the "
                  f"reference photo carries them. "
                  f"Place her EXACTLY where the user asked - no other locations, no "
                  f"backstory, nothing the user didn't say.]")
        # With an mmproj on disk the managed brain can see (2026-08-12, Jesse's
        # call): attach the refs so it reads traits off the pixels instead of
        # inventing them. Still no file names in the text - composer picks stay
        # server-side overlays either way.
        vision = []
        if _local_llm_mmproj(load_config()["llm"].get("local_model") or ""):
            refs = opts.get("refs") or []
            identity = None if lch else next(
                (r for r in refs if r.get("kind") == "identity"), None)
            person = identity.get("file") if identity else \
                (input_ref_name(lch.get("identity_ref")) if lch else None)
            if person:
                vision.append({"kind": "identity", "file": person})
            vision += [r for r in refs
                       if r.get("kind") in ("style", "clothing", "object")]
            if vision:
                d += ("\n[ATTACHED IMAGES: "
                      + ("the FIRST is the person this render must depict - "
                         "never write a skin tone, hair colour, age or body "
                         "type that contradicts it, and do not describe the "
                         "face in detail; " if person else "")
                      + "describe each style/clothing/object reference's "
                        "salient traits faithfully into the scene (garment "
                        "cut/colour/texture, palette/light/medium, "
                        "form/material).]")
        # Craft direction, not a file name - the local writer gets these too.
        d += style_directive(opts)
        if opts.get("cinematic"):
            d += CINEMATIC_DIRECTIVE
        return d, vision
    parts, vision = [], []
    tpl = effective_recipe(opts)
    refs = opts.get("refs") or []
    ch = resolve_character(opts.get("character")) if opts.get("character") else None
    identity = None if ch else next((r for r in refs if r.get("kind") == "identity"), None)
    identity_source = bool(ch or identity)
    if tpl:
        parts.append(f"template={tpl}")
    if opts.get("model"):
        entry = resolve_model_entry(opts["model"])
        if not identity_source or (entry and "identity_edit" in compatible_recipes(entry)):
            parts.append(f"model={opts['model']!r}")
    if opts.get("aspect"):
        parts.append(f"aspect={opts['aspect']!r}")
    if opts.get("mp"):
        parts.append(f"mp={opts['mp']}")
    if ch:
        parts.append(f"character={ch['id']!r}")
    loras = opts.get("loras") or []
    if identity_source:
        loras = [l for l in loras if lora_profile(l.get("name", ""))["family"] == "krea2"]
    if loras:
        parts.append("loras=[" + ", ".join(f"{l['name']}:{l['strength']}" for l in loras) + "]")
    # A selected character owns identity. Do not direct the brain toward a stale
    # manual identity image that the server will correctly ignore.
    if identity:
        parts.append(f"ref={identity['file']!r}")
    seen = [r for r in refs if r.get("kind") != "identity" and r.get("kind") in
            ("style", "clothing", "object")]
    # The person photo used to be the ONE attachment the brain never saw, so
    # scenes could confidently describe a different person than the reference
    # (wrong skin tone, wrong hair) and the identity pass had to fight the
    # prompt. The vision brain now gets the photo itself as ground truth -
    # first in the attachment order, ahead of the style/clothing refs.
    person = identity.get("file") if identity else \
        (input_ref_name(ch.get("identity_ref")) if ch else None)
    if seen:
        base = 2 if person else 1
        labels = "; ".join(f"#{i+base} = {r['kind']} reference ({r['file']})"
                            for i, r in enumerate(seen))
        parts.append("attached images: " + labels)
        vision = list(seen)
    if person:
        vision = [{"kind": "identity", "file": person}] + vision
    # Craft direction rather than generate() arguments, so it rides OUTSIDE the
    # hard-constraints block - and has to survive a turn that carries nothing
    # else, or "cinematic on, everything else default" would send nothing.
    craft = style_directive(opts)
    if opts.get("cinematic"):
        craft += CINEMATIC_DIRECTIVE
    if not parts:
        return ("\n" + craft if craft else ""), vision
    # "never invent your own values" asserts the values without vouching for
    # them, so checking them against the catalog read as diligence rather than
    # waste - the verification urge behind the eight-call catalog walk. Say
    # where they came from and the urge has nothing to feed on.
    d = ("\n\n[COMPOSER HARD CONSTRAINTS - pass these EXACTLY as the matching generate() "
         "arguments; they were resolved against the installed-model catalog before "
         "reaching you, so verify nothing and invent nothing: " + "; ".join(parts) + ". "
         + ("Describe each attached reference's salient traits faithfully into the scene "
            "(garment cut/colour/texture for clothing, palette/light/medium for style, "
            "form/material for object).]" if seen else "]"))
    d += craft
    if person:
        d += ("\n[PERSON REFERENCE - the FIRST attached image is the person this "
              "render must depict, attached as APPEARANCE GROUND TRUTH. Never write "
              "a skin tone, ethnicity, hair colour or texture, age, or body type "
              "that contradicts it; when the scene needs any of those words, read "
              "them off the photo. Do not describe the face in detail - the "
              "reference itself carries identity.]")
    if ch and ch.get("notes"):
        d += (f"\n[CHARACTER ANCHOR: {ch['name']}. {ch['notes']}\nHonor this canon in the "
              f"scene; do not restate their face - the reference carries it in identity_edit, and "
              f"txt2img recipes prepend their subject block server-side.]")
    return d, vision

_JOB_REF_RE = re.compile(r"#([0-9a-f]{4,12})\b", re.I)


def prior_render_directive(text, limit=1):
    """Resolve a #job-id mention into the scene that job actually rendered.

    Without this the brain is handed an opaque id - "iterate on #9a189484: apply
    the review fix - relax the hands" - and the only concrete words in the turn
    are the change being asked for. So it writes a whole new scene around them
    and the iterate silently becomes a fresh shot. Applying a review fix is the
    case that made this obvious: every fix produced an unrelated picture."""
    seen = []
    for match in _JOB_REF_RE.finditer(str(text or "")):
        ref = match.group(1).lower()
        if ref not in seen:
            seen.append(ref)
    if not seen:
        return ""
    entries = {str(e.get("id") or "").lower(): e for e in HUB.ledger_read() if e.get("id")}
    out = []
    for ref in seen[:limit]:
        entry = entries.get(ref) or next(
            (e for eid, e in entries.items() if eid.startswith(ref)), None)
        scene = " ".join(str((entry or {}).get("scene") or "").split())
        if not scene:
            continue
        info = entry.get("info") or {}
        facts = [f"template={entry.get('template')!r}"]
        if entry.get("seed") is not None:
            facts.append(f"seed={entry['seed']}")
        if info.get("model_path"):
            facts.append(f"model={info['model_path']!r}")
        if info.get("size"):
            facts.append(f"size={info['size']}")
        out.append(
            f"\n\n[PRIOR RENDER #{entry['id']} - {'; '.join(facts)}. Its scene was: "
            f"\"{scene}\" To change it, call generate() with that scene reused "
            f"almost word for word and ONLY the user's requested change edited in - "
            f"the change must actually appear in the scene text. Pass its seed "
            f"(copied digit for digit, in the seed argument only - never inside "
            f"the scene) for a small change that should keep the composition; omit "
            f"seed when the change restages pose, camera or light. Do not invent "
            f"a new subject, setting, camera or light.]")
    return "".join(out)


# The receipts a queued job leaves in the chat context: the prose path writes
# "[SYSTEM: the server queued that scene as job <id> ...]", the tool paths
# return {"queued": "<id>", ...} - both are how "the last one" gets an address.
_QUEUED_RECEIPT_RE = re.compile(
    r"queued that scene as job ([0-9a-f]{4,12})|\"queued\":\s*\"([0-9a-f]{4,12})\"")

# Language that points back at an existing image rather than opening a new one.
# Deliberately conservative for the local brain gate: a 4B told about a prior
# render on every turn welds its scene into fresh shots.
_REFERS_BACK_RE = re.compile(
    r"\b(?:same|again|instead|iterate|re-?roll|this one|that one|the last|previous|"
    r"keep (?:everything|the rest))\b"
    r"|^\s*(?:make|change|turn|remove|add|swap|put|give|fix|crop|zoom|brighten|"
    r"darken|closer|wider|tighter|now)\b"
    r"|\b(?:make|change|turn|remove|add|swap|put|fix)\b.{0,40}\b(?:it|her|him|"
    r"them|that|this)\b", re.I | re.S)


def last_chat_render_id(convo):
    """The newest job THIS chat queued, read from its own receipts.

    The global ledger cannot scope "the last one" - another chat, a reroll from
    the history rail, or an A/B from a different lane may be newer there."""
    for message in reversed(convo or []):
        content = message.get("content")
        if not isinstance(content, str):
            continue
        hit = None
        for match in _QUEUED_RECEIPT_RE.finditer(content):
            hit = match.group(1) or match.group(2)
        if hit:
            return hit
    return None


def resolve_action_entry(ref, convo=None):
    """A chat action's target: an explicit #id (prefix ok) or this chat's
    newest render. Returns the ledger entry's FULL id or None - the action
    routes exact-match e["id"], so a chat-typed prefix must widen here."""
    ref = str(ref or "").lstrip("#").strip().lower()
    if len(ref) < 4:
        ref = str(last_chat_render_id(convo or []) or "").lower()
        if len(ref) < 4:
            return None
    entry = next((e for e in HUB.ledger_read()
                  if str(e.get("id") or "").lower().startswith(ref)), None)
    return entry["id"] if entry else None


def last_render_directive(convo, text, local=False):
    """Ground pointing language ("the last one", "make her jacket red") when the
    user references the previous image WITHOUT a #id.

    prior_render_directive solved the explicit-id case; every other reference
    still became a fresh shot because the brain had no scene to reuse and no
    address to edit. The block carries both, plus the routing decision. The big
    brain gets it whenever a prior render exists (its contract routes); the
    local brain only on clearly back-referring turns (see _REFERS_BACK_RE)."""
    body = str(text or "")
    if _JOB_REF_RE.search(body):
        return ""                  # an explicit #id already resolved above
    ref = str(last_chat_render_id(convo) or "").lower()
    if len(ref) < 4:
        return ""
    if local and not _REFERS_BACK_RE.search(body):
        return ""
    entry = next((e for e in HUB.ledger_read()
                  if str(e.get("id") or "").lower().startswith(ref)), None) \
        or HUB.jobs.get(ref)
    scene = " ".join(str((entry or {}).get("scene") or "").split())
    if not scene:
        return ""
    seed = entry.get("seed")
    return (
        f"\n\n[PRIOR RENDER #{entry['id']} - the newest image in this chat "
        f"(template={entry.get('template')!r}"
        + (f", seed={seed}" if seed is not None else "") + f"). Its scene was: "
        f"\"{scene}\" If this message asks to CHANGE that image, call generate() "
        f"with this scene reused almost word for word and ONLY the change edited "
        f"in or out - the change must actually appear in the scene text. For a "
        f"small change that should keep the composition, pass seed={seed} in the "
        f"seed argument only (never write the seed inside the scene); omit seed "
        f"when the change restages pose, camera or light. If it is a new idea, "
        f"ignore this block entirely and build the new scene fresh.]")


def data_url_for(filename):
    name = input_ref_name(filename)
    if not name:
        return None
    root = (CDIR / "input").resolve()
    p = (root / name).resolve()
    if not p.is_relative_to(root) or not p.is_file() or p.stat().st_size > MAX_UPLOAD_BYTES:
        return None
    try:
        from PIL import Image
        import base64, io
        im = Image.open(p).convert("RGB")
        im.thumbnail((768, 768))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None

async def settings_get(_req):
    await refresh_comfy_nodes()
    cfg = load_config()
    key = cfg["llm"].get("api_key", "")
    return web.json_response({
        # One source for the number the About card shows. A version baked into
        # the bundle survives a sidecar update and then lies about what is
        # running; this cannot.
        "pixal_version": PIXAL_VERSION,
        "pixal_channel": PIXAL_CHANNEL,
        "llm": {"base_url": cfg["llm"]["base_url"], "model": cfg["llm"]["model"],
                "key_set": bool(key), "key_tail": key[-4:] if key else "",
                "local_model": cfg["llm"].get("local_model", ""),
                "local_keep": cfg["llm"].get("local_keep", True),
                "local_gpu_layers": cfg["llm"].get("local_gpu_layers", -1),
                "local_idle_minutes": cfg["llm"].get(
                    "local_idle_minutes", LLM_IDLE_EVICT_S // 60),
                "local_llms": local_llm_models()},
        "critic": {"model": cfg["critic"]["model"],
                   "installed": [{"name": n, "nsfw": _pretty_name(n)["nsfw"]}
                                 for n in installed_vl_models()]},
        "upscale": {**cfg["upscale"],
                    "installed": upscale_model_options(),
                    "image_modes": list(UPSCALE_IMAGE_MODES),
                    "pid_available": _pid_upscale_available(),
                    "video_modes": list(UPSCALE_VIDEO_MODES),
                    "video_available": bool(_video_upscale_node()),
                    "ltx25_video_available": not _ltx25_upscale_missing()},
        "edit": {**cfg["edit"],
                 "installed": [e["rel"] for e in recipe_model_candidates("qwen_edit")],
                 "default": QWEN_EDIT_MODEL},
        "vae": {**cfg["vae"],
                "installed": [e["rel"] for e in model_catalog("vae")],
                "stock": list(ZIMAGE_VAE_CANDIDATES)},
        "pid": {**cfg["pid"],
                "decode_available": _pid_node_available(PID_DECODE_NODE)},
        "video": {"default_engine": cfg["video"]["default_engine"],
                  "default_model": cfg["video"]["default_model"],
                  "engines": [{"id": e["id"], "label": e["label"],
                               "available": e.get("available", True),
                               "models": [{"id": m["id"], "label": m["label"],
                                           "available": m.get("available", True)}
                                          for m in e["models"]]}
                              for e in video_engine_options()]},
        "extra_model_roots": cfg["extra_model_roots"],
        "model_roots": [str(r) for r in model_roots(cfg)],
        "catalog_size": len(model_catalog()),
        "vram": vram_profile_state(),
        "comfy_url": COMFY,
        "comfy_editor": cfg["comfy_editor"],
        "comfy_console": cfg["comfy_console"],
        "explicit": cfg["explicit"],
    })

async def settings_post(req):
    body = await req.json()
    cfg = load_config()
    # The brain that is ALREADY running was spawned with the old placement
    # baked into its argv. Saving "chat brain on CPU" rewrote config and
    # nothing else, so a GPU-resident brain kept its layers until some later
    # chat turn happened to notice the mismatch - and with local_keep on, that
    # turn may never come. Jesse's 4B Q8 + f16 projector + 16k ctx sat on the
    # card for hours after he moved it to CPU (2026-08-22: 8.4 GB, measured).
    was_brain = (str(cfg["llm"].get("local_model") or ""),
                 cfg["llm"].get("local_gpu_layers", -1))
    llm = body.get("llm") or {}
    for k in ("base_url", "model"):
        if llm.get(k):
            cfg["llm"][k] = llm[k].strip()
    if llm.get("api_key"):
        cfg["llm"]["api_key"] = llm["api_key"].strip()
    if "local_model" in llm and isinstance(llm["local_model"], str):
        cfg["llm"]["local_model"] = llm["local_model"].strip()
    if "local_keep" in llm:
        cfg["llm"]["local_keep"] = bool(llm["local_keep"])
    if "local_gpu_layers" in llm:
        want = llm["local_gpu_layers"]
        # bool IS an int in Python - True/False are not layer counts.
        if isinstance(want, bool) or not isinstance(want, int) or want < -1:
            return web.json_response(
                {"ok": False, "error": f"not a gpu layer count: {want}"},
                status=400)
        cfg["llm"]["local_gpu_layers"] = want
    if "local_idle_minutes" in llm:
        want = llm["local_idle_minutes"]
        # bool IS an int in Python - True/False are not minute counts.
        if isinstance(want, bool) or not isinstance(want, (int, float)) or want < 0:
            return web.json_response(
                {"ok": False, "error": f"not a minute count: {want}"}, status=400)
        cfg["llm"]["local_idle_minutes"] = want   # 0 = keep it resident forever
    critic = body.get("critic") or {}
    if critic.get("model"):
        cfg["critic"]["model"] = critic["model"].strip()
    # The chat strip's brain chip is push-only, so a brain changed in Settings
    # has to say so or the chip keeps naming the old one until a reload.
    if llm:
        HUB.broadcast(type="brain", **brain_badge())
    upscale = body.get("upscale") or {}
    if "image_model" in upscale and isinstance(upscale["image_model"], str):
        # "" is a real choice: it means "ask me / none selected yet". Anything else
        # is resolved against the catalog now rather than at render time, so a name
        # that does not exist is refused here instead of failing every later
        # upscale; storing the resolved relpath is what ComfyUI wants verbatim.
        want = upscale["image_model"].strip()
        if not want:
            cfg["upscale"]["image_model"] = ""
        else:
            try:
                cfg["upscale"]["image_model"] = resolve_upscale_model(want)
            except ValueError as e:
                return web.json_response({"ok": False, "error": str(e)}, status=400)
    edit_cfg = body.get("edit") or {}
    if "model" in edit_cfg and isinstance(edit_cfg["model"], str):
        # Same contract as the upscaler above: "" means "use the recipe default",
        # and anything else is checked against the installed compatible set now,
        # so a deleted or renamed release is refused here rather than failing
        # every later edit.
        want = edit_cfg["model"].strip().replace("/", "\\")
        if want and not any(entry["rel"].replace("/", "\\").lower() == want.lower()
                            for entry in recipe_model_candidates("qwen_edit")):
            return web.json_response(
                {"ok": False, "error": f"not an installed Qwen Image Edit model: {want}"},
                status=400)
        cfg["edit"]["model"] = want
    vae = body.get("vae") or {}
    if "zimage" in vae and isinstance(vae["zimage"], str):
        want = vae["zimage"].strip().replace("/", "\\")
        if want and not _catalog_has("vae", want):
            return web.json_response(
                {"ok": False, "error": f"VAE is not installed: {want}"}, status=400)
        cfg["vae"]["zimage"] = want
    if upscale.get("image_mode") in UPSCALE_IMAGE_MODES:
        cfg["upscale"]["image_mode"] = upscale["image_mode"]
    pid_cfg = body.get("pid") or {}
    if "identity_finish" in pid_cfg:
        cfg["pid"]["identity_finish"] = bool(pid_cfg["identity_finish"])
    video_cfg = body.get("video") or {}
    if "default_engine" in video_cfg and isinstance(video_cfg["default_engine"], str):
        # "" is a real choice: it means "the server's order" (LTX 2.5 first).
        want = video_cfg["default_engine"].strip()
        if want and want not in {e["id"] for e in video_engine_options()}:
            return web.json_response(
                {"ok": False, "error": f"not a video engine: {want}"}, status=400)
        cfg["video"]["default_engine"] = want
    if "default_model" in video_cfg and isinstance(video_cfg["default_model"], str):
        # "" is a real choice: it means "the engine's first available model".
        # Anything else must name a chip some engine lists - an unavailable
        # one is still settable (its file may land later); the render-time
        # availability gates decide what actually runs, same as today.
        want = video_cfg["default_model"].strip()
        if want and want not in {m["id"] for e in video_engine_options()
                                 for m in e["models"]}:
            return web.json_response(
                {"ok": False, "error": f"not a video model: {want}"}, status=400)
        cfg["video"]["default_model"] = want
    if "comfy_editor" in body:
        cfg["comfy_editor"] = bool(body["comfy_editor"])
    if "comfy_console" in body:
        want = str(body.get("comfy_console") or "")
        if want not in ("tui", "plain"):
            return web.json_response(
                {"ok": False, "error": f"not a console style: {want}"}, status=400)
        cfg["comfy_console"] = want
    if upscale.get("video_mode") in UPSCALE_VIDEO_MODES:
        cfg["upscale"]["video_mode"] = upscale["video_mode"]
    if upscale.get("video_scale") is not None:
        try:
            low, high = UPSCALE_VIDEO_SCALE_RANGE
            cfg["upscale"]["video_scale"] = min(max(float(upscale["video_scale"]), low), high)
        except (TypeError, ValueError):
            pass
    if isinstance(body.get("extra_model_roots"), list):
        cfg["extra_model_roots"] = [r.strip() for r in body["extra_model_roots"]
                                    if isinstance(r, str) and r.strip()]
    if "comfy_url" in body:
        cfg["comfy_url"] = (body.get("comfy_url") or "").strip()
        old = COMFY
        apply_comfy_url(cfg["comfy_url"])
        if COMFY != old:
            _LM["at"] = 0.0                   # thumbs/titles come from the new box
            ws = getattr(HUB, "_ws", None)    # drop the bridge; it reconnects re-aimed
            if ws is not None and not ws.closed:
                asyncio.create_task(ws.close())
    if "vram_profile" in body:
        want = str(body.get("vram_profile") or "")
        if want not in ("auto", "32", "24", "16"):
            return web.json_response(
                {"ok": False, "error": f"not a VRAM profile: {want}"}, status=400)
        cfg["vram_profile"] = want
    if "explicit" in body:
        want = str(body.get("explicit") or "")
        if want not in ("auto", "on", "off"):
            return web.json_response(
                {"ok": False, "error": f"not an explicit mode: {want}"}, status=400)
        cfg["explicit"] = want
    save_config(cfg)
    _CATALOG["at"] = 0                         # rescan on next options call
    _SIDECAR_META.clear()
    # Moving the brain between card and CPU - or to a different model - only
    # takes effect on a fresh process. Evict ours now rather than leaving the
    # old placement holding VRAM until something else notices.
    if was_brain != (str(cfg["llm"].get("local_model") or ""),
                     cfg["llm"].get("local_gpu_layers", -1)):
        await free_brain_vram()
    return web.json_response({"ok": True})

async def setup_get(_req):
    """First-run state. detected = the install this sidecar lives inside, when
    it actually has a models folder - one-click prefill on the setup screen."""
    cfg = load_config()
    detected = str(_NEIGHBOR_COMFY.parent) if _NEIGHBOR_COMFY else ""
    return web.json_response({"needs_setup": not cfg["setup_done"],
                              "detected": cfg["comfy_root"] or detected})

async def setup_post(req):
    """The consent moment: the user names their ComfyUI install; only then does
    the app touch disk. Saves the root, kicks the narrated scan (SSE), and
    answers with where the models live + whether ComfyUI itself is up."""
    body = await req.json()
    raw = (body.get("root") or "").strip()
    c = resolve_comfy_dir(raw)
    if not c:
        return web.json_response(
            {"ok": False, "error": "no models folder there - looked for "
             "ComfyUI\\models and models under that path"}, status=400)
    cfg = load_config()
    cfg["comfy_root"] = raw
    cfg["setup_done"] = True
    save_config(cfg)
    apply_comfy_root(raw)
    _CATALOG.update(at=0, data=None)
    _SIDECAR_META.clear()
    asyncio.create_task(warmup_catalog())
    comfy_up = False
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{COMFY}/system_stats",
                             timeout=aiohttp.ClientTimeout(total=4)) as r:
                comfy_up = r.status == 200
    except Exception:
        pass
    return web.json_response({"ok": True, "models_dir": str(c / "models"),
                              "comfy": comfy_up})

async def settings_rescan(_req):
    """Re-walk every model root now (new LoRAs, new drives) - progress streams to the
    status row via the scan events."""
    _CATALOG["at"] = 0
    _SIDECAR_META.clear()
    asyncio.create_task(warmup_catalog())
    return web.json_response({"ok": True})

async def settings_test(_req):
    _turn_start()
    try:
        status, d = await llm_call([{"role": "user", "content": "reply with: ok"}], timeout=30)
        if status == 200 and d.get("choices"):
            return web.json_response({"ok": True, "model": load_config()["llm"]["model"]})
        return web.json_response({"ok": False, "error": str(d)[:300]}, status=502)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)[:300]}, status=502)
    finally:
        _turn_end()

async def characters_post(req):
    """Create/update a character anchor. User data in characters/<id>.json."""
    body = await req.json()
    ch = body.get("character") or {}
    if not ch.get("name"):
        return web.json_response({"ok": False, "error": "name required"}, status=400)
    ref = input_ref_name(ch.get("identity_ref"))
    if not ref:
        return web.json_response(
            {"ok": False, "error": "add a reference image so Identity Edit knows the character"},
            status=400)
    if not (CDIR / "input" / ref).is_file():
        return web.json_response(
            {"ok": False, "error": f"reference image not found in ComfyUI/input: {ref}"},
            status=400)
    ch["identity_ref"] = ref
    ch["id"] = re.sub(r"[^a-z0-9]+", "_", (ch.get("id") or ch["name"]).lower()).strip("_")
    if not ch["id"]:
        return web.json_response({"ok": False, "error": "bad id"}, status=400)
    CHAR_DIR.mkdir(exist_ok=True)
    (CHAR_DIR / f"{ch['id']}.json").write_text(json.dumps(ch, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    CHARACTERS[ch["id"]] = ch
    return web.json_response({"ok": True, "id": ch["id"]})


async def styles_post(req):
    """Create or update a saved style. User data in recipes/<id>.json."""
    # This is the route a pasted or shared recipe will arrive on, so malformed
    # JSON is an expected input, not an internal error. Answer with the parse
    # error itself - "Server got itself in trouble" tells the user nothing.
    try:
        body = await req.json()
    except (ValueError, UnicodeDecodeError) as exc:
        return web.json_response({"ok": False, "error": f"not valid JSON: {exc}"},
                                 status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "error": "expected a JSON object"},
                                 status=400)
    raw = dict(body.get("style") or {})
    raw["schema_version"] = RECIPE_SCHEMA_VERSION
    try:
        record = validate_saved_style(raw)
        check_style_runnable(record)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    prior = SAVED_STYLES.get(record["id"])
    provenance = dict(record.get("provenance") or {})
    provenance.setdefault("created", (prior or {}).get("provenance", {})
                          .get("created", time.time()))
    provenance["updated"] = time.time()
    provenance.setdefault("author", "")
    record["provenance"] = provenance
    try:
        write_saved_style(record)
    except OSError as exc:
        return web.json_response(
            {"ok": False, "error": f"the style file could not be written: {exc}"},
            status=500)
    return web.json_response({"ok": True, "id": record["id"], "style": record,
                              "replaced": bool(prior)})


async def styles_delete(req):
    """Delete one saved style. IDs are treated as hostile input: only the same
    canonical alphabet validate_saved_style produces may address a file here."""
    style_id = str(req.match_info.get("style_id") or "").strip()
    if not _STYLE_ID_RE.fullmatch(style_id):
        return web.json_response({"ok": False, "error": "invalid style id"}, status=400)
    if style_id not in SAVED_STYLES:
        return web.json_response({"ok": False, "error": "no such style"}, status=404)
    path = RECIPE_DIR / f"{style_id}.json"
    try:
        if path.exists() or path.is_symlink():
            path.unlink()
    except OSError:
        return web.json_response(
            {"ok": False, "error": "could not delete the style file"}, status=500)
    SAVED_STYLES.pop(style_id, None)
    return web.json_response({"ok": True, "id": style_id})


async def style_sampler(req):
    """What the editor may offer for one base+model pairing.

    Answers all of it in one call because the questions are not independent: a
    Z-Image seat exists or not DEPENDING on the model, and the values a seat
    accepts depend on the node class sitting in it.
    """
    base_id = str(req.query.get("base") or "")
    model = str(req.query.get("model") or "")
    if base_id not in STYLE_BASE_IDS:
        return web.json_response(
            {"ok": False, "error": f"unknown base recipe: {base_id or '(missing)'}"},
            status=400)
    seat = sampler_seat(base_id, model)
    return web.json_response({
        "ok": True, "base": base_id, "model": model, "tunable": bool(seat),
        "node_class": seat["class"] if seat else "",
        # Which settings this seat's node even HAS. RES4LYF's Clownshar sampler
        # carries eta; a stock KSampler does not, so the editor must not draw a
        # box that would fail on save.
        "keys": list(seat_tuning_keys(seat)),
        "options": sampler_choices(seat["class"]) if seat else {},
        "defaults": sampler_defaults(base_id, model),
        "reason": "" if seat else fixed_schedule_reason(base_id, model),
    })


async def characters_get_one(req):
    """The full anchor record, for the edit form.

    /api/options carries only what the picker draws (name, age, race, sex,
    has_ref). Editing needs the rest - style, notes, wardrobe_lock and the
    identity_ref filename - and without this route the form could only ever
    create, which is why anchors used to be delete-and-retype to fix a typo.
    """
    character_id = str(req.match_info.get("character_id") or "").strip()
    if not re.fullmatch(r"[a-z0-9_]+", character_id):
        return web.json_response({"ok": False, "error": "invalid character id"}, status=400)
    ch = CHARACTERS.get(character_id)
    if not ch:
        return web.json_response({"ok": False, "error": "character anchor not found"},
                                 status=404)
    return web.json_response({"ok": True, "character": ch})


async def characters_preview(req):
    """What this anchor will actually bake into a caption, before it is saved.

    Calls the SAME functions the builders call, so the form cannot drift from
    the render: character_subject() is prepended to every txt2img caption and
    wardrobe_lock_for() closes it. Someone filling this in was previously
    writing into a sentence they never saw.
    """
    body = await req.json()
    ch = body.get("character") or {}
    return web.json_response({"ok": True,
                              "subject": character_subject(ch),
                              "wardrobe": wardrobe_lock_for(ch)})


async def characters_delete(req):
    """Delete one character anchor record, never its ComfyUI/input source image.

    The global access gate authenticates this route before it reaches here. IDs
    are still treated as hostile input: only the same canonical alphabet used
    by characters_post may address a file inside CHAR_DIR.
    """
    character_id = str(req.match_info.get("character_id") or "").strip()
    if not re.fullmatch(r"[a-z0-9_]+", character_id):
        return web.json_response({"ok": False, "error": "invalid character id"}, status=400)
    if character_id not in CHARACTERS:
        return web.json_response({"ok": False, "error": "character anchor not found"}, status=404)

    path = CHAR_DIR / f"{character_id}.json"
    try:
        # unlink removes only the anchor JSON (or a link at that exact path).
        # identity_ref deliberately is not read or touched here.
        if path.exists() or path.is_symlink():
            path.unlink()
    except OSError:
        return web.json_response(
            {"ok": False, "error": "could not delete the character anchor file"}, status=500)

    CHARACTERS.pop(character_id, None)
    return web.json_response({"ok": True, "id": character_id,
                              "source_image_preserved": True})


async def character_ref_thumb(req):
    """Serve the anchor's identity-reference preview by character id.

    The filename never leaves the server (character_identity_ready's privacy
    contract holds); only bounded WebP pixels travel, so the composer can show
    WHOSE face rides an identity render without learning where it lives."""
    character_id = str(req.match_info.get("character_id") or "").strip()
    if not re.fullmatch(r"[a-z0-9_]+", character_id):
        return web.json_response({"ok": False, "error": "invalid character id"}, status=400)
    try:
        _ch, image = character_identity(character_id)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=404)
    root = (CDIR / "input").resolve()
    path = (root / image).resolve()
    if not path.is_file() or not path.is_relative_to(root):
        return web.json_response({"ok": False, "error": "reference image not found"}, status=404)
    try:
        stat = path.stat()
        data = await asyncio.to_thread(_input_thumbnail_bytes, str(path), stat.st_mtime_ns)
    except (OSError, ValueError) as exc:
        return web.json_response(
            {"ok": False, "error": f"could not preview reference image: {exc}"}, status=415)
    return web.Response(body=data, content_type="image/webp", headers={
        "Cache-Control": "private, max-age=3600",
        "ETag": f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"',
    })


class _ActionBody:
    """Duck-typed stand-in for web.Request: the chat tool loop reuses the
    verified /api/animate, /api/upscale and /api/review handlers without HTTP,
    and those handlers only ever call req.json()."""
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


async def _call_action_route(handler, body):
    """Run an action route directly; (payload, status) instead of a Response."""
    resp = await handler(_ActionBody(body))
    return json.loads(resp.body), resp.status


def _action_receipt(fn, target, payload):
    """Tool receipts for render actions, same discipline as generate's: the
    job is QUEUED, not finished, and the brief/verdict never rides back
    through the model (echoed receipts are how scenes got reprinted).

    Every status ends by closing the turn. "Reply with ONE short line"
    constrains the TEXT and says nothing about tools, so on a turn where
    generate had been withheld the brain worked down the list it still had -
    upscale, then review, then animate - firing three unrequested GPU jobs on
    the user's render (chats/ce52340c.json, convo 39-48)."""
    over = " This turn is over: call no further tools."
    if not payload.get("ok"):
        return {"error": payload.get("error") or "action failed"}
    if fn == "animate":
        return {"animating": target, "engine": payload.get("engine"),
                "seconds": payload.get("seconds"),
                "status": ("queued on the GPU - NOT finished. The brief was already "
                           "shown to the user. Reply with ONE short line: the clip "
                           "is rendering and takes a few minutes. Do not repeat or "
                           "describe the brief." + over)}
    if fn == "review":
        return {"reviewing": target,
                "status": ("queued - the critic's verdict posts to chat by itself. "
                           "Reply with ONE short line. Do not write a critique "
                           "yourself." + over)}
    return {"upscaling": target, "kind": payload.get("kind"),
            "status": "queued - NOT finished. Reply with ONE short line." + over}


async def animate(req):
    """One click: still -> selected video engine, with engine-safe preparation."""
    body = await req.json()
    # A pasted script is the user's own words and bypasses the motion director
    # entirely - the same contract prompt_enhance=off gives stills. A script that
    # separates its shots declares its own shot count.
    script = str(body.get("script") or "").strip()
    try:
        engine, model_id, seconds, fps = validate_video_selection(
            body.get("engine"), body.get("model"), body.get("seconds"),
            body.get("fps"))
        lora_plan = validate_video_lora_plan(
            engine, model_id, body.get("lora_plan"))
        requested_shots = body.get("shots")
        if script and requested_shots is None and engine == "h3":
            requested_shots = min(len(split_shot_script(script)) or 1, H3_SHOTS_MAX)
        shots = validate_shot_count(engine, requested_shots, seconds, model_id)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    # The chip is the lane switch, per render: fl2va builds the first-frame
    # graph, ref2va the reference graph. Every fence below keys off this.
    variant = h3_model_variant(model_id) if engine == "h3" else None
    entry = next((e for e in HUB.ledger_read() if e["id"] == body.get("id")), None)
    if not entry:
        return web.json_response({"ok": False, "error": "no such generation"}, status=404)
    img = next((i for i in entry["images"] if i.get("media", "image") == "image"),
               entry["images"][0] if entry["images"] else None)
    if not img:
        return web.json_response({"ok": False, "error": "no still on that entry"}, status=400)
    src = CDIR / "output" / (img.get("subfolder") or "") / img["filename"]
    if not src.is_file():
        return web.json_response({"ok": False, "error": "file gone: " + img["filename"]},
                                 status=404)
    # FL2VA bridge: a second render becomes the clip's exact FINAL frame. One
    # continuous take by definition - converging on a fixed frame across hard
    # cuts is not a thing the format expresses.
    last_id = str(body.get("last_id") or "").strip()
    last_entry = None
    if last_id:
        if engine != "h3":
            return web.json_response(
                {"ok": False, "error": "bridging to an end frame needs MiniMax H3"},
                status=400)
        if shots > 1:
            return web.json_response(
                {"ok": False, "error": "a bridge is one continuous take - set shots to 1"},
                status=400)
        # MiniMaxH3ReferenceToVideo has no end-frame input at all - a bridge
        # would hand the builder a last_image with nowhere to go. Refuse
        # explicitly rather than drop it.
        if variant == H3_REF2V_MODEL_ID:
            return web.json_response(
                {"ok": False, "error": "a REF2VA render has no end frame - the "
                                       "reference is an identity, not a frame "
                                       "anchor; bridging is FL2VA-only"},
                status=400)
        last_entry = next((e for e in HUB.ledger_read() if e["id"] == last_id), None)
        if not last_entry:
            return web.json_response(
                {"ok": False, "error": "no such generation for the end frame"}, status=404)
    args = {"seconds": seconds, "model": model_id}
    if fps is not None:
        args["fps"] = fps
    try:
        if engine == "h3":
            if variant == H3_REF2V_MODEL_ID:
                # The picked still becomes ref_images.ref_image_0, staged as a
                # RAW copy - never through prepare_h3_frame, which center-crops
                # to the canvas because a first frame anchors geometry. A
                # reference does not; the node scales refs itself,
                # aspect-preserved, and cropping the subject to canvas throws
                # away exactly the identity information the ref exists to
                # carry. (The bridge path's raw copy is the precedent.)
                dst = f"pixal_ref_{entry['id']}.png"
                (CDIR / "input").mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, CDIR / "input" / dst)
                # No prepared frame defines the canvas in this lane, so it
                # derives from the source still's aspect via the same
                # adaptive-canvas logic.
                from PIL import Image
                with Image.open(src) as still:
                    width, height = h3_adapt_canvas(*still.size)
                args.update(refs=[dst], width=width, height=height)
            else:
                dst, width, height = prepare_h3_frame(src)
                args.update(image=dst, width=width, height=height)
            if last_entry:
                limg = next((i for i in last_entry["images"]
                             if i.get("media", "image") == "image"),
                            last_entry["images"][0] if last_entry["images"] else None)
                if not limg:
                    return web.json_response(
                        {"ok": False, "error": "no still on the end-frame entry"},
                        status=400)
                lsrc = CDIR / "output" / (limg.get("subfolder") or "") / limg["filename"]
                if not lsrc.is_file():
                    return web.json_response(
                        {"ok": False, "error": "file gone: " + limg["filename"]},
                        status=404)
                # Raw copy is enough: the node cover-crops the last frame to
                # canvas itself (the "follower" path), unlike the geometry-
                # anchoring first frame prepare_h3_frame exists for.
                ldst = f"pixal_bridge_{last_entry['id']}.png"
                shutil.copy2(lsrc, CDIR / "input" / ldst)
                args["last_image"] = ldst
            if lora_plan is not None:
                args["lora_plan"] = lora_plan
            # Off unless asked for. Turbo trades sampling steps for time, and
            # the size of that trade is a judgement about this render, not a
            # setting Pixal should make on the user's behalf. "speed" names a
            # mode from the ladder; the old boolean still works and resolves
            # to turbo8.
            speed = body.get("speed")
            if speed and h3_speed_mode(speed) is None:
                return web.json_response(
                    {"ok": False, "error": f"unknown H3 speed mode: {speed}"},
                    status=400)
            # The distillation ladder is FL2VA-only: its LoRAs are all fl2v
            # distills and no ref2v turbo is on disk. ref2va IS quality at 20
            # steps, so a distillation ask on a ref2va chip is refused here -
            # h3_speed_settings' silent-fallback-on-missing-LoRA precedent is
            # wrong for a lane that can never honour the pick.
            mode = h3_speed_mode(speed or (H3_SPEED_LEGACY_TURBO
                                           if body.get("turbo") else H3_SPEED_DEFAULT))
            if variant and variant not in (mode or {}).get("variants", ()):
                return web.json_response(
                    {"ok": False, "error": f"{mode['label']} is an FL2VA "
                                           f"distillation and no ref2v turbo LoRA is "
                                           f"on disk - a REF2VA chip renders at "
                                           f"Quality, 20 steps"},
                    status=400)
            if speed:
                args["turbo"] = str(speed)
            elif body.get("turbo"):
                args["turbo"] = True
            # Sparse attention is ON wherever the pack is installed, so the
            # client only ever sends this to turn it OFF. Measured 1.51x on
            # this machine's canvas; see apply_h3_sparse.
            if body.get("sparse") is False:
                args["sparse"] = False
            # 2x upscale is the opposite default: opt-in, because it triples
            # the cost of a render, so the only thing worth sending is the
            # ask. Where the pack or its weights are absent the builder just
            # builds the plain graph rather than queueing a failing prompt.
            if body.get("upscale"):
                args["upscale"] = True
        else:
            dst = f"pixal_anim_{entry['id']}.png"
            (CDIR / "input").mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, CDIR / "input" / dst)
            args["image"] = dst
    except (OSError, ValueError) as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    cid = body.get("cid") or uuid.uuid4().hex[:8]
    if script:
        motion, directed = script, True     # verbatim - no director round at all
    # Everything up to H3's 15s ceiling is one generation with real internal
    # cuts; only longer pieces fall back to chaining. See h3_cut_plan().
    cut_plan = h3_cut_plan(shots, seconds) if engine == "h3" else None
    if script:
        HUB.broadcast(type="text", cid=cid, text=f"*your script:* {motion}")
        written = split_shot_script(script)
        if cut_plan and len(written) == shots:
            motion = compile_cut_script(written, cut_plan[1])
    else:
        label = "motion and sound" if engine == "h3" else "the motion"
        if shots > 1:
            label += (f" as one take with {shots - 1} cut"
                      f"{'s' if shots > 2 else ''}" if cut_plan
                      else f" across {shots} shots")
        # LOOK stage: the managed llama.cpp brain has no mmproj, so on the local
        # preset the attached frame flattens to "[attached image]" and the brief
        # gets written blind. Read the frame through the critic's VL graph first
        # and hand the director its inventory as ground truth. Cloud brains with
        # real vision keep the direct image attach below.
        look = look_end = ""
        if f"127.0.0.1:{LOCAL_LLM_PORT}" in load_config()["llm"]["base_url"]:
            # the staged frame: the prepared first frame on fl2va, the raw
            # reference copy on ref2va - either way it is in ComfyUI's input
            staged = args.get("image") or (args.get("refs") or [None])[0]
            HUB.broadcast(type="thinking", cid=cid, note="looking at the frame")
            look = await frame_inventory(staged, entry["id"], cid)
            if args.get("last_image"):
                HUB.broadcast(type="thinking", cid=cid, note="looking at the end frame")
                look_end = await frame_inventory(args["last_image"],
                                                 last_entry["id"], cid)
        HUB.broadcast(type="thinking", cid=cid, note=f"directing {label}")
        motion, directed = await direct_motion(entry["scene"], body.get("hint"),
                                               engine=engine, shots=shots,
                                               cut_times=cut_plan[1] if cut_plan else None,
                                               seconds=seconds,
                                               # the staged still, which both
                                               # engines have just written into
                                               # ComfyUI's input folder (raw
                                               # reference copy on ref2va)
                                               frame=args.get("image") or
                                                     (args.get("refs") or [None])[0],
                                               look=look,
                                               last_frame=args.get("last_image"),
                                               look_end=look_end,
                                               model=model_id)
        if cut_plan:
            motion = normalise_cut_timeline(motion, cut_plan[1])
        HUB.broadcast(type="thinkingdone", cid=cid)
        # show the brief in the lane - the user should SEE what their note became
        HUB.broadcast(type="text", cid=cid,
                      text=(f"*the brief:* {motion}" if directed else
                            f"*motion director unreachable - going with:* {motion}"))
    if cut_plan:
        args["seconds"] = cut_plan[0]      # per-shot seconds became the whole take
        template = "h3_i2v"
    elif shots > 1:
        args["shots"] = shots
        template = "h3_multishot"
    else:
        # 2.3 ("ltx" -> ltx_i2v) is reachable only through old-history rerolls
        # now, and those carry their template directly - the default is 2.5.
        template = {"h3": "h3_i2v", "ltx": "ltx_i2v"}.get(engine, "ltx25_i2v")
        # The chip IS the lane switch: a ref2va build takes the reference
        # graph. shots>1 and cut plans on a ref2va chip never reach here -
        # validate_shot_count refused them before the cut plan was computed.
        if engine == "h3" and variant == H3_REF2V_MODEL_ID:
            template = "h3_ref2v"
    if template == "h3_i2v":
        # Official trained structure (three fields + alignment header). The
        # chained multishot keeps the pack's own --- format; LTX has no such
        # contract.
        motion = assemble_h3_prompt(motion, user_script=bool(script),
                                    last_frame=bool(args.get("last_image")),
                                    seconds=args.get("seconds"))
        # Brief 9.9: fill the two trained slots with the truth instead of
        # constants - the style from the source still's provenance (entry is
        # the ledger record of the still being animated), and the beat after a
        # hanging </d> from one brain call, falling back to the neutral
        # closer. assemble_h3_prompt stays sync, so both run here.
        motion = h3_style_splice(motion, h3_style_for_entry(entry))
        motion = await repair_h3_hanging_dialogue(motion, cid)
    elif template == "h3_ref2v":
        # The six-section trained format, sibling of the fl2va assembly: the
        # DIRECTOR authored the sections (H3_REF2V_MOTION_SYSTEM); the
        # assembler repairs and guarantees structure, writes the style slot
        # from provenance, and applies the dangling-ordinal policy. No
        # alignment header, no H3_AUDIO_PROMPT, no style splice - those are
        # all fl2va-lane machinery.
        motion, ref_warnings = assemble_h3_ref2v_prompt(
            motion, [{} for _ in args.get("refs") or []],
            user_script=bool(script), style=h3_style_for_entry(entry))
        motion = await repair_h3_hanging_dialogue(motion, cid)
        if ref_warnings:
            HUB.broadcast(type="text", cid=cid,
                          text="*ref2va: " + "; ".join(ref_warnings) + "*")
    asyncio.create_task(HUB.submit(cid, "chat", template, motion,
                                   args, 1, parent=entry["id"]))
    return web.json_response({"ok": True, "cid": cid, "motion": motion,
                              "engine": engine, "model": model_id,
                              "seconds": seconds, "shots": shots})

# ---- trailer orchestration ---------------------------------------------------
# A minute of MiniMax H3 is a dozen 5s generations, not one: the single-pass
# ceiling is 15s and identity survives best inside one pass, so a trailer is
# staged as independent shots (still -> clip) and stitched at the end. Shots
# share a visual canon through their planned scenes instead of shared frames -
# hard cuts between scenes are what trailer grammar wants anyway. Three phases
# (all stills, all briefs, all clips) so the card loads each model stack once
# instead of swapping realism<->H3<->brain twelve times.

TRAILER_MAX_SHOTS = 16
TRAILER_STILL_W, TRAILER_STILL_H = 1344, 768   # ONE canvas for every shot: both
                                               # divisible by 32, so H3 renders
                                               # every clip at identical dims and
                                               # the stitch can stream-copy

_TRAILER_SHOT_RE = re.compile(
    r"SHOT\s*\d+\s*STILL\s*:\s*(.+?)\s*\|\s*MOTION\s*:\s*(.+)", re.I)

TRAILER_DIRECTOR = """You are planning a film trailer as {n} still frames, each animated into a {per}-second clip with sound. From the concept below write EXACTLY {n} shots in trailer order: cold open, escalating dread, reveal beat, final stinger.
Write one line per shot and nothing else, in this exact format:
SHOT <number> STILL: <the frame as a photograph, 35-70 words - subject, setting, composition, one named light source with direction, era and film grade> | MOTION: <what moves and what we hear, 15-30 words>
END OF CONTRACT - the three rules that matter most:
1. Subjects NEAR the camera (close or medium shots), one consistent visual canon across all shots.
2. State tempo positively ("she bolts upright"), never "slow motion" and never the word "cinematic".
3. MOTION names the ambient sound bed plus ONE clear sound event; output ONLY the {n} SHOT lines."""


async def plan_trailer_shots(concept, n, per, cid):
    status, data = await llm_call(
        [{"role": "system", "content": TRAILER_DIRECTOR.format(n=n, per=per)},
         {"role": "user", "content": concept}], cid=cid)
    if "choices" not in data:
        return []
    text = data["choices"][0]["message"].get("content") or ""
    return [{"still": m.group(1).strip(), "motion": m.group(2).strip()}
            for m in _TRAILER_SHOT_RE.finditer(text)][:n]


async def _wait_job(job, timeout):
    deadline = time.time() + timeout
    while not job.get("finalized") and time.time() < deadline:
        await asyncio.sleep(1)
    return bool(job.get("finalized")) and not job.get("error")


def _ffmpeg_tool(name="ffmpeg"):
    """ffmpeg/ffprobe wherever this box actually keeps it.

    The ComfyUI launcher puts tools\\ffmpeg\\bin on PATH for ITS process only,
    so the sidecar cannot see it and shutil.which comes back empty here even
    though ffmpeg is plainly installed. Look there explicitly."""
    exe = shutil.which(name)
    if exe:
        return exe
    beside = CDIR.parent / "tools" / "ffmpeg" / "bin" / f"{name}.exe"
    if beside.is_file():
        return str(beside)
    hits = sorted((CDIR.parent / "python_embeded" / "Lib" / "site-packages" /
                   "imageio_ffmpeg" / "binaries").glob(f"{name}*.exe"))
    return str(hits[0]) if hits else None


def _ffmpeg_exe():
    return _ffmpeg_tool("ffmpeg")


@lru_cache(maxsize=64)
def _clip_shape(path_text, size, mtime_ns):
    """(width, height, frames) of a finished clip, or None when unreadable.

    Cheap enough to run at build time - ffprobe reads the container header, not
    the stream - and cached on (path, size, mtime) so a re-upscale of the same
    clip costs nothing. The frame count is what the butler needs: an LTX 2.5
    clip upscale re-encodes EVERY frame at twice the resolution, and pricing
    that flat put a 22B two-pass job in the same bracket as an RTX VSR filter.
    """
    exe = _ffmpeg_tool("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height,nb_frames,duration,r_frame_rate",
             "-of", "json", path_text],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stream = (json.loads(out.stdout).get("streams") or [{}])[0]
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if not width or not height:
        return None
    frames = int(stream.get("nb_frames") or 0)
    if not frames:
        # nb_frames is absent in plenty of containers; duration x rate is the
        # standard fallback and only has to be close.
        try:
            num, _, den = (stream.get("r_frame_rate") or "0/1").partition("/")
            rate = float(num) / float(den or 1)
            frames = int(round(float(stream.get("duration") or 0) * rate))
        except (TypeError, ValueError, ZeroDivisionError):
            frames = 0
    return width, height, max(frames, 1)


def clip_shape(path):
    """_clip_shape keyed on a path's identity, so an edited file re-probes."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return _clip_shape(str(path), st.st_size, st.st_mtime_ns)


async def _run_ffmpeg(args):
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    return proc.returncode, (err or b"").decode(errors="replace")


async def stitch_clips(clips, dst):
    """Concat H3 clips (all 24fps, same canvas) into one mp4, audio intact.
    Stream copy first; if a clip drifted (codec or dims), re-encode once."""
    exe = _ffmpeg_exe()
    if not exe:
        raise RuntimeError("no ffmpeg found for the stitch")
    lst = dst.with_suffix(".txt")
    lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips),
                   encoding="utf-8")
    try:
        code, err = await _run_ffmpeg(
            [exe, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", str(dst)])
        if code != 0:
            fc = "".join(f"[{i}:v][{i}:a]" for i in range(len(clips))) + \
                 f"concat=n={len(clips)}:v=1:a=1[v][a]"
            args = [exe, "-y"]
            for c in clips:
                args += ["-i", str(c)]
            args += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                     "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                     "-c:a", "aac", "-b:a", "192k", "-r", "24", str(dst)]
            code, err = await _run_ffmpeg(args)
            if code != 0:
                raise RuntimeError("ffmpeg concat failed: " + err[-400:])
    finally:
        lst.unlink(missing_ok=True)


def _fit_trailer_canvas(src, name):
    """Letterbox an existing image (a poster, a title card) onto the trailer
    canvas: H3 anchors its render size to the source frame, so a portrait
    poster fed raw would come back portrait and break the stream-copy stitch."""
    from PIL import Image
    canvas = Image.new("RGB", (TRAILER_STILL_W, TRAILER_STILL_H), (0, 0, 0))
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((TRAILER_STILL_W, TRAILER_STILL_H), Image.LANCZOS)
        canvas.paste(im, ((TRAILER_STILL_W - im.width) // 2,
                          (TRAILER_STILL_H - im.height) // 2))
    dst = CDIR / "output" / "pixal_dm" / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, "PNG")
    return dst


def _crop_title(poster, box, name):
    """Lift the lettering off a poster as its own layer."""
    from PIL import Image
    with Image.open(poster) as im:
        card = im.convert("RGB").crop(tuple(box))
    dst = CDIR / "output" / "pixal_dm" / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    card.save(dst, "PNG")
    return dst


async def burn_title(clip, card, dst, start=1.4, fade=0.7, out_at=None):
    """Composite a title card over a finished clip.

    Not H3's job: MiniMaxH3ImageToVideo takes first_frame and last_frame and
    nothing else - there is no reference-image input - and lettering handed to
    a video diffusion model warps into gibberish inside a dozen frames. So the
    title is composited after the fact, the way a real trailer cuts it.

    Screen blend, not overlay: the card's ground is poster black, and screen
    leaves black untouched, so only the lettering burns through - no alpha
    channel to author. colorlevels crushes the asphalt still clinging to the
    crop below the blend's noticing. Fading a screen layer to BLACK is what
    fades it out; alpha would do nothing here.
    """
    exe = _ffmpeg_exe()
    if not exe:
        raise RuntimeError("no ffmpeg found for the title burn")
    out_at = out_at if out_at is not None else start + 2.6
    # format=gbrp on BOTH branches is not decoration: blend on a yuv420p plate
    # against an rgb24 card lets ffmpeg pick one interpretation and apply it to
    # the other's planes, which washes the whole frame magenta (2026-08-13).
    fc = (f"[0:v]format=gbrp[base];"
          f"[1:v]scale={int(TRAILER_STILL_W * 0.78)}:-1,format=gbrp,"
          f"colorlevels=rimin=0.26:gimin=0.26:bimin=0.26,"
          f"fade=t=in:st={start}:d={fade},"
          f"fade=t=out:st={out_at}:d={fade},"
          f"pad={TRAILER_STILL_W}:{TRAILER_STILL_H}:(ow-iw)/2:"
          f"{TRAILER_STILL_H}-ih-120:black[t];"
          f"[base][t]blend=all_mode=screen:shortest=1,format=yuv420p[v]")
    code, err = await _run_ffmpeg(
        [exe, "-y", "-i", str(clip), "-loop", "1", "-i", str(card),
         "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "medium", "-crf", "16",
         "-pix_fmt", "yuv420p", "-c:a", "copy", "-r", "24",
         "-shortest", str(dst)])
    if code != 0:
        raise RuntimeError("ffmpeg title burn failed: " + err[-400:])
    return dst


async def run_trailer(cid, concept, shots_in=None, seconds_total=60,
                      still_model=None, still_loras=None, stills_only=False,
                      still_seed=None, upscale=None):
    try:
        _, h3_model, per, _ = validate_video_selection("h3", None, 5, None)
    except ValueError as exc:
        HUB.broadcast(type="error", cid=cid, message=str(exc))
        return
    n = min(max(2, round(seconds_total / per)), TRAILER_MAX_SHOTS)
    if shots_in:
        shots = [{"still": str(s.get("still") or "").strip(),
                  "motion": str(s.get("motion") or "").strip(),
                  "file": str(s.get("file") or "").strip(),
                  # an already-approved clip: skip still AND animate, drop it
                  # straight into the stitch. Re-rolling an approved take is
                  # how a good clip gets lost - H3 never renders it twice.
                  "clip": str(s.get("clip") or "").strip(),
                  # verbatim H3 brief: skips the motion director entirely.
                  # The director elaborates a one-line hint into six
                  # simultaneous events ("laughs AND door slams AND crows
                  # scatter AND paint ripples"), which in 5s is mush.
                  "script": str(s.get("script") or "").strip(),
                  # {poster, box:[l,t,r,b]} - lettering composited over the
                  # finished clip instead of being generated into it
                  "title": s.get("title"),
                  # per-shot override: the tape-footage beats want the VHS
                  # LoRA while the movie beats stay on the film grade
                  "loras": s.get("loras")}
                 for s in shots_in if str(s.get("still") or "").strip()][:TRAILER_MAX_SHOTS]
    else:
        HUB.broadcast(type="thinking", cid=cid, note="planning the shot list")
        shots = await plan_trailer_shots(concept, n, per, cid)
        HUB.broadcast(type="thinkingdone", cid=cid)
    # A cut needs two shots; a stills-only look-dev pass is legitimately one
    # (a LoRA lineup renders the same frame once per variant).
    if len(shots) < (1 if stills_only else 2):
        HUB.broadcast(type="error", cid=cid, message=(
            "the trailer director couldn't produce a shot list - try again, "
            "or pass explicit shots"))
        return
    HUB.broadcast(type="text", cid=cid, text=(
        f"*trailer: {len(shots)} shots x {per}s. Stills first, then sound "
        f"and motion, then the stitch - this takes a while.*"))
    # phase 1: every still on one realism residency. A shot may bring its own
    # image instead ("file": a poster, a title card) - letterboxed, not rendered.
    stills = []
    for i, shot in enumerate(shots, 1):
        if shot.get("clip"):
            continue           # already shot and approved - straight to phase 4
        if shot.get("file"):
            try:
                card = _fit_trailer_canvas(shot["file"],
                                           f"trailer_card_{cid}_{i}.png")
                stills.append((i, shot, card, None))
            except (OSError, ValueError) as exc:
                HUB.broadcast(type="text", cid=cid,
                              text=f"*shot {i} card unreadable ({exc}) - dropping it*")
            continue
        HUB.broadcast(type="thinking", cid=cid,
                      note=f"trailer still {i}/{len(shots)}")
        still_args = {"width": TRAILER_STILL_W, "height": TRAILER_STILL_H}
        if still_model:
            still_args["model"] = still_model
        shot_loras = shot.get("loras") or still_loras
        if shot_loras:
            still_args["loras"] = list(shot_loras)
        if still_seed is not None:
            # +i so a multi-shot trailer still varies shot to shot, while a
            # one-shot lineup pass is reproducible across LoRA swaps
            still_args["seed"] = int(still_seed) + i - 1
        sjob = await HUB.submit(cid, "chat", "realism", shot["still"],
                                still_args, 1)
        ok = not sjob["error"] and await _wait_job(sjob, 600)
        img = next((im for im in sjob["images"]
                    if im.get("media", "image") == "image"), None) if ok else None
        if not img:
            HUB.broadcast(type="text", cid=cid,
                          text=f"*shot {i} still failed - dropping it*")
            continue
        stills.append((i, shot, CDIR / "output" / (img.get("subfolder") or "")
                       / img["filename"], sjob["id"]))
    if stills_only:
        # look-dev dry run: the stills are already lane cards and ledger
        # entries - judge the grade, then run the full cut
        HUB.broadcast(type="text", cid=cid,
                      text=f"*stills-only pass done: {len(stills)} frames*")
        return
    reused = [s for s in shots if s.get("clip")]
    if len(stills) + len(reused) < 2:
        HUB.broadcast(type="error", cid=cid,
                      message="too few stills survived to cut a trailer")
        return
    # phase 2: every brief on one brain residency
    briefs = []
    for n_, (i, shot, src, parent) in enumerate(stills, 1):
        HUB.broadcast(type="thinking", cid=cid,
                      note=f"directing shot {n_}/{len(stills)}")
        try:
            frame, w, h = prepare_h3_frame(src)
        except (OSError, ValueError) as exc:
            HUB.broadcast(type="text", cid=cid,
                          text=f"*shot {i} frame prep failed ({exc}) - dropping it*")
            continue
        if shot.get("script"):
            motion = assemble_h3_prompt(shot["script"], user_script=True,
                                        last_frame=False, seconds=per)
        else:
            # look="" on purpose: the pipeline AUTHORED the still scene, so the
            # director already holds ground truth - 12 VL inventories buy nothing.
            motion, _ = await direct_motion(shot["still"], shot.get("motion"),
                                            engine="h3", shots=1, seconds=per,
                                            frame=frame, look="")
            motion = assemble_h3_prompt(motion, user_script=False,
                                        last_frame=False, seconds=per)
        # Brief 9.9, same two slots as animate: the style follows the still's
        # ledger provenance (parent is the still job's entry id), and a
        # hanging </d> gets its closing beat from one brain call with the
        # neutral closer as the only fallback. A still whose entry is not in
        # the ledger yet simply keeps live-action - unknown provenance is
        # never a reason to claim stylized.
        still_entry = next((e for e in HUB.ledger_read() if e["id"] == parent),
                           None)
        motion = h3_style_splice(motion, h3_style_for_entry(still_entry))
        motion = await repair_h3_hanging_dialogue(motion, cid)
        briefs.append((i, shot, motion, frame, w, h, parent))
    # phase 3: every clip on one H3 residency
    rendered = {}
    for n_, (i, shot, motion, frame, w, h, parent) in enumerate(briefs, 1):
        HUB.broadcast(type="text", cid=cid,
                      text=f"*shot {n_}/{len(briefs)}: rolling H3*")
        vjob = await HUB.submit(cid, "chat", "h3_i2v", motion,
                                {"seconds": per, "model": h3_model,
                                 "image": frame, "width": w, "height": h},
                                1, parent=parent)
        ok = not vjob["error"] and await _wait_job(vjob, 1800)
        vid = next((im for im in vjob["images"]
                    if im.get("media") == "video"), None) if ok else None
        if not vid:
            HUB.broadcast(type="text", cid=cid,
                          text=f"*shot {n_} clip failed - dropping it*")
            continue
        made = (CDIR / "output" / (vid.get("subfolder") or "") / vid["filename"])
        card = shot.get("title") or {}
        if card.get("poster"):
            try:
                lettering = _crop_title(card["poster"], card.get("box"),
                                        f"trailer_title_{cid}_{i}.png")
                burned = made.with_name(made.stem + "-title.mp4")
                await burn_title(made, lettering, burned,
                                 start=float(card.get("start", 1.4)),
                                 out_at=card.get("out_at"))
                made = burned
                HUB.broadcast(type="text", cid=cid,
                              text=f"*shot {i}: title composited over the plate*")
            except (RuntimeError, OSError, ValueError) as exc:
                HUB.broadcast(type="text", cid=cid,
                              text=f"*shot {i} title burn failed ({exc}) - using the clean plate*")
        rendered[i] = made
    # phase 4: re-interleave. Reused clips never entered phases 1-3, so the
    # cut is assembled back in SHOT order, not render order.
    clips = []
    for i, shot in enumerate(shots, 1):
        if shot.get("clip"):
            p = Path(shot["clip"])
            if not p.is_absolute():
                p = CDIR / "output" / "pixal_dm" / p.name
            if p.is_file():
                clips.append(p)
            else:
                HUB.broadcast(type="text", cid=cid,
                              text=f"*shot {i}: approved clip {p.name} is gone - dropping it*")
        elif i in rendered:
            clips.append(rendered[i])
    if len(clips) < 2:
        HUB.broadcast(type="error", cid=cid,
                      message="too few clips survived to cut a trailer")
        return
    HUB.broadcast(type="thinking", cid=cid, note="stitching the trailer")
    jid = uuid.uuid4().hex[:8]
    dst = CDIR / "output" / "pixal_dm" / f"trailer_{jid}-audio.mp4"
    try:
        await stitch_clips(clips, dst)
    except (RuntimeError, OSError) as exc:
        HUB.broadcast(type="error", cid=cid, message=str(exc))
        return
    HUB.broadcast(type="thinkingdone", cid=cid)
    # register the stitched cut as a first-class generation: lane card,
    # ledger entry, history thumbnail - the same life every render gets
    job = {"id": jid, "cid": cid, "template": "trailer",
           "scene": " ".join(str(concept or "trailer").split())[:300],
           "seed": 0, "count": 1, "started": time.time(), "parent": None,
           "images": [], "seen": set(), "done_pids": set(), "prompt_ids": [],
           "texts": [], "spec": {},
           "info": {"model": "minimax-h3", "loras": [],
                    "size": f"{len(clips)} shots x {per}s"},
           "error": None}
    HUB.jobs[jid] = job
    HUB.broadcast(type="job", job_id=jid, cid=cid, template="trailer",
                  scene=job["scene"], seed=0, count=1)
    HUB.add_image(job, {"filename": dst.name, "subfolder": "pixal_dm",
                        "type": "output", "media": "video"})
    HUB.finalize(job)
    if not upscale:
        return
    # phase 5: the same cut again through RTX VSR, clip by clip. Feeding the
    # whole stitch in would put ~1600 frames in one tensor; 124 will not fall
    # over. The 1x cut above is already saved and stays saved.
    HUB.broadcast(type="text", cid=cid, text=(
        f"*now the 2x pass: {len(clips)} clips through RTX {upscale}. "
        f"The original stays where it is.*"))
    ups = []
    for n_, c in enumerate(clips, 1):
        HUB.broadcast(type="thinking", cid=cid,
                      note=f"upscaling clip {n_}/{len(clips)}")
        ujob = await HUB.submit(cid, "chat", "upscale_video",
                                f"flap daddies shot {n_}",
                                {"video": str(c), "mode": upscale}, 1)
        ok = not ujob["error"] and await _wait_job(ujob, 1800)
        vid = next((im for im in ujob["images"]
                    if im.get("media") == "video"), None) if ok else None
        if vid:
            ups.append(CDIR / "output" / (vid.get("subfolder") or "")
                       / vid["filename"])
            continue
        # concat needs one canvas for every clip, so a VSR miss gets a plain
        # lanczos 2x rather than being dropped - the cut stays complete.
        HUB.broadcast(type="text", cid=cid,
                      text=f"*clip {n_} VSR failed - lanczos 2x instead*")
        alt = c.with_name(c.stem + "-2x.mp4")
        code, err = await _run_ffmpeg(
            [_ffmpeg_exe(), "-y", "-i", str(c), "-vf",
             f"scale={TRAILER_STILL_W * 2}:{TRAILER_STILL_H * 2}:flags=lanczos",
             "-c:v", "libx264", "-preset", "medium", "-crf", "16",
             "-pix_fmt", "yuv420p", "-c:a", "copy", str(alt)])
        ups.append(alt if code == 0 else c)
    HUB.broadcast(type="thinking", cid=cid, note="stitching the 2x cut")
    jid2 = uuid.uuid4().hex[:8]
    dst2 = CDIR / "output" / "pixal_dm" / f"trailer_{jid2}_2x-audio.mp4"
    try:
        await stitch_clips(ups, dst2)
    except (RuntimeError, OSError) as exc:
        HUB.broadcast(type="error", cid=cid,
                      message=f"the 2x stitch failed ({exc}) - the 1x cut is fine")
        return
    HUB.broadcast(type="thinkingdone", cid=cid)
    job2 = {"id": jid2, "cid": cid, "template": "trailer",
            "scene": (" ".join(str(concept or "trailer").split())[:280]
                      + " [2x]"),
            "seed": 0, "count": 1, "started": time.time(), "parent": jid,
            "images": [], "seen": set(), "done_pids": set(), "prompt_ids": [],
            "texts": [], "spec": {},
            "info": {"model": "minimax-h3", "loras": [],
                     "size": f"{len(ups)} shots x {per}s, RTX {upscale} 2x"},
            "error": None}
    HUB.jobs[jid2] = job2
    HUB.broadcast(type="job", job_id=jid2, cid=cid, template="trailer",
                  scene=job2["scene"], seed=0, count=1)
    HUB.add_image(job2, {"filename": dst2.name, "subfolder": "pixal_dm",
                         "type": "output", "media": "video"})
    HUB.finalize(job2)


async def trailer(req):
    """POST /api/trailer {concept, seconds?, shots?: [{still, motion}], cid?}
    Fire-and-forget: the pipeline narrates into the lane as it goes."""
    body = await req.json()
    concept = str(body.get("concept") or "").strip()
    shots_in = body.get("shots")
    if not concept and not shots_in:
        return web.json_response({"ok": False, "error": "empty concept"},
                                 status=400)
    if shots_in is not None and not isinstance(shots_in, list):
        return web.json_response({"ok": False, "error": "shots must be a list"},
                                 status=400)
    try:
        seconds_total = int(body.get("seconds") or 60)
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "bad seconds"},
                                 status=400)
    cid = body.get("cid") or uuid.uuid4().hex[:8]
    asyncio.create_task(run_trailer(cid, concept, shots_in, seconds_total,
                                    still_model=body.get("still_model"),
                                    still_loras=body.get("still_loras"),
                                    stills_only=bool(body.get("stills_only")),
                                    still_seed=body.get("still_seed"),
                                    upscale=body.get("upscale")))
    return web.json_response({"ok": True, "cid": cid})


def stage_edit_entry(entry_id):
    """Stage a finished render's still into ComfyUI/input as an edit source.

    Returns (staged_name, parent_id). Raises ValueError with a user-facing
    reason (unknown id, no still, file gone); OSError propagates from the copy.
    Prefix ids are accepted so chat references like #9a18 resolve."""
    ref = str(entry_id or "").lower().lstrip("#")
    if len(ref) < 4:
        raise ValueError("no such generation")
    entry = next((e for e in HUB.ledger_read()
                  if str(e.get("id") or "").lower().startswith(ref)), None)
    if not entry:
        raise ValueError("no such generation")
    img = next((i for i in entry["images"] if i.get("media", "image") == "image"),
               entry["images"][0] if entry["images"] else None)
    if not img:
        raise ValueError("no still on that entry")
    src = CDIR / "output" / (img.get("subfolder") or "") / img["filename"]
    if not src.is_file():
        raise ValueError("file gone: " + img["filename"])
    # Comfy reads edit sources from input/, and an edited result can be edited
    # again - key the staged copy by source filename so chained edits differ.
    dst = f"pixal_edit_{Path(img['filename']).stem[:48]}.png"
    (CDIR / "input").mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, CDIR / "input" / dst)
    return dst, entry["id"]


async def edit(req):
    """One click: finished frame + a plain-language instruction -> Qwen Image Edit.

    The instruction is the user's, verbatim. Qwen-Image-Edit is trained on direct
    edit commands ("make her jacket red"), so Pixal deliberately does not run it
    through the prompt brain the way a creative render is enhanced."""
    body = await req.json()
    instruction = " ".join(str(body.get("instruction") or "").split())
    if not instruction:
        return web.json_response(
            {"ok": False, "error": "say what to change"}, status=400)
    # An attached photo is already in ComfyUI/input (that is what /api/upload
    # does), so it needs no ledger entry and no staging copy - it IS the source.
    # Editing a finished render still takes the id route below, which stages
    # output -> input first. Both end at the same builder.
    raw_input = body.get("input")
    attached = input_ref_name(raw_input) if raw_input else ""
    if raw_input and not attached:
        return web.json_response({"ok": False, "error": "bad input image name"}, status=400)
    parent = None
    if attached:
        if not (CDIR / "input" / attached).is_file():
            return web.json_response({"ok": False, "error": "file gone: " + attached},
                                     status=404)
        dst = attached
    else:
        try:
            dst, parent = stage_edit_entry(body.get("id"))
        except ValueError as exc:
            code = 404 if "no such" in str(exc) or "gone" in str(exc) else 400
            return web.json_response({"ok": False, "error": str(exc)}, status=code)
        except OSError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
    mask = str(body.get("mask") or "")
    if mask:
        # A painted mask arrives as a PNG data URL (white = edit here) and is
        # baked into a fresh staged copy's ALPHA channel - transparent pixels
        # are the edit region, the same contract ComfyUI's own mask editor
        # writes and build_klein_inpaint reads back via LoadImage's MASK output.
        import base64, io
        from PIL import Image
        try:
            raw = base64.b64decode(mask.split(",", 1)[-1])
            m = Image.open(io.BytesIO(raw)).convert("L")
        except Exception:
            return web.json_response({"ok": False, "error": "bad mask image"},
                                     status=400)
        src_img = Image.open(CDIR / "input" / dst).convert("RGBA")
        if m.size != src_img.size:
            m = m.resize(src_img.size, Image.NEAREST)
        src_img.putalpha(m.point(lambda v: 0 if v > 127 else 255))
        dst = f"pixal_mask_{Path(dst).stem[:48]}.png"
        src_img.save(CDIR / "input" / dst)
    # An attached reference image (a logo, a product shot) rides along as the
    # Plus encoder's image2 - qwen_edit only, and the masked lane can't take
    # one, so refuse rather than silently dropping what the user attached.
    reference = ""
    if body.get("reference"):
        reference = input_ref_name(body["reference"])
        if not reference:
            return web.json_response(
                {"ok": False, "error": "bad reference image name"}, status=400)
        if not (CDIR / "input" / reference).is_file():
            return web.json_response(
                {"ok": False, "error": "file gone: " + reference}, status=404)
        if mask:
            return web.json_response(
                {"ok": False, "error": "a masked edit cannot take a reference "
                                       "image yet - clear the mask first"}, status=400)
    # The source-only recipes all start from an image in input/ and differ in
    # what they do with it: qwen_edit follows an instruction, klein_inpaint
    # redraws only the painted mask, face_mint rewrites the person. Anything
    # else would have no source to work from. A mask flips the default lane.
    recipe = str(body.get("recipe") or ("klein_inpaint" if mask else "qwen_edit"))
    if recipe not in SOURCE_ONLY_RECIPE_IDS:
        return web.json_response(
            {"ok": False, "error": f"not an edit recipe: {recipe}"}, status=400)
    args = {"image": dst}
    if reference:
        args["reference"] = reference
    if body.get("megapixels") is not None:
        args["megapixels"] = body["megapixels"]
    for key in ("denoise", "eta"):
        if body.get(key) is not None:
            args[key] = body[key]
    # Recipes accept different knobs; megapixels means nothing to face_mint and
    # denoise means nothing to qwen_edit.
    args = {k: v for k, v in args.items() if k in SIGS[recipe]}
    cid = body.get("cid") or uuid.uuid4().hex[:8]
    asyncio.create_task(HUB.submit(cid, "chat", recipe, instruction,
                                   args, 1, parent=parent))
    return web.json_response({"ok": True, "cid": cid, "instruction": instruction,
                              "recipe": recipe, "source": dst})


async def input_stage(req):
    """Stage a finished render's still into ComfyUI/input, no edit attached.

    Same staging step /api/edit performs before it queues, exposed on its own:
    the character form uses it to adopt an edited reference the moment the
    edit render lands, so the result becomes pickable like any upload."""
    body = await req.json()
    try:
        dst, parent = stage_edit_entry(body.get("id"))
    except ValueError as exc:
        code = 404 if "no such" in str(exc) or "gone" in str(exc) else 400
        return web.json_response({"ok": False, "error": str(exc)}, status=code)
    except OSError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    return web.json_response({"ok": True, "name": dst, "parent": parent})


async def upscale(req):
    """One click: finished render -> a larger version of the same frame.

    Stills go through the enlarger chosen in Settings - an ESRGAN-style model
    (faithful, nothing reimagined) or NVIDIA PiD (generative tiles, real new
    texture). Clips go through RTX Video Super Resolution, audio intact."""
    body = await req.json()
    entry = next((e for e in HUB.ledger_read() if e["id"] == body.get("id")), None)
    if not entry:
        return web.json_response({"ok": False, "error": "no such generation"}, status=404)
    images = entry.get("images") or []
    clip = next((i for i in images if i.get("media") == "video"), None)
    still = next((i for i in images if i.get("media", "image") == "image"), None)
    target = still or clip
    if not target:
        return web.json_response({"ok": False, "error": "nothing to upscale"}, status=400)
    src = CDIR / "output" / (target.get("subfolder") or "") / target["filename"]
    if not src.is_file():
        return web.json_response({"ok": False, "error": "file gone: " + target["filename"]},
                                 status=404)
    cid = body.get("cid") or uuid.uuid4().hex[:8]
    if still:
        dst = f"pixal_up_{Path(target['filename']).stem[:48]}.png"
        try:
            (CDIR / "input").mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, CDIR / "input" / dst)
        except OSError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        args = {"image": dst}
        if body.get("model"):
            args["model"] = body["model"]
        if body.get("mode") in UPSCALE_IMAGE_MODES:
            args["mode"] = body["mode"]
        template = "upscale_image"
    else:
        # VHS reads the clip straight off disk - no staging copy needed.
        args = {"video": str(src)}
        for key in ("mode", "scale"):
            if body.get(key) is not None:
                args[key] = body[key]
        # The LTX 2.5 mode refines generatively; the clip's own brief keeps
        # that refine on-story. The VSR path ignores it.
        if entry.get("full_prompt"):
            args["prompt"] = entry["full_prompt"]
        template = "upscale_video"
    scene = f"upscaled: {entry.get('scene') or entry['id']}"
    asyncio.create_task(HUB.submit(cid, "chat", template, scene, args, 1,
                                   parent=entry["id"]))
    return web.json_response({"ok": True, "cid": cid, "kind": "image" if still else "video"})


# "finish" - a fixed gaussian-dither grain pass saved as <name>_finish.png - was
# removed with its job-card button. It was one hardcoded look applied blind, and
# /api/upscale now covers the same intent (make the finished frame better) with
# the user's own choice of model. Old _finish.png files stay readable in history.

CRITIC_MAX_SIDE = 1536   # composition, hands and light read fine at ~1.5K;
                         # a 4K upscale fed raw multiplies the QwenVL node's
                         # vision tokens (and VRAM spike) for nothing


def stage_critic_input(src, dst_name):
    """Stage a still into ComfyUI/input for a VL pass, downscaled when large.

    Re-encodes through PIL so the staged file is always an RGB PNG matching
    its name; falls back to a raw copy only when PIL cannot read the source
    (LoadImage sniffs content, not extension, so that still works)."""
    dst = CDIR / "input" / dst_name
    try:
        from PIL import Image
        with Image.open(src) as im:
            im = im.convert("RGB")
            if max(im.size) > CRITIC_MAX_SIDE:
                im.thumbnail((CRITIC_MAX_SIDE, CRITIC_MAX_SIDE), Image.LANCZOS)
            im.save(dst, "PNG")
    except Exception:
        shutil.copy2(src, dst)
    return dst_name


async def review(req):
    """Honest local-VL critique of a generation - the creative co-pilot pass."""
    body = await req.json()
    entry = next((e for e in HUB.ledger_read() if e["id"] == body.get("id")), None)
    if not entry:
        return web.json_response({"ok": False, "error": "no such generation"}, status=404)
    img = next((i for i in entry["images"] if i.get("media", "image") == "image"),
               None)
    if not img:
        return web.json_response({"ok": False, "error": "no still to review"}, status=400)
    src = CDIR / "output" / (img.get("subfolder") or "") / img["filename"]
    if not src.is_file():
        return web.json_response({"ok": False, "error": "file gone: " + img["filename"]},
                                 status=404)
    dst = stage_critic_input(src, f"pixal_review_{entry['id']}.png")
    cid = body.get("cid") or uuid.uuid4().hex[:8]
    HUB.broadcast(type="thinking", cid=cid, note="reading the shot")

    async def _review():
        # Brain-first: a sighted local brain critiques with no extra model
        # load; the vl_review ComfyUI job is the blind-preset fallback,
        # submitted ONLY when the reviewer's weights are already on disk -
        # the same guard the look passes (brief 9.22), because a first-run
        # fetch behind a button click is the stall 9c089d9 killed.
        try:
            try:
                text, why = await brain_vl_read(dst, CRITIC_Q, cid=cid)
            except Exception as exc:
                # brain_vl_read is built to return its reasons; a raise is
                # shaped like one, so the routing below stays the only routing.
                text, why = None, f"the brain's read failed ({exc})"
            if text is None:
                critic, on_disk = critic_weights()
                if not on_disk:
                    # A review is the whole point of the click, so where the
                    # look rides the caption quietly, this names the missing
                    # reviewer, its size and the way out - and ends the
                    # "reading the shot" spinner with the answer.
                    gb = vl_download_gb(critic)
                    size = f", ~{gb} GB" if gb else ""
                    HUB.broadcast(type="thinkingdone", cid=cid)
                    HUB.broadcast(
                        type="text", cid=cid,
                        text=(f"*the review cannot run: {why} - and the "
                              f"reviewer ({critic}{size}) is not downloaded; "
                              f"pick another in Settings or download it, "
                              f"then click review again*"))
                    return
                await HUB.submit(cid, "chat", "vl_review",
                                 f"review of #{entry['id']}", {"image": dst},
                                 1, parent=entry["id"])
                return
            fix_m = re.search(r"^FIX:\s*(.+)$", text, re.M)
            HUB.broadcast(type="review", job_id=uuid.uuid4().hex[:8], cid=cid,
                          parent=entry["id"], text=text,
                          fix=fix_m.group(1).strip() if fix_m else None)
            if HUB.convo is not None:
                HUB.convo.append({"role": "system",
                                  "content": f"[critic on #{entry['id']}: {text}]"})
        except Exception as exc:
            # The click already got its 200; a silent death here strands the
            # "reading the shot" spinner forever. Say what happened instead.
            HUB.broadcast(type="thinkingdone", cid=cid)
            HUB.broadcast(type="text", cid=cid,
                          text=f"*the review failed: {exc}*")

    asyncio.create_task(_review())
    return web.json_response({"ok": True, "cid": cid})

async def chat(req):
    body = await req.json()
    text = (body.get("text") or "").strip()
    cid = body.get("cid") or uuid.uuid4().hex[:8]
    if not text:
        return web.json_response({"ok": False, "error": "empty"}, status=400)
    cfg_llm = load_config()["llm"]
    local_brain = f"127.0.0.1:{LOCAL_LLM_PORT}" in cfg_llm["base_url"]
    directive, vision = build_directive(body.get("opts"), local=local_brain)
    directive += prior_render_directive(text)
    directive += last_render_directive(HUB.convo, text, local=local_brain)
    if directive or vision:
        content = []
        for r in vision:
            url = data_url_for(r["file"])
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})
        content.append({"type": "text", "text": text + directive})
        user_msg = {"role": "user", "content": content}
    else:
        user_msg = {"role": "user", "content": text}
    if not local_brain and not (cfg_llm.get("api_key") or os.environ.get("MOONSHOT_API_KEY")):
        return web.json_response(
            {"ok": False, "error": "no API key set - add one in settings or switch to Local"},
            status=500)
    convo = HUB.convo                     # the ACTIVE chat's LLM context
    if len(convo) > 40:                       # keep it bounded; never cut inside a tool chain
        cut = len(convo) - 40
        while cut < len(convo) and (convo[cut].get("role") == "tool"
                                    or convo[cut].get("tool_calls")):
            cut += 1
        del convo[:cut]
    HUB.lane_add({"role": "user", "text": text})
    HUB.broadcast(type="thinking", cid=cid, note=None)   # dots the instant he hits send
    asyncio.create_task(kimi_reply(cid, user_msg, convo, body.get("opts")))
    return web.json_response({"ok": True, "cid": cid})

def display_scene(scene):
    """What a stored scene is allowed to look like on its way OUT to the client.

    scene_gate now refuses server machinery on the way IN, but everything that
    got past it before is still sitting in history.jsonl and in persisted lane
    lines, and both are replayed to the browser on every tab open. Ledger entry
    079b9083 is a real render whose whole prompt is an [ATTACHED IMAGES: ...]
    block - it shows that wall of machinery in the gallery and the chat every
    time, and a fix that only guards new writes would leave it there forever.

    Scrubbing on the way out repairs every stored chat and card at once and
    touches none of the user's data. An entry whose scene was ENTIRELY
    machinery correctly comes back blank: it never was a prompt.
    """
    return _strip_history_directives(str(scene or ""))


async def lane_get(_req):
    """Replay transcript for a fresh tab: lane lines with job entries hydrated
    from the ledger (images/info/error) or the live job table if still in flight."""
    led = {e["id"]: e for e in HUB.ledger_read()}
    out = []
    for e in HUB.lane[-80:]:
        if e.get("role") == "job":
            src = led.get(e.get("job_id")) or HUB.jobs.get(e.get("job_id"))
            if not src:
                continue
            # done was hardcoded True, so a refresh mid-render replayed the job
            # as a FINISHED card with no images and no progress - the real state
            # only reappeared when the completion event fired. "elapsed" is set
            # exactly once, when the job finishes, so it is the honest signal for
            # both a ledger entry and a still-running job.
            out.append({"role": "job", "ts": e.get("ts"), "job": {
                "job_id": e["job_id"], "template": src.get("template"),
                "scene": display_scene(src.get("scene")), "seed": src.get("seed"),
                "count": src.get("count"), "images": _existing_media(src),
                "info": src.get("info"), "error": src.get("error"),
                "elapsed": src.get("elapsed"),
                "done": src.get("elapsed") is not None or bool(src.get("error"))}})
        else:
            # A lane line that is nothing BUT machinery is not a message and
            # never was - drop it rather than replay an empty bubble. Copied,
            # never mutated: HUB.lane is the record.
            text = e.get("text")
            if isinstance(text, str):
                clean = display_scene(text)
                if not clean.strip():
                    continue
                e = {**e, "text": clean}
            out.append(e)
    return web.json_response({"lane": out})

async def chats_get(_req):
    lst = sorted(HUB.chats.values(), key=lambda c: -c["ts"])
    return web.json_response({"active": HUB.active_chat,
                              "chats": [{"id": c["id"], "title": c["title"],
                                         "ts": c["ts"], "n": len(c["lane"])}
                                        for c in lst]})

async def chats_post(req):
    """new / select / delete - the server owns which chat is active (single-user
    app; every lane_add and llm turn lands on the active chat)."""
    body = await req.json()
    act, chat_id = body.get("action"), body.get("id")
    if act == "new":
        HUB.new_chat()
    elif act == "select" and chat_id in HUB.chats:
        HUB.active_chat = chat_id
    elif act == "delete" and chat_id:
        HUB.delete_chat(chat_id)
    return await chats_get(req)

async def reroll(req):
    body = await req.json()
    entry = next((e for e in HUB.ledger_read() if e["id"] == body.get("id")), None)
    if not entry:
        return web.json_response({"ok": False, "error": "no such generation"}, status=404)
    tmpl = entry["template"]
    spec = dict(entry.get("spec") or {})
    # The composer is the truth: a re-roll refines with the stack the user is
    # LOOKING at, not the one the card was born with - "I got a good render, I
    # want to refine it now - adjusting loras" (Jesse, 2026-08-14). Only a plan
    # that fits THIS card's graph may land; a plan for another recipe, or none
    # at all, falls back to the stored one with its revision healed so a card
    # older than the current stack still rolls instead of dying at 0.0s.
    live = (body.get("lora_plans") or {}).get(tmpl)
    if isinstance(live, dict):
        try:
            validate_lora_plan(tmpl, live)
            spec["lora_plan"] = live
            spec.pop("loras", None)      # the plan supersedes the legacy list
            live = True
        except (ValueError, KeyError):
            live = False
    if not live:
        spec = heal_stored_lora_plan(tmpl, spec)
    # The live model follows the same rule: it lands only if it can actually
    # drive this card's graph, so a re-roll can never strand the scene on a
    # model that has no recipe for it.
    model = body.get("model")
    if model and model != spec.get("model"):
        try:
            if tmpl in compatible_recipes(model_profile(model)):
                spec["model"] = model
        except Exception:
            pass
    # The live canvas obeys the same rule as the LoRA plan and model above: a
    # re-roll rolls at the settings the user is LOOKING at. It degrades, never
    # dies - an unknown aspect or a non-positive mp falls back to the stored
    # spec rather than 4xx-ing, and an omitted canvas leaves the stored one
    # untouched (absent != empty; a stale bundle sends neither).
    # Recipes whose own aspect is "" - keyed on the recipe's "aspect" field,
    # not a name list - take their dimensions from the source image instead of
    # the composer (qwen_edit, face_mint, klein_inpaint), so no live canvas
    # may be forced onto them.
    if RECIPE_SPECS.get(tmpl, {}).get("aspect"):
        aspect = body.get("aspect")
        if isinstance(aspect, str) and aspect in ASPECTS:
            spec["aspect"] = aspect
        mp = body.get("mp")
        if isinstance(mp, (int, float)) and not isinstance(mp, bool) \
                and math.isfinite(mp) and mp > 0:
            spec["mp"] = mp
    # The live identity dials obey the same rule as the canvas above: a
    # re-roll rolls at the likeness the user is LOOKING at, or "adjust and
    # re-roll" - the exact loop a likeness dial is FOR - silently uses the old
    # value. Present-but-bad degrades to the recipe constant, never a 4xx and
    # never the stored value the user moved away from; an omitted key keeps
    # the stored one (absent != empty, a stale bundle sends neither). Only a
    # recipe that DECLARES dials can receive them - the declaration names
    # builder parameters, so submit's SIGS filter is the same gate the graph
    # build uses.
    for dial in RECIPE_SPECS.get(tmpl, {}).get("dials") or ():
        if dial["key"] in body:
            spec[dial["key"]] = recipe_dial_value(dial, body.get(dial["key"]))
    # A locked card replays its exact seed - same shot, same dice - instead
    # of submit's fresh draw. The stored spec never carries a seed (submit
    # pops it before persisting), so this is the only way one gets back in.
    # `lock_seed` is the old client's way of asking (kept so a stale bundle
    # still works); `seed` is the held lock, and it only gets a say when there
    # is no ledger seed to restore. When lock_seed did restore one, the body's
    # seed is just the client's echo of that same value - and past 2**53 the
    # echo arrives rounded (JSON reads big integers as doubles), so letting it
    # overwrite would trade the ledger's exact seed for a lossy copy of it.
    restored = body.get("lock_seed") and entry.get("seed") is not None
    if restored:
        spec["seed"] = entry["seed"]
    frozen = held_seed(body)
    if frozen and not restored:
        spec["seed"] = frozen
    cid = body.get("cid") or uuid.uuid4().hex[:8]
    asyncio.create_task(HUB.submit(cid, "reroll", entry["template"], entry["scene"],
                                   spec, entry.get("count", 1), parent=entry["id"]))
    return web.json_response({"ok": True, "cid": cid})

def _existing_media(entry):
    """The entry's images that are still on disk. The ledger keeps recording
    a generation after the user deletes its files (its scene and seed stay
    iterable), but the grid and lane should never show a broken card."""
    out_root = CDIR / "output"
    return [im for im in (entry.get("images") or [])
            if (out_root / (im.get("subfolder") or "")
                / (im.get("filename") or "x")).is_file()]


async def history(_req):
    entries = []
    for e in HUB.ledger_read():
        imgs = _existing_media(e)
        if imgs:                     # every file gone -> the card would be
            entries.append({**e, "images": imgs,      # nothing but broken
                            "scene": display_scene(e.get("scene"))})
    return web.json_response({"entries": entries})

async def options(_req):
    await refresh_lm_cache()
    return web.json_response(HUB.options())

async def quant_alternatives(req):
    """GET /api/quant_alternatives?engine=ltx25 - the lighter-build ladder for
    an engine whose stock build does not fit the effective VRAM tier."""
    engine = str(req.rel_url.query.get("engine") or "").strip().lower()
    family = _quant_family(engine)
    if not family:
        return web.json_response(
            {"ok": False, "error": f"no quant ladder for engine: {engine}"},
            status=404)
    budget_gb = _tier_gb(vram_profile_state()["effective"])
    if budget_gb is None:
        return web.json_response(
            {"ok": False, "error": "no VRAM reading yet - the ladder needs a tier"},
            status=503)
    files = []
    for repo, fmt, prefix in QUANT_SOURCES[family]:
        try:
            siblings = await _hf_repo_files(repo)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            return web.json_response(
                {"ok": False, "error": f"huggingface.co is unreachable: {exc}"},
                status=502)
        files.extend(_quant_candidates(repo, fmt, prefix, siblings))
    return web.json_response({"ok": True, "engine": engine,
                              "budget_gb": budget_gb,
                              "files": pick_quant_rung(files, budget_gb)})

async def quant_fetch(req):
    """POST /api/quant_fetch {repo, filename, kind} - stream one curated quant
    into the family's models subfolder. Validation is the whole point: the repo
    must be on the curated ladder, so this can never become a generic downloader."""
    body = await req.json() if req.can_read_body else {}
    repo = str(body.get("repo") or "").strip()
    filename = str(body.get("filename") or "")
    kind = str(body.get("kind") or "").strip()
    if not any(repo == source_repo for sources in QUANT_SOURCES.values()
               for source_repo, _fmt, _pre in sources):
        return web.json_response({"ok": False, "error": "not a curated quant repo"},
                                 status=400)
    if kind not in KIND_DIRS:
        return web.json_response({"ok": False, "error": "unknown model kind"},
                                 status=400)
    if not _quant_safe_relpath(filename):
        return web.json_response({"ok": False, "error": "bad filename"}, status=400)
    task = QUANT_FETCH.get("task")
    if task is not None and not task.done():
        return web.json_response(
            {"ok": False, "error": "a download is already running"}, status=409)
    QUANT_FETCH["task"] = asyncio.create_task(_quant_fetch_run(repo, filename, kind))
    return web.json_response({"ok": True})

async def history_delete(req):
    """Remove one generation for good: ledger entry + its files. File deletion is
    guarded to ComfyUI/output so a mangled entry can never reach outside it."""
    body = await req.json()
    entry = HUB.ledger_delete(body.get("id"))
    if not entry:
        return web.json_response({"ok": False, "error": "not found"}, status=404)
    out_root = (CDIR / "output").resolve()
    removed = 0
    failed = 0
    for im in entry.get("images") or []:
        try:
            p = (out_root / (im.get("subfolder") or "") / (im.get("filename") or "")).resolve()
            if p.is_file() and p.is_relative_to(out_root):
                p.unlink()
                removed += 1
        except OSError as exc:
            # The ledger entry is already gone; a locked file would otherwise
            # be orphaned on disk with nothing recording it.
            failed += 1
            print(f"[pixal] could not delete {im.get('filename')}: {exc}", flush=True)
    print(f"[pixal] deleted entry {entry['id']} ({removed} files, {failed} failed)",
          flush=True)
    return web.json_response({"ok": True, "files_removed": removed,
                              "files_failed": failed})

async def upload(req):
    """Forward one image to ComfyUI's /upload/image (lands in ComfyUI/input/)."""
    data = None
    filename = "ref.png"
    content_type = "image/png"
    raw_kind = ""
    try:
        reader = await req.multipart()
        while field := await reader.next():
            if field.name == "image" and data is None:
                data = await field.read()
                filename = str(field.filename or "ref.png").replace("\\", "/").split("/")[-1]
                content_type = field.headers.get("Content-Type", "image/png")
            elif field.name == "kind":
                raw_kind = await field.text()
            else:
                await field.release()
        if data is None:
            return web.json_response({"ok": False, "error": "choose an image to upload"},
                                     status=400)
    except web.HTTPRequestEntityTooLarge:
        return web.json_response(
            {"ok": False, "error": "image is larger than the 40 MB upload limit"}, status=413)
    if not data:
        return web.json_response({"ok": False, "error": "the selected image is empty"},
                                 status=400)
    if len(data) > MAX_UPLOAD_BYTES:
        return web.json_response(
            {"ok": False, "error": "image is larger than the 40 MB upload limit"}, status=413)
    kind = reference_kind(raw_kind)
    if raw_kind and not kind:
        return web.json_response({"ok": False, "error": "unknown reference type"}, status=400)

    # quote_fields=False: the default percent-encodes the filename, and ComfyUI
    # stores that quoted form verbatim ('a b.png' lands as 'a%20b.png').
    form = aiohttp.FormData(quote_fields=False)
    form.add_field("image", data, filename=filename or "ref.png",
                   content_type=content_type)
    try:
        async with aiohttp.ClientSession() as s:
            # Do not set overwrite=true: ComfyUI safely gives same-named uploads
            # a unique suffix instead of replacing an existing character/ref source.
            async with s.post(f"{COMFY}/upload/image", data=form, timeout=120) as r:
                try:
                    out = await r.json(content_type=None)
                except (json.JSONDecodeError, aiohttp.ContentTypeError):
                    detail = (await r.text()).strip()[:240]
                    return web.json_response({
                        "ok": False,
                        "error": detail or f"ComfyUI rejected the upload ({r.status})",
                    }, status=r.status if 400 <= r.status < 600 else 502)
                if r.status >= 400 or not isinstance(out, dict):
                    detail = out.get("error") if isinstance(out, dict) else None
                    return web.json_response({
                        "ok": False,
                        "error": str(detail or f"ComfyUI rejected the upload ({r.status})")[:240],
                    }, status=r.status if 400 <= r.status < 600 else 502)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return web.json_response(
            {"ok": False, "error": f"could not upload to ComfyUI: {exc}"}, status=502)

    response_name = str(out.get("name") or "")
    response_subfolder = str(out.get("subfolder") or "").strip("/\\")
    record = input_image_record(
        f"{response_subfolder}/{response_name}" if response_subfolder else response_name,
        mtime=time.time())
    if not record:
        return web.json_response(
            {"ok": False, "error": "ComfyUI returned an invalid uploaded filename"}, status=502)
    if kind:
        try:
            record["kind"] = set_input_ref_type(record["name"], kind)
        except OSError as exc:
            return web.json_response({
                "ok": False, "name": record["name"],
                "error": f"image uploaded, but its reference type could not be saved: {exc}",
            }, status=500)
    return web.json_response({"ok": True, **record})


async def input_ref_type_post(req):
    """Assign or correct the durable semantic type of an existing input image."""
    body = await req.json()
    name = input_ref_name(body.get("name"))
    kind = reference_kind(body.get("kind"))
    if not name or not kind:
        return web.json_response(
            {"ok": False, "error": "reference image and type are required"}, status=400)
    root = (CDIR / "input").resolve()
    path = (root / name).resolve()
    if not path.is_file() or not path.is_relative_to(root):
        return web.json_response({"ok": False, "error": "input image not found"}, status=404)
    try:
        set_input_ref_type(name, kind)
    except OSError as exc:
        return web.json_response(
            {"ok": False, "error": f"reference type could not be saved: {exc}"}, status=500)
    return web.json_response({"ok": True, "name": name, "kind": kind})

def pwa_installed():
    """Whether the window can carry Pixal's own taskbar identity.

    The same _crx_ folder check pixal.vbs makes before trusting --app-id:
    config names a Chrome PWA id AND that app is actually installed. False is
    what the install nudge keys on - the fallback chrome --app= window belongs
    to Chrome on the taskbar, so pinning it pins Chrome (2026-08-20). Non-
    Windows says True: the nudge is a Windows-taskbar story."""
    if not _nt():
        return True
    app_id = str(load_config().get("chrome_app_id") or "").strip()
    if not app_id:
        return False
    base = os.environ.get("LOCALAPPDATA") or ""
    return bool(base) and (Path(base) / "Google" / "Chrome" / "User Data"
                           / "Default" / "Web Applications"
                           / f"_crx_{app_id}").is_dir()


async def status(_req):
    # The boot screen polls this every second while it waits, which makes it the
    # one place guaranteed to notice ComfyUI is down. index() alone was not
    # enough: sw.js can serve the app shell from cache, and then the handler that
    # starts ComfyUI never runs - the studio sits on "waiting for ComfyUI"
    # forever with no launcher and no error, which is indistinguishable from a
    # hang. Idempotent: kick_comfy_boot keeps at most one attempt in flight.
    #
    # But not when the user closed the window themselves. This poll runs every
    # second, so "start it whenever it is down" made the ComfyUI console
    # un-closable - it came straight back, every time.
    if not HUB.comfy_up and not comfy_closed_by_user():
        kick_comfy_boot()
    return web.json_response({"comfy": HUB.comfy_up,
                              "queue": HUB.queue_remaining,
                              "history": len(HUB.ledger_read()),
                              "boot": comfy_boot_state(),
                              "pwa": pwa_installed(),
                              "templates": list(PUBLIC_RECIPE_IDS)})

async def stop(req):
    """Interrupt running prompts + drop pending ones."""
    body = await req.json()
    jid = body.get("job_id")
    # A Stop click can land just AFTER its job finalized: HUB.jobs is never
    # pruned, and the explicit-id branch below does not filter finalized the
    # way the no-id branch does. ComfyUI's /interrupt is GLOBAL, so answering
    # that late click kills whatever started rendering next. A finalized job
    # has nothing left to cancel - say so without touching ComfyUI. Not by
    # filtering it out of `jobs` instead: an empty list falls through to the
    # untracked-orphan sweep below and interrupts anyway.
    if jid in HUB.jobs and HUB.jobs[jid].get("finalized"):
        return web.json_response({"ok": True, "stopped": 0})
    jobs = [HUB.jobs[jid]] if jid in HUB.jobs else \
        [j for j in HUB.jobs.values() if not j.get("finalized")]
    async with aiohttp.ClientSession() as s:
        for job in jobs:
            for pid in job["prompt_ids"]:
                try:
                    await s.post(f"{COMFY}/queue", json={"delete": [pid]}, timeout=10)
                except Exception:
                    pass
            if job["prompt_ids"]:
                try:
                    await s.post(f"{COMFY}/interrupt", timeout=10)
                except Exception:
                    pass
            job["error"] = "stopped"
            HUB.finalize(job)
        # HUB.jobs is in-memory, so a sidecar restart orphans whatever ComfyUI
        # is still rendering: the card freezes at step 1 and stop finds nothing
        # to cancel. Fall back to ComfyUI's own queue, which is the truth.
        if not jobs:
            orphans = await comfy_queue_ids(s)
            if orphans:
                try:
                    await s.post(f"{COMFY}/queue", json={"delete": orphans}, timeout=10)
                    await s.post(f"{COMFY}/interrupt", timeout=10)
                except Exception:
                    pass
                return web.json_response({"ok": True, "stopped": len(orphans),
                                          "untracked": True})
    return web.json_response({"ok": True, "stopped": len(jobs)})


async def comfy_queue_ids(session):
    """Every prompt id ComfyUI has running or pending, tracked by us or not."""
    try:
        async with session.get(f"{COMFY}/queue", timeout=10) as r:
            queue = await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return []
    ids = []
    for key in ("queue_running", "queue_pending"):
        for item in queue.get(key) or []:
            if isinstance(item, (list, tuple)) and len(item) > 1:
                ids.append(item[1])
    return ids


async def comfy_free(req):
    """Drop ComfyUI's cached models and let the allocator hand VRAM back.

    Deliberately manual. ComfyUI caches on purpose - the 21GB H3 stack staying
    resident is exactly why a second render is fast - so flushing after every
    job would make every job pay the load again. The chat brain is a separate
    llama.cpp process and is never touched by this.
    """
    body = await req.json() if req.can_read_body else {}
    payload = {"unload_models": bool(body.get("unload_models", True)),
               "free_memory": bool(body.get("free_memory", True))}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{COMFY}/free", json=payload, timeout=30) as r:
                ok = r.status == 200
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=502)
    if payload["unload_models"]:
        # The Settings button empties the card behind the butler's back. Left
        # unsaid, the next job would be credited with weights this call just
        # evicted and would price its own 20GB reload as free.
        HUB.forget_residency("settings freed vram")
    return web.json_response({"ok": ok})


async def free_chat_model(_req):
    """Hand back the VRAM the local chat brain is sitting on.

    Separate from /api/comfy/free on purpose: that one deliberately spares the
    chat model, because reloading it on every flush is exactly what nobody
    wants. This is the escape hatch for when its VRAM is the thing standing
    between you and a render that fits - H3's DiT alone stages at ~20GB, and a
    chat model that has grown a fat KV cache (measured at 7.2GB) is the
    difference between computing and streaming weights from host memory.

    Only ever touches a server WE spawned; the pidfile is the proof. The next
    LLM call brings it straight back.
    """
    if not _llm_state().get("pid"):
        return web.json_response({"ok": True, "freed": False,
                                  "note": "no chat model was started by Pixal"})
    before = gpu_free_bytes()
    if not await free_brain_vram():
        return web.json_response({"ok": True, "freed": False,
                                  "note": "the chat model was already gone"})
    after = gpu_free_bytes()
    freed = (after - before) if (before is not None and after is not None) else None
    return web.json_response({"ok": True, "freed": True,
                              "freed_gb": round(freed / 2**30, 1) if freed else None})


def gpu_stats():
    """(free bytes, used bytes, gpu util %, membus util %) or None. One
    nvidia-smi spawn; the utilization pair is what the paging detector needs -
    on WDDM a starved render shows busy cores over an idle memory bus while it
    streams weights from host RAM (H3, 2026-08: 100% GPU at 160W, 0% mem)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,memory.used,"
             "utilization.gpu,utilization.memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode != 0:
            return None
        free, used, gu, mu = (int(x.strip()) for x in
                              out.stdout.strip().splitlines()[0].split(","))
        return free * 2**20, used * 2**20, gu, mu
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def gpu_hogs():
    """[(name, bytes)] of OTHER processes provably holding real VRAM, biggest
    first - and empty unless the driver gives actual numbers. On WDDM
    nvidia-smi reads N/A for every process's bytes and prints bracketed
    placeholders ("[Insufficient Permissions]") for names it cannot see, so a
    row without a real size is pure noise: the first live run named
    explorer.exe as the squatter on ~9GB it did not hold. No number, no name.
    Pixal's own stack (ComfyUI's python, the llama.cpp brain) is excluded."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=process_name,used_gpu_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode != 0:
            return []
        rows = []
        for line in out.stdout.strip().splitlines():
            name, _, used = line.rpartition(",")
            base = Path(name.strip()).name.lower()
            used = used.strip()
            if (not base or base.startswith("[") or base == "python.exe"
                    or "llama" in base or not used.isdigit()):
                continue
            b = int(used) * 2**20
            if b >= int(0.5 * 2**30):   # under half a GB it is not "the rest"
                rows.append((base, b))
        rows.sort(key=lambda r: -r[1])
        return rows[:3]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def gpu_free_bytes():
    """Driver-level free VRAM, or None when it cannot be read.

    ComfyUI's /system_stats is the wrong source for this: during a render it
    reported 10.8GB free against nvidia-smi's 7.0GB, because torch counts its
    own reclaimable cache as free. When the question is "will a 20GB model fit
    alongside whatever else is on this card", only the driver's number answers
    it.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode != 0:
            return None
        return int(out.stdout.strip().splitlines()[0]) * 2**20
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


# --------------------------------------------------------------- vram butler
# Pricing a job before it queues. File size on disk tracks VRAM residency
# closely for safetensors/GGUF (int8 convrot: 12.57GB file -> 12.87GB loaded),
# so the weight bill is just the graph's model files summed once each. The
# activation profiles are heuristics tuned against measured runs on this box -
# deliberately a touch LOW, because overshooting evicts the chat brain on
# renders that were always going to fit (the wolf this must never cry).

VRAM_FLOOR = int(2.0 * 2**30)         # allocator slack beyond the estimate. Was
                                      # 1.0GB - 3% of this card, and thinner than
                                      # the desktop compositor's own resident
                                      # ~1.6GB. klein_inpaint 7f4d20e2 wanted a
                                      # single 17.09GB block with 13.02GB live
                                      # and got "Free (according to CUDA): 0
                                      # bytes": the sum fit the card, the block
                                      # did not fit the holes.
RAM_FLOOR = int(4.0 * 2**30)          # below this free RAM, Windows pages to disk
CRITIC_VRAM_NEED = int(20.0 * 2**30)  # 8B FP16 weights + vision tower (~17.5GB)
                                      # + generation activations + margin, in
                                      # DRIVER-free terms - a marginal pass OOMs
                                      # exactly like the unmanaged case did
PID_STACK_BYTES = int(4.5 * 2**30)    # PiD decoder + PixelDiT TE + autoencoder (measured)

# reclaim_vram's poll. /free returns before the pages do (cudaMallocAsync trims
# its pool asynchronously), so the deadline is what makes waiting safe rather
# than the sleep being long enough - it is a ceiling, not a duration.
VRAM_RECLAIM_DEADLINE = 8.0
VRAM_RECLAIM_POLL = 0.4
VRAM_RECLAIM_NOISE = int(0.05 * 2**30)   # under this, the pool has stopped moving

# Video is where the card gets tight and where a reload is cheapest to absorb:
# these renders run 90-170s, so paying ~10s to start from a clean card is noise,
# and starting from a dirty one is how all three ltx25 OOMs happened. Jesse's
# call, 2026-08-16: anything video flushes first, unconditionally.
VIDEO_TEMPLATES = frozenset((
    "ltx_i2v", "ltx25_i2v", "h3_i2v", "h3_multishot", "h3_ref2v",
    "upscale_video", "ltx25_upscale_video",
))
# How long a video submission will wait for the queue to drain so the
# unconditional flush above can actually run. Mid-queue the butler used to
# skip entirely - so a clip queued behind a finishing still started from a
# dirty card, which is the exact state all three ltx25 OOMs came from. 300s
# covers any still and most clips; at the deadline it proceeds as before.
VIDEO_DRAIN_WAIT = 300.0

# The WDDM paging tell (see gpu_stats): card effectively full, cores busy,
# memory bus idle = the GPU is streaming weights from host RAM, not rendering.
# Windows never surfaces this as an OOM - identity edit measured 110s/step at
# 99.9% full (2026-08-11) with nothing in any log. Four consecutive gpu_watch
# reads (~12s) before narrating, so a transient between-phase dip stays quiet.
PAGING_FREE_FLOOR = int(0.6 * 2**30)
PAGING_GPU_MIN = 85        # % cores busy
PAGING_MEMBUS_MAX = 10     # % memory-bus util below this = starved, not working
PAGING_STREAK = 4

# The rate watchdog (brief 9.10): watches the RENDER, where PAGING_* above
# watches the CARD - and fires in cases the card-level test misses, like a
# render paging against ANOTHER tenant's allocation on a not-quite-full card.
# A job's own opening steps are the baseline: a render that starts healthy
# and collapses is the paging signature; a render uniformly slow from step
# one is merely a big render, and a per-template expected s/it table would
# need the calibration data 9.8 only just started collecting. Sensor only:
# it logs and ledger-records once per job and deliberately does NOT act -
# what a tripped watchdog should DO (interrupt, flush-and-retry, narrate) is
# deferred until these logs show the real collapse rate instead of the one
# anecdote below.
# Coverage, said out loud: SKIP + BASELINE + STREAK means a job needs 10
# steps before it CAN trip. Covered: the 20-40 step lanes (qwen edit full,
# qwen image, H3 full, zimage base, anima base), the 12-16 step lanes
# (zimage anime, face mint, klein inpaint). Excluded by construction: the
# 4-step Lightning edit lane and every 8-step turbo lane - including the
# identity edit that motivated this brief, which may itself have been too
# short to detect. A 10-step lane (anima turbo) can trip only on its final
# step. A quiet ledger from short jobs means "unmeasured", not "no paging".
PAGING_RATE_SKIP = 1       # the first measured interval still carries one-off
                           # costs - allocator growth, autotune, the first
                           # preview decode - not the steady rate
PAGING_RATE_BASELINE = 5   # median of five early steps; one blip inside the
                           # window cannot move a median of five
PAGING_RATE_MULTIPLE = 4.0 # trip at 4x the job's own baseline. The observed
                           # signature was ~10x (110s/step, 2026-08-11) but that
                           # is ONE anecdote; for a log-only sensor a false
                           # positive costs a log line, a false negative costs
                           # the point of the brief. Ordinary step variance is
                           # within tens of percent - nowhere near 4x.
PAGING_RATE_STREAK = 4     # consecutive slow steps before a trip; one stall
                           # (a preview decode) must never fire it - the same
                           # reasoning PAGING_STREAK uses four reads for

def paging_rate_trip(durations, skip=PAGING_RATE_SKIP,
                     baseline=PAGING_RATE_BASELINE,
                     multiple=PAGING_RATE_MULTIPLE,
                     streak=PAGING_RATE_STREAK):
    """Pure detector over a job's measured per-step seconds, in order.

    Returns {"step", "baseline", "rate"} at the step where the collapse
    proves itself, else None. No clock, no GPU, no I/O - the sanctioned
    simulation for the live-machine rule: every test feeds injected numbers.
    Append-only input means the first trip is stable: once a streak of
    `streak` steps each >= multiple x the early median exists, every later
    call on the grown list reports the same trip, and the caller's per-job
    flag is what makes the logging once-only.
    """
    if len(durations) < skip + baseline + streak:
        return None                    # too few steps to even judge - no crash
    base = statistics.median(durations[skip:skip + baseline])
    if base <= 0:
        return None                    # a zero baseline trips on everything
    run = 0
    for i in range(skip + baseline, len(durations)):
        if durations[i] >= multiple * base:
            run += 1
            if run >= streak:
                return {"step": i + 1, "baseline": base, "rate": durations[i]}
        else:
            run = 0
    return None

# The last job's free_min below this makes the next job trim torch's
# reclaimable pool before it queues, however well it was priced. Between
# PAGING_FREE_FLOOR (0.6GB - where the paging detector fires, already the
# livelock) and VRAM_FLOOR (2.0GB - the slack the pricer reserves), so the
# near-miss is caught before it becomes either: 27 of the last 126 priced
# renders ended under 1.0GB. The trim is unload=False, always - it reclaims
# the allocator pool, never evicts a resident stack, because the reload IS
# the bill (warm identity_edit 27-28s, the same render flushed 41-54s).
PREV_JOB_FREE_GUARD = int(1.5 * 2**30)


def prev_floor_below_guard(prev_free_min, guard):
    """Did the last finalized job end closer to the wall than we tolerate?

    None means it was never sampled - no signal - and no signal must never
    read as zero, or one unsampled job switches the trim on forever (the
    stale-value bug class busy_elsewhere/forget_residency were written for).
    """
    return prev_free_min is not None and prev_free_min < guard

# ComfyUI surfaces the allocator failure as prose, and the exact wording varies
# by allocator backend - this box runs cudaMallocAsync, which says "Allocation
# on device 0 would exceed allowed memory. (out of memory)" where the native
# caching allocator says "CUDA out of memory. Tried to allocate ...". Match on
# the phrases common to both rather than on either one's full sentence.
OOM_MARKERS = ("out of memory", "exceed allowed memory", "outofmemoryerror",
               "cuda error: out of memory", "cublas_status_alloc_failed")

# Recipes that sample at their source's size but take no megapixels argument.
# Their canvas nodes are reachable through the `overrides` list every builder
# applies last, which is how the OOM retry shrinks them without a new signature.
OOM_SHRINK_NODES = {
    "klein_inpaint": ("ki:scale", "ki:maskscale"),
    "face_mint": ("fm:scale",),
}

# A decode OOM is a different failure from a sampling OOM and wants a different
# answer. The clip sampled fine - 40 minutes of it, in the case that prompted
# this - and only the VAE ran out of room turning latents into frames. Cutting
# the clip's length there throws away work that succeeded and fixes nothing
# about the step that failed.
DECODE_NODE_TYPES = ("VAEDecode", "VAEDecodeTiled", "VAEDecodeAudio",
                     "LTXVAudioVAEDecode", "LTXVLatentUpsampler")

# template -> the tiled decode whose temporal chunk we can turn down. Only
# templates that HAVE a temporal_size are listed; the rest fall through to the
# ordinary shrink path.
DECODE_TEMPORAL_NODES = {
    "ltx25_i2v": "32",
    "ltx25_upscale_video": "lu:decode",
}
DECODE_TEMPORAL_MIN = 8       # ComfyUI's own floor for temporal_size


def looks_like_oom(text):
    """Is this failure the card running out of room, rather than a bad graph?"""
    low = str(text or "").lower()
    return any(marker in low for marker in OOM_MARKERS)

# template -> (base GB, GB per canvas megapixel, GB per megapixel-FRAME).
#
# The third term is the one that was missing. Video used to be priced flat -
# "ltx25_i2v": (8.0, 0.0) charged the same for a 2-second clip and a 20-second
# one, when frames are the entire cost curve. All three ltx25 OOMs on
# 2026-08-16 were the same shape: the butler waved through a clip whose latent
# it had never looked at.
#
# Stills leave the frame term at 0 and are priced base + slope*megapixels;
# video leaves the megapixel term at 0 and is priced base + slope*mp*frames,
# so neither pays the other's curve. Every number here is a heuristic tuned on
# this box and still deliberately a touch LOW - overshooting evicts the chat
# brain on renders that were always going to fit, which is the wolf this must
# never cry. The OOM retry is what covers the tail; this only has to be close.
ACT_PROFILES = {
    # Edit recipes carry the reference injection AND a full-canvas VAE decode
    # spike at the end. Measured 2026-08-11: identity (19GB weights) + chat
    # brain (7GB) + the app window's compositor no longer fits a 32GB card -
    # first steps paged for ~40s until the window was minimized. This profile
    # is deliberately high enough that the butler rests the brain for these;
    # a 7s brain reload on the next chat beats a paging render every time.
    "identity_edit": (2.0, 1.5, 0.0), "zara_edit": (2.0, 1.5, 0.0),
    "qwen_edit": (2.0, 1.5, 0.0),
    # Klein encodes the source TWICE (masked latent + full-frame reference), so
    # its slope is double a single-encode edit's.
    "klein_inpaint": (2.0, 3.0, 0.0),
    # face_mint samples every step at the source's size rather than spiking
    # once at the end - same slope shape as an edit, higher base for Krea 2.
    "face_mint": (2.5, 1.5, 0.0),
    "upscale_image": (8.0, 0.0, 0.0),
    # LTX 2.5's slope is fitted to the only two hard numbers in the log, which
    # have to be satisfied together: 5s clips SUCCEEDED six times (so peak was
    # under the card), and three OOM'd at 29.91GB live wanting 6.35GB more (so
    # peak was ~36GB). Both hold only if the failures were longer clips. With
    # the 22.7GB staged weight peak, 0.045/mp-frame puts 5s at ~31.5GB - just
    # inside a 31.84GB card, which is exactly a render that sometimes lands and
    # sometimes does not - and 10s at ~36GB, which is the OOM.
    "ltx_i2v": (4.0, 0.0, 0.045), "ltx25_i2v": (4.0, 0.0, 0.045),
    # Same sampler, and its canvas_mp already carries the x2 upsample, so the
    # same slope over a 4x larger canvas.
    "ltx25_upscale_video": (4.0, 0.0, 0.045),
    # RTX VSR is a pure image-space filter - no sampler, no latent, no VAE. It
    # only ever holds a few frames at a time.
    "upscale_video": (2.0, 0.0, 0.002),
    # H3 is far cheaper per frame than the token count suggests: 24 latent
    # channels against LTX's 128. Fitted the same way - 15s at 362 frames
    # succeeded (169s, job 606e2e9d) on top of a 24.9GB weight peak, so its
    # activations cannot exceed ~7GB.
    "h3_i2v": (5.0, 0.0, 0.005), "h3_multishot": (5.0, 0.0, 0.005),
    # h3_i2v's exact coefficients: same spine, same canvas math. The
    # per-REFERENCE surcharge is real (ref latents ride every sampling step)
    # but unmeasured here - pricing it would need a sanctioned render, and an
    # invented coefficient is worse than the OOM retry covering the tail.
    "h3_ref2v": (5.0, 0.0, 0.005),
}
ACT_DEFAULT = (1.0, 1.2, 0.0)
# Ceiling on a canvas the pricer had to GUESS at from the graph. Nothing Pixal
# renders comes near it; it exists so one stray preset field cannot price a
# render at several hundred GB and evict the whole card to make room.
ACT_SCAN_MP_CEILING = 64.0

# The input name a loader uses -> the model folders that name could live in.
# Several of these are wider than the loader's own folder on purpose, because
# custom-node loaders reach across kinds: ltx_i2v names its video VAE through a
# CheckpointLoaderSimple even though the file sits in vae/, and every one of
# those mismatches priced at 0 bytes with no warning.
WEIGHT_KEYS = {"unet_name": ("diffusion_models", "unet"),
               "ckpt_name": ("checkpoints", "vae", "diffusion_models"),
               "clip_name": ("text_encoders", "clip"),
               "text_encoder": ("text_encoders", "clip"),   # LTXAVTextEncoderLoader
               "vae_name": ("vae",),
               "lora_name": ("loras",),
               # LatentUpscaleModelLoader shares the input name with
               # UpscaleModelLoader but keeps its files in their own folder.
               "model_name": ("upscale_models", "latent_upscale_models")}
HEAVY_KEYS = ("unet_name", "ckpt_name", "clip_name", "text_encoder")


def _weight_file_bytes(kinds, rel):
    rel_l = rel.replace("/", "\\").lower()
    for e in model_catalog():
        if e["kind"] in kinds and e["rel"].replace("/", "\\").lower() == rel_l:
            try:
                return (Path(e["root"]) / e["kind"] / e["rel"]).stat().st_size
            except OSError:
                return 0
    return 0


def graph_weight_bill(g):
    """({heavy file -> bytes}, peak bytes) for the weights the graph pages in.

    PEAK, not sum - this is the correction that stopped the butler crying wolf
    on every video render. ComfyUI loads on demand and evicts by LRU, so a
    staged graph never holds its whole bill at once: LTX 2.5 names 45.6GB of
    files on a 31.8GB card and renders fine, because its two Gemma text
    encoders (23.9GB together) are finished before its 20.0GB DiT is needed.
    Summing them priced every LTX render as impossible, so the butler flushed
    the cache and evicted the chat brain before all of them - and they OOM'd
    anyway, because the number it was defending was fiction.

    What must genuinely fit at one instant is the largest single model plus
    everything small enough to sit beside it (VAEs, LoRAs, upscalers) plus the
    activations. Anything above that line is staging, which is ComfyUI's job
    and which it does well. `heavy` is still every heavyweight by name, because
    residency tracking wants them all.

    PiD's checkpoints are loaded by name inside its own nodes rather than
    through loader inputs, so a PiD node adds the measured flat cost of its
    stack - it is never the staged-away one."""
    seen, pid_stack = {}, False
    for node in g.values():
        if node.get("class_type") in (PID_UPSCALE_NODE, PID_DECODE_NODE):
            pid_stack = True
        for key, val in (node.get("inputs") or {}).items():
            if key in WEIGHT_KEYS and isinstance(val, str) and val and val not in seen:
                seen[val] = (key, _weight_file_bytes(WEIGHT_KEYS[key], val))
    heavy = {name: sz for name, (key, sz) in seen.items() if key in HEAVY_KEYS}
    light = sum(sz for _name, (key, sz) in seen.items() if key not in HEAVY_KEYS)
    peak = (max(heavy.values()) if heavy else 0) + light
    return heavy, peak + (PID_STACK_BYTES if pid_stack else 0)


def graph_activation_bytes(template, g, info=None):
    """Sampling working-set estimate: base + per-megapixel + per-megapixel-frame.

    The canvas comes from the BUILDER (`info["canvas_mp"]`, `info["frames"]`)
    rather than from scanning the graph, because scanning was wrong in both
    directions. It missed the canvas entirely on every source-image recipe -
    klein_inpaint and qwen_edit carry no literal width/height at all, so `mp`
    read 0.0 and a 30MP inpaint priced at the 1.0GB floor. And it over-read it
    wherever a node mentions a size for some other reason: klein's composite
    step names the source's full resolution, which a max() over every
    width/height in the graph would charge as the sampling canvas.

    The graph scan stays as the fallback for builders that have not been taught
    to report, and it is still the right shape for those - an EmptyLatentImage
    node's width/height IS the canvas."""
    # "upscale_video" covers two completely different jobs: an RTX VSR filter
    # with no sampler at all, and a 22B two-pass LTX re-render. They dispatch
    # under one template name, so the graph is the only thing that can tell
    # them apart - the latent upsampler is the tell.
    if template == "upscale_video" and any(
            n.get("class_type") == "LTXVLatentUpsampler" for n in g.values()):
        template = "ltx25_upscale_video"
    base_gb, per_mp, per_mp_frame = ACT_PROFILES.get(template, ACT_DEFAULT)
    info = info or {}
    # peak_frames wins where the two differ: a multishot take reports every
    # frame it will deliver, but samples one shot at a time.
    mp = info.get("canvas_mp")
    frames = info.get("peak_frames") or info.get("frames")
    if not isinstance(mp, (int, float)) or mp <= 0:
        mp = 0.0
        for node in g.values():
            ins = node.get("inputs") or {}
            w, h = ins.get("width"), ins.get("height")
            if isinstance(w, (int, float)) and isinstance(h, (int, float)):
                mp = max(mp, (w * h) / 1e6)
        # The scan reads any node that happens to mention a size, including
        # preset fields that have nothing to do with the canvas. Clamp it:
        # a wrong estimate should cost a needless flush, not price a render at
        # several hundred GB and evict everything on the card.
        mp = min(mp, ACT_SCAN_MP_CEILING)
    if not isinstance(frames, (int, float)) or frames < 1:
        frames = 0.0
        for node in g.values():
            length = (node.get("inputs") or {}).get("length")
            if isinstance(length, (int, float)):
                frames = max(frames, float(length))
        frames = frames or 1.0
    return int((base_gb + per_mp * mp + per_mp_frame * mp * frames) * 2**30)


def ram_free_bytes():
    """Available physical RAM via GlobalMemoryStatusEx - no dependency needed,
    and 'available' (not 'free') is the number that predicts paging."""
    import ctypes
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullAvailPhys)
    except (AttributeError, OSError):
        pass
    return None


async def comfy_vram_free_bytes():
    """ComfyUI's torch-aware free VRAM: driver free PLUS torch's reclaimable
    cache. This is the RIGHT source for budgeting comfy's own next job - right
    after a render the driver number reads low precisely because torch kept its
    activation pool as reusable cache, and treating that as 'full' is the
    wolf-cry the old pre-flight check died of. (gpu_free_bytes stays the right
    source for 'will this fit alongside OTHER processes'.)"""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{COMFY}/system_stats", timeout=10) as r:
                d = await r.json()
        dev = next((x for x in d.get("devices", []) if x.get("type") == "cuda"), None)
        return int(dev["vram_free"]) if dev else None
    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError,
            TypeError, ValueError):
        return None


async def free_brain_vram():
    """Kill the chat brain WE spawned (the pidfile is the proof) and wait for
    the driver to reclaim its VRAM. True only when a live process actually
    died. Never fatal: the next LLM call starts it fresh."""
    st = _llm_state()
    pid = st.get("pid")
    if not pid:
        return False
    killed = _llm_kill(pid)
    if killed:
        await asyncio.sleep(1.5)          # the driver reclaims after the exit
    # Disown it ONLY when it is really gone. The pidfile used to come off
    # either way ("stale either way"), and it is not stale when the kill did
    # not land - taskkill answers ACCESS DENIED, or the process is still
    # inside a CUDA call. That left a LIVE brain Pixal no longer owned:
    # _llm_state() read empty from then on, _ensure_local_llm's "up and not
    # st" adopted it as an externally-started server and never respawned it,
    # and llm_call's vision gate (bool(state["mmproj"])) went permanently
    # False - so _delocalize flattened every attached image to the literal
    # text "[attached image]". Chat still looked fine; every LOOK went blind,
    # and an H3 first-frame read died with "the brain that answered has no
    # live projector" on a brain whose projector was loaded and working
    # (Jesse, 2026-08-23 - 5000 log lines of "Media count: 0").
    if not await local_llm_port_open():
        LLM_STATE.unlink(missing_ok=True)
    return killed


async def image(req):
    q = req.rel_url.query
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{COMFY}/view", params={
            "filename": q.get("filename", ""),
            "subfolder": q.get("subfolder", ""),
            "type": q.get("type", "output"),
        }, timeout=60) as r:
            data = await r.read()
            return web.Response(body=data, content_type=r.content_type,
                                status=r.status)


@lru_cache(maxsize=256)
def _output_thumbnail_bytes(path_text, mtime_ns):
    """Lane-sized WebP preview of a finished render. 1600px at quality 90:
    the original 1024/q80 pass visibly crushed skin and gradients on the lane
    (Jesse, 2026-08-12) — this is still ~100x under a PiD 4x PNG, which is the
    weight the preview exists to avoid. The RAW file in output/ is never
    touched — the lightbox and the download button read the original through
    /view. Bump the v= tag in thumbUrl (transport.js) if this encode changes
    again: previews are browser-cached immutable, old crush never heals."""
    from PIL import Image, ImageOps
    with Image.open(path_text) as source:
        source.seek(0)
        thumb = ImageOps.exif_transpose(source).copy()
    thumb.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    if thumb.mode not in ("RGB", "RGBA"):
        thumb = thumb.convert("RGBA" if "transparency" in thumb.info else "RGB")
    out = io.BytesIO()
    thumb.save(out, format="WEBP", quality=90, method=6)
    return out.getvalue()


async def output_thumbnail(req):
    """Bounded preview of a rendered output; RAW stays where ComfyUI put it.

    Anything this cannot thumbnail — a video container, a remote-ComfyUI box
    whose outputs are not on this disk, an exotic format — falls back to the
    full /view proxy, so a miss costs fidelity of intent, never a broken tile."""
    q = req.rel_url.query
    filename = (q.get("filename") or "").strip()
    sub = (q.get("subfolder") or "").strip().strip("/\\")
    typ = q.get("type", "output")
    if not filename or typ not in ("output", "input", "temp"):
        return web.json_response({"ok": False, "error": "bad thumb request"}, status=400)
    root = (CDIR / typ).resolve()
    path = ((root / sub / filename) if sub else (root / filename)).resolve()
    if not path.is_file() or not path.is_relative_to(root):
        return await image(req)
    try:
        stat = path.stat()
        data = await asyncio.to_thread(_output_thumbnail_bytes, str(path), stat.st_mtime_ns)
    except (OSError, ValueError):
        return await image(req)
    # Output filenames are unique per render, so the preview is immutable.
    return web.Response(body=data, content_type="image/webp", headers={
        "Cache-Control": "private, max-age=604800, immutable",
        "ETag": f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"',
    })


async def input_thumbnail(req):
    """Serve a bounded preview without making the browser decode full-size inputs."""
    name = input_ref_name(req.rel_url.query.get("name"))
    if not name:
        return web.json_response({"ok": False, "error": "invalid input image"}, status=400)
    root = (CDIR / "input").resolve()
    path = (root / name).resolve()
    if not path.is_file() or not path.is_relative_to(root):
        return web.json_response({"ok": False, "error": "input image not found"}, status=404)
    try:
        stat = path.stat()
        data = await asyncio.to_thread(_input_thumbnail_bytes, str(path), stat.st_mtime_ns)
    except (OSError, ValueError) as exc:
        return web.json_response(
            {"ok": False, "error": f"could not preview input image: {exc}"}, status=415)
    return web.Response(body=data, content_type="image/webp", headers={
        "Cache-Control": "private, max-age=86400",
        "ETag": f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"',
    })

ACCESS_KEY = ""     # set at boot; empty would mean the gate is off (it never is)

# Headers a reverse proxy puts in front of us (tailscale serve, cloudflared,
# nginx). Their PRESENCE means the socket we can see belongs to the proxy, not
# to the visitor - so a loopback peer proves nothing and the key is required.
# Without this check, putting any proxy in front of Pixal would hand every
# visitor on earth the free local pass.
_PROXY_HEADERS = frozenset((
    "tailscale-user-login", "tailscale-user-name", "tailscale-user-profile-pic",
    "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip",
    "forwarded", "cf-connecting-ip",
))


def _is_local_peer(request):
    """True only for a real loopback TCP peer with nobody forwarding for it.

    Until 2026-08-14 this was `request.host.split(":")[0] in ("127.0.0.1",
    "localhost")` - and `request.host` is the client-supplied HOST HEADER, not
    the connection. One `-H "Host: localhost"` therefore walked past the gate on
    every route, GET and POST, verified live against this sidecar from another
    machine on the LAN while lan_access was on. The sibling branch trusted an
    unsigned `Tailscale-User-Login` header on the same reasoning; that header is
    only stripped by `tailscale serve`, and `lan_access` is a bare 0.0.0.0 bind
    with nothing in front of it, so it was attacker-supplied too.

    Locality is a property of the socket. Never of anything the caller can type.
    """
    peer = request.transport.get_extra_info("peername") if request.transport else None
    if not peer:
        return False                       # no socket to vouch for it
    try:
        if not ipaddress.ip_address(peer[0]).is_loopback:
            return False
    except ValueError:
        return False                       # unparseable peer - not local
    return not any(h.lower() in _PROXY_HEADERS for h in request.headers)


@web.middleware
async def access_gate(request, handler):
    """The lock in front of every route. The app on THIS machine passes free;
    anything arriving over a network - LAN, tailnet, or a tunnel later - presents
    ?key=<access_key> once, which then rides an httponly cookie for 30 days.
    Wrong/no key = 403 with no hints.

    There is deliberately no free pass for tailnet devices any more (see
    _is_local_peer). A tailnet device visits the keyed URL once, exactly like
    every other remote device - one URL per device, and it removes a trust
    assumption that only held under a deployment mode Pixal does not use."""
    if _is_local_peer(request):
        return await handler(request)
    key = request.query.get("key") or request.cookies.get("pixal_key")
    if ACCESS_KEY and hmac.compare_digest(key or "", ACCESS_KEY):
        resp = await handler(request)
        if request.query.get("key"):
            resp.set_cookie("pixal_key", ACCESS_KEY, max_age=30 * 86400,
                            httponly=True, samesite="Lax")
        return resp
    return web.Response(status=403, text="pixal: key required")

# The ONLY ComfyUI paths a browser may pull through the sidecar. This was
# `{tail:.*}` until 2026-08-14 - i.e. every GET route on a ComfyUI carrying ~50
# custom-node packs. That handed a caller VideoHelperSuite's /getpath (a full
# directory listing of the user's home folder, .aws and .bash_history included),
# deno's external-image-view (absolute-path file read outside the ComfyUI tree),
# and easy-use's /reboot (an os.execv). Worse, the proxy LAUNDERS the caller:
# ComfyUI sees 127.0.0.1, so the node packs that defend themselves with their own
# loopback check were disarmed by the very hop meant to protect them.
COMFY_ASSET_PREFIXES = ("api/lm/previews",)


def _preview_path_ok(raw):
    """lora-manager's /api/lm/previews takes an ABSOLUTE path, so allowlisting
    the prefix alone would still leave an arbitrary-image reader. Bound it to the
    model roots Pixal already scans - a preview that isn't beside a model is not
    a preview."""
    if not raw:
        return False
    try:
        p = Path(urllib.parse.unquote(raw)).resolve()
    except (OSError, ValueError):
        return False
    for root in model_roots():
        try:
            if p.is_relative_to(Path(root).resolve()):
                return True
        except (OSError, ValueError):
            continue
    return False


async def comfy_asset(req):
    """GET passthrough to ComfyUI for browser-visible assets (lora-manager preview
    thumbs/videos). Remote viewers only ever see :8190 - :8188 stays private,
    which is exactly why this must stay an allowlist and never become a proxy."""
    tail = req.match_info["tail"]
    if not tail.startswith(COMFY_ASSET_PREFIXES):
        # Loud, because the failure mode of getting this list wrong is a missing
        # thumbnail with no explanation. If a preview vanishes, this line names
        # the path it wanted.
        print(f"[pixal] comfy passthrough refused: /{tail}", flush=True)
        return web.Response(status=404)
    if not _preview_path_ok(req.query.get("path")):
        return web.Response(status=404)
    url = f"{COMFY}/{tail}"
    if req.query_string:
        url += "?" + req.query_string
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=60) as r:
                body = await r.read()
                ct = (r.headers.get("Content-Type") or "application/octet-stream")
                return web.Response(body=body, status=r.status,
                                    content_type=ct.split(";")[0].strip(),
                                    headers={"Cache-Control": "max-age=3600"})
    except Exception:
        return web.Response(status=502)

async def warmup_catalog():
    """Scan every model root at boot: warms the catalog cache AND narrates itself -
    each stage broadcasts over SSE so the UI can show what the scanner sees."""
    def say(text, done=False, totals=None):
        HUB.scan = {"text": text, "done": done, "totals": totals}
        HUB.broadcast(type="scan", **HUB.scan)
    try:
        say("scanning models…")
        entries = []
        for root in model_roots():
            for kd in KIND_DIRS:
                base_dir = root / kd
                if not base_dir.is_dir():
                    continue
                n0 = len(entries)
                for p in base_dir.rglob("*"):
                    if p.is_file() and p.suffix.lower() in MODEL_EXTS \
                            and ".cache" not in p.parts:
                        try:
                            mtime = p.stat().st_mtime
                        except OSError:
                            mtime = 0
                        entries.append({"kind": kd, "root": str(root),
                                        "rel": str(p.relative_to(base_dir)),
                                        "mtime": mtime})
                if len(entries) > n0:
                    say(f"{kd} - {len(entries) - n0} files")
        _CATALOG.update(at=time.time(), data=entries)
        say("reading lora titles…")
        await refresh_lm_cache(ttl=0)          # lora-manager names/previews, if present
        # Whatever lora-manager left unnamed gets Pixal's own Civitai/CivArchive
        # by-hash pass in the background; the UI refetches options when it lands.
        asyncio.create_task(refresh_civitai_meta())
        opts = HUB.options()                   # scrapes any new titles, builds lists
        titled = sum(1 for l in opts["loras"] if l.get("title"))
        vl = installed_vl_models()
        totals = (f"{len(entries)} files · {len(opts['loras'])} loras "
                  f"({titled} titled) · {len(opts['models'])} UNETs · {len(vl)} critics")
        say(None, done=True, totals=totals)
        print(f"[pixal] catalog: {totals} | roots: {len(model_roots())}", flush=True)
    except Exception as e:
        say(None, done=True, totals=None)
        print(f"[pixal] catalog warmup failed: {e}", flush=True)

# Starting ComfyUI is NOT "run main.py". This install's launcher carries
# --fast fp16_accumulation, --use-sage-attention and --disable-dynamic-vram,
# plus TORCHINDUCTOR_CACHE_DIR and a vcvars call. Bypassing it silently drops
# every one of them - measured here as a visibly slower machine.
COMFY_LAUNCHER_PREFERENCE = ("run_nvidia_gpu_fast_fp16_accumulation.bat",
                             "run_nvidia_gpu.bat")
COMFY_BOOT_FALLBACK_SECONDS = 45.0
# The console that window shows. comfy_tui.py runs the SAME launcher on a pipe
# and draws it - phase meter, card meter, and the errors-only log below, which
# is the part that outlives the window. Settings can put the raw .bat back.
COMFY_TUI = HERE / "comfy_tui.py"
COMFY_LOGS = HERE / "logs"
# Written by the TUI the first time a boot says something that looks like a
# failure. One line, so the overlay can name the actual cause instead of
# sending everyone to a console window that has already closed.
COMFY_ERROR_LINE = COMFY_LOGS / "comfy-last-error.txt"
COMFY_ERROR_LOG = COMFY_LOGS / "comfy-errors.log"
# "proc" is the cmd.exe we spawned, held so shutdown can kill a ComfyUI that
# never bound the port. Finding it by port alone misses exactly the process that
# most needs killing: one that started, lost the bind race, and stayed resident
# holding VRAM with nothing pointing at it.
# "stalled_since" is when we first saw ComfyUI still OWNING the port but not
# answering. That state is never auto-killed - a big model load looks identical
# to a wedge from out here, and taskkilling the wrong one costs a live render -
# so it is surfaced instead, and the kill stays the user's call.
COMFY_BOOT = {"at": None, "launcher": None, "error": None, "task": None,
              "proc": None, "stalled_since": None}


def find_comfy_launcher(root=None):
    """The launcher the user actually starts ComfyUI with - it sits BESIDE the
    ComfyUI folder, not inside it. CPU and A/B test launchers are skipped.

    nt: the tuned .bat - its flags are measured, and bypassing them is slower.
    POSIX: a run*.sh beside the checkout wins (invoked through bash, so the
    executable bit does not matter), else the checkout's own main.py. A .bat
    is not bootable there, so it is never a POSIX candidate."""
    base = Path(root or CDIR).parent
    if not _nt():
        for candidate in sorted(base.glob("run*.sh")):
            low = candidate.name.lower()
            if "cpu" not in low and "test" not in low:
                return candidate
        main_py = Path(root or CDIR) / "main.py"
        return main_py if main_py.is_file() else None
    for name in COMFY_LAUNCHER_PREFERENCE:
        candidate = base / name
        if candidate.is_file():
            return candidate
    for candidate in sorted(base.glob("run*.bat")):
        low = candidate.name.lower()
        if "cpu" not in low and "test" not in low:
            return candidate
    return None


def comfy_launch_command(launcher):
    """(argv, cwd, env) for the ComfyUI console - wrapped, or raw.

    Both nt paths run the same .bat: its --fast fp16_accumulation,
    --use-sage-attention and vcvars call are load-bearing, and bypassing them is
    measurable as a slower machine. The only question is who owns the window.
    POSIX has no window to own and no tuned .bat: a run*.sh goes through bash,
    a bare checkout through its own main.py with the best local python.
    """
    cfg = load_config()
    env = dict(os.environ)
    editor = bool(cfg.get("comfy_editor"))
    if cfg.get("comfy_console") != "plain" and COMFY_TUI.is_file() \
            and sys.platform == "win32":
        cmd = [_console_python(), str(COMFY_TUI), "--launcher", str(launcher),
               "--log-dir", str(COMFY_LOGS), "--url", COMFY,
               "--expect", str(cfg.get("comfy_boot_seconds") or 0.0)]
        if editor:
            cmd.append("--editor")
        # HERE, not the launcher's folder: the wrapper cd's the .bat itself, and
        # running from Pixal's root keeps its logs where Pixal's logs live.
        return cmd, str(HERE), env
    if not _nt():
        if launcher.suffix == ".sh":
            # bash, never ./run.sh: a fresh clone may not carry the +x bit.
            return ["bash", str(launcher)], str(launcher.parent), env
        # The checkout's own main.py. Args actually forward here, so the
        # comfy_editor contract keeps its shape: --disable-auto-launch is the
        # direct form of the rundll32 trick the nt raw path is forced into.
        python = next((str(p) for p in _posix_python_candidates(launcher.parent)
                       if p.is_file()), sys.executable)
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
        env["BROWSER"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                      "System32", "rundll32.exe")
    return ["cmd.exe", "/c", str(launcher)], str(launcher.parent), env


def _console_python():
    """The interpreter to draw the console with - never a windowless one.

    pythonw.exe has no stdout to draw on, so a sidecar started under it would
    open a console window that stayed blank forever."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        windowed = exe.with_name("python.exe")
        if windowed.is_file():
            return str(windowed)
    return str(exe)


def comfy_last_error():
    """The one line the wrapper wrote about why this boot failed, if it did.

    A console window that has already closed is not a place a user can "go look
    at the error", which is why this file exists at all: the overlay gets to
    name the actual cause. Only trusted while it is newer than the boot we are
    reporting on - a stale one would blame this attempt for the last one."""
    try:
        if COMFY_ERROR_LINE.stat().st_mtime < (COMFY_BOOT["at"] or 0):
            return ""
        return COMFY_ERROR_LINE.read_text(encoding="utf-8", errors="replace").strip()[:300]
    except (OSError, ValueError):
        return ""


# Boot-stage markers in the order ComfyUI's own log emits them, latest first.
# The long silent stretch of a cold boot is the pack-import phase between the
# VRAM banner and the import-times table, so "Total VRAM" reads as that.
_BOOT_PHASES = (("Starting server", "starting the web server"),
                ("Import times for custom nodes", "final checks"),
                ("Total VRAM", "loading node packs"),
                ("Prestartup times", "prestart hooks"),
                ("** ComfyUI startup time", "waking Python"))

def _comfy_boot_phase(started_at):
    """The boot's ACTUAL stage, read from ComfyUI's live log; None if unknowable.

    comfyui.log rotates when the new process starts writing, so an mtime older
    than our launch means we would be reading the previous session's log."""
    log = CDIR / "user" / "comfyui.log"
    try:
        if not started_at or log.stat().st_mtime < started_at:
            return None
        with open(log, "rb") as f:
            f.seek(max(0, log.stat().st_size - 8192))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    return next((phase for marker, phase in _BOOT_PHASES if marker in tail), None)

def comfy_boot_state():
    """What the UI needs to draw an honest boot meter.

    ``expected`` is the last measured cold start, so the bar is calibrated to
    this machine instead of a guess; the first boot falls back to a constant.
    """
    cfg = load_config()
    expected = float(cfg.get("comfy_boot_seconds") or COMFY_BOOT_FALLBACK_SECONDS)
    started = COMFY_BOOT["at"]
    stalled = COMFY_BOOT["stalled_since"]
    return {"starting": bool(started) and not HUB.comfy_up,
            # Closing the console is a decision, so the overlay says so and
            # offers to start it again rather than sitting on "waiting for
            # ComfyUI" against something nothing is going to bring back.
            "closed": comfy_closed_by_user() and not HUB.comfy_up,
            "elapsed": round(time.time() - started, 1) if started else 0.0,
            "expected": expected,
            "phase": _comfy_boot_phase(started),
            "launcher": Path(COMFY_BOOT["launcher"]).name if COMFY_BOOT["launcher"] else None,
            # Seconds ComfyUI has owned the port without answering. NOT an
            # error: it is the normal shape of a big model load, and writing
            # COMFY_BOOT["error"] here would stick a false "ComfyUI didn't
            # start" over every 8B/H3 load and hide the progress bar with it.
            "stalled": round(time.time() - stalled, 1) if stalled else 0.0,
            "error": COMFY_BOOT["error"],
            # Where the rest of it is. The overlay prints this under an error so
            # the answer is a file you can open, not a window that has closed.
            "error_log": str(COMFY_ERROR_LOG) if COMFY_ERROR_LOG.exists() else ""}


async def comfy_reachable(timeout=4):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{COMFY}/system_stats", timeout=timeout) as r:
                return r.status == 200
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return False


async def ensure_comfy_running():
    """Bring ComfyUI up through its own launcher when it isn't already.

    So one click on Pixal is the whole studio: the sidecar starts, notices
    ComfyUI is down, and boots it in its own console while the UI shows a meter.
    """
    if await comfy_reachable():
        COMFY_BOOT["stalled_since"] = None      # it answered - no stall to report
        return
    # A boot still IN FLIGHT is not a reason to start a second one: two
    # launchers race for port 8188, one wins the bind and the loser runs on with
    # no port, which is precisely a ghost backend. COMFY_BOOT["at"] is what "in
    # flight" means - every exit path in the watcher below clears it.
    #
    # A live child with NO boot in flight is a different animal, and conflating
    # the two is what wedged the studio (2026-08-13). When ComfyUI crashes its
    # .bat parks on "Press any key to continue", so cmd.exe stays alive forever
    # and every later attempt returned right here, instantly: no boot, no error,
    # nothing running, for the rest of the sidecar's life. That console is a
    # corpse holding the door open - close it and start a fresh one.
    live = COMFY_BOOT.get("proc")
    if live is not None and live.poll() is None:
        if COMFY_BOOT.get("at"):
            return
        # A BUSY ComfyUI is not a corpse. Loading the 8B VL critic or the H3
        # stack holds its event loop long past comfy_reachable's timeout, the
        # bridge websocket drops, and /api/status re-enters here every 4s for as
        # long as comfy_up is false - so without this check a big model load
        # gets its whole tree taskkill'd mid-render (2026-08-14). The port is
        # the discriminator: a .bat parked on "Press any key" has no python left
        # holding the socket, while a stalled one is still bound. A boot that
        # timed out never bound it either, so it is still correctly reaped.
        if await asyncio.to_thread(comfy_listener_pid) is not None:
            # Never kill a process that still owns the port. But do not leave the
            # user staring at a meterless "waiting for ComfyUI" either: record
            # when the stall began so comfy_boot_state can offer a way out.
            if COMFY_BOOT["stalled_since"] is None:
                COMFY_BOOT["stalled_since"] = time.time()
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
            await asyncio.to_thread(_taskkill, live.pid)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"[pixal] could not close the stale ComfyUI console: {exc}",
                  flush=True)
        COMFY_BOOT["proc"] = None
    launcher = find_comfy_launcher()
    if not launcher:
        shape = ".bat" if _nt() else "run*.sh or main.py"
        COMFY_BOOT["error"] = (f"no ComfyUI launcher ({shape}) found beside the "
                               "ComfyUI folder - start it yourself")
        print("[pixal] " + COMFY_BOOT["error"], flush=True)
        return
    COMFY_BOOT.update(at=time.time(), launcher=str(launcher), error=None)
    # A fresh ComfyUI holds nothing. The log has 25+ of these in one session and
    # the butler credited every one of them with the dead process's residency.
    HUB.forget_residency("comfy restarting")
    print(f"[pixal] starting ComfyUI via {launcher.name}", flush=True)
    try:
        cmd, cwd, env = comfy_launch_command(launcher)
        if _nt():
            # The launcher gets its own normal console window - the same one
            # you get by double-clicking it. That window IS the VRAM indicator:
            # open means something is still on the card, and closing it takes
            # ComfyUI down. (comfy_tui keeps that contract with a job object;
            # see own_the_tree.) wShowWindow has to be explicit because
            # pixal.vbs starts run.bat HIDDEN, and a new console inherits its
            # parent's show state unless you name one.
            show = subprocess.STARTUPINFO()
            show.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            show.wShowWindow = 1                            # SW_SHOWNORMAL
            COMFY_BOOT["proc"] = subprocess.Popen(
                cmd, cwd=cwd, creationflags=0x00000010,     # CREATE_NEW_CONSOLE
                startupinfo=show, env=env)
        else:
            # No console to dress on POSIX - but start_new_session is not a
            # nicety: it makes the launcher a process-group leader, which is
            # what lets _taskkill take launcher and python down as one tree.
            COMFY_BOOT["proc"] = subprocess.Popen(
                cmd, cwd=cwd, env=env, start_new_session=True)
    except OSError as exc:
        COMFY_BOOT.update(at=None, error=f"could not start {launcher.name}: {exc}")
        print("[pixal] " + COMFY_BOOT["error"], flush=True)
        return
    for _ in range(180):                                    # 6 minutes of grace
        await asyncio.sleep(2)
        if await comfy_reachable(timeout=3):
            took = round(time.time() - COMFY_BOOT["at"], 1)
            print(f"[pixal] ComfyUI up in {took}s", flush=True)
            cfg = load_config()                    # calibrate the next boot meter
            cfg["comfy_boot_seconds"] = took
            save_config(cfg)
            # Hold the boot state until the hub's own watcher agrees. Clearing it
            # the moment the port answers blinks the UI through a frame that says
            # "waiting for ComfyUI" with no meter, right at the finish line.
            for _ in range(20):
                if HUB.comfy_up:
                    break
                await asyncio.sleep(1)
            COMFY_BOOT["at"] = None
            return
        # A launcher that has already exited is never going to answer, so a
        # crashed boot reports in seconds instead of riding out the grace.
        # (A .bat parked on `pause` after a crash keeps cmd.exe alive; that
        # shape still takes the timeout - poll() catches the clean exits.)
        proc = COMFY_BOOT.get("proc")
        if proc is not None and proc.poll() is not None:
            # "its console window has the error" was true and useless: by the
            # time anyone reads this the window is gone. The wrapper leaves the
            # reason on disk, so say the reason.
            why = comfy_last_error()
            COMFY_BOOT.update(at=None, error=(
                f"ComfyUI exited during boot - {why}" if why else
                "ComfyUI exited during boot - the output is in logs\\comfy.log"))
            print("[pixal] " + COMFY_BOOT["error"], flush=True)
            return
    why = comfy_last_error()
    COMFY_BOOT.update(at=None, error=("ComfyUI did not come up within 6 minutes"
                                      + (f" - {why}" if why else "")))
    print("[pixal] " + COMFY_BOOT["error"], flush=True)


def comfy_listener_pid(port=None):
    """The pid listening on ComfyUI's port, whoever started it.

    We only know our own child's pid when WE launched it, and the common case
    is a ComfyUI the user started. The port is the one handle that identifies
    it either way.
    """
    port = int(port or urllib.parse.urlparse(COMFY).port or 8188)
    try:
        # getattr, not a bare 0x08000000: creationflags raises ValueError - which
        # the except below does NOT catch - on any non-Windows platform, and the
        # Linux half of CI reaches this the moment a test exercises the caller.
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                             text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
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


def comfy_is_local():
    """Whether COMFY names this PC.

    Compute can be pointed at another rig (Settings -> Compute), and stopping
    a ComfyUI we do not own would end someone else's session. Every kill path
    asks this first; a blank host is the default 127.0.0.1.
    """
    host = (urllib.parse.urlparse(COMFY).hostname or "").lower()
    return host in {"", "127.0.0.1", "localhost", "::1"}


def _taskkill(pid, timeout=20):
    """Kill a process and everything under it.

    /T because ComfyUI's launcher .bat sits between us and python: killing
    either one on its own leaves the other running. POSIX gets the same reach
    from the process group: the launcher is spawned with start_new_session, so
    one killpg takes launcher and python down together."""
    if _nt():
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def stop_comfy(timeout=20):
    """Stop every ComfyUI this sidecar is responsible for; return the pids killed.

    Two handles, because either one alone leaves something behind. The tracked
    child catches a ComfyUI that never bound the port - the ghost case, which by
    definition no port lookup can find. The port owner catches one that outlived
    the sidecar that spawned it. Remote compute is never touched; that is
    someone else's box and someone else's session.
    """
    stopped = []
    proc = COMFY_BOOT.get("proc")
    if proc is not None:
        if proc.poll() is None:
            _taskkill(proc.pid, timeout)
            stopped.append(proc.pid)
        COMFY_BOOT["proc"] = None
    if comfy_is_local():
        pid = comfy_listener_pid()
        if pid and pid not in stopped:
            _taskkill(pid, timeout)
            stopped.append(pid)
    return stopped


async def restart_comfy(_req):
    """Stop ComfyUI and boot it again through its own launcher.

    For the state no endpoint can fix - a wedged sampler, a custom node that
    needs reloading.
    """
    try:
        pids = stop_comfy()
    except (OSError, subprocess.SubprocessError) as exc:
        return web.json_response({"ok": False, "error": f"could not stop ComfyUI: {exc}"},
                                 status=500)
    if pids:
        for _ in range(20):                      # let the port actually free
            await asyncio.sleep(0.5)
            if not await comfy_reachable(timeout=2):
                break
    COMFY_BOOT.update(at=None, error=None)
    kick_comfy_boot()
    return web.json_response({"ok": True, "stopped_pids": pids,
                              "boot": comfy_boot_state()})


async def restart_sidecar(_req):
    """Reload the sidecar's own code without touching the GPU stack.

    Server changes used to mean a full studio bounce: ~20GB of ComfyUI evicted
    and reloaded, the chat brain re-spawned, a minute of nothing. The sentinel
    tells on_cleanup this exit is a restart, and pixal.vbs (spawned detached,
    so it outlives us) brings the new process up to adopt the stack that is
    still running."""
    if studio_busy():
        return web.json_response(
            {"ok": False, "error": "something is still rendering - try again when idle"},
            status=409)
    if not _nt():
        # No pixal.vbs on POSIX, and phase 1 grows no daemon to replace it:
        # the honest answer is to name the door the user actually has.
        return web.json_response(
            {"ok": False, "error": "the restart lane is Windows-only (pixal.vbs) - "
                                   "restart Pixal from your shell instead"},
            status=400)
    KEEP_COMFY.write_text("restart", encoding="utf-8")
    vbs = HERE / "pixal.vbs"
    try:
        # "restart" (not "boot"): that mode waits for THIS process to release
        # 8190 before spawning, because pixal.vbs declines to spawn while the
        # status route still answers - and it answers until the signal below
        # lands. Detached so it outlives us.
        subprocess.Popen(
            ["wscript.exe", str(vbs), "restart"],
            cwd=str(HERE), close_fds=True,
            creationflags=0x00000008 | 0x08000000)   # DETACHED | NO_WINDOW
    except OSError as exc:
        KEEP_COMFY.unlink(missing_ok=True)
        return web.json_response({"ok": False, "error": f"respawn failed: {exc}"},
                                 status=500)
    # call_later, not a task: raising inside a coroutine leaves an unretrieved
    # KeyboardInterrupt and a scary traceback in the log. From a plain callback
    # it unwinds the loop exactly like a real Ctrl+C, which is what on_cleanup
    # is written for. The delay lets this response reach the wire first.
    asyncio.get_running_loop().call_later(0.75, signal.raise_signal, signal.SIGINT)
    return web.json_response({"ok": True, "note": "reloading server code"})


def comfy_closed_by_user():
    """Did the ComfyUI WE started go away because someone shut its window?

    Told apart from a crash by what is left behind. When ComfyUI crashes, its
    .bat parks on "Press any key to continue" and the cmd.exe we spawned stays
    alive holding that console - a corpse, which ensure_comfy_running is
    already built to clear away and replace. When someone closes the window,
    the whole process tree goes with it and our handle reports an exit code.

    Only ever true for a console this process launched: a ComfyUI the user
    started by hand was never ours to restart, and an adopted one leaves
    COMFY_BOOT["proc"] as None, so neither is mistaken for a close.
    """
    proc = COMFY_BOOT.get("proc")
    return bool(proc is not None and proc.poll() is not None
                and not COMFY_BOOT.get("at"))


def kick_comfy_boot():
    """Start ComfyUI on demand, at most one attempt in flight.

    Re-entrant on purpose: if a previous attempt finished - including one that
    failed, or one whose ComfyUI has since died - reloading the page tries
    again, which makes the overlay's retry button mean something.

    Every caller here is an INTENT to have ComfyUI running - opening the app,
    the overlay's start button - and each of them starts a boot, which replaces
    COMFY_BOOT["proc"] and so clears the closed-by-user reading on its own.
    Nothing has to be un-latched. status()'s poll is the one caller that asks
    first, because it speaks for nobody.
    """
    task = COMFY_BOOT.get("task")
    if task is not None and not task.done():
        return task
    task = asyncio.create_task(ensure_comfy_running())
    COMFY_BOOT["task"] = task
    return task


# Closing the window IS what closing Pixal means to the user, but a browser tab
# going away used to leave the sidecar running and a hidden, window-less ComfyUI
# holding the card - the thing they thought they had just closed. The grace
# period is what separates a close from an F5, which also drops the subscriber
# for a moment; the busy checks are what stop it ending a live render.
EXIT_GRACE_SECONDS = 30


def studio_busy():
    """Whether anything is in flight that shutting down would destroy."""
    return bool(HUB.queue_remaining) or _LLM_TURNS["n"] > 0 or bool(COMFY_BOOT.get("at"))


async def exit_when_unwatched():
    """Close the studio once the last window has been gone a while.

    Deliberately never fires before a first window has connected: pixal.vbs
    starts the sidecar and THEN launches Chrome, so an empty subscriber set at
    boot means "not open yet", not "closed".
    """
    seen, idle = False, 0
    while True:
        await asyncio.sleep(1)
        # Either transport counts as a window: an SSE subscriber, or a client
        # that polled recently. POLL_INTERVAL_MS is 1.2s in the browser, so a
        # 10s grace is many missed ticks, not a rounding error.
        if HUB.subs or (time.time() - HUB.last_poll) < 10:
            seen, idle = True, 0
            continue
        if not seen or studio_busy():
            idle = 0
            continue
        idle += 1
        if idle >= EXIT_GRACE_SECONDS:
            # "stay_up": true holds the studio open with no window connected.
            # The auto-close exists so a 21GB model stack never outlives the UI
            # that wanted it - correct at the desk, wrong away from it: a phone
            # tab that backgrounds for half a minute would take the whole studio
            # down with nobody there to start it again. Read here, not at boot,
            # so turning it off does not need a restart either.
            if load_config().get("stay_up"):
                idle = 0
                continue
            print(f"[pixal] no window for {EXIT_GRACE_SECONDS}s - closing the studio",
                  flush=True)
            signal.raise_signal(signal.SIGINT)   # aiohttp unwinds into on_cleanup
            return


async def on_start(app):
    app["bridge"] = asyncio.create_task(HUB.bridge())
    app["gpu"] = asyncio.create_task(HUB.gpu_watch())
    app["exit"] = asyncio.create_task(exit_when_unwatched())
    app["brain_reaper"] = asyncio.create_task(brain_idle_reaper())
    # no disk scan before the user has consented to one (first-run setup)
    if load_config()["setup_done"]:
        app["warmup"] = asyncio.create_task(warmup_catalog())
        # Starting Pixal means starting the studio. Booting ComfyUI only when
        # the web page is SERVED is not enough: an installed PWA answers its
        # own navigation out of the service worker cache, so that request never
        # reaches this process and nothing ever starts the backend - one click,
        # a sidecar, and no ComfyUI (2026-08-13). Cheap when it is already up:
        # ensure_comfy_running returns on its first reachability probe.
        kick_comfy_boot()

async def on_cleanup(app):
    app["bridge"].cancel()
    app["gpu"].cancel()
    app["exit"].cancel()
    if app.get("brain_reaper"):
        app["brain_reaper"].cancel()
    if COMFY_BOOT.get("task"):
        COMFY_BOOT["task"].cancel()
    if "warmup" in app:
        app["warmup"].cancel()
    # A sidecar restart for a CODE change should not cost a 20GB model reload.
    # The sentinel says "I'm coming right back" - the next boot's
    # ensure_comfy_running() adopts whatever is already answering on 8188, so
    # the restart is seconds instead of a minute. Only an INTENTIONAL restart
    # writes it (see restart_sidecar); a real shutdown never does, so the
    # take-it-with-you rule below still holds for every other exit.
    if KEEP_COMFY.exists():
        KEEP_COMFY.unlink(missing_ok=True)
        print("[pixal] restarting - leaving ComfyUI and the brain up", flush=True)
        # _exit, not return: something non-daemon (the llama.cpp handle, an
        # aiohttp connector) kept the interpreter alive for a minute after the
        # loop unwound, and the replacement instance found port 8190 still
        # bound and bowed out with "already running" - so a restart left NO
        # sidecar at all (2026-08-13). Everything worth flushing is flushed;
        # the GPU stack is deliberately still up and gets adopted next boot.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    # Pixal started ComfyUI, so Pixal takes it down with it. A 21GB model stack
    # outliving its only UI is how the card ends up starved by a process the
    # user has no window for. Remote compute is never touched.
    try:
        pids = stop_comfy()
        if pids:
            print(f"[pixal] stopped ComfyUI ({', '.join(str(p) for p in pids)})",
                  flush=True)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[pixal] could not stop ComfyUI: {exc}", flush=True)
    # The chat brain follows the same rule: WE spawned it (the pidfile is the
    # proof), so it dies with the studio - found orphaned holding ~7GB of VRAM
    # after a shutdown on 2026-08-11. A server the user started themselves
    # (run_llm.bat) has no pidfile and is never touched.
    try:
        if await free_brain_vram():
            print("[pixal] stopped the chat brain", flush=True)
    except OSError as exc:
        print(f"[pixal] could not stop the chat brain: {exc}", flush=True)

def sidecar_port_state():
    """None (free), "live" (a Pixal answers there), or "stale" (bound but mute).

    Losing the bind race is a normal thing to do - double-clicking pixal.vbs,
    or run.bat on top of a sidecar that is already up - and the loser must not
    stay alive serving nothing. But a TCP connect alone cannot tell that
    healthy case from its opposite: a hung Pixal squatting the port and
    answering nobody, which reads to the user as "Pixal won't start" with no
    evidence (2026-08-11). Only an actual HTTP answer counts as running.

    NOT a guard against seeing two python.exe for one sidecar: on Windows
    .venv\\Scripts\\python.exe is a redirector stub that spawns the base
    interpreter as a child, so a single healthy sidecar is always two PIDs.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        if probe.connect_ex(LISTEN) != 0:
            return None
    try:
        with urllib.request.urlopen(
                f"http://{LISTEN[0]}:{LISTEN[1]}/api/status", timeout=3) as r:
            return "live" if r.status == 200 else "stale"
    except OSError:
        return "stale"


def _pid_image(pid):
    """Lower-case image name (python.exe) for a pid; '' when unknowable."""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV",
                              "/NH"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    row = out.strip().splitlines()
    if not row or '","' not in row[0]:
        return ""
    return row[0].split('","')[0].strip('"').lower()


def clear_stale_sidecar():
    """Free port 8190 from a dead Pixal so the boot self-heals; True on success.

    Only a mute listener whose image is python gets killed: 8190 is Pixal's
    port and a python there that answers no HTTP is a corpse of ours, not
    someone's app. Anything else is named, never shot.
    """
    pid = comfy_listener_pid(LISTEN[1])
    if not pid:
        return False
    image = _pid_image(pid)
    if "python" not in image:
        print(f"[pixal] port {LISTEN[1]} is held by pid {pid} ({image or 'unknown'}), "
              f"which is not Pixal - free it yourself, then start Pixal again.",
              flush=True)
        return False
    print(f"[pixal] port {LISTEN[1]} was held by a dead Pixal (pid {pid}) - "
          f"clearing it", flush=True)
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    time.sleep(1.5)                       # the OS releases the port on reap
    return sidecar_port_state() is None


# ---------------------------------------------------------------- update check
#
# Brief 9.24a: Pixal may KNOW a newer build exists and say so in About; the
# download itself is 9.24b. The whole feature is advisory, so every failure
# shape - offline, GitHub down, rate-limited, garbage JSON - collapses to the
# same quiet "unknown": the running version shows and nothing else. No toast,
# no red state, no retry storm. The answer is cached for hours, so opening
# settings never hammers the API.
RELEASES_API = "https://api.github.com/repos/JesseDubb/pixal-releases/releases/latest"
RELEASE_PAGE = "https://github.com/JesseDubb/pixal-releases/releases"
UPDATE_CHECK_TTL = 6 * 60 * 60          # hours between network calls
_update_check_cache = {"at": 0.0, "result": None}


def parse_version(text):
    """"1.0.4b" / "v1.0.4b" -> ((1, 0, 4), "b"); None on anything else."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)([a-zA-Z]*)", str(text).strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split(".")), m.group(2).lower()


def compare_versions(a, b):
    """-1/0/1 for a older/equal/newer than b. Numeric parts compare as numbers
    (1.0.10b > 1.0.9b, never string order), then the pre-release letter
    (1.0.4b > 1.0.4a), and the bare release outranks every letter
    (1.0.4 > 1.0.4b)."""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        raise ValueError(f"unparseable version: {a!r} vs {b!r}")
    (na, sa), (nb, sb) = pa, pb
    width = max(len(na), len(nb))
    na += (0,) * (width - len(na))
    nb += (0,) * (width - len(nb))
    if na != nb:
        return -1 if na < nb else 1
    if sa == sb:
        return 0
    if not sa:
        return 1
    if not sb:
        return -1
    return -1 if sa < sb else 1


def _fetch_latest_release():
    """One network round-trip to GitHub. Raises on ANY failure shape - the
    caller decides what silence looks like."""
    req = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": f"pixal/{PIXAL_VERSION} update-check"})
    with urllib.request.urlopen(req, timeout=4) as resp:
        if resp.status != 200:
            raise OSError(f"releases api answered {resp.status}")
        data = json.loads(resp.read().decode("utf-8"))
    tag = str(data.get("tag_name") or "")
    if parse_version(tag) is None:
        raise ValueError(f"unparseable release tag {tag!r}")
    # The notes carry the installer hash (release.py step 13 writes "sha256
    # `<64 hex>`"); 9.24b verifies the download against it, so it rides the
    # wire from day one.
    body = str(data.get("body") or "")
    sha = re.search(r"\b([0-9a-fA-F]{64})\b", body)
    url = str(data.get("html_url") or "") or f"{RELEASE_PAGE}/tag/{tag}"
    return {"latest": tag[1:] if tag.startswith("v") else tag,
            "url": url, "sha256": sha.group(1).lower() if sha else None}


def update_check(now=None):
    """{"ok", "running", "latest", "update", "url", "sha256"}. ok False is the
    quiet unknown. Never raises, and never calls an equal or older release an
    update."""
    now = time.time() if now is None else now
    cached = _update_check_cache["result"]
    if cached is not None and now - _update_check_cache["at"] < UPDATE_CHECK_TTL:
        return dict(cached)
    result = {"ok": False, "running": PIXAL_VERSION, "latest": None,
              "update": False, "url": None, "sha256": None}
    try:
        rel = _fetch_latest_release()
        result.update(ok=True, latest=rel["latest"], url=rel["url"],
                      sha256=rel["sha256"],
                      update=compare_versions(rel["latest"], PIXAL_VERSION) > 0)
    except Exception:
        pass                                    # silent and complete, by design
    _update_check_cache.update(at=now, result=result)
    return dict(result)


async def update_check_get(_req):
    # urllib blocks, so the check rides a thread: a cold lookup must not stall
    # chat and SSE behind a 4s GitHub timeout.
    return web.json_response(await asyncio.to_thread(update_check))


def main():
    global ACCESS_KEY
    state = sidecar_port_state()
    if state == "live":
        print(f"[pixal] already running on {LISTEN[0]}:{LISTEN[1]} - "
              f"use that one", flush=True)
        return
    if state == "stale" and not clear_stale_sidecar():
        try:
            input("[pixal] press Enter to close this window ")
        except (EOFError, OSError):
            time.sleep(30)               # launched with no console stdin
        sys.exit(1)
    cfg = load_config()
    apply_comfy_url(cfg.get("comfy_url"))
    apply_comfy_root(cfg.get("comfy_root"))
    migrate_percent_encoded_inputs()
    if not cfg.get("access_key"):
        import secrets
        cfg["access_key"] = secrets.token_urlsafe(18)
        save_config(cfg)
    ACCESS_KEY = cfg["access_key"]
    # aiohttp defaults to a 1 MiB request body, which made normal camera photos
    # fail before upload() could enforce and explain Pixal's real 40 MB limit.
    app = web.Application(middlewares=[access_gate],
                          client_max_size=UPLOAD_CLIENT_MAX_BYTES)
    app["convo"] = HUB.convo               # legacy alias; HUB owns per-chat convos now
    app.router.add_get("/", index)
    app.router.add_get("/manifest.webmanifest", manifest)
    app.router.add_get("/sw.js", service_worker)
    app.router.add_static("/icons", HERE / "web" / "icons")
    app.router.add_get("/api/events", events)
    app.router.add_post("/api/chat", chat)
    app.router.add_get("/api/lane", lane_get)
    app.router.add_get("/api/chats", chats_get)
    app.router.add_post("/api/chats", chats_post)
    app.router.add_post("/api/reroll", reroll)
    app.router.add_post("/api/stop", stop)
    app.router.add_post("/api/comfy/free", comfy_free)
    app.router.add_post("/api/comfy/restart", restart_comfy)
    app.router.add_post("/api/sidecar/restart", restart_sidecar)
    app.router.add_post("/api/llm/free", free_chat_model)
    app.router.add_get("/api/history", history)
    app.router.add_post("/api/history/delete", history_delete)
    app.router.add_get("/api/options", options)
    app.router.add_get("/api/quant_alternatives", quant_alternatives)
    app.router.add_post("/api/quant_fetch", quant_fetch)
    app.router.add_post("/api/upload", upload)
    app.router.add_post("/api/input-ref-type", input_ref_type_post)
    app.router.add_get("/api/setup", setup_get)
    app.router.add_post("/api/setup", setup_post)
    app.router.add_get("/api/settings", settings_get)
    app.router.add_post("/api/settings", settings_post)
    app.router.add_post("/api/settings/test", settings_test)
    app.router.add_post("/api/settings/rescan", settings_rescan)
    app.router.add_get("/api/update-check", update_check_get)
    app.router.add_post("/api/animate", animate)
    app.router.add_post("/api/edit", edit)
    app.router.add_post("/api/input/stage", input_stage)
    app.router.add_post("/api/upscale", upscale)
    app.router.add_post("/api/review", review)
    app.router.add_post("/api/trailer", trailer)
    app.router.add_post("/api/styles", styles_post)
    # Before the {style_id} route: "sampler" is a verb, not an id.
    app.router.add_get("/api/styles/sampler", style_sampler)
    app.router.add_delete("/api/styles/{style_id}", styles_delete)
    app.router.add_post("/api/characters", characters_post)
    # Before the {character_id} routes: "preview" is a verb, not an id, and the
    # dynamic DELETE/GET would otherwise be free to match it.
    app.router.add_post("/api/characters/preview", characters_preview)
    app.router.add_delete("/api/characters/{character_id}", characters_delete)
    app.router.add_get("/api/characters/{character_id}", characters_get_one)
    app.router.add_get("/api/characters/{character_id}/ref-thumb", character_ref_thumb)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/poll", events_poll)
    app.router.add_get("/api/image", image)
    app.router.add_get("/api/thumb", output_thumbnail)
    app.router.add_get("/api/input-thumb", input_thumbnail)
    # before the {tail} catch-all, which would proxy "compat" to ComfyUI
    app.router.add_get("/api/comfy/compat", comfy_compat)
    app.router.add_get("/api/comfy/manager/status", manager_status)
    app.router.add_get("/api/comfy/{tail:.*}", comfy_asset)
    app.router.add_static("/vendor", HERE / "web" / "vendor")
    app.router.add_get("/app.js", lambda r: web.FileResponse(
        HERE / "web" / "app.js", headers={"Content-Type": "application/javascript"}))
    app.on_startup.append(on_start)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(on_cleanup)
    # LISTEN stays loopback for every self-probe in this file; only the socket
    # we actually serve on widens. ComfyUI is never exposed - remote viewers
    # reach it through the /api/comfy passthrough on this port.
    bind = "0.0.0.0" if load_config().get("lan_access") else LISTEN[0]
    print(f"pixal -> http://{LISTEN[0]}:{LISTEN[1]}   (comfy at {COMFY})", flush=True)
    if bind != LISTEN[0]:
        lan = ""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))       # no packet sent; reads the route
                lan = s.getsockname()[0]
        except OSError:
            pass
        print(f"[pixal] LAN access on: http://{lan or '<this-pc>'}:{LISTEN[1]}"
              f"/?key={ACCESS_KEY}", flush=True)
    try:
        # shutdown_timeout: the backstop behind on_shutdown. aiohttp's default is
        # 60s, and it applies the value twice, so this is a ~4s ceiling on how
        # long a restart can hold sidecar.log - not the minute that made
        # pixal.vbs spawn the replacement into a locked file.
        web.run_app(app, host=bind, port=LISTEN[1], print=None, shutdown_timeout=2.0)
    except OSError as exc:
        # A held port used to die as a traceback in a console that closed
        # before it could be read - "Pixal won't start" with no evidence.
        # Name the holder, say whether it is a live Pixal or a stale one,
        # and hold the window open long enough to be read.
        if exc.errno not in (errno.EADDRINUSE, 10048):
            raise
        holder = comfy_listener_pid(LISTEN[1])
        try:
            with urllib.request.urlopen(
                    f"http://{LISTEN[0]}:{LISTEN[1]}/api/status", timeout=3) as r:
                alive = r.status == 200
        except OSError:
            alive = False
        if alive:
            print(f"[pixal] Pixal is ALREADY RUNNING at "
                  f"http://{LISTEN[0]}:{LISTEN[1]} - use that one; this window "
                  f"can close.", flush=True)
        else:
            print(f"[pixal] port {LISTEN[1]} is held by pid {holder or '?'} "
                  f"which is not answering - a stale Pixal. Free it with:\n"
                  f"[pixal]   taskkill /PID {holder or '<pid>'} /F\n"
                  f"[pixal] then start Pixal again.", flush=True)
        try:
            input("[pixal] press Enter to close this window ")
        except (EOFError, OSError):
            time.sleep(30)                   # launched with no console stdin
        sys.exit(1)

if __name__ == "__main__":
    main()
