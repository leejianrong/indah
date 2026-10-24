"""Which process answered: an opaque node id, and the opt-in ``X-Indah-Node`` header (IND-203).

When a tab's events land on the wrong replica, the first question is which replica answered.
``create_app(node_header=True)`` (or ``INDAH_NODE_HEADER=1``) adds ``X-Indah-Node: <id>`` to every
response, the event stream's included. The id comes from ``INDAH_NODE``, else ``FLY_MACHINE_ID``,
else ``HOSTNAME`` (a pod name on Kubernetes), else a short random id that lasts for the process.

The id is opaque on purpose. A value that is not made of letters, digits, ``.``, ``_`` and ``-``
(up to 64 characters), or that is an IP address, is replaced by a short hash of itself, so a header
cannot carry an internal address or an injected line, and the same input still gives the same id.
``ctx.conn.node`` and ``app.state.node`` hold the id whether or not the header is on: they stay on
the server.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import secrets
from collections.abc import Mapping
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

HEADER = "x-indah-node"
_SAFE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_PROCESS_ID = secrets.token_hex(4)  # one per process, used when nothing names the node


def _opaque(value: str) -> str:
    return "n-" + hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:10]


def _is_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def resolve_node(environ: Mapping[str, str] | None = None) -> str:
    """The node id for this process (see the module docstring for the order and the rules)."""
    env = os.environ if environ is None else environ
    for name in ("INDAH_NODE", "FLY_MACHINE_ID", "HOSTNAME"):
        value = (env.get(name) or "").strip()
        if value:
            return value if _SAFE.fullmatch(value) and not _is_address(value) else _opaque(value)
    return _PROCESS_ID


class NodeHeaderMiddleware:
    """Add ``X-Indah-Node`` to every HTTP response (the start of a stream included)."""

    def __init__(self, app: ASGIApp, node: str) -> None:
        self.app = app
        self._header = (HEADER.encode("latin-1"), node.encode("latin-1"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_node(message: Any) -> None:
            if message["type"] == "http.response.start":
                kept = [h for h in message.get("headers", []) if h[0].lower() != self._header[0]]
                message["headers"] = [*kept, self._header]
            await send(message)

        await self.app(scope, receive, send_with_node)
