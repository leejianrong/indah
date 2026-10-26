# Host an app for real users

A notebook app trusts whoever opens it. A hosted app cannot: people log in, their data must
stay apart, and the internet is watching. This guide covers what indah gives you for that, and
what it deliberately leaves to the app that hosts it.

The division of labour is simple. **Your app (or its gateway) logs people in.** indah is told who
each request is, keeps one session per person and tab, refuses anyone else's, and gives you the
tools to decide who may see and do what. It does not own passwords, tokens or an identity
provider. Checks run inside the process, because a call to an outside service on every click
would be paid on top of a round trip through the edge, which already costs 100 to 200 ms.

The demo to read alongside this page is the **Hosted** app in the Studio (`make demo`, then Full
apps; the code is `examples/semula_hosted.py`): two users in two browser profiles, three roles, an
admin token screen, and every setting below turned on.

## A secure app in one screen

```python
import indah


def who(request) -> indah.Principal | None:
    user = my_login.lookup(request)  # your cookie, header or session
    if user is None:
        return None
    return indah.Principal(
        id=user.id, name=user.name, roles=frozenset(user.roles), workspace=user.org
    )


def build(ctx: indah.Context) -> indah.Session: ...  # ctx.user is the Principal


app = indah.create_app(
    session_factory=build,
    auth=who,
    secure=True,
    secret=os.environ["INDAH_SECRET"],  # at least 16 random bytes
    trusted_proxies=["10.0.0.0/8"],  # your gateway, so client addresses are real
    limits=indah.Limits.public(),
    security_headers=True,
    csp="strict",
)
```

If your parent app already runs Starlette's `AuthenticationMiddleware`, leave out `auth=`: with
`secure=True` indah reads `scope["user"]`.

## Identity

`Principal` is the caller. Only `id` is required, and it owns sessions.

| Field | Meaning |
|-------|---------|
| `id` | a stable, non-empty string; owns the sessions |
| `name`, `email` | for display |
| `roles` | a set of role names, for [authorization](#who-may-do-what) |
| `workspace` | the tenant or organisation, if you have them |
| `claims` | anything else you want to carry |
| `expires_at` | epoch seconds; a principal past it counts as nobody, and an open stream ends |

An authenticator may be sync or `async`. It fails closed: one that raises, or returns anything
that is not a `Principal`, means "nobody". Your session factory receives the principal as
`ctx.user`.

With `secure=True`, every route that reaches a session (`api/stream`, `api/event`, `api/upload`,
`api/file`) checks identity first:

| Situation | Answer |
|-----------|--------|
| no principal | `401` |
| no session id (nothing falls back to a shared session) | `401` |
| a session id that was not issued to this principal | `403` |
| another person's file download | `404` |

A refused request creates no session and never runs your factory. `secure=True` needs a
per-viewer `session_factory`; one shared `Session` would be one state for every user, so
`create_app` raises. Without `secure=True`, `auth=` only attaches `ctx.user`: notebooks and
public demos are unchanged.

### Signing out

`ctx.sign_out()` ends every session the user holds, shows each tab a "You are signed out" page and
stops it reconnecting. You must still end your own login (clear your cookie), or the next request
signs in again. A stream also ends that way when `Principal.expires_at` passes.

## Sessions and tokens

In a secure app the shell does not make up its session id. On load it calls
`POST api/session`, which authenticates the caller and returns a **signed token**
`<sid>.<signature>`. The signature covers the session id, the principal's id and their workspace,
so a client cannot pick an id, replay another person's, or move a token to another workspace. The
shell sends the token as its session id everywhere, and a reload resumes the same session.

`secret` signs the tokens: at least 16 random bytes, from your environment, never the source. To
rotate, pass a list: the first signs, any verifies, so deploy `[new, old]` and drop `old` later.
Changing it to something with nothing in common signs everyone out of their session (not out of
your login).

Session state lives in memory in the process and is meant to be disposable: filters, selection,
a half-typed note. Keep durable data in your own database. A restart rebuilds each session and
the tab re-initialises cleanly; `ctx.persist` can bring its small state back (see "Restorable
sessions" below). Sessions themselves are not shared, so **run one process** unless
your gateway can send a tab's requests to the process that holds its session.

An event for a session the process does not hold is refused: `409` with
`{"ok": false, "error": "unknown_session"}`, and nothing is created, because the stream is what makes
a session. The shell then opens its stream again for a fresh page and shows "Reconnected. Your last
action was not applied, please try it again." (once, and at most one recovery every few seconds).
Earlier versions built a new, empty session for that request and answered `200`, so a click
simply did nothing. Restarts and evictions now look the same way to the user: one toast and a fresh page.

That makes a misrouted click visible, not fixed. With two processes and no stickiness, a tab whose
clicks land on the wrong process keeps reconnecting and losing its state, so **run one process**
unless your gateway can pin a tab.

What can pin a tab depends on what the browser sends on every request. indah finds a session by the
`sid` in the stream URL and in the JSON body of each event, not by a cookie or a header, so a gateway
that would have to *read* the `sid` (Fly's replay cache, a hash on a header you do not send) has
nothing to key on. A gateway that **sets its own cookie** on the first page load does not need the
`sid`: the browser sends that cookie on the stream and on every event, and the gateway keeps routing
to the same process. That works today on an ingress such as Traefik: on two replicas, 20 of 20 events
stayed on the stream's pod with the cookie and 10 of 20 without it (see [Run on
Kubernetes](deploy-k8s.md)). Fly Proxy has no such cookie. Measured on Fly (IND-171): a client that
sends the request header `fly-force-instance-id: <machine id>` is pinned to that machine. indah's
own shell can send it: see [Several Fly machines](#several-fly-machines).

### Several Fly machines

Turn on the route hint and the shell does the pinning itself, with no gateway configuration. Set a
cluster secret (any long random string, the same on every machine) and scale out:

```bash
fly secrets set INDAH_CLUSTER_SECRET="$(openssl rand -hex 32)"
fly scale count 3
```

On Fly, `INDAH_ROUTE_HINT=auto` turns the hint on once the secret is set. The stream's first message
then names the machine that holds the tab (`route` in `init`, see the [protocol](protocol.md)), and the
shell sends that machine id as `fly-force-instance-id` (and `X-Indah-Route`) with every event and
upload. Download links carry `?r=<machine id>`: a browser navigation cannot set a header, so a machine
that receives a link for another machine's file answers `fly-replay` and Fly Proxy sends the request
to the right one.

What to know:

- **The secret is explicit.** It is never taken from `INDAH_SECRET`, so one secret does not do two
  jobs. Without it the hint stays off (`route_hint="fly"` with no secret logs a warning). On Fly the hint is
  only a machine id, so nothing is signed with the secret yet.
- **If the machine is gone** (a deploy replaced it, it was stopped), Fly answers `400` for the header
  or indah answers `409`. The shell opens its stream again on a machine that is running, shows the
  one "Reconnected" toast, and the next click works. The session's state is not carried over.
- **Only indah's shell sends the hint.** A script that talks to the wire protocol directly still works
  on one machine; to use several, read `route` from `init` and send the header yourself
  (`deploy/probe/sticky_check.py --follow-route` does this).
- **A Cloudflare Worker** in front passes request headers through, so the hint should survive it.
  That was not tested.
- `peers` (a forwarder for Kubernetes without cookie affinity) is not built; `INDAH_ROUTE_HINT=peers`
  is refused. On Kubernetes use an ingress with cookie affinity (see [Run on Kubernetes](deploy-k8s.md)).

Not yet checked on real machines: 20 of 20 events on a three-machine Fly app (the unit, integration and
browser tests cover the shell, the headers and the replay; the probe run is still to do).

## Cross-site requests

A secure app refuses cross-origin requests before parsing them. A page on another site can make a
visitor's browser send a form or multipart POST (a "simple" request, no preflight), which is the
classic way to upload as someone else.

- `Sec-Fetch-Site: same-origin` or `none` passes. `same-site` and `cross-site` pass only when the
  `Origin` is in `create_app(allowed_origins=["https://app.example.com"])`.
- Without Fetch Metadata, an `Origin` header must equal the server's own origin or be allowed. No
  `Origin` at all is a non-browser client and passes.

`POST api/event` also requires `Content-Type: application/json` (`415` otherwise, before the body
is read), and an event with no session id is `400`. Both hold for every app, secure or not.

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

#### Presets

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

#### On Fly

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

## Who may do what

Give your roles meaning with an optional `Policy`, and use the permission names in your code:

```python
policy = indah.Policy(
    {
        "viewer": ["entries:read"],
        "editor": ["entries:*"],  # a prefix wildcard
        "admin": ["*"],
    }
)
app = indah.create_app(..., policy=policy)
```

Without a policy, a permission is simply a role name. Nobody (no principal) holds nothing.

**Omit, do not hide.** Everything in the component tree is sent to the browser, including
components the page never shows, so a button that is merely hidden is still in the page source.
Leave restricted components out of the tree when you build it for that person:

```python
def build(ctx):
    return indah.Session(
        indah.Column(
            children=[
                Overview(),
                *ctx.only("tokens:manage", lambda: TokenScreen()),  # never built for others
            ]
        )
    )
```

`ctx.can("perm")` answers a question and `ctx.require("perm")` raises `indah.Forbidden`.

**Check again where it runs.** The page can be stale: a role may be revoked after it loaded.
`guard` checks when the event arrives, against the person making *that* request (re-authenticated
every time):

```python
Button("Delete", on_click=indah.guard("entries:write")(delete))
```

A refused action answers `403`, shows that tab a "You are not allowed to do that" toast, and does
not run the handler (an `async` handler is refused before it starts). It is not written to the
audit log. Outside a handler there is nobody to authorize, so a guarded call refuses.

Two limits to know. A role *revoked* mid-session stops working for actions at once, but components
already sent stay on screen until the session is rebuilt; a role *added* shows its components after
a rebuild. If that matters, end the user's sessions when roles change
(`store.discard_where(owner=user_id)`). And never read data a person may not see into a signal:
the value would be in the page.

**Workspaces.** A token is bound to the principal's workspace (`ctx.workspace`), so a token from
workspace A is refused once your authenticator says workspace B. Moving someone between workspaces
is your navigation: change what the authenticator returns and reload.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="hosted/policy"></indah-live>

## Showing a secret once

`SecretReveal` shows a new API token with Copy and "I have saved it" buttons:

```python
token = indah.Signal(None)


def create():
    token.set(issue_token())  # call from a handler, after the tab is connected


Column(children=[Button("Create token", create), SecretReveal(token, label="New API token")])
```

The value is an *ephemeral prop*: it goes to the open tab only, and is never put in the `init`
snapshot or the replay history, so a reload, a reconnect or a resume cannot show it again. It is
cleared when the user dismisses it, when the tab reconnects, and when the session closes. If the
connection drops before the user copied it, issue a new one. Store a hash of the token, not the
token. Never put a secret in an exception message: a failing handler's message is shown to the tab
as a toast. The component is marked sensitive, so the audit hook never records its payloads.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="hosted/secret-reveal"></indah-live>

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
`Map` (OpenStreetMap by default). For images or audio from anywhere else, list the host:

```python
indah.create_app(..., csp="strict", csp_media_hosts=["https://cdn.example.com"])
```

Any other string is used as the policy, with `{nonce}` replaced for you. It is off by default and
in `launch()`.

## Live camera

A `Camera` component sends webcam frames to a handler you write. By default the frames go as one
snapshot a second over the upload route, which works everywhere, Colab included. For a smooth feed,
turn on the WebSocket:

```
pip install "indah[live]"
```

```python
# live=indah.Live(max_sockets_per_address=2) tunes the caps
app = indah.create_app(session_factory=build, live=True)
```

Live is off unless you ask for it, and indah never turns it on for you. Colab's proxy blocks
WebSockets, so there `live=True` is ignored with a warning and the camera sends snapshots. What
changes when it is on:

- The upgrade is refused for a cross-site `Origin`, whether or not the app is `secure` (a browser does not
  apply the same-origin policy to a WebSocket). `allowed_origins` applies.
- On a `secure` app the socket uses the same signed session token as every other request.
- Behind a proxy, set `trusted_proxies` as usual, and make sure the proxy passes `Upgrade` requests
  (Cloudflare, Fly and Traefik do).
- With `csp="strict"`, `connect-src` also names the page's own `ws://` or `wss://` origin. Nothing
  else about the policy changes, and with live off it is exactly as before.
- Each address may hold 4 sockets, a frame over 1 MiB closes the socket, and a handler that is slower
  than the camera sees fewer frames, always the newest. Run a heavy model with
  `await asyncio.to_thread(model, frame.data)`.
- The browser only gives out the camera on `https://` pages or `localhost`.

## Logging in with OpenID Connect

indah ships no login, on purpose: your identity provider and your app already own that. The recipe
`examples/oidc_login.py` shows the whole pattern with [authlib](https://docs.authlib.org) in the
parent app, against any OIDC provider:

1. An anonymous visit to the dashboard is sent to `/login`, which redirects to the provider
   (authorization code with PKCE, `state` and `nonce`).
2. The provider returns to `/callback`; authlib exchanges the code and verifies the ID token's
   signature, issuer, audience, expiry and nonce. Any failure is "no login": nothing is stored.
3. A few claims go in Starlette's signed session cookie, and your authenticator turns them into a
   `Principal` on every request (`exp` becomes `expires_at`, a roles claim becomes `roles`).
4. `/logout` clears the cookie and ends that person's indah sessions.

The example installs authlib and itsdangerous itself (`pip install authlib itsdangerous`); indah
has no dependency on them. It is tested against an in-process test provider, including tokens with
a bad signature, audience, nonce and expiry.

## Rolling out without losing tabs

When a process is replaced (a new image on Kubernetes or Fly), its open tabs are connected to it.
indah drains first: on SIGTERM the process stops taking new tabs, tells every open one to reconnect
elsewhere, keeps answering the sessions it still holds, and exits when the last stream is gone or
after `drain_seconds` (default 10), whichever is first. A tab reconnects without an error. It shows
"reconnecting…", and a quiet "Still reconnecting…" note only if that takes more than a few tries. A
tab that lands on the next process starts a fresh session there, so state that is not in your own
database is rebuilt, not carried over.

- `GET /health` is liveness: `200` while the process runs.
- `GET /ready` is readiness: `200`, then `503` once the drain starts. It needs no login and touches
  no session.
- `create_app(drain_seconds=10)` sets the drain length; `drain_on_sigterm=False` leaves SIGTERM
  alone (you drain yourself).
- Under `launch()` and `uvicorn app:app` the SIGTERM handler is installed for you. Under gunicorn
  workers, a parent app that mounts indah, or anything else, call
  `await app.state.drain.run()` from your own shutdown hook. A second SIGTERM stops at once.

`LaunchHandle.drain()` does the same from code (`wait=False` returns as soon as the drain has begun);
`stop()` is unchanged and does not wait for tabs, so call `drain()` first when you want them to move.

### On Kubernetes

Ready-made manifests, with the checks that were run on them, are in [Run on Kubernetes](deploy-k8s.md);
the Fly equivalent is [Run on Fly](deploy-fly.md).

```yaml
spec:
  terminationGracePeriodSeconds: 30   # more than preStop + drain_seconds
  containers:
    - name: app
      readinessProbe:
        httpGet: { path: /ready, port: 7860 }
        periodSeconds: 5
      livenessProbe:
        httpGet: { path: /health, port: 7860 }
      lifecycle:
        preStop:
          exec: { command: ["sleep", "5"] }   # let the ingress stop routing here first
```

Kubernetes removes the pod from the service as soon as it starts terminating, and sends SIGTERM after
`preStop` finishes. The short sleep gives the ingress time to stop sending new tabs to the old pod
before the drain begins. Several replicas also need your ingress to keep a tab on one pod; see
"Sessions and tokens" above.

### On Fly

```toml
kill_signal = "SIGTERM"   # Fly's default signal is SIGINT, which indah does not drain on
kill_timeout = 15         # seconds, more than drain_seconds

[[http_service.checks]]
  method = "GET"
  path = "/ready"
  interval = "10s"
  timeout = "2s"
  grace_period = "10s"
```

These snippets follow the Kubernetes and Fly documentation. The drain itself is tested here with real
processes and a real browser; a rollout on a real cluster or a real Fly deploy is not yet.

## Restorable sessions

A tab's session lives in one process, so a restart, a rollout or a move to another replica starts it
again. `ctx.persist` keeps the small state worth keeping (the selected tab, filters, a half-typed
note) in a **state store** and puts it back when the session is rebuilt:

```python
def build(ctx):
    tab = Signal("overview")
    filters = Signal({})
    ctx.persist("tab", tab)  # restores the saved value now, saves on every change
    ctx.persist("filters", filters, version=2, ttl=3600)
    ...
```

The value is restored inside the factory, before the first paint. After that it is saved when it changes
(a burst of keystrokes is one write, about a quarter of a second later) and once more when the session
ends. A tab is found again by its session id: the shell keeps it in `sessionStorage`, so a reload or a
rebuild on another replica finds the same state. A new tab, another browser or another device starts
from the defaults. In a `secure` app the saved value also records the user, and it is ignored for anyone
else.

```python
create_app(session_factory=build, state_store="sqlite:///state.db")
```

| Store | Use it for | Notes |
|-------|------------|-------|
| `"memory"` (default) | a tab rebuilt in the same process (an idle session reaped, a dropped stream) | does not survive a restart |
| `"sqlite:///state.db"` | one replica that restarts | the standard library, one file; do not share it between replicas over a network file system |
| `"redis://host:6379/0"` | several replicas, or state that must outlive a pod | `pip install "indah[redis]"`; you provide the Redis (see below) |
| your own `StateStore` | any other shared store | five methods (`get`, `set`, `delete`, `delete_prefix`, `close`), each plain or `async def` |

Nothing runs or bundles a service for you.

### Redis

Redis is the store to use when a rolled-out or moved replica must find the state the old one saved. Install
the extra (`pip install "indah[redis]"`, which adds the `redis` package; the base install does not need it)
and point the app at your Redis:

```bash
INDAH_STATE_STORE=redis://redis:6379/0        # or: create_app(state_store="redis://redis:6379/0")
INDAH_STATE_STORE=redis INDAH_REDIS_URL=...   # the URL in its own Secret, with the password in it
```

- **TLS and users**: `rediss://` is TLS, and `redis://app:password@host:6379/0` signs in as an ACL user. That
  user needs `GET`, `SET`, `DEL`, `UNLINK`, `SCAN` and `PING` on the keys `indah:*` (your `state_namespace`
  is the first part of each key). For example `ACL SETUSER app on >password ~indah:* +get +set +del
  +unlink +scan +ping`.
- **Expiry** is Redis's own: each write sets the value's lifetime (24 hours by default, see above).
- **Failures**: timeouts are one second. A Redis that is down or slow never holds a tab: the saved values
  are read in the background after the first paint, a failed read starts from the defaults, a failed write
  is dropped, and the log says so about once a minute. A connection that was cut is reopened on the next call.
- **The doctor** (`/_indah/doctor`) shows the store kind and, for Redis, `ok` or `unreachable` with a warning.
- **Not in this store**: no registry of which replica holds which tab, and no pub/sub, so a `Topic` is still
  per replica (below).

On Kubernetes, a Redis `Deployment` and a `Service` named `redis` are enough for a start (one replica,
no persistence: restored state is a convenience, and losing it only sends tabs back to their defaults):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: {name: redis}
spec:
  replicas: 1
  selector: {matchLabels: {app: redis}}
  template:
    metadata: {labels: {app: redis}}
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          args: ["--save", "", "--maxmemory", "128mb", "--maxmemory-policy", "volatile-ttl"]
          ports: [{containerPort: 6379}]
---
apiVersion: v1
kind: Service
metadata: {name: redis}
spec:
  selector: {app: redis}
  ports: [{port: 6379}]
```

Then set `INDAH_STATE_STORE=redis://redis:6379/0` in the app's ConfigMap. Without a password, keep the
Service inside the cluster and add a NetworkPolicy; with one, put the URL in a Secret and use
`INDAH_STATE_STORE=redis` with `INDAH_REDIS_URL` from it.

On Fly, use Upstash Redis (`fly redis create`, which prints a `rediss://` URL) or a Redis of your own on
a Fly app, in the same region as your machines, and set the URL as a secret:
`fly secrets set INDAH_STATE_STORE=redis INDAH_REDIS_URL='rediss://default:...@fly-...upstash.io:6379'`.

These snippets are not yet applied to a real cluster or a real Fly app; the store itself is tested against
a real Redis in CI.

What is saved, and what never is:

- **Plain JSON only**: `str`, `int`, `float`, `bool`, `None`, `list` and `dict` with string keys. Anything
  else raises `ValueError` at the `persist` call.
- **Size caps**: 16 KB per value and 128 KB per session. A larger value is not saved (one warning), and the
  older copy is removed so it cannot come back over a newer one. `INDAH_PERSIST_MAX_BYTES` or
  `persist_max_bytes=` changes the per-value cap.
- **Lifetime**: 24 hours after the last write (`ttl=` per value, `INDAH_PERSIST_TTL` or `persist_ttl=` for
  the default).
- **No secrets**: persist UI state, not tokens. A signal shown in a `SecretReveal` (an ephemeral prop) is
  refused with an error in the log, and anything stored for it is deleted. A store holds what your app
  chose to save, so treat it like your own database.
- **Shape changes**: pass `version=` and bump it when a signal's shape changes; older values are ignored.
  `validate=` can veto a restored value.
- **Failures**: a store that is down never breaks the tab. A failed read starts from the defaults, a failed
  write is dropped, and the log says so about once a minute.
- With an `async` store, the read is awaited in the background, so the saved values arrive a moment after
  the first paint.

`guard` and your `Policy` are unaffected: restoring a value runs no handler. Several apps that share one
store should each set `state_namespace=` (or `INDAH_STATE_NAMESPACE`) so their keys do not meet.

The browser could also hold this state itself and send it back, which needs no store at all. That is not
built: the browser can read and change its own values, so the app would have to validate every restored
value, and it needs a shell change. The `StateStore` interface admits such a store when it is wanted.

<indah-live page="live/persist"></indah-live>

## Topic and Stream with several replicas

A `Topic` and a `Stream` live in one process: a producer feeds the tabs of **its own** replica only. With
more than one replica, run the producer in **every** replica and let each one read the source itself (a
poll, a queue consumer, a database change feed). Every replica then holds the same recent history and its
own tabs follow it. There is no bus between replicas, and a `Topic` you publish to in one replica is not
seen in another. If you need a shared feed that a single producer fills, tell us what you are feeding
it from; a Redis-backed `Topic` is a later card, not part of the current design.

## Configuration from the environment

A ConfigMap, a Kubernetes Secret or `fly secrets set` hands an app environment variables, not Python
arguments. `create_app` reads the variables below **only when the matching argument is not passed**:
an explicit argument always wins, even an empty list or `None`. A blank variable counts as unset. A bad
value stops the app at start with a message that names the variable. Secret values are never logged: at
start indah logs once, at INFO, which variables it used (names only).

| Variable | Argument | Example | Default |
|----------|----------|---------|---------|
| `INDAH_SECRET` | `secret=` | `INDAH_SECRET=<32+ random bytes>` | none |
| `INDAH_SECRETS` | `secret=` as a list (rotation) | `INDAH_SECRETS=<new>,<old>` | none; wins over `INDAH_SECRET` |
| `INDAH_TRUSTED_PROXIES` | `trusted_proxies=` | `fly` or `172.16.0.0/12,66.241.124.81` | none; IPs, CIDRs or the presets `fly`, `cloudflare`, `k8s`, `private`; `*` and `auto` are refused |
| `INDAH_FLY_IPS` | read by the `fly` preset | `66.241.124.81,2a09:8280:1::1c9:9684:0` | looked up from `<FLY_APP_NAME>.fly.dev` |
| `INDAH_ALLOWED_ORIGINS` | `allowed_origins=` | `https://app.example.com` | none |
| `INDAH_CSP` | `csp=` | `strict` or `off` | off |
| `INDAH_LIMITS` | `limits=` | `public` or `none` | none |
| `INDAH_DRAIN_SECONDS` | `drain_seconds=` | `30` | `10` |
| `INDAH_FACTORY_TIMEOUT` | `factory_timeout=` | `2.5` | `1` |
| `INDAH_STATE_STORE` | `state_store=` | `memory`, `sqlite:///state.db`, `redis://host:6379/0` or `redis` | `memory`; where `ctx.persist` saves |
| `INDAH_REDIS_URL` | (with `state_store="redis"`) | `rediss://user:pw@host:6379/0` | none; the Redis URL, kept apart so it can be a Secret |
| `INDAH_STATE_NAMESPACE` | `state_namespace=` | `orders` | `indah` |
| `INDAH_PERSIST_TTL` | `persist_ttl=` | `3600` | `86400` (seconds after the last write) |
| `INDAH_PERSIST_MAX_BYTES` | `persist_max_bytes=` | `8192` | `16384` (per value) |
| `INDAH_COMPRESS` | `compress=` | `0` | on |
| `INDAH_WARN_UNTRUSTED_FORWARDING` | `warn_untrusted_forwarding=` | `0` | on |
| `INDAH_NODE_HEADER` | `node_header=` | `1` | off |
| `INDAH_NODE` | names the node for `node_header` | `web-1` | `FLY_MACHINE_ID`, `HOSTNAME`, or a random id |
| `INDAH_ROUTE_HINT` | `route_hint=` | `auto`, `fly` or `off` | `auto`: on for Fly when `FLY_MACHINE_ID` is set and a cluster secret is given, else off |
| `INDAH_CLUSTER_SECRET` | `cluster_secret=` | 16+ random characters | none; never taken from `INDAH_SECRET` |
| `INDAH_DOCTOR_TOKEN` | `doctor=` | 16+ random characters | off |
| `INDAH_METRICS_TOKEN` | `metrics=` | 16+ random characters | off |

Booleans take `1`/`0`, `true`/`false`, `yes`/`no` or `on`/`off`. The secret is only read for
`secure=True`. `INDAH_CSP` takes `strict` or `off`; a custom policy string is `csp=` in code.

```bash
fly secrets set INDAH_SECRET="$(openssl rand -hex 32)" INDAH_TRUSTED_PROXIES="fly"
```

```yaml
# Kubernetes: a Secret for the secret, a ConfigMap for the rest
env:
  - name: INDAH_SECRET
    valueFrom: { secretKeyRef: { name: indah, key: secret } }
envFrom:
  - configMapRef: { name: indah-config }   # INDAH_TRUSTED_PROXIES, INDAH_DRAIN_SECONDS, ...
```

Settings with no variable (the session factory, `auth`, `policy`, `audit`, `theme`) stay in code.

### Which process answered

With several processes, the first question when a tab misbehaves is which one answered. Turn on
`node_header=True` (or `INDAH_NODE_HEADER=1`) and every response, the event stream's included, carries
`X-Indah-Node: <id>`:

```bash
curl -sI https://app.example.com/ | grep -i x-indah-node
x-indah-node: e826010b63e458
```

The id is `INDAH_NODE`, else `FLY_MACHINE_ID` (a Fly machine), else `HOSTNAME` (a pod name on
Kubernetes), else a random id that lasts for the process. It is opaque on purpose: a value that is an IP
address, or that has anything other than letters, digits, `.`, `_` and `-`, is replaced by a short hash
(`n-` and ten hex digits), so the header never carries an internal address. Repeat a request a few times: if
the id changes while one tab is open, the gateway is not pinning that tab to a process (see the sticky
session limits above). `ctx.conn.node` and `app.state.node` hold the same id with the header on or off;
the header is off by default because it tells a visitor which of your processes they reached.

### The deploy doctor

When something is wrong behind a gateway, the useful page shows what the gateway did to *one request*
and what indah made of it. Turn it on with a token (16 characters or more) and open `/_indah/doctor`:

```python
indah.create_app(..., doctor="a-long-random-token")  # or set INDAH_DOCTOR_TOKEN
indah.create_app(..., secure=True, policy=policy, doctor=True)  # a principal holding "doctor"
```

```bash
curl -H "Authorization: Bearer $INDAH_DOCTOR_TOKEN" 'https://app.example.com/_indah/doctor?format=json'
```

It shows:

- the **resolved client** next to the real **socket peer**, the scheme and the host, and the believed
  forwarded prefix: the first thing to compare when every visitor looks like one address;
- the forwarded headers that matter (`X-Forwarded-For`, `Fly-Client-IP`, `CF-Connecting-IP`, `Via` and a
  few more), from a fixed list of names. It never shows cookies, `Authorization` or any other header;
- `trusted_proxies` as indah parsed it (preset names next to the networks they expanded to), the node, the process age and the requests it has answered, the
  Fly region and machine or the pod name when they are set, the open sessions and streams, and the drain
  state;
- the settings in force as names and yes/no (never a secret), and the `INDAH_*` variables that were used
  (names only);
- **findings** in plain language: forwarded headers with no `trusted_proxies`, a peer that is not trusted,
  a resolved client that is itself a proxy, a gateway header that names a different visitor (the Fly
  mistake: the fix is the app's public IPs from `fly ips list`), a drain in progress.

Reload it a few times: if the node changes, more than one process answers.

Who may open it: a request with the token (as `Authorization: Bearer <token>` or `?token=`), or with
`doctor=True` a logged-in principal holding the `doctor` permission. Everyone else gets the same plain
`404` a missing route gives, so the page does not advertise itself. A token in a URL ends up in access
logs and browser history, so prefer the header for scripts and use a throwaway token for a browser. Ten
wrong tries from one address lock it out for a minute. The page is never cached or indexed and sets its
own strict Content-Security-Policy. It is off unless you ask, and you should keep it behind the token:
it tells whoever opens it how your deployment is wired.

### Metrics

For Prometheus, and for autoscaling on open streams, turn on `GET /metrics`. It is off unless you ask,
and it is gated like the doctor: the same token rules, and the same plain `404` for everyone else.

```python
indah.create_app(..., metrics="a-long-random-token")  # or set INDAH_METRICS_TOKEN
indah.create_app(..., secure=True, policy=policy, metrics=True)  # a principal holding "metrics"
```

The doctor token does not open it, and the metrics token does not open the doctor. The text is in the
Prometheus format and describes one process (your scraper adds the `instance` label):

| Series | Kind | Meaning |
|---|---|---|
| `indah_sessions_open` | gauge | sessions this process holds |
| `indah_streams_open` | gauge | open SSE streams (tabs connected right now) |
| `indah_draining` | gauge | `1` while the process drains, else `0` |
| `indah_events_total` | counter | events dispatched to a session |
| `indah_errors_total` | counter | handler exceptions (a `guard` refusal is not an error) |
| `indah_forwards_total` | counter | requests sent on to the process that owns the session (Fly file replays today) |
| `indah_forward_failures_total` | counter | forwards that did not reach it (stays `0` until the Kubernetes forwarder exists) |
| `indah_build_info` | gauge | always `1`, with the indah `version` as a label |

It holds counts only: no session id, user, path or secret. Keep `/metrics` off the public internet
anyway: let your scraper reach it inside the cluster, and have the ingress refuse the path from outside.
If your own app serves a route called `/metrics`, indah's takes the path while it is on.

A scrape with a bearer token (Prometheus `scrape_config`):

```yaml
scrape_configs:
  - job_name: indah
    authorization: {type: Bearer, credentials_file: /etc/prometheus/indah-token}
    static_configs: [{targets: ["indah.default.svc:8000"]}]
```

To scale on open streams, a replica's load is its connected tabs, so average `indah_streams_open` per
pod. With the Prometheus adapter exposing it as a pods metric (the adapter rule is yours to write), an
HPA looks like this. It is an example from the format, not something checked on a cluster:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: indah}
spec:
  scaleTargetRef: {apiVersion: apps/v1, kind: Deployment, name: indah}
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Pods
      pods:
        metric: {name: indah_streams_open}
        target: {type: AverageValue, averageValue: "200"}
  behavior:
    scaleDown: {stabilizationWindowSeconds: 300}   # tabs reconnect on a drain; do not flap
```

Scale-down ends streams, and a tab reconnects to another pod (see rolling out above), so keep the
window long.

## Checklist

- `secure=True`, a `secret` from the environment, and `session_factory` (not `session`).
- `trusted_proxies` set to your gateway (checked with the deploy doctor, not guessed); one process, or a gateway that pins a tab to its process.
- Restricted components built with `ctx.only`; mutating handlers wrapped in `guard`.
- `limits=Limits.public()` (or your own), `security_headers=True`, `csp="strict"`.
- `/ready` as the readiness check, SIGTERM reaching indah (Fly: `kill_signal = "SIGTERM"`), and a grace period longer than `drain_seconds`.
- An `audit=` hook that writes somewhere you keep.
- Your own login ended when you call `ctx.sign_out()`; session cookies `HttpOnly`, `Secure` and
  `SameSite=Lax`.
- The edge (Cloudflare or similar) in front for the limits only a network edge can enforce.

The wire details are in the [Protocol](protocol.md) reference, and the decisions behind each part
are ADRs 0033 to 0038 in the repository.
