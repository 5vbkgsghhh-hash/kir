using System.Collections.Immutable;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Diagnostics;

namespace KukaiRevitAnalyzers;

[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class KUKAI004_InvalidOverload : DiagnosticAnalyzer
{
    public const string Id = "KUKAI004";
    private static readonly DiagnosticDescriptor Rule = new(
        Id, "Suspicious NewFamilyInstance overload selection",
        "NewFamilyInstance called with {0} arguments — verify the overload matches the host category",
        // 2026-08-13: БЫЛО Error. Само сообщение правила говорит «ПРОВЕРЬ,
        // подходит ли перегрузка» — то есть это подозрение, а подозрение не
        // может быть приговором. Живых срабатываний за сутки ноль, а два
        // соседа той же строгости отвергли корректный код в первый же день.
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
        if (m.Name.Identifier.ValueText != "NewFamilyInstance") return;
        var argCount = inv.ArgumentList.Arguments.Count;
        if (argCount < 3 || argCount > 5)
            c.ReportDiagnostic(Diagnostic.Create(Rule, inv.GetLocation(), argCount));
    }
}
