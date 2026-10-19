"""``Stream``: an append-only reactive list, bounded by ``limit`` (IND-90, ADR-0026)."""

import pytest

from indah.reactive import computed
from indah.stream import Stream


@pytest.mark.unit
def test_append_keeps_only_the_newest_limit_rows():
    s = Stream([1, 2], limit=4)
    s.append(3, 4, 5)
    assert s.value == [2, 3, 4, 5]
    s.append(6)
    assert s.value == [3, 4, 5, 6]


@pytest.mark.unit
def test_initial_items_are_trimmed_to_the_limit():
    assert Stream(range(10), limit=3).value == [7, 8, 9]


@pytest.mark.unit
def test_limit_must_be_positive():
    with pytest.raises(ValueError):
        Stream(limit=0)


@pytest.mark.unit
def test_listeners_hear_appends_with_only_the_new_rows():
    s = Stream(limit=10)
    heard = []
    s.listen(lambda kind, payload: heard.append((kind, payload)))
    s.append("a", "b")
    s.append("c")
    assert heard == [("append", ["a", "b"]), ("append", ["c"])]


@pytest.mark.unit
def test_set_and_clear_are_replaces():
    s = Stream([1], limit=5)
    heard = []
    s.listen(lambda kind, payload: heard.append((kind, payload)))
    s.set([7, 8])
    s.clear()
    assert heard == [("replace", [7, 8]), ("replace", [])]
    assert s.value == []


@pytest.mark.unit
def test_an_empty_append_is_a_no_op():
    s = Stream(limit=5)
    heard = []
    s.listen(lambda kind, payload: heard.append(kind))
    s.append()
    assert heard == []


@pytest.mark.unit
def test_derived_values_follow_appends():
    s = Stream(limit=5)
    count = computed(lambda: len(s.value))
    s.append(1, 2)
    assert count.value == 2


@pytest.mark.unit
def test_unlisten_stops_delivery():
    s = Stream(limit=5)
    heard = []
    off = s.listen(lambda kind, payload: heard.append(kind))
    off()
    s.append(1)
    assert heard == []
