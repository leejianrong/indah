"""`python -m indah` launches the built-in demo app.

Binds the first free port from 8000 up, prints the URL, and serves until
interrupted. This is what `make demo` runs.

Honours two env vars so the same entry point works inside a container (e.g. the
Docker Compose demo): ``INDAH_HOST`` (bind address, e.g. ``0.0.0.0``) and
``INDAH_PORT`` (a fixed port instead of auto-selecting a free one).
"""

import os

from .launch import launch

if __name__ == "__main__":
    kwargs = {}
    host = os.environ.get("INDAH_HOST")
    port = os.environ.get("INDAH_PORT")
    if host:
        kwargs["host"] = host
    if port:
        kwargs["port"] = int(port)
    launch(**kwargs)
