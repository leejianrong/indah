# Spike: indah in the browser with Pyodide (IND-176, 83a)

- Date: 2026-10-23
- Question (ADR-0041, decision 5): does indah run in Pyodide, how long does it take to boot, how big is
  it, and can a postMessage shim replace `fetch` and `EventSource` so the existing shell talks to an
  in-browser `Session`?
- Code: `spikes/pyodide/` (throwaway, not shipped, nothing under `src/` or `frontend/` changed).
- Tested with: Pyodide 314.0.7 (CPython 3.14.2), indah 0.6.0 built from `main`, headless Chromium
  through Playwright, one machine (WSL2). Local file server unless a line says "CDN".

## Verdict

**Go, for a small build, loaded on demand.** It works better than the ADR assumed. The unmodified
shell renders and drives a real indah `Session` running in a Pyodide web worker, with no server at all.
55 of 68 Studio pages pass their own browser check unchanged. The costs are a first load of about 9 MB
(gzip) and 4 to 6 seconds, so it must never load unless the reader asks for it. It does not replace the
hosted iframe route (IND-173, IND-174): it is the right tool for "edit the code and run it" and for
anything that must not execute on our machines.

## 1. Does indah install and import in Pyodide?

Yes, with no change to indah.

- `micropip.install(indah wheel)` works. The wheel is pure Python (550 KB).
- Pyodide already ships `pydantic` (with a compiled `pydantic-core`), `starlette`, `anyio`, `h11` and
  `click`. Only `uvicorn` and `python-multipart` are not shipped, and indah imports both lazily.
- **Use `deps=False`.** Installing with dependencies pulled `uvicorn` and `python-multipart` from PyPI at
  run time (about 1 s more, and a network call to PyPI), and nothing in the browser uses them. With
  `deps=False`, `import indah` and `indah.create_app(...)` both work.
- Core-only is not needed: `import indah` always imports `indah.app` (so Starlette), and that is fine here.
  A core-only import would still need `indah/__init__.py` to stop importing `app`; not worth doing.
- A release from PyPI works too: `micropip.install("indah==0.5.0", deps=False)` booted the same page
  (the 0.6.0 release was not on PyPI yet when tested).

## 2. Does a postMessage transport work with the existing shell?

Yes. The shell is untouched. A 74-line script (`shim.js`) runs before it and replaces two things:

- `window.EventSource` with a class that receives frames from the worker (`api/stream`);
- `fetch("api/event")` with a `postMessage` to the worker, answered with `{"ok": true}`.

The worker (`worker.js`) boots Pyodide and runs `bridge.py` (78 lines). The bridge builds the page with
`InMemorySessionStore`, subscribes to the session's `Hub`, sends `init_message`, forwards every message the
hub publishes, and turns each event into `session.dispatch(...)` plus `hub.publish(patch_message(...))`
(what `_event` and `_publish_result` do, minus HTTP). That the protocol is a public contract and the
transport is separable (ADR-0005) held up in practice.

Proof: `studio_pages.py` opens each Studio page from the browser with no indah server and runs the page's
own `check(pw)` hook (the one `tests/e2e/test_studio.py` uses).

- **55 of 68 pass**, including tables, streaming text, a chat, `ctx.every`, toast actions, `Menu`, `Chips`,
  `Skeleton`, secret reveal, policy and custom components.
- The 13 that fail, grouped by the cause I think applies (I looked at the check each one runs but did not
  debug each separately):

| Cause | Pages | Fix in a build |
|-------|-------|----------------|
| `api/*` GET routes missing (editor module, module-component JS, favicon, file download) | `overlays/code-editor`, `extend/bridge`, `live/tab-title`, `media/download` | Serve those files as static files next to the page; `Bridge.svelte` and the editor use `import(url)`, so a service worker or real files are needed, not a `fetch` shim |
| Studio URL paths (`ctx.path` is `/links`, the check expects a URL under `c/<chapter>/`) | `overlays/context`, `routing/links`, `routing/navitem`, `routing/navigate` | A path scheme for the embedding page; routing itself (`pushState`) is client side |
| No app object (`Topic`, `ctx.tail` read `ctx.app`) | `live/topic`, `live/bounded` | Give the bridge a minimal app state; `live/topic` fails to build without it |
| Multipart upload | `media/upload` | Pass the `File` bytes through `postMessage` |
| Request headers (`ConnectionInfo`) | `extend/context` | Fill `ConnectionInfo` from `navigator` |
| The playground itself | `playground/run` | Needs its own page; running typed code is safe here, it is the visitor's own browser |

## 3. Numbers

Boot (nodeps, local server; Chromium, one machine; times from worker start, ms):

| Step | Time |
|------|------|
| `loadPyodide` (compile and start the wasm runtime) | 1,900 to 2,000 |
| load `micropip`, `pydantic`, `starlette`, `anyio`, ... | +300 |
| install the indah wheel | +350 to 400 |
| `import indah`, build the page | +950 to 1,300 |
| first frame at the page | 3,600 to 4,200 |
| shell shows the page (from navigation) | 3.9 to 4.5 s |

The same boot measured three ways (first paint from navigation):

| Case | First paint |
|------|-------------|
| Local mirror, indah wheel local | 3.9 to 4.5 s (a second load is the same: nothing is cached across runs except the HTTP cache) |
| jsDelivr CDN, first visit | 6.0 s (runtime start 3.2 to 3.4 s) |
| jsDelivr CDN, HTTP-cached | 3.95 s |
| `deps=True` (PyPI for `uvicorn`, `python-multipart`) | 4.5 to 5.0 s |
| indah 0.5.0 from PyPI, `deps=False` | 4.5 to 5.0 s |

An event round trip (click, worker, patch, DOM) is fast: two clicks and the text update came in about 120 ms
including the test driver, and a handler that updated a signal every 0.2 s delivered five patches.

Download for one page (files the browser fetched; gzip -9, so a lower bound on what a Brotli CDN sends):

| File | Raw | gzip |
|------|-----|------|
| `pyodide.asm.wasm` | 9.60 MB | 3.53 MB |
| Pyodide runtime JS and lock file | 1.39 MB | 0.29 MB |
| `python_stdlib.zip` | 2.55 MB | 2.50 MB |
| 11 Python packages (`pydantic-core` 1.3 MB of it) | 2.30 MB | 2.27 MB |
| indah wheel | 0.55 MB | 0.55 MB |
| **Total** | **16.4 MB** | **9.1 MB** |
| The shell page (already served by docs) | 0.56 MB | 0.24 MB |

Memory: the worker's wasm heap was 45 MB after boot with one page loaded. Browser-wide memory was not
measured.

Not measured: a phone or a throttled CPU (expect two to four times slower start), Firefox and Safari,
Brotli sizes, and the time to install large optional packages (`numpy`, `matplotlib`).

## What works and what does not

| Behaviour | Result |
|-----------|--------|
| `asyncio` handlers, `asyncio.sleep`, `ctx.spawn`, `ctx.every`, `loop.call_later` (the 100 ms append coalescer) | Works |
| `Stream` appends, `StreamText` token streaming, `Chat` | Works |
| `asyncio.to_thread` | Works |
| `starlette.concurrency.run_in_threadpool` (anyio worker threads) | **Fails** (`can't start new thread`); only the ASGI layer uses it, which the bridge does not |
| A handler that blocks (`time.sleep`) | Blocks the worker only; the page stays live |
| `numpy`, `matplotlib`, `PIL` | Present only as extra Pyodide packages (more download); not tested |
| Sessions, auth, `secure=True`, rate limits, CSP report | Not applicable: there is no server and one viewer |
| Racing the worker | A module worker that uses top-level `await` drops messages posted before its handler is set. The first run lost the `connect` message on a slow CDN start. Install `onmessage` synchronously and `await` inside it |

## 4. Recommendation

**Go: build it, small, lazy, and next to the iframe route rather than instead of it.** Why:

- It runs the real Python on the visitor's own machine, so "edit the code and run it" needs no server and no
  code-execution risk. That is the thing the hosted Studio cannot offer (the playground stays local-only).
- The shim is tiny and the shell needs no change, so the maintenance cost is a bridge of about 100 lines.
- The cost is mostly download (9 MB gzip, about 6 s on a cold CDN), so it only makes sense behind a
  "Run this example" button, never on page load. Cached, a second run starts in about 4 s.

What the build card (IND-83) must include:

1. A docs "Run it" component: lazy-loads Pyodide from a pinned version on click, shows progress, and falls
   back to a link to the hosted Studio page. Reuse `spikes/pyodide/{shim.js,worker.js,bridge.py}`.
2. Install `indah` from PyPI at the docs version (`micropip.install("indah==X.Y.Z", deps=False)`); the docs
   build knows the version. Pin the Pyodide version and host the runtime files with the docs, or use
   jsDelivr with a pinned URL and `integrity` where possible.
3. Static files for the `api/*` GET routes the shell fetches (`api/editor.js`, module components, favicon),
   an upload path through `postMessage`, a minimal app object for `Topic` and `ctx.tail`, and a path scheme.
4. A CI test that builds the docs and runs the examples with Playwright (the spike's `studio_pages.py` is
   the starting point), so a library release that breaks the browser build fails.
5. Size and time budgets in the card, so a later release cannot quietly make the first load worse.

Expected cost: the 5 points on IND-83 are reasonable; the risk is the long tail of server-shaped features
(second table above), which the card should declare out of scope and list on the page.

**Smallest next card:** "Docs: a lazy 'Run it' button for the quickstart example" (about 2 points):
the shim, worker and bridge from the spike, the docs build step, one example, one Playwright test. It
proves the delivery path end to end before the full playground.

IND-169 (live docs) does not wait for this: the iframe route stays the plan for the Studio pages.

## Reproduce

```bash
python spikes/pyodide/fetch_pyodide.py                   # pinned runtime + packages into .cache (git-ignored)
uv build --wheel -o spikes/pyodide/.cache/wheels
uv run --extra e2e python spikes/pyodide/run_spike.py nodeps       # boot times (also: full, nodeps-cdn)
uv run --extra e2e python spikes/pyodide/run_spike.py nodeps 0.5.0 # a release from PyPI
uv run --extra e2e python spikes/pyodide/edge_cases.py nodeps
uv run --extra e2e python spikes/pyodide/studio_pages.py           # every Studio page against its own check
```
