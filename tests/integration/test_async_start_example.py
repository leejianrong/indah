"""The async-start example (examples/async_start.py): a skeleton, then the real page."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "async_start.py"
spec = importlib.util.spec_from_file_location("async_start_example", _EXAMPLE)
ex = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ex
spec.loader.exec_module(ex)


def _types(node: dict) -> set[str]:
    found = {node["type"]}
    for child in node.get("children", []):
        found |= _types(child)
    return found


@pytest.mark.integration
async def test_a_slow_load_starts_on_a_skeleton_then_shows_the_stats():
    ui = ex.build_ui(delay=0.3, timeout=0.05)
    store = ui.state.store
    handle = await store.aget_or_create("t")
    assert "skeleton" in _types(handle.session.snapshot())
    await asyncio.sleep(0.5)
    tree = handle.session.snapshot()
    assert "skeleton" not in _types(tree)
    assert "stat" in _types(tree)
    assert [m["type"] for _, m in handle.hub.history()] == ["init"]


@pytest.mark.integration
async def test_a_fast_load_has_the_stats_in_the_first_snapshot():
    ui = ex.build_ui(delay=0.0, timeout=1.0)
    handle = await ui.state.store.aget_or_create("t")
    assert "stat" in _types(handle.session.snapshot())
    assert handle.hub.current_offset == 0
