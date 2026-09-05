"""A single-process owner for JSON settings; no filesystem access at construction.

Files remain authoritative. Reads return detached dictionaries. Writes are
serialized and replaced atomically in the same directory. This is not a
cross-process lock or a power-loss durability guarantee for the directory entry.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from pixal.config.rules import merge_saved_config

Defaults = dict | Callable[[], dict]


class ConfigUnreadableError(RuntimeError):
    pass


class ConfigWriteError(RuntimeError):
    pass


def atomic_write_json(path: Path, value: dict) -> None:
    # Preserve existing symlink/junction behavior: update the file's target.
    target = path.resolve()
    payload = json.dumps(value, ensure_ascii=False, indent=1)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=target.parent, prefix=f"{target.name}.",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None  # Commit succeeded; no later cleanup can misreport it.
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Preserve the original failure; an orphan is not user data.


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read_saved(self) -> dict:
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("settings must be a JSON object")
        return value

    def _preserve_bad(self, error: Exception) -> None:
        bad = self.path.with_suffix(".json.bad")
        if not bad.exists():
            print(f"[pixal] config.json unreadable, using defaults: {error}", flush=True)
            try:
                shutil.copy2(self.path, bad)
            except OSError:
                pass

    def load(self, defaults: Defaults) -> dict:
        with self._lock:
            # A factory hands us a fresh dictionary, avoiding a second full
            # clone on the hot path. Caller-owned dictionaries stay detached.
            cfg = defaults() if callable(defaults) else copy.deepcopy(defaults)
            if self.path.exists():
                try:
                    merge_saved_config(cfg, self._read_saved())
                except Exception as error:
                    # Preserve the legacy fallback (including partial merges),
                    # but save() refuses to overwrite this unreadable source.
                    self._preserve_bad(error)
            return cfg

    def save(self, cfg: dict) -> None:
        with self._lock:
            payload = copy.deepcopy(cfg)
            if self.path.exists():
                try:
                    saved = self._read_saved()
                    merge_saved_config(copy.deepcopy(cfg), saved)
                except Exception as error:
                    self._preserve_bad(error)
                    raise ConfigUnreadableError(
                        "config.json is unreadable. Repair or restore it before saving; "
                        "the existing file has not been replaced.") from error
                # Forward-compatible extension fields are opaque to this build,
                # not permission to erase another build's settings.
                payload = {**saved, **payload}
                for key, value in cfg.items():
                    if isinstance(value, dict) and isinstance(saved.get(key), dict):
                        payload[key] = {**saved[key], **value}
            try:
                atomic_write_json(self.path, payload)
            except OSError as error:
                raise ConfigWriteError(
                    "Settings could not be saved. Check disk space and folder permissions; "
                    "the previous file has not been replaced.") from error

    def update(self, defaults: Defaults, change: Callable[[dict], None]) -> dict:
        """Serialized read/modify/write for synchronous configuration operations."""
        with self._lock:
            cfg = self.load(defaults)
            change(cfg)
            self.save(cfg)
            return copy.deepcopy(cfg)
