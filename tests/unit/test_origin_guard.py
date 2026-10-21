"""The cross-origin rule (ADR-0033, IND-115) as a pure function, plus allowed_origins parsing."""

import pytest

from indah.guard import normalize_origins, origin_allowed

OWN = "https://app.example.com"


def ok(**kw):
    kw.setdefault("own_origin", OWN)
    kw.setdefault("sec_fetch_site", None)
    kw.setdefault("origin", None)
    return origin_allowed(**kw)


@pytest.mark.unit
@pytest.mark.parametrize("site", ["same-origin", "none", "Same-Origin"])
def test_the_browsers_same_origin_signal_passes_whatever_origin_says(site):
    assert ok(sec_fetch_site=site)
    assert ok(sec_fetch_site=site, origin="https://worker.internal")  # a proxy rewrote Host


@pytest.mark.unit
@pytest.mark.parametrize("site", ["cross-site", "same-site", "weird"])
def test_cross_and_same_site_are_refused_unless_the_origin_is_allowed(site):
    assert not ok(sec_fetch_site=site)
    assert not ok(sec_fetch_site=site, origin="https://evil.example")
    allowed = frozenset({"https://partner.example.com"})
    assert ok(sec_fetch_site=site, origin="https://partner.example.com", allowed=allowed)
    assert not ok(sec_fetch_site=site, allowed=allowed)  # no Origin to match


@pytest.mark.unit
def test_without_fetch_metadata_the_origin_header_must_match():
    assert ok(origin=OWN) and ok(origin=OWN + "/") and ok(origin="HTTPS://APP.example.com")
    assert not ok(origin="https://evil.example")
    assert not ok(origin="http://app.example.com")  # scheme matters
    assert not ok(origin="https://app.example.com:8443")  # so does the port
    assert not ok(origin="null")  # sandboxed iframes and redirects
    assert ok(
        origin="https://partner.example.com", allowed=frozenset({"https://partner.example.com"})
    )


@pytest.mark.unit
def test_no_headers_at_all_is_a_non_browser_client_and_passes():
    assert ok()


@pytest.mark.unit
def test_allowed_origins_are_validated_and_normalised():
    assert normalize_origins(["HTTPS://A.example.com/", "http://localhost:3000"]) == {
        "https://a.example.com",
        "http://localhost:3000",
    }
    assert normalize_origins(None) == frozenset()
    for bad in ["*", "app.example.com", "https://a.example.com/path", "null", "ftp://x.y", ""]:
        with pytest.raises(ValueError, match="allowed_origins"):
            normalize_origins([bad])
