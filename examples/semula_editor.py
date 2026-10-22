"""The last three semula screens: an entry editor with a version conflict, a review card,
and a playground message stack (``make demo``, under Full apps).

    python examples/semula_editor.py        # prints a URL; open /ui/

Three tabs:

* **Entry** - edit a cached entry's request and response JSON, pin it, Save. "Simulate another
  editor" bumps the stored version behind your back, so the next Save opens a ``Modal`` with a
  ``Diff`` of their version against yours: keep yours or take theirs.
* **Review** - a flagged entry: a split ``Diff`` of the incoming response against the cached
  one, a score ``Badge``, Approve and Reject (with a confirm).
* **Playground** - a keyed ``List`` of messages (role ``select``, a textarea, remove), add and
  edit them freely, then Run to stream a reply into ``StreamText``.

What it shows (IND-E24): ``CodeEditor``, ``Switch``, ``Modal``, ``Diff``, ``Badge``,
``Button(confirm=)``, ``ctx.toast``, ``Tabs``, the keyed ``List`` with ``on_item``, and
``StreamText``. Nothing here is real semula data.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

import indah

THEME = indah.Theme(light={"primary": "#1f6feb"}, dark={"primary": "#79b8ff"})
ROLES = ["system", "user", "assistant"]

REQUEST = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Refund policy?"}]}
RESPONSE = {"answer": "Annual plans are refundable within 30 days.", "confidence": 0.91}
INCOMING = {"answer": "Annual plans are refundable within 14 days.", "confidence": 0.62}


def pretty(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


class EntryStore:
    """One cached entry with a version, shared by every tab, so another editor's save can
    land between a tab's load and its Save."""

    def __init__(self) -> None:
        self.version = 1
        self.request = pretty(REQUEST)
        self.response = pretty(RESPONSE)
        self.pinned = False

    def save(self, request: str, response: str, pinned: bool) -> int:
        self.request, self.response, self.pinned = request, response, pinned
        self.version += 1
        return self.version

    def other_editor(self) -> None:
        """Stand-in for a second human saving the same entry."""
        body = json.loads(self.response)
        body["answer"] = "Annual plans are refundable within 30 days, pro-rated."
        body["edited_by"] = "someone else"
        self.save(self.request, pretty(body), self.pinned)


REPLY = (
    "Annual plans can be refunded within 30 days of purchase. After that, you can cancel "
    "and keep access until the end of the term."
)

# One row of the playground. The option labels ride along as fields because a render spec
# gets its text from the item's own props.
ROW_SPEC: dict[str, Any] = {
    "tag": "div",
    "class": "pg-row",
    "children": [
        {
            "tag": "select",
            "bind": {"value": "role"},
            "on": {"change": {"event": "role"}},
            "children": [
                {"tag": "option", "attrs": {"value": r}, "text": f"label_{r}"} for r in ROLES
            ],
        },
        {"tag": "textarea", "bind": {"value": "content"}, "on": {"input": {"event": "content"}}},
        {"tag": "button", "literal": "Remove", "on": {"click": {"event": "remove"}}},
    ],
}


def message(n: int, role: str = "user", content: str = "") -> dict[str, Any]:
    return {
        "id": f"m{n}",
        "role": role,
        "content": content,
        **{f"label_{r}": r for r in ROLES},
    }


def build_editor_app(store: EntryStore) -> Any:
    def build(ctx: indah.Context) -> indah.Session:
        # -- Entry: edit, save, conflict ----------------------------------------------
        request = indah.Signal(store.request)
        response = indah.Signal(store.response)
        pinned = indah.Signal(store.pinned)
        loaded = indah.Signal(store.version)  # the version this tab loaded
        conflict = indah.Signal(False)

        def load_current() -> None:
            request.set(store.request)
            response.set(store.response)
            pinned.set(store.pinned)
            loaded.set(store.version)

        def commit() -> None:
            loaded.set(store.save(request.value, response.value, pinned.value))
            conflict.set(False)
            ctx.toast(f"Saved as version {loaded.value}", kind="success")

        def save() -> None:
            try:
                json.loads(request.value)
                json.loads(response.value)
            except ValueError as exc:
                ctx.toast(f"Not valid JSON: {exc}", kind="error")
                return
            if store.version != loaded.value:
                conflict.set(True)  # someone saved since this tab loaded
            else:
                commit()

        def take_theirs() -> None:
            load_current()
            conflict.set(False)
            ctx.toast("Loaded the latest version", kind="info")

        def other_editor() -> None:
            store.other_editor()
            ctx.toast("Another editor saved this entry", kind="warn")

        entry = indah.Column(
            children=[
                indah.Row(
                    children=[
                        indah.Text(lambda: f"Entry, loaded at version {loaded.value}"),
                        indah.Switch(pinned, label="Pinned"),
                    ]
                ),
                indah.CodeEditor(
                    request, label="Request (JSON)", height="12rem", format_button=True
                ),
                indah.CodeEditor(
                    response,
                    label="Response (JSON)",
                    height="12rem",
                    format_button=True,
                    on_save=save,  # Ctrl/Cmd-S
                ),
                indah.Row(
                    children=[
                        indah.Button("Save", save),
                        indah.Button("Simulate another editor", other_editor, variant="ghost"),
                    ]
                ),
                indah.Modal(
                    title="This entry changed while you were editing",
                    open=conflict,
                    size="lg",
                    children=[
                        indah.Diff(
                            lambda: store.response,
                            response,
                            labels=("their version", "your edit"),
                            mode="unified",
                        ),
                        indah.Row(
                            children=[
                                indah.Button("Keep mine", commit),
                                indah.Button("Take theirs", take_theirs, variant="tonal"),
                                indah.Button(
                                    "Cancel", lambda: conflict.set(False), variant="ghost"
                                ),
                            ]
                        ),
                    ],
                ),
            ]
        )

        # -- Review: a flagged entry --------------------------------------------------
        verdict = indah.Signal("pending")
        review = indah.Column(
            children=[
                indah.Row(
                    children=[
                        indah.Text("Flagged: the new answer disagrees with the cached one"),
                        indah.Badge("score 0.62", tone="warn"),
                        indah.Badge(lambda: verdict.value, tone="info"),
                    ]
                ),
                indah.Diff(RESPONSE, INCOMING, labels=("cached", "incoming")),
                indah.Row(
                    children=[
                        indah.Button(
                            "Approve", lambda: (verdict.set("approved"), ctx.toast("Approved"))
                        ),
                        indah.Button(
                            "Reject",
                            lambda: (verdict.set("rejected"), ctx.toast("Rejected", kind="warn")),
                            variant="ghost",
                            confirm="Reject this answer?",
                        ),
                    ]
                ),
            ]
        )

        # -- Playground: a keyed message stack and a streamed reply -------------------
        messages = indah.Signal([message(1, "system", "You are terse."), message(2, "user", "Hi")])
        counter = {"n": 2}
        out = indah.StreamText(label="Reply")

        def on_item(key: Any, event: str, value: Any) -> None:
            rows = messages.value
            if event == "remove":
                messages.set([r for r in rows if r["id"] != key])
            elif event in ("role", "content"):
                messages.set([{**r, event: value} if r["id"] == key else r for r in rows])

        def add() -> None:
            counter["n"] += 1
            messages.set([*messages.value, message(counter["n"])])

        async def run() -> None:
            out.reset()
            for word in REPLY.split(" "):
                out.feed(word + " ")
                await asyncio.sleep(0.03)

        playground = indah.Column(
            children=[
                indah.List(
                    messages, key="id", item=ROW_SPEC, on_item=on_item, empty="No messages yet"
                ),
                indah.Row(
                    children=[
                        indah.Button("Add message", add, variant="tonal"),
                        indah.Button("Run", run),
                        indah.Text(lambda: f"{len(messages.value)} messages"),
                    ]
                ),
                out,
            ]
        )

        return indah.Session(
            indah.Tabs([entry, review, playground], labels=["Entry", "Review", "Playground"])
        )

    return indah.create_app(
        session_factory=build, title="semula", theme=THEME, spa=True, proxy_flush=False
    )


def build_app() -> Starlette:
    """A semula-shaped parent app: ``/v1/health`` and the editor mounted at ``/ui``."""
    store = EntryStore()
    ui = build_editor_app(store)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": store.version})

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse("ui/")

    app = Starlette(routes=[Route("/", root), Route("/v1/health", health), Mount("/ui", app=ui)])
    app.state.store = store
    app.state.ui = ui
    return app


if __name__ == "__main__":
    indah.launch(build_app())
