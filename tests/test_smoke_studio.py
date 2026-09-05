"""The opt-in harness itself must not spend GPU work during normal testing."""
import pytest

from tools import smoke_studio as smoke


@pytest.mark.parametrize("queue", [{}, None, {"queue_running": []},
    {"queue_running": [], "queue_pending": None},
    {"queue_running": [[1, "other"]], "queue_pending": []},
    {"queue_running": [], "queue_pending": [[1, "other"]]}])
def test_idle_check_fails_closed(queue):
    assert not smoke.queue_is_idle(queue)


def test_empty_engine_queue_is_idle():
    assert smoke.queue_is_idle({"queue_running": [], "queue_pending": []})


def test_events_only_belong_to_this_request():
    own = [{"type": "progress", "job_id": "mine"},
           {"type": "job", "job_id": "mine", "cid": "test"},
           {"type": "thinking", "cid": "test"}]
    foreign = [{"type": "job", "job_id": "theirs", "cid": "private"},
               {"type": "text", "text": "private"},
               {"type": "status"}, {"type": "progress", "job_id": "theirs"}]
    selected, ids = smoke.owned_events(own + foreign, "test", [])
    assert selected == own
    assert ids == {"mine"}


def test_duplicate_step_refused_before_network(monkeypatch):
    monkeypatch.setattr(smoke, "request", lambda *a, **k: pytest.fail("network"))
    with pytest.raises(RuntimeError, match="already attempted"):
        smoke.render(None, {"steps": {"image": {}}}, "image", None)


def test_changed_chat_never_switched_back(monkeypatch):
    monkeypatch.setattr(smoke, "request", lambda *a, **k: {"active": "user-selected"})
    with pytest.raises(RuntimeError, match="leaving it untouched"):
        smoke.selected({"chat": "test-chat"})


def test_preference_fingerprint_ignores_only_learned_boot_time():
    assert smoke.preference_hash('{"comfy_boot_seconds": 35.7, "edit": {"model": "a"}}') == \
        smoke.preference_hash('{"comfy_boot_seconds": 32.3, "edit": {"model": "a"}}')
    assert smoke.preference_hash('{"edit": {"model": "a"}}') != \
        smoke.preference_hash('{"edit": {"model": "b"}}')


def test_preference_fingerprint_normalizes_json_format_not_data():
    assert smoke.preference_hash('{\r\n "b": 2,\r\n "a": 1\r\n}') == \
        smoke.preference_hash('{"a":1,"b":2}')
    assert smoke.preference_hash('{"extension": {"future": true}}') != \
        smoke.preference_hash('{"extension": {"future": false}}')
