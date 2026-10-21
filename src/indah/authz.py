"""Authorization for hosted apps: who may do what (ADR-0035).

indah supplies the mechanism, not the policy. A :class:`~indah.auth.Principal` carries
``roles``; an optional :class:`Policy` maps roles to permissions::

    policy = Policy({"viewer": ["entries:read"], "editor": ["entries:*"], "admin": ["*"]})
    create_app(session_factory=build, auth=who, secure=True, secret=..., policy=policy)

    def build(ctx):
        save = guard("entries:write")(save_entry)          # re-checked on every click
        return Session(Column(children=[
            Button("Save", on_click=save),
            *ctx.only("tokens:manage", lambda: TokenScreen()),   # omitted unless allowed
        ]))

Two rules keep it safe:

- **Omit, do not hide.** The ``init`` snapshot and every patch carry whatever is in the tree, so
  a component that is merely not shown is still sent. Build restricted components only for a
  principal who may see them (``ctx.can``, ``ctx.only``).
- **Check again at dispatch.** :func:`guard` and ``ctx.require`` look at the principal of the
  request that is running the handler (re-authenticated per request), not the one the session
  was built for, so a role revoked mid-session fails closed on the next action.

Everything here fails closed: no principal, no permission, an empty permission name, or a
call outside a dispatch all refuse.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

from .auth import Principal

F = TypeVar("F", bound=Callable[..., Any])


class Forbidden(PermissionError):
    """Raised when a principal lacks a permission. A handler that raises it gets a "not
    allowed" toast, not an error trace; a request for a guarded event answers ``403``."""


class Policy:
    """Roles to permissions. ``"*"`` grants everything; ``"entries:*"`` grants every
    permission starting ``entries:``. Immutable after construction."""

    def __init__(self, grants: Mapping[str, Iterable[str]]) -> None:
        self._grants: dict[str, frozenset[str]] = {
            role: frozenset(perms) for role, perms in grants.items()
        }

    def allows(self, roles: Iterable[str], perm: str) -> bool:
        for role in roles:
            for grant in self._grants.get(role, ()):
                if grant == "*" or grant == perm:
                    return True
                if grant.endswith(":*") and perm.startswith(grant[:-1]):
                    return True
        return False

    def __repr__(self) -> str:
        return f"Policy({ {r: sorted(p) for r, p in self._grants.items()} })"


def can(principal: Principal | None, perm: str, policy: Policy | None) -> bool:
    """Whether ``principal`` holds ``perm``. Without a policy a permission is a role name."""
    if principal is None or not isinstance(perm, str) or not perm:
        return False
    if perm in principal.roles:
        return True
    return policy is not None and policy.allows(principal.roles, perm)


# The principal and policy of the request now running a handler. Set around dispatch (and
# inherited by a task spawned inside it), so a guard sees who is acting *now*.
_scope: ContextVar[tuple[Principal | None, Policy | None] | None] = ContextVar(
    "indah_authz_scope", default=None
)


@contextmanager
def authz_scope(principal: Principal | None, policy: Policy | None) -> Iterator[None]:
    token = _scope.set((principal, policy))
    try:
        yield
    finally:
        _scope.reset(token)


def current_principal() -> Principal | None:
    scope = _scope.get()
    return scope[0] if scope else None


def check(perm: str) -> None:
    """Raise :class:`Forbidden` unless the principal running this handler holds ``perm``."""
    scope = _scope.get()
    principal, policy = scope if scope else (None, None)
    if not can(principal, perm, policy):
        raise Forbidden(f"not allowed: {perm}")


def guard(perm: str) -> Callable[[F], F]:
    """Wrap an event handler so it runs only for a principal holding ``perm``.

    The check happens when the event is dispatched, before the handler runs (for an ``async``
    handler, before its coroutine is created, so the request can answer ``403``). It reads the
    principal of the current request, so it is correct even if the role changed after the
    page loaded. Outside a dispatch there is nobody to authorize, so it refuses."""
    if not isinstance(perm, str) or not perm:
        raise ValueError("guard() needs a non-empty permission")

    def wrap(fn: F) -> F:
        @functools.wraps(fn)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            check(perm)
            return fn(*args, **kwargs)

        return guarded  # type: ignore[return-value]

    return wrap
