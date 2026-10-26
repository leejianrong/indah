# ADR-0045: Tier 1 live media transport (WebSocket, opt-in)

- Status: Proposed
- Date: 2026-10-27
- Deciders: Jian (owner)

## Context

ADR-0017 declared two transport tiers and left Tier 1 (a WebSocket for continuous binary, for
live webcam and microphone) unbuilt. Tier 0 (SSE + POST, ADR-0002) stays the floor and the only tier
Colab's proxy passes. Three demos wait on Tier 1: real-time webcam detection (IND-64), streaming
speech recognition from the mic (IND-65), and, only partly, stepped video detection (IND-62, which
fits Tier 0 with upload + `ImageOverlay`, ADR-0020).

Constraints that shape the design:

- The hosted layer (ADR-0033 to 0038) is all off by default and every route goes through the same
  identity, origin, rate and CSP rules. A new route must not become a hole in them. A WebSocket is
  the classic one: browsers do not apply the same-origin policy to it, so an attacker page can open
  one with the victim's cookies unless the server checks `Origin`.
- `uvicorn` serves WebSockets only with `websockets` or `wsproto` installed, and neither is an
  indah dependency today. The base install must stay small and pure Python (no Node, ADR-0004).
- The strict CSP is `connect-src 'self'` (ADR-0038). Whether `'self'` covers `ws:`/`wss:` differs
  between browsers and versions.
- Several middlewares (`ProxyHeaders`, `OriginGuard`, `RateLimitMiddleware`) act on `http` scopes
  only and let a `websocket` scope through unexamined.

## Decision

Add an **opt-in** WebSocket route that carries **client to server binary media only**. Everything
the server sends back (detections, transcripts, state) keeps using Tier 0 SSE patches. This is the
smallest thing that serves webcam detection and streaming ASR, and it keeps the reactive path, resume
and multi-tab behaviour exactly as they are.

### Opt-in, off by default

- `create_app(live=True)` (or `live=Live(...)` to tune the caps below) mounts `WebSocket /api/live`.
  The default is `live=False`: no route, no `websockets` import, no change to any header or CSP.
- It needs the `indah[live]` extra (`websockets>=12`). `live=True` without it raises at
  `create_app` with the install command, never at first connect.
- The server tells the shell with `"live": {"path": "api/live", "v": 1}` in `window.__INDAH_CHROME__`
  only when live is on and usable. No flag means the shell never tries a socket.

### Components and Python API (new public names, accepted here)

- `Camera(on_frame=handler, fps=5, max_width=640, quality=0.7)`: the shell asks for the camera with
  `getUserMedia`, shows a local preview, and sends one JPEG per tick (canvas `toBlob`; no codec, no
  WASM, no Node).
- `Microphone(on_audio=handler, sample_rate=16000)`: 16-bit mono PCM chunks from an AudioWorklet.
  A later slice (IND-65); the wire format below already reserves it.
- The handler gets `Frame(data: bytes, content_type: str, seq: int, ts: float)` (or `AudioChunk`).
  It is an ordinary handler (ADR-0009): it runs in the sender's session under `authz_scope`, may be
  `async`, and a sync one runs in a worker thread so a slow model never blocks the event loop.
  Results are set on signals as usual and reach the page as SSE patches, for example
  `ImageOverlay(boxes=...)`.
- Decoding is the app's job (`PIL`, `numpy`, `soundfile` are the user's dependencies, as with
  `Upload`).

### Wire format (the "live" sub-protocol, version 1)

One socket per live component, so one stream never head-of-line blocks another.

1. The client's first message is a JSON text frame:
   `{"type":"hello","v":1,"sid":"<session id or signed token>","component":"<id>","kind":"video"|"audio"}`.
   The session id travels in this frame, never in the URL, so it stays out of access logs.
2. The server answers `{"type":"ready"}`, or closes with a code (below).
3. After that the client sends **binary frames**: a 4-byte big-endian unsigned `seq`, then the
   payload (JPEG bytes, or PCM16 samples). No per-frame JSON.
4. The server may send text frames `{"type":"stats","dropped":n,"processed":n}` about once a second
   (drives the shell's drop counter and tests) and `{"type":"error","message":...}` before closing.

Close codes: `1001` draining or going away, `1009` frame over the cap, `1008` policy (origin or
authz), `4400` bad hello or `v` mismatch, `4401` unauthenticated, `4403` forbidden, `4409` unknown
session (the page must reconnect its stream first), `4429` over the per-address socket cap.

### Backpressure and frame dropping

Live video is worthless late, so the rule is **latest frame wins**, at both ends:

- **Client.** Before sending, the shell checks `ws.bufferedAmount`. Above a threshold (default
  256 KiB) it skips that tick and counts it, so a slow uplink degrades the frame rate and not the
  latency. It never queues.
- **Server, video.** Each socket has a one-slot mailbox and one worker. A frame that arrives while
  the handler is busy replaces the waiting one (the replaced frame counts as dropped). The handler
  therefore always sees the newest frame and at most one runs at a time.
- **Server, audio.** Audio cannot drop silently without damaging a transcript, so it uses a bounded
  queue (default 2 s of audio) that drops the oldest chunk when full and counts it. The handler is
  told via `AudioChunk.dropped_before`.
- Caps that are always on when live is on: frame size (default 1 MiB, then `1009`), sockets per
  address (default 4, then `4429`), and a total byte budget per socket per second. `Live(...)`
  tunes them. `Limits` (ADR-0037) is for HTTP; live has its own caps because a long-lived socket
  is not a request.

### Security posture (nothing existing changes)

- **Origin.** A WebSocket upgrade is checked with the same `origin_allowed` rule as `OriginGuard`
  (ADR-0033), `allowed_origins` included, **whether or not the app is secure**, since this is a new
  route with no old behaviour to keep. A request with no `Origin` header passes, as there.
- **Identity.** The upgrade request goes to the app's `authenticate` callback (it receives a
  Starlette `HTTPConnection`, which has `headers`, `cookies` and `client` for both scopes). On a
  secure app the `hello` `sid` must be a signed token verified for that principal and a session owned
  by someone else is `4403`, using the same checks as `_open_session` (ADR-0033). The socket only
  attaches to a session that already exists (made by `api/stream`), never creates one.
- **Authz.** The handler runs under `authz_scope(principal, policy)`; a component the policy denies
  is closed `4403` (ADR-0035). The component must be a `Camera` or `Microphone` node of that
  session, so a socket cannot drive an arbitrary event.
- **Audit.** Open and close are audited with component and kind (ADR-0034). Frames are never
  audited and never logged.
- **Drain.** On drain sockets are closed `1001` and the shell reconnects like SSE.
- **Trusted proxies** (ADR-0034). `ProxyHeaders` is extended to `websocket` scopes so client
  address, `Host` and prefix are believed exactly as for HTTP, and `X-Forwarded-Proto` `https` maps
  to `wss`. Without this the origin comparison and the per-address cap would see the proxy.
  Documentation lists the proxy presets that pass an `Upgrade` (Cloudflare, Fly, Traefik and nginx do;
  Colab does not).
- **Multi-replica** (ADR-0043). The upgrade is a GET, so the existing `?r=<machine>` route hint
  applies. A replica that does not hold the session closes `4409`.

### CSP and permissions

- `connect-src 'self'` is kept, and when live is on the policy gains the explicit
  `ws://<host>` or `wss://<host>` of the request (built from the believed scheme and host per
  response, like the nonce), because `'self'` matching WebSocket schemes is not reliable across
  browsers. A custom `csp=` string is the owner's and untouched. With live off the CSP is
  byte-for-byte what it is today.
- `getUserMedia` needs no CSP directive. The AudioWorklet module is served from `GET /api/live-audio.js`
  (same origin), so `script-src 'self'` covers it and no `blob:` source is added.
- `getUserMedia` needs a secure context (https or `localhost`). The shell shows a plain explanation
  on plain-http LAN addresses. indah sets no `Permissions-Policy`; an owner who sets `camera=()`
  gets a clear in-page error, not a silent failure.

### Colab and fallback to Tier 0

- On Colab (`detect_environment()` is `COLAB`) live is **not advertised** even with `live=True`, and
  the server logs one notice. A shell that sees no `live` flag, whose socket does not become `ready`
  within 3 s, or whose socket closes abnormally, falls back.
- The fallback is Tier 0 **snapshot mode**: the same capture loop posts a JPEG to `POST /api/upload`
  (ADR-0017) at a low cap (about 1 frame per second, one in flight), and the same handler runs. A demo
  works on Colab at a reduced rate with no code change, and `Camera.transport` (a read-only signal:
  `"live"`, `"snapshot"`, `"off"`) lets an app say which it is on. Microphone has no Tier 0 live path;
  it falls back to record-then-upload.

### No Node, no new runtime requirement

The capture code is a few hundred lines in the pre-built shell (`frontend/`, rebuilt with
`make frontend`, committed as `src/indah/static/index.html`). Install and runtime still need no
Node. The only new Python dependency is the optional `websockets`.

### Versioning

Additive. `protocol_version` stays 1: no SSE message changes, the new `camera` and `microphone`
node types go in the built-ins like any component, and the socket has its own `v` in `hello`
(live sub-protocol 1) so it can change without bumping the SSE protocol. `docs/protocol.md` gets a
"Live media (Tier 1)" section and its Tier 1 paragraph is rewritten.

## Alternatives considered

| Option | Why not |
|--------|---------|
| WebSocket for everything (state too) | Breaks Colab and drops resume, replay and multi-tab behaviour that Tier 0 already has |
| WebRTC | Needs a TURN/STUN story and a native or Python media stack (aiortc, system libs); far from "pure Python, one port" |
| Send frames over `POST /api/upload` only | That is the fallback: a request per frame costs a TCP/TLS round trip and head-of-line blocks, so it caps at a few fps |
| `MediaRecorder` WebM chunks | Needs server-side demux and decode to get a frame; JPEG per tick is decodable by every imaging library |
| Server to client media over the socket now | Not needed by either demo (results are small JSON); reserved, not built |
| Always-on, probed at connect | Opens a new route on every app and every default policy; this is opt-in because a socket changes the exposure of a hosted app |
| Skip the Origin check on non-secure apps | Cross-site WebSocket hijacking would let any page stream a victim's camera into a local dev server; a new route needs no legacy exemption |

## Consequences

- Real-time detection and streaming ASR become possible off Colab, and degrade to a slow but
  working mode on Colab.
- A new optional dependency and a new route, both off by default. Existing apps are unchanged: same
  routes, same CSP, same headers.
- The proxy middleware now sees `websocket` scopes, which is a small behaviour extension covered by
  tests; HTTP behaviour is unchanged.
- Model work is the user's: indah moves bytes, bounds them, and drops late frames, nothing more. A
  handler that is slower than the frame rate sees a lower rate and always the freshest frame.
- Open questions for the owner, not decided here: whether `live` should ever default on outside
  Colab (this ADR says no), and whether the Studio should host live demos on the public gallery
  (a camera on a shared multi-user host is a privacy and cost question).

## Slices

1. Transport: `live=` option, `/api/live`, mailbox/backpressure, origin and identity checks,
   `ProxyHeaders` for websockets, CSP, unit and integration tests, `Camera` with the shell capture
   loop and the Tier 0 snapshot fallback, protocol.md.
2. Demo IND-64: webcam detection with `Camera` plus `ImageOverlay`.
3. `Microphone` and the streaming ASR demo (IND-65); IND-62 needs only Tier 0.
