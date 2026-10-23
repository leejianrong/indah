# ADR-0041: One docs-and-Studio: the docs run the Studio's pages in the browser with Pyodide

- Status: **Accepted** (option B, chosen by the owner 2026-10-23; supersedes the proposal of 2026-10-22)
- Date: 2026-10-23
- Deciders: Jian (owner)
- Relates to: ADR-0007 (docs site), ADR-0005 (public protocol), ADR-0038 (CSP), `docs/STUDIO.md`,
  `docs/spikes/pyodide.md` (IND-176, the feasibility spike)

## Context

`make demo` runs the **Studio**: 53 feature pages and 9 full apps, about 4,400 lines under
`examples/studio/`, each page a live demo with its own source. It is tested (`tests/e2e/test_studio.py`
opens every page under `csp="strict"`; `tests/unit/test_studio_coverage.py` requires a page for every
public name) but runs only from a checkout. The docs site (Zensical on GitHub Pages) shows code a reader
cannot run.

The owner's direction: **the docs and the Studio should be one thing for the user.** A reader reads about
a component and sees it work, with its source, on the same page. No separate hosted Studio, no hosted
playground. `make demo` must keep working exactly as it does now.

The Pyodide spike showed this is practical: the unmodified shell drives a real indah `Session` in a
Pyodide web worker, through a postMessage shim that replaces `EventSource` and `fetch("api/event")`.
55 of 68 Studio pages pass their own `check(pw)` hook unchanged. The first load is about 9 MB (gzip) and
4 to 6 seconds, so it must be on demand.

## Decision

**The docs site embeds Studio pages and runs them in the reader's browser. The Studio's page
definitions stay where they are and are reused as data.** There is no server for the docs examples, so
there is nothing to host, secure or pay for, and no code runs on our machines.

### 1. What stays the same

- `examples/studio/` is not moved, not put in the wheel, and not split into a package. `make demo`,
  `docs/STUDIO.md`, the page `check` hooks and the coverage test are unchanged.
- The playground chapter stays **local only**. A docs "Playground" page (IND-83) is a separate, later
  feature that runs the visitor's own typed code in their own browser; it does not reuse the server
  playground.
- The Fly gallery keeps its name and role: the owner's own whole apps. No Studio image is deployed.

### 2. How a docs page declares what it embeds

A docs page puts one line of HTML where the live example belongs:

```html
<indah-live page="layout/spacing"></indah-live>
```

`page` is `<chapter slug>/<page slug>`, the same id as the Studio URL `c/<chapter>/<page>`. Zensical
passes the tag through; a small script (`extra_javascript`, under 10 KB, no dependencies) defines the
element. Nothing else on the docs page needs to know about Pyodide.

The element renders, **without JavaScript running anything heavy**:

- the page's title and summary,
- its source in a real `<pre><code>` block, the same text the Studio shows (the build function's own
  source, so it cannot drift),
- a screenshot (`<img alt>`), generated at docs build time from the Studio e2e,
- a link "Open in the Studio" that points at the repository's `docs/STUDIO.md` run instructions
  (`make demo`, `/c/<chapter>/<page>`),
- a **Run it** button.

Only pressing **Run it** starts the browser runtime (section 5).

### 3. The page registry, as data

A build step exports the Studio's pages to `pages.json` (not committed; generated in the docs build):

```json
{"id": "layout/spacing", "title": "...", "summary": "...", "source": "def spacing(ctx): ...",
 "covers": ["Row", "Spacer"], "docs": "components.md", "runnable": true, "local_only": null,
 "screenshot": "assets/live/shots/layout-spacing.png"}
```

It is built by importing `examples.studio.core.discover()`, so the registry is the Studio, not a copy of it.
`Page` gains one optional field, `local_only: str | None = None`, a short reason. Nothing else about
`Page` changes and no existing page needs an edit unless it cannot run in a browser.

**Which pages are runnable.** A page is *runnable* unless it sets `local_only`. A runnable page must pass
its own `check(pw)` hook inside Pyodide in CI (section 8). That makes the mark honest: it is not a claim,
it is tested.

**The rule for the rest.** A page that needs a server or the owner's machine sets `local_only="<reason>"`.
The docs render its source and screenshot, replace **Run it** with a plain note ("This example needs a
server: <reason>. Run `make demo` to try it."), and never start a runtime for it. The initial list comes
from the spike (13 pages): the editor, module-component, favicon and download pages (they fetch `api/*`
files), the routing and context pages (URL paths), `live/topic` and `live/bounded` (no app object),
`media/upload` (multipart), `extend/context` (request headers) and the playground. The build card
(IND-184) fixes the ones it cheaply can, and each fix removes a mark. The 9 whole apps under `apps` are
`local_only` by default: they are ASGI apps with data files and extra dependencies, not a `Session`.

### 4. The docs bundle

The docs build produces a static bundle under `website/docs/assets/live/` (generated, git-ignored):

| File | What |
|------|------|
| `indah-<version>-py3-none-any.whl` | The wheel **built from the same commit** (`uv build --wheel`). |
| `studio.zip` | `examples/studio/` source (pure Python, about 4,400 lines), unpacked into the worker's file system. |
| `frame.html` | The shell from that wheel (`indah/static/index.html`) with `shim.js` injected first. Same origin as the docs, so an iframe needs no framing headers. |
| `shim.js`, `worker.js`, `bridge.py` | The postMessage transport, the worker, and the bridge that runs a `Session` (productionized from `spikes/pyodide/`). |
| `pages.json`, `shots/` | The registry and screenshots. |
| `runtime.json` | The pinned Pyodide version, the CDN base URL, the file list and the self-host flag. |

Each `<indah-live>` opens an `<iframe src="frame.html?page=<id>" title="...">` when run. One example runs
at a time per docs page: pressing **Run it** on another example terminates the first worker, so memory
stays at about 45 MB.

### 5. The worker boot protocol

The spike found that a module worker with top-level `await` drops messages posted before its handler
exists. The protocol is fixed:

1. `worker.js` sets `self.onmessage` **synchronously, before any `await`**. Messages that arrive before
   the runtime is ready go to a queue.
2. The page posts `{type: "boot", page, runtime}`. The worker loads Pyodide, then
   `micropip.install(<wheel url>, deps=False)` (`uvicorn` and `python-multipart` are not needed), unpacks
   `studio.zip`, imports the page by id and builds its `Session`.
3. The worker posts `{type: "ready"}`, then `init` and patch frames exactly as the server would
   (`init_message`, `patch_message`); the shim hands them to the shell's `EventSource` interface. Events
   go back as `{type: "event"}` and are answered with `{"ok": true}`.
4. Any failure posts `{type: "error", message}`; the element shows the message and the static fallback,
   not a blank frame.

### 6. Versioning

The bundle installs the wheel built from the commit being documented, so the docs always match the code
beside them (main's docs run main's code). The PyPI release matters only for the install text
(`pip install indah`). The Pyodide version is pinned in `runtime.json` and changes only by a reviewed
commit, because a Pyodide upgrade can change Python and package versions.

### 7. Size and loading rules

- **Nothing loads on page view.** The only code that runs is the element definition (under 10 KB). No
  runtime, no worker, no wheel, no network request for Pyodide until **Run it** is pressed. A test reads
  the network log.
- The **Run it** button states the cost ("Loads about 9 MB, then runs in your browser") and shows
  progress in an `aria-live` region. A **Stop** button terminates the worker.
- GitHub Pages does not let us set cache headers, so the runtime comes from **jsDelivr at the pinned
  version** (long-lived caching, shared across sites). The build can instead **self-host** the runtime
  (`runtime.json` `selfHost: true`), which is what CI uses so tests do not depend on a CDN, and what an
  offline copy of the docs would use. If the CDN fails the element shows the error and the link to run it
  locally; nothing breaks.
- **Budgets**, checked in CI: the wheel in the bundle at most 1 MB, the element script at most 10 KB,
  first frame at most 8 seconds on the CI machine from a warm cache. A release that exceeds one fails the
  build, so a later change cannot quietly make the first load worse.
- Pyodide needs `wasm-unsafe-eval`. The docs site sets no CSP today; if it ever does, `script-src` must
  allow that and the pinned CDN origin. This is noted in the docs build README.

### 8. The CI check

Two layers, matching the repo's fast and heavy tests:

- **Fast** (`tests/unit/test_docs_embeds.py`, no browser): every `<indah-live page="...">` in
  `website/docs/**` names a page in `discover()`; every `Page.docs` target is a real docs file; a
  `local_only` page has a reason; and the registry exports without error. A renamed or deleted Studio
  page fails the fast gate, not the docs readers.
- **Heavy** (a `live-examples` job in `.github/workflows/docs.yml`, on every PR that touches
  `examples/studio`, `src/indah`, `frontend`, `website` or the live runtime, and on `main`): build the
  docs, serve them, and for **every runnable page** open it in headless Chromium, run it in Pyodide and
  run the page's own `check(pw)`. It fails when a runnable page fails, when the budgets are exceeded, or
  when anything loads before **Run it**. It also lists `local_only` pages that now pass, as a note to
  promote them. The Pyodide runtime is cached with `actions/cache`. The starting point is the spike's
  `studio_pages.py`.

### 9. Accessibility and no JavaScript

- Without JavaScript the reader still gets the title, the summary, the source in a real code block, the
  screenshot with alt text and the link to run it locally. Nothing is lost except the live run.
- The button is a native `<button>`; status changes are announced; focus stays on the button and the
  iframe has a `title`. The shell inside is as accessible as the shell anywhere. A reader on a metered
  connection is never made to download anything: the click is the consent.

## Superseded alternatives (the proposal of 2026-10-22)

| Option | Why it lost |
|--------|-------------|
| **Host the Studio as its own container and embed `/embed/` pages in iframes** (proposed, then replaced) | Needs a deployed, patched-and-monitored server (Fly today, the homelab later, PAN-130), a new route with relaxed framing headers, and a hosted mode that removes the playground to avoid running visitors' code. Every visit costs us compute and every docs build depends on that host being up. It also makes the docs and the Studio two products, which is the opposite of the owner's direction. Pyodide removes all of it. |
| Embed the **gallery** instead of the Studio | The gallery shows heavy whole apps (models, maps), not features. |
| Static screenshots or recordings only | Not interactive, and they rot with every restyle. Kept only as the no-JavaScript fallback. |
| Put the Studio in the wheel, or a separate `indah-studio` package | Adds weight and a release train for something the docs do not need. Easy to add later from the same directory. |

## Consequences

- Option B needs **no deploy** and no server for the docs examples. The hosted-Studio cards (IND-173,
  IND-174) are superseded and closed.
- About 55 of 68 pages run in the docs on day one; the rest show their source and say why they need a
  server. The list shrinks as pages are fixed, and the CI check stops it from silently growing.
- The docs build gets heavier (wheel build, registry export, screenshots) and a heavy CI job. It runs only
  when the relevant paths change.
- A Studio page must stay Session-shaped to be runnable: no `api/*` file fetches, no request headers, no
  `ctx.app`. That is a small rule added to `docs/STUDIO.md`, and the CI check enforces it.
- IND-83 (the docs Playground) builds on the same runtime and bundle and needs no further server work.
- Risks: Pyodide upgrades change Python and packages (pinned, reviewed); `threading` and
  `run_in_threadpool` do not work in the browser (documented unsupported); phones and Safari were not
  measured in the spike, so the budget check and a mobile note belong to the first embed card.

## What the follow-up cards must do

1. **Registry** (IND-183): `Page.local_only`, the `pages.json` exporter, the initial marks from the
   spike table, the fast embed test, and the `docs/STUDIO.md` rule.
2. **Runtime and bundle** (IND-184): productionize the spike (`shim.js`, `worker.js`, `bridge.py`,
   `frame.html`), `scripts/build_docs_live.py`, the pinned `runtime.json`, the boot protocol, one example
   at a time, and a docs build step. Fix the cheap `local_only` pages (static `api/*` files, a minimal
   app object).
3. **The element and the first embed** (IND-181): `<indah-live>`, the static fallback, Run it and Stop,
   the quickstart example, and a test that nothing loads before the click.
4. **The CI check** (IND-185): the `live-examples` job, the budgets and the cache.
5. **Roll out** (IND-169): embeds on the components page and the guides; every runnable page with a docs
   target is embedded or listed as intentionally not.
6. **Release checklist** (IND-175): the docs bundle is built from the release commit and the gallery is
   redeployed (exact pin); there is no Studio deploy.
7. **Playground** (IND-83): a docs page where the visitor edits code and runs it, on the same bundle.
