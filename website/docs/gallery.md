# Demo gallery

Real apps built with indah. Open the [hosted gallery](https://indah-demos.fly.dev) to
try any of them right in your browser - no install, no clone. The notebook-native ones
below also run in **one click in Colab**, embedded right in the cell. Every demo's
source is a single Python file in
[`examples/`](https://github.com/leejianrong/indah/tree/main/examples).

[Open the gallery :material-arrow-right:](https://indah-demos.fly.dev){ .md-button .md-button--primary }

## Notebook-native

Model behind a UI, inline in a cell, over a single proxy-friendly port.

| Demo | Colab | What it shows |
|------|-------|---------------|
| **Streaming chatbot** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/chatbot.ipynb) | A chat reply streamed token-by-token into role bubbles over SSE. The demo uses a mock reply; swap in a real model and the UI never freezes. |
| **Image generation** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/diffusion.ipynb) | A prompt's picture refines from noise to a finished frame with real-time progress - real stable-diffusion-v1-5 frames, pre-recorded (no GPU in the hosted gallery) and replayed both forward and reverse. |
| **Image classifier** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/image-classify.ipynb) | Pick a sample photo or upload your own; a real MobileNetV2 model runs on CPU and shows the top 5 predictions as a bar chart, per-session, so viewers do not collide. |
| **Object detection** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leejianrong/indah/blob/main/examples/colab/object-detection.ipynb) | Upload an image and a mock detector boxes what it finds; hover a box for its label, scroll to zoom in. The demo uses a deterministic mock detector. |

The [hosted gallery](https://indah-demos.fly.dev) also has standalone apps - dashboards,
explorers, generators - that are built to run and deploy rather than sit in a notebook
cell. See the [Quickstart](quickstart.md) to write your own.
