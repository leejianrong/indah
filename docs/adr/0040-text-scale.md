# ADR-0040: Plain `Text` is body text; a small named scale

- Status: **Accepted** (2026-10-24, owner). The owner first decided on 2026-10-22 that default `Text` looks
  like normal body text and the old look becomes opt-in, then accepted the rest (the scale values, the
  variant names, no inline markup in plain text) on 2026-10-24.
- Date: 2026-10-22
- Deciders: Jian (owner)
- Builds on: ADR-0014, ADR-0031. Folds IND-155.

## Context

`Text("...")` renders as a 1.4rem semi-bold readout, made in the first slices for a counter or a
figure. Everything else people write with it, a label, a status line, a note, comes out looking like
a heading, and backticks show literally. 0.4.0 added `Text(size="body")` as a workaround. The semula
request (R2-11) and the gallery both hit it. Making it right changes how every app looks, so it needs
a decision, not a patch.

## How other systems handle text

| System | Default | Named scale | Notes |
|--------|---------|-------------|-------|
| Plain CSS / browser (and Svelte, which has no text component) | `<p>` and bare text are body size and weight | Headings are separate elements, `h1` to `h6` | The body is the default; emphasis is `<strong>`, `<em>`, `<code>` markup |
| MUI `Typography` | `variant="body1"` | `h1`-`h6`, `subtitle1/2`, `body1/2`, `button`, `caption`, `overline` | A `variant` picks size, weight and spacing, and a separate `component` picks the tag. Many variants |
| Chakra UI `Text` | Body (the theme's base font size) | Sizes from a token ladder (`xs` to `9xl`), `Heading` is a separate component | Size and weight are style props, not roles |
| Tailwind | Unstyled body | Utility classes `text-xs` to `text-9xl`, `font-*`, `leading-*` | No components: the default is plain body text, a size is a class you add |
| Material Design 3 | Body (medium) | Five roles, three sizes each: display, headline, title, body, label | Roles carry intent; a size within a role is the choice |

What they agree on: the **default is body text**; a figure or heading is something you ask for;
headings and body are different things. They differ in how many names they offer. MUI and Material
carry a dozen or more, which is far more than indah apps need. Chakra and Tailwind expose raw sizes,
which leaks the scale into every call. A role vocabulary (Material, MUI) is the better fit for a
Python API: the author says what the text *is*, and the design system decides how it looks, so a
theme can change it later.

## Decision

1. **`Text(source, variant="body")`.** The default is body text: 0.95rem, weight 400, line height
   1.55, the app's text colour. This is the owner's decision and the one thing that is final.
2. **Six variants, no more:**

   | variant | Use | Look |
   |---------|-----|------|
   | `body` (default) | Paragraphs, status lines, notes | 0.95rem, 400, 1.55 |
   | `title` | A heading for a block that is not Markdown | 1.3rem, 600, 1.3 |
   | `label` | The name of a field or a group | 0.85rem, 500, muted |
   | `caption` | Help text, timestamps, fine print | 0.78rem, 400, muted |
   | `mono` | Identifiers, paths, numbers that must line up | the mono font, 0.88rem, 400 |
   | `readout` | A counter or a figure | 1.4rem, 600, tabular numbers (today's look) |

   Sizes are on the existing ladder (0.78, 0.85, 0.95, 1.3, 1.4rem), so no new token layer and no
   new sizes (ADR-0031 says the shell has literals on a short ladder, not scale tokens). The values
   are Proposed for owner review. An unknown `variant` raises `ValueError` at construction.
3. **Line breaks.** Every variant except `readout` keeps newlines (`white-space: pre-line`: runs of
   spaces collapse, line breaks stay), so a multi-line string reads as written without an indented
   triple-quoted string leaking its indentation. `mono` uses `pre-wrap`, since aligned columns are its
   point. `readout` stays a single line.
4. **No inline markup in plain text.** Plain `Text` does not interpret backticks, `*` or `_`. Markup
   is `markdown=True`, which is parsed on the server into a safe block tree. The comparison does not
   argue for more: every system above makes inline emphasis explicit (an element, a component), and
   interpreting markup in a plain string would make a stray `*` or a user-supplied value change the
   output. `markdown=True` takes no `variant` (it has its own heading scale).
5. **`size=` stays as an alias**, so 0.4.0 code works: `size="body"` is `variant="body"`,
   `size="readout"` is `variant="readout"`. Giving both with different meanings raises
   `ValueError`. It is documented as deprecated in favour of `variant`, and not removed before 1.0.
6. **Wire.** A `variant` prop is sent only when it is not `body`; the `size` prop is no longer sent.
   The shell reads `variant` and treats a missing one as body. `protocol_version` stays 1: this is a
   change to what a default *looks like*, not to the wire format, and the shell is bundled in the
   same wheel as the backend.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Keep the readout default and tell people to write `size="body"` | Every plain string looks like a title. The owner decided against it. |
| A `size=` ladder like Chakra and Tailwind (`xs` to `xl`) | Leaks raw sizes into every call and cannot carry intent (a label is not just small). |
| More variants (`h1`-`h6`, `subtitle`, `overline`, `button`) | `markdown=True` already has headings; the rest is not needed by any app so far. A variant can be added later without breaking anything. |
| Parse backticks and emphasis in plain text | See decision 4. |
| A separate `Heading` component | A `title` variant covers it with one component and one wire type. |

## Consequences

- **This changes every app.** Plain `Text` shrinks from a 1.4rem semi-bold readout to 0.95rem
  regular text. Text used as a number or a figure must say `variant="readout"`. The CHANGELOG has an
  Upgrading note with that line and a way to find them (search for `Text(` where the source is a
  count, a metric or a short value).
- Studio pages, examples and the docs that used plain `Text` as a readout are updated to the opt-in
  in the same change. The public gallery and the landing page are reviewed afterwards (IND-172).
- The design-system page gains a type table; `size="body"` stays working.
- Future roles (a larger display size, an `overline`) are additive variants.
