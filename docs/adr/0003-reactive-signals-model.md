# ADR-0003: Reactive-signal programming model with granular JSON patches

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

The central pain points being solved are Streamlit's full-script rerun (every
interaction re-executes the file) and Gradio's `gr.State` chaining (multi-step
state is verbose and hard to debug). R1 requires that an interaction update only
the affected components. The public Python API is defined by whichever model is
chosen here, so it is the most expensive decision to reverse.

## Decision

indah uses a reactive model built on **signals**: named state values the user
declares and binds to components. A dependency graph records which component nodes
and handlers read each signal. When a handler mutates a signal, the core
recomputes only the dependents and emits a minimal set of JSON patches addressed
by node ID. No user code is re-executed top to bottom.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Event-driven callbacks (Gradio/JS-style) | Simpler to build, but reproduces the verbose multi-step-state pain we are trying to fix |
| Component-object mutation (ipywidgets-style) | Intuitive for small cases, but imperative UI code tangles for anything complex |
| Full-script rerun (Streamlit-style) | The exact performance failure we exist to avoid |

## Consequences

- Buys granular updates (R1), a clean mental model, and long-lived in-memory state
  that survives interactions — the whole point versus Streamlit.
- Costs real implementation effort: the dependency graph and patch-diffing are the
  novel, breakable core and carry the project's main correctness risk.
- Requires component identity to be stable across updates, which is why nodes get
  server-assigned IDs and the UI tree is modeled explicitly (see ADR-0005).
- A wrong patch set corrupts the UI silently, so this core needs the heaviest unit
  and end-to-end coverage.
