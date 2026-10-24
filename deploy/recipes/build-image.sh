#!/usr/bin/env bash
# Build the recipe app image with the indah in this checkout (a wheel built from it), for when the
# release you want is not on PyPI yet. Needs docker and uv.
# Usage: deploy/recipes/build-image.sh [tag]      default tag: indah-recipe-app:dev
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tag="${1:-indah-recipe-app:dev}"
ctx="$(mktemp -d)"
trap 'rm -rf "$ctx"' EXIT
cp -r "$here/app/." "$ctx/"
mkdir "$ctx/wheels"
uv build --wheel --out-dir "$ctx/wheels" "$here/../.." >/dev/null
docker build -t "$tag" --build-arg 'INDAH_SPEC=/app/wheels/indah-*.whl' "$ctx"
echo "built $tag"
