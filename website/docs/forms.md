# How to validate a form

This guide shows you how to build a form whose submit button is disabled until the input is valid, with an error beside the field and server-side errors for what only your code can know. It assumes you have read the [Quickstart](quickstart.md).

## Build the form

Save this as `invite.py`. It is a complete app: an email field, a role select and a submit button.

```python
import asyncio

import indah
from indah import validators

invited = set()


async def invite(values):
    await asyncio.sleep(0.2)  # stand-in for a call to your own service
    if values["email"] in invited:
        return {"email": "Already invited"}
    invited.add(values["email"])
    status.set(f"Invited {values['email']} as {values['role']}")


status = indah.Signal("")
form = indah.Form(on_submit=invite)
email = form.text(
    "email",
    label="Email",
    validate=[validators.required(), validators.email()],
)
role = form.select("role", options=["viewer", "editor"], initial="viewer")
page = indah.Column(children=[email, role, form.submit("Send invite"), indah.Text(status)])

if __name__ == "__main__":
    indah.launch(indah.create_app(session=indah.Session(page)))
```

Run `python invite.py` and open the printed URL. The button is greyed out and there is no error
on screen yet: a field shows its error once the person has changed it, so a form does not open
covered in red.

Type `ada@` into the email box. The error "Enter a valid email address" appears under it and the
button stays disabled. Finish the address and both clear.

## See the state the page sees

`form.valid`, `form.errors` and `form.values` are computed values, so you can read them in a
test or follow them from the page. Printing `form.valid.value` and `form.errors.value` before
typing, after typing `ada@`, and after typing a full address gives:

```text
start: False {'email': 'Required'}
typed 'ada@': False {'email': 'Enter a valid email address'}
typed full: True {}
```

Note that `errors` holds `Required` from the start even though the page shows nothing. The button
is disabled because of it.

## Report an error only the server knows

`on_submit` may return `{field: message}`. Press **Send invite** twice with the same address.
The first click shows "Invited ada@example.com as viewer". The second puts "Already invited"
under the email field, and it stays there until the person edits the field:

```text
after submit: Invited ada@example.com as viewer
again: {'email': 'Already invited'}
```

To set one from somewhere else, such as a background task, call `form.set_error("email", "...")`.
`form.reset()` puts every field back to its initial value with no errors.

## Choose your own rules

A validator is a function from the field's text to a message, or `None` when the text is fine.
`validators` has `required`, `min_length`, `max_length`, `pattern` and `email`. If a rule is
specific to your app, write a lambda:

```python
form.text(
    "slug",
    label="Slug",
    validate=[
        validators.required(),
        validators.pattern(r"[a-z0-9-]+", "Lowercase letters, digits and dashes"),
        lambda v: "Taken" if v in existing else None,
    ],
)
```

The first failing rule's message is the one shown. The rules run on the server on every change,
so keep them cheap.

## If you do not want a `Form`

`TextInput(..., error=)` and `Select(..., error=)` show a message under the control, and
`Button(..., disabled=)` greys a button. Each takes a value or a function of signals, so you can
wire the same behaviour by hand.

## Things to know

- The server drops a click on an invalid form, so a stale page or a script cannot bypass the
  disabled button.
- A form belongs to one session. Build it in the session factory, as with any signal.
- Not included: a schema-driven form builder, file inputs and multi-step forms. The reasons are
  in ADR-0047.

## Related

- [Components](components.md#inputs) for the inputs a form builds on.
- The Studio page "A form: disabled until valid" (`make demo`) shows the invalid, valid and
  server-error states side by side.
