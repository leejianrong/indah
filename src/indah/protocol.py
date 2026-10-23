"""The JSON UI protocol between the Python backend and the browser shell.

The protocol is versioned from v0 so the shell can reject a mismatched backend,
and it is designed to be a public contract (ADR-0005), not a private detail.

A node is {"id","type","props":{...},"children":[node,...]}.

Server -> client (over SSE):
  init  {"v","type":"init","root":<node>}                   full tree on connect
  patch {"v","type":"patch","changes":[<change>,...]}       granular updates
  error {"v","type":"error","message":"..."}                a handler failed (toast)
  toast {"v","type":"toast","message","kind","ttl"}         handler feedback (ADR-0030)
  navigate {"v","type":"navigate","path","replace"}         move the browser's URL (ADR-0029)
  chrome {"v","type":"chrome","title","favicon"}            the tab title and icon (IND-152)
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
        "textarea",
        "streamtext",
        "select",
        "image",
        "imageoverlay",
        "audio",
        "chart",
        "heatmap",
        "map",
        "dataframe",
        "table",
        "stat",
        "checkbox",
        "switch",
        "router",
        "jsontree",
        "diff",
        "link",
        "navitem",
        "splitpane",
        "masterdetail",
        "shortcuts",
        "badge",
        "code",
        "empty",
        "marked",
        "number",
        "radio",
        "multiselect",
        "chips",
        "segmented",
        "date",
        "progress",
        "barstrip",
        "spinner",
        "list",
        "chat",
        "gallery",
        "row",
        "grid",
        "spacer",
        "divider",
        "skeleton",
        "tabs",
        "sidebar",
        "appshell",
        "expander",
        "modal",
        "drawer",
        "menu",
        "commandpalette",
        "upload",
        "download",
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


# Built-in components a render spec may name instead of a tag (IND-157, ADR-0016 amendment). A
# component node is a leaf: it takes only ``bind``, which maps the component's prop to a node prop
# (or, in a List item or table cell, an item or row field). The value is the props it may bind.
# A new entry needs a shell renderer registered under the same name (Custom.svelte).
SPEC_COMPONENTS: dict[str, frozenset[str]] = {
    "marked": frozenset({"runs"}),
    "steps": frozenset({"items", "orientation", "size"}),
}


def init_message(root: dict[str, Any], chrome: dict[str, Any] | None = None) -> dict[str, Any]:
    """The full tree. ``chrome`` (``{"title", "favicon"}``) rides along when the session has
    changed the tab's title or icon (IND-152), so a fresh init restores them; it is left off
    otherwise, and a shell that ignores it just keeps the app's own."""
    message: dict[str, Any] = {"v": PROTOCOL_VERSION, "type": "init", "root": root}
    if chrome:
        message["chrome"] = chrome
    return message


def chrome_message(title: str | None, favicon: str | None) -> dict[str, Any]:
    """Set the tab's title and icon (``ctx.title``, ``ctx.favicon``). ``None`` means the app's
    own; ``favicon`` is a same-origin URL relative to the document."""
    return {"v": PROTOCOL_VERSION, "type": "chrome", "title": title, "favicon": favicon}


def patch_message(changes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": "patch", "changes": changes}


def error_message(message: str) -> dict[str, Any]:
    """A handler-failure notice: shows a UI toast; the traceback is logged server-side."""
    return {"v": PROTOCOL_VERSION, "type": "error", "message": message}


TOAST_KINDS = ("info", "success", "warn", "error")


# The reserved event target for a toast's action button (IND-160). Component ids are ``n<index>``,
# so it cannot collide with one; the event is ``action`` with the payload ``{"id": <action id>}``.
TOAST_TARGET = "__toast__"
_MAX_ACTION_LABEL = 40


def toast_message(
    message: str, kind: str = "info", ttl: float = 4.0, action: dict[str, str] | None = None
) -> dict[str, Any]:
    """Transient feedback for one session's UI. ``ttl`` is seconds; 0 keeps it until
    dismissed. ``action`` (``{"id", "label"}``) adds a button that posts the event
    ``action`` to ``TOAST_TARGET``; it is left off the wire when not given."""
    if kind not in TOAST_KINDS:
        raise ValueError(f"toast kind must be one of {TOAST_KINDS}, got {kind!r}")
    if ttl < 0:
        raise ValueError("toast ttl must be >= 0")
    message_: dict[str, Any] = {
        "v": PROTOCOL_VERSION,
        "type": "toast",
        "message": message,
        "kind": kind,
        "ttl": ttl,
    }
    if action is not None:
        aid, label = action.get("id"), action.get("label")
        if not isinstance(aid, str) or not aid:
            raise ValueError("a toast action needs an id")
        if not isinstance(label, str) or not label or len(label) > _MAX_ACTION_LABEL:
            raise ValueError(f"a toast action label must be 1 to {_MAX_ACTION_LABEL} characters")
        message_["action"] = {"id": aid, "label": label}
    return message_


def navigate_message(path: str, replace: bool = False) -> dict[str, Any]:
    """Ask the shell to move the address bar to in-app ``path`` (``replace`` rewrites the
    current history entry instead of adding one)."""
    return {"v": PROTOCOL_VERSION, "type": "navigate", "path": path, "replace": bool(replace)}


def signed_out_message() -> dict[str, Any]:
    """The caller's login ended (``ctx.sign_out()`` or ``Principal.expires_at``). The server
    closes the stream after it; the shell stops reconnecting and shows a signed-out state."""
    return {"v": PROTOCOL_VERSION, "type": "signed_out"}


def ping_message() -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": "ping"}


class EventIn(BaseModel):
    """A client-originated UI event. Rejected with 422 if it does not validate."""

    component: str
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)
    # The sender's session id (ADR-0010): routes the event to that viewer's
    # isolated session. Optional -- an id-less client (a test or a curl) falls back
    # to the default session, which is the whole app for a single-shared app.
    sid: str | None = None


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

    # One element, from the allowlist; or, instead, ``component`` names a built-in leaf
    # component (SPEC_COMPONENTS). Exactly one of the two.
    tag: str = ""
    component: str | None = None
    attrs: dict[str, str] = Field(default_factory=dict)
    class_: str = Field(default="", alias="class")
    text: str | None = None
    # Fixed text content, shown as written. ``text`` names a node prop (or, in a List, an
    # item field); ``literal`` is the text itself, so a "Remove" button needs no field.
    literal: str | None = None
    bind: dict[str, str] = Field(default_factory=dict)
    on: dict[str, EventSpec] = Field(default_factory=dict)
    children: list[RenderSpec] = Field(default_factory=list)

    def validated(self) -> RenderSpec:
        """Recursively check tags against the allowlist; raise ``ValueError`` if not."""
        if self.component is not None:
            if self.tag:
                raise ValueError("a render spec names either a tag or a component, not both")
            if self.component not in SPEC_COMPONENTS:
                raise ValueError(
                    f"render component {self.component!r} is not allowed "
                    f"(allowed: {', '.join(sorted(SPEC_COMPONENTS))})"
                )
            if (
                self.attrs
                or self.class_
                or self.text is not None
                or self.literal is not None
                or self.on
                or self.children
            ):
                raise ValueError(
                    f"a component node is a leaf: {self.component!r} takes only bind, "
                    "no attrs, class, text, literal, on or children"
                )
            unknown = set(self.bind) - SPEC_COMPONENTS[self.component]
            if unknown:
                raise ValueError(
                    f"component {self.component!r} cannot bind {sorted(unknown)} "
                    f"(it takes: {', '.join(sorted(SPEC_COMPONENTS[self.component]))})"
                )
            return self
        if not self.tag:
            raise ValueError("a render spec needs a tag or a component")
        if self.tag not in ALLOWED_TAGS:
            raise ValueError(
                f"render tag {self.tag!r} is not allowed "
                f"(allowed: {', '.join(sorted(ALLOWED_TAGS))})"
            )
        if self.text is not None and self.literal is not None:
            raise ValueError("a render spec takes either text (a prop name) or literal, not both")
        for child in self.children:
            child.validated()
        return self

    def wire(self) -> dict[str, Any]:
        """The spec as it travels on the wire (aliases applied, empties trimmed)."""
        return self.model_dump(by_alias=True, exclude_defaults=True)


RenderSpec.model_rebuild()
