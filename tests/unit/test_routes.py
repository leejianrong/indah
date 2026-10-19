import pytest

from indah.routes import compile_route, match_routes, normalize_path


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("/", "/"),
        ("/a/b", "/a/b"),
        ("/a/b/", "/a/b"),
        ("/a//b", "/a/b"),
        ("/projects/auth", "/projects/auth"),
    ],
)
def test_normalize_path(raw, want):
    assert normalize_path(raw) == want


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        "",
        "a/b",
        "//evil.example/x",
        "/a?x=1",
        "/a#frag",
        "/a b",
        "/a\\b",
        "/a\nb",
        "/" + "x" * 2100,
        5,
    ],
)
def test_normalize_path_rejects_anything_that_is_not_a_plain_in_app_path(bad):
    with pytest.raises(ValueError):
        normalize_path(bad)
    with pytest.raises(ValueError):
        normalize_path(5)


@pytest.mark.unit
def test_literal_and_param_patterns_match_and_extract():
    routes = [
        compile_route("/"),
        compile_route("/projects"),
        compile_route("/projects/{project}"),
        compile_route("/projects/{project}/entries/{entry_id}"),
    ]
    assert match_routes(routes, "/") == (0, {})
    assert match_routes(routes, "/projects") == (1, {})
    assert match_routes(routes, "/projects/auth") == (2, {"project": "auth"})
    assert match_routes(routes, "/projects/auth/entries/01J") == (
        3,
        {"project": "auth", "entry_id": "01J"},
    )
    assert match_routes(routes, "/projects/auth/entries") is None
    assert match_routes(routes, "/nope") is None
    assert match_routes(routes, "/projects/auth/") == (2, {"project": "auth"})  # trailing slash


@pytest.mark.unit
def test_params_are_percent_decoded_and_may_be_typed():
    routes = [compile_route("/n/{id:int}"), compile_route("/s/{name}")]
    assert match_routes(routes, "/n/42") == (0, {"id": 42})
    assert match_routes(routes, "/n/forty") is None  # not an int, and no other route fits
    assert match_routes(routes, "/s/caf%C3%A9%20au%20lait") == (1, {"name": "café au lait"})
    assert match_routes(routes, "/s/a%2Fb") == (
        1,
        {"name": "a/b"},
    )  # an encoded slash stays one segment


@pytest.mark.unit
def test_first_matching_route_wins_so_literals_can_shadow_params():
    routes = [compile_route("/projects/new"), compile_route("/projects/{project}")]
    assert match_routes(routes, "/projects/new")[0] == 0
    assert match_routes(routes, "/projects/other")[0] == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    ["", "x", "/a/{}", "/a/{1x}", "/a/{x:float}", "/a/{x}/{x}", "/a/{x", "/a/b{x}", "/a/*", "//a"],
)
def test_bad_patterns_are_rejected_at_definition_time(bad):
    with pytest.raises(ValueError):
        compile_route(bad)
