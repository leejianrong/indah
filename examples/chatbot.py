"""A streaming LLM chatbot in indah, runnable end to end in a Colab cell.

The example is deliberately in two layers, kept apart (ADR-0009):

- ``chat_stream`` is plain Python with no indah imports. It loads a small
  instruct model with transformers and yields the reply token by token. A real
  app drops its own model behind the same shape; on graduation the function lifts
  out of indah unchanged.
- the indah layer (``build_session``) wires that stream into a UI: a message box,
  a Send button, and a ``Chat`` of role bubbles whose in-flight reply streams into
  a live pending bubble (ADR-0016).

Generation runs on a background thread and is pulled token by token with
``asyncio.to_thread``, so the event loop is never blocked and the rest of the UI
stays live while the model generates - the same non-blocking guarantee the demo's
mock LLM shows (R3, ADR-0011).

Run it::

    python examples/chatbot.py --mock          # no model, no GPU: canned replies
    python examples/chatbot.py                  # Qwen2.5-0.5B-Instruct (downloads)
    python examples/chatbot.py --model unsloth/Llama-3.2-1B-Instruct

``--mock`` needs only indah, so the wiring is runnable and smoke-checkable without
transformers, torch, or a GPU. The real path needs the user's own deps
(``pip install transformers accelerate`` plus torch); they are never indah's, so
indah stays pure-Python with no Node at install or runtime.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator

import indah
from indah import Button, Chat, Column, Session, Signal, Text, TextInput

DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"

# A message is a plain ``{"role": ..., "content": ...}`` dict, the shape
# transformers' chat templates expect. Kept as plain data so the domain layer
# never depends on indah.
Message = dict[str, str]


# --- the model layer: plain Python, no indah imports (ADR-0009) --------------


def load_model(model_name: str = DEFAULT_MODEL):
    """Load a small instruct model + tokenizer. Plain transformers.

    ``device_map="auto"`` puts the model on the GPU when Colab has a T4 and on the
    CPU otherwise; both work for a sub-1B model. The first call downloads weights.
    """
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype="auto", device_map="auto")
    return tokenizer, model


async def chat_stream(
    tokenizer, model, messages: list[Message], *, max_new_tokens: int = 1024
) -> AsyncIterator[str]:
    """Yield an assistant reply token by token for a chat ``messages`` list.

    ``max_new_tokens`` caps how long a single reply may be. It defaults high (1024)
    and is exposed through ``build_session``/``--max-new-tokens`` so a reply is not
    truncated mid-sentence (KAN-1401). This is the generation cap only, distinct
    from the model's context window -- the small instruct models here have a large
    context (32k+), so 1024 new tokens never hits it.

    transformers' ``TextIteratorStreamer`` runs ``model.generate`` on a background
    thread and exposes a *blocking* iterator of tokens. We pull each token off it
    with ``asyncio.to_thread`` so the asyncio event loop is free between tokens and
    indah's UI never freezes while the model generates. No indah imports: this is
    the portable, graduation-clean half of the app.
    """
    import threading

    from transformers import TextIteratorStreamer

    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)

    def generate() -> None:
        try:
            model.generate(
                **inputs,
                streamer=streamer,
                max_new_tokens=max_new_tokens,
                do_sample=True,
                temperature=0.7,
                top_p=0.9,
            )
        finally:
            # Signal end-of-stream even if generate() raised, so the consumer
            # below is never left blocked forever on a dead generation thread.
            streamer.end()

    threading.Thread(target=generate, daemon=True).start()

    done = object()
    while True:
        token = await asyncio.to_thread(next, streamer, done)
        if token is done:
            break
        yield token


async def mock_chat_stream(
    tokenizer, model, messages: list[Message], *, max_new_tokens: int = 1024
) -> AsyncIterator[str]:
    """A model-free stand-in with the same shape as ``chat_stream`` (for --mock).

    Lets the whole app - wiring, streaming, transcript - run and be smoke-tested
    with no transformers/torch and no GPU. It honours ``max_new_tokens`` (one word
    ~ one token here) so the same cap that bounds a real reply is exercised.
    """
    last = messages[-1]["content"].strip() if messages else ""
    reply = (f"You said: '{last}'. " if last else "") + (
        "This is a mock reply, streamed token by token. Pass a real model to "
        "chat_stream() to swap me out - the wiring does not change."
    )
    for word in reply.split(" ")[:max_new_tokens]:
        await asyncio.sleep(0.05)
        yield word + " "


# --- the indah layer: wire the stream into a UI ------------------------------

# Coalesce a few tokens per SSE frame. Each StreamText.feed() emits one frame, and
# today every frame carries ~8 KB of proxy-flush padding (ADR-0002), so batching a
# handful of tokens per frame cuts the wire overhead several-fold with no
# perceptible loss of the streaming feel. A framework-level coalescing/debounce fix
# is tracked as a follow-up (see docs/QUESTIONS.md); this is the userland
# mitigation until then.
COALESCE_TOKENS = 3


async def _coalesced(
    stream: AsyncIterator[str], every: int = COALESCE_TOKENS
) -> AsyncIterator[str]:
    """Group ``every`` tokens into one chunk (with a final partial flush)."""
    buffer: list[str] = []
    async for token in stream:
        buffer.append(token)
        if len(buffer) >= every:
            yield "".join(buffer)
            buffer = []
    if buffer:
        yield "".join(buffer)


def build_session(stream_fn, tokenizer=None, model=None, *, max_new_tokens: int = 1024) -> Session:
    """Build the chat UI around a ``stream_fn(tokenizer, model, messages)``.

    The conversation is a ``Signal[list]`` of ``{"role","content"}`` messages
    rendered as ``Chat`` bubbles (ADR-0016); the in-flight reply streams token by
    token into a ``pending`` signal so it shows as a live, growing assistant bubble,
    then commits to the list when done. Growing the transcript is an ordinary prop
    change over the existing patch op - no dynamic-children protocol op needed.

    ``max_new_tokens`` is threaded into every ``stream_fn`` call so replies are not
    capped at the low library default and cut off mid-sentence (KAN-1401).
    """
    prompt: Signal[str] = Signal("")
    status: Signal[str] = Signal("Ask me something.")
    busy: Signal[bool] = Signal(False)
    messages: Signal[list] = Signal([])
    pending: Signal[str] = Signal("")

    async def on_send() -> None:
        question = prompt.value.strip()
        if not question or busy.value:
            return
        busy.set(True)
        status.set("Generating...")
        prompt.set("")  # clear the box for the next message
        history: list[Message] = messages.value + [{"role": "user", "content": question}]
        messages.set(history)
        pending.set("")

        parts: list[str] = []
        stream = stream_fn(tokenizer, model, list(history), max_new_tokens=max_new_tokens)
        async for chunk in _coalesced(stream):
            pending.set(pending.value + chunk)
            parts.append(chunk)

        messages.set(messages.value + [{"role": "assistant", "content": "".join(parts)}])
        pending.set("")
        busy.set(False)
        status.set("Ask me something.")

    page = Column(
        children=[
            Text("indah chatbot: replies stream in token by token as message bubbles"),
            Chat(messages, pending=pending, label="Conversation"),
            TextInput(
                prompt,
                placeholder="Type a message, then press Enter or click Send",
                label="Message",
                on_submit=on_send,
            ),
            Button("Send", on_click=on_send),
            Text(status),
        ]
    )
    return Session(page)


def main() -> None:
    parser = argparse.ArgumentParser(description="An indah streaming chatbot.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="canned replies with no model/GPU (needs only indah)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="a Hugging Face model id")
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=1024,
        help="cap on a single reply's length (raise if replies still cut off)",
    )
    args = parser.parse_args()

    if args.mock:
        session = build_session(mock_chat_stream, max_new_tokens=args.max_new_tokens)
    else:
        print(f"Loading {args.model} (the first run downloads weights)...", flush=True)
        tokenizer, model = load_model(args.model)
        session = build_session(chat_stream, tokenizer, model, max_new_tokens=args.max_new_tokens)

    indah.launch(indah.create_app(session=session))


# Module-level ASGI app for hosting (HF Spaces / uvicorn, ADR-0023): the mock
# chatbot, so a hosted demo needs no model weights or GPU. `python examples/chatbot.py`
# (main) still runs the real model by default; pass --mock for the same as here.
app = indah.create_app(session_factory=lambda: build_session(mock_chat_stream))


if __name__ == "__main__":
    main()
