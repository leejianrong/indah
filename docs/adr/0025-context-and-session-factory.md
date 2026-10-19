# ADR-0025: A per-session Context for the session factory

- Status: Accepted (first slice built, IND-87; identity fields follow in the hosted epic)
- Date: 2026-10-19
- Deciders: Jian (owner)

## Context

The semula dashboard (`docs/SEMULA-REQUESTS-PLAN.md`) needs several per-session
facilities that today have nowhere to live: a push subscription that must be released
when a tab goes (E1), toasts from handlers (E5), the current route (E4), and later the
authenticated user (H1, H3). A session factory is `Callable[[], Session]`, so it cannot
see who or what it is building for, and the store's `discard` only cancelled background
tasks, with no hook for anything else to clean up.

## Decision

- A session factory may take **no arguments** (as before) or **one `Context`**. The store
  checks once, at construction, whether the factory has a required positional parameter;
  a factory with none, or only defaults, is called with no arguments, so every existing
  app is unchanged.
- `Context` carries `sid`, `conn` (a frozen `ConnectionInfo` copy of the creating
  request: lower-cased headers, cookies, client address, path), `app`, `user` (always
  `None` until identity lands), and `on_close(fn)`. Later slices add push, toast, route
  and permission methods to it.
- `Session.close()` cancels the session's tasks and runs the `ctx.on_close` callbacks,
  once, each isolated from the others' failures. The store calls it from `discard`, LRU
  eviction and idle reaping.
- The store seam is amended (ADR-0010): `get_or_create(session_id, ctx_info=None)`;
  `SessionHandle` gains `owner` (unused until identity lands).

## Alternatives considered

| Option | Why not |
|--------|---------|
| A module-level "current session" contextvar read inside the factory | Implicit and easy to misuse from a background task; an explicit parameter is testable and greppable |
| Pass the live `Request` | It is dead once its response is sent, and a session outlives many requests |
| Always require `ctx` | Breaks every existing app and notebook for no gain |

## Consequences

- Per-session cleanup becomes possible without a leak: a subscription registered with
  `ctx.on_close` is released when the session is evicted.
- `conn` can hold credentials for the session's lifetime; it must not be logged.
- ADR-0009 still holds: `ctx` belongs in the UI-building layer. Domain logic takes plain
  values.
- A custom `SessionStore` written against the old one-argument `get_or_create` must add
  the optional parameter.
