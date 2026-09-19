"""The stock peer-analysis example (examples/stocks.py) stays runnable.

Smoke-checks the dashboard builds, that selecting a peer in the table focuses its
metric cards (the Table-selection -> Stat pattern), and that the multiselect/horizon
controls actually reshape the hero/delta chart data - all on mock data (no market
feed).
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


def _by_type(session, type_name):
    return [c for c in session._by_id.values() if c.type == type_name]


def _stat(session, label):
    return next(c for c in _by_type(session, "stat") if c.static_props()["label"] == label)


@pytest.mark.integration
def test_selecting_a_peer_focuses_its_metric_cards():
    stocks = _load_example()
    session = stocks.build()
    table = _by_type(session, "table")[0]
    price = _stat(session, "Price")

    # Defaults to the first peer.
    assert price.reactive_props()["value"]() == "${:,.2f}".format(stocks.PEERS[0]["price"])

    # Clicking a row focuses that peer's metrics.
    session.dispatch(table.id, "select", {"index": 4})
    assert price.reactive_props()["value"]() == "${:,.2f}".format(stocks.PEERS[4]["price"])


@pytest.mark.integration
def test_hero_chart_masks_a_deselected_ticker():
    stocks = _load_example()
    session = stocks.build()
    hero = _by_type(session, "chart")[0]  # the hero chart is built first
    multiselect = _by_type(session, "multiselect")[0]
    dropped = stocks.TICKERS[0]

    session.dispatch(
        multiselect.id, "change", {"value": [t for t in stocks.TICKERS if t != dropped]}
    )
    rows = hero.reactive_props()["data"]()
    col = stocks.TICKERS.index(dropped) + 1  # +1: column 0 is the week index
    assert all(row[col] is None for row in rows)
    other_col = stocks.TICKERS.index(stocks.TICKERS[1]) + 1
    assert all(row[other_col] is not None for row in rows)


@pytest.mark.integration
def test_horizon_radio_changes_the_chart_window():
    stocks = _load_example()
    session = stocks.build()
    hero = _by_type(session, "chart")[0]
    radio = _by_type(session, "radio")[0]

    assert len(hero.reactive_props()["data"]()) == stocks.FULL_WEEKS + 1  # default: 1Y

    session.dispatch(radio.id, "change", {"value": "1m"})
    assert len(hero.reactive_props()["data"]()) == stocks.HORIZON_WEEKS["1m"] + 1


@pytest.mark.unit
def test_window_rebases_every_series_to_100_at_its_start():
    stocks = _load_example()
    for ticker in stocks.TICKERS:
        assert stocks._window(ticker, 13)[0] == 100.0


@pytest.mark.unit
def test_delta_is_zero_at_the_start_of_the_window():
    stocks = _load_example()
    rows = stocks._delta_rows(stocks.TICKERS, 13)
    assert rows[0] == [0] + [0.0] * len(stocks.TICKERS)  # every peer starts at the average


@pytest.mark.unit
def test_active_falls_back_to_every_ticker_when_selection_is_empty():
    stocks = _load_example()
    session = stocks.build()
    multiselect = _by_type(session, "multiselect")[0]
    session.dispatch(multiselect.id, "change", {"value": []})
    hero = _by_type(session, "chart")[0]
    rows = hero.reactive_props()["data"]()
    assert all(v is not None for row in rows for v in row[1:])
