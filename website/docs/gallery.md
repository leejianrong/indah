# Demo gallery

Real apps built with indah. Each runs in **one click in Colab** - no install, no
clone, it embeds right in the notebook cell. An always-on hosted gallery (Hugging
Face Spaces) is on the way; until then, the Colab button is the fastest way to try
one. Every demo's source is a single Python file in
[`examples/`](https://github.com/leejianrong/indah/tree/main/examples).

## Notebook-native (the Gradio lane)

Model behind a UI, inline in a cell, over a single proxy-friendly port.

| Demo | Try it | What it shows |
|------|--------|---------------|
| **Streaming chatbot** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/chatbot.ipynb) | A chat reply streamed token-by-token into role bubbles over SSE. Swap the mock for a real model; the UI never freezes. |
| **Image generation** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/diffusion.ipynb) | A prompt-to-image sampler whose picture refines from noise to a finished frame with live progress - a natural Runpod-GPU fit. |
| **Image classifier** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/image-classify.ipynb) | The classic upload -> predict -> show, with a downloadable report. Per-session, so viewers do not collide. |

## Standalone apps (the Streamlit lane)

Real apps you run and deploy - dashboards, explorers, generators.

| Demo | Try it | What it shows |
|------|--------|---------------|
| **Live training dashboard** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/training-dashboard.ipynb) | Loss curves streaming in real time (train + val) via the append op at O(point), with a progress bar and a run-history table. The demo indah is built for on Runpod. |
| **Poster generator** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/poster.ipynb) | Tweak controls, watch a striking poster re-render live (reactive - only the image patches), then download it. The prettymapp archetype. |
| **Hybrid charting** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/charts.ipynb) | An interactive client chart (zoom, hover, live points) beside a static Matplotlib plot and a heatmap - the hybrid charting story. |

## Run one locally instead

```bash
git clone https://github.com/leejianrong/indah && cd indah
uv sync --extra dev
uv run python examples/poster.py     # prints a URL; open it in your browser
```

Or `make demo` for the built-in tour. See the [Quickstart](quickstart.md) to write
your own.
