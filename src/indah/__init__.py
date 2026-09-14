"""indah - a Python UI framework for ephemeral cloud notebooks.

Early development. Slice 1 provides the single-port ASGI app with an SSE
transport (a live counter); the reactive component API is not built yet. See
https://github.com/leejianrong/indah for the plan.
"""

from .app import create_app
from .env import Environment, detect_environment, public_url
from .launch import LaunchHandle, launch

__version__ = "0.0.1"

__all__ = [
    "__version__",
    "create_app",
    "launch",
    "LaunchHandle",
    "Environment",
    "detect_environment",
    "public_url",
]
