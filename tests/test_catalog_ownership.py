"""Catalog cache ownership and legacy call-time seams, over temporary roots."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server
from pixal.catalog import Catalog


class CatalogOwnershipTests(unittest.TestCase):
    def test_revisioned_snapshot_is_detached_and_read_only(self):
        owner = Catalog()
        source = [{"kind": "loras", "rel": "synthetic.safetensors"}]
        owner.publish(source, 100)
        owner.sidecar_meta[("loras", "synthetic")] = {"tags": ["synthetic"]}
        snap = owner.snapshot()
        source[0]["rel"] = "changed"
        self.assertEqual(snap.models[0]["rel"], "synthetic.safetensors")
        with self.assertRaises(TypeError):
            snap.models[0]["rel"] = "bad"
        with self.assertRaises(TypeError):
            snap.metadata[("loras", "synthetic")]["tags"][0] = "bad"
        owner.invalidate()
        self.assertGreater(owner.snapshot().revision, snap.revision)
        self.assertEqual(owner.snapshot().models, ())
        self.assertEqual(len(snap.models), 1)

    def test_ttl_and_explicit_invalidation_use_one_recursive_scanner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "loras" / "nested"
            folder.mkdir(parents=True)
            (folder / "one.safetensors").write_bytes(b"one")
            hidden = folder / ".cache"
            hidden.mkdir()
            (hidden / "hidden.gguf").write_bytes(b"skip")
            owner = Catalog()
            now = [100]
            get = lambda: owner.model_catalog("loras", roots=lambda: [root], clock=lambda: now[0])
            self.assertEqual([e["rel"] for e in get()], [str(Path("nested/one.safetensors"))])
            (folder / "two.gguf").write_bytes(b"two")
            self.assertEqual(len(get()), 1)
            now[0] = 131
            self.assertEqual(len(get()), 2)
            (folder / "three.pt").write_bytes(b"three")
            owner.invalidate()
            self.assertEqual(len(get()), 3)
            progress = []
            self.assertEqual(owner.scan([root], progress.append), get())
            self.assertEqual(progress, ["loras - 3 files"])
            self.assertEqual(owner.model_catalog("", roots=lambda: [root], clock=lambda: now[0]), get())
            detached = get()
            detached[0]["rel"] = "corrupted by caller"
            self.assertNotEqual(get()[0]["rel"], detached[0]["rel"])

    def test_build_memo_calls_patched_server_uncached_once_and_clears_on_error(self):
        with patch.dict(server._MODEL_ROOTS_MEMO, active=False, roots=None), \
                patch.object(server, "load_config", return_value={}) as config, \
                patch.object(server, "_model_roots_uncached", side_effect=[[Path("first")], [Path("second")]]) as roots:
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                with server._catalog_owner().build_scope():
                    self.assertEqual(server.model_roots(), [Path("first")])
                    self.assertEqual(server.model_roots(), [Path("first")])
                    raise RuntimeError("synthetic")
            self.assertEqual(server.model_roots(), [Path("second")])
            self.assertEqual((config.call_count, roots.call_count), (2, 2))
            self.assertEqual(server._MODEL_ROOTS_MEMO, {"active": False, "roots": None})

    def test_catalog_and_metadata_resolve_patched_server_roots(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(server, "_CATALOG", {"at": 0, "data": None}), \
                patch.object(server, "_SIDECAR_META", {}):
            root = Path(tmp)
            (root / "loras").mkdir()
            (root / "loras" / "one.safetensors").write_bytes(b"one")
            (root / "loras" / "one.metadata.json").write_text('{"tags": ["synthetic"]}')
            with patch.object(server, "model_roots", return_value=[root]) as roots:
                self.assertEqual(len(server.model_catalog("loras")), 1)
                self.assertEqual(server.adjacent_metadata("loras", "one.safetensors"), {"tags": ["synthetic"]})
            self.assertEqual(roots.call_count, 2)

    def test_retarget_invalidates_every_inventory_and_keeps_input_patch_seams(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, "CDIR", Path(tmp)), \
                patch.object(server, "_CATALOG", {"at": 123, "data": [{"rel": "stale"}]}), \
                patch.object(server, "_SIDECAR_META", {"stale": {}}):
            root = Path(tmp)
            (root / "models").mkdir()
            (root / "input").mkdir()
            (root / "input" / "image.png").write_bytes(b"synthetic")
            server.apply_comfy_root(str(root))
            self.assertEqual(server._CATALOG, {"at": 0, "data": None})
            self.assertEqual(server._SIDECAR_META, {})
            with patch.object(server, "_input_record_from_parts", wraps=server._input_record_from_parts) as record:
                self.assertEqual(server.input_image_catalog()[0]["name"], "image.png")
                record.assert_called_once()
            with patch.object(server, "input_ref_name", return_value="nested/example.png") as ref:
                self.assertEqual(server.input_image_record("ignored")["subfolder"], "nested")
                ref.assert_called_once_with("ignored")
            self.assertEqual(server.input_ref_name("../escape.png"), "")

    def test_independent_owners_do_not_share_any_cache(self):
        first, second = Catalog(), Catalog()
        first.publish([{"kind": "loras"}], 100)
        first.sidecar_meta["synthetic"] = {"nested": []}
        first.roots_memo.update(active=True, roots=[Path("synthetic")])
        self.assertEqual(second.snapshot().models, ())
        self.assertEqual(dict(second.snapshot().metadata), {})
        self.assertFalse(second.roots_memo["active"])
