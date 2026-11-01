# Configure and operate a hosted app

Environment variables, the deploy doctor, metrics and autoscaling.

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
session notes in [Identity, sessions and sign-in](hosting-identity.md#sessions-and-tokens)). `ctx.conn.node` and `app.state.node` hold the same id with the header on or off;
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

Scale-down ends streams, and a tab reconnects to another pod (see [Rolling out without losing tabs](hosting-scale.md#rolling-out-without-losing-tabs)), so keep the
window long.
