"""The model-comparison example (examples/llm_compare.py): charts follow the ticks and selects."""

import importlib.util
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "llm_compare.py"
if not _EXAMPLE.exists():
    pytest.skip("examples/ not present", allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("llm_compare_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _by_type(session, type_name):
    return [c for c in session._by_id.values() if c.type == type_name]


def _charts(session):
    return _by_type(session, "chart")


def _cats(chart):
    """A category chart's labels, in the order drawn."""
    return chart.reactive_props()["xCategories"]()


@pytest.mark.integration
def test_every_chart_draws_all_models_at_first():
    ex = _load()
    session = ex.build()
    bars, bench, scatter, spread = _charts(session)
    assert _cats(bars) == [  # sorted by output price, low first
        "Cobalt",
        "Ember",
        "Birch",
        "Fjord",
        "Aster",
        "Dune",
    ]
    assert len(bench.reactive_props()["data"]()) == len(ex.MODELS)
    assert len(spread.reactive_props()["data"]()) == len(ex.MODELS)
    rows = scatter.reactive_props()["data"]()
    assert len(rows) == len(ex.MODELS) and all(sum(v is not None for v in r[1:]) == 1 for r in rows)


@pytest.mark.integration
def test_unticking_a_model_removes_it_from_every_chart_and_the_table():
    ex = _load()
    session = ex.build()
    checkbox = next(
        c for c in _by_type(session, "checkbox") if c.to_json()["props"]["label"] == "Dune"
    )
    session.dispatch(checkbox.id, "change", {"value": False})
    bars, bench, scatter, spread = _charts(session)
    assert "Dune" not in _cats(bars)
    assert "Dune" not in _cats(bench)
    assert "Dune" not in _cats(spread)
    assert len(scatter.reactive_props()["data"]()) == len(ex.MODELS) - 1
    (table,) = _by_type(session, "table")
    assert "Dune" not in str(table.to_json()["props"])


@pytest.mark.integration
def test_the_benchmark_select_changes_the_score_bars():
    ex = _load()
    session = ex.build()
    bench = _charts(session)[1]
    assert _cats(bench)[0] == "Dune"  # best average first
    select = next(
        c for c in _by_type(session, "select") if c.to_json()["props"]["label"] == "Benchmark"
    )
    session.dispatch(select.id, "change", {"value": "Coding"})
    assert _cats(bench)[0] == "Aster"  # the best coder, 88


@pytest.mark.integration
def test_the_metric_select_reorders_the_bars_and_the_caption():
    ex = _load()
    session = ex.build()
    select = next(
        c for c in _by_type(session, "select") if c.to_json()["props"]["label"].startswith("Metric")
    )
    session.dispatch(select.id, "change", {"value": "speed"})
    bars = _charts(session)[0]
    assert _cats(bars)[0] == "Cobalt"  # fastest first
    texts = [t.to_json()["props"].get("text", "") for t in _by_type(session, "text")]
    assert any("Speed" in t and "higher is better" in t for t in texts)


@pytest.mark.integration
def test_stats_name_the_cheapest_fastest_and_best_value_among_the_ticked():
    ex = _load()
    session = ex.build()
    values = [s.to_json()["props"]["value"] for s in _by_type(session, "stat")]
    assert values == ["Cobalt", "Cobalt", "Cobalt"]  # the cheap model is also the best value
    for name in ex.MODELS:  # untick all: no stat may crash
        box = next(
            c for c in _by_type(session, "checkbox") if c.to_json()["props"]["label"] == name
        )
        session.dispatch(box.id, "change", {"value": False})
    assert [s.to_json()["props"]["value"] for s in _by_type(session, "stat")] == [
        "none selected"
    ] * 3


@pytest.mark.integration
def test_the_whole_snapshot_is_json():
    import json

    ex = _load()
    session = ex.build()
    json.dumps(session.snapshot())
