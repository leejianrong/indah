"""Ask questions of documents and get answers with numbered citations.

Ask about the bundled notes on indah, or upload your own ``.txt`` / ``.md`` files and ask about
those. Each answer is built from the passages that best match the question, every sentence ends in
a citation such as ``[1]``, and the **Sources** panel prints the passage each number points to, so
you can check the answer against the text it came from.

There is **no language model** in this demo. Retrieval is BM25 over paragraph-sized chunks, and an
answer is the best-matching sentences copied out of the top passages, in order, each tagged with
its source. That keeps the demo small, offline and honest: the app can only say what the documents
say, and it says "I could not find that" when nothing matches. To use a real model, replace
``compose_answer`` with a call that takes the question and the passages and returns text with the
same ``[n]`` markers; the retrieval, the citations and the UI do not change.

What it shows off:
- ``Chat`` with a live pending bubble that streams the answer word by word (an async handler);
- a keyed ``List`` with a render spec, here the Sources panel, rebuilt for each answer;
- ``Upload`` with type, size and count limits, and per-session state (``session_factory``), so one
  visitor's documents are never another's.

Run it with:  python examples/rag_chat.py   (prints a URL; embeds inline in a notebook cell).
Needs only indah.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter

import indah

MAX_UPLOADS = 5
MAX_UPLOAD_BYTES = 100_000
MAX_CHUNK_CHARS = 600
TOP_K = 3
MAX_SENTENCES = 4
KEEP_MESSAGES = 40  # a long chat is trimmed so one visitor cannot grow the page without bound
WORD_PAUSE = 0.02  # seconds between streamed words

NOTES: dict[str, str] = {
    "Why indah": (
        "Streamlit reruns the whole script on every interaction. Gradio is rigid about layout. "
        "Reflex needs a Node build step, which fails inside short-lived cloud containers.\n\n"
        "indah is a Python UI framework for ephemeral cloud notebooks such as Colab and Runpod. "
        "It is reactive, serves everything from a single port, and needs no Node at install or "
        "at run time."
    ),
    "Transport": (
        "An indah app is one ASGI application on one port. Updates reach the browser over "
        "server-sent events, and the browser sends events back with ordinary POST requests.\n\n"
        "Because it uses plain HTTP and no WebSocket, it works behind the proxies that notebook "
        "services put in front of an app, where a second port or a WebSocket often does not."
    ),
    "Reactive model": (
        "State lives in signals. A computed value derives from signals, and an effect runs when "
        "the signals it read change.\n\n"
        "When a signal changes, only the components that depend on it are updated, and the "
        "server sends the browser a small patch instead of redrawing the page."
    ),
    "Streaming": (
        "Handlers can be async. A long task can update a signal as it goes, and the browser shows "
        "each change as it arrives.\n\n"
        "This is how an LLM reply streams token by token into a chat: the pending message grows "
        "while the model generates, and the rest of the page stays responsive."
    ),
    "Hosting": (
        "For a shared deployment indah can add signed sessions with an identity, role-based "
        "authorisation, request hardening, trusted proxy handling with an audit log, and a strict "
        "content security policy.\n\n"
        "All of these are off by default, so a notebook demo stays as simple as it was."
    ),
    "Components": (
        "The starter set covers text, buttons, sliders, text inputs, selects, images, plots, "
        "tables and charts. Layout components arrange them in rows, columns, cards and "
        "sidebars.\n\n"
        "An app that needs something else can register its own component, which the browser "
        "renders without a Node build."
    ),
}

SUGGESTIONS = [
    "Why not use Streamlit?",
    "How do updates reach the browser?",
    "How does token streaming work?",
]

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be by do does for from how in is it its of on or so that the their then "
    "use used there these this to was what when where which who why will with you your not no "
    "can".split()
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def tokens(text: str) -> list[str]:
    """Lowercase words minus stop words, with a crude plural fold so 'signals' finds 'signal'."""
    out = []
    for w in _WORD.findall(text.lower()):
        if w in _STOP:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w not in _STOP:
            out.append(w)
    return out


def chunk(doc: str, text: str) -> list[dict]:
    """A document -> passages: its paragraphs, long ones cut at a sentence boundary."""
    out: list[dict] = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        while para:
            if len(para) <= MAX_CHUNK_CHARS:
                piece, para = para, ""
            else:
                cut = max(para.rfind(". ", 0, MAX_CHUNK_CHARS), para.rfind(" ", 0, MAX_CHUNK_CHARS))
                cut = cut if cut > 0 else MAX_CHUNK_CHARS
                piece, para = para[: cut + 1].strip(), para[cut + 1 :].strip()
            if piece:
                out.append({"doc": doc, "text": piece})
    return out


class Index:
    """BM25 over a list of passages. Rebuilt whenever the documents change; it is tiny."""

    K1, B = 1.5, 0.75

    def __init__(self, passages: list[dict]) -> None:
        self.passages = passages
        self.terms = [Counter(tokens(p["text"])) for p in passages]
        self.lengths = [sum(c.values()) for c in self.terms]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter = Counter()
        for c in self.terms:
            df.update(c.keys())
        n = len(passages)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, question: str, k: int = TOP_K) -> list[tuple[float, dict]]:
        query = set(tokens(question))
        scored = []
        for i, counts in enumerate(self.terms):
            norm = 1 - self.B + self.B * (self.lengths[i] / self.avg if self.avg else 0)
            score = sum(
                self.idf[t] * counts[t] * (self.K1 + 1) / (counts[t] + self.K1 * norm)
                for t in query
                if t in counts
            )
            if score > 0:
                scored.append((score, self.passages[i]))
        scored.sort(key=lambda s: -s[0])
        return scored[:k]


def compose_answer(question: str, hits: list[tuple[float, dict]]):
    """The answer text and the passages it cites, from the ranked hits.

    Keeps hits scoring at least 40% of the best, takes each one's best-matching sentence, and
    puts ``[n]`` after it, numbering the passages in the order first cited. Returns
    ``("", [])`` when there is nothing to say.
    """
    if not hits:
        return "", []
    best = hits[0][0]
    query = set(tokens(question))
    sentences, cited = [], []
    for score, passage in hits:
        if score < 0.4 * best or len(sentences) >= MAX_SENTENCES:
            continue
        parts = [s for s in _SENTENCE.split(passage["text"]) if s]
        top = max(parts, key=lambda s: len(query & set(tokens(s))))
        if passage not in cited:
            cited.append(passage)
        sentences.append(f"{top} [{cited.index(passage) + 1}]")
    return " ".join(sentences), cited


def read_upload(file: indah.UploadedFile) -> str:
    """The text of an uploaded file, or a ``ValueError`` saying why it was refused."""
    name = file.filename or "upload"
    if not name.lower().endswith((".txt", ".md")):
        raise ValueError(f"{name}: upload a .txt or .md file.")
    if file.size > MAX_UPLOAD_BYTES:
        raise ValueError(f"{name}: over {MAX_UPLOAD_BYTES // 1000} KB.")
    try:
        return file.data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{name}: not UTF-8 text.") from exc


NOT_FOUND = (
    "I could not find that in the documents. Try other words, or upload a file that covers it."
)

SOURCE_ITEM = {
    "tag": "div",
    "children": [
        {"tag": "strong", "text": "label"},
        {"tag": "p", "text": "text"},
    ],
}


class RagChat:
    """One viewer's documents, conversation and the sources of the latest answer."""

    def __init__(self) -> None:
        self.uploads: dict[str, str] = {}
        self.index = self._build()
        self.messages = indah.Signal([])
        self.pending = indah.Signal("")
        self.question = indah.Signal("")
        self.sources = indah.Signal([])
        self.notice = indah.Signal("")
        self.busy = indah.Signal(False)
        self.docs = indah.Signal(self._summary())

    def _passages(self) -> list[dict]:
        out = []
        for name, text in {**NOTES, **self.uploads}.items():
            out.extend(chunk(name, text))
        return out

    def _build(self) -> Index:
        return Index(self._passages())

    def _summary(self) -> str:
        mine = ", ".join(self.uploads) or "none"
        return f"{len(NOTES)} bundled notes. Your files: {mine}."

    def _refresh(self) -> None:
        self.index = self._build()
        self.docs.set(self._summary())
        self.sources.set([])

    def on_upload(self, file: indah.UploadedFile) -> None:
        try:
            if len(self.uploads) >= MAX_UPLOADS and file.filename not in self.uploads:
                raise ValueError(f"At most {MAX_UPLOADS} files. Clear them first.")
            self.uploads[file.filename] = read_upload(file)
        except ValueError as exc:
            self.notice.set(str(exc))
            return
        self.notice.set(f"Added {file.filename}.")
        self._refresh()

    def clear_uploads(self) -> None:
        self.uploads.clear()
        self.notice.set("Your files were removed.")
        self._refresh()

    def _say(self, role: str, content: str) -> None:
        self.messages.set(
            [*self.messages.value, {"role": role, "content": content}][-KEEP_MESSAGES:]
        )

    async def ask(self, text: str | None = None) -> None:
        question = (text if text is not None else self.question.value).strip()
        if not question or self.busy.value:
            return
        self.busy.set(True)
        try:
            self.question.set("")
            self._say("user", question)
            answer, cited = compose_answer(question, self.index.search(question))
            self.sources.set(
                [
                    {"id": str(n), "label": f"[{n}] {p['doc']}", "text": p["text"]}
                    for n, p in enumerate(cited, 1)
                ]
            )
            reply = answer or NOT_FOUND
            self.pending.set("")
            for word in reply.split(" "):
                self.pending.set((self.pending.value + " " + word).strip())
                await asyncio.sleep(WORD_PAUSE)
            self._say("assistant", reply)
            self.pending.set("")
        finally:
            self.busy.set(False)


def build() -> indah.Session:
    s = RagChat()

    async def chip(text: str) -> None:
        await s.ask(text)

    chat = indah.Chat(s.messages, pending=s.pending, label="Conversation")
    ask_row = indah.Row(
        children=[
            indah.TextInput(s.question, placeholder="Ask about the documents", on_submit=s.ask),
            indah.Button("Ask", on_click=s.ask),
        ]
    )
    chips = indah.Row(
        children=[
            indah.Button(q, on_click=(lambda q=q: chip(q)), variant="ghost") for q in SUGGESTIONS
        ],
        gap="0.5rem",
        align="start",
    )
    sources = indah.Card(
        title="Sources",
        children=[
            indah.List(
                s.sources,
                item=SOURCE_ITEM,
                key="id",
                empty="Ask a question and the passages behind the answer appear here.",
            ),
        ],
    )
    documents = indah.Card(
        title="Documents",
        children=[
            indah.Text(lambda: s.docs.value),
            indah.Upload(
                s.on_upload, accept=".txt,.md,text/plain,text/markdown", label="Add a file"
            ),
            indah.Button("Remove my files", on_click=s.clear_uploads, variant="tonal"),
            indah.Text(lambda: s.notice.value),
        ],
    )
    intro = indah.Text(
        "# Ask the documents\n\n"
        "Answers are sentences copied from the passages that best match your question, each with "
        "a number that points to its source. There is no language model: it cannot say anything "
        "the documents do not.",
        markdown=True,
    )
    return indah.Session(
        indah.Column(
            children=[
                intro,
                indah.Sidebar(
                    children=[
                        indah.Column(children=[documents, sources]),
                        indah.Column(children=[chips, chat, ask_row]),
                    ]
                ),
            ]
        )
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)
