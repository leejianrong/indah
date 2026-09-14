# ADR-0010: Session state behind a pluggable seam; in-memory the only v1 backend

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

The reactive core keeps per-session state in the Python process (ADR-0003), which
is ideal for a single-user notebook prototype. But the graduation scenario
(ADR-0008) ends in an app for *external users*: state must survive a restart and
be shared across multiple replicas behind a load balancer. In-process state gives
neither. This is the one production concern that does not come for free from indah
being a plain ASGI app, so it needs a deliberate decision.

## Decision

Access session state through a **small, documented interface (a session-store
seam)** from the start, but ship **only the in-memory implementation in v1.** The
reactive core reads and writes state exclusively through this seam, never assuming
the store is local. An external backend (e.g. Redis) is a later drop-in that
requires no change to app code.

This matches the north-star priority: design the seam now so apps are not written
against an in-memory assumption, but do not build the external backend until a
graduating app needs it.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Build a Redis/DB backend in v1 | Slows the prototyping tool for a need most prototypes never have |
| In-memory with no seam, retrofit later | Retrofitting shared state into apps written against a local-state assumption is expensive, invasive rework |

## Consequences

- Buys a real graduation path for multi-user state without paying for it in v1,
  and keeps the in-memory prototype path simple and fast.
- Costs the discipline of routing all state access through the seam even while
  there is one implementation, and of not leaking local-only semantics (e.g.
  storing unpicklable objects, assuming zero serialization cost) into the
  interface.
- Requires the seam's contract to assume state may be remote and serialized, so a
  future Redis backend is a genuine drop-in.
- A later backend inherits its own concerns (serialization, eviction, locking);
  those are deferred with the backend, not designed now.
