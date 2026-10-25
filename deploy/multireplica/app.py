"""The app every replica runs in the multi-replica e2e (IND-211, ADR-0043).

A counter that is saved with ``ctx.persist`` (so a rebuilt tab finds it in Redis), the node that
built the tab, the node that handled the last event, and a "Send an event" button so
``deploy/probe/sticky_check.py`` can drive it. Everything else comes from ``INDAH_*`` variables set
in ``compose.yml``. Nothing here is a secret.
"""

from __future__ import annotations

import os

import indah

NODE = os.environ.get("FLY_MACHINE_ID", "local")


def build(ctx: indah.Context) -> indah.Session:
    count = indah.Signal(0)
    handled_by = indah.Signal(NODE)
    ctx.persist("count", count)

    def bump() -> None:
        count.set(count.value + 1)
        handled_by.set(NODE)  # runs on whichever process received the event

    return indah.Session(
        indah.Column(
            children=[
                indah.Text("Multi-replica test", variant="title"),
                indah.Text(f"built on {NODE}", variant="mono"),
                indah.Text(lambda: f"count {count.value}"),
                indah.Text(lambda: f"last event handled on {handled_by.value}", variant="mono"),
                indah.Button("Send an event", bump),
            ]
        )
    )


app = indah.create_app(session_factory=build, title="Multi-replica test", node_header=True)
