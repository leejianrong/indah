# ADR-0030: Overlays, toasts, shortcuts and small controls

- Status: Proposed (overlays and `Button(confirm=)` in IND-94; toast, Badge/Switch/tooltip, Shortcuts and row actions follow in IND-95..99)
- Date: 2026-10-20
- Deciders: Jian (owner)

## Context

The semula dashboard (`docs/SEMULA-REQUESTS-PLAN.md`, E5) needs approve, reject and delete
flows: a drawer opened from a table row, a confirmation before a destructive click, feedback
after a handler runs, and keyboard shortcuts. indah has only an error toast.

## Decision

- **Overlays are components with an `open` signal.** `Modal(children, open=, title=, size=,
  on_close=)` and `Drawer(children, open=, side=, title=, on_close=)` share one shell
  component. The shell renders the children only while `open`, so mounting is opening. Esc,
  a backdrop click and the close button post `close`; the server clears `open` and runs
  `on_close` (sync or async). The app can also close one by setting the signal.
- **Accessibility is part of the contract:** `role="dialog"`, `aria-modal`, a label from
  `title`, focus moves in on open, Tab and Shift+Tab are trapped, Esc closes, and focus
  returns to the element that had it. Tested keyboard-only in the browser e2e.
- **`Button(confirm="...")`** is a static prop. The shell shows a small modal (Cancel focused
  by default) and posts `click` only when the user accepts. It is a UX guard, not
  authorization: the server runs any `click` it receives, so a destructive handler must
  still check permission itself (H3).
- **One overlay at a time.** Stacking modals is out of scope; a confirm inside an open
  drawer is the one nesting that works, because focus restoration is a stack of openers.
- **Closed overlays stay in the tree**, so their props are in the snapshot. They are not
  for secrets.
- **Additive wire change** (ADR-0005 amendment): new component types `modal` and `drawer`, a
  new `confirm` prop and a `close` event. No `protocol_version` bump.

Toasts, `Badge`, `Switch`, `tooltip=` and `Shortcuts` extend this ADR as they land.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Native `<dialog>` with `showModal()` | Gives focus trap and Esc for free, but Safari/Firefox focus-return and backdrop-click handling differ, and a drawer needs custom layout anyway. One hand-rolled layer is predictable. |
| Server-side confirm (a second Button revealed by a signal) | Works today (the plan's workaround) but costs a round trip and a signal per button. |
| Stack of overlays | Needs z-order and per-layer Esc routing for no stated use. |

## Consequences

- Every destructive button can ask first with one argument.
- The shell grows one component (`Overlay.svelte`).
- Because `confirm` is client-side, a scripted client can bypass it; do not rely on it for safety.
