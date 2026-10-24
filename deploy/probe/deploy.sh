#!/usr/bin/env bash
# Deploy the probe to Fly as a NEW app, `indah-probe` (never indah-demos). Needs `fly auth login`.
# Usage: deploy/probe/deploy.sh            deploy one machine
#        PROBE_TRUSTED_PROXIES=172.16.0.0/12 deploy/probe/deploy.sh   deploy with a setting
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
command -v fly >/dev/null 2>&1 || { echo "flyctl not found; install it and 'fly auth login'." >&2; exit 1; }
fly apps create indah-probe >/dev/null 2>&1 || true   # idempotent
if [ -n "${PROBE_TRUSTED_PROXIES:-}" ]; then
  # Plain config, not a secret: `fly secrets set` is just the quickest restart-with-env.
  fly secrets set -a indah-probe --stage "PROBE_TRUSTED_PROXIES=${PROBE_TRUSTED_PROXIES}" >/dev/null
fi
fly deploy "$here" --config "$here/fly.toml" --ha=false
echo "Live at https://indah-probe.fly.dev/  and  https://indah-probe.fly.dev/whoami"
