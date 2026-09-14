"""indah - a Python UI framework for ephemeral cloud notebooks.

Early development. Slice 2 adds the reactive core (signals, computeds, effects)
and a component tree (Text, Button, Slider, Column) served over the single-port
SSE transport; Slice 3 adds async handlers and token streaming (StreamText,
TextInput). Slice 4 completes the starter set (Select, Image, Plot, DataFrame) and
the register_component() seam for custom components (ADR-0012). See
https://github.com/leejianrong/indah for the plan.
"""

from .app import build_demo_session, create_app, mock_llm
from .components import (
    Button,
    Column,
    Component,
    DataFrame,
    Image,
    Plot,
    Select,
    Slider,
    StreamText,
    Text,
    TextInput,
)
from .custom import CustomComponent, custom, register_component
from .env import Environment, detect_environment, public_url
from .launch import LaunchHandle, launch
from .reactive import Computed, Signal, batch, computed, effect
from .session import DispatchResult, Session

__version__ = "0.0.1"

__all__ = [
    "__version__",
    # runtime
    "create_app",
    "build_demo_session",
    "mock_llm",
    "launch",
    "LaunchHandle",
    "Session",
    "DispatchResult",
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
    "TextInput",
    "Select",
    "Image",
    "Plot",
    "DataFrame",
    "StreamText",
    # custom components (R7)
    "register_component",
    "custom",
    "CustomComponent",
    # environment
    "Environment",
    "detect_environment",
    "public_url",
]
