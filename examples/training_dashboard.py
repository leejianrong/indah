"""A live training dashboard: streaming loss curves, progress, and a run history.

The demo indah is built for on Runpod - watch a model train in real time from a
notebook cell. A mock training loop stands in for the real thing (no ML dependency);
a real loop drops straight in behind the same shape (ADR-0009): call ``monitor.step``
from inside your epoch/step loop and everything streams to the browser over SSE.

What it shows off:
- a **Chart** with two streaming series (train + val loss) that grows point-by-point
  via the append op at O(point) - the KAN-1395 + Slice E path, ideal for long runs;
- a **Progress** bar and a row of live **Stat** KPI cards (step, train/val loss, LR)
  that update in place without freezing the page;
- a **DataFrame** run history that appends a row per epoch;
- an async handler, so the UI stays fully live while "training" runs.

Run it with:  python examples/training_dashboard.py   (prints a URL; embeds inline in
a Colab/Runpod cell).
"""

from __future__ import annotations

import asyncio
import math
import random

import indah


def _fmt_loss(v: float | None) -> str:
    return "-" if v is None else f"{v:.4f}"


def _fmt_lr(v: float | None) -> str:
    return "-" if v is None else f"{v:.2e}"


class TrainingMonitor:
    """Holds the dashboard's reactive state and the (mock) training loop.

    Split out as a plain object so the training loop reads like real code: it just
    calls ``self.step(...)`` and ``self.epoch_end(...)`` - no indah-specific plumbing
    in the loop body (ADR-0009)."""

    def __init__(self) -> None:
        self.curves = indah.Chart(
            series=[
                {"label": "train loss", "stroke": "#b5296b"},
                {"label": "val loss", "stroke": "#2e6d62"},
            ],
            title="Loss",
            x_label="step",
        )
        self.running = indah.Signal(False)
        self.progress = indah.Signal(0.0)
        self.status = indah.Signal("Idle - press Start to train.")
        # Live metrics, one signal each, shown as Stat KPI cards (not one big string).
        self.step_i = indah.Signal(0)
        self.total = indah.Signal(0)
        self.train_loss: indah.Signal = indah.Signal(None)
        self.val_loss: indah.Signal = indah.Signal(None)
        self.lr: indah.Signal = indah.Signal(None)
        self.history = indah.Signal([])  # per-epoch summary rows

    def step(self, step: int, train_loss: float, val_loss: float, total: int, lr: float) -> None:
        self.curves.push(step, round(train_loss, 4), round(val_loss, 4))
        self.progress.set((step + 1) / total)
        self.step_i.set(step + 1)
        self.total.set(total)
        self.train_loss.set(train_loss)
        self.val_loss.set(val_loss)
        self.lr.set(lr)

    def epoch_end(self, epoch: int, train_loss: float, val_loss: float) -> None:
        self.history.set(
            self.history.value
            + [{"epoch": epoch, "train_loss": round(train_loss, 4), "val_loss": round(val_loss, 4)}]
        )

    async def train(self, *, epochs: int = 5, steps_per_epoch: int = 40) -> None:
        if self.running.value:
            return
        self.running.set(True)
        self.status.set("Training...")
        self.curves.clear()
        self.history.set([])
        total = epochs * steps_per_epoch
        train_loss, val_loss = 2.2, 2.4
        try:
            for epoch in range(1, epochs + 1):
                for s in range(steps_per_epoch):
                    step = (epoch - 1) * steps_per_epoch + s
                    lr = 1e-3 * (0.5 ** (epoch - 1))
                    # A plausible decaying loss with noise; val trails a touch behind.
                    train_loss = max(0.05, train_loss * 0.985 + random.uniform(-0.01, 0.01))
                    val_loss = max(
                        0.06,
                        val_loss * 0.988
                        + 0.03 * math.sin(step / 7)
                        + random.uniform(-0.008, 0.012),
                    )
                    self.step(step, train_loss, val_loss, total, lr)
                    await asyncio.sleep(0.03)  # a real step would take much longer
                self.epoch_end(epoch, train_loss, val_loss)
            self.status.set(f"Done - {epochs} epochs, final val {val_loss:.4f}.")
        finally:
            self.running.set(False)


def build() -> indah.Session:
    m = TrainingMonitor()

    controls = indah.Card(
        title="Run",
        children=[
            indah.Button("Start training", on_click=m.train),
            indah.Spinner(active=m.running, label="training..."),
            indah.Progress(m.progress, label="Epoch progress"),
            indah.Text(lambda: m.status.value),
        ],
    )

    # Live metrics as KPI cards that update in place, instead of one big number string.
    metrics = indah.Row(
        children=[
            indah.Stat(
                value=lambda: f"{m.step_i.value}/{m.total.value}" if m.total.value else "-",
                label="Step",
            ),
            indah.Stat(value=lambda: _fmt_loss(m.train_loss.value), label="Train loss"),
            indah.Stat(value=lambda: _fmt_loss(m.val_loss.value), label="Val loss"),
            indah.Stat(value=lambda: _fmt_lr(m.lr.value), label="Learning rate"),
        ],
    )

    workspace = indah.Column(
        children=[
            metrics,
            indah.Card(children=[m.curves]),
            indah.Card(
                title="Run history",
                children=[
                    indah.DataFrame(
                        lambda: (
                            m.history.value
                            or {"columns": ["epoch", "train_loss", "val_loss"], "rows": []}
                        )
                    )
                ],
            ),
        ]
    )

    intro = indah.Text(
        "# Live training dashboard\n\n"
        "Watch loss curves stream in real time while training runs - the demo indah "
        "is built for on Runpod. The loss points arrive over SSE via the append op "
        "(O(point)), so a long run stays cheap and the page never freezes.",
        markdown=True,
    )
    return indah.Session(
        indah.Column(children=[intro, indah.Sidebar(children=[controls, workspace])])
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
