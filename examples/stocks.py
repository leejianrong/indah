"""Stock peer analysis: normalized price, peer-average comparison, and best/worst.

A single-file indah dashboard modeled on Streamlit's demo-stockpeers layout
(docs/DEMOS-DOCS-ROUND2.md A7): a normalized-price hero chart (every peer rebased to
100 at the start of the chosen window), a small-multiples grid comparing each peer to
the group's average, an over/under-performance chart (delta vs. that average), and
best/worst tiles - with a ticker multiselect and a time-horizon picker driving all of
it, plus a raw price table.

All numbers are illustrative **mock data** - there is no market feed. A real app swaps
the ``PEERS`` block (and ``_full_series``) for a data source behind the same shape, and
the rest of the UI is unchanged. Needs only indah (no extra deps).

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
TICKERS = [p["ticker"] for p in PEERS]
BY_TICKER = {p["ticker"]: p for p in PEERS}

FULL_WEEKS = 52  # one year of weekly closes, so every horizon below is a slice of it.
HORIZONS: list[tuple[str, str, int]] = [
    ("1m", "1M", 4),
    ("3m", "3M", 13),
    ("6m", "6M", 26),
    ("1y", "1Y", FULL_WEEKS),
]
HORIZON_WEEKS = {key: weeks for key, _label, weeks in HORIZONS}
DEFAULT_HORIZON = "1y"


def _full_series(ret: float, seed: int) -> list[float]:
    """A synthetic weekly price path over one year: starts at 100, ends near 100*(1+ret)."""
    rng = random.Random(seed)
    start, end = 100.0, 100.0 * (1.0 + ret)
    pts = [start]
    for i in range(1, FULL_WEEKS + 1):
        drift = start + (end - start) * (i / FULL_WEEKS)
        pts.append(round(drift + rng.uniform(-3.0, 3.0), 2))
    pts[-1] = round(end, 2)  # pin the end to the stated 1-year return
    return pts


SERIES = {p["ticker"]: _full_series(p["ret"], seed=i) for i, p in enumerate(PEERS)}


def _window(ticker: str, weeks: int) -> list[float]:
    """The ticker's last `weeks` closes, rebased to 100 at the window's start."""
    closes = SERIES[ticker][-(weeks + 1) :]
    base = closes[0]
    return [round(c / base * 100.0, 2) for c in closes]


def _peer_average(tickers: list[str], weeks: int) -> list[float]:
    """The elementwise mean of `tickers`' normalized windows - the comparison baseline."""
    windows = [_window(t, weeks) for t in tickers]
    n = len(windows[0])
    return [round(sum(w[i] for w in windows) / len(windows), 2) for i in range(n)]


def _hero_rows(active: list[str], weeks: int) -> list[list[float | None]]:
    """Rows for the hero chart: one column per ticker in TICKERS order, ``None`` for a
    deselected ticker so its line drops out without changing the chart's series count
    (indah's Chart fixes its series/legend at construction; hiding via ``None`` values
    is the seam that works within that, since a structural children op is deferred)."""
    cols = {t: _window(t, weeks) for t in active}
    return [[i] + [cols[t][i] if t in cols else None for t in TICKERS] for i in range(weeks + 1)]


def _delta_rows(active: list[str], weeks: int) -> list[list[float | None]]:
    """Rows for the over/under chart: each active ticker's normalized price minus the
    peer average (positive = outperforming the group, negative = underperforming)."""
    avg = _peer_average(active, weeks)
    cols = {t: _window(t, weeks) for t in active}
    return [
        [i] + [round(cols[t][i] - avg[i], 2) if t in cols else None for t in TICKERS]
        for i in range(weeks + 1)
    ]


def _multiple_rows(ticker: str, active: list[str], weeks: int) -> list[list[float]]:
    """Rows for one small-multiple: [week, this ticker, peer average]."""
    own = _window(ticker, weeks)
    avg = _peer_average(active, weeks)
    return [[i, own[i], avg[i]] for i in range(weeks + 1)]


def _returns(active: list[str], weeks: int) -> dict[str, float]:
    return {t: _window(t, weeks)[-1] / 100.0 - 1.0 for t in active}


def _table_source() -> dict:
    return {
        "columns": ["Ticker", "Company", "Price", "Mkt cap ($B)", "P/E", "1Y %"],
        "rows": [
            [p["ticker"], p["name"], p["price"], p["cap"], p["pe"], round(p["ret"] * 100, 1)]
            for p in PEERS
        ],
    }


def build() -> indah.Session:
    selected = indah.Signal(list(TICKERS))  # tickers shown on the hero/delta/multiples
    horizon = indah.Signal(DEFAULT_HORIZON)
    focus = indah.Signal(0)  # index of the focused peer in the full table

    def active() -> list[str]:
        return selected.value or list(TICKERS)  # never empty, or the average is undefined

    def weeks() -> int:
        return HORIZON_WEEKS[horizon.value]

    def focused() -> dict:
        return PEERS[focus.value if focus.value is not None else 0]

    header = indah.Text(lambda: f"{focused()['name']} ({focused()['ticker']})")
    metrics = indah.Row(
        children=[
            indah.Stat(value=lambda: f"${focused()['price']:,.2f}", label="Price"),
            indah.Stat(value=lambda: f"${focused()['cap']:,}B", label="Market cap"),
            indah.Stat(value=lambda: f"{focused()['pe']:.1f}", label="P/E"),
            indah.Stat(value=lambda: f"{focused()['ret'] * 100:+.1f}%", label="1-year return"),
        ],
    )

    controls = indah.Row(
        children=[
            indah.MultiSelect(
                selected,
                options=[(t, f"{t} - {BY_TICKER[t]['name']}") for t in TICKERS],
                label="Peers to compare",
            ),
            indah.Radio(horizon, options=[(k, lbl) for k, lbl, _w in HORIZONS], label="Horizon"),
        ]
    )

    hero = indah.Chart(
        data=lambda: _hero_rows(active(), weeks()),
        series=TICKERS,
        title="Normalized price (start of window = 100)",
        x_label="week",
        y_label="index",
        height=280,
    )

    delta = indah.Chart(
        data=lambda: _delta_rows(active(), weeks()),
        series=TICKERS,
        title="Over / under the peer average",
        x_label="week",
        y_label="index pts vs. average",
        height=220,
    )

    def best_worst_stat(pick) -> tuple[str, str]:
        rets = _returns(active(), weeks())
        ticker = pick(rets, key=rets.get)
        return ticker, f"{ticker} {rets[ticker] * 100:+.1f}%"

    best_worst = indah.Row(
        children=[
            indah.Stat(value=lambda: best_worst_stat(max)[1], label="Best performer"),
            indah.Stat(value=lambda: best_worst_stat(min)[1], label="Worst performer"),
        ]
    )

    multiples = indah.Grid(
        columns=3,
        children=[
            indah.Card(
                title=f"{t} vs. peer average",
                children=[
                    indah.Chart(
                        data=lambda t=t: _multiple_rows(t, active(), weeks()),
                        series=[t, "peer avg"],
                        height=160,
                    )
                ],
            )
            for t in TICKERS
        ],
    )

    table = indah.Table(_table_source(), selected=focus, label="Peer group")

    intro = indah.Text(
        "# Stock peer analysis\n\n"
        "Pick a horizon and the peers to compare: the hero chart rebases every price "
        "to 100 at the start of the window, the second chart shows who's beating the "
        "group average, and the tiles call out the best and worst performer. Click a "
        "row in the table below to focus its metric cards. All figures are "
        "illustrative mock data.",
        markdown=True,
    )
    page = indah.Column(
        children=[
            intro,
            indah.Card(children=[controls]),
            indah.Card(children=[hero]),
            indah.Card(children=[best_worst, delta]),
            indah.Card(title="Each peer vs. the group", children=[multiples]),
            indah.Card(title="Focus company", children=[header, metrics]),
            indah.Card(title="Peers", children=[table]),
        ]
    )
    return indah.Session(page)


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
