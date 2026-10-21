import pytest

from indah.components import CodeEditor
from indah.reactive import Signal


@pytest.mark.unit
def test_props_and_defaults():
    text = Signal('{"a": 1}')
    ed = CodeEditor(text, label="Body")
    assert ed.static_props() == {
        "format": False,
        "save": False,
        "language": "json",
        "readOnly": False,
        "lint": True,
        "height": "24rem",
        "label": "Body",
        "placeholder": "",
    }
    assert ed.reactive_props()["value"]() == '{"a": 1}'
    assert CodeEditor(Signal(None)).reactive_props()["value"]() == ""


@pytest.mark.unit
def test_language_and_height_are_validated():
    for lang in ("json", "yaml", "text"):
        CodeEditor(Signal(""), language=lang)
    with pytest.raises(ValueError, match="language"):
        CodeEditor(Signal(""), language="python")
    with pytest.raises(ValueError, match="height"):
        CodeEditor(Signal(""), height="tall")


@pytest.mark.unit
def test_input_writes_the_signal_and_read_only_refuses():
    text = Signal("")
    ed = CodeEditor(text)
    assert ed.handle("input", {"value": "{}"}) is True and text.value == "{}"
    assert ed.handle("input", {}) is False
    ro = CodeEditor(text, read_only=True)
    assert ro.handle("input", {"value": "x"}) is False and text.value == "{}"
    assert ro.static_props()["readOnly"] is True


@pytest.mark.unit
def test_format_reindents_json_and_keeps_key_order():
    text = Signal("")
    ed = CodeEditor(text, format_button=True)
    assert ed.static_props()["format"] is True
    ed.handle("format", {"value": '{"z":1,"a":[1,2],"m":{"k":"é"},"n":1.0}'})
    assert text.value == (
        '{\n  "z": 1,\n  "a": [\n    1,\n    2\n  ],\n  "m": {\n    "k": "é"\n  },\n  "n": 1.0\n}'
    )
    before = text.value
    assert ed.handle("format", {"value": "{not json"}) is False and text.value == before


@pytest.mark.unit
def test_format_is_json_only_and_off_when_read_only():
    assert (
        CodeEditor(Signal(""), language="yaml", format_button=True).static_props()["format"]
        is False
    )
    assert (
        CodeEditor(Signal(""), read_only=True, format_button=True).static_props()["format"] is False
    )
    assert CodeEditor(Signal(""), language="text").handle("format", {"value": "{}"}) is False


@pytest.mark.unit
async def test_save_sets_the_latest_text_then_calls_on_save():
    seen = []
    text = Signal("old")
    ed = CodeEditor(text, on_save=lambda: seen.append(text.value))
    assert ed.static_props()["save"] is True
    assert ed.handle("save", {"value": "new"}) is True
    assert seen == ["new"]

    async def later():
        seen.append("async")

    ed2 = CodeEditor(text, on_save=later)
    result = ed2.handle("save", {"value": "x"})
    await result
    assert seen[-1] == "async"
    assert CodeEditor(text).handle("save", {"value": "x"}) is False  # no on_save
