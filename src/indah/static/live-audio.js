// The Microphone AudioWorklet (ADR-0045). It runs on the audio thread, downsamples whatever the
// browser captures at (usually 44.1 or 48 kHz) to the rate the page asked for, and posts 16-bit
// little-endian mono PCM in about 100 ms pieces to the shell, which sends them over the live socket.
class IndahPcm extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const rate = (options.processorOptions && options.processorOptions.sampleRate) || 16000;
    this.step = sampleRate / rate; // input samples per output sample
    this.size = Math.max(160, Math.round(rate / 10));
    this.out = new Int16Array(this.size);
    this.filled = 0;
    this.pos = 0; // fractional read position into the current block
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    const n = channel.length;
    while (this.pos < n) {
      const i = Math.floor(this.pos);
      const frac = this.pos - i;
      const a = channel[i];
      const v = a + ((i + 1 < n ? channel[i + 1] : a) - a) * frac;
      const clamped = Math.max(-1, Math.min(1, v));
      this.out[this.filled++] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
      if (this.filled === this.size) {
        this.port.postMessage(this.out.buffer, [this.out.buffer]);
        this.out = new Int16Array(this.size);
        this.filled = 0;
      }
      this.pos += this.step;
    }
    this.pos -= n;
    return true;
  }
}
registerProcessor("indah-pcm", IndahPcm);
