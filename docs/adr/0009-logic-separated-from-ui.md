# ADR-0009: Domain logic lives in plain functions indah calls

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

The graduation model (ADR-0008) only works if the prototype's real value — the
RAG pipeline, the model inference, the image processing — survives the handoff to
the engineering team. Streamlit's failure mode is that logic and UI are fused in
one top-to-bottom rerun script, so the logic cannot be extracted and the team
rewrites from scratch. indah must not repeat that.

## Decision

Make it a core, documented principle that **domain logic lives in plain Python
functions that indah calls, kept separate from UI code.** indah wraps functions;
it does not ask you to write your logic inside its UI objects or handlers. A
button's handler should call `answer = rag_pipeline(question)`, where
`rag_pipeline` is an ordinary function with no indah imports.

The API and documentation are shaped to make this the natural way to write an
indah app, and every tutorial models it. Inline logic in handlers is not
forbidden, but the guided path keeps logic and UI apart.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Unopinionated (logic wherever) | Lowest friction to write, highest friction to graduate; portability becomes the user's problem exactly when they can least afford it |
| Streamlit-style fused script | The specific anti-pattern indah exists to avoid |

## Consequences

- Buys clean graduation on both ramps: on Composable the team keeps the functions
  untouched; on Eject they lift the functions straight into their own FastAPI
  endpoints because the functions never depended on indah.
- Also buys testability: domain logic is unit-testable without spinning up any UI.
- Costs a little ergonomics for the smallest scripts, where inlining would be
  shorter; the guided path accepts that trade for portability.
- Requires the reactive API (ADR-0003) to make "bind a component to the result of
  a function" a first-class, obvious pattern, not a workaround.
