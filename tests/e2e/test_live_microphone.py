"""A real browser with a fake microphone streams audio to a Microphone handler (ADR-0045, IND-65).

Chromium's fake media device gives ``getUserMedia`` a generated beep, so no hardware is needed.
One run serves the Tier 1 WebSocket and the AudioWorklet (``live=True``); the other has live off
and shows the record-then-upload fallback. Both run under the suite's strict CSP, so the worklet
module load and the socket origin are exercised too.
"""

import pytest

import indah
from indah import Column, Microphone, Text, create_app
from indah.launch import launch
from indah.reactive import Signal
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")

FAKE_MIC = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]


def _app(**kw):
    def factory() -> Session:
        chunks = Signal(0)
        nbytes = Signal(0)
        kind = Signal("none")

        def on_audio(chunk: indah.AudioChunk) -> None:
            chunks.set(chunks.value + 1)
            nbytes.set(nbytes.value + chunk.size)
            kind.set(chunk.content_type)

        mic = Microphone(on_audio, sample_rate=16000)
        status = Text(
            lambda: (
                f"mode={mic.transport.value} chunks={chunks.value} "
                f"bytes={nbytes.value} kind={kind.value}"
            )
        )
        return Session(Column(children=[mic, status]))

    return create_app(session_factory=factory, **kw)


@pytest.mark.e2e
def test_audio_flows_over_the_websocket_when_live_is_on():
    handle = launch(_app(live=True), block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch(args=FAKE_MIC)
            page = browser.new_context(permissions=["microphone"]).new_page()
            page.goto(handle.url)
            page.get_by_role("button", name="Start microphone").click()
            page.wait_for_function(
                "() => /mode=live chunks=([5-9]|[1-9][0-9]+) .*kind=audio\\/pcm/.test("
                "document.body.innerText)",
                timeout=20000,
            )
            # 100 ms chunks of 16 kHz 16-bit mono are 3200 bytes each
            assert "Live:" in page.inner_text("body")
            page.get_by_role("button", name="Stop microphone").click()
            page.wait_for_function("() => /mode=off/.test(document.body.innerText)", timeout=5000)
            browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_a_take_is_uploaded_on_stop_when_live_is_off():
    handle = launch(_app(), block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch(args=FAKE_MIC)
            page = browser.new_context(permissions=["microphone"]).new_page()
            page.goto(handle.url)
            page.get_by_role("button", name="Start microphone").click()
            page.wait_for_function(
                "() => /mode=recording/.test(document.body.innerText)", timeout=10000
            )
            page.wait_for_timeout(1500)
            page.get_by_role("button", name="Stop microphone").click()
            page.wait_for_function(
                "() => /mode=off chunks=1 .*kind=audio\\/wav/.test(document.body.innerText)",
                timeout=10000,
            )
            browser.close()
    finally:
        handle.stop()
