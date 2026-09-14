#!/usr/bin/env bash
# Clean-room proof of R4: indah needs zero Node at install or at runtime.
#
# Builds nothing itself - run `uv build` first (or `make cleanroom`, which does).
# Installs the freshly built wheel into a throwaway venv with JavaScript-toolchain
# tripwires placed FIRST on PATH. Each tripwire (node, npm, npx, bun, yarn, pnpm,
# vite, svelte, esbuild) logs its own invocation and exits non-zero, so any use
# during pip install OR at runtime is caught and fails the script.
#
# Usage:  scripts/cleanroom.sh
# Passes when the invocation log is empty and the app builds its tree + serves the
# pre-built shell without touching a JS tool.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
TRIP="$WORK/tripwire-bin"
LOG="$WORK/js-invocations.log"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$TRIP"
: > "$LOG"

for tool in node npm npx bun yarn pnpm vite svelte esbuild; do
  cat > "$TRIP/$tool" <<EOF
#!/usr/bin/env bash
echo "TRIPWIRE: '$tool \$*' invoked" | tee -a "$LOG" >&2
exit 87
EOF
  chmod +x "$TRIP/$tool"
done

WHEEL="$(ls "$REPO"/dist/indah-*.whl 2>/dev/null | head -1 || true)"
if [ -z "$WHEEL" ]; then
  echo "!!! no wheel in $REPO/dist - run 'uv build' first" >&2
  exit 2
fi
echo ">>> wheel under test: $WHEEL"

export PATH="$TRIP:$PATH"
uv venv "$WORK/venv" -q
# shellcheck disable=SC1091
source "$WORK/venv/bin/activate"

echo ">>> installing wheel (tripwires on PATH)"
uv pip install -q "$WHEEL"

echo ">>> importing + building the demo tree at runtime (tripwires on PATH)"
python - <<'PY'
import indah
print("indah", indah.__version__)
from indah.app import build_demo_session
snap = build_demo_session().snapshot()
assert snap.get("type") and snap.get("id"), snap  # a serialized component tree
from importlib.resources import files
shell = files("indah.static").joinpath("index.html").read_text(encoding="utf-8")
assert "EventSource" in shell and "api/stream" in shell, "shell not served from package"
print("shell bytes:", len(shell))
print("RUNTIME OK")
PY

echo ">>> tripwire log:"
if [ -s "$LOG" ]; then
  cat "$LOG"
  echo "!!! FAIL: a JS tool was invoked (violates R4)"
  exit 1
fi
echo "(empty) - zero JS-toolchain invocations at install or runtime"
echo "CLEAN-ROOM PASS"
