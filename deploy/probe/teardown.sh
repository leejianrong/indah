#!/usr/bin/env bash
# Delete the probe app. It only ever existed for the IND-170 and IND-171 checks.
set -euo pipefail
fly apps destroy indah-probe --yes
