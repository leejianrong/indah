"""``InfoTip`` (IND-159): a focusable info icon that shows a tip, and its render-spec allowance."""

import pytest

from indah import InfoTip, Signal
from indah.components import Column
from indah.protocol import BUILTIN_TYPES, SPEC_COMPONENTS, RenderSpec
from indah.session import Session
from indah.transport import Hub

pytestmark = pytest.mark.unit


def _wire(component) -> dict:
    session = Session(Column(children=[component]))
    session.bind_hub(Hub(coalesce_seconds=0))
    return session.root.to_json()["children"][0]


def test_wire_has_the_type_and_the_text_and_leaves_the_default_label_off():
    assert "infotip" in BUILTIN_TYPES
    node = InfoTip("Counts requests since midnight").to_json()
    assert node["type"] == "infotip"
    assert node["props"] == {"text": "Counts requests since midnight"}


def test_a_custom_label_travels_when_given():
    assert InfoTip("hi", label="About this metric").to_json()["props"] == {
        "text": "hi",
        "label": "About this metric",
    }


def test_text_follows_a_signal_computed_or_callable():
    text = Signal("one")
    tip = InfoTip(text)
    read = tip.reactive_props()["text"]
    assert read() == "one"
    text.set("two")
    assert read() == "two"
    assert InfoTip(lambda: "from a function").reactive_props()["text"]() == "from a function"
    # a plain string is static on the wire, not a reactive prop
    assert "text" not in InfoTip("plain").reactive_props()


def test_a_live_text_is_in_the_first_snapshot():
    text = Signal("hello")
    assert _wire(InfoTip(text))["props"]["text"] == "hello"


def test_none_and_other_values_are_shown_as_text():
    assert InfoTip(None).to_json()["props"]["text"] == ""
    assert InfoTip(42).to_json()["props"]["text"] == "42"


@pytest.mark.parametrize("label", ["", 3, None])
def test_a_bad_label_is_refused(label):
    with pytest.raises(ValueError, match="label"):
        InfoTip("x", label=label)


def test_a_render_spec_may_name_it_and_bind_text():
    assert SPEC_COMPONENTS["infotip"] == frozenset({"text"})
    spec = RenderSpec.model_validate({"component": "infotip", "bind": {"text": "why"}}).validated()
    assert spec.wire() == {"component": "infotip", "bind": {"text": "why"}}
    with pytest.raises(ValueError, match="takes"):
        RenderSpec.model_validate({"component": "infotip", "bind": {"label": "x"}}).validated()
