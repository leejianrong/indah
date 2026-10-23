"""A tiny static server for the Pyodide spike (no indah server involved).

/                 the built indah shell (src/indah/static/index.html) with shim.js injected
/pyodide/*        the pinned Pyodide runtime and packages (.cache/pyodide, see fetch_pyodide.py)
/wheels/*         the indah wheel (.cache/wheels)
/src/<path>       a whitelist of repo files the worker copies into the Pyodide file system
/shim.js, /worker.js, /bridge.py   the spike itself
"""

import http.server
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CACHE = HERE / ".cache"
# Python sources the worker may copy into Pyodide: the Studio and the example apps.
SRC_FILES = sorted(
    {str(p.relative_to(REPO)) for p in (REPO / "examples").glob("*.py")}
    | {str(p.relative_to(REPO)) for p in (REPO / "examples" / "studio").rglob("*.py")}
    | {str(p.relative_to(REPO)) for p in (REPO / "examples" / "studio" / "modules").glob("*.js")}
)
SRC_WHITELIST = set(SRC_FILES)
INJECT = '<script src="/shim.js"></script>'


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, status: int, body: bytes, ctype: str, cache: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/":
            html = (REPO / "src/indah/static/index.html").read_text()
            html = html.replace("<head>", "<head>" + INJECT, 1)
            return self._send(200, html.encode(), "text/html; charset=utf-8", cache=False)
        for prefix, root in (("/pyodide/", CACHE / "pyodide"), ("/wheels/", CACHE / "wheels")):
            if path.startswith(prefix):
                f = (root / path[len(prefix) :]).resolve()
                if root.resolve() in f.parents and f.is_file():
                    ctype = {
                        ".wasm": "application/wasm",
                        ".mjs": "text/javascript",
                        ".json": "application/json",
                        ".zip": "application/zip",
                    }.get(f.suffix, "application/octet-stream")
                    return self._send(200, f.read_bytes(), ctype)
                return self._send(404, b"", "text/plain")
        if path == "/src/manifest.json":
            import json

            return self._send(200, json.dumps(SRC_FILES).encode(), "application/json", cache=False)
        if path.startswith("/src/") and path[5:] in SRC_WHITELIST:
            return self._send(200, (REPO / path[5:]).read_bytes(), "text/plain", cache=False)
        if path in ("/shim.js", "/worker.js", "/bridge.py"):
            ctype = "text/javascript" if path.endswith(".js") else "text/plain"
            return self._send(200, (HERE / path[1:]).read_bytes(), ctype, cache=False)
        self._send(404, b"", "text/plain")


def serve(port: int = 0) -> tuple[http.server.ThreadingHTTPServer, str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


if __name__ == "__main__":
    _, url = serve(8765)
    print(url)
    threading.Event().wait()
