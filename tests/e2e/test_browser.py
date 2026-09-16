"""End-to-end through a real headless browser (Chromium via Playwright).

This is the only layer that renders the pre-built Svelte shell in a real DOM and
proves the Python core, the JSON protocol, and the shell agree - including the V4
additions (the generic Custom.svelte renderer, Select, DataFrame) that the
httpx-level e2e only exercises on the protocol side.

Heavy layer: marked `e2e`, excluded from the fast pre-push/CI gate. Needs the
browser installed:

    uv sync --extra dev --extra e2e
    uv run playwright install chromium
    uv run pytest -m e2e -q          # or: make test-e2e

The synchronous Playwright API is used deliberately: the test itself is sync (so
it never collides with pytest-asyncio's event loop), while `launch()` runs the
real uvicorn server in its own background thread.
"""

import base64
import re

import pytest

from indah.launch import launch

# Skip cleanly (rather than erroring) where the browser layer isn't installed,
# so `-m e2e` still runs the httpx layer on a plain `--extra dev` checkout.
playwright_sync = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync.sync_playwright
expect = playwright_sync.expect


@pytest.mark.e2e
def test_shell_renders_and_patches_in_a_real_browser():
    """The indah Studio demo renders in Chromium, and slider/colorpicker/Generate
    events patch the live DOM (chat bubbles, gallery) through the SSE round-trip."""
    handle = launch(block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                # 1) The init tree renders: the markdown heading, the sidebar
                # controls, and the Chat tab (active by default).
                expect(page.locator(".markdown h1", has_text="indah Studio")).to_be_visible()
                slider = page.locator("input[type=range]")
                color = page.locator("input[type=color]")
                expect(slider).to_be_visible()
                expect(page.locator("select").first).to_be_visible()
                expect(color).to_be_visible()
                expect(page.locator(".chat")).to_be_visible()

                # 2) A slider event patches its dependent label live. Setting a
                # range input's value needs a dispatched input event (fill() does
                # not fire one for type=range).
                slider.evaluate(
                    "el => { el.value = '2';"
                    " el.dispatchEvent(new Event('input', { bubbles: true })); }"
                )
                expect(page.locator("div.text", has_text="temperature = 2")).to_be_visible()

                # 3) The colorpicker (a custom component) round-trips its value into
                # Python, which patches the accent preview image's src.
                color.evaluate(
                    "el => { el.value = '#ff0000';"
                    " el.dispatchEvent(new Event('input', { bubbles: true })); }"
                )
                expect(page.locator("img[alt='accent preview']")).to_have_attribute(
                    "src", re.compile("ff0000")
                )

                # 4) Generate runs an async handler that streams into Chat bubbles and
                # then fills the Gallery - all live over SSE, without freezing the UI.
                page.locator("button", has_text="Generate").click()
                expect(page.locator(".chat .bubble.role-user")).to_be_visible()
                expect(page.locator(".chat .bubble.role-assistant")).to_be_visible()
                page.locator(".tab", has_text="Gallery").click()
                expect(page.locator(".gallery-item")).to_have_count(3)
            finally:
                browser.close()
    finally:
        handle.stop()


def _shared_signal_app(control):
    """An app whose input and a button both write the same signal, so a button
    click is a server-side change to the (still-focused) input's value - the exact
    shape of the echo that used to clobber fast typing / slider drags."""
    from indah import Button, Column, Session, Signal, Slider, TextInput, create_app

    if control == "text":
        sig = Signal("")
        field = TextInput(sig, label="Prompt")
        stale = lambda: sig.set("STALE")  # noqa: E731
    else:
        sig = Signal(1)
        field = Slider(sig, min=0, max=10, step=1, label="n")
        stale = lambda: sig.set(2)  # noqa: E731
    root = Column(children=[field, Button("set-from-server", on_click=stale)])
    return create_app(session=Session(root))


@pytest.mark.e2e
def test_focused_text_input_is_not_clobbered_by_a_server_echo():
    """While a text box is focused, a server value change to it must be ignored, so
    a stale echo can't eat fast keystrokes; once focus leaves, the box adopts the
    server value (two-way binding intact). dispatch_event fires the button handler
    without moving focus, delivering a server change while the box stays focused."""
    handle = launch(_shared_signal_app("text"), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                box = page.locator("input[type=text]").first
                expect(box).to_be_visible()
                box.click()
                page.keyboard.type("hello")
                expect(box).to_have_value("hello")
                page.locator("button", has_text="set-from-server").dispatch_event(
                    "click"
                )  # server sets it "STALE"
                page.wait_for_timeout(300)
                expect(box).to_have_value("hello")  # not clobbered while focused
                box.blur()
                expect(box).to_have_value("STALE")  # adopted once editing ends
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_dragging_slider_is_not_snapped_back_by_a_server_echo():
    """The slider version of the same guard: a server change while the thumb is
    held (focused) must not snap it back mid-drag."""
    handle = launch(_shared_signal_app("slider"), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                slider = page.locator("input[type=range]").first
                expect(slider).to_be_visible()
                slider.focus()  # as while dragging
                slider.evaluate(
                    "el => { el.value = '8';"
                    " el.dispatchEvent(new Event('input', { bubbles: true })); }"
                )
                page.locator("button", has_text="set-from-server").dispatch_event(
                    "click"
                )  # server sets it to 2
                page.wait_for_timeout(300)
                expect(slider).to_have_value("8")  # not snapped back while focused
                slider.blur()
                expect(slider).to_have_value("2")  # adopts server value after
            finally:
                browser.close()
    finally:
        handle.stop()


def _markdown_app():
    """An app with a markdown Text (including a raw <script>), a progress bar, and
    a spinner - to prove the shell renders the safe block tree and never injects."""
    from indah import Column, Progress, Session, Spinner, Text, create_app

    md = (
        "## Heading\n\n"
        "Some **bold** text and a [link](https://example.com).\n\n"
        "<script>window.__pwned = true</script>\n\n"
        "- item one\n- item two"
    )
    root = Column(
        children=[
            Text(md, markdown=True),
            Progress(0.5, label="Progress"),
            Spinner(label="Busy"),
        ]
    )
    return create_app(session=Session(root))


@pytest.mark.e2e
def test_markdown_renders_safely_with_progress_and_spinner():
    """Markdown renders as real elements, but source HTML stays inert text: no
    <script> element is created and the injected global never gets set."""
    handle = launch(_markdown_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                # Markdown became real elements.
                expect(page.locator(".markdown h2", has_text="Heading")).to_be_visible()
                expect(page.locator(".markdown strong", has_text="bold")).to_be_visible()
                expect(page.locator(".markdown a", has_text="link")).to_have_attribute(
                    "href", "https://example.com"
                )
                expect(page.locator(".markdown li")).to_have_count(2)

                # The raw <script> was NOT interpreted: no script element inside the
                # markdown, its text survives literally, and the global is unset.
                assert page.locator(".markdown script").count() == 0
                expect(page.locator(".markdown", has_text="window.__pwned")).to_be_visible()
                assert page.evaluate("() => window.__pwned") is None

                # Progress + spinner render.
                expect(page.locator("progress.progress")).to_have_attribute("value", "0.5")
                expect(page.locator(".spinner")).to_be_visible()
            finally:
                browser.close()
    finally:
        handle.stop()


def _data_list_app():
    """An app with a data-driven List, Chat, and Gallery, plus a button that grows
    all three by setting each Signal[list] to a fresh list (ADR-0016)."""
    from indah import Button, Chat, Column, Gallery, List, Session, Signal, create_app

    swatch = (
        "data:image/svg+xml,"
        "%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'%3E"
        "%3Crect width='40' height='40' fill='%23b5296b'/%3E%3C/svg%3E"
    )
    logs = Signal(["first", "second"])
    messages = Signal([{"role": "user", "content": "hi"}])
    images = Signal([swatch])

    def add():
        logs.set(logs.value + ["third"])
        messages.set(messages.value + [{"role": "assistant", "content": "hello there"}])
        images.set(images.value + [swatch])

    root = Column(
        children=[
            List(logs, empty="none"),
            Chat(messages, label="Chat"),
            Gallery(images, columns=2, label="Gallery"),
            Button("add", on_click=add),
        ]
    )
    return create_app(session=Session(root))


@pytest.mark.e2e
def test_data_driven_list_chat_and_gallery_grow_on_a_signal_change():
    """List/Chat/Gallery render from one Signal[list] each and grow when the signal
    is reassigned - add/remove is a prop change over the existing patch op."""
    handle = launch(_data_list_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                expect(page.locator(".list-item")).to_have_count(2)
                expect(page.locator(".chat .bubble")).to_have_count(1)
                expect(page.locator(".gallery-item")).to_have_count(1)

                page.locator("button", has_text="add").click()

                # Each list grew by one, live, through the SSE patch round-trip.
                expect(page.locator(".list-item")).to_have_count(3)
                expect(page.locator(".chat .bubble")).to_have_count(2)
                expect(
                    page.locator(".chat .bubble.role-assistant", has_text="hello there")
                ).to_be_visible()
                expect(page.locator(".gallery-item")).to_have_count(2)
            finally:
                browser.close()
    finally:
        handle.stop()


def _chart_app():
    """An app with a streaming line Chart and a button that pushes points, plus a
    reactive Chart driven from a slider - the two ways to feed a client chart."""
    from indah import Button, Chart, Column, Session, Signal, Slider, create_app

    live = Chart(series=["loss"], title="Training loss", x_label="step")
    gain: Signal[float] = Signal(1.0)
    static = Chart(
        lambda: [[x, gain.value * x] for x in range(6)], series=["y = k·x"], title="Reactive"
    )
    step = {"n": 0}

    def push():
        step["n"] += 1
        live.push(step["n"], 1.0 / step["n"])

    root = Column(
        children=[
            live,
            Button("push", on_click=push),
            static,
            Slider(gain, min=1, max=5, step=1, label="k"),
        ]
    )
    return create_app(session=Session(root))


@pytest.mark.e2e
def test_client_chart_renders_and_streams_points(tmp_path):
    """The client uPlot chart (ADR-0018) mounts from the init tree and grows via the
    append op: clicking push streams a point over SSE and uPlot's data array grows,
    while a reactive chart redraws when its bound slider changes."""
    handle = launch(_chart_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                # Both charts mounted as uPlot canvases from the init tree.
                expect(page.locator(".chart canvas").first).to_be_visible()
                assert page.locator(".chart canvas").count() >= 2
                expect(page.locator(".u-title", has_text="Training loss")).to_be_visible()

                # The streaming chart starts empty; each push appends one point that
                # reaches uPlot's data array (x row), live over SSE.
                live = page.locator(".chart").first
                assert live.evaluate("el => el.__uplot.data[0].length") == 0
                page.locator("button", has_text="push").click()
                page.locator("button", has_text="push").click()
                page.wait_for_function(
                    "() => document.querySelector('.chart').__uplot.data[0].length === 2"
                )

                # The reactive chart redraws when its bound signal changes: sample the
                # last y before and after moving the slider (k: 1 -> 5).
                static = page.locator(".chart").nth(1)
                before = static.evaluate("el => el.__uplot.data[1][5]")
                page.locator("input[type=range]").first.evaluate(
                    "el => { el.value = '5';"
                    " el.dispatchEvent(new Event('input', { bubbles: true })); }"
                )
                page.wait_for_function(
                    "(prev) => document.querySelectorAll('.chart')[1].__uplot.data[1][5] !== prev",
                    arg=before,
                )
            finally:
                browser.close()
    finally:
        handle.stop()


def _heatmap_app():
    """A streaming Heatmap + a button that pushes a column (a spectrogram time slice),
    plus a reactive Heatmap from a fixed field."""
    from indah import Button, Column, Heatmap, Session, create_app

    live = Heatmap(colormap="magma", title="Spectrogram")
    static = Heatmap([[0.0, 0.5, 1.0], [1.0, 0.5, 0.0]], colormap="viridis", title="Field")
    t = {"n": 0}

    def push():
        t["n"] += 1
        live.push_column([0.1 * t["n"], 0.2 * t["n"], 0.3 * t["n"]])

    root = Column(children=[live, Button("push", on_click=push), static])
    return create_app(session=Session(root))


@pytest.mark.e2e
def test_client_heatmap_renders_and_streams_columns():
    """The client heatmap (ADR-0019) mounts a canvas from the init tree, and a
    streamed column grows its field over SSE (via the array append op)."""
    handle = launch(_heatmap_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                # Both heatmaps mounted as canvases; the static one already has a field.
                expect(page.locator(".heatmap canvas").first).to_be_visible()
                assert page.locator(".heatmap canvas").count() >= 2
                page.wait_for_function(
                    "() => document.querySelectorAll('.heatmap')[1].__heatmap.ncols === 2"
                )

                # The streaming heatmap starts empty; each push appends a column live.
                live = page.locator(".heatmap").first
                assert live.evaluate("el => el.__heatmap.ncols") == 0
                page.locator("button", has_text="push").click()
                page.locator("button", has_text="push").click()
                page.wait_for_function(
                    "() => document.querySelector('.heatmap').__heatmap.ncols === 2"
                )
                assert live.evaluate("el => el.__heatmap.nrows") == 3
            finally:
                browser.close()
    finally:
        handle.stop()


def _session_counter_app():
    """A per-viewer counter over a session_factory, so each tab gets its own signal.
    This is the shape of examples/session_state.py, trimmed to one counter."""
    from indah import Button, Column, Session, Signal, Text, create_app

    def factory():
        n = Signal(0)
        root = Column(
            children=[
                Button("+1", on_click=lambda: n.set(n.value + 1)),
                Text(lambda: f"count = {n.value}"),
            ]
        )
        return Session(root)

    return create_app(session_factory=factory)


@pytest.mark.e2e
def test_two_tabs_drive_independent_session_state():
    """Two browser tabs on the same app hold independent state (ADR-0010, KAN-1418).

    Each tab mints its own per-tab session id (sessionStorage), so the server gives
    it an isolated session: clicking +1 in one tab never moves the other's counter.
    """
    handle = launch(_session_counter_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context()
            tab1 = context.new_page()
            tab2 = context.new_page()
            try:
                tab1.goto(handle.url, wait_until="domcontentloaded")
                tab2.goto(handle.url, wait_until="domcontentloaded")

                # Both start isolated at zero.
                expect(tab1.locator("div.text", has_text="count = 0")).to_be_visible()
                expect(tab2.locator("div.text", has_text="count = 0")).to_be_visible()

                # Drive them differently: tab1 twice, tab2 once.
                tab1.locator("button", has_text="+1").click()
                tab1.locator("button", has_text="+1").click()
                tab2.locator("button", has_text="+1").click()

                # Each tab reflects only its own clicks - no cross-talk.
                expect(tab1.locator("div.text", has_text="count = 2")).to_be_visible()
                expect(tab2.locator("div.text", has_text="count = 1")).to_be_visible()

                # And a tab's own view is stable: tab1 is still 2, not tab2's 1.
                expect(tab1.locator("div.text", has_text="count = 1")).to_have_count(0)
            finally:
                browser.close()
    finally:
        handle.stop()


# A 1x1 transparent PNG, so the upload e2e needs no fixture file on disk.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


def _upload_classify_app():
    """An upload -> classify -> show app (the shape of examples/upload_classify.py),
    with a sync handler so the browser assertion is deterministic."""
    from indah import (
        Column,
        Download,
        DownloadFile,
        Image,
        Session,
        Signal,
        Text,
        Upload,
        create_app,
    )

    def factory():
        preview = Signal("")
        result = Signal("")
        report = Signal(None)

        def on_upload(file):
            preview.set("data:image/png;base64," + base64.b64encode(file.data).decode())
            result.set(f"Predicted: **cat** from {file.filename}")
            report.set(DownloadFile(b"prediction: cat\n", filename="prediction.txt"))

        root = Column(
            children=[
                Upload(on_upload, accept="image/*", label="Upload an image"),
                Image(preview, alt="uploaded image"),
                Text(lambda: result.value or "_No prediction yet._", markdown=True),
                Download(report, label="Download report"),
            ]
        )
        return Session(root)

    return create_app(session_factory=factory)


@pytest.mark.e2e
def test_upload_image_classify_and_show_result(tmp_path):
    """The classic upload -> run -> show demo end to end (ADR-0017, KAN-1421):
    a file posted from the shell reaches the handler, whose result (the echoed
    image, the prediction, and a download link) patches the live DOM over SSE."""
    handle = launch(_upload_classify_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                # Before upload: no prediction, and the download link is inert.
                expect(page.locator(".markdown", has_text="No prediction yet")).to_be_visible()
                expect(page.locator("a.download")).to_have_count(0)

                # Upload an in-memory PNG through the shell's file input.
                png = tmp_path / "cat.png"
                png.write_bytes(_TINY_PNG)
                page.locator("input[type=file]").set_input_files(str(png))

                # The result patches in over SSE: prediction text, the echoed image,
                # and a now-enabled download link served from this session.
                expect(page.locator(".markdown", has_text="Predicted:")).to_be_visible()
                expect(page.locator("img[alt='uploaded image']")).to_have_attribute(
                    "src", re.compile("^data:image/png;base64,")
                )
                download = page.locator("a.download")
                expect(download).to_be_visible()
                expect(download).to_have_attribute("href", re.compile("api/file/"))
            finally:
                browser.close()
    finally:
        handle.stop()
