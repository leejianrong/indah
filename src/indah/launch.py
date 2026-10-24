"""Launch an indah app: bind a port, detect the environment, print the URL.

Serves the app on one port (ADR-0001). In a notebook it runs the server on a
background thread and embeds the app inline as an iframe, so the cell returns; as
a plain script it blocks until interrupted.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import socket
import threading
import time
from dataclasses import dataclass

from starlette.applications import Starlette

from .app import create_app
from .env import Environment, detect_environment, public_url


def find_free_port(preferred: int = 8000, *, host: str = "127.0.0.1", max_tries: int = 100) -> int:
    """Return a free TCP port, starting at ``preferred`` and stepping up.

    Uses only the stdlib so it does not depend on ``lsof``/``nc`` being present.
    """
    for port in range(preferred, preferred + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    # Fall back to letting the OS choose any free port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


# How long stop() lets uvicorn drain before it cancels streams still open.
STOP_GRACE_SECONDS = 1


@dataclass
class LaunchHandle:
    """A running indah server. Call ``stop()`` to shut it down."""

    url: str
    port: int
    _server: object
    _thread: threading.Thread
    _app: object = None

    def drain(self, wait: bool = True, timeout: float | None = None) -> None:
        """Start a graceful drain (IND-201), the same one SIGTERM starts under ``launch()``.

        The app stops taking new tabs (``GET /ready`` answers ``503``), tells every open stream
        to reconnect elsewhere, and keeps serving the sessions it holds. With ``wait`` (the
        default) this returns when no stream is open, or after the app's ``drain_seconds``
        (``timeout`` overrides the wait), whichever comes first, ending any stream still open;
        with ``wait=False`` it returns as soon as the drain has begun. It does not stop the
        server: call :meth:`stop` after it. With no stream open it returns at once."""
        drain = getattr(getattr(self._app, "state", None), "drain", None)
        loop = getattr(drain, "loop", None)
        if drain is None or loop is None or loop.is_closed():
            return

        async def begin() -> None:
            drain.begin()

        asyncio.run_coroutine_threadsafe(begin(), loop).result(5)
        if not wait:
            return
        limit = drain.seconds + 5 if timeout is None else timeout
        future = asyncio.run_coroutine_threadsafe(drain.wait(), loop)
        try:
            future.result(limit)
        except Exception:  # a timeout or a loop that is already gone: stop() takes over
            future.cancel()

    def stop(self) -> None:
        """Shut the server down. An SSE stream never ends on its own, so uvicorn is given
        ``STOP_GRACE_SECONDS`` to drain (``timeout_graceful_shutdown``) and then cancels
        the streams still open, which lets the thread end and frees the port. For a graceful
        exit that lets tabs move first, call :meth:`drain` before this."""
        # Cancelling an open stream is what we asked for, so keep uvicorn from logging it
        # as a server error.
        quiet = logging.getLogger("uvicorn.error")
        level = quiet.level
        quiet.setLevel(logging.CRITICAL)
        try:
            self._server.should_exit = True  # type: ignore[attr-defined]
            self._thread.join(timeout=STOP_GRACE_SECONDS + 4)
        finally:
            quiet.setLevel(level)


def _expect_host_proxy(app: object, environment: Environment) -> None:
    """Colab and Runpod always put their own proxy in front, so the "forwarded header but no
    trusted_proxies" warning (IND-200) would fire on every notebook run: turn it off there."""
    if environment in (Environment.COLAB, Environment.RUNPOD):
        notice = getattr(getattr(app, "state", None), "proxy_notice", None)
        if notice is not None:
            notice.enabled = False


def launch(
    app: Starlette | None = None,
    *,
    port: int | None = None,
    host: str = "127.0.0.1",
    block: bool | None = None,
    open_inline: bool = True,
) -> LaunchHandle:
    """Serve ``app`` (or a fresh demo app) and return a handle.

    ``block`` defaults to ``False`` in a notebook and ``True`` as a script.
    """
    import uvicorn

    app = create_app() if app is None else app
    environment = detect_environment()
    _expect_host_proxy(app, environment)
    port = find_free_port(host=host) if port is None else port

    # In Colab/Runpod the proxy reaches the container, so bind all interfaces.
    bind_host = "0.0.0.0" if environment in (Environment.COLAB, Environment.RUNPOD) else host

    config = uvicorn.Config(
        app,
        host=bind_host,
        port=port,
        log_level="warning",
        timeout_graceful_shutdown=int(STOP_GRACE_SECONDS),
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:  # wait for uvicorn startup to complete
        time.sleep(0.05)

    url = public_url(port, environment, host=host)
    # flush so the URL shows immediately even when stdout is a pipe (e.g. make demo).
    print(f"indah is running at {url}", flush=True)

    notebook = _in_notebook()
    if notebook and open_inline:
        _display_iframe(url)

    if block is None:
        block = not notebook

    handle = LaunchHandle(url=url, port=port, _server=server, _thread=thread, _app=app)
    if block:
        previous = _drain_on_sigterm(handle)
        try:
            thread.join()
        except KeyboardInterrupt:
            handle.stop()
        finally:
            if previous is not None:
                signal.signal(signal.SIGTERM, previous)
    return handle


def _drain_on_sigterm(handle: LaunchHandle) -> object | None:
    """A blocking ``launch()`` in the main thread drains on SIGTERM, then stops (IND-201).

    A second SIGTERM stops at once. Returns the old handler to put back, or ``None`` when no
    handler was installed (not the main thread, an app with ``drain_on_sigterm=False``)."""
    state = getattr(handle._app, "state", None)
    drain = getattr(state, "drain", None)
    if drain is None or threading.current_thread() is not threading.main_thread():
        return None
    if not getattr(state, "drain_on_sigterm", True):
        return None
    log = logging.getLogger("indah")

    def on_term(signum: int, frame: object) -> None:
        if drain.draining:
            handle.stop()
            return
        log.info("indah: SIGTERM, draining for up to %.0f s", drain.seconds)
        handle.drain()
        handle.stop()

    return signal.signal(signal.SIGTERM, on_term)


def _in_notebook() -> bool:
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    ip = get_ipython()
    return ip is not None and getattr(ip, "has_trait", lambda _: False)("kernel")


def _display_iframe(url: str, *, height: int = 480) -> None:  # pragma: no cover - needs IPython
    from IPython.display import IFrame, display

    display(IFrame(src=url, width="100%", height=height))
