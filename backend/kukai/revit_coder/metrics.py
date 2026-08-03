"""Telemetry for revit-coder pilot.

Two append-only JSONL streams:
  - coder_metrics.jsonl: every tool-call (success or fail)
  - coder_failures.jsonl: failed calls only with full attempts

Used to inform Phase 1 → Phase 2 gate decision.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import kukai.config as _config

logger = logging.getLogger(__name__)


def _append_jsonl(path_str: str, record: dict[str, Any]) -> None:
    """Append one JSON record to file (creates parents if needed). Never raises."""
    record["ts"] = datetime.now(timezone.utc).isoformat()
    try:
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("Failed to write metrics to %s: %s", path_str, e)


def log_call(
    *,
    task_preview: str,
    code_length: int,
    compile_success_first_try: bool,
    retries: int,
    latency_codegen_ms: int,
    latency_compile_ms: int,
    latency_execute_ms: int,
    exec_success: bool,
    extra: Optional[dict] = None,
) -> None:
    """Log one execute_revit_code call (revit-coder path)."""
    record: dict[str, Any] = {
        "task_preview": task_preview[:200],
        "code_length": code_length,
        "compile_success_first_try": compile_success_first_try,
        "retries": retries,
        "latency_codegen_ms": latency_codegen_ms,
        "latency_compile_ms": latency_compile_ms,
        "latency_execute_ms": latency_execute_ms,
        "exec_success": exec_success,
    }
    if extra:
        record.update(extra)
    _append_jsonl(_config.METRICS_LOG_PATH, record)


def log_failure(*, task: str, attempts: list[dict[str, Any]]) -> None:
    """Log a fully-failed call with all retry attempts.

    `attempts` example:
        [{"code": "var x = 1;", "error": "CS1002 ..."},
         {"code": "var x = 2;", "error": "CS0103 ..."}]
    """
    record = {
        "task": task,
        "attempts": attempts,
        "attempts_count": len(attempts),
    }
    _append_jsonl(_config.FAILURES_LOG_PATH, record)
