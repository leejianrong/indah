# The Studio (`make demo`)

One app that shows every feature of indah, live, with the source under each demo. It replaces the
old per-feature `make demo-*` targets.

```
make demo          # = uv run python -m examples.studio   (prints a URL)
```

## Layout

| URL | What |
|-----|------|
| `/` | home: a card per chapter |
| `/c/<chapter>/` and `/c/<chapter>/<page>` | feature pages: a small live demo, its source, its docs links |
| `/apps/<app>/ui/` | whole example apps (the realistic dashboards), mounted as-is |
| `/apps/hosted/` | the multi-user demo (sign in as bob, alice or carol in separate profiles) |
| `/play/<id>/` | a playground run (your code, run on this machine) |

Code: `examples/studio/` (`core.py` types and shell, `app.py` the parent app, `playground.py`,
`chapters/*.py` one module per chapter). Every chapter app and mounted example runs under
`csp="strict"`.

## Add a page (when indah gains a feature)

1. Pick the chapter module in `examples/studio/chapters/` (or add a new one: it just needs a
   `CHAPTER = Chapter(...)`; it is found automatically).
2. Write a build function and a `Page`:

   ```python
   def my_feature(ctx: indah.Context) -> indah.Component:
       value = indah.Signal(1)
       return indah.Column(children=[indah.MyThing(value), indah.Text(lambda: str(value.value))])


   def my_feature_check(pw) -> None:  # what to click, what to expect
       from playwright.sync_api import expect

       expect(pw.page.get_by_text("1")).to_be_visible()


   Page(
       slug="my-feature",
       title="My feature",
       summary="What the viewer is looking at.",
       build=my_feature,
       covers=("MyThing",),
       docs="components.md",
       check=my_feature_check,
   )
   ```
3. List every public name the page demonstrates in `covers`. The source shown under the demo is
   the build function itself, so it never drifts.
4. `make check` runs `tests/unit/test_studio_coverage.py`, which fails if a name in
   `indah.__all__` has no page and is not in `core.EXEMPT` (with a reason). The browser test
   `tests/e2e/test_studio.py` opens every page and runs its `check`, and fails on console
   errors, failed requests and CSP violations. Screenshots land in `/tmp/studio-shots`
   (`STUDIO_SHOTS` to change it); read them.
5. Show it in the docs: put `<indah-live page="<chapter>/<slug>"></indah-live>` in the docs page that
   `docs=` names (see "Show a page live in the docs" below). The test summary warns when a runnable
   page with a docs target has no embed.

Rules for demos: keep them small (one idea per page), deterministic (no random data without a
seed), and free of secrets. User-facing text uses hyphens, not em-dashes. A page may run work in
the background, but anything that must run for the life of the Studio (a producer feeding a
`Topic`) goes in the chapter's `lifespan`.

## Keep a page Session-shaped (the docs run it in the browser)

The docs site runs Studio pages in the reader's browser with Pyodide (ADR-0041, `<indah-live
page="chapter/page">`). A page runs there only if it is a plain `Session`: its build function returns a
component and nothing else is needed. To stay runnable, a page must not

- fetch `api/*` files (the editor module, a module component's JavaScript, favicons, downloads),
- read request headers or the Studio's own URL paths (`ctx.conn`, `ctx.path` under `c/<chapter>/`),
- use `ctx.app` (`Topic`, `ctx.tail`), or
- take a multipart upload.

If a page genuinely needs one of those, mark it with a reason and move on:

```python
Page(slug="my-feature", ..., local_only="it is served from api/my-file, which the browser has no route for")
```

A `local_only` page is still shown in the docs (source and screenshot), without a Run it button, and the
reason is printed beside it. Whole apps (`AppEntry`) are local only by default. A runnable page must pass
its own `check(pw)` inside Pyodide in CI (IND-185), so a page that breaks the rule fails there.

`uv run python scripts/export_studio_pages.py build/pages.json` exports every page as data for the docs
build, and `scripts/export_studio_pages.py --check` (also `tests/unit/test_docs_embeds.py`) fails when a
`<indah-live page="...">` in `website/docs` names a page that does not exist.

For a whole app (not a snippet), add an `AppEntry` to the `apps` chapter.

To vet every page at a glance, turn the screenshots into one sheet per chapter:
`uv run --extra e2e python scripts/studio_contact_sheet.py /tmp/studio-shots`.

## The playground

`/c/playground/` runs code the viewer types: `def build(): return <component>`. It **executes in
the server process**, so it is offered to loopback clients only and the page says so. Each run is
mounted under `/play/<id>/` (the last 16 are kept). A snippet that loops forever is reported after 5
seconds, but Python cannot kill a thread, so it keeps running until the server restarts.

## Show a page live in the docs (ADR-0041)

The docs site runs Studio pages in the reader's browser with Pyodide, so a reader sees a component work
beside the text that explains it. Put one line where the example belongs, in any page under
`website/docs/`:

```html
<indah-live page="start/choices"></indah-live>
```

`page` is `<chapter slug>/<page slug>` (the Studio URL `c/<chapter>/<page>`). The reader sees the page's
title, summary and source (the build function's own text, so it cannot drift) and a **Run it** button.
Nothing loads until they press it; then about 9 MB of runtime downloads and the page runs from a worker
with no server. Pressing **Run it** on another example stops the first.

- `make docs` builds the bundle (`scripts/build_docs_live.py bundle`: the wheel from this commit,
  `studio.zip`, `frame.html`, the worker, `pages.json`, `runtime.json`), then the site, then fills the
  embeds so they read without JavaScript (`finalize`). `make docs-serve` builds the bundle first.
- A page that cannot run in a browser sets `local_only="<reason>"`; its embed shows the source and the
  reason and has no button. The `tests/unit/test_docs_embeds.py` gate fails when an embed names a page
  that does not exist.
- A page runs in the docs when it stays Session-shaped (see the rule above). The shell's `api/*` GET
  routes do not exist on a static site; the bundle writes `api/editor.js` and each registered module
  component as real files beside `frame.html`, which is why `overlays/code-editor` and `extend/bridge`
  run. A route that serves per-session data (a download, a favicon) cannot, so those stay `local_only`.
- **Try it: every documented component is shown live.** A new public name needs a Studio page *and* an
  embed in the docs page its `docs=` points at (put it next to the text that explains it, or in the
  "Try these live" block under the component's table in `components.md`). A page the docs cannot run
  (`local_only`) is embedded too: the reader gets its source and the reason. Nothing starts before
  **Run it**, and only one example runs at a time, so a page can carry many embeds. The check
  `tests/unit/test_docs_embeds.py::test_documented_pages_have_a_live_embed` is a warning, not a
  failure: it names every runnable page with a docs target that no docs page embeds. List them
  yourself with `uv run python scripts/export_studio_pages.py --unembedded` (empty means all shown).
- Runtime files: `website/live/` (`shim.js`, `worker.js`, `bridge.py`) and
  `website/docs/javascripts/indah-live.js` (the element). The Pyodide version is pinned in
  `scripts/build_docs_live.py`; it loads from the jsDelivr CDN at that version, and
  `bundle --self-host` copies it into the bundle for tests and offline copies.
- Budgets (checked by the build and `tests/e2e/test_docs_live.py`): the wheel in the bundle at most
  1 MB, the element script at most 10 KB, Run it to the first frame at most 8 s with a warm cache.
- Try it locally: `uv run --extra e2e pytest tests/e2e/test_docs_live.py`.

## Every page also runs in the docs (Pyodide)

The docs show Studio pages live in the reader's browser (ADR-0041), so a page is written once and
runs in two places: on your machine under `make demo`, and in a Pyodide worker with no indah server.
Keep a page `Session`-shaped (a build function returning a component) and it runs in both. A page
that needs a server (an upload, a `Topic` fed by the chapter's lifespan, request headers, a URL
path) is marked `local_only="<why>"` on its `Page`; the docs then show its source and the reason,
with no Run it button.

`tests/e2e/test_studio_pyodide.py` keeps this honest:

- every page that is not `local_only` is opened as a top-level `frame.html?page=<id>` in headless
  Chromium, waits for the shell to say "live", runs the page's own `check(pw)` and fails on a
  console error, a page error or a failed request to our own files; a page whose worker cannot start
  fails at once with the Python error;
- a `local_only` page is not run but must have a reason (a page cannot be silently skipped);
- the bundle stays within its budgets and the warm first frame within `firstFrameWarmSeconds`
  (both from `runtime.json`).

Run it locally (the pinned Pyodide is downloaded once into `.cache/live-pyodide`; it skips with a
message when it cannot be fetched):

```
make test-pyodide                      # four workers, about 3 minutes
uv run --extra e2e --extra docs pytest -m pyodide -k start/choices   # one page
STUDIO_PYODIDE_PROBE=1 make test-pyodide   # also tries local_only pages and notes any that now pass
```

In CI it is its own workflow, `.github/workflows/studio-pyodide.yml`: on every push to `main`, and
on pull requests that touch the Studio, `src/indah`, the shell, the live runtime or the scripts that
build the bundle. It is not part of the fast gate or the `browser-e2e` job. If a page fails only in
Pyodide, fix the page so it stays `Session`-shaped; mark it `local_only` only with a real reason.

