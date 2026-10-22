# Design system

indah ships one look, called **Studio**, and styles every component through a small set of
named design tokens (CSS custom properties). You never restyle a component. You change a
token, and every component that uses it follows. This page is the contract: what the tokens
are, what each is for, and how to override them.

The role names follow Material Design 3 (primary, on-primary, container, outline, surface),
because that vocabulary is well understood. The values and the look are indah's own: warm
porcelain, bougainvillea magenta, deep teal.

## Overriding tokens

```python
indah.create_app(
    theme=indah.Theme(
        light={"primary": "#1f6feb"},
        dark={"primary": "#79b8ff"},
        radius="8px",
        font="system-ui, sans-serif",
    ),
    density="compact",
)
```

Only the colour roles below can be overridden, per scheme (`light` and `dark`). `radius` and
`font` apply to both. An unknown token name raises an error, so a typo cannot pass silently.
If you override a `*-container` role, also override its `on-*-container` partner so the text
stays readable. The Bunga logo is brand identity, not a theme role: a theme never recolours
it. To use your own mark, pass `logo=`. A mark that vanishes on one background needs a pair:
`logo=(light_mark, dark_mark)` shows the one that matches indah's light/dark toggle (an SVG that
relies on `currentColor` does not work, since the logo is shown in an `<img>`).

### Your own tokens

An app can add roles the core set does not have, such as a row-hover fill or a status colour.
Name them `x-<name>` and pass them per scheme; they are emitted as `--x-<name>` for your CSS
to read (a custom component's styles, for example).

```python
indah.Theme(
    extra_light={"x-brand": "#b5296b", "x-row-hover": "rgba(0, 0, 0, 0.04)"},
    extra_dark={"x-brand": "#ff7ab6", "x-row-hover": "rgba(255, 255, 255, 0.06)"},
)
```

Define a token in both schemes if it should differ, because one set only in `extra_dark` has no
value in light. Values are checked like any other theme value. The core roles stay a closed
set: `Theme(light={"x-brand": ...})` raises, and so does an extra that does not start `x-`.

The page frame is 1080px wide at most. `create_app(max_width="none")` lets it fill the window
(a dashboard with a left rail wants this), and `max_width="1400px"` or `"90rem"` sets another
cap. Anything else raises an error. It is applied as the `--page-max` token.

The browser tab reads `"<title> - indah"` when you pass `title=`. Pass `title_suffix=""` for
the exact title (`title="semula", title_suffix=""` gives `<title>semula</title>`), or any other
suffix such as `" | Semula Ops"`.

## Colour roles

Every role is defined for light and dark. Use a role by its job, never by its hex value.

| Token | Job |
|-------|-----|
| `bg` | the page background |
| `surface` | cards, panels, dialogs, popovers |
| `surface-2` | inputs, table headers, hover fill, quiet wells |
| `surface-3` | pressed or selected fill, tooltips, the strongest neutral |
| `text` | primary text |
| `muted` | secondary text, labels, placeholders |
| `outline` | borders of inputs, buttons and cards |
| `outline-soft` | hairlines: table rules, dividers |
| `primary` / `on-primary` | the main action (filled button) and text on it |
| `primary-container` / `on-primary-container` | a soft primary fill (selected row, info badge) and its text |
| `secondary` / `on-secondary` | the second accent and text on it |
| `secondary-container` / `on-secondary-container` | a soft secondary fill (tonal button) and its text |
| `ok`, `warn`, `err` | status colours, used for text and for tinted badges |
| `shadow` | the one elevation shadow |

The rules:

1. Every filled role has an `on-` partner. Put `on-primary` text on `primary`, never `text`.
2. Status is never colour alone: pair it with a word or an icon.
3. A new component uses existing roles. Adding a role is a design decision, recorded in an
   ADR, not a one-off in a component.

## Shape, type, spacing

| Token | Value | Use |
|-------|-------|-----|
| `radius` | 14px | cards, dialogs, panels |
| `radius-sm` | 10px | inputs, buttons inside dense UI, images, tooltips |
| `radius-pill` | 24px | chips and pills |
| `radius-control` | `radius-pill` | buttons and badges; `Theme(radius=)` sets it, so a squarer theme squares them too |
| `font-display` | Bricolage Grotesque | headings and the wordmark |
| `font-body` | IBM Plex Sans | body text and controls |
| `font-mono` | IBM Plex Mono | ids, numbers, table headers, code |

Body text is 15px. Small text steps down through 0.95, 0.85, 0.8 and 0.75rem, and no
component should invent a size outside that ladder. Spacing is in `rem`, on a quarter-rem
grid (0.25, 0.5, 0.75, 1, 1.5).

### Density

Tables read four tokens: `--row-h`, `--cell-pad-y`, `--cell-pad-x` and `--table-font`.
`density="comfortable"` (the default) and `"compact"` swap the whole set, for the app or for
one `Table(density=)`.

## Interaction states

| State | Treatment |
|-------|-----------|
| hover | a subtle fill change (`surface-2`) or `brightness` on filled buttons |
| pressed | the button moves 1px down |
| focus (keyboard) | a 2px `primary` outline, offset from the control. Inputs get a soft `primary` ring |
| disabled | `muted` text at reduced opacity. Only unavailable download links use it today; buttons have no disabled state yet |
| selected | `primary-container` fill |

Focus is always visible for keyboard users, and every control is reachable with the keyboard.

## Layers

Overlapping surfaces stack in a fixed order, so two components never fight over `z-index`.

| Layer | `z-index` |
|-------|-----------|
| sticky table header | 2 |
| column menu | 5 |
| modal and drawer | 50 |
| toasts (bottom centre) | 60 |
| tooltips | 70 |

Modals and drawers are centred and right-edge, and toasts sit at the bottom centre. A
tooltip opens at the pointer on hover and under the control on keyboard focus.

## Motion

Transitions are short (0.15s) and limited to colour, border and a 1px press. Anything that
loops, such as the spinner, slows down under `prefers-reduced-motion`.

## What this is not

indah is not stock Material 3. It borrows the role vocabulary and the discipline (every colour
has a job, every surface has an elevation, every state is defined) and leaves out the rest:
there is no dynamic colour, no state-layer opacity scale and no type-scale tokens. If
that changes, it changes here first.
