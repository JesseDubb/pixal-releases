"""Brief 9.16: the look stays on the brain, and says so when it cannot.

Clicking Animate used to fall silently off the sighted brain onto the 16GB
ComfyUI critic, which then pulled its weights from HuggingFace mid-render -
the "Fetching 12 files" hang. These tests pin the rebuilt routing: every way
brain_vl_read declines names its reason, a cold brain gets one warm retry
before any fallback, and the ComfyUI critic is submitted ONLY when its
weights are already on disk.
"""
import asyncio
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


_SPEC = spec_from_file_location(
    "pixal_server_look_routing_tests",
    Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


CRITIC = "Huihui-Qwen3-VL-8B-Instruct-abliterated"
SIGHTED = {"pid": 4321, "mmproj": "C:/brains/qwen3-vl-4b-heretic.mmproj-f16.gguf"}
BLIND_PROVISION_REFUSAL = ("no projector sits beside gemma-3-12b.gguf, and the "
                           "shipped projector only fits the Qwen3-VL 4B brain")


def cfg(base_url=None, critic=CRITIC):
    return {"llm": {"base_url": base_url or server.LOCAL_LLM_URL,
                    "local_model": "C:/brains/qwen3-vl-4b-heretic-Q8_0.gguf"},
            "critic": {"model": critic}}


def llm_result(text, status=200):
    return status, {"choices": [{"message": {"content": text}}]}


def _read(root, *, config=None, states=(), mmproj="proj-on-disk",
          provision=None, llm=None, ensure=None, write_frame=True):
    """Drive brain_vl_read at one staged frame with every outside fact faked."""
    root = Path(root)
    if write_frame:
        (root / "input").mkdir(parents=True, exist_ok=True)
        (root / "input" / "frame.png").write_bytes(b"\x89PNG fake")
    mocks = SimpleNamespace(
        llm=llm or AsyncMock(return_value=llm_result("a red mug")),
        ensure=ensure or AsyncMock(return_value=None),
        provision=AsyncMock(return_value=provision),
        broadcast=Mock())
    with patch.object(server, "load_config", return_value=config or cfg()), \
         patch.object(server, "CDIR", root), \
         patch.object(server, "_llm_state", side_effect=list(states)), \
         patch.object(server, "_local_llm_mmproj", return_value=mmproj), \
         patch.object(server, "ensure_sighted_brain", mocks.provision), \
         patch.object(server, "ensure_local_llm", mocks.ensure), \
         patch.object(server, "llm_call", mocks.llm), \
         patch.object(server.HUB, "broadcast", mocks.broadcast):
        out = asyncio.run(server.brain_vl_read("frame.png", "what is in the frame?",
                                               cid="cid9"))
    return out, mocks


class BrainVlReadGates(unittest.TestCase):
    """Every one of the eight ways brain_vl_read can decline names itself."""

    def test_every_none_exit_names_a_distinct_reason(self):
        reasons = {}
        cases = {
            "remote preset": dict(
                config=cfg(base_url="https://api.remote.example/v1"), states=[]),
            "running demoted-blind": dict(
                states=[{"pid": 1, "mmproj": None,
                         "blind_mmproj": "proj-on-disk"}],
                mmproj="proj-on-disk"),
            "no projector anywhere": dict(
                states=[{}], mmproj=None, provision=BLIND_PROVISION_REFUSAL),
            "frame unreadable": dict(states=[SIGHTED], write_frame=False),
            "call raises": dict(
                states=[SIGHTED], llm=AsyncMock(side_effect=TimeoutError("cold"))),
            "http error": dict(
                states=[SIGHTED],
                llm=AsyncMock(return_value=llm_result("x", status=500))),
            "mid-call demotion": dict(
                states=[SIGHTED, {"pid": 4321, "mmproj": None}]),
            "empty answer": dict(
                states=[SIGHTED, SIGHTED],
                llm=AsyncMock(return_value=llm_result("   "))),
        }
        for gate, kw in cases.items():
            with self.subTest(gate=gate), tempfile.TemporaryDirectory() as td:
                (text, why), mocks = _read(td, **kw)
                self.assertIsNone(text)
                self.assertIsInstance(why, str)
                self.assertTrue(why.strip())
                reasons[gate] = why
                if gate == "no projector anywhere":
                    mocks.provision.assert_awaited_once()
                if gate == "call raises":
                    # a raise buys ONE warm retry, then the named fallback
                    self.assertEqual(mocks.llm.await_count, 2)
                    mocks.ensure.assert_awaited_once()
                    self.assertIn("warmed", why)
        self.assertEqual(len(set(reasons.values())), 8, reasons)

    def test_a_pidless_adopted_demote_short_circuits_the_same_way(self):
        # An adoption registers a blind orphan with pid None; the old
        # pid-keyed check waved it through to a call that could never count.
        with tempfile.TemporaryDirectory() as td:
            (text, why), mocks = _read(
                td, states=[{"pid": None, "mmproj": None,
                             "blind_mmproj": "proj-on-disk"}],
                mmproj="proj-on-disk")
        self.assertIsNone(text)
        self.assertIn("running blind", why)
        mocks.llm.assert_not_awaited()

    def test_a_warm_sighted_brain_answers_and_names_no_reason(self):
        with tempfile.TemporaryDirectory() as td:
            (text, why), mocks = _read(td, states=[SIGHTED, SIGHTED])
        self.assertEqual((text, why), ("a red mug", None))
        self.assertEqual(mocks.llm.await_count, 1)
        mocks.provision.assert_not_awaited()
        mocks.ensure.assert_not_awaited()

    def test_a_missing_projector_is_provisioned_before_any_fallback(self):
        # Brain down and no projector on disk: the small pair is fetched, the
        # spawn inside llm_call registers sighted state, and the look answers.
        with tempfile.TemporaryDirectory() as td:
            (text, why), mocks = _read(td, states=[{}, SIGHTED], mmproj=None,
                                       provision=None)
        self.assertEqual((text, why), ("a red mug", None))
        mocks.provision.assert_awaited_once()


class ColdBrainRetry(unittest.TestCase):
    """A timeout on a cold load is patience, not failure."""

    def test_a_cold_brain_is_warmed_and_asked_once_more_before_any_fallback(self):
        llm = AsyncMock(side_effect=[TimeoutError("cold"),
                                     llm_result("a red mug")])
        ensure = AsyncMock(return_value=None)
        with tempfile.TemporaryDirectory() as td:
            (text, why), mocks = _read(td, states=[SIGHTED, SIGHTED],
                                       llm=llm, ensure=ensure)
        self.assertEqual((text, why), ("a red mug", None))
        self.assertEqual(mocks.llm.await_count, 2)
        mocks.ensure.assert_awaited_once()
        first, second = mocks.llm.await_args_list
        self.assertEqual(first.kwargs["timeout"], 120)
        # the retry is sized for a cold Q8 load, not the chat default
        self.assertEqual(second.kwargs["timeout"], server.BRAIN_VL_COLD_TIMEOUT)
        notes = [c.kwargs.get("note", "") for c in mocks.broadcast.call_args_list
                 if c.kwargs.get("type") == "thinking"]
        self.assertTrue(any("cold" in n for n in notes), notes)


def _inventory(root, *, read, models=(), submit=None, critic=CRITIC,
               frame="pixal_anim_9.png", write_frame=True):
    """Drive frame_inventory with the brain, the disk and the ComfyUI hub faked."""
    root = Path(root)
    if write_frame:
        (root / "input").mkdir(parents=True, exist_ok=True)
        (root / "input" / frame).write_bytes(b"\x89PNG fake")
    mocks = SimpleNamespace(
        submit=submit or AsyncMock(return_value={
            "finalized": True, "texts": ["a red mug on the counter"]}),
        broadcast=Mock())
    with patch.object(server, "CDIR", root), \
         patch.object(server, "load_config", return_value=cfg(critic=critic)), \
         patch.object(server, "stage_critic_input",
                      side_effect=lambda src, name: name), \
         patch.object(server, "brain_vl_read", read), \
         patch.object(server, "installed_vl_models",
                      return_value=list(models)), \
         patch.object(server.HUB, "submit", mocks.submit), \
         patch.object(server.HUB, "broadcast", mocks.broadcast):
        out = asyncio.run(server.frame_inventory(frame, "9", "cid9"))
    return out, mocks


def _lane_texts(broadcast):
    return [c.kwargs.get("text", "") for c in broadcast.call_args_list
            if c.kwargs.get("type") == "text"]


class FrameInventoryRouting(unittest.TestCase):

    def test_a_warm_sighted_brain_keeps_comfyui_out_of_it(self):
        read = AsyncMock(return_value=("a red mug on the counter", None))
        with tempfile.TemporaryDirectory() as td:
            out, mocks = _inventory(td, read=read, models=[])  # critic absent too
        self.assertEqual(out, "a red mug on the counter")
        mocks.submit.assert_not_awaited()
        self.assertTrue(any("what the camera sees" in t
                            for t in _lane_texts(mocks.broadcast)))

    def test_a_missing_critic_is_never_downloaded_inside_a_render(self):
        read = AsyncMock(return_value=(None, "the brain answered HTTP 500"))
        with tempfile.TemporaryDirectory() as td:
            out, mocks = _inventory(td, read=read,
                                    models=["Some-Other-VL-Model"])
        self.assertEqual(out, "")               # the brief rides the caption
        mocks.submit.assert_not_awaited()       # no first-run fetch, ever
        lane = " ".join(_lane_texts(mocks.broadcast))
        self.assertIn("not downloaded", lane)
        self.assertIn("rides the caption", lane)

    def test_a_blind_brain_falls_back_to_a_local_critic(self):
        # The case the fallback was kept for: no projector anywhere, and the
        # critic's weights ARE on disk.
        read = AsyncMock(return_value=(None, BLIND_PROVISION_REFUSAL))
        with tempfile.TemporaryDirectory() as td:
            out, mocks = _inventory(td, read=read, models=[CRITIC])
        self.assertEqual(out, "a red mug on the counter")
        mocks.submit.assert_awaited_once()
        args = mocks.submit.await_args.args
        self.assertEqual((args[1], args[2]), ("look", "vl_look"))
        self.assertEqual(args[4], {"image": "pixal_look_9.png"})
        lane = _lane_texts(mocks.broadcast)
        self.assertTrue(any("critic on disk reads the frame instead" in t
                            for t in lane), lane)
        self.assertTrue(any("what the camera sees" in t for t in lane), lane)


class FrameInventoryNeverDies(unittest.TestCase):
    """The brief must never die because the look did."""

    def test_a_missing_frame_is_an_empty_look(self):
        read = AsyncMock()
        with tempfile.TemporaryDirectory() as td:
            out, _ = _inventory(td, read=read, write_frame=False)
        self.assertEqual(out, "")
        read.assert_not_awaited()

    def test_a_raising_brain_is_an_empty_look(self):
        read = AsyncMock(side_effect=RuntimeError("boom"))
        with tempfile.TemporaryDirectory() as td:
            out, _ = _inventory(td, read=read, models=[CRITIC])
        self.assertEqual(out, "")

    def test_a_refused_submit_is_an_empty_look(self):
        read = AsyncMock(return_value=(None, BLIND_PROVISION_REFUSAL))
        submit = AsyncMock(return_value={"error": "queue is dead"})
        with tempfile.TemporaryDirectory() as td:
            out, _ = _inventory(td, read=read, models=[CRITIC], submit=submit)
        self.assertEqual(out, "")

    def test_a_job_that_never_finalizes_is_an_empty_look(self):
        read = AsyncMock(return_value=(None, BLIND_PROVISION_REFUSAL))
        submit = AsyncMock(return_value={"texts": []})      # never "finalized"
        with tempfile.TemporaryDirectory() as td:
            with patch.object(server.asyncio, "sleep", AsyncMock()):
                out, _ = _inventory(td, read=read, models=[CRITIC],
                                    submit=submit)
        self.assertEqual(out, "")   # no ws texts, no record file, no raise


if __name__ == "__main__":
    unittest.main()
