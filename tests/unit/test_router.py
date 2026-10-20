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
    other = Context("t")  # a second session; one Router per session
    no_nf = Router(other, routes={"/": Text("home")})
    other.navigate("/missing")
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


@pytest.mark.unit
def test_params_follow_the_path_as_a_signal_and_typed_segments_are_cast():
    ctx = Context("s")
    assert ctx.params.value == {}  # no router yet
    Router(
        ctx,
        routes={
            "/": Text("h"),
            "/projects/{project}/entries/{entry_id}": Text("e"),
            "/n/{id:int}": Text("n"),
        },
    )
    assert ctx.params.value == {}  # at "/"
    ctx.navigate("/projects/auth/entries/01J")
    assert ctx.params.value == {"project": "auth", "entry_id": "01J"}
    ctx.navigate("/n/42")
    assert ctx.params.value == {"id": 42}
    ctx.navigate("/nowhere")
    assert ctx.params.value == {}  # not found: no params


@pytest.mark.unit
def test_a_computed_over_params_only_recomputes_when_its_inputs_change():
    from indah.reactive import computed

    ctx = Context("s")
    Router(ctx, routes={"/p/{project}/e/{entry}": Text("e"), "/p/{project}": Text("p")})
    runs = []
    entry = computed(lambda: runs.append(1) or ctx.params.value.get("entry"))
    ctx.navigate("/p/auth/e/1")
    assert entry.value == "1"
    ctx.navigate("/p/auth/e/2")
    assert entry.value == "2"
    ctx.navigate("/p/auth")
    assert entry.value is None


@pytest.mark.unit
def test_only_one_router_per_context():
    ctx = Context("s")
    Router(ctx, routes={"/": Text("a")})
    with pytest.raises(ValueError, match="one Router"):
        Router(ctx, routes={"/": Text("b")})


@pytest.mark.unit
def test_link_active_state_exact_and_prefix():
    ctx = Context("s")
    exact = Link(ctx, "Auth", to="/projects/auth")
    prefix = Link(ctx, "Projects", to="/projects", match="prefix")
    home = Link(ctx, "Home", to="/", match="prefix")  # "/" is only ever exact
    assert home.reactive_props()["active"]() is True
    assert exact.reactive_props()["active"]() is False
    ctx.navigate("/projects/auth")
    assert exact.reactive_props()["active"]() is True
    assert prefix.reactive_props()["active"]() is True
    assert home.reactive_props()["active"]() is False
    ctx.navigate("/projects/auth/entries/01J")
    assert exact.reactive_props()["active"]() is False  # exact: only the page itself
    assert prefix.reactive_props()["active"]() is True  # prefix: the section it heads
    ctx.navigate("/projectsx")
    assert prefix.reactive_props()["active"]() is False  # whole segments, not a string prefix
    with pytest.raises(ValueError):
        Link(ctx, "x", to="/a", match="fuzzy")


@pytest.mark.unit
def test_link_to_may_be_a_callable_that_follows_the_params():
    ctx = Context("s")
    Router(
        ctx,
        routes={"/": Text("h"), "/p/{project}": Text("p"), "/p/{project}/e/{entry}": Text("e")},
    )
    link = Link(ctx, "Back", to=lambda: f"/p/{ctx.params.value.get('project')}")
    assert "to" not in link.static_props() and link.static_props() == {"label": "Back"}
    ctx.navigate("/p/auth/e/1")
    assert link.reactive_props()["to"]() == "/p/auth"
    assert link.handle("navigate", {"path": "/p/auth"}) is True and ctx.path.value == "/p/auth"
    ctx.navigate("/p/docs/e/9")
    assert link.reactive_props()["to"]() == "/p/docs"
    assert link.handle("navigate", {"path": "/p/auth"}) is False  # a stale target is refused
    assert link.reactive_props()["active"]() is False
    ctx.navigate("/p/docs")
    assert link.reactive_props()["active"]() is True
