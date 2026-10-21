"""The semula editor example (examples/semula_editor.py): save, a version conflict with a
Diff, the review card and the keyed playground stack."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "semula_editor.py"
spec = importlib.util.spec_from_file_location("semula_editor_example", _EXAMPLE)
ex = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ex
spec.loader.exec_module(ex)


def _tab(store=None, sid="a"):
    store = store or ex.EntryStore()
    app = ex.build_editor_app(store)
    return store, app.state.store.get_or_create(sid)


def _find(session, type_, pred=lambda c: True):
    return next(c for c in session._by_id.values() if c.type == type_ and pred(c))


def _button(session, label):
    return _find(session, "button", lambda c: c._label == label)


def _toasts(handle):
    return [m["message"] for _, m in handle.hub.history() if m["type"] == "toast"]


@pytest.mark.integration
def test_save_bumps_the_version_and_a_stale_save_opens_the_conflict_diff():
    store, a = _tab()
    s = a.session
    modal = _find(s, "modal")
    area = _find(s, "textarea", lambda c: c._label.startswith("Response"))
    mine = json.dumps({"answer": "my edit", "confidence": 0.5})
    s.dispatch(area.id, "input", {"value": mine})
    s.dispatch(_button(s, "Save").id, "click", {})
    assert store.version == 2 and json.loads(store.response)["answer"] == "my edit"
    assert modal.reactive_props()["open"]() is False
    assert _toasts(a) == ["Saved as version 2"]

    store.other_editor()  # v3 lands behind this tab's back
    s.dispatch(area.id, "input", {"value": json.dumps({"answer": "mine again"})})
    s.dispatch(_button(s, "Save").id, "click", {})
    assert modal.reactive_props()["open"]() is True and store.version == 3  # nothing saved
    diff = _find(s, "diff").reactive_props()["diff"]()
    assert diff["stats"]["add"] + diff["stats"]["chg"] + diff["stats"]["del"] > 0

    s.dispatch(_button(s, "Keep mine").id, "click", {})
    assert store.version == 4 and json.loads(store.response) == {"answer": "mine again"}
    assert modal.reactive_props()["open"]() is False


@pytest.mark.integration
def test_take_theirs_reloads_the_stored_version_and_invalid_json_is_not_saved():
    store, a = _tab()
    s = a.session
    area = _find(s, "textarea", lambda c: c._label.startswith("Response"))
    store.other_editor()
    s.dispatch(area.id, "input", {"value": "{not json"})
    s.dispatch(_button(s, "Save").id, "click", {})
    assert store.version == 2 and _toasts(a)[-1].startswith("Not valid JSON")
    s.dispatch(area.id, "input", {"value": "{}"})
    s.dispatch(_button(s, "Save").id, "click", {})
    s.dispatch(_button(s, "Take theirs").id, "click", {})
    assert json.loads(area._value.value)["edited_by"] == "someone else"
    assert _find(s, "modal").reactive_props()["open"]() is False


@pytest.mark.integration
def test_review_verdict_badge_follows_the_buttons():
    _, a = _tab()
    s = a.session
    badge = _find(s, "badge", lambda c: c.reactive_props()["text"]() == "pending")
    s.dispatch(_button(s, "Approve").id, "click", {})
    assert badge.reactive_props()["text"]() == "approved"
    assert _button(s, "Reject").static_props().get("confirm") == "Reject this answer?"


@pytest.mark.integration
def test_playground_rows_edit_add_and_remove_by_key():
    _, a = _tab()
    s = a.session
    lst = _find(s, "list")
    rows = lambda: lst.reactive_props()["items"]()  # noqa: E731
    assert [r["id"] for r in rows()] == ["m1", "m2"]
    s.dispatch(lst.id, "content", {"key": "m2", "index": 1, "value": "Hello there"})
    s.dispatch(lst.id, "role", {"key": "m1", "index": 0, "value": "assistant"})
    assert rows()[1]["content"] == "Hello there" and rows()[0]["role"] == "assistant"
    s.dispatch(_button(s, "Add message").id, "click", {})
    assert [r["id"] for r in rows()] == ["m1", "m2", "m3"]
    s.dispatch(lst.id, "remove", {"key": "m1", "index": 0})
    assert [r["id"] for r in rows()] == ["m2", "m3"]
    s.dispatch(lst.id, "remove", {"key": "m1", "index": 0})  # a stale key is refused
    assert [r["id"] for r in rows()] == ["m2", "m3"]


@pytest.mark.integration
async def test_run_streams_the_reply_into_the_stream_text():
    _, a = _tab()
    s = a.session
    result = s.dispatch(_button(s, "Run").id, "click", {})
    assert result.coro is not None  # async handler: the POST returns, the tokens stream after
    await result.coro
    assert _find(s, "streamtext")._text.startswith("Annual plans")
