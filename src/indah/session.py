"""A session ties a component tree to the reactive graph and the wire protocol.

It assigns stable node ids, produces the ``init`` snapshot, wires one effect per
reactive prop (so a signal change emits a patch for exactly that node), and
dispatches client events back into the graph.

Slice 3 makes dispatch async-aware (ADR-0011). A handler runs in one of two emit
modes:

- **sync dispatch** (a slider drag, a synchronous button click): mutations are
  collected into a coalescing sink and returned to the caller, which broadcasts
  them as one patch.
- **live** (an async handler between its awaits, or a StreamText being fed):
  there is no sink, so each change is published to the hub immediately, in order.

Because the reactive scheduler is synchronous and never awaits mid-flush, the
event loop only interleaves handlers at quiescent points, so concurrent async
handlers need no locking. A handler that raises does not take the UI down: the
traceback is logged and a short toast message is pushed to the client (Q-fail).

A ``Session`` is one viewer's reactive graph. Slice C gives each browser tab its
own via the session-store seam (``session_store.py``, ADR-0010), so concurrent
viewers stay isolated; ``app.py`` reaches a session only through that store, keyed
by the id the shell sends. A ``Session`` binds to its own ``Hub`` there, so its
live emits reach only that viewer's stream.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from .components import Chart, Component, Download, Heatmap, StreamText, walk
from .protocol import error_message, patch_message
from .reactive import Computation, batch, effect
from .transport import Hub

logger = logging.getLogger("indah")


@dataclass
class DispatchResult:
    """The outcome of a handled event.

    ``changes`` are the patches from synchronous mutations (broadcast by the
    caller). ``coro`` is set when the handler is async and must be awaited as a
    background task, so the POST returns immediately and the work streams over SSE.
    """

    changes: list[dict[str, Any]] = field(default_factory=list)
    coro: Coroutine[Any, Any, Any] | None = None


class Session:
    def __init__(self, root: Component) -> None:
        self.root = root
        self._by_id: dict[str, Component] = {}
        self._effects: list[Computation] = []
        # When set (during sync dispatch), reactive updates collect here as
        # {node_id: {prop: value}}. When None, updates emit live to the hub.
        self._sink: dict[str, dict[str, Any]] | None = None
        self._hub: Hub | None = None
        # Strong refs to running async-handler tasks so they are not GC'd.
        self._tasks: set[asyncio.Task[Any]] = set()
        # File-out (ADR-0017): bytes handed back to this viewer, keyed by an
        # unguessable token and served at api/file/<session_id>/<token>. The store
        # stamps session_id so the URL routes back to this session; "default" is the
        # id-less fallback (a single-shared app resolves any id to its one session).
        self.session_id: str = "default"
        self._files: dict[str, tuple[bytes, str, str]] = {}

        self._assign_ids()
        self._wire()

    # -- setup ---------------------------------------------------------------

    def _assign_ids(self) -> None:
        for index, component in enumerate(walk(self.root)):
            component.id = f"n{index}"
            self._by_id[component.id] = component

    def _wire(self) -> None:
        for component in walk(self.root):
            if isinstance(component, (StreamText, Download, Chart, Heatmap)):
                component.bind(self)
            for prop_name, getter in component.reactive_props().items():
                self._effects.append(self._make_effect(component.id, prop_name, getter))

    def _make_effect(self, node_id: str, prop_name: str, getter):
        state = {"initialised": False}

        def run() -> None:
            value = getter()  # reads signals -> subscribes this effect
            if state["initialised"]:
                self._emit(node_id, prop_name, value)
            else:
                state["initialised"] = True

        return effect(run)

    def bind_hub(self, hub: Hub) -> None:
        """Attach the hub so live (async/streaming) emits reach clients."""
        self._hub = hub

    # -- file-out (ADR-0017) -------------------------------------------------

    _MAX_FILES = 64  # bound the per-session file store (drop oldest beyond this)

    def serve_file(self, data: bytes, *, filename: str, media_type: str) -> str:
        """Register bytes for download and return the URL that serves them.

        The URL is relative (``api/file/<session_id>/<token>``) so it resolves
        behind Colab/Runpod proxy base paths. The token is unguessable, and the
        store is bounded so a long-running session does not grow without limit.
        """
        token = secrets.token_urlsafe(16)
        self._files[token] = (bytes(data), str(filename), str(media_type))
        while len(self._files) > self._MAX_FILES:
            oldest = next(iter(self._files))
            del self._files[oldest]
        return f"api/file/{self.session_id}/{token}"

    def get_file(self, token: str) -> tuple[bytes, str, str] | None:
        """The ``(data, filename, media_type)`` for a token, or ``None``."""
        return self._files.get(token)

    # -- emit paths ----------------------------------------------------------

    def _emit(self, node_id: str, prop_name: str, value: Any) -> None:
        """A reactive effect fired. Collect it (sync dispatch) or send it live."""
        if self._sink is not None:
            self._sink.setdefault(node_id, {})[prop_name] = value
        else:
            self.emit_props(node_id, {prop_name: value})

    def emit_props(self, node_id: str, props: dict[str, Any]) -> None:
        """Publish a prop replace/merge for one node immediately (live path)."""
        if self._hub is not None:
            self._hub.publish(patch_message([{"target": node_id, "props": props}]))

    def emit_append(self, node_id: str, prop: str, delta: Any) -> None:
        """Publish an append delta for one node immediately (streaming path).

        The delta is a string for text streaming (``StreamText``) or a list of rows
        for point streaming (``Chart``); the shell concatenates by type."""
        if self._hub is not None:
            self._hub.publish(patch_message([{"target": node_id, "append": {prop: delta}}]))

    def _report_error(self, exc: BaseException) -> None:
        """Log the traceback server-side and push a toast to clients; UI stays live."""
        logger.exception("indah handler raised", exc_info=exc)
        if self._hub is not None:
            self._hub.publish(error_message(f"{type(exc).__name__}: {exc}"))

    # -- wire protocol -------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """The full component tree as JSON, for the ``init`` message."""
        return self.root.to_json()

    def dispatch(
        self, component_id: str, event: str, payload: dict[str, Any]
    ) -> DispatchResult | None:
        """Apply a client event.

        Returns ``None`` if the component/event is unhandled, otherwise a
        :class:`DispatchResult`. A synchronous handler's mutations come back in
        ``.changes``; an async handler comes back as ``.coro`` for the caller to
        spawn. A synchronous handler that raises is reported (toast + log) and
        returns an empty result so the UI stays live.
        """
        component = self._by_id.get(component_id)
        if component is None:
            return None

        self._sink = {}
        outcome: dict[str, Any] = {"ret": False}

        def apply() -> None:
            outcome["ret"] = component.handle(event, payload or {})

        try:
            batch(apply)
        except Exception as exc:  # a synchronous handler blew up
            self._sink = None
            self._report_error(exc)
            return DispatchResult()  # handled: UI stays live
        finally:
            collected = self._sink
            self._sink = None

        ret = outcome["ret"]
        if ret is False:
            return None  # unknown event for this component

        changes = [{"target": nid, "props": props} for nid, props in collected.items()]
        if asyncio.iscoroutine(ret):
            return DispatchResult(changes=changes, coro=ret)
        return DispatchResult(changes=changes)

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Run an async handler in the background; report any exception as a toast."""
        task = asyncio.create_task(self._run_handler(coro))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _run_handler(self, coro: Coroutine[Any, Any, Any]) -> None:
        try:
            await coro
        except Exception as exc:
            self._report_error(exc)

    def cancel_tasks(self) -> None:
        """Cancel every running async-handler task (ADR-0024).

        Called when a session is evicted (idle-timeout/LRU) so an abandoned
        background loop -- a chatbot generation, a diffusion/training loop --
        actually stops instead of running forever with nowhere to deliver patches.
        """
        for task in list(self._tasks):
            task.cancel()
