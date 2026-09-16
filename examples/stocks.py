"""Stock peer analysis: compare a peer group's price, valuation, and 1-year return.

A single-file indah dashboard. Pick a company in the table and the metric cards and
the header retitle to that company; a client-side ``Chart`` shows each peer's
normalized 1-year price path so relative performance reads at a glance.

All numbers are illustrative **mock data** - there is no market feed. A real app swaps
the ``PEERS`` block (and ``_series``) for a data source behind the same shape, and the
rest of the UI is unchanged (ADR-0009). Needs only indah (no extra deps).

Run it with:  python examples/stocks.py   (prints a URL; embeds inline in a cell).
"""

from __future__ import annotations

import random

import indah

# Illustrative peer set (mock data): price in $, market cap in $B, P/E, 1-year return.
PEERS = [
    {"ticker": "AAPL", "name": "Apple", "price": 227.52, "cap": 3450, "pe": 34.8, "ret": 0.28},
    {"ticker": "MSFT", "name": "Microsoft", "price": 416.21, "cap": 3090, "pe": 36.1, "ret": 0.19},
    {"ticker": "GOOGL", "name": "Alphabet", "price": 168.44, "cap": 2070, "pe": 24.6, "ret": 0.31},
    {"ticker": "AMZN", "name": "Amazon", "price": 185.94, "cap": 1930, "pe": 42.3, "ret": 0.22},
    {"ticker": "META", "name": "Meta", "price": 563.70, "cap": 1430, "pe": 27.9, "ret": 0.55},
    {"ticker": "NVDA", "name": "NVIDIA", "price": 121.40, "cap": 2980, "pe": 58.2, "ret": 1.42},
]

MONTHS = 12  # the price window: 13 points, month 0..12 (start = 100).


def _series(ret: float, seed: int) -> list[float]:
    """A synthetic normalized price path: starts at 100, lands near 100*(1+ret)."""
    rng = random.Random(seed)
    start, end = 100.0, 100.0 * (1.0 + ret)
    pts = [start]
    for i in range(1, MONTHS + 1):
        drift = start + (end - start) * (i / MONTHS)
        pts.append(round(drift + rng.uniform(-4.0, 4.0), 2))
    pts[-1] = round(end, 2)  # pin the end to the stated return
    return pts


SERIES = {p["ticker"]: _series(p["ret"], seed=i) for i, p in enumerate(PEERS)}


def _chart_rows() -> list[list[float]]:
    """Rows for the Chart: ``[[month, s0, s1, ...], ...]`` (x first, then each peer)."""
    return [[m] + [SERIES[p["ticker"]][m] for p in PEERS] for m in range(MONTHS + 1)]


def _table_source() -> dict:
    return {
        "columns": ["Ticker", "Company", "Price", "Mkt cap ($B)", "P/E", "1Y %"],
        "rows": [
            [p["ticker"], p["name"], p["price"], p["cap"], p["pe"], round(p["ret"] * 100, 1)]
            for p in PEERS
        ],
    }


def build() -> indah.Session:
    selected = indah.Signal(0)  # index of the focused peer; a table click sets it

    def focus() -> dict:
        i = selected.value if selected.value is not None else 0
        return PEERS[i]

    header = indah.Text(lambda: f"{focus()['name']} ({focus()['ticker']})")
    metrics = indah.Row(
        children=[
            indah.Stat(value=lambda: f"${focus()['price']:,.2f}", label="Price"),
            indah.Stat(value=lambda: f"${focus()['cap']:,}B", label="Market cap"),
            indah.Stat(value=lambda: f"{focus()['pe']:.1f}", label="P/E"),
            indah.Stat(value=lambda: f"{focus()['ret'] * 100:+.1f}%", label="1-year return"),
        ],
    )

    chart = indah.Chart(
        data=_chart_rows(),
        series=[p["ticker"] for p in PEERS],
        title="Normalized 1-year price (start = 100)",
        x_label="month",
        y_label="index",
        height=280,
    )

    table = indah.Table(_table_source(), selected=selected, label="Peer group")

    intro = indah.Text(
        "# Stock peer analysis\n\n"
        "Click a company in the table to focus the metric cards. Each line is that "
        "peer's price over the last year, normalized to 100 at the start so relative "
        "performance reads at a glance. All figures are illustrative mock data.",
        markdown=True,
    )
    page = indah.Column(
        children=[
            intro,
            indah.Card(title="Focus company", children=[header, metrics]),
            indah.Card(children=[chart]),
            indah.Card(title="Peers", children=[table]),
        ]
    )
    return indah.Session(page)


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
