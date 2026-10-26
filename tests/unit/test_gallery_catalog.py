"""The gallery catalog file and its validation (IND-191)."""

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_FLY = Path(__file__).resolve().parents[2] / "deploy" / "fly"


def _load():
    spec = importlib.util.spec_from_file_location("gallery_catalog", _FLY / "gallery_catalog.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gallery_catalog"] = module
    spec.loader.exec_module(module)
    return module


cat = _load()


def _listed(**over):
    entry = {
        "slug": "their-app",
        "title": "Their app",
        "blurb": "A short plain sentence.",
        "author": "Someone",
        "kind": "listed",
        "url": "https://example.com/app",
        "source_url": "https://github.com/someone/app",
        "thumbnail": "chatbot.png",
        "indah_version": "0.9.0",
        "added": "2026-10-25",
        "tags": ["fun"],
    }
    entry.update(over)
    return entry


def _hosted(**over):
    entry = {
        "slug": "mine",
        "title": "Mine",
        "blurb": "A short plain sentence.",
        "author": "indah",
        "kind": "hosted",
        "module": "chatbot",
        "added": "2026-10-25",
    }
    entry.update(over)
    return entry


def test_the_real_catalog_is_valid():
    entries = cat.load_catalog()
    assert cat.validate_catalog(entries) == []
    assert len(cat.hosted(entries)) == 15


def test_a_sound_hosted_and_listed_entry_pass():
    assert cat.validate_catalog([_hosted(), _listed()]) == []


@pytest.mark.parametrize(
    ("entry", "needle"),
    [
        (_listed(url="http://example.com"), "https"),
        (_listed(url="https://user:pw@example.com"), "https"),
        (_listed(source_url="javascript:alert(1)"), "https"),
        (_listed(blurb="<b>hi</b>"), "plain text"),
        (_listed(title="a & b"), "plain text"),
        (_listed(blurb="x" * 121), "blurb"),
        (_listed(thumbnail="missing.png"), "thumbnail"),
        (_listed(thumbnail="../gallery_app.py"), "thumbnail"),
        (_listed(thumbnail=""), "missing thumbnail"),
        (_listed(slug="Bad Slug"), "slug"),
        (_listed(indah_version="latest"), "indah_version"),
        (_listed(added="yesterday"), "added"),
        (_listed(kind="other"), "kind"),
        (_hosted(url="https://example.com"), "no url"),
        (_hosted(module="not a module"), "module"),
        (_hosted(module=""), "missing module"),
    ],
)
def test_validation_rejects(entry, needle):
    problems = cat.validate_catalog([entry])
    assert any(needle in p for p in problems), problems


def test_duplicate_slugs_are_rejected():
    problems = cat.validate_catalog([_hosted(), _hosted()])
    assert any("duplicate" in p for p in problems)


def test_an_oversize_thumbnail_is_rejected(tmp_path):
    (tmp_path / "big.png").write_bytes(b"0" * (cat.THUMB_MAX_BYTES + 1))
    problems = cat.validate_catalog([_listed(thumbnail="big.png")], thumb_dir=tmp_path)
    assert any("larger" in p for p in problems)
