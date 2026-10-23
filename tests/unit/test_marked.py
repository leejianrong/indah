"""``Marked`` (IND-157): text with shaded spans, and the render-spec allowance that lets a List item
or a table cell name it. Everything is additive to ADR-0016 and ADR-0027."""

import random

import pytest

from indah import Marked, Signal, marked_runs
from indah.components import Col, Column, List
from indah.protocol import BUILTIN_TYPES, SPEC_COMPONENTS, RenderSpec
from indah.session import Session
from indah.transport import Hub


def _wire(component) -> dict:
    session = Session(Column(children=[component]))
    session.bind_hub(Hub(coalesce_seconds=0))
    return session.root.to_json()["children"][0]


# -- marked_runs: one rule set, in Python ------------------------------------


@pytest.mark.unit
def test_no_marks_is_one_plain_run():
    assert marked_runs("hello", []) == [["hello"]]
    assert marked_runs("", [(0, 3, "ok")]) == []


@pytest.mark.unit
def test_a_mark_splits_the_text_into_runs_that_join_back_to_it():
    runs = marked_runs("ignored part kept", [(0, 7, "warn")])
    assert runs == [["ignored", "warn"], [" part kept"]]
    assert "".join(r[0] for r in runs) == "ignored part kept"


@pytest.mark.unit
def test_a_label_rides_in_the_third_slot():
    assert marked_runs("abc", [(1, 2, "err", "ignored when matching")]) == [
        ["a"],
        ["b", "err", "ignored when matching"],
        ["c"],
    ]
    assert marked_runs("abc", [{"start": 0, "end": 1, "tone": "ok", "label": "x"}])[0] == [
        "a",
        "ok",
        "x",
    ]


@pytest.mark.unit
def test_offsets_are_unicode_code_points_not_utf16_units():
    text = "a\U0001f600b"  # the emoji is one code point, two UTF-16 units
    assert marked_runs(text, [(1, 2, "info")]) == [["a"], ["\U0001f600", "info"], ["b"]]


@pytest.mark.unit
def test_ranges_are_clamped_and_empty_or_inverted_marks_dropped():
    assert marked_runs("abc", [(-5, 2, "ok")]) == [["ab", "ok"], ["c"]]
    assert marked_runs("abc", [(1, 99, "ok")]) == [["a"], ["bc", "ok"]]
    assert marked_runs("abc", [(2, 2, "ok"), (2, 1, "ok"), (7, 9, "ok")]) == [["abc"]]


@pytest.mark.unit
def test_overlaps_resolve_the_same_way_whatever_the_order():
    # The earlier start wins; a later mark is trimmed to begin where the earlier one ends.
    expected = [["ab", "ok"], ["cd", "warn"], ["e"]]
    assert marked_runs("abcde", [(0, 2, "ok"), (1, 4, "warn")]) == expected
    assert marked_runs("abcde", [(1, 4, "warn"), (0, 2, "ok")]) == expected
    # A mark wholly inside an earlier one is dropped.
    assert marked_runs("abcde", [(0, 4, "ok"), (1, 2, "err")]) == [["abcd", "ok"], ["e"]]


@pytest.mark.unit
def test_touching_marks_of_the_same_tone_and_label_stay_separate_runs():
    assert marked_runs("abcd", [(0, 2, "ok"), (2, 4, "ok")]) == [["ab", "ok"], ["cd", "ok"]]


@pytest.mark.unit
def test_bad_tone_and_non_integer_offsets_are_an_error():
    with pytest.raises(ValueError, match="tone"):
        marked_runs("abc", [(0, 1, "purple")])
    with pytest.raises(TypeError, match="offset"):
        marked_runs("abc", [(0.5, 1, "ok")])
    with pytest.raises(TypeError, match="offset"):
        marked_runs("abc", [("0", 1, "ok")])
    with pytest.raises(ValueError, match="mark"):
        marked_runs("abc", [(0, 1)])


@pytest.mark.unit
def test_whatever_the_marks_the_runs_join_back_to_the_plain_text():
    rng = random.Random(7)
    for _ in range(300):
        text = "".join(rng.choice("ab é\U0001f600\n") for _ in range(rng.randint(0, 20)))
        marks = [
            (rng.randint(-3, 25), rng.randint(-3, 25), rng.choice(["ok", "warn", "err", "neutral"]))
            for _ in range(rng.randint(0, 6))
        ]
        runs = marked_runs(text, marks)
        assert "".join(r[0] for r in runs) == text
        assert all(r[0] for r in runs)  # no empty run


# -- the component ------------------------------------------------------------


@pytest.mark.unit
def test_marked_is_a_builtin_type_with_runs_on_the_wire():
    assert "marked" in BUILTIN_TYPES
    node = _wire(Marked("one two", [(0, 3, "ok")]))
    assert node["type"] == "marked"
    assert node["props"]["runs"] == [["one", "ok"], [" two"]]


@pytest.mark.unit
def test_text_and_marks_may_be_signals_and_runs_follow_them():
    text, marks = Signal("abcd"), Signal([(0, 2, "ok")])
    component = Marked(text, marks)
    session = Session(Column(children=[component]))
    session.bind_hub(Hub(coalesce_seconds=0))
    props = session.root.to_json()["children"][0]["props"]
    assert props["runs"] == [["ab", "ok"], ["cd"]]
    reactive = component.reactive_props()["runs"]
    marks.set([(2, 4, "err")])
    assert reactive() == [["ab"], ["cd", "err"]]
    text.set("xyz")
    assert reactive() == [["xy"], ["z", "err"]]


@pytest.mark.unit
def test_a_callable_source_is_read_each_time():
    box = {"t": "abc"}
    component = Marked(lambda: box["t"], lambda: [(0, 1, "warn")])
    reactive = component.reactive_props()["runs"]
    assert reactive() == [["a", "warn"], ["bc"]]
    box["t"] = "xyz"
    assert reactive() == [["x", "warn"], ["yz"]]


@pytest.mark.unit
def test_label_names_the_block_and_is_left_off_when_empty():
    assert "label" not in _wire(Marked("a"))["props"]
    assert _wire(Marked("a", label="Request"))["props"]["label"] == "Request"


# -- naming it from a render spec (List item, table cell) --------------------


@pytest.mark.unit
def test_a_spec_may_name_a_built_in_component():
    assert "marked" in SPEC_COMPONENTS
    spec = RenderSpec.model_validate({"component": "marked", "bind": {"runs": "runs"}}).validated()
    assert spec.wire() == {
        "component": "marked",
        "bind": {"runs": "runs"},
    }  # no empty tag on the wire


@pytest.mark.unit
def test_a_spec_names_a_tag_or_a_component_never_both_or_neither():
    with pytest.raises(ValueError, match="either"):
        RenderSpec.model_validate({"tag": "div", "component": "marked"}).validated()
    with pytest.raises(ValueError, match="tag or a component"):
        RenderSpec.model_validate({}).validated()
    with pytest.raises(ValueError, match="not allowed"):
        RenderSpec.model_validate({"component": "script"}).validated()


@pytest.mark.unit
def test_a_component_node_is_a_leaf_with_no_events_or_children():
    with pytest.raises(ValueError, match="leaf"):
        RenderSpec.model_validate(
            {"component": "marked", "children": [{"tag": "span", "text": "x"}]}
        ).validated()
    with pytest.raises(ValueError, match="leaf"):
        RenderSpec.model_validate(
            {"component": "marked", "on": {"click": {"event": "x"}}}
        ).validated()


@pytest.mark.unit
def test_a_component_node_nests_inside_a_tag_spec():
    spec = RenderSpec.model_validate(
        {"tag": "div", "children": [{"component": "marked", "bind": {"runs": "r"}}]}
    ).validated()
    assert spec.wire()["children"][0] == {"component": "marked", "bind": {"runs": "r"}}


@pytest.mark.unit
def test_a_list_item_and_a_table_cell_can_use_it():
    item = {"component": "marked", "bind": {"runs": "runs"}}
    items = [{"id": "a", "runs": marked_runs("find me", [(0, 4, "warn")])}]
    node = _wire(List(Signal(items), item=item))
    assert node["props"]["template"] == item
    assert node["props"]["items"][0]["runs"] == [["find", "warn"], [" me"]]
    assert Col("req", kind="cell", render=item).wire()["render"] == item


@pytest.mark.unit
def test_runs_survive_in_a_table_row_and_a_stream_row():
    from indah.components import Table
    from indah.stream import Stream

    spec = {"component": "marked", "bind": {"runs": "req"}}
    runs = marked_runs("find me", [(0, 4, "warn")])
    table = Table(
        columns=[Col("id"), Col("req", kind="cell", render=spec)],
        rows=[{"id": 1, "req": runs}],
        key="id",
    )
    rows = _wire(table)["props"]["rows"]
    assert rows[0]["req"] == [["find", "warn"], [" me"]]

    stream = Stream(limit=10)
    stream.append({"id": "a", "req": runs})
    assert _wire(
        Table(columns=[Col("id"), Col("req", kind="cell", render=spec)], rows=stream, key="id")
    )
