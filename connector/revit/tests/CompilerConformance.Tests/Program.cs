using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text.Json;
using Kir.Revit.CompilerHost;
using Kir.Revit.Protocol;

// A test runner for the ACTUAL compiler and policy, not a second validator.
// Reference paths and wrapped source arrive on stdin; assemblies are emitted
// in memory and never loaded or executed. No Revit installation is launched.
internal static class Program
{
    private static int Main()
    {
        try
        {
            var requests = JsonSerializer.Deserialize<List<CompilerRequest>>(Console.In.ReadToEnd());
            if (requests == null) throw new ArgumentException("expected a request array");
            var rows = new List<object>();
            foreach (var request in requests)
            {
                var revitReferences = new Dictionary<string, string>();
                foreach (var path in request.ReferencePaths)
                {
                    var fileName = Path.GetFileNameWithoutExtension(path);
                    if (fileName == "RevitAPI" || fileName == "RevitAPIUI")
                    {
                        // Read actual assembly metadata, never load/execute it.
                        // A directory named 2026 is not proof of a 2026 API.
                        var identity = AssemblyName.GetAssemblyName(path);
                        if (identity.Name != fileName || identity.Version == null)
                            throw new ArgumentException("Revit reference identity differs from its filename");
                        revitReferences.Add(fileName, identity.Version.ToString());
                    }
                }
                var result = Compiler.Compile(request);
                rows.Add(new { ok = result.Ok, diagnostics = result.Diagnostics,
                    revit_references = revitReferences,
                    assembly_bytes = result.AssemblyBase64 == null ? 0 : Convert.FromBase64String(result.AssemblyBase64).Length });
            }
            Console.WriteLine(JsonSerializer.Serialize(rows));
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception.GetType().Name + ": " + exception.Message);
            return 2;
        }
    }
}
