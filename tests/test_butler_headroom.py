"""Brief 9.76 - the butler keeps headroom, priced from the ledger.

Jesse (2026-08-27): "why do we run right to the limit of my vram - can't
the app unload the chat brain if it knows the render is gonna be stressed
at 31.1 GB". Measured on the ledger that night: the butler rested the
brain only when the priced stack failed the FIT test, and the price was
routinely wrong by the brain itself (identity_edit 0488e5b9: ~3.5GB
priced, 8.6GB real growth; h3_ref_still 7ff05e99: priced 29.7GB, peaked
30.1GB, 1.37GB free at the worst sample). Two fixes, tested here: a
HEADROOM rule ahead of the fit test (priced stack + resident brain within
4GB of the card rests the brain up front; jobs priced under half the card
keep it), and an activation price calibrated from the ledger's own
(peak - start) deltas with the ACT_PROFILES constant as the floor.

LIVE-MACHINE RULE: every number is injected - table, ledger, driver
reads, brain kills. No GPU read, no ComfyUI call, no render.
"""

import asyncio
import io
import unittest
from contextlib import ExitStack, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock, patch


_SPEC = spec_from_file_location(
    "pixal_server_butler_headroom", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

GB = 2**30


class HeadroomRuleTests(unittest.TestCase):
    """The pure predicate: priced stack + resident brain inside 4GB of the
    card rests the brain; under half the card priced, it stays."""

    def test_a_priced_26gb_job_with_a_55gb_brain_rests_on_a_32gb_card(self):
        # The brief's case: 26 + 5.5 = 31.5GB leaves 0.5GB of a 32GB card.
        self.assertTrue(server.brain_headroom_rest(
            26 * GB, int(5.5 * GB), 32 * GB))

    def test_a_10gb_job_keeps_the_brain(self):
        # Priced under half the card - the rest would cost the next chat a
        # reload and buys nothing.
        self.assertFalse(server.brain_headroom_rest(
            10 * GB, int(5.5 * GB), 32 * GB))

    def test_a_small_job_keeps_the_brain_even_when_it_would_not_fit(self):
        # Under half priced, so the rule never even looks at the sum.
        self.assertFalse(server.brain_headroom_rest(
            15 * GB, 13 * GB, 32 * GB))

    def test_no_brain_resident_is_nothing_to_buy(self):
        self.assertFalse(server.brain_headroom_rest(30 * GB, 0, 32 * GB))

    def test_an_unread_card_never_rests(self):
        self.assertFalse(server.brain_headroom_rest(30 * GB, int(5.5 * GB), 0))

    def test_the_boundary_is_exactly_the_headroom(self):
        # priced + brain == card - HEADROOM is headroom, not under it.
        priced = 28 * GB - int(5.5 * GB)
        self.assertFalse(server.brain_headroom_rest(
            priced, int(5.5 * GB), 32 * GB))
        self.assertTrue(server.brain_headroom_rest(
            priced + 1, int(5.5 * GB), 32 * GB))


def _entry(template, delta_gb=None, canvas_mp="missing"):
    """One finalized ledger line, newest-first assembly is the caller's."""
    e = {"id": "x", "template": template}
    if delta_gb is not None:
        e["vram"] = {"priced": None, "start": 10 * GB,
                     "peak": 10 * GB + int(delta_gb * GB), "free_min": GB}
    if canvas_mp != "missing":
        e["info"] = {"canvas_mp": canvas_mp}
    return e


class LedgerActivationEstimateTests(unittest.TestCase):
    """The calibration helper: median of (peak - start) over the newest
    <=8 same-template finals that carry both driver reads."""

    def test_returns_the_median_delta(self):
        entries = [_entry("identity_edit", d) for d in (9, 7, 5)]
        self.assertEqual(
            server.ledger_activation_estimate(entries, "identity_edit", None),
            7 * GB)

    def test_the_window_is_the_newest_eight(self):
        # Newest first: the ninth (oldest) entry never enters the median.
        entries = [_entry("identity_edit", d)
                   for d in (9, 9, 9, 9, 5, 1, 1, 1, 1)]
        self.assertEqual(
            server.ledger_activation_estimate(entries, "identity_edit", None),
            7 * GB)

    def test_entries_without_vram_fields_are_ignored(self):
        valid = [_entry("identity_edit", 6), _entry("identity_edit", 8)]
        invalid = [{"id": "a", "template": "identity_edit"},          # no vram
                   {"id": "b", "template": "identity_edit", "vram": {}},
                   {"id": "c", "template": "identity_edit",
                    "vram": {"peak": 20 * GB}}]                        # no start
        self.assertIsNone(server.ledger_activation_estimate(
            valid + invalid, "identity_edit", None))                   # 2 < 3
        valid.append(_entry("identity_edit", 10))
        self.assertEqual(
            server.ledger_activation_estimate(
                valid + invalid, "identity_edit", None),
            8 * GB)             # the invalid three never diluted the median

    def test_other_templates_never_count(self):
        entries = [_entry("identity_edit", 9), _entry("identity_edit", 9)]
        entries += [_entry("h3_still", 30)] * 5
        self.assertIsNone(
            server.ledger_activation_estimate(entries, "identity_edit", None))

    def test_the_canvas_bucket_filters_when_the_field_exists(self):
        entries = [_entry("identity_edit", 9, canvas_mp=3.1),
                   _entry("identity_edit", 9, canvas_mp=2.97),   # same bucket
                   _entry("identity_edit", 9, canvas_mp=3.15),   # same bucket
                   _entry("identity_edit", 1, canvas_mp=1.03),   # bucket 1: out
                   _entry("identity_edit", 1, canvas_mp=0.88)]   # bucket 1: out
        self.assertEqual(
            server.ledger_activation_estimate(entries, "identity_edit", 3.1),
            9 * GB)

    def test_unknown_canvases_do_not_calibrate_a_known_canvas(self):
        # Unknown-size renders cannot price a known canvas. Previously these
        # mixed large cold runs into small warm rerolls of the same recipe.
        entries = [_entry("identity_edit", 9, canvas_mp=3.1),
                   _entry("identity_edit", 9),
                   _entry("identity_edit", 9)]
        self.assertIsNone(
            server.ledger_activation_estimate(entries, "identity_edit", 3.1))

    def test_fewer_than_three_samples_is_not_a_measurement(self):
        entries = [_entry("identity_edit", 9), _entry("identity_edit", 7)]
        self.assertIsNone(
            server.ledger_activation_estimate(entries, "identity_edit", None))


class GraphActivationCalibrationTests(unittest.TestCase):
    """graph_activation_bytes with a ledger: the constant is the floor,
    the median is the price when it is higher."""

    def test_floors_at_the_constant_when_the_median_is_lower(self):
        # identity_edit at 1.0MP prices 2.0 + 1.5 = 3.5GB from the profile.
        entries = [_entry("identity_edit", 1, canvas_mp=1.0)] * 3
        self.assertEqual(
            server.graph_activation_bytes(
                "identity_edit", {}, {"canvas_mp": 1.0}, entries=entries),
            int(3.5 * GB))

    def test_adopts_the_median_when_it_is_higher(self):
        entries = [_entry("identity_edit", 9.2, canvas_mp=1.0)] * 3
        self.assertEqual(
            server.graph_activation_bytes(
                "identity_edit", {}, {"canvas_mp": 1.0}, entries=entries),
            int(9.2 * GB))

    def test_fewer_than_three_samples_leaves_the_constant(self):
        entries = [_entry("identity_edit", 9.2, canvas_mp=1.0)] * 2
        self.assertEqual(
            server.graph_activation_bytes(
                "identity_edit", {}, {"canvas_mp": 1.0}, entries=entries),
            int(3.5 * GB))

    def test_no_ledger_is_the_old_constant_behaviour(self):
        self.assertEqual(
            server.graph_activation_bytes(
                "identity_edit", {}, {"canvas_mp": 1.0}),
            int(3.5 * GB))


class _HeadroomStubHub:
    """Just enough Hub for ensure_vram: state + spies, the real methods,
    an injected card read and an injected ledger."""

    queue_remaining = 0

    def __init__(self, card_total_gb=32.0, entries=()):
        self.jobs = {}
        self.resident_heavies = {}
        self.model_last_used = {}
        self.job_seq = 0
        self.critic_hot = False
        self.prev_job_free_min = None
        self.gpu = {"total": card_total_gb} if card_total_gb else None
        self._entries = list(entries)
        self.texts = []

    def ledger_read(self):
        return self._entries

    async def flush_comfy_cache(self, why, unload=True, free_memory=True):
        if unload:
            self.resident_heavies = {}
            self.model_last_used = {}
            self.critic_hot = False
        return True

    def broadcast(self, **kw):
        if kw.get("type") == "text":
            self.texts.append(kw.get("text"))

    ensure_vram = server.Hub.ensure_vram
    reclaim_vram = server.Hub.reclaim_vram
    busy_elsewhere = server.Hub.busy_elsewhere
    forget_residency = server.Hub.forget_residency
    evict_idle_lane = server.Hub.evict_idle_lane
    rest_brain_for_render = server.Hub.rest_brain_for_render
    note_desktop_weight = server.Hub.note_desktop_weight
    idle_lane_weights = server.Hub.idle_lane_weights
    idle_lane_template = server.Hub.idle_lane_template
    _mark_used = server.Hub._mark_used


GRAPH = {"u": {"class_type": "UNETLoader",
               "inputs": {"unet_name": "stub\\heavy.safetensors"}}}
BRAIN_ROW = {"pid": 2, "name": "python.exe", "gb": 5.5, "role": "brain"}


def run_butler(hub, weight_gb, free_reads, template="zimage",
               info=None, brain_est_gb=0.0, table=(), brain_kills=None):
    """Drive the real ensure_vram with every machine read injected."""
    brain_kills = list(brain_kills or [])

    async def _kill():
        return brain_kills.pop(0) if brain_kills else False

    with ExitStack() as st:
        st.enter_context(patch.object(
            server, "_weight_file_bytes", return_value=int(weight_gb * GB)))
        st.enter_context(patch.object(
            server, "comfy_vram_free_bytes",
            AsyncMock(side_effect=[int(f * GB) for f in free_reads])))
        st.enter_context(patch.object(
            server, "gpu_free_bytes", return_value=25 * GB))
        st.enter_context(patch.object(server, "gpu_hogs", return_value=[]))
        st.enter_context(patch.object(
            server, "ram_free_bytes", return_value=32 * GB))
        st.enter_context(patch.object(
            server, "gpu_process_table", return_value=list(table)))
        st.enter_context(patch.object(
            server, "brain_vram_estimate",
            return_value=int(brain_est_gb * GB)))
        hub.brain = st.enter_context(patch.object(
            server, "free_brain_vram", AsyncMock(side_effect=_kill)))
        st.enter_context(patch.object(server.asyncio, "sleep", AsyncMock()))
        job = {"id": "h1", "cid": "c"}
        out = io.StringIO()
        with redirect_stdout(out):
            asyncio.run(hub.ensure_vram(template, dict(GRAPH), job, info))
    return job, out.getvalue()


class EnsureVramHeadroomTests(unittest.TestCase):
    """The rule wired in, ahead of the fit test: these jobs all FIT - the
    card reads 30GB free - so only the headroom rule can move the brain."""

    def test_a_priced_26gb_job_rests_the_brain_up_front(self):
        # 24GB weights + 2.2GB profile act = 26.2GB priced; + 5.5GB brain
        # leaves 0.3GB of the 32GB card. The fit test alone would wave it
        # through with the brain aboard - tonight's 31.1GB story.
        hub = _HeadroomStubHub(card_total_gb=32.0)
        run_butler(hub, 24, [30, 30], info={"canvas_mp": 1.0},
                   brain_est_gb=5.5, table=[BRAIN_ROW], brain_kills=[True])
        hub.brain.assert_awaited_once()
        self.assertEqual(
            hub.texts,
            ["*brain rested - this render prices 26.2 of 32.0 GB*"])
        self.assertEqual(hub.resident_heavies,
                         {"stub\\heavy.safetensors": 24 * GB})   # job ran

    def test_a_10gb_job_keeps_the_brain(self):
        hub = _HeadroomStubHub(card_total_gb=32.0)
        run_butler(hub, 8, [30, 30], info={"canvas_mp": 1.0},
                   brain_est_gb=5.5, table=[BRAIN_ROW], brain_kills=[True])
        hub.brain.assert_not_awaited()
        self.assertEqual(hub.texts, [])

    def test_the_tables_brain_row_prices_the_brain_not_the_estimate(self):
        # 22.2GB priced: with the table's 5.5GB the sum is 27.7GB - inside
        # headroom, no rest. The (wrong) 12GB estimate would say 34.2GB and
        # rest. No rest here is the proof the table row wins.
        hub = _HeadroomStubHub(card_total_gb=32.0)
        run_butler(hub, 20, [30, 30], info={"canvas_mp": 1.0},
                   brain_est_gb=12.0, table=[BRAIN_ROW], brain_kills=[True])
        hub.brain.assert_not_awaited()
        self.assertEqual(hub.texts, [])

    def test_an_unread_card_skips_the_rule_entirely(self):
        # 30.2GB priced with a resident brain - the rule would fire if the
        # card total were known. gpu_watch has not sampled: stay out.
        hub = _HeadroomStubHub(card_total_gb=None)
        run_butler(hub, 28, [34, 34], info={"canvas_mp": 1.0},
                   brain_est_gb=5.5, table=[BRAIN_ROW], brain_kills=[True])
        hub.brain.assert_not_awaited()
        self.assertEqual(hub.texts, [])


class ButlerLogSourceTests(unittest.TestCase):
    """The "butler: X wants ..." line names what priced the job."""

    def _not_fit_run(self, entries):
        hub = _HeadroomStubHub(card_total_gb=32.0, entries=entries)
        _job, out = run_butler(hub, 12, [5, 25, 25], template="identity_edit",
                               info={"canvas_mp": 1.0})
        line = next(l for l in out.splitlines() if "butler: identity_edit" in l)
        return line

    def test_a_ledger_priced_job_says_so(self):
        entries = [_entry("identity_edit", 9.2, canvas_mp=1.0)] * 3
        line = self._not_fit_run(entries)
        self.assertIn("9.2GB act (ledger)", line)

    def test_a_profile_priced_job_says_so(self):
        line = self._not_fit_run([])
        self.assertIn("3.5GB act (profile)", line)


if __name__ == "__main__":
    unittest.main()
