"""The Content-Security-Policy builder, nonce rewrite and tile-host registry (ADR-0038)."""

import re

import pytest

from indah import csp
from indah.components import Map


def _directives(policy: str) -> dict[str, list[str]]:
    out = {}
    for part in policy.split(";"):
        words = part.split()
        if words:
            out[words[0]] = words[1:]
    return out


@pytest.mark.unit
def test_nonces_are_long_and_never_repeat():
    nonces = {csp.new_nonce() for _ in range(200)}
    assert len(nonces) == 200
    assert all(len(n) >= 22 and re.fullmatch(r"[A-Za-z0-9_-]+", n) for n in nonces)  # >= 128 bits


@pytest.mark.unit
def test_strict_policy_has_no_unsafe_inline_for_scripts_or_styles_and_no_eval():
    d = _directives(csp.build_csp("N0NCE", img_hosts=[]))
    assert d["default-src"] == ["'none'"]
    assert "'nonce-N0NCE'" in d["script-src"] and "'unsafe-inline'" not in d["script-src"]
    assert "'nonce-N0NCE'" in d["style-src"] and "'unsafe-inline'" not in d["style-src"]
    assert d["style-src-attr"] == ["'unsafe-inline'"]  # Svelte's style="..." attributes
    assert "'unsafe-eval'" not in " ".join(sum(d.values(), []))
    assert d["connect-src"] == ["'self'"]
    assert d["frame-ancestors"] == ["'self'"]
    assert d["base-uri"] == ["'self'"] and d["form-action"] == ["'self'"]
    assert "'self'" in d["script-src"]  # the lazily imported editor module is same-origin


@pytest.mark.unit
def test_images_allow_self_data_blob_and_only_the_named_hosts():
    d = _directives(csp.build_csp("n", img_hosts=["https://tiles.example.com"]))
    assert d["img-src"] == ["'self'", "data:", "blob:", "https://tiles.example.com"]
    assert d["media-src"] == ["'self'", "data:", "blob:", "https://tiles.example.com"]  # audio too


@pytest.mark.unit
def test_a_report_uri_is_added_when_given():
    d = _directives(csp.build_csp("n", img_hosts=[], report_uri="../api/csp-report"))
    assert d["report-uri"] == ["../api/csp-report"]


@pytest.mark.unit
def test_nonce_is_added_to_every_script_and_style_tag_and_only_those():
    html = (
        '<head><script>a()</script><script type="module" crossorigin>b()</script>'
        '<style>x{}</style><style rel="stylesheet" crossorigin>y{}</style>'
        "<scripture>no</scripture><div style='c:d'></div></head>"
    )
    out = csp.add_nonce(html, "NNN")
    assert out.count('nonce="NNN"') == 4
    assert re.findall(r"<(?:script|style)\b[^>]*>", out) == [
        '<script nonce="NNN">',
        '<script nonce="NNN" type="module" crossorigin>',
        '<style nonce="NNN">',
        '<style nonce="NNN" rel="stylesheet" crossorigin>',
    ]
    assert "<scripture>" in out and "<div style='c:d'>" in out


@pytest.mark.unit
def test_the_built_shell_has_only_nonceable_inline_code():
    from indah.app import _chrome_html

    class S:
        page_title = "t"
        title_suffix = ""
        theme_css = ":root{--primary:red}"
        density = "comfortable"
        secure = True
        logo = None
        home_url = None
        source_url = None

    html = csp.add_nonce(_chrome_html(S()), "NNN")
    tags = re.findall(r"<(?:script|style)\b[^>]*>", html)
    assert len(tags) >= 4 and all('nonce="NNN"' in t for t in tags)
    assert not re.search(r"\son[a-z]+\s*=", html)  # no inline event handlers (script-src blocks)
    assert "javascript:" not in html


@pytest.mark.unit
def test_a_custom_policy_gets_the_nonce_substituted():
    assert csp.render_custom("script-src 'nonce-{nonce}'", "ABC") == "script-src 'nonce-ABC'"


@pytest.fixture
def empty_registry(monkeypatch):
    monkeypatch.setattr(csp, "_registered", {})
    monkeypatch.setattr(csp, "_served", None)


@pytest.mark.unit
def test_no_image_host_is_known_until_a_map_is_built(empty_registry):
    assert csp.known_img_hosts() == []


@pytest.mark.unit
def test_a_map_registers_its_tile_host_default_included(empty_registry):
    Map(center=(0, 0), zoom=2, tile_url="https://tiles.example.org/{z}/{x}/{y}.png")
    assert csp.known_img_hosts() == ["https://tiles.example.org"]
    Map(center=(0, 0), zoom=2)
    assert "https://tile.openstreetmap.org" in csp.known_img_hosts()


@pytest.mark.unit
def test_a_host_first_registered_after_the_policy_was_served_is_warned_about(
    empty_registry, caplog
):
    csp.known_img_hosts()  # a page is served
    with caplog.at_level("WARNING", logger="indah.csp"):
        Map(center=(0, 0), zoom=2)
    assert "csp_media_hosts" in caplog.text
    assert "https://tile.openstreetmap.org" in caplog.text


@pytest.mark.unit
def test_a_host_registered_before_the_first_page_is_not_warned_about(empty_registry, caplog):
    with caplog.at_level("WARNING", logger="indah.csp"):
        Map(center=(0, 0), zoom=2)
        csp.known_img_hosts()
    assert caplog.text == ""


@pytest.mark.unit
@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "not a url", "data:text/plain,x", "//no-scheme.example/{z}"]
)
def test_an_unusable_tile_url_registers_nothing(url, empty_registry):
    before = set(csp.known_img_hosts())
    csp.register_img_host(url)
    assert set(csp.known_img_hosts()) == before


@pytest.mark.unit
def test_a_host_with_policy_syntax_cannot_inject_a_directive(empty_registry):
    before = set(csp.known_img_hosts())
    csp.register_img_host("https://a.example.com; script-src *")
    csp.register_img_host("https://a.example.com'")
    assert set(csp.known_img_hosts()) == before
