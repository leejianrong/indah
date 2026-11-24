"""The RAG chat example (examples/rag_chat.py): retrieval, citations, uploads."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "rag_chat.py"
if not _EXAMPLE.exists():
    pytest.skip("examples/ not present", allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("rag_chat_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.WORD_PAUSE = 0
    return module


ex = _load()


def _index():
    return ex.Index([p for name, text in ex.NOTES.items() for p in ex.chunk(name, text)])


@pytest.mark.integration
def test_retrieval_finds_the_passage_that_answers_the_question():
    top = _index().search("How do updates reach the browser?")[0][1]
    assert top["doc"] == "Transport"
    assert _index().search("What is a signal?")[0][1]["doc"] == "Reactive model"
    assert _index().search("zebra quantum marmalade") == []


@pytest.mark.integration
def test_an_answer_cites_numbered_sources_in_order():
    question = "How does token streaming work in a chat?"
    answer, cited = ex.compose_answer(question, _index().search(question))
    assert cited and cited[0]["doc"] == "Streaming"
    assert answer.endswith("[1]") or "[1]" in answer
    for n in range(1, len(cited) + 1):
        assert f"[{n}]" in answer
    assert f"[{len(cited) + 1}]" not in answer
    assert ex.compose_answer("zebra", []) == ("", [])


@pytest.mark.integration
def test_long_paragraphs_are_cut_at_a_sentence_and_nothing_is_lost():
    text = " ".join(f"Sentence number {i} says something." for i in range(60))
    parts = ex.chunk("long", text)
    assert len(parts) > 1 and all(len(p["text"]) <= ex.MAX_CHUNK_CHARS for p in parts)
    assert " ".join(p["text"] for p in parts) == text


@pytest.mark.integration
async def test_asking_streams_an_answer_and_fills_the_sources():
    session = ex.build()
    chat = next(c for c in session._by_id.values() if c.type == "chat")
    sources = next(c for c in session._by_id.values() if c.type == "list")
    button = next(
        c
        for c in session._by_id.values()
        if c.type == "button" and c.to_json()["props"]["label"] == "Ask"
    )
    box = next(c for c in session._by_id.values() if c.type == "textinput")
    session.dispatch(box.id, "input", {"value": "Why not use Streamlit?"})
    result = session.dispatch(button.id, "click", {})
    await result.coro
    messages = chat.reactive_props()["messages"]()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "[1]" in messages[1]["content"]
    items = sources.reactive_props()["items"]()
    assert items and items[0]["label"].startswith("[1] Why indah")
    json.dumps(session.snapshot())


@pytest.mark.integration
async def test_nothing_matching_says_so_and_clears_the_sources():
    s = ex.RagChat()
    await s.ask("zebra quantum marmalade")
    assert s.messages.value[-1]["content"] == ex.NOT_FOUND and s.sources.value == []


@pytest.mark.integration
async def test_an_uploaded_file_becomes_a_citable_source_and_can_be_removed():
    s = ex.RagChat()
    note = b"The lighthouse keeper polishes the brass lamp every evening at dusk."
    s.on_upload(ex.indah.UploadedFile("lamp.txt", "text/plain", note))
    await s.ask("When does the keeper polish the lamp?")
    assert s.sources.value[0]["label"] == "[1] lamp.txt"
    s.clear_uploads()
    assert s.uploads == {}
    await s.ask("When does the keeper polish the lamp?")
    assert s.messages.value[-1]["content"] == ex.NOT_FOUND


@pytest.mark.integration
def test_bad_uploads_are_refused_with_a_reason():
    s = ex.RagChat()
    f = ex.indah.UploadedFile
    for file, why in (
        (f("a.pdf", "application/pdf", b"x"), ".txt or .md"),
        (f("big.txt", "text/plain", b"x" * (ex.MAX_UPLOAD_BYTES + 1)), "KB"),
        (f("bin.txt", "text/plain", b"\xff\xfe\x00"), "UTF-8"),
    ):
        s.on_upload(file)
        assert why in s.notice.value and s.uploads == {}
    for i in range(ex.MAX_UPLOADS):
        s.on_upload(f(f"n{i}.txt", "text/plain", b"hello"))
    s.on_upload(f("extra.txt", "text/plain", b"hello"))
    assert len(s.uploads) == ex.MAX_UPLOADS and "At most" in s.notice.value


@pytest.mark.integration
async def test_a_second_question_while_busy_is_ignored_and_the_chat_is_capped():
    s = ex.RagChat()
    s.busy.set(True)
    await s.ask("Why not use Streamlit?")
    assert s.messages.value == []
    s.busy.set(False)
    for _ in range(ex.KEEP_MESSAGES):
        await s.ask("What is a signal?")
    assert len(s.messages.value) == ex.KEEP_MESSAGES
