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
                page.locator("button").dispatch_event("click")  # server sets it "STALE"
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
                page.locator("button").dispatch_event("click")  # server sets it to 2
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
