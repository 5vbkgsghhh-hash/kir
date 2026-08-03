"""Unit tests for WriteBridgeAdapter — the B-1 wrapper that bridges the framework's
__result__ convention to the live exec channel's return-dict contract."""
import pytest

from kukai.modeling.bridge.write_bridge_adapter import (
    WriteBridgeAdapter,
    WrappingCompileClient,
    with_result_epilogue,
)


def test_epilogue_declares_and_returns():
    wrapped = with_result_epilogue("__result__.Add(col.Id);")
    assert "var __result__ = new List<ElementId>();" in wrapped  # prologue declares (version-safe)
    assert "__result__.Add(col.Id);" in wrapped                 # body preserved
    assert 'return __out;' in wrapped                            # epilogue returns
    assert '__out["element_ids"]' in wrapped


def _capturing_exec(result):
    box = {}
    async def fn(code: str, timeout_ms: int):
        box["code"] = code
        box["timeout_ms"] = timeout_ms
        return result
    return fn, box


@pytest.mark.asyncio
async def test_execute_wraps_and_parses_ids():
    fn, box = _capturing_exec({"success": True, "element_ids": ["100", "101"], "error": None, "duration_ms": 12})
    adapter = WriteBridgeAdapter(fn)
    out = await adapter.execute_code(session_id="dev", csharp_code="__result__ = new int[]{100,101};", expected_count=2)
    assert out["success"] is True
    assert out["element_ids"] == [100, 101]          # strings -> ints
    assert out["duration_ms"] == 12
    assert "return __out;" in box["code"]            # epilogue applied before exec
    assert len(adapter.calls) == 1                   # budget-guard contract


@pytest.mark.asyncio
async def test_execute_empty_ids_is_failure():
    fn, _ = _capturing_exec({"success": True, "element_ids": [], "error": None})
    out = await WriteBridgeAdapter(fn).execute_code(session_id="dev", csharp_code="// nothing", expected_count=1)
    assert out["success"] is False                   # no ids => fail-closed (L5 count would also fail)
    assert out["element_ids"] == []


@pytest.mark.asyncio
async def test_execute_bridge_error():
    fn, _ = _capturing_exec({"error": True, "message": "device offline"})
    out = await WriteBridgeAdapter(fn).execute_code(session_id="dev", csharp_code="x", expected_count=1)
    assert out["success"] is False
    assert "device offline" in out["error"]


@pytest.mark.asyncio
async def test_wrapping_compile_client_wraps_same_code():
    class _FakeCompile:
        def __init__(self):
            self.calls = []
            self.seen = None
        async def compile(self, code, revit_version="2026"):
            self.seen = code
            self.calls.append({"revit": revit_version})
            return {"success": True, "errors": []}
        async def health(self):
            return True

    inner = _FakeCompile()
    wc = WrappingCompileClient(inner)
    await wc.compile("__result__.Add(col.Id);", "2026")
    assert "var __result__ = new List<ElementId>();" in inner.seen   # same prologue as execute path
    assert "namespace Kukai" in inner.seen                            # canonical exec wrapper applied
    assert "public static object Execute(Document doc, UIDocument uidoc)" in inner.seen
    assert "return __out;" in inner.seen
    assert wc.calls is inner.calls                          # budget delegation
