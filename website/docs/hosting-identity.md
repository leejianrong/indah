# Identity, sessions and sign-in

Who a request is, how a tab keeps its session, and how a login reaches indah. Start from [Host an app for real users](hosting.md) if you have not read the one-screen setup.

## Identity

`Principal` is the caller. Only `id` is required, and it owns sessions.

| Field | Meaning |
|-------|---------|
| `id` | a stable, non-empty string; owns the sessions |
| `name`, `email` | for display |
| `roles` | a set of role names, for [authorization](hosting-access.md#who-may-do-what) |
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
the tab re-initialises cleanly; `ctx.persist` can bring its small state back (see [Restorable
sessions](hosting-scale.md#restorable-sessions)). Sessions themselves are not shared, so **run one process** unless
your gateway can send a tab's requests to the process that holds its session.

The shell keeps the stream's session id out of the URL, so it is not in your access logs, a proxy's
logs or the browser history. It sets a cookie `indah_sid_<key>` (one per tab, `Path=` the stream
route, `SameSite=Strict`, `Secure` on https, refreshed while the page is open) and opens
`api/stream?k=<key>`. A request for another person's token is still `403`: the cookie holds the same
signed token, checked against the current principal. Events and uploads carry the id in their JSON
body, which is not logged. The old `?sid=<id>` still works for one more release, except on an app
that sets `limits` or `security_headers`, which answers `400` to it; pass
`create_app(allow_sid_in_url=True)` to accept it there too (a shell cached from before this change
needs it), or `False` to refuse it everywhere. When the page is framed by another site (a Colab or
Jupyter output) or the browser blocks the cookie, the stream is refused before it opens and the shell
falls back to `?sid=`, so a hardened app that is framed needs `allow_sid_in_url=True`. File URLs (`api/file/<sid>/<token>`) still carry the
id in their path.

An event for a session the process does not hold is refused: `409` with
`{"ok": false, "error": "unknown_session"}`, and nothing is created, because the stream is what makes
a session. The shell then opens its stream again for a fresh page and shows "Reconnected. Your last
action was not applied, please try it again." (once, and at most one recovery every few seconds).
Earlier versions built a new, empty session for that request and answered `200`, so a click
did nothing. Restarts and evictions now look the same way to the user: one toast and a fresh page.

That makes a misrouted click visible, not fixed. With two processes and no stickiness, a tab whose
clicks land on the wrong process keeps reconnecting and losing its state, so **run one process**
unless your gateway can pin a tab.

What can pin a tab depends on what the browser sends on every request. indah finds a session by the
`sid` in a cookie the shell sets for the stream and in the JSON body of each event, not by a header
you can route on, so a gateway that would have to *read* the `sid` (Fly's replay cache, a hash on a
header you do not send) has nothing to key on. A gateway that **sets its own cookie** on the first page load does not need the
`sid`: the browser sends that cookie on the stream and on every event, and the gateway keeps routing
to the same process. That works today on an ingress such as Traefik: on two replicas, 20 of 20 events
stayed on the stream's pod with the cookie and 10 of 20 without it (see [Run on
Kubernetes](deploy-k8s.md)). Fly Proxy has no such cookie. Measured on Fly (IND-171): a client that
sends the request header `fly-force-instance-id: <machine id>` is pinned to that machine. indah's
own shell can send it: see [Several Fly machines](hosting-scale.md#several-fly-machines).

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
