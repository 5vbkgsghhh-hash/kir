"""ToolObservation — one record per tool execution, the single per-turn signal
source (Phase 4).

Replaces the three scattered structures in chat_ws (_turn_tool_names,
_turn_write_ok, _turn_lookup_norm_results): auto-show (B1), grounding (B2), the
change-witness, and golden-replay all derive from ONE list of observations via the
pure reducers below. Populated at exactly one site — the tool_end fold.

Byte-identity contract: the reducers reproduce the legacy signals EXACTLY, so
turn_observations can run in shadow (flag OFF) and be compared before cutover.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

# NAV-V2: dedicated file-producing tools whose parsed result is kept for
# nav_v2.harvest_nav_targets (file_path → panel status). NOT write tools.
_NAV_FILE_TOOLS = ("export_view", "generate_report", "edit_excel", "excel_script")


@dataclass
class ToolObservation:
    name: str                          # tool name
    ok: bool                           # result was NOT {error: true}
    is_write: bool                     # name in the write-tool set
    write_ok: bool                     # is_write AND ok  → B1 witnessed write success
    result: Any = None                 # lookup_norm: RAW result (→ B2); a write tool: the
                                        # PARSED result dict (→ NAV-V2 harvest, kukai.llm.nav_v2);
                                        # else None.
    changed: Optional[dict] = None     # {added, modified, deleted} manifest if present → witness
    seq: int = 0                       # order within the turn


def observe(
    name: str,
    raw_result: Any,
    parsed_result: Any,
    audit_result: str,
    write_tools: Iterable[str],
    seq: int,
) -> ToolObservation:
    """Build a ToolObservation from the values available at the tool_end fold.

    Byte-identity notes (verified against chat_ws):
      * ``raw_result`` is ``event.data.get("result")`` — the RAW tool result (dict
        OR json string). For lookup_norm we keep it verbatim, exactly as the legacy
        ``_turn_lookup_norm_results.append(event.data.get("result"))`` did, so the
        grounding gate sees the same payload (its lookup_norm_hit parses either).
      * ``parsed_result`` is the JSON-parsed dict (or None on non-JSON) — used only
        to read the LLM-facing change counts, which chat_ws attaches under the key
        ``"changed"`` (result.setdefault("changed", counts), chat_ws.py:1086), NOT
        ``"changes"`` (that is the raw bridge manifest, stashed separately).
      * ``ok`` mirrors the live ``_turn_write_ok`` guard (``audit_result ==
        "success"``) EXACTLY — equality on "success", not "!= error".

    NAV-V2 (2026-07-10) extension: a WRITE tool's PARSED result is now also kept
    (``parsed_result``, not ``raw_result`` — harvest needs to walk dict keys, not a
    JSON string) so kukai.llm.nav_v2.harvest_nav_targets can read it. This is a pure
    ADDITION — the two existing readers of ``.result`` (chat_ws's shadow-compare and
    tool_observation.grounding_messages) both gate strictly on
    ``name == "lookup_norm"``, so their output is byte-identical for every other
    tool name; only a NEW consumer (nav_v2) reads the write branch.
    """
    is_write = name in set(write_tools)
    ok = (audit_result == "success")
    if name == "lookup_norm":
        _result = raw_result
    elif is_write or name in _NAV_FILE_TOOLS:
        # _NAV_FILE_TOOLS (NAV-V2 completeness, 2026-07-10 Opus): dedicated
        # file-producing tools are NOT write tools (adding them to _WRITE_TOOLS
        # would shift the autoshow/wrote heuristics), but their file_path must
        # reach nav_v2.harvest_nav_targets — keep their parsed result too.
        _result = parsed_result
    else:
        _result = None
    return ToolObservation(
        name=name,
        ok=ok,
        is_write=is_write,
        write_ok=(is_write and ok),
        result=_result,
        changed=(parsed_result.get("changed") if isinstance(parsed_result, dict) else None),
        seq=seq,
    )


# ── pure reducers (each reproduces a legacy signal EXACTLY) ──────────────────

def wrote_any(obs: Iterable[ToolObservation]) -> bool:
    """Legacy: any(t in _WRITE_TOOLS for t in _turn_tool_names)."""
    return any(o.is_write for o in obs)


def write_ok_any(obs: Iterable[ToolObservation]) -> bool:
    """Legacy: _turn_write_ok."""
    return any(o.write_ok for o in obs)


def tool_names(obs: Iterable[ToolObservation]) -> list[str]:
    """Legacy: _turn_tool_names."""
    return [o.name for o in obs]


def grounding_messages(obs: Iterable[ToolObservation]) -> list[dict]:
    """Legacy: the _turn_msgs list built for the grounding gate — a name-only tool
    message, with ``_result`` attached for EVERY lookup_norm entry (even when the
    result is None), byte-identical to the aligned-iterator build in chat_ws."""
    out: list[dict] = []
    for o in obs:
        m: dict[str, Any] = {"role": "tool", "_tool_name": o.name}
        if o.name == "lookup_norm":
            m["_result"] = o.result
        out.append(m)
    return out


def change_manifests(obs: Iterable[ToolObservation]) -> list[dict]:
    """Change manifests from write tools that returned one (for the witness)."""
    return [o.changed for o in obs if o.changed]
