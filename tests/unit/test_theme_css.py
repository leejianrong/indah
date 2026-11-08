"""``Theme(css=...)``: the app's own stylesheet, after the tokens (IND-257)."""

import pytest

from indah.theme import Font, Theme

WOFF2 = b"wOF2" + b"\x00" * 60
MEDIA = "@media (max-width: 600px) { .x-card { padding: 4px; } }"


@pytest.mark.unit
def test_a_str_is_the_css_itself():
    assert MEDIA in Theme(css=MEDIA).css()


@pytest.mark.unit
def test_a_path_is_read_once(tmp_path):
    f = tmp_path / "app.css"
    f.write_text(MEDIA)
    theme = Theme(css=f)
    f.write_text("changed")
    assert MEDIA in theme.css() and "changed" not in theme.css()


@pytest.mark.unit
def test_the_css_comes_last_so_it_wins_over_tokens_and_faces():
    css = Theme(
        light={"primary": "#123456"},
        dark={"primary": "#654321"},
        fonts=[Font("A", WOFF2)],
        css=MEDIA,
    ).css()
    assert css.endswith(MEDIA)
    assert css.index("@font-face") < css.index(":root[data-theme") < css.index("@media")


@pytest.mark.unit
def test_css_alone_is_a_stylesheet():
    assert Theme(css=MEDIA).css() == MEDIA


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["a{}</style><script>x</script>", "a{}</STYLE >"])
def test_a_style_end_tag_is_refused(bad):
    with pytest.raises(ValueError, match="style"):
        Theme(css=bad)


@pytest.mark.unit
def test_a_missing_file_a_bare_file_name_and_a_huge_sheet_are_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        Theme(css=tmp_path / "nope.css")
    with pytest.raises(ValueError, match="Path"):
        Theme(css="app.css")
    with pytest.raises(ValueError, match="limit"):
        Theme(css="a{}" * 200_000)
