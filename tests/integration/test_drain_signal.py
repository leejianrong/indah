"""SIGTERM drains a real process, under launch() and under `uvicorn app:app` (IND-201)."""

import signal
import socket
import subprocess
import sys
import time

import httpx
import pytest

from indah.launch import find_free_port

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM"),
]

LAUNCH_APP = """
from indah import create_app, launch
launch(create_app(drain_seconds=3), port={port}, open_inline=False)
"""

UVICORN_APP = """
from indah import create_app
app = create_app(drain_seconds=3)
"""


def _start(tmp_path, kind: str, port: int) -> subprocess.Popen:
    if kind == "launch":
        script = tmp_path / "serve.py"
        script.write_text(LAUNCH_APP.format(port=port))
        argv = [sys.executable, str(script)]
    else:
        (tmp_path / "drainapp.py").write_text(UVICORN_APP)
        argv = [
            sys.executable,
            "-m",
            "uvicorn",
            "drainapp:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ]
    proc = subprocess.Popen(argv, cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                time.sleep(
                    0.3
                )  # launch() installs its SIGTERM handler just after it starts serving
                return proc
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.kill()
    raise AssertionError("the server did not start: " + proc.stderr.read().decode())


def _clean(code: int, proc: subprocess.Popen) -> bool:
    """A clean exit: ``launch()`` returns 0 (a bare -15 would mean the signal killed it with no
    handler); uvicorn finishes its shutdown and then re-raises the signal it caught, so its
    status is the death by SIGTERM. Either way: nothing on stderr."""
    err = proc.stderr.read().decode() if proc.stderr else ""
    allowed = (-signal.SIGTERM,) if "uvicorn" in " ".join(proc.args) else (0,)
    return code in allowed and "Traceback" not in err


def _open_stream(port: int) -> socket.socket:
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"GET /api/stream?sid=t1 HTTP/1.1\r\nHost: x\r\nAccept: text/event-stream\r\n\r\n")
    return s


def _read_until(s: socket.socket, needle: bytes, seconds: float = 6.0) -> bytes:
    buf = b""
    end = time.monotonic() + seconds
    while needle not in buf and time.monotonic() < end:
        try:
            chunk = s.recv(65536)
        except TimeoutError:
            continue
        if not chunk:
            break
        buf += chunk
    return buf


@pytest.mark.parametrize("kind", ["launch", "uvicorn"])
def test_sigterm_tells_an_open_tab_to_reconnect_then_exits_once_it_is_gone(tmp_path, kind):
    port = find_free_port()
    proc = _start(tmp_path, kind, port)
    tab = _open_stream(port)
    try:
        assert b'"type": "init"' in _read_until(tab, b'"type": "init"')

        proc.send_signal(signal.SIGTERM)

        assert b'"type": "reconnect"' in _read_until(tab, b'"type": "reconnect"')
        ready = httpx.get(f"http://127.0.0.1:{port}/ready", timeout=2)
        assert ready.status_code == 503  # still listening while it drains
        assert proc.poll() is None  # and still alive: the tab has not gone yet

        tab.close()  # the tab moved to another process
        started = time.monotonic()
        assert _clean(proc.wait(timeout=10), proc)
        assert time.monotonic() - started < 3  # well inside drain_seconds: it did not wait it out
    finally:
        tab.close()
        if proc.poll() is None:
            proc.kill()


@pytest.mark.parametrize("kind", ["launch", "uvicorn"])
def test_sigterm_with_no_tab_open_exits_promptly(tmp_path, kind):
    port = find_free_port()
    proc = _start(tmp_path, kind, port)
    try:
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        assert _clean(proc.wait(timeout=10), proc)
        assert time.monotonic() - started < 3  # drain_seconds is 3: nothing was waited out
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.parametrize("kind", ["launch", "uvicorn"])
def test_a_tab_that_never_leaves_is_ended_at_the_deadline(tmp_path, kind):
    port = find_free_port()
    proc = _start(tmp_path, kind, port)
    tab = _open_stream(port)
    try:
        _read_until(tab, b'"type": "init"')
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        assert _clean(proc.wait(timeout=15), proc)
        took = time.monotonic() - started
        assert 2.5 <= took < 10  # about drain_seconds, then a clean exit
    finally:
        tab.close()
        if proc.poll() is None:
            proc.kill()
