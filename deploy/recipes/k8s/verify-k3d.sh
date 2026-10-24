#!/usr/bin/env bash
# Verify the k8s recipes on a throwaway k3d cluster (k3s with its bundled Traefik). Needs docker,
# k3d, kubectl and uv. Nothing outside the cluster "indah-recipes" is touched.
#
#   deploy/recipes/k8s/verify-k3d.sh            run every check, then delete the cluster
#   KEEP=1 deploy/recipes/k8s/verify-k3d.sh     leave the cluster running afterwards
#   PORT=8089 ...                               host port for the cluster's ingress
#
# It builds the recipe app image from this checkout, then, on two replicas, checks (1) the Traefik
# overlay keeps a tab on one pod, (2) the plain overlay (no cookie) does not, (3) what the deploy
# doctor sees from behind Traefik, and (4) that a rolling restart sends open tabs a `reconnect`.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
cluster=indah-recipes
port="${PORT:-8089}"
host=indah.localhost
image=indah-recipe-app:verify
base="http://127.0.0.1:${port}"
tmp="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp"
  if [ -z "${KEEP:-}" ]; then k3d cluster delete "$cluster" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

say() { printf '\n== %s\n' "$*"; }
wait_up() {
  for _ in $(seq 1 60); do
    code=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $host" "$base/ready" || true)
    [ "$code" = 200 ] && return 0
    sleep 2
  done
  echo "the app did not answer 200 on /ready through the ingress" >&2
  return 1
}
# teardown: delete what apply made, and wait until the namespace is really gone
teardown() {
  kubectl delete -k "$tmp/k8s/run" >/dev/null
  kubectl wait --for=delete namespace/indah --timeout=180s >/dev/null 2>&1 || true
}
# apply <overlay> <replicas>: a copy of the manifests with our host, image and replica count
apply() {
  rm -rf "$tmp/k8s" && cp -r "$here" "$tmp/k8s"
  sed -i "s/indah.example.com/$host/" "$tmp"/k8s/overlays/*/ingress.yaml
  mkdir "$tmp/k8s/run"
  cat >"$tmp/k8s/run/kustomization.yaml" <<YAML
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: [../overlays/$1]
images:
  - {name: indah-app, newName: ${image%%:*}, newTag: ${image##*:}}
replicas:
  - {name: indah-app, count: $2}
YAML
  kubectl apply -k "$tmp/k8s/run" >/dev/null
  kubectl -n indah rollout status deploy/indah-app --timeout=180s
  wait_up
}

say "build the app image from this checkout"
"$repo/deploy/recipes/build-image.sh" "$image"

say "create the k3d cluster (k3s $(k3d version | awk '/k3s/{print $3}'), Traefik on host port $port)"
k3d cluster delete "$cluster" >/dev/null 2>&1 || true
k3d cluster create "$cluster" -p "${port}:80@loadbalancer" --wait >/dev/null
k3d image import "$image" -c "$cluster" >/dev/null
kubectl get nodes -o wide
# k3s installs Traefik with a Helm job, so the Deployment appears a little after the node is Ready.
for _ in $(seq 1 90); do
  kubectl -n kube-system get deploy traefik >/dev/null 2>&1 && break
  sleep 2
done
kubectl -n kube-system rollout status deploy/traefik --timeout=180s
kubectl -n kube-system get deploy traefik -o jsonpath='Traefik image: {.spec.template.spec.containers[0].image}{"\n"}'

say "1. traefik overlay, 2 replicas, browser-like client (expect STICKY)"
apply traefik 2
kubectl -n indah get pods -o wide
uv run python "$repo/deploy/probe/sticky_check.py" "$base" --header "Host: $host" --cookies \
  --machine-header x-indah-node --events 20

say "2. plain overlay, 2 replicas, no affinity (expect NOT STICKY)"
teardown
apply plain 2
uv run python "$repo/deploy/probe/sticky_check.py" "$base" --header "Host: $host" --cookies \
  --machine-header x-indah-node --events 20 || true

say "3. the deploy doctor behind Traefik (INDAH_TRUSTED_PROXIES=k8s from the ConfigMap)"
kubectl -n indah create secret generic indah-secrets \
  --from-literal=INDAH_DOCTOR_TOKEN=verify-token-0123456789 >/dev/null
kubectl -n indah rollout restart deploy/indah-app >/dev/null
kubectl -n indah rollout status deploy/indah-app --timeout=180s
wait_up
doctor() {
  curl -s -H "Host: $host" -H "Authorization: Bearer verify-token-0123456789" "$@" \
    "$base/_indah/doctor?format=json" | uv run python -c '
import json, sys
d = json.load(sys.stdin)
req = d["request"]
print("  socket_peer      ", req["socket_peer"])
print("  resolved_client  ", req["resolved_client"])
print("  x-forwarded-for  ", d["headers"].get("x-forwarded-for"))
print("  presets          ", d["trusted_proxies_presets"], "->", len(d["trusted_proxies"]), "networks")
print("  warnings         ", [w.get("message", w) if isinstance(w, dict) else w for w in d["warnings"]])
'
}
echo "a plain request:"
doctor
echo "a request that sends its own X-Forwarded-For: 6.6.6.6 (Traefik should not pass it on):"
doctor -H "X-Forwarded-For: 6.6.6.6"

say "4. a rolling restart sends open tabs a reconnect message (traefik overlay, 2 replicas)"
teardown
apply traefik 2
uv run python - "$base" "$host" <<'PY' &
import json, sys, time, uuid
import httpx
base, host = sys.argv[1], sys.argv[2]
t0 = time.time()
seen = []
with httpx.Client(timeout=None, headers={"Host": host}) as c:
    c.get(base + "/")
    with c.stream("GET", base + "/api/stream", params={"sid": uuid.uuid4().hex}) as r:
        try:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    t = json.loads(line[6:]).get("type")
                    if t != "ping" and (not seen or seen[-1][0] != t):
                        seen.append((t, round(time.time() - t0, 1)))
                    if t == "reconnect":
                        break
        except httpx.HTTPError as e:
            seen.append((type(e).__name__, round(time.time() - t0, 1)))
print("messages seen on the tab's stream (type, seconds):", seen)
PY
reader=$!
sleep 4
kubectl -n indah rollout restart deploy/indah-app >/dev/null
kubectl -n indah rollout status deploy/indah-app --timeout=180s
wait "$reader" || true

say "done"
