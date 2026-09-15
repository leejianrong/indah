"""indah - a Python UI framework for ephemeral cloud notebooks.

Reactive, single-port, no Node required at install or runtime. The MVP is
feature-complete: the reactive core (signals, computeds, effects), a starter
component set (Text, Button, Slider, TextInput, Select, Image, Plot, DataFrame,
StreamText, Column) served over the single-port SSE transport, async handlers and
LLM token streaming, and the register_component() seam for custom components
(ADR-0012). The wire protocol is a versioned public contract (docs/protocol.md).
See https://github.com/leejianrong/indah for the plan.
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

__version__ = "0.1.0"

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
