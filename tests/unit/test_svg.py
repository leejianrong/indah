"""Inline SVG, sanitised in Python (IND-275): the wire carries a tree of allowlisted elements and
attributes, so the shell builds it with createElementNS and never parses markup."""

import pytest

import indah
from indah import Signal, Svg
from indah.svg import parse_svg

pytestmark = pytest.mark.unit

OK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40">'
    '<defs><linearGradient id="g">'
    '<stop offset="0" stop-color="var(--primary)"/></linearGradient></defs>'
    '<rect x="0" y="0" width="50" height="20" fill="url(#g)" stroke="var(--text)"/>'
    '<g transform="translate(5 5)"><text x="1" y="2" font-size="8">a &amp; b</text></g>'
    "</svg>"
)


def test_a_valid_svg_becomes_a_tree_without_namespaces():
    tree = parse_svg(OK)
    assert tree[0] == "svg" and tree[1]["viewBox"] == "0 0 100 40" and "xmlns" not in tree[1]
    kinds = [c[0] for c in tree[2:]]
    assert kinds == ["defs", "rect", "g"]
    rect = tree[3]
    assert rect[1]["fill"] == "url(#g)" and rect[1]["stroke"] == "var(--text)"
    assert tree[4][2][2] == "a & b"  # text content is data, not markup


@pytest.mark.parametrize(
    "markup",
    [
        "<svg><script>alert(1)</script></svg>",
        "<svg><foreignObject><div/></foreignObject></svg>",
        '<svg><rect onclick="x()" width="1" height="1"/></svg>',
        '<svg><a href="javascript:x"><rect width="1" height="1"/></a></svg>',
        '<svg><image href="http://evil/x.png"/></svg>',
        '<svg><use href="#a"/></svg>',
        '<svg><rect width="1" height="1" style="fill:red"/></svg>',
        '<svg><rect width="1" height="1" fill="url(http://evil/x)"/></svg>',
        '<svg><rect width="1" height="1" fill="url(#a) url(//evil)"/></svg>',
        '<svg><rect class="x" width="1" height="1"/></svg>',
        '<!DOCTYPE svg [<!ENTITY a "b">]><svg/>',
        "<svg><rect></svg>",  # malformed
        "<div/>",  # not an svg
        "",
        "plain text",
    ],
)
def test_anything_active_or_external_is_refused(markup):
    with pytest.raises(ValueError):
        parse_svg(markup)


def test_size_limits():
    with pytest.raises(ValueError, match="elements"):
        parse_svg("<svg>" + '<rect width="1" height="1"/>' * 5001 + "</svg>")
    with pytest.raises(ValueError, match="deep"):
        parse_svg("<svg>" + "<g>" * 40 + "</g>" * 40 + "</svg>")
    with pytest.raises(ValueError, match="KB"):
        parse_svg("<svg><text>" + "x" * 300_000 + "</text></svg>")


def test_the_component_needs_a_label_or_decorative_and_follows_a_source():
    s = Svg(OK, label="A pipeline")
    props = s.to_json()["props"]
    assert s.type == "svg" and props["tree"][0] == "svg" and props["label"] == "A pipeline"
    assert Svg(OK, decorative=True).to_json()["props"]["decorative"] is True
    with pytest.raises(ValueError, match="label"):
        Svg(OK)
    live = Signal(OK)
    sv = Svg(live, label="x")
    live.set('<svg><circle r="3" cx="1" cy="1"/></svg>')
    assert sv.reactive_props()["tree"]()[2][0] == "circle"
    live.set("<svg><script/></svg>")
    with pytest.raises(ValueError):
        sv.reactive_props()["tree"]()
    assert indah.Svg is Svg
