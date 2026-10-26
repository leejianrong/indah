"""Cellular automata: Conway's Game of Life and the 1-D Wolfram rules, live.

Pick a Life pattern, or switch to a one-dimensional rule (30, 90 and 110 are the famous
ones; the Rule number slider takes any of the 256), then press Play and watch the grid
evolve generation by generation. Speed, grid size and the play, pause, step and reset
controls are all here, with a generation counter and a live-cell count.

The grid is an `indah.Heatmap` driven by a `Signal`: each generation replaces the field
(at most 64 x 64 cells, so a frame stays small). The rules themselves are plain Python
with no dependency, so the whole demo is model-free and cheap: one session does a few
thousand cell updates per second at the fastest speed, and a run stops at
``MAX_GENERATIONS`` so an idle tab cannot loop forever.

How the two worlds work:

- **Life** runs on a torus (the edges wrap). A cell is alive next generation if it has
  three live neighbours, or two and is alive already.
- **1-D rules** update one row from the row above using a rule number: its eight bits say
  what a cell becomes for each of the eight patterns of (left, centre, right). The first
  row is a single live cell; each generation adds a row underneath, and once the grid is
  full the picture scrolls up.

Run it with:  python examples/automaton.py   (prints a URL; embeds inline in a cell).
"""

from __future__ import annotations

import asyncio
import random

import indah

MAX_SIZE = 64
MIN_SIZE = 16
DEFAULT_SIZE = 48
MAX_GENERATIONS = 600  # per run; reset (or change a control) to start another

# Life patterns as (row, col) offsets from the pattern's own origin.
PATTERNS: dict[str, list[tuple[int, int]]] = {
    "glider": [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)],
    "r-pentomino": [(0, 1), (0, 2), (1, 0), (1, 1), (2, 1)],
    "acorn": [(0, 1), (1, 3), (2, 0), (2, 1), (2, 4), (2, 5), (2, 6)],
    "blinkers": [(0, 1), (1, 1), (2, 1), (0, 5), (0, 6), (0, 7), (4, 2), (4, 3), (4, 4)],
}
PATTERN_LABELS = {
    "glider": "Life: glider",
    "r-pentomino": "Life: R-pentomino (long-lived)",
    "acorn": "Life: acorn (long-lived)",
    "blinkers": "Life: blinkers",
    "random": "Life: random soup",
    "rule-30": "1-D rule 30 (chaotic)",
    "rule-90": "1-D rule 90 (Sierpinski triangle)",
    "rule-110": "1-D rule 110 (Turing complete)",
    "rule": "1-D custom rule (use Rule number)",
}
DEFAULT_MODE = "r-pentomino"
DEFAULT_RULE = 30

Grid = list[list[int]]


def empty_grid(size: int) -> Grid:
    return [[0] * size for _ in range(size)]


def seed_life(name: str, size: int, rng: random.Random | None = None) -> Grid:
    """The starting board for a Life pattern: a named pattern in the middle, or a
    random soup (about a third alive, from a fixed seed unless ``rng`` is given)."""
    grid = empty_grid(size)
    if name == "random":
        rng = rng or random.Random(7)
        return [[1 if rng.random() < 0.33 else 0 for _ in range(size)] for _ in range(size)]
    cells = PATTERNS[name]
    height = max(r for r, _ in cells) + 1
    width = max(c for _, c in cells) + 1
    top, left = (size - height) // 2, (size - width) // 2
    for r, c in cells:
        grid[top + r][left + c] = 1
    return grid


def step_life(grid: Grid) -> Grid:
    """One generation of Conway's Life on a torus."""
    n = len(grid)
    out = empty_grid(n)
    for r in range(n):
        up, here, down = grid[r - 1], grid[r], grid[(r + 1) % n]
        for c in range(n):
            left, right = c - 1, (c + 1) % n
            alive = (
                up[left] + up[c] + up[right] + here[left] + here[right]
                + down[left] + down[c] + down[right]
            )  # fmt: skip
            out[r][c] = 1 if alive == 3 or (alive == 2 and here[c]) else 0
    return out


def step_rule(row: list[int], rule: int) -> list[int]:
    """The next row of a 1-D (Wolfram) rule, wrapping at the edges. Bit ``k`` of
    ``rule`` is the new state for the neighbourhood whose (left, centre, right) bits
    read as the number ``k``."""
    n = len(row)
    return [(rule >> (row[i - 1] * 4 + row[i] * 2 + row[(i + 1) % n])) & 1 for i in range(n)]


def parse_mode(mode: str, rule: int) -> tuple[str, int]:
    """Split a Pattern choice into ``(board mode, rule number)``: ``rule-30`` is the 1-D
    mode with rule 30, plain ``rule`` is the 1-D mode with the slider's number, and a Life
    pattern keeps the number unused."""
    if mode.startswith("rule-"):
        return "rule", int(mode.removeprefix("rule-"))
    return mode, rule


def seed_rule(size: int) -> Grid:
    """A 1-D start: one live cell in the middle of the top row."""
    grid = empty_grid(size)
    grid[0][size // 2] = 1
    return grid


class Board:
    """The automaton's state, with no UI in it: a square grid, a generation count and
    the step that advances it. ``mode`` is a Life pattern name or ``"rule"``."""

    def __init__(self, mode: str = DEFAULT_MODE, size: int = DEFAULT_SIZE, rule: int = 30) -> None:
        self.mode = mode
        self.size = max(MIN_SIZE, min(MAX_SIZE, int(size)))
        self.rule = max(0, min(255, int(rule)))
        self.generation = 0
        self._row = 0  # 1-D only: the row the newest generation sits on
        self.cells = self._seed()

    def _seed(self) -> Grid:
        if self.mode == "rule":
            self._row = 0
            return seed_rule(self.size)
        return seed_life(self.mode, self.size)

    @property
    def finished(self) -> bool:
        return self.generation >= MAX_GENERATIONS

    @property
    def population(self) -> int:
        return sum(map(sum, self.cells))

    def reset(self) -> None:
        self.generation = 0
        self.cells = self._seed()

    def step(self) -> bool:
        """Advance one generation; False (and no change) once the cap is reached."""
        if self.finished:
            return False
        if self.mode == "rule":
            nxt = step_rule(self.cells[self._row], self.rule)
            if self._row + 1 < self.size:
                self._row += 1
                self.cells[self._row] = nxt
            else:  # full: scroll up one row and write the new one at the bottom
                self.cells = [*self.cells[1:], nxt]
        else:
            self.cells = step_life(self.cells)
        self.generation += 1
        return True


def columns(grid: Grid) -> list[list[int]]:
    """The Heatmap wants column-major data (``z[x][y]``), with row 0 at the bottom of
    the plot; the board's row 0 is the top, so each column is reversed."""
    return [list(col)[::-1] for col in zip(*grid, strict=True)]


class Automaton:
    """Per-session state: the board plus the controls that configure and drive it."""

    def __init__(self) -> None:
        self.mode = indah.Signal(DEFAULT_MODE)
        self.rule = indah.Signal(DEFAULT_RULE)
        self.size = indah.Signal(DEFAULT_SIZE)
        self.speed = indah.Signal(10)  # generations per second
        self.playing = indah.Signal(False)
        mode, rule = parse_mode(self.mode.peek(), self.rule.peek())
        self.board = Board(mode, self.size.peek(), rule)
        self.field = indah.Signal(columns(self.board.cells))
        self.generation = indah.Signal(0)
        self.population = indah.Signal(self.board.population)
        self.status = indah.Signal("Press Play to start.")
        # Changing the pattern, rule or size starts that world afresh.
        indah.effect(self._reconfigure)

    def _reconfigure(self) -> None:
        mode, size, rule = self.mode.value, int(self.size.value), int(self.rule.value)
        self.playing.set(False)
        mode, rule = parse_mode(mode, rule)
        self.board = Board(mode, size, rule)
        self._publish("Press Play to start.")

    def _publish(self, status: str | None = None) -> None:
        def apply() -> None:
            self.field.set(columns(self.board.cells))
            self.generation.set(self.board.generation)
            self.population.set(self.board.population)
            if status is not None:
                self.status.set(status)

        indah.batch(apply)

    def reset(self) -> None:
        self.playing.set(False)
        self.board.reset()
        self._publish("Reset.")

    def step_once(self) -> None:
        self.playing.set(False)
        if self.board.step():
            self._publish(f"Stepped to generation {self.board.generation}.")
        else:
            self._publish(f"Reached the {MAX_GENERATIONS}-generation cap: reset to run again.")

    def pause(self) -> None:
        self.playing.set(False)

    async def play(self) -> None:
        if self.playing.value:
            return
        if self.board.finished:
            self._publish(f"Reached the {MAX_GENERATIONS}-generation cap: reset to run again.")
            return
        self.playing.set(True)
        self.status.set("Running...")
        try:
            while self.playing.value:
                if not self.board.step():
                    self._publish(f"Stopped at the {MAX_GENERATIONS}-generation cap.")
                    break
                self._publish()
                await asyncio.sleep(1.0 / max(1.0, float(self.speed.value)))
            else:
                self.status.set(f"Paused at generation {self.board.generation}.")
        finally:
            self.playing.set(False)


def build() -> indah.Session:
    m = Automaton()

    controls = indah.Card(
        title="World",
        children=[
            indah.Select(
                m.mode,
                options=[(key, label) for key, label in PATTERN_LABELS.items()],
                label="Pattern",
            ),
            indah.Slider(m.rule, min=0, max=255, step=1, label="Rule number (custom 1-D rule)"),
            indah.Slider(m.size, min=MIN_SIZE, max=MAX_SIZE, step=8, label="Grid size"),
            indah.Slider(m.speed, min=1, max=30, step=1, label="Speed (generations per second)"),
        ],
    )

    run = indah.Card(
        title="Run",
        children=[
            indah.Row(
                children=[
                    indah.Button("Play", on_click=m.play),
                    indah.Button("Pause", on_click=m.pause, variant="outlined"),
                ]
            ),
            indah.Row(
                children=[
                    indah.Button("Step", on_click=m.step_once, variant="outlined"),
                    indah.Button("Reset", on_click=m.reset, variant="outlined"),
                ]
            ),
            indah.Text(lambda: m.status.value),
        ],
    )

    stats = indah.Row(
        children=[
            indah.Stat(value=lambda: str(m.generation.value), label="Generation"),
            indah.Stat(value=lambda: str(m.population.value), label="Live cells"),
        ]
    )

    grid = indah.Card(
        children=[
            indah.Heatmap(
                lambda: m.field.value,
                colormap="magma",
                zmin=0,
                zmax=1,
                title="Grid",
                height=380,
            )
        ]
    )

    intro = indah.Text(
        "# Cellular automata\n\n"
        "Conway's Game of Life and the one-dimensional rules (try 30, 90 and 110), "
        "streamed generation by generation. Each run stops after "
        f"{MAX_GENERATIONS} generations.",
        markdown=True,
    )
    return indah.Session(
        indah.Column(
            children=[
                intro,
                indah.Sidebar(
                    children=[
                        indah.Column(children=[controls, run]),
                        indah.Column(children=[stats, grid]),
                    ]
                ),
            ]
        )
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
