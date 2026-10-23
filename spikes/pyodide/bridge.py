"""The server half, inside Pyodide: one indah Session and Hub, no ASGI app and no sockets.

It does what `indah.app._open_stream` and `_event` do, minus HTTP: build the session from the
session store, send `init`, forward every message the hub publishes, and dispatch client events.
"""

import asyncio
import importlib
import json
import pkgutil

import examples.studio.chapters as _chapters
import indah
import js
from indah.protocol import init_message, patch_message
from indah.session_store import InMemorySessionStore

import __main__


def _find_page(spec):
    """``chapter-slug/page-slug`` (the Studio's own URL form) to its Page."""
    want_chapter, want_page = spec.split("/", 1)
    for info in pkgutil.iter_modules(_chapters.__path__):
        try:
            mod = importlib.import_module(f"examples.studio.chapters.{info.name}")
        except Exception:  # a chapter that needs more than the browser has is skipped
            continue
        chapter = getattr(mod, "CHAPTER", None)
        if chapter is not None and chapter.slug == want_chapter:
            return next(p for p in chapter.pages if p.slug == want_page)
    raise KeyError(spec)


PAGE = _find_page(__main__.PAGE_SPEC)


def _build(ctx):
    return indah.Session(PAGE.build(ctx))


store = InMemorySessionStore(_build)
_pumps = {}


def connect(sid):
    handle = store.get_or_create(sid)
    hub, session = handle.hub, handle.session
    queue = hub.subscribe()
    chrome = getattr(session.ctx, "_chrome", None)  # added in 0.6.0; older releases have none
    try:
        message = init_message(session.snapshot(), chrome=chrome() if chrome else None)
    except TypeError:
        message = init_message(session.snapshot())
    js.emit(json.dumps(message))

    async def pump():
        while True:
            _, message = await queue.get()
            js.emit(json.dumps(message))

    _pumps[sid] = asyncio.ensure_future(pump())


def event(body):
    raw = json.loads(body)
    handle = store.get(raw.get("sid"))
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
