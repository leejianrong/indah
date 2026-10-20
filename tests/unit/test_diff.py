import json
import time

import pytest

from indah.components import Diff
from indah.diff import MAX_LINES, compute_diff
from indah.reactive import Signal


def rows_of(d, kind):
    return [r for r in d["rows"] if r["t"] == kind]


@pytest.mark.unit
def test_add_remove_and_change_rows_with_line_numbers_and_stats():
    d = compute_diff("one\ntwo\nthree\nfour", "one\nTWO\nthree\nfour\nfive", normalise="text")
    assert d["same"] is False and d["truncated"] is False and d["approximate"] is False
    assert d["stats"] == {"add": 1, "del": 0, "chg": 1}
    chg = rows_of(d, "chg")[0]
    assert (chg["a"], chg["b"], chg["at"], chg["bt"]) == (2, 2, "two", "TWO")
    add = rows_of(d, "add")[0]
    assert (add["b"], add["text"]) == (5, "five")
    gone = compute_diff("a\nb\nc", "a\nc", normalise="text")
    assert gone["stats"] == {"add": 0, "del": 1, "chg": 0}
    assert rows_of(gone, "del")[0] == {"t": "del", "a": 2, "text": "b"}


@pytest.mark.unit
def test_changed_lines_carry_inline_character_spans_on_both_sides():
    d = compute_diff('{"name": "alpha"}', '{"name": "alpine"}', normalise="text")
    chg = rows_of(d, "chg")[0]
    a_marked = "".join(chg["at"][s:e] for s, e in chg["ai"])
    b_marked = "".join(chg["bt"][s:e] for s, e in chg["bi"])
    assert a_marked == "ha" and b_marked == "ine"
    # Two lines with nothing in common are a plain change: spans would mark everything.
    far = rows_of(compute_diff("abcdefgh", "12345678", normalise="text"), "chg")[0]
    assert far["ai"] == [] and far["bi"] == []


@pytest.mark.unit
def test_json_mode_ignores_key_order_and_formatting():
    a = {"b": 1, "a": {"y": [1, 2], "x": None}}
    b_text = '{\n"a":{"x":null,"y":[1,2]},   "b":1}'
    same = compute_diff(a, b_text, normalise="json")
    assert (
        same["same"] is True
        and same["rows"] == []
        and same["stats"] == {"add": 0, "del": 0, "chg": 0}
    )
    changed = compute_diff(a, {"b": 2, "a": {"y": [1, 2], "x": None}}, normalise="json")
    assert changed["stats"]["chg"] == 1
    chg = rows_of(changed, "chg")[0]
    assert (chg["at"].strip(), chg["bt"].strip()) == ('"b": 1', '"b": 2')
    # Text mode keeps formatting differences, so the same pair is not "same".
    assert compute_diff(a, b_text, normalise="text")["same"] is False


@pytest.mark.unit
def test_json_mode_falls_back_to_raw_text_for_non_json_and_handles_odd_inputs():
    d = compute_diff("not json\nline 2", "not json\nline two", normalise="json")
    assert d["stats"]["chg"] == 1
    assert compute_diff(None, {"a": 1})["stats"]["add"] == 3  # {, "a": 1, }
    assert compute_diff({1: "x", "b": 2}, {1: "x", "b": 2})["same"] is True  # mixed key types
    assert compute_diff(b'{"a":1}', '{"a": 1}')["same"] is True
    import datetime

    assert compute_diff({"t": datetime.date(2026, 1, 1)}, {"t": "2026-01-01"})["same"] is True


@pytest.mark.unit
def test_long_unchanged_runs_collapse_to_a_skip_row_keeping_context_lines():
    a = "\n".join(f"line {i}" for i in range(100))
    b = a.replace("line 50", "LINE 50")
    d = compute_diff(a, b, normalise="text", context=3)
    kinds = [r["t"] for r in d["rows"]]
    assert kinds == ["skip", "eq", "eq", "eq", "chg", "eq", "eq", "eq", "skip"]
    assert d["rows"][0]["n"] == 47 and d["rows"][-1]["n"] == 46
    assert d["rows"][1]["a"] == 48  # numbering continues across the skip
    full = compute_diff(a, b, normalise="text", context=None)
    assert [r["t"] for r in full["rows"]].count("eq") == 99 and "skip" not in [
        r["t"] for r in full["rows"]
    ]
    tight = compute_diff(a, b, normalise="text", context=0)
    assert [r["t"] for r in tight["rows"]] == ["skip", "chg", "skip"]


@pytest.mark.unit
def test_inputs_beyond_the_line_cap_are_truncated_and_flagged():
    a = "\n".join(f"a{i}" for i in range(MAX_LINES + 500))
    b = a + "\nextra"
    d = compute_diff(a, b, normalise="text")
    assert d["truncated"] is True
    assert d["same"] is True  # the extra line is past the cap, so it is not compared
    short = compute_diff("x", "y", normalise="text")
    assert short["truncated"] is False


@pytest.mark.unit
def test_very_long_lines_are_clipped_and_do_not_get_inline_spans():
    d = compute_diff("a" * 5000, "b" * 5000, normalise="text")
    chg = rows_of(d, "chg")[0]
    assert len(chg["at"]) <= 2001 and chg["at"].endswith("…")
    assert chg["ai"] == [] and chg["bi"] == []


@pytest.mark.unit
def test_worst_case_repetitive_inputs_finish_quickly_and_are_flagged_approximate():
    a = "\n".join("}," if i % 3 == 0 else f'  "k{i % 40}": {i % 5},' for i in range(MAX_LINES))
    b = "\n".join(
        "}," if i % 3 == 1 else f'  "k{(i * 7) % 40}": {i % 4},' for i in range(MAX_LINES)
    )
    started = time.perf_counter()
    d = compute_diff(a, b, normalise="text")
    assert time.perf_counter() - started < 3.0  # exact difflib takes ~9 s on this pair
    assert d["approximate"] is True
    # A big but mostly-equal pair stays exact: the common prefix/suffix is trimmed first.
    base = [f"unique line {i}" for i in range(MAX_LINES)]
    edited = list(base)
    edited[2500] = "edited"
    exact = compute_diff("\n".join(base), "\n".join(edited), normalise="text")
    assert exact["approximate"] is False and exact["stats"]["chg"] == 1


@pytest.mark.unit
def test_diff_component_serialises_and_follows_its_sources():
    a, b = Signal({"k": 1}), Signal({"k": 2})
    d = Diff(a, b, mode="unified", labels=("before", "after"), context=1)
    assert d.type == "diff"
    assert d.static_props() == {"mode": "unified", "labels": ["before", "after"]}
    first = d.reactive_props()["diff"]()
    assert first["stats"]["chg"] == 1
    b.set({"k": 1})
    assert d.reactive_props()["diff"]()["same"] is True
    assert Diff("a", "b").static_props() == {"mode": "split", "labels": ["incoming", "candidate"]}
    for bad in ({"mode": "side"}, {"normalise": "xml"}, {"context": -1}, {"labels": ("one",)}):
        with pytest.raises(ValueError):
            Diff("a", "b", **bad)
    json.dumps(first)  # the wire payload is plain JSON


@pytest.mark.unit
def test_replaced_blocks_pair_similar_lines_not_merely_adjacent_ones():
    a = '{\n  "legacy": true,\n  "model": "alpha-1"\n}'
    b = '{\n  "model": "alpine-1"\n}'
    d = compute_diff(a, b, normalise="text")
    assert d["stats"] == {"add": 0, "del": 1, "chg": 1}
    assert rows_of(d, "del")[0]["text"] == '  "legacy": true,'
    chg = rows_of(d, "chg")[0]
    assert chg["at"] == '  "model": "alpha-1"' and chg["bt"] == '  "model": "alpine-1"'
    # Nothing similar in the block: honest removals and additions, no invented "change".
    d = compute_diff("alpha\nbeta", "12345\n67890", normalise="text")
    assert d["stats"] == {"add": 2, "del": 2, "chg": 0}
    # Order is preserved around the best pair: edits above and below it stay where they are.
    d = compute_diff(
        "one\nthe quick brown fox\nlast", "uno\nthe quick brown cat\nfinal", normalise="text"
    )
    kinds = [r["t"] for r in d["rows"]]
    assert kinds == ["del", "add", "chg", "del", "add"]
    assert rows_of(d, "chg")[0]["at"] == "the quick brown fox"
