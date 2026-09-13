using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Kir.Revit.Protocol;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Kir.Revit.CompilerHost
{
    public static class Compiler
    {
        private const string WrapperNamespace = "Kir.Generated";
        private const string WrapperTypeName = "UserCode";
        private const string WrapperMethodName = "Execute";
        private const string WrapperTypeMissing =
            "wrapper type Kir.Generated.UserCode was not found";
        private const string WrapperMethodMissing =
            "public static Kir.Generated.UserCode.Execute was not found";

        private static readonly HashSet<string> AllowedReferenceNames =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            {
                "mscorlib",
                "netstandard",
                "System",
                "System.Core",
                "System.Private.CoreLib",
                "System.Runtime",
                "System.Runtime.Extensions",
                "System.Collections",
                "System.Collections.Concurrent",
                "System.Collections.NonGeneric",
                "System.Collections.Specialized",
                "System.Linq",
                "System.Linq.Expressions",
                "System.ObjectModel",
                "System.Memory",
                "System.Private.Uri",
                "System.Runtime.Numerics",
                "System.ComponentModel.Primitives",
                "System.ComponentModel.TypeConverter",
                "System.Text.RegularExpressions",
                "RevitAPI",
                "RevitAPIUI",
            };

        public static CompilerResponse Compile(CompilerRequest request)
        {
            if (request == null) return Fail("request is null");
            if (!string.Equals(request.Protocol, ProtocolConstants.Version, StringComparison.Ordinal))
                return Fail("protocol version mismatch");
            if (string.IsNullOrWhiteSpace(request.Source)) return Fail("source is empty");
            if (request.Source.Length > ProtocolConstants.MaxSourceChars)
                return Fail("source exceeds the protocol limit");

            try
            {
                var references = LoadReferences(request.ReferencePaths);
                var tree = CSharpSyntaxTree.ParseText(
                    request.Source,
                    new CSharpParseOptions(LanguageVersion.Latest));
                var compilation = CSharpCompilation.Create(
                    "KirGenerated_" + Guid.NewGuid().ToString("N"),
                    new[] { tree },
                    references,
                    new CSharpCompilationOptions(
                        OutputKind.DynamicallyLinkedLibrary,
                        optimizationLevel: OptimizationLevel.Release,
                        allowUnsafe: false,
                        concurrentBuild: false));

                // THE ORDER HERE IS PART OF THE CONTRACT, not a matter of taste.
                //
                // `CodePolicy` recognizes the bound document only by the EXACT shape
                // of the wrapper (`IsBoundDocumentParameter` -> `IsEntryPoint`). While
                // the shape check stood AFTER the policy, a wrong namespace, a wrong
                // class, and a wrong method all gave back the same wrong reason,
                // "type Autodesk.Revit.DB.Document may not be named": the refusal was
                // correct, the named reason was not. Measured 07.09 on real
                // RevitAPI 2023 and 2026: three different shape breakages -> 0 correct
                // reasons out of 3.
                //
                // The check below reads ONLY syntax and does NOT touch semantics.
                // This is not a shortcut: an error inside the body (CS1525 and kin) is required
                // to remain ITS OWN reason, and Roslyn still recovers the namespace/class/method
                // declarations even when such errors occur. The shape's
                // semantics (signature, return type) are checked by the existing `ValidateWrapper`
                // AFTER the compiler errors, where it belongs.
                var shapeError = ValidateWrapperShape(tree);
                if (shapeError != null) return Fail(shapeError);

                var violations = CodePolicy.Validate(compilation, tree);
                if (violations.Count > 0)
                    return new CompilerResponse { Ok = false, Diagnostics = violations };

                var diagnostics = compilation.GetDiagnostics()
                    .Where(d => d.Severity == DiagnosticSeverity.Error)
                    .Select(FormatDiagnostic)
                    .Take(100)
                    .ToList();
                if (diagnostics.Count > 0)
                    return new CompilerResponse { Ok = false, Diagnostics = diagnostics };

                var wrapperError = ValidateWrapper(compilation);
                if (wrapperError != null) return Fail(wrapperError);

                using var output = new MemoryStream();
                var emitted = compilation.Emit(output);
                if (!emitted.Success)
                {
                    return new CompilerResponse
                    {
                        Ok = false,
                        Diagnostics = emitted.Diagnostics
                            .Where(d => d.Severity == DiagnosticSeverity.Error)
                            .Select(FormatDiagnostic)
                            .Take(100)
                            .ToList(),
                    };
                }

                return new CompilerResponse
                {
                    Ok = true,
                    AssemblyBase64 = Convert.ToBase64String(output.ToArray()),
                };
            }
            catch (Exception ex)
            {
                return Fail("compiler_internal: " + ex.Message);
            }
        }

        private static List<MetadataReference> LoadReferences(IEnumerable<string>? paths)
        {
            var result = new List<MetadataReference>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var path in paths ?? Array.Empty<string>())
            {
                if (string.IsNullOrWhiteSpace(path) || !File.Exists(path)) continue;
                var fullPath = Path.GetFullPath(path);
                if (!seen.Add(fullPath)) continue;

                var name = AssemblyName.GetAssemblyName(fullPath).Name ?? string.Empty;
                if (!AllowedReferenceNames.Contains(name))
                    throw new InvalidDataException("reference is outside the compiler allowlist: " + name);
                result.Add(MetadataReference.CreateFromFile(fullPath));
            }

            if (!result.Any(r => string.Equals(
                    Path.GetFileNameWithoutExtension(r.Display), "RevitAPI",
                    StringComparison.OrdinalIgnoreCase)))
                throw new InvalidDataException("RevitAPI reference is missing");
            if (!result.Any(r => string.Equals(
                    Path.GetFileNameWithoutExtension(r.Display), "RevitAPIUI",
                    StringComparison.OrdinalIgnoreCase)))
                throw new InvalidDataException("RevitAPIUI reference is missing");
            return result;
        }

        private static string ListOrNone(IEnumerable<string> names)
        {
            var found = names.Distinct(StringComparer.Ordinal).OrderBy(n => n, StringComparer.Ordinal)
                .Take(8).ToList();
            return found.Count == 0 ? "(none)" : string.Join(", ", found);
        }

        // The wrapper's syntactic shape. The reason names EXACTLY THE link that
        // mismatched, and lists what was found — otherwise the author reads "not found"
        // and does not know what exactly he got wrong.
        private static string? ValidateWrapperShape(SyntaxTree tree)
        {
            var root = tree.GetRoot();
            var namespaces = root.DescendantNodes().OfType<BaseNamespaceDeclarationSyntax>().ToList();
            var wrappers = namespaces
                .Where(n => string.Equals(n.Name.ToString(), WrapperNamespace, StringComparison.Ordinal))
                .ToList();
            if (wrappers.Count == 0)
                return "wrapper_shape_mismatch:namespace - " + WrapperTypeMissing
                       + "; expected namespace " + WrapperNamespace
                       + ", source declares: " + ListOrNone(namespaces.Select(n => n.Name.ToString()));

            var types = wrappers.SelectMany(n => n.Members.OfType<TypeDeclarationSyntax>()).ToList();
            var wrapperTypes = types
                .Where(t => string.Equals(t.Identifier.ValueText, WrapperTypeName, StringComparison.Ordinal))
                .ToList();
            if (wrapperTypes.Count == 0)
                return "wrapper_shape_mismatch:type - " + WrapperTypeMissing
                       + "; namespace " + WrapperNamespace + " declares: "
                       + ListOrNone(types.Select(t => t.Identifier.ValueText));

            var methods = wrapperTypes.SelectMany(t => t.Members.OfType<MethodDeclarationSyntax>()).ToList();
            if (!methods.Any(m => string.Equals(m.Identifier.ValueText, WrapperMethodName, StringComparison.Ordinal)))
                return "wrapper_shape_mismatch:method - " + WrapperMethodMissing
                       + "; " + WrapperNamespace + "." + WrapperTypeName + " declares: "
                       + ListOrNone(methods.Select(m => m.Identifier.ValueText));
            return null;
        }

        private static string? ValidateWrapper(CSharpCompilation compilation)
        {
            var type = compilation.GetTypeByMetadataName(WrapperNamespace + "." + WrapperTypeName);
            if (type == null) return WrapperTypeMissing;
            var method = type.GetMembers(WrapperMethodName).OfType<IMethodSymbol>()
                .SingleOrDefault(m => m.IsStatic && m.DeclaredAccessibility == Accessibility.Public);
            if (method == null) return WrapperMethodMissing;
            if (method.Parameters.Length != 2
                || method.Parameters[0].Type.ToDisplayString() != "Autodesk.Revit.DB.Document"
                || method.Parameters[1].Type.ToDisplayString() != "Autodesk.Revit.UI.UIDocument")
                return "Execute must accept (Autodesk.Revit.DB.Document, Autodesk.Revit.UI.UIDocument)";
            if (method.ReturnType.SpecialType != SpecialType.System_Object)
                return "Execute must return System.Object";
            return null;
        }

        private static string FormatDiagnostic(Diagnostic diagnostic)
        {
            var span = diagnostic.Location.GetLineSpan();
            return diagnostic.Id + ": " + diagnostic.GetMessage()
                   + " (line " + (span.StartLinePosition.Line + 1)
                   + ", col " + (span.StartLinePosition.Character + 1) + ")";
        }

        private static CompilerResponse Fail(string diagnostic)
        {
            return new CompilerResponse { Ok = false, Diagnostics = { diagnostic } };
        }
    }
}
