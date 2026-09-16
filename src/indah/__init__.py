"""indah - a Python UI framework for ephemeral cloud notebooks.

Reactive, single-port, no Node required at install or runtime. Over the single-port
SSE transport it ships: the reactive core (signals, computeds, effects); the full
input set and layout containers (Row/Grid/Tabs/Sidebar/Expander); data-driven lists
(List/Chat/Gallery); charting (server-PNG Plot plus the client-side Chart and
Heatmap); an interactive Table and Stat cards; ImageOverlay for boxes/masks/keypoints;
file upload/download; async handlers and LLM token streaming; per-session state; and
the register_component() seam for custom components. The wire protocol is a versioned
public contract (docs/protocol.md). See https://github.com/leejianrong/indah.
"""

from .app import build_demo_session, create_app, mock_llm
from .components import (
    Button,
    Card,
    Chart,
    Chat,
    Checkbox,
    Column,
    Component,
    DataFrame,
    Date,
    Download,
    DownloadFile,
    Expander,
    Gallery,
    Grid,
    Heatmap,
    Image,
    ImageOverlay,
    List,
    MultiSelect,
    Number,
    Plot,
    Progress,
    Radio,
    Row,
    Select,
    Sidebar,
    Slider,
    Spinner,
    Stat,
    StreamText,
    Table,
    Tabs,
    Text,
    TextInput,
    Upload,
    UploadedFile,
)
from .custom import CustomComponent, custom, register_component
from .env import Environment, detect_environment, public_url
from .launch import LaunchHandle, launch
from .reactive import Computed, Signal, batch, computed, effect
from .session import DispatchResult, Session
from .session_store import (
    InMemorySessionStore,
    SessionHandle,
    SessionStore,
    SharedSessionStore,
)

__version__ = "0.2.1"

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
    # per-session state seam (ADR-0010)
    "SessionStore",
    "SessionHandle",
    "InMemorySessionStore",
    "SharedSessionStore",
    # reactive
    "Signal",
    "Computed",
    "computed",
    "effect",
    "batch",
    # components
    "Component",
    "Column",
    "Card",
    "Text",
    "Button",
    "Slider",
    "TextInput",
    "Select",
    "Checkbox",
    "Number",
    "Radio",
    "MultiSelect",
    "Date",
    "Image",
    "ImageOverlay",
    "Plot",
    "Chart",
    "Heatmap",
    "DataFrame",
    "Table",
    "Stat",
    "StreamText",
    "Progress",
    "Spinner",
    # file upload / download (ADR-0017)
    "Upload",
    "UploadedFile",
    "Download",
    "DownloadFile",
    # data-driven list (ADR-0016)
    "List",
    "Chat",
    "Gallery",
    # layout containers (ADR-0015)
    "Row",
    "Grid",
    "Tabs",
    "Sidebar",
    "Expander",
    # custom components (R7)
    "register_component",
    "custom",
    "CustomComponent",
    # environment
    "Environment",
    "detect_environment",
    "public_url",
]
