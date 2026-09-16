"""Unit tests for Download / file-out (ADR-0017).

Cover the component in isolation: how a bound Download coerces its source (URL
passthrough, raw bytes, DownloadFile) into a served per-session URL, and that
identical bytes are not re-served under a fresh token. The HTTP file route is
covered in tests/integration/test_download.py.
"""

import pytest

from indah.components import Column, Download, DownloadFile
from indah.reactive import Signal
from indah.session import Session


def _bound(source, **kw) -> tuple[Download, Session]:
    """A Download wired into a session (so it can serve bytes), with a stable id."""
    d = Download(source, **kw)
    session = Session(Column(children=[d]))
    session.session_id = "tab-a"
    return d, session


def _href(d: Download) -> str:
    return d.reactive_props()["href"]()


def _filename(d: Download) -> str:
    return d.reactive_props()["filename"]()


@pytest.mark.unit
def test_download_file_defaults():
    f = DownloadFile(b"x")
    assert f.filename == "download"
    assert f.media_type == "application/octet-stream"


@pytest.mark.unit
def test_download_serialises_its_label():
    d, _ = _bound(None, label="Export CSV")
    assert d.static_props() == {"label": "Export CSV"}


@pytest.mark.unit
def test_a_url_string_source_passes_through():
    d, _ = _bound("https://example.com/report.pdf", filename="report.pdf")
    assert _href(d) == "https://example.com/report.pdf"
    assert _filename(d) == "report.pdf"


@pytest.mark.unit
def test_none_source_yields_an_inert_link():
    d, _ = _bound(None)
    assert _href(d) == ""


@pytest.mark.unit
def test_bytes_source_is_served_at_a_per_session_url():
    sig = Signal(b"")
    d, session = _bound(sig, filename="out.csv", media_type="text/csv")
    sig.set(b"a,b\n1,2\n")
    href = _href(d)
    assert href.startswith("api/file/tab-a/")
    token = href.rsplit("/", 1)[1]
    assert session.get_file(token) == (b"a,b\n1,2\n", "out.csv", "text/csv")


@pytest.mark.unit
def test_download_file_source_carries_its_own_name_and_type():
    sig = Signal(None)
    d, session = _bound(sig)
    sig.set(DownloadFile(b"\x89PNG", filename="pic.png", media_type="image/png"))
    href = _href(d)
    token = href.rsplit("/", 1)[1]
    assert _filename(d) == "pic.png"
    assert session.get_file(token) == (b"\x89PNG", "pic.png", "image/png")


@pytest.mark.unit
def test_identical_bytes_are_not_reserved_under_a_new_token():
    sig = Signal(b"same")
    d, _ = _bound(sig, filename="a.bin")
    first = _href(d)
    again = _href(d)  # repeated getter call (also mimics a snapshot)
    assert first == again  # cached, not a fresh token

    sig.set(b"different")
    changed = _href(d)
    assert changed != first  # new bytes -> new token


@pytest.mark.unit
def test_an_unbound_download_yields_no_href():
    # Serialised standalone (no session wiring): bytes cannot be served, so inert.
    d = Download(b"data")
    assert d.reactive_props()["href"]() == ""
