"""``Steps`` (IND-163): a vertical or horizontal timeline of steps, and the render-spec allowance
(the IND-157 seam) that lets a List item or a table cell name it."""

import pytest

from indah import Signal, Steps, steps_items
from indah.components import Col, Column, List, Table
from indah.protocol import SPEC_COMPONENTS, RenderSpec
from indah.session import Session
from indah.stream import Stream
from indah.transport import Hub


def _wire(component) -> dict:
    session = Session(Column(children=[component]))
    session.bind_hub(Hub(coalesce_seconds=0))
    return session.root.to_json()["children"][0]


# -- steps_items: one rule set, in Python ------------------------------------


@pytest.mark.unit
def test_an_item_is_a_dict_a_tuple_or_a_bare_label():
    assert steps_items(
        [
            {"label": "Plan", "state": "done", "detail": "2 min"},
            ("Build", "current"),
            ("Test", "pending", "waits on build"),
            "Ship",
        ]
    ) == [
        ["Plan", "done", "2 min"],
        ["Build", "current", ""],
        ["Test", "pending", "waits on build"],
        ["Ship", "pending", ""],
    ]


@pytest.mark.unit
def test_the_state_defaults_to_pending_and_all_five_are_accepted():
    assert steps_items([{"label": "a"}]) == [["a", "pending", ""]]
    states = ("done", "current", "skipped", "off", "pending")
    assert [i[1] for i in steps_items([(s, s) for s in states])] == list(states)


@pytest.mark.unit
def test_a_bad_state_or_item_raises_a_clear_error():
    with pytest.raises(ValueError, match="state"):
        steps_items([("a", "finished")])
    with pytest.raises(ValueError, match="label"):
        steps_items([{"state": "done"}])
    with pytest.raises(TypeError, match="step"):
        steps_items([42])


@pytest.mark.unit
def test_none_and_empty_give_no_steps_and_the_list_is_capped():
    assert steps_items(None) == []
    assert steps_items([]) == []
    assert len(steps_items([f"s{i}" for i in range(500)])) == 100  # the first 100


@pytest.mark.unit
def test_label_and_detail_are_text():
    assert steps_items([(3, "done", 4.5)]) == [["3", "done", "4.5"]]


# -- the component -----------------------------------------------------------


@pytest.mark.unit
def test_defaults_put_only_the_items_on_the_wire():
    node = _wire(Steps([("a", "done"), ("b", "current")]))
    assert node["type"] == "steps"
    assert node["props"] == {"items": [["a", "done", ""], ["b", "current", ""]]}


@pytest.mark.unit
def test_orientation_size_and_label_ride_only_when_not_default():
    props = _wire(Steps(["a"], orientation="horizontal", size="compact", label="Pipeline"))["props"]
    assert props["orientation"] == "horizontal"
    assert props["size"] == "compact"
    assert props["label"] == "Pipeline"
    plain = _wire(Steps(["a"]))["props"]
    assert not {"orientation", "size", "label"} & set(plain)


@pytest.mark.unit
def test_a_bad_orientation_or_size_fails_at_construction():
    with pytest.raises(ValueError, match="orientation"):
        Steps(["a"], orientation="diagonal")
    with pytest.raises(ValueError, match="size"):
        Steps(["a"], size="huge")


@pytest.mark.unit
def test_a_bad_item_in_static_data_fails_at_construction():
    with pytest.raises(ValueError, match="state"):
        Steps([("a", "nope")])


@pytest.mark.unit
def test_a_signal_and_a_computed_are_followed_in_place():
    items = Signal([("a", "current"), ("b", "pending")])
    component = Steps(items)
    session = Session(Column(children=[component]))
    session.bind_hub(Hub(coalesce_seconds=0))
    assert session.root.to_json()["children"][0]["props"]["items"][0] == ["a", "current", ""]
    reactive = component.reactive_props()["items"]
    items.set([("a", "done"), ("b", "current")])
    assert reactive() == [["a", "done", ""], ["b", "current", ""]]


@pytest.mark.unit
def test_a_callable_source_is_read_each_time():
    box = {"state": "pending"}
    reactive = Steps(lambda: [("a", box["state"])]).reactive_props()["items"]
    assert reactive() == [["a", "pending", ""]]
    box["state"] = "done"
    assert reactive() == [["a", "done", ""]]


# -- naming it from a render spec (List item, table cell) --------------------


@pytest.mark.unit
def test_a_spec_may_name_steps_and_bind_its_props():
    assert SPEC_COMPONENTS["steps"] == frozenset({"items", "orientation", "size"})
    spec = RenderSpec.model_validate({"component": "steps", "bind": {"items": "tiers"}}).validated()
    assert spec.wire() == {"component": "steps", "bind": {"items": "tiers"}}


@pytest.mark.unit
def test_a_steps_spec_is_a_leaf_that_binds_only_what_it_takes():
    with pytest.raises(ValueError, match="cannot bind"):
        RenderSpec.model_validate({"component": "steps", "bind": {"runs": "x"}}).validated()
    with pytest.raises(ValueError, match="leaf"):
        RenderSpec.model_validate(
            {"component": "steps", "on": {"click": {"event": "x"}}}
        ).validated()


@pytest.mark.unit
def test_a_list_item_carries_step_items_as_data():
    spec = {"component": "steps", "bind": {"items": "tiers"}}
    tiers = steps_items([("exact", "done"), ("fuzzy", "current"), ("llm", "off")])
    node = _wire(List(Signal([{"id": "a", "tiers": tiers}]), item=spec))
    assert node["props"]["template"] == spec
    assert node["props"]["items"][0]["tiers"][1] == ["fuzzy", "current", ""]


@pytest.mark.unit
def test_step_items_survive_in_a_table_row_and_a_stream_row():
    spec = {"component": "steps", "bind": {"items": "tiers"}}
    tiers = steps_items([("exact", "done"), ("fuzzy", "skipped")])
    table = Table(
        columns=[Col("id"), Col("tiers", kind="cell", render=spec)],
        rows=[{"id": 1, "tiers": tiers}],
        key="id",
    )
    assert _wire(table)["props"]["rows"][0]["tiers"] == [
        ["exact", "done", ""],
        ["fuzzy", "skipped", ""],
    ]

    stream = Stream(limit=10)
    stream.append({"id": "a", "tiers": tiers})
    streamed = Table(
        columns=[Col("id"), Col("tiers", kind="cell", render=spec)], rows=stream, key="id"
    )
    assert _wire(streamed)


@pytest.mark.unit
def test_any_other_list_in_an_item_is_still_turned_into_text():
    item = {"tag": "span", "text": "other"}
    node = _wire(List(Signal([{"id": "a", "other": [1, 2]}]), item=item))
    assert node["props"]["items"][0]["other"] == "[1, 2]"
