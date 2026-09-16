"""Image generation with streamed progress: watch a picture 'denoise' step by step.

The Gradio "fake diffusion" archetype, done on indah: type a prompt, hit Generate,
and the image refines from noise to a finished frame while a progress bar fills - all
live over SSE, the UI never freezing. A real diffusion pipeline drops in behind the
same shape (ADR-0009): swap the mock ``denoise`` generator for
``for image in pipe(prompt, callback=...)`` and keep the exact same UI wiring.

The mock generator needs no ML dependency and no network: it renders each step as an
inline SVG (a colour field derived from the prompt, with noise that clears as the
steps progress), so the demo runs on indah alone. This is a natural fit for a Runpod
GPU notebook, indah's home turf.

Run it with:  python examples/diffusion.py   (prints a URL; embeds inline in a cell).
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import urllib.parse

import indah

_PALETTE = ["#b5296b", "#2e6d62", "#e0701a", "#3457d5", "#8a3ffc", "#c0362c", "#1f9d8f"]


def _colors(prompt: str) -> tuple[str, str]:
    """Two stable colours derived from the prompt, so a prompt always 'renders' the
    same picture (a real model is likewise deterministic given a seed)."""
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    return _PALETTE[digest[0] % len(_PALETTE)], _PALETTE[digest[1] % len(_PALETTE)]


def _frame(prompt: str, t: float, rng: random.Random) -> str:
    """One diffusion step as an SVG data URI. ``t`` in [0, 1] is how denoised we are:
    0 is mostly noise, 1 is the clean colour field. Noise speckles thin out and fade
    as ``t`` rises, so successive frames look like a picture emerging."""
    c1, c2 = _colors(prompt)
    signal = max(0.0, min(1.0, t))
    speckles = int(420 * (1 - signal))
    alpha = f"{0.55 * (1 - signal):.2f}"
    noise = "".join(
        f"<rect x='{rng.randint(0, 255)}' y='{rng.randint(0, 255)}' "
        f"width='{rng.randint(2, 7)}' height='{rng.randint(2, 7)}' "
        f"fill='{'#000' if rng.random() < 0.5 else '#fff'}' fill-opacity='{alpha}'/>"
        for _ in range(speckles)
    )
    # A soft two-colour field with an emerging focal shape - the "content".
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='256' height='256'>"
        "<defs><radialGradient id='g' cx='50%' cy='45%' r='70%'>"
        f"<stop offset='0%' stop-color='{c1}'/><stop offset='100%' stop-color='{c2}'/>"
        "</radialGradient></defs>"
        "<rect width='256' height='256' fill='url(#g)'/>"
        f"<circle cx='128' cy='118' r='{54 * signal:.0f}' fill='#fff' "
        f"fill-opacity='{0.20 * signal:.2f}'/>"
        f"{noise}</svg>"
    )
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


def build() -> indah.Session:
    prompt = indah.Signal("a serene mountain lake at dawn")
    steps = indah.Signal(20)
    busy = indah.Signal(False)
    image = indah.Signal(_frame("", 0.0, random.Random(0)))
    console = indah.StreamText(label="Sampler log")

    async def generate() -> None:
        if busy.value:
            return
        busy.set(True)
        n = max(2, int(steps.value))
        rng = random.Random(hashlib.sha256(prompt.value.encode()).digest())
        console.reset()
        console.feed(f"> sampling '{prompt.value.strip() or 'untitled'}' in {n} steps\n")
        try:
            for i in range(n):
                image.set(_frame(prompt.value, (i + 1) / n, rng))
                if i % max(1, n // 8) == 0 or i == n - 1:
                    console.feed(f"> step {i + 1}/{n}\n")
                await asyncio.sleep(0.08)  # a real sampler step runs on the GPU here
            console.feed("> done\n")
        finally:
            busy.set(False)

    controls = indah.Card(
        title="Prompt",
        children=[
            indah.TextInput(
                prompt, label="Prompt", placeholder="Describe an image...", on_submit=generate
            ),
            indah.Slider(steps, min=4, max=40, step=1, label="Steps"),
            indah.Button("Generate", on_click=generate),
            indah.Spinner(active=busy, label="sampling..."),
        ],
    )

    workspace = indah.Column(
        children=[
            indah.Card(children=[indah.Image(image, alt="generated image")]),
            indah.Expander(label="Sampler log", children=[console]),
        ]
    )

    intro = indah.Text(
        "# Image generation with streamed progress\n\n"
        "Type a prompt and hit **Generate** - the image refines from noise to a "
        "finished frame while sampling runs, live over SSE, without freezing the "
        "page. A real diffusion pipeline drops in behind the same shape (ADR-0009).",
        markdown=True,
    )
    return indah.Session(
        indah.Column(children=[intro, indah.Sidebar(children=[controls, workspace])])
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
