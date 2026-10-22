"""The Studio app (``make demo``): the home page, every chapter and every mounted example are
served, and the playground refuses what it should. Behaviour inside the pages is the e2e test."""

import httpx
import pytest

from examples.studio.app import build_app
from examples.studio.playground import PLAY, run_snippet


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.integration
async def test_home_every_chapter_page_and_every_app_shell_is_served():
    app = build_app()
    async with _client(app) as c:
        home = await c.get("/")
        assert home.status_code == 200 and "content-security-policy" in home.headers
        for chapter in app.state.chapters:
            index = await c.get(f"/c/{chapter.slug}/")
            assert index.status_code == 200, chapter.slug
            for page in chapter.pages:  # a deep link serves the shell (spa=True)
                deep = await c.get(f"/c/{chapter.slug}/{page.slug}")
                assert deep.status_code == 200, (chapter.slug, page.slug)
            for entry in chapter.apps:
                shell = await c.get(
                    f"/apps/{entry.slug}/{entry.open_path}", headers={"X-User": "alice"}
                )
                assert shell.status_code in (200, 302), entry.slug


@pytest.mark.integration
async def test_unknown_playground_runs_are_404_and_known_ones_redirect_to_a_slash():
    app = build_app()
    async with _client(app) as c:
        assert (await c.get("/play/nope/")).status_code == 404
        run_id, error = run_snippet("def build():\n    return indah.Text('hi')\n")
        assert error == "" and run_id in PLAY.runs
        assert (await c.get(f"/play/{run_id}")).status_code in (307, 308)
        shell = await c.get(f"/play/{run_id}/")
        assert shell.status_code == 200 and "nonce=" in shell.text  # strict CSP


@pytest.mark.integration
@pytest.mark.parametrize(
    ("code", "needle"),
    [
        ("def build(:\n", "SyntaxError"),
        ("x = 1\n", "Define a function"),
        ("def build():\n    return 5\n", "not an indah component"),
        ("def build():\n    raise RuntimeError('boom')\n", "boom"),
    ],
)
def test_run_snippet_reports_problems_instead_of_raising(code, needle):
    run_id, error = run_snippet(code)
    assert run_id is None and needle in error


@pytest.mark.integration
def test_a_snippet_that_never_returns_times_out(monkeypatch):
    import examples.studio.playground as pg

    monkeypatch.setattr(pg, "TIMEOUT_SECONDS", 0.3)
    run_id, error = pg.run_snippet("while True:\n    pass\n")
    assert run_id is None and "Timed out" in error
