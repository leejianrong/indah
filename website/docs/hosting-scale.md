# Run several replicas

Session routing, rolling deploys, restorable sessions and Redis for an app that runs more than one process. For platform recipes see [Run on Fly](deploy-fly.md) and [Run on Kubernetes](deploy-k8s.md).

## Several Fly machines

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
[Sessions and tokens](hosting-identity.md#sessions-and-tokens).

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
- **Expiry** is Redis's own: each write sets the value's lifetime (24 hours by default, set per value with `ttl=`).
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
