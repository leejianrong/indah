<script>
  // A live webcam input (ADR-0045). The browser captures; the server only receives JPEG frames.
  // Tier 1: one binary WebSocket frame per tick (4-byte big-endian seq + JPEG), skipped when the
  // socket's send buffer is backed up (latest frame wins, never queue). Tier 0 fallback: one frame
  // a second through the upload route, so the same Python handler runs where a WebSocket cannot.
  import { onDestroy } from "svelte";
  import { postEvent, postUpload, sessionId, liveConfig, liveUrl } from "./api.js";

  let { node, props } = $props();

  const READY_TIMEOUT_MS = 3000;
  const RETRY_MS = 10000;
  const MAX_BUFFERED = 256 * 1024;
  const SNAPSHOT_MS = 1000;

  let videoEl = $state();
  let canvasEl;
  let running = $state(false);
  let transport = $state("off");
  let message = $state("");
  let sent = $state(0);
  let skipped = $state(0);
  let dropped = $state(0);

  let stream = null;
  let socket = null;
  let timer = null;
  let retry = null;
  let seq = 0;
  let busy = false; // a frame is being encoded or posted: never more than one

  function setTransport(next) {
    if (transport === next) return;
    transport = next;
    postEvent(node.id, "transport", { value: next });
  }

  function openLive() {
    return new Promise((resolve) => {
      const url = liveUrl();
      if (!url || typeof WebSocket === "undefined") return resolve(null);
      let ws;
      let settled = false;
      const done = (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(wait);
        resolve(value);
      };
      const wait = setTimeout(() => {
        try {
          ws.close();
        } catch (e) {
          /* already closed */
        }
        done(null);
      }, READY_TIMEOUT_MS);
      try {
        ws = new WebSocket(url);
      } catch (e) {
        return done(null);
      }
      ws.binaryType = "arraybuffer";
      ws.onopen = () =>
        ws.send(
          JSON.stringify({
            type: "hello",
            v: liveConfig().v,
            sid: sessionId(),
            component: node.id,
            kind: "video",
          }),
        );
      ws.onmessage = (event) => {
        if (typeof event.data !== "string") return;
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch (e) {
          return;
        }
        if (msg.type === "ready") done(ws);
        else if (msg.type === "stats") dropped = msg.dropped;
      };
      ws.onerror = () => done(null);
      ws.onclose = () => {
        done(null);
        if (socket === ws) {
          socket = null;
          if (running) useSnapshots("Live connection closed, sending snapshots");
        }
      };
    });
  }

  function schedule(ms) {
    clearInterval(timer);
    timer = setInterval(tick, ms);
  }

  function useSnapshots(why) {
    message = why;
    setTransport("snapshot");
    schedule(SNAPSHOT_MS);
    clearTimeout(retry);
    if (liveConfig()) retry = setTimeout(tryLive, RETRY_MS);
  }

  async function tryLive() {
    if (!running || socket) return;
    const ws = await openLive();
    if (!running) {
      if (ws) ws.close();
      return;
    }
    if (ws) {
      socket = ws;
      message = "";
      setTransport("live");
      schedule(1000 / (props.fps || 5));
    } else {
      clearTimeout(retry);
      retry = setTimeout(tryLive, RETRY_MS);
    }
  }

  function tick() {
    if (busy || !videoEl || !videoEl.videoWidth) return;
    if (socket && socket.bufferedAmount > MAX_BUFFERED) {
      skipped += 1; // the uplink is behind: skip this tick rather than queue it
      return;
    }
    const scale = Math.min(1, (props.maxWidth || 640) / videoEl.videoWidth);
    const w = Math.round(videoEl.videoWidth * scale);
    const h = Math.round(videoEl.videoHeight * scale);
    canvasEl.width = w;
    canvasEl.height = h;
    canvasEl.getContext("2d").drawImage(videoEl, 0, 0, w, h);
    busy = true;
    canvasEl.toBlob(
      async (blob) => {
        try {
          if (!blob || !running) return;
          if (socket && socket.readyState === WebSocket.OPEN) {
            const header = new Uint8Array(4);
            new DataView(header.buffer).setUint32(0, seq >>> 0);
            seq += 1;
            socket.send(new Blob([header, blob]));
            sent += 1;
          } else if (transport === "snapshot") {
            seq += 1;
            if (await postUpload(node.id, [new File([blob], "frame.jpg", { type: "image/jpeg" })])) {
              sent += 1;
            }
          }
        } finally {
          busy = false;
        }
      },
      "image/jpeg",
      props.quality || 0.7,
    );
  }

  async function start() {
    message = "";
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      message = "The camera needs a secure page (https, or localhost).";
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: props.maxWidth || 640 } },
        audio: false,
      });
    } catch (e) {
      message =
        e && e.name === "NotAllowedError"
          ? "Camera permission was denied."
          : "No camera could be opened.";
      return;
    }
    running = true;
    sent = skipped = dropped = 0;
    videoEl.srcObject = stream;
    try {
      await videoEl.play();
    } catch (e) {
      /* a muted, inline video plays; a refusal only delays the preview */
    }
    const ws = liveConfig() ? await openLive() : null;
    if (!running) {
      if (ws) ws.close();
      return;
    }
    if (ws) {
      socket = ws;
      setTransport("live");
      schedule(1000 / (props.fps || 5));
    } else {
      useSnapshots(
        liveConfig() ? "Live connection unavailable, sending snapshots" : "Sending snapshots",
      );
    }
  }

  function stop() {
    running = false;
    clearInterval(timer);
    clearTimeout(retry);
    if (socket) {
      const ws = socket;
      socket = null;
      ws.close();
    }
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    if (videoEl) videoEl.srcObject = null;
    setTransport("off");
  }

  onDestroy(() => {
    running = false;
    clearInterval(timer);
    clearTimeout(retry);
    if (socket) socket.close();
    if (stream) stream.getTracks().forEach((t) => t.stop());
  });
</script>

<div class="camera">
  {#if props.label}<span class="camera-label">{props.label}</span>{/if}
  <video bind:this={videoEl} class="camera-preview" muted playsinline autoplay></video>
  <canvas bind:this={canvasEl} hidden></canvas>
  <div class="camera-bar">
    {#if running}
      <button type="button" class="camera-stop" onclick={stop}>Stop camera</button>
    {:else}
      <button type="button" class="camera-start" onclick={start}>Start camera</button>
    {/if}
    <span class="camera-status" data-transport={transport}>
      {#if running}{transport === "live" ? "Live" : "Snapshots"}: {sent} sent{#if skipped || dropped}, {skipped + dropped} dropped{/if}{/if}
    </span>
  </div>
  {#if message}<span class="camera-message">{message}</span>{/if}
</div>
