"""Compose chat messages for revit-coder calls.

Two modes:
  1. Generate: system + user(task + context)
  2. Repair: system + user(broken_code + error + task)

Loads markdown templates from prompts/ directory.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from kukai.revit_coder.types import ModelContext


_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load and cache prompt markdown."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


_SYSTEM_PROMPT = _load_prompt("system.md")
_REPAIR_TEMPLATE = _load_prompt("repair.md")


def compose_messages(
    task: str,
    model_context: ModelContext,
    api_context: Optional[list[str]] = None,
    error_to_fix: Optional[str] = None,
    broken_code: Optional[str] = None,
    previous_code: Optional[str] = None,
) -> list[dict[str, str]]:
    """Build chat messages for /v1/chat/completions.

    Returns list of {role, content} dicts.

    If `error_to_fix` and `broken_code` are both provided, the user message
    uses the repair template (with original task appended for goal anchoring).
    Otherwise, generate-mode: task + optional model_context + optional
    api_context + optional previous_code.
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _SYSTEM_PROMPT}
    ]

    if error_to_fix and broken_code:
        # Repair mode
        repair_text = _REPAIR_TEMPLATE.format(
            broken_code=broken_code,
            error_to_fix=error_to_fix,
        )
        user_content = f"{repair_text}\n\nOriginal task: {task}"
    else:
        # Generate mode
        parts = [f"Task: {task}"]

        ctx_dict = model_context.to_dict()
        if ctx_dict:
            parts.append(f"\nModel context: {json.dumps(ctx_dict, ensure_ascii=False)}")

        if api_context:
            parts.append("\nRelevant Revit API examples:")
            for snippet in api_context:
                parts.append(f"- {snippet}")

        if previous_code:
            parts.append(
                "\nThe user is asking you to modify previous code. "
                "Here is the previous code generated in this conversation:\n"
                f"```csharp\n{previous_code}\n```\n"
                "Modify it according to the new task."
            )

        user_content = "\n".join(parts)

    messages.append({"role": "user", "content": user_content})
    return messages
