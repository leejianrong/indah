import pytest

from indah.components import Link, Router, Text
from indah.context import Context
from indah.protocol import navigate_message


def _router(ctx, **kw):
    return Router(
        ctx,
        routes={"/": Text("home"), "/projects/{project}": Text("project")},
        not_found=Text("nope"),
        **kw,
    )


@pytest.mark.unit
def test_context_path_defaults_to_root_and_navigate_validates():
    ctx = Context("s")
    assert ctx.path.value == "/"
    ctx.navigate("/projects/auth/")
    assert ctx.path.value == "/projects/auth"
    with pytest.raises(ValueError):
        ctx.navigate("//evil.example")
    assert ctx.path.value == "/projects/auth"  # unchanged by a rejected navigation


@pytest.mark.unit
def test_navigate_publishes_a_message_only_for_server_initiated_moves():
    sent = []

    class FakeHub:
        def publish(self, msg):
            sent.append(msg)

    ctx = Context("s")
    ctx._bind_hub(FakeHub())
    ctx.navigate("/a")
    ctx.navigate("/b", replace=True)
    ctx._client_navigated("/c")  # the browser already moved: no echo
    assert sent == [navigate_message("/a", False), navigate_message("/b", True)]
    assert ctx.path.value == "/c"
    assert navigate_message("/a", False) == {
        "v": 1,
        "type": "navigate",
        "path": "/a",
        "replace": False,
    }


@pytest.mark.unit
def test_router_activates_the_matching_page_and_not_found():
    ctx = Context("s")
    r = _router(ctx)
    assert r.type == "router" and len(r.children) == 3  # two pages + not_found
    assert r.static_props() == {"routes": ["/", "/projects/{project}"], "notFound": True}
    assert r.reactive_props()["active"]() == 0
    ctx.navigate("/projects/auth")
    assert r.reactive_props()["active"]() == 1
    ctx.navigate("/zzz")
    assert r.reactive_props()["active"]() == 2  # the not_found child
    no_nf = Router(ctx, routes={"/": Text("home")})
    assert no_nf.static_props()["notFound"] is False
    assert no_nf.reactive_props()["active"]() == -1  # nothing to show


@pytest.mark.unit
def test_router_handles_a_client_navigation_and_rejects_bad_paths():
    ctx = Context("s")
    r = _router(ctx)
    assert r.handle("navigate", {"path": "/projects/auth"}) is True
    assert ctx.path.value == "/projects/auth"
    assert r.handle("navigate", {"path": "//evil.example"}) is False
    assert r.handle("navigate", {}) is False
    assert ctx.path.value == "/projects/auth"


@pytest.mark.unit
def test_router_rejects_bad_route_tables():
    ctx = Context("s")
    with pytest.raises(ValueError):
        Router(ctx, routes={})
    with pytest.raises(ValueError):
        Router(ctx, routes={"nope": Text("x")})


@pytest.mark.unit
def test_link_serialises_and_navigates_the_context_silently():
    ctx = Context("s")
    link = Link(ctx, "Entries", to="/projects/auth")
    assert link.type == "link"
    assert link.static_props() == {"label": "Entries", "to": "/projects/auth"}
    assert link.handle("navigate", {"path": "/projects/auth"}) is True
    assert ctx.path.value == "/projects/auth"
    assert link.handle("navigate", {"path": "/elsewhere"}) is False  # only its own target
    with pytest.raises(ValueError):
        Link(ctx, "x", to="https://evil.example")
