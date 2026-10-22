"""The playground backend: run a snippet of indah code and serve the result at ``/play/<id>/``.

The viewer writes ``def build(): return <component>``; each run is validated once (in a thread,
with a timeout), wrapped in its own app, and mounted here. Runs are bounded (the oldest is
dropped). THIS EXECUTES THE VIEWER'S CODE IN THE SERVER PROCESS: the Studio only offers it to
loopback clients, and the page says so.
"""

from __future__ import annotations

import secrets
import threading
import traceback
from collections import OrderedDict
from typing import Any

from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

import indah

TIMEOUT_SECONDS = 5.0
MAX_RUNS = 16


class PlayApp:
    """An ASGI app that dispatches ``/<id>/...`` to the run registered under ``id``."""

    def __init__(self, keep: int = MAX_RUNS) -> None:
        self.keep = keep
        self.runs: OrderedDict[str, ASGIApp] = OrderedDict()

    def register(self, app: ASGIApp) -> str:
        run_id = secrets.token_urlsafe(6)
        self.runs[run_id] = app
        while len(self.runs) > self.keep:
            self.runs.popitem(last=False)
        return run_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await PlainTextResponse("not found", status_code=404)(scope, receive, send)
            return
        root = scope.get("root_path", "")
        path = scope["path"]
        rel = path[len(root) :] if root and path.startswith(root) else path
        run_id, _, rest = rel.lstrip("/").partition("/")
        app = self.runs.get(run_id)
        if app is None:
            await PlainTextResponse("No such run (it may have been replaced).", 404)(
                scope, receive, send
            )
            return
        if "/" not in rel.lstrip("/"):  # /play/<id> -> /play/<id>/ so relative URLs resolve
            target = f"{root.rstrip('/')}/{run_id}/"
            await RedirectResponse(target, status_code=307)(scope, receive, send)
            return
        child = dict(scope)
        child["root_path"] = f"{root.rstrip('/')}/{run_id}"
        child["path"] = "/" + rest
        await app(child, receive, send)


PLAY = PlayApp()


def _in_thread(fn: Any, timeout: float) -> tuple[Any, str | None]:
    """Run ``fn()`` in a daemon thread; ``(result, None)`` or ``(None, a short error)``."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["result"] = fn()
        except BaseException:  # the viewer's code: report everything, never crash the server
            box["error"] = traceback.format_exc(limit=6)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return None, f"Timed out after {timeout:g}s (is there an endless loop?)"
    if "error" in box:
        return None, box["error"]
    return box.get("result"), None


def run_snippet(code: str) -> tuple[str | None, str]:
    """Compile ``code``, check it defines ``build()`` returning a component, and mount it.

    Returns ``(run_id, "")`` on success or ``(None, error text)``."""
    namespace: dict[str, Any] = {"indah": indah, "__name__": "playground"}

    def define() -> None:
        exec(compile(code, "<playground>", "exec"), namespace)  # noqa: S102 - by design

    _, error = _in_thread(define, TIMEOUT_SECONDS)
    if error:
        return None, error
    build = namespace.get("build")
    if not callable(build):
        return None, "Define a function `build()` that returns an indah component."
    probe, error = _in_thread(build, TIMEOUT_SECONDS)
    if error:
        return None, error
    if not isinstance(probe, indah.Component):
        return None, f"build() returned {type(probe).__name__}, not an indah component."

    def factory() -> indah.Session:
        return indah.Session(build())

    app = indah.create_app(
        session_factory=factory,
        title="Playground run",
        title_suffix=" - indah Studio",
        csp="strict",
        proxy_flush=False,
    )
    app.state.home_url = "/c/playground/"
    return PLAY.register(app), ""
