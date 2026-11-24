"""Compare language models: price, speed and benchmark scores, each with the chart that fits.

Tick the models to compare and pick a metric. The page draws

- a horizontal bar per model for the chosen metric (price, context window or speed);
- a bar per model for one benchmark score (or the average), chosen with a select;
- a scatter of price against average score, one dot per model, so the models worth paying for
  sit up and to the left (the frontier);
- a box and whiskers per model for how its score varies over repeated runs;
- three stat cards (cheapest, fastest, best value) and a table of every number.

The figures are **illustrative**, for made-up models, so nothing here is a claim about a real
product (real prices and scores change monthly and are measured in different ways). Swap
``MODELS`` for your own table and the page follows. Nothing is fetched at run time.

What it shows off: ``Chart`` with category bars (horizontal and vertical), a scatter built with
``chart_rows``, a box series from raw samples (``box_rows``), ``Stat`` cards, a ``Table``, and
charts that redraw when a checkbox or a select changes.

Run it with:  python examples/llm_compare.py   (prints a URL; embeds inline in a notebook cell).
"""

from __future__ import annotations

import statistics

import indah

# name -> prices in dollars per million tokens, context window in thousands of tokens, speed in
# tokens per second, the four benchmark scores (0-100), and the average score of five repeated runs.
MODELS: dict[str, dict] = {
    "Aster": {
        "input": 3.0,
        "output": 15.0,
        "context": 200,
        "speed": 62,
        "scores": {"Reasoning": 84, "Coding": 88, "Knowledge": 86, "Maths": 80},
        "runs": [84.1, 85.3, 84.8, 83.9, 85.0],
    },
    "Birch": {
        "input": 1.2,
        "output": 4.8,
        "context": 128,
        "speed": 118,
        "scores": {"Reasoning": 74, "Coding": 71, "Knowledge": 79, "Maths": 72},
        "runs": [74.0, 75.1, 73.2, 74.6, 74.4],
    },
    "Cobalt": {
        "input": 0.3,
        "output": 1.2,
        "context": 64,
        "speed": 190,
        "scores": {"Reasoning": 58, "Coding": 55, "Knowledge": 66, "Maths": 52},
        "runs": [57.0, 60.2, 55.1, 58.8, 56.4],
    },
    "Dune": {
        "input": 5.0,
        "output": 25.0,
        "context": 1000,
        "speed": 41,
        "scores": {"Reasoning": 89, "Coding": 84, "Knowledge": 91, "Maths": 87},
        "runs": [87.9, 88.4, 88.8, 87.1, 88.5],
    },
    "Ember": {
        "input": 0.6,
        "output": 2.4,
        "context": 256,
        "speed": 96,
        "scores": {"Reasoning": 69, "Coding": 77, "Knowledge": 68, "Maths": 65},
        "runs": [69.0, 70.4, 67.8, 71.1, 68.9],
    },
    "Fjord": {
        "input": 2.0,
        "output": 8.0,
        "context": 128,
        "speed": 74,
        "scores": {"Reasoning": 78, "Coding": 74, "Knowledge": 83, "Maths": 76},
        "runs": [77.6, 78.4, 77.1, 78.9, 77.8],
    },
}
BENCHMARKS = ["Reasoning", "Coding", "Knowledge", "Maths"]
# One colour per model in the scatter, fixed, so a model keeps its colour however many are shown.
COLOURS = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#b07aa1", "#76b7b2"]
COLOUR = dict(zip(MODELS, COLOURS, strict=True))
INPUT_SHARE = 0.75  # a typical call is three input tokens for every output token

# metric -> (label, unit, key, higher is better)
METRICS = {
    "input": ("Input price", "$ per 1M tokens", lambda m: m["input"], False),
    "output": ("Output price", "$ per 1M tokens", lambda m: m["output"], False),
    "context": ("Context window", "thousand tokens", lambda m: m["context"], True),
    "speed": ("Speed", "tokens per second", lambda m: m["speed"], True),
}


def blended(m: dict) -> float:
    """Dollars per million tokens for a call that is 3 parts input to 1 part output."""
    return INPUT_SHARE * m["input"] + (1 - INPUT_SHARE) * m["output"]


def average(m: dict) -> float:
    return sum(m["scores"].values()) / len(m["scores"])


def value_score(m: dict) -> float:
    """Average benchmark score per blended dollar: how much quality a dollar buys."""
    return average(m) / blended(m)


def build() -> indah.Session:
    chosen = {name: indah.Signal(True) for name in MODELS}
    metric = indah.Signal("output")
    benchmark = indah.Signal("Average")

    def names() -> list[str]:
        return [n for n in MODELS if chosen[n].value]

    def metric_rows() -> list[list]:
        _, _, key, high = METRICS[metric.value]
        pairs = sorted(((n, key(MODELS[n])) for n in names()), key=lambda p: p[1], reverse=high)
        return [[n, v] for n, v in pairs]

    def metric_title() -> str:
        label, unit, _, high = METRICS[metric.value]
        return f"{label} ({unit}, {'higher' if high else 'lower'} is better)"

    def bench_score(n: str) -> float:
        b = benchmark.value
        return round(average(MODELS[n]), 1) if b == "Average" else MODELS[n]["scores"][b]

    def bench_rows() -> list[list]:
        return sorted(([n, bench_score(n)] for n in names()), key=lambda r: -r[1])

    def scatter_rows() -> list[list]:
        # A series is fixed once the chart is built, so a model that is unticked keeps its series
        # and just has no point (a gap) until it is ticked again.
        shown = set(names())
        return indah.chart_rows(
            {n: [(blended(MODELS[n]), average(MODELS[n]))] if n in shown else [] for n in MODELS}
        )

    def spread_rows() -> list[list]:
        return indah.box_rows({n: MODELS[n]["runs"] for n in names()})

    def pick(best, key):
        pool = [n for n in names()]
        return best(pool, key=lambda n: key(MODELS[n])) if pool else None

    def stat(label, best, key, show):
        def value() -> str:
            n = pick(best, key)
            return "none selected" if n is None else n

        def help_() -> str:
            n = pick(best, key)
            return "" if n is None else show(MODELS[n])

        return indah.Stat(value=value, label=label, delta=help_)

    stats = indah.Row(
        children=[
            stat("Cheapest", min, blended, lambda m: f"${blended(m):.2f} per 1M tokens, blended"),
            stat("Fastest", max, lambda m: m["speed"], lambda m: f"{m['speed']} tokens per second"),
            stat(
                "Best value",
                max,
                value_score,
                lambda m: f"{value_score(m):.0f} score points per blended dollar",
            ),
        ]
    )

    def table_rows() -> list[dict]:
        return [
            {
                "model": n,
                "input": MODELS[n]["input"],
                "output": MODELS[n]["output"],
                "blended": round(blended(MODELS[n]), 2),
                "context": MODELS[n]["context"],
                "speed": MODELS[n]["speed"],
                "average": round(average(MODELS[n]), 1),
                "runs_sd": round(statistics.pstdev(MODELS[n]["runs"]), 2),
            }
            for n in names()
        ]

    controls = indah.Card(
        title="Compare",
        children=[
            indah.Text("Models"),
            *(indah.Checkbox(chosen[n], label=n) for n in MODELS),
            indah.Select(
                metric,
                options=[(k, v[0]) for k, v in METRICS.items()],
                label="Metric for the bar chart",
            ),
            indah.Select(benchmark, options=["Average", *BENCHMARKS], label="Benchmark"),
            indah.Text(
                "_Illustrative figures for made-up models. Not a claim about any real product._",
                markdown=True,
            ),
        ],
    )
    charts = indah.Column(
        children=[
            stats,
            indah.Text(metric_title),
            indah.Chart(
                metric_rows,
                series=[{"label": "value", "kind": "bars", "stroke": "var(--primary)"}],
                x_scale="category",
                orientation="horizontal",
                legend="off",
                height=260,
            ),
            indah.Chart(
                bench_rows,
                series=[{"label": "score", "kind": "bars", "stroke": "var(--primary)"}],
                title="Benchmark score (0 to 100, higher is better)",
                x_scale="category",
                y_range=(0, 100),
                legend="off",
                height=260,
            ),
            indah.Chart(
                scatter_rows,
                series=[
                    {"label": n, "kind": "scatter", "stroke": COLOUR[n], "size": 11} for n in MODELS
                ],
                title="Price against average score: up and to the left is better",
                x_label="blended $ per 1M tokens (3 input : 1 output)",
                y_label="average score",
                y_range=(40, 100),
                height=280,
            ),
            indah.Chart(
                spread_rows,
                series=[{"label": "average score", "kind": "box", "stroke": "var(--primary)"}],
                title="How much a model's score moves over five runs",
                x_scale="category",
                height=260,
            ),
            indah.Table(
                rows=table_rows,
                key="model",
                columns=[
                    indah.Col("model"),
                    indah.Col("input", "Input $/1M"),
                    indah.Col("output", "Output $/1M"),
                    indah.Col("blended", "Blended $/1M"),
                    indah.Col("context", "Context (K)"),
                    indah.Col("speed", "Tokens/s"),
                    indah.Col("average", "Avg score"),
                    indah.Col("runs_sd", "Run SD"),
                ],
                label="Every number",
            ),
        ]
    )
    intro = indah.Text(
        "# Compare language models\n\n"
        "Tick the models, pick a metric, and see price, speed and quality side by side. "
        "The scatter is the one to read first: a model up and to the left costs less and scores "
        "higher than the ones behind it.",
        markdown=True,
    )
    return indah.Session(indah.Column(children=[intro, indah.Sidebar(children=[controls, charts])]))


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
