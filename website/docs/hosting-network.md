# Gateways, limits and CSP

Settings for an app that sits behind a proxy and faces the internet: trusted proxies, the audit hook, rate limits, headers, compression and the Content-Security-Policy.

## Behind a gateway

Behind Cloudflare, Fly, a load balancer or your own gateway, the socket peer is the gateway, and
the real client address, scheme and path prefix arrive in `X-Forwarded-*` headers that any client
can also send. indah believes them only from the proxies you list:

```python
indah.create_app(..., trusted_proxies=["10.0.0.0/8", "203.0.113.7"])
```

- The default is none. `*` and `/0` networks are refused at startup.
- From a trusted peer, the client address is the rightmost `X-Forwarded-For` hop that is not
  itself a trusted proxy, so addresses a client prepended are never believed.
- `X-Forwarded-Proto` and `-Host` make the origin check compare against the public origin.
- `X-Forwarded-Prefix` is kept as `ctx.conn.prefix` for building absolute links. It never changes
  routing.

If you forget `trusted_proxies`, every client shares the gateway's address: one rate-limit bucket
and one stream cap for everybody.

indah tells you when that is happening. The first time a request carries `X-Forwarded-For`,
`Forwarded`, `X-Forwarded-Proto`, `Fly-Client-IP` or `CF-Connecting-IP` while `trusted_proxies` is
empty, it logs one warning per process. The warning names the header and the socket peer, never a
header value, and `app.state.proxy_warning_issued` becomes `True`. Silence it by setting
`trusted_proxies`. Passing `trusted_proxies=[]` does not silence it, because that is the same as
leaving it out. If nothing really sits in front of your app, pass
`create_app(warn_untrusted_forwarding=False)`. `launch()` turns the warning off in Colab and Runpod,
where the host's own proxy is always there.

### Presets

Typing the right CIDRs for a platform is easy to get wrong, so `trusted_proxies` also takes preset
names. A preset expands to an explicit list before anything else looks at it, composes with plain
entries, and never turns on by itself:

```python
indah.create_app(..., trusted_proxies=["fly"])
indah.create_app(..., trusted_proxies=["cloudflare", "203.0.113.7"])
```

| Preset | Expands to | Caveat |
|--------|-----------|--------|
| `private` | `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` | trusts every host in those networks |
| `k8s` | `private` plus `100.64.0.0/10` (CGNAT) and `fc00::/7` (unique local) | trusts every pod and node; narrow it to your ingress range when you know it |
| `cloudflare` | Cloudflare's published edge ranges (15 IPv4, 7 IPv6), copied into indah | the list is vendored, not fetched; it is dated in `indah/cloudflare_ips.py` and refreshed by `scripts/refresh_cloudflare_ips.py` |
| `fly` | `172.16.0.0/12` plus the app's public ingress IPs | needs the IPs: see below |

A preset **trusts every address in it**. Anyone who can send a request from inside that network can
set `X-Forwarded-For` and be believed, so use the narrowest preset that fits, and an explicit list when
you know your gateway's addresses. `"auto"` and `"*"` are refused on purpose, and so is any name
that is not in the table; the error lists the valid ones. In the environment,
`INDAH_TRUSTED_PROXIES=cloudflare,203.0.113.7` works the same way.

The `fly` preset finds the app's public IPs in one of two ways: `INDAH_FLY_IPS` (a comma separated list
of single addresses from `fly ips list`) if it is set, otherwise a DNS lookup of
`<FLY_APP_NAME>.fly.dev` when the app starts, which Fly answers with the app's public addresses (checked
from inside a machine on the probe app, IND-198). If neither works the app stops at start with a message
that says what to run (`fly ips list -a <app>`) and what to set. The lookup happens once, so restart the
app after you add or change an IP.

### On Fly

Measured on a Fly app (IND-170), the peer is a private address in `172.16.0.0/12`, the real client is
in `Fly-Client-IP`, and Fly sets `X-Forwarded-For` to `<client>, <your app's public IP>`. So trusting
only the private range resolves every visitor to your app's own address. List both:

```python
indah.create_app(..., trusted_proxies=["fly"])  # the private range plus this app's public IPs
# the same, spelled out (use your own addresses from `fly ips list`):
indah.create_app(..., trusted_proxies=["172.16.0.0/12", "66.241.124.81", "2a09:8280:1::1c9:9684:0"])
```

If you list only the private range on Fly, indah logs a warning at start that names the public addresses
it is missing and points at `["fly"]`. This was verified for IPv4 clients; an IPv6 client was not
tried. It was measured on the direct `*.fly.dev` path only: the path through a Cloudflare Worker is
not measured yet. Start uvicorn with `--no-proxy-headers` if you want only indah's rules in play.

### An audit trail

```python
indah.create_app(..., audit=lambda e: log.info("%s %s %s", e.user, e.component, e.event))
```

The hook is called after each dispatched UI event and upload with the time, the session id (never
the signed token), the user id, the component, the event and the payload **keys**. Values are
included only with `audit_payloads=True`, and never from a sensitive component (a password input,
`SecretReveal`). The hook may be sync or async and runs on the event loop, so keep it quick or hand
off to a queue. Refused requests are not audited; that is the access log's job.

## Limits and headers

Every bound is optional, and unset means "as before", so adding `Limits()` changes nothing until
you set something. `Limits.public()` is a starting point for the open internet.

```python
indah.create_app(
    ...,
    limits=indah.Limits(
        rate={
            "/api/event": indah.Rate(per_second=5, burst=30),
            "/api/upload": indah.Rate(per_second=0.5, burst=4),
        },
        max_streams_per_ip=8,
        max_event_bytes=1_000_000,
        max_upload_mb=25,
        max_sessions=1000,
        session_idle_seconds=1800,
    ),
    security_headers=True,
)
```

| Bound | When exceeded |
|-------|---------------|
| `rate` (per address, per route) | `429` with `Retry-After`; nothing is created |
| `max_streams_per_ip` | `429` on `api/stream`; a closed stream frees its slot |
| `max_event_bytes` | `413` before the body is parsed |
| `max_upload_mb` | `413` |
| `max_sessions`, `session_idle_seconds` | the least recently used or idle session is dropped |

Limits are per process, so several replicas multiply them: the gateway's limit is the global one.
The address is the socket peer after `trusted_proxies`, never a raw `X-Forwarded-For`.

`security_headers=True` adds `X-Content-Type-Options: nosniff`, `Referrer-Policy:
strict-origin-when-cross-origin` and `X-Frame-Options: DENY`. Pass a mapping to change one
(`{"X-Frame-Options": "SAMEORIGIN"}` if you embed the app in a page of your own origin; `""` drops
a header). Leave it off in a notebook, where Colab shows the app in a frame.

## Compression

indah gzips the three things it serves that are large and static: the page itself (about 580 KB,
244 KB gzipped), the code editor module (633 KB, 178 KB gzipped) and the files of a module
component. A client that sends `Accept-Encoding: gzip` gets them compressed, with `Vary:
Accept-Encoding`, so a cache keeps the two forms apart, and each form has its own `ETag` (the
gzip one ends in `-gz`) and answers `If-None-Match` with `304`. Before this, a proxy that did not
compress them itself (Fly and Cloudflare do) sent the full size.

- The event stream (`api/stream`) and the JSON routes are never compressed, so a streamed frame
  is not held back waiting for a compression window.
- The page is compressed in pieces around the CSP nonce, so a page load costs about 1 ms more
  than before (2.7 ms against 1.7 ms) rather than the 35 ms a gzip of the whole page would take.
- Compressing the page is safe against BREACH: it carries a random nonce, the base path and your
  own title and theme, never a session token or a secret. Tokens travel in a POST body, and
  one-time secrets on the stream.
- A gateway or CDN may compress again, or in a better format (brotli); that is fine, indah
  sends an already-compressed body with `Content-Encoding: gzip` and the gateway leaves it alone.
- `create_app(compress=False)` turns it off, for example behind a gateway that you want to do all
  of the compression.

## Content-Security-Policy

`csp="strict"` serves the shell with a per-response nonce on its inline script and style tags and
a policy that allows nothing else to run: no inline script, no `eval`, connections to your own
origin only. Browsers report violations to `POST api/csp-report`, kept in
`app.state.csp_violations` and logged.

Images and audio may come from your origin, `data:` and `blob:` URLs, and the tile host of any
`Map` (OpenStreetMap by default); an app with no `Map` allows no third-party image host. A `Map`
that a session builds after the page has loaded is allowed from the next load, and indah logs a
warning, so for a first-load map list its tile host as well. For images or audio from anywhere
else, list the host:

```python
indah.create_app(..., csp="strict", csp_media_hosts=["https://cdn.example.com"])
```

Any other string is used as the policy, with `{nonce}` replaced for you. It is off by default and
in `launch()`.
