# Gallery apps: the next batch (IND-194)

Decided with the owner on 2026-10-26. The gallery is one 1 GB CPU process shared by every visitor, so each
app is model-free, needs no network at run time and has bounded work per session.

## Chosen for the 0.9.x patch

| Card | App | Shows off |
|------|-----|-----------|
| IND-217 | Cellular automata (Life, rules 30, 90, 110) | Live streamed grid, sliders, run and step controls |
| IND-218 | Sorting visualiser | Streaming steps into a chart, speed control |
| IND-219 | Markov poet | `StreamText`, a small bundled public-domain corpus |
| IND-220 | Expense tracker | `ctx.persist` (restorable sessions, 0.9.0), tables, totals |

## Ranked, not chosen yet

Ranked by how cheap they are and how much they add to the gallery, after the four above.

1. Mandelbrot and Julia explorer: re-render on slider change, client heatmap. Medium.
2. Typing-speed race: streaming text diff and a live words-per-minute chart. Small.
3. Colour palette from an image: upload, k-means on CPU, copy hex. Small.
4. Budget splitter: table editing, overlays and routing. Small.

Older cards that still fit later: IND-57 (RAG chat with citations), IND-62 (video detection) and IND-65 need a
model or live media and wait for 0.10.0; IND-81 (LLM comparison charts) goes stale.

## Rules for every app

Per-session state through `session_factory`; no inline scripts or styles (the gallery runs under `csp="strict"`);
a card needs a catalog entry, a thumbnail, a Colab notebook (`make colab`), an e2e smoke test and a CHANGELOG line.
