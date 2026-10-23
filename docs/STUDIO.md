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
