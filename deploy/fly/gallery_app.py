"""One ASGI app that hosts every indah demo behind sub-paths (ADR-0023, Fly.io).

A single Starlette app mounts each demo's indah app under `/<slug>` and serves a
gallery index at `/`. This works because the indah shell uses document-relative URLs
(`api/stream`, `api/event`, ...) so it survives a base path - the same property that
makes it run behind Colab's and Runpod's proxies (ADR-0001). One machine, one domain
(`.../poster`, `.../chatbot`, ...), and it dogfoods indah's single-port/base-path
design.

Run in the deploy image with uvicorn's factory mode:
    uvicorn gallery_app:create_gallery --factory --host 0.0.0.0 --port 7860

`build_gallery` is pure (imports only Starlette) so it is unit-testable without the
examples; `create_gallery` imports the example modules (present in the deploy image).
"""

from __future__ import annotations

import html
import importlib
from typing import Any

from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route

# slug (URL + Fly), title, emoji, example module name (copied flat into the image).
MANIFEST: list[tuple[str, str, str, str]] = [
    ("chatbot", "Streaming chatbot", "💬", "chatbot"),
    ("training-dashboard", "Live training dashboard", "📈", "training_dashboard"),
    ("diffusion", "Image generation", "🎨", "diffusion"),
    ("poster", "Poster generator", "🖼️", "poster"),
    ("image-classify", "Image classifier", "🔍", "upload_classify"),
    ("charts", "Hybrid charting", "📊", "charts"),
]


def _index_html(demos: list[dict[str, Any]]) -> str:
    cards = "".join(
        # Relative links (trailing slash) so they resolve under any base path.
        f'<a class="card" href="{html.escape(d["slug"])}/">'
        f'<span class="emoji">{d["emoji"]}</span>'
        f'<span class="title">{html.escape(d["title"])}</span></a>'
        for d in demos
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>indah demos</title><style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; font-family: system-ui, sans-serif; background:#faf6f0; color:#241c22; }}
  @media (prefers-color-scheme: dark) {{ body {{ background:#191319; color:#f3e6de; }} }}
  header {{ padding: 2.5rem 1.5rem 1rem; }}
  h1 {{ margin:0; font-size:1.8rem; }} p {{ color:#6e6169; max-width:44rem; }}
  .grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(220px,1fr));
    gap:1rem; padding:1rem 1.5rem 3rem; }}
  .card {{ display:flex; flex-direction:column; gap:.5rem; padding:1.3rem;
    border-radius:14px; background:#fffdf9; border:1px solid #e0d4c6;
    text-decoration:none; color:inherit; box-shadow:0 2px 5px -2px rgba(90,20,55,.16); }}
  @media (prefers-color-scheme: dark) {{ .card {{ background:#221b22; border-color:#3a2f3a; }} }}
  .card:hover {{ border-color:#b5296b; }}
  .emoji {{ font-size:2rem; }} .title {{ font-weight:600; }}
</style></head><body>
<header><h1>indah demos</h1>
<p>Live demos built with <a href="https://github.com/leejianrong/indah">indah</a> -
a reactive Python UI framework for cloud notebooks (no Node, single port, streaming
over SSE). Pick one:</p></header>
<div class="grid">{cards}</div>
</body></html>"""


def build_gallery(demos: list[dict[str, Any]]) -> Starlette:
    """Mount each demo app under `/<slug>` and serve a gallery index at `/`.

    ``demos`` is a list of ``{"slug","title","emoji","app"}`` (``app`` is an ASGI app).
    """

    async def index(_request):
        return HTMLResponse(_index_html(demos))

    routes: list[Any] = [Mount(f"/{d['slug']}", app=d["app"]) for d in demos]
    routes.append(Route("/", index))
    return Starlette(routes=routes)


def create_gallery() -> Starlette:
    """Import the example modules and build the gallery (used in the deploy image)."""
    demos = []
    for slug, title, emoji, module in MANIFEST:
        mod = importlib.import_module(module)
        demos.append({"slug": slug, "title": title, "emoji": emoji, "app": mod.app})
    return build_gallery(demos)
