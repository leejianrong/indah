"""Chapter 7: charts, images, maps, audio and files in and out."""

from __future__ import annotations

import io
import math
import random
import struct
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
    return indah.Column(
        children=[
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
    expect(page.locator(".overlay-wrap img")).to_have_count(2)  # the picture and the mask


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
    app_kwargs={"csp_media_hosts": ["https://tile.openstreetmap.org"]},
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
            summary="Boxes, keypoints and a mask drawn over an image, in fractions so they scale.",
            build=overlay_page,
            covers=("ImageOverlay", "Checkbox"),
            docs="components.md",
            adr=(20,),
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
