import pytest

from indah.components import (
    Button,
    Checkbox,
    Column,
    DataFrame,
    Date,
    Image,
    MultiSelect,
    Number,
    Plot,
    Radio,
    Select,
    Slider,
    Text,
    TextInput,
    walk,
)
from indah.reactive import Signal


@pytest.mark.unit
def test_text_to_json_reads_source():
    s = Signal("hi")
    t = Text(s)
    t.id = "n0"
    node = t.to_json()
    assert node == {"id": "n0", "type": "text", "props": {"text": "hi"}, "children": []}


@pytest.mark.unit
def test_slider_static_and_reactive_props():
    v = Signal(4)
    sl = Slider(v, min=0, max=10, step=2, label="a")
    sl.id = "n1"
    node = sl.to_json()
    assert node["type"] == "slider"
    assert node["props"] == {"min": 0, "max": 10, "step": 2, "label": "a", "value": 4}


@pytest.mark.unit
def test_slider_input_event_sets_signal():
    v = Signal(0)
    sl = Slider(v)
    assert sl.handle("input", {"value": 7}) is True
    assert v.peek() == 7


@pytest.mark.unit
def test_slider_ignores_unknown_event():
    v = Signal(0)
    sl = Slider(v)
    assert sl.handle("click", {}) is False
    assert v.peek() == 0


@pytest.mark.unit
def test_button_click_calls_handler():
    calls = []
    b = Button("go", on_click=lambda: calls.append(1))
    assert b.handle("click", {}) is True
    assert calls == [1]


@pytest.mark.unit
def test_walk_is_preorder():
    leaf1 = Text("x")
    leaf2 = Text("y")
    root = Column(children=[leaf1, leaf2])
    assert list(walk(root)) == [root, leaf1, leaf2]


# -- Select ------------------------------------------------------------------


@pytest.mark.unit
def test_select_normalises_options_and_serialises():
    v = Signal("b")
    sel = Select(v, options=["a", ("b", "Bee"), "c"], label="pick")
    sel.id = "n0"
    props = sel.to_json()["props"]
    assert props["value"] == "b"
    assert props["label"] == "pick"
    assert props["options"] == [
        {"value": "a", "label": "a"},
        {"value": "b", "label": "Bee"},
        {"value": "c", "label": "c"},
    ]


@pytest.mark.unit
def test_select_change_event_sets_signal():
    v = Signal("a")
    sel = Select(v, options=["a", "b"])
    assert sel.handle("change", {"value": "b"}) is True
    assert v.peek() == "b"


@pytest.mark.unit
def test_select_ignores_unknown_event():
    v = Signal("a")
    sel = Select(v, options=["a", "b"])
    assert sel.handle("click", {}) is False
    assert v.peek() == "a"


# -- Image / Plot ------------------------------------------------------------


@pytest.mark.unit
def test_image_string_source_passes_through():
    img = Image("https://example.com/cat.png", alt="a cat")
    img.id = "n0"
    assert (
        img.to_json()["props"]
        == {
            "id": "n0",
            "type": "image",
            "props": {"alt": "a cat", "src": "https://example.com/cat.png"},
            "children": [],
        }["props"]
    )


@pytest.mark.unit
def test_image_bytes_source_becomes_png_data_uri():
    img = Image(b"\x89PNG\r\n")
    assert img.reactive_props()["src"]().startswith("data:image/png;base64,")


@pytest.mark.unit
def test_image_reacts_to_signal():
    src = Signal("a.png")
    img = Image(src)
    assert img.reactive_props()["src"]() == "a.png"
    src.set("b.png")
    assert img.reactive_props()["src"]() == "b.png"


class _FakeFigure:
    """A stand-in for a Matplotlib Figure: writes some bytes on savefig."""

    def savefig(self, buffer, **kwargs):
        buffer.write(b"\x89PNG-fake-figure-bytes")


@pytest.mark.unit
def test_plot_rasterises_a_figure_to_a_data_uri():
    plot = Plot(_FakeFigure())
    src = plot.reactive_props()["src"]()
    assert src.startswith("data:image/png;base64,")


@pytest.mark.unit
def test_plot_passes_through_a_url_string():
    plot = Plot("https://example.com/plot.png")
    assert plot.reactive_props()["src"]() == "https://example.com/plot.png"


# -- DataFrame ---------------------------------------------------------------


@pytest.mark.unit
def test_dataframe_from_columns_rows_dict():
    df = DataFrame({"columns": ["x", "y"], "rows": [[1, 2], [3, 4]]}, label="t")
    df.id = "n0"
    props = df.to_json()["props"]
    assert props["label"] == "t"
    assert props["data"] == {"columns": ["x", "y"], "rows": [[1, 2], [3, 4]]}


@pytest.mark.unit
def test_dataframe_from_list_of_records():
    df = DataFrame([{"a": 1, "b": 2}, {"a": 3, "b": 4}])
    assert df.reactive_props()["data"]() == {
        "columns": ["a", "b"],
        "rows": [[1, 2], [3, 4]],
    }


class _FakePandas:
    """Duck-typed pandas DataFrame: has .columns and .to_dict(orient=...)."""

    columns = ["x", "y"]

    def to_dict(self, orient):
        assert orient == "split"
        return {"columns": ["x", "y"], "data": [[1, 2], [3, 4]]}


@pytest.mark.unit
def test_dataframe_duck_types_pandas():
    df = DataFrame(_FakePandas())
    assert df.reactive_props()["data"]() == {
        "columns": ["x", "y"],
        "rows": [[1, 2], [3, 4]],
    }


@pytest.mark.unit
def test_dataframe_rejects_unsupported_source():
    df = DataFrame(42)
    with pytest.raises(TypeError):
        df.reactive_props()["data"]()


# -- Slice A input set -------------------------------------------------------


@pytest.mark.unit
def test_textinput_submit_runs_handler_and_is_always_handled():
    calls = []
    v = Signal("")
    ti = TextInput(v, on_submit=lambda: calls.append(1))
    assert ti.handle("submit", {}) is True
    assert calls == [1]
    # No handler: still handled (a no-op), so Enter never 400s.
    assert TextInput(Signal("")).handle("submit", {}) is True


@pytest.mark.unit
def test_checkbox_serialises_and_round_trips():
    v = Signal(False)
    cb = Checkbox(v, label="agree")
    cb.id = "n0"
    assert cb.to_json()["props"] == {"label": "agree", "checked": False}
    assert cb.handle("change", {"value": True}) is True
    assert v.peek() is True


@pytest.mark.unit
def test_number_serialises_and_sets_signal():
    v = Signal(3)
    n = Number(v, min=0, max=10, step=0.5, label="qty")
    n.id = "n0"
    assert n.to_json()["props"] == {"min": 0, "max": 10, "step": 0.5, "label": "qty", "value": 3}
    assert n.handle("input", {"value": 7.5}) is True
    assert v.peek() == 7.5


@pytest.mark.unit
def test_radio_normalises_options_and_sets_signal():
    v = Signal("a")
    r = Radio(v, options=["a", ("b", "Bee")], label="pick")
    r.id = "n0"
    assert r.to_json()["props"] == {
        "options": [{"value": "a", "label": "a"}, {"value": "b", "label": "Bee"}],
        "label": "pick",
        "value": "a",
    }
    assert r.handle("change", {"value": "b"}) is True
    assert v.peek() == "b"


@pytest.mark.unit
def test_multiselect_round_trips_a_list():
    v = Signal(["a"])
    ms = MultiSelect(v, options=["a", "b", "c"])
    ms.id = "n0"
    assert ms.to_json()["props"]["value"] == ["a"]
    assert ms.handle("change", {"value": ["a", "c"]}) is True
    assert v.peek() == ["a", "c"]
    # A non-list payload is rejected (unhandled), never crashes.
    assert ms.handle("change", {"value": "a"}) is False


@pytest.mark.unit
def test_date_round_trips_iso_string():
    v = Signal("")
    d = Date(v, label="when")
    d.id = "n0"
    assert d.to_json()["props"] == {"label": "when", "value": ""}
    assert d.handle("change", {"value": "2026-09-15"}) is True
    assert v.peek() == "2026-09-15"
