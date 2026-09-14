"""indah - a Python UI framework for ephemeral cloud notebooks.

Early development. Slice 2 adds the reactive core (signals, computeds, effects)
and a component tree (Text, Button, Slider, Column) served over the single-port
SSE transport. The Svelte shell and richer components come in later slices. See
https://github.com/leejianrong/indah for the plan.
"""

from .app import build_demo_session, create_app
from .components import Button, Column, Component, Slider, Text
from .env import Environment, detect_environment, public_url
from .launch import LaunchHandle, launch
from .reactive import Computed, Signal, batch, computed, effect
from .session import Session

__version__ = "0.0.1"

__all__ = [
    "__version__",
    # runtime
    "create_app",
    "build_demo_session",
    "launch",
    "LaunchHandle",
    "Session",
    # reactive
    "Signal",
    "Computed",
    "computed",
    "effect",
    "batch",
    # components
    "Component",
    "Column",
    "Text",
    "Button",
    "Slider",
    # environment
    "Environment",
    "detect_environment",
    "public_url",
]
