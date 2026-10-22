"""Menu (IND-161): a menu button with items. Additive to ADR-0030."""

import asyncio

import pytest

from indah.components import Column, Menu, MenuItem
from indah.reactive import Signal
from indah.session import Session
from indah.transport import Hub


def _wire(component) -> dict:
    session = Session(Column(children=[component]))
    session.bind_hub(Hub(coalesce_seconds=0))
    return session.root.to_json()["children"][0]


@pytest.mark.unit
def test_a_plain_menu_wires_only_what_it_needs():
    node = _wire(Menu("Actions", [MenuItem("Edit"), MenuItem("Delete")]))
    assert node["type"] == "menu"
    assert node["props"] == {
        "trigger": "Actions",
        "items": [{"id": "Edit", "label": "Edit"}, {"id": "Delete", "label": "Delete"}],
    }


@pytest.mark.unit
def test_item_options_ride_the_wire_only_when_set():
    items = [
        MenuItem("Rename", shortcut="F2"),
        MenuItem("Delete", danger=True, confirm="Delete this?", key="del"),
        MenuItem("Archive", disabled=True),
    ]
    wire = _wire(Menu("More", items, label="Row actions", align="end", variant="tonal"))["props"]
    assert wire["items"] == [
        {"id": "Rename", "label": "Rename", "shortcut": "F2"},
        {"id": "del", "label": "Delete", "danger": True, "confirm": "Delete this?"},
        {"id": "Archive", "label": "Archive", "disabled": True},
    ]
    assert wire["label"] == "Row actions" and wire["align"] == "end" and wire["variant"] == "tonal"


@pytest.mark.unit
def test_bad_menus_fail_at_construction():
    with pytest.raises(ValueError, match="trigger"):
        Menu("", [MenuItem("a")])
    with pytest.raises(ValueError, match="label"):
        MenuItem("")
    with pytest.raises(ValueError, match="twice"):
        Menu("m", [MenuItem("a"), MenuItem("a")])  # the id is the label unless key= is given
    with pytest.raises(ValueError, match="align"):
        Menu("m", [], align="middle")


@pytest.mark.unit
def test_selecting_an_item_runs_its_handler_once():
    ran: list[str] = []
    menu = Menu(
        "m", [MenuItem("a", lambda: ran.append("a")), MenuItem("b", lambda: ran.append("b"))]
    )
    assert menu.handle("select", {"item": "b"}) is True
    assert ran == ["b"]


@pytest.mark.unit
def test_an_async_handler_is_handed_back_for_the_session_to_await():
    async def go() -> None:
        pass

    menu = Menu("m", [MenuItem("a", go)])
    result = menu.handle("select", {"item": "a"})
    assert asyncio.iscoroutine(result)
    result.close()


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload", [{}, {"item": "nope"}, {"item": 3}, {"item": ["a"]}, {"item": "off"}]
)
def test_unknown_malformed_and_disabled_selections_do_nothing(payload):
    ran: list[str] = []
    menu = Menu(
        "m", [MenuItem("a", lambda: ran.append("a")), MenuItem("off", ran.clear, disabled=True)]
    )
    assert menu.handle("select", payload) is True  # swallowed, not an error
    assert ran == []
    assert menu.handle("other", {"item": "a"}) is False


@pytest.mark.unit
def test_items_can_follow_a_signal_and_stale_ids_do_nothing():
    ran: list[str] = []
    items = Signal([MenuItem("a", lambda: ran.append("a"))])
    menu = Menu("m", lambda: items.value)
    node = _wire(menu)
    assert node["props"]["items"] == [{"id": "a", "label": "a"}]
    items.set([MenuItem("b", lambda: ran.append("b"))])
    assert [i["id"] for i in menu.reactive_props()["items"]()] == ["b"]
    menu.handle("select", {"item": "a"})  # clicked just as it disappeared
    assert ran == []
    menu.handle("select", {"item": "b"})
    assert ran == ["b"]


@pytest.mark.unit
def test_live_items_are_not_also_sent_as_static_props():
    menu = Menu("m", Signal([MenuItem("a")]))
    assert "items" not in menu.static_props()
    assert "items" in menu.reactive_props()


@pytest.mark.unit
def test_a_live_source_is_checked_when_built_and_again_when_read():
    with pytest.raises(ValueError, match="twice"):
        Menu("m", lambda: [MenuItem("a"), MenuItem("a")])
    items = Signal([MenuItem("a")])
    menu = Menu("m", items)
    items.set([MenuItem("a"), MenuItem("a")])
    with pytest.raises(ValueError, match="twice"):
        menu.reactive_props()["items"]()
