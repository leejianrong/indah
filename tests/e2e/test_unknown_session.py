"""A tab whose session the process no longer holds recovers and says so (IND-199).

With several processes and no affinity (or after a restart or an eviction) a click can reach a
process that does not hold the tab's session. The server answers ``409 unknown_session``; the
shell then opens its stream again for a fresh ``init`` and shows one toast, instead of letting the
click vanish. Runs under ``csp="strict"`` (the conftest default).
"""

import pytest

import indah
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

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


@pytest.mark.e2e
def test_a_lost_session_is_rebuilt_with_one_toast_and_the_next_click_works():
    app = _app()
    handle = launch(app, block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                button = page.get_by_role("button", name="Add one")
                expect(page.get_by_text("count 0")).to_be_visible()
                button.click()
                expect(page.get_by_text("count 1")).to_be_visible()

                # Another process has the tab's session now: this one forgets it (without closing
                # the open stream, which is what a misrouted click looks like).
                store = app.state.store
                (sid,) = list(store._handles)  # noqa: SLF001
                store._handles.pop(sid)  # noqa: SLF001

                button.click()  # 409 unknown_session -> the shell reconnects
                expect(page.get_by_text(TOAST)).to_be_visible()
                expect(page.get_by_text("count 0")).to_be_visible()  # a fresh session
                assert store.get(sid) is not None  # the stream built it again

                button.click()  # and the next click works
                expect(page.get_by_text("count 1")).to_be_visible()
                assert page.get_by_text(TOAST).count() == 1  # said once, not on every click
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_two_lost_clicks_in_a_row_do_not_loop_or_repeat_the_toast():
    app = _app()
    handle = launch(app, block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                button = page.get_by_role("button", name="Add one")
                expect(page.get_by_text("count 0")).to_be_visible()
                store = app.state.store
                for _ in range(2):
                    (sid,) = list(store._handles)  # noqa: SLF001
                    store._handles.pop(sid)  # noqa: SLF001
                    button.click()
                    page.wait_for_timeout(200)
                expect(page.get_by_text(TOAST)).to_be_visible()
                assert page.get_by_text(TOAST).count() == 1
            finally:
                browser.close()
    finally:
        handle.stop()
