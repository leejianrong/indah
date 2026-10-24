# Changelog

All notable changes to indah are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (indah is 0.x, so a minor release may change
behaviour; each such change is listed under "Changed"). The wire protocol has its own
version, `protocol_version`, and it is still **1**: every change below is additive.

Earlier releases (0.1.0 to 0.2.2) are described on the
[GitHub Releases page](https://github.com/leejianrong/indah/releases).

## [Unreleased]

### Added

- Readiness and a graceful drain for rollouts (IND-201). `GET /ready` answers `200` while the process
  takes new tabs and `503` once it drains (`GET /health` stays the liveness check). On SIGTERM, under
  `launch()` or `uvicorn app:app`, the process stops taking new streams and sessions (`503` with
  `Retry-After`), sends every open stream a `reconnect` message with a spread-out delay, keeps answering
  the sessions it holds, and exits when the last stream has gone or after
  `create_app(drain_seconds=10)`. The shell moves to the next process without an error, retrying while the
  old one still refuses it. `LaunchHandle.drain()` does the same from code, `drain_on_sigterm=False` leaves
  SIGTERM alone, and `await app.state.drain.run()` is the hook for gunicorn, a parent app or anything else.
  With no stream open the drain is over at once, so a quiet process exits as quickly as before. A new
  additive message type and route (`protocol_version` stays 1); an older shell ignores `reconnect` and
  reconnects as for any dropped stream. `hosting.md` has a readiness, `preStop` and Fly `kill_signal`
  recipe. The Fly and Kubernetes settings follow their documentation and have not been run on a real
  cluster; the drain is tested with real processes and a real browser.
- A startup warning for the commonest proxy mistake: when a request carries `X-Forwarded-For`,
  `Forwarded`, `X-Forwarded-Proto`, `Fly-Client-IP` or `CF-Connecting-IP` and `trusted_proxies` is
  empty, indah logs one warning per process naming the header and the socket peer (never a value) and
  sets `app.state.proxy_warning_issued`. `create_app(warn_untrusted_forwarding=False)` silences it for
  an app with no proxy in front, and `launch()` does so in Colab and Runpod. Nothing else changes:
  addresses are still believed only from `trusted_proxies`.

- Compression for what indah serves (ADR-0042, IND-189): the page, `api/editor.js` and the files of a
  module component go out gzipped when the client sends `Accept-Encoding: gzip`, with `Vary:
  Accept-Encoding` and a separate `ETag` per form (`304` still works). The page goes from 581,178 to
  243,716 bytes and `editor.js` from 633,404 to 177,815, so a client behind a proxy that does not
  compress sends a quarter to a third as much. The event stream and JSON routes are never compressed.
  The static pieces of the page are compressed once and the CSP nonce is added around them, so a page
  load costs about 1 ms more rather than 35. `create_app(compress=False)` turns it off. No wire change
  (`protocol_version` stays 1).

### Changed


- The source distribution (sdist) no longer carries `examples/` or the gallery thumbnails: it drops from
  6.5 MB to 1.5 MB. The wheel (what `pip install` uses) is unchanged. Tests that read `examples/` are
  skipped when you run the suite from an sdist; clone the repository to run all of them.

### Added

- Optional extras (ADR-0042): `pip install "indah[plot]"` (matplotlib), `"indah[data]"` (pandas,
  numpy), `"indah[all]"` (both) and `"indah[demos]"` (the libraries the gallery demos and examples
  use). indah duck-types these libraries, so none is required and the base install is unchanged
  (four direct dependencies); an extra documents a tested version floor. A `DataFrame` or `Table`
  given something it cannot read now says to use a pandas frame (`indah[data]`), a dict or a list
  of row dicts.
- A size budget in CI (ADR-0042): `docs/size-budget.json` limits the wheel, the shell, `editor.js`,
  the direct dependencies and the base install, and the build job fails when one goes over. `make size`
  runs it locally.

- The docs have a **Playground** (`playground.md`): edit an indah app and run it in your own browser with
  Pyodide, with no install and no server (ADR-0041). Write `def build()` returning a component, the same
  contract as the Studio's local playground, so snippets move between them. Nothing loads until you press
  Run (about 9 MB compressed the first time), a run starts in about 4 seconds once cached, your code is sent
  nowhere, an endless loop is stopped after 5 seconds (and Stop works at any time), and a syntax error or
  an exception is shown under the editor as a traceback from your own lines. It starts from the Studio
  playground's examples and the quickstart. With JavaScript off the editor and the examples still read. The
  page lists what cannot work without a server. The Studio's own playground still runs only on your
  machine. Docs only: `src/indah` does not change.

- `InfoTip(text, label=)`: a small focusable info icon that shows a short note (the design's "i" beside a
  label). It opens on hover and keyboard focus, a click or tap pins it open, and Escape, blur or a press
  outside closes it; Escape closes only the note, so a modal behind it stays open. It is one tab stop, a
  real button named by `label` and described by the note (`aria-describedby`, `role="tooltip"`), the note
  stays inside the screen at 390px, and `text` may be a `Signal`, `Computed` or function. A render spec can
  name it (`{"component": "infotip", "bind": {"text": ...}}`) for a `List` item or a table cell. A new
  component type and spec component, so `protocol_version` stays 1 and nothing existing changes.

### Changed

- The docs show a live example next to each documented component: 73 `<indah-live>` embeds across the
  components, dashboard, quickstart, chatbot, custom components, design system and hosting pages. Nothing
  downloads until a reader presses **Run it**, and one example runs at a time; the 10 pages that need a
  server show their source and say why they cannot run. A new `unembedded_pages()` check (a warning in
  `tests/unit/test_docs_embeds.py`, or `scripts/export_studio_pages.py --unembedded`) names any runnable
  Studio page with a docs target that no docs page embeds. No library change.

- Hosting guide: what Fly sends to an app (measured, IND-170) and the `trusted_proxies` value that
  works there (the private range plus the app's own public IPs; the private range alone resolves every
  visitor to the app's address), and what sticky sessions need (IND-171: a stray event to the wrong
  process builds a new session and is silently lost; indah finds a session by `sid`, not a cookie or
  header, so gateway cookie affinity has nothing to key on). Docs only.

### Fixed

- Docs: the summary line of a live example now shows `code` spans as code instead of with literal
  backticks (the page's source and the rest of the summary stay escaped).

## [0.7.0] - 2026-10-24

More building blocks, and the start of live docs. This release adds the last of the dashboard pieces as
built-ins (`CommandPalette`, `Marked`, `BarStrip`, `Steps`), and the machinery that lets the docs site run
Studio pages in the reader's browser with Pyodide. Everything is new API: nothing existing changes, and
`protocol_version` is still 1.

### Added

- The docs can run Studio pages in the reader's browser (ADR-0041): `<indah-live page="...">` shows a page's
  source and a **Run it** button that starts a Pyodide worker running the real indah `Session`, with no
  server. Nothing loads until the button is pressed. Built by `make docs`; see `docs/STUDIO.md`. No change
  to the library.
- `BarStrip(series, height=, tones=, names=, labels=, max=, label=)`: a small activity strip with one
  bar per interval (calls per minute, hits and misses stacked), for a dashboard header rather than a
  chart. `series` is a list, `Signal`, `Computed` or function; a bar is a number or a tuple of segment
  values. It updates in place (the bars are not remounted) and takes its tones from the theme. A tooltip
  names each bar and its segments ("12:03: 4 (hit 3, miss 1)"), the strip is one tab stop whose arrow keys,
  Home and End read each bar, and a live region says the same, so colour is not the only cue. It
  respects reduced motion and works under `csp="strict"`. A new component type (`barstrip`), so
  `protocol_version` stays 1 and nothing existing changes.
- `Steps(items, orientation=, size=)` and `steps_items(items)`: a timeline of steps (a pipeline, a checklist, the
  tiers a request went through), vertical or horizontal. A step is `done`, `current`, `skipped`, `off` or
  `pending`, each with its own drawing (a check, a ring with a dot, a barred ring, a dashed ring, an empty
  ring) as well as its theme colour, a skipped label is struck through, and a screen reader hears "step 2 of 5,
  done" with the step's `detail`. The current step is `aria-current="step"`. Display only, so not a tab stop.
  `size="compact"` is one tight line with the detail as hover text. `items` may be a `Signal`, `Computed` or
  function and updates in place. A render spec may name it, `{"component": "steps", "bind": {"items": "tiers"}}`,
  so a `List` item or a table cell (a `Stream`-fed table too) can draw it from a `steps_items` field; there it is
  compact and horizontal unless `orientation` or `size` are bound too (ADR-0016 amendment). A new component type
  and a new spec component (additive, `protocol_version` stays 1); nothing existing changes.
- `Marked(text, marks)` and `marked_runs(text, marks)`: text with shaded spans, for the part of a request
  that was ignored when matching or the words a check flagged. A mark is `(start, end, tone)` or
  `(start, end, tone, label)`; offsets are Unicode code points, a range is clamped, an empty one dropped,
  and an overlap is cut to begin where the earlier mark ends, so the same input always draws the same
  runs. The tones are the theme's (`ok`, `warn`, `err`, `info`, `neutral`), each with its own underline as
  well as its colour, and the label is hover text. The spans are real elements that add no characters, so
  copying gives back the plain text. A render spec may now name a built-in leaf component,
  `{"component": "marked", "bind": {"runs": "runs"}}`, so a `List` item or a table cell can show it from a
  `marked_runs` field (ADR-0016 amendment). A new component type and an optional spec field (additive,
  `protocol_version` stays 1); nothing existing changes.
- `CommandPalette(commands, shortcut="mod+k")` and `Command(label, on_run | to=, group=, shortcut=, keywords=,
  confirm=, key=)`: the dashboard driven like a terminal. Ctrl or Cmd+K opens a dialog; type to filter, arrows
  move, Enter runs, Escape closes and gives focus back. A command runs a function (sync or `async`) or jumps
  to an in-app page (`to=`, with `CommandPalette(..., ctx=ctx)`), and may ask to `confirm`. The filter runs in
  the browser in a fixed order: label prefix, then a word prefix, a substring, a subsequence (`gl` finds
  "Go to log"), then keywords and group, ties in the order given. `commands` may be a `Signal`, `Computed`
  or function, so a page adds its own commands while it shows. It follows the key-routing rule of ADR-0030:
  never opens over another dialog, ignores a bare key typed in a field, and the shortcut is listed in the `?`
  help. To omit a command for someone who may not use it, build the list with `ctx.only` and wrap the handler
  in `guard`. A new component type (`commandpalette`, event `run`), so `protocol_version` stays 1 and nothing
  existing changes.

### Known limitations

- `trusted_proxies` has still not been checked against the real Cloudflare and Fly path (IND-170), and
  sticky sessions are unverified (IND-171).
- `Marked` does not draw inside a `Diff` pane (the `Diff` draws its own changes); show it beside one.
- A `Menu` and a module component cannot sit in a table cell: a cell spec is display only.
- The live docs examples load Pyodide on demand (about 9 MB compressed) and have been tried in Chromium
  only, with a self-hosted runtime; the jsDelivr path, Safari, Firefox and phones are not yet checked.

## [0.6.0] - 2026-10-23

Tables, text and small controls. This release makes plain `Text` look like normal body text, adds
rich table cells and keyboard navigation, an async session factory with a `Skeleton`, a `Menu`, an
empty state, a copyable code block, toast actions, `ctx.every` and `ctx.spawn`, and a title and
favicon the server can change. **Read "Upgrading" first: plain `Text` now looks smaller in every app.**
`protocol_version` is still 1; every wire change is additive.

### Added

- `Menu(trigger, items)` and `MenuItem(label, on_click, danger=, shortcut=, confirm=, disabled=, key=)`: a menu
  button that follows the ARIA menu pattern. It opens on click, Enter, Space or the arrow keys; Up and Down
  move and wrap, Home and End jump, a letter jumps to the next item that starts with it, Escape closes and
  returns focus to the trigger, and Tab closes and moves on (no keyboard trap). `confirm=` asks first like
  `Button`, `danger` uses the theme's error tone, a `disabled` item is shown but cannot be chosen, and
  `shortcut=` is display text only. `items` may be a `Signal`, `Computed` or function, so the menu follows
  the data; a click is matched to the current items by id, so a stale one does nothing. To omit an item for
  someone who may not use it, build the list with `ctx.only` and wrap the handler in `guard`. A new component
  type (`menu`, event `select`), so `protocol_version` stays 1 and nothing existing changes.
- In an `AppShell` on a narrow screen, a button that only opens something (it has `aria-haspopup`, like a
  `Menu` trigger) no longer closes the drawer; choosing a link or an ordinary button still does.

- `ctx.title` and `ctx.favicon`: set the tab's title and icon from the server, with no reload, for an
  attention cue like "(2) semula" with a red dot. Icons are registered with
  `create_app(favicons={name: path-or-bytes})` (PNG, SVG, ICO, JPEG or WebP, up to 64 KB, at most 16) and
  served by the app (`GET api/brand/favicon/<name>`), so they work under `csp="strict"`. `None` puts the
  app's own back. A change reaches that session only; a reload or a reconnect keeps it, and a new session
  starts with the defaults. A new `chrome` message and an optional `chrome` key on `init` (additive,
  `protocol_version` stays 1); apps that do not use them are unchanged.
- `Empty(title, body, action=, children=)` and `Code(text, language=, copy=True)`. `Empty` is a centred
  empty state (the one command that fills a log, with a button); `Code` is a read-only monospace block
  that keeps newlines and indentation, with a Copy button that puts the plain text on the clipboard and
  shows a "Copied" toast in that tab (no server round trip). Where the browser blocks the clipboard the
  text is selected and the toast asks for Ctrl+C. Both are new component types (additive,
  `protocol_version` stays 1) and nothing existing changes.
- Table keyboard navigation: `Table(on_open=fn)` (or `keyboard=True`) makes a rich or remote table one
  tab stop (`role=grid`) that `j`/`k` and the arrows, `Home`/`End`, `PageUp`/`PageDown`, Space (ticks a
  `checked=` row) and Enter drive; Enter calls `fn(key)` (sync or `async`), or selects like a click
  when there is no `on_open`. The active row is held by key, so streamed rows, sorting and `follow=` do
  not move it, it scrolls into view under the sticky header (also in a 20,000-row `virtual` table), and
  an arrow past the end of a paged or remote table turns the page. A focused table takes its keys first
  and `Shortcuts` yields; modifier combos and typing in an input are never the table's; Tab and Escape
  leave. Off by default, so no existing table changes. New optional props `keyboard` and `openable`
  and an `open` event (additive, `protocol_version` stays 1). The key-routing rule is in ADR-0030.
- Async session factory (IND-153, ADR-0025 amendment): `session_factory` may be `async def`. It is awaited
  for up to `create_app(factory_timeout=1.0)` seconds, so its data is in the first snapshot (no dash,
  then the number). A slower factory lets the tab start on `factory_placeholder()` (a `Skeleton` by
  default) and the real page replaces it on the same stream when the factory finishes; a factory that
  raises shows the error and the next connection retries, and closing the tab cancels it. Sync factories are
  unchanged. A custom `SessionStore` may add `aget_or_create`; one without it is untouched.
- `Skeleton(lines=3, height=)`: grey placeholder bars that pulse (not for a viewer who prefers reduced
  motion). A new component type (additive; a second `init` mid-stream is documented in
  `docs/protocol.md`, `protocol_version` stays 1).


- `ctx.toast(message, action=("Undo", fn), ttl=)`: a toast with a button. Clicking it runs `fn` once
  (a plain function or `async def`, checked by `guard()` at the click) and dismisses the toast. It goes to
  this tab only; a second click or a stale toast does nothing. The pending handlers are held per session
  and bounded. The toast message gains an optional `action` and the click posts the reserved target
  `__toast__` (additive, `protocol_version` stays 1; a toast without `action` is unchanged).

- `ctx.every(seconds, fn, immediately=False)` and `ctx.spawn(coro)`: background work for the life of a
  session. `every` calls a plain or `async` function on a timer; both are cancelled when the session
  ends (discard, eviction, idle reaping), and an exception is logged once and does not stop the loop.
  It replaces a hand-rolled task cancelled from `on_close`. No wire change.
- Rich table cells and truncation (IND-148): `Col(kind="cell", render=<spec>, sort_key=)` draws a
  composite cell (a meter, a two-line caller, a tier rail) from the row's fields, using the same spec
  vocabulary and tag allowlist as a `List` item; it is display only. The spec travels once in the
  column, so a `Stream`-fed table sends nothing extra per row. A cell column sorts and is searched by
  `sort_key`. `Col(truncate=True, max_width=)` clips a long text value with an ellipsis and a tooltip,
  and `wrap=True` wraps it (refused with `virtual=True`). All optional and off by default, so a table
  that does not use them is unchanged, and virtual scroll is as fast as before (additive,
  `protocol_version` stays 1).

### Changed

- **Plain `Text` is now body text** (ADR-0040, IND-166). It was a 1.4rem semi-bold readout, so every
  label and status line looked like a title. The default is now 0.95rem regular text with line breaks
  kept. `Text(source, variant=)` picks a role: `body` (default), `title`, `label`, `caption`, `mono`
  and `readout`, the old large look. `size="body"` and `size="readout"` from 0.4.0 still work. A text
  that is `markdown=True` is unchanged and takes no `variant`. The wire format only gains an optional
  `variant` prop (absent means body), so `protocol_version` stays 1.

### Upgrading

- **Plain `Text` looks smaller.** If a `Text` shows a number or a figure (a counter, a metric, a KPI),
  add `variant="readout"` to get the old look back. Search your code for `Text(` whose source is a
  count or a short value. A `Text` used as a heading can use `variant="title"`.

### Known limitations

- `trusted_proxies` has still not been checked against the real Cloudflare and Fly path (IND-170), and
  sticky sessions are unverified (IND-171).
- A `Menu` and a module component cannot sit in a table cell: a cell spec is display only.
- `factory_timeout` and `factory_placeholder` apply to the built-in session store, not to a `store=` you
  pass.

## [0.5.0] - 2026-10-22

The building blocks of an app screen. This release adds a frame (`AppShell`), the controls and layout
pieces a dashboard header needs, and a way to ship your own element: a module component that the
shell loads as a web component (ADR-0039). Everything is new API; no existing app looks or behaves
differently, and `protocol_version` is still 1.

### Added

- Module components (ADR-0039): `register_component(type, module=, events=, two_way=, fallback=)` ships an
  ES module (a file or bytes, read once; never a URL; up to 1 MB) whose default export is an `HTMLElement`.
  The shell loads it from the app itself (`GET api/components/<type>.js`, content-hashed and cached for good),
  defines it as `indah-x-<type>`, sets the props as properties, forwards the declared CustomEvents to
  `custom(..., on_<event>=handler)` and writes a two-way prop from `detail.value`. A module that fails
  shows its `fallback` text and the page keeps working. It works under `csp="strict"`, `secure=True`,
  `guard()` and the audit hook. A new reserved prop and route, so `protocol_version` stays 1; spec
  components and every default are unchanged.
- Reactive options: `Select`, `Radio`, `MultiSelect`, `Chips` and `Segmented` take `options=` as a
  list, or a `Signal`, `Computed` or callable returning one, and follow it with no reload (a project
  created after the page loads appears in the switcher). A selection whose value is still offered is kept;
  a multi-value control (`MultiSelect`, `Chips(multi=True)`) drops values that are no longer offered, and a
  single-value control leaves its signal alone. A list works exactly as before and stays static on the wire;
  a live source sends `options` as a patch (additive, `protocol_version` stays 1).
- `AppShell(rail=, main=, top=, rail_width=)`: the frame of an app, with a rail that stays put while
  main scrolls, an optional top bar, main keeping `create_app(max_width=)`, and on a narrow screen a
  drawer behind a menu button (Escape, the backdrop or choosing a link closes it). It works inside a
  `Router` page and with `spa=True`. A new component type with optional props, so `protocol_version`
  stays 1 and no existing app changes (ADR-0014 amendment).
- `Chips(value, options=, multi=)` and `Segmented(value, options=, tones=)`: filter chips and a segmented
  control, two-way bound to a signal (a `Signal[str]`, or a `Signal[list]` for `multi=True`). An option may
  be `"a"`, `(value, label)` or `{value, label, count, tone}`; a count shows beside the label and a tone
  (`ok`, `warn`, `err`, `info`) tints it. A single choice is a radio group (arrow keys move and select, with a
  roving tab stop); multi chips are toggle buttons. New component types, nothing existing changes
  (additive, `protocol_version` stays 1).
- `create_app(logo=(light, dark))`: a mark per colour scheme, chosen by indah's own light/dark toggle, so a
  dark mark no longer vanishes on the dark page. A single `logo=` is unchanged (`protocol_version` stays 1).
- `NavItem(ctx, label, to=, badge=, icon=, match=)`: a `Link` for a rail or sidebar with a live count badge
  that hides when it is empty or zero. A new component type (additive, `protocol_version` stays 1).
- Layout primitives: `Row(justify=)` (`start`, `center`, `end`, `between`, `around`), `Column(gap=)`,
  `Spacer` (grows to fill a row, or `size=` for a fixed gap), `Divider` (`vertical=` for a column rule)
  and `Card(variant=, padding=)` with `"outlined"` (the default and the current look), `"flat"` and
  `"tonal"`. A title on the left and actions on the right is now `Row(justify="between")`. Every new
  prop is optional and left off the wire at its default, so an app that does not use them sends and
  looks as before; `spacer` and `divider` are new component types (additive, `protocol_version` stays 1).

### Known limitations

- `trusted_proxies` has still not been checked against the real Cloudflare and Fly path (IND-170), and
  sticky sessions are unverified (IND-171).
- A module component cannot yet sit inside a `List` row or a table cell; that needs the table cell
  spec (IND-148). A module is code that runs in the page with the app's privileges, so register only
  files you wrote or vendored, and never one a user supplies (see ADR-0039).
- A logo pair (`logo=(light, dark)`) takes two images; an SVG that uses `currentColor` does not follow
  the page colour because the logo is shown in an `<img>`.

## [0.4.0] - 2026-10-22

Hosted use. This release adds what an app needs to run for real users behind a login: identity,
signed per-user sessions, roles, one-time secrets, rate limits and a strict Content-Security-Policy,
plus a code editor and a round of small requests from the first dashboard built on indah. Nothing
is on by default: an app that worked on 0.3.0 behaves as before, with two small exceptions listed
under "Upgrading". Start with the new guide, "Host an app for real users", on the docs site.

### Added

**Identity and sessions** (ADR-0033, ADR-0034)

- `Principal` and an `Authenticator` (`create_app(auth=)`): a function from the request to who
  the caller is. `ctx.user` carries it into the session factory, and each session is owned by it.
  With `secure=True` and no `auth=`, Starlette's `scope["user"]` is used.
- `create_app(secure=True)` makes identity a rule on every route that reaches a session: no
  principal is `401`, no session id is `401`, another person's session is `403` (their file
  download `404`), and a refused request creates no session. It needs a per-viewer
  `session_factory` and a `secret` (16 bytes or more; a list rotates).
- Signed session tokens: the shell trades its login for `<sid>.<signature>` with
  `POST api/session`, and a reload keeps its session. The signature covers the principal and the
  workspace, so ids cannot be chosen, replayed or moved.
- An origin guard on a secure app (`allowed_origins=`), so a cross-site form or multipart POST
  is refused before it is parsed. `ctx.sign_out()` ends every tab of a user and shows a
  signed-out page; an open stream also ends when `Principal.expires_at` passes.
- `trusted_proxies=`: `X-Forwarded-For`, `-Proto`, `-Host` and `-Prefix` are believed only from
  the proxies you list (default none; `*` is refused). `ctx.conn.prefix` holds the forwarded
  prefix.
- `audit=` and `audit_payloads=`: a hook called after each UI event and upload with who, which
  component, which event and the payload keys. Values are included only on request, and never
  from a sensitive component.

**Authorization and secrets** (ADR-0035, ADR-0036)

- `Policy` (roles to permissions, with `*` and `prefix:*`), `ctx.can`, `ctx.require`, `ctx.only`
  and `guard(perm)(handler)`. Restricted components are omitted when the tree is built for the
  principal, because hidden components are still in the page. `guard` checks again when the
  event arrives, against the person making that request, so a role revoked mid-session fails the
  next action (`403`, a "not allowed" toast, not audited). `ctx.workspace` exposes the workspace
  a session is bound to.
- `SecretReveal`: shows a new API token once, with Copy and "I have saved it". The value is an
  *ephemeral prop*: sent to the open tab only, never put in the `init` snapshot or the replay
  history, and cleared on dismiss, on a fresh `init` and when the session closes. It is marked
  sensitive for the audit hook. `Component.ephemeral`, `Component.forget()` and
  `Hub.publish(record=False)` are the mechanism.

**Hardening** (ADR-0037, ADR-0038)

- `indah.hardening`: `Limits` (every bound optional; unset means as before), `Rate`,
  `Limits.public()`, and the rate-limit and security-header middleware that used to live in the
  public gallery's deploy code. `create_app(limits=, security_headers=)` adds a per-address,
  per-route token bucket (`429` with `Retry-After`), a cap on open streams per address (`429`),
  event and upload body caps (`413`), session count and idle bounds, and the headers
  `X-Content-Type-Options`, `Referrer-Policy` and `X-Frame-Options`.
- `create_app(csp="strict")`: a Content-Security-Policy with a fresh nonce on the shell's inline
  tags, no inline script or `eval`, same-origin connections only, and a violation report
  collector (`POST api/csp-report`, `app.state.csp_violations`). `csp_media_hosts=` lists extra
  image and audio hosts; a `Map` registers its tile host. Off by default and in `launch()`. The
  whole browser test suite now runs under it and fails on any violation.

**The Studio** (`make demo`)

- `make demo` is now the **indah Studio**: one app with a chapter per area (start, layout, overlays,
  routing, data, live, media, extend, hosting), 53 feature pages that each show a live demo, its
  source and its docs links, 9 full example apps (live log, pending queue, 20,000-row table, routed
  dashboard, editor, hosted roles and tokens, component showcase, themed app, params and deep
  links), and a playground that runs a few lines of indah you type. The per-feature `make demo-*`
  targets and the review server are gone; the full apps are still files in `examples/`.
- A test fails when a public name in `indah.__all__` has no Studio page, and the browser suite opens
  every page (under `csp="strict"`) and fails on console errors, failed requests and CSP violations.
  See `docs/STUDIO.md` to add a page.

**Editor and recipes**

- `CodeEditor`: a JSON, YAML and plain-text editor (CodeMirror 6) with highlighting,
  auto-indent, auto-closing brackets and quotes, bracket matching, folding, search, line
  numbers, JSON lint with the error position, a read-only mode, a Format button that keeps key
  order, a Ctrl/Cmd-S save hook and `{{placeholder}}` highlighting. It loads lazily from
  `GET /api/editor.js` the first time one renders (about 180 KB compressed, only for apps that
  use it), follows the app theme, and falls back to a text area if it cannot load. ADR-0032.
- `examples/oidc_login.py`: a recipe for OpenID Connect login in the parent app with authlib
  (PKCE, state, nonce, full ID-token verification), handing a `Principal` to indah. It fails
  closed on any token that does not verify and is tested against an in-process provider. indah
  itself has no authlib dependency, and there is no `indah[auth]`.
- `make demo-hosted` now shows three roles (viewer, editor, admin), an admin-only API-token
  screen (create with reveal-once, list, revoke with a confirm) and every hardening switch on.

**Small requests from the first dashboard** (ADR-0031 amendment)

- `py.typed`: the package ships type information.
- `create_app(title_suffix=)` sets the page title's suffix (`""` gives the exact title) and
  `create_app(max_width=)` sets the page frame's widest size (`"none"` fills the window).
- `Theme(extra_light=, extra_dark=)`: an app's own `x-<name>` tokens, emitted as `--x-<name>`.
- `Col(time_format="clock" | "datetime")`: absolute times in a table's time column.
- Docs: a synchronous handler runs on the event loop (use `async def` for long work). The wire
  protocol is published in full on the docs site, with a test that keeps the two copies equal.
- `scripts/latency_probe.py` times an event round trip against a deployed app. On the public
  gallery from Singapore, indah adds a few milliseconds, a hop to Fly about 16 ms, and the
  Cloudflare path 100 to 200 ms per interaction, which is why checks run in the process rather
  than calling an outside service per event.

### Changed

- A link in `Text(markdown=True)` that points within the site (`/path`, `#anchor`, `./x`, `../x`)
  now opens in the same tab; links to other sites (`http(s)`, `mailto`) still open in a new tab.
- `POST /api/event` requires `Content-Type: application/json` (`415` otherwise, before the body
  is read), so a cross-site "simple" request cannot reach the handler.
- An event with no session id is `400`, unless the app is one explicit shared `Session`
  (`create_app(session=)`). Nothing falls back to a shared `default` session any more.
- The public gallery no longer trusts a client-supplied `X-Forwarded-For` for rate limiting; it
  uses Fly's `Fly-Client-IP`, else the socket peer. Its three routes now have a bucket each
  rather than sharing one. In core, the client address is the socket peer, or the forwarded
  address from a trusted proxy.
- `authlib`, `itsdangerous` and `cryptography` joined the `dev` extra for the recipe's test.
  They are not dependencies of indah.

### Fixed

- `MultiSelect` is now a list of checkboxes (a labelled group, operable with the keyboard)
  instead of a native `<select multiple>`. The wire format and events are unchanged, so
  `protocol_version` stays 1.
- `Text(size="body")`: plain `Text` is a large readout by design, which made status lines and
  notes look like headings. `size="body"` renders normal body text with newlines kept; the
  default is unchanged. It is an additive optional prop (`protocol_version` stays 1). Plain text
  still shows backticks literally: use `markdown=True` for markup.
- `UploadedFile.text()` takes `errors=` (`"strict"` by default, as before), so a file that is not
  clean UTF-8 can be read with `"replace"` or `"ignore"` instead of raising.
- The "only one Router per session" error now explains the limit and what to do instead.
- A custom component's nested `on` now round-trips. `register_component` built its event map from
  the top-level spec only, so an `input` inside a `children` tree changed nothing on the server.
- A render spec takes `"literal"` for fixed text, so a `List` row button reads `"Remove"` without a
  `"Remove"` field on every item (`text` still names a prop or item field). The spec field is
  additive and `protocol_version` stays 1.
- `Row(align=...)` is honoured for buttons and badges: with any `align` other than the default
  `"stretch"` they size to their content instead of growing to share the row (a Badge beside two
  Buttons no longer stretches). The default row is unchanged.
- `Theme(radius=)` now reaches buttons and badges, which were always pill-shaped. They use a new
  `--radius-control` token that defaults to `--radius-pill`, so apps without a theme look as before.

### Known limitations

- A session can have only one `Router`, because the address bar is one path per tab. A second
  one raises an error that says so and what to use instead (`Tabs`, or a `Signal`); a Router
  cannot be demonstrated inside a page of another routed app. Nested routers are not planned.
- Sessions are in memory. With more than one process, use sticky sessions at the gateway. There
  is no external session store.
- `trusted_proxies` is tested with simulated headers; it has not yet been checked against the
  real Cloudflare and Fly path.
- A role revoked mid-session stops actions at once, but components already sent stay on screen
  until the session is rebuilt; a role added shows its components after a rebuild.
- A `Map` with a custom tile host built after the first page load is allowed under a strict CSP
  from the next load. Declare it with `csp_media_hosts=` to avoid that.
- Limits are per process; several replicas multiply them.

### Upgrading from 0.3.x

No code changes are needed unless your code or a script posts events by hand:

1. `POST /api/event` must send `Content-Type: application/json`. Anything else is now `415`.
2. A `POST /api/event` with no `sid` is now `400` for an app built with `session_factory=` (the
   shell always sends one). An app built with `session=` still accepts it. Tests that post
   events directly should pass a `sid`, and open the stream with the same `?sid=`.
3. If you copied the gallery's rate-limit or security-header middleware, import
   `RateLimitMiddleware` and `SecurityHeadersMiddleware` from `indah.hardening` instead.

Two things look different without any code change: `MultiSelect` is now a list of checkboxes
(same value, same events), and an app that sets `Theme(radius=)` now gets that radius on its
buttons and badges too (they were always pill-shaped). Neither changes the wire protocol.

To host an app for real users, follow "Host an app for real users" on the docs site. The new
options (`auth`, `secure`, `limits`, `security_headers`, `csp`, `trusted_proxies`, `audit`, `policy`)
are all off or unset by default.

## [0.3.0] - 2026-10-21

Dashboard support. This release adds what an app needs when indah lives inside a larger
service: live push to every tab, big tables, overlays, routing, editors and a documented
design system. Start with the new guide, "Build a dashboard", on the docs site.

### Added

- **Mounting.** The shell works under any mount prefix (a relative `<base href>`), and
  `create_app(spa=True)` serves the shell for deep links such as `/ui/projects/auth`.
- **`Context`.** A session factory may take a `Context`: `ctx.toast`, `ctx.path`,
  `ctx.params`, `ctx.navigate`, `ctx.latest`, `ctx.tail` and `ctx.on_close`.
- **Live push.** `Topic` (app-level channel), `Stream` (append-only, bounded list, sent as
  small `append` patches with a `trim`), and the 100 ms append coalescer.
- **Theming.** `Theme(light=, dark=, radius=, font=)`, a custom `logo=`, and
  `create_app(density="comfortable" | "compact")`. New tokens `on-primary-container` and
  `on-secondary-container`.
- **Design system.** A published "Design system" page and ADR-0031 record the token
  contract; a unit test keeps the shell, `Theme` and the page in step.
- **Table v2.** Keyed rows, typed columns (`Col`: text, mono, badge, time, number), a sticky
  header, `Stream` rows, client-side search, column toggle and follow-tail, row actions
  (`RowAction`), multi-select (`checked=`), `density=`, a remote mode (`remote=` with a
  `TableQuery` loader, `reload_on=`, `query=`) and virtual scroll (`virtual=`), tested with
  20,000 rows. On a remote table, "N of M selected" and **Select all M** gather every
  matching row (up to 10,000).
- **Overlays and feedback.** `Modal`, `Drawer`, `Button(confirm=)`, toasts, `Badge`,
  `Switch`, a `tooltip=` prop on every component, and `Shortcuts` with a `?` help overlay.
- **Inputs.** `TextArea`, with the same typing-safe behaviour as the other inputs.
- **Panes and routing.** `SplitPane`, `MasterDetail`, `Router`, `Link` (with active state),
  route params as signals, and `not_found`.
- **Viewers.** `JsonTree` (search, collapse, copy path) and a server-side `Diff` (split or
  unified, with word-level highlights).
- **Editable lists.** `List(key=, on_item=)`: keyed rows, row events carrying the row key,
  and in-row inputs that keep focus and text while updates arrive.
- **Demos.** `make demo-review` serves every semula demo behind one index page; the single
  demos are `make demo-semula`, `demo-pending`, `demo-entries`, `demo-routes` and
  `demo-editor`.

### Changed

- `POST /api/event` bodies are capped (`create_app(max_event_bytes=)`, default 1 MiB); a
  larger one is rejected with `413`. A text area holding a very large document may need a
  higher cap.
- A rich `Table` now draws row separators only (no vertical cell lines), and its sticky
  header is opaque with a drawn bottom edge. Search boxes are rounded like other inputs.
- The tonal button and the info badge take their text colour from the new `on-*-container`
  roles, so it shifts slightly.
- The default Bunga logo no longer follows an app theme's `primary`; it keeps its brand
  colours. Use `logo=` for your own mark.
- Tooltips open at the pointer (on keyboard focus: under the control), flip above near the
  bottom edge and stay inside the window.

### Fixed

- After a server restart, an open tab is sent a fresh `init` instead of staying on a stale
  tree, and it reopens on the page it is on now rather than the one it started on.
- `LaunchHandle.stop()` now ends the server even while a browser tab holds an SSE stream
  open.

### Known limitations

- Every `Router` page runs its reactive code even when it is not showing, with empty
  params. Read params with `ctx.params.value.get(...)`, never `[...]`. Do not put
  role-restricted content in a page: hidden pages are in the snapshot.
- `Table(follow=True)` is not available with `remote=` and raises `ValueError`.
- A keyed `List` takes a signal or a callable, not a `Stream`.
- `Modal` has no position option, and `Button` has no disabled state.
- indah keeps sessions in memory and does not authenticate users. Authentication,
  authorization and rate limiting belong in the app that mounts it.

### Upgrading from 0.2.x

No code changes are required for an app that worked on 0.2.2. Check three things:

1. If you POST very large values (for example a big `TextArea`), raise
   `max_event_bytes`.
2. If you override colours with CSS of your own, check the tonal button and the info badge.
3. If you use `Theme`, you may now set `on-primary-container` and `on-secondary-container`;
   set them whenever you override the matching `*-container` role.

[0.4.0]: https://github.com/leejianrong/indah/releases/tag/v0.4.0
[0.3.0]: https://github.com/leejianrong/indah/releases/tag/v0.3.0
