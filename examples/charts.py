"""Hybrid charting (ADR-0018): a live client chart beside static server plots.

Three ways to draw, side by side:

- a live-updating line chart -- ``Chart`` streams points over the append op, so the
  curve grows at O(point) and zoom/hover run in the browser (client-side, uPlot);
- a reactive line chart -- ``Chart`` whose data is recomputed from a slider;
- a static Matplotlib ``Plot`` and a heatmap -- rasterised to a PNG on the Python
  side (the zero-JS path), so they need nothing in the browser.

Matplotlib is duck-typed (as in the built-in demo): if it is not installed the two
static panels fall back to an inline-SVG note, so the example still runs on indah
alone. Run it with:  python examples/charts.py   (or `make demo` for the full tour).
"""

from __future__ import annotations

import asyncio
import math
import urllib.parse

import indah


def _matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib.figure import Figure

        return Figure
    except Exception:
        return None


def _sine_plot():
    Figure = _matplotlib()
    if Figure is None:
        return _svg_note("matplotlib not installed")

    def figure():
        fig = Figure(figsize=(4, 2.4))
        ax = fig.add_subplot(111)
        xs = [i * 0.2 for i in range(40)]
        ax.plot(xs, [math.sin(x) for x in xs], color="#b5296b")
        ax.plot(xs, [math.cos(x) for x in xs], color="#2e6d62")
        ax.set_title("Static Matplotlib plot")
        return fig

    return indah.Plot(figure, alt="sine and cosine")


def _heatmap():
    Figure = _matplotlib()
    if Figure is None:
        return _svg_note("matplotlib not installed")

    def figure():
        fig = Figure(figsize=(4, 2.4))
        ax = fig.add_subplot(111)
        grid = [[math.sin(x / 3) * math.cos(y / 3) for x in range(30)] for y in range(20)]
        ax.imshow(grid, aspect="auto", cmap="magma")
        ax.set_title("Heatmap (server PNG)")
        ax.set_axis_off()
        return fig

    return indah.Plot(figure, alt="heatmap")


def _svg_note(text: str):
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='120'>"
        f"<rect width='320' height='120' rx='12' fill='#f3ebe0'/>"
        f"<text x='160' y='64' font-size='14' fill='#6e6169' text-anchor='middle' "
        f"font-family='sans-serif'>{text}</text></svg>"
    )
    return indah.Image("data:image/svg+xml," + urllib.parse.quote(svg, safe=""), alt=text)


def build() -> indah.Session:
    # 1) A live line chart fed by streaming points (client-side uPlot).
    live = indah.Chart(series=["loss"], title="Live training loss", x_label="step", points=True)
    running = indah.Signal(False)

    async def train() -> None:
        if running.value:
            return
        running.set(True)
        live.clear()
        loss = 1.6
        for step in range(80):
            loss = max(0.05, loss * 0.96 + (0.02 * math.sin(step / 3)))
            live.push(step, round(loss, 4))
            await asyncio.sleep(0.05)  # a real training step would take longer
        running.set(False)

    # 2) A reactive chart recomputed from a slider (interactive, no streaming).
    k = indah.Signal(2.0)
    reactive = indah.Chart(
        lambda: [[x, k.value * math.sin(x / 4)] for x in range(48)],
        series=["k·sin(x/4)"],
        title="Reactive chart",
        x_label="x",
    )

    controls = indah.Card(
        title="Controls",
        children=[
            indah.Button("Run training", on_click=train),
            indah.Spinner(active=running, label="training..."),
            indah.Slider(k, min=1, max=8, step=0.5, label="Amplitude k"),
        ],
    )

    charts = indah.Grid(
        columns=2,
        children=[
            indah.Card(children=[live]),
            indah.Card(children=[reactive]),
            indah.Card(children=[_sine_plot()]),
            indah.Card(children=[_heatmap()]),
        ],
    )

    intro = indah.Text(
        "# Hybrid charting\n\n"
        "Client-side **Chart** (interactive, live-updating) alongside server-PNG "
        "**Plot** (static, zero-JS). Both ride the same reactive props -- no wire "
        "change (ADR-0018).",
        markdown=True,
    )
    return indah.Session(indah.Column(children=[intro, indah.Sidebar(children=[controls, charts])]))


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
