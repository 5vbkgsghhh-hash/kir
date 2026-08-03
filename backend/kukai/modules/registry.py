"""Module registry — discovers, loads, and manages KUKAI modules."""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from kukai.modules.base import KukaiModule, ModuleDeps, ToolDef

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Known module paths — maps name → Python module path
_MODULE_MAP: dict[str, str] = {
    "audit": "kukai.audit",
    "commands": "kukai.commands",
}


class ModuleRegistry:
    """Discovers, loads, and manages KUKAI modules.

    Usage in main.py:
        registry = ModuleRegistry()
        await registry.load_modules(["vor", "audit"], deps)
        tools = registry.get_all_tools()
        prompts = registry.get_all_prompts()
    """

    def __init__(self) -> None:
        self._modules: dict[str, KukaiModule] = {}

    @property
    def modules(self) -> dict[str, KukaiModule]:
        return dict(self._modules)

    @property
    def module_names(self) -> list[str]:
        return list(self._modules.keys())

    async def load_modules(
        self,
        module_names: list[str],
        deps: ModuleDeps,
    ) -> None:
        """Discover, instantiate, and start modules by name.

        Args:
            module_names: List of module names to load (e.g. ["vor", "audit"]).
            deps: Shared dependencies to inject into each module.
        """
        for name in module_names:
            name = name.strip()
            if not name:
                continue

            module_path = _MODULE_MAP.get(name)
            if module_path is None:
                logger.warning("Unknown module %r — skipping", name)
                continue

            try:
                py_module = importlib.import_module(module_path)
                module_class = getattr(py_module, "module_class", None)

                if module_class is None:
                    logger.warning(
                        "Module %r has no 'module_class' attribute — skipping", name
                    )
                    continue

                if not (isinstance(module_class, type) and issubclass(module_class, KukaiModule)):
                    logger.warning(
                        "Module %r module_class is not a KukaiModule subclass — skipping", name
                    )
                    continue

                instance = module_class()
                await instance.on_startup(deps)
                self._modules[name] = instance
                logger.info("Module loaded: %s", instance)

            except Exception:
                logger.exception("Failed to load module %r", name)

    def register_routes(self, app: "FastAPI") -> None:
        """Register all module routes with the FastAPI app."""
        for module in self._modules.values():
            try:
                module.register_routes(app)
            except Exception:
                logger.exception("Failed to register routes for %s", module.name)

    def get_all_tools(self) -> list[ToolDef]:
        """Collect tool definitions from all loaded modules."""
        tools: list[ToolDef] = []
        for module in self._modules.values():
            try:
                module_tools = module.register_tools()
                tools.extend(module_tools)
                if module_tools:
                    logger.debug(
                        "Module %s registered %d tools", module.name, len(module_tools)
                    )
            except Exception:
                logger.exception("Failed to get tools from %s", module.name)
        return tools

    def get_all_prompts(self) -> dict[str, str]:
        """Collect prompt sections from all loaded modules."""
        prompts: dict[str, str] = {}
        for module in self._modules.values():
            try:
                module_prompts = module.register_prompts()
                prompts.update(module_prompts)
            except Exception:
                logger.exception("Failed to get prompts from %s", module.name)
        return prompts

    async def shutdown(self) -> None:
        """Shutdown all modules in reverse order."""
        for name in reversed(list(self._modules.keys())):
            module = self._modules[name]
            try:
                await module.on_shutdown()
                logger.info("Module shut down: %s", name)
            except Exception:
                logger.exception("Error shutting down module %s", name)
        self._modules.clear()

    def get_module(self, name: str) -> KukaiModule | None:
        """Get a loaded module by name."""
        return self._modules.get(name)
