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

## Amendment (2026-10-22): an `async def` factory (IND-153)

A first paint with a dash and then the number is a flicker semula hand-rolls around. The factory may
now be `async def` (a coroutine function, or an object whose `__call__` is one).

- `InMemorySessionStore.aget_or_create` is the async twin of `get_or_create`; `app.py` awaits it
  when the store has it, and a custom store without it is untouched. `get_or_create` on a store with
  an async factory raises a `RuntimeError` that names `aget_or_create`. A sync factory takes the old
  path byte for byte.
- The request waits up to `create_app(factory_timeout=1.0)`. If the factory has finished, its
  session is registered and its tree is the first snapshot, with no extra message.
- If not, a **placeholder** session is registered (`factory_placeholder()`, default a `Skeleton`),
  so the stream and `POST api/event` work at once. When the factory finishes, the real session is
  swapped into the same `SessionHandle` and a fresh `init` is published on the same hub. The shell
  already replaces its tree on a second `init`, and a `Router` is told the current path again
  (its re-init rule). Nothing new on the wire except the `skeleton` component type, so
  `protocol_version` stays 1.
- Concurrent requests for one id share one factory run, so two tabs of one sid or a stream and an
  event never build twice. Discarding the id (idle reaping, LRU eviction, `ctx.sign_out`, a closed
  tab) cancels a running factory and runs the `ctx.on_close` callbacks registered so far, and a
  factory that finishes after that is dropped.
- A factory error before the timeout propagates to the request (as a sync factory's does). After the
  placeholder is shown it is logged, sent as an `error` message and the session is discarded, so the
  next connection retries instead of showing a skeleton for ever.
- A secure app is unchanged: the owner and `ctx.user` are fixed before the factory runs, and
  the signed-token checks run before `aget_or_create`.
- The limit is per request and the factory runs on the event loop, so a factory must `await` its I/O.
  A blocking call in it stalls every tab, as it would in a handler.

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
