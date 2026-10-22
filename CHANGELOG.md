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
- `NavItem(ctx, label, to=, badge=, icon=, match=)`: a `Link` for a rail or sidebar with a live count badge
  that hides when it is empty or zero. A new component type (additive, `protocol_version` stays 1).
- Layout primitives: `Row(justify=)` (`start`, `center`, `end`, `between`, `around`), `Column(gap=)`,
  `Spacer` (grows to fill a row, or `size=` for a fixed gap), `Divider` (`vertical=` for a column rule)
  and `Card(variant=, padding=)` with `"outlined"` (the default and the current look), `"flat"` and
  `"tonal"`. A title on the left and actions on the right is now `Row(justify="between")`. Every new
  prop is optional and left off the wire at its default, so an app that does not use them sends and
  looks as before; `spacer` and `divider` are new component types (additive, `protocol_version` stays 1).

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
