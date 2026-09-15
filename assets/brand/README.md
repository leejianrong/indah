# indah brand assets

The visual identity for indah, part of the **abang-ai** suite. Decided in the
post-MVP planning round (2026-09-15); see `docs/adr/0014-design-system-and-identity.md`.

## Logo — "Bunga"

A four-petal bloom: two magenta petals (vertical), two teal (horizontal). *indah*
means "beautiful" in Malay, so the mark is the soft, floral counterpoint to the
suite's angular ketupat — same minimalism and warm palette, curvy instead of woven.

| File | Use |
|------|-----|
| `indah-mark.svg` | Primary two-tone mark (magenta + teal). Shell header, docs logo. |
| `indah-mark-mono.svg` | Single-colour via `currentColor`; inherits text colour. |
| `favicon.svg` | Favicon (transparent tile; reads on light and dark tabs). |

The **wordmark** is the text "indah" set in **Bricolage Grotesque** 700, letter-spacing
`-0.03em`, in a single ink colour (never split or multi-coloured). Pair it with the
mark to its left for the lockup.

## Theme — "Studio"

The shell's default theme (`docs/adr/0014-...`). Warm porcelain ground, bougainvillea
magenta primary, deep teal secondary; Bricolage Grotesque display over IBM Plex Sans,
IBM Plex Mono for data.

| Token | Light | Dark |
|-------|-------|------|
| primary (magenta) | `#b5296b` | `#f06ca6` |
| secondary (teal) | `#2e6d62` | `#66b7a6` |
| background | `#faf6f0` | `#191319` |
| surface | `#fffdf9` | `#221b22` |
| text | `#241c22` | `#f1e7ee` |
| muted | `#6e6169` | `#bda9b6` |
| outline | `#e0d4c6` | `#4a3d48` |

The full token set and the theming mechanism (a theme is a CSS custom-property set on
the pre-built shell — no rebuild per theme) are specified in ADR-0014. Only Studio
ships as the baked default for now; a user-selectable theme switcher is deferred.

## Explorations

`explorations/` preserves the interactive proposals the identity was chosen from, so
the rejected directions are not lost:

- `theme-studio.html` — the three theme directions (Sistem / Studio / Precision) on the
  real component set, light/dark.
- `logo-studio.html` — the logo options (Bunga / Kuntum / Pusaran / Daun), light/dark,
  with mono and favicon sizes.

Open either file in a browser. They are design mockups, not the live Svelte shell.
