# ADR-0029: Routing and deep links

- Status: Accepted (Router, Link, `ctx.path`, history in IND-105; params, `ctx.params`, active links in IND-106)
- Date: 2026-10-20
- Deciders: Jian (owner)

## Context

The semula dashboard is mounted under `/ui` and has several screens (projects, an entries
list, one entry). Users paste links to an entry, open links in a new tab and expect Back to
work. indah had `Tabs` for sections but no URL: a reload lost the page and a link could not
be shared. ADR-0016 deferred the structural children op, so pages cannot be added at runtime.

## Decision

- **Static tree, signal path.** `Router(ctx, routes={pattern: page}, not_found=)` builds every
  page up front, like `Tabs` children, and exposes one reactive prop `active` (the index of
  the page whose pattern matches `ctx.path`, the `not_found` child, or -1). The shell renders
  only the active child. A page is a function of data (route params, IND-106), not of
  structure, so no structural op and no `protocol_version` bump. Cost: every page's effects
  exist from the start.
- **The path is session state.** `ctx.path` is a `Signal[str]` holding an *in-app path*: the
  URL path after the app's mount point (`/projects/auth` for `/ui/projects/auth`).
  `ctx.navigate(path, replace=False)` sets it and publishes a `navigate` message so the shell
  `pushState`s/`replaceState`s the address bar. `indah.routes.normalize_path` is the one
  gatekeeper: a plain `/a/b` only, no `//host`, query, fragment, backslash, whitespace or
  control character, at most 2048 characters. The path is handed back to the browser to push,
  so it must never be able to name another origin.
- **Links are real links.** `Link(ctx, label, to=)` renders `<a href>` at the real URL. A
  plain left click is intercepted: the shell `pushState`s and posts `navigate {path}` (no
  echo `navigate` message, the browser already moved). Middle-click, Ctrl/Cmd-click and "open
  in new tab" use the href like any link. `Router` listens for `popstate` and posts the new
  in-app path, so Back/Forward follow the history.
- **Params are a computed signal (IND-106).** The one `Router` per session registers its table
  with the context, and `ctx.params` is a `Computed[dict]` of the matched route's params
  (`{}` when nothing matches), so a page derives its data with an ordinary `computed` over
  `ctx.params.value.get(...)` and is recomputed only when its inputs change. A `{name:int}`
  segment is cast to `int`; a value that is not one does not match. Because every page exists
  from the start, its reactive code runs on every navigation, so it must tolerate absent
  params (`.get`). `Link(match="exact"|"prefix")` has a reactive `active` prop (the shell adds
  `class=active` and `aria-current=page`); `prefix` also lights up for pages beneath it, by whole
  segments.
- **A new tab starts where its URL says.** The shell sends `&path=` on the stream URL. On a
  fresh connect (no `Last-Event-Id`) the server sets `ctx.path` from it before building the
  `init` snapshot, so a pasted deep link or a reload opens that page even though the tab
  keeps its session id across full page loads. An automatic EventSource reconnect carries a
  `Last-Event-Id` and a path that was only right when the tab first connected, so the
  session's current page is kept.
- **Deep links need the SPA fallback.** `create_app(spa=True)` serves the shell for any
  non-`api/` GET path and gives it a relative `<base href>` (IND-86). `Router` documents the
  requirement; it is not inferred, because the tree does not exist when the routes are added.
- **The shell captures the app root once at load** (`new URL(".", document.baseURI)`), before
  any `pushState`. A page with no `<base>` (the root, or a one-segment path like `/ui/zzz`)
  would otherwise resolve `api/*` against the already-pushed deeper URL. This also fixed
  single-segment deep links, where the old `apiUrl` appended `/` to a page URL.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Build a page only when its route is visited | Needs the structural children op (ADR-0016) and a bump. Static pages are cheap for a handful of screens. |
| Hash routing (`#/projects/auth`) | Needs no server fallback, but links look wrong, cannot be mounted-path clean and cannot be read by the server on connect. |
| A global "current context" so `Router`/`Link` need no `ctx` | Hidden state; explicit `ctx` is one argument and keeps tests simple. |

## Consequences

- Hidden pages are still in the snapshot. Anything role-restricted must be left out at build
  time (H3), never merely not shown.
- Redirects, guards and lazy or nested routers are out of scope.
- A server restart loses the session, and the reconnecting tab starts from the path in its
  original stream URL, which can be one page behind. A reload fixes it.
