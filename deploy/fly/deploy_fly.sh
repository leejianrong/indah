#!/usr/bin/env bash
# Deploy the indah demo gallery to Fly.io as ONE app (ADR-0023, self-hosted path).
#
# One machine serves every demo behind a sub-path (see gallery_app.py / build_gallery.sh).
# Machines auto-stop when idle (min 0), so the gallery costs ~nothing at rest.
#
# Prereqs: flyctl installed (https://fly.io/docs/flyctl/install/) and `fly auth login`.
# Usage:   ./deploy_fly.sh
# Env:     FLY_APP (default "indah-demos"; Fly app names are GLOBAL, change if taken),
#          FLY_REGION (default "sin").
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
app="${FLY_APP:-indah-demos}"

command -v fly >/dev/null 2>&1 || { echo "flyctl not found - install it and 'fly auth login' first." >&2; exit 1; }

FLY_APP="$app" "$here/build_gallery.sh"
out="$here/build"

fly apps create "$app" >/dev/null 2>&1 || true   # idempotent: ignore "already exists"
fly deploy "$out" --config "$out/fly.toml" --ha=false

echo
echo "Live at https://$app.fly.dev  (demos at /chatbot, /training-dashboard, /diffusion,"
echo "  /poster, /image-classify, /charts). Add those URLs to website/docs/gallery.md."
