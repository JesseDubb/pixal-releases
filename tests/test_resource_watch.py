"""Brief 9.48 — the butler watches the whole card, not just ComfyUI.

2026-08-25, one afternoon, three misses: identity renders went 27s -> 130s
while ComfyUI held 21GB of a left-behind edit lane (the butler never evicted
it), dwm crept to 2.5GB unseen, and the warmed brain's normal 8.3GB read as
"nothing to reclaim". The fix is a standing watch at price time: a
per-process GPU table (the Windows `\\GPU Process Memory\\Dedicated Usage`
counter sees every process, which nvidia-smi on WDDM does not), a fixed
eviction order - idle lane weights, then the brain, then the desktop is
named but never touched - and a post-hoc tell when a job still ran at the
wall.

LIVE-MACHINE RULE: no ComfyUI, no GPU, no counters - sessions, subprocesses,
tables, clocks and pidfiles are all injected.
"""

import asyncio
import json
import time
import unittest
from contextlib import ExitStack
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


_SPEC = spec_from_file_location(
    "pixal_server_resource_watch", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

GB = 2**30

# A captured `Get-Counter '\GPU Process Memory(*)\Dedicated Usage'` sample set,
# emitted one `instance=cooked` line per engine by the reader.
COUNTER_SAMPLE = (
    "pid_47728_luid_0x00000000_0x0000d3c0_phys_0=22020096\r\n"
    "pid_47728_luid_0x00000000_0x0000d3c0_phys_1=1048576\r\n"
    "pid_1234_luid_0x00000000_0x0000aa11_phys_0=8589934592\r\n"
    "\r\n"
    "not a counter line\r\n"
)

TASKLIST_SAMPLE = (
    '"dwm.exe","47728","Console","1","50,000 K"\r\n'
    '"python.exe","1234","Console","1","8,388,608 K"\r\n'
    '"broken line without a pid"\r\n'
)


class GpuCounterParserTests(unittest.TestCase):
    """The table parser on a captured Get-Counter sample: instances key by
    pid (`pid_<n>_luid_..._phys_<e>`), one line per ENGINE, so a process is
    the SUM of its engines - and junk lines are skipped, never parsed."""

    def test_engines_of_one_pid_sum_and_pids_stay_separate(self):
        usage = server._parse_gpu_counter_samples(COUNTER_SAMPLE)
        self.assertEqual(usage[47728], 22020096 + 1048576)
        self.assertEqual(usage[1234], 8589934592)

    def test_junk_and_blank_lines_are_ignored(self):
        usage = server._parse_gpu_counter_samples(COUNTER_SAMPLE)
        self.assertEqual(len(usage), 2)

    def test_no_samples_is_an_empty_table_not_an_error(self):
        self.assertEqual(server._parse_gpu_counter_samples(""), {})

    def test_tasklist_maps_pid_to_name(self):
        names = server._parse_tasklist_csv(TASKLIST_SAMPLE)
        self.assertEqual(names, {47728: "dwm.exe", 1234: "python.exe"})


class GpuRoleTests(unittest.TestCase):
    """Every row is classified: our ComfyUI, our brain, the desktop
    (dwm+explorer - the ones Clean up -> Reset desktop answers), or other."""

    def test_each_role(self):
        self.assertEqual(server._gpu_role(10, "python.exe", {10}, 20), "comfy")
        self.assertEqual(server._gpu_role(20, "python.exe", {10}, 20), "brain")
        self.assertEqual(server._gpu_role(30, "dwm.exe", {10}, 20), "desktop")
        self.assertEqual(server._gpu_role(31, "explorer.exe", {10}, 20), "desktop")
        self.assertEqual(server._gpu_role(40, "chrome.exe", {10}, 20), "other")

    def test_the_desktop_match_is_case_insensitive(self):
        self.assertEqual(server._gpu_role(30, "DWM.EXE", set(), None), "desktop")


def _table_rows():
    return {111: 21 * GB, 222: 8 * GB + GB // 2, 333: GB + GB // 2,
            444: GB, 555: GB // 2}


def _table_names():
    return {111: "python.exe", 222: "python.exe", 333: "dwm.exe",
            444: "explorer.exe", 555: "chrome.exe"}


class GpuProcessTableTests(unittest.TestCase):
    """Assembly: counter bytes + tasklist names + roles, biggest first, 2s
    cache. An unreadable machine is an empty table, never an error."""

    def setUp(self):
        server._GPU_TABLE.update(ts=0.0, rows=[])

    def _windows(self, usage):
        return patch.object(server, "_nt", return_value=True), \
               patch.object(server, "_gpu_counter_usage", return_value=usage), \
               patch.object(server, "_process_names", return_value=_table_names()), \
               patch.object(server, "_comfy_local_pids", return_value=[111]), \
               patch.object(server, "_llm_state", return_value={"pid": 222})

    def test_rows_carry_pid_name_gb_role_biggest_first(self):
        patches = self._windows(_table_rows())
        with ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            rows = server.gpu_process_table()
        self.assertEqual([r["pid"] for r in rows], [111, 222, 333, 444, 555])
        self.assertEqual([r["role"] for r in rows],
                         ["comfy", "brain", "desktop", "desktop", "other"])
        self.assertAlmostEqual(rows[0]["gb"], 21.0, places=2)
        self.assertAlmostEqual(rows[1]["gb"], 8.5, places=2)

    def test_the_second_read_inside_two_seconds_is_cached(self):
        usage = _table_rows()
        patches = self._windows(usage)
        with ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            first = server.gpu_process_table()
            usage.clear()                      # the counter "went empty"...
            second = server.gpu_process_table()  # ...but the cache answers
        self.assertEqual(first, second)

    def test_an_unreadable_counter_is_an_empty_table(self):
        patches = self._windows(None)
        with ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            self.assertEqual(server.gpu_process_table(), [])

    def test_posix_reads_nvidia_smi_compute_apps(self):
        usage = _table_rows()
        with patch.object(server, "_nt", return_value=False), \
             patch.object(server, "_nvml_process_usage",
                          return_value=(usage, _table_names())), \
             patch.object(server, "_comfy_local_pids", return_value=[111]), \
             patch.object(server, "_llm_state", return_value={"pid": 222}):
            rows = server.gpu_process_table()
        self.assertEqual([r["role"] for r in rows],
                         ["comfy", "brain", "desktop", "desktop", "other"])


class _WatchStubHub:
    """Just enough Hub for ensure_vram and the watch: state + spies, the real
    methods. `calls` records the eviction order as ("flush", free_memory) and
    "brain" entries; `texts` records the lane."""

    queue_remaining = 0

    def __init__(self, resident=None, last_used=None, job_seq=0, critic_hot=False):
        self.jobs = {}
        self.resident_heavies = dict(resident or {})
        self.model_last_used = dict(last_used or {})
        self.job_seq = job_seq
        self.critic_hot = critic_hot
        self.prev_job_free_min = None
        self.calls = []
        self.texts = []
    gpu = None        # 9.76: no card read -> the headroom rule stays out

    def ledger_read(self):   # 9.76: no ledger -> the constants price
        return []

    async def flush_comfy_cache(self, why, unload=True, free_memory=True):
        if unload:
            # the warm trim (unload=False) sends no request - not an eviction
            self.calls.append(("flush", free_memory))
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
               "inputs": {"unet_name": "ZiT\\new.safetensors"}}}
# zimage is unprofiled: 12GB weights + 1GB act + 2GB floor = 15GB need.


class EvictionOrderTests(unittest.TestCase):
    """The fixed order on a fake table + fake residency: idle lane weights
    first (soft unload, never free_memory), the brain only when that was not
    enough, the desktop named and never touched."""

    def run_butler(self, hub, free_reads, brain_est_gb=0, brain_kills=None,
                   table=None, gpu_free_gb=20):
        brain_kills = brain_kills if brain_kills is not None else []

        async def _kill():
            hub.calls.append("brain")
            return brain_kills.pop(0) if brain_kills else False

        with ExitStack() as st:
            st.enter_context(patch.object(
                server, "_weight_file_bytes", return_value=12 * GB))
            st.enter_context(patch.object(
                server, "comfy_vram_free_bytes",
                AsyncMock(side_effect=[f * GB for f in free_reads])))
            st.enter_context(patch.object(
                server, "gpu_free_bytes", return_value=gpu_free_gb * GB))
            st.enter_context(patch.object(
                server, "gpu_hogs", return_value=[]))
            st.enter_context(patch.object(
                server, "ram_free_bytes", return_value=32 * GB))
            st.enter_context(patch.object(
                server, "gpu_process_table", return_value=table or []))
            st.enter_context(patch.object(
                server, "brain_vram_estimate",
                return_value=int(brain_est_gb * GB)))
            hub.brain = st.enter_context(patch.object(
                server, "free_brain_vram", AsyncMock(side_effect=_kill)))
            st.enter_context(patch.object(
                server.asyncio, "sleep", AsyncMock()))
            job = {"id": "w1", "cid": "c"}
            asyncio.run(hub.ensure_vram("zimage", dict(GRAPH), job))
        return job


class IdleLaneFirstTests(EvictionOrderTests):
    """The 16:19 incident: a left-behind edit lane is evicted before anything
    else moves, toasted, and the render fits without the brain or the flush."""

    def hub_with_idle_edit_lane(self, edit_seq=1, job_seq=3):
        return _WatchStubHub(
            resident={"FireRed\\edit.safetensors": 21 * GB},
            last_used={"FireRed\\edit.safetensors": (edit_seq, "identity_edit", 21 * GB)},
            job_seq=job_seq)

    def test_the_idle_lane_is_freed_and_the_brain_is_never_asked(self):
        hub = self.hub_with_idle_edit_lane()
        job = self.run_butler(hub, [10, 25], brain_est_gb=6,
                              table=[{"pid": 10, "name": "python.exe",
                                      "gb": 21.0, "role": "comfy"}])
        self.assertEqual(hub.calls, [("flush", False)])   # soft, never free_memory
        hub.brain.assert_not_awaited()
        self.assertEqual(hub.texts, ["*freed 21 GB of idle edit weights*"])
        self.assertEqual(hub.resident_heavies,
                         {"ZiT\\new.safetensors": 12 * GB})
        self.assertTrue(job.get("model_switch"))          # cleared, then loads

    def test_the_brain_rests_only_when_the_idle_lane_was_not_enough(self):
        hub = self.hub_with_idle_edit_lane()
        self.run_butler(hub, [10, 12, 18], brain_est_gb=6, brain_kills=[True],
                        table=[{"pid": 10, "name": "python.exe",
                                "gb": 21.0, "role": "comfy"}])
        self.assertEqual(hub.calls, [("flush", False), "brain"])  # the order
        self.assertEqual(hub.texts,
                         ["*freed 21 GB of idle edit weights*",
                          "*brain rested for the render (6.0 GB)*"])

    def test_a_lane_used_by_the_last_two_jobs_is_still_in_play(self):
        # N=2: the edit lane ran 2 jobs ago - ping-ponging lanes must never
        # evict each other, so this falls through to the plain flush.
        hub = self.hub_with_idle_edit_lane(edit_seq=2, job_seq=2)
        self.run_butler(hub, [10], table=[])
        self.assertNotIn(("flush", False), hub.calls)
        self.assertIn(("flush", True), hub.calls)          # the hard flush ran
        hub.brain.assert_not_awaited()                     # no brain to rest
        self.assertEqual(len(hub.texts), 1)
        self.assertTrue(hub.texts[0].startswith("*making room"))

    def test_the_desktop_is_named_but_never_touched(self):
        hub = self.hub_with_idle_edit_lane()
        self.run_butler(hub, [10, 25], brain_est_gb=6, table=[
            {"pid": 10, "name": "python.exe", "gb": 21.0, "role": "comfy"},
            {"pid": 20, "name": "dwm.exe", "gb": 1.7, "role": "desktop"},
            {"pid": 21, "name": "explorer.exe", "gb": 0.9, "role": "desktop"}])
        self.assertEqual(hub.calls, [("flush", False)])    # no desktop action
        self.assertEqual(
            hub.texts[-1],
            "*desktop holds 2.6 GB - Clean up → Reset desktop*")

    def test_a_quiet_desktop_gets_no_line(self):
        hub = self.hub_with_idle_edit_lane()
        self.run_butler(hub, [10, 25], brain_est_gb=6, table=[
            {"pid": 10, "name": "python.exe", "gb": 21.0, "role": "comfy"},
            {"pid": 20, "name": "dwm.exe", "gb": 1.0, "role": "desktop"}])
        self.assertEqual(hub.texts, ["*freed 21 GB of idle edit weights*"])


class WarmRerunAtTheWallTests(EvictionOrderTests):
    """The steady state of the incident: the current stack is resident
    (hot == weights), yet the trim cannot make activation headroom because an
    idle lane holds the card. The watch evicts the lane and the rerun pays a
    reload instead of paging (41-54s measured against 130s)."""

    def warm_hub(self, with_idle_lane=True):
        last_used = {"ZiT\\new.safetensors": (3, "zimage", 12 * GB)}
        if with_idle_lane:
            last_used["FireRed\\edit.safetensors"] = (1, "identity_edit", 21 * GB)
        return _WatchStubHub(
            resident={"ZiT\\new.safetensors": 12 * GB},
            last_used=last_used, job_seq=3)

    def test_the_idle_lane_goes_and_the_own_stack_reloads(self):
        hub = self.warm_hub()
        # comfy reads 2GB (pricing: < act+floor, so the warm path), the trim
        # settles at 1GB (driver), and the post-eviction read is 25GB.
        with patch.object(server, "VRAM_TRIM_DEADLINE", 0.01):
            job = self.run_butler(
                hub, [2, 25], brain_est_gb=0, gpu_free_gb=1,
                table=[{"pid": 10, "name": "python.exe",
                        "gb": 30.0, "role": "comfy"}])
        self.assertEqual(hub.calls, [("flush", False)])
        self.assertEqual(hub.texts, ["*freed 21 GB of idle edit weights*"])
        self.assertEqual(hub.resident_heavies,
                         {"ZiT\\new.safetensors": 12 * GB})
        self.assertTrue(job.get("model_switch"))

    def test_nothing_idle_rest_the_brain_and_keep_the_stack(self):
        hub = self.warm_hub(with_idle_lane=False)
        with patch.object(server, "VRAM_TRIM_DEADLINE", 0.01):
            self.run_butler(hub, [2, 10], brain_est_gb=6, brain_kills=[True],
                            gpu_free_gb=1, table=[])
        self.assertEqual(hub.calls, ["brain"])
        self.assertEqual(hub.texts, ["*brain rested for the render (6.0 GB)*"])
        self.assertEqual(hub.resident_heavies,     # the warm stack stayed
                         {"ZiT\\new.safetensors": 12 * GB})


class GuardEvictsTheIdleLaneTests(EvictionOrderTests):
    """The 9.35 near-miss guard tried brain-then-pool-trim; the pool trim
    cannot touch a resident lane, so a proven near-miss now evicts the idle
    lane FIRST - the steady state of the incident, where the brain was
    already gone and every render paged anyway."""

    def test_a_near_miss_evicts_the_idle_lane_before_the_brain(self):
        hub = _WatchStubHub(
            resident={"ZiT\\new.safetensors": 12 * GB},
            last_used={"ZiT\\new.safetensors": (3, "zimage", 12 * GB),
                       "FireRed\\edit.safetensors": (1, "identity_edit", 21 * GB)},
            job_seq=3)
        hub.prev_job_free_min = int(0.7 * GB)      # the last job ran at the wall
        # comfy reads 8GB: the job fits by price (8 >= 1 + 2), so the guard -
        # not the fall-through - is what acts.
        self.run_butler(hub, [8], brain_est_gb=6, gpu_free_gb=1, table=[])
        self.assertEqual(hub.calls, [("flush", False)])
        hub.brain.assert_not_awaited()
        self.assertEqual(hub.texts, ["*freed 21 GB of idle edit weights*"])
        self.assertEqual(hub.resident_heavies,
                         {"ZiT\\new.safetensors": 12 * GB})


class FullCardTellTests(unittest.TestCase):
    """The post-hoc tell: a job whose free_min still came in under 1GB gets a
    job-done line saying it rendered at a full card, N seconds slower than
    the lane's median from history."""

    class _FinalizeHub:
        def __init__(self):
            self.texts = []
            self.broadcasts = []
            self.jobs = {}
            self.convo = None

        def broadcast(self, **kw):
            self.broadcasts.append(kw)
            if kw.get("type") == "text":
                self.texts.append(kw.get("text"))

        finalize = server.Hub.finalize
        ledger_append = server.Hub.ledger_append
        ledger_read = server.Hub.ledger_read
        lane_median_elapsed = server.Hub.lane_median_elapsed

    PRIORS = ({"id": "p1", "template": "zimage", "elapsed": 27.0},
              {"id": "p2", "template": "zimage", "elapsed": 28.0},
              {"id": "p3", "template": "zimage", "elapsed": 27.5})

    def run_finalize(self, priors=PRIORS, free_min=int(0.7 * GB), ran_for=130.0):
        hub = self._FinalizeHub()
        with TemporaryDirectory() as td:
            ledger = Path(td) / "history.jsonl"
            ledger.write_text("".join(json.dumps(p) + "\n" for p in priors),
                              encoding="utf-8")
            job = {"id": "cur", "cid": "c", "template": "zimage", "scene": "s",
                   "full_prompt": "", "seed": 1, "count": 1, "spec": {},
                   "info": None, "images": [{"filename": "x.png"}],
                   "started": time.time() - ran_for, "texts": [],
                   "error": None, "_vram_free_min": free_min}
            with patch.object(server, "LEDGER", ledger):
                hub.finalize(job)
        return hub, job

    def test_a_slow_job_at_the_wall_is_told(self):
        hub, job = self.run_finalize()
        tells = [t for t in hub.texts if "rendered at a full card" in t]
        self.assertEqual(len(tells), 1)
        seconds = int(tells[0].split(" - ")[1].split(" ")[0])
        # ~130s against a 27.5s median: N ~= 103.
        self.assertTrue(100 <= seconds <= 105)
        self.assertEqual(tells[0],
                         f"*rendered at a full card - {seconds} s slower "
                         "than usual*")

    def test_a_comfortable_free_min_says_nothing(self):
        hub, _ = self.run_finalize(free_min=2 * GB)
        self.assertEqual(hub.texts, [])

    def test_an_unsampled_job_says_nothing(self):
        hub, _ = self.run_finalize(free_min=None)
        self.assertEqual(hub.texts, [])

    def test_a_job_at_its_usual_pace_says_nothing(self):
        hub, _ = self.run_finalize(ran_for=27.4)
        self.assertEqual(hub.texts, [])

    def test_no_history_is_no_baseline_and_no_tell(self):
        hub, _ = self.run_finalize(priors=())
        self.assertEqual(hub.texts, [])


class VramTableRouteTests(unittest.IsolatedAsyncioTestCase):
    """GET /api/vram/table serves the same table the watch acts on - 9.46's
    section and the telemetry strip read it from here."""

    async def test_the_route_returns_the_rows(self):
        rows = [{"pid": 111, "name": "python.exe", "gb": 21.0, "role": "comfy"}]
        with patch.object(server, "gpu_process_table", return_value=rows):
            resp = await server.vram_table(SimpleNamespace())
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(resp.text), rows)


if __name__ == "__main__":
    unittest.main()
