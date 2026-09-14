# ADR-0008: Prototype-to-production graduation via the protocol boundary

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

indah's core scenario has two personas with a handoff between them:

1. **The prototyper** (junior dev, ML engineer, data scientist) wraps a pipeline
   (RAG chatbot, image bounding-box tool, etc.) in a few lines and launches it in
   Colab/Runpod to share a working demo the same day.
2. **The engineering team** later picks up the validated prototype and turns it
   into a real app for external users: authn/authz, hosting, a custom frontend,
   multi-user state.

The open question (raised as F4, and expanded here) was what "transition to a
real app" means. Left unanswered, it risks either scope explosion (indah becomes
a full-stack framework) or a dead end (the prototype is throwaway and the team
rewrites from zero).

## Decision

Support **two graduation paths as exit ramps off one stable boundary — the JSON
UI protocol (ADR-0005)** — and design the boundary now while building support
incrementally (north-star priority; nothing production is built into v1).

- **Composable (primary, supported):** indah stays in the stack. Because indah is
  a standard ASGI app (ADR-0001), the team mounts it inside their own
  FastAPI/Starlette app, wraps it with their own auth, and swaps auto-generated
  components for hand-written Svelte one at a time via the registration seam
  (ADR-0005), keeping the Python backend and state.
- **Eject (enabled, not built in v1):** the team leaves indah. The public,
  versioned protocol makes it possible to generate a standalone frontend targeting
  it, and the logic-separation principle (ADR-0009) lets the team lift the Python
  domain logic straight out. A codegen/scaffold tool is built only when demand
  appears.

The graduation continuum (each row shares the protocol boundary):

| Jump-off | What survives | Path |
|---|---|---|
| Deploy as-is, add auth middleware | Everything | Composable |
| Swap components to Svelte piece by piece | Python backend + state | Composable |
| Replace whole frontend, keep Python backend | Python backend + state | Composable |
| Regenerate frontend + lift logic out | Protocol + plain-Python logic | Eject |

**Auth is bring-your-own via seams.** indah ships no auth system; it exposes
standard ASGI middleware/dependency seams so the team plugs in their own
(Starlette/FastAPI auth, or Auth0/Clerk/Supabase). indah owns no security-critical
subsystem.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Grow-up: indah gains auth/persistence/multi-tenancy so the same app goes to prod | Triples scope; puts indah head-to-head with full-stack frameworks; indah would own auth's threat model |
| Eject-only: indah is purely a scaffold you always leave | Throws away the prototype's Python investment on day one; no path for apps that fit indah's model |
| Build both fully in v1 | Violates the north-star priority; delays a usable prototyping tool |
| Batteries-included auth | Makes indah own a security-critical subsystem for marginal convenience |

## Consequences

- Buys a coherent, low-cost graduation story: both ramps reuse the one boundary we
  already committed to, so Composable is nearly free and Eject stays possible.
- Costs discipline at the boundary: the protocol must stay genuinely public,
  versioned, and documented (ADR-0005), and indah must stay mountable as a plain
  ASGI sub-app (no assumptions that it owns the whole process).
- Requires the state seam (ADR-0010) and the logic-separation principle
  (ADR-0009) to hold, or the handoff leaks indah-specific assumptions.
- Forecloses indah being a one-stop production platform; that is deliberate.
