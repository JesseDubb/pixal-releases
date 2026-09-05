import copy
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from pixal.config.rules import default_config
from pixal.config.store import ConfigStore, ConfigUnreadableError, ConfigWriteError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/config_1_3_1b.json").read_text())


def defaults():
    return default_config(kimi_url="https://api.moonshot.ai/v1/chat/completions", kimi_model="kimi-k3",
                          api_key="", image_mode="model", image_vsr_mode="VSR Ultra", video_mode="VSR High")


class ConfigStoreTests(unittest.TestCase):
    def test_defaults_match_the_committed_build_and_are_detached(self):
        self.assertEqual(defaults(), FIXTURE["defaults"])
        changed = defaults()
        changed["llm"]["model"] = "changed"
        self.assertEqual(defaults(), FIXTURE["defaults"])

    def test_loading_matches_legacy_fixtures_including_partial_fallback(self):
        for case in FIXTURE["cases"]:
            with self.subTest(saved=case["saved"]), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.json"
                if case["saved"] is not None:
                    path.write_text(json.dumps(case["saved"]), encoding="utf-8")
                result = ConfigStore(path).load(defaults())
                digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
                self.assertEqual(digest, case["sha256"])

    def test_construction_does_not_create_or_read_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "absent/config.json"
            with patch.object(Path, "read_text", side_effect=AssertionError("unexpected read")):
                ConfigStore(path)
            self.assertFalse(path.parent.exists())

    def test_default_factory_runs_on_each_load_without_sharing_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(Path(tmp) / "config.json")
            first = store.load(defaults)
            first["llm"]["model"] = "only this caller"
            self.assertEqual(store.load(defaults), FIXTURE["defaults"])

    def test_write_round_trip_preserves_unicode_and_extension_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"future_extension": {"enabled": True},
                                       "llm": {"future_option": 2}}), encoding="utf-8")
            store = ConfigStore(path)
            cfg = store.load(defaults())
            cfg["llm"]["model"] = "synthetic — modèle"
            store.save(cfg)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["llm"]["model"], cfg["llm"]["model"])
            self.assertEqual(saved["future_extension"], {"enabled": True})
            self.assertEqual(saved["llm"]["future_option"], 2)
            self.assertEqual([file.name for file in path.parent.iterdir()], ["config.json"])

    def test_bad_json_is_backed_up_but_cannot_be_overwritten_by_a_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            original = b'{"broken":'
            path.write_bytes(original)
            store = ConfigStore(path)
            self.assertEqual(store.load(defaults()), defaults())
            with self.assertRaises(ConfigUnreadableError):
                store.save(defaults())
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(path.with_suffix(".json.bad").read_bytes(), original)

    def test_unmergeable_json_is_also_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"llm": 5}', encoding="utf-8")
            with self.assertRaises(ConfigUnreadableError):
                ConfigStore(path).save(defaults())
            self.assertEqual(path.read_text(), '{"llm": 5}')

    def test_failures_before_commit_leave_the_old_file_and_no_partial_temp(self):
        for operation in ("os.replace", "os.fsync", "tempfile.NamedTemporaryFile"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.json"
                original = json.dumps(defaults()).encode()
                path.write_bytes(original)
                with patch("pixal.config.store." + operation, side_effect=OSError("synthetic disk failure")):
                    with self.assertRaises(ConfigWriteError):
                        ConfigStore(path).save(defaults())
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual([file.name for file in path.parent.iterdir()], ["config.json"])

    def test_concurrent_updates_are_serialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(Path(tmp) / "config.json")
            def increment(cfg):
                cfg["llm"]["synthetic_count"] = cfg["llm"].get("synthetic_count", 0) + 1
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda _: store.update(defaults(), increment), range(24)))
            self.assertEqual(store.load(defaults())["llm"]["synthetic_count"], 24)

    def test_a_rejected_update_leaves_persistent_state_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(Path(tmp) / "config.json")
            store.save(defaults())
            original = store.path.read_bytes()
            def reject(cfg):
                cfg["llm"]["model"] = "must not persist"
                raise ValueError("invalid change")
            with self.assertRaises(ValueError):
                store.update(defaults(), reject)
            self.assertEqual(store.path.read_bytes(), original)

    def test_independent_stores_do_not_share_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = [ConfigStore(Path(tmp) / name) for name in ("one.json", "two.json")]
            cfg = defaults()
            cfg["llm"]["model"] = "only first"
            first.save(cfg)
            self.assertEqual(second.load(defaults()), defaults())
            self.assertFalse(second.path.exists())
