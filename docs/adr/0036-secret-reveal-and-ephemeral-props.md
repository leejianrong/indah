# ADR-0036: `SecretReveal` and ephemeral props

- Status: Accepted (IND-119)
- Date: 2026-10-22
- Deciders: Jian (owner)

## Context

A hosted dashboard issues API tokens, and a token is shown exactly once. Showing a secret through
an ordinary signal leaks it three ways: the `init` snapshot carries every prop, so any later
reconnect with a fresh snapshot resends it; the hub keeps the last 512 messages for resume
(`Hub._history`), so a resume replays the patch that set it; and a signal keeps its value for the
life of the session. A secret needs to reach one tab, once, and then be gone.

## Decision

- **Ephemeral props.** A `Component` may declare `ephemeral = frozenset({"value"})`. For those
  props:
  - `to_json()` (the snapshot) leaves them out;
  - a patch that sets one to a value is split from the rest of its change and published with
    `Hub.publish(..., record=False)`: it reaches the live subscribers, takes an SSE offset, and
    never enters the replay history (a resume skips the offset). The same split applies on the
    synchronous path (`DispatchResult.transient`, published by the route) and on the live path
    (`Session.emit_props`);
  - setting one to `None` (clearing it) carries no secret and is recorded like any patch, so a
    tab that was offline when the user dismissed it is told on resume.
- **Forget.** `Component.forget()` (a no-op by default) drops a held secret. `Session` calls it
  for every ephemeral component on `close()` and whenever a tab connects with a fresh `init`,
  because that snapshot cannot carry the value and nothing is left to show it. The consequence
  is that a secret must be set from a handler, after the tab is connected, not while the tree is
  built; and a tab that drops before the user copies it loses it, and the user issues a new one.
- **`SecretReveal(value: Signal[str | None], *, label="", on_dismiss=None)`.** Shows the value in
  a monospace box with Copy (the Clipboard API, falling back to selecting the text on an insecure
  origin) and "I have saved it". Dismissing clears the signal and then calls `on_dismiss`. The
  component is `sensitive`, so the audit hook (ADR-0034) never records its payloads.
- **Secrets stay out of messages.** A failing handler's exception text is echoed to the tab as a
  toast, so an exception must never contain a secret. This is documented, not enforced.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Show it in a `Text` and clear it later | In the snapshot and the replay history until cleared; a reconnect before clearing resends it. |
| Skip the offset for an unrecorded patch | A client then sees two different messages with one offset, and resume gap detection gets harder. An unused offset is harmless. |
| Encrypt the secret in the snapshot | The key would have to reach the browser. Not delivering it is simpler and stronger. |
| Keep it until dismissed, across reloads | Contradicts "shown once"; it would sit in server memory for a tab that cannot show it. |

## Consequences

- The secret exists in server memory only between being set and the next dismiss, reconnect with
  a snapshot, or session close, and in the browser DOM until dismissed. It is not logged by
  indah. Two tabs share nothing: a session is per tab.
- A third-party client sees an absent `value` prop and nothing else; no new message type, so
  `protocol_version` stays 1.
- `Component` gains `ephemeral` and `forget()`; `Hub.publish` gains `record`; `DispatchResult`
  gains `transient`.
