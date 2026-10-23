// Pyodide worker: boots the runtime, installs the indah wheel, runs bridge.py.
const params = new URLSearchParams(location.search);
const mode = params.get("mode") || "full";
const pageSpec = params.get("page") || "start/first-app";
const CDN = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
const root = mode.endsWith("-cdn") ? CDN : "/pyodide/";
const t0 = performance.now();
const mark = (name) => postMessage({ kind: "mark", name, t: performance.now() - t0 });
const fail = (err) => postMessage({ kind: "error", text: String((err && err.stack) || err) });

self.emit = (data) => postMessage({ kind: "frame", data });

let bridge;
let pyodide;
const ready = (async () => {
  try {
    // No top-level await: the message handler below must be installed before any message arrives.
    const { loadPyodide } = await import(root + "pyodide.mjs");
    const py = await loadPyodide({ indexURL: root });
    pyodide = py;
    mark("runtime");
    await py.loadPackage(["micropip", "pydantic", "starlette", "anyio", "h11", "click"]);
    mark("packages");
    const wheel = await (await fetch("/wheels/index.json")).json();
    // "pypi:X.Y.Z" installs the released wheel from PyPI instead of the local build.
    const spec = wheel.name.startsWith("pypi:")
      ? "indah==" + wheel.name.slice(5)
      : location.origin + "/wheels/" + wheel.name;
    py.globals.set("WHEEL_URL", spec);
    py.globals.set("MODE", mode);
    py.globals.set("PAGE_SPEC", pageSpec);
    await py.runPythonAsync(`
import micropip
if MODE == "full":
    await micropip.install(WHEEL_URL)
else:
    await micropip.install(WHEEL_URL, deps=False)
`);
    mark("install");
    // The Studio page source, copied into the Pyodide file system.
    for (const p of await (await fetch("/src/manifest.json")).json()) {
      const text = await (await fetch("/src/" + p)).text();
      const dir = p.split("/").slice(0, -1).join("/");
      py.FS.mkdirTree(dir);
      py.FS.writeFile(p, text);
    }
    for (const init of ["examples/__init__.py", "examples/studio/__init__.py", "examples/studio/chapters/__init__.py"]) {
      py.FS.writeFile(init, "");
    }
    py.FS.writeFile("bridge.py", await (await fetch("/bridge.py")).text());
    bridge = py.pyimport("bridge");
    mark("imported");
    postMessage({
      kind: "stats",
      stats: {
        wasmHeapBytes: py._module.HEAPU8.length,
        jsHeapBytes: (performance.memory || {}).usedJSHeapSize || null,
      },
    });
    return bridge;
  } catch (err) {
    fail(err);
    throw err;
  }
})();

onmessage = async (e) => {
  try {
    const b = await ready;
    if (e.data.kind === "connect") b.connect(e.data.sid);
    else if (e.data.kind === "event") b.event(e.data.body);
    else if (e.data.kind === "py") {
      // Spike-only: run a snippet in the worker and report what it printed or raised.
      let value;
      try {
        value = String(await pyodide.runPythonAsync(e.data.code));
      } catch (err) {
        value = "RAISED " + String(err.message).trim().split("\n").slice(-1)[0];
      }
      postMessage({ kind: "result", id: e.data.id, value });
    }
  } catch (err) {
    fail(err);
  }
};
