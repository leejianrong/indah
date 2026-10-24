#!/usr/bin/env bash
# Deploy the probe to Fly as a NEW app, `indah-probe` (never indah-demos). Needs `fly auth login`
# and `uv` (it builds a wheel of this checkout, so the probe runs the indah under test).
# Usage: deploy/probe/deploy.sh            deploy one machine
#        INDAH_TRUSTED_PROXIES=172.16.0.0/12 deploy/probe/deploy.sh   deploy with a setting
#        INDAH_DOCTOR_TOKEN=... deploy/probe/deploy.sh   also turn on /_indah/doctor (16+ chars)
# (PROBE_TRUSTED_PROXIES is still read as an alias for INDAH_TRUSTED_PROXIES.)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
command -v fly >/dev/null 2>&1 || { echo "flyctl not found; install it and 'fly auth login'." >&2; exit 1; }
command -v uv >/dev/null 2>&1 || { echo "uv not found; it builds the wheel the probe installs." >&2; exit 1; }
rm -rf "$here/wheels" && uv build --wheel --out-dir "$here/wheels" "$here/../.." >/dev/null
fly apps create indah-probe >/dev/null 2>&1 || true   # idempotent
trusted="${INDAH_TRUSTED_PROXIES:-${PROBE_TRUSTED_PROXIES:-}}"
if [ -n "$trusted" ]; then
  # Plain config, not a secret: `fly secrets set` is just the quickest restart-with-env.
  fly secrets set -a indah-probe --stage "INDAH_TRUSTED_PROXIES=${trusted}" >/dev/null
fi
if [ -n "${INDAH_DOCTOR_TOKEN:-}" ]; then
  # A real secret: it is read from your environment and never printed.
  fly secrets set -a indah-probe --stage "INDAH_DOCTOR_TOKEN=${INDAH_DOCTOR_TOKEN}" >/dev/null
fi
fly deploy "$here" --config "$here/fly.toml" --ha=false
rm -rf "$here/wheels"
echo "Live at https://indah-probe.fly.dev/  and  https://indah-probe.fly.dev/whoami"
