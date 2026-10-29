"""Frame, Cell, Grid track lists and height="fill" (ADR-0046)."""

import pytest

import indah
from indah.protocol import BUILTIN_TYPES


@pytest.mark.unit
def test_frame_wire_props_and_defaults():
    frame = indah.Frame([indah.Text("x")], rows="56px 1fr 196px", kiosk=True, fit="shrink")
    assert frame.to_json()["props"] == {
        "width": 1920,
        "height": 1080,
        "tracks": "1fr",
        "gap": "1rem",
        "padding": "1.25rem",
        "rows": "56px 1fr 196px",
        "fit": "shrink",
        "kiosk": True,
    }
    plain = indah.Frame().to_json()["props"]
    assert "fit" not in plain and "kiosk" not in plain and "rows" not in plain


@pytest.mark.unit
@pytest.mark.parametrize("bad", [0, 199, 8001, 1920.5, True, "1920"])
def test_frame_rejects_bad_sizes(bad):
    with pytest.raises(ValueError, match="width"):
        indah.Frame(width=bad)


@pytest.mark.unit
def test_frame_rejects_unknown_fit():
    with pytest.raises(ValueError, match="fit"):
        indah.Frame(fit="cover")
    assert indah.Frame(fit="width").to_json()["props"]["fit"] == "width"


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    ["1fr; color: red", "1fr}", "url(x)", "1fr /* */", "calc(1px+1px)", "", "  ", "1 fr", "9" * 3],
)
def test_track_lists_refuse_anything_that_is_not_a_track_size(value):
    with pytest.raises(ValueError):
        indah.Grid(columns=value)
    with pytest.raises(ValueError):
        indah.Frame(rows=value)


@pytest.mark.unit
def test_track_lists_accept_the_usual_sizes_and_normalise_spaces():
    props = indah.Grid(columns="760px   minmax(0, 1fr)  auto", rows="auto 1fr").to_json()["props"]
    assert props["tracks"] == "760px minmax(0, 1fr) auto"
    assert props["rows"] == "auto 1fr"
    assert "columns" not in props


@pytest.mark.unit
def test_grid_with_a_count_is_unchanged_on_the_wire():
    assert indah.Grid(columns=3).to_json()["props"] == {"gap": "1rem", "columns": 3}


@pytest.mark.unit
def test_frame_gap_and_padding_are_lengths():
    for field in ("gap", "padding"):
        with pytest.raises(ValueError, match=field):
            indah.Frame(**{field: "1rem; color: red"})
    assert indah.Frame(gap="16px", padding="20px").to_json()["props"]["gap"] == "16px"


@pytest.mark.unit
def test_cell_spans():
    assert indah.Cell().to_json()["props"] == {}
    assert indah.Cell(columns=2, rows=3).to_json()["props"] == {"columns": 2, "rows": 3}
    for bad in (0, 25, 1.5, True):
        with pytest.raises(ValueError):
            indah.Cell(columns=bad)


@pytest.mark.unit
def test_chart_and_heatmap_accept_fill_and_reject_junk_heights():
    assert indah.Chart([[0, 1]], series=["y"], height="fill").to_json()["props"]["height"] == "fill"
    assert indah.Heatmap([[0.0]], height="fill").to_json()["props"]["height"] == "fill"
    assert indah.Chart([[0, 1]], series=["y"], height=180).to_json()["props"]["height"] == 180
    for bad in ("tall", 10, None, True):
        with pytest.raises(ValueError, match="height"):
            indah.Chart([[0, 1]], series=["y"], height=bad)


@pytest.mark.unit
def test_new_container_types_are_reserved_for_the_shell():
    assert {"frame", "cell"} <= BUILTIN_TYPES
    with pytest.raises(ValueError, match="built-in"):
        indah.register_component("frame", render={"tag": "div"})
