"""Measure indah's event-to-patch latency through any URL (IND-140).

For each sample it POSTs ``api/event`` and times how long until the matching ``patch``
arrives on the open SSE stream, so it measures the whole round trip a user feels:
client -> gateway -> app -> reactive flush -> SSE -> gateway -> client. Run it on
localhost for the floor, then through the real gateway (Fly + Cloudflare) or a Colab
proxy URL for the number that matters.

    uv run python scripts/latency_probe.py http://127.0.0.1:8000/            # list nodes
    uv run python scripts/latency_probe.py URL --component n2 --event input \\
        --payload '{"value": "probe-{i}"}' --samples 100 --rate 1.5

``{i}`` in ``--payload`` is replaced by the sample number, so each event changes state
(an unchanged value produces no patch). ``--rate`` is events per second: keep it under
the target's rate limit (the public gallery allows a burst of 30, then 2 per second).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid

import httpx


def _walk(node: dict, out: list[dict]) -> None:
    out.append(node)
    for child in node.get("children", []):
        _walk(child, out)


async def _messages(resp: httpx.Response):
    """Yield (arrival_time, message) for each ``data:`` frame on an SSE response."""
    async for line in resp.aiter_lines():
        if line.startswith("data:"):
            yield time.perf_counter(), json.loads(line[5:])


def percentile(sorted_ms: list[float], p: float) -> float:
    k = (len(sorted_ms) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(sorted_ms) - 1)
    return sorted_ms[lo] + (sorted_ms[hi] - sorted_ms[lo]) * (k - lo)


async def probe(args: argparse.Namespace) -> int:
    base = args.url if args.url.endswith("/") else args.url + "/"
    sid = f"probe-{uuid.uuid4().hex[:12]}"
    timeout = httpx.Timeout(10.0, read=None)
    async with httpx.AsyncClient(timeout=timeout, http2=args.http2) as client:
        async with client.stream("GET", f"{base}api/stream", params={"sid": sid}) as resp:
            resp.raise_for_status()
            stream = _messages(resp).__aiter__()
            init = None
            async for _, msg in stream:
                if msg.get("type") == "init":
                    init = msg
                    break
            if init is None:
                print("no init message", file=sys.stderr)
                return 1
            # A background reader stamps each frame on arrival, so a patch that lands
            # before the POST response is not charged for the time we spent not reading.
            frames: asyncio.Queue = asyncio.Queue()

            async def pump() -> None:
                try:
                    async for arrived, msg in stream:
                        frames.put_nowait((arrived, msg))
                except httpx.HTTPError:
                    pass  # the stream closed under us; the sample loop reports the timeout

            pump_task = asyncio.create_task(pump())
            nodes: list[dict] = []
            _walk(init["root"], nodes)
            if not args.component:
                for n in nodes:
                    print(n["id"], n["type"], json.dumps(n["props"])[:90])
                pump_task.cancel()
                return 0

            posts: list[float] = []
            e2e: list[float] = []
            failures = 0
            interval = 1.0 / args.rate
            for i in range(args.samples):
                body = {
                    "component": args.component,
                    "event": args.event,
                    "payload": json.loads(args.payload.replace("{i}", str(i))),
                    "sid": sid,
                }
                while not frames.empty():
                    frames.get_nowait()
                t0 = time.perf_counter()
                r = await client.post(f"{base}api/event", json=body)
                t_post = time.perf_counter()
                if r.status_code != 200:
                    failures += 1
                    print(f"sample {i}: POST {r.status_code}", file=sys.stderr)
                    await asyncio.sleep(interval)
                    continue
                try:
                    while True:
                        arrived, msg = await asyncio.wait_for(frames.get(), args.wait)
                        if msg.get("type") == "patch":
                            break
                except asyncio.TimeoutError:
                    failures += 1
                    print(f"sample {i}: no patch within {args.wait}s", file=sys.stderr)
                    continue
                posts.append((t_post - t0) * 1000)
                e2e.append((arrived - t0) * 1000)
                await asyncio.sleep(max(0.0, interval - (time.perf_counter() - t0)))
            pump_task.cancel()

    if not e2e:
        print("no successful samples", file=sys.stderr)
        return 1
    e2e.sort()
    posts.sort()
    print(f"target {base}  samples ok={len(e2e)} failed={failures}")
    for label, xs in (("event -> patch", e2e), ("POST response", posts)):
        print(
            f"  {label:15} p50 {percentile(xs, 0.5):7.1f} ms  p95 {percentile(xs, 0.95):7.1f} ms"
            f"  max {xs[-1]:7.1f} ms  mean {statistics.mean(xs):7.1f} ms  min {xs[0]:7.1f} ms"
        )
    return 0 if not failures else 2


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("url", help="app root, e.g. http://127.0.0.1:8000/ or https://host/slug/")
    ap.add_argument("--component", help="node id to drive; omit to list the nodes and exit")
    ap.add_argument("--event", default="input")
    ap.add_argument("--payload", default='{"value": "probe-{i}"}')
    ap.add_argument("--samples", type=int, default=100)
    ap.add_argument("--rate", type=float, default=1.5, help="events per second")
    ap.add_argument("--wait", type=float, default=10.0, help="seconds to wait for each patch")
    ap.add_argument("--http2", action="store_true", help="needs httpx[http2]")
    sys.exit(asyncio.run(probe(ap.parse_args())))


if __name__ == "__main__":
    main()
