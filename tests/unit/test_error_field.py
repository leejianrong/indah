"""IND-260: ``error=`` on CodeEditor and TextArea, and an error-toned ``Text``."""

import pytest

from indah import CodeEditor, Signal, Text, TextArea


def _props(component):
    out = dict(component.static_props())
    out.update({k: fn() for k, fn in component.reactive_props().items()})
    return out


@pytest.mark.unit
@pytest.mark.parametrize("cls", [CodeEditor, TextArea])
def test_error_is_reactive_and_empty_means_none(cls):
    msg = Signal("")
    box = cls(Signal("x"), error=msg)
    assert _props(box)["error"] is None
    msg.set("Bad value")
    assert _props(box)["error"] == "Bad value"


@pytest.mark.unit
@pytest.mark.parametrize("cls", [CodeEditor, TextArea])
def test_no_error_argument_sends_no_error_prop(cls):
    assert "error" not in _props(cls(Signal("x")))


@pytest.mark.unit
def test_text_tone_err_is_a_static_prop_and_other_tones_are_refused():
    assert _props(Text("x", tone="err"))["tone"] == "err"
    assert "tone" not in _props(Text("x"))
    with pytest.raises(ValueError):
        Text("x", tone="pink")
