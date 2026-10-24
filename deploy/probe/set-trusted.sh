#!/usr/bin/env bash
# Change the probe's trusted_proxies without a rebuild. Usage: set-trusted.sh "172.16.0.0/12,10.0.0.0/8"
# An empty argument clears it (trust nothing).
set -euo pipefail
fly secrets set -a indah-probe "INDAH_TRUSTED_PROXIES=${1:-}"
