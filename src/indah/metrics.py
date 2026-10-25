"""``GET /metrics``: Prometheus text for one indah process (IND-212).

Off by default. ``create_app(metrics="a-long-token")`` (or ``INDAH_METRICS_TOKEN``) mounts it,
behind the same gate as the deploy doctor (:mod:`indah.doctor`): a bearer token, or with
``metrics=True`` a logged-in principal holding the ``metrics`` permission. Anyone else gets the
plain ``404`` a missing route gives. The numbers describe this process only; a scraper adds the
``instance`` label.

The text is written by hand (the format is a few lines), so there is no new dependency. It holds
counts and a drain flag, never a session id, user, path or secret.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from .doctor import Gate, _nothing

PATH = "/metrics"
PERMISSION = "metrics"
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class Metrics:
    """Running totals for this process. Plain integers: the event loop is single-threaded."""

    def __init__(self) -> None:
        self.events = 0  # events a session accepted and dispatched
        self.errors = 0  # handler exceptions (a refusal by ``guard`` is not an error)
        self.forwards = 0  # requests sent on to the process that owns the session
        self.forward_failures = 0  # forwards that did not reach it

    def count_error(self) -> None:
        self.errors += 1


def _version() -> str:
    from . import __version__

    return __version__


def render(metrics: Metrics, *, sessions: int | None, streams: int | None, draining: bool) -> str:
    """The exposition text. A count that is not known (a store that cannot say) is left out."""
    series: list[tuple[str, str, str, int]] = []
    if sessions is not None:
        series.append(("indah_sessions_open", "gauge", "Sessions held by this process.", sessions))
    if streams is not None:
        series.append(("indah_streams_open", "gauge", "Open SSE streams; scale on this.", streams))
    series += [
        ("indah_draining", "gauge", "1 while the process drains, else 0.", int(draining)),
        ("indah_events_total", "counter", "Events dispatched to a session.", metrics.events),
        ("indah_errors_total", "counter", "Handler exceptions.", metrics.errors),
        (
            "indah_forwards_total",
            "counter",
            "Requests forwarded to the process that owns the session.",
            metrics.forwards,
        ),
        (
            "indah_forward_failures_total",
            "counter",
            "Forwards that did not reach that process.",
            metrics.forward_failures,
        ),
    ]
    out: list[str] = []
    for name, kind, help_text, value in series:
        out += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}", f"{name} {value}"]
    out += [
        "# HELP indah_build_info The indah version, as a label.",
        "# TYPE indah_build_info gauge",
        f'indah_build_info{{version="{_version()}"}} 1',
    ]
    return "\n".join(out) + "\n"


async def handler(request: Request) -> Response:
    """``GET /metrics``: gated; ``404`` for everyone else."""
    state = request.app.state
    gate: Gate | None = getattr(state, "metrics_gate", None)
    if gate is None or not await gate.allows(request):
        return _nothing()
    store = state.store
    count = getattr(store, "open_sessions", None)
    text = render(
        state.metrics,
        sessions=count if isinstance(count, int) else None,
        streams=state.drain.open_streams,
        draining=state.drain.draining,
    )
    return Response(
        text,
        media_type=CONTENT_TYPE,
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",
            "X-Content-Type-Options": "nosniff",
        },
    )
