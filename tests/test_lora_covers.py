"""Every LoRA wears its own cover (brief 9.19b).

`refresh_civitai_meta` used to name and thumbnail `diffusion_models` only; a
LoRA got lora-manager's record or nothing, and 172 of Jesse's 415 LoRAs sat
family-`unknown` (the 9.19a table pass left 141, all of them WAN/LTX/Minimax
video LoRAs on this box). The same by-hash pass now covers LoRAs - lazily:
a local sidecar always wins and suppresses the lookup entirely, a LoRA whose
family no installed model can run is never hashed, and only the active
families plus the unknowns (the pass's whole reason to exist) are scanned.
A hit's `baseModel` fills `BY_HASH_BASE_MODEL`, rank 2 of 4 in `lora_profile`.

Filed as test_lora_covers.py because a parallel 9.19e job owns
tests/test_lora_meta.py for its picker-view suite; both are discovered by
`unittest discover` all the same.

What these tests pin:

  SidecarWins            - a LoRA with <stem>.jpeg beside it is used as-is:
                           no hash, no lookup, the picker wears the sidecar.
  ByHashAndTwins         - a bare LoRA is looked up by sha256; a byte-identical
                           twin or rename adopts the record with NO network
                           (Jesse's krea2filterbypass case).
  NullTitleRetry         - a null in _lora_titles.json is a miss, not a
                           tombstone: retried, never re-persisted.
  MissStaysCached        - a CivitAI/CivArchive miss is cached and not
                           re-queried next pass - until the retry window ends.
  LazyFamilyGate         - nothing is hashed for a family the picker has not
                           asked for (no installed model runs it); unknowns
                           are always in play.
  BaseModelClassifies    - a by-hash `baseModel` reaches install/families.json
                           through BY_HASH_BASE_MODEL and lora_stack stops
                           dropping the LoRA.

RED proof: all nine tests failed against the pre-9.19b tree - five on
behaviour (the LoRA pass simply did not exist, so no lookup ever ran and the
hook never filled), four on the missing machinery itself.
"""

import asyncio
import hashlib
import json
import os
import struct
import unittest
import urllib.parse
from contextlib import ExitStack, contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import ANY, AsyncMock, patch

def CANON(rel):
    """The rel in Pixal's INTERNAL canonical form: backslash, lowercased.

    Not a path. lora_profile opens with `rel.replace("/", BS)` and
    _sync_by_hash_base_models keys BY_HASH_BASE_MODEL the same way, so that
    form is the app's cross-platform convention for identifying a LoRA -
    deliberately stable whatever the filesystem uses. Look the hook up with
    this, and touch the disk with R().
    """
    return rel.replace("/", chr(92)).lower()


def R(*parts):
    """A catalog rel, in the platform's own separator.

    model_catalog builds every rel as str(path.relative_to(base)), so they
    carry os.sep - a backslash on Windows, a forward slash on Linux. These
    tests were written on Windows and hardcoded the backslash form, which on
    Linux is not a path at all: it is one filename with a backslash in it. The
    misc/ directory was never created, the file landed where nothing looked,
    and five of these tests failed in CI while passing locally.

    Note this is the rel only. The CivitAI cache key keeps its own literal
    backslash on every platform (_civ_key is kind + chr(92) + rel) because it
    is a namespace separator, not a path - so "loras" + chr(92) + rel stays
    correct here.
    """
    return os.path.join(*parts)


ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_lora_covers", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def write_safetensors(path, metadata=None, payload=b""):
    """A minimal safetensors: 8-byte header span + json header + payload."""
    header = json.dumps({"__metadata__": metadata or {}}).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header + payload)


@contextmanager
def library(loras, models=()):
    """A faked model library under one temp root: {rel: payload} LoRAs written
    to disk (real files, so hashing/stat/header reads all run for real) plus
    diffusion-model rels that only need to classify. A None payload registers
    the rel without writing the file - for twins and renames that arrive
    mid-test. model_catalog, model_roots and the sidecar-metadata read answer
    for this library and nothing else."""
    with TemporaryDirectory() as td:
        root = Path(td)
        entries = []
        for rel, payload in loras.items():
            if payload is None:
                entries.append({"rel": rel, "root": str(root), "kind": "loras",
                                "mtime": 0})
                continue
            p = root / "loras" / rel
            write_safetensors(p, payload=payload)
            entries.append({"rel": rel, "root": str(root), "kind": "loras",
                            "mtime": p.stat().st_mtime})
        for rel in models:
            entries.append({"rel": rel, "root": str(root),
                            "kind": "diffusion_models", "mtime": 0})
        with patch.object(server, "model_catalog",
                          side_effect=lambda kind=None, ttl=30:
                          [e for e in entries
                           if kind is None or e["kind"] == kind]), \
             patch.object(server, "model_roots", return_value=[root]), \
             patch.object(server, "adjacent_metadata", return_value={}):
            yield root


class LoraMetaBase(unittest.TestCase):
    """Shared hygiene: per-test cache files, an empty by-hash hook, no
    lora-manager, a silenced broadcast, and clean memoized header reads."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        tmp = Path(self._td.name)
        self.civ_cache = tmp / "civitai.json"
        self.title_cache = tmp / "titles.json"
        server.BY_HASH_BASE_MODEL.clear()
        server._CIV.update(data=None, busy=False)
        server._LM.update(at=0.0, by_rel={}, models_by_rel={})
        for fn in ("_lora_title_cached", "_lora_header_base_model"):
            f = getattr(server, fn, None)
            if hasattr(f, "cache_clear"):
                f.cache_clear()
        self._stack = ExitStack()
        self.addCleanup(self._stack.close)
        self._stack.enter_context(patch.object(server, "_CIVITAI_CACHE", self.civ_cache))
        self._stack.enter_context(patch.object(server, "_LORA_TITLE_CACHE", self.title_cache))
        self.broadcast = self._stack.enter_context(patch.object(server.HUB, "broadcast"))

    def mock_lookup(self, civ_result, arch_result=("miss", None)):
        civ = self._stack.enter_context(
            patch.object(server, "_civitai_by_hash", AsyncMock(return_value=civ_result)))
        arch = self._stack.enter_context(
            patch.object(server, "_civarchive_by_hash", AsyncMock(return_value=arch_result)))
        return civ, arch

    def refresh(self):
        asyncio.run(server.refresh_civitai_meta())

    def stored(self):
        return json.loads(self.civ_cache.read_text(encoding="utf-8")) \
            if self.civ_cache.exists() else {}


class SidecarWins(LoraMetaBase):
    """A LoRA with a local sidecar is used as-is and triggers NO lookup:
    not hashed, not queried, and the picker wears the sidecar cover."""

    def test_sidecar_lora_is_never_hashed_or_looked_up(self):
        rel = R("misc", "covered.safetensors")
        # The bare companion proves the pass RAN and skipped only the covered
        # one - without it 'no lookup' is vacuously true when nothing scans.
        bare = R("misc", "bare.safetensors")
        with library({rel: b"covered-bytes", bare: b"bare-bytes"}) as root:
            cover = root / "loras" / "misc" / "covered.jpeg"
            cover.write_bytes(b"jpeg")
            sha = self._stack.enter_context(
                patch.object(server, "_sha256_of", wraps=server._sha256_of))
            civ, arch = self.mock_lookup(("hit", {"name": "Bare", "version": "",
                                                  "thumb": "", "base": "",
                                                  "source": "civitai"}))
            self.refresh()
            hashed = {str(call.args[0]) for call in sha.call_args_list}
            self.assertNotIn(str(root / "loras" / rel), hashed)
            civ.assert_awaited_once()             # the bare companion only
            self.assertIsNone(self.stored().get("loras\\" + rel))
            self.assertEqual(server._civ_hit(bare, "loras")["name"], "Bare")

            # Used as-is: the picker entry wears the sidecar through the
            # existing lora-manager preview proxy - not a network cover.
            entry = {"name": rel}
            server._lora_entry_extras(entry, rel)
            self.assertIn("covered.jpeg",
                          urllib.parse.unquote(entry.get("thumb", "")))
            self.assertIsNone(entry.get("title"))   # nothing invented

    def test_metadata_sidecar_alone_also_suppresses_the_lookup(self):
        rel = R("misc", "documented.safetensors")
        bare = R("misc", "bare.safetensors")
        with library({rel: b"documented-bytes", bare: b"bare-bytes"}) as root:
            (root / "loras" / "misc" / "documented.metadata.json").write_text(
                json.dumps({"base_model": "Krea 2"}), encoding="utf-8")
            sha = self._stack.enter_context(
                patch.object(server, "_sha256_of", wraps=server._sha256_of))
            civ, arch = self.mock_lookup(("miss", None))
            self.refresh()
            hashed = {str(call.args[0]) for call in sha.call_args_list}
            self.assertNotIn(str(root / "loras" / rel), hashed)
            civ.assert_awaited_once()             # the bare companion only
            self.assertIsNone(self.stored().get("loras\\" + rel))


class ByHashAndTwins(LoraMetaBase):
    """A LoRA with no sidecar is looked up by sha256, and a renamed file
    resolves to the same record as its byte-identical twin - the FILE is the
    identity, not the name (Jesse's krea2filterbypass case)."""

    HIT = {"name": "Alpha Style", "version": "v1",
           "thumb": "https://image.civitai.com/x/alpha.jpeg",
           "base": "Krea 2", "source": "civitai"}

    def test_lookup_is_by_sha256_and_twins_share_one_record(self):
        rel_a = R("misc", "alpha.safetensors")
        rel_b = R("misc", "alpha_renamed.safetensors")   # the twin's filing name
        rel_c = R("misc", "alpha_moved.safetensors")     # the rename target
        with library({rel_a: b"alpha-bytes" * 64,
                      rel_b: None, rel_c: None}) as root:
            civ, arch = self.mock_lookup(("hit", dict(self.HIT)))
            self.refresh()
            want_sha = hashlib.sha256(
                (root / "loras" / rel_a).read_bytes()).hexdigest()
            civ.assert_awaited_once_with(ANY, want_sha)
            arch.assert_not_awaited()
            self.assertEqual(server._civ_hit(rel_a, "loras")["name"], "Alpha Style")
            self.assertEqual(server.BY_HASH_BASE_MODEL[CANON(rel_a)], "Krea 2")

            # The byte-identical twin arrives under another name: hashed (a
            # LoRA is small), adopted by sha, NO second network call.
            write_safetensors(root / "loras" / rel_b,
                              payload=b"alpha-bytes" * 64)
            self.refresh()
            civ.assert_awaited_once()
            self.assertEqual(server._civ_hit(rel_b, "loras")["name"], "Alpha Style")
            self.assertEqual(server.BY_HASH_BASE_MODEL[CANON(rel_b)], "Krea 2")

            # Renamed away: the new name adopts the record the same way.
            (root / "loras" / rel_b).rename(
                root / "loras" / rel_c)
            self.refresh()
            civ.assert_awaited_once()
            self.assertEqual(server._civ_hit(rel_c, "loras")["name"], "Alpha Style")
            self.assertEqual(server.BY_HASH_BASE_MODEL[CANON(rel_c)], "Krea 2")

    def test_the_picker_wears_the_by_hash_cover_and_name(self):
        rel = R("misc", "alpha.safetensors")
        with library({rel: b"alpha-bytes" * 64}):
            self.mock_lookup(("hit", dict(self.HIT)))
            self.refresh()
            entry = {"name": rel, "title": None}
            server._lora_entry_extras(entry, rel)
            self.assertEqual(entry["title"], "Alpha Style")
            self.assertEqual(entry["thumb"], self.HIT["thumb"])
            self.assertEqual(entry["base"], "Krea 2")


class NullTitleRetry(LoraMetaBase):
    """The _lora_titles.json trap: a null title stored as a PRESENT key pinned
    titleless LoRAs forever (162 of them sit sticky on the real box). A miss
    now stays retryable and is never written back."""

    def test_a_null_cached_title_does_not_suppress_a_retry(self):
        rel = R("misc", "titled.safetensors")
        with library({}) as root:
            write_safetensors(root / "loras" / rel,
                              {"modelspec.title": "The Real Title"}, b"x")
            self.title_cache.write_text(json.dumps({rel: None}), encoding="utf-8")
            titles = server._lora_title_map([rel])
            self.assertEqual(titles[rel], "The Real Title")
            # The retry healed the cache: the hit replaced the null.
            self.assertEqual(json.loads(self.title_cache.read_text(encoding="utf-8"))[rel],
                             "The Real Title")

    def test_a_real_miss_is_never_written_back_and_a_new_file_retries(self):
        rel = R("misc", "titleless.safetensors")
        with library({}) as root:
            p = root / "loras" / rel
            write_safetensors(p, {}, b"y")
            self.assertIsNone(server._lora_title_map([rel])[rel])
            stored = json.loads(self.title_cache.read_text(encoding="utf-8")) \
                if self.title_cache.exists() else {}
            self.assertNotIn(rel, stored)          # no sticky null
            # Same rel, new bytes (a fixed download): the memo keys on
            # (path, mtime, size), so the replacement is re-read, not pinned.
            write_safetensors(p, {"ss_output_name": "Now Titled"}, b"yz")
            self.assertEqual(server._lora_title_map([rel])[rel], "Now Titled")


class MissStaysCached(LoraMetaBase):
    """The CivitAI cache records misses and hashes on purpose: an obscure LoRA
    is queried once, not on every pass - but the retry window expiring DOES
    re-query it."""

    def test_a_miss_is_cached_and_not_requeried_next_pass(self):
        rel = R("misc", "obscure.safetensors")
        with library({rel: b"obscure-bytes"}):
            civ, arch = self.mock_lookup(("miss", None))
            self.refresh()
            civ.assert_awaited_once()
            arch.assert_awaited_once()
            rec = self.stored()["loras\\" + rel]
            self.assertNotIn("hit", rec)
            self.assertTrue(rec.get("sha256"))

            self.refresh()                          # fresh miss: no re-query
            civ.assert_awaited_once()
            arch.assert_awaited_once()

            # The retry window ending re-queries exactly once more.
            data = self.stored()
            data["loras\\" + rel]["checked"] -= server._CIV_MISS_RETRY + 60
            self.civ_cache.write_text(json.dumps(data), encoding="utf-8")
            server._CIV["data"] = None              # force a reload
            self.refresh()
            self.assertEqual(civ.await_count, 2)


class LazyFamilyGate(LoraMetaBase):
    """Jesse: 'we probably only have to scan for LoRAs of active base models.'
    A LoRA whose family no installed model can run is a family the picker
    never asks about - it is not hashed. Unknowns are always in play: the
    pass exists to classify them."""

    HIT = {"name": "Styler", "version": "", "thumb": "", "base": "",
           "source": "civitai"}

    def test_nothing_is_hashed_for_a_family_not_in_play(self):
        qwen_lora = R("Qwen", "Qwen-Image-Styler.safetensors")   # qwen_image by path
        unknown = R("misc", "probe.safetensors")
        with library({qwen_lora: b"qwen-bytes", unknown: b"probe-bytes"}) as root:
            sha = self._stack.enter_context(
                patch.object(server, "_sha256_of", wraps=server._sha256_of))
            civ, _arch = self.mock_lookup(("hit", dict(self.HIT)))
            self.refresh()                          # no installed models at all
            hashed = {Path(call.args[0]).name for call in sha.call_args_list}
            self.assertIn("probe.safetensors", hashed)        # unknowns: the job
            self.assertNotIn("Qwen-Image-Styler.safetensors", hashed)
            civ.assert_awaited_once()                          # the unknown only
            self.assertEqual(server._civ_hit(qwen_lora, "loras"), {})
            self.assertEqual(server._civ_hit(unknown, "loras")["name"], "Styler")

        # The family comes into play: a qwen_image model is installed now, so
        # the same LoRA is scanned - and the unknown's record moves to the new
        # library by sha (donor adoption), with no second network call for it.
        with library({qwen_lora: b"qwen-bytes", unknown: b"probe-bytes"},
                     models=(R("Qwen", "qwen-image.safetensors"),)):
            self.refresh()
            self.assertEqual(server._civ_hit(qwen_lora, "loras")["name"], "Styler")
            self.assertEqual(civ.await_count, 2)     # one per distinct content


class BaseModelClassifies(LoraMetaBase):
    """The 9.19a hook filled end to end: a by-hash hit's baseModel reaches
    install/families.json through BY_HASH_BASE_MODEL and the LoRA classifies -
    so lora_stack stops dropping it before the sampler."""

    def test_a_by_hash_base_model_reaches_the_family_table(self):
        rel = R("misc", "probe.safetensors")             # no sidecar/header/folder hint
        hit = {"name": "Probe", "version": "turbo",
               "thumb": "", "base": "ZImageTurbo", "source": "civitai"}
        with library({rel: b"probe-bytes"}):
            self.assertEqual(server.lora_profile(rel)["family"], "unknown")
            civ, _arch = self.mock_lookup(("hit", dict(hit)))
            self.refresh()
            civ.assert_awaited_once()
            self.assertEqual(server.BY_HASH_BASE_MODEL[CANON(rel)], "ZImageTurbo")

            profile = server.lora_profile(rel)
            self.assertEqual((profile["family"], profile["variant"]),
                             ("zimage", "turbo"))
            self.assertTrue(profile["supported"])
            with patch.object(server, "resolve_lora", side_effect=lambda name: name):
                kept, dropped = server.lora_stack([rel + ":0.8"], family="zimage")
                self.assertEqual([r for r, _st in kept], [rel])
                self.assertEqual(dropped, [])
                kept, dropped = server.lora_stack([rel + ":0.8"], family="krea2")
                self.assertEqual(kept, [])
                self.assertEqual(dropped, ["incompatible probe"])


if __name__ == "__main__":
    unittest.main()
