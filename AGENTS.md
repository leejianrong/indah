# AGENTS.md

## What

indah is a Python UI framework for ephemeral cloud notebooks (Colab, Runpod):
reactive, single-port, no Node required at install or runtime.

Status: early development. Slice 1 (single-port ASGI app + SSE transport, a live
counter demo) is implemented; the reactive component API (Slice 2, ADR-0003) is
not built yet. Trust the code over any doc where they disagree, and fix the doc.

Layout:

- `src/indah/` package (src layout, hatchling build)
- `tests/unit`, `tests/integration` (fast layer, no infra), `tests/e2e` (heavy)
- `docs/` PLAN, SLICES, QUESTIONS, RELEASING, and `docs/adr/` for decisions
  (the user-facing docs site will be Zensical, FastAPI-style; see ADR-0007)
- `.github/workflows/` CI and PyPI publish

## Why

Streamlit reruns the whole script per interaction; Gradio is layout-rigid; Reflex
needs a Node build step that fails inside transient cloud containers. indah fills
that gap. The load-bearing decisions are in `docs/adr/` (read 0002 on transport
and 0003 on the reactive model before touching those areas).

## How

Toolchain is `uv` (not plain pip/venv). Common commands (see `make help`):

- Setup: `uv sync --extra dev`
- Fast gate (run before pushing): `make check` (ruff + `pytest -m "unit or integration"`)
- Full tests: `uv run pytest`
- Build: `uv build`
- Install the pre-push hook once: `make hooks`

Conventions:

- Branch per slice off fresh `main`; land via PR with green CI; no direct pushes to `main`.
- Every bug or flake gets a failing test first, then the fix.
- Tests are marked `unit` / `integration` / `e2e`; keep infra-free tests out of the `e2e` mark.
- Never commit secrets or a PyPI token. Releasing is documented in `docs/RELEASING.md`.
- User-facing text (README, package description, release notes) uses hyphens, not em-dashes.
