"""The sorting example (examples/sorting.py) builds, runs a sort and can be shuffled."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sorting.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("sorting_example_app", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _instant(ex):
    """Replay at full speed in a test: keep the steps per frame, drop the pauses."""
    ex.SPEEDS = tuple((steps, 0) for steps, _ in ex.SPEEDS)


def _by_type(session, type_name):
    return [c for c in session._by_id.values() if c.type == type_name]


def _button(session, label):
    return next(b for b in _by_type(session, "button") if b.reactive_props()["label"]() == label)


@pytest.mark.integration
def test_the_app_builds_with_unsorted_bars_and_zero_counters():
    ex = _load_example()
    session = ex.build()
    (strip,) = _by_type(session, "barstrip")
    series = strip.reactive_props()["series"]()
    assert len(series) == ex.DEFAULT_SIZE
    values = [sum(bar) for bar in series]
    assert sorted(values) == list(range(1, ex.DEFAULT_SIZE + 1)) and not ex.is_sorted(values)
    assert [s.reactive_props()["value"]() for s in _by_type(session, "stat")] == ["0", "0", "0"]


@pytest.mark.integration
async def test_sort_button_runs_to_a_sorted_array_with_counters():
    ex = _load_example()
    _instant(ex)
    session = ex.build()
    result = session.dispatch(_button(session, "Sort").id, "click", {})
    assert result is not None and result.coro is not None  # async handler
    await result.coro
    (strip,) = _by_type(session, "barstrip")
    series = strip.reactive_props()["series"]()
    assert [bar[3] for bar in series] == list(range(1, ex.DEFAULT_SIZE + 1))  # all "sorted"
    comparisons, swaps, steps = (s.reactive_props()["value"]() for s in _by_type(session, "stat"))
    assert int(comparisons.replace(",", "")) > 0 and int(swaps.replace(",", "")) > 0
    assert int(steps.replace(",", "")) == int(comparisons.replace(",", "")) + int(
        swaps.replace(",", "")
    )


@pytest.mark.integration
async def test_every_algorithm_finishes_through_the_ui_path():
    ex = _load_example()
    _instant(ex)
    for name in ex.ALGORITHMS:
        sorter = ex.Sorter()
        sorter.algorithm.set(name)
        sorter.speed.set(10)
        await sorter.sort()
        assert sorter.done.value and not sorter.running.value, name
        assert ex.is_sorted(sorter.values.value), name


@pytest.mark.integration
async def test_a_run_stops_at_the_step_cap(monkeypatch):
    ex = _load_example()
    _instant(ex)
    monkeypatch.setattr(ex, "MAX_STEPS", 30)
    sorter = ex.Sorter()
    sorter.size.set(100)
    sorter.shuffle()
    await sorter.sort()
    assert sorter.steps.value == 30
    assert not sorter.done.value and not sorter.running.value
    assert "limit" in sorter.status.value


@pytest.mark.integration
def test_shuffle_and_size_reset_the_run():
    ex = _load_example()
    session = ex.build()
    slider = _by_type(session, "slider")[0]  # array size comes first
    session.dispatch(slider.id, "input", {"value": 60})
    (strip,) = _by_type(session, "barstrip")
    assert len(strip.reactive_props()["series"]()) == 60
    before = strip.reactive_props()["series"]()
    session.dispatch(_button(session, "Shuffle").id, "click", {})
    assert strip.reactive_props()["series"]() != before


@pytest.mark.integration
async def test_shuffle_aborts_a_run_in_progress():
    ex = _load_example()
    _instant(ex)
    sorter = ex.Sorter()
    sorter.size.set(100)
    sorter.shuffle()
    sorter.speed.set(1)
    task = asyncio.ensure_future(sorter.sort())
    await asyncio.sleep(0.01)
    sorter.shuffle()
    await task
    assert not sorter.running.value and not sorter.done.value
    assert sorter.steps.value == 0
