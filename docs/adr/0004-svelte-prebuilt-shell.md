# ADR-0004: Pre-compiled Svelte frontend shell, bundled in the wheel

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

R4 requires zero Node/npm/bun at install or runtime — this is the differentiator
against Reflex, which runs `npm run build` inside the container on launch. The
frontend must therefore be built ahead of time and shipped as static assets. The
shell is a patch-heavy renderer (it applies many small JSON patches by node ID),
and it is an internal implementation detail invisible to the Python user, which
lowers the cost of the choice.

## Decision

The frontend shell is a **Svelte** single-page app, built in CI and bundled as
static assets inside the Python wheel. Svelte compiles components to small
imperative DOM updates with no virtual-DOM runtime, which suits the patch-by-ID
update model and keeps the bundled assets small. Building the wheel requires Node;
installing and running it never does.

## Alternatives considered

| Option | Why not |
|--------|---------|
| React (FastUI's choice) | Larger runtime and virtual-DOM overhead for a patch-heavy renderer; bigger bundle in the wheel |
| Vanilla JS / Lit Web Components | No runtime at all, but far more boilerplate to build the rendering engine |
| Ship source + build on launch (Reflex-style) | Directly violates R4; the failure mode we exist to avoid |

## Consequences

- Buys tiny pre-built assets, fast cold start (supports the <3s target), and a
  natural fit for granular DOM patching.
- Costs access to React's larger ready-made component ecosystem, so early
  components are hand-built.
- Requires a CI build step that produces the assets and a check that the committed
  assets match the source, so a stale bundle cannot ship.
- Because the shell is internal, swapping frameworks later is possible but means a
  full shell rewrite — the JSON protocol (ADR-0005) is the stable boundary that
  makes that survivable.
