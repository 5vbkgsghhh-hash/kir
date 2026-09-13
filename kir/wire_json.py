"""Strict JSON encoding and bounded, explicitly incomplete failure diagnostics.

The caller supplies effect knowledge. Encoding never executes an operation,
interprets a native receipt, or turns malformed output into a normal result.
"""
from __future__ import annotations

import json
import math


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


def reject_constant(_value):
    raise ValueError("non-finite JSON constant")


def finite_float(text: str) -> float:
    """`parse_float` hook: finite syntax such as `1e400` must not parse into infinity."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def exception_name(error) -> str:
    """An encodable cause name without calling arbitrary exception formatting."""
    return type(error).__name__[:120].encode("utf-8", "backslashreplace").decode("utf-8")


def failure(value, *, known_effect: str, context=None) -> dict:
    """A diagnostic projection, never a replacement receipt or retry permission."""
    if known_effect not in {"none", "unknown", "committed"}:
        raise ValueError("effect knowledge must be supplied explicitly")
    remaining = [256, 8192]
    active = set()
    issues = []
    truncated = False

    def issue(path, reason):
        nonlocal truncated
        if len(issues) < 16:
            issues.append({"path": path[:256], "reason": reason})
        else:
            truncated = True

    def copy(item, path, depth):
        nonlocal truncated
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 16:
            truncated = True
            issue(path, "diagnostic_limit")
            return None
        if type(item) is int and item.bit_length() > 4096:
            truncated = True
            issue(path, "oversized_diagnostic_integer")
            return None
        if item is None or type(item) in (bool, int):
            return item
        if type(item) is float:
            if math.isfinite(item):
                return item
            issue(path, "non_finite_number")
            return None
        if type(item) is str:
            limit = min(2048, max(0, remaining[1]))
            shown = item[:limit]
            try:
                shown.encode("utf-8")
            except UnicodeError:
                issue(path, "invalid_unicode")
                return None
            remaining[1] -= min(len(item), limit)
            if len(item) > limit:
                truncated = True
                issue(path, "diagnostic_limit")
            return shown
        if type(item) not in (dict, list, tuple):
            issue(path, "unsupported_json_value")
            return None
        if id(item) in active:
            issue(path, "cyclic_value")
            return None
        active.add(id(item))
        try:
            result = {} if type(item) is dict else []
            rows = item.items() if type(item) is dict else enumerate(item)
            for key, child in rows:
                if remaining[0] <= 0:
                    truncated = True
                    issue(path, "diagnostic_limit")
                    break
                if type(item) is dict:
                    if type(key) is not str or len(key) > 128:
                        remaining[0] -= 1  # skipped entries still spend the visit budget
                        issue(path, "unsupported_diagnostic_key")
                        truncated = True
                        continue
                    try:
                        key.encode("utf-8")
                    except UnicodeError:
                        remaining[0] -= 1
                        issue(path, "invalid_unicode_key")
                        continue
                    result[key] = copy(child, path + "/" + key.replace("~", "~0").replace("/", "~1"), depth + 1)
                else:
                    result.append(copy(child, path + "/" + str(key), depth + 1))
            return result
        finally:
            active.remove(id(item))

    reported = copy(value, "", 0)
    return {"ok": False, "state": "response_schema_failure",
            "effect": known_effect, "retry_safe": False,
            "context": context or {}, "reported_result": reported,
            "reported_result_is_partial": True,
            "reported_result_truncated": truncated, "invalid_paths": issues}


def identity_context(value) -> dict:
    """Retain known correlation fields, not arbitrary objects or their repr()."""
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in ("operation_id", "request_id", "program_digest", "job_id", "task_id")
            if type(value.get(key)) is str and len(value[key]) <= 256
            and value[key].isascii()}
