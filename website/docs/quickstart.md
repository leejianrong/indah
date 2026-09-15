# Quickstart

## Install

indah is pure-Python to install and run - no Node, npm, or bun, because the
frontend ships pre-built inside the wheel.

```bash
pip install indah
```

Prefer to run from a clone:

```bash
git clone https://github.com/leejianrong/indah && cd indah
uv sync --extra dev
make demo            # prints a URL; binds the first free port from 8000
```

## Your first app

An app is a tree of components bound to reactive signals. Mutate a signal and only
the components that read it update.

```python
import indah
from indah import Signal, computed, Column, Slider, Text, Session

a, b = Signal(2), Signal(3)
total = computed(lambda: f"a + b = {a.value + b.value}")

page = Column(
    children=[
        Slider(a, min=0, max=10, label="a"),
        Slider(b, min=0, max=10, label="b"),
        Text(total),
    ]
)

indah.launch(indah.create_app(session=Session(page)))
```

- **`Signal`** holds a value. Read it with `.value`, set it with `.set(...)`.
- **`computed`** derives a value from other signals and recomputes only when one
  of them changes.
- **`Column`** lays its children out vertically; components like `Slider` and
  `Text` bind to a signal or computed.
- **`launch()`** binds a free port, starts the single-port ASGI app, and prints
  the URL. In a notebook it also embeds the app inline in the cell.

## Launching in each environment

=== "Colab / Runpod"

    Run the cell. `launch()` detects the platform, binds the port, and prints the
    proxy URL (and embeds the app inline). No tunnel, no WebSocket, no Node.

    ```python
    handle = indah.launch(indah.create_app(session=Session(page)))
    ```

=== "Local notebook"

    The same call works in a local JupyterLab. The app renders inline in the
    output cell.

=== "Script"

    From `python app.py`, `launch()` blocks and serves until you stop it; open the
    printed `http://127.0.0.1:<port>/` in a browser.

    ```python
    if __name__ == "__main__":
        indah.launch(indah.create_app(session=Session(page)))
    ```

## Streaming and async work

Heavy work runs async and streams into the UI instead of freezing it. A `Button`
handler can be `async def`; a `StreamText` grows token by token over SSE while the
rest of the page stays live.

```python
import indah
from indah import Signal, Button, TextInput, StreamText, Column, Session

prompt = Signal("")
out = StreamText(label="Response")


async def on_generate():
    out.reset()
    async for token in indah.mock_llm(prompt.value):  # any async generator
        out.feed(token)


page = Column(
    children=[
        TextInput(prompt, label="Prompt"),
        Button("Generate", on_click=on_generate),
        out,
    ]
)

indah.launch(indah.create_app(session=Session(page)))
```

`indah.mock_llm` is a stand-in async generator. Swap in a real model client with
the same shape - it never imports indah, so your generation logic stays plain
Python.

## Next

- [Components](components.md) - the full starter set.
- [Custom components](custom-components.md) - add your own.
