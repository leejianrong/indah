"""The stock peer-analysis example (examples/stocks.py) stays runnable.

Smoke-checks the dashboard builds and that selecting a peer in the table focuses its
metric cards (the Table-selection -> Stat pattern), all on mock data (no market feed).
"""

import importlib.util
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "stocks.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("stocks_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stat(session, label):
    return next(
        c
        for c in session._by_id.values()
        if c.type == "stat" and c.static_props()["label"] == label
    )


@pytest.mark.integration
def test_selecting_a_peer_focuses_its_metric_cards():
    stocks = _load_example()
    session = stocks.build()
    table = next(c for c in session._by_id.values() if c.type == "table")
    price = _stat(session, "Price")

    # Defaults to the first peer.
    assert price.reactive_props()["value"]() == "${:,.2f}".format(stocks.PEERS[0]["price"])

    # Clicking a row focuses that peer's metrics.
    session.dispatch(table.id, "select", {"index": 4})
    assert price.reactive_props()["value"]() == "${:,.2f}".format(stocks.PEERS[4]["price"])


@pytest.mark.integration
def test_chart_rows_are_x_plus_one_value_per_peer():
    stocks = _load_example()
    rows = stocks._chart_rows()
    assert len(rows) == stocks.MONTHS + 1  # a point per month, start inclusive
    assert all(len(r) == 1 + len(stocks.PEERS) for r in rows)  # x, then one per peer
