"""Reasoning trace logger — captures Gemini's chain-of-thought + tool calls per turn.

Why this exists:
    Gemini's thinking/reasoning content streams to the UI as transient "thinking
    bubbles" but is never persisted. When a query fails (or barely succeeds),
    the model itself often narrates exactly what went wrong — sketch plane was
    invalid, family template rejected NewExtrusion, coordinate conversion was
    off, etc. Without persistence, that signal is lost the moment the chunk is
    forwarded to the WebSocket.

    User feedback (2026-05-22, live family-editor debug):
        "модель же сама говорит с чем она сталкивается когда что то делает.
         нам надо как то сделать так чтобы ризонинг сохранлся каждый раз в логи"

    This module solves that. Each turn is appended as a single JSONL row to
    `backend/data/reasoning_traces.jsonl` (path override: env
    `KUKAI_REASONING_TRACE_LOG_PATH`). Disabled by setting
    `KUKAI_REASONING_LOG_ENABLED=0`.

Schema (per row):
    {
      "ts":               ISO-8601 UTC timestamp at flush
      "session_id":       chat session id (truncated to 32 chars upstream)
      "device_id":        device installer-id (when present)
      "query":            user message text (raw, truncated to 4000 chars)
      "is_family_editor": bool — family-mode vs project-mode
      "revit_version":    "2025" / "2026" / ... when reported by bridge
      "thinking_mode":    bool — Pro 3.1 thinking vs Flash fast
      "reasoning":        concatenated reasoning_chunk content (full)
      "final_text":       concatenated stream_chunk content (response shown)
      "tool_calls":       [ { "name", "arguments", "result_preview",
                              "success" (bool), "duration_ms" } ]
      "errors":           [ {"type", "message"} ]
      "duration_ms":      wall-clock of the full turn
      "elapsed_until_first_chunk_ms": TTFT (first stream/reasoning chunk)
    }

The accumulator is created at the start of a turn (chat_ws.py), updated on
every relevant StreamEvent inside the per-turn loop, and flushed in the
turn's `finally` block. Best-effort: any flush error is logged and swallowed
— never breaks the user-facing chat.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("kukai.reasoning_logger")

# Lazy module-level lock — single writer process-wide so concurrent turns
# don't tear lines in the JSONL. Per-call overhead is negligible (in-memory
# buffer + one os.write).
_write_lock = asyncio.Lock()


def _resolve_log_path() -> Path:
    """Resolve the JSONL log path from env or fall back to backend/data/.

    backend/data/ exists in both dev and prod layouts.
    """
    override = os.environ.get("KUKAI_REASONING_TRACE_LOG_PATH", "").strip()
    if override:
        return Path(override)
    # repo_root/backend/data/reasoning_traces.jsonl
    # this file lives at backend/kukai/llm/reasoning_logger.py
    here = Path(__file__).resolve()
    backend_root = here.parent.parent.parent  # kukai/llm/ → kukai/ → backend/
    return backend_root / "data" / "reasoning_traces.jsonl"


def is_enabled() -> bool:
    """Trace logging is on by default; opt-out via KUKAI_REASONING_LOG_ENABLED=0."""
    return os.environ.get("KUKAI_REASONING_LOG_ENABLED", "1").strip() not in ("0", "false", "no", "off")


@dataclass
class _PendingTool:
    name: str
    started_at: float
    arguments: str = ""


@dataclass
class ReasoningTrace:
    """Per-turn accumulator. One instance lives for the duration of one user
    query → assistant-response cycle (including all tool rounds).
    """

    session_id: str
    device_id: str = ""
    query: str = ""
    is_family_editor: bool = False
    revit_version: str = ""
    thinking_mode: bool = False
    started_at: float = field(default_factory=time.monotonic)
    first_chunk_at: Optional[float] = None
    reasoning_parts: list[str] = field(default_factory=list)
    final_text_parts: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    # Step 8 (KUKAI_TRUTH_GATE): fake-готово detection rows for THIS turn,
    # appended by chat_ws from the internal "truth_gate" StreamEvent. Empty
    # (the default) on every turn while the flag is OFF → to_row() emits no
    # new key and existing rows/readers are byte-identical.
    truth_gate: list[dict[str, Any]] = field(default_factory=list)
    _pending_tool: Optional[_PendingTool] = None

    # --- event hooks (called from chat_ws.py inside the stream loop) ---

    def on_reasoning_chunk(self, text: str) -> None:
        if not text:
            return
        if self.first_chunk_at is None:
            self.first_chunk_at = time.monotonic()
        self.reasoning_parts.append(text)

    def on_stream_chunk(self, text: str) -> None:
        if not text:
            return
        if self.first_chunk_at is None:
            self.first_chunk_at = time.monotonic()
        self.final_text_parts.append(text)

    def on_tool_start(self, tool_name: str, arguments: str = "") -> None:
        # Close any leftover pending tool (defensive — shouldn't normally happen,
        # but if tool_end was missed for any reason we don't want to lose it).
        if self._pending_tool is not None:
            self._finalize_tool(result_str="", success=False)
        self._pending_tool = _PendingTool(name=tool_name, started_at=time.monotonic(), arguments=arguments)

    def on_tool_end(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            payload = {}
        tool_name = payload.get("tool", "")
        result_str = payload.get("result", "")
        if not isinstance(result_str, str):
            try:
                result_str = json.dumps(result_str, ensure_ascii=False, default=str)
            except Exception:
                result_str = str(result_str)
        arguments = payload.get("arguments", "") or ""
        if self._pending_tool is None or (tool_name and self._pending_tool.name != tool_name):
            # Mismatched / unstarted — create a minimal record so we still log it.
            self._pending_tool = _PendingTool(name=tool_name or "(unknown)", started_at=time.monotonic(), arguments=arguments)
        else:
            # Prefer the args we got in tool_end (chat_ws sometimes sends them
            # only there — see chat_ws.py:1353).
            if arguments and not self._pending_tool.arguments:
                self._pending_tool.arguments = arguments

        success = True
        try:
            parsed = json.loads(result_str) if result_str else None
            if isinstance(parsed, dict) and parsed.get("error") is True:
                success = False
        except (json.JSONDecodeError, TypeError):
            pass

        self._finalize_tool(result_str=result_str, success=success)

    def on_error(self, payload: Any) -> None:
        if isinstance(payload, dict):
            msg = payload.get("error") or payload.get("message") or json.dumps(payload, ensure_ascii=False, default=str)
            etype = payload.get("type", "error")
        else:
            msg = str(payload)
            etype = "error"
        self.errors.append({"type": etype, "message": str(msg)[:1000]})

    # --- internals ---

    def _finalize_tool(self, result_str: str, success: bool) -> None:
        pt = self._pending_tool
        if pt is None:
            return
        duration_ms = int((time.monotonic() - pt.started_at) * 1000)
        # Cap result preview so logs stay small. Full tool results are already
        # in audit/DB.
        preview = result_str[:1500]
        # If args are JSON, keep them as-is; otherwise stringify safely.
        args_preview = pt.arguments
        if isinstance(args_preview, str) and len(args_preview) > 2000:
            args_preview = args_preview[:2000] + "...[truncated]"
        self.tool_calls.append(
            {
                "name": pt.name,
                "arguments": args_preview,
                "result_preview": preview,
                "success": success,
                "duration_ms": duration_ms,
            }
        )
        self._pending_tool = None

    # --- serialization ---

    def to_row(self) -> dict[str, Any]:
        # Close any tool left dangling (e.g. cancelled mid-execution).
        if self._pending_tool is not None:
            self._finalize_tool(result_str="", success=False)

        now = time.monotonic()
        duration_ms = int((now - self.started_at) * 1000)
        ttft_ms: Optional[int] = None
        if self.first_chunk_at is not None:
            ttft_ms = int((self.first_chunk_at - self.started_at) * 1000)

        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "device_id": self.device_id,
            "query": (self.query or "")[:4000],
            "is_family_editor": self.is_family_editor,
            "revit_version": self.revit_version,
            "thinking_mode": self.thinking_mode,
            "reasoning": "".join(self.reasoning_parts),
            "final_text": "".join(self.final_text_parts),
            "tool_calls": self.tool_calls,
            "errors": self.errors,
            "duration_ms": duration_ms,
            "elapsed_until_first_chunk_ms": ttft_ms,
        }
        # Step 8: only present when the truth gate actually fired this turn —
        # flag OFF (or no detection) keeps the row schema exactly as before.
        if self.truth_gate:
            row["truth_gate"] = self.truth_gate
        return row


async def flush_trace(trace: ReasoningTrace) -> None:
    """Append one trace row to the JSONL log. Best-effort — never raises."""
    if not is_enabled():
        return
    row = trace.to_row()
    # Skip totally empty rows (no query, no reasoning, no text, no tools) —
    # these come from shortcuts / cancelled turns and just pollute the log.
    if not row["query"] and not row["reasoning"] and not row["final_text"] and not row["tool_calls"] and not row["errors"]:
        return

    path = _resolve_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("reasoning_logger: mkdir failed: %s", e)
        return

    line = json.dumps(row, ensure_ascii=False, default=str)

    def _append() -> None:
        # Open in append mode — atomic append is guaranteed by POSIX for writes
        # under PIPE_BUF; for Windows we rely on the in-process asyncio lock.
        with open(path, "a", encoding="utf-8", newline="") as f:
            f.write(line)
            f.write("\n")

    async with _write_lock:
        try:
            await asyncio.to_thread(_append)
        except Exception as e:  # noqa: BLE001
            logger.warning("reasoning_logger: append failed (%s): %s", path, e)
