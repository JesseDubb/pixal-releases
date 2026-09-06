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
  TrainerDefaultsAreNotTitles - aitk_lora in the header is a miss, healed
                           out of the cache; a title two files share names
                           neither, and the filename takes over.
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
import time
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


class TwoVersionsOfOneModel(LoraMetaBase):
    """Three installed pairs share a CivitAI MODEL name because they are two
    versions of one model (HMNSFW V2 / V2.5, snofs v1 / v1_1, hmpussy v6 /
    Vagina). The header dedupe runs before the CivitAI floor and cannot see
    them; the by-hash record carries the VERSION name, and that tells them
    apart (2026-09-06)."""

    def _hits(self, root, versions):
        """_civitai_by_hash answering per sha256 of the FILE on disk:
        {rel: version}. A miss for anything else."""
        by_sha = {server._sha256_of(root / "loras" / rel): version
                  for rel, version in versions.items()}

        async def lookup(_s, sha):
            version = by_sha.get(sha)
            if version is None:
                return "miss", None
            return "hit", {"name": "HMNSFW - AIO Sex LoRA", "version": version,
                           "thumb": "", "base": "MiniMax H3", "source": "civitai"}
        self._stack.enter_context(patch.object(server, "_civitai_by_hash", lookup))
        self._stack.enter_context(patch.object(
            server, "_civarchive_by_hash", AsyncMock(return_value=("miss", None))))

    def _picker(self, rels):
        entries = [{"name": rel, "title": None} for rel in rels]
        for entry in entries:
            server._lora_entry_extras(entry, entry["name"])
        server._disambiguate_lora_titles(entries)
        return {e["name"]: e["title"] for e in entries}

    def test_a_shared_model_name_wears_each_files_version(self):
        a, b, c = (R("misc", f) for f in ("HMNSFW_AIO_V2.safetensors",
                                                "HMNSFW_AIO_V2.5.safetensors",
                                                "other.safetensors"))
        with library({a: b"v2-bytes" * 8, b: b"v25-bytes" * 8, c: b"other" * 8}) as root:
            self._hits(root, {a: "V2", b: "V2.5"})
            self.refresh()
            titles = self._picker([a, b, c])
        self.assertEqual(titles[a], "HMNSFW - AIO Sex LoRA V2")
        self.assertEqual(titles[b], "HMNSFW - AIO Sex LoRA V2.5")
        self.assertIsNone(titles[c])                 # a miss keeps its filename

    def test_a_lone_hit_never_grows_a_version(self):
        a = R("misc", "HMNSFW_AIO_V2.safetensors")
        with library({a: b"v2-bytes" * 8}) as root:
            self._hits(root, {a: "V2"})
            self.refresh()
            self.assertEqual(self._picker([a])[a], "HMNSFW - AIO Sex LoRA")

    def test_a_version_the_name_already_carries_is_not_doubled(self):
        a, b = (R("misc", f) for f in ("x_v2.safetensors", "x_v2b.safetensors"))
        with library({a: b"one" * 8, b: b"two" * 8}) as root:
            self._hits(root, {a: "AIO Sex LoRA", b: "V2.5"})
            self.refresh()
            titles = self._picker([a, b])
        self.assertEqual(titles[a], "HMNSFW - AIO Sex LoRA")   # version is in the name
        self.assertEqual(titles[b], "HMNSFW - AIO Sex LoRA V2.5")

    def test_when_the_version_cannot_tell_them_apart_the_filename_does(self):
        a, b = (R("misc", f) for f in ("twin_a.safetensors", "twin_b.safetensors"))
        with library({a: b"aaa" * 8, b: b"bbb" * 8}) as root:
            self._hits(root, {a: "V2", b: "V2"})
            self.refresh()
            titles = self._picker([a, b])
        self.assertIsNone(titles[a])
        self.assertIsNone(titles[b])


class VideoPreviewsAreCovers(LoraMetaBase):
    """MiniMax H3 is a video model, so CivitAI previews its LoRAs as video -
    and _civitai_by_hash took images only, so all 22 H3 LoRAs on the real box
    were stored as hits with an empty thumb, which a stored hit never
    revisited. Now: the first video is a cover (LoraThumb plays mp4), a
    thumbless hit is retried on the miss window, and a record stored before
    the rule changed gets one more look (2026-09-06)."""

    class _Resp:
        def __init__(self, payload):
            self.status, self._payload = 200, payload
        async def json(self):
            return self._payload
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False

    class _Session:
        def __init__(self, payload):
            self.payload = payload
        def get(self, _url, timeout=None):
            return VideoPreviewsAreCovers._Resp(self.payload)

    def test_a_video_only_version_yields_its_first_video_as_the_cover(self):
        payload = {"model": {"name": "HMNSFW - AIO Sex LoRA"}, "name": "V2",
                   "baseModel": "MiniMax H3",
                   "images": [{"type": "video", "url": "https://image.civitai.com/x/1.mp4"},
                              {"type": "video", "url": "https://image.civitai.com/x/2.mp4"}]}
        status, hit = asyncio.run(
            server._civitai_by_hash(self._Session(payload), "ab" * 32))
        self.assertEqual(status, "hit")
        self.assertEqual(hit["thumb"], "https://image.civitai.com/x/1.mp4")

    def test_an_image_still_beats_a_video(self):
        payload = {"model": {"name": "Alpha"}, "name": "v1", "baseModel": "Krea 2",
                   "images": [{"type": "video", "url": "https://image.civitai.com/x/1.mp4"},
                              {"type": "image", "url": "https://image.civitai.com/x/1.jpeg"}]}
        _status, hit = asyncio.run(
            server._civitai_by_hash(self._Session(payload), "ab" * 32))
        self.assertEqual(hit["thumb"], "https://image.civitai.com/x/1.jpeg")

    def test_a_thumbless_hit_is_asked_again_once_its_window_or_the_rule_allows(self):
        recent = R("misc", "recent.safetensors")     # thumbless, checked just now
        stale = R("misc", "stale.safetensors")       # thumbless, checked before the rule
        covered = R("misc", "covered.safetensors")   # has a cover, checked long ago
        with library({recent: b"recent" * 64, stale: b"stale" * 64,
                      covered: b"covered" * 64}) as root:
            def record(rel, thumb, checked):
                p = root / "loras" / rel
                st = p.stat()
                return {"size": st.st_size, "mtime": st.st_mtime,
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                        "checked": checked,
                        "hit": {"name": "N", "version": "v", "thumb": thumb,
                                "base": "MiniMax H3", "source": "civitai"}}
            now = time.time()
            self.civ_cache.write_text(json.dumps({
                "loras" + chr(92) + recent: record(recent, "", now),
                "loras" + chr(92) + stale: record(stale, "", server._CIV_THUMB_RULE_SINCE - 1),
                "loras" + chr(92) + covered: record(
                    covered, "https://image.civitai.com/x/c.jpeg", now - 400 * 86400),
            }), encoding="utf-8")
            civ, _arch = self.mock_lookup(("hit", {
                "name": "N", "version": "v", "thumb": "https://image.civitai.com/x/1.mp4",
                "base": "MiniMax H3", "source": "civitai"}))
            self.refresh()
            civ.assert_awaited_once()               # the stale one, and only it
            self.assertEqual(server._civ_hit(stale, "loras")["thumb"],
                             "https://image.civitai.com/x/1.mp4")
            self.assertEqual(server._civ_hit(recent, "loras")["thumb"], "")
            self.assertEqual(server._civ_hit(covered, "loras")["thumb"],
                             "https://image.civitai.com/x/c.jpeg")
            # Re-checked: stamped now, so the next load leaves it alone.
            stored = json.loads(self.civ_cache.read_text(encoding="utf-8"))
            self.assertGreater(stored["loras" + chr(92) + stale]["checked"],
                               server._CIV_THUMB_RULE_SINCE)


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


class TrainerDefaultsAreNotTitles(LoraMetaBase):
    """ss_output_name is kohya's / AI Toolkit's --output_name: the filename at
    training time, not a title. Eight LoRAs on the real box all read
    `aitk_lora` in the picker and blocked their own CivitAI names, which only
    apply to an EMPTY title. A trainer default is a miss; a title shared by
    more than one installed file resolves to the filename for all of them."""

    def stored_titles(self):
        return json.loads(self.title_cache.read_text(encoding="utf-8")) \
            if self.title_cache.exists() else {}

    def test_a_trainer_default_is_a_miss_and_never_cached(self):
        rel = R("misc", "PAWG_krea2_epoch32.safetensors")
        with library({}) as root:
            write_safetensors(root / "loras" / rel, {"ss_output_name": "aitk_lora"}, b"x")
            self.assertIsNone(server._lora_title_map([rel])[rel])
            self.assertNotIn(rel, self.stored_titles())

    def test_a_trainer_default_cached_as_a_hit_is_healed(self):
        rel = R("misc", "HMBody_D_e10.safetensors")
        with library({}) as root:
            write_safetensors(root / "loras" / rel, {"ss_output_name": "aitk_lora"}, b"x")
            self.title_cache.write_text(json.dumps({rel: "aitk_lora"}), encoding="utf-8")
            self.assertIsNone(server._lora_title_map([rel])[rel])
            self.assertNotIn(rel, self.stored_titles())

    def test_a_trainer_default_yields_to_the_next_header_key(self):
        rel = R("misc", "instant-camera.safetensors")
        with library({}) as root:
            write_safetensors(root / "loras" / rel,
                              {"modelspec.title": "lora",
                               "ss_output_name": "Instant camera portrait"}, b"x")
            self.assertEqual(server._lora_title_map([rel])[rel],
                             "Instant camera portrait")

    def test_a_title_shared_by_two_files_resolves_to_neither(self):
        a, b, c = (R("misc", f) for f in ("snofs_krea_v1.safetensors",
                                          "snofs_krea_v1_2.safetensors",
                                          "unique.safetensors"))
        with library({}) as root:
            for rel in (a, b):
                write_safetensors(root / "loras" / rel,
                                  {"ss_output_name": "snofs_krea"}, b"x")
            write_safetensors(root / "loras" / c, {"modelspec.title": "Only One"}, b"y")
            titles = server._lora_title_map([a, b, c])
            self.assertIsNone(titles[a])
            self.assertIsNone(titles[b])
            self.assertEqual(titles[c], "Only One")
            # The header truth stays cached per file: sharing is a property of
            # the collection, resolved on every pass and never persisted.
            self.assertEqual(self.stored_titles()[a], "snofs_krea")


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
