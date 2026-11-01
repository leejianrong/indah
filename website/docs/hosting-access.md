# Roles, permissions and secrets

How to decide who sees and does what, and how to show a secret once. It assumes identity is set up (see [Identity, sessions and sign-in](hosting-identity.md)).

## Who may do what

Give your roles meaning with an optional `Policy`, and use the permission names in your code:

```python
policy = indah.Policy(
    {
        "viewer": ["entries:read"],
        "editor": ["entries:*"],  # a prefix wildcard
        "admin": ["*"],
    }
)
app = indah.create_app(..., policy=policy)
```

Without a policy, a permission is a role name. Nobody (no principal) holds nothing.

**Omit, do not hide.** Everything in the component tree is sent to the browser, including
components the page never shows, so a button that is merely hidden is still in the page source.
Leave restricted components out of the tree when you build it for that person:

```python
def build(ctx):
    return indah.Session(
        indah.Column(
            children=[
                Overview(),
                *ctx.only("tokens:manage", lambda: TokenScreen()),  # never built for others
            ]
        )
    )
```

`ctx.can("perm")` answers a question and `ctx.require("perm")` raises `indah.Forbidden`.

**Check again where it runs.** The page can be stale: a role may be revoked after it loaded.
`guard` checks when the event arrives, against the person making *that* request (re-authenticated
every time):

```python
Button("Delete", on_click=indah.guard("entries:write")(delete))
```

A refused action answers `403`, shows that tab a "You are not allowed to do that" toast, and does
not run the handler (an `async` handler is refused before it starts). It is not written to the
audit log. Outside a handler there is nobody to authorize, so a guarded call refuses.

Two limits to know. A role *revoked* mid-session stops working for actions at once, but components
already sent stay on screen until the session is rebuilt; a role *added* shows its components after
a rebuild. If that matters, end the user's sessions when roles change
(`store.discard_where(owner=user_id)`). And never read data a person may not see into a signal:
the value would be in the page.

**Workspaces.** A token is bound to the principal's workspace (`ctx.workspace`), so a token from
workspace A is refused once your authenticator says workspace B. Moving someone between workspaces
is your navigation: change what the authenticator returns and reload.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="hosted/policy"></indah-live>

## Showing a secret once

`SecretReveal` shows a new API token with Copy and "I have saved it" buttons:

```python
token = indah.Signal(None)


def create():
    token.set(issue_token())  # call from a handler, after the tab is connected


Column(children=[Button("Create token", create), SecretReveal(token, label="New API token")])
```

The value is an *ephemeral prop*: it goes to the open tab only, and is never put in the `init`
snapshot or the replay history, so a reload, a reconnect or a resume cannot show it again. It is
cleared when the user dismisses it, when the tab reconnects, and when the session closes. If the
connection drops before the user copied it, issue a new one. Store a hash of the token, not the
token. Never put a secret in an exception message: a failing handler's message is shown to the tab
as a toast. The component is marked sensitive, so the audit hook never records its payloads.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="hosted/secret-reveal"></indah-live>
