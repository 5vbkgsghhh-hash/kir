using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

internal static class FakeDotnet
{
    private static void Put(string path, string text)
    { Directory.CreateDirectory(Path.GetDirectoryName(path)!); File.WriteAllText(path, text); }
    // Minimal managed metadata only, not an executable Revit implementation.
    private static void Managed(string path, string name, params string[] references)
    {
        var metadata=new MetadataBuilder();
        metadata.AddModule(0,metadata.GetOrAddString(name+".dll"),metadata.GetOrAddGuid(new Guid(SHA256.HashData(Encoding.UTF8.GetBytes(name)).Take(16).ToArray())),default,default);
        metadata.AddAssembly(metadata.GetOrAddString(name),new Version(0,1,0,0),default,default,(AssemblyFlags)0,(AssemblyHashAlgorithm)0);
        metadata.AddTypeDefinition(TypeAttributes.NotPublic,default,metadata.GetOrAddString("<Module>"),default,MetadataTokens.FieldDefinitionHandle(1),MetadataTokens.MethodDefinitionHandle(1));
        foreach(var reference in references)
        {
            var platform=reference=="mscorlib";
            metadata.AddAssemblyReference(metadata.GetOrAddString(reference),platform?new Version(4,0,0,0):new Version(0,1,0,0),default,
                platform?metadata.GetOrAddBlob(Convert.FromHexString("b77a5c561934e089")):default,(AssemblyFlags)0,default);
        }
        var image=new ManagedPEBuilder(new PEHeaderBuilder(imageCharacteristics:Characteristics.ExecutableImage|Characteristics.Dll),new MetadataRootBuilder(metadata),new BlobBuilder(),flags:CorFlags.ILOnly,
            deterministicIdProvider:content=>BlobContentId.FromHash(SHA256.HashData(content.SelectMany(blob=>blob.GetBytes()).ToArray())));
        var blob=new BlobBuilder();image.Serialize(blob);Directory.CreateDirectory(Path.GetDirectoryName(path)!);File.WriteAllBytes(path,blob.ToArray());
    }
    public static int Main(string[] args)
    {
        if (args.SequenceEqual(new[] { "--version" })) { Console.WriteLine("8.0.423"); return 0; }
        if (args.Length == 3 && args[0] == "--make-refs")
        {
            Directory.CreateDirectory(args[1]);
            foreach (var referenceName in new[] { "RevitAPI", "RevitAPIUI" })
            {
                var references = ((string)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")!).Split(Path.PathSeparator)
                    .Select(path => MetadataReference.CreateFromFile(path));
                var source = $"[assembly:System.Reflection.AssemblyVersion(\"{int.Parse(args[2]) - 2000}.0.0.0\")] public sealed class FixtureNotRevit {{ }}";
                var compilation = CSharpCompilation.Create(referenceName, new[] { CSharpSyntaxTree.ParseText(source) }, references,
                    new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
                var emitted = compilation.Emit(Path.Combine(args[1], referenceName + ".dll"));
                if (!emitted.Success) throw new Exception(string.Join("\n", emitted.Diagnostics));
            }
            return 0;
        }
        var mode = Environment.GetEnvironmentVariable("KIR_PACKAGE_FAKE_MODE") ?? "success";
        var project = args[1]; var operation = args[0];
        var year = args.FirstOrDefault(x => x.StartsWith("-p:RevitVersion=", StringComparison.Ordinal))?.Split('=')[1];
        var configuration = args[Array.IndexOf(args, "-c") + 1];
        var code = mode == "publish_fail" && operation == "publish" ? 17
            : mode == "client_fail" && project.Contains("Kir.Revit.PipeClient") ? 19
            : mode == "build_fail_2026" && year == "2026" ? 23 : 0;
        File.AppendAllText(Environment.GetEnvironmentVariable("KIR_PACKAGE_FAKE_TRACE")!, JsonSerializer.Serialize(new
        { operation, project, year, configuration, exit_code = code, args, cwd = Environment.CurrentDirectory }) + "\n");
        if (code != 0) return code;
        var output = args[Array.IndexOf(args, "-o") + 1];
        Directory.CreateDirectory(output);
        if (mode == "mutate_capture") Put(Path.Combine(Environment.CurrentDirectory, "mutated.cs"), "changed");
        if (operation == "build")
        {
            Managed(Path.Combine(output,"Kir.Revit.Connector.dll"),"Kir.Revit.Connector","Kir.Revit.Protocol");
            Managed(Path.Combine(output,"Kir.Revit.Protocol.dll"),"Kir.Revit.Protocol","DeclaredAddonDependency");
            Managed(Path.Combine(output,"DeclaredAddonDependency.dll"),"DeclaredAddonDependency",year=="2023"?"mscorlib":"System.Private.CoreLib");
            if (mode == "forbidden_addin") Put(Path.Combine(output, "WindowsBase.dll"), "SDK_REFERENCE_NOT_ALLOWED");
            return 0;
        }
        var name = Path.GetFileNameWithoutExtension(project);
        var files = new[] { name + ".exe", name + ".dll", "Kir.Revit.Protocol.dll", "coreclr.dll", "hostfxr.dll", "hostpolicy.dll", "System.Private.CoreLib.dll", "DeclaredDependency.dll" };
        foreach (var file in files)
            if (!(mode == "missing_runtime" && file == "DeclaredDependency.dll")) Put(Path.Combine(output, file), "NEW_" + name + "_" + configuration);
        Managed(Path.Combine(output,"System.Private.CoreLib.dll"),"System.Private.CoreLib");
        // WindowsBase in a helper's bundled Core runtime is not the forbidden
        // desktop reference beside the add-in. Preserve it; never strip by name.
        Put(Path.Combine(output, "WindowsBase.dll"), "BUNDLED_CORE_FACADE");
        Put(Path.Combine(output, name + ".runtimeconfig.json"), JsonSerializer.Serialize(new
        { runtimeOptions = new { tfm = "net8.0", includedFrameworks = new[] { new { name = "Microsoft.NETCore.App", version = "8.0.29" } } } }));
        Put(Path.Combine(output, name + ".deps.json"), JsonSerializer.Serialize(new
        {
            runtimeTarget = new { name = ".NETCoreApp,Version=v8.0/win-x64" },
            targets = new Dictionary<string, object>
            {
                [".NETCoreApp,Version=v8.0/win-x64"] = new Dictionary<string, object>
                {
                    [name + "/0.1.0"] = new { runtime = new Dictionary<string, object>
                    { [name + ".dll"] = new { }, ["DeclaredDependency.dll"] = new { }, ["WindowsBase.dll"] = new { } } },
                    ["runtimepack.Microsoft.NETCore.App.Runtime.win-x64/8.0.29"] = new
                    { runtime = new Dictionary<string, object> { ["System.Private.CoreLib.dll"] = new { } },
                      native = new Dictionary<string, object> { ["coreclr.dll"] = new { }, ["hostfxr.dll"] = new { }, ["hostpolicy.dll"] = new { } } }
                }
            }
        }));
        return 0;
    }
}
