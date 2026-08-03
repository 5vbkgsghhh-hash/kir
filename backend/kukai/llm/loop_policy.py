"""Pure loop-policy helpers for the chat tool loop (extracted from client.py).

Pure relocation (2026-07-04 client.py decomposition, Step 1): every body below
is byte-identical to its previous definition in ``kukai/llm/client.py``.
``client.py`` re-exports all names (and rebinds ``_tool_choice_for`` /
``_should_dedup`` / ``_MUST_ACT_INTENTS`` as ``LLMClient`` class attributes) so
every existing importer and test keeps working unchanged.

Stateless: decision functions + pattern tables only. The one textual delta from
the relocation is inside ``_tool_choice_for``: it now references the
module-level ``_MUST_ACT_INTENTS`` instead of ``LLMClient._MUST_ACT_INTENTS``
— the class attribute is rebound to THIS same frozenset object, so the
behavior is identical.
"""
from __future__ import annotations

import json
from typing import Any, Optional

# --- Dynamic timeout calculation ---

# Patterns that indicate write operations
_WRITE_PATTERNS = [
    "Transaction", "t.Start()", "t.Commit()",
    ".Set(", ".Delete(", "doc.Delete(",
    "Create.", "NewFamilyInstance", "Wall.Create",
    "ElementTransformUtils.Move", "ElementTransformUtils.Copy",
    "ElementTransformUtils.Rotate",
    "SetElementOverrides",
]

# Tool names that ALWAYS mutate the model when they succeed (used to invalidate
# the convergence dedup cache so a legitimate re-query AFTER a write is not
# punished as a duplicate — the look→act→see loop). execute_revit_code is a
# write only when its code carries a _WRITE_PATTERNS marker; family_* tools are
# all writes except the read-only inspect_family — both handled in
# _tool_call_is_write() below.
_ALWAYS_WRITE_TOOLS = frozenset({"apply_revit_write"})
_FAMILY_READ_ONLY_TOOLS = frozenset({"inspect_family"})


def _tool_call_is_write(tool_name: str, tool_args: dict[str, Any]) -> bool:
    """Whether a *successful* tool call mutated the model, reusing the existing
    write-detection scaffolding (no new classifier):

    - ``apply_revit_write`` — always a write (the dedicated write tool).
    - ``family_*`` tools — every geometry/parameter mutator; only the
      read-state ``inspect_family`` is excluded.
    - ``execute_revit_code`` — a write iff its ``code`` contains a
      ``_WRITE_PATTERNS`` marker (same heuristic as the timeout estimator).
    """
    if tool_name in _ALWAYS_WRITE_TOOLS:
        return True
    if tool_name.startswith("family_") or tool_name in ("inspect_family",):
        return tool_name not in _FAMILY_READ_ONLY_TOOLS
    if tool_name == "execute_revit_code":
        code = (tool_args or {}).get("code", "") or ""
        return any(p in code for p in _WRITE_PATTERNS)
    return False


# Number of consecutive failures of the SAME tool before the loop stops the
# model retrying and injects a "do not retry" hint.
_CONSECUTIVE_ERROR_LIMIT = 3


def _bump_tool_error(counts: dict[str, int], tool_name: str) -> bool:
    """Record one failure of ``tool_name`` in the per-tool counter.

    Returns True iff this tool has now failed ``_CONSECUTIVE_ERROR_LIMIT`` times
    in a row — the caller should then inject the stop-retrying hint. When the
    threshold fires the counter for that tool is RESET to 0, so a subsequent
    failure shows the model the real error detail again instead of re-firing the
    truncated "failed 3 times" replacement every time (model-blinding bug).
    """
    counts[tool_name] = counts.get(tool_name, 0) + 1
    if counts[tool_name] >= _CONSECUTIVE_ERROR_LIMIT:
        counts[tool_name] = 0
        return True
    return False


def _reset_tool_error(counts: dict[str, int], tool_name: str) -> None:
    """Clear the consecutive-error streak for ``tool_name`` after it succeeds."""
    counts.pop(tool_name, None)


def _invalidate_dedup_after_write(seen_sigs: dict[str, int], keep_sig: Optional[str] = None) -> None:
    """Clear the convergence dedup signatures after a write-type tool succeeds.

    Without this, a legitimate re-query issued to VERIFY a write (the
    look→act→see loop) collides with the identical pre-write query signature and
    is wrongly suppressed as a duplicate. Writes change the world, so prior
    read signatures no longer describe a redundant call.

    ``keep_sig`` PRESERVES the write's own signature so an identical write
    repeated right after is still caught as a duplicate (Fable review — prevent
    double-write; clearing everything reopened the double-write hole).
    """
    kept = seen_sigs.get(keep_sig) if keep_sig is not None else None
    seen_sigs.clear()
    if keep_sig is not None and kept is not None:
        seen_sigs[keep_sig] = kept

# Patterns that indicate model-wide operations
_MODEL_WIDE_PATTERNS = [
    "doc.GetWarnings()", "GetAllElements",
    "PurgeUnused", "DeleteUnused",
    "doc.Regenerate()",
]

# Absolute max from config, default 360s
_MAX_EXECUTE_TIMEOUT_MS: int = 360_000


def _calculate_execute_timeout(
    code: str,
    estimated_elements: int | None = None,
    max_timeout_ms: int | None = None,
) -> int:
    """Estimate appropriate timeout based on code content and element count.

    Timeout tiers:
    - Simple read (count, get parameter): 30s
    - Write <100 elements: 60s
    - Write 100-1000 elements: 120s
    - Write 1000+ elements: 240s
    - Model-wide operations: 360s

    Returns timeout in milliseconds.
    """
    cap = max_timeout_ms or _MAX_EXECUTE_TIMEOUT_MS

    # Check for model-wide operations first
    for pattern in _MODEL_WIDE_PATTERNS:
        if pattern in code:
            return min(360_000, cap)

    is_write = any(p in code for p in _WRITE_PATTERNS)

    if not is_write:
        # Read-only operation
        return min(30_000, cap)

    # Write operation — scale by estimated elements
    if estimated_elements is not None:
        if estimated_elements > 1000:
            return min(240_000, cap)
        elif estimated_elements > 100:
            return min(120_000, cap)
        else:
            return min(60_000, cap)

    # No element estimate — infer from code heuristics
    # If code iterates over a collector without a limit, assume medium batch
    if "foreach" in code.lower() or "ForEach" in code or ".ToElements()" in code:
        return min(120_000, cap)

    # Default write
    return min(60_000, cap)


def _looks_like_unexecuted_csharp(text: str) -> bool:
    """True when the assistant's answer carries Revit C# code in a fenced block
    but no tool was called — i.e. the model WROTE code as chat text instead of
    calling execute_revit_code, so nothing runs in Revit (the prod
    "ничего не сделано" failure). Conservative: requires a fenced code block, so
    it won't fire on prose that merely mentions the API."""
    if not text:
        return False
    low = text.lower()
    if "```csharp" in low or "```c#" in low or "```cs\n" in low:
        return True
    if "```" in text and (
        "new transaction(" in low
        or "filteredelementcollector" in low
        or ".commit()" in low
    ):
        return True
    return False


def _smart_truncate(result_str: str, max_chars: int = 50_000) -> str:
    """Truncate tool results intelligently, preserving JSON structure."""
    if len(result_str) <= max_chars:
        return result_str

    try:
        data = json.loads(result_str)
        # If it's a dict with a list value, truncate the list
        if isinstance(data, dict):
            # Snapshot keys before iterating — we mutate `data` inside the loop
            # (adding _{key}_truncated/_total/_shown keys), which would otherwise
            # raise RuntimeError: dictionary changed size during iteration.
            for key, val in list(data.items()):
                if isinstance(val, list) and len(val) > 200:
                    total = len(val)
                    data[key] = val[:200]
                    data[f"_{key}_truncated"] = True
                    data[f"_{key}_total"] = total
                    data[f"_{key}_shown"] = 200
            truncated = json.dumps(data, ensure_ascii=False, default=str)
            if len(truncated) <= max_chars:
                return truncated
        # If it's a list directly
        elif isinstance(data, list) and len(data) > 200:
            total = len(data)
            truncated_data = data[:200]
            truncated_data.append({"_truncated": True, "_total": total, "_shown": 200})
            truncated = json.dumps(truncated_data, ensure_ascii=False, default=str)
            if len(truncated) <= max_chars:
                return truncated
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: wrap the truncated preview in a VALID JSON envelope so the tool
    # message stays parseable (audit H3). The preview is re-escaped by json.dumps,
    # so quote/backslash-heavy text can inflate the serialized size — shrink the
    # preview until the WHOLE envelope fits max_chars (Fable review: it could ~2x
    # the cap). shown_chars reports the ACTUAL preview length, not the budget.
    budget = max(0, max_chars - 500)  # headroom for the envelope scaffolding
    while True:
        preview = result_str[:budget]
        out = json.dumps({
            "error": False,
            "truncated": True,
            "total_chars": len(result_str),
            "shown_chars": len(preview),
            "note": ("Output too large; showing a prefix only. Ask the user to narrow "
                     "the query if the full data is needed."),
            "preview": preview,
        }, ensure_ascii=False)
        if len(out) <= max_chars or budget == 0:
            return out
        budget = int(budget * 0.8) if budget > 10 else 0


# Action intents that must PRODUCE a tool call rather than a narrated plan
# (audit H2 — root of "52% chats = 0 tool_calls"). diagnose/converse are
# excluded: diagnose gets a softer grounding directive and may legitimately
# be explanatory; converse answers directly.
# Must match the LLM classifier's 11-way enum (intent_classifier.py) — `list`
# and `export` are action intents too (Fable review: they were missing, so
# "выведи список …" / export turns weren't forced to call a tool).
_MUST_ACT_INTENTS = frozenset(
    {"create", "modify", "delete", "schedule", "tag", "filter", "count", "list", "export"}
)


def _tool_choice_for(intent: Optional[str], tool_round: int, should_use_tools: bool) -> str:
    """Force a tool call on the FIRST round of an action intent so the model
    cannot just narrate a plan; revert to 'auto' on later rounds so the model
    can synthesize the final answer once tools have run (never forces forever)."""
    if should_use_tools and tool_round == 0 and intent in _MUST_ACT_INTENTS:
        return "required"
    return "auto"


def _should_dedup(seen_count: int, sig_errored: bool) -> bool:
    """A repeated identical tool call is a redundant duplicate ONLY if it has
    already run this turn AND the prior identical call did NOT error. A prior
    error means this is a legitimate retry (transient bridge failure /
    compile-error repair) and must be allowed. Applies to ALL tools (Fable
    review): this both prevents a duplicate WRITE (the blanket exec exemption
    had removed that brake) and unblocks a genuine failed-call retry (H5)."""
    return seen_count >= 2 and not sig_errored
