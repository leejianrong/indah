"""Every runnable Studio page runs in the browser with Pyodide (ADR-0041, IND-185).

The docs show Studio pages live: the same page definitions as ``make demo``, running in a Pyodide
worker with no indah server. This test keeps that promise honest. It builds the docs bundle with
the pinned Pyodide self-hosted (cached under ``.cache/live-pyodide``), serves it with the cache
headers GitHub Pages and a CDN send, and for each page of the Studio:

* a **runnable** page is opened as a top-level ``frame.html?page=<id>``, waits for the shell to say
  "live", then runs the page's own ``check(pw)`` (the hook ``tests/e2e/test_studio.py`` uses). It
  fails on a console error, a page error or a failed request that the page does not declare;
* a **local-only** page is not run, but must say why (a non-empty reason, shown in the docs).
  ``STUDIO_PYODIDE_PROBE=1`` also tries those pages and prints the ones that now pass, as a note.

Marked ``pyodide`` (and not ``e2e``) so the fast browser job does not download a 9 MB runtime; it
runs in its own CI job. It skips with a clear message when the runtime cannot be downloaded.

    make test-pyodide      # 4 workers; or: uv run --extra e2e --extra docs pytest -m pyodide -n 4
"""

import fcntl
import functools
import http.server
import importlib.util
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

from examples.studio import registry  # noqa: E402
from examples.studio.core import discover  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CACHE_LOCK = ROOT / ".cache" / "live-pyodide.lock"
PROBE = os.environ.get("STUDIO_PYODIDE_PROBE") == "1"
# A page's check reloads, or waits on a server-shaped round trip, a little slower in Pyodide
# (hosted/secret-reveal reloads the page, which restarts the runtime: about 7 s).
EXPECT_TIMEOUT_MS = 20_000
BOOT_TIMEOUT_MS = 120_000

pytestmark = pytest.mark.pyodide

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


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """The docs bundle with the pinned Pyodide self-hosted, served over HTTP."""
    build = _load_build_script()
    out = tmp_path_factory.mktemp("studio-pyodide") / "live"
    # Each xdist worker builds its own bundle, but they share the Pyodide download cache: on a cold
    # cache (CI's first run) four workers writing it at once leave partial files and every first
    # page hangs. One build at a time; the later ones find the cache complete.
    CACHE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            runtime = build.build_bundle(out, self_host=True)
        except OSError as exc:  # no network and nothing cached for the pinned runtime
            pytest.skip(
                f"the pinned Pyodide {build.PYODIDE_VERSION} could not be downloaded: {exc}"
            )
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    handler = functools.partial(_Handler, directory=str(out))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield {"base": base, "runtime": runtime, "build": build}
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


@pytest.fixture(scope="module", autouse=True)
def _expect_timeout():
    expect.set_options(timeout=EXPECT_TIMEOUT_MS)
    yield
    expect.set_options(timeout=5_000)


@dataclass
class StudioPage:
    """What a page's ``check(pw)`` receives (the same shape tests/e2e/test_studio.py passes)."""

    page: object
    base: str
    url: str
    context: object = None


def _entries():
    out = {}
    for chapter in discover():
        for page in chapter.pages:
            out[f"{chapter.slug}/{page.slug}"] = page
    return out


ENTRIES = _entries()
PAGES = [p for p in registry.export_pages() if p["kind"] == "page"]


# frame.html is the top-level page here, so the shim has no parent to tell when the worker fails.
# Listen to the worker's messages ourselves, so a page that cannot start fails at once and says why.
_WATCH_WORKER = """
(() => {
  const Real = window.Worker;
  window.Worker = class extends Real {
    constructor(...args) {
      super(...args);
      this.addEventListener("message", (e) => {
        if (e.data && e.data.type === "error") window.__workerError = String(e.data.message);
      });
    }
  };
})();
"""


def _wait_live(page) -> None:
    """The shell says "live" once the worker has sent its first frame; a worker error ends it."""
    page.wait_for_function(
        "window.__workerError || [...document.querySelectorAll('.status span')]"
        ".some(s => s.textContent.trim() === 'live')",
        timeout=BOOT_TIMEOUT_MS,
    )
    error = page.evaluate("window.__workerError || null")
    if error:
        lines = error.strip().splitlines()
        raise RuntimeError(f"the page could not start in Pyodide: {lines[-1][:200]}")


def _run_page(bundle, browser, page_id: str) -> list[str]:
    """Open one page in Pyodide and run its own check. Returns the problems it saw."""
    entry = ENTRIES[page_id]
    base = bundle["base"]
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    ctx.add_init_script(_WATCH_WORKER)
    page = ctx.new_page()
    problems: list[str] = []

    def allowed(text: str) -> bool:
        return any(a in text for a in entry.expected_errors)

    page.on(
        "console",
        lambda m: (
            problems.append(f"console: {m.text}")
            if m.type == "error" and not allowed(m.text)
            else None
        ),
    )
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on(
        "response",
        lambda r: (
            problems.append(f"http {r.status}: {r.url}")
            if r.status >= 400 and not allowed(r.url) and not allowed(str(r.status))
            else None
        ),
    )
    # A page may fetch from a third party (a Map's tiles); only our own files must load.
    page.on(
        "requestfailed",
        lambda r: (
            problems.append(f"request failed: {r.url}")
            if r.url.startswith(base) and not allowed(r.url)
            else None
        ),
    )
    try:
        page.goto(f"{base}/frame.html?page={page_id}", wait_until="domcontentloaded")
        _wait_live(page)
        if entry.check is not None:
            entry.check(StudioPage(page=page, base=base + "/", url=page.url, context=ctx))
        page.wait_for_timeout(300)
    finally:
        ctx.close()
    return problems


@pytest.mark.parametrize("item", PAGES, ids=[p["id"] for p in PAGES])
def test_studio_page_in_pyodide(bundle, browser, item):
    if item["local_only"] is not None:
        reason = item["local_only"].strip()
        assert len(reason) >= 10, f"{item['id']}: local_only needs a real reason, got {reason!r}"
        if PROBE:
            try:
                problems = _run_page(bundle, browser, item["id"])
            except Exception as exc:  # noqa: BLE001
                problems = [f"{type(exc).__name__}: {str(exc).splitlines()[0][:100]}"]
            if not problems:
                print(f"\nNOTE: {item['id']} is local_only ({reason}) but now passes in Pyodide")
        return
    problems = _run_page(bundle, browser, item["id"])
    assert not problems, f"{item['id']} did not run cleanly in Pyodide: {problems}"


def test_every_page_is_runnable_or_says_why():
    """A page is never silently skipped: it runs, or it carries a reason."""
    silent = [p["id"] for p in PAGES if not p["runnable"] and not (p["local_only"] or "").strip()]
    assert not silent, f"pages that neither run nor say why: {silent}"
    assert any(p["runnable"] for p in PAGES)


def test_bundle_stays_within_its_budgets(bundle):
    problems = bundle["build"].budget_problems(bundle["runtime"]["sizes"])
    assert not problems, problems


def test_first_frame_within_the_warm_budget(bundle, browser):
    """Page load to "live" with the runtime already cached (budget: runtime.json)."""
    budget = bundle["runtime"]["budgets"]["firstFrameWarmSeconds"]
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    seconds = []
    try:
        for _ in range(2):  # the second load has the runtime cached, as a repeat visitor does
            page = ctx.new_page()
            t = time.perf_counter()
            page.goto(f"{bundle['base']}/frame.html?page=start/choices")
            _wait_live(page)
            seconds.append(time.perf_counter() - t)
            page.close()
    finally:
        ctx.close()
    print(f"\nfirst frame: cold {seconds[0]:.1f}s, warm {seconds[1]:.1f}s (budget {budget}s)")
    assert seconds[1] <= budget, f"warm first frame took {seconds[1]:.1f}s, budget {budget}s"
