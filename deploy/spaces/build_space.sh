#!/usr/bin/env bash
# Assemble a Hugging Face Docker Space folder for each indah demo (ADR-0023).
#
# It writes a ready-to-push Space into build/<slug>/ (Dockerfile + requirements.txt
# + app.py + README.md with the HF frontmatter). It does NOT push to Hugging Face -
# that needs your HF account/token; see README.md in this directory for the push step.
#
# Usage:
#   ./build_space.sh            # build every demo in demos.tsv
#   ./build_space.sh poster     # build just one (by slug)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
out="$here/build"
only="${1:-}"

# indah source for the Space image. Until indah is on PyPI, install from git@main;
# swap this for "indah" (a pinned release) once published.
INDAH_REQ='indah @ git+https://github.com/leejianrong/indah@main'

mkdir -p "$out"

while IFS=$'\t' read -r slug example title emoji extra; do
  case "$slug" in ''|\#*) continue ;; esac              # skip blanks/comments
  [ -n "$only" ] && [ "$slug" != "$only" ] && continue

  src="$repo_root/examples/$example"
  if [ ! -f "$src" ]; then
    echo "!! $slug: examples/$example not found, skipping" >&2
    continue
  fi

  dir="$out/$slug"
  mkdir -p "$dir"
  cp "$src" "$dir/app.py"

  {
    echo "$INDAH_REQ"
    echo "uvicorn[standard]"
    [ "$extra" != "-" ] && for pkg in $extra; do echo "$pkg"; done
  } > "$dir/requirements.txt"

  cat > "$dir/Dockerfile" <<'DOCKER'
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 7860
# The example exposes a module-level `app` (an indah ASGI app).
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
DOCKER

  cat > "$dir/README.md" <<README
---
title: indah - $title
emoji: $emoji
colorFrom: pink
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# $title

A live demo of [**indah**](https://github.com/leejianrong/indah) - a reactive
Python UI framework for cloud notebooks (no Node, single port, streaming over SSE).

Source: [\`examples/$example\`](https://github.com/leejianrong/indah/blob/main/examples/$example).
README

  echo "built $out/$slug/  ($title)"
done < "$here/demos.tsv"

echo
echo "Done. Push each build/<slug>/ to a Hugging Face Docker Space - see README.md."
