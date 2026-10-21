# ADR-0031: The indah design framework

- Status: Accepted
- Date: 2026-10-21
- Deciders: Jian (owner)
- Builds on: ADR-0014 (design system and identity)

## Context

ADR-0014 set the Studio look and a token layer, and said the role architecture "follows
Material 3". The semula work then added components fast (overlays, tables, panes, viewers,
toasts, tooltips) and the owner asked two things during the visual review: take the good and
relevant parts of Material 3, not all of it, and write our own framework down so components
stay consistent.

The review also turned up exactly the drift a written contract prevents: `type=search` inputs
missed the shared input styling and rendered square, a sticky table header leaked rows because
a component chose its own border model, the default logo recoloured itself with the app theme,
and a tooltip positioned itself by a rule that only worked for small elements.

ADR-0014 also overstated things. It listed type scale and state-layer opacities as part of
the token layer. The shell has neither: sizes are literals on a short ladder, and states are
per-component rules.

## Decision

1. **The framework is documented in one place**: `website/docs/design-system.md` (the
   published page) is the source of truth for token names, jobs, shape, type, density, states,
   layers and motion. This ADR records why. Where they disagree with the shell, the shell
   wins and the page is fixed.
2. **Adopt from Material 3**: role-based colour with an `on-` partner for every filled role
   (adds `on-primary-container` and `on-secondary-container`), light and dark schemes, a
   container role for soft fills, visible keyboard focus, a fixed elevation and layer order,
   and tokenised shape and density.
3. **Do not adopt**: dynamic colour, a tonal-palette generator, state-layer opacity tokens,
   or a full type-scale token set. Studio's own look stays. Adding any of them needs a
   superseding ADR.
4. **Brand is not a theme role.** The Bunga mark uses `--brand-a` and `--brand-b`, which
   `Theme` cannot override. An app that wants its own mark passes `logo=`.
5. **Components consume tokens only.** A new component uses existing roles, radii, font
   stacks and layers. A new colour role, radius or layer is a design decision recorded here
   or in a later ADR. Form controls share one rule block, so a new input type is added to it.
6. **A test guards drift** (`tests/unit/test_design_tokens.py`): light and dark define the same
   tokens, every token `Theme` accepts exists in the shell, and every colour token is named
   in the published page.

## Consequences

- One page to point a contributor or a semula designer at, and a failing test when a token is
  added without documenting it.
- `Theme` accepts two more tokens. An app that overrides a `*-container` role should override
  its `on-` partner too. The page says so.
- The tonal button and the info badge now take their text from the `on-*-container` roles, so
  their text colour changed slightly. No wire change, no `protocol_version` bump.
- Known gaps, recorded rather than hidden: states are still per-component rules, text sizes
  are literals on a ladder, `Modal` has no position option, and `Button` has no disabled state.
