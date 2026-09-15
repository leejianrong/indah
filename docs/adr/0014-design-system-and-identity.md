# ADR-0014: Design system, tokens, and visual identity

- Status: Accepted
- Date: 2026-09-15
- Deciders: Jian (owner)

## Context

The pre-built shell (ADR-0004) shipped with a generic indigo look that reads as
"AI-typical" (EPIC-209, owner feedback). The post-MVP roadmap adds a wave of new
shell components — layout containers (ADR-0015), a data-driven list (ADR-0016),
media widgets (ADR-0017), charts (ADR-0018), and the rest of the basic input set.
If the visual language is set *after* those are built, every component is styled
twice. So the design system has to be a foundational layer (Slice 0) that lands
before them, and each new component is drawn to it once.

Two forces shape it. First, we want a *coherent* system, not ad-hoc CSS: named
roles for colour, a type scale, shape and elevation, state layers — the rigour
Material 3 is built on. Second, we do **not** want to look like stock Material or
any other template; the point of the round was to stop reading as generic.

## Decision

Adopt a **design-token layer** as the shell's styling contract: CSS custom
properties for colour roles, type scale, shape, elevation, and state, applied by
role rather than by literal value. The role architecture follows Material 3
(`primary`, `on-primary`, `surface`, `outline`, corner/elevation scales, state-layer
opacities), but the values are seeded to a distinctive identity — MD3's system, not
MD3's look.

**Default theme — "Studio".** Warm porcelain ground, bougainvillea magenta primary,
deep teal secondary; Bricolage Grotesque as the display face, IBM Plex Sans for
body, IBM Plex Mono for data/labels. Full light + dark token values are recorded in
`assets/brand/README.md` and wired in Slice 0.

**Theming is a token swap.** Because the shell is pre-built, a theme is just a set
of token values — no per-theme rebuild. Only Studio ships as the baked default now;
a user-selectable theme switcher is a cheap later addition (deferred), and the token
contract is designed so it drops in without touching components.

**Logo — "Bunga".** A four-petal bloom (two magenta petals vertical, two teal
horizontal): *indah* = "beautiful", the soft/floral counterpoint to the suite's
angular ketupat, sharing its minimalism and warm palette. The **wordmark** is
"indah" in Bricolage Grotesque 700, a single ink colour, never split or
multi-coloured. Source SVGs live in `assets/brand/` (`indah-mark.svg`,
`indah-mark-mono.svg`, `favicon.svg`).

**One identity across surfaces.** The shell header and the Zensical docs site
(ADR-0007) both adopt the Studio palette and the Bunga mark/favicon, replacing the
indigo defaults.

This is entirely shell/site-side styling and asset work; it does **not** touch the
wire protocol.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Ship stock Material 3 | The rigour is what we want, but the literal look reads as generic/Google — the exact "AI-typical" feel we set out to leave |
| Keep ad-hoc per-component CSS | No coherence; every new component reinvents spacing/colour and gets restyled later — the retrofit we're avoiding |
| A utility-CSS framework (Tailwind etc.) | Adds build tooling and cuts against the pre-built, dependency-light shell; tokens give the same discipline with none of it |
| Defer the visual language until components exist | Guarantees the double-styling this ADR exists to prevent |

## Consequences

- A token contract the shell is built on; new components (ADR-0015..0018, the input
  set) consume roles, so they inherit the identity for free.
- Theming is near-free: additional themes are token sets; the switcher is a small,
  contained later feature, not a rebuild.
- indah has one identity across the shell and the docs site; the indigo defaults go.
- Brand source assets are versioned in `assets/brand/`, with the rejected theme and
  logo explorations preserved under `assets/brand/explorations/` so the decision is
  auditable.
- No `protocol_version` change: this is presentation, not wire format.
