"""The diffusion example (examples/diffusion.py) stays runnable.

Smoke-checks that Generate replays one real (pre-recorded) frame per step, with
progress, over the session dispatch + hub path, for each pre-baked prompt/direction.
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
def test_frames_are_real_data_and_cover_every_prompt_and_direction():
    example = _load_example()
    for slug, _prompt, _seed in example.PROMPTS:
        for process, _label in example.PROCESSES:
            frames = example._frames_for(slug, process)
            assert len(frames) > 1  # more than a single static frame
            assert all(f.startswith("data:image/webp;base64,") for f in frames)
            # The sequence progresses overall (not every consecutive pair need differ --
            # two late, near-converged denoising steps can compress to the same bytes).
            assert frames[0] != frames[-1]


@pytest.mark.integration
async def test_generate_streams_a_frame_per_step():
    example = _load_example()
    session = example.build()
    hub = Hub()
    session.bind_hub(hub)

    button = next(c for c in session._by_id.values() if c.type == "button")
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
    expected = example._frames_for(example.PROMPTS[0][0], example.PROCESSES[0][0])
    # The `image` signal starts already at expected[0] (build()'s idle preview), and the
    # reactive diff engine only emits a patch when a set() actually changes the value -- so
    # simulate that same dedup-against-the-running-value to get the real expected stream.
    deduped, previous = [], expected[0]
    for f in expected[1:]:
        if f != previous:
            deduped.append(f)
        previous = f
    assert frames == deduped
    assert frames[-1] == expected[-1]  # settles on the real, final frame
