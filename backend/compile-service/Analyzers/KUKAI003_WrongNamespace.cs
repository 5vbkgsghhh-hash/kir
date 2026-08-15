using System.Collections.Immutable;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Diagnostics;

namespace KukaiRevitAnalyzers;

[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class KUKAI003_WrongNamespace : DiagnosticAnalyzer
{
    public const string Id = "KUKAI003";

    private static readonly DiagnosticDescriptor Rule = new(
        id: Id,
        title: "Disallowed using namespace",
        messageFormat: "Namespace '{0}' is not in the Revit/System/Microsoft allowlist",
        category: "RevitAPI.Security",
        // 2026-08-13: БЫЛО Error — и рубило `Autodesk.Windows`, то есть ровно
        // ту способность (чтение чужой ленты), которую в тот же день вернули в
        // белый список сборок. Список префиксов здесь — ТРЕТИЙ по счёту список
        // разрешённого, живущий отдельно от белого списка сборок; ровно на
        // расхождении двух таких списков мы уже потеряли 4 дня 09–13.08.
        // Авторитет — компилятор: несуществующее пространство имён он и так
        // отвергает через CS0246. Правило остаётся подсказкой, не приговором.
        defaultSeverity: DiagnosticSeverity.Warning,
        isEnabledByDefault: true);

    public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics =>
        ImmutableArray.Create(Rule);

    private static readonly string[] AllowedPrefixes =
    {
        "Autodesk.Revit", "System", "Microsoft"
    };

    public override void Initialize(AnalysisContext context)
    {
        context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
        context.EnableConcurrentExecution();
        context.RegisterSyntaxNodeAction(Analyze, SyntaxKind.UsingDirective);
    }

    private static void Analyze(SyntaxNodeAnalysisContext ctx)
    {
        var node = (UsingDirectiveSyntax)ctx.Node;
        if (node.StaticKeyword.IsKind(SyntaxKind.StaticKeyword))
            return; // `using static X` is fine
        var ns = node.Name?.ToString();
        if (ns is null) return;
        foreach (var ok in AllowedPrefixes)
        {
            if (ns == ok || ns.StartsWith(ok + "."))
                return;
        }
        ctx.ReportDiagnostic(Diagnostic.Create(Rule, node.GetLocation(), ns));
    }
}
