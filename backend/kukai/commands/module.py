"""CommandsModule — KukaiModule implementation for user-defined commands."""

from __future__ import annotations

import logging
from typing import Any

from kukai.commands.manager import CommandManager
from kukai.commands.storage import CommandStorage
from kukai.modules.base import KukaiModule, ModuleDeps, ToolDef

logger = logging.getLogger(__name__)


class CommandsModule(KukaiModule):
    """User-defined reusable recipes (prompt + C# code + parameters)."""

    @property
    def name(self) -> str:
        return "commands"

    @property
    def version(self) -> str:
        return "1.0"

    async def on_startup(self, deps: ModuleDeps) -> None:
        self._storage = CommandStorage(deps.db)
        await self._storage.ensure_table()
        self._manager = CommandManager(self._storage, deps.bridge, deps.llm)

    def register_tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="save_command",
                description=(
                    "Сохранить текущий рецепт как пользовательскую команду. "
                    "Используй после успешного выполнения кода, когда пользователь "
                    "просит запомнить/сохранить действие."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Имя команды (без пробелов, латиница или кириллица)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Описание что делает команда",
                        },
                        "code": {
                            "type": "string",
                            "description": "C# код (последний успешно выполненный)",
                        },
                        "prompt_instructions": {
                            "type": "string",
                            "description": "Инструкции для AI при вызове команды",
                        },
                        "tags": {
                            "type": "string",
                            "description": "Теги через запятую",
                        },
                    },
                    "required": ["name", "description", "code"],
                },
                handler=self._handle_save,
            ),
            ToolDef(
                name="list_commands",
                description="Показать список сохранённых пользовательских команд.",
                parameters={
                    "type": "object",
                    "properties": {
                        "search": {
                            "type": "string",
                            "description": "Поиск по имени/описанию/тегам",
                        },
                    },
                },
                handler=self._handle_list,
            ),
            ToolDef(
                name="run_command",
                description="Выполнить сохранённую пользовательскую команду.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Имя команды",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "Параметры для подстановки",
                        },
                    },
                    "required": ["name"],
                },
                handler=self._handle_run,
            ),
            ToolDef(
                name="delete_command",
                description="Удалить пользовательскую команду.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Имя команды для удаления",
                        },
                    },
                    "required": ["name"],
                },
                handler=self._handle_delete,
            ),
        ]

    def register_prompts(self) -> dict[str, str]:
        return {
            "commands": (
                "## Пользовательские команды\n"
                "Пользователь может сохранять часто используемые действия как команды.\n\n"
                "**Сохранение:** когда пользователь говорит "
                '"сохрани как команду", "запомни это", "создай команду":\n'
                "1. Возьми последний УСПЕШНО выполненный C# код из диалога\n"
                "2. Спроси имя и описание\n"
                "3. Вызови save_command\n\n"
                "**Вызов:** когда пользователь вводит /имя_команды:\n"
                "1. Вызови run_command с именем\n"
                "2. Покажи результат\n\n"
                '**Список:** когда пользователь спрашивает "какие команды", "мои команды":\n'
                "1. Вызови list_commands\n"
                "2. Покажи список с описаниями"
            ),
        }

    async def _handle_save(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        cmd = await self._manager.save_command(
            name=params["name"],
            description=params["description"],
            code=params["code"],
            prompt_instructions=params.get("prompt_instructions", ""),
            tags=params.get("tags", ""),
        )
        return {"saved": True, "name": cmd.name, "id": cmd.id}

    async def _handle_list(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        commands = await self._manager.list_commands(params.get("search"))
        return {
            "commands": [
                {
                    "name": c.name,
                    "description": c.description,
                    "verified": c.verified,
                    "tags": c.tags,
                }
                for c in commands
            ],
            "count": len(commands),
        }

    async def _handle_run(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        return await self._manager.run_command(
            params["name"], params.get("parameters")
        )

    async def _handle_delete(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        deleted = await self._manager.delete_command(params["name"])
        return {"deleted": deleted, "name": params["name"]}
