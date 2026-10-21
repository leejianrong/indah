# Host an app for real users

A notebook app trusts whoever opens it. A hosted app cannot: people log in, their data must
stay apart, and the internet is watching. This guide covers what indah gives you for that, and
what it deliberately leaves to the app that hosts it.

The division of labour is simple. **Your app (or its gateway) logs people in.** indah is told who
each request is, keeps one session per person and tab, refuses anyone else's, and gives you the
tools to decide who may see and do what. It does not own passwords, tokens or an identity
provider. Checks run inside the process, because a call to an outside service on every click
would be paid on top of a round trip through the edge, which already costs 100 to 200 ms.

The demo to read alongside this page is `examples/semula_hosted.py` (`make demo-hosted`): two
users in two browser profiles, three roles, an admin token screen, and every setting below turned
on.

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
the tab re-initialises cleanly. With more than one process, use sticky sessions at your gateway so
a tab's requests reach the process that holds its session. There is no external session store.

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

## Checklist

- `secure=True`, a `secret` from the environment, and `session_factory` (not `session`).
- `trusted_proxies` set to your gateway; sticky sessions if you run more than one process.
- Restricted components built with `ctx.only`; mutating handlers wrapped in `guard`.
- `limits=Limits.public()` (or your own), `security_headers=True`, `csp="strict"`.
- An `audit=` hook that writes somewhere you keep.
- Your own login ended when you call `ctx.sign_out()`; session cookies `HttpOnly`, `Secure` and
  `SameSite=Lax`.
- The edge (Cloudflare or similar) in front for the limits only a network edge can enforce.

The wire details are in the [Protocol](protocol.md) reference, and the decisions behind each part
are ADRs 0033 to 0038 in the repository.
