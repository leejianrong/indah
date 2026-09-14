"""The JSON UI protocol between the Python backend and the browser shell.

Slice 1 has only the three message types needed for a live counter. The protocol
is versioned from v0 so the shell can reject a mismatched backend, and it is
designed to be a public contract (ADR-0005), not a private detail.

A node is {"id","type","props":{...},"children":[node,...]}.

Server -> client (over SSE):
  init  {"v":0,"type":"init","root":<node>}                 full tree on connect
  patch {"v":0,"type":"patch","changes":[{"target":"<id>","props":{...}}]}
  ping  {"v":0,"type":"ping"}                               heartbeat

Client -> server (HTTP POST /api/event):
  {"component":"<id>","event":"<name>","payload":{...}}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 0


def init_message(root: dict[str, Any]) -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": "init", "root": root}


def patch_message(changes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": "patch", "changes": changes}


def ping_message() -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": "ping"}


class EventIn(BaseModel):
    """A client-originated UI event. Rejected with 422 if it does not validate."""

    component: str
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)
