"""Pie (ADR-0046)."""

import pytest

import indah
from indah.protocol import BUILTIN_TYPES


@pytest.mark.unit
def test_wire_props_and_reactive_sources():
    lit = indah.Signal(1)
    share = indah.Signal(0.25)
    pie = indah.Pie(
        lambda: [
            {"label": "explore", "value": share.value, "color": "var(--x-explore)"},
            {"label": "exploit", "value": 1 - share.value},
        ],
        active=lit,
        height=150,
        show_labels=False,
        label="Decision",
    )
    props = pie.to_json()["props"]
    assert props["height"] == 150 and props["showLabels"] is False and props["label"] == "Decision"
    assert props["slices"][0] == {"label": "explore", "value": 0.25, "color": "var(--x-explore)"}
    assert props["slices"][1] == {"label": "exploit", "value": 0.75}
    assert props["active"] == 1
    lit.set(None)
    share.set(0.5)
    props = pie.to_json()["props"]
    assert props["active"] is None and props["slices"][0]["value"] == 0.5


@pytest.mark.unit
def test_a_fixed_pie_with_no_active_slice():
    props = indah.Pie([{"label": "a", "value": 3}]).to_json()["props"]
    assert props["active"] is None and props["showLabels"] is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "slices",
    [
        [{"label": "no value"}],
        [{"value": -1}],
        [{"value": True}],
        [{"value": 1, "color": "url(x)"}],
        ["a"],
        [{"value": 1}] * 25,
    ],
)
def test_bad_slices_are_refused(slices):
    with pytest.raises(ValueError):
        indah.Pie(slices)


@pytest.mark.unit
def test_bad_reactive_slices_are_refused_when_read():
    pie = indah.Pie(lambda: [{"value": -2}])
    with pytest.raises(ValueError):
        pie.to_json()


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs", [{"height": 20}, {"height": 900}, {"active": -1}, {"active": "a"}]
)
def test_bad_options_are_refused(kwargs):
    with pytest.raises(ValueError):
        indah.Pie([{"value": 1}], **kwargs)


@pytest.mark.unit
def test_pie_is_a_reserved_builtin_type():
    assert "pie" in BUILTIN_TYPES
