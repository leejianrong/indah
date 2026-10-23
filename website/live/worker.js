// The Pyodide worker (ADR-0041). Boot protocol:
//   page -> worker  {type:"boot", page, runtime}   start; everything below may arrive before "ready"
//                   {type:"connect", sid}          the shell opened its stream
//                   {type:"event", body}           a UI event (the JSON body of POST api/event)
//   worker -> page  {type:"progress", text}  {type:"ready"}  {type:"frame", data}  {type:"error", message}
// The message handler is installed synchronously, before any await, and anything that arrives
// before the runtime is ready is queued and replayed in order, so no message is lost.
const queue = [];
let bridge = null;

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

const fail = (err) => postMessage({ type: "error", message: String((err && err.message) || err) });
const progress = (text) => postMessage({ type: "progress", text });

async function boot({ page, runtime }) {
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
    progress("Loading the page");
    const zip = await (await fetch(runtime.studio)).arrayBuffer();
    py.unpackArchive(zip, "zip");
    py.FS.writeFile("bridge.py", await (await fetch(runtime.bridge)).text());
    const b = py.pyimport("bridge");
    b.init(page, (text) => postMessage({ type: "frame", data: text }));
    bridge = b;
    postMessage({ type: "ready" });
    for (const m of queue.splice(0)) handle(m);
  } catch (err) {
    fail(err);
  }
}
