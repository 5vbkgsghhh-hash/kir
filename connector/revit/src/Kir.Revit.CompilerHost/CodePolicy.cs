using System;
using System.Collections.Generic;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Kir.Revit.CompilerHost
{
    public static class CodePolicy
    {
        // The runtime hands generated code exactly one document. Everything
        // below exists so the generated assembly cannot NAME a second one, and
        // cannot reach an effect that outlives or escapes that document. A
        // blocklist of "dangerous members" cannot state that: Application alone
        // publishes ~80 members and Element.Document is inherited by every
        // element, so the reachable set is open-ended. The document rules are
        // therefore stated over the type system, not over member names.
        private const string DocumentTypeName = "Autodesk.Revit.DB.Document";
        private const string UiDocumentTypeName = "Autodesk.Revit.UI.UIDocument";
        // The allowlist below is stated over the NAMESPACE, not over one type:
        // `Application` has a sibling, `ControlledApplication`, that publishes
        // SharedParametersFilename / RecordingJournalFilename / Create too, and
        // a rule naming a single type would have left it to the API to refuse.
        private const string ApplicationServicesNamespace = "Autodesk.Revit.ApplicationServices";
        private const string WrapperTypeName = "Kir.Generated.UserCode";
        private const string WrapperMethodName = "Execute";
        private const string BoundDocumentParameterName = "doc";

        private static readonly string[] BlockedNamespacePrefixes =
        {
            "System.IO",
            "System.Net",
            "System.Reflection",
            "System.Diagnostics",
            "System.Runtime.InteropServices",
            "System.Runtime.Loader",
            "System.Security",
            "System.Threading",
            "System.Threading.Tasks",
            "System.Management",
            "System.CodeDom",
            "System.Windows",
            "Microsoft.Win32",
            "Microsoft.CSharp",
        };

        // Members of these namespaces are refused; the NAMES stay legal because
        // the required wrapper signature is Execute(Document, UIDocument) and a
        // parameter has to name its own type.
        private static readonly string[] MemberBlockedNamespacePrefixes =
        {
            "Autodesk.Revit.UI",
        };

        private static readonly HashSet<string> BlockedTypes =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "System.Activator",
                "System.AppDomain",
                "System.Environment",
                "System.GC",
                "System.Type",
                "Autodesk.Revit.UI.TaskDialog",
                "Autodesk.Revit.DB.BasicFileInfo",
                "Autodesk.Revit.DB.ModelPathUtils",
                "Autodesk.Revit.DB.TransmissionData",
                "Autodesk.Revit.DB.ExternalFileUtils",
                // Process-wide registries: a registration here outlives the
                // operation and can remove or replace another add-in's.
                "Autodesk.Revit.DB.UpdaterRegistry",
                "Autodesk.Revit.DB.ExternalService.ExternalServiceRegistry",
            };

        // `Autodesk.Revit.Creation.Document` is a DIFFERENT type that happens to
        // share the short name — the element factory of one document. Values of
        // it may only be read straight off the bound document, so the factory
        // provably belongs to `doc` and cannot be carried in from anywhere else
        // (external review, X-R2). Measured cost of this rule: zero — all 51
        // uses in the golden corpus are direct `doc.Create.NewX(...)`, and
        // nothing in the tree binds the factory to a variable.
        private const string CreationDocumentTypeName = "Autodesk.Revit.Creation.Document";

        private static readonly HashSet<string> BoundDocumentFactoryMembers =
            new HashSet<string>(StringComparer.Ordinal) { "Create", "FamilyCreate" };

        // Types whose values ARE (or iterate) documents. Naming one is refused
        // outright; the single exception is the bound `doc` parameter's own type.
        private static readonly HashSet<string> DocumentValuedTypes =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "Autodesk.Revit.DB.Document",
                "Autodesk.Revit.DB.DocumentSet",
                "Autodesk.Revit.DB.DocumentSetIterator",
            };

        // Members of the bound document whose effect leaves the document:
        // filesystem, cloud, central model, linked models, or the document's
        // own identity (which the native precondition owns, not generated code).
        private static readonly HashSet<string> BlockedDocumentMembers =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "AcquireCoordinates",
                "Close",
                "EnableCloudWorksharing",
                "EnableWorksharing",
                "Export",
                "ExportImage",
                "GetCloudModelPath",
                "GetWorksharingCentralModelPath",
                "Import",
                "Link",
                "LoadFamily",
                "LoadFamilySymbol",
                "PathName",
                "Print",
                "PrintManager",
                "PublishCoordinates",
                "ReloadLatest",
                "Save",
                "SaveAs",
                "SaveAsCloudModel",
                "SaveCloudModel",
                "SynchronizeWithCentral",
            };

        // Application is an ALLOWLIST, not a blocklist: it is the process-wide
        // object, and its open set includes Documents, journal writes, ini/library
        // paths, shared-parameter file state, document factories and the event
        // hub. Only read-only scalars the KIR emitters actually use are admitted.
        private static readonly HashSet<string> AllowedApplicationMembers =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "AngleTolerance",
                "FamilyTemplatePath",
                "ShortCurveTolerance",
                "VersionBuild",
                "VersionName",
                "VersionNumber",
                "VertexTolerance",
            };

        // Members of other Revit types whose effect leaves the document: they
        // read a file from the host filesystem into the model.
        private static readonly Dictionary<string, HashSet<string>> BlockedTypeMembers =
            new Dictionary<string, HashSet<string>>(StringComparer.Ordinal)
            {
                {
                    "Autodesk.Revit.DB.RevitLinkType",
                    new HashSet<string>(StringComparer.Ordinal)
                        { "Load", "LoadFrom", "Reload", "ReloadFrom" }
                },
            };

        // Transaction scopes carry no Document property in the 2021-2026 API, so
        // the bound document can only be checked at the CONSTRUCTOR argument.
        private static readonly HashSet<string> DocumentScopedTypes =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "Autodesk.Revit.DB.Transaction",
                "Autodesk.Revit.DB.SubTransaction",
                "Autodesk.Revit.DB.TransactionGroup",
            };

        public static List<string> Validate(CSharpCompilation compilation, SyntaxTree tree)
        {
            var violations = new SortedSet<string>(StringComparer.Ordinal);
            try
            {
                var root = tree.GetRoot();
                ValidateSyntax(root, violations);
                ValidateEntryPoint(compilation, violations);
                var model = compilation.GetSemanticModel(tree, ignoreAccessibility: false);
                foreach (var node in root.DescendantNodesAndSelf())
                {
                    var symbol = model.GetSymbolInfo(node).Symbol;
                    if (symbol != null) ValidateSymbol(symbol, node, violations);
                    var type = model.GetTypeInfo(node).Type;
                    if (type != null && type.TypeKind == TypeKind.Dynamic)
                        Add(violations, "dynamic is not allowed", node);
                    ValidateDocumentBinding(model, node, symbol, violations);
                    ValidateDocumentScopedConstruction(model, node, violations);
                    ValidateEventRegistration(model, node, violations);
                }
            }
            catch (Exception ex)
            {
                violations.Add("policy_internal: semantic analysis failed: " + ex.Message);
            }
            return violations.ToList();
        }

        private static void ValidateSyntax(SyntaxNode root, ISet<string> violations)
        {
            foreach (var directive in root.DescendantTrivia(descendIntoTrivia: true)
                         .Where(trivia => trivia.IsDirective).Select(trivia => trivia.GetStructure())
                         .Where(node => node != null))
                Add(violations, "preprocessor directives are not allowed", directive!);

            foreach (var node in root.DescendantNodesAndSelf())
            {
                switch (node)
                {
                    case UnsafeStatementSyntax _:
                    case PointerTypeSyntax _:
                    case FunctionPointerTypeSyntax _:
                    case StackAllocArrayCreationExpressionSyntax _:
                    case LockStatementSyntax _:
                    case AwaitExpressionSyntax _:
                    case GotoStatementSyntax _:
                    case WhileStatementSyntax _:
                    case DoStatementSyntax _:
                        Add(violations, node.Kind() + " is not allowed", node);
                        break;
                    case ForStatementSyntax loop when loop.Condition == null:
                        Add(violations, "unbounded for loop is not allowed", node);
                        break;
                    case MethodDeclarationSyntax method when method.Modifiers.Any(SyntaxKind.AsyncKeyword):
                        Add(violations, "async methods are not allowed", node);
                        break;
                    case LocalFunctionStatementSyntax method when method.Modifiers.Any(SyntaxKind.AsyncKeyword):
                        Add(violations, "async local functions are not allowed", node);
                        break;
                }
            }
        }

        private static void ValidateSymbol(ISymbol symbol, SyntaxNode node, ISet<string> violations)
        {
            var declaresType = symbol is INamedTypeSymbol;
            var type = SymbolType(symbol);
            var typeName = type?.ToDisplayString() ?? string.Empty;
            var namespaceName = type?.ContainingNamespace?.ToDisplayString() ?? string.Empty;

            if (BlockedNamespacePrefixes.Any(prefix => InNamespace(namespaceName, prefix)))
            {
                Add(violations, "blocked namespace: " + namespaceName, node);
                return;
            }

            if (!declaresType
                && MemberBlockedNamespacePrefixes.Any(prefix => InNamespace(namespaceName, prefix)))
            {
                Add(violations, "blocked member of namespace " + namespaceName + ": " + symbol.Name, node);
                return;
            }

            if (BlockedTypes.Contains(typeName))
            {
                Add(violations, "blocked type: " + typeName, node);
                return;
            }

            if (symbol is IMethodSymbol method && method.Name == "GetType"
                && method.ContainingType?.ToDisplayString() == "object")
                Add(violations, "runtime type discovery is not allowed", node);

            if (typeName == DocumentTypeName && !declaresType
                && BlockedDocumentMembers.Contains(symbol.Name))
                Add(violations, "blocked Document member: " + symbol.Name, node);

            if (!declaresType && InNamespace(namespaceName, ApplicationServicesNamespace)
                && !AllowedApplicationMembers.Contains(symbol.Name))
                Add(violations, "Application member outside the read-only allowlist: " + symbol.Name, node);

            if (!declaresType && BlockedTypeMembers.TryGetValue(typeName, out var blockedMembers)
                && blockedMembers.Contains(symbol.Name))
                Add(violations, "blocked member: " + typeName + "." + symbol.Name, node);
        }

        // The document barrier. Generated code may hold exactly one document —
        // the `doc` parameter the runtime bound — so (1) the document types may
        // not be named anywhere else, and (2) no expression may PRODUCE a
        // Document unless it is that parameter. Together these refuse
        // Application.Documents, UIDocument.Document, Element.Document,
        // RevitLinkInstance.GetLinkDocument, Document.EditFamily and
        // DocumentChangedEventArgs.GetDocument without enumerating them, and
        // therefore refuse every write into a document that was not bound.
        private static void ValidateDocumentBinding(SemanticModel model, SyntaxNode node,
            ISymbol? symbol, ISet<string> violations)
        {
            if (symbol is ITypeSymbol named && DocumentValuedTypes.Contains(named.ToDisplayString()))
            {
                if (!IsBoundDocumentParameterType(model, node))
                    Add(violations, "type " + named.ToDisplayString()
                        + " may not be named; generated code is bound to the single `doc` parameter", node);
                return;
            }

            // The NAME half of `a.B` is an expression of B's type too, and it can
            // never be the bound parameter, so judging it would condemn every
            // `doc.Create`. The access as a whole is judged one node up; that is
            // where the receiver is visible. (Caught by this file's own legal
            // control before shipping: `doc.Create.NewRoom(...)` went red.)
            if (node.Parent is MemberAccessExpressionSyntax parentAccess && parentAccess.Name == node) return;
            if (node.Parent is MemberBindingExpressionSyntax parentBinding && parentBinding.Name == node) return;
            if (!(node is ExpressionSyntax expression) || !ProducesValue(expression)) return;
            var produced = model.GetTypeInfo(expression).Type?.ToDisplayString();
            if (produced == CreationDocumentTypeName)
            {
                if (!IsBoundDocumentFactory(model, expression))
                    Add(violations, "a " + CreationDocumentTypeName
                        + " expression must be read directly off the bound `doc` parameter", node);
                return;
            }
            if (produced != DocumentTypeName) return;
            if (symbol is IParameterSymbol parameter && IsBoundDocumentParameter(parameter)) return;
            Add(violations, "a Document expression must be the bound `doc` parameter", node);
        }

        private static void ValidateDocumentScopedConstruction(SemanticModel model, SyntaxNode node,
            ISet<string> violations)
        {
            if (!(node is ObjectCreationExpressionSyntax creation)) return;
            var created = model.GetTypeInfo(creation).Type?.ToDisplayString();
            if (created == null || !DocumentScopedTypes.Contains(created)) return;
            var first = creation.ArgumentList == null || creation.ArgumentList.Arguments.Count == 0
                ? null : creation.ArgumentList.Arguments[0].Expression;
            if (first is IdentifierNameSyntax identifier
                && model.GetSymbolInfo(identifier).Symbol is IParameterSymbol parameter
                && IsBoundDocumentParameter(parameter)) return;
            Add(violations, created + " must be opened on the bound `doc` parameter", node);
        }

        // A handler registered here outlives the operation: it keeps running
        // after the receipt is written, and on 2025-2026 it pins the collectible
        // load context the runtime unloads.
        private static void ValidateEventRegistration(SemanticModel model, SyntaxNode node,
            ISet<string> violations)
        {
            if (!(node is AssignmentExpressionSyntax assignment)) return;
            if (!assignment.IsKind(SyntaxKind.AddAssignmentExpression)
                && !assignment.IsKind(SyntaxKind.SubtractAssignmentExpression)) return;
            if (model.GetSymbolInfo(assignment.Left).Symbol is IEventSymbol handled)
                Add(violations, "event registration is not allowed: " + handled.Name, node);
        }

        private static bool ProducesValue(ExpressionSyntax expression)
        {
            switch (expression)
            {
                case IdentifierNameSyntax _:
                case MemberAccessExpressionSyntax _:
                case MemberBindingExpressionSyntax _:
                case InvocationExpressionSyntax _:
                case ObjectCreationExpressionSyntax _:
                case ElementAccessExpressionSyntax _:
                case CastExpressionSyntax _:
                    return true;
                default:
                    return false;
            }
        }

        // `doc.Create` / `doc.FamilyCreate` and nothing else: the receiver must be
        // the bound parameter itself, not a local that once held it (a local of
        // document type is already refused, but the factory has its own type).
        private static bool IsBoundDocumentFactory(SemanticModel model, ExpressionSyntax expression)
        {
            if (!(expression is MemberAccessExpressionSyntax access)) return false;
            if (!BoundDocumentFactoryMembers.Contains(access.Name.Identifier.ValueText)) return false;
            return model.GetSymbolInfo(access.Expression).Symbol is IParameterSymbol receiver
                   && IsBoundDocumentParameter(receiver);
        }

        private static bool IsBoundDocumentParameterType(SemanticModel model, SyntaxNode node)
        {
            if (!(node.Parent is ParameterSyntax parameter) || parameter.Type != node) return false;
            return model.GetDeclaredSymbol(parameter) is IParameterSymbol symbol
                   && IsBoundDocumentParameter(symbol);
        }

        // The bound document is the FIRST parameter of the one entry point the
        // runtime actually invokes — the same method Compiler.ValidateWrapper
        // resolves. Matching on the name `Execute` alone was not enough: a
        // `static object Execute(Document doc)` LOCAL FUNCTION inside the body
        // satisfied it, and thereby earned both the right to name the type and
        // the status of a bound expression (external review, X-R1).
        private static bool IsBoundDocumentParameter(IParameterSymbol parameter)
        {
            return parameter.Name == BoundDocumentParameterName
                   && parameter.Ordinal == 0
                   && parameter.Type?.ToDisplayString() == DocumentTypeName
                   && parameter.ContainingSymbol is IMethodSymbol method
                   && IsEntryPoint(method);
        }

        private static bool IsEntryPoint(IMethodSymbol method)
        {
            return method.MethodKind == MethodKind.Ordinary
                   && method.Name == WrapperMethodName
                   && method.IsStatic
                   && method.DeclaredAccessibility == Accessibility.Public
                   && method.ReturnType?.SpecialType == SpecialType.System_Object
                   && method.Parameters.Length == 2
                   && method.Parameters[0].Type?.ToDisplayString() == DocumentTypeName
                   && method.Parameters[1].Type?.ToDisplayString() == UiDocumentTypeName
                   && method.ContainingType?.ToDisplayString() == WrapperTypeName;
        }

        // Two public static `Execute` members made Compiler.ValidateWrapper's
        // SingleOrDefault throw, and the host answered "compiler_internal:
        // Sequence contains more than one matching element" — fail-safe, but it
        // named the wrong thing. The refusal belongs here, by its own name.
        private static void ValidateEntryPoint(CSharpCompilation compilation, ISet<string> violations)
        {
            var wrapper = compilation.GetTypeByMetadataName(WrapperTypeName);
            if (wrapper == null) return;
            var entries = wrapper.GetMembers(WrapperMethodName).OfType<IMethodSymbol>()
                .Where(m => m.IsStatic && m.DeclaredAccessibility == Accessibility.Public)
                .ToList();
            if (entries.Count <= 1) return;
            var line = 0;
            var location = entries[1].Locations.FirstOrDefault(l => l.IsInSource);
            if (location != null) line = location.GetLineSpan().StartLinePosition.Line + 1;
            violations.Add("policy: exactly one public static " + WrapperTypeName + "."
                           + WrapperMethodName + " is allowed; found " + entries.Count
                           + " (line " + line + ")");
        }

        private static bool InNamespace(string namespaceName, string prefix)
        {
            return namespaceName.Equals(prefix, StringComparison.Ordinal)
                   || namespaceName.StartsWith(prefix + ".", StringComparison.Ordinal);
        }

        private static INamedTypeSymbol? SymbolType(ISymbol symbol)
        {
            if (symbol is INamedTypeSymbol named) return named;
            return symbol.ContainingType;
        }

        private static void Add(ISet<string> violations, string message, SyntaxNode node)
        {
            var line = node.GetLocation().GetLineSpan().StartLinePosition.Line + 1;
            violations.Add("policy: " + message + " (line " + line + ")");
        }
    }
}
