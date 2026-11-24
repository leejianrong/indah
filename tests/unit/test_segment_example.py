"""The segmentation example's region grower and upload checks (examples/segment.py)."""

import importlib.util
import io
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "segment.py"
if not _EXAMPLE.exists():  # an sdist carries no examples/
    pytest.skip("examples/ not present", allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("segment_example_app", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ex = _load()


def _two_blocks():
    img = np.zeros((20, 40, 3), dtype=np.uint8)
    img[:, :20] = (200, 30, 30)
    img[:, 20:] = (30, 30, 200)
    return img


@pytest.mark.unit
def test_a_region_stops_at_a_colour_edge():
    region = ex.grow_region(_two_blocks(), (5, 5), 20)
    assert region[:, :20].all() and not region[:, 20:].any()


@pytest.mark.unit
def test_a_looser_tolerance_crosses_the_edge():
    assert ex.grow_region(_two_blocks(), (5, 5), 400).all()


@pytest.mark.unit
def test_a_box_fences_the_region_and_a_seed_outside_it_finds_nothing():
    img = np.full((20, 40, 3), 100, dtype=np.uint8)
    region = ex.grow_region(img, (10, 10), 10, box=(5, 5, 15, 15))
    assert region.sum() == 100 and region[5:15, 5:15].all()
    assert not ex.grow_region(img, (30, 10), 10, box=(5, 5, 15, 15)).any()


@pytest.mark.unit
def test_a_disconnected_patch_of_the_same_colour_is_not_joined():
    img = np.zeros((10, 30, 3), dtype=np.uint8)
    img[:, 10:15] = 255  # a wall splits two black halves
    region = ex.grow_region(img, (2, 5), 10)
    assert region[:, :10].all() and not region[:, 15:].any()


@pytest.mark.unit
def test_the_samples_have_distinct_regions():
    img = ex.make_sample("shapes")
    assert img.shape == (240, 320, 3)
    disc = ex.grow_region(img, (90, 90), ex.TOLERANCE_DEFAULT)
    assert 0.05 < disc.mean() < 0.25 and not disc[10, 300]


def _png(w, h):
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (w, h), (1, 2, 3)).save(out, format="PNG")
    return out.getvalue()


@pytest.mark.unit
def test_uploads_are_checked_and_shrunk():
    big = ex.load_upload(_png(900, 450), "image/png")
    assert big.shape == (160, 320, 3)
    with pytest.raises(ValueError, match="JPEG"):
        ex.load_upload(b"x", "text/plain")
    with pytest.raises(ValueError, match="not a picture"):
        ex.load_upload(b"not an image", "image/png")
    with pytest.raises(ValueError, match="MB"):
        ex.load_upload(b"0" * (ex.MAX_UPLOAD + 1), "image/png")
