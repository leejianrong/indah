# Build a chatbot

This walkthrough builds a streaming LLM chatbot that runs end to end in a single
Colab runtime: a small instruct model loaded with
[transformers](https://huggingface.co/docs/transformers), streaming its reply
token by token into an indah page. No Node, no separate server, no GPU required
(though a free T4 makes it snappier).

This walkthrough has its own notebook,
[`examples/chatbot_colab.ipynb`](https://github.com/leejianrong/indah/blob/main/examples/chatbot_colab.ipynb)
(open it directly in Colab - no setup) - a step-by-step build of the transformers
model layer. It's different from the **Streaming chatbot** in the
[gallery](gallery.md#notebook-native): that one is a ready-to-click demo (mock reply
or bring-your-own-key via OpenRouter); this guide builds the real-model version from
scratch. The source behind both lives in
[`examples/chatbot.py`](https://github.com/leejianrong/indah/blob/main/examples/chatbot.py).

## The two layers

indah keeps domain logic in plain functions it merely calls, apart from the UI
(ADR-0009). This example is built that way:

- **The model layer** yields tokens and imports nothing from indah. A real app
  drops its own model in behind the same shape, and the function lifts out
  unchanged when the prototype graduates to a production backend.
- **The indah layer** wires that stream of tokens into a live page.

## Install

indah is pure-Python to install and run. `transformers`, `accelerate`, and
`torch` are *your* dependencies, not indah's - which is what keeps indah light.
Colab already ships `torch`.

```bash
pip install indah transformers accelerate
```

## The model layer (no indah imports)

`chat_stream` yields the assistant's reply token by token. transformers'
`TextIteratorStreamer` runs `model.generate` on a background thread and exposes a
blocking iterator; pulling each token off it with `asyncio.to_thread` keeps the
asyncio event loop free, so indah's UI never freezes while the model generates.

```python
import asyncio
import threading

from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"

tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype="auto", device_map="auto")


async def chat_stream(messages, *, max_new_tokens=512):
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)

    def generate():
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
            streamer.end()  # unblock the consumer even if generate() raised

    threading.Thread(target=generate, daemon=True).start()

    done = object()
    while True:
        token = await asyncio.to_thread(next, streamer, done)
        if token is done:
            break
        yield token
```

### Choosing a model

Any instruct model with a chat template works. Two that fit free Colab:

=== "Qwen2.5-0.5B-Instruct (default)"

    Small (~1 GB), fast first token, Apache-2.0. Snappy on a T4 and usable on CPU.

    ```python
    MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
    ```

=== "Llama-3.2-1B-Instruct"

    Larger and a step up in quality; still comfortable on a free T4.

    ```python
    MODEL = "unsloth/Llama-3.2-1B-Instruct"
    ```

## The indah app

The whole conversation lives in **one `StreamText`**. Each turn is fed in as
*append* deltas - the user's line, then the assistant's tokens as they arrive - so
the transcript grows at O(token) cost on the wire and re-renders correctly if the
proxy drops the stream and the browser reconnects (ADR-0011).

```python
import indah
from indah import Button, Column, Session, Signal, StreamText, Text, TextInput

COALESCE_TOKENS = 3


async def coalesced(stream, every=COALESCE_TOKENS):
    buffer = []
    async for token in stream:
        buffer.append(token)
        if len(buffer) >= every:
            yield "".join(buffer)
            buffer = []
    if buffer:
        yield "".join(buffer)


prompt = Signal("")
status = Signal("Ask me something.")
busy = Signal(False)
transcript = StreamText(label="Conversation")
messages = []  # plain [{"role", "content"}] chat history


async def on_send():
    question = prompt.value.strip()
    if not question or busy.value:
        return
    busy.set(True)
    status.set("Generating...")
    prompt.set("")
    messages.append({"role": "user", "content": question})
    transcript.feed(f"You: {question}\n")
    transcript.feed("Assistant: ")

    parts = []
    async for chunk in coalesced(chat_stream(messages)):
        transcript.feed(chunk)
        parts.append(chunk)

    transcript.feed("\n\n")
    messages.append({"role": "assistant", "content": "".join(parts)})
    busy.set(False)
    status.set("Ask me something.")


page = Column(
    children=[
        Text("indah chatbot"),
        TextInput(prompt, placeholder="Type a message, then click Send", label="Message"),
        Button("Send", on_click=on_send),
        Text(status),
        transcript,
    ]
)

handle = indah.launch(indah.create_app(session=Session(page)))
```

`on_send` is an `async` handler, so indah runs it as a background task and the
`POST` returns immediately; generation runs on its own worker thread. Between the
two, the page stays fully responsive while the model works.

!!! note "Why coalesce tokens?"

    Each `feed()` is one SSE frame, and today every frame carries a small padding
    block so Colab's proxy flushes it immediately (ADR-0002). Batching a few tokens
    per frame keeps the wire light without any visible loss of the streaming feel.
    A framework-level version of this is a tracked follow-up.

## Run it without a model

[`examples/chatbot.py`](https://github.com/leejianrong/indah/blob/main/examples/chatbot.py)
has a `--mock` mode - canned replies with the same streaming shape, needing only
indah - so you can test the wiring with no model, no downloads, and no GPU. Save it
locally and run `python chatbot.py --mock`, or pick `--model unsloth/Llama-3.2-1B-Instruct`
for a bigger model than the default.

## Next

- [Components](components.md) - the full starter set.
- [Protocol](protocol.md) - the wire contract behind the streaming.
