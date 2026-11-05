"""``Theme(fonts=[Font(...)])``: self-hosted woff2 files and their ``@font-face`` rules (IND-256).

A font is bytes or a path read once. Nothing here may become a URL the browser fetches from
anywhere but the app's own origin.
"""

import hashlib

import pytest

import indah
from indah.theme import Font, Theme

WOFF2 = b"wOF2" + b"\x00" * 60


def _name(data: bytes = WOFF2) -> str:
    return hashlib.sha256(data).hexdigest()[:16] + ".woff2"


@pytest.mark.unit
def test_font_is_public():
    assert indah.Font is Font and "Font" in indah.__all__


@pytest.mark.unit
def test_a_font_becomes_a_font_face_with_swap_and_a_same_origin_url():
    css = Theme(fonts=[Font("Hanken Grotesk", WOFF2, weight="100 900")]).css()
    assert "@font-face {" in css
    assert "font-family: 'Hanken Grotesk';" in css
    assert "font-weight: 100 900;" in css and "font-style: normal;" in css
    assert "font-display: swap;" in css
    assert f"src: url(api/fonts/{_name()}) format('woff2');" in css
    assert "http" not in css and "//" not in css


@pytest.mark.unit
def test_the_font_files_are_kept_by_content_name():
    theme = Theme(fonts=[Font("A", WOFF2), Font("B", WOFF2 + b"x", style="italic")])
    assert theme.font_files == {_name(): WOFF2, _name(WOFF2 + b"x"): WOFF2 + b"x"}
    assert Theme().font_files == {}


@pytest.mark.unit
def test_a_path_is_read_once_at_creation(tmp_path):
    path = tmp_path / "f.woff2"
    path.write_bytes(WOFF2)
    theme = Theme(fonts=[Font("A", path)])
    path.write_bytes(b"changed")
    assert theme.font_files == {_name(): WOFF2}


@pytest.mark.unit
def test_font_face_comes_before_the_tokens_and_fonts_alone_make_css():
    css = Theme(fonts=[Font("A", WOFF2)], font_body="A, sans-serif").css()
    assert css.index("@font-face") < css.index(":root {")
    assert Theme(fonts=[Font("A", WOFF2)]).css().startswith("@font-face")


@pytest.mark.unit
@pytest.mark.parametrize(
    "src",
    [
        "https://example.com/f.woff2",
        "http://example.com/f.woff2",
        "//example.com/f.woff2",
        "data:font/woff2;base64,AAAA",
        b"not a font",
        b"wOFF" + b"\x00" * 20,  # woff1 is not accepted
        b"",
    ],
)
def test_only_woff2_bytes_or_a_local_file_are_accepted(src):
    with pytest.raises((ValueError, OSError)):
        Theme(fonts=[Font("A", src)])


@pytest.mark.unit
def test_a_missing_file_and_an_oversized_file_fail_at_creation(tmp_path):
    with pytest.raises(OSError):
        Theme(fonts=[Font("A", tmp_path / "missing.woff2")])
    with pytest.raises(ValueError, match="limit"):
        Theme(fonts=[Font("A", b"wOF2" + b"\x00" * (2 * 1024 * 1024))])


@pytest.mark.unit
@pytest.mark.parametrize(
    "family", ["", "a'b", "a; b", "a}", "a\\b", "a</style>", "url(x)", "x" * 61]
)
def test_family_is_a_plain_name(family):
    with pytest.raises(ValueError):
        Theme(fonts=[Font(family, WOFF2)])


@pytest.mark.unit
@pytest.mark.parametrize("weight", ["bold", "400; x", "0", "1000", "400 900 1", "", "400-900"])
def test_weight_is_numeric(weight):
    with pytest.raises(ValueError):
        Theme(fonts=[Font("A", WOFF2, weight=weight)])


@pytest.mark.unit
def test_style_is_normal_or_italic():
    with pytest.raises(ValueError):
        Theme(fonts=[Font("A", WOFF2, style="oblique 10deg")])
    assert "font-style: italic;" in Theme(fonts=[Font("A", WOFF2, style="italic")]).css()


@pytest.mark.unit
def test_duplicates_and_too_many_fonts_are_refused():
    with pytest.raises(ValueError, match="twice"):
        Theme(fonts=[Font("A", WOFF2), Font("A", WOFF2 + b"x")])
    with pytest.raises(ValueError, match="at most"):
        Theme(fonts=[Font(f"F{i}", WOFF2) for i in range(9)])


@pytest.mark.unit
def test_a_non_font_item_is_refused():
    with pytest.raises(TypeError):
        Theme(fonts=["a.woff2"])  # type: ignore[list-item]
