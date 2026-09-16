"""A pretty map generator: restyle a stylized city map and download it.

The prettymapp-style showcase: a handful of controls drive a striking, framed "map"
you can download. Here the map is procedurally generated art - streets, blocks, water,
and parks laid down from a seed (no geodata or heavy dependency, so it runs on indah
alone). The pattern is identical to wrapping real prettymapp / OSM data behind the same
controls (ADR-0009).

What it shows off:
- **reactive rendering** - the preview recomputes from the inputs with no rerun, only
  the image node patches;
- **file-out** - the finished map downloads as an SVG via the ``Download`` component
  (ADR-0017), served per session.

Run it with:  python examples/prettymap.py   (prints a URL; embeds inline in a cell).
"""

from __future__ import annotations

import math
import random
import urllib.parse

import indah

# prettymapp-flavoured themes: a role colour each for ground, streets, buildings,
# water, parks, and the ink used for the frame and label.
_THEMES = {
    "Peach": {
        "bg": "#fff1e6",
        "street": "#e0701a",
        "building": "#e5989b",
        "water": "#a7c7e7",
        "green": "#a3b18a",
        "ink": "#5a2a27",
    },
    "Ink": {
        "bg": "#0f1216",
        "street": "#e8e8e8",
        "building": "#3a3f47",
        "water": "#2e5d8a",
        "green": "#3a6b4f",
        "ink": "#e8e8e8",
    },
    "Citrus": {
        "bg": "#fffdf4",
        "street": "#2e6d62",
        "building": "#e0b500",
        "water": "#7fae00",
        "green": "#3aa76d",
        "ink": "#2e3b1f",
    },
    "Rose": {
        "bg": "#20161a",
        "street": "#b5296b",
        "building": "#7a1f4f",
        "water": "#5b7a9a",
        "green": "#2e6d62",
        "ink": "#f3e6de",
    },
}
_SHAPES = ["Circle", "Square"]

_W = 600
_H = 680
_CX = _CY = _W // 2  # map centre
_R = 270  # map radius (half-size of the framed area)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _frame(shape: str, ink: str) -> str:
    if shape == "Circle":
        return (
            f"<circle cx='{_CX}' cy='{_CY}' r='{_R}' fill='none' stroke='{ink}' stroke-width='6'/>"
        )
    return (
        f"<rect x='{_CX - _R}' y='{_CY - _R}' width='{2 * _R}' height='{2 * _R}' rx='18' "
        f"fill='none' stroke='{ink}' stroke-width='6'/>"
    )


def render_map(name: str, theme: str, shape: str, density: int, seed: int) -> str:
    """Deterministically render a stylized city map to an SVG string from the controls."""
    t = _THEMES.get(theme, _THEMES["Peach"])
    rng = random.Random(f"{name}-{shape}-{density}-{seed}")
    lo_x, hi_x = _CX - _R, _CX + _R
    lo_y, hi_y = _CY - _R, _CY + _R
    parts: list[str] = [f"<rect x='0' y='0' width='{_W}' height='{_H}' fill='{t['bg']}'/>"]

    # Parks (soft green ellipses).
    for _ in range(3):
        gx, gy = rng.randint(lo_x, hi_x), rng.randint(lo_y, hi_y)
        rr = rng.randint(40, 90)
        parts.append(
            f"<ellipse cx='{gx}' cy='{gy}' rx='{rr}' ry='{int(rr * 0.7)}' "
            f"fill='{t['green']}' fill-opacity='0.55'/>"
        )

    # A river band (wavy thick stroke), most of the time.
    if rng.random() < 0.7:
        y0 = rng.randint(lo_y + 40, hi_y - 40)
        pts = " ".join(
            f"{x},{y0 + 30 * math.sin(x / 70 + seed):.0f}" for x in range(0, _W + 20, 20)
        )
        parts.append(
            f"<polyline points='{pts}' fill='none' stroke='{t['water']}' stroke-width='26' "
            "stroke-linecap='round' stroke-opacity='0.9'/>"
        )

    # Buildings (little blocks scattered off the water).
    for _ in range(density * 24):
        bx, by = rng.randint(lo_x, hi_x), rng.randint(lo_y, hi_y)
        bw, bh = rng.randint(6, 16), rng.randint(6, 16)
        parts.append(
            f"<rect x='{bx}' y='{by}' width='{bw}' height='{bh}' "
            f"fill='{t['building']}' fill-opacity='0.85'/>"
        )

    # Streets: a few thick primaries, then a light secondary grid.
    for _ in range(3):
        parts.append(
            f"<line x1='{rng.randint(lo_x, hi_x)}' y1='{lo_y}' x2='{rng.randint(lo_x, hi_x)}' "
            f"y2='{hi_y}' stroke='{t['street']}' stroke-width='7'/>"
        )
        parts.append(
            f"<line x1='{lo_x}' y1='{rng.randint(lo_y, hi_y)}' x2='{hi_x}' "
            f"y2='{rng.randint(lo_y, hi_y)}' stroke='{t['street']}' stroke-width='7'/>"
        )
    step = max(24, 90 - density * 6)
    for gx in range(lo_x, hi_x, step):
        parts.append(
            f"<line x1='{gx}' y1='{lo_y}' x2='{gx}' y2='{hi_y}' "
            f"stroke='{t['street']}' stroke-width='2' stroke-opacity='0.5'/>"
        )
    for gy in range(lo_y, hi_y, step):
        parts.append(
            f"<line x1='{lo_x}' y1='{gy}' x2='{hi_x}' y2='{gy}' "
            f"stroke='{t['street']}' stroke-width='2' stroke-opacity='0.5'/>"
        )

    if shape == "Circle":
        clip = f"<circle cx='{_CX}' cy='{_CY}' r='{_R}'/>"
    else:
        clip = f"<rect x='{_CX - _R}' y='{_CY - _R}' width='{2 * _R}' height='{2 * _R}' rx='18'/>"
    label = _escape((name or "Somewhere").strip()[:28])
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{_W}' height='{_H}'>"
        f"<defs><clipPath id='mapclip'>{clip}</clipPath></defs>"
        f"<rect width='{_W}' height='{_H}' fill='{t['bg']}'/>"
        f"<g clip-path='url(#mapclip)'>{''.join(parts)}</g>"
        f"{_frame(shape, t['ink'])}"
        f"<text x='{_CX}' y='{_CY + _R + 46}' text-anchor='middle' font-size='34' "
        f"font-family='Georgia, serif' font-weight='700' fill='{t['ink']}'>{label}</text>"
        f"<text x='{_CX}' y='{_CY + _R + 74}' text-anchor='middle' font-size='15' "
        f"font-family='sans-serif' fill='{t['ink']}' fill-opacity='0.7'>"
        f"{theme} · made with indah</text>"
        "</svg>"
    )


def _data_uri(svg: str) -> str:
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


def build() -> indah.Session:
    name = indah.Signal("Kuala Lumpur")
    theme = indah.Signal("Peach")
    shape = indah.Signal("Circle")
    density = indah.Signal(6)
    seed = indah.Signal(7)

    def svg() -> str:
        return render_map(name.value, theme.value, shape.value, int(density.value), int(seed.value))

    controls = indah.Card(
        title="Map",
        children=[
            indah.TextInput(name, label="Place", placeholder="A place name..."),
            indah.Select(theme, options=list(_THEMES), label="Theme"),
            indah.Radio(shape, options=_SHAPES, label="Frame"),
            indah.Slider(density, min=3, max=12, step=1, label="Density"),
            indah.Slider(seed, min=0, max=50, step=1, label="Seed"),
            indah.Download(
                lambda: indah.DownloadFile(
                    svg().encode("utf-8"), filename="prettymap.svg", media_type="image/svg+xml"
                ),
                label="Download map (SVG)",
            ),
        ],
    )

    preview = indah.Card(children=[indah.Image(lambda: _data_uri(svg()), alt="map preview")])

    intro = indah.Text(
        "# Pretty map generator\n\n"
        "Restyle the map with the controls and it re-renders live (reactive - only the "
        "image patches, no rerun), then **download** it. The map is generated art; wrap "
        "real prettymapp / OSM data behind the same controls (ADR-0009).",
        markdown=True,
    )
    return indah.Session(
        indah.Column(children=[intro, indah.Sidebar(children=[controls, preview])])
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
