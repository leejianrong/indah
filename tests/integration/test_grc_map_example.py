"""The GRC-map example (examples/grc_map.py) stays runnable.

Smoke-checks the dashboard builds, that switching the election year re-renders the
choropleth and the stats/table, and that the embedded electoral-boundary cache
decodes correctly - all without a network call (the cache is bundled, gzip+base64, in
the module itself, per data.gov.sg / ELD).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "grc_map.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("grc_map_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _by_type(session, type_name):
    return [c for c in session._by_id.values() if c.type == type_name]


@pytest.mark.integration
def test_every_curated_year_decodes_and_renders():
    gm = _load_example()
    assert gm.YEARS  # the embedded cache isn't empty
    for year in gm.YEARS:
        fig = gm.render_choropleth(year)
        assert fig.savefig  # duck-typed like indah.Plot expects


@pytest.mark.integration
def test_changing_the_year_radio_updates_map_stats_and_table():
    gm = _load_example()
    session = gm.build()
    radio = _by_type(session, "radio")[0]
    plot = _by_type(session, "image")[0]
    stat = _by_type(session, "stat")[0]  # "Total electors"
    table = _by_type(session, "table")[0]

    before_src = plot.reactive_props()["src"]()
    before_stat = stat.reactive_props()["value"]()
    before_rows = table.reactive_props()["rows"]()

    other = next(y for y in gm.YEARS if y != gm.DEFAULT_YEAR)
    session.dispatch(radio.id, "change", {"value": other})

    assert plot.reactive_props()["src"]() != before_src
    assert stat.reactive_props()["value"]() != before_stat
    assert table.reactive_props()["rows"]() != before_rows


@pytest.mark.integration
def test_the_unmatched_2025_division_renders_as_no_data():
    gm = _load_example()
    divisions = gm._load("2025")["divisions"]
    unmatched = [d for d in divisions if d["electors"] is None]
    assert unmatched  # the known ELD/boundary name-join gap (see the fetch script)
    rows = gm._table_rows("2025")
    assert any(row["electors"] == "no data" for row in rows)


@pytest.mark.unit
def test_load_caches_the_decoded_geometry():
    gm = _load_example()
    first = gm._load(gm.DEFAULT_YEAR)
    second = gm._load(gm.DEFAULT_YEAR)
    assert first is second  # decoded once, not on every call


@pytest.mark.unit
def test_global_domain_spans_every_cached_year():
    gm = _load_example()
    vmin, vmax = gm._global_domain()
    all_values = [
        d["electors"]
        for year in gm.YEARS
        for d in gm._load(year)["divisions"]
        if d["electors"] is not None
    ]
    assert vmin == min(all_values)
    assert vmax == max(all_values)


@pytest.mark.integration
def test_table_columns_are_sized_to_fit_a_phone():
    """The division column is clipped at 18ch (full name on hover) and the number column has a short
    header, so both columns fit a 390px viewport with no sideways scroll (IND-178). Measured in a
    real browser at the time; this pins the two knobs that decide it."""
    gm = _load_example()
    name, electors = gm._TABLE_COLUMNS
    assert name.truncate is True
    assert name.max_width == "18ch"
    assert len(electors.title) <= 10  # "Electors", not "Registered electors"


@pytest.mark.integration
def test_colourbar_ticks_are_few_and_readable():
    """The ticks used to run together ("100000120000140000"): few of them, with a compact format."""
    gm = _load_example()
    fig = gm.render_choropleth(gm.DEFAULT_YEAR)
    cbar_ax = fig.axes[-1]
    fig.canvas.draw()
    labels = [t.get_text() for t in cbar_ax.get_xticklabels() if t.get_text()]
    assert 3 <= len(labels) <= 6
    assert all(len(label) <= 5 for label in labels), labels  # e.g. "100k", never "100000"
    assert any(label.endswith("k") for label in labels)


@pytest.mark.integration
def test_no_data_is_distinct_from_the_low_end_and_is_in_the_legend():
    gm = _load_example()
    fig = gm.render_choropleth(gm.DEFAULT_YEAR)
    assert gm.NO_DATA_COLOR.lower() not in {gm.RAMP_LOW.lower(), "#d8d2c8"}  # not the old beige
    legend_texts = [t.get_text() for t in fig.texts] + [
        t.get_text() for ax in fig.axes for t in ax.texts
    ]
    legend = fig.axes[0].get_legend()
    if legend is not None:
        legend_texts += [t.get_text() for t in legend.get_texts()]
    assert any("no data" in t.lower() for t in legend_texts)


@pytest.mark.integration
def test_division_outlines_are_light_not_heavy():
    gm = _load_example()
    fig = gm.render_choropleth(gm.DEFAULT_YEAR)
    coll = fig.axes[0].collections[0]
    assert max(coll.get_linewidths()) <= 0.3
    edge = coll.get_edgecolor()[0][:3]
    assert sum(edge) / 3 > 0.7  # a pale line between fills, not black ink
