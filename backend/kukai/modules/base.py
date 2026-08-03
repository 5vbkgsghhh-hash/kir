"""Base class for all KUKAI modules.

Every engine (VOR, Audit, IFC, etc.) implements KukaiModule.
This gives us: dynamic tool registration, modular prompts,
config-driven enable/disable, and clean dependency injection.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from kukai.bridge.client import BridgeClient
    from kukai.llm.client import LLMClient
    from kukai.llm.prompts import PromptAssembler
    from kukai.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass
class ToolDef:
    """Tool definition that a module contributes to the LLM.

    This is a lightweight descriptor — the actual tool implementation
    stays inside the module. The LLM tool system reads these to build
    the tool list dynamically.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Any  # async callable(params, context) -> result

    def to_openai_dict(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ModuleDeps:
    """Shared dependencies injected into modules at startup."""

    bridge: BridgeClient
    llm: LLMClient
    db: Database
    prompts: PromptAssembler
    data_dir: Any = None  # Path to backend/data/


class KukaiModule(ABC):
    """Base class for KUKAI engines.

    Each module must implement:
    - name/version properties
    - on_startup() for initialization with deps
    - register_tools() for LLM tools
    - register_prompts() for system prompt sections

    Optional:
    - register_routes() for HTTP/WS endpoints
    - on_shutdown() for cleanup
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique module name (e.g. 'vor', 'audit', 'ifc')."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Module version string."""
        ...

    @property
    def requires(self) -> list[str]:
        """List of required dependencies: 'bridge', 'llm', 'db', 'prompts'."""
        return ["bridge", "llm", "db"]

    @abstractmethod
    async def on_startup(self, deps: ModuleDeps) -> None:
        """Initialize the module with shared dependencies.

        Called once during app startup. Store what you need, create engines, etc.
        """
        ...

    async def on_shutdown(self) -> None:
        """Cleanup on app shutdown. Override if needed."""
        pass

    @abstractmethod
    def register_tools(self) -> list[ToolDef]:
        """Return tool definitions this module contributes to the LLM.

        Called after on_startup(). Each ToolDef becomes available
        to the AI agent when this module is enabled.
        """
        ...

    def register_prompts(self) -> dict[str, str]:
        """Return prompt sections to inject into the system prompt.

        Keys are section names, values are markdown text.
        Example: {"audit": "## /аудит — Проверка модели\\n..."}
        Default: no prompt sections.
        """
        return {}

    def register_routes(self, app: "FastAPI") -> None:
        """Register HTTP/WebSocket routes. Override if needed."""
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} v={self.version!r}>"
