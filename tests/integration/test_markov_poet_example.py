"""The Markov poet example (examples/markov_poet.py) builds and streams a poem on Generate."""

import importlib.util
import sys
from pathlib import Path

import pytest

from indah.transport import Hub

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "markov_poet.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("markov_poet_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


@pytest.mark.integration
def test_the_poem_opens_filled_not_blank():
    example = _load_example()
    session = example.build()
    assert len(_node(session, "streamtext").text.split()) >= 20


# Seeds whose poem is short: with ``finish_sentence`` a poem that finds no full stop within the
# extra words is cut back to the last one, so the length slider is a target, not a floor (IND-234).
# 38 gives 22 words, 140 gives 21 tokens; 7 is an ordinary one.
@pytest.mark.integration
@pytest.mark.parametrize("seed", [7, 38, 140, 241])
async def test_generate_streams_the_poem_word_by_word(monkeypatch, seed):
    import random
    from types import SimpleNamespace

    example = _load_example()
    monkeypatch.setattr(example, "WORD_DELAY", 0)
    monkeypatch.setattr(
        example,
        "random",
        SimpleNamespace(Random=lambda s=None: random.Random(seed if s is None else s)),
    )
    session = example.build()
    hub = Hub()
    session.bind_hub(hub)
    stream = _node(session, "streamtext")
    generate = next(c for c in session._by_id.values() if c.type == "button")

    result = session.dispatch(generate.id, "click", {})
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    appended = [
        change["append"]["text"]
        for _, msg in hub.history()
        for change in msg.get("changes", [])
        if "append" in change and "text" in change["append"]
    ]
    assert len(appended) > 10  # one append per token, not one big patch
    assert "".join(appended).strip() == stream.text.strip()
    assert len(stream.text.split()) >= 15
    assert stream.text.strip().rstrip("\"')").endswith((".", "!", "?"))


@pytest.mark.integration
def test_the_fixed_seed_gives_the_same_poem_each_time(monkeypatch):
    import asyncio

    example = _load_example()
    monkeypatch.setattr(example, "WORD_DELAY", 0)

    def run() -> str:
        session = example.build()
        session.bind_hub(Hub())
        switch = _node(session, "switch")
        session.dispatch(switch.id, "change", {"value": True})
        button = _node(session, "button")
        asyncio.run(session.dispatch(button.id, "click", {}).coro)
        return _node(session, "streamtext").text

    assert run() == run()
