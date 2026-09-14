"""Session-level tests: reactive graph + wire protocol, no HTTP."""

import pytest

from indah.components import Column, Slider, Text
from indah.reactive import Signal, computed
from indah.session import Session


def _demo():
    a = Signal(2)
    b = Signal(3)
    total = computed(lambda: f"{a.value + b.value}")
    root = Column(children=[Slider(a, label="a"), Slider(b, label="b"), Text(total)])
    return Session(root), a, b


@pytest.mark.integration
def test_snapshot_assigns_ids_and_serialises_tree():
    session, _, _ = _demo()
    root = session.snapshot()
    assert root["id"] == "n0"
    assert root["type"] == "column"
    ids = [child["id"] for child in root["children"]]
    assert ids == ["n1", "n2", "n3"]
    assert root["children"][2] == {
        "id": "n3",
        "type": "text",
        "props": {"text": "5"},
        "children": [],
    }


def _props_for(changes, target):
    return next((c["props"] for c in changes if c["target"] == target), None)


@pytest.mark.integration
def test_slider_event_patches_dependents_only_never_the_other_slider():
    session, _, _ = _demo()
    # n1 is slider "a". Changing it touches the computed label (n3) and slider a's
    # own value (n1, which genuinely depends on signal a) -- but never slider b (n2).
    result = session.dispatch("n1", "input", {"value": 8})

    targets = {c["target"] for c in result.changes}
    assert result.coro is None  # a plain sync handler
    assert "n2" not in targets  # the unrelated slider is untouched: fine-grained
    assert _props_for(result.changes, "n3") == {"text": "11"}  # 8 + 3


@pytest.mark.integration
def test_label_updates_when_either_signal_changes():
    session, _, _ = _demo()
    assert _props_for(session.dispatch("n1", "input", {"value": 0}).changes, "n3") == {"text": "3"}
    assert _props_for(session.dispatch("n2", "input", {"value": 0}).changes, "n3") == {"text": "0"}


@pytest.mark.integration
def test_unknown_component_returns_none():
    session, _, _ = _demo()
    assert session.dispatch("does-not-exist", "input", {"value": 1}) is None


@pytest.mark.integration
def test_no_op_change_produces_no_patches():
    session, _, _ = _demo()
    # Setting slider a to its current value (2) changes nothing downstream.
    result = session.dispatch("n1", "input", {"value": 2})
    assert result.changes == []
