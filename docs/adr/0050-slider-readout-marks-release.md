# ADR-0050: Slider readout, marks, log scale and commit on release

- Status: **Accepted** 2026-11-12
- Date: 2026-11-12
- Deciders: Jian (owner)
- Builds on: ADR-0013 (focus-owned inputs), ADR-0043 (disabled inputs)
- Driven by: a slider-driven cost model in a separate project. The needs are general: any slider
  that feeds a costly recompute, and any parameter that spans decades.

## Decision

All additive and off by default (no `protocol_version` bump, ADR-0005).

1. **`show_value`** adds a readout beside the label, formatted to the decimals of `step`. It follows
   the thumb while dragging (local state, cleared once the server echoes the same value or the thumb
   is let go), so a stale echo does not pull it back.
2. **`scale="log"`**: the native range input runs over 0..400 and the shell maps that to
   `min..max` by powers, rounding to a multiple of `step`. Python refuses `min <= 0`. The server
   value is mapped back to a position by the same rule, so patches and the focused-echo guard still work.
3. **`marks`**: up to 12 `{value, label?}` ticks, each inside `min..max`, drawn under the track as
   spans placed through CSSOM (no style attribute, so strict CSP holds). A custom row was chosen over
   `<datalist>` because browsers do not draw datalist labels on range inputs and it would not map to a log track.
4. **`commit="release"`**: the shell posts `input` on the DOM `change` event (pointer release, or each
   key press) instead of on every `input`. The event name and payload are unchanged, so the server side
   (`Slider.handle`) is the same and an old server or client interoperates.

## Not in scope

Range sliders (two thumbs), a unit suffix, and a debounce for the default mode.
