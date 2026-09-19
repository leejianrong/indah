"""The diffusion example (examples/diffusion.py) stays runnable.

Smoke-checks the pre-recorded frames for every prompt/direction, and that Play,
Prev, and Next all move through the real frame sequence over the session dispatch
path. Play is an async handler, so its incremental frames arrive over the bound
hub as it runs; Prev/Next/the prompt Select are synchronous, so their one-shot
result comes back directly in the dispatch's own ``changes``.
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


def _label(button) -> str:
    return button.reactive_props()["label"]()


def _buttons(session) -> dict[str, object]:
    buttons = [c for c in session._by_id.values() if c.type == "button"]
    return {_label(b): b for b in buttons}


def _image_src(result, image_id) -> str:
    return next(
        c["props"]["src"] for c in result.changes if c["target"] == image_id and "src" in c["props"]
    )


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
async def test_play_streams_a_frame_per_step_over_the_hub():
    example = _load_example()
    session = example.build()
    hub = Hub()
    session.bind_hub(hub)

    play_button = _buttons(session)["Play"]
    result = session.dispatch(play_button.id, "click", {})
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


@pytest.mark.integration
def test_next_and_prev_step_one_frame_at_a_time():
    example = _load_example()
    session = example.build()
    buttons = _buttons(session)
    image = next(c for c in session._by_id.values() if c.type == "image")
    expected = example._frames_for(example.PROMPTS[0][0], example.PROCESSES[0][0])

    r1 = session.dispatch(buttons["Next"].id, "click", {})
    r2 = session.dispatch(buttons["Next"].id, "click", {})
    r3 = session.dispatch(buttons["Prev"].id, "click", {})

    assert [_image_src(r, image.id) for r in (r1, r2, r3)] == [
        expected[1],
        expected[2],
        expected[1],
    ]


@pytest.mark.integration
def test_switching_prompt_resets_to_frame_zero():
    example = _load_example()
    session = example.build()
    image = next(c for c in session._by_id.values() if c.type == "image")
    select = next(
        c
        for c in session._by_id.values()
        if c.type == "select" and c.static_props()["label"] == "Prompt"
    )

    result = session.dispatch(select.id, "change", {"value": example.PROMPTS[1][0]})

    expected0 = example._frames_for(example.PROMPTS[1][0], example.PROCESSES[0][0])[0]
    assert _image_src(result, image.id) == expected0
