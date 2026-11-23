"""Sparkline, TickStrip and the Stat extensions (IND-263)."""

import pytest

import indah
from indah import Col, Signal, Sparkline, Stat, TickStrip, spark_values, tick_states
from indah.protocol import SPEC_COMPONENTS

pytestmark = pytest.mark.unit


def test_spark_values_keep_finite_numbers_and_gaps_and_ride_a_table_cell():
    v = spark_values([1, 2.5, None, float("nan"), float("inf"), 4])
    assert list(v) == [1, 2.5, None, None, None, 4]
    assert len(spark_values(range(900))) == 500 and spark_values(range(900))[-1] == 899  # the last
    for bad in (["x"], [True]):
        with pytest.raises(ValueError, match="number"):
            spark_values(bad)
    # A table row carries it as nested data, not as text.
    table = indah.Table(rows=[{"name": "a", "trend": spark_values([1, 2, 3])}], key="name")
    assert table.to_json()["props"]["rows"][0]["trend"] == [1, 2, 3]


def test_tick_states_accept_words_booleans_and_none():
    assert list(tick_states(["ok", True, False, None, "warn", "err", "neutral"])) == [
        "ok", "ok", "err", "neutral", "warn", "err", "neutral",
    ]  # fmt: skip
    with pytest.raises(ValueError, match="state"):
        tick_states(["fine"])
    assert len(tick_states(["ok"] * 900)) == 200 and True


def test_a_table_cell_may_bind_the_new_components():
    assert SPEC_COMPONENTS["sparkline"] == frozenset({"values", "tone"})
    assert SPEC_COMPONENTS["ticks"] == frozenset({"states"})
    col = Col(
        "trend",
        kind="cell",
        render={"component": "sparkline", "bind": {"values": "trend", "tone": "tone"}},
    )
    assert col.wire()["render"]["component"] == "sparkline"
    with pytest.raises(ValueError):
        Col("t", kind="cell", render={"component": "sparkline", "bind": {"color": "x"}})


def test_sparkline_and_tickstrip_components():
    s = Sparkline([1, 2, 3], tone="ok", fill=True, height=30, label="Cost")
    props = s.to_json()["props"]
    assert s.type == "sparkline" and props["values"] == [1, 2, 3] and props["tone"] == "ok"
    assert props["fill"] is True and props["height"] == 30 and props["label"] == "Cost"
    live = Signal([1, 2])
    sp = Sparkline(live)
    live.set([5, 6, 7])
    assert sp.reactive_props()["values"]() == [5, 6, 7]
    t = TickStrip(["ok", "err"], label="Last runs")
    assert t.type == "ticks" and t.to_json()["props"]["states"] == ["ok", "err"]
    for kwargs in ({"tone": "loud"}, {"height": 0}, {"height": 200}, {"color": "url(x)"}):
        with pytest.raises(ValueError):
            Sparkline([1], **kwargs)


def test_stat_takes_delta_good_tone_and_spark():
    plain = Stat("1").to_json()["props"]
    assert "deltaGood" not in plain and "tone" not in plain and "spark" not in plain
    s = Stat("9", delta="-3%", delta_good=True, tone="warn", spark=[1, 2, 3])
    props = s.to_json()["props"]
    assert props["deltaGood"] is True and props["tone"] == "warn" and props["spark"] == [1, 2, 3]
    live = Signal([1, 2])
    st = Stat("1", spark=live, delta_good=lambda: False, tone=lambda: "err")
    assert st.reactive_props()["spark"]() == [1, 2]
    assert st.reactive_props()["deltaGood"]() is False and st.reactive_props()["tone"]() == "err"
    with pytest.raises(ValueError):
        Stat("1", tone="loud")
