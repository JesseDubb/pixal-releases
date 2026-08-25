"""Brief 9.33 - cache-hit telemetry, sensor only.

ComfyUI caches every node output and skips any node whose inputs are
unchanged since the previous prompt; whether that actually fires for Pixal's
graphs was never observed, because the ws bridge dropped `execution_cached`.
This sensor captures the frame per job, rides the ledger at finalize, and
prints one console line per job. It deliberately does NOT act - the number
decides whether the next lever is prewarming or graph keying.

LIVE-MACHINE RULE: no ComfyUI, no GPU, no ledger file - every input is
injected.
"""

import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]

_SPEC = spec_from_file_location("pixal_server_cache_telemetry", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

_REPORT_SPEC = spec_from_file_location("pixal_cache_report", ROOT / "cache_report.py")
cache_report = module_from_spec(_REPORT_SPEC)
_REPORT_SPEC.loader.exec_module(cache_report)


class CacheSummaryTests(unittest.TestCase):
    """cache_summary is a pure function: node ids in, class-type lists out."""

    NODES = {"1": "UNETLoader", "2": "CLIPTextEncode",
             "3": "KSampler", "4": "VAEDecode"}

    def test_a_full_hit_skips_everything(self):
        s = server.cache_summary(dict(self.NODES), ["1", "2", "3", "4"])
        self.assertTrue(s["observed"])
        self.assertEqual(s["hit"], 4)
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["skipped"], ["CLIPTextEncode", "KSampler",
                                        "UNETLoader", "VAEDecode"])
        self.assertEqual(s["ran"], [])

    def test_a_full_miss_runs_everything(self):
        """An observed empty list is a real 0% - ComfyUI sent the frame and
        named nothing."""
        s = server.cache_summary(dict(self.NODES), [])
        self.assertTrue(s["observed"])
        self.assertEqual(s["hit"], 0)
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["skipped"], [])
        self.assertEqual(s["ran"], ["CLIPTextEncode", "KSampler",
                                    "UNETLoader", "VAEDecode"])

    def test_no_frame_is_unobserved_and_never_a_miss(self):
        """None means ComfyUI never sent the frame - the same None rule
        prev_floor_below_guard states: no signal must not read as zero hits."""
        s = server.cache_summary(dict(self.NODES), None)
        self.assertFalse(s["observed"])
        self.assertEqual(s["hit"], 0)
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["skipped"], [])
        self.assertEqual(s["ran"], [])

    def test_ids_comfy_reports_but_we_dont_know_are_not_counted(self):
        """ComfyUI can name a subgraph node; unknown ids neither crash the
        summary nor inflate the hit count."""
        s = server.cache_summary(dict(self.NODES), ["1", "2", "99", "100"])
        self.assertTrue(s["observed"])
        self.assertEqual(s["hit"], 2)
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["skipped"], ["CLIPTextEncode", "UNETLoader"])
        self.assertEqual(s["ran"], ["KSampler", "VAEDecode"])

    def test_class_types_are_deduplicated(self):
        """Two CLIPTextEncode nodes (positive + negative prompt) are one line
        of work to a human reading the ledger; ids are what get counted."""
        nodes = {"1": "CLIPTextEncode", "2": "CLIPTextEncode", "3": "KSampler"}
        s = server.cache_summary(nodes, ["3"])
        self.assertEqual(s["hit"], 1)
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["skipped"], ["KSampler"])
        self.assertEqual(s["ran"], ["CLIPTextEncode"])


class _FinalizeHub:
    """Just enough Hub for finalize's ledger bookkeeping (the same seam the
    paging-watchdog tests use): the real method, spies for the side effects."""

    def __init__(self):
        self.critic_hot = False
        self.prev_job_free_min = None
        self.ledgered = []

    def broadcast(self, **kw):
        pass

    def ledger_append(self, entry):
        self.ledgered.append(entry)

    finalize = server.Hub.finalize


class CacheFinalizeTests(unittest.TestCase):
    """The summary rides history.jsonl beside the vram and paging_watchdog
    blocks, and the console gets exactly one line per job."""

    def job(self, **extra):
        return {"id": "c9", "cid": "c", "template": "qwen_image",
                "started": time.time(), "images": [{"filename": "a.png"}],
                "error": None, "scene": "s", "seed": 1, "count": 1,
                "spec": {}, **extra}

    def cache_lines(self, prints):
        return [str(c) for c in prints.call_args_list if "[pixal] cache:" in str(c)]

    def test_an_observed_job_records_and_logs_the_hit(self):
        hub = _FinalizeHub()
        nodes = {"1": "UNETLoader", "2": "KSampler", "3": "VAEDecode"}
        with patch("builtins.print") as prints:
            hub.finalize(self.job(node_types=nodes, _cached_nodes=["1"]))
        entry = hub.ledgered[0]
        self.assertEqual(entry["cache"],
                         {"observed": True, "hit": 1, "total": 3,
                          "skipped": ["UNETLoader"], "ran": ["KSampler", "VAEDecode"]})
        lines = self.cache_lines(prints)
        self.assertEqual(len(lines), 1, "one cache line per job")
        self.assertIn("1/3 nodes skipped", lines[0])
        self.assertIn("job c9", lines[0])
        self.assertIn("ran: KSampler, VAEDecode", lines[0])

    def test_a_job_with_no_frame_records_unobserved_not_a_miss(self):
        hub = _FinalizeHub()
        nodes = {"1": "UNETLoader", "2": "KSampler"}
        with patch("builtins.print") as prints:
            hub.finalize(self.job(node_types=nodes))
        self.assertEqual(hub.ledgered[0]["cache"],
                         {"observed": False, "hit": 0, "total": 2,
                          "skipped": [], "ran": []})
        lines = self.cache_lines(prints)
        self.assertEqual(len(lines), 1)
        self.assertIn("no execution_cached frame", lines[0])

    def test_a_job_without_node_types_records_nothing_and_says_nothing(self):
        """A job that never reached ComfyUI (refused pre-flight) has no
        graph to judge - silence, not a bogus unobserved row."""
        hub = _FinalizeHub()
        with patch("builtins.print") as prints:
            hub.finalize(self.job())
        self.assertNotIn("cache", hub.ledgered[0])
        self.assertEqual(self.cache_lines(prints), [])


class CacheReportTests(unittest.TestCase):
    """The report is the tool the brief exists for; it must never traceback -
    least of all on the ledger state that exists today (every entry
    pre-sensor) or on no ledger at all."""

    def run_report(self, path):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cache_report.main(path)
        self.assertEqual(rc, 0)
        return out.getvalue()

    def test_an_absent_ledger_reports_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = self.run_report(Path(tmp) / "no_such_ledger.jsonl")
        self.assertIn("no ledger entries", text)

    def test_an_empty_ledger_reports_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            path.write_text("", encoding="utf-8")
            text = self.run_report(path)
        self.assertIn("no ledger entries", text)

    def test_a_pre_sensor_ledger_reads_as_unobserved_not_as_misses(self):
        """Today's real ledger: entries with no cache block at all. The
        report must say unobserved, never 0% - the same None rule the
        summary itself follows."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            entries = [{"id": "a1", "ts": time.time(), "template": "qwen_image"},
                       {"id": "b2", "ts": time.time(), "template": "qwen_image"},
                       {"id": "c3", "ts": time.time(), "template": "h3_full"}]
            path.write_text("".join(json.dumps(e) + "\n" for e in entries),
                            encoding="utf-8")
            text = self.run_report(path)
        self.assertIn("3 pre-sensor", text)
        self.assertIn("observed 0/2", text)          # qwen_image row
        self.assertNotIn("0% (", text)               # never reads as a miss
        self.assertIn("pre-sensor (no cache data)", text)

    def test_observed_entries_drive_the_hit_rate_and_ran_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            entries = [
                {"id": "a1", "ts": time.time(), "template": "qwen_image",
                 "cache": {"observed": True, "hit": 3, "total": 4,
                           "skipped": ["UNETLoader"], "ran": ["KSampler"]}},
                {"id": "b2", "ts": time.time(), "template": "qwen_image",
                 "cache": {"observed": True, "hit": 1, "total": 4,
                           "skipped": [], "ran": ["KSampler"]}},
                {"id": "c3", "ts": time.time(), "template": "qwen_image",
                 "cache": {"observed": False, "hit": 0, "total": 4,
                           "skipped": [], "ran": []}},
            ]
            path.write_text("".join(json.dumps(e) + "\n" for e in entries),
                            encoding="utf-8")
            text = self.run_report(path)
        self.assertIn("observed 2/3", text)
        self.assertIn("50% (4/8 nodes)", text)       # aggregate, not per-job mean
        self.assertIn("most-common ran: KSampler", text)
        self.assertIn("no execution_cached frame", text)


if __name__ == "__main__":
    unittest.main()
