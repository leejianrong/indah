"""End-to-end: boot a real uvicorn server via launch() and drive it over TCP.

This is the heavy layer (real server, real threads, real SSE) and is excluded
from the fast pre-push/CI gate. It stops short of a browser; the browser and the
Colab/Runpod proxy smoke check are added as the shell matures (see docs/SLICES.md).

Run with:  make test-e2e
"""

import asyncio
import json

import httpx
import pytest

from indah.launch import launch


async def _next_data(lines, timeout: float = 5.0) -> dict:
    while True:
        line = await asyncio.wait_for(lines.__anext__(), timeout)
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())


@pytest.mark.e2e
async def test_two_slider_demo_patches_only_the_label_over_real_tcp():
    handle = launch(block=False, open_inline=False)
    try:
        async with httpx.AsyncClient(base_url=handle.url, timeout=10.0) as client:
            assert (await client.get("/health")).status_code == 200

            async with client.stream("GET", "/api/stream") as response:
                lines = response.aiter_lines()

                init = await _next_data(lines)
                assert init["type"] == "init"
                root = init["root"]
                assert root["type"] == "column"
                # column -> [slider a (n1), slider b (n2), text (n3)]
                assert root["children"][2]["props"]["text"] == "a + b = 5"

                posted = await client.post(
                    "/api/event",
                    json={"component": "n1", "event": "input", "payload": {"value": 8}},
                )
                assert posted.status_code == 200

                patch = await _next_data(lines)
                assert patch["type"] == "patch"
                changes = patch["changes"]
                targets = {c["target"] for c in changes}
                assert "n2" not in targets  # the other slider is never touched
                label = next(c for c in changes if c["target"] == "n3")
                assert label["props"] == {"text": "a + b = 11"}
    finally:
        handle.stop()
