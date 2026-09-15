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


def _find(node: dict, node_type: str) -> dict | None:
    if node.get("type") == node_type:
        return node
    for child in node.get("children", []):
        found = _find(child, node_type)
        if found is not None:
            return found
    return None


@pytest.mark.e2e
async def test_streaming_demo_streams_tokens_incrementally_and_stays_responsive():
    handle = launch(block=False, open_inline=False)
    try:
        async with httpx.AsyncClient(base_url=handle.url, timeout=15.0) as client:
            assert (await client.get("/health")).status_code == 200

            async with client.stream("GET", "/api/stream") as response:
                lines = response.aiter_lines()

                init = await _next_data(lines)
                assert init["type"] == "init"
                chat_node = _find(init["root"], "chat")
                button_node = _find(init["root"], "button")  # first button = Generate
                slider_node = _find(init["root"], "slider")
                assert chat_node is not None and button_node is not None

                # Click Generate: the assistant reply must arrive as many small
                # `pending` patches (token by token), not a single final dump.
                posted = await client.post(
                    "/api/event", json={"component": button_node["id"], "event": "click"}
                )
                assert posted.status_code == 200

                pending_patches = 0
                last_pending = ""
                slider_patched = False
                # Read a batch of frames while generation runs; drive a slider event
                # in the middle to prove the UI stays responsive during streaming.
                for i in range(60):
                    msg = await _next_data(lines)
                    if msg["type"] != "patch":
                        continue
                    for change in msg["changes"]:
                        props = change.get("props") or {}
                        if change["target"] == chat_node["id"] and "pending" in props:
                            pending_patches += 1
                            last_pending = props["pending"]
                        if change["target"] == slider_node["id"] and "props" in change:
                            slider_patched = True
                    if i == 2:
                        # An unrelated event mid-stream is accepted and handled.
                        await client.post(
                            "/api/event",
                            json={
                                "component": slider_node["id"],
                                "event": "input",
                                "payload": {"value": 7},
                            },
                        )
                    if pending_patches >= 3 and slider_patched:
                        break

                assert pending_patches >= 3  # incremental: token by token, not one dump
                assert last_pending.strip()  # actual text arrived
                assert slider_patched  # the rest of the UI stayed live while streaming
    finally:
        handle.stop()


@pytest.mark.e2e
async def test_registered_custom_component_renders_and_responds():
    """A registered custom component (the demo's colour picker) ships its render
    spec in the init tree and round-trips an event over the real server (R7)."""
    handle = launch(block=False, open_inline=False)
    try:
        async with httpx.AsyncClient(base_url=handle.url, timeout=15.0) as client:
            async with client.stream("GET", "/api/stream") as response:
                lines = response.aiter_lines()
                init = await _next_data(lines)
                picker = _find(init["root"], "colorpicker")
                # It rendered: the node carries its declarative render spec.
                assert picker is not None
                assert picker["props"]["_spec"]["tag"] == "input"

                # It responds: an input event patches the picker's bound value back.
                await client.post(
                    "/api/event",
                    json={
                        "component": picker["id"],
                        "event": "input",
                        "payload": {"value": "#00ff00"},
                    },
                )
                patched = None
                for _ in range(20):
                    msg = await _next_data(lines)
                    if msg["type"] != "patch":
                        continue
                    for change in msg["changes"]:
                        if (
                            change["target"] == picker["id"]
                            and change.get("props", {}).get("value") == "#00ff00"
                        ):
                            patched = change
                    if patched:
                        break
                assert patched is not None  # the custom event round-tripped
    finally:
        handle.stop()
