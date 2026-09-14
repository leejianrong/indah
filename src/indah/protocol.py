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

from pydantic import BaseModel, Field

# Bumped 0 -> 1 in Slice 3: adds the append patch op and the error message. The
# shell ships with the backend and rejects a mismatched version (ADR-0005).
PROTOCOL_VERSION = 1


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
