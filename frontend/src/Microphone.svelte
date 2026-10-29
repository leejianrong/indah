<script>
  // A live microphone input (ADR-0045). Tier 1: an AudioWorklet (served from the same origin as
  // /api/live-audio.js, so the strict CSP needs nothing new) downsamples to the requested rate and
  // sends 16-bit mono PCM in ~100 ms binary frames (4-byte big-endian seq + samples) over the live
  // socket. There is no live path without a socket, so the fallback records and, on Stop, uploads
  // one WAV take through the upload route.
  import { onDestroy } from "svelte";
  import { postEvent, postUpload, sessionId, liveConfig, liveUrl, apiUrl } from "./api.js";

  let { node, props } = $props();

  const READY_TIMEOUT_MS = 3000;
  const MAX_BUFFERED = 1024 * 1024;
  const MAX_TAKE_SECONDS = 60;

  let running = $state(false);
  let transport = $state("off");
  let message = $state("");
  let sent = $state(0);
  let skipped = $state(0);
  let dropped = $state(0);
  let level = $state(0);

  let stream = null;
  let socket = null;
  let context = null;
  let source = null;
  let processor = null;
  let seq = 0;
  let take = []; // Float32 blocks while recording (fallback)
  let takeRate = 0;
  let takeSamples = 0;

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
            kind: "audio",
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
          if (running) {
            message = "Live connection closed";
            stop();
          }
        }
      };
    });
  }

  function peak(samples) {
    let m = 0;
    for (let i = 0; i < samples.length; i++) m = Math.max(m, Math.abs(samples[i]));
    return m;
  }

  function sendPcm(buffer) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const view = new Int16Array(buffer);
    level = Math.min(1, peak(view) / 0x7fff);
    if (socket.bufferedAmount > MAX_BUFFERED) {
      skipped += 1; // the uplink is far behind: shed this chunk, the server reports the gap
      return;
    }
    const header = new Uint8Array(4);
    new DataView(header.buffer).setUint32(0, seq >>> 0);
    seq += 1;
    socket.send(new Blob([header, buffer]));
    sent += 1;
  }

  async function startLive(ws) {
    context = new AudioContext();
    await context.audioWorklet.addModule(apiUrl(liveConfig().path + "-audio.js"));
    source = context.createMediaStreamSource(stream);
    processor = new AudioWorkletNode(context, "indah-pcm", {
      processorOptions: { sampleRate: props.sampleRate || 16000 },
      numberOfOutputs: 0,
    });
    processor.port.onmessage = (event) => sendPcm(event.data);
    source.connect(processor);
    socket = ws;
    setTransport("live");
  }

  function startRecording() {
    context = new AudioContext();
    takeRate = context.sampleRate;
    take = [];
    takeSamples = 0;
    source = context.createMediaStreamSource(stream);
    // ScriptProcessor is deprecated but needs no extra script route, which is the point of the
    // fallback: it must work where the live route (and so the worklet file) is not served.
    processor = context.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = (event) => {
      const block = new Float32Array(event.inputBuffer.getChannelData(0));
      take.push(block);
      takeSamples += block.length;
      level = Math.min(1, peak(block));
      if (takeSamples / takeRate >= MAX_TAKE_SECONDS) stop();
    };
    source.connect(processor);
    processor.connect(context.destination); // silent: the output buffer is left zeroed
    setTransport("recording");
  }

  function wav(blocks, fromRate, toRate) {
    const total = blocks.reduce((n, b) => n + b.length, 0);
    const flat = new Float32Array(total);
    let at = 0;
    for (const b of blocks) {
      flat.set(b, at);
      at += b.length;
    }
    const step = fromRate / toRate;
    const count = Math.floor(total / step);
    const pcm = new Int16Array(count);
    for (let k = 0; k < count; k++) {
      const p = k * step;
      const i = Math.floor(p);
      const a = flat[i];
      const v = a + ((i + 1 < total ? flat[i + 1] : a) - a) * (p - i);
      const c = Math.max(-1, Math.min(1, v));
      pcm[k] = c < 0 ? c * 0x8000 : c * 0x7fff;
    }
    const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
    const text = (o, s) => [...s].forEach((ch, j) => out.setUint8(o + j, ch.charCodeAt(0)));
    text(0, "RIFF");
    out.setUint32(4, 36 + pcm.length * 2, true);
    text(8, "WAVEfmt ");
    out.setUint32(16, 16, true);
    out.setUint16(20, 1, true);
    out.setUint16(22, 1, true);
    out.setUint32(24, toRate, true);
    out.setUint32(28, toRate * 2, true);
    out.setUint16(32, 2, true);
    out.setUint16(34, 16, true);
    text(36, "data");
    out.setUint32(40, pcm.length * 2, true);
    new Int16Array(out.buffer, 44).set(pcm);
    return new Blob([out], { type: "audio/wav" });
  }

  async function start() {
    message = "";
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      message = "The microphone needs a secure page (https, or localhost).";
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (e) {
      message =
        e && e.name === "NotAllowedError"
          ? "Microphone permission was denied."
          : "No microphone could be opened.";
      return;
    }
    running = true;
    sent = skipped = dropped = 0;
    seq = 0;
    const ws = liveConfig() ? await openLive() : null;
    if (!running) {
      if (ws) ws.close();
      return;
    }
    try {
      if (ws) await startLive(ws);
      else {
        message = liveConfig()
          ? "Live connection unavailable, recording a take"
          : "Recording a take, sent when you press Stop";
        startRecording();
      }
    } catch (e) {
      message = "Audio capture is not available in this browser.";
      stop();
    }
  }

  function teardown() {
    if (processor) {
      processor.disconnect();
      processor.onaudioprocess = null;
      if (processor.port) processor.port.onmessage = null;
    }
    if (source) source.disconnect();
    if (context) context.close().catch(() => {});
    processor = source = context = null;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  function stop() {
    const wasRecording = transport === "recording";
    running = false;
    level = 0;
    if (socket) {
      const ws = socket;
      socket = null;
      ws.close();
    }
    const blocks = take;
    const rate = takeRate;
    take = [];
    teardown();
    if (wasRecording && blocks.length) {
      const blob = wav(blocks, rate, props.sampleRate || 16000);
      postUpload(node.id, [new File([blob], "take.wav", { type: "audio/wav" })]).then((ok) => {
        if (ok) sent += 1;
        else message = "The take could not be sent.";
      });
    }
    setTransport("off");
  }

  onDestroy(() => {
    running = false;
    if (socket) socket.close();
    teardown();
  });
</script>

<div class="mic">
  {#if props.label}<span class="mic-label">{props.label}</span>{/if}
  <div class="mic-bar">
    {#if running}
      <button type="button" class="mic-stop" onclick={stop}>Stop microphone</button>
    {:else}
      <button type="button" class="mic-start" onclick={start}>Start microphone</button>
    {/if}
    <span class="mic-meter" aria-hidden="true"><span style="width: {Math.round(level * 100)}%"></span></span>
    <span class="mic-status" data-transport={transport}>
      {#if running}{transport === "live" ? "Live" : "Recording"}: {sent} sent{#if skipped || dropped}, {skipped + dropped} dropped{/if}{:else if sent && transport === "off"}{sent} sent{/if}
    </span>
  </div>
  {#if message}<span class="mic-message">{message}</span>{/if}
</div>
