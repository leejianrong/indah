"""Build the docs' live-example bundle: Studio pages that run in the reader's browser (ADR-0041).

    uv run python scripts/build_docs_live.py bundle [--self-host] [--wheel WHEEL] [--out DIR]
    uv run python scripts/build_docs_live.py finalize [--site DIR]

``bundle`` writes ``website/docs/assets/live/`` (generated, git-ignored): the indah wheel built from
this commit, ``studio.zip`` (the Studio's source), ``frame.html`` (the shell with the postMessage
shim injected), the worker, the bridge, ``pages.json`` (the Studio's page registry), a few static
files for the shell's ``api/*`` GET routes, and ``runtime.json`` (the pinned Pyodide version, where
it is loaded from, and the size budgets). It downloads nothing unless ``--self-host`` is given.

``finalize`` runs after ``zensical build``: it fills each ``<indah-live page="...">`` in the built
HTML with its title, summary and source, so the example reads without JavaScript, and each
``<indah-playground>`` with its editor and starting points (IND-83).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LIVE_SRC = ROOT / "website" / "live"
ELEMENT_JS = ROOT / "website" / "docs" / "javascripts" / "indah-live.js"
PLAYGROUND_JS = ROOT / "website" / "docs" / "javascripts" / "indah-playground.js"
DEFAULT_OUT = ROOT / "website" / "docs" / "assets" / "live"
PYODIDE_CACHE = ROOT / ".cache" / "live-pyodide"

PYODIDE_VERSION = "314.0.7"  # CPython 3.14.2; change only by a reviewed commit (ADR-0041 section 6)
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
# Pyodide packages the indah core needs; uvicorn and python-multipart are not (deps=False).
PACKAGES = ["micropip", "pydantic", "starlette", "anyio", "h11", "click"]
CORE_FILES = [
    "pyodide.mjs",
    "pyodide.asm.mjs",
    "pyodide.asm.wasm",
    "python_stdlib.zip",
    "pyodide-lock.json",
]
BUDGETS = {
    "wheelBytes": 1_000_000,  # the indah wheel in the bundle (ADR-0041, ADR-0042)
    "elementScriptBytes": 10_000,  # the <indah-live> element script
    "playgroundScriptBytes": 12_000,  # the <indah-playground> element script (IND-83)
    "firstFrameWarmSeconds": 8,  # Run it to the first frame, warm cache (checked by the CI job)
}
STUDIO_URL = "https://github.com/leejianrong/indah/blob/main/docs/STUDIO.md"
RUN_NOTE = "Loads about 9 MB, then runs in your browser."


# -- the bundle ---------------------------------------------------------------------------------


def build_wheel(dest: Path) -> Path:
    """``uv build --wheel`` of this checkout, so the docs run the code beside them."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["uv", "build", "--wheel", "-o", tmp, str(ROOT)], check=True)
        built = sorted(Path(tmp).glob("indah-*.whl"))[-1]
        shutil.copy(built, dest / built.name)
    return dest / built.name


def studio_zip(dest: Path) -> int:
    """The Studio's source, for the worker's file system. The whole example apps (the gallery's
    demos and the dashboards) are not in it: they are ``local_only``, and the chapters do not
    import them."""
    files: dict[str, bytes] = {}
    for path in sorted((ROOT / "examples" / "studio").rglob("*")):
        rel = path.relative_to(ROOT)
        if "__pycache__" in rel.parts or not path.is_file():
            continue
        if path.suffix == ".py" or rel.parts[:3] == ("examples", "studio", "modules"):
            files[rel.as_posix()] = path.read_bytes()
    # a package needs an __init__ in the worker even where the checkout has none
    for name in list(files):
        parent = Path(name).parent
        while parent.as_posix() not in (".", ""):
            files.setdefault((parent / "__init__.py").as_posix(), b"")
            parent = parent.parent
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            z.writestr(name, data)
    return dest.stat().st_size


def frame_html(shell: str) -> str:
    """The shell with the shim loaded first (one change: a script tag after ``<head>``)."""
    match = re.search(r"<head[^>]*>", shell)
    if match is None:
        raise SystemExit("the shell has no <head> to inject the shim after")
    return shell[: match.end()] + '<script src="shim.js"></script>' + shell[match.end() :]


def static_api_files(out: Path) -> list[str]:
    """Real files where the shell fetches ``api/*`` GET routes, so those pages run (a static host
    has no routes): the editor module and each registered module component."""
    import importlib

    custom = importlib.import_module("indah.custom")  # not `indah.custom`, the function
    written = []
    editor = ROOT / "src" / "indah" / "static" / "editor.js"
    if editor.is_file():
        (out / "api").mkdir(exist_ok=True)
        shutil.copy(editor, out / "api" / "editor.js")
        written.append("api/editor.js")
    for reg in custom._REGISTRY.values():
        if reg.module:
            target = out / "api" / "components" / f"{reg.type}.js"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(reg.module)
            written.append(f"api/components/{reg.type}.js")
    return written


def fetch_pyodide(dest: Path) -> int:
    """Self-host the pinned runtime and packages (tests, offline copies; never a plain build)."""
    PYODIDE_CACHE.mkdir(parents=True, exist_ok=True)

    def get(name: str) -> Path:
        f = PYODIDE_CACHE / name
        if not f.exists():
            with urllib.request.urlopen(PYODIDE_CDN + name, timeout=120) as resp:  # noqa: S310
                data = resp.read()
            # Atomic: another process (a parallel test worker) must never see half a file.
            part = f.with_name(f"{f.name}.{os.getpid()}.part")
            part.write_bytes(data)
            part.replace(f)
        return f

    dest.mkdir(parents=True, exist_ok=True)
    names = list(CORE_FILES)
    lock = json.loads(get("pyodide-lock.json").read_text())["packages"]
    todo, seen = list(PACKAGES), set()
    while todo:
        key = todo.pop().lower().replace("_", "-")
        if key in seen or key not in lock:
            continue
        seen.add(key)
        todo.extend(lock[key].get("depends", []))
        names.append(lock[key]["file_name"])
    total = 0
    for name in dict.fromkeys(names):
        shutil.copy(get(name), dest / name)
        total += (dest / name).stat().st_size
    return total


def budget_problems(sizes: dict[str, int]) -> list[str]:
    out = []
    if sizes["wheelBytes"] > BUDGETS["wheelBytes"]:
        out.append(
            f"the wheel is {sizes['wheelBytes']:,} bytes; the budget is {BUDGETS['wheelBytes']:,}"
        )
    if sizes["elementScriptBytes"] > BUDGETS["elementScriptBytes"]:
        out.append(
            f"indah-live.js is {sizes['elementScriptBytes']:,} bytes; "
            f"the budget is {BUDGETS['elementScriptBytes']:,}"
        )
    if sizes.get("playgroundScriptBytes", 0) > BUDGETS["playgroundScriptBytes"]:
        out.append(
            f"indah-playground.js is {sizes['playgroundScriptBytes']:,} bytes; "
            f"the budget is {BUDGETS['playgroundScriptBytes']:,}"
        )
    return out


def build_bundle(out: Path, wheel: Path | None = None, self_host: bool = False) -> dict:
    """Write the whole bundle into ``out`` and return ``runtime.json``'s content."""
    from examples.studio import registry

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name in ("shim.js", "worker.js", "bridge.py"):
        shutil.copy(LIVE_SRC / name, out / name)
    if wheel is None:
        wheel_path = build_wheel(out)
    else:
        wheel_path = out / wheel.name
        shutil.copy(wheel, wheel_path)
    zip_bytes = studio_zip(out / "studio.zip")
    shell = (ROOT / "src" / "indah" / "static" / "index.html").read_text(encoding="utf-8")
    (out / "frame.html").write_text(frame_html(shell), encoding="utf-8")
    pages = registry.export_pages()  # imports every chapter, which registers the module components
    (out / "pages.json").write_text(registry.dumps(pages), encoding="utf-8")
    statics = static_api_files(out)
    pyodide_bytes = fetch_pyodide(out / "pyodide") if self_host else 0
    sizes = {
        "wheelBytes": wheel_path.stat().st_size,
        "studioZipBytes": zip_bytes,
        "frameHtmlBytes": (out / "frame.html").stat().st_size,
        "pagesJsonBytes": (out / "pages.json").stat().st_size,
        "elementScriptBytes": ELEMENT_JS.stat().st_size if ELEMENT_JS.is_file() else 0,
        "playgroundScriptBytes": PLAYGROUND_JS.stat().st_size if PLAYGROUND_JS.is_file() else 0,
        "pyodideSelfHostedBytes": pyodide_bytes,
    }
    runtime = {
        "pyodide": PYODIDE_VERSION,
        "base": "pyodide/" if self_host else PYODIDE_CDN,
        "selfHost": self_host,
        "packages": PACKAGES,
        "wheel": wheel_path.name,
        "studio": "studio.zip",
        "bridge": "bridge.py",
        "staticApi": statics,
        "pages": sum(1 for p in pages if p["runnable"]),
        "budgets": BUDGETS,
        "sizes": sizes,
    }
    (out / "runtime.json").write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    return runtime


# -- finalize: static content for the no-JavaScript reader --------------------------------------

_EMBED = re.compile(
    r"(?:<p>\s*)?<indah-live\b(?P<attrs>[^>]*)>\s*</indah-live>(?:\s*</p>)?", re.IGNORECASE
)
_PAGE = re.compile(r"""\bpage\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def render_embed(page: dict) -> str:
    """One embed's static markup. The element script adds the Run it behaviour on top."""
    e = html.escape
    pid = e(page["id"], quote=True)
    if page["runnable"]:
        action = (
            f'<button type="button" class="indah-live-run" hidden>Run it</button> '
            f'<span class="indah-live-note">{RUN_NOTE}</span>'
        )
    else:
        reason = e(page["local_only"] or "")
        action = (
            f'<span class="indah-live-note">This example needs a server: {reason}. '
            f"Run <code>make demo</code> to try it.</span>"
        )
    return (
        f'<indah-live page="{pid}" data-prerendered>'
        f'<figure class="indah-live-card">'
        f"<figcaption><strong>{e(page['title'])}</strong> - {e(page['summary'])}</figcaption>"
        f'<pre class="indah-live-source"><code class="language-python">'
        f"{e(page['source'] or '')}</code></pre>"
        f'<p class="indah-live-actions">{action} '
        f'<a href="{STUDIO_URL}">Open in the Studio</a> '
        f'<span class="indah-live-id">(<code>make demo</code>, then <code>c/{pid}</code>)'
        f"</span></p>"
        f'<div class="indah-live-status" role="status" aria-live="polite"></div>'
        f'<div class="indah-live-stage"></div>'
        f"</figure></indah-live>"
    )


def finalize_html(text: str, pages: dict[str, dict]) -> tuple[str, int]:
    """Fill every ``<indah-live>`` in one built page. Returns (new text, how many filled)."""
    count = 0

    def fill(m: re.Match) -> str:
        nonlocal count
        match = _PAGE.search(m.group("attrs"))
        pid = (
            match.group(1) if match and match.group(1) is not None else match and match.group(2)
        ) or ""
        page = pages.get(pid.strip())
        if page is None:
            raise SystemExit(f'<indah-live page="{pid}"> names no Studio page')
        count += 1
        return render_embed(page)

    return _EMBED.sub(fill, text), count


def finalize(site: Path, bundle: Path) -> int:
    page_list = json.loads((bundle / "pages.json").read_text(encoding="utf-8"))
    pages = {p["id"]: p for p in page_list}
    playground = None
    total = 0
    for path in sorted(site.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        if "<indah-live" not in text and "<indah-playground" not in text:
            continue
        new, n = finalize_html(text, pages)
        if "<indah-playground" in new:
            playground = playground or render_playground(playground_starters(page_list))
            new, k = _PLAYGROUND.subn(lambda _m, html_=playground: html_, new)
            n += k
        if n:
            path.write_text(new, encoding="utf-8")
            total += n
    return total


# -- the docs Playground (IND-83) ---------------------------------------------------------------

# Studio pages whose source also works as a snippet: self-contained (only ``indah``), and the
# build function takes a ``ctx`` it never reads. The Studio playground's starters are used as is.
PLAYGROUND_PAGES = ("start/quickstart", "layout/containers")
_DEF = re.compile(r"^def \w+\(ctx[^)]*\)\s*(?:->[^:]+)?:", re.MULTILINE)


def playground_starters(pages: list[dict]) -> list[dict]:
    """``[{id, title, code}]``: the snippets the Playground offers, all as ``def build()``."""
    from examples.studio.chapters.playground import STARTERS

    out = []
    by_id = {p["id"]: p for p in pages}
    for pid in PLAYGROUND_PAGES:
        page = by_id[pid]
        code, n = _DEF.subn("def build():", page["source"] or "", count=1)
        if not n or "ctx" in code:
            raise SystemExit(f"{pid} cannot be a Playground starter: its build function uses ctx")
        out.append({"id": pid.replace("/", "-"), "title": page["title"], "code": code})
    for title, code in STARTERS.items():
        out.append(
            {
                "id": re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
                "title": title,
                "code": code,
            }
        )
    for starter in out:
        if "import indah" not in starter["code"]:
            starter["code"] = "import indah\n\n\n" + starter["code"]
    return out


def render_playground(starters: list[dict]) -> str:
    """The Playground's static markup: readable and copyable with no JavaScript. The element script
    adds the buttons (the ``indah-play-js`` ones are hidden until then)."""
    e = html.escape
    options = "".join(
        f'<option value="{e(s["id"], quote=True)}">{e(s["title"])}</option>' for s in starters
    )
    listing = "".join(
        f"<details><summary>{e(s['title'])}</summary>"
        f'<pre><code class="language-python" data-starter="{e(s["id"], quote=True)}">'
        f"{e(s['code'])}</code></pre>"
        f"</details>"
        for s in starters
    )
    return (
        "<indah-playground data-prerendered>"
        '<div class="indah-play">'
        '<label for="indah-play-code"><strong>Your code</strong> '
        "(<code>def build()</code> returns an indah component)</label>"
        '<textarea id="indah-play-code" class="indah-play-code" rows="16" spellcheck="false" '
        'autocomplete="off" autocapitalize="off" aria-describedby="indah-play-help">'
        f"{e(starters[0]['code'])}</textarea>"
        '<p id="indah-play-help" class="indah-play-note">'
        "Tab indents; press Escape, then Tab, to leave the editor. "
        "Ctrl+Enter (or Cmd+Enter) runs.</p>"
        '<p class="indah-live-actions">'
        '<button type="button" class="indah-live-run indah-play-run indah-play-js" '
        "hidden>Run</button> "
        '<button type="button" class="indah-play-stop indah-play-js" hidden disabled>Stop</button> '
        '<button type="button" class="indah-play-reset indah-play-js" hidden>Reset</button> '
        '<label class="indah-play-js" hidden>Start from '
        f'<select class="indah-play-pick">{options}</select></label> '
        f'<span class="indah-live-note">{RUN_NOTE} Nothing is sent anywhere.</span></p>'
        '<div class="indah-play-status indah-live-status" role="status" aria-live="polite"></div>'
        '<pre class="indah-play-error" role="alert" hidden></pre>'
        '<div class="indah-play-stage"></div></div>'
        '<section class="indah-play-starters"><h3>Starting points</h3>'
        f"{listing}</section></indah-playground>"
    )


_PLAYGROUND = re.compile(
    r"(?:<p>\s*)?<indah-playground\b[^>]*>\s*</indah-playground>(?:\s*</p>)?", re.IGNORECASE
)


# -- command line -------------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bundle", help="build website/docs/assets/live/")
    b.add_argument("--out", type=Path, default=DEFAULT_OUT)
    b.add_argument("--wheel", type=Path, help="use this wheel instead of building one")
    b.add_argument("--self-host", action="store_true", help="also copy the pinned Pyodide runtime")
    f = sub.add_parser("finalize", help="fill <indah-live> in the built site")
    f.add_argument("--site", type=Path, default=ROOT / "website" / "site")
    f.add_argument("--bundle", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if args.cmd == "bundle":
        runtime = build_bundle(args.out, args.wheel, args.self_host)
        for line in budget_problems(runtime["sizes"]):
            print(f"over budget: {line}", file=sys.stderr)
        print(json.dumps(runtime["sizes"], indent=2), file=sys.stderr)
        return 1 if budget_problems(runtime["sizes"]) else 0
    n = finalize(args.site, args.bundle)
    print(f"filled {n} <indah-live> / <indah-playground> embed(s) in {args.site}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
