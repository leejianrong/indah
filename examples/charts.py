"""Hybrid charting: a live client chart beside static server plots.

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


# A Plot is a PNG, and a PNG does not know whether the page is light or dark. So the figures are
# drawn on a transparent background with mid-grey ink that reads on both (IND-177).
_INK = "#8d8691"


def _transparent(fig, *axes):
    """Transparent figure and axes, mid-grey text, spines and ticks."""
    fig.patch.set_alpha(0)
    for ax in axes:
        ax.set_facecolor("none")
        ax.title.set_color(_INK)
        ax.tick_params(colors=_INK)
        for spine in ax.spines.values():
            spine.set_color(_INK)
    return fig


def _sine_figure():
    from matplotlib.figure import Figure

    fig = Figure(figsize=(4, 2.4))
    ax = fig.add_subplot(111)
    xs = [i * 0.2 for i in range(40)]
    ax.plot(xs, [math.sin(x) for x in xs], color="#b5296b")
    ax.plot(xs, [math.cos(x) for x in xs], color="#2e6d62")
    ax.set_title("Static Matplotlib plot")
    return _transparent(fig, ax)


def _heatmap_figure():
    from matplotlib.figure import Figure

    fig = Figure(figsize=(4, 2.4))
    ax = fig.add_subplot(111)
    grid = [[math.sin(x / 3) * math.cos(y / 3) for x in range(30)] for y in range(20)]
    ax.imshow(grid, aspect="auto", cmap="magma")
    ax.set_title("Heatmap (server PNG)")
    ax.set_axis_off()
    return _transparent(fig, ax)


def _sine_plot():
    if _matplotlib() is None:
        return _svg_note("matplotlib not installed")
    return indah.Plot(_sine_figure, alt="sine and cosine")


def _heatmap():
    if _matplotlib() is None:
        return _svg_note("matplotlib not installed")
    return indah.Plot(_heatmap_figure, alt="heatmap")


def _svg_note(text: str):
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='120'>"
        f"<rect width='320' height='120' rx='12' fill='#8d8691' fill-opacity='0.14'/>"
        f"<text x='160' y='64' font-size='14' fill='#8d8691' text-anchor='middle' "
        f"font-family='sans-serif'>{text}</text></svg>"
    )
    return indah.Image("data:image/svg+xml," + urllib.parse.quote(svg, safe=""), alt=text)


_STEPS = 80


def _loss_curve():
    """The mock training loss, one ``(step, loss)`` per step (the same curve every time)."""
    loss = 1.6
    for step in range(_STEPS):
        loss = max(0.05, loss * 0.96 + (0.02 * math.sin(step / 3)))
        yield step, round(loss, 4)


def build() -> indah.Session:
    # 1) A live line chart fed by streaming points (client-side uPlot).
    live = indah.Chart(series=["loss"], title="Live training loss", x_label="step", points=True)
    running = indah.Signal(False)
    # Open on a finished sample run, so the visitor sees a curve at once (IND-179); a run clears it.
    live.extend([[step, loss] for step, loss in _loss_curve()])

    async def train() -> None:
        if running.value:
            return
        running.set(True)
        live.clear()
        for step, loss in _loss_curve():
            live.push(step, loss)
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
            indah.Text(
                "Showing a sample run. Press Run training to watch a new one.", variant="caption"
            ),
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
        "**Plot** (static, zero-JS). Both ride the same reactive props, so nothing "
        "about the wiring changes between them.",
        markdown=True,
    )
    return indah.Session(indah.Column(children=[intro, indah.Sidebar(children=[controls, charts])]))


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
