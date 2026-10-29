"""A sorting visualiser: watch bubble, insertion, selection, merge or quick sort work.

Pick an algorithm, an array size and a speed, then press Sort. Each algorithm is a
plain Python generator that yields one step at a time (a comparison, a swap, or a
write); the app replays those steps into a bar strip and keeps live counters.

What it shows off:
- an async handler that streams a long-running computation into the page, a few
  steps per frame, so the UI stays live (press Shuffle to abort a run);
- a **BarStrip** as the bar chart: a bar's colour says what the algorithm is doing to
  it (compared, swapped or written, and finally sorted), and the tooltip names the
  state too, so colour is never the only cue;
- **Stat** counters for comparisons, swaps and steps, and per-session state, so
  every visitor sorts their own array.

Every run is capped at ``MAX_STEPS`` steps, so one visitor cannot hog the process.

Run it with:  python examples/sorting.py   (prints a URL; embeds inline in a notebook cell).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterator

import indah

MIN_SIZE, MAX_SIZE, DEFAULT_SIZE = 10, 100, 50  # a bar is at most 16px wide: 50 fill the card
MAX_STEPS = 20_000  # a hard cap per run; bubble sort on 100 items needs under 10,000
# (steps replayed per frame, seconds per frame) at speed 1..10: one UI update per frame, however
# many steps. The shell eases a bar's colour change over 0.2 s, so the slow speeds pause long
# enough for a highlight to show in full; the fast ones blur, which is what fast looks like.
SPEEDS = (
    (1, 0.3), (1, 0.2), (1, 0.12), (2, 0.08), (3, 0.05),
    (5, 0.03), (8, 0.03), (12, 0.03), (24, 0.03), (50, 0.03),
)  # fmt: skip

# A step is ("compare", i, j), ("swap", i, j) or ("write", i, value). Merge sort has no
# swaps, only writes into the array, so its writes count under "Swaps / writes".
Step = tuple[str, int, int]


def bubble_sort(a: list[int]) -> Iterator[Step]:
    n = len(a)
    for end in range(n - 1, 0, -1):
        swapped = False
        for i in range(end):
            yield ("compare", i, i + 1)
            if a[i] > a[i + 1]:
                a[i], a[i + 1] = a[i + 1], a[i]
                swapped = True
                yield ("swap", i, i + 1)
        if not swapped:
            return


def insertion_sort(a: list[int]) -> Iterator[Step]:
    for i in range(1, len(a)):
        j = i
        while j > 0:
            yield ("compare", j - 1, j)
            if a[j - 1] <= a[j]:
                break
            a[j - 1], a[j] = a[j], a[j - 1]
            yield ("swap", j - 1, j)
            j -= 1


def selection_sort(a: list[int]) -> Iterator[Step]:
    n = len(a)
    for i in range(n - 1):
        low = i
        for j in range(i + 1, n):
            yield ("compare", low, j)
            if a[j] < a[low]:
                low = j
        if low != i:
            a[i], a[low] = a[low], a[i]
            yield ("swap", i, low)


def merge_sort(a: list[int]) -> Iterator[Step]:
    def sort(lo: int, hi: int) -> Iterator[Step]:  # sorts a[lo:hi]
        if hi - lo < 2:
            return
        mid = (lo + hi) // 2
        yield from sort(lo, mid)
        yield from sort(mid, hi)
        left, right = a[lo:mid], a[mid:hi]
        i = j = 0
        for k in range(lo, hi):
            if i < len(left) and j < len(right):
                yield ("compare", lo + i, mid + j)
                take_left = left[i] <= right[j]
            else:
                take_left = i < len(left)
            if take_left:
                a[k] = left[i]
                i += 1
            else:
                a[k] = right[j]
                j += 1
            yield ("write", k, a[k])

    yield from sort(0, len(a))


def quick_sort(a: list[int]) -> Iterator[Step]:
    def sort(lo: int, hi: int) -> Iterator[Step]:  # sorts a[lo..hi], Lomuto partition
        if lo >= hi:
            return
        pivot = hi
        store = lo
        for i in range(lo, hi):
            yield ("compare", i, pivot)
            if a[i] < a[pivot]:
                if i != store:
                    a[i], a[store] = a[store], a[i]
                    yield ("swap", i, store)
                store += 1
        if store != pivot:
            a[store], a[pivot] = a[pivot], a[store]
            yield ("swap", store, pivot)
        yield from sort(lo, store - 1)
        yield from sort(store + 1, hi)

    yield from sort(0, len(a) - 1)


ALGORITHMS = {
    "Bubble sort": bubble_sort,
    "Insertion sort": insertion_sort,
    "Selection sort": selection_sort,
    "Merge sort": merge_sort,
    "Quick sort": quick_sort,
}


def is_sorted(a: list[int]) -> bool:
    return all(a[i] <= a[i + 1] for i in range(len(a) - 1))


def shuffled(size: int, rng: random.Random) -> list[int]:
    """A random permutation of 1..size, the size clamped to the allowed range."""
    size = max(MIN_SIZE, min(MAX_SIZE, int(size)))
    values = list(range(1, size + 1))
    rng.shuffle(values)
    while is_sorted(values):  # never open on an array that is already in order
        rng.shuffle(values)
    return values


def run(name: str, values: list[int], max_steps: int | None = None) -> Iterator[Step]:
    """Sort ``values`` in place, yielding steps until done or the cap (``MAX_STEPS``) is hit."""
    limit = MAX_STEPS if max_steps is None else max_steps
    for count, step in enumerate(ALGORITHMS[name](values), start=1):
        yield step
        if count >= limit:
            return


# Segments of a bar, bottom to top: only one is ever non-zero, so the bar's colour is its state.
TONES = ["info", "warn", "err", "ok"]
NAMES = ["unsorted", "compared", "swapped or written", "sorted"]
PLAIN, COMPARED, MOVED, DONE = range(4)


def bars(values: list[int], marks: dict[int, int], done: bool) -> list[list[int]]:
    out = []
    for i, v in enumerate(values):
        seg = [0, 0, 0, 0]
        seg[DONE if done else marks.get(i, PLAIN)] = v
        out.append(seg)
    return out


class Sorter:
    """One visitor's array, counters and the run in progress."""

    def __init__(self) -> None:
        self._rng = random.Random()
        self._token = 0  # bumping it tells a run in progress to stop
        self.algorithm = indah.Signal("Bubble sort")
        self.size = indah.Signal(DEFAULT_SIZE)
        self.speed = indah.Signal(4)
        self.values = indah.Signal(shuffled(DEFAULT_SIZE, self._rng))
        self.marks: indah.Signal[dict[int, int]] = indah.Signal({})
        self.done = indah.Signal(False)
        self.running = indah.Signal(False)
        self.comparisons = indah.Signal(0)
        self.swaps = indah.Signal(0)
        self.steps = indah.Signal(0)
        self.status = indah.Signal("Press Sort to start.")

    def shuffle(self, size: int | None = None) -> None:
        """Stop any run, deal a new array and zero the counters."""
        self._token += 1
        self.values.set(shuffled(self.size.peek() if size is None else size, self._rng))
        self.marks.set({})
        self.done.set(False)
        self.running.set(False)
        self.comparisons.set(0)
        self.swaps.set(0)
        self.steps.set(0)
        self.status.set("Press Sort to start.")

    async def sort(self) -> None:
        if self.running.value:
            return
        if self.done.value:
            self.shuffle()
        self._token += 1
        token = self._token
        name = self.algorithm.value
        work = list(self.values.value)
        self.running.set(True)
        self.status.set(f"{name}...")
        compares = swaps = steps = 0
        stream = run(name, work)
        exhausted = False
        try:
            while not exhausted:
                marks: dict[int, int] = {}
                per_frame, pause = SPEEDS[int(self.speed.value) - 1]
                for _ in range(per_frame):
                    step = next(stream, None)
                    if step is None:
                        exhausted = True
                        break
                    kind, a, b = step
                    steps += 1
                    if kind == "compare":
                        compares += 1
                        marks = {a: COMPARED, b: COMPARED}
                    else:
                        swaps += 1
                        marks = {a: MOVED} if kind == "write" else {a: MOVED, b: MOVED}
                if self._token != token:
                    return  # a shuffle replaced this run
                self.values.set(list(work))
                self.marks.set({} if exhausted else marks)
                self.comparisons.set(compares)
                self.swaps.set(swaps)
                self.steps.set(steps)
                if not exhausted:
                    await asyncio.sleep(pause)
            if is_sorted(work):
                self.done.set(True)
                self.status.set(f"Sorted in {steps:,} steps.")
            else:
                self.status.set(f"Stopped at the {MAX_STEPS:,} step limit.")
        finally:
            if self._token == token:
                self.running.set(False)


def build() -> indah.Session:
    s = Sorter()

    def resize() -> None:
        size = s.size.value  # the only signal this effect reads
        if size != len(s.values.peek()):
            s.shuffle(size)

    indah.effect(resize)

    controls = indah.Card(
        title="Sort",
        children=[
            indah.Select(s.algorithm, options=list(ALGORITHMS), label="Algorithm"),
            indah.Slider(s.size, min=MIN_SIZE, max=MAX_SIZE, step=5, label="Array size"),
            indah.Slider(s.speed, min=1, max=10, step=1, label="Speed"),
            indah.Row(
                children=[
                    indah.Button("Sort", on_click=s.sort),
                    indah.Button("Shuffle", on_click=s.shuffle, variant="tonal"),
                ]
            ),
            indah.Spinner(active=s.running, label="sorting..."),
            indah.Text(lambda: s.status.value),
        ],
    )

    counters = indah.Row(
        children=[
            indah.Stat(value=lambda: f"{s.comparisons.value:,}", label="Compares"),
            indah.Stat(value=lambda: f"{s.swaps.value:,}", label="Swaps / writes"),
            indah.Stat(value=lambda: f"{s.steps.value:,}", label="Steps"),
        ],
    )

    strip = indah.BarStrip(
        lambda: bars(s.values.value, s.marks.value, s.done.value),
        height=240,
        tones=TONES,
        names=NAMES,
        labels=lambda: [f"Position {i + 1}" for i in range(len(s.values.value))],
        label="Array being sorted",
    )

    intro = indah.Text(
        "# Sorting visualiser\n\n"
        "Pick an algorithm and watch it work. Pink bars are waiting, amber bars are being "
        "compared, red bars have just been swapped (or written, for merge sort), and green means "
        "sorted. "
        "Runs stop at a fixed step limit.",
        markdown=True,
    )
    return indah.Session(
        indah.Column(
            children=[
                intro,
                indah.Sidebar(
                    children=[
                        controls,
                        indah.Column(children=[counters, indah.Card(children=[strip])]),
                    ]
                ),
            ]
        )
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
