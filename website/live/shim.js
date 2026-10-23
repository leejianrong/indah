// Page side (ADR-0041): replaces EventSource and fetch("api/event") of the unmodified shell with a
// postMessage channel to the Pyodide worker. Injected into frame.html before the shell runs.
(() => {
  const page = new URLSearchParams(location.search).get("page");
  const tell = (m) => parent !== window && parent.postMessage({ source: "indah-live", ...m }, "*");
  const sources = new Set();
  const worker = new Worker("worker.js", { type: "module" });
  worker.onmessage = (e) => {
    const m = e.data;
    if (m.type === "frame") for (const s of sources) s._deliver(m.data);
    else tell(m);
  };
  worker.onerror = (e) => tell({ type: "error", message: e.message || "the worker failed to start" });
  addEventListener("pagehide", () => worker.terminate());

  fetch("runtime.json")
    .then((r) => r.json())
    .then((runtime) => worker.postMessage({ type: "boot", page, runtime }))
    .catch((err) => tell({ type: "error", message: "runtime.json: " + err }));

  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.onopen = this.onmessage = this.onerror = null;
      sources.add(this);
      worker.postMessage({ type: "connect", sid: new URL(url, location.href).searchParams.get("sid") });
    }
    close() {
      this.readyState = 2;
      sources.delete(this);
    }
    _deliver(data) {
      if (this.readyState === 0) {
        this.readyState = 1;
        if (this.onopen) this.onopen({});
      }
      if (this.onmessage) this.onmessage({ data });
    }
  }
  FakeEventSource.CONNECTING = 0;
  FakeEventSource.OPEN = 1;
  FakeEventSource.CLOSED = 2;
  window.EventSource = FakeEventSource;

  const realFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    if (/api\/event(\?|$)/.test(url)) {
      worker.postMessage({ type: "event", body: init && init.body });
      return Promise.resolve(
        new Response('{"ok":true}', { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    }
    if (/api\/(upload|session)(\?|$)/.test(url)) {
      return Promise.resolve(new Response('{"ok":false}', { status: 501 }));
    }
    return realFetch(input, init);
  };

  // Let the docs page size the iframe to the content.
  addEventListener("DOMContentLoaded", () => {
    // The shell's body is min-height: 100vh, which in an iframe is the iframe's own height: measuring
    // it would keep growing the frame to its cap. Measure the content instead.
    document.body.style.minHeight = "0";
    const send = () => tell({ type: "height", height: document.documentElement.scrollHeight });
    new ResizeObserver(send).observe(document.body);
    send();
  });
})();
