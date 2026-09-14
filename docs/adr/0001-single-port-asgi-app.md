# ADR-0001: Serve frontend and backend from one ASGI app on one port

- Status: Accepted
- Date: 2026-09-14
- Deciders: Jian (owner)

## Context

The target environments — Google Colab and RunPod — expose a running server to
the outside world through an HTTP proxy tied to a single port
(`google.colab.kernel.proxyPort(N)`; `https://{pod}-{port}.proxy.runpod.net`).
Reflex's split of a Next.js port and a FastAPI port is exactly what breaks these
proxies. R0 and R2 require the app to be reachable through one proxied port with
no build step.

## Decision

indah runs as a single ASGI application (Starlette, served by Uvicorn) on one
port. A static route serves the pre-built frontend shell from inside the package;
all dynamic behaviour lives under `/api/*` on the same origin and port. `launch()`
binds the port, detects Colab vs RunPod vs local, and prints/embeds the correct
URL.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Separate frontend + backend ports (Reflex-style) | Colab/RunPod proxy one port; a second port is unreachable |
| Static assets on a CDN, API on the pod | Adds an external dependency and breaks offline/air-gapped use |
| Serve frontend from Jupyter's own server | Couples us to the notebook host; fails for `python app.py` and RunPod tabs |

## Consequences

- Buys trivial proxy compatibility and offline operation; one URL to share.
- Costs us the option of scaling frontend and backend independently — acceptable
  for a dev/notebook tool.
- Requires that same-origin be assumed everywhere, which simplifies the transport
  (no CORS) but means the transport choice (ADR-0002) must also live on this port.
