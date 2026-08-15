using System.Collections.Immutable;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Diagnostics;

namespace KukaiRevitAnalyzers;

[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class KUKAI002_MissingNullGuard : DiagnosticAnalyzer
{
    public const string Id = "KUKAI002";

    private static readonly DiagnosticDescriptor Rule = new(
        id: Id,
        title: "Missing null guard after Revit element lookup",
        messageFormat: "Result of '{0}' may be null; guard with null check, pattern, or '?.'",
        category: "RevitAPI.Correctness",
        // 2026-08-13: БЫЛО Error, то есть ЖЁСТКАЯ блокировка. За первый день в
        // проде правило сработало 158 раз, и все 158 — ложные: оно рубило
        // СОБСТВЕННЫЙ серверный экстрактор (revit_ir/decompile_read), который
        // работает неделями. 22 минуты живой прогон разбора модели возвращал
        // пользователю «Внутренняя ошибка: серверный шаблон не скомпилировался».
        //
        // Почему ложные: правило синтаксическое и ищет охрану ТОЛЬКО в шести
        // следующих операторах того же блока. Охрана дальше по коду, охрана
        // внутри помощника и «null здесь допустим» ему не видны по построению.
        // Прибор, покрывающий часть диапазона, опаснее отсутствующего — как
        // Warning он остаётся подсказкой, но ход больше не рубит (гейт
        // отбирает только Severity == Error, RoslynCompiler.cs:222).
        defaultSeverity: DiagnosticSeverity.Warning,
        isEnabledByDefault: true,
        description: "GetElement and FirstElement can return null. Always null-check before dereference.");

    public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics =>
        ImmutableArray.Create(Rule);

    public override void Initialize(AnalysisContext context)
    {
        context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
        context.EnableConcurrentExecution();
        context.RegisterSyntaxNodeAction(Analyze, SyntaxKind.LocalDeclarationStatement);
    }

    // FilteredElementCollector.FirstOrDefault() also returns null, but we cannot
    // distinguish it from generic LINQ via name alone — promote-via-SemanticModel
    // is Phase 2 work. Today: rely on GetElement / FirstElement only. KUKAI002 is
    // the syntactic safety net; the Reflexion repair loop (Phase 2) catches the
    // rest via runtime exceptions.
    private static readonly string[] NullableCalls = { "GetElement", "FirstElement" };

    private static void Analyze(SyntaxNodeAnalysisContext ctx)
    {
        var decl = (LocalDeclarationStatementSyntax)ctx.Node;
        var variable = decl.Declaration.Variables.FirstOrDefault();
        if (variable?.Initializer?.Value is not InvocationExpressionSyntax invocation)
            return;
        if (invocation.Expression is not MemberAccessExpressionSyntax member)
            return;
        var methodName = member.Name.Identifier.ValueText;
        if (!NullableCalls.Contains(methodName))
            return;

        // Look for null guard in the next 6 statements within the same block.
        var block = decl.Parent as BlockSyntax;
        if (block == null) return;
        var statements = block.Statements;
        var idx = statements.IndexOf(decl);
        var name = variable.Identifier.ValueText;
        var window = statements.Skip(idx + 1).Take(6);

        foreach (var stmt in window)
        {
            var text = stmt.ToString();
            if (text.Contains($"{name} == null") || text.Contains($"{name} != null")
                || text.Contains($"{name} is null") || text.Contains($"{name} is not null")
                || text.Contains($"{name}?."))
            {
                return; // guarded
            }
        }

        ctx.ReportDiagnostic(Diagnostic.Create(Rule, invocation.GetLocation(), methodName));
    }
}
