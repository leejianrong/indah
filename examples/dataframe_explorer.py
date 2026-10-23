"""DataFrame explorer: filter, sort, check rows and plot them, in one small file.

Load a table, narrow it with chips and a slider, sort and search it, tick rows to compare them,
and see the distribution of any column update as you go. It is the shape of a notebook's
"look at this DataFrame" cell, as a live app: nothing reruns, only what changed redraws.

The data is **synthetic and deterministic**: 3,000 made-up cars (invented makes, a seeded random
generator, no third-party dataset), so there is nothing to download and no licence to carry. A
real app swaps ``make_cars()`` for ``pandas.read_csv(...).to_dict("records")`` and the rest of the
UI is unchanged. Needs only indah (no extra deps); the table is virtual, so it stays fast at
tens of thousands of rows.

Run it with:  python examples/dataframe_explorer.py   (prints a URL; embeds inline in a cell).
"""

from __future__ import annotations

import random
import statistics
from collections import Counter

import indah

# class: (weight kg, horsepower, mpg, price $, share of the fleet).
# These are means; each car varies around them.
CLASSES: dict[str, tuple[int, int, float, int, float]] = {
    "Hatchback": (1150, 120, 38.0, 22_000, 0.22),
    "Sedan": (1450, 165, 33.0, 31_000, 0.26),
    "SUV": (1900, 220, 26.0, 43_000, 0.26),
    "Truck": (2300, 290, 20.0, 52_000, 0.10),
    "Van": (2100, 190, 23.0, 38_000, 0.06),
    "Sports": (1350, 380, 24.0, 78_000, 0.10),
}
CLASS_NAMES = list(CLASSES)
MAKES = ["Arbor", "Birchwood", "Cobalt", "Dune", "Ember", "Fjord", "Garnet", "Harbor", "Ibis"]
MODEL_WORDS = ["Aster", "Bramble", "Cedar", "Dahlia", "Elm", "Fern", "Ginkgo", "Heath", "Iris"]
YEAR_MIN, YEAR_MAX = 2010, 2024
N_CARS = 3000
SEED = 42

# The columns the plot can show, as (field, label, unit).
METRICS: list[tuple[str, str, str]] = [
    ("mpg", "Economy", "mpg"),
    ("hp", "Power", "hp"),
    ("weight", "Weight", "kg"),
    ("price", "Price", "$"),
]
METRIC_FIELDS = [m[0] for m in METRICS]
METRIC_LABEL = {field: label for field, label, _unit in METRICS}
METRIC_UNIT = {field: unit for field, _label, unit in METRICS}
BINS = 24


def make_cars(n: int = N_CARS, seed: int = SEED) -> list[dict]:
    """``n`` made-up cars, the same ones every time for a given ``seed``."""
    rng = random.Random(seed)
    weights = [CLASSES[c][4] for c in CLASS_NAMES]
    rows = []
    for i in range(n):
        cls = rng.choices(CLASS_NAMES, weights=weights)[0]
        weight, hp, mpg, price, _share = CLASSES[cls]
        year = rng.randint(YEAR_MIN, YEAR_MAX)
        newer = (year - YEAR_MIN) / (YEAR_MAX - YEAR_MIN)  # 0 (oldest) .. 1 (newest)
        car_weight = round(rng.gauss(weight, weight * 0.07))
        car_hp = round(max(60, rng.gauss(hp * (1 + 0.12 * newer), hp * 0.12)))
        # Heavier and stronger cars drink more; newer ones drink a little less.
        car_mpg = max(8.0, rng.gauss(mpg * (1 + 0.15 * newer), mpg * 0.08))
        car_mpg *= 1 - 0.0002 * (car_hp - hp) - 0.00004 * (car_weight - weight)
        car_price = max(8_000, rng.gauss(price * (1 + 0.20 * newer), price * 0.10))
        rows.append(
            {
                "id": f"c{i:04d}",
                "make": rng.choice(MAKES),
                "model": f"{rng.choice(MODEL_WORDS)} {rng.randint(1, 9) * 100}",
                "cls": cls,
                "year": year,
                "mpg": round(car_mpg, 1),
                "hp": car_hp,
                "weight": car_weight,
                "price": round(car_price, -2),
            }
        )
    return rows


CARS = make_cars()
BY_ID = {r["id"]: r for r in CARS}


def filter_rows(rows: list[dict], classes: list[str], year_from: int) -> list[dict]:
    """The rows whose class is chosen and whose year is ``year_from`` or later."""
    chosen = set(classes)
    return [r for r in rows if r["cls"] in chosen and r["year"] >= year_from]


def class_counts(rows: list[dict], year_from: int) -> dict[str, int]:
    """How many cars each class has from ``year_from`` on (the number shown on its chip)."""
    counts = Counter(r["cls"] for r in rows if r["year"] >= year_from)
    return {c: counts.get(c, 0) for c in CLASS_NAMES}


def histogram_edges(rows: list[dict], field: str, bins: int = BINS) -> list[float]:
    """``bins + 1`` equal-width edges spanning ``field`` over ``rows`` (empty for no rows)."""
    values = [r[field] for r in rows]
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        hi = lo + 1
    step = (hi - lo) / bins
    return [lo + step * i for i in range(bins + 1)]


def histogram_counts(rows: list[dict], field: str, edges: list[float]) -> list[int]:
    """How many of ``rows`` fall in each bin of ``edges`` (the last bin includes its top edge)."""
    if not edges:
        return []
    bins = len(edges) - 1
    lo, step = edges[0], edges[1] - edges[0]
    counts = [0] * bins
    for r in rows:
        k = min(bins - 1, max(0, int((r[field] - lo) / step)))
        counts[k] += 1
    return counts


def distribution_rows(matching: list[dict], checked: list[dict], field: str) -> list[list]:
    """Rows for the chart: ``[bin middle, % of matching cars, % of ticked rows]`` per bin.

    Each line is a share of its own group, so two ticked rows are still readable beside 700 cars.
    """
    edges = histogram_edges(matching, field)
    if not edges:
        return []
    every = histogram_counts(matching, field, edges)
    picked = histogram_counts(checked, field, edges)

    def share(counts: list[int], i: int) -> float:
        total = sum(counts)
        return round(100 * counts[i] / total, 1) if total else 0.0

    return [
        [round((edges[i] + edges[i + 1]) / 2, 1), share(every, i), share(picked, i)]
        for i in range(len(every))
    ]


def summary(rows: list[dict], field: str) -> dict[str, float | None]:
    """The count, mean and median of ``field`` over ``rows`` (``None`` when there are none)."""
    values = [r[field] for r in rows]
    if not values:
        return {"count": 0, "mean": None, "median": None}
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
    }


def format_value(field: str, value: float | None) -> str:
    """A number with its unit, or a dash for none."""
    if value is None:
        return "-"
    if field == "price":
        return f"${value:,.0f}"
    if field == "mpg":
        return f"{value:.1f} mpg"
    return f"{value:,.0f} {METRIC_UNIT[field]}"


def build() -> indah.Session:
    chosen = indah.Signal(list(CLASS_NAMES))  # the class chips
    year_from = indah.Signal(YEAR_MIN)
    metric = indah.Signal("mpg")  # which column the chart and the tiles read
    checked = indah.Signal([])  # keys of the rows ticked in the table

    def matching() -> list[dict]:
        return filter_rows(CARS, chosen.value, int(year_from.value))

    def checked_rows() -> list[dict]:
        shown = {r["id"] for r in matching()}  # a ticked row that was filtered out drops out
        return [BY_ID[k] for k in checked.value if k in shown]

    def chips() -> list[dict]:
        counts = class_counts(CARS, int(year_from.value))
        return [{"value": c, "label": c, "count": counts[c]} for c in CLASS_NAMES]

    def stat(which: str):
        def value() -> str:
            s = summary(matching(), metric.value)
            return format_value(metric.value, s[which])

        return value

    intro = indah.Text(
        "# DataFrame explorer\n\n"
        "Narrow 3,000 cars with the chips and the slider, sort and search the table, and tick "
        "rows to compare them with the rest. The chart shows how the column you pick is spread "
        "across the cars that match. The data is synthetic (made-up cars, seeded), so every "
        "visit sees the same table.",
        markdown=True,
    )

    filters = indah.Card(
        title="Filter",
        children=[
            indah.Chips(chosen, options=chips, multi=True, label="Class"),
            indah.Slider(
                year_from,
                min=YEAR_MIN,
                max=YEAR_MAX,
                step=1,
                label="Model year from",
            ),
            indah.Text(
                lambda: (
                    f"{len(matching()):,} of {len(CARS):,} cars match "
                    f"(model year {int(year_from.value)} or later)."
                ),
                variant="caption",
            ),
        ],
    )

    tiles = indah.Grid(
        columns=4,
        children=[
            indah.Stat(value=lambda: f"{len(matching()):,}", label="Cars"),
            indah.Stat(value=stat("mean"), label="Average"),
            indah.Stat(value=stat("median"), label="Median"),
            indah.Stat(value=lambda: f"{len(checked_rows()):,}", label="Ticked rows"),
        ],
    )

    chart = indah.Chart(
        data=lambda: distribution_rows(matching(), checked_rows(), metric.value),
        series=["matching cars", "ticked rows"],
        title="How the cars are spread",
        x_label="value of the chosen column",
        y_label="% of the group",
        height=260,
    )

    plot = indah.Card(
        title="Plot",
        children=[
            indah.Segmented(
                metric, options=[(field, label) for field, label, _unit in METRICS], label="Column"
            ),
            tiles,
            chart,
            indah.Text(
                lambda: (
                    f"Each line is a share of its group: the ticked rows show where they sit "
                    f"among the {len(matching()):,} cars."
                    if checked_rows()
                    else "Tick a few rows in the table to draw them as a second line."
                ),
                variant="caption",
            ),
        ],
    )

    table = indah.Table(
        rows=lambda: matching(),
        key="id",
        columns=[
            indah.Col("make", "Make"),
            indah.Col("model", "Model"),
            indah.Col("cls", "Class"),
            indah.Col("year", "Year", width="7ch"),
            indah.Col("mpg", "mpg", kind="number", width="8ch"),
            indah.Col("hp", "hp", kind="number", width="8ch"),
            indah.Col("weight", "kg", kind="number", width="9ch"),
            indah.Col("price", "Price ($)", kind="number", width="11ch"),
        ],
        checked=checked,
        search=True,
        column_toggle=True,
        virtual=True,
        height="26rem",
        density="compact",
        keyboard=True,
        label="Cars",
    )

    page = indah.Column(
        children=[
            intro,
            filters,
            plot,
            indah.Card(
                title="Cars",
                children=[
                    indah.Row(
                        justify="between",
                        children=[
                            indah.Text(
                                "Click a header to sort, type to search, tick rows to compare.",
                                variant="caption",
                            ),
                            indah.Button("Clear ticked rows", lambda: checked.set([])),
                        ],
                    ),
                    table,
                ],
            ),
        ]
    )
    return indah.Session(page)


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
