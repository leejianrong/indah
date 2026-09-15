"""Per-session state: two browser tabs, independent state on one app (ADR-0010).

Each viewer gets its own reactive graph, so what you do in one tab never leaks into
another. This app builds a fresh graph per session (a `session_factory`), so open
the printed URL in two tabs and drive them independently: the counter, the name,
and the note in one tab stay entirely private to that tab.

Run it with:  python examples/session_state.py
Then open the URL in two browser tabs. No Node, at install or at runtime.
"""

import indah
from indah import Button, Card, Column, Row, Session, Signal, Text, TextInput, create_app


def build_session() -> Session:
    """A fresh per-viewer graph. Called once per browser tab by the session store."""
    count = Signal(0)
    name = Signal("")
    note = Signal("")

    return Session(
        Column(
            children=[
                Text(
                    "# Per-session state\n\n"
                    "This page is **private to your tab**. Open the same URL in a "
                    "second tab and drive it: the two never share state.",
                    markdown=True,
                ),
                Card(
                    title="Your counter",
                    children=[
                        Text(lambda: f"count = {count.value}"),
                        Row(
                            gap="0.75rem",
                            children=[
                                Button("+1", on_click=lambda: count.set(count.value + 1)),
                                Button("Reset", on_click=lambda: count.set(0), variant="tonal"),
                            ],
                        ),
                    ],
                ),
                Card(
                    title="Your details",
                    children=[
                        TextInput(name, label="Name", placeholder="Type your name..."),
                        TextInput(note, label="A private note", placeholder="Only this tab"),
                        Text(
                            lambda: (
                                f"Hi {name.value or 'stranger'} - "
                                f"your note is: {note.value or '(empty)'}"
                            )
                        ),
                    ],
                ),
            ]
        )
    )


if __name__ == "__main__":
    # session_factory (not session=) is what makes each tab isolated: the store
    # calls it once per session id the shell sends.
    indah.launch(create_app(session_factory=build_session))
