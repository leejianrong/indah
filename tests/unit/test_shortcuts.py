import inspect

import pytest

from indah.components import Shortcuts
from indah.keys import normalize_keys


@pytest.mark.unit
@pytest.mark.parametrize(
    ("spec", "want"),
    [
        ("a", "a"),
        ("A", "a"),
        ("g l", "g l"),
        ("  g   L ", "g l"),
        ("mod+k", "mod+k"),
        ("Ctrl+K", "mod+k"),
        ("cmd+k", "mod+k"),
        ("shift+alt+mod+x", "mod+alt+shift+x"),
        ("?", "?"),
        ("escape", "escape"),
        ("mod++", "mod++"),
    ],
)
def test_normalize_keys(spec, want):
    assert normalize_keys(spec) == want


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["", "   ", "mod+", "mod+shift", "a+b", "foo+k", "g  +l"])
def test_normalize_keys_rejects_garbage(bad):
    with pytest.raises(ValueError):
        normalize_keys(bad)


@pytest.mark.unit
def test_shortcuts_serialise_with_labels_and_dispatch_press():
    hits = []
    sc = Shortcuts(
        {
            "A": lambda: hits.append("approve"),
            "g l": (lambda: hits.append("log"), "Go to the log"),
        }
    )
    assert sc.type == "shortcuts"
    assert sc.static_props() == {
        "keys": [{"keys": "a", "label": ""}, {"keys": "g l", "label": "Go to the log"}]
    }
    assert sc.handle("press", {"keys": "g l"}) is True
    assert sc.handle("press", {"keys": "a"}) is True
    assert hits == ["log", "approve"]
    assert sc.handle("press", {"keys": "z"}) is False
    assert sc.handle("press", {}) is False


@pytest.mark.unit
def test_shortcuts_async_handler_is_returned_and_duplicates_rejected():
    async def go():
        pass

    r = Shortcuts({"a": go}).handle("press", {"keys": "a"})
    assert inspect.iscoroutine(r)
    r.close()
    with pytest.raises(ValueError):
        Shortcuts({"a": lambda: None, "A": lambda: None})
