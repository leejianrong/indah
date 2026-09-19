"""Upload -> detect -> show boxes: object detection, indah-style.

Upload an image; a (mock) detector finds a handful of objects and draws labeled
boxes over the image via ``ImageOverlay``. The "model" here is a deterministic
stand-in with no heavy deps, but it is a plain function behind a plain handler,
so a real detector (e.g. an onnxruntime/YOLO call) drops straight in - the rest
of the app is unchanged.

Boxes use ``label_mode="hover"``: with several detections on one image, a
permanent label per box gets noisy fast, so labels show as a tooltip on hover
instead (indah#78). Scroll to zoom into a small detection, drag to pan once
zoomed - both come from ``ImageOverlay`` itself (indah#77), no code here.

Each viewer gets an isolated session (``session_factory``), so one person's
upload and detections are private to their tab. Runs on Tier 0 (SSE + POST),
so it works behind Colab's proxy.

Run it with:  python examples/object_detection.py
Then open the URL and upload an image. No Node, at install or at runtime.
"""

import asyncio
import base64
import hashlib

import indah
from indah import (
    Card,
    Column,
    ImageOverlay,
    Session,
    Signal,
    Spinner,
    Text,
    Upload,
    UploadedFile,
    create_app,
)

# The stand-in object classes a real detector might return.
LABELS = [
    "cat",
    "dog",
    "car",
    "person",
    "bicycle",
    "traffic light",
    "backpack",
    "cup",
]


def detect(data: bytes) -> list[dict]:
    """A deterministic mock detector: same bytes -> same boxes.

    Stands in for a real detector call. Replace the body with an inference call
    and the rest of the app does not change. Coordinates are fractions of the
    image ([0, 1]), the convention ``ImageOverlay`` expects.
    """
    digest = hashlib.sha256(data).digest()
    count = 3 + digest[0] % 4  # 3-6 boxes - enough for hover-only labels to matter
    boxes = []
    for i in range(count):
        x0, y0, x1, y1 = digest[i * 4 : i * 4 + 4]
        boxes.append(
            {
                "x": round((x0 / 255) * 0.7, 3),
                "y": round((y0 / 255) * 0.7, 3),
                "w": round(0.15 + (x1 / 255) * 0.2, 3),
                "h": round(0.15 + (y1 / 255) * 0.2, 3),
                "label": LABELS[digest[(i + 8) % len(digest)] % len(LABELS)],
                "score": round(0.55 + (digest[(i + 16) % len(digest)] % 45) / 100, 2),
            }
        )
    return boxes


def _data_uri(file: UploadedFile) -> str:
    """The uploaded image bytes as a data: URI, so the shell can show it back."""
    mime = file.content_type or "image/png"
    return f"data:{mime};base64," + base64.b64encode(file.data).decode("ascii")


def build_session() -> Session:
    """A fresh per-viewer graph: upload an image, detect objects, show boxes."""
    preview: Signal[str] = Signal("")
    detections: Signal[list] = Signal([])
    status: Signal[str] = Signal("")
    busy: Signal[bool] = Signal(False)

    async def on_upload(file: UploadedFile) -> None:
        busy.set(True)
        status.set("")
        detections.set([])
        preview.set(_data_uri(file))
        await asyncio.sleep(0.4)  # stand in for model latency (never blocks the UI)
        boxes = detect(file.data)
        detections.set(boxes)
        noun = "object" if len(boxes) == 1 else "objects"
        status.set(f"Detected **{len(boxes)}** {noun}. Hover a box to read its label.")
        busy.set(False)

    return Session(
        Column(
            children=[
                Text(
                    "# Object detection\n\n"
                    "Upload an image and a mock detector boxes what it finds. Hover a "
                    "box for its label - scroll to zoom into a small detection, drag "
                    "to pan once zoomed. Each tab is its own session, so your upload "
                    "and results stay private to it.",
                    markdown=True,
                ),
                Card(
                    title="Input",
                    children=[
                        Upload(on_upload, accept="image/*", label="Upload an image"),
                        Spinner(active=busy, label="Detecting..."),
                    ],
                ),
                Card(
                    title="Result",
                    children=[
                        ImageOverlay(
                            preview,
                            boxes=detections,
                            label_mode="hover",
                            alt="uploaded image",
                        ),
                        Text(lambda: status.value or "_No detections yet._", markdown=True),
                    ],
                ),
            ]
        )
    )


# Module-level ASGI app for hosting.
app = create_app(session_factory=build_session)


if __name__ == "__main__":
    indah.launch(app)
