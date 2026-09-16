"""The pretty-map example (examples/prettymap.py) stays runnable.

Smoke-checks the generator renders a deterministic SVG from the controls, that the
seed changes the output, and that the app wires the controls + image + download.
"""

import importlib.util
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "prettymap.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("prettymap_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
def test_render_map_is_deterministic_svg_that_responds_to_the_seed():
    pm = _load_example()
    a = pm.render_map("Kuala Lumpur", "Peach", "Circle", 6, 7)
    assert a.startswith("<svg") and a.rstrip().endswith("</svg>")
    assert "Kuala Lumpur" in a  # the place label is drawn
    assert a == pm.render_map("Kuala Lumpur", "Peach", "Circle", 6, 7)  # deterministic
    assert a != pm.render_map("Kuala Lumpur", "Peach", "Circle", 6, 8)  # seed changes it


@pytest.mark.integration
def test_app_wires_controls_image_and_download():
    pm = _load_example()
    session = pm.build()
    types = {c.type for c in session._by_id.values()}
    assert {"image", "download", "select", "slider", "radio", "textinput"} <= types
