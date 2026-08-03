"""Data models for the Commands module."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserCommand:
    """A user-defined reusable recipe (prompt + C# code + parameters)."""

    id: int | None = None
    name: str = ""                    # "/двери_по_сп"
    description: str = ""             # "Расстановка дверей по СП"
    prompt_instructions: str = ""     # Инструкции для AI при вызове
    code_template: str = ""           # Последний рабочий C# код
    parameters_schema: str = ""       # JSON string: {"width": "int"}
    verified: bool = False
    iterations: int = 0
    created_at: str = ""
    updated_at: str = ""
    tags: str = ""                    # "двери,СП,эвакуация"
