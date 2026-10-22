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

For a whole app (not a snippet), add an `AppEntry` to the `apps` chapter.

## The playground

`/c/playground/` runs code the viewer types: `def build(): return <component>`. It **executes in
the server process**, so it is offered to loopback clients only and the page says so. Each run is
mounted under `/play/<id>/` (the last 16 are kept). A snippet that loops forever is reported after 5
seconds, but Python cannot kill a thread, so it keeps running until the server restarts.
