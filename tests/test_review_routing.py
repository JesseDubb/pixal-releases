"""Brief 9.22: the Review button stops carrying the download Animate lost.

9c089d9 kept the LOOK stage from submitting the ComfyUI critic when its
weights are not on disk; the Review button kept the same hole - a click on a
machine whose reviewer was never downloaded pulled ~16GB from HuggingFace
behind a "reading the shot" spinner, with no explanation. These tests pin the
rebuilt routing: the review and the look consult ONE shared guard, a missing
reviewer is named (with its size and the way out) instead of failing
silently, the local-critic fallback survives for the blind-brain case it was
kept for, and review() never raises.
"""
import asyncio
import json
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


_SPEC = spec_from_file_location(
    "pixal_server_review_routing_tests",
    Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


CRITIC = "Huihui-Qwen3-VL-8B-Instruct-abliterated"
BLIND = ("no projector sits beside gemma-3-12b.gguf, and the shipped "
         "projector only fits the Qwen3-VL 4B brain")
REVIEW_TEXT = ("LOOKS: a red mug on a counter.\nWORKS: the rim light.\n"
               "PROBLEMS: the handle melts.\nFIX: reroll with a plainer mug")


def cfg(critic=CRITIC):
    return {"llm": {"base_url": server.LOCAL_LLM_URL,
                    "local_model": "C:/brains/qwen3-vl-4b-heretic-Q8_0.gguf"},
            "critic": {"model": critic}}


class _Req:
    """Just enough aiohttp request for review(): an awaitable json()."""
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


async def _settled(resp_coro):
    """Await the handler, then every task it spawned, so the route the click
    took is fully played out before assertions run."""
    resp = await resp_coro
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)
    return resp


def _review(root, *, read, models=(), submit=None, critic=CRITIC, entry=True,
            scene=None, recipe=None):
    """Drive /api/review - handler AND its spawned task - with every outside
    fact faked."""
    root = Path(root)
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "output" / "shot.png").write_bytes(b"\x89PNG fake")
    mocks = SimpleNamespace(
        submit=submit or AsyncMock(return_value={"id": "job1"}),
        broadcast=Mock())
    ledger = ([{"id": "abc123", "scene": scene, "template": recipe,
                "images": [{"filename": "shot.png",
                                            "subfolder": ""}]}]
              if entry else [])
    with patch.object(server, "CDIR", root), \
         patch.object(server, "load_config", return_value=cfg(critic)), \
         patch.object(server, "stage_critic_input",
                      side_effect=lambda src, name: name), \
         patch.object(server, "brain_vl_read", read), \
         patch.object(server, "installed_vl_models",
                      return_value=list(models)), \
         patch.object(server.HUB, "ledger_read", return_value=ledger), \
         patch.object(server.HUB, "submit", mocks.submit), \
         patch.object(server.HUB, "broadcast", mocks.broadcast), \
         patch.object(type(server.HUB), "convo", new=property(lambda self: None)):
        resp = asyncio.run(_settled(server.review(
            _Req({"id": "abc123", "cid": "cid9"}))))
    return resp, mocks


def _lane_texts(broadcast):
    return [c.kwargs.get("text", "") for c in broadcast.call_args_list
            if c.kwargs.get("type") == "text"]


def _types(broadcast):
    return [c.kwargs.get("type") for c in broadcast.call_args_list]


class MissingReviewerWeights(unittest.TestCase):
    """The reviewer is not on disk: no silent 16GB pull, and no dead button."""

    def test_vl_review_is_not_submitted(self):
        read = AsyncMock(return_value=(None, BLIND))
        with tempfile.TemporaryDirectory() as td:
            resp, mocks = _review(td, read=read, models=["Some-Other-VL"])
        self.assertEqual(resp.status, 200)
        mocks.submit.assert_not_awaited()      # no first-run fetch, ever

    def test_the_user_is_told_what_is_missing_and_the_way_out(self):
        read = AsyncMock(return_value=(None, BLIND))
        with tempfile.TemporaryDirectory() as td:
            resp, mocks = _review(td, read=read, models=[])
        lane = " ".join(_lane_texts(mocks.broadcast))
        self.assertIn(CRITIC, lane)                 # WHICH reviewer is missing
        self.assertIn("~16 GB", lane)               # roughly how big
        self.assertIn(BLIND, lane)                  # the brain's own reason
        self.assertIn("Settings", lane)             # the way out
        self.assertIn("download", lane)
        # the "reading the shot" spinner must end with the answer
        self.assertIn("thinkingdone", _types(mocks.broadcast))


class LocalReviewerFallback(unittest.TestCase):
    """The case the fallback was kept for: weights on disk, blind brain."""

    def test_vl_review_is_submitted(self):
        read = AsyncMock(return_value=(None, BLIND))
        with tempfile.TemporaryDirectory() as td:
            resp, mocks = _review(td, read=read, models=[CRITIC])
        self.assertEqual(resp.status, 200)
        mocks.submit.assert_awaited_once()
        args = mocks.submit.await_args.args
        self.assertEqual((args[1], args[2]), ("chat", "vl_review"))
        self.assertEqual(args[4], {"image": "pixal_review_abc123.png",
                                   "brief": None, "recipe": None})
        self.assertEqual(mocks.submit.await_args.kwargs.get("parent"), "abc123")


class SightedBrainReview(unittest.TestCase):

    def test_single_line_vision_answers_keep_the_actionable_fix(self):
        read = AsyncMock(return_value=(" ".join(REVIEW_TEXT.split()), None))
        with tempfile.TemporaryDirectory() as td:
            _, mocks = _review(td, read=read)
        reviews = [c.kwargs for c in mocks.broadcast.call_args_list
                   if c.kwargs.get("type") == "review"]
        self.assertEqual(reviews[0]["fix"], "reroll with a plainer mug")
        self.assertEqual(reviews[0]["text"], REVIEW_TEXT)

    def test_both_paths_receive_the_same_selected_render_brief(self):
        scene = "Woodcut illustration of a still fox; flat indigo and cream."
        questions = []
        for answer in ((REVIEW_TEXT, None), (None, BLIND)):
            read = AsyncMock(return_value=answer)
            with tempfile.TemporaryDirectory() as td:
                _, mocks = _review(td, read=read, models=[CRITIC],
                                   scene=scene, recipe="fantasy")
            question = read.await_args.args[1]
            questions.append(question)
            self.assertIn(scene, question)
            if answer[0] is None:
                params = mocks.submit.await_args.args[4]
                with patch.object(server, "load_config", return_value=cfg()):
                    graph, _, _ = server.build_review("review of #abc123", 17, **params)
                self.assertEqual(graph["2"]["inputs"]["custom_prompt"], question)
        self.assertEqual(questions[0], questions[1])

    def test_partial_answer_never_becomes_an_actionable_review(self):
        read = AsyncMock(return_value=("LOOKS: a mug. FIX: add neon.", None))
        with tempfile.TemporaryDirectory() as td:
            _, mocks = _review(td, read=read, models=[CRITIC])
        self.assertNotIn("review", _types(mocks.broadcast))
        self.assertIn("thinkingdone", _types(mocks.broadcast))
        self.assertTrue(any("incomplete" in text for text in _lane_texts(mocks.broadcast)))
        mocks.submit.assert_not_awaited()

    def test_clean_review_does_not_offer_a_pointless_reroll(self):
        read = AsyncMock(return_value=(
            "LOOKS: a still fox. WORKS: composition. PROBLEMS: none. FIX: none.", None))
        with tempfile.TemporaryDirectory() as td:
            _, mocks = _review(td, read=read)
        reviews = [c.kwargs for c in mocks.broadcast.call_args_list
                   if c.kwargs.get("type") == "review"]
        self.assertEqual(len(reviews), 1)
        self.assertIsNone(reviews[0]["fix"])

    def test_a_sighted_brain_answers_and_comfyui_is_never_submitted(self):
        read = AsyncMock(return_value=(REVIEW_TEXT, None))
        with tempfile.TemporaryDirectory() as td:
            resp, mocks = _review(td, read=read, models=[])   # no critic either
        self.assertEqual(resp.status, 200)
        mocks.submit.assert_not_awaited()
        reviews = [c for c in mocks.broadcast.call_args_list
                   if c.kwargs.get("type") == "review"]
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].kwargs["text"], REVIEW_TEXT)
        self.assertEqual(reviews[0].kwargs["fix"], "reroll with a plainer mug")
        self.assertEqual(reviews[0].kwargs["parent"], "abc123")


class OneGuardSharedWithTheLook(unittest.TestCase):
    """The review and the look consult the SAME callable. It is patched here,
    so two implementations cannot merely be agreeing today."""

    def test_both_paths_ask_the_same_callable(self):
        guard = Mock(return_value=(CRITIC, True))       # weights "on disk"
        read = AsyncMock(return_value=(None, BLIND))    # brain declines both
        submit = AsyncMock(return_value={"finalized": True,
                                         "texts": ["a red mug"]})
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "frame.png").write_bytes(b"\x89PNG fake")
            (root / "output").mkdir()
            (root / "output" / "shot.png").write_bytes(b"\x89PNG fake")
            ledger = [{"id": "abc123", "images": [{"filename": "shot.png",
                                                   "subfolder": ""}]}]
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "load_config", return_value=cfg()), \
                 patch.object(server, "stage_critic_input",
                              side_effect=lambda src, name: name), \
                 patch.object(server, "brain_vl_read", read), \
                 patch.object(server, "installed_vl_models", return_value=[]), \
                 patch.object(server, "critic_weights", guard), \
                 patch.object(server.HUB, "ledger_read", return_value=ledger), \
                 patch.object(server.HUB, "submit", submit), \
                 patch.object(server.HUB, "broadcast", Mock()), \
                 patch.object(type(server.HUB), "convo",
                              new=property(lambda self: None)):
                # installed_vl_models says EMPTY: any path reaching ComfyUI
                # did so on the guard's word, not on a check of its own.
                asyncio.run(server.frame_inventory("frame.png", "9", "cid9"))
                asyncio.run(_settled(server.review(
                    _Req({"id": "abc123", "cid": "cid9"}))))
        self.assertEqual(guard.call_count, 2)       # look AND review
        self.assertEqual(submit.await_count, 2)     # the guard's verdict drove both
        templates = sorted(c.args[2] for c in submit.await_args_list)
        self.assertEqual(templates, ["vl_look", "vl_review"])


class ReviewNeverDies(unittest.TestCase):
    """A click that already got its 200 must never die silently."""

    def test_a_raising_brain_still_reaches_a_local_critic(self):
        # brain_vl_read is built to return its reasons; a raise is shaped like
        # one, so the fallback it would have named still gets its chance.
        read = AsyncMock(side_effect=RuntimeError("boom"))
        with tempfile.TemporaryDirectory() as td:
            resp, mocks = _review(td, read=read, models=[CRITIC])
        self.assertEqual(resp.status, 200)
        mocks.submit.assert_awaited_once()
        self.assertEqual(mocks.submit.await_args.args[2], "vl_review")

    def test_a_raising_brain_with_no_critic_is_a_named_failure(self):
        read = AsyncMock(side_effect=RuntimeError("boom"))
        with tempfile.TemporaryDirectory() as td:
            resp, mocks = _review(td, read=read, models=[])
        self.assertEqual(resp.status, 200)
        mocks.submit.assert_not_awaited()
        lane = " ".join(_lane_texts(mocks.broadcast))
        self.assertIn("boom", lane)
        self.assertIn(CRITIC, lane)
        self.assertIn("thinkingdone", _types(mocks.broadcast))

    def test_a_refused_submit_is_a_named_failure(self):
        read = AsyncMock(return_value=(None, BLIND))
        submit = AsyncMock(side_effect=ConnectionError("comfy is down"))
        with tempfile.TemporaryDirectory() as td:
            resp, mocks = _review(td, read=read, models=[CRITIC], submit=submit)
        self.assertEqual(resp.status, 200)
        lane = " ".join(_lane_texts(mocks.broadcast))
        self.assertIn("failed", lane)
        self.assertIn("thinkingdone", _types(mocks.broadcast))

    def test_a_missing_entry_is_a_404_not_a_raise(self):
        read = AsyncMock()
        with tempfile.TemporaryDirectory() as td:
            resp, _ = _review(td, read=read, entry=False)
        self.assertEqual(resp.status, 404)
        self.assertEqual(json.loads(resp.text)["ok"], False)
        read.assert_not_awaited()


class DownloadSizeInTheMessage(unittest.TestCase):
    """The warning names roughly how big the missing reviewer is."""

    def test_rough_fp16_size_read_off_the_name(self):
        self.assertEqual(server.vl_download_gb(CRITIC), 16)            # 8B
        self.assertEqual(server.vl_download_gb("Qwen3-VL-4B-Instruct"), 8)
        self.assertEqual(server.vl_download_gb("Qwen2.5-VL-32B-Instruct"), 64)
        self.assertIsNone(server.vl_download_gb("JoyCaption-Beta-One"))


if __name__ == "__main__":
    unittest.main()
