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
    type = "button"

    def __init__(self, label: Source, on_click: Callable[[], Any] | None = None) -> None:
        super().__init__()
        self._label = label
        self._on_click = on_click

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
