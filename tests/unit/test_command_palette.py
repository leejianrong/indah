"""CommandPalette (IND-165): a keyboard palette of commands. Additive to ADR-0030."""

import asyncio

import pytest

from indah.components import Column, Command, CommandPalette
from indah.reactive import Signal
from indah.session import Session
from indah.transport import Hub


def _wire(component) -> dict:
    session = Session(Column(children=[component]))
    session.bind_hub(Hub(coalesce_seconds=0))
    return session.root.to_json()["children"][0]


class FakeCtx:
    """Just enough of Context for a jump command: it records where the tab was sent."""

    def __init__(self) -> None:
        self.went: list[str] = []

    def navigate(self, path: str, *, replace: bool = False) -> None:
        self.went.append(path)


@pytest.mark.unit
def test_a_plain_palette_wires_only_what_it_needs():
    node = _wire(CommandPalette([Command("Go home", lambda: None), Command("Sign out", lambda: 1)]))
    assert node["type"] == "commandpalette"
    assert node["props"] == {
        "shortcut": "mod+k",
        "commands": [
            {"id": "Go home", "label": "Go home"},
            {"id": "Sign out", "label": "Sign out"},
        ],
    }


@pytest.mark.unit
def test_command_options_ride_the_wire_only_when_set():
    commands = [
        Command(
            "Open log",
            to="/log/",
            group="Go to",
            shortcut="g l",
            keywords="requests tail",
            key="log",
        ),
        Command("Delete all", lambda: None, confirm="Delete everything?", keywords=["wipe", "rm"]),
    ]
    props = _wire(
        CommandPalette(
            commands, ctx=FakeCtx(), shortcut="Ctrl+P", placeholder="Search...", label="Jump"
        )
    )["props"]
    assert props["shortcut"] == "mod+p"
    assert props["placeholder"] == "Search..." and props["label"] == "Jump"
    assert props["commands"] == [
        {
            "id": "log",
            "label": "Open log",
            "group": "Go to",
            "shortcut": "g l",
            "keywords": ["requests", "tail"],
        },
        {
            "id": "Delete all",
            "label": "Delete all",
            "confirm": "Delete everything?",
            "keywords": ["wipe", "rm"],
        },
    ]
    # the server-side action never reaches the browser, only that a command exists
    assert "to" not in props["commands"][0] and "on_run" not in str(props)


@pytest.mark.unit
def test_bad_palettes_fail_at_construction():
    with pytest.raises(ValueError, match="label"):
        Command("", lambda: None)
    with pytest.raises(ValueError, match="exactly one"):
        Command("both", lambda: None, to="/x")
    with pytest.raises(ValueError, match="exactly one"):
        Command("neither")
    with pytest.raises(ValueError, match="in-app path"):
        Command("away", to="https://example.com")
    with pytest.raises(ValueError, match="twice"):
        CommandPalette([Command("a", lambda: 1), Command("a", lambda: 2)])
    with pytest.raises(TypeError, match="Command"):
        CommandPalette(["a"])
    with pytest.raises(ValueError, match="ctx"):
        CommandPalette([Command("Go", to="/x")])  # a jump needs a Context to move the tab
    with pytest.raises(ValueError, match="one key"):
        CommandPalette([], shortcut="g l")  # a sequence cannot open it
    with pytest.raises(ValueError, match="empty"):
        CommandPalette([], shortcut="")


@pytest.mark.unit
def test_running_a_command_calls_its_handler_once():
    ran: list[str] = []
    palette = CommandPalette(
        [Command("a", lambda: ran.append("a")), Command("b", lambda: ran.append("b"))]
    )
    assert palette.handle("run", {"command": "b"}) is True
    assert ran == ["b"]


@pytest.mark.unit
def test_a_jump_command_moves_the_tab():
    ctx = FakeCtx()
    palette = CommandPalette([Command("Log", to="/log")], ctx=ctx)
    assert palette.handle("run", {"command": "Log"}) is True
    assert ctx.went == ["/log"]


@pytest.mark.unit
def test_an_async_handler_is_handed_back_for_the_session_to_await():
    async def go() -> None:
        pass

    result = CommandPalette([Command("a", go)]).handle("run", {"command": "a"})
    assert asyncio.iscoroutine(result)
    result.close()


@pytest.mark.unit
@pytest.mark.parametrize("payload", [{}, {"command": "nope"}, {"command": 3}, {"command": ["a"]}])
def test_unknown_and_malformed_runs_do_nothing(payload):
    ran: list[str] = []
    palette = CommandPalette([Command("a", lambda: ran.append("a"))])
    assert palette.handle("run", payload) is True  # swallowed, not an error
    assert ran == []
    assert palette.handle("other", {"command": "a"}) is False


@pytest.mark.unit
def test_live_commands_follow_the_source_and_a_vanished_command_cannot_run():
    ran: list[str] = []
    page = Signal("home")

    def commands():
        out = [Command("Always", lambda: ran.append("always"))]
        if page.value == "log":
            out.append(Command("Clear log", lambda: ran.append("clear")))  # a page's own command
        return out

    palette = CommandPalette(commands)
    session = Session(Column(children=[palette]))
    hub = Hub(coalesce_seconds=0)
    session.bind_hub(hub)
    ids = lambda: [c["id"] for c in session.root.to_json()["children"][0]["props"]["commands"]]  # noqa: E731
    assert ids() == ["Always"]
    page.set("log")
    assert ids() == ["Always", "Clear log"]
    assert palette.handle("run", {"command": "Clear log"}) is True
    page.set("home")
    assert ids() == ["Always"]
    assert palette.handle("run", {"command": "Clear log"}) is True  # stale: nothing runs
    assert ran == ["clear"]
