# ADR-0037: Core hardening: `Limits`, security headers, rate limit, stream cap

- Status: Accepted (IND-120; CSP is IND-121)
- Date: 2026-10-22
- Deciders: Jian (owner)

## Context

The public gallery has carried its own hardening since ADR-0024: baseline security headers and a
per-IP token bucket, both in `deploy/fly/gallery_app.py`, outside the wheel. A hosted app (semula)
needs the same, and two things were missing everywhere: nothing bounded the number of
long-lived SSE streams one address could hold (a token bucket cannot), and the bucket read
`X-Forwarded-For` unconditionally, so a client could pick its own address (ADR-0034).

## Decision

- **`indah.hardening`** holds the middleware (`SecurityHeadersMiddleware`, `RateLimitMiddleware`,
  both plain ASGI, so they do not buffer the SSE stream), the `Rate` and `Limits` dataclasses and
  a `StreamLimiter`. The gallery imports the middleware back from here.
- **`Limits` is a bundle of optional bounds, and unset means today's behaviour:**
  `rate` (suffix -> `Rate(per_second, burst)`), `max_event_bytes`, `max_upload_mb`,
  `max_streams_per_ip`, `max_sessions` and `session_idle_seconds`. `create_app(limits=Limits())`
  changes nothing; a bound applies only when set. `Limits.public()` is the gallery's setting
  (30 burst, 2 per second on `api/event`, `api/upload` and `api/stream`; 200 sessions; 30 minutes
  idle), a starting point for a public deployment.
- **Over a bound is a status, never a crash:** rate limit `429` with `Retry-After`; a stream over
  `max_streams_per_ip` `429`; an event body over `max_event_bytes` `413` (the existing cap, now
  settable here); an upload over `max_upload_mb` `413`. A refused request creates no session.
- **The client address is the socket peer**, as `ProxyHeaders` (ADR-0034) resolved it: from
  `X-Forwarded-For` only when the peer is in `trusted_proxies`. Nothing here reads
  `X-Forwarded-For` itself. A platform that sets its own trustworthy header (Fly's
  `Fly-Client-IP`) passes `client_ip=` to the middleware; the gallery does, in its deploy code,
  not in core.
- **`create_app(security_headers=True)`** adds `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin` and `X-Frame-Options: DENY` to every
  response. A mapping replaces the defaults (a value of `""` drops that header), for a host that
  embeds the app in a frame of its own origin (`SAMEORIGIN`). Off by default and in `launch()`:
  Colab shows the app in an iframe.
- Each bucket is per `(route suffix, address)`, so the gallery's three routes no longer share
  one bucket (a burst of events does not now starve the stream reconnect). Idle buckets are
  pruned so the table cannot grow without bound.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Default `Limits` that are safe for the internet | Changes every notebook and test; "unset reproduces today" keeps the upgrade free. `Limits.public()` is one call away. |
| Rate limit in the gateway only | Cloudflare and Fly are the first line (and their config is the operator's), but only the app knows its routes and SSE semantics. This is the backstop. |
| Count streams with a token bucket | A held-open stream costs nothing per second, so a bucket never trips; a connection count is the right control. |
| One shared bucket per address across routes | Cheaper but couples an event burst to a stream reconnect; per-route buckets are easier to reason about. |

## Consequences

- Behind a gateway an operator must list it in `trusted_proxies`, or every client shares the
  gateway's address (and one bucket, and one stream cap).
- The caps are per process. Several replicas multiply them; the gateway's limit is the global one.
- No wire change; `protocol_version` stays 1. Supersedes the "rate limit lives in the gallery"
  and unconditional `X-Forwarded-For` parts of ADR-0024.
