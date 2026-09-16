"""Multipart upload over the HTTP boundary (ADR-0017), in-process via ASGITransport.

Proves an uploaded file reaches the target Upload component's handler and its
result patches the UI, that limits are enforced (missing/unknown component, size),
and that an upload is isolated to the sender's session (rides Slice C).
"""

import asyncio

import httpx
import pytest

from indah.app import create_app
from indah.components import Column, Text, Upload
from indah.reactive import Signal
from indah.session import Session


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _upload_app(*, max_mb: float = 25, multiple: bool = False, async_handler: bool = False):
    """n1 is an Upload; n2 is a Text echoing the last handler result over signal `out`."""

    def factory() -> Session:
        out = Signal("")

        if multiple:

            def on_upload(files):
                out.set(",".join(f.filename for f in files))
        elif async_handler:

            async def on_upload(file):
                await asyncio.sleep(0)  # yield: exercise the background-task path
                out.set(f"{file.filename}:{file.text()}")
        else:

            def on_upload(file):
                out.set(f"{file.filename}:{file.text()}")

        root = Column(children=[Upload(on_upload, multiple=multiple), Text(lambda: out.value)])
        return Session(root)

    return create_app(session_factory=factory, max_upload_mb=max_mb)


def _text(handle) -> str:
    return handle.session.snapshot()["children"][1]["props"]["text"]


@pytest.mark.integration
async def test_an_upload_reaches_the_handler_and_patches_the_ui():
    app = _upload_app()
    async with _client(app) as client:
        resp = await client.post(
            "/api/upload",
            data={"sid": "tab-a", "component": "n1"},
            files={"file": ("hello.txt", b"hi there", "text/plain")},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "files": ["hello.txt"]}
    handle = app.state.store.get("tab-a")
    assert _text(handle) == "hello.txt:hi there"
    assert handle.hub.current_offset == 1  # the handler's patch was published


@pytest.mark.integration
async def test_multiple_files_reach_the_handler():
    app = _upload_app(multiple=True)
    async with _client(app) as client:
        resp = await client.post(
            "/api/upload",
            data={"sid": "tab-a", "component": "n1"},
            files=[
                ("file", ("a.txt", b"1", "text/plain")),
                ("file", ("b.txt", b"2", "text/plain")),
            ],
        )
    assert resp.status_code == 200
    assert _text(app.state.store.get("tab-a")) == "a.txt,b.txt"


@pytest.mark.integration
async def test_async_upload_handler_runs_in_the_background_and_patches():
    app = _upload_app(async_handler=True)
    async with _client(app) as client:
        resp = await client.post(
            "/api/upload",
            data={"sid": "tab-a", "component": "n1"},
            files={"file": ("z.txt", b"zzz", "text/plain")},
        )
        assert resp.status_code == 200
        # The POST returns before the async handler finishes; let the spawned task run.
        for _ in range(10):
            if _text(app.state.store.get("tab-a")) == "z.txt:zzz":
                break
            await asyncio.sleep(0.01)
    assert _text(app.state.store.get("tab-a")) == "z.txt:zzz"


@pytest.mark.integration
async def test_missing_component_field_is_rejected_400():
    app = _upload_app()
    async with _client(app) as client:
        resp = await client.post(
            "/api/upload",
            data={"sid": "tab-a"},  # no component
            files={"file": ("a.txt", b"1", "text/plain")},
        )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_unknown_component_is_rejected_400():
    app = _upload_app()
    async with _client(app) as client:
        resp = await client.post(
            "/api/upload",
            data={"sid": "tab-a", "component": "nope"},
            files={"file": ("a.txt", b"1", "text/plain")},
        )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_an_oversize_file_is_rejected_413():
    app = _upload_app(max_mb=0.001)  # ~1 KB cap
    async with _client(app) as client:
        resp = await client.post(
            "/api/upload",
            data={"sid": "tab-a", "component": "n1"},
            files={"file": ("big.bin", b"x" * 5000, "application/octet-stream")},
        )
    assert resp.status_code == 413
    # Rejected before the handler ran: the session was never even touched.
    assert app.state.store.get("tab-a") is None


@pytest.mark.integration
async def test_an_upload_is_isolated_to_the_senders_session():
    app = _upload_app()
    async with _client(app) as client:
        await client.post(
            "/api/upload",
            data={"sid": "tab-a", "component": "n1"},
            files={"file": ("a.txt", b"AAA", "text/plain")},
        )
        # tab-b uploads nothing; establish its session with an empty handler call
        await client.post(
            "/api/upload",
            data={"sid": "tab-b", "component": "n1"},
            files={"file": ("b.txt", b"BBB", "text/plain")},
        )
    a = app.state.store.get("tab-a")
    b = app.state.store.get("tab-b")
    assert _text(a) == "a.txt:AAA"
    assert _text(b) == "b.txt:BBB"  # each sees only its own upload
    assert a.hub is not b.hub
