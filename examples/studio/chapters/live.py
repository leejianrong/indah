"""Chapter 6: live data, streaming and the reactive helpers."""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import AsyncIterator
from typing import Any

import indah

from ..core import Chapter, Page

# -- App-level feed: a producer in the chapter's lifespan publishes seeded fake events --------

EVENTS = indah.Topic("studio-events", replay=200)  # keeps the last 200 for late tabs
KINDS = ["deploy", "alert", "login", "backup"]
KIND_TONES = {"deploy": "info", "alert": "err", "login": "ok", "backup": "neutral"}


async def produce(topic: indah.Topic, *, interval: float = 0.4, seed: int = 11) -> None:
    rng = random.Random(seed)
    n = 0
    while True:
        n += 1
        topic.publish({"id": f"ev-{n:05d}", "kind": rng.choice(KINDS), "value": rng.randint(1, 99)})
        await asyncio.sleep(interval)


@contextlib.asynccontextmanager
async def lifespan(_chapter: Any) -> AsyncIterator[None]:
    for n in range(1, 21):  # a little history, so a page is never empty on first open
        EVENTS.publish({"id": f"ev-h{n:03d}", "kind": KINDS[n % 4], "value": n})
    task = asyncio.create_task(produce(EVENTS))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


EVENT_COLUMNS = [
    indah.Col("id", kind="mono"),
    indah.Col("kind", kind="badge", tones=KIND_TONES),
    indah.Col("value", kind="number"),
]


# -- Topic ---------------------------------------------------------------------------------------


def topic(ctx: indah.Context) -> indah.Component:
    rows = ctx.tail(EVENTS, limit=100)  # a Stream seeded from the topic's history
    newest = ctx.latest(EVENTS)  # a signal holding the newest item
    return indah.Column(
        children=[
            indah.Text(lambda: f"Newest event: {newest.value['id']} ({newest.value['kind']})"),
            indah.Table(rows=rows, key="id", columns=EVENT_COLUMNS, height="16rem", follow=True),
        ]
    )


def topic_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator("tbody tr").first).to_be_visible()
    newest = page.get_by_text("Newest event: ").inner_text()
    page.wait_for_timeout(1500)  # the producer publishes every 0.4 s
    assert page.get_by_text("Newest event: ").inner_text() != newest


# -- Bounded streams -----------------------------------------------------------------------------


def bounded(ctx: indah.Context) -> indah.Component:
    last5 = ctx.tail(EVENTS, limit=5)  # only the newest five are kept, on the server and in the tab
    seen = indah.Signal(0)
    stop = indah.Signal(False)
    ctx.on_close(EVENTS.subscribe(lambda _e: None if stop.value else seen.set(seen.value + 1)))
    return indah.Column(
        children=[
            indah.Text(lambda: f"{seen.value} events seen since you opened this page"),
            indah.Text(lambda: f"{len(last5.value)} kept (limit {last5.limit})"),
            indah.List(
                lambda: [f"{e['id']}  {e['kind']}" for e in last5.value], empty="Waiting..."
            ),
            indah.Switch(stop, label="Pause counting"),
        ]
    )


def bounded_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("5 kept (limit 5)")).to_be_visible()
    expect(page.get_by_text("events seen since you opened")).not_to_have_text(
        "0 events seen since you opened this page"
    )
    page.get_by_role("switch", name="Pause counting").click()
    frozen = page.get_by_text("events seen since you opened").inner_text()
    page.wait_for_timeout(1200)
    assert page.get_by_text("events seen since you opened").inner_text() == frozen
    expect(page.get_by_text("5 kept (limit 5)")).to_be_visible()  # the tail still moved on, bounded


# -- ctx.every and ctx.spawn ---------------------------------------------------------------------


def every(ctx: indah.Context) -> indah.Component:
    ticks = indah.Signal(0)
    ctx.every(0.5, lambda: ticks.set(ticks.value + 1), immediately=True)  # stops with the tab
    ran = indah.Signal("not yet")

    async def background() -> None:
        await asyncio.sleep(0.5)
        ran.set("done")

    ctx.spawn(background())  # any coroutine, cancelled if the tab closes first
    return indah.Column(
        children=[
            indah.Text(lambda: f"Refreshed {ticks.value} time(s)"),
            indah.Text(lambda: f"Background task: {ran.value}"),
        ]
    )


def every_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("Background task: done")).to_be_visible()
    first = page.get_by_text("Refreshed ").inner_text()
    page.wait_for_timeout(1300)
    assert page.get_by_text("Refreshed ").inner_text() != first


# -- Skeleton ------------------------------------------------------------------------------------


def skeleton(ctx: indah.Context) -> indah.Component:
    loaded = indah.Signal(False)
    ctx.spawn(_finish_loading(loaded))  # data "arrives" after a moment
    return indah.Column(
        children=[
            indah.Skeleton(lines=1, height="1.6rem"),  # a title
            indah.Skeleton(),  # three lines, the last one shorter
            indah.Text(
                lambda: (
                    "Loaded: the real content replaces the placeholder."
                    if loaded.value
                    else "Loading..."
                )
            ),
        ]
    )


async def _finish_loading(loaded: indah.Signal) -> None:
    await asyncio.sleep(1.0)
    loaded.set(True)


def skeleton_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".skeleton").first).to_be_visible()
    expect(page.get_by_text("Loaded: the real content")).to_be_visible()


# -- StreamText ----------------------------------------------------------------------------------


def stream_text(ctx: indah.Context) -> indah.Component:
    prompt = indah.Signal("Why is the sky blue?")
    out = indah.StreamText(label="Reply")

    async def generate() -> None:
        out.reset()
        async for token in indah.mock_llm(prompt.value):  # any async generator works
            out.feed(token)

    return indah.Column(
        children=[
            indah.TextInput(prompt, label="Prompt", on_submit=generate),
            indah.Button("Generate", generate),
            out,
        ]
    )


def stream_text_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_label("Prompt").fill("tell me a story")
    page.get_by_role("button", name="Generate").click()
    expect(
        page.get_by_text("you asked 'tell me a story'")
    ).to_be_visible()  # it grows token by token
    expect(page.get_by_text("never blocks while it generates")).to_be_visible(timeout=10000)


# -- Progress and Spinner ------------------------------------------------------------------------


def progress(ctx: indah.Context) -> indah.Component:
    done = indah.Signal(0.0)
    busy = indah.Signal(False)

    async def run() -> None:
        busy.set(True)
        done.set(0.0)
        for step in range(1, 11):
            await asyncio.sleep(0.08)
            done.set(step / 10)
        busy.set(False)
        ctx.toast("All 10 steps finished", kind="success")

    return indah.Column(
        children=[
            indah.Button("Start job", run),
            indah.Spinner(active=busy, label="Working"),
            indah.Progress(done, label="Job progress"),
            indah.Text(lambda: f"{round(done.value * 100)}% done"),
        ]
    )


def progress_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("0% done")).to_be_visible()
    page.get_by_role("button", name="Start job").click()
    expect(page.get_by_text("Working")).to_be_visible()  # the spinner shows while busy
    expect(page.get_by_text("100% done")).to_be_visible(timeout=10000)
    expect(page.get_by_text("All 10 steps finished")).to_be_visible()  # the toast
    expect(page.get_by_text("Working")).to_have_count(0)


# -- Chat ----------------------------------------------------------------------------------------


def chat(ctx: indah.Context) -> indah.Component:
    messages = indah.Signal([{"role": "assistant", "content": "Hi! Ask me anything."}])
    pending = indah.Signal("")  # the reply still being typed
    draft = indah.Signal("")

    async def send() -> None:
        question = draft.value.strip()
        if not question:
            return
        messages.set([*messages.value, {"role": "user", "content": question}])
        draft.set("")
        async for token in indah.mock_llm(question):
            pending.set(pending.value + token)
        messages.set([*messages.value, {"role": "assistant", "content": pending.value.strip()}])
        pending.set("")

    return indah.Column(
        children=[
            indah.Chat(messages, pending=pending, label="Conversation"),
            indah.TextInput(draft, placeholder="Say something", label="Message", on_submit=send),
            indah.Button("Send", send),
        ]
    )


def chat_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("Hi! Ask me anything.")).to_be_visible()
    page.get_by_label("Message").fill("hello there")
    page.get_by_role("button", name="Send").click()
    expect(page.get_by_text("hello there").first).to_be_visible()
    expect(page.get_by_text("here is a streamed reply")).to_be_visible(timeout=10000)
    expect(page.get_by_label("Message")).to_have_value("")


# -- effect --------------------------------------------------------------------------------------


def effect_page(ctx: indah.Context) -> indah.Component:
    name = indah.Signal("Ada")
    log = indah.Signal([])

    def note() -> None:  # reads `name`, so it reruns whenever `name` changes
        log.set([*log.peek(), f"name is now {name.value!r}"])

    indah.effect(note)  # runs once now, then on every change
    return indah.Column(
        children=[
            indah.TextInput(name, label="Name"),
            indah.Text(lambda: "\n".join(f"- {line}" for line in log.value), markdown=True),
        ]
    )


def effect_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("name is now 'Ada'")).to_be_visible()
    page.get_by_label("Name").fill("Grace")
    expect(page.get_by_text("name is now 'Grace'")).to_be_visible()
    expect(page.get_by_text("name is now 'Ada'")).to_be_visible()  # the earlier run is still logged


# -- batch ---------------------------------------------------------------------------------------


def batch_page(ctx: indah.Context) -> indah.Component:
    first, second = indah.Signal(0), indah.Signal(0)
    runs = indah.Signal(0)
    seen = {"n": 0}

    def watcher() -> None:  # an effect that reads both signals
        first.value, second.value  # noqa: B018
        seen["n"] += 1
        runs.set(seen["n"])

    indah.effect(watcher)

    # A sync click handler is already batched by indah. Code after an `await` (or in a background
    # task) is not, so each write reruns the effect unless you wrap the writes in `batch`.
    async def separately() -> None:
        await asyncio.sleep(0)
        first.set(first.value + 1)
        second.set(second.value + 1)  # two writes: the effect reruns twice

    async def together() -> None:
        await asyncio.sleep(0)

        def both() -> None:
            first.set(first.value + 1)
            second.set(second.value + 1)

        indah.batch(both)  # the same two writes: the effect reruns once

    return indah.Column(
        children=[
            indah.Row(
                children=[
                    indah.Button("Write both", separately),
                    indah.Button("Write both in a batch", together, variant="tonal"),
                ]
            ),
            indah.Text(lambda: f"first={first.value}, second={second.value}"),
            indah.Text(lambda: f"The effect has run {runs.value} time(s)."),
        ]
    )


def batch_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("The effect has run 1 time(s).")).to_be_visible()
    page.get_by_role("button", name="Write both", exact=True).click()
    expect(page.get_by_text("The effect has run 3 time(s).")).to_be_visible()  # +2
    page.get_by_role("button", name="Write both in a batch").click()
    expect(page.get_by_text("The effect has run 4 time(s).")).to_be_visible()  # +1
    expect(page.get_by_text("first=2, second=2")).to_be_visible()


CHAPTER = Chapter(
    slug="live",
    title="Live and streaming",
    order=60,
    blurb=(
        "Data that arrives while you watch: app-level feeds, token streams, progress, chat. "
        "Handlers may be `async`, so the page stays live while they work."
    ),
    lifespan=lifespan,
    pages=[
        Page(
            slug="topic",
            title="Topic: one feed, every tab",
            summary=(
                "A producer in the app's lifespan publishes to a `Topic`. Each tab follows it with "
                "`ctx.tail` (rows) and `ctx.latest` (the newest). Open this page in two tabs."
            ),
            build=topic,
            covers=("Topic", "Stream", "Table", "Col", "Context"),
            docs="dashboards.md",
            adr=(26,),
            check=topic_check,
        ),
        Page(
            slug="bounded",
            title="Bounded streams",
            summary=(
                "`ctx.tail(topic, limit=5)` keeps the newest five and sends only new rows, so a "
                "log that never ends costs a constant amount."
            ),
            build=bounded,
            covers=("Stream", "Topic", "List", "Switch"),
            docs="dashboards.md",
            adr=(26,),
            check=bounded_check,
        ),
        Page(
            slug="every",
            title="ctx.every and ctx.spawn",
            summary=(
                "A refresh loop and a background task that belong to this tab: `ctx.every` calls "
                "a function on a timer and `ctx.spawn` runs a coroutine. Both stop when the tab "
                "closes, and a failing call is logged once without stopping the loop."
            ),
            build=every,
            covers=("Context", "Signal"),
            docs="dashboards.md",
            adr=(25,),
            check=every_check,
        ),
        Page(
            slug="skeleton",
            title="Skeleton: a placeholder while data loads",
            summary=(
                "Grey pulsing bars for content that has not arrived. An `async def` session factory "
                "that takes too long starts the tab on one too (see the Async start app)."
            ),
            build=skeleton,
            covers=("Skeleton",),
            docs="components.md",
            adr=(25,),
            check=skeleton_check,
        ),
        Page(
            slug="stream-text",
            title="StreamText: tokens as they arrive",
            summary="An async handler feeds a `StreamText`; only the new token crosses the wire.",
            build=stream_text,
            covers=("StreamText", "TextInput", "Button"),
            docs="chatbot.md",
            adr=(11,),
            check=stream_text_check,
        ),
        Page(
            slug="progress",
            title="Progress and Spinner",
            summary="An async handler writes a signal as it goes; the bar and the spinner follow it.",
            build=progress,
            covers=("Progress", "Spinner", "Signal"),
            docs="components.md",
            adr=(11,),
            check=progress_check,
        ),
        Page(
            slug="chat",
            title="Chat",
            summary="Role bubbles bound to a list, plus a live bubble (`pending`) for a reply being typed.",
            build=chat,
            covers=("Chat",),
            docs="chatbot.md",
            adr=(16,),
            check=chat_check,
        ),
        Page(
            slug="effect",
            title="effect: run code when signals change",
            summary="An `effect` runs once, then again whenever a signal it read changes. Type in the box.",
            build=effect_page,
            covers=("effect",),
            docs="quickstart.md",
            adr=(3,),
            check=effect_check,
        ),
        Page(
            slug="batch",
            title="batch: one update, not two",
            summary=(
                "Two writes rerun a dependent effect twice. Inside `batch` it reruns once. "
                "(A sync click handler is batched for you; this matters after an `await` or in a task.)"
            ),
            build=batch_page,
            covers=("batch", "effect"),
            docs="quickstart.md",
            adr=(3,),
            check=batch_check,
        ),
    ],
)
