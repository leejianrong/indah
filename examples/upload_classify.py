"""Upload -> classify -> show: the classic Gradio ML demo, now in indah (ADR-0017).

Upload an image; a (mock) classifier predicts a label; the page shows the image
back, the prediction, and a downloadable report. The "model" here is a deterministic
stand-in with no heavy deps, but it is a plain function behind a plain handler
(ADR-0009), so a real model client drops straight in -- swap ``classify`` for a call
to torch/transformers and the rest of the app is unchanged.

Each viewer gets an isolated session (``session_factory``, ADR-0010), so one
person's upload and result are private to their tab. Runs on Tier 0 (SSE + POST),
so it works behind Colab's proxy.

Run it with:  python examples/upload_classify.py
Then open the URL and upload an image. No Node, at install or at runtime.
"""

import asyncio
import base64
import hashlib

import indah
from indah import (
    Card,
    Column,
    Download,
    DownloadFile,
    Image,
    Session,
    Signal,
    Spinner,
    Text,
    Upload,
    UploadedFile,
    create_app,
)

# The stand-in "labels" a real image classifier might return.
LABELS = [
    "tabby cat",
    "golden retriever",
    "espresso",
    "sports car",
    "sunflower",
    "mountain lake",
    "acoustic guitar",
    "lighthouse",
]


def classify(data: bytes) -> tuple[str, float]:
    """A deterministic mock classifier: same bytes -> same label + confidence.

    Stands in for a real model call. Replace the body with an inference call and the
    rest of the app does not change (ADR-0009).
    """
    digest = hashlib.sha256(data).digest()
    label = LABELS[digest[0] % len(LABELS)]
    confidence = 0.60 + (digest[1] % 40) / 100  # 0.60 - 0.99
    return label, confidence


def _data_uri(file: UploadedFile) -> str:
    """The uploaded image bytes as a data: URI, so the shell can show it back."""
    mime = file.content_type or "image/png"
    return f"data:{mime};base64," + base64.b64encode(file.data).decode("ascii")


def build_session() -> Session:
    """A fresh per-viewer graph: upload an image, classify it, show the result."""
    preview: Signal[str] = Signal("")
    result: Signal[str] = Signal("")
    report: Signal = Signal(None)
    busy: Signal[bool] = Signal(False)

    async def on_upload(file: UploadedFile) -> None:
        busy.set(True)
        result.set("")
        report.set(None)
        preview.set(_data_uri(file))
        await asyncio.sleep(0.4)  # stand in for model latency (never blocks the UI)
        label, confidence = classify(file.data)
        result.set(f"Prediction: **{label}**  \nConfidence: **{confidence:.0%}**")
        summary = (
            f"file: {file.filename}\n"
            f"size: {file.size} bytes\n"
            f"prediction: {label}\n"
            f"confidence: {confidence:.2f}\n"
        )
        report.set(
            DownloadFile(summary.encode(), filename="prediction.txt", media_type="text/plain")
        )
        busy.set(False)

    return Session(
        Column(
            children=[
                Text(
                    "# Image classifier\n\n"
                    "Upload an image and a mock model predicts a label. Each tab is its "
                    "own session, so your upload and result stay private to it.",
                    markdown=True,
                ),
                Card(
                    title="Input",
                    children=[
                        Upload(on_upload, accept="image/*", label="Upload an image"),
                        Spinner(active=busy, label="Classifying..."),
                    ],
                ),
                Card(
                    title="Result",
                    children=[
                        Image(preview, alt="uploaded image"),
                        Text(lambda: result.value or "_No prediction yet._", markdown=True),
                        Download(report, label="Download report", filename="prediction.txt"),
                    ],
                ),
            ]
        )
    )


if __name__ == "__main__":
    indah.launch(create_app(session_factory=build_session))
