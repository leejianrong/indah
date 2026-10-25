"""The route hint (IND-197, ADR-0043): tell the tab which process holds its stream.

With several Fly machines, an event that lands on a machine other than the stream's is lost
(``409 unknown_session``). The fix is on the client: indah's own shell sends the stream's machine
id back as the request header ``fly-force-instance-id``, and Fly Proxy routes the request there.
The server's part is to say which machine that is: the ``init`` message carries
``route: {hint, node, transport}``, and file URLs it mints carry ``?r=<hint>``.

The hint is off unless ``INDAH_CLUSTER_SECRET`` (or ``create_app(cluster_secret=)``) is set. That
secret is never derived from ``secret=``, so one secret does not do two jobs. On Fly the hint is a
plain machine id and not a capability (a client can only choose its own machine and get a ``409``
from the wrong one), so nothing is signed with the secret yet; it is the explicit switch the
Kubernetes forwarder (IND-209) will also need.

``INDAH_ROUTE_HINT`` is ``auto`` (the default: ``fly`` when ``FLY_MACHINE_ID`` is set, else off),
``fly`` or ``off``. ``peers`` is reserved for the Kubernetes forwarder and is refused for now.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_MODES = ("auto", "fly", "peers", "off")
MACHINE_ID = re.compile(r"[A-Za-z0-9]{1,32}")  # a Fly machine id is 14 hex characters


@dataclass(frozen=True)
class RouteHint:
    """What this process tells its tabs: a machine ``hint`` and the ``transport`` that uses it."""

    hint: str
    transport: str  # "fly": the shell sends fly-force-instance-id

    def wire(self, node: str) -> dict[str, Any]:
        """The ``route`` object of an ``init`` message."""
        return {"hint": self.hint, "node": node, "transport": self.transport}


def resolve_route_hint(
    mode: str | None = None,
    cluster_secret: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> RouteHint | None:
    """The hint for this process, or ``None`` when it is off (see the module docstring).

    ``mode`` and ``cluster_secret`` are the ``create_app`` arguments; ``None`` means not given, so
    the variable is read. An explicit empty ``cluster_secret`` counts as given, and as no secret."""
    env = os.environ if environ is None else environ
    if mode is None:
        mode = (env.get("INDAH_ROUTE_HINT") or "").strip().lower() or "auto"
        source = "INDAH_ROUTE_HINT"
    else:
        mode = mode.strip().lower()
        source = "route_hint="
    if mode not in _MODES:
        raise ValueError(f"{source} must be one of {', '.join(_MODES)}, got {mode!r}")
    if mode == "peers":
        raise ValueError(
            f"{source} 'peers' needs the Kubernetes forwarder, which is not built yet; "
            "use 'fly' on Fly, or put a cookie-affinity ingress in front on Kubernetes"
        )
    if mode == "off":
        return None
    machine = (env.get("FLY_MACHINE_ID") or "").strip()
    if mode == "auto" and not machine:
        return None
    if mode == "fly" and not machine:
        raise ValueError(f"{source} 'fly' needs FLY_MACHINE_ID, which Fly sets on every machine")
    secret = (env.get("INDAH_CLUSTER_SECRET") or "") if cluster_secret is None else cluster_secret
    if not secret.strip():
        return None  # the hint needs the cluster secret, explicitly (ADR-0043, Q5)
    if not MACHINE_ID.fullmatch(machine):
        return None  # never put an odd value in a header or a URL
    return RouteHint(hint=machine, transport="fly")
