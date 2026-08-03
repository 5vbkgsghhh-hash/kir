"""Business logic for user commands."""

from __future__ import annotations

import logging
import string
from typing import TYPE_CHECKING

from kukai.commands.models import UserCommand

if TYPE_CHECKING:
    from kukai.bridge.client import BridgeClient
    from kukai.commands.storage import CommandStorage
    from kukai.llm.client import LLMClient

logger = logging.getLogger(__name__)


class CommandManager:
    """Manages user-defined commands: save, run, list, delete."""

    def __init__(
        self,
        storage: CommandStorage,
        bridge: BridgeClient,
        llm: LLMClient,
    ) -> None:
        self._storage = storage
        self._bridge = bridge
        self._llm = llm

    async def save_command(
        self,
        name: str,
        description: str,
        code: str,
        prompt_instructions: str = "",
        parameters_schema: str = "",
        tags: str = "",
    ) -> UserCommand:
        """Save a new command or update existing."""
        cmd = UserCommand(
            name=name,
            description=description,
            code_template=code,
            prompt_instructions=prompt_instructions,
            parameters_schema=parameters_schema,
            tags=tags,
        )
        # Check if exists — preserve id and iterations
        existing = await self._storage.get(name)
        if existing:
            cmd.id = existing.id
            cmd.iterations = existing.iterations
            cmd.verified = existing.verified

        cmd.id = await self._storage.save(cmd)
        logger.info("Command saved: %s (id=%s)", name, cmd.id)
        return cmd

    async def run_command(
        self, name: str, parameters: dict | None = None
    ) -> dict:
        """Load command and execute its code through bridge.

        1. Load from storage
        2. If parameters -> substitute into code_template
        3. Execute via bridge
        4. Return result
        """
        cmd = await self._storage.get(name)
        if cmd is None:
            return {"error": True, "message": f"Command '{name}' not found"}

        code = cmd.code_template
        if parameters:
            try:
                code = string.Template(code).safe_substitute(parameters)
            except (ValueError, KeyError) as exc:
                logger.warning("Parameter substitution failed for %s: %s", name, exc)

        try:
            exec_result = await self._bridge.execute(code=code, timeout_ms=30000)
        except Exception as exc:
            logger.exception("Command execution failed: %s", name)
            return {"error": True, "message": f"Execution failed: {exc}"}

        if not exec_result.success:
            return {
                "error": True,
                "message": f"Command '{name}' failed: {exec_result.output}",
            }

        # Bump iteration count (preserve original template, not substituted code)
        await self._storage.update_code(name, cmd.code_template, cmd.iterations + 1)

        return {
            "success": True,
            "command": name,
            "output": exec_result.output,
            "execution_time_ms": exec_result.execution_time_ms,
        }

    async def list_commands(self, search: str | None = None) -> list[UserCommand]:
        """List available commands."""
        return await self._storage.list_all(search)

    async def delete_command(self, name: str) -> bool:
        """Delete a command."""
        deleted = await self._storage.delete(name)
        if deleted:
            logger.info("Command deleted: %s", name)
        return deleted
