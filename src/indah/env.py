"""Detect the runtime environment and build the public URL for a launched app.

The target platforms proxy a single port to the outside world in different ways:

- **Colab** proxies via a runtime call, ``google.colab.kernel.proxyPort(port)``,
  which returns an opaque ``googleusercontent.com`` URL. It cannot be built from
  the port alone, so we resolve it through an injected callable (real one imports
  ``google.colab``; tests pass a fake).
- **Runpod** exposes ``https://{POD_ID}-{port}.proxy.runpod.net``, which *can* be
  built from the pod id (an env var) and the port.
- **Local** is just ``http://{host}:{port}``.

See ADR-0001 (single port) and ADR-0002 (why the transport must survive these
proxies).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from enum import Enum


class Environment(str, Enum):
    COLAB = "colab"
    RUNPOD = "runpod"
    LOCAL = "local"


def detect_environment(env: Mapping[str, str] | None = None) -> Environment:
    """Return the environment indah is running in.

    Detection order is Colab, then Runpod, then local. ``env`` overrides
    ``os.environ`` for testing.
    """
    env = os.environ if env is None else env

    # Colab sets COLAB_RELEASE_TAG; the google.colab module is also importable.
    if env.get("COLAB_RELEASE_TAG") or _module_available("google.colab"):
        return Environment.COLAB
    if env.get("RUNPOD_POD_ID"):
        return Environment.RUNPOD
    return Environment.LOCAL


def public_url(
    port: int,
    environment: Environment | None = None,
    *,
    host: str = "127.0.0.1",
    env: Mapping[str, str] | None = None,
    colab_proxy: Callable[[int], str] | None = None,
) -> str:
    """Build the externally reachable URL for ``port`` in the given environment.

    ``colab_proxy`` resolves the Colab proxy URL for a port; it defaults to the
    real ``google.colab`` call and is injectable for tests.
    """
    env = os.environ if env is None else env
    environment = detect_environment(env) if environment is None else environment

    if environment is Environment.COLAB:
        proxy = colab_proxy or _colab_proxy_url
        return proxy(port).rstrip("/")
    if environment is Environment.RUNPOD:
        pod_id = env.get("RUNPOD_POD_ID", "")
        return f"https://{pod_id}-{port}.proxy.runpod.net"
    return f"http://{host}:{port}"


def _colab_proxy_url(port: int) -> str:  # pragma: no cover - requires Colab runtime
    from google.colab.output import eval_js  # type: ignore[import-not-found]

    return eval_js(f"google.colab.kernel.proxyPort({port})")


def _module_available(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False
