"""Object detection on a video, stepped frame by frame, indah-style (IND-62).

Upload a short video (or a handful of images), and the server picks up to 24 frames spread across
it, runs the same SSD-MobileNetV1 detector as ``object_detection.py`` on each, and then a slider
scrubs through the frames with the boxes drawn on each one. Detection runs once, up front, so
scrubbing is instant.

This is a Tier 0 demo (plain SSE + POST, ADR-0017/0045): nothing live, so it works behind Colab's
proxy as it is. Decoding a video needs ``av`` (PyAV, which bundles ffmpeg); without it the page
still takes images, and the "Use the sample photos" button needs nothing extra.

Run it with:  python examples/video_detect.py
Needs:        pip install "indah[demos]" av     (``av`` is this demo's own dependency)
"""

import asyncio
import base64
import importlib.util
import io
from pathlib import Path

import indah
from indah import (
    Button,
    Card,
    Column,
    ImageOverlay,
    Row,
    Session,
    Signal,
    Slider,
    Spinner,
    Text,
    Upload,
    UploadedFile,
    create_app,
)

MAX_FRAMES = 24
MAX_WIDTH = 480

_module = None


def _detector():
    """``object_detection`` loaded on first use, so importing this module needs no model library."""
    global _module
    if _module is None:
        path = Path(__file__).with_name("object_detection.py")
        spec = importlib.util.spec_from_file_location("indah_example_object_detection", path)
        _module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_module)
    return _module


def detect(data: bytes) -> list[dict]:
    return _detector().detect(data)


def sample_frames() -> list[bytes]:
    """The detector demo's bundled photos, as frames."""
    return [base64.b64decode(b64) for _label, b64 in _detector()._SAMPLES.values()]


def pick_indices(count: int) -> list[int]:
    """Up to ``MAX_FRAMES`` indices spread evenly over ``count`` frames, first and last included."""
    if count <= MAX_FRAMES:
        return list(range(count))
    return sorted({round(i * (count - 1) / (MAX_FRAMES - 1)) for i in range(MAX_FRAMES)})


def video_frames(data: bytes) -> list[bytes]:
    """Up to ``MAX_FRAMES`` JPEGs spread evenly over a video's bytes (needs ``av`` and Pillow)."""
    import av  # noqa: PLC0415 - optional, this demo's own dependency

    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.video[0]
        frames = []
        for frame in container.decode(stream):
            frames.append(frame.to_image())
            if len(frames) > 600:  # a safety stop for long clips
                break
    out = []
    for index in pick_indices(len(frames)):
        image = frames[index].convert("RGB")
        if image.width > MAX_WIDTH:
            image = image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=80)
        out.append(buffer.getvalue())
    return out


def _uri(data: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _summary(index: int, count: int, boxes: list[dict]) -> str:
    names = sorted({b["label"] for b in boxes})
    found = f"{len(boxes)} objects: {', '.join(names)}" if boxes else "nothing detected"
    return f"**Frame {index + 1} of {count}**: {found}"


def build_session() -> Session:
    """A fresh per-viewer graph: frames and their boxes, a slider to step through them."""
    frames: Signal[list] = Signal([])  # data: URIs
    found: Signal[list] = Signal([])  # a box list per frame
    position: Signal[float] = Signal(0)  # slider, 0..100 (a percentage of the way through)
    status: Signal[str] = Signal("_Upload a video or some images, or use the sample photos._")
    busy: Signal[bool] = Signal(False)

    def index() -> int:
        count = len(frames.value)
        return round(position.value / 100 * (count - 1)) if count > 1 else 0

    async def analyse(images: list[bytes]) -> None:
        busy.set(True)
        frames.set([])
        found.set([])
        position.set(0)
        uris, results = [], []
        for n, data in enumerate(images, 1):
            status.set(f"_Detecting frame {n} of {len(images)}..._")
            results.append(await asyncio.to_thread(detect, data))
            uris.append(_uri(data))
        indah.batch(
            lambda: (
                frames.set(uris),
                found.set(results),
                status.set(f"_Done: {len(uris)} frames. Drag the slider._"),
                busy.set(False),
            )
        )

    async def on_upload(files: list[UploadedFile]) -> None:
        if busy.value or not files:
            return
        try:
            first = files[0]
            if first.content_type.startswith("video/"):
                status.set("_Reading the video..._")
                images = await asyncio.to_thread(video_frames, first.data)
            else:
                images = [f.data for f in files if f.content_type.startswith("image/")]
                images = images[:MAX_FRAMES]
        except ImportError:
            status.set("_Reading video needs `pip install av`. Images work without it._")
            return
        except Exception:  # an undecodable file is the user's to fix, not a crash
            status.set("_That file could not be read as a video._")
            return
        if not images:
            status.set("_No frames found._")
            return
        await analyse(images)

    async def on_samples() -> None:
        if not busy.value:
            await analyse(sample_frames())

    def picture() -> str:
        items = frames.value
        return items[index()] if items else ""

    def boxes() -> list:
        items = found.value
        return items[index()] if items else []

    return Session(
        Column(
            children=[
                Text(
                    "# Video detection\n\n"
                    "Upload a short clip. A real SSD-MobileNetV1 model boxes what it finds in up "
                    "to 24 frames spread across it, then you scrub through them with the slider.",
                    markdown=True,
                ),
                Card(
                    title="Input",
                    children=[
                        Row(
                            children=[Button("Use the sample photos", on_click=on_samples)],
                            align="start",
                        ),
                        Upload(
                            on_upload,
                            accept="video/*,image/*",
                            multiple=True,
                            label="Or upload a video (or images)",
                        ),
                        Spinner(active=busy, label="Working..."),
                    ],
                ),
                Card(
                    title="Frames",
                    children=[
                        ImageOverlay(
                            indah.computed(picture),
                            boxes=indah.computed(boxes),
                            label_mode="hover",
                            alt="the current frame",
                        ),
                        Slider(position, min=0, max=100, step=1, label="Position in the video"),
                        Text(
                            lambda: (
                                _summary(index(), len(frames.value), boxes())
                                if frames.value
                                else status.value
                            ),
                            markdown=True,
                        ),
                    ],
                ),
            ]
        )
    )


app = create_app(session_factory=build_session, max_upload_mb=25)


if __name__ == "__main__":
    indah.launch(app)
