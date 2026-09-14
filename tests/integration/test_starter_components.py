"""Integration tests for the V4 starter set + custom seam (R5, R7).

Each value-bearing component must round-trip: set from Python is reflected in the
snapshot/patch, and a UI event is readable back in Python. Input components
(Select, custom colorpicker) round-trip both ways; display components (Image,
DataFrame) reflect the Python-set value into the tree.
"""

import httpx
import pytest

from indah.app import create_app
from indah.components import Column, DataFrame, Image, Select
from indah.custom import clear_registry, custom, register_component
from indah.reactive import Signal
from indah.session import Session


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


# -- Select: two-way round-trip ---------------------------------------------


@pytest.mark.integration
def test_select_round_trips_both_ways():
    choice = Signal("a")
    session = Session(Column(children=[Select(choice, options=["a", "b", "c"])]))

    # set from Python -> shown in the snapshot
    choice.set("b")
    assert session.snapshot()["children"][0]["props"]["value"] == "b"

    # changed in UI -> readable in Python, and patched back
    result = session.dispatch("n1", "change", {"value": "c"})
    assert choice.peek() == "c"
    assert result.changes == [{"target": "n1", "props": {"value": "c"}}]


# -- Image / DataFrame: display round-trip -----------------------------------


@pytest.mark.integration
def test_image_reflects_python_set_value():
    src = Signal("first.png")
    session = Session(Column(children=[Image(src, alt="fig")]))
    assert session.snapshot()["children"][0]["props"]["src"] == "first.png"

    # Image is display-only: Python drives it, no UI-change direction.
    src.set("second.png")
    assert session.snapshot()["children"][0]["props"]["src"] == "second.png"


@pytest.mark.integration
def test_dataframe_reflects_python_set_value():
    table = Signal({"columns": ["x"], "rows": [[1]]})
    session = Session(Column(children=[DataFrame(table)]))
    assert session.snapshot()["children"][0]["props"]["data"] == {
        "columns": ["x"],
        "rows": [[1]],
    }
    table.set({"columns": ["x", "y"], "rows": [[1, 2], [3, 4]]})
    assert session.snapshot()["children"][0]["props"]["data"]["columns"] == ["x", "y"]


# -- Custom component: round-trip over HTTP ----------------------------------


@pytest.mark.integration
async def test_custom_component_round_trips_over_http():
    register_component(
        "colorpicker",
        render={
            "tag": "input",
            "attrs": {"type": "color"},
            "bind": {"value": "value"},
            "on": {"input": {"event": "input", "prop": "value"}},
        },
    )
    colour = Signal("#ff8800")
    app = create_app(session=Session(Column(children=[custom("colorpicker", value=colour)])))

    async with _client(app) as client:
        resp = await client.post(
            "/api/event",
            json={"component": "n1", "event": "input", "payload": {"value": "#00ff00"}},
        )
    assert resp.status_code == 200
    assert colour.peek() == "#00ff00"

    # The render spec is in the served snapshot so the shell can render the node.
    node = app.state.session.snapshot()["children"][0]
    assert node["type"] == "colorpicker"
    assert node["props"]["_spec"]["tag"] == "input"
    assert node["props"]["value"] == "#00ff00"
