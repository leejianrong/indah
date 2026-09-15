# ADR-0016: Dynamic content — a data-driven list, not a structural op

- Status: Proposed
- Date: 2026-09-15
- Deciders: Jian (owner)

## Context

Growing/variable content — chat bubbles, image galleries, logs, search results,
RAG source citations — is the other half of the shared foundation (Slice B). The
gap was first framed as a missing **structural protocol op**: v1 patches only merge
props or append a string delta (ADR-0011); there is no op to add, remove, or reorder
a node's children at runtime (Q-children, KAN-1396). A growing list is faked today
by appending into one `StreamText`, which cannot style or address individual items.

A structural children op is real work and a `protocol_version` bump. But most of the
value does not need it. `DataFrame` already renders a variable number of rows from a
single reactive `data` prop over ordinary prop-merge patches — the tree does not
grow, the data does. The same shape covers chat, galleries, and logs.

## Decision

Ship a **data-driven list** first. A `List`/`Repeat` component holds its items in one
reactive prop (`Signal[list]`); the shell renders each item through an item template
(a built-in template for the specialisations, the render-spec vocabulary of ADR-0012
for custom items). Specialisations: `Chat` (role bubbles, auto-scroll) and `Gallery`
(image grid). Adding, removing, or reordering items is a normal prop change carried
by the existing `patch` op — **no `protocol_version` bump**.

Defer the general **structural children op** (add/remove/reorder arbitrary,
heterogeneous child *nodes*) until a use case genuinely needs it — runtime-added
tabs, dynamic forms, multi-page. When built it will be a protocol change with its own
ADR. This supersedes the framing of KAN-1396: the list is the near-term answer, the
structural op is the deferred general one.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Build the structural children op now | Harder, a protocol version bump, and more than chat/gallery/logs actually need |
| Keep the single-`StreamText` transcript | Cannot style, address, or lay out individual items; no bubbles, no gallery |
| Model each item as its own node in the tree | That *is* the structural op; deferred for the same reasons |

## Consequences

- Chat bubbles (KAN-1398), galleries, and logs ship without touching the wire
  format; the chatbot example is rebuilt on `Chat`.
- Homogeneous, data-shaped lists are covered; genuinely heterogeneous runtime
  children (mixed component types added at runtime) remain deferred to the structural
  op.
- The item-template design (how far the built-in templates go before a custom item
  template is needed) is the substance of the slice.
- Reordering/removal semantics (keys, stable identity) are defined here so a later
  structural op stays consistent with them.
