"""Tier-1 integration tests: real compile-service on port 52412 runs custom analyzers.

PREREQUISITES (CI nightly job, or manual operator):
  $ cd backend/compile-service && dotnet run -c Release
  ...service should print 'RoslynCompiler initialized' and bind to 52412.
"""
from __future__ import annotations
import httpx
import pytest

from kukai.modeling.bridge.compile_client import HttpCompileClient


pytestmark = pytest.mark.tier1


import os

# Wave 7.5 follow-up: env-overridable compile-service URL so tier1 can hit a
# port other than the canonical 52412 (Navisworks dev-backend grabs 52412
# in some dev environments).
_COMPILE_SERVICE_URL = os.environ.get(
    "KUKAI_COMPILE_SERVICE_URL", "http://localhost:52412"
)


@pytest.fixture(scope="session")
def _service_ready() -> bool:
    """Probe the compile-service once per session; skip dependent tests if down.

    Verifies BOTH port responsiveness AND that /health returns the expected
    {"status": "ready"} payload — catches the case where some other service
    occupies the port without being compile-service.
    """
    try:
        r = httpx.get(f"{_COMPILE_SERVICE_URL}/health", timeout=2.0)
        if r.status_code != 200:
            return False
        return r.json().get("status") == "ready"
    except (httpx.HTTPError, ValueError):
        return False


@pytest.fixture(autouse=True)
def _require_service(_service_ready):
    if not _service_ready:
        pytest.skip(
            f"compile-service not responding at {_COMPILE_SERVICE_URL} "
            f"(start with `dotnet run -c Release` in backend/compile-service "
            f"OR set KUKAI_COMPILE_SERVICE_URL to override the URL)"
        )


@pytest.fixture(scope="session")
def _compile_url() -> str:
    return _COMPILE_SERVICE_URL


_KUKAI001 = """
namespace Autodesk.Revit.DB { public class Transaction : System.IDisposable {
    public Transaction(Document d, string n) {} public void Dispose() {}
    public void Start() {} public void Commit() {} } public class Document {} }
using Autodesk.Revit.DB;
class C { public static void M(Document doc) {
  for (int i = 0; i < 3; i++) {
    using (var t = new Transaction(doc, \"x\")) { t.Start(); t.Commit(); }
  } } }
"""

_KUKAI002 = """
namespace Autodesk.Revit.DB { public class Document { public object GetElement(int id) => null!; } }
using Autodesk.Revit.DB;
class C { public static void M(Document doc) {
  var sym = doc.GetElement(10);
  var n = sym.ToString();
} }
"""

_CLEAN = """
using Autodesk.Revit.DB;
namespace Autodesk.Revit.DB { public class Document {} }
class C { public static void M(Document d) {} }
"""

# Audit T1 — KUKAI004 (Error severity): NewFamilyInstance with wrong arg count
_KUKAI004 = """
class C { public static void M(object doc) {
  var unused = NewFamilyInstance(1, 2);
} static object NewFamilyInstance(int a, int b) => null!; }
"""

# Audit T1 — KUKAI005 (Warning severity, post-N3 downgrade):
# Transaction.Commit() followed by GetElement in same block.
_KUKAI005 = """
namespace Autodesk.Revit.DB {
  public class Document { public object GetElement(int id) => null!; }
  public class Transaction : System.IDisposable {
    public Transaction(Document d, string n) {}
    public void Start() {} public void Commit() {} public void Dispose() {}
  }
}
using Autodesk.Revit.DB;
class C { public static void M(Document d) {
  var t = new Transaction(d, \"x\");
  t.Start();
  t.Commit();
  var elt = d.GetElement(5);
} }
"""

# Audit T1 — KUKAI006 (Warning severity, post-N4 downgrade):
# Activate() (mutating call) in a block without Regenerate().
_KUKAI006 = """
namespace Autodesk.Revit.DB { public class Symbol { public void Activate() {} } }
using Autodesk.Revit.DB;
class C { public static void M(Symbol s) {
  s.Activate();
} }
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("code, expected_rule_id", [
    (_KUKAI001, "KUKAI001"),
    (_KUKAI002, "KUKAI002"),
    ("using SneakyMalware; class C {}", "KUKAI003"),
    (_KUKAI004, "KUKAI004"),
])
async def test_analyzer_reports_diagnostic(code, expected_rule_id):
    """Error-severity analyzers — surface in result.errors AND set success=False."""
    result = await HttpCompileClient().compile(code, revit_version="2026")
    assert result.success is False
    assert any(e.code == expected_rule_id for e in result.errors), \
        f"want {expected_rule_id} in {[e.code for e in result.errors]}"


@pytest.mark.asyncio
@pytest.mark.parametrize("code, expected_rule_id", [
    (_KUKAI005, "KUKAI005"),
    (_KUKAI006, "KUKAI006"),
])
async def test_warning_analyzer_surfaces_without_blocking(code, expected_rule_id):
    """Warning-severity analyzers (KUKAI005/006 post-N3+N4):
    surfaced in result.errors so the repair_loop + judge can react,
    but do NOT set success=False (post-N3+N4 projection filter)."""
    result = await HttpCompileClient().compile(code, revit_version="2026")
    assert result.success is True, \
        f"warning should not block; errors={[e.code+': '+e.message for e in result.errors]}"
    assert any(e.code == expected_rule_id for e in result.errors), \
        f"want {expected_rule_id} surfaced in result.errors={[e.code for e in result.errors]}"


@pytest.mark.asyncio
async def test_clean_code_compiles():
    result = await HttpCompileClient().compile(_CLEAN, revit_version="2026")
    assert result.success is True, f"errors={[e.code+': '+e.message for e in result.errors]}"


@pytest.mark.asyncio
async def test_revit_version_field_is_sent():
    """Regression: HttpCompileClient must send revitVersion. Schema-fix verification."""
    # If revit_version field wasn't sent, server returns 400 'revitVersion is required'.
    # Either success or analyzer-error is fine -- just not a transport-level fault.
    result = await HttpCompileClient().compile("class C {}", revit_version="2026")
    assert isinstance(result.success, bool)


@pytest.mark.asyncio
async def test_unknown_revit_version_surfaces_revit_version_error():
    result = await HttpCompileClient().compile("class C {}", revit_version="1999")
    assert result.success is False
    assert any(e.code == "REVIT_VERSION" for e in result.errors)
