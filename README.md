# indah

> *indah* — Malay for **beautiful / elegant**.

A Python UI framework for ephemeral cloud notebooks (Google Colab, RunPod) that
keeps Streamlit's zero-config, single-port, fast-startup deploy story **and** adds
the async performance of a real full-stack app — with **no Node/npm/bun** required
at install or runtime.

> **Status: early planning / placeholder.** This is a `0.0.x` name reservation.
> The public API is not yet stable. See [`PLAN.md`](PLAN.md) and
> [`SLICES.md`](SLICES.md) for where this is going.

## Why

Streamlit reruns your entire script on every interaction; Gradio's layout and
state model get awkward past a demo; Reflex needs a Node build step that is
painful inside a transient cloud container. indah aims to fill that gap:

- **Single-port ASGI app** — serves the frontend and the API on one port, so it
  works through Colab's and RunPod's HTTP proxies.
- **No runtime Node** — the frontend ships pre-built inside the wheel.
- **SSE + HTTP POST transport** — works through Colab's proxy, which does not
  support WebSockets.
- **Reactive signals** — mutate a state variable and only the affected components
  update. No full-script reruns.
- **Async-first** — heavy PyTorch/LLM work streams into the UI instead of freezing
  it.

## Planning docs

| Doc | What |
|-----|------|
| [`PLAN.md`](PLAN.md) | Problem, solution, scope, requirements, architecture |
| [`SLICES.md`](SLICES.md) | Vertical build increments with test plans |
| [`QUESTIONS.md`](QUESTIONS.md) | Decision register |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records |

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

## License

[Apache License 2.0](LICENSE).
