"""Scheduled link health for listed gallery apps (IND-192). Fake fetcher, fake clock, no network."""

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_FLY = Path(__file__).resolve().parents[2] / "deploy" / "fly"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _FLY / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load("gallery_catalog")
h = _load("gallery_health")

NOW = "2026-10-26T06:00:00+00:00"


def fetcher(table):
    """table maps (method, url) -> (status, location) or an Exception."""
    calls = []

    def fetch(method, url, timeout):
        calls.append((method, url))
        r = table[(method, url)]
        if isinstance(r, Exception):
            raise r
        return r

    fetch.calls = calls
    return fetch


def test_head_ok():
    f = fetcher({("HEAD", "https://a.example/"): (200, None)})
    assert h.check_url("https://a.example/", f) == (True, "200")
    assert f.calls == [("HEAD", "https://a.example/")]


def test_head_refused_falls_back_to_get():
    f = fetcher(
        {("HEAD", "https://a.example/"): (405, None), ("GET", "https://a.example/"): (200, None)}
    )
    assert h.check_url("https://a.example/", f)[0] is True


def test_server_error_fails():
    f = fetcher(
        {("HEAD", "https://a.example/"): (503, None), ("GET", "https://a.example/"): (503, None)}
    )
    ok, why = h.check_url("https://a.example/", f)
    assert not ok and "503" in why


def test_network_error_fails():
    f = fetcher(
        {
            ("HEAD", "https://a.example/"): OSError("refused"),
            ("GET", "https://a.example/"): OSError("refused"),
        }
    )
    ok, why = h.check_url("https://a.example/", f)
    assert not ok and "refused" in why


def test_follows_a_few_https_redirects():
    f = fetcher(
        {
            ("HEAD", "https://a.example/"): (301, "https://b.example/x"),
            ("HEAD", "https://b.example/x"): (200, None),
        }
    )
    assert h.check_url("https://a.example/", f)[0] is True


def test_redirect_to_http_or_loop_fails():
    f = fetcher(
        {
            ("HEAD", "https://a.example/"): (302, "http://a.example/"),
            ("GET", "https://a.example/"): (302, "http://a.example/"),
        }
    )
    assert h.check_url("https://a.example/", f)[0] is False
    loop = {
        ("HEAD", "https://a.example/"): (302, "https://a.example/"),
        ("GET", "https://a.example/"): (302, "https://a.example/"),
    }
    assert h.check_url("https://a.example/", fetcher(loop))[0] is False


def test_refuses_non_https_and_credentials_without_fetching():
    f = fetcher({})
    assert h.check_url("http://a.example/", f)[0] is False
    assert h.check_url("https://u:p@a.example/", f)[0] is False
    assert f.calls == []


def test_update_state_counts_and_recovers():
    s = {}
    s = h.update_state(s, {"x": (False, "503")}, NOW)
    s = h.update_state(s, {"x": (False, "503")}, NOW)
    assert s["x"]["failures"] == 2 and s["x"]["last_ok"] is None
    s = h.update_state(s, {"x": (True, "200")}, "2026-11-02T06:00:00+00:00")
    assert s["x"] == {
        "last_ok": "2026-11-02T06:00:00+00:00",
        "failures": 0,
        "last_checked": "2026-11-02T06:00:00+00:00",
        "detail": "200",
    }


def test_update_state_drops_slugs_no_longer_listed():
    s = h.update_state({"gone": {"failures": 9}}, {"x": (True, "200")}, NOW)
    assert "gone" not in s


@pytest.mark.parametrize(
    ("failures", "status"),
    [
        (0, "ok"),
        (2, "ok"),
        (3, "not_responding"),
        (7, "not_responding"),
        (8, "hidden"),
        (50, "hidden"),
    ],
)
def test_status_thresholds(failures, status):
    assert h.status_for({"failures": failures}) == status


def test_unknown_entry_is_ok():
    assert h.status_for(None) == "ok"


def test_load_state_tolerates_missing_and_broken(tmp_path):
    assert h.load_state(tmp_path / "none.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    assert h.load_state(bad) == {}
    good = tmp_path / "g.json"
    h.save_state(good, {"x": {"failures": 1}})
    assert h.load_state(good) == {"x": {"failures": 1}}


def test_visible_listed_hides_and_marks():
    entries = [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}, {"slug": "d"}]
    state = {"b": {"failures": 3}, "c": {"failures": 8}}
    out = h.apply_status(entries, state)
    assert [e["slug"] for e in out] == ["a", "b", "d"]
    assert [e["status"] for e in out] == ["ok", "not_responding", "ok"]


def test_thumbnail_problems(tmp_path):
    (tmp_path / "ok.png").write_bytes(b"x" * 10)
    (tmp_path / "big.png").write_bytes(b"x" * (h.THUMB_MAX_BYTES + 1))
    entries = [
        {"slug": "a", "thumbnail": "ok.png"},
        {"slug": "b", "thumbnail": "big.png"},
        {"slug": "c", "thumbnail": "missing.png"},
    ]
    probs = h.thumbnail_problems(entries, tmp_path)
    assert len(probs) == 2 and any("b" in p for p in probs) and any("c" in p for p in probs)


def test_summary_flags_dead_and_recovered():
    entries = [
        {"slug": "a", "title": "A", "url": "https://a.example/"},
        {"slug": "b", "title": "B", "url": "https://b.example/"},
    ]
    state = {
        "a": {"failures": 3, "last_ok": None, "detail": "503"},
        "b": {"failures": 0, "last_ok": NOW, "detail": "200"},
    }
    text = h.summary(entries, state, [])
    assert "Not responding" in text and "| A |" in text
    assert "No listed apps" not in text
    assert "No listed apps" in h.summary([], {}, [])
