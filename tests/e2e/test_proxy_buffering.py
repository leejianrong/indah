"""E2E: reproduce Colab's window-buffering proxy and prove the flush-pad fix.

Colab's front-end proxy forwards the upstream response in fixed-size windows,
holding a small SSE frame until its window fills. That left the shell stuck - first
on "connecting..." (no bytes at all), then, once a lead-in flush was added, "live"
but empty because the `init` frame after it sat in a fresh unfilled window.

We reproduce that here with a local TCP proxy that buffers the server->client
direction in >= WINDOW-byte windows (it never switches to pass-through, exactly
like Colab), put it in front of a real launched app, and drive the shell through it
in a real browser. The app renders and patches only because every SSE frame is
followed by comment padding that fills the window and forces a flush
(``indah.app._SSE_FLUSH_PAD``). A negative test disables that padding and shows the
same proxy stalls - so the test proves the fix, not luck.

Heavy layer: marked e2e, excluded from the fast gate. The browser case needs the
e2e extra installed (see tests/e2e/README.md). Run: make test-e2e.
"""

import asyncio
import threading

import httpx
import pytest

import indah.app as app_mod
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync.sync_playwright
expect = playwright_sync.expect

WINDOW = 8192  # bytes the proxy buffers before it releases a window (Colab-like)


class BufferingProxy:
    """A TCP reverse proxy that windows the upstream->client direction.

    It forwards client->upstream bytes at once (POST events are unaffected) and,
    for the SSE stream connection only, holds server->client bytes until it has >=
    ``window`` of them, then releases exactly that window and keeps buffering the
    remainder - so a small trailing SSE frame is never delivered on its own.
    Non-stream requests (the index HTML, favicon) pass through untouched, matching
    what actually matters: Colab breaks the never-ending stream, not finite
    responses. Runs its asyncio server on a background thread so a synchronous test
    can use it.
    """

    def __init__(self, upstream_host: str, upstream_port: int, window: int = WINDOW) -> None:
        self._upstream = (upstream_host, upstream_port)
        self._window = window
        self.port: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    async def _buffered(self, reader, writer) -> None:
        buf = bytearray()
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    if buf:  # flush the tail when the upstream closes the response
                        writer.write(bytes(buf))
                        await writer.drain()
                    break
                buf += chunk
                while len(buf) >= self._window:
                    writer.write(bytes(buf[: self._window]))
                    await writer.drain()
                    del buf[: self._window]
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    async def _immediate(self, reader, writer) -> None:
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    async def _handle(self, client_reader, client_writer) -> None:
        # Peek the request line so only the SSE stream connection is window-buffered;
        # the index HTML and other finite responses pass through untouched.
        head = await client_reader.read(4096)
        is_stream = b"/api/stream" in head.split(b"\r\n", 1)[0]
        up_reader, up_writer = await asyncio.open_connection(*self._upstream)
        up_writer.write(head)
        await up_writer.drain()
        upstream_to_client = self._buffered if is_stream else self._immediate
        await asyncio.gather(
            self._immediate(client_reader, up_writer),  # rest of client -> upstream
            upstream_to_client(up_reader, client_writer),
        )

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())
        self._loop.run_forever()
        self._loop.close()

    async def _serve(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        self._ready.set()

    async def _shutdown(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def start(self) -> "BufferingProxy":
        self._thread.start()
        assert self._ready.wait(5), "buffering proxy did not start"
        return self

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), loop).result(timeout=5)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        self._thread.join(timeout=5)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _first_data_line(url: str, timeout: float) -> str | None:
    """The first SSE ``data:`` line read from ``url``, or None if none arrives in
    ``timeout`` (the proxy held it)."""
    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("GET", f"{url}/api/stream") as resp:
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        return line
    except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError):
        return None
    return None


@pytest.mark.e2e
def test_shell_renders_and_patches_through_a_window_buffering_proxy():
    """The demo renders and a slider patches through a Colab-style buffering proxy -
    proving the per-frame flush padding pushes each SSE frame out of the window."""
    handle = launch(block=False, open_inline=False)
    proxy = BufferingProxy("127.0.0.1", handle.port).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(proxy.url, wait_until="domcontentloaded")
                # The init frame made it through the buffering proxy: the tree rendered.
                slider = page.locator("input[type=range]").first
                expect(slider).to_be_visible()
                # A live patch also flushes: drag the slider, the label updates.
                slider.evaluate(
                    "el => { el.value = '7';"
                    " el.dispatchEvent(new Event('input', { bubbles: true })); }"
                )
                expect(page.locator("div.text", has_text="2 x 7 = 14")).to_be_visible()
            finally:
                browser.close()
    finally:
        proxy.stop()
        handle.stop()


@pytest.mark.e2e
def test_without_flush_padding_the_same_proxy_stalls():
    """Guard proof: disable the flush padding and the identical proxy holds the
    init - no data arrives - so it is the padding, not chance, that makes it work."""
    original = app_mod._SSE_FLUSH_PAD
    app_mod._SSE_FLUSH_PAD = ""  # simulate the pre-fix build
    handle = launch(block=False, open_inline=False)
    proxy = BufferingProxy("127.0.0.1", handle.port).start()
    try:
        assert _first_data_line(proxy.url, timeout=3.0) is None  # stalled
    finally:
        proxy.stop()
        handle.stop()
        app_mod._SSE_FLUSH_PAD = original
