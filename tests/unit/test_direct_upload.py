"""Unit tests for DirectUpload: the pick -> target -> done exchange with the shell."""

import asyncio

import pytest

from indah.components import DirectUpload


def target(info):
    return {"url": f"http://store/put/{info['filename']}", "headers": {"x-a": "1"}}


@pytest.mark.unit
def test_picking_a_file_offers_a_target_and_done_clears_it():
    done = []
    u = DirectUpload(target, on_done=done.append, label="Data", accept=".zip")
    assert u.static_props() == {"label": "Data", "accept": ".zip"}
    assert u.reactive_props()["target"]() is None
    assert u.handle("pick", {"filename": "a.zip", "size": 5, "content_type": "application/zip"})
    t = u.reactive_props()["target"]()
    assert t == {"id": 1, "url": "http://store/put/a.zip", "headers": {"x-a": "1"}}
    assert u.handle("done", {"filename": "a.zip", "ok": True, "status": 200})
    assert u.reactive_props()["target"]() is None and done == [
        {"filename": "a.zip", "ok": True, "status": 200}
    ]


@pytest.mark.unit
def test_picking_the_same_file_again_gets_a_new_id():
    u = DirectUpload(target)
    u.handle("pick", {"filename": "a.zip"})
    u.handle("done", {})
    u.handle("pick", {"filename": "a.zip"})
    assert u.reactive_props()["target"]()["id"] == 2


@pytest.mark.unit
def test_the_handler_receives_the_file_facts_and_may_be_async():
    seen = {}

    async def get_target(info):
        seen.update(info)
        return {"url": "https://store/x"}

    u = DirectUpload(get_target)
    coro = u.handle("pick", {"filename": "a.zip", "size": "7", "content_type": "application/zip"})
    asyncio.run(coro)
    assert seen == {"filename": "a.zip", "size": 7, "content_type": "application/zip"}
    assert u.reactive_props()["target"]()["headers"] == {}


@pytest.mark.unit
@pytest.mark.parametrize("bad", [None, {}, {"url": "file:///etc/passwd"}, {"url": "javascript:1"}])
def test_a_target_must_be_an_http_url(bad):
    u = DirectUpload(lambda info: bad)
    with pytest.raises(ValueError, match="get_target"):
        u.handle("pick", {"filename": "a"})


@pytest.mark.unit
def test_unknown_events_are_unhandled():
    assert DirectUpload(target).handle("click", {}) is False
