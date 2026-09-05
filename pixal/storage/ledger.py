"""Append-only JSONL ledger with per-owner stat cache and own-append tail parse."""
import json
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from aiohttp import web

_current = ContextVar("pixal.ledger", default=None)


@contextmanager
def scope(consumer, owner):
    token = _current.set((consumer, owner))
    try:
        yield
    finally:
        _current.reset(token)


def current(consumer):
    value = _current.get()
    return value[1] if value is not None and value[0] is consumer else None


class Ledger:
    def __init__(self, path):
        self.path = Path(path)

    def ledger_append(self, entry):
        try:
            before = self.path.stat().st_size if self.path.exists() else 0
        except OSError:
            before = None
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # Arm ledger_read's tail parse only when its cache was current for the
        # file as it stood before this write; otherwise it re-reads everything.
        cached = getattr(self, "_ledger_key", None)
        self._ledger_append_from = before if (
            before is not None and cached is not None and cached[1] == before) else None

    def ledger_delete(self, eid, *, read=None):
        """Rewrite the ledger without one entry; returns the removed entry or None.
        The ONE sanctioned exception to append-only - user-initiated delete."""
        entries = (read or self.ledger_read)()[::-1]          # back to file order
        entry = next((e for e in entries if e.get("id") == eid), None)
        if entry:
            with self.path.open("w", encoding="utf-8") as f:
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
        if not self.path.exists():
            return []
        try:
            stat = self.path.stat()
            key = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            key = None
        if key is not None and getattr(self, "_ledger_key", None) == key:
            return self._ledger_cache
        prev_key, prev = getattr(self, "_ledger_key", None), getattr(self, "_ledger_cache", None)
        # Our own append is the one write that may be parsed as a tail: the
        # cached rows are still the file's first prev_size bytes, so only what
        # ledger_append added since is decoded. Anything else - a rewrite by
        # ledger_delete, an outside edit, no cache yet - is parsed whole, as
        # before. The full parse was ~70 ms on a 7.7 MB ledger (2026-09-05):
        # small, but paid on the loop right as the picture lands.
        start = 0
        if prev is not None and prev_key is not None and key is not None \
                and getattr(self, "_ledger_append_from", None) == prev_key[1] \
                and key[1] > prev_key[1]:
            start = prev_key[1]
        self._ledger_append_from = None
        fresh = []
        with self.path.open("rb") as f:
            if start:
                f.seek(start)
            for raw in f.read().decode("utf-8", "replace").splitlines():
                line = raw.strip()
                if line:
                    try:
                        fresh.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        out = fresh[::-1] + (prev if start else [])   # newest first
        if key is not None:
            self._ledger_key, self._ledger_cache = key, out
        return out

LEDGER_KEY = web.AppKey("pixal.ledger", Ledger)
