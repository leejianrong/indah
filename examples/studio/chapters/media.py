"""Chapter 7: charts, images, maps, audio and files in and out."""

from __future__ import annotations

import io
import math
import random
import struct
import sys
import threading
import wave
import zlib

import indah

from ..core import Chapter, Page

# ---- generators (pure Python, deterministic) --------------------------------------------------


def make_png(width: int, height: int, pixel) -> bytes:
    """A small RGBA PNG from ``pixel(x, y) -> (r, g, b, a)``; stdlib only."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixel(x, y))

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )


def scene_png() -> bytes:
    """A little landscape: sky gradient, a sun, a hill and a house."""

    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        if (x - 130) ** 2 + (y - 30) ** 2 < 15**2:
            return (255, 214, 90, 255)
        if y > 95 + 10 * math.sin(x / 22):
            return (74, 140, 84, 255)
        if 40 < x < 80 and 62 < y < 98:
            return (190, 96, 80, 255)
        return (110 + y, 160 + y // 2, 235, 255)

    return make_png(160, 120, pixel)


def mask_png() -> bytes:
    """A translucent overlay (the "house" segment) the same size as the scene."""
    return make_png(
        160,
        120,
        lambda x, y: (230, 50, 90, 255) if 40 < x < 80 and 62 < y < 98 else (0, 0, 0, 0),
    )


def tile_png(index: int) -> bytes:
    """A 96x96 swatch whose hue depends on ``index``."""
    hue = (index * 47) % 255
    return make_png(
        96,
        96,
        lambda x, y: (hue, (x * 2 + hue) % 255, (y * 2 + 90) % 255, 255),
    )


def curve_png() -> bytes:
    """A 360x180 line plot drawn pixel by pixel (stands in for a Matplotlib figure)."""
    w, h = 360, 180
    points = {x: int(h / 2 - 60 * math.sin(x / 28) * math.exp(-x / 400)) for x in range(w)}

    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        if abs(y - points[x]) <= 1:
            return (91, 91, 214, 255)
        if y == h // 2 or x == 0:
            return (150, 150, 150, 255)
        return (255, 255, 255, 255)

    return make_png(w, h, pixel)


def tone_wav(freq: float, seconds: float = 0.5, rate: int = 16000) -> bytes:
    """A mono 16-bit WAV sine tone."""
    frames = b"".join(
        struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * n / rate)))
        for n in range(int(seconds * rate))
    )
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)
    return out.getvalue()


def ripple(freq: float) -> list[list[float]]:
    """A 48x32 field, column-major (z[x][y]), for the heatmap."""
    return [[math.sin(freq * math.hypot(x - 24, y - 16) / 3) for y in range(32)] for x in range(48)]


# ---- chart ------------------------------------------------------------------------------------


def live_chart(ctx: indah.Context) -> indah.Component:
    chart = indah.Chart(series=["signal"], title="Live signal", x_label="tick", points=True)
    rng = random.Random(7)
    ticks = indah.Signal(0)

    def add(n: int) -> None:
        for _ in range(n):
            chart.push(ticks.value, math.sin(ticks.value / 6) + rng.uniform(-0.2, 0.2))
            ticks.set(ticks.value + 1)

    def reset() -> None:
        chart.clear()
        ticks.set(0)

    add(30)  # start with a curve already on screen

    return indah.Column(
        children=[
            chart,
            indah.Row(
                children=[
                    indah.Button("Add 10 points", lambda: add(10)),
                    indah.Button("Clear", reset, variant="ghost"),
                ]
            ),
            indah.Text(lambda: f"{ticks.value} points pushed (only the new rows travel)."),
        ]
    )


def live_chart_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".chart canvas").first).to_be_visible()
    expect(page.get_by_text("30 points pushed")).to_be_visible()
    page.get_by_role("button", name="Add 10 points").click()
    expect(page.get_by_text("40 points pushed")).to_be_visible()
    page.wait_for_function("() => document.querySelector('.chart').__uplot.data[0].length === 40")
    page.get_by_role("button", name="Clear").click()
    expect(page.get_by_text("0 points pushed")).to_be_visible()
    page.wait_for_function("() => document.querySelector('.chart').__uplot.data[0].length === 0")
    page.get_by_role("button", name="Add 10 points").click()
    page.get_by_role("button", name="Add 10 points").click()
    page.wait_for_function("() => document.querySelector('.chart').__uplot.data[0].length === 20")


def chart_kinds(ctx: indah.Context) -> indah.Component:
    rng = random.Random(3)
    n = 60
    decay = [[i, round(0.97**i, 4)] for i in range(1, n + 1)]
    dots = [
        [i, round(40 + 55 * (1 - 0.97**i) + rng.uniform(-12, 12), 1), None] for i in range(1, n + 1)
    ]
    for row in dots[::7]:
        row[1], row[2] = None, row[1] - 25  # a few runs that did badly
    at = indah.Signal(30)

    return indah.Column(
        children=[
            indah.Slider(at, min=1, max=n, step=1, label="Current episode"),
            indah.Chart(
                decay,
                series=[{"label": "decay", "kind": "bars", "stroke": "var(--primary)"}],
                title="Bars, with a playhead, the future dimmed and the current bar highlighted",
                x_range=(0.5, n + 0.5),
                y_range=(0, 1),
                playhead=at,
                shade_after=True,
                highlight=at,
                highlight_color="var(--ok)",
                legend="off",
                height=170,
            ),
            indah.Chart(
                dots,
                series=[
                    {"label": "good", "kind": "scatter", "stroke": "var(--primary)", "size": 6},
                    {"label": "poor", "kind": "scatter", "stroke": "var(--muted)", "size": 6},
                ],
                title="Scatter dots and a dashed reference rule",
                x_range=(0.5, n + 0.5),
                y_range=(0, 110),
                rules=[{"y": 90, "label": "target 90", "color": "var(--ok)"}],
                legend="labels",
                height=170,
            ),
        ]
    )


def pie_lit(ctx: indah.Context) -> indah.Component:
    lit = indah.Signal(1)
    epsilon = 0.127
    return indah.Column(
        children=[
            indah.Pie(
                [
                    {"label": "explore", "value": epsilon, "color": "var(--warn)"},
                    {"label": "exploit", "value": 1 - epsilon, "color": "var(--primary)"},
                ],
                active=lit,
                height=170,
            ),
            indah.Row(
                children=[
                    indah.Button("Explore", lambda: lit.set(0), variant="ghost"),
                    indah.Button("Exploit", lambda: lit.set(1), variant="ghost"),
                    indah.Button("None", lambda: lit.set(None), variant="ghost"),
                ]
            ),
        ]
    )


def pie_lit_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".pie svg path").first).to_be_visible()
    expect(page.get_by_text("87.3%")).to_be_visible()
    page.get_by_role("button", name="Explore").click()
    page.wait_for_function(
        "() => { const p = document.querySelectorAll('.pie-slice');"
        " return p.length === 2 && p[0].style.opacity === '1' && p[1].style.opacity === '0.3'; }"
    )


def heatmap_marks(ctx: indah.Context) -> indah.Component:
    state = indah.Signal(12)
    action = indah.Signal(2)
    cols = 24
    field = [
        [None if (x * 5 + y * 3) % 7 < 2 else round(math.sin(x / 3 + y), 2) for y in range(4)]
        for x in range(cols)
    ]  # None is a cell with no value, drawn blank rather than as the lowest colour
    return indah.Column(
        children=[
            indah.Row(
                children=[
                    indah.Slider(state, min=0, max=cols - 1, step=1, label="State"),
                    indah.Slider(action, min=0, max=3, step=1, label="Action"),
                ]
            ),
            indah.Heatmap(
                field,
                colormap=["var(--err)", "var(--surface-2)", "var(--ok)"],
                zmin=-1,
                zmax=1,
                null_color="var(--surface)",
                origin="top",
                row_labels=["up", "down", "left", "right"],
                col_groups=[
                    {"start": 0, "end": 11, "label": "first half"},
                    {"start": 12, "end": 23, "label": "second half"},
                ],
                mark_x=state,
                mark_y=action,
                height=190,
                title="Blank cells, labels, groups and a marked cell",
            ),
        ]
    )


def heatmap_marks_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".heatmap canvas").first).to_be_visible()
    page.wait_for_function("() => document.querySelector('.heatmap').__heatmap.ncols === 24")


def chart_kinds_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".chart canvas").nth(1)).to_be_visible()
    expect(page.get_by_text("good", exact=True)).to_be_visible()  # the labels-only legend
    page.wait_for_function(
        "() => document.querySelectorAll('.chart')[1].__uplot.data[0].length === 60"
    )


# ---- slider that recomputes a chart on release ----------------------------------------------


def slider_release(ctx: indah.Context) -> indah.Component:
    n = indah.Signal(256)

    def curve() -> list[list[float]]:
        top = int(n.value)
        sizes = sorted({max(1, round(top * i / 40)) for i in range(1, 41)})
        return [[s, 3.1 * s**3 / 1e9, 40 * s**2 / 1e6] for s in sizes]

    return indah.Column(
        children=[
            indah.Slider(
                n,
                min=16,
                max=4096,
                step=1,
                label="Problem size n",
                scale="log",
                show_value=True,
                commit="release",
                marks=[{"value": 64}, {"value": 1024, "label": "cliff 1,024"}, {"value": 4096}],
            ),
            indah.Chart(
                curve,
                series=[
                    {"label": "n cubed term", "stroke": "var(--primary)"},
                    {"label": "n squared term", "stroke": "var(--muted)"},
                ],
                title="Cost terms up to n (recomputed when the thumb is released)",
                x_label="size",
                y_label="cost (millions of gates)",
                playhead=n,
                height=220,
            ),
            indah.Text(lambda: f"The server has n = {n.value:,.0f} (it only changes on release)."),
        ]
    )


def slider_range(ctx: indah.Context) -> indah.Component:
    # The track follows the data: choosing a world changes the years the slider covers.
    worlds = {"Long": (1900, 2020), "Short": (1990, 2000)}
    world = indah.Signal("Long")
    year = indah.Signal(1950)

    return indah.Column(
        children=[
            indah.Select(
                world,
                options=list(worlds),
                label="World",
            ),
            indah.Slider(
                year,
                min=lambda: worlds[world.value][0],
                max=lambda: worlds[world.value][1],
                label="Year",
                show_value=True,
            ),
            indah.Text(lambda: f"Year {year.value:.0f} of {worlds[world.value]}."),
        ]
    )


# ---- chart steps, scales and annotations ------------------------------------------------------


def chart_steps(ctx: indah.Context) -> indah.Component:
    # Best-so-far cost by day: it only changes when someone beats it, so it is a staircase. The
    # public record is sampled on other days, which chart_rows aligns into one table.
    ours = [(0, 120.0), (3, 96.0), (4, 71.5), (9, 58.0), (14, 44.0), (21, 41.2)]
    public = [(0, 90.0), (7, 62.0), (16, 45.0)]
    rows = indah.chart_rows({"ours": ours, "public best": public})
    # A cost model that spans decades: gates grow as n cubed, so a log axis is the readable one.
    sizes = [2**k for k in range(4, 13)]
    gates = [[n, 3.1 * n**3 / 1000] for n in sizes]
    return indah.Column(
        children=[
            indah.Chart(
                rows,
                series=[
                    {"label": "ours", "kind": "step", "stroke": "var(--primary)", "width": 2.5},
                    {
                        "label": "public best",
                        "kind": "step",
                        "stroke": "var(--muted)",
                        "dash": [5, 4],
                    },
                ],
                title="Best cost so far (a staircase, lower is better)",
                x_label="day",
                y_range=(30, 130),
                rules=[
                    {"y": 45, "label": "threshold 45", "color": "var(--ok)"},
                    {"x": 9, "label": "v3 promoted", "color": "var(--primary)"},
                ],
                bands=[{"y0": 30, "y1": 45, "color": "var(--ok)", "alpha": 0.1}],
                markers=[{"x": 14, "y": 44, "label": "44 on day 14", "color": "var(--ok)"}],
                height=240,
            ),
            indah.Chart(
                gates,
                series=[{"label": "cost", "stroke": "var(--primary)"}],
                title="Cost against size, both axes logarithmic",
                x_label="size n",
                x_scale="log",
                y_scale="log",
                y_range=(10, 10_000_000),
                bands=[{"x0": 2048, "x1": 4096, "color": "var(--err)", "label": "over budget"}],
                rules=[{"y": 1000, "label": "budget", "color": "var(--err)"}],
                points=True,
                height=240,
            ),
        ]
    )


_BENCH = [["adder", 120], ["qft", 310], ["grover", 540], ["shor", 880], ["vqe", 260]]


def chart_events(ctx: indah.Context) -> indah.Component:
    clicked = indah.Signal(None)
    hovered = indah.Signal(None)
    picked = indah.Signal(None)

    def follow() -> None:
        if clicked.value is not None:
            picked.set(clicked.value["index"])

    indah.effect(follow)  # a click on a bar selects that table row
    return indah.Column(
        children=[
            indah.Chart(
                _BENCH,
                series=[{"label": "gates", "kind": "bars", "stroke": "var(--primary)"}],
                title="Gates per benchmark",
                x_scale="category",
                hovered=hovered,
                clicked=clicked,
                height=240,
            ),
            indah.Text(
                lambda: (
                    "Hover a bar."
                    if hovered.value is None
                    else f"Over {hovered.value['x']}: {hovered.value['y']} gates"
                ),
                variant="caption",
            ),
            indah.Table(
                [{"benchmark": b, "gates": g} for b, g in _BENCH],
                selected=picked,
                label="Benchmarks",
            ),
            indah.Text(
                lambda: (
                    "Click a bar."
                    if picked.value is None
                    else f"Selected: {_BENCH[picked.value][0]}"
                )
            ),
        ]
    )


def chart_events_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    plot = page.locator(".u-over").first
    expect(plot).to_be_visible(timeout=15_000)
    box = plot.bounding_box()
    assert box is not None
    # The fourth of five bars, "shor", sits at 70 percent of the plot's width.
    x, y = box["x"] + box["width"] * 0.7, box["y"] + box["height"] * 0.7
    page.mouse.move(x, y)
    expect(page.get_by_text("Over shor: 880 gates")).to_be_visible()
    page.mouse.move(box["x"] + box["width"] + 40, box["y"] + box["height"] + 40)
    expect(page.get_by_text("Hover a bar.")).to_be_visible()  # leaving clears it
    page.mouse.click(x, y)
    expect(page.get_by_text("Selected: shor")).to_be_visible()


def chart_bars(ctx: indah.Context) -> indah.Component:
    stages = [["adder", 30, 50, 40], ["qft", 90, 120, 100], ["grover", 160, 210, 170]]
    funnel = [["submitted", 1200], ["compiled", 940], ["optimised", 610], ["verified", 280]]
    spread = indah.box_rows(
        {
            "fast": [8, 9, 9, 10, 11, 12, 14],
            "steady": [20, 22, 25, 26, 30, 31, 40],
            "slow": [30, 55, 60, 75, 90, 120],
        }
    )
    return indah.Column(
        children=[
            indah.Chart(
                stages,
                series=[
                    {"label": "parse", "kind": "bars"},
                    {"label": "route", "kind": "bars"},
                    {"label": "emit", "kind": "bars"},
                ],
                title="Stage time per circuit (stacked)",
                x_scale="category",
                stack=True,
                height=240,
            ),
            indah.Chart(
                funnel,
                series=[{"label": "circuits", "kind": "bars", "stroke": "var(--primary)"}],
                title="Funnel (horizontal)",
                x_scale="category",
                orientation="horizontal",
                height=220,
            ),
            indah.Chart(
                spread,
                series=[{"label": "latency", "kind": "box", "stroke": "var(--primary)"}],
                title="Latency spread (box)",
                x_scale="category",
                height=240,
            ),
        ]
    )


def chart_bars_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".u-over")).to_have_count(3, timeout=15_000)
    plots = page.evaluate(
        "() => [...document.querySelectorAll('.u-over')].map((o) => { const u = o.closest('.chart, div')"
        " ; return o.getBoundingClientRect().width; })"
    )
    assert all(w > 100 for w in plots)
    # Stacked: the top series' data are running totals, so its value is the sum of the three.
    totals = page.evaluate("document.querySelectorAll('.uplot')[0].parentElement.__uplot.data[3]")
    assert totals == [120, 310, 540], totals
    # A box series is one legend entry, not five.
    expect(page.locator(".uplot").nth(2).locator(".u-series:visible")).to_have_count(1)  # latency


def chart_axes(ctx: indah.Context) -> indah.Component:
    import datetime

    # A run sampled every six hours: x is a real timestamp, so the axis shows dates.
    start = datetime.datetime(2026, 11, 1)
    runs = [[start + datetime.timedelta(hours=6 * i), 100 - 3.2 * i + (i % 3)] for i in range(14)]
    # Bit widths are counts: a narrow range must not show 2.5 or 3.5.
    widths = [[w, 2**w] for w in range(3, 8)]
    step = indah.Signal(6)
    return indah.Column(
        children=[
            indah.Chart(
                runs,
                series=[{"label": "cost", "stroke": "var(--primary)"}],
                title="Cost by time (UTC)",
                x_scale="time",
                height=220,
            ),
            indah.Chart(
                widths,
                series=[{"label": "states", "stroke": "var(--primary)"}],
                title="States by bit width",
                x_label="bits",
                x_integer=True,
                points=True,
                height=220,
            ),
            indah.Slider(step, min=0, max=13, label="Step"),
            indah.Chart(
                [[i, 100 - 3.2 * i + (i % 3)] for i in range(14)],
                series=[{"label": "cost", "stroke": "var(--primary)"}],
                title="A labelled playhead",
                x_integer=True,
                playhead=step,
                playhead_label=lambda: f"step {step.value:.0f}",
                height=220,
            ),
        ]
    )


def chart_category(ctx: indah.Context) -> indah.Component:
    # Gate counts per benchmark, with a budget line the slider moves: the line is a callable, so
    # the overlay redraws without rebuilding the chart.
    rows = [["adder", 120], ["qft", 310], ["grover", 540], ["shor", 880], ["vqe", 260]]
    budget = indah.Signal(400)
    return indah.Column(
        children=[
            indah.Slider(budget, min=100, max=1000, step=10, label="Budget", show_value=True),
            indah.Chart(
                rows,
                series=[{"label": "gates", "kind": "bars", "stroke": "var(--primary)"}],
                title="Gates per benchmark",
                x_scale="category",
                y_range=(0, 1000),
                rules=lambda: [{"y": budget.value, "label": f"budget {budget.value:.0f}"}],
                bands=lambda: [
                    {"y0": budget.value, "y1": 1000, "color": "var(--err)", "alpha": 0.08}
                ],
                height=260,
            ),
        ]
    )


def chart_category_check(pw) -> None:
    page = pw.page
    page.wait_for_function("() => document.querySelector('.chart')?.__uplot")
    # Five bars at positions 0..4, and half a slot of room either side.
    assert page.evaluate(
        "() => { const u = document.querySelector('.chart').__uplot;"
        " return u.data[0].join() === '0,1,2,3,4' && u.scales.x.min === -0.5 && u.scales.x.max === 4.5; }"
    )
    # The axis writes the labels, not the positions.
    assert page.evaluate(
        "() => { const u = document.querySelector('.chart').__uplot;"
        " return u.axes[0].values(u, [0, 1, 4]).join() === 'adder,qft,vqe'; }"
    )
    uplot_before = page.evaluate(
        "() => { window.__u = document.querySelector('.chart').__uplot; return 1; }"
    )
    slider = page.locator("input[type=range]")
    slider.evaluate(
        "(el) => { el.value = 700; el.dispatchEvent(new Event('input', {bubbles: true}));"
        " el.dispatchEvent(new Event('change', {bubbles: true})); }"
    )
    page.wait_for_function(
        "() => document.querySelector('.chart').parentElement.parentElement.textContent.includes('700')"
    )
    # The same plot instance is still there: the line moved without a rebuild.
    assert page.evaluate("() => window.__u === document.querySelector('.chart').__uplot")
    assert uplot_before == 1


def chart_axes_check(pw) -> None:
    page = pw.page
    page.wait_for_function(
        "() => { const c = document.querySelectorAll('.chart');"
        " return c.length === 3 && [...c].every((e) => e.__uplot); }"
    )
    # The time chart's scale is a time scale; the first x is 2026-11-01 00:00 UTC.
    assert page.evaluate(
        "() => { const u = document.querySelectorAll('.chart')[0].__uplot;"
        " return u.scales.x.time === true && u.data[0][0] === 1793491200; }"
    )
    # Integer ticks: every x axis split that is drawn is a whole number.
    page.wait_for_function(
        "() => { const u = document.querySelectorAll('.chart')[1].__uplot;"
        " const ax = u.axes[0]; const vals = ax._splits.filter((v, i) => ax.filter(u, ax._splits, 0)[i] != null);"
        " return vals.length > 0 && vals.every(Number.isInteger); }"
    )
    page.wait_for_function(
        "() => document.querySelectorAll('.chart')[2].__uplot.data[0].length === 14"
    )


def slider_release_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".chart canvas").first).to_be_visible()
    expect(page.locator(".slider-value")).to_have_text("256")
    expect(page.locator(".slider-mark")).to_have_count(3)
    expect(page.get_by_text("The server has n = 256")).to_be_visible()
    slider = page.locator("input[type=range]")

    def drag_to(position: int, fire_change: bool) -> None:
        slider.evaluate(
            "(el, [p, c]) => { el.value = p; el.dispatchEvent(new Event('input', {bubbles: true}));"
            " if (c) el.dispatchEvent(new Event('change', {bubbles: true})); }",
            [position, fire_change],
        )

    drag_to(400, False)  # the far end of the log track: the readout follows, nothing is sent
    expect(page.locator(".slider-value")).to_have_text("4,096")
    page.wait_for_timeout(500)
    expect(page.get_by_text("The server has n = 256")).to_be_visible()
    drag_to(400, True)  # release
    expect(page.get_by_text("The server has n = 4,096")).to_be_visible()
    page.wait_for_function(
        "() => { const d = document.querySelector('.chart').__uplot.data[0];"
        " return d[d.length - 1] === 4096; }"
    )


def choice_cards(ctx: indah.Context) -> indah.Component:
    level = indah.Signal("normal")
    blurbs = {
        "easy": "Forgiving: hints are on and mistakes are free.",
        "normal": "The intended game: hints on request.",
        "hard": "No hints and one life.",
    }
    return indah.Column(
        children=[
            indah.ChoiceCards(
                level,
                label="Difficulty",
                options=[
                    {
                        "value": k,
                        "title": k.title(),
                        "body": v,
                        **({"badge": "Recommended"} if k == "normal" else {}),
                    }
                    for k, v in blurbs.items()
                ],
                columns=3,
            ),
            indah.Text(lambda: f"You picked {level.value}: {blurbs[level.value]}"),
        ]
    )


def choice_cards_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".choicecard")).to_have_count(3)
    expect(page.get_by_role("radio", name="Normal")).to_be_checked()
    expect(page.locator(".choicecard-badge")).to_have_text("Recommended")
    expect(page.locator(".choicecards")).to_have_attribute("data-cols", "3")
    page.locator(".choicecard", has_text="Hard").click()
    expect(page.get_by_text("You picked hard: No hints and one life.")).to_be_visible()
    expect(page.locator(".choicecard.on")).to_have_count(1)
    # A native radio group: the arrow keys move the choice.
    page.get_by_role("radio", name="Hard").focus()
    page.keyboard.press("ArrowUp")
    expect(page.get_by_text("You picked normal")).to_be_visible()


def timeline_page(ctx: indah.Context) -> indah.Component:
    # A world that changes on irregular dates: it steps through exactly its dates.
    years = [1990, 1994, 1995, 2001, 2003, 2004, 2010, 2016, 2020]
    events = [0, 3, 1, 0, 5, 2, 0, 1, 4]
    year = indah.Signal(1990)
    playing = indah.Signal(False)
    return indah.Column(
        children=[
            indah.Timeline(
                year,
                years,
                density=events,
                unit="year",
                playing=playing,
                speed=4,
                label="History",
            ),
            indah.Text(lambda: f"{year.value}", variant="display"),
            indah.Text(lambda: "Playing." if playing.value else "Paused."),
        ]
    )


def timeline_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".timeline-now")).to_have_text("1990")
    expect(page.locator(".timeline-bar")).to_have_count(9)
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page.locator(".timeline-now")).to_have_text("1994")
    expect(page.get_by_text("1994", exact=True).first).to_be_visible()
    # "Next event" skips a point with no density (1995 has some, 2001 has none).
    page.get_by_role("button", name="Next event").click()
    expect(page.locator(".timeline-now")).to_have_text("1995")
    page.get_by_role("button", name="Next event").click()
    expect(page.locator(".timeline-now")).to_have_text("2003")  # 2001 has no events
    page.get_by_role("button", name="Previous event").click()
    expect(page.locator(".timeline-now")).to_have_text("1995")
    # A keyboard user can play and pause: space on the track.
    slider = page.get_by_role("slider")
    expect(slider).to_have_attribute("aria-valuetext", "year 1995, step 3 of 9")
    slider.focus()
    page.keyboard.press("End")
    expect(page.locator(".timeline-now")).to_have_text("2020")
    page.keyboard.press("Home")
    expect(page.locator(".timeline-now")).to_have_text("1990")
    page.keyboard.press(" ")
    expect(page.get_by_text("Playing.")).to_be_visible()
    # At 4 steps a second it reaches the end by itself and stops there.
    expect(page.locator(".timeline-now")).to_have_text("2020", timeout=6000)
    expect(page.get_by_text("Paused.")).to_be_visible()


def slider_range_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    slider = page.locator("input[type=range]")
    expect(slider).to_have_attribute("min", "1900")
    expect(slider).to_have_attribute("max", "2020")
    page.get_by_label("World").select_option("Short")
    expect(slider).to_have_attribute("min", "1990")
    expect(slider).to_have_attribute("max", "2000")
    expect(page.locator(".slider-value")).to_have_text("1,990")
    # The slider pulled the signal to the new range, so the server's own text agrees.
    expect(page.get_by_text("Year 1990 of")).to_be_visible()


def chart_steps_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".chart canvas").nth(1)).to_be_visible()
    # The union of the two series' days, with a gap where one has no point.
    page.wait_for_function(
        "() => { const u = document.querySelectorAll('.chart')[0].__uplot;"
        " return u.data[0].length === 8 && u.data[2].includes(null); }"
    )
    page.wait_for_function(
        "() => { const u = document.querySelectorAll('.chart')[1].__uplot;"
        " return u.scales.x.distr === 3 && u.scales.y.distr === 3; }"
    )


# ---- heatmap ----------------------------------------------------------------------------------


def heatmap(ctx: indah.Context) -> indah.Component:
    freq = indah.Signal(2.0)
    return indah.Column(
        children=[
            indah.Heatmap(
                lambda: ripple(freq.value),
                colormap="viridis",
                zmin=-1,
                zmax=1,
                title="Ripple",
                x_label="x",
                y_label="y",
            ),
            indah.Slider(freq, min=1, max=6, step=1, label="Frequency"),
            indah.Text(lambda: f"Frequency {freq.value:g}"),
        ]
    )


def _demo_graph(n: int = 900, groups: int = 5) -> tuple[list[dict], list[dict]]:
    """A small community graph, the same every time: nodes in groups, mostly linked within one."""
    rng = random.Random(7)
    nodes = [{"id": f"n{i}", "group": f"Team {i % groups + 1}"} for i in range(n)]
    links: set[tuple[int, int]] = set()
    while len(links) < int(n * 2.2):
        a = rng.randrange(n)
        near = rng.random() < 0.9
        b = (rng.randrange(n // groups) * groups + a % groups) % n if near else rng.randrange(n)
        if a != b:
            links.add((min(a, b), max(a, b)))
    edges = [
        {"source": f"n{a}", "target": f"n{b}", "id": f"e{i}"}
        for i, (a, b) in enumerate(sorted(links))
    ]
    return nodes, edges


def _longest_path(edges: list[dict], start: str) -> dict[str, list[str]]:
    """The shortest path from ``start`` to the node farthest from it, as node and edge ids."""
    around: dict[str, list[tuple[str, str]]] = {}
    for e in edges:
        around.setdefault(e["source"], []).append((e["target"], e["id"]))
        around.setdefault(e["target"], []).append((e["source"], e["id"]))
    came: dict[str, tuple[str, str] | None] = {start: None}
    queue, last = [start], start
    for node in queue:
        last = node
        for nxt, edge in around.get(node, []):
            if nxt not in came:
                came[nxt] = (node, edge)
                queue.append(nxt)
    nodes, links = [last], []
    while came[nodes[-1]] is not None:
        prev, edge = came[nodes[-1]]
        nodes.append(prev)
        links.append(edge)
    return {"nodes": nodes[::-1], "edges": links[::-1]}


def graph_page(ctx: indah.Context) -> indah.Component:
    nodes, edges = _demo_graph()
    path = _longest_path(edges, "n0")
    selected = indah.Signal(None)
    hovered = indah.Signal(None)
    window = indah.Signal(120)
    trace = indah.Signal(False)
    return indah.Column(
        children=[
            indah.Graph(
                nodes,
                edges,
                selected=selected,
                hovered=hovered,
                focus_size=window,
                highlight=lambda: path if trace.value else None,
                height=420,
                label="A community graph of 900 nodes",
            ),
            indah.Slider(window, min=20, max=900, step=10, label="Nodes drawn in full"),
            indah.Switch(trace, label="Highlight the longest path from n0"),
            indah.Text(lambda: f"Selected {selected.value}" if selected.value else "Click a node"),
            indah.Text(lambda: f"Hovering {hovered.value}" if hovered.value else "Hover a node"),
        ]
    )


def graph_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator('.graph-stage[data-settled="true"]')).to_be_visible(timeout=30_000)
    expect(page.locator(".graph-canvas")).to_be_visible()
    expect(page.get_by_text("Click a node", exact=True)).to_be_visible()
    page.locator(".graph-canvas").focus()
    page.keyboard.press("+")
    page.get_by_role("switch").click()  # highlight the path; the graph must not reload
    expect(page.locator('.graph-stage[data-settled="true"]')).to_be_visible()
    expect(page.get_by_text("Click a node", exact=True)).to_be_visible()


# A small world that changes by year: every node has a first and a last year, so a year view needs
# "not there yet", "this year" and "ended" without moving anything (ADR-0053).
_WORLD = [(f"n{i}", 2000 + (i * 5) // 40, 2002 + (i * 7) % 4 + (i % 3)) for i in range(40)]
_WORLD_EDGES = [(f"n{i}", f"n{(i * 3 + 1) % 40}") for i in range(40)] + [
    (f"n{i}", f"n{i + 1}") for i in range(39)
]


def _world_at(year: int) -> tuple[list[dict], list[dict]]:
    nodes = []
    for name, born, ended in _WORLD:
        node: dict = {"id": name, "label": name, "group": "past" if year > born else "new"}
        if born > year:
            node["opacity"] = 0.25  # not there yet
        elif ended < year:
            node.update(opacity=0.55, label_style="strike")  # ended
        elif born == year:
            node["ring"] = True  # new this year
        nodes.append(node)
    gone = {name for name, _, ended in _WORLD if ended < year}
    edges = [
        {
            "source": a,
            "target": b,
            **({"dash": True, "opacity": 0.8} if a in gone or b in gone else {}),
        }
        for a, b in _WORLD_EDGES
        if a != b
    ]
    return nodes, edges


def graph_styles_page(ctx: indah.Context) -> indah.Component:
    year = indah.Signal(2000)
    world = indah.computed(lambda: _world_at(year.value))
    return indah.Column(
        children=[
            indah.Graph(
                lambda: world.value[0],
                lambda: world.value[1],
                layout="stable",
                focus_size=6,
                height=380,
                label="A world by year",
            ),
            indah.Slider(year, min=2000, max=2004, step=1, label="Year", show_value=True),
            indah.Text(lambda: f"Year {year.value}", variant="caption"),
        ]
    )


def _grown(size: int) -> tuple[list[dict], list[dict]]:
    nodes = [{"id": f"k{i}", "label": f"k{i}", "group": "a" if i % 2 else "b"} for i in range(size)]
    edges = [{"source": f"k{i}", "target": f"k{(i * 5 + 2) % size}"} for i in range(size)]
    edges += [{"source": f"k{i}", "target": f"k{i + 1}"} for i in range(size - 1)]
    return nodes, [e for e in edges if e["source"] != e["target"]]


def graph_keep_page(ctx: indah.Context) -> indah.Component:
    size = indah.Signal(20)
    grown = indah.computed(lambda: _grown(size.value))
    return indah.Column(
        children=[
            indah.Graph(
                lambda: grown.value[0],
                lambda: grown.value[1],
                update="keep",
                transition_ms=300,
                height=380,
                label="A graph that grows",
            ),
            indah.Button("Add 10 nodes", on_click=lambda: size.set(size.value + 10)),
            indah.Text(lambda: f"{size.value} nodes", variant="caption"),
        ]
    )


def graph_keep_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator('.graph-stage[data-settled="true"]')).to_be_visible(timeout=30_000)
    ids = [f"k{i}" for i in range(20)]
    # World coordinates: the view re-fits to the larger graph, so screen positions may shift.
    read = (
        "(ids) => { const g = document.querySelector('.graph-stage').__graph; const v = g.view();"
        " return Object.fromEntries(ids.map((i) => { const [x, y] = g.screenOf(i);"
        " return [i, [Math.round((x - v.tx) / v.k * 100), Math.round((y - v.ty) / v.k * 100)]]; })); }"
    )
    before = page.evaluate(read, ids)
    page.get_by_role("button", name="Add 10 nodes").click()
    expect(page.get_by_text("30 nodes")).to_be_visible()
    page.wait_for_function("document.querySelector('.graph-stage').__graph.nodes === 30")
    page.wait_for_timeout(500)
    assert page.evaluate(read, ids) == before  # every id it already had stayed put


def graph_styles_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    stage = page.locator('.graph-stage[data-settled="true"]')
    expect(stage).to_be_visible(timeout=30_000)
    ids = [name for name, _, _ in _WORLD]
    read = "(ids) => Object.fromEntries(ids.map((i) => [i, document.querySelector('.graph-stage').__graph.screenOf(i)]))"
    before = page.evaluate(read, ids)
    slider = page.get_by_role("slider")
    slider.focus()
    for _ in range(4):
        slider.press("ArrowRight")
    expect(page.get_by_text("Year 2004")).to_be_visible()
    page.wait_for_timeout(600)
    after = page.evaluate(read, ids)
    # Stepping the year changed styles and groups, and not one node moved.
    assert before == after
    # An ended edge between two nodes that are only dots is still drawn, dashed.
    _, edges = _world_at(2004)
    gone = [
        e
        for e in edges
        if e.get("dash")
        and not page.evaluate(
            "([a, b]) => { const g = document.querySelector('.graph-stage').__graph;"
            " return g.isDetailed(a) || g.isDetailed(b); }",
            [e["source"], e["target"]],
        )
    ]
    assert gone, "no dashed edge lies outside the focus window"
    e = gone[0]
    hits = page.evaluate(
        """([a, b]) => {
          const stage = document.querySelector('.graph-stage');
          const c = stage.querySelector('canvas');
          const ctx = c.getContext('2d');
          const r = c.width / c.getBoundingClientRect().width;
          const [ax, ay] = stage.__graph.screenOf(a);
          const [bx, by] = stage.__graph.screenOf(b);
          let n = 0;
          for (let i = 1; i < 60; i++) {
            const t = i / 60;
            const d = ctx.getImageData(Math.round((ax + (bx - ax) * t) * r), Math.round((ay + (by - ay) * t) * r), 1, 1).data;
            if (d[3] > 0) n++;
          }
          return n;
        }""",
        [e["source"], e["target"]],
    )
    assert hits > 5, f"the dashed edge was not drawn ({hits} marked pixels)"


def heatmap_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".heatmap canvas").first).to_be_visible()
    slider = page.get_by_role("slider")
    slider.focus()
    slider.press("ArrowRight")
    expect(page.get_by_text("Frequency 3")).to_be_visible()
    expect(page.locator(".heatmap canvas").first).to_be_visible()


# ---- map --------------------------------------------------------------------------------------

CITIES = {"Paris": (48.8566, 2.3522), "Tokyo": (35.6762, 139.6503), "Lagos": (6.5244, 3.3792)}


def map_page(ctx: indah.Context) -> indah.Component:
    city = indah.Signal("Paris")
    center = indah.computed(lambda: CITIES[city.value])
    pin = indah.computed(
        lambda: [{"lat": center.value[0], "lon": center.value[1], "label": city.value}]
    )
    lat, lon = CITIES["Paris"]
    area = [{"points": [(lat + 0.02, lon - 0.03), (lat + 0.02, lon + 0.03), (lat - 0.02, lon)]}]
    return indah.Column(
        children=[
            indah.Map(center, zoom=11, markers=pin, polygons=area, height=300, label="City map"),
            indah.Select(city, options=list(CITIES), label="Fly to"),
            indah.Text(lambda: f"Centred on {city.value}."),
        ]
    )


def map_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".map.leaflet-container")).to_be_visible()
    expect(page.locator(".map path.leaflet-interactive")).to_have_count(2)  # marker + polygon
    page.get_by_label("Fly to").select_option("Tokyo")
    expect(page.get_by_text("Centred on Tokyo.")).to_be_visible()
    expect(page.locator(".map.leaflet-container")).to_be_visible()


# ---- plot / image / overlay -------------------------------------------------------------------


def plot_page(ctx: indah.Context) -> indah.Component:
    return indah.Plot(curve_png(), alt="damped sine")


def plot_check(pw) -> None:
    from playwright.sync_api import expect

    img = pw.page.get_by_role("img", name="damped sine")
    expect(img).to_be_visible()
    assert img.get_attribute("src").startswith("data:image/png;base64,")
    assert img.evaluate("el => el.naturalWidth") == 360


def image_page(ctx: indah.Context) -> indah.Component:
    sources = {
        "Bytes": scene_png(),
        "Data URI": "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='120'>"
        "<rect width='160' height='120' fill='%235b5bd6'/>"
        "<circle cx='80' cy='60' r='34' fill='%23ffd65a'/></svg>",
    }
    choice = indah.Signal("Bytes")
    return indah.Column(
        children=[
            indah.Radio(choice, options=list(sources), label="Source"),
            indah.Image(lambda: sources[choice.value], alt="the picture"),
        ]
    )


def image_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    img = page.get_by_role("img", name="the picture")
    expect(img).to_be_visible()
    assert img.get_attribute("src").startswith("data:image/png;base64,")
    page.get_by_label("Data URI").check()
    expect(img).to_have_attribute("src", __import__("re").compile("^data:image/svg"))


def overlay_page(ctx: indah.Context) -> indah.Component:
    boxes = [{"x": 0.22, "y": 0.5, "w": 0.3, "h": 0.32, "label": "house", "score": 0.93}]
    points = [{"x": 0.81, "y": 0.25, "label": "sun", "color": "#ffb300"}]
    mask = [{"src": mask_png(), "opacity": 0.5}]
    show_boxes, show_points, show_mask = (indah.Signal(v) for v in (True, True, False))
    # Shapes in raster pixels (ADR-0052): two overlapping "tiles" you can pick, and a close-up.
    tiles = {"left": [0, 0, 100, 120], "right": [60, 0, 160, 120]}
    picked, stage = indah.Signal("left"), indah.Signal(0)

    def shapes():
        if stage.value != 0:  # a layer is switched off by leaving its shapes out
            return []
        return [
            {"id": k, "box": b, "pick": True, "label": f"tile {k}", "dash": [6, 4]}
            for k, b in tiles.items()
        ]

    def steps():
        return [
            ("Cut", "current" if stage.value == 0 else "done"),
            ("Detect", "current" if stage.value == 1 else "pending"),
        ]

    return indah.Column(
        children=[
            indah.Steps(steps, orientation="horizontal", on_select=stage.set),
            indah.ImageOverlay(
                scene_png(),
                size=(160, 120),
                shapes=shapes,
                selected=picked,
                on_pick=picked.set,
                alt="tiles",
            ),
            indah.Text(lambda: f"picked: {picked.value}"),
            indah.ImageOverlay(
                scene_png(),
                size=(160, 120),
                alt="close-up",
                view=lambda: [tiles[picked.value][0], 0, 100, 75],
            ),
            indah.ImageOverlay(
                scene_png(),
                boxes=lambda: boxes if show_boxes.value else [],
                points=lambda: points if show_points.value else [],
                masks=lambda: mask if show_mask.value else [],
                alt="a landscape",
            ),
            indah.Row(
                children=[
                    indah.Checkbox(show_boxes, label="Boxes"),
                    indah.Checkbox(show_points, label="Keypoints"),
                    indah.Checkbox(show_mask, label="Mask"),
                ]
            ),
        ]
    )


def overlay_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".overlay-wrap .ov-box")).to_have_count(1)
    expect(page.get_by_text("house")).to_be_visible()
    page.get_by_label("Boxes").uncheck()
    expect(page.locator(".overlay-wrap .ov-box")).to_have_count(0)
    page.get_by_label("Boxes").check()
    expect(page.locator(".overlay-wrap .ov-box")).to_have_count(1)
    page.get_by_label("Mask").check()
    expect(page.locator(".overlay-wrap img")).to_have_count(4)  # three pictures and the mask
    expect(page.get_by_text("picked: left")).to_be_visible()
    page.locator(".ov-shapes rect").nth(1).click()
    expect(page.get_by_text("picked: right")).to_be_visible()
    page.get_by_role("button", name="Detect").click()
    expect(page.locator(".ov-shapes rect")).to_have_count(0)


# ---- audio ------------------------------------------------------------------------------------


def audio_page(ctx: indah.Context) -> indah.Component:
    freq = indah.Signal(440)
    return indah.Column(
        children=[
            indah.Select(freq, options=[(220, "A3 (220 Hz)"), (440, "A4 (440 Hz)")], label="Pitch"),
            indah.Audio(lambda: tone_wav(float(freq.value)), media_type="audio/wav"),
        ]
    )


def audio_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    audio = page.locator("audio")
    expect(audio).to_have_count(1)
    first = audio.get_attribute("src")
    assert first.startswith("data:audio/wav;base64,")
    page.get_by_label("Pitch").select_option(label="A3 (220 Hz)")
    page.wait_for_function(
        "(old) => document.querySelector('audio').getAttribute('src') !== old", arg=first
    )
    page.wait_for_function("() => document.querySelector('audio').duration > 0.4")


# ---- gallery ----------------------------------------------------------------------------------


def gallery_page(ctx: indah.Context) -> indah.Component:
    images = indah.Signal([tile_png(i) for i in range(3)])

    def grow() -> None:
        images.set([*images.value, tile_png(len(images.value))])

    return indah.Column(
        children=[
            indah.Gallery(images, columns=3, label="Swatches"),
            indah.Button("Add a tile", grow),
        ]
    )


def gallery_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    grid = page.locator(".gallery img")
    expect(grid).to_have_count(3)
    page.get_by_role("button", name="Add a tile").click()
    expect(grid).to_have_count(4)


# ---- upload / download ------------------------------------------------------------------------


def upload_page(ctx: indah.Context) -> indah.Component:
    report = indah.Signal("No file yet.")

    def on_upload(file: indah.UploadedFile) -> None:
        lines = len(file.text(errors="replace").splitlines())  # a stray byte will not raise
        report.set(
            f"Got {file.filename} ({file.content_type}), {file.size} bytes, {lines} line(s)."
        )

    return indah.Column(
        children=[
            indah.Upload(on_upload, label="Choose a text file", accept=".txt,.csv"),
            indah.Text(lambda: report.value),
        ]
    )


def upload_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.locator("input[type=file]").set_input_files(
        {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"one\ntwo\nthree\n"}
    )
    expect(page.get_by_text("Got notes.txt (text/plain), 14 bytes, 3 line(s).")).to_be_visible()


_sink: dict = {}


def _put_sink() -> str:
    """A throwaway local PUT endpoint (CORS open) that only counts bytes, for the demo."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    if "url" not in _sink:

        class Sink(BaseHTTPRequestHandler):
            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "PUT")
                self.send_header("Access-Control-Allow-Headers", "*")

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_PUT(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self._cors()
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Sink)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _sink["url"] = f"http://127.0.0.1:{server.server_port}"
    return _sink["url"]


def direct_upload_page(ctx: indah.Context) -> indah.Component:
    report = indah.Signal("No file yet.")

    def get_target(info: dict) -> dict:
        # In an app this is a presigned URL from your object store.
        return {"url": f"{_put_sink()}/{info['filename']}"}

    def on_done(result: dict) -> None:
        report.set(
            f"{result['filename']}: {'stored' if result['ok'] else 'failed (' + result['error'] + ')'}."
        )

    return indah.Column(
        children=[
            indah.DirectUpload(get_target, on_done=on_done, label="Choose a file"),
            indah.Text(lambda: report.value),
        ]
    )


def direct_upload_check(pw) -> None:
    from playwright.sync_api import expect

    pw.page.locator("input[type=file]").set_input_files(
        {"name": "big.bin", "mimeType": "application/octet-stream", "buffer": b"x" * 100_000}
    )
    expect(pw.page.get_by_text("big.bin: stored.")).to_be_visible()


def download_page(ctx: indah.Context) -> indah.Component:
    rows = indah.Signal(3.0)
    report = indah.computed(
        lambda: indah.DownloadFile(
            b"n,square\n" + "".join(f"{n},{n * n}\n" for n in range(int(rows.value))).encode(),
            filename="squares.csv",
            media_type="text/csv",
        )
    )
    return indah.Column(
        children=[
            indah.Number(rows, min=1, max=20, label="Rows"),
            indah.Download(report, label="Download squares.csv"),
        ]
    )


def download_check(pw) -> None:
    page = pw.page
    page.get_by_label("Rows").fill("4")
    page.wait_for_timeout(400)
    with page.expect_download() as info:
        page.get_by_text("Download squares.csv").click()
    download = info.value
    assert download.suggested_filename == "squares.csv"
    with open(download.path()) as fh:
        assert fh.read() == "n,square\n0,0\n1,1\n2,4\n3,9\n"


# ---- camera -----------------------------------------------------------------------------------


def camera(ctx: indah.Context) -> indah.Component:
    seen = indah.Signal(0)
    last = indah.Signal("no frame yet")

    def on_frame(frame: indah.CameraFrame) -> None:  # a plain handler; it may be `async def` too
        seen.set(seen.value + 1)
        last.set(f"{frame.size // 1024} KiB {frame.content_type}, frame {frame.seq}")

    cam = indah.Camera(on_frame, label="Your camera", fps=2, max_width=320)
    return indah.Column(
        children=[
            cam,
            indah.Text(lambda: f"{seen.value} frame(s) received, last: {last.value}"),
            indah.Text(lambda: f"Sent over: {cam.transport.value}"),
            indah.Text(
                "Frames go over a WebSocket when the app is made with `create_app(live=True)` "
                '(`indah.Live(...)` tunes the caps; needs `pip install "indah[live]"`). Without it '
                "this page sends about one snapshot a second, which also works on Colab.",
                markdown=True,
            ),
        ]
    )


def camera_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("0 frame(s) received")).to_be_visible()
    page.get_by_role("button", name="Start camera").click()
    # The test browser has no camera: the shell says so instead of failing.
    expect(page.get_by_text("No camera could be opened.")).to_be_visible()


CHAPTER = Chapter(
    slug="media",
    # The chapter's Map is built when a session opens, after the page (and its CSP) is served.
    # The direct-upload demo PUTs to a local sink on another origin, which connect-src must name.
    app_kwargs={
        "csp_media_hosts": ["https://tile.openstreetmap.org"],
        "csp_connect_hosts": [] if sys.platform == "emscripten" else [_put_sink()],
    },
    title="Media and files",
    order=70,
    blurb=(
        "Charts and heatmaps draw in the browser from plain props; images, audio and plots are "
        "bytes you hand over; uploads and downloads go through per-session routes."
    ),
    pages=[
        Page(
            slug="chart",
            title="Live chart",
            summary="Each push sends only the new row; the browser (uPlot) appends it and keeps zoom.",
            build=live_chart,
            covers=("Chart",),
            docs="components.md",
            adr=(18,),
            check=live_chart_check,
        ),
        Page(
            slug="chart-kinds",
            title="Bars, dots and markers",
            summary=(
                "A series can be bars or dots. A playhead dims what has not happened yet, a "
                "highlight picks out one bar, and a rule marks a target. Colours written as "
                "`var(--token)` follow the light and dark switch."
            ),
            build=chart_kinds,
            covers=(),
            docs="components.md",
            adr=(44,),
            check=chart_kinds_check,
        ),
        Page(
            slug="slider-release",
            title="Slider: readout, marks and commit on release",
            summary=(
                "A slider can show its value, put ticks and labels on the track, space the track "
                'by powers (`scale="log"`) and send its value only when the thumb is released '
                '(`commit="release"`), so a costly recompute runs once per drag.'
            ),
            build=slider_release,
            covers=(),
            docs="components.md",
            adr=(50,),
            check=slider_release_check,
        ),
        Page(
            slug="chart-category",
            title="Category axis and live threshold",
            summary=(
                '`x_scale="category"` labels each bar with its name, and `rules`, `bands` and '
                "`markers` may be callables, so a threshold line follows a slider and the chart "
                "redraws the overlay without rebuilding."
            ),
            build=chart_category,
            covers=(),
            docs="components.md",
            adr=(49,),
            check=chart_category_check,
        ),
        Page(
            slug="chart-events",
            title="Chart hover and click",
            summary=(
                "`Chart(hovered=, clicked=)` report the point or bar under the pointer as signals: "
                "hover is debounced, a click selects a table row here."
            ),
            build=chart_events,
            covers=(),
            docs="components.md",
            adr=(18,),
            check=chart_events_check,
        ),
        Page(
            slug="chart-bars",
            title="Stacked, horizontal and box charts",
            summary=(
                '`stack=True` stacks bar series, `orientation="horizontal"` draws them sideways for '
                'funnels, and a `kind="box"` series draws box and whiskers from five numbers '
                "(`box_rows` makes them from samples)."
            ),
            build=chart_bars,
            covers=("box_rows",),
            docs="components.md",
            adr=(49,),
            check=chart_bars_check,
        ),
        Page(
            slug="chart-axes",
            title="Time axis, whole-number ticks and a labelled playhead",
            summary=(
                '`x_scale="time"` draws dates for a series of timestamps, `x_integer=True` keeps '
                "the ticks of a count on whole numbers, and `playhead_label` says what the "
                "playhead line marks."
            ),
            build=chart_axes,
            covers=(),
            docs="components.md",
            adr=(49,),
            check=chart_axes_check,
        ),
        Page(
            slug="choice-cards",
            title="Choice cards",
            summary=(
                "A radio group where each option is a card with a title and a sentence of "
                "explanation, for a preset, a difficulty or a persona. Arrow keys move the choice."
            ),
            build=choice_cards,
            covers=("ChoiceCards",),
            docs="components.md",
            check=choice_cards_check,
        ),
        Page(
            slug="graph-styles",
            title="Graph element styles and a stable layout",
            summary=(
                "Nodes take `ring`, `opacity` and `label_style`, edges take `dash`, `opacity` and "
                '`width`, drawn the same inside and outside the focus window. `layout="stable"` '
                "seeds the layout from ids only, so stepping the year changes styles and groups "
                "without moving a node."
            ),
            build=graph_styles_page,
            covers=(),
            docs="graph.md",
            adr=(53,),
            check=graph_styles_check,
        ),
        Page(
            slug="graph-keep",
            title="Graph update keep",
            summary=(
                '`Graph(update="keep")` keeps the position of every id a replaced graph already had '
                "and places only new ids near their neighbours; `transition_ms` fades them in."
            ),
            build=graph_keep_page,
            covers=(),
            docs="graph.md",
            adr=(53,),
            check=graph_keep_check,
        ),
        Page(
            slug="timeline",
            title="Timeline",
            summary=(
                "Step through the moments that exist, however irregular: buttons for the previous "
                "and next point or event, play at up to 4 steps a second, density bars for the busy "
                "moments, and the arrow, Home, End and space keys."
            ),
            build=timeline_page,
            covers=("Timeline",),
            docs="components.md",
            adr=(53,),
            check=timeline_check,
        ),
        Page(
            slug="slider-range",
            title="Slider with a live range",
            summary=(
                "`min`, `max` and `step` can be signals or callables, so the track follows data "
                "that arrives later (the years of a generated world) instead of padding it."
            ),
            build=slider_range,
            covers=(),
            docs="components.md",
            check=slider_range_check,
        ),
        Page(
            slug="chart-steps",
            title="Steps, log axes and annotations",
            summary=(
                "A `step` series draws a staircase for a value that only changes at events. "
                "Axes can be logarithmic, rules can be vertical, and bands and markers call out a "
                "region or a point. `chart_rows` lines up series that have different x values."
            ),
            build=chart_steps,
            covers=("chart_rows",),
            docs="components.md",
            adr=(49,),
            check=chart_steps_check,
        ),
        Page(
            slug="pie",
            title="Pie with a lit slice",
            summary=(
                "A pie that lights one slice: it is pulled out and glows while the others dim. "
                "Use it to show which of several outcomes just happened."
            ),
            build=pie_lit,
            covers=("Pie",),
            docs="components.md",
            adr=(44,),
            check=pie_lit_check,
        ),
        Page(
            slug="heatmap-marks",
            title="Heatmap labels and marks",
            summary=(
                "A colormap can be your own colour stops, a cell with no value stays blank, rows and "
                "runs of columns can be labelled, and one cell can be spotlit (`mark_x`, `mark_y`)."
            ),
            build=heatmap_marks,
            covers=(),
            docs="components.md",
            adr=(44,),
            check=heatmap_marks_check,
        ),
        Page(
            slug="heatmap",
            title="Heatmap",
            summary="A 2-D field drawn on a canvas. Move the slider and the whole field is replaced.",
            build=heatmap,
            covers=("Heatmap",),
            docs="components.md",
            adr=(19,),
            check=heatmap_check,
        ),
        Page(
            slug="graph",
            title="Graph",
            summary=(
                "A node-link graph: drag to pan, wheel to zoom, click a node to select it. Only the "
                "nodes nearest the middle are drawn in full; the rest are dots."
            ),
            build=graph_page,
            covers=("Graph",),
            docs="graph.md",
            adr=(48,),
            check=graph_check,
        ),
        Page(
            slug="map",
            title="Map",
            summary=(
                "Leaflet with markers and polygons. Tiles load from OpenStreetMap in your own "
                "browser, so offline you see the shapes on a blank map."
            ),
            build=map_page,
            covers=("Map",),
            docs="components.md",
            check=map_check,
        ),
        Page(
            slug="camera",
            title="Camera",
            summary=(
                "A webcam preview whose frames reach a Python handler as a `CameraFrame`. Press "
                "**Start camera** and allow it; the counts below update as frames arrive."
            ),
            build=camera,
            covers=("Camera", "CameraFrame", "Live"),
            docs="hosting-live.md#live-camera",
            adr=(45,),
            check=camera_check,
            local_only="needs a camera and a server route that receives the frames",
        ),
        Page(
            slug="plot",
            title="Plot",
            summary=(
                "A rendered figure shown as an image. Pass a Matplotlib `Figure` or, as here, PNG bytes."
            ),
            build=plot_page,
            covers=("Plot",),
            docs="components.md",
            check=plot_check,
        ),
        Page(
            slug="image",
            title="Image",
            summary="A URL, a `data:` URI or raw PNG bytes. Change the source and the picture follows.",
            build=image_page,
            covers=("Image", "Radio"),
            docs="components.md",
            adr=(17,),
            check=image_check,
        ),
        Page(
            slug="overlay",
            title="Image overlay",
            summary="Boxes, keypoints and a mask in fractions, plus pickable shapes in raster pixels and a cropped view.",
            build=overlay_page,
            covers=("ImageOverlay", "Checkbox"),
            docs="components.md",
            adr=(20, 52),
            check=overlay_check,
        ),
        Page(
            slug="audio",
            title="Audio",
            summary="WAV bytes generated in Python and played with the browser's own controls.",
            build=audio_page,
            covers=("Audio", "Select"),
            docs="components.md",
            adr=(17,),
            check=audio_check,
        ),
        Page(
            slug="gallery",
            title="Gallery",
            summary="An image grid bound to a list signal; append to the list to grow it.",
            build=gallery_page,
            covers=("Gallery", "Button"),
            docs="components.md",
            adr=(16,),
            check=gallery_check,
        ),
        Page(
            slug="upload",
            local_only="a multipart upload is posted to api/upload, which the browser runtime does not provide",
            title="Upload",
            summary="`on_upload` receives an `UploadedFile` with its name, type and bytes.",
            build=upload_page,
            covers=("Upload", "UploadedFile"),
            docs="components.md",
            adr=(17,),
            check=upload_check,
        ),
        Page(
            slug="direct-upload",
            local_only="the browser PUTs the file to another origin, which the browser runtime does not provide",
            title="Direct upload",
            summary="`DirectUpload` sends the file from the browser to a URL your app returns "
            "(a presigned PUT), with a progress bar. The server never sees the bytes.",
            build=direct_upload_page,
            covers=("DirectUpload",),
            docs="components.md",
            check=direct_upload_check,
        ),
        Page(
            slug="download",
            local_only="a download is served from api/file/..., a route the browser runtime does not provide",
            title="Download",
            summary="A computed `DownloadFile` becomes a per-session link; change the rows, get a new file.",
            build=download_page,
            covers=("Download", "DownloadFile", "Number", "computed"),
            docs="components.md",
            adr=(17,),
            check=download_check,
        ),
    ],
)
