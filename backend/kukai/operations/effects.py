"""Typed execution effects for the Revit bridge.

Arbitrary C# is deliberately classified as ``WRITE_OR_UNKNOWN``.  A request
may bypass the durable write journal only when trusted in-process code attaches
the private read capability below.  The capability is an object identity, not
a JSON value, so a tool argument, prompt, or remote caller cannot forge it.

The lexical guard is defence in depth for trusted callers: it catches a
collector/probe that accidentally grows an obvious mutation.  It is not used
to infer that arbitrary code is safe.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Mapping


class ExecutionEffect(str, Enum):
    """Effect class understood by the bridge transport."""

    READ_ONLY = "read_only"
    WRITE_OR_UNKNOWN = "write_or_unknown"


class ReadOnlySource(str, Enum):
    """Closed set of internal components allowed to request read execution."""

    MODEL_CENSUS = "model_census"
    EVALUATOR_PROBE = "evaluator_probe"


class ReadOnlyContractViolation(ValueError):
    """A read capability was forged, malformed, or attached to mutating code."""


_CAPABILITY_KEY = "_kukai_read_capability"
_SOURCE_KEY = "_kukai_read_source"
_READ_CAPABILITY = object()

# These patterns intentionally target obvious model/UI/filesystem effects.
# The authority is the unforgeable in-process capability; this list prevents
# accidental contract drift in the small trusted collectors that hold it.
_MUTATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Revit transaction", re.compile(
        r"\b(?:SubTransaction|TransactionGroup|Transaction)\s*(?:<|\()",
        re.IGNORECASE,
    )),
    ("document create API", re.compile(
        r"\b(?:doc|document)\s*\.\s*Create\b|\bFamilyCreate\b",
        re.IGNORECASE,
    )),
    ("document delete API", re.compile(
        r"\b(?:doc|document)\s*\.\s*Delete\s*\(",
        re.IGNORECASE,
    )),
    ("parameter/property mutation", re.compile(
        r"\.\s*(?:Set|SetValueString|ChangeTypeId)\s*\(",
        re.IGNORECASE,
    )),
    ("element transform", re.compile(
        r"\bElementTransformUtils\s*\.\s*"
        r"(?:Move|Rotate|Mirror|Copy|Transform)\w*\s*\(",
        re.IGNORECASE,
    )),
    ("selection mutation", re.compile(
        r"\.\s*Selection\s*\.\s*SetElementIds\s*\(",
        re.IGNORECASE,
    )),
    ("document persistence/export", re.compile(
        r"\b(?:doc|document)\s*\.\s*(?:Save|SaveAs|Export)\s*\(",
        re.IGNORECASE,
    )),
    ("filesystem/process/network API", re.compile(
        r"\b(?:System\s*\.\s*IO|File|Directory|Process|HttpClient|WebRequest|Socket)"
        r"\s*\.",
        re.IGNORECASE,
    )),
)


def _without_comments_and_literals(code: str) -> str:
    """Blank comments and literals while preserving token boundaries.

    This is deliberately a small lexer, not a C# parser.  It prevents a status
    string such as ``"Transaction count"`` from tripping the drift guard.
    """

    result: list[str] = []
    index = 0
    length = len(code)
    state = "code"

    while index < length:
        char = code[index]
        nxt = code[index + 1] if index + 1 < length else ""

        if state == "code":
            if char == "/" and nxt == "/":
                result.extend((" ", " "))
                index += 2
                state = "line_comment"
                continue
            if char == "/" and nxt == "*":
                result.extend((" ", " "))
                index += 2
                state = "block_comment"
                continue
            if char == "@" and nxt == '"':
                result.extend((" ", " "))
                index += 2
                state = "verbatim_string"
                continue
            if char == '"':
                result.append(" ")
                index += 1
                state = "string"
                continue
            if char == "'":
                result.append(" ")
                index += 1
                state = "char"
                continue
            result.append(char)
            index += 1
            continue

        if state == "line_comment":
            if char in "\r\n":
                result.append(char)
                state = "code"
            else:
                result.append(" ")
            index += 1
            continue

        if state == "block_comment":
            if char == "*" and nxt == "/":
                result.extend((" ", " "))
                index += 2
                state = "code"
            else:
                result.append(char if char in "\r\n" else " ")
                index += 1
            continue

        if state == "verbatim_string":
            if char == '"' and nxt == '"':
                result.extend((" ", " "))
                index += 2
            elif char == '"':
                result.append(" ")
                index += 1
                state = "code"
            else:
                result.append(char if char in "\r\n" else " ")
                index += 1
            continue

        # Normal string or character literal.
        if char == "\\" and nxt:
            result.extend((" ", " "))
            index += 2
        elif (state == "string" and char == '"') or (
            state == "char" and char == "'"
        ):
            result.append(" ")
            index += 1
            state = "code"
        else:
            result.append(char if char in "\r\n" else " ")
            index += 1

    return "".join(result)


def assert_read_only_code(code: Any) -> None:
    """Fail closed when a trusted read capsule contains an obvious effect."""

    if not isinstance(code, str) or not code.strip():
        raise ReadOnlyContractViolation("read-only execution requires non-empty C#")
    tokens = _without_comments_and_literals(code)
    for label, pattern in _MUTATION_PATTERNS:
        if pattern.search(tokens):
            raise ReadOnlyContractViolation(
                f"read-only execution contains {label}"
            )


def mark_read_only(
    params: Mapping[str, Any],
    source: ReadOnlySource,
) -> dict[str, Any]:
    """Attach an in-process read capability after validating the code body."""

    if not isinstance(source, ReadOnlySource):
        raise ReadOnlyContractViolation("read-only source must be typed")
    marked = dict(params or {})
    if "_operation" in marked:
        raise ReadOnlyContractViolation(
            "read-only execution cannot carry a write operation identity"
        )
    assert_read_only_code(marked.get("code"))
    marked[_CAPABILITY_KEY] = _READ_CAPABILITY
    marked[_SOURCE_KEY] = source
    return marked


def is_authorized_read_only(params: Mapping[str, Any]) -> bool:
    """Return True only for a valid in-process capability; reject forgeries."""

    if _CAPABILITY_KEY not in params and _SOURCE_KEY not in params:
        return False
    if params.get(_CAPABILITY_KEY) is not _READ_CAPABILITY:
        raise ReadOnlyContractViolation("invalid read-only capability")
    source = params.get(_SOURCE_KEY)
    if not isinstance(source, ReadOnlySource):
        raise ReadOnlyContractViolation("invalid read-only source")
    assert_read_only_code(params.get("code"))
    return True


def consume_execution_effect(
    method: str,
    params: Mapping[str, Any],
) -> tuple[dict[str, Any], ExecutionEffect, str | None]:
    """Strip internal capability metadata and return the declared effect."""

    clean = dict(params or {})
    authorized_read = is_authorized_read_only(clean)
    clean.pop(_CAPABILITY_KEY, None)
    source = clean.pop(_SOURCE_KEY, None)

    if not authorized_read:
        return clean, ExecutionEffect.WRITE_OR_UNKNOWN, None
    if method != "execute":
        raise ReadOnlyContractViolation(
            "read-only capability is valid only for execute"
        )
    return clean, ExecutionEffect.READ_ONLY, source.value
