# Demo gallery

Real apps built with indah. Every demo is **running live** in the
[hosted gallery](https://indah-demos.fly.dev) - no install, no clone, just open it in
your browser. Each also runs in **one click in Colab**, embedded right in the notebook
cell. Every demo's source is a single Python file in
[`examples/`](https://github.com/leejianrong/indah/tree/main/examples).

[Open the live gallery :material-arrow-right:](https://indah-demos.fly.dev){ .md-button .md-button--primary }

## Notebook-native

Model behind a UI, inline in a cell, over a single proxy-friendly port.

| Demo | Live | Colab | What it shows |
|------|------|-------|---------------|
| **Streaming chatbot** | [Open](https://indah-demos.fly.dev/chatbot/) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/chatbot.ipynb) | A chat reply streamed token-by-token into role bubbles over SSE. The demo uses a mock reply; swap in a real model and the UI never freezes. |
| **Image generation** | [Open](https://indah-demos.fly.dev/diffusion/) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/diffusion.ipynb) | A prompt-to-image sampler whose picture refines from noise to a finished frame with live progress. The demo replays a mock sampler; a real pipeline drops in behind the same shape. |
| **Image classifier** | [Open](https://indah-demos.fly.dev/image-classify/) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/image-classify.ipynb) | The classic upload -> predict -> show, with a downloadable report. A real MobileNetV2 model runs live on CPU, per-session, so viewers do not collide. |
| **Object detection** | [Open](https://indah-demos.fly.dev/object-detection/) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/object-detection.ipynb) | Upload an image and a mock detector boxes what it finds; hover a box for its label, scroll to zoom in. The demo uses a deterministic mock detector. |

## Standalone apps

Real apps you run and deploy - dashboards, explorers, generators.

| Demo | Live | Colab | What it shows |
|------|------|-------|---------------|
| **Live training dashboard** | [Open](https://indah-demos.fly.dev/training-dashboard/) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/training-dashboard.ipynb) | Loss curves streaming in real time (train + val) via the append op at O(point), with a progress bar and a run-history table. The demo indah is built for on Runpod. |
| **Poster generator** | [Open](https://indah-demos.fly.dev/poster/) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/poster.ipynb) | Tweak controls, watch a striking poster re-render live (reactive - only the image patches), then download it. |
| **Hybrid charting** | [Open](https://indah-demos.fly.dev/charts/) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/charts.ipynb) | An interactive client chart (zoom, hover, live points) beside a static Matplotlib plot and a heatmap - the hybrid charting story. |
| **Stock peer analysis** | [Open](https://indah-demos.fly.dev/stocks/) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/stocks.ipynb) | Pick a company and its metric cards refocus; a client chart shows each peer's normalized 1-year price. Mock data, dashboard pattern (Table selection drives Stat cards). |
| **Pretty map** | [Open](https://indah-demos.fly.dev/prettymap/) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/prettymap.ipynb) | Restyle a generated city map (streets, blocks, water, parks) with a few controls - it re-renders live, then downloads as SVG. The generate-and-download archetype. |

## Run one locally instead

```bash
git clone https://github.com/leejianrong/indah && cd indah
uv sync --extra dev
uv run python examples/poster.py     # prints a URL; open it in your browser
```

Or `make demo` for the built-in tour. See the [Quickstart](quickstart.md) to write
your own.
