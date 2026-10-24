"""Do a tab's stream and its events reach the same machine? (IND-171)

    uv run python deploy/probe/sticky_check.py https://indah-probe.fly.dev \\
        [--events 20] [--new-conn] [--header "Name: value"]

Opens the SSE stream for one session id, finds the "Send an event" button in the first snapshot,
posts N events with that session id, and prints which machine answered each POST
(``X-Probe-Machine``), the HTTP status, and how many of the resulting patches actually arrived on
the tab's stream. With working stickiness every POST is answered by the stream's machine and every
event produces a patch. Standard library and httpx only; the probe never stores anything.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid

import httpx


def find_button(node: dict, label: str) -> str | None:
    if node.get("type") == "button" and node.get("props", {}).get("label") == label:
        return node["id"]
    for child in node.get("children", []):
        found = find_button(child, label)
        if found:
            return found
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--events", type=int, default=20)
    ap.add_argument("--new-conn", action="store_true", help="a fresh connection for every POST")
    ap.add_argument(
        "--header", action="append", default=[], help='extra request header "Name: value"'
    )
    args = ap.parse_args()
    base = args.base.rstrip("/")
    extra = dict(h.split(": ", 1) for h in args.header)
    sid = uuid.uuid4().hex
    state: dict = {"machine": None, "button": None, "patches": 0, "inits": 0, "status": None}
    ready = threading.Event()

    def reader() -> None:
        with httpx.Client(timeout=None, headers=extra) as c:
            with c.stream("GET", f"{base}/api/stream", params={"sid": sid}) as r:
                state["status"] = r.status_code
                state["machine"] = r.headers.get("x-probe-machine")
                for line in r.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    msg = json.loads(line[6:])
                    if msg.get("type") == "init":
                        state["inits"] += 1
                        state["button"] = find_button(msg["root"], "Send an event")
                        ready.set()
                    elif msg.get("type") == "patch":
                        state["patches"] += 1

    threading.Thread(target=reader, daemon=True).start()
    if not ready.wait(40) or not state["button"]:
        raise SystemExit(f"no snapshot with the button (stream status {state['status']})")
    print(f"stream: machine {state['machine']}, session {sid[:8]}")
    body = {"sid": sid, "component": state["button"], "event": "click", "payload": {}}
    answered: dict[str, int] = {}
    statuses: dict[int, int] = {}
    client = None if args.new_conn else httpx.Client(timeout=20, headers=extra)
    for _ in range(args.events):
        c = client or httpx.Client(timeout=20, headers=extra)
        r = c.post(f"{base}/api/event", json=body)
        m = r.headers.get("x-probe-machine", "?")
        answered[m] = answered.get(m, 0) + 1
        statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
        if client is None:
            c.close()
        time.sleep(0.15)
    time.sleep(2)
    same = answered.get(state["machine"] or "", 0)
    print(f"POST answered by: {answered}  statuses: {statuses}")
    print(f"patches that reached the tab's stream: {state['patches']} of {args.events} events")
    print(f"events handled on the stream's machine: {same} of {args.events}")
    print("STICKY" if same == args.events and state["patches"] >= args.events else "NOT STICKY")


if __name__ == "__main__":
    main()
