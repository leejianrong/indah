"""An audit trail for hosted apps: who did what, without what they typed (ADR-0034).

``create_app(audit=fn)`` calls ``fn(AuditEvent)`` after each UI event is dispatched. The
event names the session, the principal, the component and the event, and the *keys* of the
payload. Payload **values** are left out unless ``audit_payloads=True``, and values from a
component marked ``sensitive`` (a password ``TextInput``) are never included, so a log of
events cannot become a log of secrets. ``fn`` may be sync or async; one that raises is logged
and does not affect the request.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("indah")


@dataclass(frozen=True)
class AuditEvent:
    ts: float  # epoch seconds
    sid: str  # the session id (not the signed token)
    user: str | None  # the principal's id, or None for an app with no authenticator
    component: str  # the node id the event came from
    event: str  # "click", "input", "upload", ...
    payload_keys: tuple[str, ...]
    payload: Mapping[str, Any] | None = None  # only with audit_payloads=True, never if sensitive


AuditHook = Callable[[AuditEvent], Any]

_pending: set[asyncio.Task[Any]] = set()


def emit(
    hook: AuditHook | None,
    *,
    sid: str,
    user: str | None,
    component: str,
    event: str,
    payload: Mapping[str, Any],
    include_payload: bool,
    sensitive: bool,
) -> None:
    """Build and deliver one event. Never raises."""
    if hook is None:
        return
    try:
        item = AuditEvent(
            ts=time.time(),
            sid=sid,
            user=user,
            component=component,
            event=event,
            payload_keys=tuple(sorted(str(k) for k in payload)),
            payload=dict(payload) if include_payload and not sensitive else None,
        )
        result = hook(item)
        if inspect.isawaitable(result):
            task = asyncio.ensure_future(_guard(result))
            _pending.add(task)  # a task with no reference can be collected mid-flight
            task.add_done_callback(_pending.discard)
    except Exception:
        logger.exception("indah audit hook raised")


async def _guard(awaitable: Any) -> None:
    try:
        await awaitable
    except Exception:
        logger.exception("indah audit hook raised")
