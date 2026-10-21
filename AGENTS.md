# AGENTS.md

## What

indah is a Python UI framework for ephemeral cloud notebooks (Colab, Runpod):
reactive, single-port, no Node required at install or runtime.

Status: early development, MVP feature-complete. Slices 1-4 are implemented:
single-port ASGI app + SSE/POST transport (ADR-0002), the reactive core
(signals/computeds/effects, ADR-0003), a pre-built Svelte shell (ADR-0004), async
handlers + LLM token streaming (ADR-0011), the starter component set (Text, Button,
Slider, TextInput, Select, Image, Plot, DataFrame, StreamText, Column), and a
`register_component()` seam for custom components (ADR-0012). The JSON protocol is
documented as a versioned public contract (`docs/protocol.md`, ADR-0005). Post-MVP
slices are also in: per-session state (ADR-0010), layout and data-driven lists, media
upload, hybrid charting, the Studio design system, a Zensical docs site (ADR-0007) and a
public demo gallery. Current work is the **semula requests**: enhancements for the
semula dashboard (live push, a rich Table, overlays, routing, editors, then hosted
identity/authz/hardening). The plan is `docs/SEMULA-REQUESTS-PLAN.md`; progress is board
IND (epics IND-E19..E26, label `semula`). Done so far: mount-safe shell, `Context`, app
theme, `Topic`/`Stream`, Table v2 core, the live-log demo (`make demo-semula`), and the
overlays slice (TextArea, Modal/Drawer/confirm, toasts, Badge/Switch/tooltip, Shortcuts, Table
row actions and multi-select, `make demo-pending`).
Trust the code over any doc where they disagree, and fix the doc.

Layout:

- `src/indah/` package (src layout, hatchling build); the built shell is bundled
  at `src/indah/static/index.html`
- `frontend/` Svelte source for the shell (build-time only; not shipped, not
  needed to install or run indah)
- `examples/demo.ipynb` the notebook demo, `examples/starter_components.py` a
  ~20-line app, `examples/chatbot.py` + `examples/chatbot_colab.ipynb` the
  flagship "real LLM in Colab" chatbot (transformers is the user's dep, not
  indah's); `examples/semula_log.py` the semula-shaped live request log (`make
  demo-semula`; the requests behind it are in `docs/SEMULA-REQUESTS-PLAN.md`),
  `examples/semula_pending.py` the pending queue with drawer, toast and shortcuts (`make demo-pending`),
  `examples/semula_entries.py` the 20k-row SQLite entries browser (`make demo-entries`),
  `examples/semula_routes.py` the routed dashboard with deep links under `/ui` (`make demo-routes`),
  `examples/semula_editor.py` the entry editor, conflict diff, review card and playground (`make demo-editor`),
  `examples/semula_review.py` every semula demo behind one index (`make demo-review`);
  `docs/DEV-DOCKER.md` the Docker/Traefik flow
- `tests/unit`, `tests/integration` (fast layer, no infra), `tests/e2e` (heavy)
- `docs/` PLAN, SLICES, QUESTIONS, RELEASING, `protocol.md` (the public wire
  contract), and `docs/adr/` for decisions (engineering docs, not the published site)
- `website/` the user-facing docs site (Zensical -> GitHub Pages, ADR-0007); its
  own `docs/` source tree, separate from the engineering `docs/` above
- `.github/workflows/` CI, docs (Pages), and PyPI publish

## Why

Streamlit reruns the whole script per interaction; Gradio is layout-rigid; Reflex
needs a Node build step that fails inside transient cloud containers. indah fills
that gap. The load-bearing decisions are in `docs/adr/` (read 0002 on transport
and 0003 on the reactive model before touching those areas).

## How

Toolchain is `uv` (not plain pip/venv). Common commands (see `make help`):

- Setup: `uv sync --extra dev`
- Try the demo: `make demo` (prints a URL; binds the first free port from 8000);
  `make demo-notebook` (inline in JupyterLab); `make demo-docker` (Docker, free
  port); `make demo-traefik` (Docker via a machine-wide Traefik at indah.localhost)
- Fast gate (run before pushing): `make check` (ruff + `pytest -m "unit or integration"`)
- Full tests: `uv run pytest`
- Rebuild the Svelte shell after editing `frontend/`: `make frontend` (needs Node;
  commit the regenerated `src/indah/static/index.html` or CI's stale check fails)
- Docs site: `make docs` (build) / `make docs-serve` (preview); needs `--extra docs`
  (Zensical). CI build-checks it on every PR and deploys to Pages on merge.
- Build the wheel: `uv build`
- Install the pre-push hook once: `make hooks`

Conventions:

- Branch per slice off fresh `main`; land via PR with green CI; no direct pushes to `main`.
- Every bug or flake gets a failing test first, then the fix.
- Tests are marked `unit` / `integration` / `e2e`; keep infra-free tests out of the `e2e` mark.
- Never commit secrets or a PyPI token. Releasing is documented in `docs/RELEASING.md`.
- User-facing text (README, package description, release notes) uses hyphens, not em-dashes.
