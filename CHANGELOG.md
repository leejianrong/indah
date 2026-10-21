# Changelog

All notable changes to indah are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (indah is 0.x, so a minor release may change
behaviour; each such change is listed under "Changed"). The wire protocol has its own
version, `protocol_version`, and it is still **1**: every change below is additive.

Earlier releases (0.1.0 to 0.2.2) are described on the
[GitHub Releases page](https://github.com/leejianrong/indah/releases).

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

[0.3.0]: https://github.com/leejianrong/indah/releases/tag/v0.3.0
