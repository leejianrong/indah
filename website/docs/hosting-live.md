# Live camera and microphone

How to turn on the WebSocket that carries camera frames and microphone audio, and what changes when it is on.

## Live camera

A `Camera` component sends webcam frames to a handler you write. By default the frames go as one
snapshot a second over the upload route, which works everywhere, Colab included. For a smooth feed,
turn on the WebSocket:

```bash
pip install "indah[live]"
```

```python
# live=indah.Live(max_sockets_per_address=2) tunes the caps
app = indah.create_app(session_factory=build, live=True)
```

Live is off unless you ask for it, and indah never turns it on for you. Colab's proxy blocks
WebSockets, so there `live=True` is ignored with a warning and the camera sends snapshots. What
changes when it is on:

- The upgrade is refused for a cross-site `Origin`, whether or not the app is `secure` (a browser does not
  apply the same-origin policy to a WebSocket). `allowed_origins` applies.
- On a `secure` app the socket uses the same signed session token as every other request.
- Behind a proxy, set `trusted_proxies` as usual, and make sure the proxy passes `Upgrade` requests
  (Cloudflare, Fly and Traefik do).
- With `csp="strict"`, `connect-src` also names the page's own `ws://` or `wss://` origin. Nothing
  else about the policy changes, and with live off it is exactly as before.
- Each address may hold 4 sockets, a frame over 1 MiB closes the socket, and a handler that is slower
  than the camera sees fewer frames, always the newest. Run a heavy model with
  `await asyncio.to_thread(model, frame.data)`.
- The browser only gives out the camera on `https://` pages or `localhost`.

### Live microphone

A `Microphone` rides the same socket and the same switches: `live=True` turns it on, and nothing is
added for an app that does not. Its handler gets an `AudioChunk` of 16-bit mono PCM (about 100 ms),
in order. If the handler is slower than speech, audio waits up to `Live.audio_buffer_seconds` (2 s),
then the oldest is dropped and the next chunk says so in `dropped_before`. The page loads a small
AudioWorklet from `/api/live-audio.js` on your own origin, which the strict CSP already allows. On
Colab, or wherever the socket is unavailable, the browser records and sends one WAV take when you
press Stop. See `examples/mic_transcribe.py`.
