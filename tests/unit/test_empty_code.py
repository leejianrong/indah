"""``Empty`` (an empty-state block) and ``Code`` (a read-only block with a Copy button), IND-158."""

import pytest

import indah
from indah import Button, Code, Column, Empty, Signal, Text
from indah.protocol import BUILTIN_TYPES
from indah.reactive import Computed
from indah.session import Session

pytestmark = pytest.mark.unit


def test_the_new_types_are_builtin():
    assert {"code", "empty"} <= BUILTIN_TYPES
    with pytest.raises(ValueError):
        indah.register_component("code", render={"tag": "div"})


def test_code_sends_text_and_leaves_defaults_off_the_wire():
    node = Code("make demo").to_json()
    assert node["type"] == "code"
    assert node["props"] == {"text": "make demo"}


def test_code_language_and_label_ride_along_and_copy_can_be_turned_off():
    props = Code("select 1", language="sql", label="Query", copy=False).to_json()["props"]
    assert props == {"text": "select 1", "language": "sql", "label": "Query", "copy": False}


def test_code_text_follows_a_signal_computed_or_callable():
    sig = Signal("a")
    code = Code(sig)
    assert code.reactive_props()["text"]() == "a"
    sig.set("b")
    assert code.reactive_props()["text"]() == "b"
    assert Code(Computed(lambda: sig.value + "!")).reactive_props()["text"]() == "b!"
    assert Code(lambda: "c").reactive_props()["text"]() == "c"


def test_code_keeps_newlines_and_indentation_exactly():
    text = "def f():\n    return 1\n"
    assert Code(text).to_json()["props"]["text"] == text


def test_code_rejects_a_non_string_language():
    with pytest.raises(TypeError):
        Code("x", language=3)  # type: ignore[arg-type]


def test_empty_sends_title_and_body_and_nothing_else_by_default():
    node = Empty("No requests yet", "Run the proxy to see traffic.").to_json()
    assert node["type"] == "empty"
    assert node["props"] == {"title": "No requests yet", "body": "Run the proxy to see traffic."}
    assert node["children"] == []


def test_empty_body_is_optional():
    assert Empty("Nothing here").to_json()["props"] == {"title": "Nothing here", "body": ""}


def test_empty_puts_the_action_first_and_flags_it():
    action = Button("Start", lambda: None)
    extra = Code("semula log")
    node = Empty("Empty", action=action, children=[extra]).to_json()
    assert node["props"]["hasAction"] is True
    assert [c["type"] for c in node["children"]] == ["button", "code"]


def test_empty_without_an_action_has_no_flag_and_keeps_children_in_order():
    node = Empty("Empty", children=[Text("a"), Text("b")]).to_json()
    assert "hasAction" not in node["props"]
    assert [c["props"]["text"] for c in node["children"]] == ["a", "b"]


def test_empty_action_must_be_a_component():
    with pytest.raises(TypeError):
        Empty("x", action="click me")  # type: ignore[arg-type]


def test_empty_title_and_body_follow_signals():
    title = Signal("Loading")
    node = Empty(title, lambda: "body")
    title.set("Done")
    assert node.reactive_props()["title"]() == "Done"
    assert node.reactive_props()["body"]() == "body"


def test_a_tree_with_both_builds_a_session_snapshot():
    root = Column(children=[Empty("Nothing", action=Button("Go", lambda: None)), Code("x")])
    snap = Session(root).snapshot()
    assert [c["type"] for c in snap["children"]] == ["empty", "code"]
    assert snap["children"][0]["children"][0]["type"] == "button"
