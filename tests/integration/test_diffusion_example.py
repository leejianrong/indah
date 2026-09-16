"""The diffusion example (examples/diffusion.py) stays runnable.

Smoke-checks that Generate streams one image frame per step (with progress) over the
session dispatch + hub path, and that a prompt renders deterministically.
"""

import importlib.util
from pathlib import Path

import pytest

from indah.transport import Hub

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "diffusion.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("diffusion_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
def test_frames_are_deterministic_per_prompt_and_denoise():
    import random

    example = _load_example()
    a = example._frame("a cat", 0.5, random.Random(0))
    b = example._frame("a cat", 0.5, random.Random(0))
    assert a == b and a.startswith("data:image/svg+xml,")  # same prompt+seed -> same frame


@pytest.mark.integration
async def test_generate_streams_a_frame_per_step():
    example = _load_example()
    session = example.build()
    hub = Hub()
    session.bind_hub(hub)

    # Find the prompt input and the Generate button; shrink steps for a fast run.
    button = next(c for c in session._by_id.values() if c.type == "button")
    slider = next(c for c in session._by_id.values() if c.type == "slider")
    session.dispatch(slider.id, "input", {"value": 5})  # 5 steps

    result = session.dispatch(button.id, "click", {})
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    image = next(c for c in session._by_id.values() if c.type == "image")
    frames = [
        change["props"]["src"]
        for _, msg in hub.history()
        for change in msg.get("changes", [])
        if change.get("target") == image.id and "src" in change.get("props", {})
    ]
    assert len(frames) == 5  # one image frame streamed per step
    assert all(f.startswith("data:image/svg+xml,") for f in frames)
