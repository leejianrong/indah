import datetime
import json

import pytest

from indah.components import MAX_JSON_BYTES, JsonTree
from indah.reactive import Signal


def _doc(t):
    return t.reactive_props()["doc"]()


@pytest.mark.unit
def test_serialises_objects_text_and_bytes_to_json_safe_data():
    assert _doc(JsonTree({"a": [1, 2, {"b": None}]})) == {
        "data": {"a": [1, 2, {"b": None}]},
        "error": None,
    }
    assert _doc(JsonTree('{"x": [true, 1.5]}'))["data"] == {"x": [True, 1.5]}
    assert _doc(JsonTree(b'{"x": 1}'))["data"] == {"x": 1}
    assert _doc(JsonTree("[1, 2]"))["data"] == [1, 2]
    assert _doc(JsonTree('"just a string"'))["data"] == "just a string"


@pytest.mark.unit
def test_non_json_values_become_strings_and_the_result_always_dumps():
    when = datetime.datetime(2026, 10, 20, 12, 0)
    doc = _doc(JsonTree({"when": when, "n": float("nan"), "i": float("inf"), "s": {1, 2}, 5: "k"}))
    data = doc["data"]
    assert data["when"] == str(when) and data["n"] == "nan" and data["i"] == "inf"
    assert data["5"] == "k" and isinstance(data["s"], str)  # keys are strings, sets stringified
    json.dumps(data, allow_nan=False)  # nothing a browser's JSON.parse would choke on


@pytest.mark.unit
def test_invalid_text_and_oversize_documents_report_an_error_instead_of_raising():
    bad = _doc(JsonTree("{not json"))
    assert bad["data"] is None and "Invalid JSON" in bad["error"]
    huge = _doc(JsonTree({"k": "x" * (MAX_JSON_BYTES + 10)}))
    assert huge["data"] is None and "too large" in huge["error"]
    deep: dict = {}
    node = deep
    for _ in range(500):
        node["n"] = {}
        node = node["n"]
    ok = _doc(JsonTree(deep))
    assert ok["error"] is None and ok["data"] is not None  # a runaway depth is cut, not a crash
    assert "Invalid JSON" in _doc(JsonTree("[" * 100000))["error"]  # parser recursion limit


@pytest.mark.unit
def test_value_may_be_a_signal_or_callable_and_static_props():
    src = Signal({"a": 1})
    t = JsonTree(src, expanded=2, search=False, label="Request")
    assert t.type == "jsontree"
    assert t.static_props() == {"expanded": 2, "search": False, "label": "Request"}
    assert _doc(t)["data"] == {"a": 1}
    src.set({"a": 2})
    assert _doc(t)["data"] == {"a": 2}
    assert _doc(JsonTree(lambda: [1]))["data"] == [1]
    assert JsonTree({}).static_props() == {"expanded": 1, "search": True, "label": ""}
    with pytest.raises(ValueError):
        JsonTree({}, expanded=-1)
