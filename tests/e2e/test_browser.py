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


@pytest.mark.e2e
def test_shell_still_mounts_with_a_malformed_browser_locale():
    """A malformed navigator.language (e.g. Chromium under LANG=C.UTF-8 reporting
    "en-US@posix") must not crash the shell's bootstrap - uPlot constructs an
    Intl.NumberFormat from it at module load time, before the SSE connection even
    opens (indah#76). Force the malformed tag via an init script so the repro is
    deterministic regardless of the test runner's own locale."""
    handle = launch(block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context()
            context.add_init_script(
                "Object.defineProperty(navigator, 'language', { get: () => 'en-US@posix' });"
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                expect(page.locator(".markdown h1", has_text="indah Studio")).to_be_visible()
                assert not errors, f"page errors: {errors}"
            finally:
                context.close()
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


def _overlay_app(label_mode="always"):
    """An ImageOverlay with detection boxes from a signal + a button that adds one -
    the read-only overlay path (ADR-0020), streaming detections as a prop update."""
    from indah import Button, Column, ImageOverlay, Session, Signal, create_app

    img = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' "
        "height='100'%3E%3Crect width='200' height='100' fill='%23ccc'/%3E%3C/svg%3E"
    )
    boxes = Signal([{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "label": "cat", "score": 0.9}])

    def add():
        boxes.set(boxes.value + [{"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2, "label": "dog"}])

    root = Column(
        children=[
            ImageOverlay(img, boxes=boxes, alt="scene", label_mode=label_mode),
            Button("add", on_click=add),
        ]
    )
    return create_app(session=Session(root))


def _overlay_overflow_app():
    """A box outside [0,1] and a labeled point - overflow: hidden on .overlay-wrap
    must keep the box from bleeding outside the image (indah#78)."""
    from indah import Column, ImageOverlay, Session, create_app

    img = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' "
        "height='100'%3E%3Crect width='200' height='100' fill='%23ccc'/%3E%3C/svg%3E"
    )
    root = Column(
        children=[
            ImageOverlay(
                img,
                boxes=[{"x": 1.5, "y": 1.5, "w": 0.3, "h": 0.3, "label": "offscreen"}],
                points=[{"x": 0.5, "y": 0.5, "label": "center"}],
                alt="scene",
            )
        ]
    )
    return create_app(session=Session(root))


@pytest.mark.e2e
def test_image_overlay_draws_boxes_and_streams_detections():
    """Detection boxes render over the image at fractional positions, with labels,
    and a new detection appears live over SSE (ADR-0020)."""
    handle = launch(_overlay_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                boxes = page.locator(".overlay-wrap .ov-box")
                expect(boxes).to_have_count(1)
                # Positioned by fraction: x=0.1 -> left:10%.
                assert boxes.first.evaluate("el => el.style.left") == "10%"
                expect(page.locator(".ov-label", has_text="cat")).to_be_visible()

                # A streamed detection shows up live.
                page.locator("button", has_text="add").click()
                expect(boxes).to_have_count(2)
                expect(page.locator(".ov-label", has_text="dog")).to_be_visible()
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_image_overlay_hover_label_mode_uses_a_title_not_a_visible_span():
    """label_mode="hover" swaps the permanent .ov-label for a native title tooltip,
    and re-enables pointer-events so the box is actually a hover target (indah#78)."""
    handle = launch(_overlay_app(label_mode="hover"), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                box = page.locator(".overlay-wrap .ov-box").first
                expect(box).to_be_visible()
                expect(page.locator(".ov-label")).to_have_count(0)
                assert box.evaluate("el => el.title") == "cat 90%"
                assert box.evaluate("el => getComputedStyle(el).pointerEvents") == "auto"
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_image_overlay_wheel_zooms_drag_pans_and_reset_restores_identity():
    """Scroll-wheel zooms toward the cursor, dragging while zoomed pans, and the
    reset button snaps back to identity - all via a single transform on .ov-content,
    so boxes/points (percent-positioned within it) move in lockstep (indah#77)."""
    handle = launch(_overlay_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                wrap = page.locator(".overlay-wrap")
                content = page.locator(".ov-content")
                expect(wrap).to_be_visible()
                assert content.evaluate("el => el.style.transform") == (
                    "translate(0px, 0px) scale(1)"
                )
                expect(page.locator(".ov-reset-btn")).to_have_count(0)

                # Scroll-wheel zooms in toward the cursor.
                box = wrap.bounding_box()
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                page.mouse.move(cx, cy)
                page.mouse.wheel(0, -1000)
                zoomed = content.evaluate("el => el.style.transform")
                scale = float(re.search(r"scale\(([\d.]+)\)", zoomed).group(1))
                assert scale > 1
                expect(wrap).to_have_class(re.compile(r"\bzoomed\b"))
                expect(page.locator(".ov-reset-btn")).to_be_visible()

                # Dragging while zoomed pans (translate changes).
                page.mouse.down()
                page.mouse.move(cx - 30, cy - 20, steps=5)
                page.mouse.up()
                panned = content.evaluate("el => el.style.transform")
                assert panned != zoomed

                # Reset view snaps back to identity.
                page.locator(".ov-reset-btn").click()
                expect(content).to_have_js_property(
                    "style.transform", "translate(0px, 0px) scale(1)"
                )
                expect(page.locator(".ov-reset-btn")).to_have_count(0)
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_image_overlay_clips_out_of_range_content_and_point_tooltip_works():
    """An out-of-[0,1] box can't bleed outside the image (overflow: hidden on
    .overlay-wrap), and a point's native title tooltip is a real hover target now
    that pointer-events is re-enabled (indah#78)."""
    handle = launch(_overlay_overflow_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                wrap = page.locator(".overlay-wrap")
                expect(wrap).to_be_visible()
                assert wrap.evaluate("el => getComputedStyle(el).overflow") == "hidden"

                point = page.locator(".ov-point").first
                expect(point).to_be_visible()
                assert point.evaluate("el => el.title") == "center"
                assert point.evaluate("el => getComputedStyle(el).pointerEvents") == "auto"
            finally:
                browser.close()
    finally:
        handle.stop()


def _table_app():
    """A selectable, sortable Table driving a Stat, plus a text echo of the selection
    - the dashboard pattern: pick a row, the rest of the app reacts."""
    from indah import Column, Session, Signal, Stat, Table, Text, create_app

    rows = [
        {"ticker": "AAPL", "price": 220},
        {"ticker": "MSFT", "price": 410},
        {"ticker": "NVDA", "price": 130},
    ]
    picked = Signal(None)

    def price_of():
        i = picked.value
        return f"${rows[i]['price']}" if i is not None else "-"

    root = Column(
        children=[
            Table(rows, selected=picked, label="Peers"),
            Stat(price_of, label="Selected price"),
            Text(lambda: "none" if picked.value is None else rows[picked.value]["ticker"]),
        ]
    )
    return create_app(session=Session(root))


@pytest.mark.e2e
def test_table_sorts_and_selects_and_drives_a_stat():
    """The Table sorts client-side on a header click and selects a row, which
    round-trips to Python and updates a bound Stat (ADR-0021)."""
    handle = launch(_table_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                rows = page.locator("table.table tbody tr")
                expect(rows).to_have_count(3)
                # First data row is AAPL in source order.
                expect(rows.first.locator("td").first).to_have_text("AAPL")

                # Sort by price ascending: NVDA (130) rises to the top (client-side).
                page.locator("table.table th .th-sort", has_text="price").click()
                expect(rows.first.locator("td").first).to_have_text("NVDA")

                # Select that row -> round-trips, the Stat and text echo update.
                rows.first.click()
                expect(page.locator(".stat-value")).to_have_text("$130")
                expect(page.locator("div.text", has_text="NVDA")).to_be_visible()
                expect(rows.first).to_have_class(re.compile("selected"))
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


_BLANK_TILE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="


def _map_app():
    """An interactive Map bound to a center signal, with a marker, a polygon, and a
    polyline, plus a button that flies to a new place (G5). Uses a data: URI as the
    tile source (Leaflet's {z}/{x}/{y} substitution is a no-op on it) so the test
    never makes a real network request to a tile server."""
    from indah import Button, Column, Map, Session, Signal, create_app

    center = Signal((1.35, 103.82))
    markers = [{"lat": 1.35, "lon": 103.82, "label": "here"}]
    polygons = [{"points": [(1.34, 103.81), (1.36, 103.81), (1.35, 103.83)]}]
    polylines = [{"points": [(1.34, 103.80), (1.345, 103.805), (1.35, 103.81)], "weight": 4}]

    def fly():
        center.set((51.5, -0.12))

    m = Map(
        center,
        zoom=11,
        markers=markers,
        polygons=polygons,
        polylines=polylines,
        tile_url=_BLANK_TILE,
        height=300,
    )
    root = Column(children=[m, Button("fly", on_click=fly)])
    return create_app(session=Session(root))


@pytest.mark.e2e
def test_map_renders_markers_and_flies_to_a_new_center():
    """The map mounts a real Leaflet instance with its marker, polygon, and
    polyline, and Python setting a new center flies the existing map there (G5)."""
    handle = launch(_map_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                container = page.locator(".map.leaflet-container")
                expect(container).to_be_visible()
                # The circle marker + the polygon + the polyline are all SVG vector
                # layers; only the polygon's path auto-closes back to its first point.
                expect(page.locator(".map path.leaflet-interactive")).to_have_count(3)

                def center():
                    return container.evaluate(
                        "el => { const c = el.__map.getCenter(); "
                        "return [Math.round(c.lat * 100) / 100, Math.round(c.lng * 100) / 100]; }"
                    )

                assert center() == [1.35, 103.82]
                page.locator("button", has_text="fly").click()
                page.wait_for_function(
                    "() => Math.round(document.querySelector('.map').__map.getCenter().lat) === 52"
                )
                assert center() == [51.5, -0.12]
            finally:
                browser.close()
    finally:
        handle.stop()


# A real subset of examples/data/gpx_viewer/southern-ridges-sg.json (points
# 0, 30, 65, 100, -1 of the actual fetched/cached track), not synthetic coordinates.
_GPX_POINTS = [
    (1.278139, 103.813222),
    (1.279891, 103.804978),
    (1.280516, 103.794525),
    (1.288247, 103.788487),
    (1.296998, 103.772546),
]
_GPX_CURRENT_COLOR = "#b5296b"


def _gpx_viewer_app():
    """The shape of examples/gpx_viewer.py, trimmed to a handful of real trackpoints:
    a Map with the track as a polyline plus a moving current-position marker,
    scrubbed by a Slider bound to the same progress signal the real demo uses."""
    from indah import Column, Map, Session, Signal, Slider, create_app

    progress = Signal(0.0)

    def current_point():
        # Interpolate by point index (not haversine distance) - good enough for
        # this trimmed-down e2e check; the real demo interpolates by distance.
        t = (progress.value / 100.0) * (len(_GPX_POINTS) - 1)
        i = min(int(t), len(_GPX_POINTS) - 2)
        frac = t - i
        lat = _GPX_POINTS[i][0] + (_GPX_POINTS[i + 1][0] - _GPX_POINTS[i][0]) * frac
        lon = _GPX_POINTS[i][1] + (_GPX_POINTS[i + 1][1] - _GPX_POINTS[i][1]) * frac
        return lat, lon

    def markers():
        lat, lon = current_point()
        start_lat, start_lon = _GPX_POINTS[0]
        end_lat, end_lon = _GPX_POINTS[-1]
        return [
            {"lat": start_lat, "lon": start_lon, "label": "Start", "color": "#2e6d62"},
            {"lat": end_lat, "lon": end_lon, "label": "End", "color": "#8a3ffc"},
            {
                "lat": lat,
                "lon": lon,
                "label": "Current position",
                "color": _GPX_CURRENT_COLOR,
                "radius": 9,
            },
        ]

    trail_map = Map(
        (1.2867, 103.7936),
        zoom=13,
        markers=markers,
        polylines=[{"points": _GPX_POINTS, "color": "#b5296b", "weight": 4}],
        tile_url=_BLANK_TILE,
        height=300,
    )
    scrubber = Slider(progress, min=0, max=100, step=1, label="Progress")
    root = Column(children=[trail_map, scrubber])
    return create_app(session=Session(root))


@pytest.mark.e2e
def test_gpx_viewer_shape_renders_track_and_syncs_scrubber_to_marker():
    """The first demo to exercise the real interactive Map: the real-track polyline
    (an open path, not auto-closed like a polygon) plus start/end/current markers
    render as real Leaflet vector layers, and dragging the progress slider moves the
    current-position marker along the track."""
    handle = launch(_gpx_viewer_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                container = page.locator(".map.leaflet-container")
                expect(container).to_be_visible()
                # 3 circleMarkers (start/end/current) + 1 open polyline, all SVG paths.
                expect(page.locator(".map path.leaflet-interactive")).to_have_count(4)

                # Find the current-position circleMarker by its distinctive color
                # (options.color), rather than assuming draw/iteration order. `color`
                # is passed in as an arg rather than f-string-interpolated, to keep
                # the JS source short and injection-free.
                find_by_color = """(color) => {
                    let found = null;
                    document.querySelector('.map').__map.eachLayer((l) => {
                        if (l.getLatLng && l.options && l.options.color === color) found = l;
                    });
                    const p = found.getLatLng();
                    return [p.lat, p.lng];
                }"""

                before = page.evaluate(find_by_color, _GPX_CURRENT_COLOR)
                assert round(before[0], 4) == round(_GPX_POINTS[0][0], 4)

                slider = page.locator("input[type=range]")
                slider.evaluate(
                    "el => { el.value = '100';"
                    " el.dispatchEvent(new Event('input', { bubbles: true })); }"
                )
                page.wait_for_function(
                    """([color, before]) => {
                        let found = null;
                        document.querySelector('.map').__map.eachLayer((l) => {
                            if (l.getLatLng && l.options && l.options.color === color) found = l;
                        });
                        const p = found.getLatLng();
                        return Math.abs(p.lat - before[0]) > 0.0001
                            || Math.abs(p.lng - before[1]) > 0.0001;
                    }""",
                    arg=[_GPX_CURRENT_COLOR, before],
                )
                after = page.evaluate(find_by_color, _GPX_CURRENT_COLOR)
                # At 100% progress the current marker should sit at the real track's
                # end point.
                assert round(after[0], 4) == round(_GPX_POINTS[-1][0], 4)
                assert round(after[1], 4) == round(_GPX_POINTS[-1][1], 4)
            finally:
                browser.close()
    finally:
        handle.stop()


def _audio_app():
    """An Audio player bound to a signal, plus a button that swaps the clip - both a
    URL and raw bytes (base64 data: URI) round-trip through the same node (G8)."""
    from indah import Audio, Button, Column, Session, Signal, create_app

    clip = Signal("https://example.com/a.mp3")

    def swap():
        clip.set(b"RIFFtinywavbytes")

    root = Column(children=[Audio(clip, media_type="audio/wav"), Button("swap", on_click=swap)])
    return create_app(session=Session(root))


@pytest.mark.e2e
def test_audio_renders_and_swaps_source_live():
    """A URL source renders as a native <audio controls> element; swapping to raw
    bytes (a data: URI) updates its src live over SSE, no full reload (G8)."""
    handle = launch(_audio_app(), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                audio = page.locator("audio.audio")
                expect(audio).to_have_attribute("src", "https://example.com/a.mp3")
                assert audio.evaluate("el => el.hasAttribute('controls')")

                page.locator("button", has_text="swap").click()
                expect(audio).to_have_attribute("src", re.compile(r"^data:audio/wav;base64,"))
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_audio_with_no_source_shows_a_placeholder():
    """A `None` source renders the empty-state span, not a broken <audio> tag."""
    from indah import Audio, Column, Session, create_app

    handle = launch(
        create_app(session=Session(Column(children=[Audio(None)]))),
        block=False,
        open_inline=False,
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                expect(page.locator(".audio-empty")).to_have_text("No audio")
                expect(page.locator("audio")).to_have_count(0)
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


_RESTART_SERVER = """
import sys, uvicorn
from indah.app import create_app
from indah.components import Button, Column, Text
from indah.reactive import Signal
from indah.session import Session

word, port = sys.argv[1], int(sys.argv[2])

def factory():
    n = Signal(0)
    return Session(
        Column(
            children=[
                Button("tick", on_click=lambda: n.set(n.value + 1)),
                Text(lambda: f"{word} {n.value}"),
            ]
        )
    )

uvicorn.run(create_app(session_factory=factory), host="127.0.0.1", port=port, log_level="error")
"""


def _start_server(word: str, port: int):
    import subprocess
    import sys
    import time
    import urllib.request

    proc = subprocess.Popen([sys.executable, "-c", _RESTART_SERVER, word, str(port)])
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5)
            return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("server did not start")


@pytest.mark.e2e
def test_open_tab_reinitialises_after_the_server_restarts():
    """IND-85: a restarted server has a fresh hub, so the tab's Last-Event-Id belongs
    to a hub that no longer exists. The tab must be sent a new `init` (here the text
    changes from v1 to v2) rather than sit on a stale tree. The server runs in a
    subprocess so killing it really drops the open SSE connection, as a deploy does."""
    from indah.launch import find_free_port

    port = find_free_port(18500)
    proc = _start_server("v1", port)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
                expect(page.locator("div.text", has_text="v1 0")).to_be_visible()
                # A patch first, so the tab holds a real Last-Event-Id before the restart.
                page.get_by_role("button", name="tick").click()
                expect(page.locator("div.text", has_text="v1 1")).to_be_visible()

                proc.kill()
                proc.wait()
                proc = _start_server("v2", port)

                # EventSource reconnects on its own; the new hub must re-init it.
                expect(page.locator("div.text", has_text="v2 0")).to_be_visible(timeout=20_000)
            finally:
                browser.close()
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.e2e
def test_mounted_app_opens_and_stays_live_on_a_deep_link():
    """IND-86: indah mounted at /ui under a parent app, opened directly on an in-app
    path. The shell must render and its api/* calls must resolve to the app root, so a
    click round-trips (the counter increments) rather than 404ing at the deep path."""
    from starlette.applications import Starlette
    from starlette.routing import Mount

    from indah.app import create_app
    from indah.components import Button, Column, Text
    from indah.reactive import Signal
    from indah.session import Session

    def factory() -> Session:
        n = Signal(0)
        return Session(
            Column(
                children=[
                    Button("tick", on_click=lambda: n.set(n.value + 1)),
                    Text(lambda: f"count {n.value}"),
                ]
            )
        )

    parent = Starlette(routes=[Mount("/ui", app=create_app(session_factory=factory, spa=True))])
    handle = launch(parent, block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(
                    f"http://127.0.0.1:{handle.port}/ui/projects/auth/entries/01J",
                    wait_until="domcontentloaded",
                )
                expect(page.locator("div.text", has_text="count 0")).to_be_visible()
                page.get_by_role("button", name="tick").click()
                expect(page.locator("div.text", has_text="count 1")).to_be_visible()
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_themed_app_shows_its_tokens_logo_and_wordmark_in_light_and_dark():
    """IND-88: an app-level theme overrides the shell's tokens in both schemes, and a
    custom logo plus title replace the Bunga mark and the "indah" wordmark."""
    from indah.app import create_app
    from indah.components import Column, Text
    from indah.session import Session
    from indah.theme import Theme

    logo = (
        b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8'>"
        b"<rect width='8' height='8' fill='#1f6feb'/></svg>"
    )
    app = create_app(
        session_factory=lambda: Session(Column(children=[Text("hello")])),
        title="semula",
        logo=logo,
        theme=Theme(light={"primary": "#1f6feb"}, dark={"primary": "#79b8ff"}, radius="3px"),
    )
    handle = launch(app, block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                expect(page.locator("header.brand .wordmark")).to_have_text("semula")
                img = page.locator("header.brand img.mark")
                expect(img).to_be_visible()
                assert img.evaluate("el => el.naturalWidth") > 0  # the logo actually loaded

                def token(name: str) -> str:
                    return page.evaluate(
                        "n => getComputedStyle(document.documentElement)"
                        ".getPropertyValue(n).trim()",
                        name,
                    )

                page.evaluate("document.documentElement.dataset.theme = 'light'")
                assert token("--primary") == "#1f6feb" and token("--radius") == "3px"
                page.evaluate("document.documentElement.dataset.theme = 'dark'")
                assert token("--primary") == "#79b8ff"
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_stream_bound_list_appends_live_and_trims_to_its_limit():
    """IND-90: rows appended to a Stream reach the browser as coalesced append patches,
    and the `trim` keeps only the newest `limit` in the DOM."""
    import asyncio

    from indah.app import create_app
    from indah.components import Button, Column, List
    from indah.session import Session
    from indah.stream import Stream

    def factory() -> Session:
        rows = Stream(limit=5)

        async def burst() -> None:
            for i in range(12):
                rows.append({"t": f"row {i}"})
                await asyncio.sleep(0.03)

        return Session(
            Column(
                children=[
                    List(rows, item={"tag": "span", "text": "t"}),
                    Button("go", on_click=burst),
                ]
            )
        )

    handle = launch(create_app(session_factory=factory), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                page.get_by_role("button", name="go").click()
                expect(page.locator(".list-item", has_text="row 11")).to_be_visible()
                texts = page.locator(".list-item").all_inner_texts()
                assert texts == [f"row {i}" for i in range(7, 12)]
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_two_tabs_follow_a_topic_published_from_another_thread():
    """IND-89: a plain thread publishes to a Topic; both open tabs show the rows, while a
    per-tab counter stays separate."""
    import threading
    import time

    from indah.app import create_app
    from indah.components import Button, Column, List, Text
    from indah.context import Context
    from indah.push import Topic
    from indah.reactive import Signal
    from indah.session import Session

    topic: Topic[dict] = Topic("log", replay=50)

    def factory(ctx: Context) -> Session:
        rows = ctx.tail(topic, limit=20)
        mine = Signal(0)
        return Session(
            Column(
                children=[
                    List(rows, item={"tag": "span", "text": "t"}),
                    Button("mine", on_click=lambda: mine.set(mine.value + 1)),
                    Text(lambda: f"mine={mine.value}"),
                ]
            )
        )

    handle = launch(create_app(session_factory=factory), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            tabs = [browser.new_context().new_page() for _ in range(2)]
            try:
                for page in tabs:
                    page.goto(handle.url, wait_until="domcontentloaded")
                    expect(page.locator("div.text", has_text="mine=0")).to_be_visible()

                def publisher() -> None:
                    for i in range(15):
                        topic.publish_threadsafe({"t": f"event {i}"})
                        time.sleep(0.02)

                threading.Thread(target=publisher).start()
                for page in tabs:
                    expect(page.locator(".list-item", has_text="event 14")).to_be_visible()
                    assert page.locator(".list-item").count() == 15

                tabs[0].get_by_role("button", name="mine").click()
                expect(tabs[0].locator("div.text", has_text="mine=1")).to_be_visible()
                expect(tabs[1].locator("div.text", has_text="mine=0")).to_be_visible()
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_rich_table_renders_typed_cells_selects_by_key_and_follows_a_stream():
    """IND-91: typed cells (badge, mono, relative time, number), a sticky header, selection
    by row key that survives sorting, and rows streamed in live."""
    import time

    from indah.app import create_app
    from indah.components import Button, Col, Column, Table, Text
    from indah.reactive import Signal
    from indah.session import Session
    from indah.stream import Stream

    def row(i: int, result: str) -> dict:
        return {
            "id": f"01ROW{i}",
            "result": result,
            "score": 1000 + i,
            "ts": int(time.time() * 1000) - 30_000,
        }

    def factory() -> Session:
        rows = Stream([row(1, "hit"), row(2, "miss")], limit=50)
        picked: Signal = Signal(None)
        return Session(
            Column(
                children=[
                    Table(
                        rows=rows,
                        key="id",
                        selected=picked,
                        height="12rem",
                        columns=[
                            Col("id", kind="mono", width="12ch"),
                            Col("result", kind="badge", tones={"hit": "ok", "miss": "warn"}),
                            Col("score", kind="number"),
                            Col("ts", title="When", kind="time"),
                        ],
                    ),
                    Button("more", on_click=lambda: rows.append(row(3, "hit"))),
                    Text(lambda: f"picked={picked.value}"),
                ]
            )
        )

    handle = launch(create_app(session_factory=factory), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                expect(page.locator("tbody tr")).to_have_count(2)
                expect(page.locator(".cell-badge.tone-ok", has_text="hit")).to_have_count(1)
                expect(page.locator(".cell-badge.tone-warn", has_text="miss")).to_have_count(1)
                assert page.locator("code.cell-mono").first.inner_text() == "01ROW1"
                assert "1,001" in page.locator("td.num").first.inner_text()
                expect(page.locator("tbody tr td").nth(3)).to_have_text(re.compile(r"\d+s ago"))
                assert (
                    page.locator("thead th").first.evaluate("el => getComputedStyle(el).position")
                    == "sticky"
                )

                # Sort by score descending, then select the top row: the key (not the
                # position) reaches Python.
                page.get_by_role("button", name="score").click()
                page.get_by_role("button", name="score").click()
                page.locator("tbody tr").first.click()
                expect(page.locator("div.text", has_text="picked=01ROW2")).to_be_visible()
                expect(page.locator("tbody tr.selected")).to_have_count(1)

                page.get_by_role("button", name="more").click()
                expect(page.locator("tbody tr")).to_have_count(3)
                expect(page.locator("tbody tr.selected td code")).to_have_text("01ROW2")
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_streaming_table_filters_toggles_columns_and_follows_the_tail():
    """IND-92: client-side search over rows still streaming in, a remembered column
    toggle, and follow-tail that pauses when the viewer scrolls up."""
    import asyncio
    import itertools

    from indah.app import create_app
    from indah.components import Button, Col, Column, Table
    from indah.session import Session
    from indah.stream import Stream

    def factory() -> Session:
        rows = Stream(limit=500)
        counter = itertools.count()

        async def burst() -> None:
            for _ in range(30):
                i = next(counter)
                rows.append({"id": f"r{i:03d}", "result": "miss" if i % 2 else "hit", "score": i})
                await asyncio.sleep(0.01)

        return Session(
            Column(
                children=[
                    Table(
                        rows=rows,
                        key="id",
                        height="10rem",
                        search=True,
                        column_toggle=True,
                        follow=True,
                        label="Log",
                        columns=[Col("id", kind="mono"), Col("result"), Col("score")],
                    ),
                    Button("go", on_click=burst),
                ]
            )
        )

    handle = launch(create_app(session_factory=factory), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                scroller = page.locator(".table-scroll.rich")

                def gap() -> float:
                    return scroller.evaluate(
                        "el => el.scrollHeight - el.scrollTop - el.clientHeight"
                    )

                # Column toggle: hide "score"; the choice survives a reload.
                page.locator(".col-toggle summary").click()
                page.get_by_label("score").uncheck()
                expect(page.locator("thead th", has_text="score")).to_have_count(0)
                page.reload(wait_until="domcontentloaded")
                expect(page.locator("thead th", has_text="result")).to_have_count(1)
                expect(page.locator("thead th", has_text="score")).to_have_count(0)

                # Follow: after a burst the newest row is in view.
                page.get_by_role("button", name="go").click()
                expect(page.locator("tbody tr")).to_have_count(30)
                assert gap() < 24

                # Scroll up: following pauses, and a second burst does not drag us down.
                scroller.evaluate("el => { el.scrollTop = 0; }")
                expect(page.get_by_role("button", name="Resume following")).to_be_visible()
                page.get_by_role("button", name="go").click()
                expect(page.locator("tbody tr")).to_have_count(60)
                assert scroller.evaluate("el => el.scrollTop") < 24
                page.get_by_role("button", name="Resume following").click()
                assert gap() < 24
                expect(page.get_by_role("button", name="Resume following")).to_have_count(0)

                # Filter while rows keep arriving: new matching rows appear, others do not.
                page.get_by_label("Filter rows").fill("miss")
                expect(page.locator("tbody tr")).to_have_count(30)
                expect(page.locator(".table-count")).to_have_text("30 of 60")
                page.get_by_role("button", name="go").click()
                expect(page.locator("tbody tr")).to_have_count(45)
                assert all("miss" in t for t in page.locator("tbody tr").all_inner_texts())
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_semula_live_log_two_tabs_follow_the_same_calls():
    """IND-93: the semula-shaped demo, mounted at /ui under a parent with a lifespan
    producer at 40 events/s. Both tabs show the same live rows, the DOM stays at the
    limit, and a selection in one tab does not move the other."""
    import importlib.util
    import sys
    import time
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "examples" / "semula_log.py"
    spec = importlib.util.spec_from_file_location("semula_log_e2e", path)
    example = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = example
    spec.loader.exec_module(example)

    handle = launch(example.build_app(rate=40.0, limit=30, seed=2), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            tabs = [browser.new_context().new_page() for _ in range(2)]
            try:
                for page in tabs:
                    page.goto(handle.url.rstrip("/") + "/ui/", wait_until="domcontentloaded")
                    expect(page.locator("tbody tr")).to_have_count(30, timeout=15_000)

                time.sleep(1.5)

                def ids(page):
                    return set(page.locator("tbody tr code.cell-mono").all_inner_texts())

                a, b = ids(tabs[0]), ids(tabs[1])
                assert len(a) == len(b) == 30  # bounded at the limit
                assert len(a & b) >= 15  # the same live stream (they differ by a moment)

                tabs[0].locator("tbody tr").last.click()
                expect(tabs[0].locator("tbody tr.selected")).to_have_count(1)
                expect(tabs[0].locator(".card", has_text="via")).to_be_visible()
                expect(tabs[1].locator(".card", has_text="Select a row")).to_be_visible()
                expect(tabs[1].locator("tbody tr.selected")).to_have_count(0)
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_focused_textarea_survives_a_300ms_echo_and_flushes_on_blur():
    """Typing into a TextArea behind a slow echo loses nothing: the server's late
    echoes are ignored while focused (ADR-0013), keystrokes are debounced into few
    POSTs, and blur flushes the final text so the server signal ends up complete."""
    import time

    from indah import Column, Session, Signal, TextArea, create_app

    sig = Signal("")
    app = create_app(session=Session(Column(children=[TextArea(sig, label="Notes")])))
    handle = launch(app, block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            posts = []
            page.on("request", lambda r: posts.append(1) if r.url.endswith("api/event") else None)

            def slow(route):  # delay every event by 300 ms: a laggy proxy
                time.sleep(0.3)
                route.continue_()

            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                box = page.locator("textarea").first
                expect(box).to_be_visible()
                page.route("**/api/event", slow)
                box.click()
                text = "line one\nline two, typed fairly quickly"
                page.keyboard.type(text, delay=20)
                expect(box).to_have_value(text)
                page.wait_for_timeout(1200)  # let the delayed echoes land
                expect(box).to_have_value(text)  # nothing clobbered
                assert 0 < len(posts) < len(text)  # debounced, not per keystroke
                box.blur()
                page.wait_for_timeout(1000)
                assert sig.value == text
                expect(box).to_have_value(text)
            finally:
                browser.close()
    finally:
        handle.stop()


def _dialog_app():
    from indah import Button, Column, Drawer, Modal, Session, Signal, Text, create_app

    shown, note, deleted = Signal(False), Signal(False), []
    root = Column(
        children=[
            Button("Open modal", lambda: shown.set(True)),
            Button("Open drawer", lambda: note.set(True)),
            Button("Delete", lambda: deleted.append(1), confirm="Delete this entry?"),
            Modal(
                [Text("modal body"), Button("Inside", lambda: None)],
                open=shown,
                title="Details",
            ),
            Drawer([Text("drawer body")], open=note, title="Row", side="right"),
        ]
    )
    return create_app(session=Session(root)), shown, note, deleted


@pytest.mark.e2e
def test_modal_is_keyboard_operable_traps_focus_and_returns_it_on_esc():
    app, shown, _, _ = _dialog_app()
    handle = launch(app, block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                opener = page.get_by_role("button", name="Open modal")
                opener.focus()
                page.keyboard.press("Enter")
                dialog = page.get_by_role("dialog", name="Details")
                expect(dialog).to_be_visible()
                assert dialog.get_attribute("aria-modal") == "true"
                for _ in range(6):  # Tab never leaves the dialog
                    page.keyboard.press("Tab")
                    assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null")
                page.keyboard.press("Shift+Tab")
                assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null")
                page.keyboard.press("Escape")
                expect(dialog).to_have_count(0)
                assert shown.value is False  # the close event reached the server
                expect(opener).to_be_focused()
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_drawer_opens_and_closes_from_its_button_and_backdrop():
    app, _, note, _ = _dialog_app()
    handle = launch(app, block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                page.get_by_role("button", name="Open drawer").click()
                drawer = page.get_by_role("dialog", name="Row")
                expect(drawer).to_be_visible()
                page.get_by_role("button", name="Close").click()
                expect(drawer).to_have_count(0)
                assert note.value is False
                page.get_by_role("button", name="Open drawer").click()
                expect(drawer).to_be_visible()
                page.mouse.click(5, 5)  # backdrop
                expect(drawer).to_have_count(0)
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_confirm_button_posts_nothing_until_accepted():
    app, _, _, deleted = _dialog_app()
    handle = launch(app, block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                trigger = page.get_by_role("button", name="Delete", exact=True)
                trigger.click()
                dialog = page.get_by_role("dialog", name="Delete this entry?")
                expect(dialog).to_be_visible()
                expect(page.get_by_role("button", name="Cancel")).to_be_focused()  # safe default
                page.wait_for_timeout(300)
                assert deleted == []
                page.keyboard.press("Escape")
                expect(dialog).to_have_count(0)
                page.wait_for_timeout(300)
                assert deleted == []  # cancelled: still nothing posted
                trigger.click()
                dialog.get_by_role("button", name="Delete", exact=True).click()
                expect(dialog).to_have_count(0)
                page.wait_for_timeout(500)
                assert deleted == [1]
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_ctx_toast_appears_in_the_sender_tab_only_and_expires():
    from indah import Button, Column, Session, create_app

    def build(ctx):
        return Session(
            Column(
                children=[
                    Button("ok", lambda: ctx.toast("Released 01J", kind="success", ttl=1)),
                    Button("sticky", lambda: ctx.toast("Stay", kind="warn", ttl=0)),
                ]
            )
        )

    handle = launch(create_app(session_factory=build), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            a, b = browser.new_page(), browser.new_page()
            try:
                for page in (a, b):
                    page.goto(handle.url, wait_until="domcontentloaded")
                    expect(page.get_by_role("button", name="ok", exact=True)).to_be_visible()
                a.get_by_role("button", name="ok", exact=True).click()
                toast = a.locator(".toast.success")
                expect(toast).to_have_text("Released 01J")
                assert b.locator(".toast").count() == 0  # not the other tab
                expect(toast).to_have_count(0, timeout=4000)  # ttl 1 s
                a.get_by_role("button", name="sticky").click()
                sticky = a.locator(".toast.warn")
                expect(sticky).to_be_visible()
                a.wait_for_timeout(1500)
                expect(sticky).to_be_visible()  # ttl 0: stays
                sticky.click()
                expect(sticky).to_have_count(0)  # until dismissed
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_badge_switch_and_tooltip_render_and_round_trip():
    from indah import Badge, Button, Column, Session, Signal, Switch, create_app

    pinned = Signal(False)
    label = Signal("pending")
    root = Column(
        children=[
            Badge(label, tone="warn"),
            Switch(pinned, label="Pinned"),
            Button("Hover me", lambda: label.set("done"), tooltip="Marks the call done"),
        ]
    )
    handle = launch(create_app(session=Session(root)), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                badge = page.locator(".badge.tone-warn")
                expect(badge).to_have_text("pending")
                sw = page.get_by_role("switch", name="Pinned")
                expect(sw).to_have_attribute("aria-checked", "false")
                sw.click()
                expect(sw).to_have_attribute("aria-checked", "true")
                assert pinned.value is True  # round-tripped to the signal
                pinned.set(False)  # and back from the server
                expect(sw).to_have_attribute("aria-checked", "false")

                btn = page.get_by_role("button", name="Hover me")
                btn.hover()
                tip = page.get_by_role("tooltip")
                expect(tip).to_have_text("Marks the call done")
                page.keyboard.press("Escape")
                expect(tip).to_have_count(0)
                page.mouse.move(0, 0)
                btn.focus()  # keyboard focus shows it too
                expect(page.get_by_role("tooltip")).to_be_visible()
                btn.click()
                expect(badge.or_(page.locator(".badge"))).to_have_text("done")
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_shortcuts_fire_outside_inputs_only_and_help_lists_them():
    from indah import Column, Modal, Session, Shortcuts, Signal, Text, TextArea, create_app

    log, note, shown = [], Signal(""), Signal(False)
    root = Column(
        children=[
            Shortcuts(
                {
                    "a": (lambda: log.append("a"), "Approve"),
                    "g l": (lambda: log.append("g l"), "Go to the log"),
                    "mod+k": lambda: log.append("mod+k"),
                    "m": lambda: shown.set(True),
                }
            ),
            TextArea(note, label="Reply"),
            Modal([Text("dlg")], open=shown, title="Dialog"),
        ]
    )
    handle = launch(create_app(session=Session(root)), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                box = page.locator("textarea")
                expect(box).to_be_visible()
                page.keyboard.press("a")
                page.keyboard.press("g")
                page.keyboard.press("l")
                page.wait_for_timeout(400)
                assert log == ["a", "g l"]
                box.click()
                page.keyboard.type("a g l")  # typing: nothing fires
                page.keyboard.press("Control+k")  # a combo does fire in a field
                page.wait_for_timeout(400)
                assert log == ["a", "g l", "mod+k"]
                expect(box).to_have_value("a g l")
                box.blur()
                page.keyboard.press("g")
                page.keyboard.press("x")  # broken sequence, no fire
                page.keyboard.press("l")
                page.wait_for_timeout(300)
                assert log == ["a", "g l", "mod+k"]
                page.keyboard.press("Shift+?")
                help_ = page.get_by_role("dialog", name="Keyboard shortcuts")
                expect(help_).to_contain_text("Approve")
                expect(help_).to_contain_text("Go to the log")
                page.keyboard.press("Escape")
                expect(help_).to_have_count(0)
                page.keyboard.press("m")  # opens a dialog...
                expect(page.get_by_role("dialog", name="Dialog")).to_be_visible()
                page.keyboard.press("a")  # ...under which shortcuts are off
                page.wait_for_timeout(300)
                assert log == ["a", "g l", "mod+k"]
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_table_row_actions_with_confirm_and_multi_select():
    from indah import Col, RowAction, Session, Signal, Table, create_app

    rows = [{"id": f"r{i}", "name": f"call {i}"} for i in range(1, 4)]
    checked, selected, log = Signal([]), Signal(None), []
    table = Table(
        rows=rows,
        columns=[Col("id", "ID"), Col("name", "Name")],
        key="id",
        selected=selected,
        checked=checked,
        actions=[
            RowAction("Pin", lambda k: log.append(("pin", k))),
            RowAction("Delete", lambda k: log.append(("del", k)), confirm="Delete this call?"),
        ],
    )
    handle = launch(create_app(session=Session(table)), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                row2 = page.locator("tbody tr").nth(1)
                expect(row2).to_be_visible()
                row2.get_by_role("button", name="Pin").click()
                page.wait_for_timeout(300)
                assert log == [("pin", "r2")]
                assert selected.value is None  # an action click is not a row select

                row2.get_by_role("button", name="Delete").click()
                dialog = page.get_by_role("dialog", name="Delete this call?")
                expect(dialog).to_be_visible()
                page.wait_for_timeout(300)
                assert log == [("pin", "r2")]  # nothing until accepted
                dialog.get_by_role("button", name="Delete", exact=True).click()
                page.wait_for_timeout(300)
                assert log[-1] == ("del", "r2")

                row2.get_by_label("Select row").check()
                page.locator("tbody tr").nth(0).get_by_label("Select row").check()
                page.wait_for_timeout(300)
                assert sorted(checked.value) == ["r1", "r2"]
                assert selected.value is None  # checking is not selecting
                page.get_by_label("Select all rows").check()
                page.wait_for_timeout(300)
                assert sorted(checked.value) == ["r1", "r2", "r3"]
                page.get_by_label("Select all rows").uncheck()
                page.wait_for_timeout(300)
                assert checked.value == []
                checked.set(["r3"])  # server-side change reaches the boxes
                expect(page.locator("tbody tr").nth(2).get_by_label("Select row")).to_be_checked()
                row2.locator("td").nth(1).click()
                page.wait_for_timeout(300)
                assert selected.value == "r2"  # a plain row click still selects
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_pending_queue_release_in_one_tab_clears_the_row_in_both():
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "examples" / "semula_pending.py"
    spec = importlib.util.spec_from_file_location("semula_pending_e2e", path)
    ex = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ex
    spec.loader.exec_module(ex)

    app = ex.build_app(rate=80, max_pending=3, seed=5)
    handle = launch(app, block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            a, b = browser.new_page(), browser.new_page()
            try:
                for page in (a, b):
                    page.goto(handle.url.rstrip("/") + "/ui/", wait_until="domcontentloaded")
                    expect(page.locator("tbody tr")).to_have_count(3)
                    expect(page.get_by_text("3 waiting")).to_be_visible()
                queue = app.state.queue
                first = queue.snapshot()[0]["id"]

                # Review in tab A: drawer, reply, Submit.
                a.locator("tbody tr").first.get_by_role("button", name="Review").click()
                drawer = a.get_by_role("dialog", name="Review call")
                expect(drawer).to_be_visible()
                expect(drawer).to_contain_text(first)
                box = drawer.locator("textarea")
                box.fill("Use the 30-day policy.")
                drawer.get_by_role("button", name="Submit").click()
                expect(a.locator(".toast.success")).to_contain_text("Released")
                a.wait_for_timeout(300)
                assert queue.resolved[0].reply == "Use the 30-day policy."
                assert first not in a.locator("tbody").inner_text()
                assert first not in b.locator("tbody").inner_text()  # gone in tab B too
                assert b.locator(".toast").count() == 0  # the toast was A's alone

                # Keyboard triage in tab B: j moves the cursor, r rejects the row.
                b.locator("body").click(position={"x": 2, "y": 2})
                b.keyboard.press("j")
                second = queue.snapshot()[0]["id"]
                expect(b.locator("tbody tr.selected")).to_have_count(1)
                b.keyboard.press("r")
                b.wait_for_timeout(400)
                assert queue.resolved[-1].call["id"] == second
                assert queue.resolved[-1].outcome == "rejected"
                assert second not in a.locator("tbody").inner_text()
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_remote_table_debounces_queries_and_round_trips_search_sort_and_paging():
    import time

    from indah import Col, Session, Table, create_app

    data = [{"id": f"r{i:05d}", "n": i, "name": f"call {i}"} for i in range(2000)]
    queries = []

    def loader(q):
        queries.append((q.search, q.sort, q.offset, q.seq))
        if q.search == "call 1":
            time.sleep(0.6)  # a slow old query: it must not overwrite the next one
        rows = [r for r in data if q.search in r["name"]]
        if q.sort:
            rows.sort(key=lambda r: r[q.sort[0]], reverse=q.sort[1] == "desc")
        return rows[q.offset : q.offset + q.limit], len(rows)

    table = Table(
        columns=[Col("id", kind="mono"), Col("n", kind="number", sortable=True), Col("name")],
        key="id",
        remote=loader,
        search=True,
        page_size=20,
    )
    handle = launch(create_app(session=Session(table)), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                rows = page.locator("tbody tr")
                expect(rows).to_have_count(20)
                expect(page.get_by_text("2000 rows")).to_be_visible()
                expect(page.get_by_text("Page 1 / 100")).to_be_visible()

                # A burst of typing is one query, not one per key.
                box = page.get_by_label("Filter rows")
                before = len(queries)
                box.press_sequentially("call 17", delay=30)
                expect(page.get_by_text("111 rows")).to_be_visible()  # 17, 170-179, 1700-1799 ...
                assert len(queries) - before <= 2

                # Stale drop: "call 1" is slow; the newer "call 12" must win.
                box.fill("")
                box.press_sequentially("call 1", delay=10)
                page.wait_for_timeout(300)  # debounce fired, the slow loader is running
                box.press_sequentially("2", delay=10)
                expect(page.get_by_text("111 rows")).to_be_visible()  # "call 12"
                page.wait_for_timeout(1000)  # long enough for the slow "call 1" answer to land
                expect(page.get_by_text("1111 rows")).to_have_count(0)  # it was dropped
                expect(page.get_by_text("111 rows")).to_be_visible()
                assert all("call 12" in r.inner_text() for r in rows.all())

                # Server-side sort and paging.
                box.fill("")
                expect(page.get_by_text("2000 rows")).to_be_visible()
                page.get_by_role("button", name="n", exact=True).click()
                page.get_by_role("button", name="n", exact=True).click()  # descending
                expect(rows.first).to_contain_text("call 1999")
                page.get_by_role("button", name="Next").click()
                expect(page.get_by_text("Page 2 / 100")).to_be_visible()
                expect(rows.first).to_contain_text("call 1979")
                assert queries[-1][1] == ("n", "desc") and queries[-1][2] == 20
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_virtual_remote_table_keeps_the_dom_small_scrolls_smoothly_and_refetches_on_sort():
    from indah import Col, Session, Table, create_app

    n = 20000
    data = [{"id": f"r{i:06d}", "n": i, "name": f"call {i}"} for i in range(n)]
    queries = []

    def loader(q):
        queries.append((q.search, q.sort, q.offset, q.limit))
        rows = data
        if q.search:
            rows = [r for r in rows if q.search in r["name"]]
        if q.sort:
            rows = sorted(rows, key=lambda r: r[q.sort[0]], reverse=q.sort[1] == "desc")
        return rows[q.offset : q.offset + q.limit], len(rows)

    table = Table(
        columns=[Col("id", kind="mono"), Col("n", kind="number", sortable=True), Col("name")],
        key="id",
        remote=loader,
        search=True,
        height="24rem",
        virtual=True,
    )
    handle = launch(create_app(session=Session(table)), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                expect(page.get_by_text("20000 rows")).to_be_visible()
                expect(page.locator("tbody tr:not(.vspacer):not(.ph)").first).to_be_visible()
                dom_rows = lambda: page.locator("tbody tr").count()  # noqa: E731
                assert dom_rows() < 200

                # The scrollbar tracks `total`: 20k rows of 36 px.
                height = page.evaluate("document.querySelector('.table-scroll').scrollHeight")
                assert abs(height - n * 36) < 400

                # Scroll through the whole table in big steps, measuring frame times.
                stats = page.evaluate(
                    """async () => {
                      const el = document.querySelector('.table-scroll');
                      let last = performance.now(), worst = 0, frames = 0;
                      for (let y = 0; y < el.scrollHeight; y += 18000) {
                        el.scrollTop = y;
                        await new Promise(r => requestAnimationFrame(r));
                        const t = performance.now();
                        worst = Math.max(worst, t - last);
                        last = t;
                        frames++;
                      }
                      return {worst, frames};
                    }"""
                )
                assert stats["worst"] < 100, stats
                assert dom_rows() < 200

                # Jump to the middle: rows for that position arrive and are the right ones.
                page.evaluate("document.querySelector('.table-scroll').scrollTop = 10000 * 36")
                page.wait_for_timeout(800)
                first = page.locator("tbody tr:not(.vspacer):not(.ph)").first.inner_text()
                idx = int(first.split("call ")[1].split()[0])
                assert 9980 <= idx <= 10010, first
                assert dom_rows() < 200

                # Sorting round-trips: descending puts the last row first, scrollbar unchanged.
                page.get_by_role("button", name="n", exact=True).click()
                page.get_by_role("button", name="n", exact=True).click()
                expect(page.locator("tbody tr:not(.vspacer):not(.ph)").first).to_contain_text(
                    "call 19999"
                )
                assert page.evaluate("document.querySelector('.table-scroll').scrollTop") == 0
                assert queries[-1][1] == ("n", "desc")

                # Search shrinks the scrollbar to the matches.
                page.get_by_label("Filter rows").fill("call 1999")
                expect(page.get_by_text("11 rows")).to_be_visible()
                height = page.evaluate("document.querySelector('.table-scroll').scrollHeight")
                assert height < 20 * 36 + 100
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_virtual_static_table_renders_only_the_visible_rows():
    from indah import Col, Session, Table, create_app

    rows = [{"id": f"r{i}", "n": i} for i in range(5000)]
    table = Table(
        rows=rows,
        columns=[Col("id"), Col("n", kind="number", sortable=True)],
        key="id",
        height="20rem",
        virtual=True,
        search=True,
    )
    handle = launch(create_app(session=Session(table)), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                expect(page.locator("tbody tr").first).to_be_visible()
                assert page.locator("tbody tr").count() < 60
                page.evaluate("document.querySelector('.table-scroll').scrollTop = 3000 * 36")
                expect(page.get_by_text("r3000", exact=True)).to_be_visible()
                assert page.locator("tbody tr").count() < 60
                page.get_by_label("Filter rows").fill("r49")
                expect(page.locator("tbody tr:not(.vspacer)").first).to_contain_text("r49")
            finally:
                browser.close()
    finally:
        handle.stop()


def _panes_app(**app_kw):
    from indah import (
        Col,
        Column,
        MasterDetail,
        Session,
        Signal,
        SplitPane,
        Table,
        Text,
        create_app,
    )

    picked, open_ = Signal(None), Signal(False)
    rows = [{"id": f"r{i}", "name": f"call {i}"} for i in range(8)]
    table = Table(rows=rows, columns=[Col("id"), Col("name")], key="id", selected=picked)
    root = Column(
        children=[
            SplitPane(Text("left pane"), Text("right pane"), initial=0.4, key="t1"),
            MasterDetail(table, Text("the detail"), open=open_, key="t2", title="Call detail"),
        ]
    )
    return create_app(session=Session(root), **app_kw), open_


@pytest.mark.e2e
def test_split_pane_drags_resizes_by_keyboard_and_the_ratio_survives_reload():
    app, _ = _panes_app()
    handle = launch(app, block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1100, "height": 800})
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                sep = page.get_by_role("separator").first
                expect(sep).to_have_attribute("aria-valuenow", "40")

                first = page.locator(".split-pane").first
                width0 = first.bounding_box()["width"]
                box = sep.bounding_box()
                page.mouse.move(box["x"] + 5, box["y"] + 5)
                page.mouse.down()
                page.mouse.move(box["x"] + 5 + 150, box["y"] + 5, steps=5)
                page.mouse.up()
                assert first.bounding_box()["width"] > width0 + 100  # dragged wider
                dragged = int(sep.get_attribute("aria-valuenow"))
                assert dragged > 40

                sep.focus()
                page.keyboard.press("ArrowLeft")
                assert int(sep.get_attribute("aria-valuenow")) == dragged - 2
                page.keyboard.press("Shift+ArrowLeft")
                assert int(sep.get_attribute("aria-valuenow")) == dragged - 12
                page.keyboard.press("Home")
                expect(sep).to_have_attribute("aria-valuenow", "20")  # clamped to min
                page.keyboard.press("End")
                expect(sep).to_have_attribute("aria-valuenow", "80")
                page.keyboard.press("ArrowRight")
                expect(sep).to_have_attribute("aria-valuenow", "80")  # never past the limit
                page.keyboard.press("Home")
                page.keyboard.press("ArrowRight")  # 22

                page.reload(wait_until="domcontentloaded")  # a new session, same browser
                expect(page.get_by_role("separator").first).to_have_attribute("aria-valuenow", "22")
                page.get_by_role("separator").first.dblclick()
                expect(page.get_by_role("separator").first).to_have_attribute("aria-valuenow", "40")
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_master_detail_is_a_split_when_wide_and_a_drawer_when_narrow():
    app, open_ = _panes_app()
    handle = launch(app, block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1100, "height": 800})
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                expect(page.get_by_text("the detail")).to_be_visible()  # wide: side by side

                page.set_viewport_size({"width": 600, "height": 800})
                expect(page.get_by_text("the detail")).to_have_count(0)  # narrow: hidden
                open_.set(True)  # the app picked a row
                drawer = page.get_by_role("dialog", name="Call detail")
                expect(drawer).to_contain_text("the detail")
                page.keyboard.press("Escape")
                expect(drawer).to_have_count(0)
                assert open_.value is False  # the close reached the server

                page.set_viewport_size({"width": 1100, "height": 800})
                expect(page.get_by_text("the detail")).to_be_visible()
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_compact_density_shrinks_table_rows_app_wide_and_per_table():
    from indah import Col, Column, Session, Table, create_app

    rows = [{"id": f"r{i}"} for i in range(6)]

    def tables():
        return Column(
            children=[
                Table(rows=rows, columns=[Col("id")], key="id", label="plain"),
                Table(rows=rows, columns=[Col("id")], key="id", label="dense", density="compact"),
            ]
        )

    def row_height(page, label):
        return (
            page.locator(".field", has_text=label)
            .locator("tbody tr")
            .first.bounding_box()["height"]
        )

    heights = {}
    for name, kw in (("comfortable", {}), ("compact", {"density": "compact"})):
        handle = launch(create_app(session=Session(tables()), **kw), block=False, open_inline=False)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                try:
                    page.goto(handle.url, wait_until="domcontentloaded")
                    expect(page.locator("tbody tr").first).to_be_visible()
                    heights[name] = (row_height(page, "plain"), row_height(page, "dense"))
                finally:
                    browser.close()
        finally:
            handle.stop()
    plain, dense = heights["comfortable"]
    assert dense < plain - 6  # a per-table override shrinks just that table
    assert heights["compact"][0] < plain - 6  # app-wide compact shrinks the plain one too
    assert abs(heights["compact"][0] - heights["compact"][1]) < 1


@pytest.mark.e2e
def test_entries_browser_meets_its_scroll_and_latency_budgets_on_20k_rows():
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "examples" / "semula_entries.py"
    spec = importlib.util.spec_from_file_location("semula_entries_e2e", path)
    ex = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ex
    spec.loader.exec_module(ex)

    handle = launch(ex.build_app(n=20_000, seed=4), block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1300, "height": 900})
            try:
                page.goto(handle.url.rstrip("/") + "/ui/", wait_until="domcontentloaded")
                body = page.locator("tbody tr:not(.vspacer):not(.ph)")
                expect(body.first).to_be_visible()
                expect(page.get_by_text("20000 rows")).to_be_visible()
                assert page.locator("tbody tr").count() < 200

                # Scrolling the whole table stays within the frame budget, DOM bounded.
                worst = page.evaluate(
                    """async () => {
                      const el = document.querySelector('.table-scroll');
                      let last = performance.now(), worst = 0;
                      for (let y = 0; y < el.scrollHeight; y += 20000) {
                        el.scrollTop = y;
                        await new Promise(r => requestAnimationFrame(r));
                        const t = performance.now();
                        worst = Math.max(worst, t - last);
                        last = t;
                      }
                      return worst;
                    }"""
                )
                assert worst < 100, worst
                assert page.locator("tbody tr").count() < 200

                # Project filter and search narrow the scrollbar; sorting by hits reorders.
                page.get_by_label("Project").select_option("docs-qa")
                expect(page.get_by_text("20000 rows")).to_have_count(0)
                page.get_by_label("Filter rows").fill("case 1999")
                expect(page.get_by_text("rows").first).to_be_visible()
                page.get_by_label("Filter rows").fill("")
                page.get_by_role("button", name="hits", exact=True).click()
                page.get_by_role("button", name="hits", exact=True).click()  # descending
                page.wait_for_timeout(500)
                hits = [
                    int(r.locator("td.num").inner_text().replace(",", "")) for r in body.all()[:10]
                ]
                assert hits == sorted(hits, reverse=True)

                # Selecting a row previews it beside the table; pinning shows a badge.
                body.nth(2).click()
                expect(page.get_by_text("Cached response")).to_be_visible()
                page.get_by_role("button", name="Pin / unpin").click()
                expect(page.locator(".cell-badge", has_text="pinned").first).to_be_visible()

                # Compact density shrinks the rows.
                before = body.first.bounding_box()["height"]
                page.get_by_role("switch", name="Compact").click()
                page.wait_for_timeout(300)
                assert body.first.bounding_box()["height"] < before - 4
            finally:
                browser.close()
    finally:
        handle.stop()


def _routed_parent_app():
    from starlette.applications import Starlette
    from starlette.routing import Mount

    from indah import Button, Column, Link, Router, Session, Text, create_app

    def build(ctx):
        return Session(
            Column(
                children=[
                    Link(ctx, "Home", to="/"),
                    Link(ctx, "Auth project", to="/projects/auth"),
                    Button("Go to billing", lambda: ctx.navigate("/projects/billing")),
                    Button("Replace to home", lambda: ctx.navigate("/", replace=True)),
                    Router(
                        ctx,
                        routes={
                            "/": Text("HOME PAGE"),
                            "/projects/{project}": Text("PROJECT PAGE"),
                            "/projects/{project}/entries/{entry_id}": Text("ENTRY PAGE"),
                        },
                        not_found=Text("NOT FOUND PAGE"),
                    ),
                ]
            )
        )

    ui = create_app(session_factory=build, spa=True, proxy_flush=False)
    return Starlette(routes=[Mount("/ui", app=ui)])


@pytest.mark.e2e
def test_router_deep_links_back_forward_new_tab_and_server_navigation_under_a_mount():
    handle = launch(_routed_parent_app(), block=False, open_inline=False)
    root = handle.url.rstrip("/")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context()
            page = context.new_page()
            try:
                # A pasted deep link opens that page, under the /ui mount.
                page.goto(f"{root}/ui/projects/auth/entries/01J", wait_until="domcontentloaded")
                expect(page.get_by_text("ENTRY PAGE")).to_be_visible()
                page.goto(f"{root}/ui/zzz", wait_until="domcontentloaded")
                expect(page.get_by_text("NOT FOUND PAGE")).to_be_visible()

                # Links navigate without a page load, and Back/Forward follow the history.
                page.goto(f"{root}/ui/", wait_until="domcontentloaded")
                expect(page.get_by_text("HOME PAGE")).to_be_visible()
                page.evaluate("window.__marker = 'same-document'")
                page.get_by_role("link", name="Auth project").click()
                expect(page.get_by_text("PROJECT PAGE")).to_be_visible()
                assert page.url == f"{root}/ui/projects/auth"
                assert page.evaluate("window.__marker") == "same-document"  # no reload
                page.go_back()
                expect(page.get_by_text("HOME PAGE")).to_be_visible()
                assert page.url == f"{root}/ui/"
                page.go_forward()
                expect(page.get_by_text("PROJECT PAGE")).to_be_visible()
                assert page.url == f"{root}/ui/projects/auth"

                # A link is a real href: opening it in a new tab lands on the same page.
                href = page.get_by_role("link", name="Auth project").get_attribute("href")
                assert href == "/ui/projects/auth"
                other = context.new_page()
                other.goto(root + href, wait_until="domcontentloaded")
                expect(other.get_by_text("PROJECT PAGE")).to_be_visible()
                other.close()

                # Server-side navigation moves the address bar; replace=True rewrites history.
                page.get_by_role("button", name="Go to billing").click()
                expect(page).to_have_url(f"{root}/ui/projects/billing")
                page.get_by_role("button", name="Replace to home").click()
                expect(page).to_have_url(f"{root}/ui/")
                expect(page.get_by_text("HOME PAGE")).to_be_visible()
                page.go_back()  # replace dropped the billing entry: back is the auth page
                expect(page).to_have_url(f"{root}/ui/projects/auth")
                expect(page.get_by_text("PROJECT PAGE")).to_be_visible()

                # A reload keeps the page: the stream asks for it by path.
                page.reload(wait_until="domcontentloaded")
                expect(page.get_by_text("PROJECT PAGE")).to_be_visible()
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_route_params_and_active_links_follow_the_url():
    from starlette.applications import Starlette
    from starlette.routing import Mount

    from indah import Column, Link, Router, Session, Sidebar, Text, computed, create_app

    entries = {("auth", "01J"): "the login reply", ("auth", "02K"): "the logout reply"}

    def build(ctx):
        entry = computed(
            lambda: entries.get((ctx.params.value.get("project"), ctx.params.value.get("entry_id")))
        )
        nav = Column(
            children=[
                Link(ctx, "Home", to="/"),
                Link(ctx, "Auth", to="/projects/auth", match="prefix"),
                Link(ctx, "Entry 01J", to="/projects/auth/entries/01J"),
                Link(ctx, "Entry 02K", to="/projects/auth/entries/02K"),
            ]
        )
        pages = Router(
            ctx,
            routes={
                "/": Text("HOME"),
                "/projects/{project}": Text(lambda: f"PROJECT {ctx.params.value.get('project')}"),
                "/projects/{project}/entries/{entry_id}": Text(
                    lambda: f"ENTRY {ctx.params.value.get('entry_id')}: {entry.value}"
                ),
            },
            not_found=Text("NOT FOUND"),
        )
        return Session(Sidebar(children=[nav, pages]))

    ui = create_app(session_factory=build, spa=True, proxy_flush=False)
    handle = launch(Starlette(routes=[Mount("/ui", app=ui)]), block=False, open_inline=False)
    root = handle.url.rstrip("/")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(f"{root}/ui/projects/auth/entries/02K", wait_until="domcontentloaded")
                expect(page.get_by_text("ENTRY 02K: the logout reply")).to_be_visible()
                active = page.locator("a.link.active")
                expect(active).to_have_count(2)  # the section (prefix) and the page itself
                expect(page.locator("a.link[aria-current=page]")).to_have_count(2)
                expect(active.nth(0)).to_have_text("Auth")
                expect(active.nth(1)).to_have_text("Entry 02K")

                page.get_by_role("link", name="Entry 01J").click()
                expect(page.get_by_text("ENTRY 01J: the login reply")).to_be_visible()
                expect(page.locator("a.link.active", has_text="Entry 01J")).to_have_count(1)
                expect(page.locator("a.link.active", has_text="Entry 02K")).to_have_count(0)

                page.get_by_role("link", name="Home").click()
                expect(page.get_by_text("HOME", exact=True)).to_be_visible()
                expect(page.locator("a.link.active")).to_have_count(1)
                page.go_back()  # Back restores the page, its params and the highlight
                expect(page.get_by_text("ENTRY 01J: the login reply")).to_be_visible()
                expect(page.locator("a.link.active", has_text="Auth")).to_have_count(1)
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_routes_demo_deep_link_row_click_switcher_back_and_new_tab_under_ui():
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "examples" / "semula_routes.py"
    spec = importlib.util.spec_from_file_location("semula_routes_e2e", path)
    ex = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ex
    spec.loader.exec_module(ex)

    app = ex.build_app(per_project=8, seed=3)
    entry = next(iter(app.state.data["docs-qa"].values()))
    handle = launch(app, block=False, open_inline=False)
    root = handle.url.rstrip("/")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context()
            page = context.new_page()
            try:
                # Paste an entry URL into a fresh tab: it opens that entry.
                page.goto(f"{root}/ui/projects/docs-qa/entries/{entry['id']}")
                expect(page.get_by_text(entry["response"])).to_be_visible()
                expect(page.locator("a.link.active", has_text="docs-qa")).to_have_count(1)

                # Back to the project via the in-page link; then click a row to open an entry.
                page.get_by_role("link", name="Back to the project").click()
                expect(page).to_have_url(f"{root}/ui/projects/docs-qa")
                expect(page.get_by_text("8 cached entries")).to_be_visible()
                page.locator("tbody tr").nth(1).click()
                expect(page).to_have_url(re.compile(r"/ui/projects/docs-qa/entries/[0-9A-Z]{10}$"))
                expect(page.get_by_text("Cached response")).to_be_visible()

                # The project switcher lives in the URL, and Back undoes it.
                page.get_by_role("link", name="Back to the project").click()
                page.get_by_label("Project").select_option("code-review")
                expect(page).to_have_url(f"{root}/ui/projects/code-review")
                page.go_back()
                expect(page).to_have_url(f"{root}/ui/projects/docs-qa")
                expect(page.get_by_label("Project")).to_have_value("docs-qa")
                page.go_forward()
                expect(page).to_have_url(f"{root}/ui/projects/code-review")

                # A link opened in a new tab lands on the same page.
                href = page.get_by_role("link", name="docs-qa").get_attribute("href")
                other = context.new_page()
                other.goto(root + href)
                expect(other.get_by_text("8 cached entries")).to_be_visible()
                other.close()

                # Overview, Back stays put, and an unknown address is a 404 page.
                page.get_by_role("link", name="Overview").click()
                expect(page.get_by_text("Pick one from the sidebar")).to_be_visible()
                page.wait_for_timeout(300)
                assert page.url == f"{root}/ui/"  # the switcher did not bounce us to a project
                page.goto(f"{root}/ui/no/such/page")
                expect(page.get_by_text("There is no page at this address.")).to_be_visible()
                page.get_by_role("link", name="Go to the overview").click()
                expect(page.get_by_text("Pick one from the sidebar")).to_be_visible()
            finally:
                browser.close()
    finally:
        handle.stop()
