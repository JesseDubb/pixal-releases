"""Catalog ownership. Construction/import is inert; all reads are explicit.

The legacy adapters supply callbacks at call time so patched server names stay
observable. Snapshots are recursively read-only; legacy wire lists are detached.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import copy
import json
from pathlib import Path
from types import MappingProxyType

KIND_DIRS = ["checkpoints", "loras", "diffusion_models", "unet", "vae", "clip",
             "text_encoders", "controlnet", "upscale_models",
             # the LTX spatial upscalers live here; without it in the scan the
             # 2.5 engine read as missing its upscaler with the file on disk
             "latent_upscale_models",
             # the mmh3 ClipProj weights a small Qwen3-VL encoder needs to
             # stand in for MiniMax H3's 32B one (9.94); unscanned, the
             # encoder row could never offer a pick
             "clip_projections"]
MODEL_EXTS = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin")
INPUT_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".jfif", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".avif",
}

def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class CatalogSnapshot:
    revision: int
    roots: tuple
    models: tuple
    metadata: object
    inputs: tuple


class Catalog:
    def __init__(self):
        self.yaml_roots = {"key": None, "roots": []}
        self.roots_memo = {"active": False, "roots": None}
        self.cache = {"at": 0, "data": None}
        self.sidecar_meta = {}
        self.input_root = {"key": None, "path": None}
        self.revision = 0
        self._roots = ()
        self._inputs = ()

    def invalidate(self, *, metadata=True):
        """Discard inventory after a root/engine change, rescan or new download."""
        self.cache.update(at=0, data=None)
        self.yaml_roots.update(key=None, roots=[])
        self.input_root.update(key=None, path=None)
        self.roots_memo["roots"] = None
        self._roots = ()
        self._inputs = ()
        if metadata:
            self.sidecar_meta.clear()
        self.revision += 1

    @contextmanager
    def build_scope(self):
        """Synchronous options-build memo, never a time-based roots cache."""
        self.roots_memo.update(active=True, roots=None)
        try:
            yield
        finally:
            self.roots_memo.update(active=False, roots=None)

    def snapshot(self):
        return CatalogSnapshot(self.revision, tuple(self._roots),
                               _freeze(self.cache["data"] or []),
                               _freeze(self.sidecar_meta), _freeze(self._inputs))

    def publish(self, entries, now):
        self.cache.update(at=now, data=copy.deepcopy(entries))
        self.revision += 1

    def scan(self, roots, progress=None):
        entries = []
        for root in roots:
            for kd in KIND_DIRS:
                base_dir = root / kd
                if not base_dir.is_dir():
                    continue
                n0 = len(entries)
                for p in base_dir.rglob("*"):
                    if p.is_file() and p.suffix.lower() in MODEL_EXTS and ".cache" not in p.parts:
                        try:
                            st = p.stat()
                            mtime, size = st.st_mtime, st.st_size
                        except OSError:
                            mtime, size = 0, 0
                        entries.append({"kind": kd, "root": str(root),
                                        "rel": str(p.relative_to(base_dir)),
                                        "mtime": mtime, "size": size})
                if progress and len(entries) > n0:
                    progress(f"{kd} - {len(entries) - n0} files")
        return entries

    def model_catalog(self, kind=None, ttl=30, *, roots, clock):
        now = clock()
        if self.cache["data"] is None or now - self.cache["at"] > ttl:
            self.publish(self.scan(roots()), now)
        data = self.cache["data"]
        return [dict(e) for e in data if not kind or e["kind"] == kind]

    def _yaml_model_roots(self, yaml_path):
        """The base_path entries of extra_model_paths.yaml, parsed once per file
        version. A catalog build asks for the roots about 800 times (once per LoRA
        and model row), and re-parsing the YAML on each ask was three of the
        build's four seconds."""
        try:
            st = yaml_path.stat()
        except OSError:
            return []
        key = (str(yaml_path), st.st_mtime_ns, st.st_size)
        if self.yaml_roots["key"] == key:
            return list(self.yaml_roots["roots"])
        roots = []
        try:
            import yaml
            for section in (yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}).values():
                if isinstance(section, dict):
                    bp = section.get("base_path")
                    if bp:
                        roots.append(Path(bp))
        except Exception:
            pass
        self.yaml_roots.update(key=key, roots=roots)
        return list(roots)

    def model_roots(self, cfg=None, *, read_config, uncached):
        """Every root we scan: ComfyUI/models, extra_model_paths.yaml entries, and any
        roots the user added in settings (other drives, other layouts)."""
        if cfg is None and self.roots_memo["active"]:
            if self.roots_memo["roots"] is None:
                self.roots_memo["roots"] = uncached(read_config())
            return list(self.roots_memo["roots"])
        return uncached(cfg or read_config())

    def _model_roots_uncached(self, cfg, *, comfy_root, yaml_roots):
        roots = [comfy_root / "models"]
        roots.extend(yaml_roots(comfy_root / "extra_model_paths.yaml"))
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
        if self._roots != tuple(out):
            self._roots = tuple(out)
            self.revision += 1
        return out

    def adjacent_metadata(self, kind, rel, *, roots):
        """Best-effort Lora-Manager sidecar metadata for one installed asset."""
        key = (kind, str(rel).lower())
        if key in self.sidecar_meta:
            return copy.deepcopy(self.sidecar_meta[key])
        out = {}
        for root in roots():
            p = root / kind / rel
            mp = p.with_suffix(".metadata.json")
            if not mp.is_file():
                continue
            try:
                out = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                out = {}
            break
        self.sidecar_meta[key] = out
        self.revision += 1
        return copy.deepcopy(out)

    def _input_parts(self, ref):
        """The normalized path parts of a ComfyUI/input-relative name, or None
        when the name is unsafe (empty, absolute, drive-qualified, dotted)."""
        name = str(ref or "").strip().replace("\\", "/").removeprefix("input/")
        parts = name.split("/")
        if (not name or name.startswith("/") or "\0" in name or
                any(part in ("", ".", "..") or ":" in part for part in parts)):
            return None
        return parts

    def _input_root_resolved(self, comfy_root):
        """ComfyUI/input, resolved once per comfy root. resolve() is a realpath
        walk (nt._getfinalpathname per component) and it ran twice per image on
        every catalog build - 0.3 s of the picker payload (2026-09-05)."""
        key = str(comfy_root)
        if self.input_root["key"] != key:
            self.input_root.update(key=key, path=(comfy_root / "input").resolve())
        return self.input_root["path"]

    def input_ref_name(self, ref, *, parts_for, root_for):
        """Normalize a ComfyUI/input-relative image path; reject path traversal."""
        parts = parts_for(ref)
        if parts is None:
            return ""
        root = root_for()
        candidate = root.joinpath(*parts).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return ""
        return "/".join(parts)

    def input_image_record(self, name, *, mtime=None, ref_name, record_from_parts):
        """One browser-safe record for an image under ComfyUI/input."""
        canonical = ref_name(name)
        if not canonical:
            return None
        return record_from_parts(canonical.split("/"), mtime)

    def _input_record_from_parts(self, parts, mtime=None, *, ref_types):
        """The record for parts already known to sit under ComfyUI/input."""
        canonical = "/".join(parts)
        record = {
            "name": canonical,
            "filename": parts[-1],
            "subfolder": "/".join(parts[:-1]),
            "type": "input",
        }
        if mtime is not None:
            record["mtime"] = mtime
        kind = ref_types.get(canonical)
        if kind:
            record["kind"] = kind
        return record

    def input_image_catalog(self, *, comfy_root, parts_for, record_from_parts):
        """Every supported ComfyUI input image, newest first, including subfolders."""
        root = comfy_root / "input"
        if not root.is_dir():
            if self._inputs:
                self._inputs = ()
                self.revision += 1
            return []
        records = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in INPUT_IMAGE_SUFFIXES:
                continue
            try:
                rel = path.relative_to(root).as_posix()
                mtime = path.stat().st_mtime
            except (OSError, ValueError):
                continue
            # The walk itself put this path under input/, so the traversal
            # resolve that input_ref_name pays for a user-supplied name is
            # redundant here - it was two realpath walks per image, 492 images.
            parts = parts_for(rel)
            if parts is not None:
                records.append(record_from_parts(parts, mtime))
        records.sort(key=lambda item: (-item.get("mtime", 0), item["name"].lower()))
        if self._inputs != records:
            self._inputs = copy.deepcopy(records)
            self.revision += 1
        return records

