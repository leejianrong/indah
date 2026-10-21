"""Ephemeral props and ``SecretReveal`` (ADR-0036, IND-119): a secret is shown once and never
kept where a reconnect could replay it."""

import json

import pytest

from indah.components import Column, SecretReveal, Text
from indah.protocol import init_message
from indah.reactive import Signal
from indah.session import Session

SECRET = "tok_live_SUPER-SECRET-123"


def _session(**kw):
    value: Signal[str | None] = Signal(None)
    dismissed: list[int] = []
    reveal = SecretReveal(value, label="API token", on_dismiss=lambda: dismissed.append(1), **kw)
    session = Session(Column(children=[Text("hi"), reveal]))
    return session, value, reveal, dismissed


def _wire(hub) -> str:
    return json.dumps(hub.history())


@pytest.mark.unit
def test_the_snapshot_never_carries_the_value_but_keeps_the_other_props():
    session, value, reveal, _ = _session()
    value.set(SECRET)
    snap = json.dumps(init_message(session.snapshot()))
    assert SECRET not in snap and "value" not in session.snapshot()["children"][1]["props"]
    assert session.snapshot()["children"][1]["props"]["label"] == "API token"


@pytest.mark.unit
def test_a_live_set_reaches_subscribers_but_not_the_replay_history():
    from indah.transport import Hub

    session, value, reveal, _ = _session()
    hub = Hub()
    session.bind_hub(hub)
    queue = hub.subscribe()
    value.set(SECRET)  # outside a dispatch: the live path
    delivered = json.dumps([m for _, m in list(queue._queue)])  # noqa: SLF001
    assert SECRET in delivered  # the open tab sees it
    assert SECRET not in _wire(hub)  # a reconnect cannot be replayed it
    assert SECRET not in json.dumps(hub.replay_since(0) or [])


@pytest.mark.unit
def test_a_sync_dispatch_splits_the_secret_out_of_the_recorded_changes():
    from indah.components import Button

    value: Signal[str | None] = Signal(None)
    btn = Button("make", on_click=lambda: value.set(SECRET))
    session = Session(Column(children=[btn, SecretReveal(value)]))
    result = session.dispatch(btn.id, "click", {})
    assert SECRET not in json.dumps(result.changes)
    assert SECRET in json.dumps(result.transient)


@pytest.mark.unit
def test_dismiss_clears_the_signal_runs_the_callback_and_the_clear_is_recorded():
    from indah.transport import Hub

    session, value, reveal, dismissed = _session()
    hub = Hub()
    session.bind_hub(hub)
    value.set(SECRET)
    result = session.dispatch(reveal.id, "dismiss", {})
    assert value.value is None and dismissed == [1]
    assert result is not None and result.changes  # the clear carries no secret: it is recorded


@pytest.mark.unit
def test_closing_the_session_clears_an_undismissed_secret():
    session, value, reveal, _ = _session()
    value.set(SECRET)
    session.close()
    assert value.value is None


@pytest.mark.unit
def test_it_is_marked_sensitive_so_an_audit_log_never_holds_its_payload():
    _, _, reveal, _ = _session()
    assert reveal.sensitive is True


@pytest.mark.unit
def test_an_unrecorded_publish_still_gets_an_offset_and_a_resume_skips_it():
    from indah.transport import Hub

    hub = Hub()
    hub.publish({"type": "a"})
    off = hub.publish({"type": "secret"}, record=False)
    hub.publish({"type": "b"})
    assert off == 2
    replay = hub.replay_since(0)
    assert [m["type"] for _, m in replay] == ["a", "b"]


@pytest.mark.unit
def test_forget_ephemeral_clears_the_secret_without_closing_the_session():
    session, value, reveal, _ = _session()
    value.set(SECRET)
    session.forget_ephemeral()  # what a fresh init does: its snapshot cannot carry it
    assert value.value is None
