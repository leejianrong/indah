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


def _pending_patches(hub: Hub) -> list[str]:
    """The successive ``pending`` values patched to the Chat -- the live bubble."""
    out = []
    for _, msg in hub.history():
        if msg.get("type") != "patch":
            continue
        for change in msg.get("changes", []):
            props = change.get("props") or {}
            if "pending" in props:
                out.append(props["pending"])
    return out


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


def _messages(chat):
    return chat.reactive_props()["messages"]()


@pytest.mark.integration
async def test_mock_chatbot_streams_into_bubbles_and_clears_the_prompt():
    chatbot = _load_example()
    session = chatbot.build_session(chatbot.mock_chat_stream)
    hub = Hub()
    session.bind_hub(hub)

    textinput = _node(session, "textinput")
    button = _node(session, "button")
    chat = _node(session, "chat")

    # Type a message, then click Send.
    session.dispatch(textinput.id, "input", {"value": "hello there"})
    result = session.dispatch(button.id, "click", {})
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    # The transcript holds the user's turn and the streamed assistant reply.
    messages = _messages(chat)
    assert messages[0] == {"role": "user", "content": "hello there"}
    assert messages[1]["role"] == "assistant"
    assert "hello there" in messages[1]["content"]  # the mock echoes the question
    # It streamed live (the pending bubble was patched more than once, then cleared),
    # and the prompt box cleared.
    assert len(_pending_patches(hub)) > 1
    assert chat.reactive_props()["pending"]() == ""
    assert textinput._value.value == ""


@pytest.mark.integration
async def test_build_session_threads_max_new_tokens_into_the_stream():
    """The reply cap (KAN-1401) reaches the stream: build_session must pass
    max_new_tokens through to stream_fn, not drop it (which capped replies at the
    library default and cut them off). The mock honours the cap, so a small value
    yields a short reply."""
    chatbot = _load_example()
    session = chatbot.build_session(chatbot.mock_chat_stream, max_new_tokens=3)
    hub = Hub()
    session.bind_hub(hub)

    textinput = _node(session, "textinput")
    button = _node(session, "button")
    chat = _node(session, "chat")

    session.dispatch(textinput.id, "input", {"value": "hi"})
    result = session.dispatch(button.id, "click", {})
    await result.coro

    reply = _messages(chat)[1]["content"]
    assert len(reply.split()) == 3  # capped at 3 tokens, not the full mock reply


@pytest.mark.integration
async def test_mock_chatbot_is_guarded_against_an_empty_message():
    chatbot = _load_example()
    session = chatbot.build_session(chatbot.mock_chat_stream)
    hub = Hub()
    session.bind_hub(hub)

    button = _node(session, "button")
    chat = _node(session, "chat")
    result = session.dispatch(button.id, "click", {})  # nothing typed
    assert result is not None and result.coro is not None
    await result.coro

    # An empty prompt produces no messages and no patches.
    assert _messages(chat) == []
    assert _pending_patches(hub) == []
