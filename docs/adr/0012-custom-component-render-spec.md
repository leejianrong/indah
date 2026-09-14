# ADR-0012: Custom components via a declarative render spec

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

R7 asks that custom components be registrable without forking the framework, and
ADR-0005 committed to a `register_component()` seam that maps a user component type
to a shell renderer, keyed off the public JSON protocol. Slice V4 has to make that
seam real.

The tension is with ADR-0004: the shell ships **pre-built**, and R4 forbids any
Node/npm at install or runtime. A genuinely new *hand-written* Svelte component
cannot be added to a user's installed shell, because compiling it would need the
Node toolchain we deliberately keep out of the runtime. So "register a component"
in v0 cannot mean "ship new component code to the browser". It has to mean
something the already-built, generic shell can act on at runtime, from data alone.

## Decision

A custom component is registered with a small, **declarative render spec** that the
shell's built-in generic renderer interprets at runtime. `register_component(type,
render=...)` validates the spec against a Pydantic schema in `protocol.py` (so it
is part of the versioned public contract) and stores it. `custom(type, **props)`
builds an instance, binding props to signals (reactive, two-way) or static values.

The spec travels on the wire as a reserved static prop, `_spec`, carried once in
the node's `init` snapshot. When the shell meets a node type it does not render
natively but whose props carry `_spec`, it builds the element from the spec:

- `tag` — one element, from a safe allowlist (no `script`/`iframe`/`style`/…);
- `attrs` / `class` — static attributes;
- `bind` — element attribute ← node prop (so a signal change patches it);
- `text` — node prop → text content;
- `on` — DOM event → indah event, posting `{value}` for a value round-trip;
- `children` — nested specs (recursive), for a small composite.

Because the spec is data, not code, no shell rebuild and no runtime Node are
involved, and the round-trip is identical to a built-in input: set the bound
signal from Python and the element updates; interact in the UI and the signal is
readable in Python.

The worked example is a `colorpicker` (`<input type="color">`) two-way bound to a
`Signal[str]`, shipped in the built-in demo.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Ship user-authored Svelte compiled at runtime | Needs the Node toolchain at runtime, which R4 forbids and ADR-0004 designed away |
| Fetch a user JS bundle the shell `import()`s | Reintroduces a build step and an external asset request that Colab/Runpod base-path proxying breaks (ADR-0001); larger attack surface |
| A full client template language (loops, conditionals, expressions) | Roughly the scope of a framework; the escape-hatch tooling is explicitly deferred (ADR-0005). The declarative element spec covers the common value-bearing widget without it |
| Keep custom components Python-only, reusing a built-in renderer | Cannot express a genuinely new element (a colour input, a progress meter); fails R7's intent |

## Consequences

- Delivers R7 within R4's no-runtime-Node constraint: new value-bearing widgets
  (colour input, progress/meter, badges, small composites) register from Python
  and round-trip like built-ins, with the pre-built shell untouched.
- The render spec is now part of the public protocol surface: it is versioned with
  `protocol_version`, validated on registration, and documented in
  `docs/protocol.md`. Widening it (new spec fields) is a protocol change.
- The tag allowlist and the data-only (no code, no arbitrary HTML) design keep the
  generic renderer's surface inert; a spec cannot inject script or fetch remote
  code. The dev-tool threat model (Q-sec) still holds.
- The spec cannot express loops or conditionals. A component that needs those is
  the signal that the deferred full escape hatch (a hand-written frontend against
  the protocol, ADR-0005/0008) is the right tool, not a bigger spec language.
