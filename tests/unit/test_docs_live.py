"""The docs' live-example bundle (ADR-0041, IND-184): what the build writes, how it fills embeds."""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location(
        "build_docs_live", ROOT / "scripts" / "build_docs_live.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bundle(build, tmp_path_factory):
    out = tmp_path_factory.mktemp("bundle") / "live"
    wheel = tmp_path_factory.mktemp("wheel") / "indah-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"not a real wheel")
    runtime = build.build_bundle(out, wheel=wheel)
    return out, runtime


@pytest.mark.unit
def test_the_element_script_stays_within_its_budget(build):
    size = (ROOT / "website" / "docs" / "javascripts" / "indah-live.js").stat().st_size
    assert size <= build.BUDGETS["elementScriptBytes"]


@pytest.mark.unit
def test_the_bundle_has_everything_the_runtime_loads(bundle):
    out, runtime = bundle
    for name in ("shim.js", "worker.js", "bridge.py", "frame.html", "studio.zip", "pages.json"):
        assert (out / name).is_file(), name
    assert (out / runtime["wheel"]).read_bytes() == b"not a real wheel"
    assert json.loads((out / "runtime.json").read_text()) == runtime
    # the shell's api/* GET routes become real files next to frame.html
    assert (out / "api" / "editor.js").is_file()
    assert (out / "api" / "components" / "tier-rail.js").is_file()


@pytest.mark.unit
def test_runtime_json_pins_pyodide_and_writes_the_budgets(build, bundle):
    _, runtime = bundle
    assert runtime["pyodide"] == build.PYODIDE_VERSION
    assert f"v{build.PYODIDE_VERSION}" in runtime["base"]  # the CDN url carries the pinned version
    assert runtime["selfHost"] is False and runtime["base"].startswith("https://")
    assert runtime["budgets"] == build.BUDGETS
    assert runtime["budgets"]["wheelBytes"] <= 1_000_000  # the card's budget
    assert runtime["budgets"]["firstFrameWarmSeconds"] == 8
    assert "uvicorn" not in runtime["packages"]  # deps=False: only the browser's needs


@pytest.mark.unit
def test_the_shim_is_injected_once_before_the_shell_runs(build):
    html = build.frame_html(
        '<!doctype html><html><head lang="x"><title>t</title></head><body></body>'
    )
    assert html.count('<script src="shim.js"></script>') == 1
    assert html.index("shim.js") < html.index("<title>")
    with pytest.raises(SystemExit):
        build.frame_html("<html>no head</html>")


@pytest.mark.unit
def test_studio_zip_has_the_studio_and_not_the_whole_example_apps(bundle):
    out, _ = bundle
    names = set(zipfile.ZipFile(out / "studio.zip").namelist())
    assert "examples/__init__.py" in names and "examples/studio/chapters/start.py" in names
    assert "examples/studio/modules/tier-rail.js" in names
    assert not any(
        n.startswith("examples/") and n.count("/") == 1 and n != "examples/__init__.py"
        for n in names
    )


@pytest.mark.unit
def test_budget_problems_name_what_is_over(build):
    ok = {"wheelBytes": 900_000, "elementScriptBytes": 5_000}
    assert build.budget_problems(ok) == []
    over = build.budget_problems({"wheelBytes": 1_000_001, "elementScriptBytes": 10_001})
    assert len(over) == 2 and "wheel" in over[0] and "indah-live.js" in over[1]


@pytest.fixture(scope="module")
def pages(bundle):
    out, _ = bundle
    return {p["id"]: p for p in json.loads((out / "pages.json").read_text())}


@pytest.mark.unit
def test_finalize_fills_a_runnable_embed_and_unwraps_its_paragraph(build, pages):
    text = '<p><indah-live page="start/choices"></indah-live></p>'
    new, n = build.finalize_html(text, pages)
    assert n == 1
    assert (
        new.startswith('<indah-live page="start/choices" data-prerendered>')
        and "<p>" not in new[:20]
    )
    assert (
        "<pre" in new and "indah-live-run" in new and "hidden" in new
    )  # the button waits for the script
    assert "Chips" in new  # the page's own source is there for a reader with no JavaScript


@pytest.mark.unit
def test_finalize_says_why_a_local_only_page_cannot_run_and_has_no_button(build, pages):
    new, n = build.finalize_html('<indah-live page="extend/context"></indah-live>', pages)
    assert n == 1 and "needs a server" in new and "indah-live-run" not in new and "make demo" in new


@pytest.mark.unit
def test_finalize_is_idempotent_and_refuses_an_unknown_page(build, pages):
    once, _ = build.finalize_html('<indah-live page="start/choices"></indah-live>', pages)
    twice, n = build.finalize_html(once, pages)
    assert n == 0 and twice == once
    with pytest.raises(SystemExit):
        build.finalize_html('<indah-live page="nope/nothing"></indah-live>', pages)


@pytest.mark.unit
def test_finalize_escapes_source_text(build, pages):
    page = dict(pages["start/choices"], source="<script>alert(1)</script> & more", title="a<b")
    new, _ = build.finalize_html(
        '<indah-live page="start/choices"></indah-live>', {"start/choices": page}
    )
    assert "<script>" not in new and "&lt;script&gt;" in new and "a&lt;b" in new


@pytest.mark.unit
def test_finalize_walks_a_built_site(build, bundle, tmp_path):
    out, _ = bundle
    site = tmp_path / "site"
    (site / "x").mkdir(parents=True)
    (site / "x" / "index.html").write_text('<p><indah-live page="start/choices"></indah-live></p>')
    (site / "plain.html").write_text("<p>nothing</p>")
    assert build.finalize(site, out) == 1
    assert "data-prerendered" in (site / "x" / "index.html").read_text()
    assert (site / "plain.html").read_text() == "<p>nothing</p>"
