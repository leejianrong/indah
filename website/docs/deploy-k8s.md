# Run on Kubernetes

A kustomize base for an indah app, with one overlay per ingress, written for k3s first. The files are in
`deploy/recipes/k8s/` in the repository.

## The pieces

| File | What it sets |
|------|--------------|
| `base/deployment.yaml` | readiness on `/ready`, liveness on `/health`, a 5 s `preStop`, a 30 s grace period, a non-root user, `INDAH_NODE` from the pod name |
| `base/configmap.yaml` | `INDAH_TRUSTED_PROXIES`, `INDAH_NODE_HEADER`, `INDAH_DRAIN_SECONDS` |
| `base/service.yaml`, `base/pdb.yaml` | a ClusterIP Service and a PodDisruptionBudget (`maxUnavailable: 1`) |
| `overlays/traefik/` | the sticky cookie, for k3s's default ingress |
| `overlays/ingress-nginx/` | cookie affinity for ingress-nginx |
| `overlays/plain/` | any ingress, no affinity |

## Deploy on k3s

```bash
deploy/recipes/build-image.sh my-registry/indah-app:1      # or your own image; see the Dockerfile
# edit overlays/traefik/ingress.yaml (your host) and base/kustomization.yaml (image, replicas)
kubectl apply -k deploy/recipes/k8s/overlays/traefik
kubectl -n indah create secret generic indah-secrets \
  --from-literal=INDAH_DOCTOR_TOKEN="$(openssl rand -hex 24)"
kubectl -n indah rollout restart deploy/indah-app          # pick the secret up
```

The Secret is not in the manifests, so it never lands in git. `INDAH_SECRET` (for `secure=True`) goes in
the same Secret.

## Several replicas need affinity

A tab's state lives in one pod, and its stream and its events must reach that pod. Without help, a Service
sends each request to any pod: with two replicas and no affinity, only 10 of 20 test clicks took effect. The
other 10 reached a pod that did not hold the tab, and indah answered them with HTTP 409 so the tab reconnects. The fix at the ingress is a **cookie**: the
ingress sets it on the first response, the browser sends it back on the stream and on every event, and the
ingress keeps sending that browser to the same pod.

On Traefik (k3s's default), the cookie is configured by annotations **on the Service**:

```yaml
metadata:
  annotations:
    traefik.ingress.kubernetes.io/service.sticky.cookie: "true"
    traefik.ingress.kubernetes.io/service.sticky.cookie.name: "indah-affinity"
    traefik.ingress.kubernetes.io/service.sticky.cookie.httponly: "true"
    traefik.ingress.kubernetes.io/service.sticky.cookie.samesite: "lax"
    traefik.ingress.kubernetes.io/service.sticky.cookie.maxage: "86400"
    # over HTTPS also: traefik.ingress.kubernetes.io/service.sticky.cookie.secure: "true"
```

(The Traefik documentation lists these under the Kubernetes Ingress provider, for Traefik v3.7. k3s v1.35
ships Traefik 3.6, where they were tested.) With a Traefik `IngressRoute` instead of an Ingress, the cookie
is `sticky.cookie` on the service entry; that form was not tested here.

Affinity is **best effort**. A pod restart, a rollout or a scale-down ends the sessions that were on it:
the tab reconnects to another pod and starts a fresh session there, so keep state you care about in your own
database. indah drains first (below), which makes a rollout a reconnect, not an error.

!!! warning "ingress-nginx is retired"
    The Kubernetes project [retired ingress-nginx in March 2026](https://www.kubernetes.io/blog/2026/01/29/ingress-nginx-statement/),
    so it gets no more fixes. The overlay is here for clusters that still run it; it follows the
    [ingress-nginx cookie affinity documentation](https://kubernetes.github.io/ingress-nginx/examples/affinity/cookie/)
    (`affinity: cookie`, `affinity-mode: persistent`) and was **not tested**.

## Rolling out without losing tabs

The Deployment has `maxUnavailable: 0`, a `preStop` sleep of 5 s so the ingress stops sending new tabs to the
old pod, then SIGTERM, then `INDAH_DRAIN_SECONDS` (10 s) of draining, inside a 30 s grace period. Keep
`terminationGracePeriodSeconds` above `preStop` plus the drain. Readiness is `/ready`, which turns 503 as
the drain starts. See [Rolling out without losing tabs](hosting.md#rolling-out-without-losing-tabs).

## The client address

`INDAH_TRUSTED_PROXIES: "k8s"` trusts every private range plus the CGNAT range, which is broad: any pod
could then set `X-Forwarded-For` and be believed. When you know your ingress controller's pods' range
(k3s default: `10.42.0.0/16`), name that instead. To keep the visitor's real address on k3s, its built-in
load balancer must not rewrite it: set `externalTrafficPolicy: Local` on the Traefik Service (k3s takes
that from a `HelmChartConfig` for `traefik` in `kube-system`). **Check it with the deploy doctor**
(`/_indah/doctor`, enabled by `INDAH_DOCTOR_TOKEN`): it warns when the resolved client is an address inside
`trusted_proxies`, which means the real visitor is hidden.

## What was checked

On k3s v1.35.5 with Traefik 3.6.13 in a throwaway k3d cluster, two replicas, on 2026-10-24
(`deploy/recipes/k8s/verify-k3d.sh` repeats all of it; indah built from the repository checkout, since the
settings above are newer than the 0.7.0 release):

| Check | Result |
|-------|--------|
| Traefik overlay, browser-like client | cookie `indah-affinity` set on the page load; **20 of 20** events answered by the stream's pod, 20 of 20 patches reached the tab |
| Plain overlay, no cookie | **10 of 20** events reached the tab; the other 10 got HTTP 409 |
| Deploy doctor behind Traefik | the peer is the Traefik pod (`10.42.0.x`); a client-sent `X-Forwarded-For: 6.6.6.6` never reached the app |
| Rolling restart, open tab | the tab received `reconnect` after the `preStop` sleep, as the drain began |

Not checked: ingress-nginx, a Traefik `IngressRoute`, the real visitor address on a real k3s
(k3d's Docker networking hides it: Traefik saw `10.42.0.1`, so `externalTrafficPolicy: Local` was not
tested), the Gateway API, and a Cloudflare Tunnel in front of the cluster.
