# Multi-replica e2e (IND-211, ADR-0043)

Does indah keep working with three replicas and no affinity? The claim in ADR-0043 is tested here, not
assumed (IND-171: 3 of 20 events landed without routing). Two parts: a Docker simulation that runs in CI,
and a real run on Fly that is **pending** the owner's go-ahead.

## Docker simulation (done)

`deploy/multireplica/compose.yml`: three indah replicas (`r1` to `r3`, machine ids `n1` to `n3`), one Redis
(the `ctx.persist` state store) and one nginx with two listeners:

| Balancer | Behaviour | Stands for |
|----------|-----------|------------|
| `:8081` plain spray | every request to a random replica, no memory of the tab | no affinity at all (the hard case) |
| `:8082` simulated Fly | `fly-force-instance-id: n2` goes to `n2`; no header goes to any replica; a machine that is gone, or an id that does not exist, answers a plain `400` | Fly Proxy |

The simulation is not Fly. It encodes what the shell and ADR-0043 assume Fly does; the real run below is what
checks that assumption.

Run it: `make test-multireplica` (needs Docker, `uv sync --extra dev --extra e2e --extra redis`, and
Chromium). The tests are `tests/e2e/test_multireplica.py`, mark `multireplica`, opt-in with
`INDAH_TEST_MULTIREPLICA=1`, so they are never in `-m "unit or integration"`. CI runs them in
`.github/workflows/multireplica.yml`, which writes the timings to the job summary.

| Scenario | What the test asserts |
|----------|-----------------------|
| Spray, no hint | `sticky_check.py` on `:8081` reports NOT STICKY with `409` answers, and a stray event gets `409 unknown_session` in indah's JSON |
| Spray, with the hint | `sticky_check.py --follow-route` on `:8082`: 20 of 20 events on the stream's machine, 20 of 20 patches; the same run without the header is NOT STICKY |
| A tab through the simulated Fly | ten clicks in a real browser, every `/api/event` carries the owner's `fly-force-instance-id`, no toast |
| Rolling restart with drain | each replica gets SIGTERM, exits after its drain, comes back; the same page (never reloaded) reconnects and shows the saved count each time, then accepts a click. Run behind both balancers (behind the plain one only the reconnect and restore are asserted, as its clicks have no route) |
| Owner killed | SIGKILL on the tab's replica after the value reached Redis; the next click gets the simulated Fly `400`, the shell shows the "Reconnected" toast once, rebuilds on another replica with the saved count, and the next click works. One toast in total (counted as toasts ever inserted, since a toast fades) |
| Cluster secret | a fourth replica without `INDAH_CLUSTER_SECRET` shows route hint `off` in its doctor while the others show `fly`, and its `init` has no route, so `--follow-route` stops with a clear message |

### What the secret scenario can and cannot show

Today `INDAH_CLUSTER_SECRET` only switches the hint on; nothing is signed with it until the Kubernetes
forwarder (IND-209), and the doctor does not show a fingerprint of it. So a *missing* secret is visible, and a
*differing* one is not. The test says so in its docstring. When IND-209 lands, extend that scenario with a
replica holding a different secret and assert the doctor flags it.

### Timings and flakiness

One cold run on a WSL2 laptop (image already built, base images pulled; a first build adds about 50 s):

| Step | Seconds |
|------|---------|
| `compose up --build --wait` (image build, Redis, three replicas, balancer) | 44 |
| spray without the hint | 6 |
| `--follow-route` 20 of 20 | 11 |
| ten clicks through the simulated Fly | 1 |
| rolling restart with drain, per balancer | 19 |
| owner killed (the test, then bringing the replica back) | 12 + 11 |
| secret scenario | 6 |
| whole module | about 135 |

CI's own numbers are in each run's job summary. Measures against flakiness: every wait is an explicit
Playwright expectation or a poll with a deadline (no fixed sleeps except the 1.2 s that lets a value reach
Redis, which is its documented write delay); every test first brings all three replicas back up; the compose
service health checks gate the start; failed runs print the last 60 log lines of every container; the spray
test relies on a random split of 20 events missing the owner at least once, which fails to hold with
probability under one in a billion. The one known race window is the killed-owner scenario: the click must
land before EventSource reconnects by itself (about 3 s after the kill). It is sent right after the kill
returns, well inside that window, and has been stable in repeated local runs.

## Fly run (pending)

**Not run.** It needs three Fly machines on `indah-probe` and a secret, so it waits for the owner's go-ahead.
It never touches `indah-demos` (the gallery). The exact runbook:

```bash
# 0. Once: flyctl logged in. Everything below is on the throwaway app, in region sin.
cd deploy/probe

# 1. A cluster secret (never printed) and the probe, with the hint on.
fly apps create indah-probe 2>/dev/null || true
fly secrets set -a indah-probe --stage "INDAH_CLUSTER_SECRET=$(openssl rand -hex 24)" >/dev/null
./deploy.sh                       # builds a wheel of this checkout; one machine

# 2. Three machines that stay up (auto-stop would hide the routing).
fly scale count 3 -a indah-probe --region sin --yes
fly machine list -a indah-probe   # note the three ids
for id in $(fly machine list -a indah-probe --json | jq -r '.[].id'); do
  fly machine update "$id" -a indah-probe --autostop=off --yes
done

# 3. The check. x-probe-machine names the machine that answered.
cd ../..
uv run python deploy/probe/sticky_check.py https://indah-probe.fly.dev --new-conn            # expect NOT STICKY
uv run python deploy/probe/sticky_check.py https://indah-probe.fly.dev --follow-route        # expect 20 of 20
uv run python deploy/probe/sticky_check.py https://indah-probe.fly.dev --follow-route --new-conn   # expect 20 of 20

# 4. Rolling restart with drain: open https://indah-probe.fly.dev/ in a browser, then
cd deploy/probe && ./deploy.sh && cd ../..    # a rolling deploy; watch the tab reconnect, not reload
fly logs -a indah-probe                       # look for the drain and "reconnect" lines

# 5. Owner killed: note the "built by machine" id on the page, then
fly machine stop <that id> -a indah-probe
#    click "Send an event" in the open tab; expect one "Reconnected" toast, then a working tab.
#    (The probe has no Redis, so there is no restored count to check. See "Restore on Fly" below.)

# 6. Tear down.
fly machine start <that id> -a indah-probe
deploy/probe/teardown.sh
```

What to record: the three `sticky_check.py` outputs, the Fly Proxy answer for a stopped machine
(status and body: the shell treats a `400` that is not indah's JSON as "machine gone", and this is the
unverified assumption), whether the stream's `X-Probe-Machine` stays the same across `--new-conn`, and the
time from `fly machine stop` to a working tab.

### Restore on Fly

The probe app does not use a state store. To check restore on real Fly too, run `deploy/multireplica/app.py`
as a second throwaway app with Upstash Redis (`fly redis create`, then
`fly secrets set INDAH_STATE_STORE=redis INDAH_REDIS_URL=rediss://...` and the cluster secret) and repeat
steps 4 and 5 there, counting clicks before and after. This costs an Upstash instance for the run, which is
also why it waits for the owner.

### Results

Run on 2026-10-25, three `shared-cpu-1x` machines in `sin` on a throwaway `indah-probe` (since destroyed),
the hint on through `INDAH_CLUSTER_SECRET`, `--autostop=off`. Steps 1 to 3 and the Fly Proxy answers of step 5
were run. The browser steps (the rolling deploy with a tab open, the "Reconnected" toast) and the Upstash
restore check were not run on Fly; the compose fixture covers them against a simulated Fly.

| Check | Result |
|-------|--------|
| `sticky_check.py --new-conn` (no route) | NOT STICKY: events answered by all three machines, 2 of 20 patches reached the tab, 18 returned `409` |
| `--follow-route` | STICKY: 20 of 20 events and 20 of 20 patches, every POST answered by the stream's machine |
| `--follow-route --new-conn` | STICKY: 20 of 20 and 20 of 20, on a different machine from the first run |
| `init.route` | `{hint: <machine id>, node: <machine id>, transport: "fly"}`, the hint equal to the machine that built the session |
| Header for an id that does not exist | `400`, empty body, `server: Fly/...` (this confirms the shell's assumption: a `400` that is not indah's JSON means "machine gone") |
| Header for a stopped machine | Fly Proxy starts it (autostart on) and routes the request there: about 2.7 s cold, then indah answers `409 unknown_session` as JSON, so the shell reopens the stream and the tab recovers |

Notes:

- The stopped-machine case is gentler than the simulation: with autostart on, a gone owner does not give a
  `400`; the replacement is woken and answers `409`. The `400` path is for a machine that was destroyed (a
  scale-down or a deploy that replaced it).
- Not measured: the time from stopping the owner to a working tab in a browser.
