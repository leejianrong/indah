"""Unit tests for the streaming primitives: resume logic and StreamText feed."""

import pytest

from indah.components import Column, StreamText
from indah.session import Session
from indah.transport import Hub

# -- resume / reconnect (ADR-0011) ------------------------------------------


@pytest.mark.unit
def test_replay_since_returns_messages_after_the_offset_without_duplication():
    hub = Hub()
    for i in range(1, 6):
        hub.publish({"n": i})  # offsets 1..5

    resumed = hub.replay_since(2)  # client last saw offset 2

    assert [offset for offset, _ in resumed] == [3, 4, 5]  # only the missed ones
    assert [msg["n"] for _, msg in resumed] == [3, 4, 5]


@pytest.mark.unit
def test_replay_since_none_or_current_yields_nothing():
    hub = Hub()
    hub.publish({"n": 1})
    hub.publish({"n": 2})

    assert hub.replay_since(None) == []  # a fresh connect resumes nothing
    assert hub.replay_since(2) == []  # already current
    assert hub.replay_since(9) == []  # client somehow ahead


@pytest.mark.unit
def test_replay_since_reports_a_gap_when_messages_were_evicted():
    hub = Hub(history_size=3)
    for i in range(1, 6):
        hub.publish({"n": i})  # only offsets 3,4,5 remain buffered

    # The client last saw 1, but 2 has been evicted -> a gap the caller must
    # recover from by resending a full init, not a partial replay.
    assert hub.replay_since(1) is None
    # Last saw 2: the next needed message (3) is still buffered -> a clean resume.
    assert [offset for offset, _ in hub.replay_since(2)] == [3, 4, 5]


# -- StreamText feed ---------------------------------------------------------


def _stream_session():
    stream = StreamText(label="out")
    session = Session(Column(children=[stream]))
    hub = Hub()
    session.bind_hub(hub)
    return session, stream, hub


@pytest.mark.unit
def test_feed_accumulates_text_and_emits_append_deltas():
    session, stream, hub = _stream_session()

    stream.feed("Hello ")
    stream.feed("world")

    assert stream.text == "Hello world"
    # Each feed is its own append patch carrying only the delta (O(token) wire cost).
    changes = [msg["changes"][0] for _, msg in hub.history()]
    assert changes == [
        {"target": stream.id, "append": {"text": "Hello "}},
        {"target": stream.id, "append": {"text": "world"}},
    ]


@pytest.mark.unit
def test_reset_clears_text_and_emits_a_replace():
    session, stream, hub = _stream_session()
    stream.feed("stale")

    stream.reset()

    assert stream.text == ""
    _, last = hub.history()[-1]
    assert last["changes"][0] == {"target": stream.id, "props": {"text": ""}}


@pytest.mark.unit
def test_snapshot_carries_full_accumulated_text_for_resume():
    session, stream, hub = _stream_session()
    stream.feed("abc")

    # A resume that falls back to init must re-render the full text so far.
    node = session.snapshot()["children"][0]
    assert node["type"] == "streamtext"
    assert node["props"]["text"] == "abc"
