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

## Where each topic lives

| You want to | Read |
|-------------|------|
| Know who a request is, keep a session per tab, sign out, log in with OIDC | [Identity, sessions and sign-in](hosting-identity.md) |
| Decide who may do what, or show a secret once | [Roles, permissions and secrets](hosting-access.md) |
| Run behind Cloudflare, Fly or a load balancer; limit abuse; set a CSP | [Gateways, limits and CSP](hosting-network.md) |
| Stream a camera or microphone | [Live camera and microphone](hosting-live.md) |
| Run more than one process, roll out a deploy, restore sessions | [Run several replicas](hosting-scale.md) |
| Set options from the environment, check a deploy, read metrics | [Configure and operate a hosted app](hosting-config.md) |

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
