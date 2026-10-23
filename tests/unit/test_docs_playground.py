"""The docs Playground (IND-83): the starting points, the in-browser runner's Python half, markup.

None of this needs a browser or Pyodide: ``website/live/bridge.py`` is plain Python over indah, and
the Playground's starters must be runnable snippets in its own ``def build()`` contract.
"""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

import indah
from examples.studio import registry

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build():
    return _load("build_docs_live_pg", ROOT / "scripts" / "build_docs_live.py")


@pytest.fixture()
def bridge():
    """A fresh copy of the worker's Python half for each test (it keeps module state)."""
    return _load("live_bridge_pg", ROOT / "website" / "live" / "bridge.py")


@pytest.fixture(scope="module")
def starters(build):
    return build.playground_starters(registry.export_pages())


@pytest.mark.unit
def test_starters_are_runnable_snippets_in_the_build_contract(starters):
    assert len(starters) >= 4
    ids = [s["id"] for s in starters]
    assert len(set(ids)) == len(ids)
    for s in starters:
        assert s["code"].startswith("import indah")
        assert "def build():" in s["code"] and "ctx" not in s["code"], s["id"]
        namespace: dict = {"__name__": "playground"}
        exec(compile(s["code"], f"<{s['id']}>", "exec"), namespace)
        assert isinstance(namespace["build"](), indah.Component), s["id"]


@pytest.mark.unit
def test_a_starter_taken_from_a_studio_page_is_that_pages_source(starters):
    quickstart = next(s for s in starters if s["id"] == "start-quickstart")
    source = next(p for p in registry.export_pages() if p["id"] == "start/quickstart")["source"]
    assert quickstart["code"].endswith(source.split(":\n", 1)[1])


@pytest.mark.unit
def test_good_code_is_accepted_and_connects(bridge, starters):
    frames: list[str] = []
    assert bridge.init_code(starters[0]["code"], frames.append) == ""

    async def connect():
        bridge.connect("s1")
        await asyncio.sleep(0)

    asyncio.run(connect())
    first = json.loads(frames[0])
    assert first["type"] == "init" and first["root"]["type"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("def build(:\n    pass", "SyntaxError"),
        ("x = 1", "Define a function `build()`"),
        ("def build():\n    return 41 + 1", "returned int, not an indah component"),
        ("def build():\n    raise ValueError('nope')", "ValueError: nope"),
        ("raise RuntimeError('at import')", "RuntimeError: at import"),
        ("def build():\n    return indah.NoSuchComponent()", "AttributeError"),
    ],
)
def test_bad_code_is_explained_inline(bridge, code, expected):
    problem = bridge.init_code(code, lambda text: None)
    assert expected in problem


@pytest.mark.unit
def test_a_traceback_starts_at_the_readers_lines_not_the_runner(bridge):
    problem = bridge.init_code("def build():\n    return 1 / 0", lambda text: None)
    assert '"<playground>"' in problem and "ZeroDivisionError" in problem
    assert "bridge.py" not in problem and "exec(" not in problem


@pytest.mark.unit
def test_the_playground_markup_reads_without_javascript(build, starters):
    markup = build.render_playground(starters)
    assert markup.count("data-starter=") == len(starters)
    assert starters[0]["code"].splitlines()[0] in markup  # the editor starts with the first starter
    assert "indah-play-js" in markup and "hidden" in markup  # buttons wait for the script
    assert 'role="alert"' in markup and 'aria-live="polite"' in markup
    assert '<label for="indah-play-code">' in markup
    assert "Nothing is sent anywhere" in markup


@pytest.mark.unit
def test_finalize_fills_the_playground_and_leaves_other_pages_alone(build, tmp_path):
    pages = registry.export_pages()
    bundle = tmp_path / "live"
    bundle.mkdir()
    (bundle / "pages.json").write_text(registry.dumps(pages), encoding="utf-8")
    site = tmp_path / "site"
    (site / "playground").mkdir(parents=True)
    (site / "other").mkdir()
    (site / "playground" / "index.html").write_text(
        "<p><indah-playground></indah-playground></p>", encoding="utf-8"
    )
    (site / "other" / "index.html").write_text("<p>plain</p>", encoding="utf-8")
    assert build.finalize(site, bundle) == 1
    text = (site / "playground" / "index.html").read_text(encoding="utf-8")
    assert "<textarea" in text and "</indah-playground>" in text
    assert (site / "other" / "index.html").read_text(encoding="utf-8") == "<p>plain</p>"
    assert build.finalize(site, bundle) == 0  # filled once; a second run changes nothing


@pytest.mark.unit
def test_the_playground_script_is_inside_its_budget(build):
    size = build.PLAYGROUND_JS.stat().st_size
    assert size <= build.BUDGETS["playgroundScriptBytes"], size
    assert build.budget_problems(
        {"wheelBytes": 0, "elementScriptBytes": 0, "playgroundScriptBytes": 10**6}
    )


@pytest.mark.unit
def test_the_docs_page_and_nav_exist():
    assert (ROOT / "website" / "docs" / "playground.md").is_file()
    toml = (ROOT / "website" / "zensical.toml").read_text(encoding="utf-8")
    assert "playground.md" in toml and "indah-playground.js" in toml
    page = (ROOT / "website" / "docs" / "playground.md").read_text(encoding="utf-8")
    assert "<indah-playground></indah-playground>" in page
    assert "—" not in page  # hyphens, not em-dashes
