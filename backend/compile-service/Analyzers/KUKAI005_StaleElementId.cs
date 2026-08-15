using System.Collections.Immutable;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Diagnostics;

namespace KukaiRevitAnalyzers;

[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class KUKAI005_StaleElementId : DiagnosticAnalyzer
{
    public const string Id = "KUKAI005";
    private static readonly DiagnosticDescriptor Rule = new(
        Id, "ElementId potentially stale after Transaction.Commit()",
        "ElementId may be invalidated after t.Commit(); re-fetch from doc if needed",
        // Audit N3 — downgrade from Error to Warning. The block-only sibling scan
        // produces false positives (commit-then-read-back is a legitimate Revit
        // pattern: the new ElementId remains valid post-commit). Proper semantic
        // model analysis deferred; until then emit as Warning so the diagnostic
        // surfaces to the user without hard-blocking compilation.
        "RevitAPI.Correctness", DiagnosticSeverity.Warning, true);

    public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics =>
        ImmutableArray.Create(Rule);

    public override void Initialize(AnalysisContext ctx)
    {
        ctx.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
        ctx.EnableConcurrentExecution();
        ctx.RegisterSyntaxNodeAction(Analyze, SyntaxKind.InvocationExpression);
    }

    private static void Analyze(SyntaxNodeAnalysisContext c)
    {
        var inv = (InvocationExpressionSyntax)c.Node;
        if (inv.Expression is not MemberAccessExpressionSyntax m) return;
        if (m.Name.Identifier.ValueText != "Commit") return;

        var block = inv.FirstAncestorOrSelf<BlockSyntax>();
        var stmt = inv.FirstAncestorOrSelf<StatementSyntax>();
        if (block == null || stmt == null) return;

        var siblings = block.Statements.ToList();
        var commitIdx = siblings.IndexOf(stmt);
        for (var i = commitIdx + 1; i < siblings.Count; i++)
        {
            if (siblings[i].ToString().Contains(".GetElement("))
            {
                c.ReportDiagnostic(Diagnostic.Create(Rule, siblings[i].GetLocation()));
                return;
            }
        }
    }
}
