"""Do a tab's stream and its events reach the same machine? (IND-171)

    uv run python deploy/probe/sticky_check.py https://indah-probe.fly.dev \\
        [--events 20] [--new-conn] [--header "Name: value"] \\
        [--cookies] [--machine-header x-indah-node] [--follow-route]

Opens the SSE stream for one session id, finds the "Send an event" button in the first snapshot,
posts N events with that session id, and prints which machine answered each POST
(``X-Probe-Machine`` by default; ``--machine-header`` names another, such as ``x-indah-node``),
the HTTP status, and how many of the resulting patches actually arrived on the tab's stream.
With working stickiness every POST is answered by the stream's machine and every event produces
a patch. ``--cookies`` makes the check behave like a browser: it loads the page first and sends
the cookies it got (an ingress affinity cookie) on the stream and on every POST. Standard
library and httpx only; the probe never stores anything. ``--follow-route`` acts like indah's shell
(IND-197): it takes ``route`` from the first ``init`` (the app needs ``INDAH_CLUSTER_SECRET``) and
sends ``X-Indah-Route`` and, on Fly, ``fly-force-instance-id`` on every POST, with no gateway
config.
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
    ap.add_argument(
        "--machine-header",
        default="x-probe-machine",
        help="response header that names the machine or pod that answered",
    )
    ap.add_argument(
        "--cookies",
        action="store_true",
        help="act like a browser: GET / first, then send its cookies on the stream and every POST",
    )
    ap.add_argument(
        "--follow-route",
        action="store_true",
        help="send the route hint from init on every POST, like the shell does (IND-197)",
    )
    args = ap.parse_args()
    base = args.base.rstrip("/")
    extra = dict(h.split(": ", 1) for h in args.header)
    sid = uuid.uuid4().hex
    state: dict = {
        "machine": None,
        "button": None,
        "patches": 0,
        "inits": 0,
        "status": None,
        "route": None,
    }
    ready = threading.Event()
    jar = httpx.Cookies()
    if args.cookies:
        with httpx.Client(timeout=20, headers=extra, cookies=jar) as first:
            first.get(f"{base}/")
            jar.update(first.cookies)
        print(f"cookies from the page load: {sorted(jar.keys()) or 'none'}")

    def reader() -> None:
        with httpx.Client(timeout=None, headers=extra, cookies=jar) as c:
            with c.stream("GET", f"{base}/api/stream", params={"sid": sid}) as r:
                state["status"] = r.status_code
                state["machine"] = r.headers.get(args.machine_header)
                for line in r.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    msg = json.loads(line[6:])
                    if msg.get("type") == "init":
                        state["inits"] += 1
                        state["route"] = msg.get("route")
                        state["button"] = find_button(msg["root"], "Send an event")
                        ready.set()
                    elif msg.get("type") == "patch":
                        state["patches"] += 1

    threading.Thread(target=reader, daemon=True).start()
    if not ready.wait(40) or not state["button"]:
        raise SystemExit(f"no snapshot with the button (stream status {state['status']})")
    print(f"stream: machine {state['machine']}, session {sid[:8]}, route {state['route']}")
    route_headers: dict[str, str] = {}
    if args.follow_route:
        route = state["route"]
        if not route:
            raise SystemExit("--follow-route: init carried no route (is INDAH_CLUSTER_SECRET set?)")
        route_headers["X-Indah-Route"] = route["hint"]
        if route.get("transport") == "fly":
            route_headers["fly-force-instance-id"] = route["hint"]
    body = {"sid": sid, "component": state["button"], "event": "click", "payload": {}}
    answered: dict[str, int] = {}
    statuses: dict[int, int] = {}
    client = None if args.new_conn else httpx.Client(timeout=20, headers=extra, cookies=jar)
    for _ in range(args.events):
        c = client or httpx.Client(timeout=20, headers=extra, cookies=jar)
        r = c.post(f"{base}/api/event", json=body, headers=route_headers)
        m = r.headers.get(args.machine_header, "?")
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
