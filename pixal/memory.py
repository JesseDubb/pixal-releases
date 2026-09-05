"""Small, dependency-free memory policy; engine/process actions stay in Hub.

Unknown telemetry is not zero. Estimates are advisory; only measured critical
headroom blocks admission. Recovery changes one job, never saved preferences.
"""
import ctypes
import math
import re
from dataclasses import dataclass

GIB = 2**30
GPU_OOM_MARKERS = (
    "out of memory", "exceed allowed memory", "outofmemoryerror",
    "cublas_status_alloc_failed", "cudaerrormemoryallocation",
)
CPU_OOM_MARKERS = (
    "defaultcpuallocator", "can't allocate memory", "cannot allocate memory",
    "paging file is too small",
    "not enough memory resources", "winerror 1455", "std::bad_alloc",
    "_arraymemoryerror",
)


class MemoryPressureError(RuntimeError):
    """Measured pressure remains after reclamation; do not auto-retry blindly."""


def memory_failure_kind(error):
    text = str(error or "").lower()
    # OutOfMemoryError contains MemoryError, so device-specific evidence wins.
    if any(word in text for word in ("cuda", "device 0", "cublas", "hip out of memory")) \
            and any(word in text for word in GPU_OOM_MARKERS):
        return "gpu"
    if any(word in text for word in CPU_OOM_MARKERS) or re.search(r"\bmemoryerror\b", text):
        return "ram"
    return "gpu" if any(word in text for word in GPU_OOM_MARKERS) else None


def positive_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


@dataclass(frozen=True)
class HostMemory:
    available: int
    commit_available: int

    def critical_reason(self):
        # Physical pressure alone can page; exhausted commit cannot. Keep a
        # modest reserve for the desktop and reject only proven severe pressure.
        if self.commit_available < 2 * GIB:
            return f"only {self.commit_available / GIB:.1f} GiB of system commit headroom remains"
        if self.available < GIB:
            return f"only {self.available / GIB:.1f} GiB of physical RAM is available"
        return None


def host_memory_status():
    """Windows physical AND commit availability in one inexpensive OS call."""
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
            (name, ctypes.c_uint64) for name in (
                "total_phys", "avail_phys", "total_page", "avail_page",
                "total_virtual", "avail_virtual", "avail_extended")]

    state = MEMORYSTATUSEX()
    state.length = ctypes.sizeof(state)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            return HostMemory(int(state.avail_phys), int(state.avail_page))
    except (AttributeError, OSError):
        pass
    return None


STILL_LATENTS = frozenset(("EmptyLatentImage", "EmptySD3LatentImage",
                          "EmptyFlux2LatentImage", "EmptyHunyuanLatentVideo"))


def still_canvas(graph):
    """A single literal sampling canvas, not a source/composite/output size.

    Video and ambiguous multi-canvas graphs deliberately have no generic shrink
    plan. Sizing adapters for those recipes remain with their builders.
    """
    candidates = []
    for nid, node in graph.items():
        ins = node.get("inputs") or {}
        if node.get("class_type") not in STILL_LATENTS or ins.get("length", 1) != 1:
            continue
        w, h = ins.get("width"), ins.get("height")
        if positive_number(w) and positive_number(h):
            candidates.append((nid, int(w), int(h), ins.get("batch_size", 1)))
    if len(candidates) != 1:
        return None
    nid, w, h, batch = candidates[0]
    # Some schedulers take literal dimensions alongside the latent. Keep those
    # in sync on recovery; never rewrite a linked or unrelated source canvas.
    peers = [key for key, node in graph.items()
             if (node.get("inputs") or {}).get("width") == w
             and (node.get("inputs") or {}).get("height") == h]
    return {"node": nid, "width": w, "height": h, "peers": peers,
            "batch": int(batch) if positive_number(batch) else 1}


def shrink_still_spec(spec, canvas, parameters):
    """Return a detached, genuinely smaller spec and note, or no safe plan."""
    if not canvas or "overrides" not in parameters:
        return None
    result = dict(spec)
    overrides = list(spec.get("overrides") or ())
    batch = canvas["batch"]
    if batch > 1:
        smaller = max(1, batch // 2)
        overrides.append({"node": canvas["node"], "input": "batch_size", "value": smaller})
        result["overrides"] = overrides
        return result, f"with batch {smaller} instead of {batch}"
    if canvas.get("resizable") is False:
        return None  # preset-only decoders cannot accept an arbitrary half canvas
    w, h = canvas["width"], canvas["height"]
    mp = w * h / 1e6
    target = max(0.5, mp / 2)
    if target >= mp:
        return None
    ratio = math.sqrt(target / mp)
    # Round DOWN so a retry never accidentally samples the same or larger area.
    nw, nh = max(16, int(w * ratio / 16) * 16), max(16, int(h * ratio / 16) * 16)
    if nw * nh >= w * h:
        return None
    if "mp" in parameters:
        result["mp"] = nw * nh / 1e6
    if "width" in parameters and "height" in parameters:
        result.update(width=nw, height=nh)
    # Builders apply overrides last. Replacing mp alone loses to an old explicit
    # width/height override and was the cause of identical-size OOM retries.
    for node in canvas["peers"]:
        overrides.extend(({"node": node, "input": "width", "value": nw},
                          {"node": node, "input": "height", "value": nh}))
    result["overrides"] = overrides
    return result, f"at {nw} x {nh} ({nw * nh / 1e6:.2f}MP) instead of {w} x {h}"
