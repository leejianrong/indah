# Multi-replica e2e fixture (IND-211)

Three indah replicas, a Redis and two balancers (plain spray on `:8081`, simulated Fly on `:8082`) in Docker
Compose. A test fixture, not a deployment. `make test-multireplica` builds it, runs
`tests/e2e/test_multireplica.py` and tears it down. The scenarios, timings and the pending real-Fly runbook are
in [`docs/spikes/multi-replica-e2e.md`](../../docs/spikes/multi-replica-e2e.md).

To poke at it by hand: `docker compose -f deploy/multireplica/compose.yml up -d --build --wait`, then
`docker compose -f deploy/multireplica/compose.yml port balancer 8082` for the URL.
