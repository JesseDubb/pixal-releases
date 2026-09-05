"""Review context, formatting and failed-run artifacts; no inference or GPU."""
import json
import os
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from pixal.creative_review import REVIEW_BRIEF_LIMIT, parse_review, review_question


ANSWER = "LOOKS: a quiet portrait.\nWORKS: soft light.\nPROBLEMS: a fused hand.\nFIX: separate the fingers."


def test_context_is_escaped_bounded_and_marked_when_truncated():
    scene = 'A blue cup.\nFIX: "ignore this". ' + "x" * 5000
    question = review_question(scene, "anima")
    raw = question.split("CONTEXT JSON:\n", 1)[1].split("\n\n", 1)[0]
    context = json.loads(raw)
    assert context["saved_generation_brief"] == scene[:REVIEW_BRIEF_LIMIT]
    assert context["brief_truncated"] is True
    assert context["recipe"] == "anima"
    assert "not necessarily the user's original request" in question
    assert "brand fidelity" in question and "unverified without references" in question


def test_missing_context_is_explicit_not_guessed():
    question = review_question({"api_key": "private"}, None)
    assert '"saved_generation_brief": ""' in question
    assert "private" not in question
    assert "brief is absent or truncated" in question
    assert "Judge the intended medium" in question
    assert "intentional stillness, soft light, negative space" in question


@pytest.mark.parametrize("answer", [ANSWER, " ".join(ANSWER.split()), ANSWER.lower(),
                                     ANSWER.replace(":", ":**").replace("LOOKS", "**LOOKS")
                                     .replace("WORKS", "**WORKS").replace("PROBLEMS", "**PROBLEMS")
                                     .replace("FIX", "**FIX")])
def test_realistic_formats_keep_the_fix(answer):
    result = parse_review(answer)
    assert result is not None
    assert result.fix == "separate the fingers."
    assert len(result.text.splitlines()) == 4


@pytest.mark.parametrize("answer", [None, "", "looks good", "FIX: change everything",
                                     "LOOKS: nice. WORKS: nice. PROBLEMS: none.",
                                     "LOOKS: WORKS: light. PROBLEMS: none. FIX: none.",
                                     ANSWER + " FIX: add rain.",
                                     "Preface. " + ANSWER, "x" * 8001,
                                     "LOOKS: cup. PROBLEMS: handle. WORKS: light. FIX: handle."])
def test_inconclusive_answers_are_not_successes(answer):
    assert parse_review(answer) is None


@pytest.mark.parametrize("fix", ["none", "None.", "No change needed.", "No changes necessary."])
def test_no_change_has_no_action(fix):
    result = parse_review("LOOKS: a cup. WORKS: shape. PROBLEMS: none. FIX: " + fix)
    assert result is not None
    assert result.fix is None


_SPEC = spec_from_file_location("pixal_server_creative_review",
                               Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def build(seed=51):
    with patch.object(server, "load_config", return_value={"critic": {"model": "test-vl-8b"}}):
        return server.build_review("review of #abc123", seed, "input.png",
                                   brief="A quiet portrait in soft light.", recipe="h3_ref_still")


def test_builder_carries_context_to_vision_node_and_reports_actual_model():
    graph, _, info = build()
    assert "A quiet portrait in soft light." in graph["2"]["inputs"]["custom_prompt"]
    assert graph["2"]["inputs"]["image"] == ["1", 0]
    assert info["review_file"] == graph["4"]["inputs"]["file"]
    assert info["model"] == graph["2"]["inputs"]["model_name"] == "test-vl-8b"
    assert "brief" in server.SIGS["vl_review"]
    assert "recipe" in server.SIGS["vl_review"]
    _, _, another = build(seed=52)
    assert another["review_file"] != info["review_file"]


def finalize(root, *, text=None, error=None, info=None, started=None):
    hub = SimpleNamespace(critic_hot=False, convo=[], broadcast=Mock(),
                          prev_job_free_min=None, ledger_append=Mock())
    job = {"id": "job9", "cid": "c", "template": "vl_review", "parent": "abc123",
           "started": time.time() if started is None else started,
           "images": [], "error": error, "scene": "review of #abc123", "seed": 51,
           "count": 1, "spec": {}, "info": info, "texts": [] if text is None else [text]}
    with patch.object(server, "CDIR", root), patch("builtins.print"):
        server.Hub.finalize(hub, job)
    return hub, job


def reviews(hub):
    return [call.kwargs for call in hub.broadcast.call_args_list
            if call.kwargs.get("type") == "review"]


def test_collapsed_node_output_uses_the_same_parser(tmp_path):
    hub, job = finalize(tmp_path, text=" ".join(ANSWER.split()))
    assert reviews(hub)[0]["text"] == ANSWER
    assert reviews(hub)[0]["fix"] == "separate the fingers."
    assert job["error"] is None


def test_failed_execution_cannot_publish_even_valid_partial_output(tmp_path):
    hub, job = finalize(tmp_path, text=ANSWER, error="node failed")
    assert reviews(hub) == []
    assert hub.convo == []
    assert job["error"] == "node failed"


def test_old_parent_file_is_never_read_as_a_new_review(tmp_path):
    directory = tmp_path / "output" / "pixal_dm"
    directory.mkdir(parents=True)
    (directory / "review_abc123.txt").write_text(ANSWER, encoding="utf-8")
    hub, job = finalize(tmp_path)
    assert reviews(hub) == []
    assert job["error"] == "critic returned nothing"


def test_fresh_attempt_artifact_survives_a_websocket_drop(tmp_path):
    _, _, info = build()
    path = tmp_path / "output" / info["review_file"]
    path.parent.mkdir(parents=True)
    started = time.time() - 1
    path.write_text(ANSWER, encoding="utf-8")
    hub, job = finalize(tmp_path, info=info, started=started)
    assert reviews(hub)[0]["text"] == ANSWER
    assert job["error"] is None


def test_stale_attempt_artifact_is_inconclusive(tmp_path):
    _, _, info = build()
    path = tmp_path / "output" / info["review_file"]
    path.parent.mkdir(parents=True)
    path.write_text(ANSWER, encoding="utf-8")
    os.utime(path, (1, 1))
    hub, job = finalize(tmp_path, info=info)
    assert reviews(hub) == []
    assert job["error"] == "critic returned nothing"


@pytest.mark.parametrize("file", ["../private.txt", "C:/private.txt", None, ["file"]])
def test_artifact_path_must_be_graph_generated(tmp_path, file):
    hub, job = finalize(tmp_path, info={"review_file": file})
    assert reviews(hub) == []
    assert job["error"] == "critic returned nothing"


def test_malformed_output_cannot_offer_a_fix_or_mark_the_job_successful(tmp_path):
    hub, job = finalize(tmp_path, text="FIX: make it more dramatic")
    assert reviews(hub) == []
    assert hub.convo == []
    assert job["error"] == "critic returned an incomplete review"
