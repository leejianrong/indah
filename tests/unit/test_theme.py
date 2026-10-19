"""App-level theme tokens (IND-88): override the shell's CSS custom properties for one app.

The values land inside a ``<style>`` block, so anything that could close it, start a rule
or fetch a resource must be refused up front.
"""

import pytest

from indah.theme import Theme


@pytest.mark.unit
def test_empty_theme_has_no_css():
    assert Theme().css() == ""


@pytest.mark.unit
def test_light_dark_radius_and_font_become_scoped_custom_properties():
    css = Theme(
        light={"primary": "#1f6feb", "--bg": "#f7f7f9"},
        dark={"primary": "#79b8ff"},
        radius="8px",
        font="system-ui, sans-serif",
    ).css()
    assert ":root {" in css and "--primary: #1f6feb;" in css and "--bg: #f7f7f9;" in css
    assert "--radius: 8px;" in css
    assert "--font-body: system-ui, sans-serif;" in css and "--font-display:" in css
    assert ':root[data-theme="dark"] {' in css and "--primary: #79b8ff;" in css
    # dark rules come after light so they win at equal specificity
    assert css.index(":root {") < css.index('[data-theme="dark"]')


@pytest.mark.unit
def test_radius_and_font_apply_to_both_schemes_once():
    css = Theme(radius="4px").css()
    assert css.count("--radius: 4px;") == 1  # radius is not a per-scheme colour


@pytest.mark.unit
@pytest.mark.parametrize("name", ["nope", "--nope", "primary; color", "radius", "font-body", ""])
def test_unknown_or_non_colour_token_names_are_rejected(name):
    with pytest.raises(ValueError):
        Theme(light={name: "#fff"})


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "red; background: url(x)",
        "red}</style><script>alert(1)</script>",
        "url(https://evil.example/x.png)",
        "@import 'x'",
        "expression(alert(1))",
        "javascript:alert(1)",
        "a\nb",
        "{",
        "#" + "f" * 200,
        "",
    ],
)
def test_hostile_or_malformed_values_are_rejected(value):
    with pytest.raises(ValueError):
        Theme(light={"primary": value})
    with pytest.raises(ValueError):
        Theme(radius=value)
    with pytest.raises(ValueError):
        Theme(font=value)


@pytest.mark.unit
def test_ordinary_css_values_are_accepted():
    Theme(
        light={
            "shadow": "0 2px 5px -2px rgba(90, 20, 55, 0.16), 0 1px 2px rgba(0,0,0,.1)",
            "primary": "oklch(62% 0.2 255)",
        },
        font='"IBM Plex Sans", system-ui, sans-serif',
    )
