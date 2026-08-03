"""Excel script executor — Gemini writes openpyxl code, backend runs it on full file.

Security: AST-based validation blocks dangerous operations (file I/O, network, eval).
Gemini sees only first ~20 rows for context, but the script operates on ALL data.
"""

from __future__ import annotations

import ast
import io
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# --- Allowed imports for scripts ---
ALLOWED_MODULES = frozenset({
    "openpyxl", "openpyxl.styles", "openpyxl.utils", "openpyxl.formatting",
    "openpyxl.formatting.rule", "openpyxl.chart", "openpyxl.chart.series",
    "openpyxl.chart.label", "openpyxl.chart.reference", "openpyxl.worksheet",
    "openpyxl.worksheet.datavalidation",
    "math", "datetime", "decimal", "enum", "re", "collections",
})

# Top-level module names (for prefix matching: "openpyxl.foo" -> "openpyxl")
ALLOWED_TOP_MODULES = frozenset({m.split(".")[0] for m in ALLOWED_MODULES})

# Blocked builtins
BLOCKED_BUILTINS = frozenset({
    "eval", "compile", "__import__", "open",
    "input", "globals", "locals", "breakpoint", "exit", "quit",
    "getattr", "setattr", "delattr",
})

# Blocked attribute names (on any object)
BLOCKED_ATTRS = frozenset({
    "system", "popen", "remove", "rmdir", "unlink",
    "makedirs", "rename",
    "__subclasses__", "__bases__", "__code__", "__globals__",
})

# Max script execution time (seconds)
SCRIPT_TIMEOUT = 30


def validate_script(code: str) -> str | None:
    """Validate openpyxl script for safety via AST analysis.

    Returns error message if validation fails, None if safe.
    """
    if not code or not code.strip():
        return "Empty script"

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Syntax error: {e}"

    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in ALLOWED_TOP_MODULES:
                    return f"Import '{alias.name}' blocked. Allowed: openpyxl, math, datetime, decimal, re, collections"

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top not in ALLOWED_TOP_MODULES:
                    return f"Import from '{node.module}' blocked"

        # Check function calls
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in BLOCKED_BUILTINS:
                    return f"Function '{node.func.id}()' blocked"

            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in BLOCKED_ATTRS:
                    return f"Method '.{node.func.attr}()' blocked"

        # Check attribute access (non-call)
        elif isinstance(node, ast.Attribute):
            if node.attr in BLOCKED_ATTRS:
                return f"Access to '.{node.attr}' blocked"

    return None  # Passed


def run_excel_script(
    excel_bytes: bytes,
    code: str,
    timeout: int = SCRIPT_TIMEOUT,
) -> tuple[bytes, str]:
    """Run openpyxl script on Excel workbook in a restricted namespace.

    Args:
        excel_bytes: Source .xlsx file bytes
        code: Python script (gets `wb` injected as openpyxl Workbook)
        timeout: Max execution time in seconds

    Returns:
        (modified_xlsx_bytes, log_output)

    Raises:
        ValueError: If script validation fails
        RuntimeError: If execution fails or times out
    """
    # Validate first
    error = validate_script(code)
    if error:
        raise ValueError(error)

    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))

    # Build restricted namespace
    log_lines: list[str] = []

    import math
    import datetime
    import decimal

    # Restricted __import__ — only allows whitelisted modules
    # Required because `from openpyxl.styles import Font` calls __import__ internally
    _real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _safe_import(name, *args, **kwargs):
        top = name.split(".")[0]
        if top not in ALLOWED_TOP_MODULES:
            raise ImportError(f"Import '{name}' not allowed in excel_script")
        return _real_import(name, *args, **kwargs)

    safe_builtins = {
        "True": True, "False": False, "None": None,
        "int": int, "float": float, "str": str, "bool": bool,
        "list": list, "dict": dict, "tuple": tuple, "set": set,
        "frozenset": frozenset,
        "len": len, "range": range, "enumerate": enumerate,
        "zip": zip, "map": map, "filter": filter,
        "sorted": sorted, "reversed": reversed,
        "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
        "isinstance": isinstance, "type": type,
        "print": lambda *args, **kw: log_lines.append(" ".join(str(a) for a in args)),
        "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError,
        "RuntimeError": RuntimeError, "Exception": Exception,
        "__import__": _safe_import,
        "__name__": "<excel_script>",
    }

    safe_globals: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "wb": wb,
        "openpyxl": openpyxl,
        "math": math,
        "datetime": datetime,
        "decimal": decimal,
    }

    # Run in thread with timeout
    result_container: dict[str, Any] = {"error": None}

    def _run_sandboxed():
        try:
            compiled = compile(code, "<excel_script>", "exec")
            # Sandboxed execution: restricted __builtins__, no file/network access
            _sandbox_exec(compiled, safe_globals)
        except Exception as e:
            result_container["error"] = e

    thread = threading.Thread(target=_run_sandboxed, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        raise RuntimeError(f"Script timeout ({timeout}s)")

    if result_container["error"] is not None:
        raise RuntimeError(f"Script error: {result_container['error']}")

    # Save modified workbook
    output = io.BytesIO()
    wb.save(output)

    log_output = "\n".join(log_lines) if log_lines else ""
    logger.info("Excel script OK: %d bytes, %d log lines", len(output.getvalue()), len(log_lines))

    return output.getvalue(), log_output


def _sandbox_exec(compiled_code, namespace):
    """Execute pre-compiled code in the given namespace.

    This is a thin wrapper to make the sandboxed execution explicit
    and separately testable. The namespace must have restricted __builtins__.

    Uses single dict for globals+locals so variable assignments are visible
    to subsequent lines (exec with separate dicts has scoping issues).
    """
    # The compiled_code was already validated by validate_script() (AST check)
    # and the namespace has restricted __builtins__ (no open, eval, etc.)
    exec(compiled_code, namespace)  # noqa: S102
