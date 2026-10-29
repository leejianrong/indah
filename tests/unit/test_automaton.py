"""The cellular-automaton rules and board (examples/automaton.py): pure logic."""

import importlib.util
import random
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "automaton.py"


def _load():
    spec = importlib.util.spec_from_file_location("automaton_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


A = _load()


def _live(grid):
    return {(r, c) for r, row in enumerate(grid) for c, v in enumerate(row) if v}


@pytest.mark.unit
def test_blinker_oscillates_with_period_two():
    grid = A.empty_grid(8)
    for c in (2, 3, 4):
        grid[3][c] = 1
    once = A.step_life(grid)
    assert _live(once) == {(2, 3), (3, 3), (4, 3)}
    assert A.step_life(once) == grid


@pytest.mark.unit
def test_block_is_a_still_life():
    grid = A.empty_grid(8)
    for r, c in ((1, 1), (1, 2), (2, 1), (2, 2)):
        grid[r][c] = 1
    assert A.step_life(grid) == grid


@pytest.mark.unit
def test_glider_moves_one_cell_diagonally_every_four_generations():
    grid = A.seed_life("glider", 16)
    start = _live(grid)
    for _ in range(4):
        grid = A.step_life(grid)
    assert _live(grid) == {(r + 1, c + 1) for r, c in start}


@pytest.mark.unit
def test_life_wraps_at_the_edges():
    grid = A.empty_grid(8)
    for r in (7, 0, 1):  # a vertical blinker straddling the top and bottom edges
        grid[r][4] = 1
    assert _live(A.step_life(grid)) == {(0, 3), (0, 4), (0, 5)}


@pytest.mark.unit
def test_rule_30_first_rows_match_the_known_pattern():
    row = [0, 0, 0, 0, 1, 0, 0, 0, 0]
    row = A.step_rule(row, 30)
    assert row == [0, 0, 0, 1, 1, 1, 0, 0, 0]
    row = A.step_rule(row, 30)
    assert row == [0, 0, 1, 1, 0, 0, 1, 0, 0]


@pytest.mark.unit
def test_rule_90_draws_sierpinski_and_rule_0_and_255_are_uniform():
    row = [0, 0, 0, 1, 0, 0, 0]
    assert A.step_rule(row, 90) == [0, 0, 1, 0, 1, 0, 0]
    assert A.step_rule(row, 0) == [0] * 7
    assert A.step_rule(row, 255) == [1] * 7


@pytest.mark.unit
def test_rule_110_rule_bits():
    # 110 = 0b01101110: neighbourhoods 111, 100 and 000 die, the rest live.
    assert [A.step_rule([0, 0, 0, 0, 0], 110)[2]] == [0]
    assert A.step_rule([0, 0, 1, 0, 0], 110) == [0, 1, 1, 0, 0]


@pytest.mark.unit
def test_seed_patterns_fit_and_random_is_reproducible():
    for name in A.PATTERNS:
        for size in (A.MIN_SIZE, A.MAX_SIZE):
            grid = A.seed_life(name, size)
            assert len(grid) == size
            assert len(_live(grid)) == len(A.PATTERNS[name])
    a = A.seed_life("random", 24, random.Random(1))
    assert a == A.seed_life("random", 24, random.Random(1))
    assert 0 < len(_live(a)) < 24 * 24


@pytest.mark.unit
def test_board_clamps_size_and_rule():
    assert A.Board(size=10_000).size == A.MAX_SIZE
    assert A.Board(size=1).size == A.MIN_SIZE
    assert A.Board("rule", rule=999).rule == 255


@pytest.mark.unit
def test_1d_board_fills_downwards_then_scrolls():
    board = A.Board("rule", size=A.MIN_SIZE, rule=30)
    assert board.population == 1
    for _ in range(A.MIN_SIZE - 1):
        board.step()
    assert board.generation == A.MIN_SIZE - 1
    assert sum(board.cells[-1]) > 0  # the last row is now written
    top_before = board.cells[1]
    board.step()  # grid is full: scrolls
    assert board.cells[0] == top_before
    assert board.generation == A.MIN_SIZE


@pytest.mark.unit
def test_generation_cap_stops_a_run_and_reset_clears_it():
    board = A.Board("glider", size=A.MIN_SIZE)
    board.generation = A.MAX_GENERATIONS - 1
    assert board.step() is True
    assert board.finished
    before = [row[:] for row in board.cells]
    assert board.step() is False
    assert board.cells == before
    board.reset()
    assert board.generation == 0 and not board.finished


@pytest.mark.unit
def test_columns_are_column_major_with_row_zero_at_the_bottom():
    grid = [[1, 0], [0, 0]]  # a live cell at the top left
    assert A.columns(grid) == [[0, 1], [0, 0]]


@pytest.mark.unit
def test_parse_mode_maps_the_pattern_choices():
    assert A.parse_mode("rule-110", 30) == ("rule", 110)
    assert A.parse_mode("rule", 77) == ("rule", 77)
    assert A.parse_mode("glider", 77) == ("glider", 77)
    assert set(A.PATTERN_LABELS) >= {"rule-30", "rule-90", "rule-110", "rule"}


@pytest.mark.unit
def test_the_default_start_is_a_rich_garden_that_fits_every_size():
    assert A.DEFAULT_MODE == "garden" and "garden" in A.PATTERN_LABELS
    for size in (A.MIN_SIZE, A.DEFAULT_SIZE, A.MAX_SIZE):
        grid = A.seed_life("garden", size)
        assert len(grid) == size
        assert len(_live(grid)) >= 25  # not a lonely five-cell speck on black
    assert A.seed_life("garden", A.DEFAULT_SIZE) == A.seed_life("garden", A.DEFAULT_SIZE)
