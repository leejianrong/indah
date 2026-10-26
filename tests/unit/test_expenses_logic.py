"""The expense tracker's pure logic (examples/expenses.py): bounds, totals, restore check."""

import importlib.util
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "expenses.py"
spec = importlib.util.spec_from_file_location("expenses_example", _EXAMPLE)
ex = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ex
spec.loader.exec_module(ex)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [(12.345, 12.35), ("7", 7.0), (0.01, 0.01), (100000, 100000.0)]
    + [(x, None) for x in (0, -3, 100000.01, "abc", None, True, float("nan"), float("inf"))],
)
def test_amounts_are_rounded_to_cents_and_bounded(raw, expected):
    assert ex.parse_amount(raw) == expected


@pytest.mark.unit
def test_add_appends_with_a_fresh_id_and_cleans_the_description():
    rows, problem = ex.add_expense(ex.SAMPLE, "  Tea   and   cake ", "4.5", "Food")
    assert problem == ""
    assert rows[-1] == {"id": 7, "description": "Tea and cake", "amount": 4.5, "category": "Food"}
    assert len(ex.SAMPLE) == 6  # the input is not mutated


@pytest.mark.unit
@pytest.mark.parametrize(
    ("description", "amount", "category"),
    [
        ("", 5, "Food"),
        ("x" * 41, 5, "Food"),
        ("Tea", 0, "Food"),
        ("Tea", 5, "Gold"),
    ],
)
def test_bad_input_changes_nothing_and_says_why(description, amount, category):
    rows, problem = ex.add_expense(ex.SAMPLE, description, amount, category)
    assert rows is ex.SAMPLE and problem


@pytest.mark.unit
def test_the_row_limit_holds():
    rows = [
        {"id": i, "description": "x", "amount": 1.0, "category": "Food"}
        for i in range(1, ex.MAX_ROWS + 1)
    ]
    same, problem = ex.add_expense(rows, "one more", 1, "Food")
    assert same is rows and str(ex.MAX_ROWS) in problem
    assert len(ex.add_expense(ex.delete_expense(rows, 1), "one more", 1, "Food")[0]) == ex.MAX_ROWS


@pytest.mark.unit
def test_totals_and_the_running_chart():
    assert ex.total(ex.SAMPLE) == 232.95
    by_cat = dict(zip(ex.CATEGORIES, ex.totals_by_category(ex.SAMPLE), strict=True))
    assert by_cat == {"Food": 81.3, "Transport": 53.0, "Home": 74.15, "Fun": 24.5, "Other": 0.0}
    chart = ex.running_total(ex.SAMPLE)
    assert chart[0] == [0, 0.0] and chart[-1] == [6, 232.95] and len(chart) == 7
    assert ex.running_total([]) == [[0, 0.0]]


@pytest.mark.unit
def test_a_restored_value_is_checked():
    assert ex.valid_rows(ex.SAMPLE) and ex.valid_rows([])
    row = ex.SAMPLE[0]
    for bad in (
        "nope",
        [row, row],  # duplicate id
        [{**row, "amount": -1}],
        [{**row, "category": "Gold"}],
        [{**row, "description": ""}],
        [{**row, "extra": 1}],
        [{**row, "id": i} for i in range(ex.MAX_ROWS + 1)],
    ):
        assert not ex.valid_rows(bad)
