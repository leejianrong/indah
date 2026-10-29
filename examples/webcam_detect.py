"""Live webcam object detection, indah-style (IND-64, ADR-0045).

Press "Start camera" and the browser sends a small JPEG several times a second; each frame is run
through the same SSD-MobileNetV1 detector as ``object_detection.py`` and shown back with boxes.

This is the Tier 1 demo: frames travel over an opt-in WebSocket (``create_app(live=True)``, which
needs ``pip install "indah[live]"``). It is meant for a machine that passes WebSockets (your laptop,
Runpod, your own server). Where it cannot, for example in Colab, the camera falls back to about one
snapshot a second over plain HTTP and the same handler still runs, just slower.

The detector is slower than the camera, and that is fine: while one frame is being detected the
newest frame waits and older ones are dropped, so the boxes follow the picture closely instead of
lagging further behind. The model run is off the event loop (``asyncio.to_thread``).

The browser only hands out the camera on ``https://`` pages or ``localhost``.

Run it with:  python examples/webcam_detect.py
Needs:        pip install "indah[live,demos]"
"""

import asyncio
import base64
import importlib.util
from pathlib import Path

import indah
from indah import Camera, CameraFrame, Card, Column, ImageOverlay, Session, Signal, Text, create_app

_detector = None


def detect(data: bytes) -> list[dict]:
    """Boxes for one JPEG, from ``object_detection.detect`` (loaded on first use, so importing this
    module needs no model library)."""
    global _detector
    if _detector is None:
        path = Path(__file__).with_name("object_detection.py")
        spec = importlib.util.spec_from_file_location("indah_example_object_detection", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _detector = module.detect
    return _detector(data)


def _status(boxes: list[dict]) -> str:
    if not boxes:
        return "_Nothing detected in this frame._"
    names = sorted({b["label"] for b in boxes})
    return f"**{len(boxes)}** objects: {', '.join(names)}"


def build_session() -> Session:
    """A fresh per-viewer graph: a camera in, the last analysed frame and its boxes out."""
    picture: Signal[str] = Signal("")
    boxes: Signal[list] = Signal([])
    status: Signal[str] = Signal("_Press Start camera._")
    frames: Signal[int] = Signal(0)

    async def on_frame(frame: CameraFrame) -> None:
        found = await asyncio.to_thread(detect, frame.data)
        uri = f"data:{frame.content_type};base64,{base64.b64encode(frame.data).decode()}"
        # One batch, so the picture and its boxes arrive together and never disagree.
        indah.batch(
            lambda: (
                picture.set(uri),
                boxes.set(found),
                status.set(_status(found)),
                frames.set(frames.value + 1),
            )
        )

    camera = Camera(on_frame, label="Your camera", fps=4, max_width=480)

    return Session(
        Column(
            children=[
                Text(
                    "# Live detection\n\n"
                    "A real SSD-MobileNetV1 model boxes what your camera sees, on the server's "
                    "CPU. The picture on the right is the exact frame the boxes belong to. Frames "
                    "the model cannot keep up with are dropped, so it stays close to live.",
                    markdown=True,
                ),
                Card(title="Camera", children=[camera]),
                Card(
                    title="Detections",
                    children=[
                        ImageOverlay(
                            picture, boxes=boxes, label_mode="always", alt="analysed frame"
                        ),
                        Text(lambda: status.value, markdown=True),
                        Text(
                            lambda: f"Analysed {frames.value}, sent over {camera.transport.value}"
                        ),
                    ],
                ),
            ]
        )
    )


def _has_websockets() -> bool:
    return importlib.util.find_spec("websockets") is not None


# live=True only when a WebSocket library is installed; without one the demo runs on snapshots.
app = create_app(session_factory=build_session, live=_has_websockets(), max_upload_mb=4)


if __name__ == "__main__":
    indah.launch(app)
