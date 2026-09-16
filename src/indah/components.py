"""UI components: a tree of nodes, each serialisable to JSON (ADR-0005).

A component holds static props and, where a prop is bound to a signal, a getter
that reads it. The session (session.py) assigns each node a stable id, serialises
the tree for the ``init`` message, and wires an effect per reactive prop so a
signal change emits a minimal patch for exactly that node.

Domain logic stays out of here: a Button's ``on_click`` is a plain callable the
caller supplies, a Slider writes to a plain Signal, and a StreamText is fed by a
plain async generator the caller wraps (ADR-0009).
"""

from __future__ import annotations

import base64
import inspect
import io
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .markdown import to_blocks
from .protocol import RenderSpec
from .reactive import Computed, Signal

if TYPE_CHECKING:
    from .session import Session

# A prop value may be static, a signal/computed, or a zero-arg callable.
Source = Any


def _read(source: Source) -> Any:
    if isinstance(source, (Signal, Computed)):
        return source.value
    if callable(source):
        return source()
    return source


class Component:
    type: str = "component"

    def __init__(self, children: list[Component] | None = None) -> None:
        self.id: str | None = None
        self.children: list[Component] = children or []

    def static_props(self) -> dict[str, Any]:
        return {}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        """Prop name -> getter. Getters read signals, so effects can track them."""
        return {}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        """Apply a client event.

        Return ``False`` if unhandled, ``True`` if handled synchronously, or a
        coroutine if the handler is async (the session awaits it as a background
        task so long work never blocks the request or the event loop).
        """
        return False

    def to_json(self) -> dict[str, Any]:
        props = dict(self.static_props())
        for name, getter in self.reactive_props().items():
            props[name] = getter()
        return {
            "id": self.id,
            "type": self.type,
            "props": props,
            "children": [child.to_json() for child in self.children],
        }


class Column(Component):
    type = "column"


class Card(Component):
    """A surface panel: a titled card that floats on the page ground (ADR-0014).

    The building block of the "panels on warm porcelain" Studio layout -- wrap a
    region's children in a ``Card`` to give it a surface, radius, and soft shadow.
    ``title`` renders a small uppercase panel heading.
    """

    type = "card"

    def __init__(self, children: list[Component] | None = None, *, title: str = "") -> None:
        super().__init__(children)
        self._title = title

    def static_props(self) -> dict[str, Any]:
        return {"title": self._title}


class Text(Component):
    """A text display bound to a source.

    With ``markdown=True`` the source is rendered as a safe subset of Markdown: it
    is parsed (server-side) into a block tree the shell renders through its safe DOM
    builder, so raw HTML stays literal and nothing can inject script (see
    ``markdown.py``). The node then carries ``blocks`` instead of ``text``.
    """

    type = "text"

    def __init__(self, source: Source, *, markdown: bool = False) -> None:
        super().__init__()
        self._source = source
        self._markdown = markdown

    def static_props(self) -> dict[str, Any]:
        return {"markdown": True} if self._markdown else {}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        if self._markdown:
            return {"blocks": lambda: to_blocks(str(_read(self._source)))}
        return {"text": lambda: str(_read(self._source))}


class Button(Component):
    """A clickable button.

    ``variant`` picks the Studio treatment: ``"filled"`` (default, the magenta
    primary), ``"tonal"`` (the teal secondary container -- a softer secondary
    action), or ``"ghost"`` (outline only). It is a static styling prop; the
    click behaviour is identical.
    """

    type = "button"

    def __init__(
        self,
        label: Source,
        on_click: Callable[[], Any] | None = None,
        *,
        variant: str = "filled",
    ) -> None:
        super().__init__()
        self._label = label
        self._on_click = on_click
        self._variant = variant

    def static_props(self) -> dict[str, Any]:
        # Only emit a non-default variant, so a plain Button stays minimal on the wire.
        return {"variant": self._variant} if self._variant != "filled" else {}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"label": lambda: str(_read(self._label))}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "click" and self._on_click is not None:
            result = self._on_click()
            if inspect.iscoroutine(result):
                return result  # async handler: the session awaits it in the background
            return True
        return False


class Slider(Component):
    type = "slider"

    def __init__(
        self,
        value: Signal[float],
        *,
        min: float = 0,
        max: float = 100,
        step: float = 1,
        label: str = "",
    ) -> None:
        super().__init__()
        self._value = value
        self._min = min
        self._max = max
        self._step = step
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"min": self._min, "max": self._max, "step": self._step, "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "input" and "value" in payload:
            self._value.set(payload["value"])
            return True
        return False


class TextInput(Component):
    """A single-line text box two-way bound to a ``Signal[str]``.

    Needed for the Slice 3 demo's prompt box; part of the R5 starter set (V4).
    """

    type = "textinput"

    def __init__(
        self,
        value: Signal[str],
        *,
        placeholder: str = "",
        label: str = "",
        on_submit: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__()
        self._value = value
        self._placeholder = placeholder
        self._label = label
        self._on_submit = on_submit

    def static_props(self) -> dict[str, Any]:
        return {"placeholder": self._placeholder, "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "input" and "value" in payload:
            self._value.set(str(payload["value"]))
            return True
        if event == "submit":
            # Enter in the box. Always handled (a no-op without on_submit, so it
            # never 400s); runs on_submit sync or async, like a Button click.
            if self._on_submit is not None:
                result = self._on_submit()
                if inspect.iscoroutine(result):
                    return result
            return True
        return False


class Checkbox(Component):
    """A checkbox two-way bound to a ``Signal[bool]`` (R5)."""

    type = "checkbox"

    def __init__(self, value: Signal[bool], *, label: str = "") -> None:
        super().__init__()
        self._value = value
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"checked": lambda: bool(self._value.value)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "change" and "value" in payload:
            self._value.set(bool(payload["value"]))
            return True
        return False


class Number(Component):
    """A numeric input two-way bound to a ``Signal[float]`` (R5).

    Like a Slider without the track: a plain number box with optional bounds.
    """

    type = "number"

    def __init__(
        self,
        value: Signal[float],
        *,
        min: float | None = None,
        max: float | None = None,
        step: float = 1,
        label: str = "",
    ) -> None:
        super().__init__()
        self._value = value
        self._min = min
        self._max = max
        self._step = step
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"min": self._min, "max": self._max, "step": self._step, "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "input" and "value" in payload:
            self._value.set(payload["value"])
            return True
        return False


class Date(Component):
    """A date picker two-way bound to a ``Signal[str]`` (ISO ``YYYY-MM-DD``) (R5)."""

    type = "date"

    def __init__(self, value: Signal[str], *, label: str = "") -> None:
        super().__init__()
        self._value = value
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event in ("input", "change") and "value" in payload:
            self._value.set(str(payload["value"]))
            return True
        return False


def _normalise_option(option: Any) -> dict[str, str]:
    """Accept ``"a"`` or ``("value", "Label")`` -> ``{"value","label"}`` (both str).

    HTML ``<select>`` values are strings on the wire, so a Select rounds-trips
    string values; pass ``(value, label)`` tuples when the shown text differs from
    the value.
    """
    if isinstance(option, (tuple, list)) and len(option) == 2:
        value, label = option
        return {"value": str(value), "label": str(label)}
    return {"value": str(option), "label": str(option)}


class Select(Component):
    """A drop-down two-way bound to a ``Signal[str]`` (R5, value-bearing).

    Set the signal from Python and the selection updates; choose in the UI and the
    signal is readable in Python (via the ``change`` event).
    """

    type = "select"

    def __init__(
        self,
        value: Signal[str],
        *,
        options: list[Any],
        label: str = "",
    ) -> None:
        super().__init__()
        self._value = value
        self._options = [_normalise_option(o) for o in options]
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"options": self._options, "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event in ("change", "input") and "value" in payload:
            self._value.set(str(payload["value"]))
            return True
        return False


class Radio(Component):
    """A radio group two-way bound to a ``Signal[str]`` (R5).

    Like a Select, but shows every option at once. Options are ``"a"`` or
    ``(value, label)`` tuples, same as Select.
    """

    type = "radio"

    def __init__(self, value: Signal[str], *, options: list[Any], label: str = "") -> None:
        super().__init__()
        self._value = value
        self._options = [_normalise_option(o) for o in options]
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"options": self._options, "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event in ("change", "input") and "value" in payload:
            self._value.set(str(payload["value"]))
            return True
        return False


class MultiSelect(Component):
    """A multi-select two-way bound to a ``Signal[list[str]]`` (R5).

    The signal holds the list of selected string values; choosing in the UI
    replaces it. Options are ``"a"`` or ``(value, label)`` tuples, same as Select.
    """

    type = "multiselect"

    def __init__(self, value: Signal[list], *, options: list[Any], label: str = "") -> None:
        super().__init__()
        self._value = value
        self._options = [_normalise_option(o) for o in options]
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"options": self._options, "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: list(self._value.value)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event in ("change", "input") and "value" in payload:
            values = payload["value"]
            if not isinstance(values, (list, tuple)):
                return False
            self._value.set([str(v) for v in values])
            return True
        return False


class Image(Component):
    """An image bound to a source that yields a URL or a ``data:`` URI (R5).

    The source is a signal/string/callable; set it from Python and the shown image
    updates. Displays only (no UI-change direction); its current value stays
    readable via the bound signal.
    """

    type = "image"

    def __init__(self, source: Source, *, alt: str = "") -> None:
        super().__init__()
        self._source = source
        self._alt = alt

    def static_props(self) -> dict[str, Any]:
        return {"alt": self._alt}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"src": lambda: _image_src(_read(self._source))}


def _image_src(value: Any) -> str:
    """Coerce a source value to something an ``<img src>`` accepts.

    A string (URL or ``data:`` URI) passes through; raw ``bytes`` are encoded as a
    PNG ``data:`` URI so a caller can hand over image bytes directly.
    """
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        encoded = base64.b64encode(bytes(value)).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    return str(value)


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_boxes(value: Any) -> list[dict[str, Any]]:
    """Normalise detection boxes to ``[{x,y,w,h,label,color,score}, ...]`` (coords in
    ``[0, 1]``, fractions of the image)."""
    out: list[dict[str, Any]] = []
    for b in value or []:
        if isinstance(b, dict):
            box = {
                "x": _num(b.get("x")),
                "y": _num(b.get("y")),
                "w": _num(b.get("w")),
                "h": _num(b.get("h")),
            }
        elif isinstance(b, (list, tuple)) and len(b) >= 4:
            box = {"x": _num(b[0]), "y": _num(b[1]), "w": _num(b[2]), "h": _num(b[3])}
        else:
            continue
        if isinstance(b, dict):
            if b.get("label") is not None:
                box["label"] = str(b["label"])
            if b.get("color"):
                box["color"] = str(b["color"])
            if b.get("score") is not None:
                box["score"] = _num(b["score"])
        out.append(box)
    return out


def _to_points(value: Any) -> list[dict[str, Any]]:
    """Normalise keypoints to ``[{x,y,label,color}, ...]`` (coords in ``[0, 1]``)."""
    out: list[dict[str, Any]] = []
    for p in value or []:
        if isinstance(p, dict):
            pt = {"x": _num(p.get("x")), "y": _num(p.get("y"))}
            if p.get("label") is not None:
                pt["label"] = str(p["label"])
            if p.get("color"):
                pt["color"] = str(p["color"])
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            pt = {"x": _num(p[0]), "y": _num(p[1])}
        else:
            continue
        out.append(pt)
    return out


def _to_masks(value: Any) -> list[dict[str, Any]]:
    """Normalise masks to ``[{src, opacity}, ...]`` - each an overlay image (a
    URL/``data:`` URI or PNG ``bytes``) drawn over the base image with an alpha."""
    out: list[dict[str, Any]] = []
    for m in value or []:
        if isinstance(m, dict):
            src = _image_src(m.get("src"))
            opacity = _num(m.get("opacity", 0.5), 0.5)
        else:
            src = _image_src(m)
            opacity = 0.5
        if src:
            out.append({"src": src, "opacity": opacity})
    return out


class ImageOverlay(Component):
    """An image with vector overlays drawn on top (ADR-0020): the read-only display
    path for detection boxes, segmentation masks, and keypoints.

    The base image is a ``source`` (URL / ``data:`` URI / PNG ``bytes``, like
    ``Image``). ``boxes``, ``points``, and ``masks`` are reactive sources whose
    coordinates are **fractions of the image** (``[0, 1]``), so they line up at any
    rendered size. Because they are ordinary reactive props, streaming a model's
    output per frame is a prop update over the existing ``patch`` op - no
    ``protocol_version`` bump. Display only (the model produces the shapes; the shell
    draws them); interactive annotation - the user *drawing* boxes - is the ADR-0020
    step-two follow-up.

    - ``boxes``: ``{x, y, w, h, label?, color?, score?}`` (or an ``(x, y, w, h)`` tuple).
    - ``points``: ``{x, y, label?, color?}`` (or an ``(x, y)`` tuple).
    - ``masks``: an overlay image (URL / ``data:`` / bytes) or ``{src, opacity?}``.
    """

    type = "imageoverlay"

    def __init__(
        self,
        source: Source,
        *,
        boxes: Source = None,
        points: Source = None,
        masks: Source = None,
        alt: str = "",
    ) -> None:
        super().__init__()
        self._source = source
        self._boxes = boxes
        self._points = points
        self._masks = masks
        self._alt = alt

    def static_props(self) -> dict[str, Any]:
        return {"alt": self._alt}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        props: dict[str, Callable[[], Any]] = {
            "src": lambda: _image_src(_read(self._source)),
            "boxes": lambda: _to_boxes(_read(self._boxes)),
            "points": lambda: _to_points(_read(self._points)),
            "masks": lambda: _to_masks(_read(self._masks)),
        }
        return props


class Plot(Component):
    """A rendered figure, shown as an image (R5).

    Accepts a Matplotlib ``Figure`` (duck-typed on ``savefig`` -- no hard
    dependency), raw PNG ``bytes``, or a URL / ``data:`` URI string, in a signal or
    plain. The figure is rasterised to a PNG ``data:`` URI on the Python side, so
    nothing extra is needed in the browser and it rounds-trips like an image.
    """

    type = "image"  # reuses the shell's <img> renderer

    def __init__(self, source: Source, *, alt: str = "plot") -> None:
        super().__init__()
        self._source = source
        self._alt = alt

    def static_props(self) -> dict[str, Any]:
        return {"alt": self._alt}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"src": lambda: _figure_src(_read(self._source))}


def _figure_src(value: Any) -> str:
    """A Matplotlib ``Figure`` -> PNG ``data:`` URI; otherwise defer to _image_src."""
    if value is not None and hasattr(value, "savefig"):
        buffer = io.BytesIO()
        value.savefig(buffer, format="png", bbox_inches="tight")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    return _image_src(value)


def _normalise_series(spec: Any) -> dict[str, Any]:
    """A series descriptor: ``"loss"`` or ``{"label","stroke"}`` -> a wire dict."""
    if isinstance(spec, dict):
        out: dict[str, Any] = {"label": str(spec.get("label", ""))}
        if spec.get("stroke"):
            out["stroke"] = str(spec["stroke"])
        return out
    return {"label": str(spec)}


def _to_rows(value: Any) -> list[list[Any]]:
    """Coerce chart data to a JSON-safe list of rows ``[[x, y0, y1, ...], ...]``."""
    if value is None:
        return []
    rows: list[list[Any]] = []
    for row in value:
        if isinstance(row, (list, tuple)):
            rows.append([_json_safe(v) for v in row])
        else:
            rows.append([_json_safe(row)])
    return rows


class Chart(Component):
    """An interactive, client-side chart (ADR-0018, hybrid charting).

    Where ``Plot`` rasterises a figure to a PNG on the Python side (the zero-JS
    static path), ``Chart`` sends its data as ordinary reactive props and the shell's
    bundled uPlot draws it in the browser -- so zoom (drag on the x-axis), hover, and
    live updates all run client-side, with no PNG per frame. It is a line /
    time-series chart: ``series`` names the y-columns, and the data is a list of rows
    ``[[x, y0, y1, ...], ...]`` (x first, then one value per series).

    Two ways to drive it:

    - **Reactive** -- pass ``data`` as a ``Signal`` / callable / list; setting it
      replaces the whole dataset (good for a static chart, or one recomputed from
      inputs).
    - **Streaming** -- leave ``data`` unset and call :meth:`push` (or :meth:`extend`)
      to append points. Each call emits an *append* patch carrying only the new
      row(s), so a live curve grows at O(point) on the wire, the same way
      ``StreamText`` streams text. :meth:`clear` resets it. ``snapshot`` always
      carries the full accumulated data, so a fresh connect or a resume re-renders
      the whole curve (ADR-0011).

    Example (a streaming loss curve fed from a training loop, ADR-0009)::

        chart = Chart(series=["loss"], title="Training loss", x_label="step")

        async def train():
            chart.clear()
            for step, loss in enumerate(run_epoch()):
                chart.push(step, loss)
                await asyncio.sleep(0)
    """

    type = "chart"

    def __init__(
        self,
        data: Source = None,
        *,
        series: list[Any] | None = None,
        title: str = "",
        x_label: str = "",
        y_label: str = "",
        height: int = 240,
        points: bool = False,
    ) -> None:
        super().__init__()
        self._reactive = data is not None
        self._data = data
        self._buffer: list[list[Any]] = []
        self._series = [_normalise_series(s) for s in (series or [])]
        self._title = title
        self._x_label = x_label
        self._y_label = y_label
        self._height = int(height)
        self._points = bool(points)
        self._session: Session | None = None

    def bind(self, session: Session) -> None:
        """Called by the session during wiring so push/extend/clear can emit patches."""
        self._session = session

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {
            "series": self._series,
            "title": self._title,
            "xLabel": self._x_label,
            "yLabel": self._y_label,
            "height": self._height,
            "points": self._points,
        }
        if not self._reactive:
            # Streaming mode: carry the accumulated data in the snapshot so a fresh
            # connect / resume re-renders the full curve.
            props["data"] = [list(row) for row in self._buffer]
        return props

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        if self._reactive:
            return {"data": lambda: _to_rows(_read(self._data))}
        return {}

    # -- streaming API (only when data= is unset) ----------------------------

    def _guard_streaming(self) -> None:
        if self._reactive:
            raise TypeError(
                "push/extend/clear are for a streaming Chart; this one has reactive data="
            )

    def push(self, *row: Any) -> None:
        """Append one point ``(x, y0, y1, ...)`` and emit an append delta."""
        self._guard_streaming()
        point = [_json_safe(v) for v in row]
        self._buffer.append(point)
        if self._session is not None:
            self._session.emit_append(self.id, "data", [point])

    def extend(self, rows: Any) -> None:
        """Append several points at once, as a single append patch."""
        self._guard_streaming()
        batch = [[_json_safe(v) for v in row] for row in rows]
        if not batch:
            return
        self._buffer.extend(batch)
        if self._session is not None:
            self._session.emit_append(self.id, "data", batch)

    def clear(self) -> None:
        """Reset the accumulated points (emits a props replace)."""
        self._guard_streaming()
        self._buffer = []
        if self._session is not None:
            self._session.emit_props(self.id, {"data": []})


def _to_columns(value: Any) -> list[list[Any]]:
    """Coerce a 2-D field to a JSON-safe list of columns ``[[y0, y1, ...], ...]``."""
    if value is None:
        return []
    cols: list[list[Any]] = []
    for col in value:
        cols.append([_json_safe(v) for v in col])
    return cols


class Heatmap(Component):
    """A client-side heatmap / 2-D field (ADR-0019): spectrograms, heatmaps, maps.

    The interactive/real-time counterpart to a server-PNG ``Plot`` of a raster: the
    2-D field rides ordinary reactive props and the shell's canvas renderer draws it
    (no PNG per frame, no ``protocol_version`` bump). The field ``z`` is **column-major**
    -- a list of columns, ``z[x][y]`` -- so a streaming spectrogram appends one new
    column (a time slice) per frame via the append op at O(column), the same path
    ``Chart``/``StreamText`` use. The shell draws column ``x`` at horizontal position
    ``x`` and colours cell ``(x, y)`` by ``z[x][y]`` through ``colormap``.

    Two ways to drive it, like ``Chart``:

    - **Reactive** -- pass ``z`` as a ``Signal`` / callable / list of columns; setting
      it replaces the whole field (a confusion matrix, an attention map).
    - **Streaming** -- leave ``z`` unset and call :meth:`push_column` (or
      :meth:`extend`) to append time slices (a live spectrogram); :meth:`clear`
      resets. ``snapshot`` carries the full field for a resume.

    ``zmin`` / ``zmax`` fix the colour scale (else it auto-scales in the browser);
    ``colormap`` is one of the shell's built-ins (``"magma"``, ``"viridis"``,
    ``"gray"``).
    """

    type = "heatmap"

    def __init__(
        self,
        z: Source = None,
        *,
        colormap: str = "magma",
        zmin: float | None = None,
        zmax: float | None = None,
        title: str = "",
        x_label: str = "",
        y_label: str = "",
        height: int = 240,
    ) -> None:
        super().__init__()
        self._reactive = z is not None
        self._z = z
        self._buffer: list[list[Any]] = []
        self._colormap = colormap
        self._zmin = zmin
        self._zmax = zmax
        self._title = title
        self._x_label = x_label
        self._y_label = y_label
        self._height = int(height)
        self._session: Session | None = None

    def bind(self, session: Session) -> None:
        """Called by the session during wiring so push/extend/clear can emit patches."""
        self._session = session

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {
            "colormap": self._colormap,
            "zmin": self._zmin,
            "zmax": self._zmax,
            "title": self._title,
            "xLabel": self._x_label,
            "yLabel": self._y_label,
            "height": self._height,
        }
        if not self._reactive:
            props["z"] = [list(col) for col in self._buffer]
        return props

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        if self._reactive:
            return {"z": lambda: _to_columns(_read(self._z))}
        return {}

    # -- streaming API (only when z= is unset) -------------------------------

    def _guard_streaming(self) -> None:
        if self._reactive:
            raise TypeError(
                "push_column/extend/clear are for a streaming Heatmap; this one has reactive z="
            )

    def push_column(self, column: Any) -> None:
        """Append one column (a time slice) and emit an append delta."""
        self._guard_streaming()
        col = [_json_safe(v) for v in column]
        self._buffer.append(col)
        if self._session is not None:
            self._session.emit_append(self.id, "z", [col])

    def extend(self, columns: Any) -> None:
        """Append several columns at once, as a single append patch."""
        self._guard_streaming()
        batch = [[_json_safe(v) for v in col] for col in columns]
        if not batch:
            return
        self._buffer.extend(batch)
        if self._session is not None:
            self._session.emit_append(self.id, "z", batch)

    def clear(self) -> None:
        """Reset the accumulated field (emits a props replace)."""
        self._guard_streaming()
        self._buffer = []
        if self._session is not None:
            self._session.emit_props(self.id, {"z": []})


class DataFrame(Component):
    """A tabular display bound to a source (R5).

    Accepts a pandas ``DataFrame`` (duck-typed -- no hard dependency), a
    ``{"columns": [...], "rows": [[...], ...]}`` dict, or a list of row dicts, in a
    signal or plain. Set it from Python and the rendered table updates.
    """

    type = "dataframe"

    def __init__(self, source: Source, *, label: str = "") -> None:
        super().__init__()
        self._source = source
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"data": lambda: _to_table(_read(self._source))}


class Table(Component):
    """An interactive table (ADR-0021): sort, page, and select, on reactive props.

    A superset of ``DataFrame``'s display - it takes the same source (a pandas frame,
    a ``{"columns","rows"}`` dict, or a list of row dicts) - adding interaction the
    shell handles client-side: click a header to sort, page through large data, and
    click a row to select it. Selection round-trips: bind ``selected`` to a
    ``Signal[int]`` (the selected row index, or ``None``) and a click sets it, so the
    selection drives the rest of the app (the dashboard pattern: pick a row -> charts
    update). Sorting and paging are client-side (no round-trip), so the table stays
    responsive; the data still rides one reactive prop, so no ``protocol_version``
    bump. Use ``DataFrame`` when you only need to show a table.
    """

    type = "table"

    def __init__(
        self,
        source: Source,
        *,
        page_size: int = 0,
        selected: Signal[int] | None = None,
        label: str = "",
    ) -> None:
        super().__init__()
        self._source = source
        self._page_size = int(page_size)
        self._selected = selected
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {
            "pageSize": self._page_size,
            "selectable": self._selected is not None,
            "label": self._label,
        }

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        props: dict[str, Callable[[], Any]] = {"data": lambda: _to_table(_read(self._source))}
        if self._selected is not None:
            props["value"] = lambda: (
                None if self._selected.value is None else int(self._selected.value)
            )
        return props

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "select" and "index" in payload and self._selected is not None:
            self._selected.set(int(payload["index"]))
            return True
        return False


class Stat(Component):
    """A metric / KPI card (ADR-0021): a big value with a label and optional delta.

    The tile dashboards pair with a ``Table``. ``value`` and ``delta`` are sources
    (signal / callable / plain); the shell colours the delta green when it does not
    start with ``-`` and red when it does (so pass e.g. ``"+2.4%"`` / ``"-1.1%"``).
    Display only; no new protocol capability.
    """

    type = "stat"

    def __init__(
        self, value: Source, *, label: str = "", delta: Source = None, help: str = ""
    ) -> None:
        super().__init__()
        self._value = value
        self._label = label
        self._delta = delta
        self._help = help

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label, "help": self._help}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        props: dict[str, Callable[[], Any]] = {"value": lambda: str(_read(self._value))}
        if self._delta is not None:
            props["delta"] = lambda: None if _read(self._delta) is None else str(_read(self._delta))
        return props


def _json_safe(value: Any) -> Any:
    """Coerce a cell value to something JSON can carry (e.g. a numpy scalar)."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):  # numpy / pandas scalar
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    return str(value)


def _to_table(source: Any) -> dict[str, Any]:
    """Normalise a table-ish value to ``{"columns": [...], "rows": [[...], ...]}``."""
    if source is None:
        return {"columns": [], "rows": []}
    # pandas DataFrame (duck-typed): to_dict(orient="split") -> {columns, data}.
    if hasattr(source, "columns") and hasattr(source, "to_dict"):
        split = source.to_dict(orient="split")
        columns = [str(c) for c in split.get("columns", [])]
        rows = [[_json_safe(v) for v in row] for row in split.get("data", [])]
        return {"columns": columns, "rows": rows}
    if isinstance(source, dict) and "columns" in source and "rows" in source:
        columns = [str(c) for c in source["columns"]]
        rows = [[_json_safe(v) for v in row] for row in source["rows"]]
        return {"columns": columns, "rows": rows}
    if isinstance(source, (list, tuple)) and source and isinstance(source[0], dict):
        columns = list(source[0].keys())
        rows = [[_json_safe(row.get(c)) for c in columns] for row in source]
        return {"columns": [str(c) for c in columns], "rows": rows}
    raise TypeError(f"DataFrame cannot render a {type(source).__name__}")


class StreamText(Component):
    """A text container that grows token-by-token over the SSE channel (R5).

    Unlike a signal-bound ``Text``, a StreamText holds a plain accumulating
    string (not a signal), so:

    - ``snapshot()`` always carries the full text so far -- a fresh connect or a
      resume that falls back to ``init`` re-renders correctly (ADR-0011);
    - ``feed(token)`` emits an *append* patch carrying only the delta, so the wire
      cost is O(token), not O(text) per token.

    Feed it from a plain async generator the caller wraps (ADR-0009)::

        stream = StreamText()

        async def on_generate():
            stream.reset()
            async for token in my_llm(prompt.value):
                stream.feed(token)
    """

    type = "streamtext"

    def __init__(self, *, label: str = "") -> None:
        super().__init__()
        self._text = ""
        self._label = label
        self._session: Session | None = None

    def bind(self, session: Session) -> None:
        """Called by the session during wiring so feed/reset can emit patches."""
        self._session = session

    @property
    def text(self) -> str:
        return self._text

    def static_props(self) -> dict[str, Any]:
        # Current text (not truly static) so init/resume snapshots are complete.
        return {"text": self._text, "label": self._label}

    def feed(self, token: str) -> None:
        """Append a token: grows the text and emits an append patch to clients."""
        token = str(token)
        if not token:
            return
        self._text += token
        if self._session is not None:
            self._session.emit_append(self.id, "text", token)

    def reset(self) -> None:
        """Clear the accumulated text (e.g. before a new generation)."""
        self._text = ""
        if self._session is not None:
            self._session.emit_props(self.id, {"text": ""})


class Progress(Component):
    """A progress bar bound to a source (R5, Slice A).

    Pass a value in ``[0, max]`` (a signal, number, or callable) to show
    determinate progress; pass ``None`` (the default) for an indeterminate bar that
    just signals "working". Set the value from Python and the bar updates reactively.
    """

    type = "progress"

    def __init__(self, value: Source = None, *, max: float = 1.0, label: str = "") -> None:
        super().__init__()
        self._value = value
        self._max = max
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"max": self._max, "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: _progress_value(_read(self._value))}


def _progress_value(value: Any) -> float | None:
    """Coerce a progress value to a float, or ``None`` for an indeterminate bar."""
    if value is None:
        return None
    return float(value)


class Spinner(Component):
    """An indeterminate busy indicator (Slice A).

    ``active`` (a signal or bool) toggles it: while true the shell shows a spinner
    (and the optional ``label``); while false it renders nothing, so it can gate on
    a "loading" signal.
    """

    type = "spinner"

    def __init__(self, *, active: Source = True, label: str = "") -> None:
        super().__init__()
        self._active = active
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"active": lambda: bool(_read(self._active))}


# -- File upload (ADR-0017) --------------------------------------------------
#
# Upload is the one input whose payload is binary, not JSON, so it does not ride
# ``POST /api/event``: the shell posts the file(s) to a separate multipart route
# (``POST /api/upload``), and the app hands the bytes to this component's handler
# as ``UploadedFile`` objects. Everything after that is ordinary indah -- the
# handler mutates signals / feeds a StreamText and results flow back over SSE.


@dataclass
class UploadedFile:
    """One uploaded file's bytes and metadata, handed to an ``Upload`` handler.

    ``data`` is the raw bytes; ``text()`` decodes them and ``size`` is their length.
    The handler owns what it does with the bytes (ADR-0009/Q-sec).
    """

    filename: str
    content_type: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)

    def text(self, encoding: str = "utf-8") -> str:
        return self.data.decode(encoding)


class Upload(Component):
    """A file input (image / audio / any file), ADR-0017.

    ``on_upload`` is a plain callable the caller supplies (ADR-0009). It receives an
    :class:`UploadedFile` (or a ``list`` of them when ``multiple=True``); it may be
    sync or ``async def`` (an async handler runs in the background like a Button's,
    so a slow model never blocks the request). ``accept`` is an HTML accept hint
    (e.g. ``"image/*"``) and ``multiple`` allows selecting several files; both are UI
    hints -- the hard size cap is enforced server-side by the upload route.
    """

    type = "upload"

    def __init__(
        self,
        on_upload: Callable[[Any], Any] | None = None,
        *,
        label: str = "",
        accept: str = "",
        multiple: bool = False,
    ) -> None:
        super().__init__()
        self._on_upload = on_upload
        self._label = label
        self._accept = accept
        self._multiple = multiple

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label, "accept": self._accept, "multiple": bool(self._multiple)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        # The upload route dispatches a synthetic "upload" event whose payload
        # carries the parsed UploadedFile objects (not JSON) -- so it reuses the
        # whole session dispatch/sink/error path like any other event.
        if event == "upload":
            files: list[UploadedFile] = list(payload.get("files", []))
            if self._on_upload is not None:
                arg: Any = files if self._multiple else (files[0] if files else None)
                result = self._on_upload(arg)
                if inspect.iscoroutine(result):
                    return result  # async handler: awaited as a background task
            return True  # always handled (a no-op without a handler), never 400s
        return False


@dataclass
class DownloadFile:
    """Bytes to hand back to the user, with the filename the browser saves as."""

    data: bytes
    filename: str = "download"
    media_type: str = "application/octet-stream"


class Download(Component):
    """A download link that hands the user a file back (ADR-0017).

    Bind ``source`` to a signal/callable/plain value that yields one of:

    - a URL string (served elsewhere) -- passed through as the link target;
    - raw ``bytes`` -- served by indah at a per-session blob URL (``filename`` and
      ``media_type`` name the download);
    - a :class:`DownloadFile` -- bytes plus their own filename/media type.

    Set the source from Python (e.g. after a run produces a CSV or an image) and the
    link updates; ``None`` yields an inert link. Serving is per-session (ADR-0010),
    so one viewer's file is not reachable from another's session.
    """

    type = "download"

    def __init__(
        self,
        source: Source = None,
        *,
        label: str = "Download",
        filename: str = "download",
        media_type: str = "application/octet-stream",
    ) -> None:
        super().__init__()
        self._source = source
        self._label = label
        self._filename = filename
        self._media_type = media_type
        self._session: Session | None = None
        self._cache: tuple[Any, tuple[str, str]] | None = None

    def bind(self, session: Session) -> None:
        """Called by the session during wiring so bytes can be served per-session."""
        self._session = session

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {
            "href": lambda: self._resolve()[0],
            "filename": lambda: self._resolve()[1],
        }

    def _resolve(self) -> tuple[str, str]:
        """Coerce the source to ``(href, filename)``, serving bytes if needed.

        Cached by the source value so repeated getter calls (the two props, plus
        every snapshot) do not re-serve identical bytes under a fresh token.
        """
        value = _read(self._source)
        if self._cache is not None and _same_download(self._cache[0], value):
            return self._cache[1]

        if value is None:
            result = ("", self._filename)
        elif isinstance(value, DownloadFile):
            result = self._serve(value.data, value.filename, value.media_type)
        elif isinstance(value, (bytes, bytearray)):
            result = self._serve(bytes(value), self._filename, self._media_type)
        else:
            result = (str(value), self._filename)  # already a URL

        self._cache = (value, result)
        return result

    def _serve(self, data: bytes, filename: str, media_type: str) -> tuple[str, str]:
        if self._session is None:
            return ("", filename)  # not wired yet (e.g. serialised standalone)
        return (self._session.serve_file(data, filename=filename, media_type=media_type), filename)


def _same_download(a: Any, b: Any) -> bool:
    """Value-equality for the download cache, treating bytes/bytearray by content."""
    if isinstance(a, (bytes, bytearray)) and isinstance(b, (bytes, bytearray)):
        return bytes(a) == bytes(b)
    return a is b or a == b


# -- Layout containers (ADR-0015) --------------------------------------------
#
# These arrange existing child nodes, so they need no new protocol capability:
# the tree still serialises as nodes with ``children`` and their show/active state
# rides ordinary reactive props merged by the existing ``patch`` op. Layout itself
# is CSS in the shell driven by these static props (columns, gap, orientation).


def _as_signal(value: Any, default: Any, cast: Callable[[Any], Any]) -> Signal:
    """Return ``value`` if it is a Signal, else wrap a plain value in one.

    Lets ``Tabs``/``Expander`` accept either a caller's Signal (so the app drives
    the active/open state) or a plain literal (so the container is self-contained
    and the shell's clicks still round-trip through the reactive graph).
    """
    if isinstance(value, Signal):
        return value
    return Signal(cast(default if value is None else value))


class Row(Component):
    """A horizontal flex row of children, wrapping onto the next line as needed."""

    type = "row"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        gap: str = "1rem",
        wrap: bool = True,
        align: str = "stretch",
    ) -> None:
        super().__init__(children)
        self._gap = gap
        self._wrap = wrap
        self._align = align

    def static_props(self) -> dict[str, Any]:
        return {"gap": self._gap, "wrap": bool(self._wrap), "align": self._align}


class Grid(Component):
    """An N-column grid of children that collapses to one column at phone width."""

    type = "grid"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        columns: int = 2,
        gap: str = "1rem",
    ) -> None:
        super().__init__(children)
        self._columns = columns
        self._gap = gap

    def static_props(self) -> dict[str, Any]:
        return {"columns": int(self._columns), "gap": self._gap}


class Tabs(Component):
    """A tabbed container: one child panel shown at a time (ADR-0015).

    ``labels`` names the tabs (one per child); ``active`` is the index of the shown
    panel. Pass a ``Signal[int]`` to drive it from Python, or leave it and the
    container keeps its own; either way a tab click round-trips through the graph
    and the shell re-renders only the active panel.
    """

    type = "tabs"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        labels: list[Any],
        active: Signal[int] | int | None = None,
    ) -> None:
        super().__init__(children)
        self._labels = [str(label) for label in labels]
        self._active = _as_signal(active, 0, int)

    def static_props(self) -> dict[str, Any]:
        return {"labels": self._labels}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"active": lambda: int(self._active.value)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "select" and "index" in payload:
            self._active.set(int(payload["index"]))
            return True
        return False


class Sidebar(Component):
    """A persistent side region plus a main region (ADR-0015).

    The first child renders in the sidebar; the rest render in the main region.
    On a narrow screen the sidebar stacks above the main region.
    """

    type = "sidebar"


class Expander(Component):
    """A collapsible section: a labelled header that shows/hides its children.

    ``open`` is a reactive prop -- pass a ``Signal[bool]`` to drive it from Python,
    or a plain bool for the initial state. Toggling in the UI round-trips through
    the graph and the shell renders the children only while open.
    """

    type = "expander"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        label: str = "",
        open: Signal[bool] | bool = False,
    ) -> None:
        super().__init__(children)
        self._label = label
        self._open = _as_signal(open, False, bool)

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"open": lambda: bool(self._open.value)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "toggle":
            if "value" in payload:
                self._open.set(bool(payload["value"]))
            else:
                self._open.set(not self._open.value)
            return True
        return False


# -- Data-driven list (ADR-0016) ---------------------------------------------
#
# Growing/variable content (logs, search results, chat, galleries) is modelled as
# *data*, not as a growing subtree: the items live in one reactive prop and the
# shell renders each through a template. Add/remove/reorder is an ordinary prop
# change carried by the existing ``patch`` op -- no structural children op, no
# ``protocol_version`` bump. ``Chat`` and ``Gallery`` are specialisations the shell
# renders with a built-in template; the generic ``List`` renders each item with an
# ADR-0012 render spec (or as text when none is given).


def _to_items(value: Any) -> list[Any]:
    """Coerce a source value to a JSON-safe list of items (dicts or scalars)."""
    if value is None:
        return []
    out: list[Any] = []
    for item in value:
        if isinstance(item, dict):
            out.append({str(k): _json_safe(v) for k, v in item.items()})
        else:
            out.append(_json_safe(item))
    return out


class List(Component):
    """A data-driven list bound to a ``Signal[list]`` (ADR-0016).

    The items live in one reactive prop; set the signal to a new list to add,
    remove, or reorder (mutating in place will not notify -- assign a fresh list,
    e.g. ``items.set(items.value + [row])``). Pass an ``item`` render spec (the
    ADR-0012 vocabulary, binding each item's fields) to shape each row; without one
    each item renders as text. ``empty`` is shown when the list is empty.
    """

    type = "list"

    def __init__(
        self,
        items: Source,
        *,
        item: dict[str, Any] | RenderSpec | None = None,
        empty: str = "",
    ) -> None:
        super().__init__()
        self._items = items
        self._empty = empty
        if item is None:
            self._template: dict[str, Any] | None = None
        else:
            spec = item if isinstance(item, RenderSpec) else RenderSpec.model_validate(item)
            self._template = spec.validated().wire()

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {"empty": self._empty}
        if self._template is not None:
            props["template"] = self._template
        return props

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"items": lambda: _to_items(_read(self._items))}


def _to_messages(value: Any) -> list[dict[str, str]]:
    """Normalise chat messages to ``[{"role","content"}, ...]`` (both strings)."""
    if value is None:
        return []
    out: list[dict[str, str]] = []
    for message in value:
        if isinstance(message, dict):
            role = str(message.get("role", "assistant"))
            content = str(message.get("content", ""))
        elif isinstance(message, (tuple, list)) and len(message) == 2:
            role, content = str(message[0]), str(message[1])
        else:
            continue
        out.append({"role": role, "content": content})
    return out


class Chat(Component):
    """A chat transcript of role bubbles bound to a ``Signal[list]`` (ADR-0016).

    ``messages`` is a list of ``{"role","content"}`` (or ``(role, content)``) items;
    the shell renders one bubble per message and auto-scrolls to the newest. Bind
    ``pending`` to a ``Signal[str]`` to show a live, still-streaming assistant bubble
    while a reply is being generated (set it back to ``""`` once committed).
    """

    type = "chat"

    def __init__(self, messages: Source, *, pending: Source = None, label: str = "") -> None:
        super().__init__()
        self._messages = messages
        self._pending = pending
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {
            "messages": lambda: _to_messages(_read(self._messages)),
            "pending": lambda: str(_read(self._pending)) if self._pending is not None else "",
        }


def _to_images(value: Any) -> list[dict[str, str]]:
    """Normalise gallery images to ``[{"src","alt","caption"}, ...]``.

    Accepts a URL/``data:`` URI string, raw PNG ``bytes``, or a dict with ``src``
    (plus optional ``alt``/``caption``); reuses the ``Image`` source coercion.
    """
    if value is None:
        return []
    out: list[dict[str, str]] = []
    for image in value:
        if isinstance(image, dict):
            out.append(
                {
                    "src": _image_src(image.get("src")),
                    "alt": str(image.get("alt", "")),
                    "caption": str(image.get("caption", "")),
                }
            )
        else:
            out.append({"src": _image_src(image), "alt": "", "caption": ""})
    return out


class Gallery(Component):
    """An image grid bound to a ``Signal[list]`` (ADR-0016).

    ``images`` is a list of URL/``data:`` strings, PNG ``bytes``, or
    ``{"src","alt","caption"}`` dicts; the shell lays them out in ``columns``
    columns (collapsing on a phone). Set the signal to a new list to grow the grid.
    """

    type = "gallery"

    def __init__(self, images: Source, *, columns: int = 3, label: str = "") -> None:
        super().__init__()
        self._images = images
        self._columns = columns
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"columns": int(self._columns), "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"images": lambda: _to_images(_read(self._images))}


def walk(root: Component):
    """Yield every component in the tree, pre-order."""
    yield root
    for child in root.children:
        yield from walk(child)
