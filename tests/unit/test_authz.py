"""Policy evaluation and the dispatch-time guard (ADR-0035, IND-118)."""

import asyncio

import pytest

from indah.auth import Principal
from indah.authz import Forbidden, Policy, authz_scope, can, guard


def _p(*roles, workspace=None):
    return Principal(id="u", roles=frozenset(roles), workspace=workspace)


@pytest.mark.unit
def test_without_a_policy_a_permission_is_a_role_name():
    assert can(_p("admin"), "admin", None)
    assert not can(_p("viewer"), "admin", None)


@pytest.mark.unit
def test_a_policy_maps_roles_to_permissions_with_wildcards():
    policy = Policy({"viewer": ["entries:read"], "editor": ["entries:*"], "admin": ["*"]})
    assert can(_p("viewer"), "entries:read", policy)
    assert not can(_p("viewer"), "entries:write", policy)
    assert can(_p("editor"), "entries:write", policy)
    assert not can(_p("editor"), "tokens:create", policy)
    assert can(_p("admin"), "tokens:create", policy)
    assert can(_p("viewer", "editor"), "entries:write", policy)  # any role is enough


@pytest.mark.unit
def test_nobody_can_do_anything_and_unknown_roles_grant_nothing():
    policy = Policy({"admin": ["*"]})
    assert not can(None, "anything", policy)
    assert not can(None, "anything", None)
    assert not can(_p("ghost"), "anything", policy)
    assert not can(_p("admin"), "", policy)  # an empty permission is never granted


@pytest.mark.unit
def test_star_in_a_role_name_is_not_a_wildcard_for_the_caller():
    assert not can(_p("admin"), "*", None)  # asking for "*" needs the literal role "*"


@pytest.mark.unit
def test_guard_runs_the_handler_when_the_current_principal_may_and_refuses_otherwise():
    calls = []

    @guard("editor")
    def delete(x=0):
        calls.append(x)
        return "ok"

    with authz_scope(_p("editor"), None):
        assert delete(3) == "ok"
    with authz_scope(_p("viewer"), None), pytest.raises(Forbidden):
        delete(4)
    assert calls == [3]


@pytest.mark.unit
def test_guard_fails_closed_with_no_principal_in_scope():
    ran = []

    @guard("editor")
    def delete():
        ran.append(1)

    with pytest.raises(Forbidden):
        delete()  # called outside any dispatch: nobody to authorize
    with authz_scope(None, None), pytest.raises(Forbidden):
        delete()
    assert ran == []


@pytest.mark.unit
async def test_guard_checks_before_an_async_handler_is_even_created():
    ran = []

    @guard("editor")
    async def delete():
        ran.append(1)

    with authz_scope(_p("viewer"), None), pytest.raises(Forbidden):
        delete()  # refused synchronously, so a POST can answer 403
    assert ran == []
    with authz_scope(_p("editor"), None):
        coro = delete()
    await coro
    assert ran == [1]


@pytest.mark.unit
async def test_a_spawned_task_keeps_the_principal_it_was_dispatched_with():
    @guard("editor")
    async def work():
        await asyncio.sleep(0)

    with authz_scope(_p("editor"), None):
        task = asyncio.create_task(work())
    await task  # the scope exited, but the task copied it at creation


@pytest.mark.unit
def test_guard_keeps_the_handler_signature_and_policy_is_read_from_the_scope():
    import inspect

    policy = Policy({"editor": ["entries:write"]})

    @guard("entries:write")
    def save(payload):
        return payload

    assert list(inspect.signature(save).parameters) == ["payload"]
    with authz_scope(_p("editor"), policy):
        assert save(1) == 1
    with authz_scope(_p("viewer"), policy), pytest.raises(Forbidden):
        save(1)


@pytest.mark.unit
def test_guard_rejects_an_empty_permission_at_decoration_time():
    with pytest.raises(ValueError):
        guard("")
