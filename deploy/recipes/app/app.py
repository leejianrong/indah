"""A small indah app to deploy with the Fly and Kubernetes recipes. Replace it with your own.

It shows which process built the page and which one handled the last click, so you can see a
rollout, a second replica or a missing affinity cookie with your own eyes. Configuration comes from
`INDAH_*` environment variables (see the hosting guide): the recipes set `INDAH_TRUSTED_PROXIES`,
`INDAH_NODE_HEADER` and `INDAH_DRAIN_SECONDS`, and a secret `INDAH_DOCTOR_TOKEN` turns on
`/_indah/doctor`.

    uvicorn app:app --no-proxy-headers
"""

from __future__ import annotations

import os
import socket

import indah

# The process name as the platform knows it: a Fly machine id, a pod name, or the host name.
NODE = os.environ.get("INDAH_NODE") or os.environ.get("FLY_MACHINE_ID") or socket.gethostname()


def build(ctx: indah.Context) -> indah.Session:
    events = indah.Signal(0)
    last = indah.Signal(NODE)

    def ping() -> None:
        events.set(events.value + 1)
        last.set(NODE)  # runs on whichever process received the click

    return indah.Session(
        indah.Column(
            children=[
                indah.Text("indah is running", variant="title"),
                indah.Text(f"This page was built by {NODE}.", variant="mono"),
                indah.Text(
                    lambda: f"{events.value} event(s), the last handled by {last.value}",
                    variant="mono",
                ),
                indah.Button("Send an event", ping),
                indah.Text(
                    "With two replicas and no affinity the count stops moving: see the guide.",
                    variant="caption",
                ),
            ]
        )
    )


app = indah.create_app(session_factory=build, title="indah on your platform")
