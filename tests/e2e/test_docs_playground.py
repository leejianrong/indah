"""The docs Playground (IND-83): edit indah code and run it in the browser, with no server.

Two groups, so the fast browser job stays fast:

* ``e2e`` (needs no Pyodide): nothing loads before Run, the editor reads and copies with
  JavaScript off, Tab indents and Escape lets Tab leave, Reset and the starter list work;
* ``pyodide`` (own CI job, downloads the pinned runtime once): Run really runs a typed snippet, a
  bad one shows its error and no frame, an endless loop is stopped, and Stop works. Skipped with a
  clear message when the runtime cannot be downloaded.
"""

import fcntl
import functools
import http.server
import importlib.util
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

from examples.studio import registry  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CACHE_LOCK = ROOT / ".cache" / "live-pyodide.lock"
SCRIPT = ROOT / "website" / "docs" / "javascripts" / "indah-playground.js"
BOOT_MS = 120_000

_TYPES = {".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm"}


class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **_TYPES}

    def end_headers(self):  # what Pages and a CDN send: a cached runtime is a warm one
        self.send_header("Cache-Control", "max-age=600")
        super().end_headers()

    def log_message(self, *args):
        pass


def _load_build_script():
    spec = importlib.util.spec_from_file_location(
        "build_docs_live", ROOT / "scripts" / "build_docs_live.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class Site:
    base: str
    selfhosted: bool
    starters: list


def _make_site(root: Path, *, self_host: bool) -> Site:
    build = _load_build_script()
    selfhosted = self_host
    CACHE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # parallel workers share the Pyodide download cache
        try:
            build.build_bundle(root / "assets" / "live", self_host=self_host)
        except OSError:  # no network and nothing cached for the pinned runtime
            selfhosted = False
            build.build_bundle(root / "assets" / "live", self_host=False)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    starters = build.playground_starters(registry.export_pages())
    (root / "javascripts").mkdir()
    (root / "javascripts" / "indah-playground.js").write_text(SCRIPT.read_text())
    (root / "index.html").write_text(
        "<!doctype html><title>Playground</title><main>"
        f"{build.render_playground(starters)}</main>"
        '<script src="javascripts/indah-playground.js"></script>'
    )
    handler = functools.partial(_Handler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site = Site(
        base=f"http://127.0.0.1:{server.server_address[1]}",
        selfhosted=selfhosted,
        starters=starters,
    )
    site.server = server
    return site


@pytest.fixture(scope="module")
def light_site(tmp_path_factory):
    """The page and its bundle with no Pyodide (the CDN base): enough for everything before Run."""
    site = _make_site(tmp_path_factory.mktemp("playground-light"), self_host=False)
    yield site
    site.server.shutdown()


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """The page with the pinned Pyodide self-hosted, for real runs."""
    site = _make_site(tmp_path_factory.mktemp("playground"), self_host=True)
    if not site.selfhosted:
        site.server.shutdown()
        pytest.skip("the pinned Pyodide could not be downloaded")
    yield site
    site.server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _editor(page):
    return page.get_by_label("Your code")


# -- before Run: no Pyodide, no server -------------------------------------------------------------


@pytest.mark.e2e
def test_nothing_heavy_loads_before_run(light_site, browser):
    page = browser.new_page()
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    try:
        page.goto(light_site.base + "/")
        expect(page.get_by_role("button", name="Run", exact=True)).to_be_visible()
        page.wait_for_timeout(500)
    finally:
        page.close()
    heavy = [u for u in urls if any(k in u for k in ("pyodide", ".whl", "frame.html", "worker.js"))]
    assert heavy == []


@pytest.mark.e2e
def test_the_editor_and_starters_read_with_javascript_off(light_site, browser):
    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    try:
        page.goto(light_site.base + "/")
        expect(_editor(page)).to_have_value(light_site.starters[0]["code"])
        expect(page.get_by_role("button", name="Run", exact=True)).to_be_hidden()
        expect(page.locator("details")).to_have_count(len(light_site.starters))
        expect(page.get_by_text("Nothing is sent anywhere")).to_be_visible()
    finally:
        ctx.close()


@pytest.mark.e2e
def test_tab_indents_and_escape_lets_tab_leave_the_editor(light_site, browser):
    page = browser.new_page()
    try:
        page.goto(light_site.base + "/")
        editor = _editor(page)
        editor.fill("")
        editor.press("Tab")
        expect(editor).to_have_value("    ")
        editor.press("Escape")
        editor.press("Tab")  # now it moves on, so the keyboard is never trapped
        assert page.evaluate("document.activeElement.className") != "indah-play-code"
    finally:
        page.close()


@pytest.mark.e2e
def test_picking_a_starter_and_reset_load_its_code(light_site, browser):
    page = browser.new_page()
    try:
        page.goto(light_site.base + "/")
        editor = _editor(page)
        second = light_site.starters[1]
        page.get_by_label("Start from").select_option(second["id"])
        expect(editor).to_have_value(second["code"])
        editor.fill("# my own code")
        page.get_by_role("button", name="Reset").click()
        expect(editor).to_have_value(second["code"])
    finally:
        page.close()


# -- Run: the real thing, in Pyodide ---------------------------------------------------------------


def _run(page, code):
    _editor(page).fill(code)
    page.get_by_role("button", name="Run", exact=True).click()


@pytest.mark.pyodide
def test_run_runs_a_typed_snippet_with_no_server(site, browser):
    page = browser.new_page(viewport={"width": 1100, "height": 900})
    problems: list[str] = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    try:
        page.goto(site.base + "/")
        code = (
            "import indah\n\n"
            "def build():\n"
            "    n = indah.Signal(0)\n"
            "    return indah.Column(children=[\n"
            '        indah.Button("Add one", lambda: n.set(n.value + 1)),\n'
            '        indah.Text(lambda: f"n = {n.value}"),\n'
            "    ])\n"
        )
        _run(page, code)
        frame = page.frame_locator("iframe")
        expect(frame.get_by_text("n = 0")).to_be_visible(timeout=BOOT_MS)
        frame.get_by_role("button", name="Add one").click()
        expect(frame.get_by_text("n = 1")).to_be_visible(timeout=20_000)
        expect(page.locator(".indah-play-status")).to_contain_text("Running")

        # edit and run again: a fresh worker, the new code
        _run(page, code.replace('f"n = ', 'f"count = '))
        expect(frame.get_by_text("count = 0")).to_be_visible(timeout=BOOT_MS)
        assert page.locator("iframe").count() == 1
    finally:
        page.close()
    assert not problems, problems


@pytest.mark.pyodide
@pytest.mark.parametrize(
    ("code", "shown"),
    [
        ("def build():\n    return 1 / 0", "ZeroDivisionError"),
        ("def build(:\n    pass", "SyntaxError"),
        ("x = 1", "Define a function `build()`"),
        ("def build():\n    return 'text'", "returned str, not an indah component"),
        # raised later, when the page connects (a lambda the component calls): still the reader's
        ("def build():\n    return indah.Text(lambda: undefined_name)", "NameError"),
    ],
)
def test_a_bad_snippet_shows_its_error_and_no_frame(site, browser, code, shown):
    page = browser.new_page(viewport={"width": 1100, "height": 900})
    try:
        page.goto(site.base + "/")
        _run(page, code)
        error = page.get_by_role("alert")
        expect(error).to_contain_text(shown, timeout=BOOT_MS)
        assert (
            "bridge.py" not in error.inner_text()
        )  # a traceback from their lines, not the runner's
        expect(page.locator(".indah-play-status")).to_contain_text("Your code raised an error")
        expect(page.locator("iframe")).to_have_count(0)
        expect(page.get_by_role("button", name="Stop")).to_be_disabled()
        # the page still works: a good snippet runs afterwards
        _run(page, "import indah\n\ndef build():\n    return indah.Text('recovered')\n")
        expect(page.frame_locator("iframe").get_by_text("recovered")).to_be_visible(timeout=BOOT_MS)
        expect(error).to_be_hidden()
    finally:
        page.close()


@pytest.mark.pyodide
def test_an_endless_loop_is_stopped_and_the_page_recovers(site, browser):
    page = browser.new_page(viewport={"width": 1100, "height": 900})
    try:
        page.goto(site.base + "/")
        started = time.perf_counter()
        _run(page, "def build():\n    while True:\n        pass\n")
        status = page.locator(".indah-play-status")
        expect(status).to_contain_text("did not return for 5 seconds", timeout=BOOT_MS)
        print(f"endless loop stopped {time.perf_counter() - started:.1f}s after Run")
        expect(page.locator("iframe")).to_have_count(0)
        _run(page, "import indah\n\ndef build():\n    return indah.Text('back again')\n")
        expect(page.frame_locator("iframe").get_by_text("back again")).to_be_visible(
            timeout=BOOT_MS
        )
    finally:
        page.close()


@pytest.mark.pyodide
def test_stop_removes_the_frame_and_says_so(site, browser):
    page = browser.new_page(viewport={"width": 1100, "height": 900})
    try:
        page.goto(site.base + "/")
        _run(page, "import indah\n\ndef build():\n    return indah.Text('hello')\n")
        expect(page.frame_locator("iframe").get_by_text("hello")).to_be_visible(timeout=BOOT_MS)
        page.get_by_role("button", name="Stop").click()
        expect(page.locator("iframe")).to_have_count(0)
        expect(page.locator(".indah-play-status")).to_contain_text("Stopped")
    finally:
        page.close()


@pytest.mark.pyodide
def test_playground_first_frame_is_within_the_budget_written_on_the_page(site, browser):
    """The docs page promises about 4 seconds once cached, and 4 to 6 on the first run.

    The name has ``first_frame`` so CI runs it alone, not in the parallel step where other pages'
    boots slow it (the same rule as the Studio's own first-frame test).
    """
    ctx = browser.new_context(viewport={"width": 1100, "height": 900})
    try:
        seconds = []
        for _ in range(2):  # the second run has the runtime in the HTTP cache
            page = ctx.new_page()
            page.goto(site.base + "/")
            t = time.perf_counter()
            page.get_by_role("button", name="Run", exact=True).click()
            expect(page.frame_locator("iframe").get_by_role("slider").first).to_be_visible(
                timeout=BOOT_MS
            )
            seconds.append(time.perf_counter() - t)
            page.close()
    finally:
        ctx.close()
    print(f"playground run to first frame: first {seconds[0]:.1f}s, cached {seconds[1]:.1f}s")
    assert seconds[1] <= 8, f"a cached run took {seconds[1]:.1f}s"
