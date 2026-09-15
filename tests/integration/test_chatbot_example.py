"""The flagship chatbot example (examples/chatbot.py) stays runnable.

Drives the ``--mock`` wiring - no transformers/torch, no GPU - through the same
session + hub path a click takes, so the example is smoke-checked in CI. The real
model path (``chat_stream``) is not exercised here; it needs the user's own heavy
deps and is proven by hand in Colab (the R2 smoke check).
"""

import importlib.util
from pathlib import Path

import pytest

from indah.transport import Hub

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "chatbot.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("chatbot_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _appends(hub: Hub) -> list[str]:
    deltas = []
    for _, msg in hub.history():
        if msg.get("type") != "patch":
            continue
        for change in msg.get("changes", []):
            if "append" in change:
                deltas.append(change["append"]["text"])
    return deltas


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


@pytest.mark.integration
async def test_mock_chatbot_streams_a_transcript_and_clears_the_prompt():
    chatbot = _load_example()
    session = chatbot.build_session(chatbot.mock_chat_stream)
    hub = Hub()
    session.bind_hub(hub)

    textinput = _node(session, "textinput")
    button = _node(session, "button")
    transcript = _node(session, "streamtext")

    # Type a message, then click Send.
    session.dispatch(textinput.id, "input", {"value": "hello there"})
    result = session.dispatch(button.id, "click", {})
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    # The transcript holds the user's turn and the streamed assistant reply.
    assert transcript.text.startswith("You: hello there\nAssistant: ")
    assert "hello there" in transcript.text  # the mock echoes the question
    # It grew via append patches (not one final dump), and the prompt box cleared.
    assert len(_appends(hub)) > 1
    assert textinput._value.value == ""


@pytest.mark.integration
async def test_mock_chatbot_is_guarded_against_an_empty_message():
    chatbot = _load_example()
    session = chatbot.build_session(chatbot.mock_chat_stream)
    hub = Hub()
    session.bind_hub(hub)

    button = _node(session, "button")
    result = session.dispatch(button.id, "click", {})  # nothing typed
    assert result is not None and result.coro is not None
    await result.coro

    # An empty prompt produces no transcript and no patches.
    assert _node(session, "streamtext").text == ""
    assert _appends(hub) == []
