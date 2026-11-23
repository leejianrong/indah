"""Unit tests for the Graph component (ADR-0048): the columnar wire form and every build-time error.

The graph ships as columns, and edges refer to nodes by integer index, so a mistake (a duplicate
id, an edge to a node that is not there, too many nodes) must fail in Python before anything is
sent. The browser side (layout and drawing) is covered by the e2e suite and the layout benchmark.
"""

import pytest

from indah.components import GRAPH_MAX_NODES, Column, Graph
from indah.protocol import PROTOCOL_VERSION
from indah.reactive import Signal
from indah.session import Session
from indah.transport import Hub


def _props(g: Graph) -> dict:
    Session(Column(children=[g]))
    return g.to_json()["props"]


@pytest.mark.unit
def test_plain_ids_and_pairs_ship_as_columns_with_indexed_edges():
    props = _props(Graph(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "a")]))
    assert props["nodes"] == {"id": ["a", "b", "c"]}
    assert props["edges"] == {"s": [0, 1, 2], "t": [1, 2, 0]}
    assert props["height"] == 480 and props["layout"] == "auto"


@pytest.mark.unit
def test_optional_columns_appear_only_when_some_node_uses_them():
    nodes = [
        {"id": "a", "label": "Alpha", "group": "x", "size": 6, "color": "#ff0000"},
        {"id": "b"},
    ]
    cols = _props(Graph(nodes, []))["nodes"]
    assert cols["label"] == ["Alpha", None]
    assert cols["group"] == ["x", None]
    assert cols["size"] == [6.0, None]
    assert cols["color"] == ["#ff0000", None]
    assert "x" not in cols and "y" not in cols


@pytest.mark.unit
def test_edge_dicts_carry_optional_ids_and_colours():
    edges = [{"source": "a", "target": "b", "id": "F1", "color": "var(--primary)"}]
    cols = _props(Graph(["a", "b"], edges))["edges"]
    assert cols == {"s": [0], "t": [1], "id": ["F1"], "color": ["var(--primary)"]}


@pytest.mark.unit
def test_no_edges_is_fine():
    assert _props(Graph(["a", "b"]))["edges"] == {"s": [], "t": []}
    assert _props(Graph([]))["nodes"] == {"id": []}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("nodes", "edges", "message"),
    [
        (["a", "a"], [], "duplicate graph node id 'a'"),
        (["a", ""], [], "non-empty string id"),
        ([1, 2], [], "non-empty string id|id or a dict"),
        ([{"id": "a", "colour": "red"}], [], "unknown graph node keys"),
        ([{"id": "a", "size": -1}], [], "size must be positive"),
        ([{"id": "a", "color": "url(http://evil)"}], [], "CSS colour"),
        (["a", "b"], [("a", "z")], "edge 0 names unknown node 'z'"),
        (["a", "b"], [("a", "b"), ("q", "b")], "edge 1 names unknown node 'q'"),
        (["a", "b"], [("a",)], "must be \\(source, target\\)"),
        (["a"], [{"source": "a", "target": "a", "weight": 3}], "unknown graph edge keys"),
    ],
)
def test_a_bad_graph_raises_in_python_at_build_time(nodes, edges, message):
    with pytest.raises(ValueError, match=message):
        Graph(nodes, edges)


@pytest.mark.unit
def test_max_nodes_and_the_edge_cap_are_enforced():
    with pytest.raises(ValueError, match="at most 3 nodes"):
        Graph(["a", "b", "c", "d"], [], max_nodes=3)
    Graph(["a", "b", "c"], [], max_nodes=3)
    nodes = ["0", "1"]
    with pytest.raises(ValueError, match="at most 6 edges"):
        Graph(nodes, [("0", "1")] * 7, max_nodes=2)
    Graph(nodes, [("0", "1")] * 6, max_nodes=2)  # three times max_nodes edges are allowed


@pytest.mark.unit
@pytest.mark.parametrize("bad", [0, -1, GRAPH_MAX_NODES + 1, True, 2.5, "10"])
def test_max_nodes_must_be_within_the_ceiling(bad):
    with pytest.raises(ValueError, match="max_nodes must be between"):
        Graph(["a"], [], max_nodes=bad)


@pytest.mark.unit
def test_layout_given_needs_a_position_for_every_node():
    nodes = [{"id": "a", "x": 0, "y": 1}, {"id": "b", "x": 2, "y": 3}]
    cols = _props(Graph(nodes, [], layout="given"))["nodes"]
    assert cols["x"] == [0.0, 2.0] and cols["y"] == [1.0, 3.0]
    with pytest.raises(ValueError, match="needs an x for every node"):
        Graph([{"id": "a", "x": 0, "y": 1}, {"id": "b"}], [], layout="given")
    with pytest.raises(ValueError, match="'layered' or 'given'"):
        Graph(["a"], [], layout="radial")


@pytest.mark.unit
def test_auto_layout_does_not_send_positions():
    nodes = [{"id": "a", "x": 0, "y": 1}]
    assert "x" not in _props(Graph(nodes, []))["nodes"]


@pytest.mark.unit
def test_height_label_and_legend_props():
    g = Graph(["a"], [], height="fill", label="Entities", legend=False)
    props = _props(g)
    assert props["height"] == "fill" and props["label"] == "Entities" and props["legend"] is False
    with pytest.raises(ValueError, match="height"):
        Graph(["a"], [], height=10)


@pytest.mark.unit
def test_a_reactive_graph_is_columnarised_once_and_replaced_whole():
    nodes: Signal[list] = Signal(["a", "b"])
    edges: Signal[list] = Signal([("a", "b")])
    g = Graph(nodes, edges)
    session = Session(Column(children=[g]))
    hub = Hub()
    session.bind_hub(hub)

    snap = session.snapshot()["children"][0]["props"]
    assert snap["nodes"] == {"id": ["a", "b"]} and snap["edges"] == {"s": [0], "t": [1]}

    nodes.set(["a", "b", "c"])
    edges.set([("a", "b"), ("b", "c")])
    props = {}
    for _, msg in hub.history():
        assert msg["v"] == PROTOCOL_VERSION
        for change in msg["changes"]:
            props.update(change["props"])
    assert props["nodes"] == {"id": ["a", "b", "c"]}
    assert props["edges"] == {"s": [0, 1], "t": [1, 2]}


@pytest.mark.unit
def test_a_reactive_graph_with_a_bad_value_fails_when_it_is_built():
    with pytest.raises(ValueError, match="unknown node"):
        Graph(Signal(["a"]), Signal([("a", "b")]))


@pytest.mark.unit
def test_an_unrelated_signal_does_not_recolumnarise_the_graph(monkeypatch):
    import indah.components as components

    calls = []
    real = components._graph_columns
    monkeypatch.setattr(
        components, "_graph_columns", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    nodes = Signal(["a", "b"])
    other = Signal(0)
    g = Graph(nodes, [("a", "b")])
    g2 = Graph(lambda: ["a", "b"] if other.value >= 0 else [], [])
    Session(Column(children=[g, g2]))
    built = len(calls)
    other.set(1)  # g2 reads it and is rebuilt; g never reads it
    assert len(calls) == built + 1


@pytest.mark.unit
def test_focus_size_is_a_prop_and_must_be_a_sensible_whole_number():
    assert _props(Graph(["a"], []))["focusSize"] == 300
    assert _props(Graph(["a"], [], focus_size=50))["focusSize"] == 50
    for bad in (0, -5, 5001, 2.5, True, "300"):
        with pytest.raises(ValueError, match="focus_size must be"):
            Graph(["a"], [], focus_size=bad)


@pytest.mark.unit
def test_highlight_is_checked_against_the_graphs_nodes_and_edge_ids():
    edges = [{"source": "a", "target": "b", "id": "F1"}, ("b", "c")]
    props = _props(Graph(["a", "b", "c"], edges, highlight={"nodes": ["a", "b"], "edges": ["F1"]}))
    assert props["highlight"] == {"nodes": ["a", "b"], "edges": ["F1"]}
    with pytest.raises(ValueError, match="unknown node 'zz'"):
        Graph(["a"], [], highlight={"nodes": ["zz"]})
    with pytest.raises(ValueError, match="unknown edge 'F9'; give edges an 'id'"):
        Graph(["a", "b"], edges[:1], highlight={"edges": ["F9"]})
    with pytest.raises(ValueError, match="'nodes' and/or 'edges'"):
        Graph(["a"], [], highlight={"path": []})
    with pytest.raises(ValueError, match="'nodes' and/or 'edges'"):
        Graph(["a"], [], highlight=["a"])


@pytest.mark.unit
def test_a_reactive_highlight_and_focus_size_update_without_resending_the_graph():
    edges = [{"source": "a", "target": "b", "id": "F1"}]
    path: Signal[dict | None] = Signal(None)
    size: Signal[int] = Signal(300)
    g = Graph(["a", "b"], edges, highlight=path, focus_size=size)
    session = Session(Column(children=[g]))
    hub = Hub()
    session.bind_hub(hub)
    snap = session.snapshot()["children"][0]["props"]
    assert snap["highlight"] == {"nodes": [], "edges": []} and snap["focusSize"] == 300

    path.set({"nodes": ["a"], "edges": ["F1"]})
    size.set(40)
    changed = {}
    for _, msg in hub.history():
        for change in msg["changes"]:
            changed.update(change["props"])
    assert changed == {"highlight": {"nodes": ["a"], "edges": ["F1"]}, "focusSize": 40}
    assert "nodes" not in changed and "edges" not in changed


@pytest.mark.unit
def test_selected_is_a_two_way_signal_and_the_viewer_cannot_set_an_unknown_id():
    selected: Signal[str | None] = Signal(None)
    g = Graph(["a", "b", "c"], [("a", "b")], selected=selected)
    session = Session(Column(children=[g]))
    hub = Hub()
    session.bind_hub(hub)
    props = session.snapshot()["children"][0]["props"]
    assert props["selectable"] is True and props["selected"] is None

    assert g.handle("select", {"id": "b"}) is True and selected.value == "b"
    assert g.handle("select", {"id": None}) is True and selected.value is None
    selected.set("a")
    for bad in ({"id": "zzz"}, {"id": 7}, {"id": ["a"]}, {}):
        assert g.handle("select", bad) is False
    assert selected.value == "a"  # none of them changed it
    assert g.handle("select", {"id": "zzz"}) is False
    assert g.handle("click", {}) is False

    selected.set("c")  # from Python: pushed to the viewer as a prop
    sent = {}
    for _, msg in hub.history():
        for change in msg["changes"]:
            sent.update(change["props"])
    assert sent["selected"] == "c"


@pytest.mark.unit
def test_a_graph_without_a_selected_signal_is_display_only():
    g = Graph(["a", "b"], [])
    assert "selectable" not in _props(g) and "selected" not in g.reactive_props()
    assert g.handle("select", {"id": "a"}) is False


@pytest.mark.unit
def test_an_unknown_selected_value_or_focus_raises():
    with pytest.raises(ValueError, match="unknown graph node 'zz'"):
        Graph(["a"], [], selected=Signal("zz"))
    with pytest.raises(ValueError, match="unknown graph node 'zz'"):
        Graph(["a"], [], focus="zz")
    sel = Signal(None)
    g = Graph(["a"], [], selected=sel)
    Session(Column(children=[g]))
    with pytest.raises(ValueError, match="unknown graph node"):
        sel.set("nope")


@pytest.mark.unit
def test_focus_is_a_prop_and_a_reactive_focus_updates_alone():
    assert _props(Graph(["a", "b"], [], focus="b"))["focus"] == "b"
    where: Signal[str | None] = Signal("a")
    g = Graph(["a", "b"], [], focus=where)
    session = Session(Column(children=[g]))
    hub = Hub()
    session.bind_hub(hub)
    assert session.snapshot()["children"][0]["props"]["focus"] == "a"
    where.set("b")
    changed = {}
    for _, msg in hub.history():
        for change in msg["changes"]:
            changed.update(change["props"])
    assert changed == {"focus": "b"}


@pytest.mark.unit
def test_hovered_is_a_one_way_signal_the_viewer_sets_and_never_receives():
    hovered: Signal[str | None] = Signal(None)
    g = Graph(["a", "b", "c"], [("a", "b")], hovered=hovered)
    props = _props(g)
    assert props["hoverable"] is True
    assert "hovered" not in g.reactive_props() and "hovered" not in props  # one way: not pushed

    assert g.handle("hover", {"id": "b"}) is True and hovered.value == "b"
    assert g.handle("hover", {"id": None}) is True and hovered.value is None
    hovered.set("a")
    for bad in ({"id": "zzz"}, {"id": 7}, {"id": ["a"]}, {}):
        assert g.handle("hover", bad) is False
    assert hovered.value == "a"  # none of them changed it
    hovered.set("c")  # setting it from Python does not move the viewer
    assert "hovered" not in g.reactive_props()


@pytest.mark.unit
def test_a_graph_without_a_hovered_signal_sends_nothing_and_ignores_hover():
    g = Graph(["a", "b"], [])
    assert "hoverable" not in _props(g)
    assert g.handle("hover", {"id": "a"}) is False


@pytest.mark.unit
def test_an_unknown_initial_hovered_value_raises():
    with pytest.raises(ValueError, match="unknown graph node 'zz'"):
        Graph(["a"], [], hovered=Signal("zz"))


# -- element styles and the stable layout (IND-278, ADR-0053) ------------------------------------


@pytest.mark.unit
def test_node_and_edge_styles_ride_as_optional_columns():
    nodes = [
        {"id": "a", "ring": True, "opacity": 0.4, "label_style": "strike"},
        {"id": "b", "ring": "var(--ok)", "label_style": "bold"},
        "c",
    ]
    edges = [
        {"source": "a", "target": "b", "dash": True, "opacity": 0.5, "width": 2},
        {"source": "b", "target": "c", "dash": [6, 3]},
        ("a", "c"),
    ]
    props = Graph(nodes, edges).static_props()
    assert props["nodes"]["ring"] == [True, "var(--ok)", None]
    assert props["nodes"]["opacity"] == [0.4, None, None]
    assert props["nodes"]["labelStyle"] == ["strike", "bold", None]
    assert props["edges"]["dash"] == [True, [6, 3], None]
    assert props["edges"]["opacity"] == [0.5, None, None]
    assert props["edges"]["width"] == [2, None, None]


@pytest.mark.unit
def test_an_unstyled_graph_sends_no_style_columns():
    props = Graph(["a", "b"], [("a", "b")]).static_props()
    assert set(props["nodes"]) == {"id"} and set(props["edges"]) == {"s", "t"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "node",
    [
        {"id": "a", "opacity": 1.5},
        {"id": "a", "opacity": True},
        {"id": "a", "ring": "url(x)"},
        {"id": "a", "label_style": "italic"},
    ],
)
def test_a_bad_node_style_is_refused(node):
    with pytest.raises(ValueError):
        Graph([node])


@pytest.mark.unit
@pytest.mark.parametrize(
    "edge",
    [
        {"dash": "yes"},
        {"dash": [5]},
        {"dash": [0, 4]},
        {"opacity": -0.1},
        {"width": 0},
        {"width": 99},
    ],
)
def test_a_bad_edge_style_is_refused(edge):
    with pytest.raises(ValueError):
        Graph(["a", "b"], [{"source": "a", "target": "b", **edge}])


@pytest.mark.unit
def test_layout_stable_is_accepted_and_sent():
    assert Graph(["a"], layout="stable").static_props()["layout"] == "stable"
    with pytest.raises(ValueError):
        Graph(["a"], layout="radial")


# -- frames (IND-280, ADR-0053 part 3) -------------------------------------------------------------

_FN = ["a", "b", "c"]
_FE = [{"source": "a", "target": "b", "id": "ab"}, {"source": "b", "target": "c", "id": "bc"}]


@pytest.mark.unit
def test_frames_go_to_the_wire_with_wire_names_and_frame_follows_a_signal():
    from indah import Signal

    frame = Signal(1)
    g = Graph(
        _FN,
        _FE,
        frames=[
            {},
            {
                "nodes": {"a": {"ring": True, "label_style": "strike"}},
                "edges": {"ab": {"dash": True}},
            },
            {"hide": ["c", "bc"]},
        ],
        frame=frame,
    )
    props = g.static_props()
    assert props["frames"][1] == {
        "nodes": {"a": {"ring": True, "labelStyle": "strike"}},
        "edges": {"ab": {"dash": True}},
    }
    assert props["frames"][2] == {"hide": ["c", "bc"]} and props["frames"][0] == {}
    assert g.reactive_props()["frame"]() == 1
    assert g.handle("frame", {"index": 2}) is True and frame.value == 2
    for bad in (3, -1, True, "1", None):
        assert g.handle("frame", {"index": bad}) is False
    assert frame.value == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    "frames",
    [
        [{"nodes": {"zz": {"ring": True}}}],  # unknown node
        [{"edges": {"zz": {"dash": True}}}],  # unknown edge
        [{"hide": ["zz"]}],
        [{"nodes": {"a": {"opacity": 2}}}],  # a bad style
        [{"nodes": {"a": {"dash": True}}}],  # an edge style on a node
        [{"bogus": 1}],
        ["nope"],
        [{}] * 401,
    ],
)
def test_frames_refuse_mistakes_in_python(frames):
    with pytest.raises(ValueError):
        Graph(_FN, _FE, frames=frames)


@pytest.mark.unit
def test_frames_total_entries_are_capped():
    nodes = [f"n{i}" for i in range(500)]
    frames = [{"nodes": {n: {"opacity": 0.5} for n in nodes}} for _ in range(121)]  # 60,500
    with pytest.raises(ValueError, match="60,000"):
        Graph(nodes, frames=frames)


@pytest.mark.unit
def test_frame_needs_frames_and_a_valid_start():
    from indah import Signal

    with pytest.raises(ValueError, match="frames"):
        Graph(_FN, frame=Signal(0))
    with pytest.raises(ValueError, match="frame"):
        Graph(_FN, frames=[{}, {}], frame=Signal(2))
    assert "frames" not in Graph(_FN).static_props()


@pytest.mark.unit
def test_timeline_link_names_the_graph_and_needs_matching_frames():
    from indah import Signal, Timeline

    g = Graph(_FN, _FE, frames=[{}, {}, {}])
    g.id = "n7"
    tl = Timeline(Signal(1), [1, 2, 3], link=g)
    assert tl.static_props()["link"] == "n7"
    with pytest.raises(ValueError, match="frames"):
        Timeline(Signal(1), [1, 2], link=g)  # 2 points, 3 frames
    with pytest.raises(ValueError, match="Graph"):
        Timeline(Signal(1), [1, 2], link="n7")
    with pytest.raises(ValueError, match="frames"):
        Timeline(Signal(1), [1, 2], link=Graph(_FN))  # a graph without frames


@pytest.mark.unit
def test_update_keep_and_transition_are_off_by_default_and_sent_when_set():
    base = Graph(["a"]).static_props()
    assert "update" not in base and "transitionMs" not in base
    props = Graph(["a"], update="keep", transition_ms=300).static_props()
    assert props["update"] == "keep" and props["transitionMs"] == 300


@pytest.mark.unit
@pytest.mark.parametrize("bad", [-1, 2001, 1.5, True, "5"])
def test_transition_ms_is_an_int_from_0_to_2000(bad):
    with pytest.raises(ValueError, match="transition_ms"):
        Graph(["a"], transition_ms=bad)


@pytest.mark.unit
def test_update_must_be_relayout_or_keep():
    with pytest.raises(ValueError, match="'relayout' or 'keep'"):
        Graph(["a"], update="morph")


# -- directed edges, node shapes and the layered layout (IND-264) ---------------------------------


@pytest.mark.unit
def test_directed_and_layered_are_sent_and_off_by_default():
    base = Graph(["a"]).static_props()
    assert "directed" not in base and base["layout"] == "auto"
    props = Graph(["a"], directed=True, layout="layered").static_props()
    assert props["directed"] is True and props["layout"] == "layered"


@pytest.mark.unit
def test_node_shape_and_dash_ride_as_optional_columns():
    nodes = [{"id": "a", "shape": "square", "dash": True}, {"id": "b", "dash": [4, 2]}, "c"]
    cols = Graph(nodes).static_props()["nodes"]
    assert cols["shape"] == ["square", None, None]
    assert cols["dash"] == [True, [4, 2], None]
    assert set(Graph(["a"]).static_props()["nodes"]) == {"id"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "node",
    [{"id": "a", "shape": "star"}, {"id": "a", "dash": "yes"}, {"id": "a", "dash": [0, 3]}],
)
def test_a_bad_node_shape_or_dash_is_refused(node):
    with pytest.raises(ValueError):
        Graph([node])
