"""Run the Studio's own browser checks against pages served from Pyodide (no indah server).

For every Studio page: open the unmodified shell with the page built in a Pyodide worker, then
call the page's own ``check(pw)`` (the same hook tests/e2e/test_studio.py uses). Prints one line
per page and a summary.

    uv run --extra e2e python spikes/pyodide/studio_pages.py [slug-filter]
"""

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from examples.studio.core import discover  # noqa: E402

import serve  # noqa: E402

CACHE = Path(__file__).parent / ".cache"


@dataclass
class StudioPage:
    page: object
    base: str
    url: str
    context: object = None


def main(only: str | None) -> None:
    wheels = sorted((CACHE / "wheels").glob("indah-*.whl"))
    (CACHE / "wheels" / "index.json").write_text(json.dumps({"name": wheels[-1].name}))
    server, base = serve.serve()
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
        for chapter in discover():
            for entry in chapter.pages:
                name = f"{chapter.slug}/{entry.slug}"
                if only and only not in name:
                    continue
                page = ctx.new_page()
                problems: list[str] = []
                page.on(
                    "pageerror", lambda e, problems=problems: problems.append(f"pageerror: {e}")
                )
                t = time.perf_counter()
                status, detail = "pass", ""
                try:
                    page.goto(f"{base}/?mode=nodeps&page={name}")
                    spike_err = None
                    page.wait_for_function(
                        "window.__spike.frames > 0 || window.__spike.errors.length", timeout=45_000
                    )
                    page.wait_for_timeout(300)  # let the shell paint the first snapshot
                    spike_err = page.evaluate("window.__spike.errors[0] || null")
                    if spike_err:
                        raise RuntimeError(spike_err.strip().splitlines()[-1][:160])
                    if entry.check is not None:
                        entry.check(
                            StudioPage(page=page, base=base + "/", url=page.url, context=ctx)
                        )
                except Exception as exc:  # noqa: BLE001
                    status = "FAIL"
                    detail = (
                        str(exc).strip().splitlines()[0][:140]
                        if str(exc).strip()
                        else type(exc).__name__
                    )
                results.append((name, status, detail, round(time.perf_counter() - t, 1)))
                print(f"{status:4} {name:38} {results[-1][3]:>5}s  {detail}", flush=True)
                page.close()
        browser.close()
    server.shutdown()
    ok = sum(1 for r in results if r[1] == "pass")
    print(f"\n{ok} of {len(results)} Studio pages pass their own check in Pyodide")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
