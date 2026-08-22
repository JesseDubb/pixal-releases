"""Brief 9.10 - the paging watchdog, sensor only.

On Windows the allocator never OOMs - WDDM pages silently: an identity edit
measured 110s/step on a 99.9%-full card (2026-08-11) with nothing in any
log. Every earlier defence is pre-flight, and pre-flight cannot be made
reliable on a card shared with ~20 opaque WDDM tenants. This sensor watches
the RENDER, relative to the job's own opening steps, and on a trip it logs
and ledger-records once per job. It deliberately does NOT act - what a
tripped watchdog should DO is a deferred product decision.

LIVE-MACHINE RULE: every number in this file is injected. No GPU read, no
ComfyUI call, no render.
"""

import time
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch


_SPEC = spec_from_file_location(
    "pixal_server_paging_watchdog", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


class PagingRateTripTests(unittest.TestCase):
    """The detector is a pure function over a sequence of step durations -
    the sanctioned simulation for the live-machine rule."""

    def test_healthy_steps_throughout_never_trip(self):
        durations = [32.0, 34.0, 33.0, 33.5, 32.5, 34.5, 33.0, 32.0,
                     33.5, 34.0, 33.0, 32.5, 33.0, 34.0]
        self.assertIsNone(server.paging_rate_trip(durations))

    def test_a_sustained_collapse_past_the_multiple_trips(self):
        """Healthy opening, then a collapse well past 4x sustained past the
        streak: trip at skip(1) + baseline(5) + streak(4) = step 10."""
        durations = [33.0] * 6 + [150.0] * 4
        trip = server.paging_rate_trip(durations)
        self.assertIsNotNone(trip)
        self.assertEqual(trip["step"], 10)
        self.assertEqual(trip["baseline"], 33.0)
        self.assertEqual(trip["rate"], 150.0)

    def test_a_collapse_that_ends_before_the_streak_does_not_trip(self):
        durations = [33.0] * 6 + [150.0] * 3 + [33.0] * 6
        self.assertIsNone(server.paging_rate_trip(durations))

    def test_a_single_slow_step_among_healthy_ones_does_not_trip(self):
        """One stall - a preview decode, a gc - is not paging."""
        durations = [33.0] * 6 + [400.0] + [33.0] * 8
        self.assertIsNone(server.paging_rate_trip(durations))

    def test_a_uniformly_slow_render_does_not_trip(self):
        """Slow from step one is a big render, not a collapse: the baseline
        is slow too, so there is nothing to collapse AGAINST. This is the
        false positive that matters most."""
        self.assertIsNone(server.paging_rate_trip([150.0] * 20))

    def test_too_few_steps_never_trip_and_never_crash(self):
        self.assertIsNone(server.paging_rate_trip([]))
        self.assertIsNone(server.paging_rate_trip([33.0]))
        self.assertIsNone(server.paging_rate_trip([33.0] * 9))
        # even a maximal collapse inside a job too short to judge
        self.assertIsNone(server.paging_rate_trip([33.0] * 3 + [500.0] * 6))

    def test_a_zero_baseline_cannot_trip_everything(self):
        """Anything is >= 4x zero; a degenerate baseline is no signal."""
        self.assertIsNone(server.paging_rate_trip([0.0] * 12))

    def test_the_first_trip_is_stable_as_the_list_grows(self):
        """The input is append-only, so the same trip comes back on every
        later call - the caller's per-job flag relies on it."""
        durations = [33.0] * 6 + [150.0] * 4
        first = server.paging_rate_trip(durations)
        later = server.paging_rate_trip(durations + [150.0] * 10)
        self.assertIsNotNone(first)
        self.assertEqual(first, later)

    def test_the_four_step_lightning_edit_lane_is_structurally_excluded(self):
        """The edit lane runs Qwen Lightning at 4 steps; a 10-step floor can
        never see it. Said out loud so a quiet ledger is never misread as
        'no paging happened'."""
        self.assertIsNone(server.paging_rate_trip([10.0, 10.0, 900.0, 900.0]))

    def test_the_multiple_stays_in_the_sensitive_band(self):
        """Brief 9.10 sizes the trip at 4-5x, NOT the ~10x of the single
        observed anecdote: for a log-only sensor a false positive costs a
        log line, a false negative costs the point of the brief."""
        self.assertGreaterEqual(server.PAGING_RATE_MULTIPLE, 4.0)
        self.assertLessEqual(server.PAGING_RATE_MULTIPLE, 5.0)


class WatchdogWiringTests(unittest.TestCase):
    """Through Hub.note_step_rate with an injected clock: one log line and
    one job record per job, and never a GPU read on the per-step path."""

    def setUp(self):
        self.hub = server.Hub.__new__(server.Hub)
        self.hub.subs = set()
        self.sent = []
        self.hub.broadcast = lambda **kw: self.sent.append(kw)

    def feed(self, job, gaps):
        """One progress event per entry; gaps[i] is the seconds step i+2
        took (the first event only starts the clock). gpu_free_bytes and
        gpu_stats are rigged to explode: the per-step path must add NO GPU
        read - that is what the live-machine rule is guarding. Collapse gaps
        stay under STEP_SLOW_SECONDS so the older absolute check stays quiet
        and only the relative watchdog can speak."""
        now = [1000.0]
        steps = len(gaps) + 1
        with patch.object(server.time, "time", lambda: now[0]), \
             patch.object(server, "gpu_free_bytes",
                          side_effect=AssertionError("GPU read on the step path")), \
             patch.object(server, "gpu_stats",
                          side_effect=AssertionError("GPU read on the step path")), \
             patch("builtins.print") as prints:
            for i in range(steps):
                self.hub.note_step_rate(job, {"value": i + 1, "max": steps})
                if i < len(gaps):
                    now[0] += gaps[i]
        return prints

    @staticmethod
    def watchdog_lines(prints):
        return [str(c) for c in prints.call_args_list
                if "paging-watchdog" in str(c)]

    def test_a_collapse_logs_and_records_once_per_job(self):
        job = {"id": "j", "cid": "c", "template": "qwen_image",
               "_vram_free_min": int(0.42 * 2**30)}   # the gpu_watch sample
        prints = self.feed(job, [25.0] * 6 + [110.0] * 10)
        lines = self.watchdog_lines(prints)
        self.assertEqual(len(lines), 1, "one log line per job, not one per step")
        self.assertIn("qwen_image", lines[0])
        self.assertIn("110s/step", lines[0])
        self.assertIn("25.0s baseline", lines[0])
        self.assertIn("0.42GB", lines[0])
        self.assertEqual(job["_paging_watchdog"],
                         {"step": 10, "baseline_s": 25.0, "rate_s": 110.0,
                          "free_min": int(0.42 * 2**30)})
        # Sensor only: the trip is never narrated into the lane.
        self.assertEqual([m for m in self.sent if m.get("type") == "text"], [])

    def test_an_unsampled_card_still_logs_the_trip(self):
        """gpu_watch never sampled this job: log WITHOUT the free figure
        rather than adding a read on the hot path."""
        job = {"id": "j", "cid": "c", "template": "qwen_image"}
        prints = self.feed(job, [25.0] * 6 + [110.0] * 6)
        lines = self.watchdog_lines(prints)
        self.assertEqual(len(lines), 1)
        self.assertNotIn("free min", lines[0])
        self.assertIsNone(job["_paging_watchdog"]["free_min"])

    def test_a_healthy_job_says_nothing(self):
        job = {"id": "j", "cid": "c", "template": "qwen_image"}
        prints = self.feed(job, [25.0] * 15)
        self.assertEqual(self.watchdog_lines(prints), [])
        self.assertNotIn("_paging_watchdog", job)

    def test_a_short_edit_job_cannot_trip(self):
        """The 4-step Lightning edit lane is outside coverage by
        construction - even a 9x collapse never reaches the floor."""
        job = {"id": "j", "cid": "c", "template": "qwen_edit"}
        prints = self.feed(job, [10.0, 10.0, 90.0, 90.0])
        self.assertEqual(self.watchdog_lines(prints), [])
        self.assertNotIn("_paging_watchdog", job)


class _FinalizeHub:
    """Just enough Hub for finalize's ledger bookkeeping (the same seam the
    vram-block tests use): the real method, spies for the side effects."""

    def __init__(self):
        self.critic_hot = False
        self.prev_job_free_min = None
        self.ledgered = []

    def broadcast(self, **kw):
        pass

    def ledger_append(self, entry):
        self.ledgered.append(entry)

    finalize = server.Hub.finalize


class PagingWatchdogLedgerTests(unittest.TestCase):
    """A trip is exactly the kind of number brief 9.8 said must outlive
    sidecar.log rotation: it rides history.jsonl beside the vram block."""

    def job(self, **extra):
        return {"id": "f1", "cid": "c", "template": "qwen_image",
                "started": time.time(), "images": [{"filename": "a.png"}],
                "error": None, "scene": "s", "seed": 1, "count": 1,
                "spec": {}, **extra}

    def test_a_tripped_job_records_the_collapse_beside_the_vram_block(self):
        hub = _FinalizeHub()
        watchdog = {"step": 10, "baseline_s": 25.0, "rate_s": 110.0,
                    "free_min": int(0.42 * 2**30)}
        hub.finalize(self.job(_vram_peak=28 * 2**30,
                              _vram_free_min=int(0.42 * 2**30),
                              _paging_watchdog=watchdog))
        self.assertEqual(len(hub.ledgered), 1)
        entry = hub.ledgered[0]
        self.assertIn("vram", entry)
        self.assertEqual(entry["paging_watchdog"], watchdog)

    def test_a_clean_job_records_no_watchdog_block(self):
        hub = _FinalizeHub()
        hub.finalize(self.job(_vram_peak=28 * 2**30))
        self.assertNotIn("paging_watchdog", hub.ledgered[0])


if __name__ == "__main__":
    unittest.main()
