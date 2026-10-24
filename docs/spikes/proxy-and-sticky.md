# Trusted proxies and sticky sessions on Fly (IND-170, IND-171)

- Date: 2026-10-24. indah 0.6.0 on a throwaway Fly app, `indah-probe` (`deploy/probe/`), region `sin`.
- Method: a probe app that echoes what the request looked like and which machine answered
  (`X-Probe-Machine`). Client: this machine (Singapore, public address 122.11.212.50, found with
  `curl https://api.ipify.org`, a third-party request).
- **Half done.** The direct Fly path and all of IND-171 are measured here. The Cloudflare Worker hop
  of IND-170 needs the owner's dashboard steps in `deploy/probe/README.md`; it is not measured, and
  IND-170 stays open.

## 1. What Fly sends (direct path, no Worker)

`curl -s https://indah-probe.fly.dev/whoami`, `trusted_proxies` empty:

| What | Value |
|------|-------|
| socket peer (what indah sees) | `172.16.1.226` (Fly's private range) |
| `Fly-Client-IP` | `122.11.212.50` (the real client) |
| `X-Forwarded-For` | `122.11.212.50, 66.241.124.81` |
| `X-Forwarded-Proto`, `-Port`, `-Ssl` | `https`, `443`, `on` |
| `Via` | `2 fly.io` |
| `Host` | `indah-probe.fly.dev` |

`fly ips list -a indah-probe` shows `66.241.124.81` is the app's own shared IPv4 ingress address. So
Fly appends **its ingress address**, not just the client, to `X-Forwarded-For`. A client-sent
`X-Forwarded-For: 6.6.6.6` arrives as `6.6.6.6, 122.11.212.50, 66.241.124.81`.

## 2. `trusted_proxies` variants (direct path)

indah takes the rightmost hop that is not a trusted proxy (ADR-0034). Set with
`deploy/probe/set-trusted.sh "<list>"`; client column is `resolved_client`.

| `trusted_proxies` | Client, no spoof | Client, spoofed `X-Forwarded-For: 6.6.6.6` | Right? |
|-------------------|------------------|--------------------------------------------|--------|
| none | `172.16.1.226` | `172.16.1.226` | no: every visitor shares one address |
| `172.16.0.0/12` | `66.241.124.81` | `66.241.124.81` | **no**: the app's own ingress address |
| `172.16.0.0/12,66.241.124.81` | `122.11.212.50` | `122.11.212.50` | yes; the spoofed hop is ignored |
| `*` | refused at startup | | by design |

Trusting only the private range looks right and is wrong: every visitor resolves to the same
ingress address, so the per-address rate limit and stream cap are shared by everybody, the very
thing `trusted_proxies` is meant to fix. The working value on Fly is the private range **plus the
app's public ingress addresses** (`fly ips list`). With `*`, the machine exits at startup
(`ValueError: trusted_proxies entry '*' is not an IP address or CIDR`) and stays stopped; a `/0`
network is refused with its own message (unit-tested in `tests/unit/test_proxy_headers.py`).

The IPv6 ingress address (`2a09:8280:1::1c9:9684:0` here) was added to the list as a precaution.
**Unverified:** this machine has no IPv6 route, so a client arriving over IPv6 was not tried, and
what Fly appends to `X-Forwarded-For` in that case is not known.

## 3. Sticky sessions: the failure (IND-171)

`fly scale count 2` (two machines in `sin`). `deploy/probe/sticky_check.py` opens one tab's stream,
then posts 20 click events with that session id. A POST to a machine that does not hold the
session builds a **new** session there and answers `200`; its patch goes to that machine's hub,
and the tab, whose stream is on the other machine, never sees it.

| Run | Stream on | POSTs answered by | HTTP | Patches that reached the tab |
|-----|-----------|-------------------|------|-------------------------------|
| one keep-alive client | `d8d1…` | `e826…` 17, `d8d1…` 3 | all 200 | 3 of 20 |
| a new connection per POST | `e826…` | `e826…` 5, `d8d1…` 15 | all 200 | 5 of 20 |

The failure is **silent**: no error status, the button just does nothing most of the time.

## 4. What works without changing indah

indah identifies a session by `sid` in the stream's query string and in the JSON body of each event
(`frontend/src/api.js`). There is no cookie and no header carrying it. That decides what can work:

| Option | Works today? | Why |
|--------|--------------|-----|
| Fly replay cache by cookie or header ([doc](https://docs.fly.io/networking/dynamic-request-routing)) | no | needs a cookie or header; indah sends neither |
| Cloudflare Load Balancing cookie affinity ([doc](https://developers.cloudflare.com/load-balancing/understand-basics/session-affinity/)) | not tested | a `__cflb` cookie pins to an **origin**; the machines of one Fly app are not separate public origins, so it would need one Fly app per machine and a load balancer (the doc does not state its price) |
| App-side `fly-replay` | not built | needs a machine id in the session id (design below) |
| A client that sends `fly-force-instance-id: <machine>` | **yes, measured** | 12 of 12 events on the stream's machine, for either machine, `STICKY`; a machine id that does not exist is `400` |
| `fly-prefer-instance-id: <machine>` | yes, measured | 12 of 12; falls back to another machine if the preferred one is down, which brings the silent failure back |
| One machine | yes | what the gallery does (`--ha=false`) |

Sources: Fly [Dynamic Request Routing](https://docs.fly.io/networking/dynamic-request-routing)
(request headers `fly-force-instance-id`, `fly-prefer-instance-id`; the `fly-replay` response header;
replay cache keyed on a cookie or header; 1 MB limit on replayed requests) and the
[sticky sessions blueprint](https://docs.fly.io/blueprints/sticky-sessions) (the client-side header,
or `fly-replay` plus the replay cache; the first request takes an extra hop). Fly's docs do not say
what happens under `auto_stop` when the target machine is stopped: not tested.

So **sticky sessions are not possible on Fly today with indah as it is, except through a client that
sets `fly-force-instance-id`**. The browser shell does not. The production Cloudflare Worker could:
hash the `sid` (stream URL) or read it from the small JSON event body, map it to a machine id from a
configured list and add the header. That has costs (the list changes when machines are added, which
resets the sessions that move; an upload carries `sid` in a multipart body, which a Worker should not
parse), so it is a recipe to try, not a recommendation.

## 5. A small design that would fix it in indah (a follow-up card, not built)

The shell already makes every event with `fetch`, which can set headers. If the server told the
shell which machine holds the session, the shell could send `fly-force-instance-id` itself:

1. The first `init` message gains an optional `route` hint (additive, `protocol_version` stays 1),
   for example `{"route": {"fly-force-instance-id": "<FLY_MACHINE_ID>"}}`, sent only when the env var is
   set.
2. The shell adds those headers to `POST api/event` and `api/upload`. The stream (an `EventSource`) cannot
   set headers, and a reconnect lands anywhere; a reconnect to the wrong machine builds a new session
   and a fresh `init`, which is today's behaviour.
3. If the machine is gone, `force` answers an error; the shell treats it as "session lost" and
   re-opens the stream. Tests: this probe is the harness.

## 6. Not verified

- The Cloudflare Worker hop (IND-170): what `CF-Connecting-IP`, `X-Forwarded-For` and `Via` look like
  after `browser -> Cloudflare -> Worker fetch() -> Fly`, and which `trusted_proxies` value resolves the
  visitor there. Needs `deploy/probe/README.md`.
- IPv6 clients; Safari and any browser behaviour (none involved: only `curl` and `httpx`).
- Whether machine ids are stable across `fly deploy`. A rolling deploy updated the gallery's machine
  in place (same id in the log), but replacement was not tried.
- A stopped target machine under `auto_stop`; Cloudflare Load Balancing price and a two-app setup.
- Other platforms' proxies (Render, Railway, Kubernetes ingress).

## Commands

```
deploy/probe/deploy.sh                                   # new app indah-probe, one machine
deploy/probe/set-trusted.sh "172.16.0.0/12,66.241.124.81"
curl -s https://indah-probe.fly.dev/whoami -H 'X-Forwarded-For: 6.6.6.6'
fly ips list -a indah-probe
fly scale count 2 -a indah-probe --yes
uv run python deploy/probe/sticky_check.py https://indah-probe.fly.dev --events 20 --new-conn
uv run python deploy/probe/sticky_check.py https://indah-probe.fly.dev --events 12 --new-conn \
  --header "fly-force-instance-id: <machine id>"
deploy/probe/teardown.sh                                 # when finished
```
