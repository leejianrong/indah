# ADR-0005: Versioned JSON UI protocol as a public contract; escape hatch deferred

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

An open question was whether to support transitioning from Python-only UI to a
hand-written frontend (JS/HTML/Svelte). Building that tooling now (scaffolding, a
typed JS client, HMR) would roughly double v0 scope and pull in the Node
toolchain R4 exists to avoid. But if the wire format between Python and the shell
is left as a private implementation detail, making it public later is an expensive
retrofit. R6 and R7 (public protocol, custom components) depend on this.

## Decision

The JSON UI protocol — the component-tree serialization and the patch/event
messages between the Python core and the shell — is designed as a **documented,
versioned public contract** from v0. Every payload carries a `protocol_version`
the shell checks on connect and rejects on mismatch. A `register_component()` seam
lets user code map a custom component type to a shell renderer against this
protocol. The **full escape-hatch tooling is deferred**: no scaffolding, typed
client, or HMR ships in v0.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Build the full escape hatch in v0 | Roughly doubles scope and reintroduces the Node toolchain R4 forbids |
| Keep the protocol private, defer entirely | Retrofitting a public, versioned contract later is expensive and breaks early adopters |

## Consequences

- Buys a stable boundary that makes ADR-0004's shell swappable, enables custom
  components (R7), and keeps a future hand-written frontend cheap to add.
- Costs upfront discipline: the protocol must be documented and versioned even
  while it has one consumer, and changes now incur a compatibility check.
- Requires the shell to validate `protocol_version` and fail loudly on mismatch,
  so a backend/shell version skew cannot silently misrender.
