"""The expense tracker (examples/expenses.py): add, delete, clear with a confirm, and the
rows coming back when the session is rebuilt (ctx.persist)."""

import importlib.util
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "expenses.py"
spec = importlib.util.spec_from_file_location("expenses_example_app", _EXAMPLE)
ex = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ex
spec.loader.exec_module(ex)


def _tab(app, sid="a"):
    return app.state.store.get_or_create(sid).session


def _find(session, type_, pred=lambda c: True):
    return next(c for c in session._by_id.values() if c.type == type_ and pred(c))


def _button(session, label):
    return _find(session, "button", lambda c: c._label == label)


def _rows(session):
    table = _find(session, "table", lambda c: c._key == "id")
    return table.reactive_props()["rows"]()


def _fill(s, description, amount):
    s.dispatch(_find(s, "textinput").id, "input", {"value": description})
    s.dispatch(_find(s, "number").id, "input", {"value": amount})


@pytest.mark.integration
def test_it_opens_with_sample_rows_and_adds_and_deletes():
    app = ex.app
    s = _tab(app, "add")
    assert len(_rows(s)) == len(ex.SAMPLE)

    _fill(s, "Coffee", 3.5)
    s.dispatch(_button(s, "Add expense").id, "click", {})
    assert _rows(s)[-1]["description"] == "Coffee"
    assert _find(s, "stat").reactive_props()["value"]() == "$236.45"

    table = _find(s, "table", lambda c: c._key == "id")
    s.dispatch(table.id, "action", {"action": "a0", "key": _rows(s)[-1]["id"]})
    assert len(_rows(s)) == len(ex.SAMPLE)


@pytest.mark.integration
def test_a_bad_amount_is_refused_with_a_message():
    s = _tab(ex.app, "bad")
    _fill(s, "Yacht", 10_000_000)
    s.dispatch(_button(s, "Add expense").id, "click", {})
    assert len(_rows(s)) == len(ex.SAMPLE)


@pytest.mark.integration
def test_clear_all_waits_for_the_confirm():
    s = _tab(ex.app, "clear")
    modal = _find(s, "modal")
    s.dispatch(_button(s, "Clear all").id, "click", {})
    assert modal.reactive_props()["open"]() is True and len(_rows(s)) == len(ex.SAMPLE)
    s.dispatch(_button(s, "Keep them").id, "click", {})
    assert modal.reactive_props()["open"]() is False and len(_rows(s)) == len(ex.SAMPLE)
    s.dispatch(_button(s, "Clear all").id, "click", {})
    confirm = [c for c in s._by_id.values() if c.type == "button" and c._label == "Clear all"][-1]
    s.dispatch(confirm.id, "click", {})
    assert _rows(s) == [] and modal.reactive_props()["open"]() is False


@pytest.mark.integration
def test_the_rows_come_back_when_the_session_is_rebuilt():
    app = ex.indah.create_app(session_factory=ex.build)
    app.state.persist_delay = 0
    s = _tab(app, "tab-1")
    _fill(s, "Taxi", 20)
    s.dispatch(_button(s, "Add expense").id, "click", {})
    assert _rows(s)[-1]["description"] == "Taxi"

    app.state.store.discard("tab-1")  # a reaped session, or a restart with a durable store
    again = _tab(app, "tab-1")
    assert _rows(again)[-1]["description"] == "Taxi" and len(_rows(again)) == 7
    assert len(_rows(_tab(app, "tab-2"))) == len(ex.SAMPLE)  # another tab starts from the sample


@pytest.mark.integration
def test_the_category_breakdown_is_a_labelled_table_not_unlabelled_bars():
    s = _tab(ex.app, "cats")
    assert not [c for c in s._by_id.values() if c.type == "barstrip"]
    table = _find(s, "table", lambda c: c._key == "category")
    assert [col.title for col in table._columns] == ["Category", "Total ($)"]
