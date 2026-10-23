"""Edge cases: run snippets inside the Pyodide worker of the running page and print what happened.

uv run --extra e2e python spikes/pyodide/edge_cases.py
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
import serve  # noqa: E402

CACHE = Path(__file__).parent / ".cache"

CASES = {
    "every Studio page builds and snapshots": """
import importlib, pkgutil, json, indah
import examples.studio.chapters as chs
ok, bad = 0, {}
for info in pkgutil.iter_modules(chs.__path__):
    try:
        chapter = importlib.import_module(f"examples.studio.chapters.{info.name}").CHAPTER
    except BaseException as e:
        bad[f"module {info.name}"] = f"{type(e).__name__}: {str(e)[:70]}"
        continue
    for page in chapter.pages:
        try:
            s = indah.Session(page.build(indah.Context("x"))); s.snapshot(); ok += 1
        except BaseException as e:
            bad[f"{info.name}/{page.slug}"] = f"{type(e).__name__}: {str(e)[:70]}"
json.dumps({"build_ok": ok, "failed": len(bad), "failures": bad}, indent=1)
""",
    "installed packages": """
import micropip, json
json.dumps(sorted(f"{k}=={v.version}" for k, v in micropip.list().items() if k in ("indah","uvicorn","python-multipart","starlette","anyio","pydantic","pydantic-core","h11","click")))
""",
    "import indah + core names": """
import indah
f"indah {indah.__version__}: Signal, Text, Table, Chips, Menu, Session ok" if all(hasattr(indah, n) for n in ("Signal","Text","Table","Chips","Menu","Session")) else "MISSING"
""",
    "import indah.launch / uvicorn": """
import importlib
try:
    importlib.import_module("uvicorn"); r = "uvicorn imports"
except Exception as e:
    r = f"uvicorn: {type(e).__name__}: {e}"
r
""",
    "create_app (ASGI) builds": """
import indah
app = indah.create_app(session_factory=lambda: indah.Session(indah.Text("hi")))
type(app).__name__
""",
    "asyncio streaming handler (0.2 s ticks)": """
import asyncio, json, indah
from indah.session_store import InMemorySessionStore
out = indah.Signal("")
async def run():
    for ch in "hello":
        out.set(out.value + ch)
        await asyncio.sleep(0.2)
sess = indah.Session(indah.Column(children=[indah.Text(out)]))
store = InMemorySessionStore(lambda: sess)
h = store.get_or_create("t"); q = h.hub.subscribe()
h.session.spawn(run())
got = []
for _ in range(5):
    off, msg = await asyncio.wait_for(q.get(), 3)
    got.append(msg["type"])
f"{len(got)} patches streamed: {got[:2]}..."
""",
    "Stream append coalescer (call_later)": """
import asyncio, indah
from indah.session_store import InMemorySessionStore
s = indah.Stream(limit=100)
sess = indah.Session(indah.Column(children=[indah.Table(columns=[indah.Col("a")], rows=s)]))
h = InMemorySessionStore(lambda: sess).get_or_create("t2"); q = h.hub.subscribe()
for i in range(50): s.append({'a': i})
off, msg = await asyncio.wait_for(q.get(), 3)
f"{msg['type']} with {len(msg['changes'][0].get('append', {}).get('rows', []))} rows in one patch"
""",
    "asyncio.to_thread (threads)": """
import asyncio
try:
    await asyncio.to_thread(lambda: 1); r = "to_thread works"
except BaseException as e:
    r = f"to_thread: {type(e).__name__}: {e}"
r
""",
    "starlette run_in_threadpool (anyio worker threads)": """
from starlette.concurrency import run_in_threadpool
try:
    await run_in_threadpool(lambda: 1); r = "threadpool works"
except BaseException as e:
    r = f"threadpool: {type(e).__name__}: {e}"
r
""",
    "blocking time.sleep(0.3) in a handler": """
import time
t = time.perf_counter(); time.sleep(0.3); f"blocked the worker {round(time.perf_counter()-t,2)} s (UI stays live: the worker is separate)"
""",
    "numpy (Pyodide package, not in the lock cache)": """
import importlib
try:
    importlib.import_module("numpy"); r = "numpy present"
except Exception as e:
    r = f"numpy: {type(e).__name__}"
r
""",
}


def main() -> None:
    wheels = sorted((CACHE / "wheels").glob("indah-*.whl"))
    (CACHE / "wheels" / "index.json").write_text(json.dumps({"name": wheels[-1].name}))
    server, base = serve.serve()
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{base}/?mode={mode}")
        page.get_by_role("button", name="Add one").wait_for(timeout=60_000)
        print(f"mode={mode}")
        for name, code in CASES.items():
            value = page.evaluate("code => window.__spike.py(code)", code)
            print(f"- {name}: {value}")
        browser.close()
    server.shutdown()


if __name__ == "__main__":
    main()
