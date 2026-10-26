"""The sorting visualiser's algorithms (examples/sorting.py): pure generators, no UI."""

import importlib.util
import random
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sorting.py"


def _load():
    spec = importlib.util.spec_from_file_location("sorting_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sorting = _load()


def _cases():
    rng = random.Random(3)
    yield [5, 4, 3, 2, 1]
    yield [1, 2, 3, 4, 5]
    yield [2, 2, 1, 1, 3]
    yield [7]
    yield []
    for n in (10, 33, 100):
        yield sorting.shuffled(n, rng)


@pytest.mark.unit
@pytest.mark.parametrize("name", list(sorting.ALGORITHMS))
def test_every_algorithm_sorts_and_only_yields_known_steps(name):
    for case in _cases():
        work = list(case)
        steps = list(sorting.ALGORITHMS[name](work))
        assert work == sorted(case)
        assert all(kind in ("compare", "swap", "write") for kind, _, _ in steps)


@pytest.mark.unit
@pytest.mark.parametrize("name", list(sorting.ALGORITHMS))
def test_step_counts_are_sensible(name):
    n = 100
    work = sorting.shuffled(n, random.Random(1))
    steps = list(sorting.ALGORITHMS[name](work))
    compares = sum(1 for kind, _, _ in steps if kind == "compare")
    assert n - 1 <= compares <= n * (n - 1) // 2  # at least one pass, at most all pairs
    assert len(steps) < sorting.MAX_STEPS  # a full 100-item run fits under the cap
    if name == "Merge sort":
        assert compares < 700  # n log n, far below the quadratic sorts


@pytest.mark.unit
def test_an_already_sorted_array_is_cheap_for_bubble_and_insertion():
    for name in ("Bubble sort", "Insertion sort"):
        steps = list(sorting.ALGORITHMS[name](list(range(1, 51))))
        assert len(steps) == 49 and all(kind == "compare" for kind, _, _ in steps)


@pytest.mark.unit
def test_steps_are_applied_to_the_array_when_yielded():
    """Replaying only the swaps and writes onto a copy reproduces the sorted array."""
    for name, algo in sorting.ALGORITHMS.items():
        original = sorting.shuffled(40, random.Random(9))
        work = list(original)
        replay = list(original)
        for kind, a, b in algo(work):
            if kind == "swap":
                replay[a], replay[b] = replay[b], replay[a]
            elif kind == "write":
                replay[a] = b
        assert replay == sorted(original), name


@pytest.mark.unit
def test_run_is_capped():
    work = sorting.shuffled(100, random.Random(2))
    steps = list(sorting.run("Bubble sort", work, max_steps=50))
    assert len(steps) == 50
    assert not sorting.is_sorted(work)


@pytest.mark.unit
def test_shuffled_clamps_the_size_and_never_returns_sorted():
    rng = random.Random(0)
    assert len(sorting.shuffled(5, rng)) == sorting.MIN_SIZE
    assert len(sorting.shuffled(5000, rng)) == sorting.MAX_SIZE
    for _ in range(50):
        values = sorting.shuffled(sorting.MIN_SIZE, rng)
        assert sorted(values) == list(range(1, sorting.MIN_SIZE + 1))
        assert not sorting.is_sorted(values)


@pytest.mark.unit
def test_bars_colour_by_state():
    values = [3, 1, 2]
    assert sorting.bars(values, {1: sorting.COMPARED}, False) == [
        [3, 0, 0, 0],
        [0, 1, 0, 0],
        [2, 0, 0, 0],
    ]
    assert sorting.bars(values, {1: sorting.COMPARED}, True) == [[0, 0, 0, v] for v in values]
