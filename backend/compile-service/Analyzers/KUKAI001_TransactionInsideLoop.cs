using System.Collections.Immutable;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Diagnostics;

namespace KukaiRevitAnalyzers;

[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class KUKAI001_TransactionInsideLoop : DiagnosticAnalyzer
{
    public const string Id = "KUKAI001";

    private static readonly DiagnosticDescriptor Rule = new(
        id: Id,
        title: "Transaction inside loop",
        messageFormat: "Avoid opening a Revit Transaction inside a loop (use one outer Transaction)",
        category: "RevitAPI.Performance",
        // 2026-08-13: БЫЛО Error. Транзакция в цикле — законный приём (по
        // транзакции на элемент, чтобы отказ одного не отменил остальные), и
        // рубить его жёстко нельзя. Живая проба 13.08 показала отказ на
        // корректном коде. Остаётся подсказкой.
        defaultSeverity: DiagnosticSeverity.Warning,
        isEnabledByDefault: true,
        description: "Each transaction roundtrips Revit's undo stack. Wrap the loop in a single Transaction.");

    public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics =>
        ImmutableArray.Create(Rule);

    public override void Initialize(AnalysisContext context)
    {
        context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
        context.EnableConcurrentExecution();
        context.RegisterSyntaxNodeAction(Analyze, SyntaxKind.ObjectCreationExpression);
    }

    private static void Analyze(SyntaxNodeAnalysisContext ctx)
    {
        var creation = (ObjectCreationExpressionSyntax)ctx.Node;
        var typeName = creation.Type.ToString();
        if (typeName != "Transaction" && !typeName.EndsWith(".Transaction"))
            return;

        var enclosingLoop = creation.Ancestors().FirstOrDefault(a =>
            a is ForStatementSyntax || a is ForEachStatementSyntax ||
            a is WhileStatementSyntax || a is DoStatementSyntax);

        if (enclosingLoop != null)
        {
            ctx.ReportDiagnostic(Diagnostic.Create(Rule, creation.GetLocation()));
        }
    }
}
