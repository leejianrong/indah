# ADR-0013: Focused inputs are owned by the client

- Status: Accepted
- Date: 2026-09-15
- Deciders: Jian (owner)

## Context

indah's inputs are two-way bound. When you drag a slider or type in a text box,
the shell POSTs the new value, the server writes it into a signal, and the reactive
core emits a patch that carries the value back to that same node. The shell bound
the DOM element's value straight to that patch, so the element always reflected
server state. On localhost this is invisible: the round trip is a millisecond, and
the value that comes back is the value you just sent.

Over a real proxy it falls apart. The first Colab runs of `0.1.0rc1` showed it
plainly once the transport itself was fixed (ADR-0002): typing quickly dropped
letters, and dragging the slider made the thumb jitter and snap backwards. The
cause is a feedback loop between the user and a laggy echo. Say you type `h`, `e`,
`l`. Each keystroke posts, but the echoes come back a beat late. While the box
already shows `hel`, the echo for `h` arrives, the shell sets the DOM value back to
`h`, the cursor jumps to the end, and your next keystroke lands on stale text. The
faster you type relative to the round trip, the more the echo clobbers what you are
doing. The slider is the same story with a single number: a stale echo yanks the
thumb back to where it was two frames ago.

The round trip got heavier, not lighter, once we added the per-frame flush padding
that Colab's buffering needs (ADR-0002), so the effect was worse on the exact
platform we care about most.

## Decision

While a value-bearing input has focus, the DOM owns its value and the shell ignores
server echoes for it. The moment focus leaves (including on `blur`), the element
adopts whatever value the server settled on, so two-way binding stays intact for
everything that isn't the live edit in progress.

Concretely, in `Node.svelte`: the text box and slider bind to an element reference
rather than reactively to `props.value`. An effect writes the server value into the
element only when `document.activeElement` is not that element, and a `blur`
handler syncs it once editing ends. A signal changed from anywhere else still
flows to the input the usual way, as long as the user isn't holding it at that
moment.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Debounce the client's input events | Cuts the echo traffic, which is worth doing, but doesn't fix the race on its own: a single late echo can still clobber. It also delays server state, so a handler that reads the value right after typing (clicking Generate) can miss the last keystrokes unless we also flush on blur. Left as a later optimisation. |
| Don't echo a value back to the node that originated it | Fixes the common case at the source and saves the wasted patch, but the server has to track which node caused the change, and any *other* dependant of that signal still needs the update. A cleaner follow-up, not the minimal fix. |
| Make inputs fully uncontrolled (never sync from the server) | Simple, but then a programmatic change to a signal would never reach its input, breaking a real feature (a reset button clearing a field). |

## Consequences

- Fast typing and slider drags are smooth again: the user's edits are never
  overwritten by an echo of their own earlier value.
- The trade is that a value changed by *someone else* while you're editing the same
  field won't appear until you blur. For a single-user dev tool (Q-sec, Q-concur)
  that's the right call; per-session isolation and any multi-writer story come later
  (ADR-0010), and this rule is compatible with both.
- It doesn't reduce echo traffic. Each keystroke still round-trips and still carries
  the ~8 KB flush pad from ADR-0002. Debouncing the client and skipping the
  echo-to-origin are the two follow-ups that would cut that, and both compose with
  this decision rather than replacing it.
- Guarded by two end-to-end tests that deliver a server change to a focused input
  and assert it survives, then that it's adopted on blur (`tests/e2e/test_browser.py`).
