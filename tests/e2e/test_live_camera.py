"""A real browser with a fake camera sends frames to a Camera handler (ADR-0045, IND-74).

Chromium's fake media device gives ``getUserMedia`` a generated test pattern, so no hardware is
needed. One run serves the Tier 1 WebSocket (``live=True``), the other has live off and shows the
Tier 0 snapshot fallback. Both run under the suite's strict CSP, so the ``connect-src`` entry for
the socket is exercised too.
"""

import pytest

import indah
from indah import Camera, Column, Text, create_app
from indah.launch import launch
from indah.reactive import Signal
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")

FAKE_CAMERA = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]


def _app(**kw):
    def factory() -> Session:
        count = Signal(0)
        last = Signal(0)

        def on_frame(frame: indah.Frame) -> None:
            count.set(count.value + 1)
            last.set(frame.size)

        cam = Camera(on_frame, fps=10, max_width=160)
        status = Text(lambda: f"mode={cam.transport.value} frames={count.value} bytes={last.value}")
        return Session(Column(children=[cam, status]))

    return create_app(session_factory=factory, **kw)


def _run(page_url: str, expect_mode: str) -> str:
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch(args=FAKE_CAMERA)
        page = browser.new_context(permissions=["camera"]).new_page()
        page.goto(page_url)
        page.get_by_role("button", name="Start camera").click()
        page.wait_for_function(
            f"() => /mode={expect_mode} frames=[1-9]/.test(document.body.innerText)",
            timeout=20000,
        )
        text = page.inner_text("body")
        page.get_by_role("button", name="Stop camera").click()
        page.wait_for_function("() => /mode=off/.test(document.body.innerText)", timeout=5000)
        browser.close()
    return text


@pytest.mark.e2e
def test_frames_flow_over_the_websocket_when_live_is_on():
    handle = launch(_app(live=True), block=False, open_inline=False)
    try:
        text = _run(handle.url, "live")
        assert "Live:" in text
    finally:
        handle.stop()


@pytest.mark.e2e
def test_frames_flow_as_snapshots_when_live_is_off():
    handle = launch(_app(), block=False, open_inline=False)
    try:
        text = _run(handle.url, "snapshot")
        assert "Snapshots:" in text
    finally:
        handle.stop()


@pytest.mark.e2e
def test_the_webcam_detection_demo_draws_boxes_from_a_fake_camera():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "examples" / "webcam_detect.py"
    spec = importlib.util.spec_from_file_location("webcam_detect_e2e", path)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    demo.detect = lambda data: [
        {"x": 0.2, "y": 0.2, "w": 0.4, "h": 0.4, "label": "cup", "score": 0.9}
    ]
    handle = launch(
        create_app(session_factory=demo.build_session, live=True), block=False, open_inline=False
    )
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch(args=FAKE_CAMERA)
            page = browser.new_context(permissions=["camera"]).new_page()
            page.goto(handle.url)
            page.get_by_role("button", name="Start camera").click()
            page.wait_for_selector(".ov-box", timeout=20000)
            page.wait_for_function(
                "() => /sent over live/.test(document.body.innerText)", timeout=5000
            )
            browser.close()
    finally:
        handle.stop()
