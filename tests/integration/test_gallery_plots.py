"""Server-drawn gallery plots keep a transparent background (IND-177).

A Matplotlib figure is saved as a PNG, which has no idea whether the page is light or dark. A white
figure shows as a light box on the dark page, so the demos draw on a transparent background with
mid-grey text that reads on both. Skipped without matplotlib, like the other demo tests.
"""

import importlib.util
import io
import sys
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")
image = pytest.importorskip("matplotlib.image")

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_plot_example", _EXAMPLES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses looks the module up by name
    spec.loader.exec_module(module)
    return module


def _png(fig):
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")  # exactly what indah.Plot does
    buffer.seek(0)
    return image.imread(buffer, format="png")


def _assert_transparent_margin(pixels):
    assert pixels.shape[2] == 4, "the PNG has no alpha channel"
    assert pixels[0, 0, 3] == 0, "the corner is opaque: the figure background is not transparent"
    assert pixels[..., 3].max() > 0, "the figure drew nothing"


def test_the_line_plot_is_transparent():
    _assert_transparent_margin(_png(_load("charts")._sine_figure()))


def test_the_heatmap_margin_is_transparent():
    _assert_transparent_margin(_png(_load("charts")._heatmap_figure()))


def test_the_prediction_bars_are_transparent():
    fig = _load("upload_classify")._predictions_chart([("tabby cat", 0.8), ("tiger cat", 0.1)])
    _assert_transparent_margin(_png(fig))


def test_the_svg_cards_are_not_a_light_box():
    """The audio waveform and the plot fallback note are SVG: no opaque cream card either."""
    import urllib.parse

    np = pytest.importorskip("numpy")
    svg = urllib.parse.unquote(
        _load("audio_analysis")._waveform_svg(np.zeros(100)).split(",", 1)[1]
    )
    note = urllib.parse.unquote(
        _load("charts")._svg_note("hi").reactive_props()["src"]().split(",", 1)[1]
    )
    for text in (svg, note):
        assert "#f3ebe0" not in text, "an opaque light card shows as a white box on the dark page"
