"""The map-poster example (examples/map_poster.py) stays runnable.

Smoke-checks the dashboard builds, that the location/theme/frame controls actually
reshape the rendered poster, and that the embedded OSM cache decodes correctly - all
without a network call (the cache is bundled, gzip+base64, in the module itself).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "map_poster.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("map_poster_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    # dataclasses (module has `from __future__ import annotations`) resolves field
    # types via sys.modules[cls.__module__] - it must be registered before exec.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _by_type(session, type_name):
    return [c for c in session._by_id.values() if c.type == type_name]


@pytest.mark.integration
def test_every_curated_location_decodes_and_renders():
    mp = _load_example()
    assert mp.LOCATIONS  # the embedded cache isn't empty
    for slug in mp.LOCATIONS:
        fig = mp.render_poster(slug, "Porcelain", "Circle")
        assert fig.savefig  # duck-typed like indah.Plot expects


@pytest.mark.integration
def test_changing_the_location_select_re_renders_the_poster():
    mp = _load_example()
    session = mp.build()
    select = _by_type(session, "select")[0]  # location is the first Select
    plot = _by_type(session, "image")[0]

    before = plot.reactive_props()["src"]()
    other = next(slug for slug in mp.LOCATIONS if slug != mp.DEFAULT_LOCATION)
    session.dispatch(select.id, "change", {"value": other})
    after = plot.reactive_props()["src"]()
    assert before != after


@pytest.mark.integration
def test_changing_the_frame_shape_re_renders_the_poster():
    mp = _load_example()
    session = mp.build()
    radio = _by_type(session, "radio")[0]
    plot = _by_type(session, "image")[0]

    before = plot.reactive_props()["src"]()
    session.dispatch(radio.id, "change", {"value": "Square"})
    assert radio.reactive_props()["value"]() == "Square"
    after = plot.reactive_props()["src"]()
    assert before != after


@pytest.mark.integration
def test_download_produces_valid_svg_bytes():
    mp = _load_example()
    svg = mp._svg_bytes(mp.DEFAULT_LOCATION, "Noir", "Square")
    assert svg.startswith(b"<?xml") or b"<svg" in svg[:200]


@pytest.mark.unit
def test_load_caches_the_decoded_geometry():
    mp = _load_example()
    first = mp._load(mp.DEFAULT_LOCATION)
    second = mp._load(mp.DEFAULT_LOCATION)
    assert first is second  # decoded once, not on every call


@pytest.mark.unit
def test_bbox_matches_the_natural_extent_of_the_shapes():
    mp = _load_example()
    data = {
        "streets": [[[0.0, 0.0], [1.0, 1.0]]],
        "buildings": [],
        "water": [],
        "green": [],
        "center": [0.5, 0.5],
    }
    x0, x1, y0, y1 = mp._bbox(data)
    assert x0 < 0.0 and x1 > 1.0  # padded outward, not clipped to the raw extent
    assert y0 < 0.0 and y1 > 1.0
