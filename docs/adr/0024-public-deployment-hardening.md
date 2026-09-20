# ADR-0024: Public-deployment hardening for the Fly demo gallery

- Status: Accepted
- Date: 2026-09-20
- Deciders: Jian (owner)

## Context

The Fly demo gallery (`indah-demos.fly.dev`, ADR-0023) is public, unauthenticated, and
runs on a single machine. A capability review (`docs/DEMOS-DOCS-ROUND2.md` §D) named
five concrete risks: resource exhaustion (long-lived SSE streams + unbounded per-session
state), upload abuse (unbounded-size, arbitrary-file ingress), outbound egress abuse (a
future live-OSM demo making arbitrary third-party calls), cost/bandwidth from an
uncontrolled scale-out, and reputational risk from LLM output served off our domain.

This ADR records the layered defense and what's implemented now versus deferred.

## Decision

**Layers, outside in:** `client -> Cloudflare (documented, not yet wired) -> Fly Anycast
+ fly-proxy (TLS, routing, LB) -> the Starlette gallery app (path routing, security
headers, per-IP rate limiting) -> InMemorySessionStore (per-session isolation, TTL/LRU
eviction) -> each demo`.

**No nginx/Traefik in production.** Fly Machines already sit behind `fly-proxy`
(Anycast, TLS termination, routing, load balancing, health checks), and the Starlette
gallery app (`deploy/fly/gallery_app.py`) is itself the path router (`Mount` per demo).
Adding nginx or Traefik in front would duplicate `fly-proxy` for no benefit. Traefik
stays local-dev-only (`make demo-traefik`), unrelated to this production path.

**Rate limiting lives in two places on purpose.** Cloudflare (once wired) blocks abuse
at the edge, before it reaches the box - cheapest, but it doesn't understand indah's
SSE/session semantics. Per-IP, per-endpoint limits on the expensive routes
(`/api/event`, `/api/upload`, `/api/stream`) have to be app-level.

**Session TTL/eviction is `InMemorySessionStore`'s concern, not a new seam.**
`InMemorySessionStore` (ADR-0010) was an unbounded `dict` with no eviction - a cheap way
to OOM one machine from many abandoned tabs, and worse, an evicted session's background
loop (chatbot generation, a diffusion/training loop) had no way to be cancelled, so
dropping the dict entry alone would not have stopped it from running. Fixed by adding an
optional idle-timeout reaper and an LRU cap to the store itself (both default to
unbounded - no behavior change for notebook/test use, where nothing should evict), plus
a `Session.cancel_tasks()` the store calls on eviction. The public Fly gallery turns
these limits on (`deploy/fly/gallery_app.py`); nothing else does.

## What's implemented (this slice, two PRs)

- `fly.toml` per-machine connection concurrency limit (`[http_service.concurrency]`).
  `deploy_fly.sh` already deploys with `--ha=false`, so Fly does not provision a second
  machine under load - the concurrency limit bounds simultaneous SSE connections on the
  one machine instead of letting it OOM.
- The image-classifier demo's upload path: a lower size cap (4 MB, down from the
  framework's 25 MB default) and a server-side content-type allowlist (images only).
- Baseline security response headers (`X-Content-Type-Options`, `Referrer-Policy`,
  `X-Frame-Options`) on the gallery app.
- App-level per-IP rate limiting (token bucket) on `/api/event`, `/api/upload`, and
  `/api/stream`, reading `Fly-Client-IP` (falling back to `X-Forwarded-For`, then the
  socket peer).
- `InMemorySessionStore` gains optional `idle_timeout_seconds` (TTL reaper) and
  `max_sessions` (LRU cap); the Fly gallery sets both, everything else leaves them
  unbounded. Eviction cancels the session's background tasks.

## Deferred (named explicitly, not forgotten)

- **Wiring Cloudflare itself.** It needs a domain the owner controls in Cloudflare's
  DNS - `indah-demos.fly.dev` is a Fly-owned subdomain, not ours to delegate. Documented
  as a manual owner step in `deploy/fly/README.md` for when a domain exists.
- **Origin-IP hiding.** Even with Cloudflare proxying a future custom domain, Fly's
  machine still has a directly reachable public IP. Real hiding needs a Cloudflare
  Tunnel (`cloudflared`) or an app-level check that requests carry a shared Cloudflare
  secret header / originate from Cloudflare's published IP ranges. Not built.
- **Bounding async-loop iteration count / wall-clock time** (the chatbot generation loop,
  the diffusion/training-dashboard loops). TTL/LRU eviction plus task cancellation stops
  an *abandoned* session's loop; it does not cap how long a *live* one may run. Left for
  a later slice, likely alongside R2-9's diffusion transport-control work since that PR
  already reshapes the loop.
- **Egress curation for a real OSM-backed map poster** (R2-8/A8). This ADR only keeps
  today's stance: every demo's outbound calls go to fixed, hardcoded hosts (or none) -
  no user-controlled destination exists yet, so there is nothing new to curate here.
- **A hand-tuned Content-Security-Policy.** Needs a manual check against the bundled
  Svelte shell's actual asset/connect origins first, to avoid silently breaking the app
  with an overly strict policy picked by guesswork.

## Consequences

- The public gallery gets meaningfully harder to abuse (bounded concurrency, bounded
  uploads, bounded sessions, per-IP throttling) without adding new production
  infrastructure or an external account dependency.
- `InMemorySessionStore`'s public constructor grows two optional keyword arguments;
  every existing caller (notebooks, examples, tests) is unaffected since both default to
  `None` (unbounded, today's behavior).
- Cloudflare and a hardened CSP remain real gaps until a custom domain exists and the
  shell's asset origins are audited; both are written down here rather than silently
  dropped.
