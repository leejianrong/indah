"""Click to segment: click a spot, or drag a box, and the region around it lights up.

Pick a sample picture (or upload your own), choose **Point** or **Box**, and draw on it. indah
sends the point or box to Python, Python grows a region from it by colour, and the region comes
back as a mask drawn over the picture. A slider sets how far a pixel's colour may differ from the
seed's and still join the region.

What it shows off:
- `ImageOverlay(draw=, on_draw=)` (ADR-0020 step 2): the user draws, the app decides what it means.
  indah keeps no list of what was drawn; this app shows its seed back as a `shapes` entry;
- an overlay mask (`masks=`) that is a PNG made in Python, redrawn on every click or slider move;
- the picture's pixel size (`size=`), so a drawn point lands on the pixel under the pointer at any
  rendered size.

It is a classic region grower, not a neural network: there is no model to download, nothing runs
off the page, and every region is capped by the picture's size (the picture is shrunk to
``MAX_SIDE`` pixels on its longest edge first), so one visitor cannot hog the process. Each
viewer's picture and region are their own (``session_factory``).

Run it with:  python examples/segment.py   (prints a URL; embeds inline in a notebook cell).
Needs numpy and Pillow (``pip install indah[demos]``).
"""

from __future__ import annotations

import io
import math

import indah

MAX_SIDE = 320  # the picture is shrunk to this on its longest edge before anything runs
MAX_UPLOAD = 8_000_000  # bytes; larger uploads are refused before decoding
MAX_PIXELS = 25_000_000  # an upload that decodes to more pixels than this is refused
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
TOLERANCE_MIN, TOLERANCE_MAX, TOLERANCE_DEFAULT = 5, 120, 40
MASK_RGB = (255, 94, 0)
MASK_OPACITY = 0.6


def _png(array) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.fromarray(array).save(out, format="PNG")
    return out.getvalue()


def make_sample(name: str):
    """A synthetic ``(H, W, 3)`` uint8 picture with a few distinct, slightly noisy regions."""
    import numpy as np

    h, w = 240, 320
    yy, xx = np.mgrid[0:h, 0:w]
    rng = np.random.default_rng(7)
    img = np.zeros((h, w, 3), dtype=float)
    if name == "shapes":
        img[:] = (232, 226, 210)  # paper
        discs = [((90, 90), 55, (70, 130, 200)), ((215, 80), 40, (220, 90, 90))]
        for (cx, cy), r, colour in discs:
            img[(xx - cx) ** 2 + (yy - cy) ** 2 < r * r] = colour
        img[150:215, 120:290] = (90, 170, 110)  # a green bar
        img[160:205, 140:190] = (240, 200, 70)  # a yellow tile inside it
    else:  # "landscape"
        sky = np.linspace(0, 1, h)[:, None]
        img[:] = (110 + 60 * sky)[..., None] * (0.7, 0.9, 1.3)
        img[(xx - 250) ** 2 + (yy - 50) ** 2 < 22**2] = (255, 214, 90)  # sun
        hills = 150 + 18 * np.sin(xx / 30.0)
        img[yy > hills] = (74, 140, 84)
        img[(yy > 120) & (yy < 175) & (xx > 70) & (xx < 140)] = (190, 96, 80)  # house
        img[(yy > 95) & (yy <= 120) & (xx > 85) & (xx < 125) & (yy > 215 - xx)] = (
            120,
            60,
            50,
        )  # roof
    img += rng.normal(0, 4, img.shape)  # film grain, so a tolerance of zero finds almost nothing
    return np.clip(img, 0, 255).astype(np.uint8)


SAMPLES = {"Shapes": "shapes", "Landscape": "landscape"}


def load_upload(data: bytes, content_type: str):
    """An upload -> ``(H, W, 3)`` uint8 shrunk to ``MAX_SIDE``; a ``ValueError`` says why not."""
    import numpy as np
    from PIL import Image, UnidentifiedImageError

    if content_type not in ALLOWED_TYPES:
        raise ValueError("Upload a JPEG, PNG or WebP picture.")
    if len(data) > MAX_UPLOAD:
        raise ValueError(f"That file is over {MAX_UPLOAD // 1_000_000} MB.")
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > MAX_PIXELS:
            raise ValueError("That picture is too large to open here.")
        image = image.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("That file is not a picture indah can read.") from exc
    scale = min(1.0, MAX_SIDE / max(image.size))
    if scale < 1.0:
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        )
    return np.asarray(image, dtype=np.uint8)


def grow_region(rgb, seed: tuple[float, float], tolerance: float, box=None):
    """The pixels joined to ``seed`` through neighbours whose colour is within ``tolerance`` of the
    seed's colour (Euclidean distance in RGB, the seed's colour taken as the mean of its 3x3
    patch), as an ``(H, W)`` bool array. ``box`` = ``(x1, y1, x2, y2)`` keeps the region inside it.
    """
    import numpy as np

    h, w = rgb.shape[:2]
    sx = min(max(int(seed[0]), 0), w - 1)
    sy = min(max(int(seed[1]), 0), h - 1)
    patch = rgb[max(sy - 1, 0) : sy + 2, max(sx - 1, 0) : sx + 2].reshape(-1, 3).astype(float)
    centre = patch.mean(axis=0)
    close = np.sqrt(((rgb.astype(float) - centre) ** 2).sum(axis=2)) <= tolerance
    if box is not None:
        x1, y1, x2, y2 = (
            int(math.floor(box[0])),
            int(math.floor(box[1])),
            int(math.ceil(box[2])),
            int(math.ceil(box[3])),
        )
        fence = np.zeros_like(close)
        fence[max(y1, 0) : min(y2, h), max(x1, 0) : min(x2, w)] = True
        close &= fence
    region = np.zeros_like(close)
    if not close[sy, sx]:
        return region
    stack = [(sy, sx)]
    region[sy, sx] = True
    while stack:
        y, x = stack.pop()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and close[ny, nx] and not region[ny, nx]:
                region[ny, nx] = True
                stack.append((ny, nx))
    return region


def mask_png(region) -> bytes:
    """A region -> a transparent RGBA PNG with the region filled."""
    import numpy as np

    h, w = region.shape
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[region] = (*MASK_RGB, 255)
    return _png(out)


class Segmenter:
    """One viewer's picture, tool, tolerance and region."""

    def __init__(self) -> None:
        self.tool = indah.Signal("point")
        self.tolerance = indah.Signal(TOLERANCE_DEFAULT)
        self.picture = indah.Signal(make_sample("shapes"))
        self.seed: indah.Signal[dict | None] = indah.Signal(None)  # the last drawn shape
        self.status = indah.Signal("Click the picture, or drag a box, to segment it.")

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.picture.value.shape[:2]
        return (w, h)

    def region(self):
        seed = self.seed.value
        if seed is None:
            return None
        rgb = self.picture.value
        if seed["kind"] == "point":
            return grow_region(rgb, seed["point"], self.tolerance.value)
        x1, y1, x2, y2 = seed["box"]
        return grow_region(
            rgb, ((x1 + x2) / 2, (y1 + y2) / 2), self.tolerance.value, box=seed["box"]
        )

    def on_draw(self, shape: dict) -> None:
        self.seed.set(shape)

    def pick_sample(self, name: str) -> None:
        self.picture.set(make_sample(SAMPLES[name]))
        self.clear()

    def on_upload(self, file: indah.UploadedFile) -> None:
        try:
            self.picture.set(load_upload(file.data, file.content_type))
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.clear()

    def clear(self) -> None:
        self.seed.set(None)
        self.status.set("Click the picture, or drag a box, to segment it.")


def build() -> indah.Session:
    s = Segmenter()

    # One computed so the mask and the readout share a single region-growing pass.
    region = indah.computed(s.region)

    def masks():
        r = region.value
        return [] if r is None else [{"src": mask_png(r), "opacity": MASK_OPACITY}]

    def shapes():
        seed = s.seed.value
        if seed is None:
            return []
        item = {"id": "seed", "stroke": "#ffffff", "width": 2, "label": "your " + seed["kind"]}
        item["box" if seed["kind"] == "box" else "point"] = seed[seed["kind"]]
        return [item]

    def readout() -> str:
        r = region.value
        if r is None:
            return s.status.value
        area = int(r.sum())
        if area == 0:
            return "Nothing there matches at this tolerance. Raise it, or pick another spot."
        h, w = r.shape
        return f"Region: {area:,} pixels, {100 * area / (w * h):.1f}% of the picture."

    controls = indah.Card(
        title="Segment",
        children=[
            indah.Radio(s.tool, options=[("point", "Point"), ("box", "Box")], label="Tool"),
            indah.Slider(
                s.tolerance, min=TOLERANCE_MIN, max=TOLERANCE_MAX, step=5, label="Colour tolerance"
            ),
            indah.Text("Try a sample:"),
            indah.Row(
                children=[
                    indah.Button(name, on_click=(lambda n=name: s.pick_sample(n)), variant="ghost")
                    for name in SAMPLES
                ],
                gap="0.5rem",
                align="start",
            ),
            indah.Upload(s.on_upload, accept="image/*", label="Or upload your own"),
            indah.Button("Clear", on_click=s.clear, variant="tonal"),
        ],
    )
    stage = indah.Card(
        title="Picture",
        children=[
            indah.ImageOverlay(
                lambda: _png(s.picture.value),
                size=lambda: s.size,
                masks=masks,
                shapes=shapes,
                draw=lambda: s.tool.value,
                on_draw=s.on_draw,
                alt="The picture to segment",
            ),
            indah.Text(readout),
        ],
    )
    intro = indah.Text(
        "# Click to segment\n\n"
        "Choose **Point** and click a thing, or **Box** and drag around it. The orange region is "
        "every pixel joined to your spot by a similar colour. Move the tolerance slider to make it "
        "pickier or looser. It is a region grower, not a neural network, so it follows colour, "
        "not meaning.",
        markdown=True,
    )
    return indah.Session(indah.Column(children=[intro, indah.Sidebar(children=[controls, stage])]))


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
