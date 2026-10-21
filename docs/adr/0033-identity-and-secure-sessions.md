# ADR-0033: Identity seams and secure sessions

- Status: Accepted (principal and ownership, IND-113; signed tokens, IND-114; origin guard and
  sign-out, IND-115)
- Date: 2026-10-21
- Deciders: Jian (owner)

## Context

semula hosts indah behind its own login. Until now any caller could open any session by
sending its id, an id-less request fell back to one shared `default` session, and a session
factory could not see who it was building for (`Context.user` was always `None`). The latency
probe (`docs/SEMULA-REQUESTS-PLAN.md`, "Gateway latency") shows the edge costs 100 to 200 ms per
event, so identity has to be checked in process; a per-event call to an outside service would be
paid on top of that.

## Decision

- **indah does not log anyone in.** It asks the parent app who a request is through an
  `Authenticator`: `Callable[[Request], Principal | None | Awaitable[...]]`. With
  `secure=True` and no `auth=`, the default authenticator reads Starlette's `scope["user"]`, so a
  parent app's `AuthenticationMiddleware` needs no indah-specific glue.
- `Principal` (frozen): `id` (required, owns sessions), `name`, `email`, `roles`, `workspace`,
  `claims`, `expires_at`. A principal past `expires_at` counts as nobody.
- The principal reaches the session factory as `ctx.user` (through `ConnectionInfo.user`, so the
  store seam is unchanged) and becomes the handle's `owner`.
- `create_app(secure=True)` makes identity a rule, on `/api/stream`, `/api/event`, `/api/upload`
  and `/api/file`:
  - no principal: **401**; an id-less request: **401** (nothing falls back to `default`);
  - an existing session owned by another principal: **403**, and a download of another's file is
    a **404**;
  - a refused request creates no session and never runs the factory.
- **Fail closed.** An authenticator that raises, or returns a non-`Principal`, is "nobody".
  `secure=True` with a single shared `Session` raises at `create_app`, because one state for
  every user cannot be secure.
- **Signed session tokens (IND-114).** A secure app needs `secret=` (at least 16 bytes; a list
  rotates, the first signs and any verifies). `POST api/session {resume}` authenticates the
  caller and returns `token = sid + "." + base64url(HMAC-SHA256(secret, "indah-session-v1" | sid |
  principal.id | workspace))`, with `sid` 128 random bits. A `resume` token that verifies for the
  same principal comes back unchanged, so a reload keeps its session; anything else mints a new
  one. The shell sends the token as its session id on every route, and the server verifies it
  against the *current* principal before the store is touched: forged, replayed (other
  principal), tampered and unsigned ids are all 403 and create nothing. The store is keyed by the
  `sid` part; the signature never reaches it. `InMemorySessionStore.discard_where(owner=)` drops
  a user's sessions.
- **Origin guard (IND-115).** A secure app refuses cross-origin requests (`indah.guard`): every
  state-changing request plus `api/stream` and `api/file`. `Sec-Fetch-Site: same-origin|none`
  passes; `same-site` and `cross-site` pass only when `Origin` is in `create_app(allowed_origins=)`.
  Without Fetch Metadata, an `Origin` must equal the server's own origin or be allowed; no
  `Origin` at all is a non-browser client and passes. The refusal is a 403 before anything is
  parsed or created. This is what stops a cross-site multipart upload (a "simple" request, so no
  preflight). Behind a proxy that rewrites `Host`, same-origin browsers still pass on
  `Sec-Fetch-Site`; `allowed_origins` covers a gateway on another origin.
- **Sign-out (IND-115).** `ctx.sign_out()` publishes a `signed_out` message to every session
  the user owns and discards them (`discard_where(owner=, farewell=)`); the stream ends after
  it, the shell stops reconnecting and shows "You are signed out" with its tree dropped. The
  parent app must still end its own login. A stream also ends with `signed_out` when
  `Principal.expires_at` passes, so a lapsed login does not keep an open stream alive.
- With `auth=` but not `secure=`, the principal is only attached (`ctx.user`): enforcement is
  opt-in, so notebooks and the gallery are unchanged.

## Alternatives considered

| Option | Why not |
|--------|---------|
| indah owns OIDC login (`indah[auth]`) | A second security surface and a dependency; semula's core already owns tokens, workspaces and API auth. Reversible later. |
| Read identity only from a header | Ties indah to one gateway convention; a callable covers headers, cookies and scope. |
| Bind the owner on first use only | Stops hijack of an existing session, but a client could still pick `default` or flood the store with ids. IND-114 adds a signed token for that. |

## Consequences

- A token never expires by itself: the login does (`Principal.expires_at`, checked on every
  request), and the signature only proves which principal a session id was issued to. Rotating
  the secret to nothing-in-common invalidates every session.
- `ConnectionInfo.user` and `ctx.user` carry the principal for the session's lifetime. A role
  revoked mid-session is not reflected there; authorization (a later slice) re-checks at
  dispatch.
- Wire changes are additive, so `protocol_version` stays 1: the `signed_out` server message
  (an unknown type is ignored by older shells), the `POST api/session` route, and HTTP
  statuses on existing routes.
- Amends ADR-0008 (auth stays out of core by default; core gains these seams), ADR-0010
  (`SessionHandle.owner` is now set) and ADR-0025 (`Context.user` is now populated).
