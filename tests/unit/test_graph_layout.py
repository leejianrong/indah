"""The Graph layout and spatial index (frontend/graph/*.js), run under Node (ADR-0048).

The renderer is a browser module, but the layout and the spatial index are pure functions, so they
run here under plain Node on graphs built in Python. These guard what the browser tests cannot see
cheaply: the shape of the layout on a hard graph, determinism, and the index agreeing with brute
force. Skipped when Node is not installed.
"""

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
PROBES = Path(__file__).parent / "js"

pytestmark = [pytest.mark.unit, pytest.mark.skipif(NODE is None, reason="Node is not installed")]


def run_probe(name: str, payload: dict | None = None) -> dict:
    done = subprocess.run(
        [NODE, str(PROBES / name)],
        input=json.dumps(payload or {}),
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return json.loads(done.stdout)


def cross_linked_graph(n: int = 1000, seed: int = 3) -> dict:
    """Six groups of uneven size, edges only between different groups (as people, organisations and
    places link), and a skewed degree so about a third of the nodes have one edge or none."""
    rng = random.Random(seed)
    sizes = [350, 250, 150, 100, 100, 50]
    group = [g for g, size in enumerate(sizes) for _ in range(size)]
    weight = [(rank + 1) ** -1.1 for rank in range(n)]
    order = list(range(n))
    rng.shuffle(order)
    heavy = [0.0] * n
    for rank, node in enumerate(order):
        heavy[node] = weight[rank]
    edges: set[tuple[int, int]] = set()
    while len(edges) < int(n * 2.5):
        a, b = rng.choices(range(n), weights=heavy, k=2)
        if group[a] != group[b]:
            edges.add((min(a, b), max(a, b)))
    pairs = sorted(edges)
    return {"n": n, "group": group, "s": [a for a, _ in pairs], "t": [b for _, b in pairs]}


def test_the_test_graph_really_is_hard():
    graph = cross_linked_graph()
    degree = [0] * graph["n"]
    for a, b in zip(graph["s"], graph["t"], strict=True):
        degree[a] += 1
        degree[b] += 1
    assert sum(d <= 1 for d in degree) / graph["n"] > 0.25  # the case IND-250 is about
    assert sum(d == 0 for d in degree) > 50


def test_the_core_of_a_hard_graph_fills_a_readable_share_of_the_view():
    m = run_probe("layout_probe.mjs", cross_linked_graph())
    assert m["finite"]
    # On this graph the middle filled 2.2 percent of the fitted view before IND-250 and 11.2 after;
    # the threshold sits between them, so going back to the old spacing fails.
    assert m["coreFill"] > 0.08, m


def test_groups_stay_separate_after_the_tighter_spacing():
    m = run_probe("layout_probe.mjs", cross_linked_graph())
    # Centres are further apart than a group is wide (1.08 here; at spacing 0.5 it drops below 1,
    # which is why the spacing is not tighter).
    assert m["groupSeparation"] > 1.0, m


def test_the_layout_is_deterministic_and_settles_in_its_step_budget():
    m = run_probe("layout_probe.mjs", cross_linked_graph())
    assert m["deterministic"]
    assert m["steps"] <= m["expectedSteps"]


def test_the_spatial_index_agrees_with_brute_force():
    result = run_probe("spatial_probe.mjs")
    assert result["checked"] >= 200
    assert result["bad"] == 0


def test_a_stable_layout_ignores_group_and_node_order():
    ids = [f"n{i}" for i in range(60)]
    edges = [[ids[i], ids[(i * 7 + 3) % 60]] for i in range(60) if i != (i * 7 + 3) % 60]
    result = run_probe("stable_probe.mjs", {"ids": ids, "edges": edges})
    assert result["startGroup"] < 1e-9  # the group a node is in does not place it
    assert result["startOrder"] < 1e-9  # nor does its position in the list
    assert result["endGroup"] < 1e-6  # so settling the same graph gives the same picture


def _layered(ids, edges):
    return run_probe("layered_probe.mjs", {"ids": ids, "edges": edges})


def test_layered_puts_a_node_one_layer_below_its_deepest_parent():
    ids = ["a", "b", "c", "d", "e", "lone"]
    r = _layered(ids, [["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"], ["a", "d"], ["d", "e"]])
    y = r["y"]
    assert y["a"] < y["b"] == y["c"] < y["d"] < y["e"]  # d follows its deepest parent, not a
    assert y["lone"] == y["a"]  # a node with no edges is a root
    assert r["x"]["b"] != r["x"]["c"]  # siblings do not stack
    assert r["deterministic"]


def test_layered_breaks_a_cycle_and_still_places_every_node():
    r = _layered(["a", "b", "c"], [["a", "b"], ["b", "c"], ["c", "a"]])
    assert r["y"]["a"] < r["y"]["b"] < r["y"]["c"]  # broken at the first node in list order


def test_layered_orders_a_layer_to_avoid_a_crossing():
    # Without ordering, y1 sits left of x1 while its child sits right of x1's child: a crossing.
    ids = ["x", "y", "x1", "y1"]
    r = _layered(ids, [["x", "y1"], ["y", "x1"]])
    left_first = r["x"]["x"] < r["x"]["y"]
    assert (r["x"]["y1"] < r["x"]["x1"]) == left_first
