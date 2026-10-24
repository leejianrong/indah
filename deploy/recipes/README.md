# Deploy recipes

Working configuration for running an indah app on Fly and on Kubernetes (k3s first). The guides on
the docs site explain every setting; this directory holds the files.

| Path | What |
|------|------|
| `app/` | A small example app and the Dockerfile both recipes use. Replace `app.py` with yours. |
| `build-image.sh` | Build that image with the indah in this checkout (for a release not on PyPI yet). |
| `fly/` | `fly.toml` (one machine, `/ready` check, SIGTERM) and `deploy.sh`. |
| `k8s/base/` | Deployment, Service, ConfigMap, PodDisruptionBudget, Namespace. |
| `k8s/overlays/traefik/` | The Service annotations for a sticky cookie on Traefik (k3s's default ingress). |
| `k8s/overlays/ingress-nginx/` | Cookie affinity annotations for ingress-nginx (retired upstream, not verified). |
| `k8s/overlays/plain/` | Any ingress, no affinity: one replica. |
| `k8s/verify-k3d.sh` | Re-runs every check below on a throwaway k3d cluster. |

These recipes use `/ready`, the `INDAH_*` settings, the node header, the `trusted_proxies` presets
and the deploy doctor. Those arrived after indah 0.7.0, so install the next release, or build from
a checkout with `build-image.sh` (Fly: `INDAH_FROM_CHECKOUT=1 fly/deploy.sh`).

## What was verified, and what was not

Verified (2026-10-24, indah built from this checkout, version 0.7.0 plus unreleased changes):

- **k3s v1.35.5 with Traefik 3.6.13, in k3d**, `k8s/verify-k3d.sh`, two replicas:
  - the Traefik overlay sets the `indah-affinity` cookie, and a browser-like client had **20 of 20**
    events answered by its stream's pod and 20 of 20 patches arrive;
  - the plain overlay (no cookie) had **10 of 20** events reach the tab: the other 10 got HTTP 409
    (the loud failure for an unknown session);
  - the deploy doctor behind Traefik, and that Traefik drops a client-sent `X-Forwarded-For`;
  - a rolling restart sends an open tab `reconnect` after the 5 s `preStop` sleep.
- **Fly**, a throwaway app (`indah-recipe-test`, since destroyed), one machine in `sin`: `fly.toml` is
  accepted, the `/ready` check passes, `X-Indah-Node` carries the machine id, the doctor answers
  404 without its token, the `fly` preset resolved the app's own IPs and the doctor reported the real
  client address, and `fly deploy` and `fly machine restart --signal SIGTERM` both reached open tabs
  as a `reconnect`.

Not verified:

- ingress-nginx (the project was retired upstream in March 2026), a Traefik `IngressRoute`, and the
  Gateway API: the manifests follow their documentation.
- The real client address on a real k3s: k3d's Docker networking hides it (Traefik saw `10.42.0.1`),
  so `externalTrafficPolicy: Local` was not tested. Check it with the deploy doctor on your cluster.
- Fly with two machines (see the sticky-session measurements in `docs/spikes/proxy-and-sticky.md`),
  IPv6 clients, and a Cloudflare Worker in front.
