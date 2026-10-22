import inspect

import pytest

from indah.components import (
    Audio,
    Badge,
    Button,
    Card,
    Checkbox,
    Col,
    Column,
    DataFrame,
    Date,
    Drawer,
    Expander,
    Grid,
    Image,
    Map,
    MasterDetail,
    Modal,
    MultiSelect,
    Number,
    Plot,
    Progress,
    Radio,
    Row,
    RowAction,
    Select,
    Sidebar,
    Slider,
    Spinner,
    SplitPane,
    Switch,
    Table,
    Tabs,
    Text,
    TextArea,
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
def test_button_variant_only_serialises_when_not_default():
    plain = Button("go")
    plain.id = "n0"
    assert plain.to_json()["props"] == {"label": "go"}  # no variant on a filled button
    tonal = Button("go", variant="tonal")
    tonal.id = "n1"
    assert tonal.to_json()["props"] == {"variant": "tonal", "label": "go"}


@pytest.mark.unit
def test_card_serialises_title_and_keeps_children():
    card = Card(children=[Text("a"), Text("b")], title="Panel")
    card.id = "n0"
    node = card.to_json()
    assert node["type"] == "card"
    assert node["props"] == {"title": "Panel"}
    assert [c["props"]["text"] for c in node["children"]] == ["a", "b"]


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


# -- Audio ---------------------------------------------------------------


@pytest.mark.unit
def test_audio_string_source_passes_through():
    clip = Audio("https://example.com/clip.mp3")
    assert clip.reactive_props()["src"]() == "https://example.com/clip.mp3"


@pytest.mark.unit
def test_audio_bytes_source_becomes_data_uri_with_media_type():
    clip = Audio(b"RIFF...", media_type="audio/wav")
    assert clip.reactive_props()["src"]().startswith("data:audio/wav;base64,")


@pytest.mark.unit
def test_audio_none_source_is_empty_string():
    clip = Audio(None)
    assert clip.reactive_props()["src"]() == ""


@pytest.mark.unit
def test_audio_reacts_to_signal():
    src = Signal("a.mp3")
    clip = Audio(src)
    assert clip.reactive_props()["src"]() == "a.mp3"
    src.set("b.mp3")
    assert clip.reactive_props()["src"]() == "b.mp3"


# -- Map -------------------------------------------------------------------


@pytest.mark.unit
def test_map_center_accepts_a_plain_tuple():
    m = Map((1.35, 103.8), zoom=11)
    assert m.reactive_props()["center"]() == [1.35, 103.8]
    assert m.reactive_props()["zoom"]() == 11


@pytest.mark.unit
def test_map_markers_normalise_dicts_and_tuples():
    m = Map((0, 0), markers=[{"lat": 1.3, "lon": 103.8, "label": "here"}, (1.4, 103.9)])
    markers = m.reactive_props()["markers"]()
    assert markers[0] == {"lat": 1.3, "lon": 103.8, "label": "here"}
    assert markers[1] == {"lat": 1.4, "lon": 103.9}


@pytest.mark.unit
def test_map_markers_skip_an_entry_missing_lat_or_lon():
    m = Map((0, 0), markers=[{"lat": 1.3}, {"lat": 1.3, "lon": 103.8}])
    markers = m.reactive_props()["markers"]()
    assert markers == [{"lat": 1.3, "lon": 103.8}]


@pytest.mark.unit
def test_map_polygons_normalise_points_and_style():
    m = Map((0, 0), polygons=[{"points": [(1.3, 103.8), (1.31, 103.81)], "color": "#2e6d62"}])
    polygons = m.reactive_props()["polygons"]()
    assert polygons == [{"points": [[1.3, 103.8], [1.31, 103.81]], "color": "#2e6d62"}]


@pytest.mark.unit
def test_map_polylines_normalise_points_and_style():
    m = Map((0, 0), polylines=[{"points": [(1.3, 103.8), (1.31, 103.81)], "color": "#b5296b"}])
    polylines = m.reactive_props()["polylines"]()
    assert polylines == [{"points": [[1.3, 103.8], [1.31, 103.81]], "color": "#b5296b"}]


@pytest.mark.unit
def test_map_polylines_accept_plain_point_lists_and_weight():
    m = Map((0, 0), polylines=[[(1.3, 103.8), (1.31, 103.81), (1.32, 103.82)]])
    polylines = m.reactive_props()["polylines"]()
    assert polylines == [{"points": [[1.3, 103.8], [1.31, 103.81], [1.32, 103.82]]}]

    m = Map(
        (0, 0),
        polylines=[{"points": [(1.3, 103.8), (1.31, 103.81)], "weight": 5, "label": "track"}],
    )
    polylines = m.reactive_props()["polylines"]()
    assert polylines == [{"points": [[1.3, 103.8], [1.31, 103.81]], "weight": 5, "label": "track"}]


@pytest.mark.unit
def test_map_reacts_to_a_center_signal():
    center = Signal((1.3, 103.8))
    m = Map(center)
    assert m.reactive_props()["center"]() == [1.3, 103.8]
    center.set((1.4, 103.9))
    assert m.reactive_props()["center"]() == [1.4, 103.9]


@pytest.mark.unit
def test_map_defaults_to_no_markers_polygons_or_polylines():
    m = Map((0, 0))
    assert m.reactive_props()["markers"]() == []
    assert m.reactive_props()["polygons"]() == []
    assert m.reactive_props()["polylines"]() == []


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
def test_textinput_password_masks_the_field():
    # Off by default; opt in for secrets like an API key.
    assert TextInput(Signal("")).static_props()["password"] is False
    assert TextInput(Signal(""), password=True).static_props()["password"] is True


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


# -- Slice A layout containers (ADR-0015) ------------------------------------


@pytest.mark.unit
def test_row_serialises_static_layout_props_and_keeps_children():
    a, b = Text("a"), Text("b")
    row = Row(children=[a, b], gap="0.5rem", wrap=False, align="center")
    row.id = "n0"
    node = row.to_json()
    assert node["type"] == "row"
    assert node["props"] == {"gap": "0.5rem", "wrap": False, "align": "center"}
    assert [c["props"]["text"] for c in node["children"]] == ["a", "b"]


@pytest.mark.unit
def test_grid_serialises_columns_and_gap():
    grid = Grid(children=[Text("a")], columns=3, gap="2rem")
    grid.id = "n0"
    assert grid.to_json()["props"] == {"columns": 3, "gap": "2rem"}


@pytest.mark.unit
def test_row_and_grid_have_no_handler():
    # Pure layout: arrangement only, no events to handle.
    assert Row().handle("click", {}) is False
    assert Grid().handle("select", {"index": 0}) is False


@pytest.mark.unit
def test_sidebar_is_a_plain_container():
    # First child is the aside, the rest the main region -- a rendering concern;
    # on the wire it is just a node with children (no split in the protocol).
    aside, main = Column(), Column()
    sb = Sidebar(children=[aside, main])
    sb.id = "n0"
    node = sb.to_json()
    assert node["type"] == "sidebar"
    assert len(node["children"]) == 2


@pytest.mark.unit
def test_tabs_serialise_labels_and_default_active_zero():
    tabs = Tabs(children=[Text("one"), Text("two")], labels=["One", "Two"])
    tabs.id = "n0"
    props = tabs.to_json()["props"]
    assert props == {"labels": ["One", "Two"], "active": 0}


@pytest.mark.unit
def test_tabs_select_event_sets_active_index():
    tabs = Tabs(children=[Text("one"), Text("two")], labels=["One", "Two"])
    assert tabs.handle("select", {"index": 1}) is True
    assert tabs.to_json()["props"]["active"] == 1
    # An unrelated event is unhandled.
    assert tabs.handle("click", {}) is False


@pytest.mark.unit
def test_tabs_active_can_be_driven_by_a_caller_signal():
    active = Signal(0)
    tabs = Tabs(children=[Text("one"), Text("two")], labels=["One", "Two"], active=active)
    active.set(1)
    assert tabs.to_json()["props"]["active"] == 1
    # A UI select writes back into the same signal.
    assert tabs.handle("select", {"index": 0}) is True
    assert active.peek() == 0


@pytest.mark.unit
def test_expander_serialises_label_and_open_state():
    exp = Expander(children=[Text("detail")], label="More", open=True)
    exp.id = "n0"
    assert exp.to_json()["props"] == {"label": "More", "open": True}


@pytest.mark.unit
def test_expander_toggle_flips_open_and_can_be_set_explicitly():
    exp = Expander(children=[Text("detail")], label="More")
    assert exp.to_json()["props"]["open"] is False
    assert exp.handle("toggle", {}) is True
    assert exp.to_json()["props"]["open"] is True
    assert exp.handle("toggle", {"value": False}) is True
    assert exp.to_json()["props"]["open"] is False
    assert exp.handle("click", {}) is False


@pytest.mark.unit
def test_expander_open_can_be_driven_by_a_caller_signal():
    is_open = Signal(False)
    exp = Expander(children=[Text("detail")], label="More", open=is_open)
    is_open.set(True)
    assert exp.to_json()["props"]["open"] is True
    assert exp.handle("toggle", {}) is True
    assert is_open.peek() is False


# -- Slice A: markdown Text, Progress, Spinner -------------------------------


@pytest.mark.unit
def test_plain_text_is_unchanged_without_markdown():
    t = Text(Signal("hi"))
    t.id = "n0"
    # No markdown flag, no blocks prop -- exactly the pre-Slice-A shape.
    assert t.to_json() == {"id": "n0", "type": "text", "props": {"text": "hi"}, "children": []}


@pytest.mark.unit
def test_markdown_text_emits_blocks_not_text():
    t = Text(Signal("# Hi"), markdown=True)
    t.id = "n0"
    props = t.to_json()["props"]
    assert props["markdown"] is True
    assert props["blocks"] == [{"tag": "h1", "children": ["Hi"]}]
    assert "text" not in props  # markdown renders from the block tree


@pytest.mark.unit
def test_markdown_text_reacts_to_its_source():
    src = Signal("a")
    t = Text(src, markdown=True)
    assert t.reactive_props()["blocks"]() == [{"tag": "p", "children": ["a"]}]
    src.set("**b**")
    assert t.reactive_props()["blocks"]() == [
        {"tag": "p", "children": [{"tag": "strong", "children": ["b"]}]}
    ]


@pytest.mark.unit
def test_progress_determinate_serialises_value_and_max():
    p = Progress(Signal(0.4), max=1.0, label="Loading")
    p.id = "n0"
    assert p.to_json()["props"] == {"max": 1.0, "label": "Loading", "value": 0.4}


@pytest.mark.unit
def test_progress_is_indeterminate_when_value_is_none():
    p = Progress(label="Working")
    assert p.reactive_props()["value"]() is None


@pytest.mark.unit
def test_progress_reacts_to_signal():
    v = Signal(0)
    p = Progress(v, max=10)
    assert p.reactive_props()["value"]() == 0.0
    v.set(7)
    assert p.reactive_props()["value"]() == 7.0


@pytest.mark.unit
def test_spinner_serialises_label_and_reactive_active():
    active = Signal(True)
    sp = Spinner(active=active, label="Thinking")
    sp.id = "n0"
    props = sp.to_json()["props"]
    assert props == {"label": "Thinking", "active": True}
    active.set(False)
    assert sp.reactive_props()["active"]() is False


@pytest.mark.unit
def test_spinner_defaults_to_active():
    assert Spinner().reactive_props()["active"]() is True


@pytest.mark.unit
def test_containers_walk_preorder_over_nested_children():
    leaf = Text("x")
    inner = Column(children=[leaf])
    root = Tabs(children=[inner], labels=["T"])
    assert list(walk(root)) == [root, inner, leaf]


@pytest.mark.unit
def test_textarea_serialises_and_round_trips():
    v = Signal("a\nb")
    ta = TextArea(v, label="Notes", placeholder="...", rows=6)
    assert ta.type == "textarea"
    assert ta.static_props() == {"placeholder": "...", "label": "Notes", "rows": 6}
    assert ta.reactive_props()["value"]() == "a\nb"
    assert ta.handle("input", {"value": "x\ny"}) is True
    assert v.value == "x\ny"
    assert ta.handle("nope", {}) is False


# -- Overlays (IND-94) -------------------------------------------------------


@pytest.mark.unit
def test_modal_and_drawer_serialise_and_close_sets_open_false():
    closed = []
    flag = Signal(True)
    m = Modal([Text("hi")], open=flag, title="Sure?", size="lg", on_close=lambda: closed.append(1))
    assert m.type == "modal"
    assert m.static_props() == {"title": "Sure?", "size": "lg"}
    assert m.reactive_props()["open"]() is True
    assert m.handle("close", {}) is True
    assert flag.value is False and closed == [1]

    d = Drawer([Text("x")], open=Signal(False), side="left", title="Row")
    assert d.type == "drawer"
    assert d.static_props() == {"title": "Row", "side": "left"}
    assert d.reactive_props()["open"]() is False
    assert d.handle("nope", {}) is False


@pytest.mark.unit
def test_overlay_accepts_a_plain_bool_and_validates_choices():
    assert Modal([], open=True).reactive_props()["open"]() is True
    with pytest.raises(ValueError):
        Modal([], open=Signal(False), size="huge")
    with pytest.raises(ValueError):
        Drawer([], open=Signal(False), side="top")


@pytest.mark.unit
def test_modal_async_on_close_is_returned_for_the_session_to_await():
    async def on_close():
        pass

    result = Modal([], open=Signal(True), on_close=on_close).handle("close", {})
    assert inspect.iscoroutine(result)
    result.close()


@pytest.mark.unit
def test_button_confirm_is_a_static_prop_and_click_is_unchanged():
    calls = []
    b = Button("Delete", lambda: calls.append(1), confirm="Delete this entry?")
    assert b.static_props() == {"confirm": "Delete this entry?"}
    assert Button("x").static_props() == {}
    assert b.handle("click", {}) is True and calls == [1]


# -- Badge, Switch, tooltip (IND-96) -----------------------------------------


@pytest.mark.unit
def test_badge_serialises_text_source_and_tone():
    label = Signal("pending")
    b = Badge(label, tone="warn")
    assert b.type == "badge"
    assert b.static_props() == {"tone": "warn"}
    assert b.reactive_props()["text"]() == "pending"
    label.set("done")
    assert b.reactive_props()["text"]() == "done"
    assert Badge("x").static_props() == {"tone": "neutral"}
    with pytest.raises(ValueError):
        Badge("x", tone="purple")


@pytest.mark.unit
def test_switch_round_trips_a_bool_signal():
    v = Signal(False)
    sw = Switch(v, label="Pinned")
    assert sw.type == "switch"
    assert sw.static_props() == {"label": "Pinned"}
    assert sw.reactive_props()["checked"]() is False
    assert sw.handle("change", {"value": True}) is True
    assert v.value is True
    assert sw.reactive_props()["checked"]() is True
    assert sw.handle("change", {}) is False


@pytest.mark.unit
def test_any_component_accepts_a_tooltip_kwarg():
    assert Button("x", tooltip="Does x").to_json()["props"]["tooltip"] == "Does x"
    assert Text("t", tooltip="hint").to_json()["props"]["tooltip"] == "hint"
    assert Modal([], open=True, tooltip="m").to_json()["props"]["tooltip"] == "m"
    assert "tooltip" not in Button("x").to_json()["props"]
    assert Column(children=[Text("a")], tooltip="col").to_json()["props"]["tooltip"] == "col"


# -- Table row actions and multi-select (IND-99) -----------------------------


def _rich(**kw):
    rows = [{"id": "a", "n": 1}, {"id": "b", "n": 2}]
    return Table(rows=rows, columns=[Col("id"), Col("n")], key="id", **kw)


@pytest.mark.unit
def test_row_actions_serialise_and_dispatch_with_the_row_key():
    got = []
    t = _rich(
        actions=[
            RowAction("Pin", lambda k: got.append(("pin", k))),
            RowAction("Delete", lambda k: got.append(("del", k)), confirm="Delete it?"),
        ]
    )
    assert t.static_props()["actions"] == [
        {"id": "a0", "label": "Pin", "variant": "ghost"},
        {"id": "a1", "label": "Delete", "variant": "ghost", "confirm": "Delete it?"},
    ]
    assert t.handle("action", {"action": "a1", "key": "b"}) is True
    assert t.handle("action", {"action": "a0", "key": "a"}) is True
    assert got == [("del", "b"), ("pin", "a")]
    assert t.handle("action", {"action": "a9", "key": "a"}) is False
    assert t.handle("action", {"action": "a0"}) is False  # no key


@pytest.mark.unit
def test_row_action_async_handler_is_returned():
    async def go(key):
        pass

    r = _rich(actions=[RowAction("Go", go)]).handle("action", {"action": "a0", "key": "a"})
    assert inspect.iscoroutine(r)
    r.close()


@pytest.mark.unit
def test_checked_signal_round_trips_a_list_of_keys():
    checked = Signal([])
    t = _rich(checked=checked)
    assert t.static_props()["checkable"] is True
    assert t.reactive_props()["checked"]() == []
    assert t.handle("check", {"keys": ["a", "b"]}) is True
    assert checked.value == ["a", "b"]
    assert t.reactive_props()["checked"]() == ["a", "b"]
    assert t.handle("check", {"keys": "a"}) is False  # must be a list
    assert _rich().static_props()["checkable"] is False


@pytest.mark.unit
def test_actions_and_checked_need_the_rich_form():
    with pytest.raises(ValueError):
        Table([{"a": 1}], checked=Signal([]))
    with pytest.raises(ValueError):
        Table([{"a": 1}], actions=[RowAction("x", lambda k: None)])
    with pytest.raises(ValueError):  # keys are what actions and checks are about
        Table(rows=[{"a": 1}], columns=[Col("a")], checked=Signal([]))


# -- SplitPane, MasterDetail, density (IND-103) ------------------------------


@pytest.mark.unit
def test_splitpane_serialises_and_validates():
    a, b = Text("a"), Text("b")
    sp = SplitPane(a, b, initial=0.3, min=0.15, key="log")
    assert sp.type == "splitpane" and sp.children == [a, b]
    assert sp.static_props() == {
        "direction": "horizontal",
        "initial": 0.3,
        "min": 0.15,
        "key": "log",
    }
    v = SplitPane(a, b, direction="vertical", height="20rem").static_props()
    assert v["direction"] == "vertical" and v["height"] == "20rem"
    assert "key" not in SplitPane(a, b).static_props()
    assert sp.handle("anything", {}) is False  # purely client-side, no events
    for bad in (
        {"direction": "diagonal"},
        {"initial": 0},
        {"initial": 1},
        {"min": 0.6},
        {"min": 0},
        {"initial": 0.1, "min": 0.2},  # initial outside [min, 1 - min]
        {"height": "tall"},
    ):
        with pytest.raises(ValueError):
            SplitPane(a, b, **bad)


@pytest.mark.unit
def test_masterdetail_open_signal_and_close_event():
    flag = Signal(False)
    md = MasterDetail(Text("list"), Text("detail"), open=flag, title="Call")
    assert md.type == "masterdetail" and len(md.children) == 2
    assert md.static_props() == {"initial": 0.4, "min": 0.2, "title": "Call"}
    assert md.reactive_props()["open"]() is False
    flag.set(True)
    assert md.reactive_props()["open"]() is True
    assert md.handle("close", {}) is True and flag.value is False
    assert MasterDetail(Text("a"), Text("b")).reactive_props()["open"]() is False  # own signal


@pytest.mark.unit
def test_table_density_prop():
    rows = [{"id": "a"}]
    t = Table(rows=rows, columns=[Col("id")], key="id", density="compact")
    assert t.static_props()["density"] == "compact"
    assert "density" not in Table(rows=rows, columns=[Col("id")], key="id").static_props()
    with pytest.raises(ValueError):
        Table(rows=rows, columns=[Col("id")], key="id", density="tiny")


@pytest.mark.unit
def test_table_density_may_be_a_signal():
    dense = Signal("comfortable")
    t = Table(rows=[{"id": "a"}], columns=[Col("id")], key="id", density=dense)
    assert "density" not in t.static_props()
    assert t.reactive_props()["density"]() == "comfortable"
    dense.set("compact")
    assert t.reactive_props()["density"]() == "compact"
    dense.set("tiny")  # a bad value from a signal falls back rather than breaking the table
    assert t.reactive_props()["density"]() == "comfortable"


@pytest.mark.unit
def test_text_size_body_is_a_static_prop_and_readout_is_the_default():
    assert "size" not in Text("x").to_json()["props"]
    assert Text("x", size="body").to_json()["props"]["size"] == "body"
    with pytest.raises(ValueError):
        Text("x", size="huge")
