"""Content-Security-Policy for the shell (ADR-0038).

``create_app(csp="strict")`` serves the shell with a per-response nonce on its inline
``<script>`` and ``<style>`` tags and a policy that allows nothing else to run::

    default-src 'none'; script-src 'nonce-N' 'self'; style-src 'nonce-N';
    style-src-attr 'unsafe-inline'; img-src 'self' data: blob: <tile hosts>; ...

``style-src-attr 'unsafe-inline'`` is the one concession: Svelte writes ``style="..."``
attributes, and an inline *attribute* cannot run script. Everything that can run code is
nonce-or-same-origin only. ``img-src`` starts with no third-party host: a ``Map`` registers its
tile host when it is built, and images from other hosts need ``create_app(csp_media_hosts=[...])``.

The policy is off by default and in ``launch()``: Colab and similar hosts frame the app and
supply their own origins, which a fixed policy would break.
"""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Iterable
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d{1,5})?")
_registered: dict[str, None] = {}  # insertion-ordered set of ``scheme://host[:port]``
# The hosts the last served page's policy carried; ``None`` until a page is served.
_served: set[str] | None = None
_TAG = re.compile(r"<(script|style)(?=[\s>])", re.IGNORECASE)


def new_nonce() -> str:
    """128+ random bits, URL-safe (a CSP nonce must be unguessable and unique per response)."""
    return secrets.token_urlsafe(18)


def add_nonce(html: str, nonce: str) -> str:
    """Put ``nonce="..."`` on every ``<script>`` and ``<style>`` opening tag."""
    return _TAG.sub(lambda m: f'<{m.group(1)} nonce="{nonce}"', html)


def add_nonce_parts(html: str) -> list[str]:
    """``html`` cut after each ``<script`` and ``<style`` tag name, so that joining the parts with
    ``' nonce="N"'`` gives exactly ``add_nonce(html, "N")``. The parts are the same from one
    response to the next, which lets a compressed copy of each be reused (ADR-0042)."""
    parts, last = [], 0
    for m in _TAG.finditer(html):
        parts.append(html[last : m.end()])
        last = m.end()
    parts.append(html[last:])
    return parts


def host_source(url: str) -> str | None:
    """``https://host[:port]`` for an http(s) URL, or ``None`` for anything else.

    Strict on purpose: the result is pasted into a header, so it must not be able to carry a
    space, ``;`` or quote (which would start a new directive or source)."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.replace("{", "x").replace("}", "x"))
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not _HOST.fullmatch(parts.netloc):
        return None
    return f"{parts.scheme}://{parts.netloc}"


def register_img_host(url: str) -> None:
    """Allow images (map tiles) from ``url``'s host in the policy. Unusable URLs are ignored."""
    source = host_source(url)
    if source is None:
        return
    if source not in _registered and _served is not None and source not in _served:
        log.warning(
            "image host %s was registered after a page was served, so that page's CSP blocks "
            "it until the next load; declare it up front with create_app(csp_media_hosts=[%r])",
            source,
            source,
        )
    _registered[source] = None


def known_img_hosts() -> list[str]:
    """The registered hosts, for the policy of a page about to be served."""
    global _served
    hosts = list(_registered)
    _served = set(hosts) | (_served or set())
    return hosts


def build_csp(
    nonce: str,
    *,
    img_hosts: Iterable[str],
    report_uri: str | None = None,
    connect_extra: Iterable[str] = (),
) -> str:
    """The strict policy for one response. ``img_hosts`` are extra ``scheme://host`` sources;
    ``connect_extra`` adds sources to ``connect-src`` (the live WebSocket origin, ADR-0045)."""
    connect = " ".join(["'self'", *connect_extra])
    images = " ".join(["'self'", "data:", "blob:", *img_hosts])
    directives = [
        "default-src 'none'",
        f"script-src 'nonce-{nonce}' 'self'",
        f"style-src 'nonce-{nonce}'",
        "style-src-attr 'unsafe-inline'",
        f"img-src {images}",
        f"media-src {images.replace(' data:', ' data:', 1)}",
        "font-src 'self' data:",
        f"connect-src {connect}",
        "frame-ancestors 'self'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
    if report_uri:
        directives.append(f"report-uri {report_uri}")
    return "; ".join(directives)


def render_custom(policy: str, nonce: str) -> str:
    """A custom policy string, with ``{nonce}`` replaced by this response's nonce."""
    return policy.replace("{nonce}", nonce)
