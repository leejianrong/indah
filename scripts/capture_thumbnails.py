"""Capture real screenshots of each demo for the gallery thumbnails.

Launches each example's indah app on a local port, drives it with headless Chromium
(Playwright), lets it render (and nudges the demos that need a click to show output),
then saves a cropped PNG to ``deploy/fly/thumbnails/<slug>.png``. The landing page uses
these as the gallery card thumbnails; run this by hand after a demo's look changes.

Needs the browser + a couple of demo deps:

    uv run playwright install chromium            # once
    uv run --extra e2e --with matplotlib python scripts/capture_thumbnails.py
"""

from __future__ import annotations

import importlib
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
OUT = ROOT / "deploy" / "fly" / "thumbnails"

# A small SVG scene, just visible enough that a detection demo's boxes render over
# actual content in the screenshot rather than a blank/invisible upload.
_DEMO_SCENE_SVG = (
    b"<svg xmlns='http://www.w3.org/2000/svg' width='480' height='300'>"
    b"<rect width='480' height='300' fill='#d8d2c8'/>"
    b"<circle cx='150' cy='160' r='70' fill='#8a8590'/>"
    b"<rect x='280' y='70' width='140' height='95' rx='8' fill='#b5296b'/>"
    b"<circle cx='400' cy='230' r='30' fill='#2e6d62'/>"
    b"</svg>"
)

# slug, example module, optional nudge ("train" / "generate" / "chat" / "upload" / None).
DEMOS = [
    ("chatbot", "chatbot", "chat"),
    ("training-dashboard", "training_dashboard", "train"),
    ("diffusion", "diffusion", "generate"),
    ("poster", "poster", None),
    ("image-classify", "upload_classify", None),
    ("object-detection", "object_detection", "upload"),
    ("charts", "charts", None),
    ("stocks", "stocks", None),
    ("prettymap", "prettymap", None),
]

VIEWPORT = {"width": 900, "height": 640}  # ~14:10, matches the card's aspect ratio


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve(app, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    return server


def _nudge(page, kind: str | None) -> None:
    """Best-effort interaction so a demo shows real output in the shot."""
    try:
        if kind == "train":
            page.get_by_role("button", name="Start training").click(timeout=2000)
            page.wait_for_timeout(2000)  # let a couple of epochs stream in
        elif kind == "generate":
            page.get_by_role("button").first.click(timeout=2000)
            page.wait_for_timeout(1800)
        elif kind == "chat":
            box = page.get_by_placeholder("Type a message, then press Enter or click Send")
            box.fill("What can indah do?", timeout=2000)
            page.get_by_role("button", name="Send").click(timeout=2000)
            page.wait_for_timeout(1500)
        elif kind == "upload":
            page.locator("input[type=file]").set_input_files(
                {"name": "demo.svg", "mimeType": "image/svg+xml", "buffer": _DEMO_SCENE_SVG},
                timeout=2000,
            )
            page.wait_for_timeout(1500)
    except Exception as exc:  # noqa: BLE001 - a nudge is optional, never fatal
        print(f"    (nudge {kind!r} skipped: {exc})")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for slug, module, nudge in DEMOS:
            port = _free_port()
            app = importlib.import_module(module).app
            server = _serve(app, port)
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
            try:
                page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
                page.wait_for_selector(".shell", timeout=8000)
                # Wait until the SSE stream is live and the tree has rendered (the shell
                # shows "connecting..." until then), not just a fixed sleep.
                page.wait_for_function(
                    "!document.body.innerText.toLowerCase().includes('connecting')",
                    timeout=10000,
                )
                page.wait_for_timeout(900)  # settle: first paint + fonts
                _nudge(page, nudge)
                page.wait_for_timeout(300)
                page.evaluate("window.scrollTo(0, 0)")  # every thumb shows the header
                page.wait_for_timeout(150)
                dest = OUT / f"{slug}.png"
                page.screenshot(path=str(dest))  # viewport crop
                print(f"  wrote {dest.relative_to(ROOT)}")
            finally:
                page.close()
                server.should_exit = True
                time.sleep(0.2)
        browser.close()


if __name__ == "__main__":
    main()
