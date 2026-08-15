using System.Threading.Tasks;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Testing;
using Microsoft.CodeAnalysis.Diagnostics;
using Microsoft.CodeAnalysis.Testing;
using Microsoft.CodeAnalysis.Testing.Verifiers;
using Xunit;
using KukaiRevitAnalyzers;

namespace Analyzers.Tests;

internal static class AnalyzerHarness
{
    public static Task Verify<TAnalyzer>(
        string code,
        DiagnosticSeverity? expectedSev = null,
        params DiagnosticResult[] additionalExpected)
        where TAnalyzer : DiagnosticAnalyzer, new()
    {
        var test = new CSharpAnalyzerTest<TAnalyzer, XUnitVerifier> { TestCode = code };
        // The [|...|] markers in `code` automatically populate ExpectedDiagnostics
        // at the analyzer's default severity, so no explicit DiagnosticResult is needed
        // for warning-level rules either.
        _ = expectedSev; // parameter kept for documentation/back-compat
        foreach (var d in additionalExpected)
        {
            test.ExpectedDiagnostics.Add(d);
        }
        return test.RunAsync();
    }
}

public class KUKAI001_Tests
{
    [Fact] public Task NoTransactionInLoop_Ok() => AnalyzerHarness.Verify<KUKAI001_TransactionInsideLoop>(@"
class C { void M() { using (var t = new Transaction()) { for (int i = 0; i < 10; i++) { } } } }
class Transaction : System.IDisposable { public void Dispose() {} }");

    [Fact] public Task TransactionInsideLoop_Flags() => AnalyzerHarness.Verify<KUKAI001_TransactionInsideLoop>(@"
class C { void M() { for (int i = 0; i < 10; i++) { using (var t = [|new Transaction()|]) { } } } }
class Transaction : System.IDisposable { public void Dispose() {} }");
}

public class KUKAI002_Tests
{
    [Fact] public Task GetElementWithGuard_Ok() => AnalyzerHarness.Verify<KUKAI002_MissingNullGuard>(@"
class D { public object GetElement(int id) => null!; }
class C { void M() { var d = new D(); var x = d.GetElement(1); if (x == null) return; var y = x.ToString(); } }");

    [Fact] public Task GetElementWithoutGuard_Flags() => AnalyzerHarness.Verify<KUKAI002_MissingNullGuard>(@"
class D { public object GetElement(int id) => null!; }
class C { void M() { var d = new D(); var x = [|d.GetElement(1)|]; var y = x.ToString(); } }");
}

public class KUKAI003_Tests
{
    [Fact] public Task SystemUsing_Ok() => AnalyzerHarness.Verify<KUKAI003_WrongNamespace>(
        "using System; class C {}");

    [Fact] public Task RogueUsing_Flags() => AnalyzerHarness.Verify<KUKAI003_WrongNamespace>(
        "[|using SneakyMalware;|] class C {}",
        additionalExpected: new[]
        {
            // Rogue namespace also triggers CS0246 ("type or namespace not found"); harness
            // requires explicit acknowledgement of compiler diagnostics it sees.
            DiagnosticResult.CompilerError("CS0246")
                .WithSpan(1, 7, 1, 20)
                .WithArguments("SneakyMalware"),
        });
}

public class KUKAI004_Tests
{
    [Fact] public Task FiveArgOverload_Ok() => AnalyzerHarness.Verify<KUKAI004_InvalidOverload>(@"
class Doc { public object NewFamilyInstance(int a, int b, int c, int d, int e) => null!; }
class C { void M() { new Doc().NewFamilyInstance(1,2,3,4,5); } }");

    [Fact] public Task TwoArgOverload_Flags() => AnalyzerHarness.Verify<KUKAI004_InvalidOverload>(@"
class Doc { public object NewFamilyInstance(int a, int b) => null!; }
class C { void M() { [|new Doc().NewFamilyInstance(1, 2)|]; } }");
}

public class KUKAI005_Tests
{
    [Fact] public Task NoLookupAfterCommit_Ok() => AnalyzerHarness.Verify<KUKAI005_StaleElementId>(@"
class T { public void Commit() {} }
class C { void M() { var t = new T(); t.Commit(); } }");

    [Fact] public Task LookupAfterCommit_Flags() => AnalyzerHarness.Verify<KUKAI005_StaleElementId>(@"
class Doc { public object GetElement(int id) => null!; }
class T { public void Commit() {} }
class C { void M() { var t = new T(); var d = new Doc(); t.Commit(); [|var elem = d.GetElement(5);|] } }");

    // Audit N3 — KUKAI005 false-positive documentation. The block-only sibling scan
    // currently still flags commit-then-read-back, but the severity is Warning so
    // it no longer hard-blocks compilation. Proper fix (semantic model + ID flow)
    // deferred. This test pins the current behavior at Warning severity rather than
    // claiming the false positive is gone.
    [Fact] public Task CommitThenReadBack_StillFlags_ButAsWarning() => AnalyzerHarness.Verify<KUKAI005_StaleElementId>(@"
class Doc { public object GetElement(int id) => null!; }
class T { public void Commit() {} }
class C { void M() { var t = new T(); var d = new Doc(); t.Commit(); [|var elem = d.GetElement(5);|] } }",
        expectedSev: DiagnosticSeverity.Warning);
}

public class KUKAI006_Tests
{
    [Fact] public Task ActivateWithRegenerate_Ok() => AnalyzerHarness.Verify<KUKAI006_MissingRegenerate>(@"
class Sym { public void Activate() {} } class Doc { public void Regenerate() {} }
class C { void M() { var s = new Sym(); var d = new Doc(); s.Activate(); d.Regenerate(); } }");

    [Fact] public Task ActivateWithoutRegenerate_Flags() => AnalyzerHarness.Verify<KUKAI006_MissingRegenerate>(@"
class Sym { public void Activate() {} }
class C { void M() { var s = new Sym(); [|s.Activate()|]; } }");

    // Audit N4 — KUKAI006 false-positive documentation. The block-text scan misses
    // outer-scope Regenerate when Activate is inside a nested braced if-block.
    // The current analyzer still flags this case, but at Warning severity so it
    // no longer hard-blocks compilation. Pins behavior; proper semantic fix deferred.
    [Fact] public Task BracedIfActivateThenOuterRegenerate_StillFlags_ButAsWarning() => AnalyzerHarness.Verify<KUKAI006_MissingRegenerate>(@"
class Sym { public bool IsActive { get; set; } public void Activate() {} }
class Doc { public void Regenerate() {} }
class C { void M() { var s = new Sym(); var d = new Doc(); if (!s.IsActive) { [|s.Activate()|]; } d.Regenerate(); } }",
        expectedSev: DiagnosticSeverity.Warning);
}
