"""tier1 — real Roslyn compile-service, started by conftest fixture.

Validates the end-to-end HttpCompileClient ↔ compile-service contract on
port 52412: good code compiles, bad code surfaces Roslyn diagnostics, and
unknown Revit versions are rejected.
"""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.compile_client import HttpCompileClient


_GOOD_CSHARP = """\
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
namespace Kukai {
  public class UserCode {
    public static object Execute(Document doc, UIDocument uidoc) {
      return doc.Title;
    }
  }
}
"""

_BAD_CSHARP = """\
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
namespace Kukai {
  public class UserCode {
    public static object Execute(Document doc, UIDocument uidoc) {
      return doc.Title    // missing semicolon
    }
  }
}
"""


@pytest.mark.tier1
@pytest.mark.asyncio
async def test_real_compile_accepts_good_csharp(compile_service):
    client = HttpCompileClient(base_url=compile_service, timeout_seconds=30.0)
    assert await client.health() is True
    result = await client.compile(_GOOD_CSHARP, revit_version="2026")
    assert result.success is True, result.error
    assert result.error is None


@pytest.mark.tier1
@pytest.mark.asyncio
async def test_real_compile_rejects_bad_csharp(compile_service):
    client = HttpCompileClient(base_url=compile_service)
    result = await client.compile(_BAD_CSHARP, revit_version="2026")
    assert result.success is False
    assert result.error is not None
    assert any("CS1002" in e.code or "expected" in e.message for e in result.errors)


@pytest.mark.tier1
@pytest.mark.asyncio
async def test_real_compile_unknown_version_fails(compile_service):
    """compile-service rejects unknown Revit versions."""
    client = HttpCompileClient(base_url=compile_service)
    result = await client.compile(_GOOD_CSHARP, revit_version="9999")
    assert result.success is False
