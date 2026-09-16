"""A poster / artifact generator: tweak inputs, watch a poster render, download it.

The prettymapp archetype - the most-shared kind of community showcase app: a handful
of controls drive a striking generated image you can download. Here the artifact is a
parametric generative-art poster (no map data or heavy dependency needed, so it runs
on indah alone); the pattern is identical to wrapping prettymapp, matplotlib, or a
diffusion image behind the same controls.

What it shows off:
- **reactive rendering** - the preview recomputes from the inputs with no rerun, only
  the image node patches;
- **file-out** - the finished poster downloads as an SVG via the ``Download`` component
  (ADR-0017), served per session.

Run it with:  python examples/poster.py   (prints a URL; embeds inline in a cell).
"""

from __future__ import annotations

import math
import random
import urllib.parse

import indah

# prettymapp-flavoured palette names, each a small set of ramp colours + a ground.
_PALETTES = {
    "Peach": {
        "ground": "#fff1e6",
        "ink": "#5a2a27",
        "ramp": ["#ffb4a2", "#e5989b", "#b5838d", "#e0701a"],
    },
    "Auburn": {
        "ground": "#20161a",
        "ink": "#f3e6de",
        "ramp": ["#b5296b", "#7a1f4f", "#c0362c", "#e0701a"],
    },
    "Citrus": {
        "ground": "#fffdf4",
        "ink": "#2e3b1f",
        "ramp": ["#e0b500", "#7fae00", "#2e6d62", "#3aa76d"],
    },
    "Flannel": {
        "ground": "#101418",
        "ink": "#dfe7ee",
        "ramp": ["#3457d5", "#2e6d62", "#8a3ffc", "#5b7a9a"],
    },
}
_STYLES = ["Concentric", "Grid", "Waves"]


def render_poster(title: str, palette: str, style: str, density: int, seed: int) -> str:
    """Deterministically render a poster to an SVG string from the controls."""
    pal = _PALETTES.get(palette, _PALETTES["Peach"])
    ground, ink, ramp = pal["ground"], pal["ink"], pal["ramp"]
    rng = random.Random(f"{style}-{density}-{seed}")
    w, h = 600, 800
    art_h = 640
    shapes: list[str] = []

    if style == "Concentric":
        cx, cy = w / 2, art_h / 2
        for i in range(density * 3, 0, -1):
            r = 30 + i * (min(w, art_h) / (density * 3 + 2)) / 2
            shapes.append(
                f"<circle cx='{cx + rng.randint(-20, 20)}' cy='{cy + rng.randint(-20, 20)}' "
                f"r='{r:.0f}' fill='none' stroke='{ramp[i % len(ramp)]}' stroke-width='6'/>"
            )
    elif style == "Grid":
        cols = max(2, density)
        cell = w / cols
        rows = int(art_h / cell)
        for gy in range(rows):
            for gx in range(cols):
                if rng.random() < 0.72:
                    shapes.append(
                        f"<rect x='{gx * cell:.0f}' y='{gy * cell:.0f}' "
                        f"width='{cell:.0f}' height='{cell:.0f}' "
                        f"fill='{ramp[rng.randint(0, len(ramp) - 1)]}' "
                        f"fill-opacity='{rng.uniform(0.5, 1):.2f}'/>"
                    )
    else:  # Waves
        bands = density * 2
        for b in range(bands):
            y0 = art_h * b / bands
            amp = rng.uniform(10, 40)
            pts = " ".join(
                f"{x},{y0 + amp * math.sin(x / 60 + b + seed):.0f}" for x in range(0, w + 20, 20)
            )
            shapes.append(
                f"<polyline points='{pts}' fill='none' stroke='{ramp[b % len(ramp)]}' "
                f"stroke-width='5' stroke-opacity='0.85'/>"
            )

    safe_title = (title or "Untitled").strip()[:28]
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}'>"
        f"<rect width='{w}' height='{h}' fill='{ground}'/>"
        f"<svg width='{w}' height='{art_h}'>{''.join(shapes)}</svg>"
        f"<text x='40' y='{art_h + 70}' font-size='42' font-family='Georgia, serif' "
        f"font-weight='700' fill='{ink}'>{_escape(safe_title)}</text>"
        f"<text x='40' y='{art_h + 108}' font-size='18' font-family='sans-serif' "
        f"fill='{ink}' fill-opacity='0.7'>{palette} · {style} · made with indah</text>"
        "</svg>"
    )
    return svg


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _data_uri(svg: str) -> str:
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


def build() -> indah.Session:
    title = indah.Signal("Kuala Lumpur")
    palette = indah.Signal("Peach")
    style = indah.Signal("Concentric")
    density = indah.Signal(6)
    seed = indah.Signal(7)

    def svg() -> str:
        return render_poster(
            title.value, palette.value, style.value, int(density.value), int(seed.value)
        )

    controls = indah.Card(
        title="Design",
        children=[
            indah.TextInput(title, label="Title", placeholder="Poster title..."),
            indah.Select(palette, options=list(_PALETTES), label="Palette"),
            indah.Radio(style, options=_STYLES, label="Style"),
            indah.Slider(density, min=3, max=12, step=1, label="Density"),
            indah.Slider(seed, min=0, max=50, step=1, label="Seed"),
            indah.Download(
                lambda: indah.DownloadFile(
                    svg().encode("utf-8"), filename="poster.svg", media_type="image/svg+xml"
                ),
                label="Download poster (SVG)",
            ),
        ],
    )

    preview = indah.Card(children=[indah.Image(lambda: _data_uri(svg()), alt="poster preview")])

    intro = indah.Text(
        "# Poster generator\n\n"
        "Tweak the controls and the poster re-renders live (reactive - only the image "
        "patches, no rerun), then **download** it. Swap the generator for prettymapp, "
        "matplotlib, or a diffusion image behind the same controls (ADR-0009).",
        markdown=True,
    )
    return indah.Session(
        indah.Column(children=[intro, indah.Sidebar(children=[controls, preview])])
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
