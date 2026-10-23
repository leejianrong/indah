# ADR-0030: Overlays, toasts, shortcuts and small controls

- Status: Accepted (overlays IND-94, toast IND-95, small controls IND-96, shortcuts IND-97, table actions IND-99; demo IND-100)
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

- **Toasts (IND-95).** `ctx.toast(message, kind=, ttl=)` publishes a new `toast` message on
  the session's own hub, so it reaches only that session's tabs (a shared-store app shares
  its one hub). The shell keeps a stack of up to four; the existing handler-failure `error`
  message is shown through the same stack as an `error` toast. `ttl=0` stays until clicked.
  A toast is ephemeral by design: it is not replayed to a fresh connection, and secrets
  must not go in one. Like a signal write it must be called on the event loop.

- **Small controls (IND-96).** `Badge(text, tone=)` is a status chip (same tones as a Table
  badge cell), `Switch(signal, label=)` a `role=switch` two-way bool. `tooltip=` works on
  **every** component: `Component.__init_subclass__` wraps each subclass constructor to accept
  it, so custom subclasses get it too (type checkers will not see the kwarg). The prop rides
  `props.tooltip` and the shell wraps the node in a box-less tooltip. `badge` and `switch`
  are now reserved built-in type names, so `register_component("badge")` is rejected.

- **Shortcuts (IND-97).** `Shortcuts({spec: fn | (fn, label)})` is an invisible node: the
  shell listens while it is mounted (so a map inside a tab is scoped to that tab), posts
  `press {keys}`, and the server runs the handler. Specs are canonicalised by `indah.keys`
  and the shell tokenises key events the same way. Sequences (`g l`) time out after 1 s;
  a broken sequence restarts from the key that broke it. Bare keys and sequences are ignored
  in inputs; `mod+`/`alt+` combos fire in inputs; nothing fires under a dialog. `?` opens a
  help overlay built from the labels of every mounted map. Not user-rebindable.

Table row actions and multi-select (IND-99) are recorded in ADR-0027.

**Key routing for focused widgets (IND-164, note).** A widget that owns keys while it has focus
(the keyboard-navigable `Table`; the `CommandPalette` of IND-165 follows the same rule) obeys
these, in this order:

1. It acts only on key events whose target is the widget itself, never on keys typed in an input,
   textarea or button inside it, and never on a key with `ctrl`, `meta` or `alt` held. `mod+`
   combos always belong to `Shortcuts`.
2. When it handles a key it calls `preventDefault()`. `Shortcuts` already skips a defaulted event,
   so a bare `j` moves the table's row when the table has focus and fires the `Shortcuts` `j`
   binding anywhere else. The focused widget is the more specific context, so it wins.
3. It never traps: Tab moves on and Escape blurs it (WCAG 2.1.2).
4. A widget's keys are opt-in (`Table(keyboard=True)` or `on_open=`), so an existing page's key
   behaviour does not change when the shell is upgraded.

**Menu (IND-161, note).** `Menu(trigger, items)` is the ARIA menu button: `role="menu"` and `menuitem`,
`aria-haspopup`/`aria-expanded`, arrows (wrapping), Home/End, a typeahead letter, Escape to the trigger, Tab
closes and moves on. It follows the key-routing rule above (acts only on keys from the trigger or an item,
defaults every key it handles, never traps). The popup is moved to `<body>` and placed in viewport
coordinates, because an ancestor with a transform (the AppShell drawer) or an overflow would move or clip a
`position: fixed` child; it closes on an outside click, a scroll or a resize rather than drift from its
trigger. An item is chosen by id (`key=`, else the label) against the *current* items, so a stale click does
nothing; `confirm=` reuses the Button confirm dialog. The wire adds the `menu` type and a `select {item}`
event (additive). Omitting an item for a principal is the app's job with `ctx.only`, as for any component.

**CommandPalette (IND-165, note).** `CommandPalette(commands, shortcut="mod+k")` and `Command(label, on_run | to,
group=, shortcut=, keywords=, confirm=, key=)`. The palette is its own window listener for its shortcut (so it
opens with no round trip), not a `Shortcuts` entry; it lists the key in the `?` help overlay. It follows the key
routing rule: it skips a key someone already handled, never opens over another dialog, ignores a bare key typed
into a field (a `mod+`/`alt+` combo still opens it), and defaults every key it handles. Once open it is a modal
dialog (`role="dialog"`, a combobox over a listbox with `aria-activedescendant`); Tab stays inside and Escape or
the shortcut closes it, which is the way out (WCAG 2.1.2), and focus returns to what had it. Filtering is client
side over the list the server sent, in a fixed order (label prefix, word prefix, substring, subsequence, then
keywords and group; ties keep the given order). Only `run {command}` reaches the server, and it is matched to the
*current* commands by id, so an omitted, stale or forged id does nothing. A jump (`to=`) calls `ctx.navigate`, so
a palette with one needs `ctx=`. The wire adds the `commandpalette` type and a `run` event (additive).

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
