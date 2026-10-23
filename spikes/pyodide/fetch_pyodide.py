"""Download a pinned Pyodide runtime and the few packages indah needs into ./.cache/pyodide.

Nothing here is committed or shipped: the cache is git-ignored. Usage: python fetch_pyodide.py
"""

import json
import sys
import urllib.request
from pathlib import Path

VERSION = "314.0.7"  # Pyodide release (CPython 3.14.2, emscripten 5.0.3)
BASE = f"https://cdn.jsdelivr.net/pyodide/v{VERSION}/full/"
OUT = Path(__file__).parent / ".cache" / "pyodide"
CORE = [
    "pyodide.mjs",
    "pyodide.asm.mjs",
    "pyodide.asm.wasm",
    "python_stdlib.zip",
    "pyodide-lock.json",
]
# Pyodide packages the indah core and its ASGI layer need (names as in the lock file).
WANT = ["micropip", "pydantic", "starlette", "anyio", "h11", "click"]


def get(name: str) -> bytes:
    with urllib.request.urlopen(BASE + name, timeout=120) as resp:  # noqa: S310
        return resp.read()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in CORE:
        if not (OUT / name).exists():
            (OUT / name).write_bytes(get(name))
        total += (OUT / name).stat().st_size
    lock = json.loads((OUT / "pyodide-lock.json").read_text())["packages"]
    todo, seen = list(WANT), set()
    while todo:
        key = todo.pop().lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        pkg = lock.get(key) or lock.get(key.replace("-", "_"))
        if pkg is None:
            print(f"not a Pyodide package: {key}", file=sys.stderr)
            continue
        todo.extend(pkg.get("depends", []))
        f = pkg["file_name"]
        if not (OUT / f).exists():
            (OUT / f).write_bytes(get(f))
        print(f"{key:20} {pkg['version']:10} {(OUT / f).stat().st_size:>10,} bytes")
        total += (OUT / f).stat().st_size
    print(f"total cached: {total:,} bytes in {OUT}")
    for name in CORE:
        print(f"  {name:22} {(OUT / name).stat().st_size:>12,}")


if __name__ == "__main__":
    main()
