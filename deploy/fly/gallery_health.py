"""Link health for listed gallery apps (IND-192).

Pure standard library, so the logic runs in the fast test layer with a fake fetcher and clock.
``check_gallery_links.py`` is the scheduled entry point; ``gallery_app`` reads the state file this
module writes and never touches the network itself.

State is one JSON object, ``slug -> {last_ok, last_checked, failures, detail}``. ``failures`` counts
consecutive failed checks and goes back to 0 on the first success, so a recovered app returns with
no code change.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from gallery_catalog import THUMB_MAX_BYTES

NOT_RESPONDING_AFTER = 3  # consecutive failed checks before the card says "Not responding"
HIDDEN_AFTER = 8  # consecutive failed checks before the card is left out
MAX_REDIRECTS = 3
TIMEOUT = 15.0
STATE_FILE = Path(__file__).parent / "gallery_status.json"

# A fetcher does one request WITHOUT following redirects and returns (status, location or None).
Fetcher = Callable[[str, str, float], "tuple[int, str | None]"]
Result = "tuple[bool, str]"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def urllib_fetch(method: str, url: str, timeout: float) -> tuple[int, str | None]:
    """The real fetcher. No cookies, no credentials, no redirect following (check_url does that)."""
    req = urllib.request.Request(
        url, method=method, headers={"User-Agent": "indah-gallery-linkcheck"}
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.headers.get("Location")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location")


def _plain_https(url: str) -> bool:
    p = urlparse(url)
    return p.scheme == "https" and bool(p.netloc) and not p.username and not p.password


def _one(method: str, url: str, fetch: Fetcher, timeout: float) -> tuple[bool, str]:
    for _ in range(MAX_REDIRECTS + 1):
        if not _plain_https(url):
            return False, "not a plain https URL"
        try:
            status, location = fetch(method, url, timeout)
        except Exception as e:  # noqa: BLE001 - any network failure is just "not responding"
            return False, f"{type(e).__name__}: {e}"[:120]
        if 300 <= status < 400 and location:
            url = urljoin(url, location)
            continue
        return (200 <= status < 300), str(status)
    return False, "too many redirects"


def check_url(
    url: str, fetch: Fetcher = urllib_fetch, timeout: float = TIMEOUT
) -> tuple[bool, str]:
    """HEAD first; any failure is retried once as GET (some servers refuse HEAD)."""
    if not _plain_https(url):
        return False, "not a plain https URL"
    ok, why = _one("HEAD", url, fetch, timeout)
    if ok:
        return ok, why
    return _one("GET", url, fetch, timeout)


def update_state(
    state: dict[str, Any], results: dict[str, tuple[bool, str]], now: str
) -> dict[str, Any]:
    """Fold one round of results into the state. Slugs no longer listed are dropped."""
    out: dict[str, Any] = {}
    for slug, (ok, detail) in results.items():
        prev = state.get(slug) or {}
        out[slug] = {
            "last_ok": now if ok else prev.get("last_ok"),
            "last_checked": now,
            "failures": 0 if ok else int(prev.get("failures", 0)) + 1,
            "detail": detail,
        }
    return out


def status_for(entry_state: dict[str, Any] | None) -> str:
    failures = int((entry_state or {}).get("failures", 0))
    if failures >= HIDDEN_AFTER:
        return "hidden"
    if failures >= NOT_RESPONDING_AFTER:
        return "not_responding"
    return "ok"


def apply_status(entries: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    """The entries to show: hidden ones left out, the rest copied with a ``status`` key."""
    shown = []
    for e in entries:
        status = status_for(state.get(e["slug"]))
        if status != "hidden":
            shown.append({**e, "status": status})
    return shown


def load_state(path: Path = STATE_FILE) -> dict[str, Any]:
    """Read the state file. Missing or unreadable means nothing is known, so every card shows."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def thumbnail_problems(entries: list[dict[str, Any]], thumb_dir: Path) -> list[str]:
    problems = []
    for e in entries:
        name = e.get("thumbnail")
        path = thumb_dir / name if name else None
        if path is None or Path(name).name != name or not path.is_file():
            problems.append(f"{e['slug']}: thumbnail {name!r} is missing")
        elif path.stat().st_size > THUMB_MAX_BYTES:
            problems.append(f"{e['slug']}: thumbnail is larger than {THUMB_MAX_BYTES} bytes")
    return problems


_LABEL = {"ok": "Working", "not_responding": "Not responding", "hidden": "Hidden"}


def summary(entries: list[dict[str, Any]], state: dict[str, Any], problems: list[str]) -> str:
    """Markdown for $GITHUB_STEP_SUMMARY."""
    lines = ["## Gallery link check", ""]
    if not entries:
        lines.append("No listed apps in the catalog yet.")
    else:
        lines += [
            "| App | Status | Failures | Last working | Last result |",
            "|---|---|---|---|---|",
        ]
        for e in entries:
            s = state.get(e["slug"]) or {}
            lines.append(
                f"| {e['title']} | {_LABEL[status_for(s)]} | {s.get('failures', 0)} | "
                f"{s.get('last_ok') or 'never seen'} | {s.get('detail', '')} |"
            )
        lines += [
            "",
            f"A card says Not responding after {NOT_RESPONDING_AFTER} failed weekly checks "
            f"and is hidden after {HIDDEN_AFTER}. One success brings it back.",
        ]
    if problems:
        lines += ["", "### Thumbnail problems", ""] + [f"- {p}" for p in problems]
    return "\n".join(lines) + "\n"
