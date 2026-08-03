"""Deterministic "show what was found" — reveal (KUKAI_REVEAL_FOUND).

Product insight (operator, 2026-07-08): highlighting found elements must NOT hang
on the LLM deciding to call show_elements. After ANY find (query_model), the
system deterministically selects + frames the results in the viewport, so the user
always sees something happen — and the model has one fewer tool to juggle (which
directly helps tool-selection quality, the whole point of guidance-v2).

This module is the PURE, testable core. Two thin wiring sites live in chat_ws:
  1. capture — at the tool_end fold, pull found ids out of read results;
  2. act    — in the post-turn present block, select + frame (or, in shadow, just
     record the fire decision so we can size the effect before enabling).

Flag: KUKAI_REVEAL_FOUND = "0"/off (default) | "shadow" (measure, no action) |
"1"/on. Default OFF ⇒ every path below is skipped ⇒ byte-identical legacy turn.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

# The model already showed the elements itself — don't double-act / fight its choice.
_EXPLICIT_SHOW = ("show_elements", "select_elements", "highlight_elements")


def reveal_mode() -> str:
    v = (os.environ.get("KUKAI_REVEAL_FOUND", "0") or "0").strip().lower()
    if v in ("1", "on", "enforce", "true"):
        return "on"
    if v == "shadow":
        return "shadow"
    return "off"


def reveal_cap() -> int:
    """Max found elements to auto-select — selecting thousands is noisy/heavy, so
    a big find just reports its count and skips the reveal."""
    try:
        return max(1, int(os.environ.get("KUKAI_REVEAL_CAP", "500")))
    except (ValueError, TypeError):
        return 500


def extract_found_ids(parsed: Any, cap: int = 5000) -> list[str]:
    """Recursively collect element ids from any ``"ids"`` list in a parsed tool
    result. Handles the flat query_model shape ({"ids":[...], "count":N}) and the
    v2 wrapper ({"results": {cat: {"ids":[...]}}}). Deduped, order-preserving,
    hard-capped so a pathological result can't blow memory. Returns string ids;
    summary/count results (no "ids") yield []."""
    out: list[str] = []
    seen: set[str] = set()

    def _walk(node: Any) -> None:
        if len(out) >= cap:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "ids" and isinstance(v, list):
                    for x in v:
                        if isinstance(x, bool):
                            continue
                        if isinstance(x, (str, int)):
                            s = str(x).strip()
                            if s and s not in seen:
                                seen.add(s)
                                out.append(s)
                                if len(out) >= cap:
                                    return
                else:
                    _walk(v)
        elif isinstance(node, list):
            for x in node:
                _walk(x)

    _walk(parsed)
    return out


def should_reveal(found_ids: Any, write_ok: bool, tool_names: Iterable[str], cap: int) -> bool:
    """Pure gate. Reveal fires when a find returned a manageable set (1..cap) AND
    the turn was a READ (no successful write — writes drive the separate auto-show)
    AND the model did not already explicitly show/select the elements itself."""
    n = len(found_ids)
    if n == 0 or n > cap:
        return False
    if write_ok:
        return False
    if any(t in _EXPLICIT_SHOW for t in tool_names):
        return False
    return True


def build_reveal_code(found_ids: Iterable[Any]) -> str:
    """Version-safe select + frame C#. Mirrors kukai/write/operations.py's proven
    ``new ElementId(id)`` (int) construction — the codebase's accepted cross-version
    pattern — then SetElementIds + ShowElements. Runs fire-and-forget on the bridge;
    every step is try/catch so a stale id never breaks the turn."""
    ints: list[int] = []
    for s in found_ids:
        try:
            ints.append(int(str(s)))
        except (ValueError, TypeError):
            continue
    arr = ",".join(str(i) for i in ints)
    return (
        "var __ids=new List<ElementId>();"
        f"foreach(var __n in new int[]{{{arr}}}){{ try{{ __ids.Add(new ElementId(__n)); }}catch{{}} }}"
        "if(__ids.Count>0){ try{ uidoc.Selection.SetElementIds(__ids); }catch{}"
        " try{ uidoc.ShowElements(__ids); }catch{} }"
        "return new { revealed = __ids.Count };"
    )
