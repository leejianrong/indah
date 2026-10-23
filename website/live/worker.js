// The Pyodide worker (ADR-0041). Boot protocol:
//   page -> worker  {type:"boot", page, runtime}   start; everything below may arrive before "ready"
//                   {type:"boot", code, runtime}   the docs Playground: run this snippet instead of a page
//                   {type:"connect", sid}          the shell opened its stream
//                   {type:"event", body}           a UI event (the JSON body of POST api/event)
//   worker -> page  {type:"progress", text}  {type:"ready"}  {type:"frame", data}  {type:"error", message}
//                   {type:"running"}  the snippet is about to run (it may never return)
//                   {type:"beat"}     every second while the worker is free; a silent worker is stuck
// The message handler is installed synchronously, before any await, and anything that arrives
// before the runtime is ready is queued and replayed in order, so no message is lost.
const queue = [];
let bridge = null;
// A free worker answers its timer; one stuck in an endless loop cannot, which is how the page knows.
setInterval(() => postMessage({ type: "beat" }), 1000);

function handle(m) {
  if (m.type === "connect") bridge.connect(m.sid);
  else if (m.type === "event") bridge.event(m.body);
}

self.onmessage = (e) => {
  const m = e.data;
  if (m.type === "boot") boot(m);
  else if (bridge) {
    try {
      handle(m);
    } catch (err) {
      fail(err);
    }
  } else queue.push(m);
};

// The docs Playground shows the reader's own errors: a traceback that starts at their lines, not at
// the runner's, and flagged `user` so the page says "your code" rather than "could not start".
let playground = false;
const tidy = (text) => {
  const lines = String(text).split("\n");
  const at = lines.findIndex((l) => l.includes('File "<playground>"'));
  return at < 0 ? text : ["Traceback (most recent call last):", ...lines.slice(at)].join("\n");
};
const fail = (err) => {
  const text = String((err && err.message) || err);
  if (playground) postMessage({ type: "error", message: tidy(text), user: true });
  else postMessage({ type: "error", message: text });
};
const progress = (text) => postMessage({ type: "progress", text });

async function boot({ page, code, runtime }) {
  playground = typeof code === "string";
  try {
    const base = new URL(runtime.base, self.location.href).href;
    progress("Starting the Python runtime");
    const { loadPyodide } = await import(base + "pyodide.mjs");
    const py = await loadPyodide({ indexURL: base });
    progress("Loading packages");
    await py.loadPackage(runtime.packages);
    progress("Installing indah");
    py.globals.set("WHEEL_URL", new URL(runtime.wheel, self.location.href).href);
    await py.runPythonAsync("import micropip\nawait micropip.install(WHEEL_URL, deps=False)");
    if (!playground) {
      progress("Loading the page");
      const zip = await (await fetch(runtime.studio)).arrayBuffer();
      py.unpackArchive(zip, "zip");
    }
    py.FS.writeFile("bridge.py", await (await fetch(runtime.bridge)).text());
    const b = py.pyimport("bridge");
    const emit = (text) => postMessage({ type: "frame", data: text });
    if (playground) {
      progress("Running your code");
      postMessage({ type: "running" });
      const problem = b.init_code(code, emit);
      if (problem) return postMessage({ type: "error", message: problem, user: true });
    } else {
      b.init(page, emit);
    }
    bridge = b;
    postMessage({ type: "ready" });
    for (const m of queue.splice(0)) handle(m);
  } catch (err) {
    fail(err);
  }
}
