#!/usr/bin/env bash
# Deploy the recipe app to Fly as ONE machine. Needs `fly auth login`.
# Usage: deploy/recipes/fly/deploy.sh <app-name> [region]
#   INDAH_DOCTOR_TOKEN=<16+ chars> ...   also turns on /_indah/doctor (stored as a Fly secret)
#   INDAH_FROM_CHECKOUT=1 ...            install the indah in this checkout (needs uv), for a release
#                                        that is not on PyPI yet; otherwise pip installs `indah`
# For your own app: copy deploy/recipes/app, put your code in it, and deploy that directory.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
app="${1:?usage: deploy.sh <app-name> [region]}"
region="${2:-sin}"
command -v fly >/dev/null 2>&1 || { echo "flyctl not found; install it and 'fly auth login'." >&2; exit 1; }
ctx="$here/../app"
args=()
if [ -n "${INDAH_FROM_CHECKOUT:-}" ]; then
  command -v uv >/dev/null 2>&1 || { echo "uv not found; it builds the wheel." >&2; exit 1; }
  ctx="$(mktemp -d)"
  trap 'rm -rf "$ctx"' EXIT
  cp -r "$here/../app/." "$ctx/"
  mkdir "$ctx/wheels"
  uv build --wheel --out-dir "$ctx/wheels" "$here/../../.." >/dev/null
  args=(--build-arg 'INDAH_SPEC=/app/wheels/indah-*.whl')
fi
fly apps create "$app" >/dev/null 2>&1 || true   # idempotent
if [ -n "${INDAH_DOCTOR_TOKEN:-}" ]; then
  # Read from your environment, never printed.
  fly secrets set -a "$app" --stage "INDAH_DOCTOR_TOKEN=${INDAH_DOCTOR_TOKEN}" >/dev/null
fi
fly deploy "$ctx" --config "$here/fly.toml" --app "$app" --primary-region "$region" --ha=false "${args[@]}"
echo "Live at https://$app.fly.dev/"
