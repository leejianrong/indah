"""Unit tests for the register_component() custom-component seam (ADR-0012)."""

import pytest

from indah.custom import clear_registry, custom, register_component, registered
from indah.reactive import Signal

COLORPICKER = {
    "tag": "input",
    "attrs": {"type": "color"},
    "bind": {"value": "value"},
    "on": {"input": {"event": "input", "prop": "value"}},
}


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


@pytest.mark.unit
def test_register_records_a_wire_render_spec():
    reg = register_component("colorpicker", render=COLORPICKER)
    assert reg.type == "colorpicker"
    assert reg.render["tag"] == "input"
    assert reg.render["attrs"] == {"type": "color"}
    # The round-trip map: the indah "input" event writes the "value" prop.
    assert reg.events == {"input": "value"}
    assert registered("colorpicker") is reg


@pytest.mark.unit
def test_custom_instance_ships_spec_and_reactive_value():
    register_component("colorpicker", render=COLORPICKER)
    colour = Signal("#ff8800")
    picker = custom("colorpicker", value=colour)
    picker.id = "n0"

    node = picker.to_json()
    assert node["type"] == "colorpicker"
    # The render spec rides along once as the reserved _spec static prop...
    assert node["props"]["_spec"]["tag"] == "input"
    # ...and the bound signal is a reactive prop.
    assert node["props"]["value"] == "#ff8800"


@pytest.mark.unit
def test_custom_event_writes_back_to_the_bound_signal():
    register_component("colorpicker", render=COLORPICKER)
    colour = Signal("#ff8800")
    picker = custom("colorpicker", value=colour)
    assert picker.handle("input", {"value": "#00ff00"}) is True
    assert colour.peek() == "#00ff00"  # changed in UI -> readable in Python


@pytest.mark.unit
def test_custom_ignores_unknown_event():
    register_component("colorpicker", render=COLORPICKER)
    colour = Signal("#ff8800")
    picker = custom("colorpicker", value=colour)
    assert picker.handle("click", {}) is False
    assert colour.peek() == "#ff8800"


@pytest.mark.unit
def test_custom_supports_static_props():
    register_component(
        "badge",
        render={"tag": "span", "class": "badge", "text": "label"},
    )
    badge = custom("badge", label="v0")
    badge.id = "n0"
    props = badge.to_json()["props"]
    assert props["label"] == "v0"  # static (not a signal) prop
    assert props["_spec"]["text"] == "label"


@pytest.mark.unit
def test_custom_unregistered_type_raises():
    with pytest.raises(ValueError):
        custom("nope", value=Signal(""))


@pytest.mark.unit
def test_register_rejects_a_disallowed_tag():
    with pytest.raises(ValueError):
        register_component("evil", render={"tag": "script"})


@pytest.mark.unit
def test_register_rejects_a_builtin_type_collision():
    with pytest.raises(ValueError):
        register_component("slider", render={"tag": "div"})


@pytest.mark.unit
def test_register_rejects_an_empty_type():
    with pytest.raises(ValueError):
        register_component("", render={"tag": "div"})


@pytest.mark.unit
def test_register_rejects_a_malformed_spec():
    # An unknown field in the render spec violates the protocol schema.
    with pytest.raises(ValueError):
        register_component("x", render={"tag": "div", "bogus": 1})
