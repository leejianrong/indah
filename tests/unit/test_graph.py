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
    with pytest.raises(ValueError, match="'auto' or 'given'"):
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
