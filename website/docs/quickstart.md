# Quickstart

## Install

indah is pure-Python to install and run - no Node, npm, or bun, because the
frontend ships pre-built inside the wheel.

```bash
pip install indah
```

### Optional extras

The base install keeps four dependencies. indah never imports the libraries below itself: it
accepts their objects by duck-typing, so you only need an extra when your app uses the library
and you want a tested version range installed with it.

| Install | Adds | For |
|---------|------|-----|
| `pip install "indah[plot]"` | `matplotlib` | `Plot(figure)` |
| `pip install "indah[data]"` | `pandas`, `numpy` | `DataFrame` and `Table` from a pandas frame, numpy values in cells |
| `pip install "indah[all]"` | `plot` + `data` | both of the above |
| `pip install "indah[demos]"` | `numpy`, `pillow`, `onnxruntime`, `huggingface_hub`, `matplotlib` | running the gallery demos and the examples |

Quote the brackets in `zsh`. The extras do not make the install smaller; they only keep heavy
libraries out of the base install. The reasons are in ADR-0042.

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

Try it here. This is the same app, running in your browser with no server. Nothing is
downloaded until you press **Run it**, and then it loads about 9 MB (compressed) once. With
JavaScript off you still see the example's source and summary, without the button.

<indah-live page="start/quickstart"></indah-live>

Move a slider and the text changes. Only the `Text` that reads `total` is updated; the sliders
and the layout are not sent again.

## Launching in each environment

=== "Colab / Runpod"

    These snippets reuse `page` from the app above. Run the cell. `launch()` detects the platform, binds the port, and prints the
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

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="start/first-app"></indah-live>

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

## Batching writes

Writing two signals that one effect reads would normally run the effect twice. Wrap the
writes in `indah.batch` to run it once, after both:

```python
import indah
from indah import Signal, effect

first, last = Signal(""), Signal("")
effect(lambda: print(f"name: {first.value} {last.value}"))

indah.batch(lambda: (first.set("Ada"), last.set("Lovelace")))  # one run, after both
first.set("Grace")  # outside a batch: one run per write
```

The effect runs once when it is created, once for the batch, and once for the last write:

```text
name:  
name: Ada Lovelace
name: Grace Lovelace
```

You rarely need it in a click or input handler: indah already runs every synchronous handler
inside a `batch`, so two writes there cause one update. `batch` matters after an `await`, where
that wrapper has ended, and in background tasks and threads you start yourself.

Try it live. Nothing downloads until you press **Run it**.

<indah-live page="live/effect"></indah-live>

<indah-live page="live/batch"></indah-live>

## Next

- [Playground](playground.md) - edit this app and run it in your browser.
- [Components](components.md) - the full starter set.
- [Custom components](custom-components.md) - add your own.
