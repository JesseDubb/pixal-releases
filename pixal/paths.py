"""Explicit application assets, private data and engine locations.

Construction never creates directories, reads configuration or resolves junctions.
Existing installations keep their paths. Alternate roots are opt-in; this module
does not migrate files or redirect an already-running engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def _absolute(path: Path | str) -> Path:
    # absolute(), deliberately not resolve(): portable installs can use junctions.
    return Path(path).absolute()


def resolve_comfy_dir(root: object) -> Path | None:
    """Accept a portable root, a checkout, or its models directory."""
    try:
        path = Path(str(root).strip().strip('"').rstrip("\\/"))
    except Exception:
        return None
    if path.name.lower() == "models" and path.is_dir():
        return path.parent
    for candidate in (path / "ComfyUI", path):
        if (candidate / "models").is_dir():
            return candidate
    return None


@dataclass(frozen=True)
class RuntimePaths:
    app_root: Path
    data_root: Path
    comfy_root: Path
    model_roots: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        for name in ("app_root", "data_root", "comfy_root"):
            object.__setattr__(self, name, _absolute(getattr(self, name)))
        object.__setattr__(self, "model_roots", tuple(_absolute(root) for root in self.model_roots))

    @classmethod
    def discover(cls, app_root: Path, *, data_root: Path | None = None,
                 comfy_root: Path | None = None) -> RuntimePaths:
        app_root = _absolute(app_root)
        if comfy_root is None:
            neighbor = app_root.parent
            comfy_root = neighbor if (neighbor / "models").is_dir() else app_root
        return cls(app_root, data_root if data_root is not None else app_root, comfy_root)

    @classmethod
    def from_environment(cls, app_root: Path, environ: Mapping[str, str]) -> RuntimePaths:
        # No implicit os.environ read: callers select their environment explicitly.
        roots = {}
        for variable, name in (("PIXAL_DATA_DIR", "data_root"), ("PIXAL_COMFY_DIR", "comfy_root")):
            value = environ.get(variable, "").strip()
            if value:
                path = Path(value)
                if not path.is_absolute():
                    raise ValueError(f"{variable} must be an absolute path")
                roots[name] = path
        return cls.discover(app_root, **roots)

    @property
    def config_file(self) -> Path:
        return self.data_root / "config.json"

    @property
    def chats_dir(self) -> Path:
        return self.data_root / "chats"

    @property
    def web_dir(self) -> Path:
        return self.app_root / "web"
