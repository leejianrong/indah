# ADR-0035: Authorization: omit at build time, guard at dispatch

- Status: Accepted (IND-118)
- Date: 2026-10-22
- Deciders: Jian (owner)

## Context

With identity in place (ADR-0033) a hosted app has viewers, editors and admins. indah does not
own the roles or the policy (semula's core does), but it must make the safe thing the easy thing.
Two facts shape the design. Everything in the component tree is sent to the browser: the `init`
snapshot and every later patch carry a component's props whether or not the shell shows it, so
"hidden" is not "protected". And a session outlives a role change: a tree built for an editor is
still on screen after the identity provider demotes them.

## Decision

- **A permission is a role name, or something a `Policy` grants.** `Principal.roles` already
  exists. `create_app(policy=Policy({"viewer": ["entries:read"], "editor": ["entries:*"],
  "admin": ["*"]}))` maps roles to permissions; `"*"` grants all and `"entries:*"` a prefix. With
  no policy, `ctx.can("admin")` simply asks whether the user has the role `admin`. Policy
  authoring is not indah's job and there is no UI for it.
- **`ctx.can(perm)`, `ctx.require(perm)`, `ctx.only(perm, build)`.** `can` is a boolean;
  `require` raises `Forbidden`; `only` returns `[build()]` or `[]`, so a restricted component is
  never constructed for someone who may not see it. No user, an empty permission name and an
  unknown role all mean "no".
- **Omit, do not hide.** The rule for restricted UI is to leave it out of the tree when the tree
  is built for that principal. There are deliberately no `visible=` or `disabled=` props: they
  would invite exactly the mistake the rule exists to prevent. (`Button(disabled=...)`-style
  affordances stay UX only and are documented as not a control.)
- **`guard(perm)(handler)` re-checks at dispatch.** The check runs when the event arrives,
  against the principal of *that request*, which is re-authenticated every time (ADR-0033). A
  `ContextVar` carries it into the handler, and into any task the handler spawns (a task copies
  the context when it is created). `ctx.can`/`ctx.require` read the same scope when called from a
  handler, and fall back to `ctx.user` while the tree is built. So a role revoked since the page
  loaded fails the next action. The wrapper is a plain function that checks first and then calls
  the handler, so an `async` handler is refused *before* its coroutine exists and the request can
  answer `403`. Outside any dispatch there is no principal, and a guarded call refuses.
- **A refusal is a `403`, a warning toast and no audit entry.** A handler that raises `Forbidden`
  (from `guard` or `ctx.require`) makes `POST /api/event` and `POST /api/upload` answer `403`
  and sends the tab a "You are not allowed to do that." toast, with no stack trace in the log
  (it is a refusal, not a bug). A refused event is not audited, in line with ADR-0034 (rejected
  requests are the access log's job). An `async` handler that raises `Forbidden` after its first
  await has already been accepted, so it gets the toast only.
- **Sessions are workspace-scoped.** A session token is signed over the principal id and
  `Principal.workspace` (ADR-0033), so a token for workspace A does not verify when the
  authenticator now says workspace B: `403`, nothing created, and a fresh login gets a fresh
  session. `ctx.workspace` exposes it. Moving a user between workspaces is the parent app's
  navigation (it changes what the authenticator returns); indah does not offer a switch call.

## Alternatives considered

| Option | Why not |
|--------|---------|
| `visible=`/`disabled=` props that hide a component | The component and its props are still in the snapshot and the patches. Easy to mistake for a control. |
| Check the role once, when the session is built | A revoked role would keep working for as long as the tab stays open. |
| Rebuild or discard the session when roles change | The open stream has nothing to tell the tab (there is no "reload" message), and a forced rebuild would lose state; the guard already makes the action safe. The parent app can end sessions with `ctx.sign_out()` or `store.discard_where(owner=)`. |
| A policy DSL (resources, conditions) | semula's core owns authorization. indah supplies the mechanism and a small role-to-permission map. |

## Consequences

- A role *added* mid-session does not show the newly allowed components until the session is
  rebuilt (a reload keeps the session by design, ADR-0033); a role *revoked* mid-session stops
  working for actions at once but leaves the already-sent components on screen until then. If
  that matters, end the user's sessions when roles change.
- Restricted data must not be read into a signal for a user who may not see it, for the same
  reason a component is omitted: a signal's value goes out in the snapshot.
- `Policy`, `Forbidden` and `guard` are exported from `indah`; `Context` gains `workspace`,
  `can`, `require` and `only`; `DispatchResult` gains `forbidden`.
- Wire changes: none beyond new HTTP statuses on existing routes. `protocol_version` stays 1.
