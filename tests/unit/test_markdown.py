import json

import pytest

from indah.markdown import to_blocks


def _tags(nodes):
    """Every element tag anywhere in a block tree."""
    out = set()
    for node in nodes:
        if isinstance(node, dict):
            out.add(node.get("tag"))
            out |= _tags(node.get("children", []))
    return out


@pytest.mark.unit
def test_heading_and_paragraph():
    blocks = to_blocks("# Title\n\nHello world")
    assert blocks == [
        {"tag": "h1", "children": ["Title"]},
        {"tag": "p", "children": ["Hello world"]},
    ]


@pytest.mark.unit
def test_heading_levels():
    assert to_blocks("### Three")[0]["tag"] == "h3"
    assert to_blocks("###### Six")[0]["tag"] == "h6"
    # Seven hashes is not a heading -> a paragraph.
    assert to_blocks("####### Nope")[0]["tag"] == "p"


@pytest.mark.unit
def test_inline_bold_italic_and_code():
    blocks = to_blocks("a **b** _c_ `d`")
    assert blocks == [
        {
            "tag": "p",
            "children": [
                "a ",
                {"tag": "strong", "children": ["b"]},
                " ",
                {"tag": "em", "children": ["c"]},
                " ",
                {"tag": "code", "children": ["d"]},
            ],
        }
    ]


@pytest.mark.unit
def test_nested_emphasis():
    blocks = to_blocks("**bold _and italic_**")
    strong = blocks[0]["children"][0]
    assert strong["tag"] == "strong"
    assert {"tag": "em", "children": ["and italic"]} in strong["children"]


@pytest.mark.unit
def test_fenced_code_block_keeps_text_literal():
    blocks = to_blocks("```python\nprint('hi')\n```")
    assert blocks == [{"tag": "pre", "children": [{"tag": "code", "children": ["print('hi')"]}]}]


@pytest.mark.unit
def test_unordered_and_ordered_lists():
    ul = to_blocks("- one\n- two")
    assert ul[0]["tag"] == "ul"
    assert [li["children"] for li in ul[0]["children"]] == [["one"], ["two"]]
    ol = to_blocks("1. first\n2. second")
    assert ol[0]["tag"] == "ol"
    assert len(ol[0]["children"]) == 2


@pytest.mark.unit
def test_blockquote_recurses_into_blocks():
    blocks = to_blocks("> quoted **line**")
    assert blocks[0]["tag"] == "blockquote"
    assert blocks[0]["children"][0]["tag"] == "p"


@pytest.mark.unit
def test_horizontal_rule():
    assert to_blocks("---")[0] == {"tag": "hr"}


@pytest.mark.unit
def test_safe_link_becomes_anchor():
    blocks = to_blocks("[docs](https://example.com)")
    anchor = blocks[0]["children"][0]
    assert anchor == {"tag": "a", "href": "https://example.com", "children": ["docs"]}


@pytest.mark.unit
def test_relative_and_mailto_links_allowed():
    assert "a" in _tags(to_blocks("[a](/local)"))
    assert "a" in _tags(to_blocks("[a](#anchor)"))
    assert "a" in _tags(to_blocks("[a](mailto:x@example.com)"))


@pytest.mark.unit
def test_javascript_link_is_rejected_and_kept_literal():
    blocks = to_blocks("[click](javascript:alert(1))")
    # No anchor is produced; the text survives literally for the shell to escape.
    assert "a" not in _tags(blocks)
    assert "javascript:alert(1)" in json.dumps(blocks)


@pytest.mark.unit
def test_raw_html_never_becomes_an_element():
    # The whole point: source HTML is data, never markup. No script/img/div tags
    # appear as elements; the angle-bracket text is preserved as a string leaf.
    blocks = to_blocks("<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>")
    tags = _tags(blocks)
    assert "script" not in tags
    assert "img" not in tags
    assert "div" not in tags
    dumped = json.dumps(blocks)
    assert "alert(1)" in dumped  # preserved as literal text, escaped at render


@pytest.mark.unit
def test_backslash_escapes_markup():
    blocks = to_blocks(r"a \*not italic\* b")
    assert blocks == [{"tag": "p", "children": ["a *not italic* b"]}]


@pytest.mark.unit
def test_every_node_is_a_string_or_allowlisted_tag():
    md = "# H\n\ntext **b** `c` [l](https://x.com)\n\n- i\n\n> q\n\n```\ncode\n```\n\n---"
    allowed = {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "pre",
        "code",
        "blockquote",
        "ul",
        "ol",
        "li",
        "strong",
        "em",
        "a",
        "br",
        "hr",
    }
    assert _tags(to_blocks(md)) <= allowed
