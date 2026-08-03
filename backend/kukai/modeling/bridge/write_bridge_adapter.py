"""WriteBridgeAdapter — adapt the live exec channel to the framework's ExecuteGate
bridge contract, and deterministically bridge the wrapper mismatch.

The framework's persona makes the LLM set ``__result__`` to an int[] of created
element ids (the framework's own wrapper convention). The LIVE exec wrapper has no
``__result__`` and surfaces the C# ``return`` value instead. So (critic B-1) we do
NOT ask the LLM to hand-roll the return dict — we wrap its code deterministically:

  * PROLOGUE declares ``int[] __result__`` so the proposal's ``__result__ = …``
    assignment compiles against the live wrapper;
  * EPILOGUE converts ``__result__`` into the ``{success, element_ids, error}`` dict
    the bridge surfaces and ExecuteGate expects.

The SAME wrapping is applied to the code that is COMPILED and the code that is
EXECUTED (critic M-1) — see WrappingCompileClient — so L3 validates exactly what
L4 runs.
"""
from __future__ import annotations
from typing import Any, Awaitable, Callable

from kukai.modeling.bridge.exec_wrapper import wrap_execute

ExecFn = Callable[[str, int], Awaitable[Any]]

# Declared at the top so the proposal's `__result__.Add(<el>.Id)` calls are valid
# against the live wrapper (which does not pre-declare __result__).
#
# CONTRACT: __result__ is a List<ElementId> — the proposal/template appends each
# created element's `.Id` (an ElementId), NEVER an int. This is version-safe:
# Revit 2024+ element ids are 64-bit and `ElementId.IntegerValue` no longer
# exists (only `.Value`, a long that does not fit an int[]). Collecting the
# ElementId itself and stringifying it in the epilogue sidesteps the whole
# int-vs-long / IntegerValue-vs-Value version trap (memory: ids travel as
# Id.ToString() strings, never .IntegerValue/.Value).
RESULT_PROLOGUE = "var __result__ = new List<ElementId>();\n"

# Converts __result__ (filled by the proposal) into the bridge result dict.
# ElementId.ToString() yields the numeric id as a string in every Revit version;
# the Python side parses it back to an int (Python ints are unbounded, so 64-bit
# ids survive).
RESULT_EPILOGUE = """
var __out = new Dictionary<string,object>();
var __ids = new List<object>();
try { if (__result__ != null) foreach (var __i in __result__) { if (__i != null) __ids.Add(__i.ToString()); } } catch {}
__out["success"] = true;
__out["element_ids"] = __ids;
__out["error"] = null;
return __out;
"""


def with_result_epilogue(csharp_code: str) -> str:
    """Wrap proposal C# so __result__ is declared (prologue) and returned as the
    bridge result dict (epilogue). MUST be applied identically before compile and
    before execute."""
    return RESULT_PROLOGUE + csharp_code.rstrip() + "\n" + RESULT_EPILOGUE


class WriteBridgeAdapter:
    """bridge_client for ExecuteGate, over the live exec channel."""

    def __init__(self, exec_fn: ExecFn, *, timeout_ms: int = 30000) -> None:
        self._exec = exec_fn
        self._timeout_ms = timeout_ms
        self.calls: list[dict[str, Any]] = []  # Wave 6B budget-guard contract

    async def execute_code(self, *, session_id: str, csharp_code: str, expected_count: int = 1) -> dict[str, Any]:
        self.calls.append({"method": "execute_code", "session_id": session_id})
        res = await self._exec(with_result_epilogue(csharp_code), self._timeout_ms)
        if not isinstance(res, dict) or res.get("error"):
            msg = res.get("message") if isinstance(res, dict) else "unexpected result shape"
            return {"success": False, "element_ids": [], "error": str(msg or "bridge error"), "duration_ms": 0}
        eids: list[int] = []
        for x in (res.get("element_ids") or []):
            try:
                eids.append(int(x))
            except (ValueError, TypeError):
                continue
        return {
            "success": bool(res.get("success", True)) and bool(eids),
            "element_ids": eids,
            "error": res.get("error"),
            "duration_ms": int(res.get("duration_ms", 0) or 0),
        }


class WrappingCompileClient:
    """Wraps a CompileClient so it compiles EXACTLY what ExecuteGate runs (critic
    M-1: L3 must validate exactly what L4 runs).

    The live exec path is two layers of wrapping:
      1. WriteBridgeAdapter applies ``with_result_epilogue`` (declare __result__,
         build the {success, element_ids, error} return dict);
      2. the backend ``_bridge_callback`` then wraps THAT method body into the
         canonical ``Kukai.UserCode.Execute(Document, UIDocument)`` class
         (HEADER/FOOTER) before the bridge compiles+runs it.

    The standalone compile-service does no wrapping, so here we reproduce BOTH
    layers — ``wrap_execute(with_result_epilogue(code))`` — so the compile gate
    sees byte-for-byte what the live bridge executes."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def calls(self) -> list[dict[str, Any]]:
        return getattr(self._inner, "calls", [])

    async def compile(self, csharp_code: str, revit_version: str = "2026"):
        return await self._inner.compile(wrap_execute(with_result_epilogue(csharp_code)), revit_version)

    async def health(self) -> bool:
        return await self._inner.health()
