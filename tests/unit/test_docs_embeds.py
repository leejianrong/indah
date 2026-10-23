"""The docs embed Studio pages (ADR-0041): the registry, the embeds and the local-only marks.

A renamed or deleted Studio page, an embed that names a page that does not exist, or a page
that cannot run in a browser but does not say why, fails here (the fast gate) and not for a reader.
"""

import json
from pathlib import Path

import pytest

from examples.studio import registry
from examples.studio.core import discover

ROOT = Path(__file__).resolve().parents[2]

# The pages the Pyodide spike found server-shaped (docs/spikes/pyodide.md, section 2), minus the
# ones the docs bundle fixed with static files next to frame.html (IND-184): they run now.
FIXED_BY_STATIC_API_FILES = {"overlays/code-editor", "extend/bridge"}
SPIKE_LOCAL_ONLY = {
    "live/tab-title",
    "media/download",
    "overlays/context",
    "routing/links",
    "routing/navitem",
    "routing/navigate",
    "live/topic",
    "live/bounded",
    "media/upload",
    "extend/context",
    "playground/run",
}


@pytest.fixture(scope="module")
def exported():
    return registry.export_pages()


@pytest.mark.unit
def test_ids_are_unique_and_match_the_studio(exported):
    ids = [p["id"] for p in exported]
    assert len(ids) == len(set(ids))
    expected = [f"{c.slug}/{item.slug}" for c in discover() for item in [*c.pages, *c.apps]]
    assert ids == expected


@pytest.mark.unit
def test_every_page_is_runnable_or_says_why_not(exported):
    for p in exported:
        if p["runnable"]:
            assert p["local_only"] is None, p["id"]
        else:
            assert isinstance(p["local_only"], str) and p["local_only"].strip(), p["id"]
            assert "—" not in p["local_only"], f"{p['id']}: use hyphens, not em-dashes"


@pytest.mark.unit
def test_the_spike_pages_and_whole_apps_are_marked_local_only(exported):
    by_id = {p["id"]: p for p in exported}
    for pid in SPIKE_LOCAL_ONLY:
        assert pid in by_id and not by_id[pid]["runnable"], pid
    for pid in FIXED_BY_STATIC_API_FILES:
        assert pid in by_id and by_id[pid]["runnable"], f"{pid} should run in the docs now"
    for p in exported:
        if p["kind"] == "app":
            assert not p["runnable"], f"{p['id']} is a whole app and must be local only"
    assert any(p["runnable"] for p in exported), "no page can run in a browser"


@pytest.mark.unit
def test_export_is_deterministic_and_json(exported):
    first = registry.dumps(registry.export_pages())
    second = registry.dumps(registry.export_pages())
    assert first == second
    assert json.loads(first) == exported
    for p in exported:
        assert set(p) == {
            "id", "chapter", "slug", "kind", "title", "summary", "source", "covers", "docs",
            "adr", "runnable", "local_only", "screenshot",
        }  # fmt: skip
        if p["kind"] == "page":
            assert p["source"].strip(), p["id"]
        assert p["screenshot"].startswith("assets/live/shots/") and p["screenshot"].endswith(".png")


@pytest.mark.unit
def test_embeds_in_the_real_docs_name_real_pages():
    assert registry.embed_problems(ROOT / "website" / "docs") == []


@pytest.mark.unit
def test_an_embed_of_a_missing_page_is_reported(tmp_path):
    (tmp_path / "ok.md").write_text('text\n<indah-live page="layout/spacing"></indah-live>\n')
    (tmp_path / "bad.md").write_text('<indah-live page="layout/not-a-page"></indah-live>\n')
    (tmp_path / "typo.md").write_text("<indah-live page='nowhere'></indah-live>\n")
    problems = registry.embed_problems(tmp_path)
    assert len(problems) == 2
    assert any("bad.md" in p and "layout/not-a-page" in p for p in problems)
    assert any("typo.md" in p and "nowhere" in p for p in problems)


@pytest.mark.unit
def test_embedding_a_local_only_page_is_allowed(tmp_path):
    """It shows the source and a note instead of Run it (ADR-0041, section 3)."""
    (tmp_path / "x.md").write_text('<indah-live page="routing/links"></indah-live>\n')
    assert registry.embed_problems(tmp_path) == []


@pytest.mark.unit
def test_an_embed_with_no_page_is_reported(tmp_path):
    (tmp_path / "x.md").write_text("<indah-live></indah-live>\n")
    (problem,) = registry.embed_problems(tmp_path)
    assert "x.md" in problem and "page" in problem


@pytest.mark.unit
def test_every_docs_target_exists(exported):
    for p in exported:
        if p["docs"]:
            assert (ROOT / "website/docs" / p["docs"].split("#")[0]).exists(), p["id"]


def _first_python_block(markdown: str, after: str) -> str:
    """The first ```python block that follows the heading ``after``."""
    tail = markdown.split(after, 1)[1]
    return tail.split("```python", 1)[1].split("```", 1)[0]


@pytest.mark.unit
def test_the_quickstart_embeds_a_page_that_runs_its_code(exported):
    """The quickstart's first app is also a Studio page, and the page shows the same code.

    The docs must show what runs (ADR-0041): every statement of the quickstart's `page`
    (signals, the computed, the three components) has to be in the embedded page's source.
    """
    quickstart = (ROOT / "website/docs/quickstart.md").read_text()
    assert '<indah-live page="start/quickstart"></indah-live>' in quickstart
    page = next(p for p in exported if p["id"] == "start/quickstart")
    assert page["runnable"] and page["docs"] == "quickstart.md"
    shown = _first_python_block(quickstart, "## Your first app")
    wanted = [
        line.strip()
        for line in shown.splitlines()
        if line.strip()
        and not line.startswith(("import ", "from ", "indah.launch", "page = ", ")", "]"))
    ]
    ran = page["source"].replace("indah.", "")
    missing = [line for line in wanted if line not in ran]
    assert wanted and not missing, f"the quickstart shows code the page does not run: {missing}"
