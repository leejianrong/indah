"""``disabled=`` on the value-bearing inputs: one shared mechanism (IND-243)."""

import pytest

import indah
from indah import Column, Signal
from indah.session import Session

OPTS = ["a", "b"]
# name -> (factory(sig, **kw), initial, event, forged payload value)
CASES = {
    "Slider": (lambda v, **k: indah.Slider(v, **k), 5.0, "input", 9),
    "TextInput": (lambda v, **k: indah.TextInput(v, **k), "x", "input", "forged"),
    "TextArea": (lambda v, **k: indah.TextArea(v, **k), "x", "input", "forged"),
    "Checkbox": (lambda v, **k: indah.Checkbox(v, **k), False, "change", True),
    "Switch": (lambda v, **k: indah.Switch(v, **k), False, "change", True),
    "Number": (lambda v, **k: indah.Number(v, **k), 1.0, "input", 7),
    "Date": (lambda v, **k: indah.Date(v, **k), "2026-01-01", "input", "2026-02-02"),
    "Select": (lambda v, **k: indah.Select(v, options=OPTS, **k), "a", "change", "b"),
    "Radio": (lambda v, **k: indah.Radio(v, options=OPTS, **k), "a", "change", "b"),
    "MultiSelect": (lambda v, **k: indah.MultiSelect(v, options=OPTS, **k), ["a"], "change", ["b"]),
    "Chips": (lambda v, **k: indah.Chips(v, options=OPTS, **k), "a", "change", "b"),
    "Segmented": (lambda v, **k: indah.Segmented(v, options=OPTS, **k), "a", "change", "b"),
}
PARAMS = pytest.mark.parametrize("name", list(CASES))


def _props(c):
    out = dict(c.static_props())
    out.update({k: fn() for k, fn in c.reactive_props().items()})
    return out


def _make(name, **kw):
    make, init, event, payload = CASES[name]
    sig = Signal(init)
    return make(sig, **kw), sig, init, event, payload


@pytest.mark.unit
@PARAMS
def test_default_is_unchanged_on_the_wire(name):
    comp, *_ = _make(name)
    assert "disabled" not in _props(comp) and not comp.locked()


@pytest.mark.unit
@PARAMS
@pytest.mark.parametrize("flag", [True, False])
def test_accepts_a_bool_and_emits_it(name, flag):
    comp, *_ = _make(name, disabled=flag)
    assert _props(comp)["disabled"] is flag


@pytest.mark.unit
@PARAMS
def test_accepts_a_signal_and_a_callable_live(name):
    off = Signal(True)
    comp, *_ = _make(name, disabled=off)
    assert _props(comp)["disabled"] is True
    off.set(False)
    assert _props(comp)["disabled"] is False
    comp2, *_ = _make(name, disabled=lambda: not off.value)
    assert _props(comp2)["disabled"] is True


@pytest.mark.unit
@PARAMS
def test_the_server_rejects_a_forged_event_then_accepts_it_once_unlocked(name):
    off = Signal(True)
    comp, sig, init, event, payload = _make(name, disabled=off)
    session = Session(Column(children=[comp]))
    session.dispatch(comp.id, event, {"value": payload})
    assert sig.value == init
    off.set(False)
    assert session.dispatch(comp.id, event, {"value": payload}) is not None
    assert sig.value == payload
