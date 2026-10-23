// Page side of the spike: replaces EventSource and fetch("api/event") of the unmodified shell
// with a postMessage channel to a Pyodide web worker running the Python Session.
(() => {
  const mode = new URLSearchParams(location.search).get("mode") || "full";
  const t0 = performance.now();
  const spike = (window.__spike = { mode, marks: {}, frames: 0, stats: {}, errors: [] });
  const pageSpec = new URLSearchParams(location.search).get("page") || "start/first-app";
  const worker = new Worker(
    "/worker.js?mode=" + mode + "&page=" + encodeURIComponent(pageSpec),
    { type: "module" },
  );
  const sources = new Set();
  const pending = new Map();
  let nextId = 1;
  spike.py = (code) =>
    new Promise((resolve) => {
      const id = nextId++;
      pending.set(id, resolve);
      worker.postMessage({ kind: "py", id, code });
    });

  worker.onmessage = (e) => {
    const m = e.data;
    if (m.kind === "frame") {
      spike.frames++;
      if (!("firstFrame" in spike.marks)) spike.marks.firstFrame = performance.now() - t0;
      for (const s of sources) s._deliver(m.data);
    } else if (m.kind === "mark") spike.marks[m.name] = m.t;
    else if (m.kind === "stats") Object.assign(spike.stats, m.stats);
    else if (m.kind === "error") spike.errors.push(m.text);
    else if (m.kind === "result") pending.get(m.id)(m.value);
  };
  worker.onerror = (e) => spike.errors.push("worker: " + (e.message || e));

  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.onopen = this.onmessage = this.onerror = null;
      sources.add(this);
      worker.postMessage({ kind: "connect", sid: new URL(url).searchParams.get("sid") });
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
      worker.postMessage({ kind: "event", body: init && init.body });
      return Promise.resolve(
        new Response('{"ok":true}', { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    }
    if (/api\/(upload|session)(\?|$)/.test(url)) {
      return Promise.resolve(new Response('{"ok":false}', { status: 501 }));
    }
    return realFetch(input, init);
  };
})();
