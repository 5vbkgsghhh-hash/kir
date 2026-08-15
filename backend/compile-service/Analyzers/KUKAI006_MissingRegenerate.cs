using System.Collections.Immutable;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Diagnostics;

namespace KukaiRevitAnalyzers;

[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class KUKAI006_MissingRegenerate : DiagnosticAnalyzer
{
    public const string Id = "KUKAI006";
    private static readonly DiagnosticDescriptor Rule = new(
        Id, "Geometry mutation without Regenerate()",
        "Geometry was mutated (Activate/MoveElement/JoinGeometry) without a subsequent doc.Regenerate()",
        // Audit N4 — downgrade from Error to Warning. The block-scoped
        // Regenerate() text search misses outer-scope regenerate calls (e.g.
        // braced if(symbol.IsActive==false){ symbol.Activate(); } followed by
        // doc.Regenerate() at the outer scope). Proper semantic analysis (data
        // flow up to nearest containing transaction block) deferred; until
        // then emit as Warning to surface signal without false-positive blocks.
        "RevitAPI.Correctness", DiagnosticSeverity.Warning, true);

    private static readonly string[] MutatingCalls =
        { "Activate", "MoveElement", "JoinGeometry", "UnjoinGeometry",
          "Rotate", "RotateElement", "DisallowJoinAtEnd" };

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
        if (!MutatingCalls.Contains(m.Name.Identifier.ValueText)) return;

        var block = inv.FirstAncestorOrSelf<BlockSyntax>();
        if (block == null) return;
        if (block.ToString().Contains(".Regenerate()")) return;

        c.ReportDiagnostic(Diagnostic.Create(Rule, inv.GetLocation()));
    }
}
