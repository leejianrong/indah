"""The server half, inside Pyodide: one indah Session and Hub, no ASGI app and no sockets.

It does what ``indah.app._open_stream`` and ``_event`` do, minus HTTP: build the session from the
session store, send ``init``, forward every message the hub publishes, and dispatch client events.
The worker calls ``init(page_id, emit)``, then ``connect(sid)`` and ``event(body)``.
"""

import asyncio
import importlib
import json
import pkgutil

import indah
from indah.protocol import init_message, patch_message
from indah.session_store import InMemorySessionStore

_store = None
_emit = None
_pumps = {}


def _find_page(spec):
    """``chapter-slug/page-slug`` (the Studio's own URL form) to its Page."""
    import examples.studio.chapters as chapters

    want_chapter, want_page = spec.split("/", 1)
    for info in pkgutil.iter_modules(chapters.__path__):
        try:
            mod = importlib.import_module(f"examples.studio.chapters.{info.name}")
        except Exception:  # a chapter that needs more than the browser has is skipped
            continue
        chapter = getattr(mod, "CHAPTER", None)
        if chapter is not None and chapter.slug == want_chapter:
            for page in chapter.pages:
                if page.slug == want_page:
                    return page
    raise KeyError(f"no Studio page {spec!r}")


def init(page_id, emit):
    """Build the store for one Studio page. ``emit(text)`` sends one frame to the page."""
    global _store, _emit
    _emit = emit
    page = _find_page(page_id)

    def build(ctx):
        return indah.Session(page.build(ctx))

    _store = InMemorySessionStore(build)


def init_code(code, emit):
    """The docs Playground (IND-83): run the reader's own snippet, in their browser's worker.

    The contract is the Studio playground's: define ``build()`` returning an indah component
    (``indah`` is already imported). Returns ``""`` when the page is ready to connect, otherwise a
    short error text (a traceback from the snippet's own lines) for the page to show. A snippet
    that never returns blocks this worker; the page notices the missing heartbeat and terminates it.
    """
    global _store, _emit
    _emit = emit
    namespace = {"indah": indah, "__name__": "playground"}
    try:
        exec(compile(code, "<playground>", "exec"), namespace)  # noqa: S102 - in the browser
    except BaseException as exc:  # the reader's code: report everything
        return _explain(exc)
    build = namespace.get("build")
    if not callable(build):
        return "Define a function `build()` that returns an indah component."
    try:
        probe = build()
    except BaseException as exc:
        return _explain(exc)
    if not isinstance(probe, indah.Component):
        return f"build() returned {type(probe).__name__}, not an indah component."

    def make(ctx):
        return indah.Session(build())

    _store = InMemorySessionStore(make)
    return ""


def _explain(exc):
    """A traceback that starts at the snippet, not at this module's ``exec`` call."""
    import traceback

    if isinstance(exc, SyntaxError):
        return "".join(traceback.format_exception_only(type(exc), exc)).rstrip()
    tb = exc.__traceback__
    while tb is not None and tb.tb_frame.f_code.co_filename != "<playground>":
        tb = tb.tb_next
    return "".join(traceback.format_exception(type(exc), exc, tb, limit=6)).rstrip()


def connect(sid):
    handle = _store.get_or_create(sid)
    hub, session = handle.hub, handle.session
    queue = hub.subscribe()
    chrome = getattr(session.ctx, "_chrome", None)  # added in 0.6.0; older releases have none
    try:
        message = init_message(session.snapshot(), chrome=chrome() if chrome else None)
    except TypeError:
        message = init_message(session.snapshot())
    _emit(json.dumps(message))

    async def pump():
        while True:
            _, message = await queue.get()
            _emit(json.dumps(message))

    old = _pumps.pop(sid, None)
    if old is not None:
        old.cancel()
    _pumps[sid] = asyncio.ensure_future(pump())


def event(body):
    raw = json.loads(body)
    handle = _store.get(raw.get("sid"))
    if handle is None:
        return
    result = handle.session.dispatch(raw["component"], raw["event"], raw.get("payload") or {})
    if result is None or result.forbidden:
        return
    if result.coro is not None:
        handle.session.spawn(result.coro)
    if result.changes:
        handle.hub.publish(patch_message(result.changes))
    if result.transient:
        handle.hub.publish(patch_message(result.transient), record=False)
