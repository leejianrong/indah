"""indah - a Python UI framework for ephemeral cloud notebooks.

Reactive, single-port, no Node required at install or runtime. Over the single-port
SSE transport it ships: the reactive core (signals, computeds, effects); the full
input set and layout containers (Row/Grid/Tabs/Sidebar/Expander); data-driven lists
(List/Chat/Gallery); charting (server-PNG Plot plus the client-side Chart and
Heatmap); an interactive client-side Map (pan/zoom, markers, polygons); an
interactive Table and Stat cards; ImageOverlay for boxes/masks/keypoints; native
Audio playback; file upload/download; async handlers and LLM token streaming;
per-session state; and
the register_component() seam for custom components. The wire protocol is a versioned
public contract (docs/protocol.md). See https://github.com/leejianrong/indah.
"""

from .app import build_demo_session, create_app, mock_llm
from .auth import Authenticator, Principal
from .authz import Forbidden, Policy, guard
from .components import (
    Audio,
    Badge,
    Button,
    Card,
    Chart,
    Chat,
    Checkbox,
    CodeEditor,
    Col,
    Column,
    Component,
    DataFrame,
    Date,
    Diff,
    Download,
    DownloadFile,
    Drawer,
    Expander,
    Gallery,
    Grid,
    Heatmap,
    Image,
    ImageOverlay,
    JsonTree,
    Link,
    List,
    Map,
    MasterDetail,
    Modal,
    MultiSelect,
    Number,
    Plot,
    Progress,
    Radio,
    Router,
    Row,
    RowAction,
    Select,
    Shortcuts,
    Sidebar,
    Slider,
    Spinner,
    SplitPane,
    Stat,
    StreamText,
    Switch,
    Table,
    TableQuery,
    Tabs,
    Text,
    TextArea,
    TextInput,
    Upload,
    UploadedFile,
)
from .context import ConnectionInfo, Context
from .custom import CustomComponent, custom, register_component
from .env import Environment, detect_environment, public_url
from .launch import LaunchHandle, launch
from .push import Topic
from .reactive import Computed, Signal, batch, computed, effect
from .session import DispatchResult, Session
from .session_store import (
    InMemorySessionStore,
    SessionHandle,
    SessionStore,
    SharedSessionStore,
)
from .stream import Stream
from .theme import Theme

__version__ = "0.3.0"

__all__ = [
    "__version__",
    # runtime
    "create_app",
    "build_demo_session",
    "mock_llm",
    "launch",
    "LaunchHandle",
    "Session",
    "Stream",
    "Theme",
    "Topic",
    "Context",
    "Principal",
    "Policy",
    "guard",
    "Forbidden",
    "Authenticator",
    "ConnectionInfo",
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
    "TextArea",
    "CodeEditor",
    "TextInput",
    "Select",
    "Checkbox",
    "Number",
    "Radio",
    "MultiSelect",
    "Date",
    "Image",
    "ImageOverlay",
    "Audio",
    "Badge",
    "Plot",
    "Chart",
    "Heatmap",
    "Map",
    "DataFrame",
    "Table",
    "TableQuery",
    "Stat",
    "StreamText",
    "Progress",
    "Spinner",
    "SplitPane",
    "Switch",
    # file upload / download (ADR-0017)
    "Upload",
    "UploadedFile",
    "Diff",
    "Download",
    "DownloadFile",
    # data-driven list (ADR-0016)
    "JsonTree",
    "Link",
    "List",
    "Modal",
    "Chat",
    "Col",
    "Gallery",
    # layout containers (ADR-0015)
    "Router",
    "Row",
    "RowAction",
    "Grid",
    "Tabs",
    "Shortcuts",
    "MasterDetail",
    "Sidebar",
    "Drawer",
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
