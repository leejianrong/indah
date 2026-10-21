# ADR-0034: Trusted proxies, forwarded prefix and an audit hook

- Status: Accepted (IND-116)
- Date: 2026-10-21
- Deciders: Jian (owner)

## Context

Hosted indah sits behind a gateway (Cloudflare and Fly today, semula's gateway next). Two
things follow. The socket peer is the gateway, so the real client address, the public scheme and
any path prefix arrive in `X-Forwarded-*` headers, which any client can send. And an operator
wants a record of who did what, without that record becoming a store of what people typed.
The gallery trusted `X-Forwarded-For` unconditionally (ADR-0024); that is the thing to avoid.

## Decision

- `create_app(trusted_proxies=[...])` names the peers (IPs or CIDRs) whose forwarded headers are
  believed. **The default is none.** `*` and any `/0` network are refused at startup, because a
  wildcard makes every header believable.
- From a trusted peer, `indah.proxy.ProxyHeaders` reads:
  - `X-Forwarded-For`: the client is the rightmost hop that is not itself a trusted proxy, so
    addresses a client prepended are never believed. An unparseable hop means "do not guess": the
    peer stays.
  - `X-Forwarded-Proto` (`http`/`https` only) and `X-Forwarded-Host` (a plain host[:port]): so the
    origin guard (ADR-0033) compares the browser's `Origin` against the public origin, not the
    internal one behind TLS termination.
  - `X-Forwarded-Prefix`: kept as `ctx.conn.prefix` for apps that build absolute links. It must
    be a plain absolute path (`/a/b`); anything else (`//x`, `..`, a query, spaces) is ignored,
    never repaired. It does **not** change routing or `root_path`, so a route that happens to
    share the prefix still matches.
- Headers from any other peer are ignored. The server's scope is copied, not mutated.
- `create_app(audit=fn, audit_payloads=False)` calls `fn(AuditEvent)` after each dispatched UI
  event and each upload: `ts`, `sid` (the session id, never the signed token), `user` (principal
  id or `None`), `component`, `event` and the sorted payload **keys**. Values are included only
  with `audit_payloads=True`, and **never** from a component whose `sensitive` flag is set (a
  password `TextInput`; `SecretReveal` later). The hook may be sync or async; one that raises is
  logged and does not affect the request. Rejected events (unknown component, 401/403) are not
  audited; that is the access log's job.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Rely only on uvicorn `--proxy-headers` | It does not cover the prefix, and `launch()` and a mounted app do not all run under uvicorn's flags. Kept as the complement for access logs. |
| Honour `X-Forwarded-Prefix` as `root_path` | Starlette strips `root_path` from the routing path, so a route sharing the prefix would misroute. A separate field is safer. |
| Payload values on by default, with a redaction list | A new sensitive field would leak until someone remembered to add it; opt-in values plus a never-for-sensitive rule fail closed. |

## Consequences

- Behind a gateway an app must list the gateway's address, or it sees the gateway as every client.
  Fly's and Cloudflare's ranges are published; semula knows its own.
- The audit hook runs on the event loop: keep it quick, or hand off to a queue.
- No wire change; `protocol_version` stays 1.
- Supersedes in part ADR-0024's unconditional `X-Forwarded-For` trust, for core. The gallery's own
  rate limiter still reads `Fly-Client-IP`; it moves into core with the hardening slice (IND-120).
