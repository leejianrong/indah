"""The pure pieces of Tier 1 live media (ADR-0045): options, frames, mailbox, byte budget."""

import asyncio

import pytest

from indah.components import Camera, UploadedFile
from indah.live import ByteBudget, Frame, Live, Mailbox, pack_frame, parse_frame


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
