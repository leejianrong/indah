"""The shell sends the route hint back (IND-197, ADR-0043).

On Fly, with a cluster secret, the stream's init names the machine; the shell then sends
``fly-force-instance-id`` and ``X-Indah-Route`` on every event, and a 400 that is not indah's own
(Fly's answer for a machine that is gone) re-opens the stream. Runs under ``csp="strict"``.
"""

import pytest

import indah
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

MACHINE = "e826010b63e458"
TOAST = "Reconnected. Your last action was not applied, please try it again."


def _app():
    def build() -> indah.Session:
        n = indah.Signal(0)
        return indah.Session(
            indah.Column(
                children=[
                    indah.Button("Add one", on_click=lambda: n.set(n.value + 1)),
                    indah.Text(lambda: f"count {n.value}"),
                ]
            )
        )

    return indah.create_app(session_factory=build)


@pytest.fixture
def fly(monkeypatch):
    monkeypatch.setenv("FLY_MACHINE_ID", MACHINE)
    monkeypatch.setenv("INDAH_CLUSTER_SECRET", "a-cluster-secret-of-some-length")


@pytest.mark.e2e
def test_events_carry_the_fly_header_and_a_gone_machine_reopens_the_stream(fly):
    handle = launch(_app(), block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                seen: list[dict] = []
                page.on(
                    "request",
                    lambda r: seen.append(r.headers) if r.url.endswith("/api/event") else None,
                )
                streams = 0

                def on_stream(r):
                    nonlocal streams
                    streams += r.url.split("?")[0].endswith("/api/stream")

                page.on("request", on_stream)
                page.goto(handle.url, wait_until="domcontentloaded")
                expect(page.get_by_text("count 0")).to_be_visible()
                page.get_by_role("button", name="Add one").click()
                expect(page.get_by_text("count 1")).to_be_visible()
                assert seen[0]["fly-force-instance-id"] == MACHINE
                assert seen[0]["x-indah-route"] == MACHINE

                # Fly answers 400 (not indah's JSON) for a machine that no longer exists.
                page.route(
                    "**/api/event",
                    lambda route: route.fulfill(status=400, body="no such machine"),
                    times=1,
                )
                page.get_by_role("button", name="Add one").click()
                expect(page.get_by_text(TOAST)).to_be_visible()
                page.get_by_role("button", name="Add one").click()
                expect(page.get_by_text("count 2")).to_be_visible()  # the new init's hint works
                assert streams == 2  # the stream was opened again once
                assert seen[-1]["fly-force-instance-id"] == MACHINE
                assert page.get_by_text(TOAST).count() == 1
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_without_the_hint_no_routing_headers_are_sent(monkeypatch):
    for name in ("FLY_MACHINE_ID", "INDAH_CLUSTER_SECRET"):
        monkeypatch.delenv(name, raising=False)
    handle = launch(_app(), block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                seen: list[dict] = []
                page.on(
                    "request",
                    lambda r: seen.append(r.headers) if r.url.endswith("/api/event") else None,
                )
                page.goto(handle.url, wait_until="domcontentloaded")
                page.get_by_role("button", name="Add one").click()
                expect(page.get_by_text("count 1")).to_be_visible()
                assert "fly-force-instance-id" not in seen[0]
                assert "x-indah-route" not in seen[0]
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_uploads_carry_the_fly_header_too(fly, tmp_path):
    def build() -> indah.Session:
        got = indah.Signal("nothing yet")
        return indah.Session(
            indah.Column(
                children=[
                    indah.Upload(lambda f: got.set(f"got {f.filename}"), label="Pick"),
                    indah.Text(lambda: got.value),
                ]
            )
        )

    handle = launch(indah.create_app(session_factory=build), block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                seen: list[dict] = []
                page.on(
                    "request",
                    lambda r: seen.append(r.headers) if r.url.endswith("/api/upload") else None,
                )
                page.goto(handle.url, wait_until="domcontentloaded")
                note = tmp_path / "note.txt"
                note.write_text("hello")
                page.locator("input[type=file]").set_input_files(str(note))
                expect(page.get_by_text("got note.txt")).to_be_visible()
                assert seen[0]["fly-force-instance-id"] == MACHINE
                assert seen[0]["x-indah-route"] == MACHINE
            finally:
                browser.close()
    finally:
        handle.stop()
