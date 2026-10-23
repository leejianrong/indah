"""Run the Pyodide spike in headless Chromium and print the measurements.

uv build --wheel -o spikes/pyodide/.cache/wheels
python spikes/pyodide/fetch_pyodide.py
uv run --extra e2e python spikes/pyodide/run_spike.py [full|nodeps]
"""

import gzip
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
import serve  # noqa: E402

CACHE = Path(__file__).parent / ".cache"


def _transfer(urls: list[str]) -> dict:
    """Raw and gzip -9 bytes of every file the page took from the local mirror."""
    out: dict[str, list[int]] = {}
    for url in dict.fromkeys(urls):
        path = urlparse(url).path
        for prefix, root in (("/pyodide/", CACHE / "pyodide"), ("/wheels/", CACHE / "wheels")):
            f = root / path[len(prefix) :]
            if path.startswith(prefix) and f.is_file():
                raw = f.read_bytes()
                kind = (
                    "wasm"
                    if f.suffix == ".wasm"
                    else "runtime js"
                    if f.suffix == ".mjs"
                    else "stdlib zip"
                    if f.suffix == ".zip"
                    else "lock file"
                    if f.suffix == ".json"
                    else "indah wheel"
                    if f.name.startswith("indah")
                    else "python packages"
                )
                row = out.setdefault(kind, [0, 0, 0])
                row[0] += len(raw)
                row[1] += len(gzip.compress(raw, 9))
                row[2] += 1
    return {k: {"raw": v[0], "gzip": v[1], "files": v[2]} for k, v in out.items()}


def main(mode: str, pypi: str | None = None) -> dict:
    wheels = sorted((CACHE / "wheels").glob("indah-*.whl"))
    name = f"pypi:{pypi}" if pypi else wheels[-1].name
    (CACHE / "wheels" / "index.json").write_text(json.dumps({"name": name}))
    server, base = serve.serve()
    out = {"mode": mode, "wheel": name, "wheel_bytes": wheels[-1].stat().st_size}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()  # one context so the second load can use the HTTP cache
        for label in ("cold", "warm"):
            page = ctx.new_page()
            logs: list[str] = []
            urls: list[str] = []
            page.on("response", lambda r, urls=urls: urls.append(r.url))
            page.on("console", lambda m, logs=logs: logs.append(f"{m.type}: {m.text}"[:300]))
            page.on("pageerror", lambda e, logs=logs: logs.append(f"pageerror: {e}"[:300]))
            t = time.perf_counter()
            page.goto(f"{base}/?mode={mode}")
            run = {}
            try:
                btn = page.get_by_role("button", name="Add one")
                btn.wait_for(timeout=60_000)
                run["first_paint_s"] = round(time.perf_counter() - t, 2)
                btn.click()
                btn.click()
                page.get_by_text("n = 2").wait_for(timeout=10_000)
                run["event_roundtrip_ok"] = True
                run["roundtrip_ms"] = round(
                    (time.perf_counter() - t) * 1000 - run["first_paint_s"] * 1000
                )
            except Exception as exc:  # noqa: BLE001
                run["error"] = str(exc).splitlines()[0][:200]
                run["first_paint_s"] = None
            spike = page.evaluate("window.__spike")
            run["marks_ms"] = {k: round(v) for k, v in spike["marks"].items()}
            run["stats"] = spike["stats"]
            run["worker_errors"] = [e[:1500] for e in spike["errors"][:1]]
            run["frames"] = spike["frames"]
            run["transfer"] = _transfer(urls)
            run["console"] = [m for m in logs if not m.startswith("log:")][:6]
            if label == "cold":
                page.screenshot(path=str(CACHE / f"shot-{mode}.png"))
            out[label] = run
            page.close()
        browser.close()
    server.shutdown()
    return out


if __name__ == "__main__":
    print(
        json.dumps(
            main(
                sys.argv[1] if len(sys.argv) > 1 else "full",
                sys.argv[2] if len(sys.argv) > 2 else None,
            ),
            indent=2,
        )
    )
