"""The docs' live examples (ADR-0041, IND-184): a Studio page running in the browser with Pyodide.

Three layers, none needing an indah server:

* the **worker boot protocol** against a stub runtime (offline, fast): a ``connect`` or ``event``
  that arrives before the runtime is ready is queued and replayed in order, not lost;
* the **element**: nothing loads on page view, Run it opens one example, another Run it stops the
  first, a ``local_only`` page offers no Run it;
* a **real run** of a Studio page in Pyodide, using the page's own ``check(pw)`` (skipped when the
  pinned Pyodide cannot be downloaded, so a CI without network stays green).
"""

import functools
import http.server
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

ROOT = Path(__file__).resolve().parents[2]
ELEMENT = ROOT / "website" / "docs" / "javascripts" / "indah-live.js"

_TYPES = {".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm"}


class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **_TYPES}

    def end_headers(self):  # what GitHub Pages and a CDN send: a cached runtime is a warm one
        self.send_header("Cache-Control", "max-age=600")
        super().end_headers()

    def log_message(self, *args):
        pass


def _serve(directory: Path):
    handler = functools.partial(_Handler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


# -- the boot protocol, against a stub runtime ---------------------------------------------------

_STUB_PYODIDE = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export async function loadPyodide() {
  await sleep(400);  // the runtime takes a while: messages sent now must wait, not vanish
  let emit = null;
  let page = null;
  return {
    loadPackage: async () => {},
    globals: { set() {} },
    runPythonAsync: async () => {},
    unpackArchive() {},
    FS: { writeFile() {} },
    pyimport: () => ({
      init(p, fn) { emit = fn; page = p; },  // like the real bridge: no frame until a connect
      connect(sid) { emit("connect " + sid + " " + page); },
      event(body) { emit("event " + body); },
    }),
  };
}
"""

_PROTOCOL_PAGE = """<!doctype html><title>protocol</title><script type="module">
const w = new Worker("worker.js", { type: "module" });
window.frames_seen = [];
window.types_seen = [];
w.onmessage = (e) => {
  window.types_seen.push(e.data.type);
  if (e.data.type === "frame") window.frames_seen.push(e.data.data);
};
// A shell connects and posts events straight away, before the runtime exists.
w.postMessage({ type: "connect", sid: "s1" });
w.postMessage({ type: "event", body: "e1" });
w.postMessage({ type: "boot", page: "p/x", runtime: {
  base: "stub/", packages: [], wheel: "w.whl", studio: "studio.zip", bridge: "bridge.py" } });
w.postMessage({ type: "event", body: "e2" });  // after boot, still before ready
window.worker = w;
</script>"""


@pytest.mark.e2e
def test_worker_replays_messages_sent_before_ready(browser, tmp_path):
    (tmp_path / "stub").mkdir()
    (tmp_path / "stub" / "pyodide.mjs").write_text(_STUB_PYODIDE)
    (tmp_path / "worker.js").write_text((ROOT / "website" / "live" / "worker.js").read_text())
    (tmp_path / "studio.zip").write_bytes(b"")
    (tmp_path / "bridge.py").write_text("")
    (tmp_path / "index.html").write_text(_PROTOCOL_PAGE)
    server, base = _serve(tmp_path)
    page = browser.new_page()
    try:
        page.goto(base + "/")
        page.wait_for_function("window.types_seen.includes('ready')", timeout=15_000)
        page.wait_for_function("window.frames_seen.length >= 3", timeout=5_000)
        # connect and e1 were posted before boot, e2 after it; none was lost or reordered
        assert page.evaluate("window.frames_seen") == [
            "connect s1 p/x",
            "event e1",
            "event e2",
        ]
        assert page.evaluate("window.types_seen.indexOf('ready')") < page.evaluate(
            "window.types_seen.indexOf('frame')"
        )
    finally:
        page.close()
        server.shutdown()


# -- the element and a real run ------------------------------------------------------------------


@dataclass
class Site:
    base: str
    selfhosted: bool
    budget_seconds: float


def _docs_page(*pages: str) -> str:
    embeds = "\n".join(f'<indah-live page="{p}"></indah-live>' for p in pages)
    return (
        "<!doctype html><title>docs</title><main>\n"
        f"{embeds}\n</main>\n"
        '<script src="javascripts/indah-live.js"></script>'
    )


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """A tiny docs site: the built bundle, the element script and a page with three embeds."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_docs_live", ROOT / "scripts" / "build_docs_live.py"
    )
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)

    root = tmp_path_factory.mktemp("docs-live")
    selfhosted = True
    try:
        runtime = build.build_bundle(root / "assets" / "live", self_host=True)
    except OSError:  # no network for the pinned Pyodide: build against the CDN, skip real runs
        selfhosted = False
        runtime = build.build_bundle(root / "assets" / "live", self_host=False)
    (root / "javascripts").mkdir()
    (root / "javascripts" / "indah-live.js").write_text(ELEMENT.read_text())
    pages = (
        "start/choices",
        "start/reactive",
        "extend/context",
        "overlays/code-editor",
        "extend/bridge",
    )
    (root / "index.html").write_text(_docs_page(*pages))
    server, base = _serve(root)
    yield Site(
        base=base, selfhosted=selfhosted, budget_seconds=runtime["budgets"]["firstFrameWarmSeconds"]
    )
    server.shutdown()


@pytest.mark.e2e
def test_nothing_heavy_loads_before_run_it(site, browser):
    page = browser.new_page()
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    try:
        page.goto(site.base + "/")
        expect(page.get_by_role("button", name="Run it").first).to_be_visible()
        page.wait_for_timeout(500)
    finally:
        page.close()
    heavy = [
        u
        for u in urls
        if any(k in u for k in ("pyodide", ".whl", "studio.zip", "frame.html", "worker.js"))
    ]
    assert heavy == []  # only the page, the element script and pages.json were requested


@pytest.mark.e2e
def test_a_local_only_page_has_no_run_button_and_says_why(site, browser):
    page = browser.new_page()
    try:
        page.goto(site.base + "/")
        card = page.locator("indah-live[page='extend/context']")
        expect(card).to_contain_text("needs a server")
        expect(card.get_by_role("button")).to_have_count(0)
        expect(card.locator("pre code")).to_contain_text("def ")  # the source is still shown
    finally:
        page.close()


class _FramePage:
    """What a Studio check expects of ``pw.page``: locators in the frame, keys from the page."""

    def __init__(self, page, frame):
        self._page, self._frame = page, frame

    def __getattr__(self, name):
        return getattr(self._page if name == "keyboard" else self._frame, name)


@dataclass
class _Pw:  # what a Studio page's check(pw) receives
    page: object
    context: object = None
    base: str = ""
    url: str = ""


def _run(site, browser, page_id, ready, check=None, timeout=120_000):
    """Press Run it on ``page_id``, wait for ``ready(frame)``, then run the page's own check."""
    page = browser.new_page(viewport={"width": 1100, "height": 900})
    problems: list[str] = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    try:
        page.goto(site.base + "/")
        card = page.locator(f"indah-live[page='{page_id}']")
        card.get_by_role("button", name="Run it").click()
        expect(card.get_by_role("button", name="Stop")).to_be_visible()
        frame = card.frame_locator("iframe")
        ready(frame)
        expect(card.locator(".indah-live-status")).to_contain_text("Running")
        if check is not None:
            check(_Pw(page=_FramePage(page, frame), base=site.base + "/", url=page.url))
    finally:
        page.close()
    assert not problems, problems


def _need_pyodide(site):
    if not site.selfhosted:
        pytest.skip("the pinned Pyodide could not be downloaded")


@pytest.mark.e2e
def test_run_it_runs_a_studio_page_in_the_browser(site, browser):
    """The real thing: Pyodide, the wheel and the page's own check, with no server."""
    _need_pyodide(site)
    from examples.studio.chapters.start import choices_check

    page = browser.new_page(viewport={"width": 1100, "height": 900})
    try:
        page.goto(site.base + "/")
        first = page.locator("indah-live[page='start/choices']")
        first.get_by_role("button", name="Run it").click()
        frame = first.frame_locator("iframe")
        expect(frame.get_by_role("radiogroup", name="Level")).to_be_visible(timeout=120_000)
        choices_check(_Pw(page=_FramePage(page, frame)))

        # a second example stops the first (one worker at a time per docs page)
        second = page.locator("indah-live[page='start/reactive']")
        second.get_by_role("button", name="Run it").click()
        expect(first.locator("iframe")).to_have_count(0)
        expect(first.get_by_role("button", name="Run it")).to_be_visible()
        expect(second.locator("iframe")).to_have_count(1)
        second.get_by_role("button", name="Stop").click()
        expect(second.locator("iframe")).to_have_count(0)
    finally:
        page.close()


@pytest.mark.e2e
@pytest.mark.parametrize("page_id", ["overlays/code-editor", "extend/bridge"])
def test_pages_that_fetched_api_files_run_from_static_files(site, browser, page_id):
    """The editor module and a module component load from real files beside frame.html."""
    _need_pyodide(site)
    from examples.studio.core import discover

    entry = next(p for c in discover() for p in c.pages if f"{c.slug}/{p.slug}" == page_id)
    _run(
        site,
        browser,
        page_id,
        ready=lambda frame: expect(frame.locator("body")).not_to_contain_text(
            "connecting", timeout=120_000
        ),
        check=entry.check,
    )


@pytest.mark.e2e
def test_first_frame_within_the_warm_budget(site, browser):
    """Run it to the first frame, with the runtime already cached (ADR-0041 budget: 8 s)."""
    _need_pyodide(site)
    import time

    ctx = browser.new_context(viewport={"width": 1100, "height": 900})
    try:
        seconds = []
        for _ in range(2):  # the second run has the runtime in the HTTP cache
            page = ctx.new_page()
            page.goto(site.base + "/")
            card = page.locator("indah-live[page='start/choices']")
            t = time.perf_counter()
            card.get_by_role("button", name="Run it").click()
            expect(
                card.frame_locator("iframe").get_by_role("radiogroup", name="Level")
            ).to_be_visible(timeout=120_000)
            seconds.append(time.perf_counter() - t)
            page.close()
    finally:
        ctx.close()
    print(f"first frame: cold {seconds[0]:.1f}s, warm {seconds[1]:.1f}s")
    assert seconds[1] <= site.budget_seconds, f"warm first frame took {seconds[1]:.1f}s"
