"""The JSON UI protocol between the Python backend and the browser shell.

The protocol is versioned from v0 so the shell can reject a mismatched backend,
and it is designed to be a public contract (ADR-0005), not a private detail.

A node is {"id","type","props":{...},"children":[node,...]}.

Server -> client (over SSE):
  init  {"v","type":"init","root":<node>}                   full tree on connect
  patch {"v","type":"patch","changes":[<change>,...]}       granular updates
  error {"v","type":"error","message":"..."}                a handler failed (toast)
  ping  {"v","type":"ping"}                                 heartbeat

A patch ``change`` is one of:
  {"target":"<id>","props":{...}}          replace/merge these props (Slice 2)
  {"target":"<id>","append":{"text":"..."}} append a delta onto a prop (Slice 3)

State-bearing messages (patch, error) are tagged on the wire with an SSE ``id:``
(a per-stream offset) so a reconnecting ``EventSource`` can resume via
``Last-Event-Id`` (ADR-0002, ADR-0011); init and ping carry no id.

Client -> server (HTTP POST /api/event):
  {"component":"<id>","event":"<name>","payload":{...}}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Bumped 0 -> 1 in Slice 3: adds the append patch op and the error message. The
# shell ships with the backend and rejects a mismatched version (ADR-0005).
PROTOCOL_VERSION = 1

# The component types the pre-built shell renders natively. A custom type
# registered via register_component() must not collide with one of these, and its
# render spec is interpreted by the shell's generic renderer (ADR-0012).
BUILTIN_TYPES = frozenset(
    {
        "column",
        "card",
        "text",
        "button",
        "slider",
        "textinput",
        "streamtext",
        "select",
        "image",
        "dataframe",
        "checkbox",
        "number",
        "radio",
        "multiselect",
        "date",
        "progress",
        "spinner",
        "list",
        "chat",
        "gallery",
        "row",
        "grid",
        "tabs",
        "sidebar",
        "expander",
    }
)

# Tags the generic custom-component renderer may create. Kept to a safe, inert set
# (no script/iframe/style/object) because a render spec is data that drives the
# shell to build DOM (ADR-0012).
ALLOWED_TAGS = frozenset(
    {
        "div", "span", "p", "label", "input", "select", "option", "button",
        "textarea", "progress", "meter", "img", "a", "ul", "ol", "li", "table",
        "thead", "tbody", "tr", "th", "td", "strong", "em", "small", "code",
        "pre", "h1", "h2", "h3", "h4",
    }
)  # fmt: skip


def init_message(root: dict[str, Any]) -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": "init", "root": root}


def patch_message(changes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": "patch", "changes": changes}


def error_message(message: str) -> dict[str, Any]:
    """A handler-failure notice: shows a UI toast; the traceback is logged server-side."""
    return {"v": PROTOCOL_VERSION, "type": "error", "message": message}


def ping_message() -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": "ping"}


class EventIn(BaseModel):
    """A client-originated UI event. Rejected with 422 if it does not validate."""

    component: str
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


# -- Custom-component render spec (ADR-0012) ---------------------------------
#
# A registered custom component ships a declarative render spec that the shell's
# generic renderer interprets at runtime -- no shell rebuild, no runtime Node. The
# spec travels on the wire as the reserved ``_spec`` prop, so it is part of the
# public protocol. It describes one element (optionally nested) with static attrs,
# props bound onto attributes, optional text, and DOM events routed back as indah
# events for a value round-trip.


class EventSpec(BaseModel):
    """A DOM event routed back to the server as an indah event.

    ``event`` is the indah event name posted to ``/api/event``; ``prop`` names the
    bound node prop (a Signal) the event's value is written into, giving the
    two-way round-trip. The shell posts ``{"value": <element value>}``.
    """

    model_config = ConfigDict(extra="forbid")

    event: str
    prop: str | None = None


class RenderSpec(BaseModel):
    """A declarative, safe description of how the shell renders a custom node.

    Validated on registration so a malformed spec (e.g. a disallowed tag) is
    rejected before it can reach the shell.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tag: str
    attrs: dict[str, str] = Field(default_factory=dict)
    class_: str = Field(default="", alias="class")
    text: str | None = None
    bind: dict[str, str] = Field(default_factory=dict)
    on: dict[str, EventSpec] = Field(default_factory=dict)
    children: list[RenderSpec] = Field(default_factory=list)

    def validated(self) -> RenderSpec:
        """Recursively check tags against the allowlist; raise ``ValueError`` if not."""
        if self.tag not in ALLOWED_TAGS:
            raise ValueError(
                f"render tag {self.tag!r} is not allowed "
                f"(allowed: {', '.join(sorted(ALLOWED_TAGS))})"
            )
        for child in self.children:
            child.validated()
        return self

    def wire(self) -> dict[str, Any]:
        """The spec as it travels on the wire (aliases applied, empties trimmed)."""
        return self.model_dump(by_alias=True, exclude_defaults=True)


RenderSpec.model_rebuild()
