"""Per-intent tool masking (KUKAI_TOOL_MASKING) + palette-flag resolution.

WHY (task 2026-07-04, Tool Palette v2): the full tool schema (~17 tools,
~5.9K tokens) is sent on EVERY LLM call while live usage is execute_revit_code
73% / get_model_info 8% / apply_revit_write 3% / long tail <2%. Masking sends
each turn only the tool family the ROUTER'S INTENT needs, cutting prompt cost
and DeepSeek's fat-schema confusion — with two hard safety rails:

* FAIL-OPEN everywhere: unknown/missing intent → FULL list; family-editor
  panels are never masked; names outside the maskable universe (module tools,
  future tools) are never dropped.
* The model can NEVER be hard-locked out of a capability: every masked panel
  carries ``request_more_tools(reason)`` — calling it returns the full catalog
  (names + one-liners) AND unmasks the panel for the rest of the turn
  (dispatch side: kukai/llm/tool_handlers/palette_v2.py).

Flag reads happen at CALL time (KUKAI_EXEC_PIPELINE convention — restart-free
operator flips). Both flags OFF ⇒ ``resolve_tool_panel`` returns the base list
object UNCHANGED (identity) — byte-identical turns.

This module also owns the runtime KUKAI_TOOLS_V2 re-resolution: the client
caches ``self._tools`` at startup, so a runtime flag flip is honored here by
rebuilding the palette through ``get_tool_definitions`` (cheap, per-call).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

MASKING_FLAG = "KUKAI_TOOL_MASKING"


def masking_enabled() -> bool:
    """KUKAI_TOOL_MASKING=1 turns per-intent masking on (env read at call
    time; a typo can never activate). Default OFF."""
    return os.environ.get(MASKING_FLAG, "0") == "1"


# ─────────────────────────────────────────────────────────────────────────────
# The intent → toolset policy, AS DATA.
#
# Sets contain BOTH v1 and v2 tool names — masking composes with either
# palette (independent flags); names absent from the live palette are simply
# not matched. Router intent vocabulary (kukai/agents/router.py):
# count/list/filter/tag/delete/modify/create/schedule/export/diagnose/converse.
# ─────────────────────────────────────────────────────────────────────────────

_READ = frozenset({
    "get_model_info", "get_model_details", "query_model", "inspect",
    "lookup_norm", "add_user_note",
})
_SHOW = frozenset({"select_elements", "highlight_elements", "show_elements"})
_EXEC = frozenset({"execute_revit_code"})
_WRITE = frozenset({"apply_revit_write"}) | _EXEC
_REPORT = frozenset({
    "generate_report", "modify_excel", "excel_script", "edit_excel",
    "process_uploaded_file",
})
_EXPORT = frozenset({
    "export_view", "export_sheets_pdf", "send_local_file", "export",
    "import_cad",
})

_MINIMAL_SET = frozenset({"get_model_info", "lookup_norm", "add_user_note"})
_READ_SET = _READ | _SHOW | _EXEC
_WRITE_SET = _READ | _SHOW | _WRITE          # grounding reads stay available
_EXPORT_SET = _READ | _EXEC | _EXPORT | _REPORT  # "выгрузи в Excel" lands here
_SCHEDULE_SET = _READ | _EXEC | _WRITE | _REPORT

INTENT_TOOLSETS: dict[str, frozenset[str]] = {
    "converse": _MINIMAL_SET,
    "count": _READ_SET,
    "list": _READ_SET,
    "filter": _READ_SET,
    "diagnose": _READ_SET | _REPORT,          # analysis → may compile a report
    "tag": _WRITE_SET,
    "create": _WRITE_SET,
    "modify": _WRITE_SET,
    "delete": _WRITE_SET,
    "export": _EXPORT_SET,
    "schedule": _SCHEDULE_SET,
}

# The universe of names the policy is allowed to hide. Anything OUTSIDE this
# set (module-registry tools, family_* tools, future additions) is NEVER
# masked — fail-open per tool.
KNOWN_MASKABLE: frozenset[str] = (
    _READ | _SHOW | _EXEC | _WRITE | _REPORT | _EXPORT
)


def request_more_tools_def() -> dict[str, Any]:
    """The meta-tool appended to every masked panel — the model's guaranteed
    escape hatch out of the mask."""
    return {
        "type": "function",
        "function": {
            "name": "request_more_tools",
            "description": (
                "Открыть ПОЛНЫЙ каталог инструментов KUKAI, если в текущей "
                "панели не хватает нужного (экспорт, Excel, запись и т.д.). "
                "Возвращает список всех инструментов и открывает их до конца "
                "этого хода."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Что ты хочешь сделать и какого инструмента не хватает.",
                    },
                },
                "required": ["reason"],
            },
        },
    }


def catalog(tools: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Full-catalog view for the request_more_tools result: name + one-liner
    (first sentence of the description, capped)."""
    out: list[dict[str, str]] = []
    for t in tools:
        fn = t.get("function") or {}
        name = fn.get("name") or ""
        if not name or name == "request_more_tools":
            continue
        desc = (fn.get("description") or "").strip()
        first = desc.split(". ", 1)[0].strip()
        out.append({"name": name, "summary": (first[:140] or name)})
    return out


def mark_unmasked() -> None:
    """Unmask the panel for the rest of THIS turn (called by the
    request_more_tools handler). Mutates the shared per-turn dict so the mark
    is visible even when tool execution ran in a copied child context."""
    from kukai.llm.turn_context import _turn_tool_mask_state
    state = _turn_tool_mask_state.get()
    if state is not None:
        state["unmasked"] = True
    else:  # router never published (masking wasn't applied) — best-effort
        _turn_tool_mask_state.set({"unmasked": True})


def _is_v2_palette(tools: list[dict[str, Any]]) -> bool:
    from kukai.llm.tools import V2_NEW_TOOLS
    return any((t.get("function") or {}).get("name") in V2_NEW_TOOLS for t in tools)


def resolve_tool_panel(
    base: list[dict[str, Any]],
    module_registry: Any = None,
    context: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """The single per-request entry point (called from LLMClient._resolve_tools).

    1. Honors a RUNTIME KUKAI_TOOLS_V2 flip: if the flag state disagrees with
       the shape of ``base`` (client startup cache), rebuild via
       get_tool_definitions — restart-free, both directions.
    2. Applies per-intent masking (KUKAI_TOOL_MASKING) on top of v1 OR v2.

    Both flags OFF ⇒ returns ``base`` unchanged (same object) — byte-identical.
    """
    tools = base
    try:
        from kukai.llm.tools import get_tool_definitions, tools_v2_enabled
        if tools_v2_enabled() != _is_v2_palette(tools):
            tools = get_tool_definitions(module_registry=module_registry, context=context)
    except Exception:  # noqa: BLE001 — palette resolution must never kill a turn
        logger.exception("tool palette v2 re-resolution failed — serving base list")
        tools = base

    if not masking_enabled():
        return tools
    try:
        return _mask(tools, context)
    except Exception:  # noqa: BLE001 — masking must never kill a turn (fail-open)
        logger.exception("tool masking failed — serving full list")
        return tools


def _mask(
    tools: list[dict[str, Any]], context: Optional[Any]
) -> list[dict[str, Any]]:
    # Family-editor panels are purpose-built and intent vocabulary doesn't map
    # onto them — never mask.
    if context is not None and getattr(context, "is_family_editor", False):
        return tools

    from kukai.llm.turn_context import _turn_route_intent, _turn_tool_mask_state

    state = _turn_tool_mask_state.get()
    if state is not None and state.get("unmasked"):
        return tools  # request_more_tools opened the catalog for this turn

    intent = _turn_route_intent.get()
    allowed = INTENT_TOOLSETS.get(intent or "")
    if allowed is None:
        return tools  # unknown / unpublished intent → FULL list (fail-open)

    panel = [
        t for t in tools
        if (t.get("function") or {}).get("name") not in KNOWN_MASKABLE
        or (t.get("function") or {}).get("name") in allowed
    ]
    if len(panel) == len(tools):
        return tools  # nothing hidden — no meta-tool noise
    logger.debug(
        "tool masking: intent=%s panel=%d/%d", intent, len(panel), len(tools)
    )
    return panel + [request_more_tools_def()]
