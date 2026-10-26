"""The pure pieces of Tier 1 live media (ADR-0045): options, frames, mailbox, byte budget."""

import asyncio

import pytest

from indah.components import Camera, UploadedFile
from indah.live import (
    AudioChunk,
    AudioQueue,
    ByteBudget,
    Frame,
    Live,
    Mailbox,
    pack_frame,
    parse_frame,
)


@pytest.mark.unit
def test_a_frame_round_trips_through_the_wire_format():
    raw = pack_frame(7, b"jpegbytes")
    assert parse_frame(raw) == (7, b"jpegbytes")


@pytest.mark.unit
@pytest.mark.parametrize("raw", [b"", b"\x00\x00\x00", b"\x00\x00\x00\x01"])
def test_a_frame_with_no_payload_is_refused(raw):
    with pytest.raises(ValueError):
        parse_frame(raw)


@pytest.mark.unit
def test_live_rejects_nonsense_caps():
    with pytest.raises(ValueError):
        Live(max_frame_bytes=0)
    with pytest.raises(ValueError):
        Live(stats_seconds=0)
    assert Live().max_sockets_per_address == 4


@pytest.mark.unit
async def test_the_mailbox_keeps_only_the_latest_frame():
    box = Mailbox()
    assert box.put(Frame(b"a", seq=1)) is False
    assert box.put(Frame(b"b", seq=2)) is True
    assert box.put(Frame(b"c", seq=3)) is True
    got = await box.get()
    assert got is not None and got.seq == 3
    assert (box.dropped, box.processed) == (2, 1)


@pytest.mark.unit
async def test_the_mailbox_waits_then_wakes_and_ends_on_close():
    box = Mailbox()
    task = asyncio.create_task(box.get())
    await asyncio.sleep(0)
    assert not task.done()
    box.put(Frame(b"x", seq=1))
    assert (await task).seq == 1
    ender = asyncio.create_task(box.get())
    await asyncio.sleep(0)
    box.close()
    assert await ender is None


@pytest.mark.unit
async def test_a_frame_put_before_close_is_still_delivered():
    box = Mailbox()
    box.put(Frame(b"x", seq=9))
    box.close()
    assert (await box.get()).seq == 9
    assert await box.get() is None


@pytest.mark.unit
def test_the_byte_budget_refills_each_second():
    now = [0.0]
    budget = ByteBudget(100, clock=lambda: now[0])
    assert budget.allow(60)
    assert not budget.allow(60)
    now[0] = 1.5
    assert budget.allow(60)


@pytest.mark.unit
def test_camera_handler_gets_frames_and_snapshot_uploads():
    seen = []
    cam = Camera(seen.append)
    assert cam.handle("frame", {"frame": Frame(b"1", seq=1)}) is True
    up = UploadedFile(filename="snap.jpg", content_type="image/jpeg", data=b"2")
    assert cam.handle("upload", {"files": [up]}) is True
    assert [f.data for f in seen] == [b"1", b"2"]
    assert seen[1].content_type == "image/jpeg"


@pytest.mark.unit
def test_camera_ignores_a_frame_that_a_client_posted_as_json():
    seen = []
    cam = Camera(seen.append)
    assert cam.handle("frame", {"frame": "not a Frame"}) is True
    assert seen == []


@pytest.mark.unit
def test_camera_reports_its_transport_and_rejects_unknown_values():
    cam = Camera()
    assert cam.transport.value == "off"
    cam.handle("transport", {"value": "live"})
    assert cam.transport.value == "live"
    cam.handle("transport", {"value": "carrier pigeon"})
    assert cam.transport.value == "live"


@pytest.mark.unit
async def test_an_async_camera_handler_comes_back_as_a_coroutine():
    async def on_frame(frame):
        return frame

    result = Camera(on_frame).handle("frame", {"frame": Frame(b"1")})
    assert asyncio.iscoroutine(result)
    await result


@pytest.mark.unit
def test_camera_props():
    cam = Camera(fps=3, max_width=320, quality=0.5, label="Cam")
    assert cam.static_props() == {"fps": 3, "maxWidth": 320, "quality": 0.5, "label": "Cam"}
    with pytest.raises(ValueError):
        Camera(fps=0)
    with pytest.raises(ValueError):
        Camera(quality=2)


@pytest.mark.unit
async def test_the_audio_queue_keeps_order_and_drops_the_oldest_when_over_budget():
    q = AudioQueue(250)
    for seq in range(1, 6):
        q.put(AudioChunk(b"x" * 100, seq=seq))
    assert q.dropped == 3  # only the two newest fit in 250 bytes
    first = await q.get()
    second = await q.get()
    assert (first.seq, first.dropped_before) == (4, 3)
    assert (second.seq, second.dropped_before) == (5, 0)
    q.close()
    assert await q.get() is None


@pytest.mark.unit
def test_live_audio_budget_must_be_positive():
    with pytest.raises(ValueError):
        Live(audio_buffer_seconds=0)


@pytest.mark.unit
def test_microphone_validates_and_exposes_its_props():
    from indah.components import Microphone

    mic = Microphone(lambda c: None, sample_rate=8000, label="Speak")
    assert mic.static_props()["sampleRate"] == 8000
    assert mic.transport.value == "off"
    with pytest.raises(ValueError):
        Microphone(sample_rate=100)


@pytest.mark.unit
def test_a_microphone_handler_gets_a_chunk_and_a_recorded_upload():
    from indah.components import Microphone

    seen = []
    mic = Microphone(seen.append, sample_rate=16000)
    mic.handle("audio", {"chunk": AudioChunk(b"ab", seq=1)})
    mic.handle("audio", {"chunk": "forged"})  # only the socket builds a chunk
    mic.handle("upload", {"files": [UploadedFile("a.wav", "audio/wav", b"RIFF")]})
    assert [c.content_type for c in seen] == ["audio/pcm", "audio/wav"]
    assert seen[1].data == b"RIFF" and seen[1].sample_rate == 16000
