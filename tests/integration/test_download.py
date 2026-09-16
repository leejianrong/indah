"""File-out over the HTTP boundary (ADR-0017): a served blob URL.

Proves a file handed back by a handler is downloadable at its per-session URL with
the right bytes and filename, that unknown ids/tokens 404, and that one viewer's
file is not reachable from another's session (rides Slice C).
"""

import httpx
import pytest

from indah.app import create_app
from indah.components import Button, Column, Download
from indah.reactive import Signal
from indah.session import Session


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _fileout_app():
    """n1 is a button that generates a CSV; n2 is a Download bound to those bytes."""

    def factory() -> Session:
        data = Signal(b"")

        def make():
            data.set(b"name,score\nAda,99\n")

        root = Column(
            children=[
                Button("Make CSV", on_click=make),
                Download(data, label="Download", filename="report.csv", media_type="text/csv"),
            ]
        )
        return Session(root)

    return create_app(session_factory=factory)


def _download_href(handle) -> str:
    return handle.session.snapshot()["children"][1]["props"]["href"]


@pytest.mark.integration
async def test_a_generated_file_is_downloadable_at_its_served_url():
    app = _fileout_app()
    async with _client(app) as client:
        await client.post("/api/event", json={"sid": "tab-a", "component": "n1", "event": "click"})
        href = _download_href(app.state.store.get("tab-a"))
        assert href.startswith("api/file/tab-a/")
        resp = await client.get("/" + href)  # href is document-relative

    assert resp.status_code == 200
    assert resp.content == b"name,score\nAda,99\n"
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="report.csv"' in resp.headers["content-disposition"]


@pytest.mark.integration
async def test_unknown_token_and_session_are_404():
    app = _fileout_app()
    async with _client(app) as client:
        # A real session, bogus token.
        await client.post("/api/event", json={"sid": "tab-a", "component": "n1", "event": "click"})
        assert (await client.get("/api/file/tab-a/nope")).status_code == 404
        # A bogus session.
        assert (await client.get("/api/file/ghost/whatever")).status_code == 404


@pytest.mark.integration
async def test_a_served_file_is_isolated_to_its_own_session():
    app = _fileout_app()
    async with _client(app) as client:
        await client.post("/api/event", json={"sid": "tab-a", "component": "n1", "event": "click"})
        href = _download_href(app.state.store.get("tab-a"))
        token = href.rsplit("/", 1)[1]

        # The same token under a different session id must not resolve.
        app.state.store.get_or_create("tab-b")  # exists, but has no such file
        assert (await client.get(f"/api/file/tab-b/{token}")).status_code == 404
        # ...while it still resolves under its own session.
        assert (await client.get(f"/api/file/tab-a/{token}")).status_code == 200
