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
    before_rows = table.reactive_props()["data"]()["rows"]

    other = next(y for y in gm.YEARS if y != gm.DEFAULT_YEAR)
    session.dispatch(radio.id, "change", {"value": other})

    assert plot.reactive_props()["src"]() != before_src
    assert stat.reactive_props()["value"]() != before_stat
    assert table.reactive_props()["data"]()["rows"] != before_rows


@pytest.mark.integration
def test_the_unmatched_2025_division_renders_as_no_data():
    gm = _load_example()
    divisions = gm._load("2025")["divisions"]
    unmatched = [d for d in divisions if d["electors"] is None]
    assert unmatched  # the known ELD/boundary name-join gap (see the fetch script)
    rows = gm._table_source("2025")["rows"]
    assert any(row[1] == "no data" for row in rows)


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
