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

    def on_frame(frame: indah.Frame) -> None:  # a plain handler; it may be `async def` too
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
                "A webcam preview whose frames reach a Python handler as a `Frame`. Press "
                "**Start camera** and allow it; the counts below update as frames arrive."
            ),
            build=camera,
            covers=("Camera", "Frame", "Live"),
            docs="hosting.md#live-camera",
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
