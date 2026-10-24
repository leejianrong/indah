# ADR-0043: Running more than one replica

- Status: **Proposed** (IND-207; some decisions recorded 2026-10-24, see "Decisions so far"; the 0.9.0 build
  cards start only after it is accepted)
- Date: 2026-10-24
- Deciders: Jian (owner)
- Builds on: ADR-0010 (the session-store seam), ADR-0002 (SSE and POST, resume, epochs), ADR-0026 (hub,
  `Topic`, `Stream`), ADR-0033 (secure sessions and signed ids), ADR-0035 and ADR-0036 (authz, ephemeral
  props), ADR-0037 (per-process limits), ADR-0042 (extras and size), IND-199 (loud unknown session),
  IND-201 (drain)
- Evidence: `docs/spikes/proxy-and-sticky.md` (IND-170, IND-171), the 2026-10-24 explainer

## Decisions so far (2026-10-24, owner)

| Question | State | What it means for the build |
|----------|-------|-----------------------------|
| Q2 Is losing live handler state when an owner pod dies acceptable? | **Accepted** | Tier B restore softens it; no attempt is made to re-run a session's work elsewhere. |
| Q5 The cluster secret | **Decided: require it explicitly** | `INDAH_CLUSTER_SECRET` (or the matching `create_app` argument) is required for the route hint and the k8s forwarder. It is never derived from `secret=`, so one secret never does two jobs. Without it the hint and `/_indah/forward` stay off. |
| Q6 A hint-aware shell as a requirement for Tier C | **Recommended, leaning accepted** | Only indah's own shell is supported as a routing client; a third-party wire client still works on one pod or behind Tier A. Build the Fly half (IND-197, the `fly-force-instance-id` hint). Keep the k8s forwarder (IND-209) deferred unless the owner's ingress cannot do cookie affinity. |
| Q1 What fronts the owner's k3s | **Open** | The owner is checking: Traefik or ingress-nginx talking to the pods (cookie affinity works, Tier C on k8s is unneeded), or a Cloudflare Tunnel straight to a Service (no affinity, IND-209 is needed). |
| Q3 First state store | **Recommended: Redis**, plus a new option to evaluate | Redis is the first networked adapter. A browser-held option is added to the alternatives (see Backends); the `StateStore` interface must admit a client-held implementation. |
| Topic and Stream across replicas | **Open** | Recommendation: document "run the producer in every replica" now; decide a pub/sub adapter later in IND-216. |

## Context

The owner wants to run several indah replicas soon, on Fly and on their own k3s/k8s. What the code
and the probe measurements say today:

- **A tab's session is a graph of closures in one process.** Signals, computeds, handlers, the
  `Hub` and its SSE queues, `ctx.on_close` callbacks and background tasks cannot be serialised or
  shared (ADR-0010 always said the seam would carry "id in, handle out", and
  `docs/SEMULA-REQUESTS-PLAN.md` H4 sized an external store at about 10 points for exactly this
  reason).
- **The stream makes the session.** `GET api/stream?sid=...` builds the session on the replica that
  accepts it; that replica is the **owner**. Every later `POST api/event` and `POST api/upload` must
  reach the same replica, because its handler runs on that replica's signals and its patch goes to
  that replica's hub (`_event` in `app.py`).
- **Without routing, the failure was silent** (3 of 20 and 5 of 20 events reached the tab on two Fly
  machines). IND-199 made it loud: an event for an id the process does not hold is `409
  unknown_session` and the shell re-opens the stream. That is correct but it is not multi-replica
  support: most clicks would fail.
- **Routing facts.** The `sid` travels in the stream URL and the JSON body, never in a header or
  cookie, so no gateway can pin on it. Kubernetes ingresses (Traefik, ingress-nginx) can set their own
  affinity cookie, which the browser then sends on the stream and every POST, with no indah change. Fly
  Proxy has no cookie affinity; it pins only on a **client-sent** header (`fly-force-instance-id`,
  measured 12 of 12) and offers `fly-replay` as a response header (documented, request body up to 1 MB).
- **The edge is slow, the cluster is not.** A per-event call to an outside service costs 100 ms or more
  at the edge (the gateway probe in `docs/SEMULA-REQUESTS-PLAN.md`); a hop inside a cluster or a Fly
  private network is about 1 ms. Anything on the hot path must stay in process or one local hop.
- **The shell already sends one thing per event** (`fetch`), and the server already tells the shell
  things at stream open (`init`, `chrome`, `reconnect`). Teaching the server to hand the shell a
  routing hint is a small, additive step.

## Goals and non-goals

Goals, in the owner's order of need:

1. A deployment with N replicas keeps every tab working: clicks reach the owner.
2. A rollout, restart or scale-down loses at most a tab's **small state**, and the tab recovers by
   itself (reconnect, restore, one toast).
3. The path is available without running another service when the platform can already route.
4. Nothing changes for notebooks and single-process apps, and the base install stays stdlib plus its
   four direct dependencies (ADR-0042).

Non-goals:

- **Stateless pods.** Sessions stay in one process. We do not serialise closures, and we do not move a
  live session between replicas.
- **Surviving the owner dying mid-session without loss.** Running handlers, open file handles, a
  streaming LLM answer and unsaved signals are gone. What survives is only what the app persisted
  (Tier B). The user sees one toast and a restored page.
- **Exactly-once events.** An event forwarded to a dead owner fails loudly and is not retried
  (events are not idempotent).
- **Running or bundling Redis.** Any shared service is optional, external and provided by the user.

## Decision

Three tiers, each useful alone, built in this order of value for the cost:

| Tier | What it gives | indah change | Needs another service |
|------|---------------|--------------|-----------------------|
| **A. Affinity at the gateway** | all of a tab's requests reach its owner | none (recipes and docs, IND-206) | no |
| **B. Restorable sessions** | a rebuilt session starts from small persisted state | `ctx.persist`, a `StateStore` | only to share state across replicas |
| **C. Route hint and forwarding** | any replica's front door works, and events still reach the owner | a signed hint in `init`, a header on events, a forwarder | no |

**Recommendation.** Do A now (it is documentation and manifests), B and the Fly half of C next, and the
k8s forwarder of C only if the owner's k3s cannot do cookie affinity. Redis enters as the **state
store** (and later shared rate limits), **not as the router**. The registry-plus-bus design the card
sketched is the heavier way to reach C; the section "A cheaper design" below explains why a signed hint
replaces it.

### Tier A: affinity at the gateway

The ingress sets an affinity cookie on the response that loads the page. The browser sends it on the
stream (`EventSource`, same origin) and on every POST, so the stream and its events land on one pod.
Traefik: the `traefik.ingress.kubernetes.io/service.sticky.cookie` Service annotation. ingress-nginx:
`nginx.ingress.kubernetes.io/affinity: cookie`. (Both from their documentation, untested here; IND-206
runs them on the owner's k3s and records what was measured.) It is best effort: a pod restart, a
rollout or a scale-in still ends the owner's sessions, which Tier B makes survivable. Affinity does not
exist on Fly, and it does not exist where a proxy that balances per connection sits in front of the pods
(a Cloudflare Tunnel pointing at a ClusterIP Service, for example).

### Tier B: restorable sessions

**API.** `ctx.persist(name, signal, *, ttl=None, max_bytes=None)` registers a signal for persistence and
restores it. In the session factory:

```python
def build(ctx):
    tab = Signal("overview")
    filters = Signal({})
    ctx.persist("tab", tab)  # restores the saved value if there is one, then saves on change
    ctx.persist("filters", filters)
    ...
```

- `persist` reads the store once, synchronously from the factory's point of view (the async factory path
  of IND-153 awaits it), sets the signal to the saved value if one exists, then subscribes and writes
  on change, coalesced (default 250 ms) so typing does not hammer the store.
- **Key**: `(namespace, principal id or "", sid, name)`. The `sid` is a stable per-tab key: the shell
  keeps it in `sessionStorage`, so it survives a reload (secure apps keep their signed token the same
  way, `resume`, ADR-0033). A tab that restarts on another replica presents the same `sid`, so it finds
  its state. A new tab has a new `sid` and starts fresh, which is the right behaviour.
- **Values**: JSON only (str, int, float, bool, None, list, dict), rejected otherwise with a clear
  error at `persist` or at first write. Default cap 16 KB per value and 128 KB per session; over the
  cap, the write is skipped with one warning.
- **Never persisted**: ephemeral props (ADR-0036: the prop is not a signal the app owns), anything the
  app did not register, `Secret`-type values. `persist` refuses a signal bound to an ephemeral prop.
  The audit hook and the doctor page never print persisted values.
- **Ownership**: the principal id is part of the key and is checked again on read, so another user who
  somehow presents the same `sid` gets nothing. `Policy` and `guard` are unaffected: restoring a value
  does not run a handler, and components still obey `ctx.only` at tree-build time.
- **Restore ordering**: values are applied inside the factory, before the first snapshot, so the first
  `init` already shows them. An async store read is bounded by the factory timeout (IND-153); on a
  timeout the page shows the skeleton and the restored values arrive with the real tree.
- **Versioning**: each saved value carries `v` (an optional `ctx.persist(..., version=2)`); a value
  whose version differs is ignored, so a deploy that changes a signal's shape does not feed old data to
  new code. A type check (`validate=` callable) is optional.
- **TTL**: default 24 hours from the last write, renewed by writes. The sweep is the store's job
  (SQLite: delete on open and on write; Redis: native `EXPIRE`).

**`StateStore` interface** (stdlib types, sync and async variants in one protocol so the in-memory and
SQLite stores stay simple):

```python
class StateStore(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl: float | None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def delete_prefix(self, prefix: str) -> None: ...  # a user's or a tab's whole state
    async def close(self) -> None: ...
```

Implementations: **memory** (default; process-local, so it is exactly today's behaviour), **SQLite**
(stdlib, in the base install; one file; right for a single replica that restarts, or replicas sharing a
ReadWriteMany volume, which we do not recommend because SQLite locking over network filesystems is
unreliable), **Redis** (`indah[redis]`, the way to share state across replicas). Postgres follows the
same interface later if asked.

### Tier C: route hint and forwarding

**Idea.** The owner is wherever the tab's **stream** is open. The server tells the tab where that is.
The tab sends the answer back with every event. Whoever receives an event with a hint that is not
itself sends it on. No registry, no lease, no bus.

1. On stream open the owner adds an optional `route` field to `init` (and to every later `init` after a
   reconnect): `{"route": {"hint": "<signed hint>"}}`. The hint names the owner and is unforgeable.
2. The shell stores it in memory and sends it on every `POST api/event` and `POST api/upload` (header
   `X-Indah-Route`), and file URLs minted by the owner carry it (`api/file/<sid>/<token>?r=<hint>`).
3. A replica that receives an event whose hint names someone else forwards it to that replica; one
   whose hint names itself, or that has no hint, handles it locally as today.

Two transports, because the platforms differ:

| Platform | Transport | Why |
|----------|-----------|-----|
| **Fly** | the shell also sends `fly-force-instance-id: <machine id>` (taken from the hint's machine field); the Fly Proxy routes the request to that machine. A non-existent id is `400`, which the shell treats as "session lost" | zero forwarding code in indah, no body-size limit (the header routes, it does not replay), uploads work, no private networking needed, measured 12 of 12 |
| **k8s without affinity** | the receiving replica forwards the request over HTTP to the owner pod's address inside the hint | needs pod-to-pod reachability, which Kubernetes gives by default |

On Fly the hint is not security relevant (a client choosing its own machine can only get a `409` from the
wrong one), so it is a plain machine id. On k8s the hint **is** a capability that tells a replica which
address to connect to, so it must be signed or the endpoint is an SSRF primitive.

**Hint format (k8s forwarding).** `base64url(address "|" port "|" issued_at) "." base64url(HMAC-SHA256(
cluster_key, "indah-route-v1" | payload))`, where `cluster_key` comes from the explicitly configured
`INDAH_CLUSTER_SECRET` (never derived from `create_app(secret=)`, owner decision 2026-10-24), the same on every replica. A receiver
verifies the MAC and that `issued_at` is within 24 hours, that the address is a private or link-local
address (never a public one: a defence in depth against a leaked key), and that the port is the app's
own. A bad hint is a plain local attempt, which becomes the loud `409` if this replica does not hold the
session: it never makes an outgoing connection. The owner never puts its public address in a hint.

**Forwarding envelope (k8s).** The receiving replica B has already done everything the front door does
today: origin guard, content-type and size caps, JSON validation, **authentication** (the principal for
this request, fresh) and the **rate limit** (per address, ADR-0037). It then sends the original
`POST api/event` body to `http://<owner>/_indah/forward` with:

- headers `X-Indah-Forward-Sig` = HMAC-SHA256(cluster_key, "indah-forward-v1" | timestamp | node of B |
  sha256(body) | canonical principal blob), `X-Indah-Forward-Ts`, `X-Indah-Forward-Principal` (a JSON
  blob of `id`, `roles`, `workspace`, `claims`, `expires_at`, base64url);
- the original body unchanged (events) or streamed through unchanged (uploads, size-capped by the same
  `max_upload_mb`);
- a timeout (default 2 s, `INDAH_FORWARD_TIMEOUT`) and **no retry**.

The owner verifies the signature, that the timestamp is within 30 s (replay window), that the principal
blob has not expired, and that it holds the session (else `409 unknown_session`); then it runs the same
code as a local event with the carried principal as the request principal: `authz_scope`, `guard`, the
audit hook (the audit record gains `forwarded_by` with B's node id), `session.dispatch`,
`session.spawn`, publish to **its own** hub. The response (`{"ok": true}`, `403`, `400`, `409`) goes back
to B, and B returns it to the browser unchanged. The owner does not rate-limit forwarded requests (B
already did; double counting would halve the budget).

Nothing about the session moves. The patch is published to the owner's hub and reaches the tab over the
stream the tab already has open. That is the point: **no state sharing and no closure serialisation**.

**Stale and missing owners.**

- The owner died or was replaced: the connection fails, times out or the new process answers `409
  unknown_session`. B returns `409` with `error: "owner_unreachable"` (or the owner's own
  `unknown_session`), the shell re-opens the stream (a new owner and a new hint, Tier B restores the
  state) and shows the one toast IND-199 added. No registry TTL has to expire first, so recovery is as
  fast as the failure is detected.
- A **half-open old stream**: the tab's connection dropped but the old owner has not noticed. The tab
  reconnects to replica R, which accepts the stream and becomes the owner (the stream decides; there
  is no lease to take). The old owner A still holds the stale session until its stream ends or idle
  eviction. An event that carries A's old hint reaches A, which refuses it with `409` when its hub has no
  live subscriber (a check that costs nothing: `hub.subscriber_count == 0`), so it never silently
  eats a click. The window is the time between the drop and the next `init`, which is the reconnect
  time.
- **Two tabs, one sid** (a duplicated browser tab that copies `sessionStorage`): out of scope; the
  last stream wins, as today.

**Everything else that touches a replica boundary**:

| Request | Decision | Why |
|---------|----------|-----|
| `GET api/stream` landing anywhere | accepted: the receiving replica becomes the owner | the stream decides; a redirect or a replay would need the registry we are avoiding, and the session is built from the factory plus Tier B restore anyway |
| `POST api/event` | route by hint (Fly header, or forward) | the hot path |
| `POST api/upload` | Fly: header routes it (no 1 MB limit). k8s: forwarded, streamed, with the upload cap | `fly-replay` would cap uploads at 1 MB, so Fly uses the header, not a replay |
| `GET api/file/<sid>/<token>` | the URL carries the hint. Fly: a browser navigation cannot set a header, so a replica that receives a misrouted GET replies `fly-replay: instance=<owner id>` (a GET has no body, so the 1 MB replay limit does not apply). k8s: forwarded | tokens live in the owner's `Session` file store |
| `Last-Event-Id` resume landing on a non-owner | a fresh stream: `Hub.epoch` differs, so the existing resume rule sends a full `init` (ADR-0002, IND-85) | resume is an optimisation; a full snapshot is always correct |
| `POST api/session` (secure) | any replica (it only signs) | stateless |
| `/health`, `/ready`, `/_indah/doctor` | per replica, never forwarded | they describe the replica |
| `Topic` and `Stream` fan-out | per replica, unchanged | ADR-0026 already said cross-process fan-out is out of scope; with N replicas a producer must run in each replica or publish through its own bus (see Open questions) |

**Drain (IND-201).** A draining owner keeps answering events for sessions it holds (its tabs are still
connected until `reconnect`), so forwards to a draining owner succeed. A draining replica as a
*receiver* still forwards (it holds nothing). After a `reconnect` the new `init` carries a new hint, so
no event is aimed at the old pod for long. A pod IP reused by a new pod answers `409 unknown_session`
because it holds no such session.

**Secure sessions.** The signed session token is verified at B exactly as today (`state.signer.verify`,
the same `secret` on every replica is therefore a documented requirement; startup warns when a secure
app runs more than one replica without a configured secret, if the doctor can tell). The forwarded
principal is B's fresh authentication, so a role revoked a second ago still fails the next event at the
owner, as for a local event. The owner never trusts a hint or a forwarded principal without the cluster
MAC.

### A cheaper design than the registry plus bus

The card sketched a **session owner registry** (`sid -> replica`, TTL, renewed, claimed on stream open)
plus **forwarding over a shared bus** (Redis pub/sub). It works, and it needs no cooperation from the
browser, but it costs more and is more fragile than a hint:

| | Registry plus bus (the card) | Signed hint plus direct forward (this ADR) |
|---|------------------------------|--------------------------------------------|
| Extra service | **required** (Redis or equivalent) | none |
| Hot-path cost | a registry read on every misrouted event, bus round trip | none when the hint names the receiver; one in-cluster hop otherwise |
| Failure detection | wait for the lease TTL, or false positives on renewal lag | immediate: connect error, timeout or `409` |
| Split brain | needs fencing tokens (two replicas claim one sid) | none: the stream decides, a stale owner refuses with no live subscriber |
| Browser change | none | the shell stores and sends a hint (small, additive) |
| Works for a client that cannot send a header | yes | no (third-party clients fall back to local handling, which is Tier A or a single process) |
| New attack surface | the bus (auth, tenant isolation, replay) | the forward endpoint, protected by an HMAC with a replay window |
| Platform-native transport | none | Fly header routes with zero code |

The deciding point is that Redis would be on the path of **every** deployment that wants more than one
replica, to solve a problem (find the owner) whose answer the browser already carries after one `init`.
A registry stays available as an optional backend if a client appears that cannot send the hint; it is
not part of the first build.

## Backends

| Option | Registry | Bus | State store | Extra service | Fit |
|--------|----------|-----|-------------|---------------|-----|
| **Signed hint plus direct HTTP** (this ADR) | not needed | not needed | no | no | routing on k8s; the Fly header handles Fly |
| **Redis** (`indah[redis]`) | yes (keys with TTL) | yes (pub/sub, streams) | yes | yes, user-provided (a Deployment, Upstash, Fly) | **state store** and shared rate limits; the registry mode if ever needed |
| Postgres LISTEN/NOTIFY | table with TTL | NOTIFY, 8 KB payload cap | yes | yes (a database most apps already have) | good second state store; poor as a hot-path bus |
| NATS | KV bucket | request/reply fits forwarding well | KV | yes (a new system) | strong technically; a new service for one feature |
| k8s Lease objects | one Lease per session | no | no | none, but RBAC and API-server load | per-session leases are too heavy |
| Direct pod-to-pod HTTP | needs a registry or a hint | the HTTP call is the bus | no | no | this is the transport under the signed hint |
| **Browser-held state** (new, 2026-10-24) | not needed | not needed | yes, in the tab (`localStorage` or `sessionStorage`) | no | a state store with no service; evaluate in the IND-208 build |

**Why Redis first for the store.** Restoring after a rollout or a node move needs state that outlives
the pod and is readable from any other pod. The owner's k3s can run Redis in minutes; Fly has Upstash
and a Redis app. SQLite covers a single replica that restarts. Redis also provides the TTLs and the
atomic counters that shared rate limits need (IND-213). indah never starts, bundles or manages it:
`INDAH_REDIS_URL` points at the user's instance, TLS and auth are the URL's. What a deployment with **no**
extra service gets: Tier A or the Tier C hint for routing, and, after the owner dies, a reload with
default state plus one toast, never wrong data.

**Browser-held state (option added 2026-10-24).** The shell keeps the small persisted values (what
`ctx.persist` would save) in the browser and sends them back in `init` or on reconnect, so a rebuilt session
starts from them with no service at all.

- Pros: no extra service on Fly or k8s; survives the loss of any pod, a rollout and a node move; it comes with
  the tab, so there is nothing to expire server side and no per-tab server memory.
- Cons: the client is untrusted, so the app must validate what comes back (the same rule as any input), with
  a size cap; a per-session HMAC key lets indah detect tampering, but it gives no secrecy (the browser can
  read its own values); the values are per browser, not per person (a second device or a cleared browser
  starts blank); stored values must not include secrets or anything the user must not be able to see;
  ephemeral props (ADR-0036) are never persisted, here or elsewhere; it needs the hint-aware shell
  (the same shell requirement as Tier C) and a shell change.
- Verdict: **evaluate in the IND-208 build.** The `StateStore` interface must admit a client-held
  implementation (a store that returns values the request carried, plus the signature check). Redis remains
  the recommended first networked adapter for state that must outlive the browser.

## Failure modes

The rule everywhere: **fall back to local behaviour, warn once, never hold the event path longer than a
short timeout**.

| Failure | What happens | What the user sees |
|---------|--------------|--------------------|
| State store down or slow at `persist` read | factory continues with defaults after the factory timeout; warning logged once per minute | first paint without saved state |
| State store down at write | writes are dropped and retried on the next change, bounded queue, warning | nothing (state not saved) |
| Owner unreachable (forward fails, 2 s) | `409 owner_unreachable`, no retry | one toast and a re-opened stream, restored state if the store is up |
| Owner restarted (new process on the same address) | `409 unknown_session` | same |
| Receiver cannot verify the hint | handled locally: `409` if it holds no such session | same |
| Network partition between replicas | forwards time out as above; tabs on a healthy path keep working | affected tabs recover when the partition heals or after one toast |
| Replica restarts | its tabs reconnect (the stream drops, `EventSource` retries, or `reconnect` after a drain) | reconnect, restore |
| Hint clock skew | `issued_at` window is 24 h, forward timestamp window 30 s: document NTP; a skewed replica refuses forwards loudly in the doctor page | `409`, then recovery |
| Cluster secret differs between replicas | every forward fails the MAC check; the doctor page flags it | `409` on every misrouted event; fix the config |

## Security

- **The forward endpoint** is reachable only with a valid HMAC over a fresh timestamp, the body hash and
  the principal blob; it never serves browsers (the origin guard does not apply, it requires the
  signature instead) and is not in the public route table when `INDAH_PEERS` and a cluster secret are
  unset (it is not mounted at all). Network policy should also restrict it to the replicas.
- **No SSRF**: a hint carries an address only inside a MAC, the address must be private, the port the
  app's own, and a forward is one HTTP request with a timeout and no redirects followed.
- **Replay**: the 30 s timestamp window plus one-shot body hash caching per replica (a small LRU of
  recent signatures) makes a captured forward useless after a minute, and a repeat inside the window is
  refused.
- **Tenant isolation**: the principal is carried and re-checked; `workspace` is part of the signed blob
  and of the session key (ADR-0033). A forged principal needs the cluster key.
- **Redis**: TLS and ACL users with a key-prefix restriction (`~indah:*`), documented; values are
  application state, so treat Redis as sensitive as the app's own database. Keys include the principal
  id; values are JSON the app chose to persist (never ephemeral or secret).
- **The doctor page** (IND-205) may show: the replica id, the configured peer discovery and the number of
  peers resolved, forward success and failure counts, whether the cluster secret is set and matches (a
  fingerprint, never the secret), the state store kind and its health. It never shows hints, keys,
  values or addresses beyond what a deployer already knows.

## Rate limits and metrics (hooks, built later)

- **Per-address rate limits** (ADR-0037) stay at the **receiving** replica, where the visitor connects, so
  N replicas multiply them (the 0.4.0 known limitation). A shared counter store (IND-213) is a small
  interface (`take(key, rate) -> allowed`) with a local default and a Redis implementation that falls back
  to local on error; it costs a Redis round trip per limited request, so it is opt-in
  (`INDAH_LIMITS_SHARED=redis`) and the doctor page says so.
- **Metrics** (IND-212): counters `indah_forwards_total{result}`, `indah_route_hint_misses_total`,
  `indah_unknown_session_total`, `indah_state_store_errors_total{op}`, and gauges for sessions, streams,
  drain. The HPA recommendation is to scale on open streams per pod.

## Wire protocol, configuration and size

Everything below is additive and `protocol_version` stays 1 (ADR-0005 amendment); an older shell ignores
`route` and sends no hint, which is the same as Tier A or a single process.

- `init` gains optional `route: {hint, node}`. `POST api/event` and `POST api/upload` accept the optional
  header `X-Indah-Route`. `api/file` URLs gain an optional `r` query value. A new internal route
  `POST /_indah/forward` (only mounted with a cluster secret and peers). New `409` error names:
  `owner_unreachable` (beside the existing `unknown_session`). `docs/protocol.md` documents each when it
  ships.
- Environment variables (IND-202 style; an explicit argument always wins): `INDAH_ROUTE_HINT`
  (`auto`, `fly`, `peers`, `off`; `auto` picks `fly` when `FLY_MACHINE_ID` is set, `peers` when
  `INDAH_PEERS` is set, else `off`), `INDAH_PEERS` (a DNS name to resolve, normally a headless Service, or
  `self` for single process tests), `INDAH_PEER_PORT`, `INDAH_ADVERTISE_ADDRESS` (the pod IP from the
  Kubernetes downward API `status.podIP`, else the first private address), `INDAH_CLUSTER_SECRET`,
  `INDAH_FORWARD_TIMEOUT` (default 2 s), `INDAH_STATE_STORE` (`memory`, `sqlite:///path`, `redis://...`),
  `INDAH_REDIS_URL`, `INDAH_PERSIST_TTL`, `INDAH_PERSIST_MAX_BYTES`.
- **Size**: Tier B and C add stdlib Python only (about 600 lines estimated, no new base dependency);
  the shell grows by the hint handling (a few hundred bytes of JS, well inside the budget: the shell is
  199,839 bytes gzip against 275,000). The Redis adapter lives behind `indah[redis]`
  (`redis>=5`), imported on use, so the base install stays at 12 distributions (ADR-0042).

## Testing strategy

- **Unit**: hint signing and verification (tamper, expiry, public address refused, bad port), the
  forwarding envelope (MAC, replay window, principal blob), `StateStore` contract tests run against
  memory, SQLite and Redis with one shared suite, `ctx.persist` (restore, version mismatch, cap, ephemeral
  refused, ownership).
- **Integration**: two in-process apps sharing a cluster secret on loopback addresses: an event to the
  wrong app reaches the owner and its stream; `409` cases; secure sessions with `guard` and the audit
  hook; drain.
- **IND-211, multi-replica e2e** (a slower CI job like `studio-pyodide`): docker compose with three
  replicas, a Redis service, and **two balancers**: (1) a plain round-robin one (the hard case, forwarding
  on), (2) one that honours `fly-force-instance-id` (the Fly behaviour, simulated). Scenarios: a tab keeps
  working while its events are sprayed over every replica; a rolling restart with drain keeps tabs
  (reconnect, restore); the owner killed shows one toast and the restored state; the secret mismatch is
  flagged; and the existing `deploy/probe/sticky_check.py` reports 20 of 20. A real-Fly run on the probe
  app with three machines and the header is part of IND-211's acceptance, since the simulation is not
  Fly.
- **Real cluster**: IND-206 applies the manifests to the owner's k3s and records whether Traefik's cookie
  affinity gives 20 of 20.

## Consequences

- A deployment gets multi-replica routing with zero extra services (Fly header, Tier A cookie, or the
  signed-hint forwarder), and Redis only when the app wants state that survives a pod.
- The shell learns one new thing (a hint) and the server one new endpoint; both are off unless
  configured.
- Sessions still live in one process. An owner death costs live handler state; Tier B softens that to a
  toast and a restored page for the state the app chose to save.
- `Topic` and `Stream` producers are per replica. An app that publishes from a background task in one
  replica reaches only that replica's tabs. This is the largest remaining gap for multi-replica apps
  and is **not** solved here (see Open questions).
- IND-197 (the shell sends the Fly header), deprioritised on 2026-10-24, comes back as the first Tier C
  card, because it is the cheapest complete answer for Fly.

## Smallest useful first slice

1. **IND-206 (0.8.0)**: Tier A recipes for the owner's k3s, verified with `sticky_check.py`. No indah
   code, and it answers "multi-replica on my cluster" today.
2. **Route hint, Fly half (IND-197, revived, 5 points)**: `init.route`, the shell sends
   `fly-force-instance-id` and `X-Indah-Route`, file GET replay. Fly multi-machine works.
3. **Restorable sessions (IND-208) with memory and SQLite**, then the **Redis store** (IND-210, scope
   reduced to the store).
4. **Forwarder for k8s without affinity (IND-209, reshaped)** only if the owner's k3s needs it.

## What changes if the owner chooses less

- **Tier A only**: no indah code beyond IND-206. Fly stays one machine. Cost: nothing; limit: a pod restart
  loses sessions.
- **A and B**: add `ctx.persist`, the stores (IND-208, IND-210). Restarts and rollouts recover.
- **A, B and C-Fly**: add IND-197. Fly scales to several machines.
- **Everything**: add IND-209 (forwarder) and IND-213 (shared limits).

## Re-sized card list

| Card | Was | Now | Release |
|------|-----|-----|---------|
| IND-197 Route hint: `init.route`, shell sends the hint and the Fly header, file GET replay | 5 (deprioritised) | **5, revived, first** | 0.9.0 |
| IND-208 Restorable sessions: `ctx.persist`, `StateStore` (memory, SQLite) | 5 | 5 (adds version, TTL, caps, ownership check) | 0.9.0 |
| IND-210 Redis `StateStore` adapter (`indah[redis]`) | 3 (also registry and pub/sub) | **3, store only** (no registry, no bus) | 0.9.0 |
| IND-211 Multi-replica e2e (compose, two balancers, Fly probe run) | 3 | **5** (two balancers and a real Fly run; points are 1, 2, 3, 5, 8) | 0.9.0 |
| IND-212 `/metrics` | 2 | 2 (adds forward and hint counters) | 0.9.0 |
| IND-209 Peer forwarder for k8s without affinity (signed hint, `/_indah/forward`) | 3 (registry core) | **5, reshaped**; built only if the owner's ingress cannot do cookie affinity | after 0.9.0 |
| IND-213 Shared rate limits | 3 | 3 | after 0.9.0 |
| NEW IND-216: a `Topic` and `Stream` story for multiple replicas (decision card, see Open questions) | n/a | 2 | 0.9.0 |

0.9.0 core is IND-197, 208, 210, 211, 212 and IND-216: 5 + 5 + 3 + 5 + 2 + 2 = 22 points, plus
the two gallery cards (IND-196, IND-191, 5 points) already planned.

## Open questions for the owner

1. **What fronts your k3s?** (STILL OPEN, the owner is checking.) Traefik or ingress-nginx talking to the pods (cookie affinity works,
   IND-209 is not needed) or a Cloudflare Tunnel pointing at a Service (no affinity: IND-209 is
   needed)? This decides whether the k8s forwarder is built at all.
2. **Is losing live handler state on an owner crash acceptable?** DECIDED 2026-10-24: yes, with Tier B
   softening it. A design that survives it would need the session's work to be re-runnable from persisted
   inputs, which is a different framework.
3. **Redis as the first store adapter, or Postgres?** (Recommended: Redis; a browser-held option is also to be evaluated, see Backends.) Redis is recommended (TTLs, counters, one service for
   state and limits); Postgres is the one most apps already run. Both fit the same interface.
4. **`Topic` and `Stream` with more than one replica.** (STILL OPEN; recommendation: document producer-per-replica now, decide a pub/sub adapter in IND-216.) Background producers feed only their own replica's
   tabs. Options: document "run the producer in every replica", a `Topic` backend on Redis streams
   (reopens the bus we avoided), or leave it for a user who needs it. The 2-point decision card will
   write it up; the owner's semula use is the deciding case.
5. **The cluster secret**: DECIDED 2026-10-24: require `INDAH_CLUSTER_SECRET` explicitly; do not derive it from
   `secret=`.
6. **Is a hint-aware shell acceptable as a requirement** for Tier C, with Tier A or a single process as the
   answer for third-party clients? RECOMMENDED and leaning accepted (2026-10-24): yes; build the Fly half only.

## Appendix: the Tier C flow (k8s forwarding), one page

```
   Browser tab (sid = S)                Replica B (any)                      Replica A (owner of S)
   ---------------------                ---------------                      ----------------------
 1                                                                           GET api/stream?sid=S  <-- landed here
                                                                             factory builds session, Tier B restores
                                                                             init { ..., route: { hint: H(A) } }
   <============================ SSE stream stays open on A ===================
 2 POST api/event  X-Indah-Route: H(A)
     body { sid: S, component, event }
        --------------------------->  origin guard, caps, JSON check
                                      authenticate -> principal P
                                      rate limit (per address, here)
                                      verify H(A): MAC ok, private addr
                                      H(A) names A, not me -> forward
                                      POST http://A/_indah/forward
                                        body (unchanged)
                                        Sig = HMAC(key, ts | B | sha256(body) | P)
                                        --------------------------------->  verify Sig, ts within 30 s
                                                                             session S held? else 409
                                                                             authz_scope(P); guard; audit(forwarded_by=B)
                                                                             session.dispatch / spawn
                                                                             hub.publish(patch)  -----+
                                        <---------------------------------  { ok: true }              |
        <---------------------------  { ok: true }                                                    |
   <======================== patch arrives on the tab's stream (A's hub) <=============================+

 Failure: A gone  -> B: connect error or 2 s timeout -> 409 owner_unreachable
          shell: toast once, re-open stream (new owner R, new hint H(R), Tier B restore)

 Fly:  steps 2 and the forward are replaced by the header fly-force-instance-id: <A's machine id>,
       so the Fly Proxy delivers the POST straight to A. B never sees it.
```
