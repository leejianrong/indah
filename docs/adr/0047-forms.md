# ADR-0047: A form helper: disabled until valid, errors beside the field

- Status: Accepted (IND-241)
- Date: 2026-11-01
- Deciders: Jian (owner)

## Context

A text box, a select and a button are three unrelated signals, so there is no "Send is disabled
until the email looks like one", and a validation message is a line of `Text` far from the field.
semula's invite, token and signup screens all want this. The reactive core already has what a
form needs (signals, computed values, a button that runs a handler); what is missing is a place
to put the rules, and two small things in the shell: a button that can be disabled, and an error
line under an input.

## Decision

A `Form` groups inputs, takes a validator per field, exposes `valid` and the error text, and
makes one submit button that is disabled while the form is invalid. It builds ordinary
components, so layout is the app's own and nothing about standalone inputs changes.

```python
form = indah.Form(on_submit=invite)               # invite(values) -> None | {field: message}
email = form.text("email", label="Email", validate=[indah.validators.required(),
                                                    indah.validators.email()])
role = form.select("role", options=["viewer", "editor"], initial="viewer")
page = indah.Column(children=[email, role, form.submit("Send invite")])
```

- **Validators are plain functions** `str -> str | None` (the message, or `None` when fine). A
  validator that raises counts as invalid with the message "Invalid". `indah.validators` has
  `required`, `min_length`, `max_length`, `pattern` and `email` and nothing else; anything else is
  a lambda.
- **`form.text(name, ...)` and `form.select(name, ...)`** return a `TextInput` / `Select` bound to
  a signal the form owns (`initial=` seeds it). They gain a reactive `error` prop.
- **`form.valid`** (a `Computed[bool]`), **`form.values`** (a `Computed[dict[str, str]]`) and
  **`form.errors`** (a `Computed[dict[str, str]]`, the current error of every invalid field)
  read like any other signal, so a summary line or another button can follow them.
- **When an error shows.** Not on load. A field shows its error once its value has changed at
  least once (even back to `initial`). So an empty required field is silent until the person has
  touched it, while the submit button is already disabled.
- **`form.submit(label)`** returns a `Button` whose new `disabled` prop is true while the form is
  invalid or a submission is running. The server drops a click while the button is disabled, and
  the submit handler checks `valid` again before it calls `on_submit`, so a crafted click cannot
  submit an invalid form.
- **Submitting.** `on_submit(values)` (sync or async) gets the values dict. It may return
  `{field: message}` to put a server-side error beside a field ("already invited"). Such an error
  stays until that field's value changes. `form.set_error(name, message)` does the same from
  elsewhere, `form.reset()` restores every `initial` and clears errors, and `form.submitting` is a
  `Signal[bool]`.

Wire changes are additive, so `protocol_version` stays 1: `Button` gets an optional reactive
`disabled` (sent only when the button was given a source for it), and `TextInput` / `Select` an
optional reactive `error` (sent only when given). An older shell ignores both props, so the form
still validates on submit, it just does not grey the button or show the text.

## Leaves out

A schema-driven form builder, nested or repeated fields, file inputs, multi-step forms, async
validators, cross-field validators other than reading `form.values` yourself, and any validation
in the browser: every rule runs on the server, on each change, in the same round trip as the
input event. Fields other than text and select (a slider, a switch) can still sit beside the form;
they are not part of it.

## Alternatives considered

| Option | Why not |
|--------|---------|
| `error=` and `disabled=` on the components only, no `Form` | Every app would rewrite the same touched-state and submit guard |
| Validators that run in the browser | Needs a second implementation of every rule, and a rule that matters has to run on the server anyway |
| A form schema (dict or dataclass) that renders itself | A form builder is out of scope, and it takes layout away from the app |
| `Form` as a layout component with children | Forces one layout; a plain object that hands back components does not |

## Consequences

- No new component type, so no new shell code beyond a disabled attribute and an error line.
- Every keystroke runs the field's validators on the server. They must be cheap and synchronous.
- `Form` is per session (build it in the session factory), like any signal.
