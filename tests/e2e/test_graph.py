"""The Graph component in a real browser (ADR-0048, IND-245): it lays out, draws, pans and zooms.

The performance gate is **settle time**: a 5,000-node, 12,000-edge graph must finish its layout
in under three seconds. Frame rate is recorded and informational only, because headless CI
Chromium is software-rendered. The whole e2e suite already runs under ``csp="strict"`` and fails on
any violation, so this also proves the lazy module loads under it.
"""

import random

import pytest

import indah
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")

SETTLE_GATE_MS = 3000


def _graph(n: int, m: int, groups: int, seed: int = 7):
    rng = random.Random(seed)
    nodes = [{"id": f"n{i}", "group": f"g{i % groups}"} for i in range(n)]
    edges = set()
    while len(edges) < m:
        a = rng.randrange(n)
        # Mostly within the group, some across, like a community graph.
        b = (
            (rng.randrange(n // groups) * groups + a % groups) % n
            if rng.random() < 0.85
            else rng.randrange(n)
        )
        if a != b:
            edges.add((f"n{a}", f"n{b}"))
    return nodes, sorted(edges)


def _open(nodes, edges, **kwargs):
    app = indah.Card(children=[indah.Graph(nodes, edges, **kwargs)])
    return launch(indah.create_app(session=indah.Session(app)), block=False, open_inline=False)


def _wait_settled(page, timeout=30_000):
    page.wait_for_selector('.graph-stage[data-settled="true"]', timeout=timeout)
    return page.evaluate("() => ({ ...document.querySelector('.graph-stage').__graph })")


def _ink(page) -> int:
    """How many canvas pixels are not transparent: a blank canvas is 0."""
    return page.evaluate(
        """() => {
          const c = document.querySelector('.graph-canvas');
          const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
          let n = 0;
          for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
          return n;
        }"""
    )


@pytest.mark.e2e
def test_a_5000_node_graph_settles_inside_the_gate_and_draws():
    nodes, edges = _graph(5000, 12000, 8)
    handle = _open(nodes, edges, height=520, label="Community graph")
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_context(viewport={"width": 1100, "height": 800}).new_page()
            page.goto(handle.url)
            info = _wait_settled(page)
            assert info["nodes"] == 5000 and info["edges"] == 12000 and info["groups"] == 8
            assert info["settleMs"] < SETTLE_GATE_MS, info  # the gate
            print(
                f"graph 5000/12000 settled in {info['settleMs']} ms over {info['steps']} steps "
                f"(a draw costs {info.get('drawMs')} ms)"
            )
            assert _ink(page) > 5000
            legend = page.locator(".graph-legend li")
            assert legend.count() == 8
            page.screenshot(path="/tmp/graph-5000.png")
            browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_drag_pans_and_the_wheel_zooms():
    nodes, edges = _graph(300, 700, 4)
    handle = _open(nodes, edges, height=480)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_context(viewport={"width": 900, "height": 700}).new_page()
            page.goto(handle.url)
            _wait_settled(page)
            box = page.locator(".graph-canvas").bounding_box()
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

            def snap():
                return page.evaluate("() => document.querySelector('.graph-canvas').toDataURL()")

            before = snap()
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx + 120, cy + 60, steps=6)
            page.mouse.up()
            panned = snap()
            assert panned != before
            page.mouse.move(cx, cy)
            page.mouse.wheel(0, -600)
            page.wait_for_timeout(100)
            assert snap() != panned
            browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_a_replaced_graph_is_laid_out_again():
    nodes = indah.Signal([{"id": "a"}, {"id": "b"}])
    edges = indah.Signal([("a", "b")])
    app = indah.Card(children=[indah.Graph(nodes, edges, height=300)])
    handle = launch(indah.create_app(session=indah.Session(app)), block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_context(viewport={"width": 900, "height": 700}).new_page()
            page.goto(handle.url)
            assert _wait_settled(page)["nodes"] == 2

            def replace():
                nodes.set([{"id": str(i)} for i in range(40)])
                edges.set([(str(i), str(i + 1)) for i in range(39)])

            indah.batch(
                replace
            )  # both together, so no edge ever names a node that is not there yet
            page.wait_for_function(
                "() => document.querySelector('.graph-stage').__graph.nodes === 40", timeout=15_000
            )
            assert _wait_settled(page)["edges"] == 39
            browser.close()
    finally:
        handle.stop()
