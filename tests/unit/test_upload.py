"""Unit tests for the Upload component and UploadedFile (ADR-0017).

These cover the component in isolation: how it serialises, and how its synthetic
``upload`` event reaches the caller's plain handler (single vs multiple, sync vs
async, and the no-handler no-op). The HTTP multipart route is covered in
tests/integration/test_upload.py.
"""

import pytest

from indah.components import Upload, UploadedFile


@pytest.mark.unit
def test_uploaded_file_size_and_text():
    f = UploadedFile(filename="notes.txt", content_type="text/plain", data=b"hello")
    assert f.size == 5
    assert f.text() == "hello"


@pytest.mark.unit
def test_upload_serialises_its_ui_hints():
    u = Upload(label="Pick a file", accept="image/*", multiple=True)
    assert u.static_props() == {"label": "Pick a file", "accept": "image/*", "multiple": True}


@pytest.mark.unit
def test_single_upload_passes_one_file_to_the_handler():
    seen = {}

    def on_upload(file):
        seen["file"] = file

    u = Upload(on_upload)  # multiple defaults to False
    f = UploadedFile("a.png", "image/png", b"\x89PNG")
    assert u.handle("upload", {"files": [f]}) is True
    assert seen["file"] is f  # one UploadedFile, not a list


@pytest.mark.unit
def test_multiple_upload_passes_a_list_to_the_handler():
    seen = {}

    def on_upload(files):
        seen["files"] = files

    u = Upload(on_upload, multiple=True)
    files = [UploadedFile("a", "text/plain", b"1"), UploadedFile("b", "text/plain", b"2")]
    assert u.handle("upload", {"files": files}) is True
    assert seen["files"] == files  # the whole list


@pytest.mark.unit
def test_async_upload_handler_returns_a_coroutine_for_background_run():
    async def on_upload(file):
        return None

    u = Upload(on_upload)
    result = u.handle("upload", {"files": [UploadedFile("a", "text/plain", b"1")]})
    import inspect

    assert inspect.iscoroutine(result)
    result.close()  # don't leave it un-awaited


@pytest.mark.unit
def test_upload_with_no_handler_is_still_handled_never_errors():
    u = Upload()  # no on_upload
    assert u.handle("upload", {"files": []}) is True
    # An empty single upload passes None rather than indexing an empty list.
    called = {}
    u2 = Upload(lambda f: called.setdefault("arg", f))
    assert u2.handle("upload", {"files": []}) is True
    assert called["arg"] is None


@pytest.mark.unit
def test_upload_ignores_unrelated_events():
    assert Upload(lambda f: None).handle("click", {}) is False
