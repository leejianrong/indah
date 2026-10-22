"""register_component(module=...): a component backed by an ES module (ADR-0039)."""

import hashlib

import pytest

from indah.custom import (
    _REGISTRY,
    MAX_MODULE_BYTES,
    MAX_MODULES,
    clear_registry,
    custom,
    register_component,
)
from indah.reactive import Signal

JS = b"export default class extends HTMLElement {}"


@pytest.fixture(autouse=True)
def _isolate_registry():
    saved = dict(_REGISTRY)
    clear_registry()
    yield
    clear_registry()
    _REGISTRY.update(saved)


@pytest.mark.unit
def test_module_registration_takes_bytes_and_hashes_them():
    reg = register_component("tier-rail", module=JS, events=["pick"])
    assert reg.module == JS
    assert reg.render is None
    assert reg.module_hash == hashlib.sha256(JS).hexdigest()[:16]
    assert reg.forward == ("pick",)


@pytest.mark.unit
def test_module_registration_reads_a_path_once(tmp_path):
    path = tmp_path / "rail.js"
    path.write_bytes(JS)
    reg = register_component("tier-rail", module=str(path))
    path.write_bytes(b"changed")  # a later edit does not reach the registry
    assert reg.module == JS
    assert register_component("tier-rail", module=path).module == b"changed"


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    ["https://cdn.example/x.js", "http://x/y.js", "//cdn.example/x.js", "data:text/javascript,1"],
)
def test_a_url_is_never_accepted_as_a_module(bad):
    with pytest.raises(ValueError, match="URL"):
        register_component("tier-rail", module=bad)


@pytest.mark.unit
def test_exactly_one_of_render_and_module():
    with pytest.raises(ValueError, match="exactly one"):
        register_component("x-y", render={"tag": "div"}, module=JS)
    with pytest.raises(ValueError, match="exactly one"):
        register_component("x-y")


@pytest.mark.unit
@pytest.mark.parametrize(
    "name", ["Tier", "tier_rail", "-a", "a--b", "a b", "../x", "a/b", "1a", ""]
)
def test_a_module_type_must_be_a_safe_name(name):
    with pytest.raises(ValueError):
        register_component(name, module=JS)


@pytest.mark.unit
def test_a_builtin_name_is_refused_for_a_module():
    with pytest.raises(ValueError, match="built-in"):
        register_component("button", module=JS)


@pytest.mark.unit
def test_missing_file_empty_and_oversize_modules_are_refused(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        register_component("a-b", module=str(tmp_path / "nope.js"))
    with pytest.raises(ValueError, match="empty"):
        register_component("a-b", module=b"")
    with pytest.raises(ValueError, match="1 MB|too large"):
        register_component("a-b", module=b"x" * (MAX_MODULE_BYTES + 1))


@pytest.mark.unit
def test_the_registry_of_modules_is_bounded_but_a_type_can_be_replaced():
    for i in range(MAX_MODULES):
        register_component(f"c-{i}", module=JS)
    with pytest.raises(ValueError, match="too many"):
        register_component("one-more", module=JS)
    register_component("c-0", module=JS + b"//v2")  # replacing is fine


@pytest.mark.unit
def test_event_names_and_two_way_are_validated():
    with pytest.raises(ValueError):
        register_component("a-b", module=JS, events=["Bad Name"])
    with pytest.raises(ValueError):
        register_component("a-b", module=JS, two_way={"value": "no spaces allowed"})
    reg = register_component("a-b", module=JS, events=["pick"], two_way={"value": "change"})
    assert set(reg.forward) == {"pick", "change"}
    assert reg.two_way == {"value": "change"}


@pytest.mark.unit
def test_the_snapshot_carries_module_not_spec_and_patches_carry_neither():
    register_component(
        "tier-rail", module=JS, events=["pick"], two_way={"value": "change"}, fallback="steps"
    )
    steps, value = Signal(["a", "b"]), Signal(1)
    rail = custom("tier-rail", steps=steps, value=value, label="Tiers")
    rail.id = "n3"
    props = rail.to_json()["props"]
    assert "_spec" not in props
    reg_hash = hashlib.sha256(JS).hexdigest()[:16]
    assert props["_module"] == {
        "url": f"api/components/tier-rail.js?v={reg_hash}",
        "tag": "indah-x-tier-rail",
        "events": ["pick", "change"],
        "twoWay": ["value"],
        "fallback": "steps",
    }
    assert props["steps"] == ["a", "b"] and props["value"] == 1 and props["label"] == "Tiers"
    assert set(rail.reactive_props()) == {"steps", "value"}  # _module is static, sent once


@pytest.mark.unit
def test_on_event_handler_receives_the_detail():
    register_component("tier-rail", module=JS, events=["pick"])
    seen = []
    rail = custom("tier-rail", on_pick=seen.append)
    assert rail.handle("pick", {"detail": {"tier": 3}}) is True
    assert seen == [{"tier": 3}]
    assert "on_pick" not in rail.to_json()["props"]


@pytest.mark.unit
def test_an_async_handler_is_returned_for_the_session_to_run():
    register_component("tier-rail", module=JS, events=["pick"])

    async def handler(detail):
        return detail

    rail = custom("tier-rail", on_pick=handler)
    ret = rail.handle("pick", {"detail": 1})
    assert hasattr(ret, "send")  # a coroutine, awaited by the session in the background
    ret.close()


@pytest.mark.unit
def test_an_event_that_was_not_declared_is_ignored():
    register_component("tier-rail", module=JS, events=["pick"])
    called = []
    rail = custom("tier-rail", on_pick=called.append)
    assert rail.handle("other", {"detail": 1}) is False
    assert called == []


@pytest.mark.unit
def test_on_handler_for_an_undeclared_event_is_an_error_at_construction():
    register_component("tier-rail", module=JS, events=["pick"])
    with pytest.raises(ValueError, match="on_nope"):
        custom("tier-rail", on_nope=lambda d: None)


@pytest.mark.unit
def test_two_way_writes_detail_value_to_the_bound_signal():
    register_component("tier-rail", module=JS, two_way={"value": "change"})
    value = Signal(1)
    rail = custom("tier-rail", value=value)
    assert rail.handle("change", {"detail": {"value": 4}}) is True
    assert value.peek() == 4
    assert rail.handle("change", {"detail": 5}) is False  # no `value` key: nothing to write
    assert value.peek() == 4


@pytest.mark.unit
def test_two_way_needs_a_signal_to_write_to():
    register_component("tier-rail", module=JS, two_way={"value": "change"})
    rail = custom("tier-rail", value=3)  # static: there is nothing to write back to
    assert rail.handle("change", {"detail": {"value": 4}}) is False


@pytest.mark.unit
def test_a_spec_component_is_unchanged_and_on_prefixed_props_stay_props():
    register_component("chip", render={"tag": "span", "text": "label"})
    chip = custom("chip", label="x", on_thing="kept")
    chip.id = "n0"
    props = chip.to_json()["props"]
    assert props["_spec"]["tag"] == "span" and "_module" not in props
    assert props["on_thing"] == "kept"
